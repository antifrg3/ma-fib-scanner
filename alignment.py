#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
alignment.py — 이평 정배열/역배열 판별 (크립토 1시간봉)
─────────────────────────────────────────────────────────────────────────
정배열 = 20 > 50 > 100 > 200  (단기가 위, 상승 추세)
역배열 = 20 < 50 < 100 < 200  (단기가 아래, 하락 추세)
그 외  = 혼조(정렬 안 됨)

정렬 강도(0~100): 이평 간 간격이 얼마나 벌어졌나(추세 강도).
현재가 위치: 모든 이평 위/아래인지도 참고로.
"""
from dataclasses import dataclass
import numpy as np
import pandas as pd

MAS = [20, 50, 100, 200]   # 정배열 판단 이평(1h 기준)


@dataclass
class AlignState:
    status: str        # bull(정배열) | bear(역배열) | mixed
    strength: float    # 정렬 강도 0~100 (이평 최대-최소 간격 / 가격 %)
    mas: dict          # {길이: 값}
    price: float
    above_all: bool    # 현재가가 모든 이평 위
    below_all: bool    # 현재가가 모든 이평 아래
    rsi: float


def _ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def _rsi(close: pd.Series, n: int = 14) -> pd.Series:
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d).clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    rs = up / dn.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def compute_alignment(df: pd.DataFrame) -> AlignState | None:
    """1h OHLC DataFrame → AlignState. 데이터 부족 시 None."""
    if df is None or len(df) < max(MAS) + 5:
        return None
    c = df["Close"]
    vals = {n: float(_ema(c, n).iloc[-1]) for n in MAS}
    order = [vals[n] for n in MAS]     # [ema20, ema50, ema100, ema200]
    price = float(c.iloc[-1])

    # 정배열: 20>50>100>200 (내림차순), 역배열: 오름차순
    is_bull = all(order[i] > order[i + 1] for i in range(len(order) - 1))
    is_bear = all(order[i] < order[i + 1] for i in range(len(order) - 1))
    status = "bull" if is_bull else "bear" if is_bear else "mixed"

    hi, lo = max(order), min(order)
    strength = (hi - lo) / price * 100 if price else 0.0

    rsi = float(_rsi(c).iloc[-1])
    return AlignState(
        status=status, strength=strength, mas=vals, price=price,
        above_all=price > hi, below_all=price < lo, rsi=rsi,
    )


STATUS_LABEL = {
    "bull":  ("🟢 정배열", "20>50>100>200 · 상승 추세"),
    "bear":  ("🔴 역배열", "20<50<100<200 · 하락 추세"),
    "mixed": ("⚪ 혼조", "정렬 안 됨"),
}
STATUS_CLS = {"bull": "al-bull", "bear": "al-bear", "mixed": "al-mixed"}
