#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
outperform.py — BTC 대비 강세 코인 탐지 (알트시즌 로직)
─────────────────────────────────────────────────────────────────────────
CMC 알트시즌 인덱스와 같은 개념: "최근 N일간 BTC를 이긴 코인 찾기".
CMC 크롤링 없이 바이낸스 데이터로 자체 계산.

방식:
  1) 바이낸스 24h 거래대금 상위 100개(스테이블/래핑/레버리지 제외) 수집
  2) 각 코인의 30일·90일 수익률 vs BTC 수익률 비교
  3) BTC를 이긴(초과수익>0) 코인만 필터 → 초과수익 순 정렬

정배열 스캐너(이평 정렬)가 놓치는 '갓 오르기 시작한 알트'까지 포착.
"""
import json
import urllib.request
from dataclasses import dataclass
import numpy as np
import pandas as pd

BINANCE_BASES = ["https://data-api.binance.vision", "https://api.binance.com"]

STABLE = {"USDT", "USDC", "BUSD", "TUSD", "DAI", "FDUSD", "USDD", "USDP",
          "GUSD", "PYUSD", "EURT", "EUR", "FRAX", "LUSD", "USTC"}
WRAPPED = {"WBTC", "WETH", "WBETH", "STETH", "WSTETH", "CBETH", "RETH",
           "BETH", "WBNB", "SOLETH"}


def _is_stable(base: str) -> bool:
    return base in STABLE


def _is_leveraged(base: str) -> bool:
    return base.endswith(("UP", "DOWN", "BULL", "BEAR")) or "3L" in base or "3S" in base


def top_symbols(n: int = 100) -> list[str]:
    """바이낸스 24h 거래대금 상위 N개 USDT 페어(정제)."""
    data = None
    for base_url in BINANCE_BASES:
        try:
            req = urllib.request.Request(base_url + "/api/v3/ticker/24hr",
                                         headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.loads(r.read().decode())
            if data:
                break
        except Exception:
            continue
    if not data:
        return []
    rows = []
    for d in data:
        sym = d.get("symbol", "")
        if not sym.endswith("USDT"):
            continue
        base = sym[:-4]
        if _is_stable(base) or base in WRAPPED or _is_leveraged(base):
            continue
        try:
            qv = float(d.get("quoteVolume", 0))
        except (TypeError, ValueError):
            qv = 0.0
        rows.append((sym, qv))
    rows.sort(key=lambda x: x[1], reverse=True)
    return [s for s, _ in rows[:n]]


def fetch_closes(symbol: str, days: int = 120) -> pd.Series | None:
    """일봉 종가 시리즈(최근 days+ 개)."""
    for base_url in BINANCE_BASES:
        try:
            url = (f"{base_url}/api/v3/klines?symbol={symbol}"
                   f"&interval=1d&limit={days + 5}")
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=25) as r:
                d = json.loads(r.read().decode())
            if isinstance(d, list) and len(d) >= 30:
                idx = pd.to_datetime([k[0] for k in d], unit="ms")
                return pd.Series([float(k[4]) for k in d], index=idx)
        except Exception:
            continue
    return None


def _ret(closes: pd.Series, days: int) -> float | None:
    """days일 전 대비 수익률(%). 데이터 부족 시 None."""
    if closes is None or len(closes) < days + 1:
        return None
    now = float(closes.iloc[-1])
    past = float(closes.iloc[-(days + 1)])
    if past <= 0:
        return None
    return (now / past - 1) * 100


@dataclass
class OutperformState:
    symbol: str
    ret30: float | None
    ret90: float | None
    excess30: float | None    # 코인 30일 - BTC 30일
    excess90: float | None
    beats_btc30: bool
    beats_btc90: bool
    closes: pd.Series


def scan_outperformers(top_n: int = 100):
    """상위 top_n 코인 중 BTC를 이긴 것들. (btc_ret30, btc_ret90, [OutperformState]) 반환."""
    syms = top_symbols(top_n)
    if "BTCUSDT" not in syms:
        syms = ["BTCUSDT"] + syms

    btc = fetch_closes("BTCUSDT", 120)
    btc30 = _ret(btc, 30)
    btc90 = _ret(btc, 90)
    if btc30 is None or btc90 is None:
        return None, None, []

    out = []
    for sym in syms:
        if sym == "BTCUSDT":
            continue
        closes = fetch_closes(sym, 120)
        if closes is None:
            continue
        r30 = _ret(closes, 30)
        r90 = _ret(closes, 90)
        if r30 is None and r90 is None:
            continue
        e30 = (r30 - btc30) if r30 is not None else None
        e90 = (r90 - btc90) if r90 is not None else None
        out.append(OutperformState(
            symbol=sym, ret30=r30, ret90=r90, excess30=e30, excess90=e90,
            beats_btc30=(e30 is not None and e30 > 0),
            beats_btc90=(e90 is not None and e90 > 0),
            closes=closes,
        ))
    return btc30, btc90, out
