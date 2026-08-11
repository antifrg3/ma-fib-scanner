#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mtfband.py — 멀티타임프레임 볼린저 역추세 스크리너 로직
─────────────────────────────────────────────────────────────────────────
셋업: 4시간봉 밴드 '끝'에서 역추세 진입. 일봉/4시간/1시간 밴드를 겹쳐 보고,
      가장 극단(일봉 밖)까지 갔다가 되돌아오는 자리를 최상급으로 본다.

트리거(4시간봉):
  · 꼬리로 밴드 이탈 + 종가는 밴드 안 = 거부(소진) → 반전 후보
  · 단, 연속 EXTREME_MAX봉 이상 종가가 밴드 밖이면 '추세'로 보고 제외
    (밴드 타고 흐르는 강추세에서 역추세 진입하는 함정 방지)

등급(⭐):
  · 일봉 밴드 이탈 ⭐⭐⭐ / 4시간 밴드 이탈 ⭐⭐ / 1시간 밴드만 ⭐
  · 1시간 RSI 다이버전스 +⭐ · 4시간 다이버전스 +⭐⭐ (드물어 가중치↑)

1시간 상태는 '정보'로만 제공(필터 아님) — 진입 타점은 사용자가 판단.
"""
from dataclasses import dataclass, field
import numpy as np
import pandas as pd

BB_LEN = 20
BB_MULT = 2.0
RSI_LEN = 14
EXTREME_MAX = 3       # 종가가 밴드 밖으로 연속 이 봉 이상이면 추세로 간주(제외)
PIVOT_LEN = 5         # 다이버전스용 스윙 좌우 봉 수
DIV_LOOKBACK = 150    # 다이버전스 탐색 구간(봉) — 스윙 2개가 들어갈 만큼 넓게
DIV_RECENT_MAX = 30   # 최근 스윙이 현재봉에서 이 봉 이내여야 유효(오래된 신호 배제)


def _rsi(close: pd.Series, n: int = RSI_LEN) -> pd.Series:
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d).clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    rs = up / dn.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def bands(df: pd.DataFrame, length: int = BB_LEN, mult: float = BB_MULT):
    """볼린저 (중심, 상단, 하단) 시리즈."""
    c = df["Close"]
    mid = c.rolling(length).mean()
    dev = mult * c.rolling(length).std()
    return mid, mid + dev, mid - dev


def _pivots(s: pd.Series, left: int, right: int, low_side: bool):
    """스윙 저점(low_side=True)/고점 인덱스 리스트."""
    out = []
    v = s.values
    for i in range(left, len(v) - right):
        w = v[i - left:i + right + 1]
        if low_side and v[i] == w.min() and (w == v[i]).sum() == 1:
            out.append(i)
        elif (not low_side) and v[i] == w.max() and (w == v[i]).sum() == 1:
            out.append(i)
    return out


def find_divergence(df: pd.DataFrame, bullish: bool) -> bool:
    """RSI 다이버전스(피벗 기반). bullish=True면 강세(가격 저점↓ + RSI 저점↑).
       최근 스윙이 DIV_RECENT_MAX봉 이내일 때만 유효(지난 다이버전스 배제)."""
    if df is None or len(df) < PIVOT_LEN * 2 + RSI_LEN + 20:
        return False
    sub = df.tail(DIV_LOOKBACK)
    price = sub["Low"] if bullish else sub["High"]
    rsi = _rsi(sub["Close"])
    idxs = _pivots(price, PIVOT_LEN, PIVOT_LEN, low_side=bullish)
    if len(idxs) < 2:
        return False
    i1, i2 = idxs[-2], idxs[-1]          # 직전 스윙, 최근 스윙
    if (len(sub) - 1 - i2) > DIV_RECENT_MAX:
        return False                      # 최근 스윙이 너무 오래됨
    p1, p2 = float(price.iloc[i1]), float(price.iloc[i2])
    r1, r2 = float(rsi.iloc[i1]), float(rsi.iloc[i2])
    if np.isnan(r1) or np.isnan(r2):
        return False
    if bullish:
        return p2 < p1 and r2 > r1        # 가격 더 낮은 저점, RSI 더 높은 저점
    return p2 > p1 and r2 < r1            # 가격 더 높은 고점, RSI 더 낮은 고점


@dataclass
class MTFState:
    signal: str            # long | short | none
    stars: int             # 총 ⭐ (1~5)
    extremity: str         # daily | h4 | h1 — 어느 밴드까지 이탈했나
    div_1h: bool
    div_4h: bool
    price: float
    rsi_1h: float
    h1_note: str           # 1시간 상태 설명(정보용)
    pct_b_4h: float        # 4시간 밴드 내 위치(0=하단, 1=상단)
    detail: list = field(default_factory=list)


def _pct_b(price: float, up: float, dn: float) -> float:
    rng = up - dn
    return (price - dn) / rng if rng > 0 else 0.5


def compute_mtf(df1d: pd.DataFrame, df4h: pd.DataFrame, df1h: pd.DataFrame) -> MTFState | None:
    """일봉/4시간/1시간 → 역추세 셋업 판정."""
    for d, need in ((df1d, BB_LEN + 5), (df4h, BB_LEN + EXTREME_MAX + 5),
                    (df1h, PIVOT_LEN * 2 + RSI_LEN + 30)):
        if d is None or len(d) < need:
            return None

    m4, u4, l4 = bands(df4h)
    c4 = df4h["Close"]
    last = -1
    close4 = float(c4.iloc[last])
    hi4, lo4 = float(df4h["High"].iloc[last]), float(df4h["Low"].iloc[last])
    up4, dn4 = float(u4.iloc[last]), float(l4.iloc[last])
    if np.isnan(up4) or np.isnan(dn4):
        return None

    # ── 트리거: 꼬리 이탈 + 종가 거부 ──
    wick_below = lo4 < dn4 and close4 >= dn4     # 하단 찌르고 복귀 → 롱 후보
    wick_above = hi4 > up4 and close4 <= up4     # 상단 찌르고 복귀 → 숏 후보

    # ── 추세 함정 필터: 종가가 연속으로 밴드 밖이면 제외 ──
    closes_below = (c4 < l4).tail(EXTREME_MAX).sum()
    closes_above = (c4 > u4).tail(EXTREME_MAX).sum()
    if wick_below and closes_below >= EXTREME_MAX:
        wick_below = False
    if wick_above and closes_above >= EXTREME_MAX:
        wick_above = False

    if not wick_below and not wick_above:
        return None
    bullish = wick_below
    signal = "long" if bullish else "short"

    # ── 등급: 어느 밴드까지 이탈했나 (해당 봉의 극단값 기준) ──
    _, u1d, l1d = bands(df1d)
    _, u1h, l1h = bands(df1h)
    up1d, dn1d = float(u1d.iloc[-1]), float(l1d.iloc[-1])
    up1h, dn1h = float(u1h.iloc[-1]), float(l1h.iloc[-1])
    extreme_px = lo4 if bullish else hi4

    if bullish:
        if extreme_px < dn1d:
            extremity, base = "daily", 3
        elif extreme_px < dn4:
            extremity, base = "h4", 2
        else:
            extremity, base = "h1", 1
    else:
        if extreme_px > up1d:
            extremity, base = "daily", 3
        elif extreme_px > up4:
            extremity, base = "h4", 2
        else:
            extremity, base = "h1", 1

    # ── 다이버전스 ──
    div1h = find_divergence(df1h, bullish)
    div4h = find_divergence(df4h, bullish)
    stars = min(5, base + (1 if div1h else 0) + (2 if div4h else 0))

    # ── 1시간 상태(정보용) ──
    r1h = float(_rsi(df1h["Close"]).iloc[-1])
    c1h = float(df1h["Close"].iloc[-1])
    m1h = float(bands(df1h)[0].iloc[-1])
    if bullish:
        h1_note = ("반등 확인 (중심선 위)" if c1h > m1h
                   else "반등 시작 (RSI 50↑)" if r1h >= 50 else "아직 반등 미확인")
    else:
        h1_note = ("하락 확인 (중심선 아래)" if c1h < m1h
                   else "하락 시작 (RSI 50↓)" if r1h < 50 else "아직 하락 미확인")

    detail = []
    detail.append(("일봉 밴드 이탈" if extremity == "daily"
                   else "4시간 밴드 이탈" if extremity == "h4" else "1시간 밴드 이탈"))
    if div1h:
        detail.append("1H 다이버전스")
    if div4h:
        detail.append("4H 다이버전스")

    return MTFState(signal=signal, stars=stars, extremity=extremity,
                    div_1h=div1h, div_4h=div4h, price=close4, rsi_1h=r1h,
                    h1_note=h1_note, pct_b_4h=_pct_b(close4, up4, dn4), detail=detail)


SIGNAL_LABEL = {
    "long":  ("🟢 롱 후보", "밴드 하단 이탈 후 거부 — 역추세 매수"),
    "short": ("🔴 숏 후보", "밴드 상단 이탈 후 거부 — 역추세 매도"),
}
SIGNAL_CLS = {"long": "mtf-long", "short": "mtf-short"}
EXTREMITY_LABEL = {
    "daily": "📊 일봉 밴드 이탈 (최대 극단)",
    "h4":    "📊 4시간 밴드 이탈",
    "h1":    "📊 1시간 밴드 이탈",
}
