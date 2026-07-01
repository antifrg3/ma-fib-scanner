#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
시장 체제(regime) 판별 — 추세장 vs 횡보장.
규칙(단순·투명, 과최적화 없음):
  · 방향  : 종가 vs 200일선, 200일선 기울기(20일)
  · 강도  : ADX(14)  — ≥25 추세, <20 횡보
분류 → 어떤 전략(돌파/눌림목)에 무게를 둘지 힌트.
영상 프레임워크의 '시장 체제' 층 구현. 데이터는 각 시장 벤치마크 일봉.
"""
import numpy as np
import pandas as pd

import ma_fib_scanner as s

_CACHE: dict = {}

BENCH = {"us": "SPY", "etf": "SPY", "kr": "^KS11", "kretf": "^KS11", "crypto": "BTCUSDT"}
BENCH_LABEL = {"SPY": "S&P500", "^KS11": "코스피", "BTCUSDT": "비트코인"}

# 백테스트(8.9년 BTC · 21.5년 주식)로 검증된 자산별 최적 추세추종 이평 길이.
# BTC=50(빠른 자산), 미국지수=200(느린 자산), 코스피=100(추세추종 이점 약함).
_OPT_MA = {"BTCUSDT": 50, "SPY": 200, "^KS11": 100}

BIAS_TXT = {"breakout": "돌파 우위", "pullback": "눌림목 우위", "caution": "신중 · 비중축소",
            "neutral_up": "중립(약상승)", "neutral": "중립"}
BIAS_CLS = {"breakout": "rg-up", "pullback": "rg-range", "caution": "rg-down",
            "neutral_up": "rg-neu", "neutral": "rg-neu"}


def _adx(df, n=14):
    h, l, c = df["High"], df["Low"], df["Close"]
    up, dn = h.diff(), -l.diff()
    pdm = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), index=df.index)
    mdm = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), index=df.index)
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / n, adjust=False).mean()
    pdi = 100 * pdm.ewm(alpha=1 / n, adjust=False).mean() / atr
    mdi = 100 * mdm.ewm(alpha=1 / n, adjust=False).mean() / atr
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return dx.ewm(alpha=1 / n, adjust=False).mean()


def _fetch(symbol, cfg):
    if symbol == "BTCUSDT":
        return s.fetch_daily_crypto("BTCUSDT")
    return s.fetch_daily(symbol, cfg.daily_period)


def compute_regime(symbol, cfg):
    if symbol in _CACHE:
        return _CACHE[symbol]
    df = _fetch(symbol, cfg)
    if df is None or len(df) < 60:
        _CACHE[symbol] = None
        return None
    c = df["Close"]
    # 자산별 검증된 최적 길이 우선, 데이터 부족 시 축소
    want = _OPT_MA.get(symbol, 200)
    ma_len = want if len(df) >= want + 10 else (100 if len(df) >= 110 else 50)
    ma = c.rolling(ma_len).mean()
    price, mav = float(c.iloc[-1]), float(ma.iloc[-1])
    above = (price / mav - 1) * 100
    back = min(21, len(ma) - 1)
    slope = (mav / float(ma.iloc[-1 - back]) - 1) * 100
    adx = float(_adx(df).iloc[-1])

    trending, ranging = adx >= 25, adx < 20
    up = price > mav and slope > 0
    down = price < mav and slope < 0
    if down and trending:
        label, bias = "하락 추세", "caution"
    elif up and trending:
        label, bias = "상승 추세", "breakout"
    elif ranging:
        label, bias = "횡보", "pullback"
    elif up:
        label, bias = "약한 상승", "neutral_up"
    else:
        label, bias = "혼조", "neutral"

    r = {"symbol": symbol, "label": label, "bias": bias,
         "above": above, "slope": slope, "adx": adx, "ma_len": ma_len}
    _CACHE[symbol] = r
    return r


def regime_for_market(market, cfg=None):
    cfg = cfg or s.Config()
    try:
        return compute_regime(BENCH.get(market, "SPY"), cfg)
    except Exception:
        return None


def badge_html(r, active):
    """active: 'pullback' | 'breakout' — 현재 페이지 기준으로 유리/불리 힌트."""
    if not r:
        return ""
    sym_lbl = BENCH_LABEL.get(r["symbol"], r["symbol"])
    cls, bias = BIAS_CLS[r["bias"]], BIAS_TXT[r["bias"]]
    is_kr = r["symbol"] == "^KS11"
    if r["bias"] == "breakout":
        hint = "✓ 돌파에 유리한 국면" if active == "breakout" else "지금은 🚀 돌파 탭이 더 유리"
    elif r["bias"] == "pullback":
        hint = "✓ 눌림목에 유리한 국면" if active == "pullback" else "지금은 📉 눌림목 탭이 더 유리"
    elif r["bias"] == "caution":
        hint = "⚠ 추세 약세 — 신규 비중 축소"
    else:
        hint = "국면 중립 — 선별적으로"
    # 한국은 백테스트상 추세추종 이점이 약함 → 평균회귀(눌림목) 우선 안내
    if is_kr and active == "breakout":
        hint = "한국은 추세추종 이점 약함 — 📉 눌림목(평균회귀) 우선 권장"
    return (
        f'<div class="regime {cls}">'
        f'<span class="rg-state">{sym_lbl} · {r["label"]}</span>'
        f'<span class="rg-bias">{bias}</span>'
        f'<span class="rg-num">{r["ma_len"]}일선 {r["above"]:+.1f}% · 기울기 {r["slope"]:+.1f}% · ADX {r["adx"]:.0f}</span>'
        f'<span class="rg-hint">{hint}</span>'
        f'</div>')


def sizing_hint(r, active):
    """국면 게이트: (기본 리스크%, 배너HTML). 돌파는 강세장 전제라 약세일수록 강하게 축소.
    반환 risk는 사이징 계산기 기본값, banner는 약세 시 카드 위에 뜨는 경고 띠."""
    default_risk, banner = "1", ""
    if not r:
        return default_risk, banner
    bias = r["bias"]
    if active == "breakout":
        if bias == "breakout":
            default_risk = "1"
        elif bias in ("neutral_up", "neutral"):
            default_risk = "0.75"
            banner = ('<div class="gate gate-warn">⚠️ 국면 중립 — 돌파 신뢰도 보통. '
                      '리스크를 평소의 3/4로 낮춰 시작하세요.</div>')
        elif bias == "pullback":
            default_risk = "0.5"
            banner = ('<div class="gate gate-warn">⚠️ 횡보 국면 — 돌파는 가짜(휩쏘)가 늘어납니다. '
                      '신규 비중을 절반으로 줄이고, 📉 눌림목 탭도 함께 보세요.</div>')
        else:  # caution (하락 추세)
            default_risk = "0.3"
            banner = ('<div class="gate gate-off">🚫 약세 추세 — 돌파 전략에 가장 불리한 국면입니다. '
                      '신규 진입은 최소화하고, 되도록 현금 비중을 유지하세요.</div>')
    else:  # pullback 페이지
        # 백테스트(유니버스 724/439건): 눌림목은 국면필터 얹으면 기대값이 오히려 하락.
        # 골든크로스 자체가 추세전환 신호라, 지수 약세 초입의 좋은 기회를 필터가 잘라냄.
        # → 리스크 자동축소는 하지 않고(역효과), 낙폭 주의만 정보성으로 안내.
        if bias == "caution":
            banner = ('<div class="gate gate-note">지수는 약세지만, 눌림목은 개별 종목이 '
                      '먼저 도는 초입을 잡습니다(백테스트상 국면필터가 오히려 기대값을 낮춤). '
                      '비중은 유지하되 손절만 엄격히 지키세요.</div>')
        elif bias == "breakout":
            banner = ('<div class="gate gate-note">강한 상승 추세입니다 — 되돌림이 얕을 수 있어요. '
                      '🚀 돌파 탭도 함께 확인하세요.</div>')
    return default_risk, banner
