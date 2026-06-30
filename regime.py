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
    ma_len = 200 if len(df) >= 210 else (100 if len(df) >= 110 else 50)
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
    if r["bias"] == "breakout":
        hint = "✓ 돌파에 유리한 국면" if active == "breakout" else "지금은 🚀 돌파 탭이 더 유리"
    elif r["bias"] == "pullback":
        hint = "✓ 눌림목에 유리한 국면" if active == "pullback" else "지금은 📉 눌림목 탭이 더 유리"
    elif r["bias"] == "caution":
        hint = "⚠ 추세 약세 — 신규 비중 축소"
    else:
        hint = "국면 중립 — 선별적으로"
    return (
        f'<div class="regime {cls}">'
        f'<span class="rg-state">{sym_lbl} · {r["label"]}</span>'
        f'<span class="rg-bias">{bias}</span>'
        f'<span class="rg-num">200일선 {r["above"]:+.1f}% · 기울기 {r["slope"]:+.1f}% · ADX {r["adx"]:.0f}</span>'
        f'<span class="rg-hint">{hint}</span>'
        f'</div>')
