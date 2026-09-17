#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
rvwap.py — Rolling VWAP 돌파 판별 (TradingView 지표 이식)
─────────────────────────────────────────────────────────────────────────
일반 VWAP은 세션 시작부터 누적하지만, Rolling VWAP은 '최근 N시간'을 계속
굴러가는 창으로 계산한다. 세션이 없는 크립토에 더 맞는 이유다.

원본 계산:
    rollingVWAP = Σ(src × vol) / Σ(vol)          (시간 창 기준)
    variance    = Σ(vol × src²)/Σ(vol) - VWAP²   (E[x²] - E[x]²)
    stDev       = √variance
    밴드         = VWAP ± stDev × 배수

롤링 기간은 차트 시간봉에 따라 자동 결정(원본 timeStep()):
    ~1분 → 1시간 · ~5분 → 4시간 · ~1시간 → 1일
    ~4시간 → 3일 · ~12시간 → 7일 · 일봉 → 약 1개월

신호: 종가가 RVWAP을 상향/하향 교차 + 그 봉 거래량이 평균 이상.
      단순 교차만 보면 휩쏘가 많아 거래량 확인을 붙였다.
"""
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

MS_MIN = 60 * 1000
MS_HOUR = MS_MIN * 60
MS_DAY = MS_HOUR * 24

MIN_BARS = 10          # 시간 창이 비는 것을 막는 최소 봉 수(원본 minBarsInput)
VOL_MULT = 1.0         # 돌파 봉 거래량 / 평균 거래량 최소 배수
VOL_AVG_LEN = 20
FRESH_BARS = 3         # 최근 N봉 내 교차만 '방금 발생'으로 인정
BAND_MULTS = (1.0, 2.0)


def auto_window_ms(interval: str) -> int:
    """원본 timeStep(): 차트 시간봉 → 롤링 기간(ms)."""
    tf_ms = {
        "1m": MS_MIN, "3m": MS_MIN * 3, "5m": MS_MIN * 5, "15m": MS_MIN * 15,
        "30m": MS_MIN * 30, "1h": MS_HOUR, "2h": MS_HOUR * 2, "4h": MS_HOUR * 4,
        "6h": MS_HOUR * 6, "12h": MS_HOUR * 12, "1d": MS_DAY, "1w": MS_DAY * 7,
    }.get(interval, MS_HOUR * 4)

    if tf_ms <= MS_MIN:
        return MS_HOUR
    if tf_ms <= MS_MIN * 5:
        return MS_HOUR * 4
    if tf_ms <= MS_HOUR:
        return MS_DAY
    if tf_ms <= MS_HOUR * 4:
        return MS_DAY * 3
    if tf_ms <= MS_HOUR * 12:
        return MS_DAY * 7
    if tf_ms <= MS_DAY:
        return int(MS_DAY * 30.4375)
    if tf_ms <= MS_DAY * 7:
        return MS_DAY * 90
    return MS_DAY * 365


def window_label(ms: int) -> str:
    d = ms // MS_DAY
    h = (ms % MS_DAY) // MS_HOUR
    if d >= 30:
        return "1개월"
    if d == 7:
        return "1주"
    parts = []
    if d:
        parts.append(f"{d}일")
    if h:
        parts.append(f"{h}시간")
    return " ".join(parts) or "1시간"


def rolling_vwap(df: pd.DataFrame, interval: str,
                 min_bars: int = MIN_BARS) -> pd.DataFrame:
    """RVWAP과 표준편차를 계산. 시간 창 기준이므로 봉 수가 아닌 기간으로 자른다."""
    win_ms = auto_window_ms(interval)
    # 봉 간격으로 창 길이를 봉 수로 환산(크립토는 봉 간격이 일정해 이 방식이 정확)
    if len(df) < 2:
        return pd.DataFrame()
    bar_ms = int((df.index[-1] - df.index[-2]).total_seconds() * 1000)
    if bar_ms <= 0:
        return pd.DataFrame()
    n = max(int(win_ms / bar_ms), min_bars)

    src = (df["High"] + df["Low"] + df["Close"]) / 3.0      # 원본 기본값 hlc3
    vol = df["Volume"]

    sum_sv = (src * vol).rolling(n, min_periods=min_bars).sum()
    sum_v = vol.rolling(n, min_periods=min_bars).sum()
    sum_ssv = (vol * src.pow(2)).rolling(n, min_periods=min_bars).sum()

    vwap = sum_sv / sum_v.replace(0, np.nan)
    var = (sum_ssv / sum_v.replace(0, np.nan)) - vwap.pow(2)
    var = var.clip(lower=0)                                  # 원본: 음수면 0
    sd = np.sqrt(var)

    out = pd.DataFrame({"vwap": vwap, "sd": sd}, index=df.index)
    out.attrs["window_ms"] = win_ms
    out.attrs["bars"] = n
    return out


@dataclass
class RvwapState:
    signal: str            # up | down | none
    bars_ago: int
    price: float
    vwap: float
    dist: float            # 가격의 VWAP 대비 이격(%)
    sd_pos: float          # VWAP에서 몇 σ 떨어져 있나
    vol_ratio: float       # 돌파 봉 거래량 / 평균
    window: str            # 롤링 기간 표시용
    # 상위 시간봉(일봉) 맥락
    d_vwap: Optional[float] = None
    d_above: Optional[bool] = None
    d_dist: Optional[float] = None


def compute(df: pd.DataFrame, interval: str = "4h",
            df_daily: Optional[pd.DataFrame] = None,
            fresh: int = FRESH_BARS, vol_mult: float = VOL_MULT) -> Optional[RvwapState]:
    """RVWAP 교차 + 거래량 확인. df_daily를 주면 일봉 RVWAP 맥락도 함께."""
    rv = rolling_vwap(df, interval)
    if rv.empty or rv["vwap"].isna().all():
        return None

    c = df["Close"]
    v = df["Volume"]
    vwap = rv["vwap"]
    sd = rv["sd"]

    above = c > vwap
    vol_avg = v.rolling(VOL_AVG_LEN, min_periods=5).mean()

    signal, bars_ago, vol_ratio = "none", -1, 0.0
    for k in range(fresh):
        i = len(df) - 1 - k
        if i < 1 or pd.isna(vwap.iloc[i]) or pd.isna(vwap.iloc[i - 1]):
            continue
        va = float(vol_avg.iloc[i]) if not pd.isna(vol_avg.iloc[i]) else 0.0
        vr = (float(v.iloc[i]) / va) if va > 0 else 0.0
        crossed_up = bool(above.iloc[i]) and not bool(above.iloc[i - 1])
        crossed_dn = (not bool(above.iloc[i])) and bool(above.iloc[i - 1])
        if (crossed_up or crossed_dn) and vr >= vol_mult:
            signal = "up" if crossed_up else "down"
            bars_ago, vol_ratio = k, vr
            break

    if signal == "none":
        return None

    price = float(c.iloc[-1])
    vw = float(vwap.iloc[-1])
    sdv = float(sd.iloc[-1]) if not pd.isna(sd.iloc[-1]) else 0.0
    st = RvwapState(
        signal=signal, bars_ago=bars_ago, price=price, vwap=vw,
        dist=(price / vw - 1) * 100 if vw else 0.0,
        sd_pos=((price - vw) / sdv) if sdv > 0 else 0.0,
        vol_ratio=vol_ratio, window=window_label(rv.attrs.get("window_ms", 0)),
    )

    # 상위 시간봉 맥락 — 일봉 RVWAP(롤링 약 1개월) 대비 위치
    if df_daily is not None and len(df_daily) > 40:
        drv = rolling_vwap(df_daily, "1d")
        if not drv.empty and not pd.isna(drv["vwap"].iloc[-1]):
            dv = float(drv["vwap"].iloc[-1])
            dprice = float(df_daily["Close"].iloc[-1])
            st.d_vwap = dv
            st.d_above = dprice > dv
            st.d_dist = (dprice / dv - 1) * 100 if dv else 0.0
    return st


SIGNAL_LABEL = {
    "up":   ("🟢 상방 돌파", "종가가 RVWAP 위로 — 매수세 우위 전환"),
    "down": ("🔴 하방 이탈", "종가가 RVWAP 아래로 — 매도세 우위 전환"),
}
SIGNAL_CLS = {"up": "rv-up", "down": "rv-down"}
