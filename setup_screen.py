#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
setup_screen.py — 미너비니 추세 템플릿 + 트리거 이벤트 (일봉)
─────────────────────────────────────────────────────────────────────────
2층 구조.

■ 1층: 추세 템플릿 7조건 — "추세가 건강한가"(상태)
   ① 주가가 150일 또는 200일선 위
   ② 150일선이 200일선 위
   ③ 200일선이 우상향
   ④ 고점·저점이 연이어 높아짐
   ⑤ 상승 시 거래량↑, 하락 시 거래량↓ (평균 비교)
   ⑥ 거래량 실린 상승봉 개수 > 하락봉 개수 (개수 비교, ⑤와 보완)
   ⑦ 52주 신저가 대비 25%↑ (+ 신고가에서 너무 멀지 않을 것)

■ 2층: 트리거 이벤트 — "지금 터졌는가"(사건)
   🚀 전고점 돌파 장대양봉 · 🏔️ 신고가 · 💥 횡보 후 장대양봉

7개 전부보다 'N개 이상'으로 보는 편이 실용적(기본 6). 트리거는 별도 표시.
"""
from dataclasses import dataclass, field
from typing import Optional, List, Tuple

import numpy as np
import pandas as pd

# ── 추세 템플릿 파라미터 ──
MA_MID = 150
MA_LONG = 200
MA_SLOPE_LOOKBACK = 20      # 200일선 우상향 판정 구간
PIVOT_LEN = 10              # 고점·저점 스윙 판정 좌우 봉
VOL_SHORT = 20              # 최근 거래량 구간
VOL_PRIOR = 60              # 비교할 직전 구간(겹치지 않음)
UPDOWN_LOOKBACK = 30        # 상승/하락일 거래량 비교 구간
UPDOWN_MIN = 1.0            # 상승일 평균 / 하락일 평균 최소
VOL_BAR_MULT = 1.3          # '거래량 실림' 판정(평균 대비)
LOW_GAIN_MIN = 25.0         # 52주 저가 대비 최소 상승률(%)
HIGH_DIST_MAX = 25.0        # 52주 고가 대비 최대 하락률(%)
WEEK52 = 252
PASS_MIN_DEFAULT = 6        # 7개 중 몇 개 이상이면 통과

# ── 트리거 파라미터 ──
BREAKOUT_LOOKBACK = 60      # 전고점 판단 구간
# ※ 아래 값은 sweep_triggers.py 실측(135종목)에 근거해 확정.
#    몸통 배수는 1.2~2.0 사이에서 결과가 동일했다(병목은 '전고점 돌파' 자체).
#    → 손해 없이 놓칠 가능성만 줄이도록 1.2로 완화.
#    거래량 배수는 1.2→1.5에서 2개→1개로 실제 변별력이 있어 1.5 유지.
#    횡보 폭 10%는 크립토에서 0건(15일간 그 안에 갇히는 일이 없음) → 20%로 완화.
BIG_BODY_MULT = 1.2         # 장대양봉: 몸통이 평균 몸통의 이 배수 이상
BIG_VOL_MULT = 1.5          # 트리거 거래량 배수
TIGHT_LOOKBACK = 15         # 횡보 판정 구간
TIGHT_RANGE_MAX = 0.20      # 횡보: 구간 고저폭이 가격의 이 비율 이내


def _f(x) -> Optional[float]:
    try:
        if hasattr(x, "item"):
            x = x.item()
        v = float(x)
        return None if np.isnan(v) else v
    except Exception:
        return None


def _pivots(s: pd.Series, left: int, right: int, low_side: bool) -> List[int]:
    """스윙 고점/저점 인덱스.
    좌우 이웃과 직접 비교한다. (구간 최대/최소가 유일한지 따지면
    동일값·부동소수점 중복에서 하나도 못 잡는 경우가 생김)"""
    out, v = [], s.values
    n = len(v)
    for i in range(left, n - right):
        cur = v[i]
        if np.isnan(cur):
            continue
        lo_side = v[i - left:i]
        hi_side = v[i + 1:i + right + 1]
        if low_side:
            if cur <= lo_side.min() and cur < hi_side.min():
                out.append(i)
        else:
            if cur >= lo_side.max() and cur > hi_side.max():
                out.append(i)
    return out


@dataclass
class SetupResult:
    ticker: str
    market: str
    price: float
    # 조건별 통과 여부와 표시값
    conds: List[Tuple[str, bool, str]] = field(default_factory=list)
    passed_count: int = 0
    passed: bool = False
    triggers: List[str] = field(default_factory=list)   # 발생한 트리거 라벨
    score: float = 0.0
    # 주요 수치(정렬·표시용)
    ma_dist: float = 0.0
    vol_ratio: float = 0.0
    updown_ratio: float = 0.0
    gain_from_low: float = 0.0
    dist_from_high: float = 0.0


def evaluate(ticker: str, df: pd.DataFrame, market: str = "",
             pass_min: int = PASS_MIN_DEFAULT) -> Optional[SetupResult]:
    """일봉 OHLCV → 추세 템플릿 7조건 + 트리거 판정."""
    if df is None or len(df) < MA_LONG + MA_SLOPE_LOOKBACK + 10:
        return None
    if "Volume" not in df.columns:
        return None

    c, v, h, l, o = df["Close"], df["Volume"], df["High"], df["Low"], df["Open"]
    price = _f(c.iloc[-1])
    if price is None or price <= 0:
        return None

    ma150s = c.rolling(MA_MID).mean()
    ma200s = c.rolling(MA_LONG).mean()
    ma150 = _f(ma150s.iloc[-1])
    ma200 = _f(ma200s.iloc[-1])
    if ma150 is None or ma200 is None or ma200 <= 0:
        return None

    conds: List[Tuple[str, bool, str]] = []

    # ① 주가가 150일 또는 200일선 위
    c1 = price > ma150 or price > ma200
    ma_dist = (price / ma200 - 1) * 100
    conds.append(("주가 > 150/200일선", c1, f"200선 대비 {ma_dist:+.1f}%"))

    # ② 150일선 > 200일선
    c2 = ma150 > ma200
    conds.append(("150일선 > 200일선", c2, f"{(ma150/ma200-1)*100:+.1f}%"))

    # ③ 200일선 우상향
    prev200 = _f(ma200s.iloc[-1 - MA_SLOPE_LOOKBACK])
    slope = ((ma200 / prev200 - 1) * 100) if (prev200 and prev200 > 0) else 0.0
    c3 = slope > 0
    conds.append(("200일선 우상향", c3, f"{MA_SLOPE_LOOKBACK}일 {slope:+.1f}%"))

    # ④ 고점·저점 연속 상승
    win = df.tail(WEEK52) if len(df) >= WEEK52 else df
    hi_idx = _pivots(win["High"], PIVOT_LEN, PIVOT_LEN, low_side=False)
    lo_idx = _pivots(win["Low"], PIVOT_LEN, PIVOT_LEN, low_side=True)
    hh = ll = False
    if len(hi_idx) >= 2:
        hh = float(win["High"].iloc[hi_idx[-1]]) > float(win["High"].iloc[hi_idx[-2]])
    if len(lo_idx) >= 2:
        ll = float(win["Low"].iloc[lo_idx[-1]]) > float(win["Low"].iloc[lo_idx[-2]])
    c4 = hh and ll
    conds.append(("고점·저점 상승", c4,
                  ("고점↑ 저점↑" if c4 else
                   "고점↑" if hh else "저점↑" if ll else "미형성")))

    # ⑤ 상승 시 거래량↑ / 하락 시↓ (평균 비교)
    recent = df.tail(UPDOWN_LOOKBACK)
    chg = recent["Close"].diff()
    uv = _f(recent.loc[chg > 0, "Volume"].mean()) if (chg > 0).any() else None
    dv = _f(recent.loc[chg < 0, "Volume"].mean()) if (chg < 0).any() else None
    if uv and dv and dv > 0:
        updown_ratio = uv / dv
    elif uv and not dv:
        updown_ratio = 2.0          # 조정 자체가 없는 강한 상승
    else:
        updown_ratio = 0.0
    c5 = updown_ratio >= UPDOWN_MIN
    conds.append(("상승↑/하락↓ 거래량", c5, f"{updown_ratio:.2f}배"))

    # ⑥ 거래량 실린 상승봉 개수 > 하락봉 개수
    vavg = v.rolling(50).mean()
    big = v > (vavg * VOL_BAR_MULT)
    up_bar = (c > o) & big
    dn_bar = (c < o) & big
    nu = int(up_bar.tail(WEEK52 // 4).sum())
    nd = int(dn_bar.tail(WEEK52 // 4).sum())
    c6 = nu > nd
    conds.append(("거래량 실린 상승봉 우위", c6, f"상승 {nu} / 하락 {nd}"))

    # ⑦ 52주 저가 +25%↑ & 고가 -25% 이내
    w = df.tail(WEEK52)
    lo52 = _f(w["Low"].min())
    hi52 = _f(w["High"].max())
    gain_low = ((price / lo52 - 1) * 100) if (lo52 and lo52 > 0) else 0.0
    dist_high = ((1 - price / hi52) * 100) if (hi52 and hi52 > 0) else 100.0
    c7 = gain_low >= LOW_GAIN_MIN and dist_high <= HIGH_DIST_MAX
    conds.append(("52주 저가 +25%↑ / 고가 근처", c7,
                  f"저가 +{gain_low:.0f}% · 고가 -{dist_high:.0f}%"))

    passed_count = sum(1 for _, ok, _ in conds if ok)
    passed = passed_count >= pass_min

    # ── 거래량 추세(표시용) ──
    v_short = _f(v.tail(VOL_SHORT).mean())
    prior = v.iloc[-(VOL_SHORT + VOL_PRIOR):-VOL_SHORT]
    v_prior = _f(prior.mean()) if len(prior) else None
    vol_ratio = (v_short / v_prior) if (v_short and v_prior and v_prior > 0) else 0.0

    # ── 2층: 트리거 이벤트 ──
    triggers: List[str] = []
    body = (c - o).abs()
    body_avg = _f(body.tail(50).mean()) or 0.0
    last_body = _f(body.iloc[-1]) or 0.0
    last_up = _f(c.iloc[-1]) > _f(o.iloc[-1])
    last_vol = _f(v.iloc[-1]) or 0.0
    vol_avg50 = _f(vavg.iloc[-1]) or 0.0
    big_candle = last_up and body_avg > 0 and last_body >= body_avg * BIG_BODY_MULT
    big_vol = vol_avg50 > 0 and last_vol >= vol_avg50 * BIG_VOL_MULT

    # 🚀 전고점 돌파 장대양봉
    prior_high = _f(h.iloc[-(BREAKOUT_LOOKBACK + 1):-1].max())
    if big_candle and big_vol and prior_high and price > prior_high:
        triggers.append("🚀 전고점 돌파")

    # 🏔️ 신고가 (52주 기준)
    if hi52 and price >= hi52 * 0.999:
        triggers.append("🏔️ 52주 신고가")

    # 💥 횡보 후 장대양봉
    tw = df.iloc[-(TIGHT_LOOKBACK + 1):-1]
    if len(tw) >= TIGHT_LOOKBACK:
        t_hi, t_lo = _f(tw["High"].max()), _f(tw["Low"].min())
        if t_hi and t_lo and t_lo > 0:
            tight = (t_hi - t_lo) / t_lo <= TIGHT_RANGE_MAX
            if tight and big_candle and big_vol:
                triggers.append("💥 횡보 후 돌파")

    # ── 정렬 점수 ──
    score = passed_count * 12
    score += min(max(vol_ratio - 1, 0) * 60, 30)
    score += min(max(updown_ratio - 1, 0) * 40, 25)
    score += min(gain_low, 120) * 0.2
    score -= dist_high * 0.6
    score += len(triggers) * 15

    return SetupResult(
        ticker=ticker, market=market, price=price, conds=conds,
        passed_count=passed_count, passed=passed, triggers=triggers,
        score=round(score, 1), ma_dist=ma_dist, vol_ratio=vol_ratio,
        updown_ratio=updown_ratio, gain_from_low=gain_low, dist_from_high=dist_high,
    )
