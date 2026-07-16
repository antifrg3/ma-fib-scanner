#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ssband.py — SS Band + 슈퍼트렌드 롱/숏 판별 (사용자 Pine v4 지표 이식)
─────────────────────────────────────────────────────────────────────────
원본 Pine 로직:
  shadow = (VPT - SMA(VPT,14)) / stdev(VPT-SMA,28) * stdev(high-low,28)
  out    = shadow>0 ? high+shadow : low+shadow
  c = EMA(out, len)   (밴드 상단색 기준)
  o = EMA(open, len)
  밴드색: c>o → 녹색(lime) / 아니면 주황
  슈퍼트렌드: vpt=EMA(out,len) 기준 ±ATR(10)×1 밴드, trend=1(파랑)/-1(빨강)
  len(1시간봉, tf=100): 100/60*7 = 11 (Pine 정수 나눗셈 방식)

롱 = 5분봉 종가>SMA200 + 1시간봉 종가>SMA50 + 밴드 녹색 + 슈퍼트렌드 파랑
숏 = 전부 반대
"""
from dataclasses import dataclass
import numpy as np
import pandas as pd

ST_MULT = 1.0      # 슈퍼트렌드 계수
ST_PERIOD = 10     # ATR 기간
WINDOW_LEN = 28
V_LEN = 14
TF_INPUT = 100     # Pine의 tf 입력 기본값

SMA_5M = 200       # 5분봉 SMA 기간
SMA_1H = 50        # 1시간봉 SMA 기간


def _pine_len_1h() -> int:
    # timeframe.isintraday & multiplier(60) >= 1 → tf/multiplier*7
    return int(TF_INPUT / 60 * 7)   # 11 (Pine도 정수 연산 시 11.67→시리즈길이로 11 사용)


def _ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def _atr(df: pd.DataFrame, n: int) -> pd.Series:
    h, l, c = df["High"], df["Low"], df["Close"]
    pc = c.shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()   # Pine atr = RMA


def compute_ssband(df1h: pd.DataFrame) -> dict | None:
    """1시간봉 OHLCV → SS Band 색 + 슈퍼트렌드 방향. Pine 로직 그대로."""
    need = max(WINDOW_LEN, V_LEN, ST_PERIOD) + _pine_len_1h() + 10
    if df1h is None or len(df1h) < need:
        return None
    h, l, o, c, v = df1h["High"], df1h["Low"], df1h["Open"], df1h["Close"], df1h["Volume"]

    hilow = (h - l) * 100
    openclose = (c - o) * 100
    vol = v / hilow.replace(0, np.nan)
    spreadvol = (openclose * vol).fillna(0)
    vpt_series = spreadvol + spreadvol.cumsum()   # Pine: spreadvol + cum(spreadvol)

    smooth = vpt_series.rolling(V_LEN).mean()
    price_spread = (h - l).rolling(WINDOW_LEN).std()
    v_spread = (vpt_series - smooth).rolling(WINDOW_LEN).std()
    shadow = (vpt_series - smooth) / v_spread.replace(0, np.nan) * price_spread
    # 방어: v_spread→0 으로 shadow 폭발 시 가격 스케일로 클리핑(실데이터에선 거의 발동 안 함)
    cap = (h - l).rolling(WINDOW_LEN).mean() * 10
    shadow = shadow.clip(lower=-cap, upper=cap)
    out = pd.Series(np.where(shadow > 0, h + shadow, l + shadow), index=df1h.index)

    ln = _pine_len_1h()
    band_c = _ema(out, ln)         # 거래량가중가격 EMA (빨간 플롯)
    band_o = _ema(o, ln)           # 시가 EMA (녹색 플롯)
    band_green = bool(band_c.iloc[-1] > band_o.iloc[-1])   # 녹색 = c > o

    # 슈퍼트렌드 (vpt = EMA(out, len) 기준)
    vpt = _ema(out, ln)
    atr = _atr(df1h, ST_PERIOD)
    up_lev = vpt - ST_MULT * atr
    dn_lev = vpt + ST_MULT * atr

    n = len(df1h)
    up_trend = np.zeros(n)
    down_trend = np.zeros(n)
    trend = np.zeros(n, dtype=int)
    cl = c.values
    upv, dnv = up_lev.values, dn_lev.values
    for i in range(n):
        if i == 0:
            up_trend[i] = upv[i] if not np.isnan(upv[i]) else 0.0
            down_trend[i] = dnv[i] if not np.isnan(dnv[i]) else 0.0
            trend[i] = 1
            continue
        up_trend[i] = max(upv[i], up_trend[i - 1]) if cl[i - 1] > up_trend[i - 1] else upv[i]
        down_trend[i] = min(dnv[i], down_trend[i - 1]) if cl[i - 1] < down_trend[i - 1] else dnv[i]
        if cl[i] > down_trend[i - 1]:
            trend[i] = 1
        elif cl[i] < up_trend[i - 1]:
            trend[i] = -1
        else:
            trend[i] = trend[i - 1] if trend[i - 1] != 0 else 1

    st_blue = bool(trend[-1] == 1)   # 파란색 = trend 1
    return {"band_green": band_green, "st_blue": st_blue,
            "band_c": float(band_c.iloc[-1]), "band_o": float(band_o.iloc[-1]),
            "st_line": float(up_trend[-1] if trend[-1] == 1 else down_trend[-1])}


@dataclass
class SSState:
    signal: str          # long | short | none
    above_5m200: bool    # 5분봉 종가 > SMA200
    above_1h50: bool     # 1시간봉 종가 > SMA50
    band_green: bool     # SS밴드 녹색(c>o)
    st_blue: bool        # 슈퍼트렌드 파랑(trend=1)
    price: float
    long_cnt: int        # 롱 조건 충족 수(0~4)
    short_cnt: int


def compute_signal(df5m: pd.DataFrame, df1h: pd.DataFrame) -> SSState | None:
    """5분봉 + 1시간봉 → 4조건 롱/숏 판별."""
    if df5m is None or len(df5m) < SMA_5M + 5:
        return None
    if df1h is None or len(df1h) < SMA_1H + 5:
        return None
    ss = compute_ssband(df1h)
    if ss is None:
        return None

    c5 = float(df5m["Close"].iloc[-1])
    sma5 = float(df5m["Close"].rolling(SMA_5M).mean().iloc[-1])
    c1 = float(df1h["Close"].iloc[-1])
    sma1 = float(df1h["Close"].rolling(SMA_1H).mean().iloc[-1])

    a5 = c5 > sma5
    a1 = c1 > sma1
    bg = ss["band_green"]
    sb = ss["st_blue"]

    long_cnt = int(a5) + int(a1) + int(bg) + int(sb)
    short_cnt = int(not a5) + int(not a1) + int(not bg) + int(not sb)

    signal = "long" if long_cnt == 4 else "short" if short_cnt == 4 else "none"
    return SSState(signal=signal, above_5m200=a5, above_1h50=a1,
                   band_green=bg, st_blue=sb, price=c1,
                   long_cnt=long_cnt, short_cnt=short_cnt)


SIGNAL_LABEL = {
    "long":  ("🟢 롱", "5m>200 · 1h>50 · 밴드녹색 · ST파랑"),
    "short": ("🔴 숏", "5m<200 · 1h<50 · 밴드주황 · ST빨강"),
    "none":  ("⚪ 조건 미충족", ""),
}
SIGNAL_CLS = {"long": "ss-long", "short": "ss-short", "none": "ss-none"}
