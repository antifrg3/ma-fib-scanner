#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
squeeze.py — 스퀴즈 탐지 로직 (TTM Squeeze + WMA 리본 + RSI 방향)
─────────────────────────────────────────────────────────────────────────
스퀴즈 = 변동성 압축 → 곧 큰 움직임 예고. 두 방식 결합으로 판별:

1) TTM Squeeze (메인, John Carter):
   볼린저밴드(20, 2σ)가 켈트너채널(20, 1.5 ATR) '안으로' 들어가면 압축 ON.
   → BB상단<KC상단 AND BB하단>KC하단  이면 스퀴즈(압축).

2) WMA 리본 수렴 (보조, 사용자 AWMA):
   12개 WMA(3~15 단기, 30~60 장기)의 폭(최대-최소)/가격.
   폭이 좁을수록 압축 강함. 최근 대비 좁아지면 수렴 중.

방향 (RSI 14, 중심선 50):
   스퀴즈 해제(터짐) 시점에 RSI>50 → 롱 / RSI<50 → 숏 / 압축 지속 → 대기.

상태 분류:
   squeeze_on  : 지금 압축 중 (BB⊂KC). 방향 대기(🟡).
   fired_long  : 직전까지 압축→해제 + RSI>50 (🟢 롱 돌파)
   fired_short : 직전까지 압축→해제 + RSI<50 (🔴 숏 돌파)
   none        : 압축도 최근 해제도 아님.
"""
from dataclasses import dataclass
import numpy as np
import pandas as pd

# WMA 리본 (사용자 AWMA 코드 그대로)
RIBBON_SHORT = [3, 5, 8, 10, 12, 15]
RIBBON_LONG = [30, 35, 40, 45, 50, 60]

BB_LEN = 20
BB_MULT = 2.0
KC_LEN = 20
KC_MULT = 1.5
RSI_LEN = 14
FIRE_LOOKBACK = 8   # 최근 N봉 내 압축→해제면 '방금 터짐'으로 간주


def _rma(series: pd.Series, n: int) -> pd.Series:
    return series.ewm(alpha=1 / n, adjust=False).mean()


def _atr(df: pd.DataFrame, n: int) -> pd.Series:
    h, l, c = df["High"], df["Low"], df["Close"]
    pc = c.shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return _rma(tr, n)


def _rsi(close: pd.Series, n: int) -> pd.Series:
    d = close.diff()
    up = d.clip(lower=0)
    dn = (-d).clip(lower=0)
    rs = _rma(up, n) / _rma(dn, n).replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def _wma(series: pd.Series, n: int) -> pd.Series:
    w = np.arange(1, n + 1)
    return series.rolling(n).apply(lambda x: np.dot(x, w) / w.sum(), raw=True)


@dataclass
class SqueezeState:
    status: str          # squeeze_on | fired_long | fired_short | none
    squeeze_on: bool     # 현재 압축 여부
    fired_bars_ago: int  # 해제된 지 몇 봉 전(0=오늘), -1=해당없음
    rsi: float
    ribbon_width_pct: float   # 리본 폭 / 가격 (%) — 작을수록 압축
    ribbon_pctile: float      # 최근 120봉 대비 리본폭 백분위(0=가장좁음)
    bb_in_kc: bool
    price: float


def compute_squeeze(df: pd.DataFrame) -> SqueezeState | None:
    """일봉 OHLC DataFrame → SqueezeState. 데이터 부족 시 None."""
    if df is None or len(df) < max(KC_LEN, max(RIBBON_LONG)) + 10:
        return None
    c = df["Close"]

    # 1) TTM Squeeze
    basis = c.rolling(BB_LEN).mean()
    dev = BB_MULT * c.rolling(BB_LEN).std()
    bb_up, bb_dn = basis + dev, basis - dev
    kc_mid = c.rolling(KC_LEN).mean()
    rng = _atr(df, KC_LEN)
    kc_up, kc_dn = kc_mid + KC_MULT * rng, kc_mid - KC_MULT * rng
    bb_in_kc = (bb_up < kc_up) & (bb_dn > kc_dn)   # 압축 시리즈

    # 2) WMA 리본 폭
    ribbon = pd.DataFrame({n: _wma(c, n) for n in RIBBON_SHORT + RIBBON_LONG})
    width = (ribbon.max(axis=1) - ribbon.min(axis=1))
    width_pct = (width / c) * 100
    # 최근 120봉 대비 현재 폭 백분위(0=가장좁음=최대압축)
    recent = width_pct.tail(120).dropna()
    cur_w = float(width_pct.iloc[-1]) if not np.isnan(width_pct.iloc[-1]) else None
    pctile = float((recent < cur_w).mean() * 100) if cur_w is not None and len(recent) else 50.0

    # 3) RSI
    rsi = _rsi(c, RSI_LEN)
    rsi_now = float(rsi.iloc[-1])

    on_now = bool(bb_in_kc.iloc[-1])
    # 최근 FIRE_LOOKBACK봉 내에 '압축→해제' 전환이 있었나
    fired_ago = -1
    for k in range(1, min(FIRE_LOOKBACK, len(bb_in_kc) - 1) + 1):
        if (not bool(bb_in_kc.iloc[-k])) and bool(bb_in_kc.iloc[-k - 1]):
            fired_ago = k - 1
            break

    if on_now:
        status = "squeeze_on"
    elif fired_ago >= 0:
        status = "fired_long" if rsi_now >= 50 else "fired_short"
    else:
        status = "none"

    return SqueezeState(
        status=status, squeeze_on=on_now, fired_bars_ago=fired_ago,
        rsi=rsi_now, ribbon_width_pct=(cur_w if cur_w is not None else float("nan")),
        ribbon_pctile=pctile, bb_in_kc=on_now, price=float(c.iloc[-1]),
    )


# 상태 → 표시 라벨/색
STATUS_LABEL = {
    "squeeze_on": ("🟡 스퀴즈 압축 중", "대기 (방향 미정)"),
    "fired_long": ("🟢 롱 돌파", "압축 해제 + RSI>50"),
    "fired_short": ("🔴 숏 돌파", "압축 해제 + RSI<50"),
    "none": ("— 해당 없음", ""),
}
STATUS_CLS = {"squeeze_on": "sq-wait", "fired_long": "sq-long",
              "fired_short": "sq-short", "none": "sq-none"}
