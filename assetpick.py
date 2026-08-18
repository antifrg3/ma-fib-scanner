#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
assetpick.py — 거래 대상 자산 선정 스코어링 (바이낸스 거래 가능 자산만)
─────────────────────────────────────────────────────────────────────────
목적: "망하지 않을 만큼 안정적인데, 트레이딩할 만큼 움직이는" 자산 찾기.
      신호 타이밍이 아니라 '무엇을 볼지' 정하는 유니버스 선정 도구.

3축 평가:
  ① 유동성  — 24h 거래대금. 슬리피지 없이 들락날락 가능한가.
  ② 변동성  — ATR%(일 평균 진폭/가격). 너무 잔잔하면 수수료 못 이기고,
              너무 크면 손절이 자꾸 털림. 스윗스팟 구간을 높게 평가.
  ③ 추세효율 — |순변화| / 총이동거리. 톱질만 하는지, 방향을 갖고 가는지.
              같은 변동성이라도 이게 높아야 트레이딩이 됨.

크립토와 bStocks(토큰화 주식) 모두 바이낸스 24시간 거래라 조건이 동일 →
같은 잣대로 공정 비교 가능.
"""
from dataclasses import dataclass
from typing import Optional
import numpy as np
import pandas as pd

ATR_LEN = 14
EFF_LEN = 30          # 추세효율 측정 구간(일)
VOL_SWEET = (3.0, 10.0)   # ATR% 스윗스팟 (이 안이면 만점)
MIN_LIQ_USD = 5_000_000   # 최소 일 거래대금(이하면 후보 제외)
MIN_BARS = 60             # 최소 데이터 일수(신규 상장 배제)


def atr_pct(df: pd.DataFrame, n: int = ATR_LEN) -> Optional[float]:
    """ATR을 가격 대비 %로. 하루에 평균 몇 % 움직이나."""
    if df is None or len(df) < n + 5:
        return None
    h, l, c = df["High"], df["Low"], df["Close"]
    pc = c.shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / n, adjust=False).mean().iloc[-1]
    price = float(c.iloc[-1])
    return float(atr / price * 100) if price > 0 else None


def trend_efficiency(df: pd.DataFrame, n: int = EFF_LEN) -> Optional[float]:
    """추세효율(0~1). |기간 순변화| / 일별 변화 총합.
       1에 가까울수록 한 방향으로 곧게, 0에 가까울수록 톱질."""
    if df is None or len(df) < n + 2:
        return None
    c = df["Close"].tail(n + 1)
    net = abs(float(c.iloc[-1]) - float(c.iloc[0]))
    path = float(c.diff().abs().sum())
    return float(net / path) if path > 0 else None


def _score_liq(qv: float) -> float:
    """거래대금 점수 0~100. 로그 스케일(1M=0, 10M=40, 100M=70, 1B=100)."""
    if qv <= 0:
        return 0.0
    x = np.log10(max(qv, 1e5))
    return float(np.clip((x - 6.0) / 3.0 * 100, 0, 100))   # 1M~1B → 0~100


def _score_vol(a: float) -> float:
    """변동성 점수 0~100. 스윗스팟 구간 만점, 벗어날수록 감점."""
    lo, hi = VOL_SWEET
    if a is None:
        return 0.0
    if lo <= a <= hi:
        return 100.0
    if a < lo:
        return float(np.clip(a / lo * 100, 0, 100))          # 너무 잔잔
    return float(np.clip(100 - (a - hi) * 6, 0, 100))        # 너무 과격


def _score_eff(e: float) -> float:
    """추세효율 점수 0~100.
       실제 시장에서 30일 효율은 0.1~0.5가 대부분(0.6+는 드문 강추세).
       0.20 이하는 톱질로 보고 강하게 감점, 0.45 이상이면 만점."""
    if e is None:
        return 0.0
    return float(np.clip((e - 0.20) / 0.25 * 100, 0, 100))


@dataclass
class AssetScore:
    symbol: str
    kind: str          # crypto | bstock
    quote_vol: float   # 24h 거래대금(USDT)
    atr_pct: float
    efficiency: float
    ret_30d: float
    score_liq: float
    score_vol: float
    score_eff: float
    total: float       # 종합 0~100
    grade: str         # 최적 | 양호 | 보통 | 부적합


def evaluate(symbol: str, df: pd.DataFrame, quote_vol: float, kind: str) -> Optional[AssetScore]:
    """일봉 OHLC + 24h 거래대금 → 자산 평가."""
    if df is None or len(df) < MIN_BARS:
        return None
    a = atr_pct(df)
    e = trend_efficiency(df)
    if a is None or e is None:
        return None

    c = df["Close"]
    r30 = ((float(c.iloc[-1]) / float(c.iloc[-31]) - 1) * 100
           if len(c) > 31 else 0.0)

    sl, sv, se = _score_liq(quote_vol), _score_vol(a), _score_eff(e)
    # 유동성은 문턱(있으면 됨), 변동성·효율이 실제 거래 매력도 → 가중치 차등
    total = sl * 0.25 + sv * 0.40 + se * 0.35

    if quote_vol < MIN_LIQ_USD:
        # 유동성 미달은 아무리 좋아도 거래 불가 → 총점도 깎아 순위에서 내림
        total = min(total, 40.0)
        grade = "부적합"
    elif total >= 75:
        grade = "최적"
    elif total >= 60:
        grade = "양호"
    elif total >= 45:
        grade = "보통"
    else:
        grade = "부적합"

    return AssetScore(symbol=symbol, kind=kind, quote_vol=quote_vol,
                      atr_pct=a, efficiency=e, ret_30d=r30,
                      score_liq=sl, score_vol=sv, score_eff=se,
                      total=round(total, 1), grade=grade)


GRADE_CLS = {"최적": "ap-best", "양호": "ap-good", "보통": "ap-ok", "부적합": "ap-bad"}
KIND_LABEL = {"crypto": "🪙 크립토", "bstock": "📈 주식토큰"}
