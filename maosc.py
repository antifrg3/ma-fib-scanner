#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
maosc.py — MA Oscillator Map 신호 판별 (ChartPrime 지표 이식)
─────────────────────────────────────────────────────────────────────────
원본 Pine 로직:
    diff   = close - MA(50)
    maxVal = highest(|diff|, 50)          # 최근 50봉 중 최대 이격
    osc    = diff / maxVal * 100          # -100 ~ +100 으로 정규화

신호(극단 이격을 찍고 되돌아오는 첫 봉):
    Upper = osc[1] == 100  and osc < 100   → 위쪽 극단 이탈 후 꺾임(과열/숏 후보)
    Lower = osc[1] == -100 and osc > -100  → 아래쪽 극단 이탈 후 꺾임(과매도/롱 후보)

osc가 ±100이라는 건 '지금 이격이 최근 50봉 중 최대'라는 뜻이다.
그 상태가 풀리는 순간 = 극단에서 되돌아서기 시작하는 지점.
평균회귀 성격의 신호이며, 추세가 강할 땐 되돌림이 얕게 끝날 수 있다.
"""
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

MA_LEN = 50
MA_TYPE = "SMA"      # 원본 기본값
NORM_LEN = 50        # |diff| 최대값 탐색 구간
FRESH_BARS = 3       # 최근 N봉 내 신호를 '방금 발생'으로 인정


def _ma(s: pd.Series, n: int, kind: str = MA_TYPE) -> pd.Series:
    if kind == "EMA":
        return s.ewm(span=n, adjust=False).mean()
    if kind in ("SMMA (RMA)", "RMA"):
        return s.ewm(alpha=1 / n, adjust=False).mean()
    if kind == "WMA":
        w = np.arange(1, n + 1)
        return s.rolling(n).apply(lambda x: np.dot(x, w) / w.sum(), raw=True)
    return s.rolling(n).mean()          # SMA


def oscillator(df: pd.DataFrame, ma_len: int = MA_LEN,
               norm_len: int = NORM_LEN, ma_type: str = MA_TYPE) -> pd.Series:
    """원본과 동일한 osc 시리즈."""
    c = df["Close"]
    ma = _ma(c, ma_len, ma_type)
    diff = c - ma
    max_val = diff.abs().rolling(norm_len).max()
    return (diff / max_val.replace(0, np.nan)) * 100


@dataclass
class MaOscState:
    signal: str          # upper | lower | none
    bars_ago: int        # 신호가 몇 봉 전(0=현재봉)
    osc: float           # 현재 osc 값
    osc_prev: float
    price: float
    ma: float
    ma_dist: float       # 가격의 MA 대비 이격(%)
    level: Optional[float]   # 신호 봉의 고가(upper) / 저가(lower)


def compute(df: pd.DataFrame, ma_len: int = MA_LEN, norm_len: int = NORM_LEN,
            ma_type: str = MA_TYPE, fresh: int = FRESH_BARS) -> Optional[MaOscState]:
    """최근 fresh봉 내에 Upper/Lower 신호가 있었는지 판정."""
    need = max(ma_len, norm_len) + fresh + 5
    if df is None or len(df) < need:
        return None

    osc = oscillator(df, ma_len, norm_len, ma_type)
    if osc.isna().all():
        return None

    c = df["Close"]
    ma = _ma(c, ma_len, ma_type)
    price = float(c.iloc[-1])
    ma_now = float(ma.iloc[-1])
    if np.isnan(ma_now) or ma_now == 0:
        return None

    o = osc.values
    n = len(o)
    signal, bars_ago, level = "none", -1, None

    # 최근 fresh봉을 훑어 신호 탐색 (가장 최근 것 우선)
    for k in range(fresh):
        i = n - 1 - k
        if i < 1 or np.isnan(o[i]) or np.isnan(o[i - 1]):
            continue
        # 부동소수점 오차 대비: 100에 사실상 도달했는지로 판정
        prev_top = o[i - 1] >= 99.999
        prev_bot = o[i - 1] <= -99.999
        if prev_top and o[i] < 99.999:
            signal, bars_ago = "upper", k
            level = float(df["High"].iloc[i - 1])
            break
        if prev_bot and o[i] > -99.999:
            signal, bars_ago = "lower", k
            level = float(df["Low"].iloc[i - 1])
            break

    return MaOscState(
        signal=signal, bars_ago=bars_ago,
        osc=float(o[-1]) if not np.isnan(o[-1]) else 0.0,
        osc_prev=float(o[-2]) if n > 1 and not np.isnan(o[-2]) else 0.0,
        price=price, ma=ma_now, ma_dist=(price / ma_now - 1) * 100,
        level=level,
    )


SIGNAL_LABEL = {
    "upper": ("🔴 상단 신호", "위쪽 극단 이격 후 꺾임 — 과열/되돌림 후보"),
    "lower": ("🟢 하단 신호", "아래쪽 극단 이격 후 꺾임 — 과매도/반등 후보"),
    "none":  ("— 신호 없음", ""),
}
SIGNAL_CLS = {"upper": "mo-upper", "lower": "mo-lower", "none": "mo-none"}
