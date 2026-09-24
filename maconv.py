#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
maconv.py — 이평 수렴(20/50/200) 판별
─────────────────────────────────────────────────────────────────────────
"세 이평선이 만난다" = 세 선이 좁은 폭 안에 모인 상태(수렴).
방향이 정해지기 직전의 압축 구간으로 본다.

    spread% = (max(MA20,MA50,MA200) - min(...)) / 종가 × 100

기준을 두 가지로 함께 본다. 실측(40종목·39,240봉) 결과 종목별 '하위10% 지점'이
0.11%~1.85%로 17배까지 갈려, 한 기준만으로는 공정하지 않기 때문이다.

  · 절대 기준 — spread ≤ ABS_MAX(0.5%). 실측상 전체의 약 10.5%가 해당.
                금·은·주식토큰처럼 원래 변동성이 낮은 자산이 주로 걸린다.
  · 상대 기준 — 그 종목 최근 REL_LOOKBACK봉 중 하위 REL_PCT% 이내.
                변동성이 큰 알트도 '자기 기준으로 드물게 좁은' 상태를 잡는다.

등급:
  both  🎯 둘 다 충족 — 절대적으로도 좁고 그 종목에게도 드묾(가장 강함)
  rel   📊 상대만     — 알트가 모처럼 조여진 상태
  abs   📏 절대만     — 원래 좁은 자산. 신호 가치는 낮음

태그(부가 정보): 정렬 방향 · 돌파 · 거래량 마름 · 수렴 심화
"""
from dataclasses import dataclass, field
from typing import Optional, List

import numpy as np
import pandas as pd

MAS = (20, 50, 200)
ABS_MAX = 0.5           # 절대 기준(%) — 실측 분포상 하위 약 10%
REL_LOOKBACK = 500      # 상대 기준 비교 구간(봉)
REL_PCT = 10.0          # 그 구간 중 하위 N% 이내면 상대 수렴
BREAK_SD = 1.0          # 돌파 판정: 종가가 세 선 범위를 이 배수만큼 벗어남
VOL_DRY_MAX = 0.85      # 거래량 마름: 최근 10봉 평균 / 50봉 평균
TIGHTEN_BARS = 10       # 수렴 심화 판정 구간


@dataclass
class ConvState:
    grade: str                 # both | rel | abs
    spread: float              # 현재 spread(%)
    rel_pct: float             # 자기 기록 중 하위 몇 %인가
    price: float
    ma: dict                   # {기간: 값}
    direction: str             # up | down | mixed
    tags: List[str] = field(default_factory=list)
    vol_ratio: float = 0.0
    tighten: float = 0.0       # 최근 구간 spread 변화(-면 좁아지는 중)


def spread_series(df: pd.DataFrame) -> pd.Series:
    c = df["Close"]
    m = pd.DataFrame({n: c.rolling(n).mean() for n in MAS})
    return (m.max(axis=1) - m.min(axis=1)) / c * 100


def compute(df: pd.DataFrame) -> Optional[ConvState]:
    """일/시간봉 OHLCV → 수렴 상태. 수렴이 아니면 None."""
    if df is None or len(df) < max(MAS) + 30:
        return None
    c = df["Close"]
    sp = spread_series(df).dropna()
    if len(sp) < 30:
        return None

    cur = float(sp.iloc[-1])
    if np.isnan(cur):
        return None

    # 상대 위치 — 그 종목 자신의 과거 대비
    hist = sp.tail(REL_LOOKBACK)
    rel = float((hist <= cur).mean() * 100)

    is_abs = cur <= ABS_MAX
    is_rel = rel <= REL_PCT
    # 기준 미달도 'near'로 반환한다. 시장이 수렴 구간이 아니면 통과 종목이
    # 0개가 되어 화면이 비는데, 그때도 '가장 조여진 축'은 볼 수 있어야 한다.
    if is_abs and is_rel:
        grade = "both"
    elif is_abs:
        grade = "abs"
    elif is_rel:
        grade = "rel"
    else:
        grade = "near"

    price = float(c.iloc[-1])
    ma_vals = {n: float(c.rolling(n).mean().iloc[-1]) for n in MAS}
    hi, lo = max(ma_vals.values()), min(ma_vals.values())

    # 정렬 방향
    a, b, d = ma_vals[MAS[0]], ma_vals[MAS[1]], ma_vals[MAS[2]]
    if a > b > d:
        direction = "up"
    elif a < b < d:
        direction = "down"
    else:
        direction = "mixed"

    tags: List[str] = []
    if direction == "up":
        tags.append("🟢 상방 정렬")
    elif direction == "down":
        tags.append("🔴 하방 정렬")
    else:
        tags.append("⚪ 뒤섞임")

    # 돌파 — 종가가 이평 묶음 밖으로 벗어나기 시작
    band = hi - lo
    if band > 0:
        if price > hi + band * BREAK_SD:
            tags.append("💥 상방 돌파")
        elif price < lo - band * BREAK_SD:
            tags.append("💥 하방 돌파")

    # 거래량 마름 — 수렴 중 거래가 줄면 압축이 더 유의미
    vol_ratio = 0.0
    if "Volume" in df.columns:
        v = df["Volume"]
        v10 = float(v.tail(10).mean())
        v50 = float(v.tail(50).mean())
        if v50 > 0:
            vol_ratio = v10 / v50
            if vol_ratio <= VOL_DRY_MAX:
                tags.append("🔇 거래량 마름")

    # 수렴 심화 — 최근 구간에서 spread가 줄어드는 중
    tighten = 0.0
    if len(sp) > TIGHTEN_BARS:
        past = float(sp.iloc[-1 - TIGHTEN_BARS])
        if past > 0:
            tighten = (cur / past - 1) * 100
            if tighten <= -20:
                tags.append("📉 수렴 심화")

    return ConvState(grade=grade, spread=cur, rel_pct=rel, price=price,
                     ma=ma_vals, direction=direction, tags=tags,
                     vol_ratio=vol_ratio, tighten=tighten)


GRADE_LABEL = {
    "both": ("🎯 둘 다 충족", "절대적으로도 좁고 이 종목에겐 드문 수렴"),
    "rel":  ("📊 상대 기준", "자기 기록 대비 드물게 좁아진 상태"),
    "abs":  ("📏 절대 기준", "폭은 좁으나 이 종목에겐 평범 — 원래 변동성이 낮은 자산"),
    "near": ("👀 근접 관찰", "기준 미달 — 다만 지금 가장 조여진 축에 속함"),
}
GRADE_CLS = {"both": "cv-both", "rel": "cv-rel", "abs": "cv-abs", "near": "cv-near"}
