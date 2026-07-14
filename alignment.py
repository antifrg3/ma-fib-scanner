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
    stage: str = ""         # early(🌱 초기) | building(🌿 진행) | full(🌳 완성) | ""
    cross_days_ago: int = -1  # 20×50 골든크로스가 몇 봉 전(-1=없음)


EARLY_LOOKBACK = 15   # 최근 N봉 내 20×50 크로스면 '초기'로 인정


def _ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def _rsi(close: pd.Series, n: int = 14) -> pd.Series:
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d).clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    rs = up / dn.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def compute_alignment(df: pd.DataFrame) -> AlignState | None:
    """일봉 OHLC DataFrame → AlignState. 데이터 부족 시 None.
       stage(상승 정렬 진행 단계):
         early(🌱)    = 20>50 + 최근 EARLY_LOOKBACK봉 내 20×50 골든크로스 (시작점)
         building(🌿) = 20>50>100 성립, 200 정렬은 아직
         full(🌳)     = 20>50>100>200 완성"""
    if df is None or len(df) < max(MAS) + 5:
        return None
    c = df["Close"]
    emas = {n: _ema(c, n) for n in MAS}
    vals = {n: float(emas[n].iloc[-1]) for n in MAS}
    order = [vals[n] for n in MAS]     # [ema20, ema50, ema100, ema200]
    price = float(c.iloc[-1])

    # 정배열: 20>50>100>200 (내림차순), 역배열: 오름차순
    is_bull = all(order[i] > order[i + 1] for i in range(len(order) - 1))
    is_bear = all(order[i] < order[i + 1] for i in range(len(order) - 1))
    status = "bull" if is_bull else "bear" if is_bear else "mixed"

    hi, lo = max(order), min(order)
    strength = (hi - lo) / price * 100 if price else 0.0
    rsi = float(_rsi(c).iloc[-1])

    # ── 단계 판정 (상승 방향) ──
    above = emas[20] > emas[50]
    cross_ago = -1
    arr = (above & ~above.shift(1).fillna(False)).values
    idxs = np.where(arr)[0]
    if len(idxs) and bool(above.iloc[-1]):
        cross_ago = int(len(df) - 1 - idxs[-1])

    stage = ""
    if is_bull:
        stage = "full"
    elif vals[20] > vals[50] > vals[100]:
        stage = "building"
    elif vals[20] > vals[50] and 0 <= cross_ago <= EARLY_LOOKBACK:
        stage = "early"

    return AlignState(
        status=status, strength=strength, mas=vals, price=price,
        above_all=price > hi, below_all=price < lo, rsi=rsi,
        stage=stage, cross_days_ago=cross_ago,
    )


STATUS_LABEL = {
    "bull":  ("🟢 정배열", "20>50>100>200 · 상승 추세"),
    "bear":  ("🔴 역배열", "20<50<100<200 · 하락 추세"),
    "mixed": ("⚪ 혼조", "정렬 안 됨"),
}
STATUS_CLS = {"bull": "al-bull", "bear": "al-bear", "mixed": "al-mixed"}

STAGE_LABEL = {
    "early":    ("🌱 초기 전환", "20×50 골든크로스 직후 — 시작점 후보"),
    "building": ("🌿 진행 중", "20>50>100 — 정배열 형성 중"),
    "full":     ("🌳 정배열 완성", "20>50>100>200"),
}
STAGE_CLS = {"early": "st-early", "building": "st-building", "full": "st-full"}
