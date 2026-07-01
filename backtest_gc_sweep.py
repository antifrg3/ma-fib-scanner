#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
골든크로스 진입 신호 이평 길이 스윕 — "어느 길이가 좋은 종목을 발굴하나"
──────────────────────────────────────────────────────────────────
목적: 국면 판별이 아니라 '진입 신호'로서의 골든크로스 최적 길이 검증.
      크로스로 잡은 눌림목 거래의 기대값(R)이 이평 길이에 따라 어떻게 변하나.

방식: 골든크로스(빠른선 F × 200) → 피보 0.382~0.618 눌림 진입.
      F를 30/50/100/150으로 스윕하고, 각 시장(미국·한국·크립토)에서
      유니버스 전체 거래를 POOL해 기대값·PF·거래수 비교.

핵심 질문:
  · 크립토는 짧은 F(50 등)가 미국(200)보다 좋은 종목을 더 잘 잡나?
  · 한국은 100 근처가 최적인가?
  · 미국은 정말 200(느린선)이 최적인가?

주식=야후 일봉 / 크립토=바이낸스 일봉. (4h는 이번 결과 부족 시 별도)
룩어헤드 방지, 왕복 비용 0.2% 반영.

실행:
  cd ~/GitHub/ma-fib-scanner
  python3 backtest_gc_sweep.py
"""
import warnings
warnings.filterwarnings("ignore")
import os
import time
import json
import urllib.request
from datetime import datetime, timezone
import numpy as np
import pandas as pd

COST = 0.001
GC_LOOKBACK = 120
PRE_LOOKBACK = 60
ENTRY_FIB = 0.5
STOP_FIB = 0.618
SLOW = 200
FAST_SWEEP = [30, 50, 100, 150]     # 진입 신호 빠른선 길이 스윕


def read_universe(path, limit=None):
    if not os.path.exists(path):
        return []
    out = [l.split("#")[0].strip() for l in open(path, encoding="utf-8")]
    out = [x for x in out if x]
    return out[:limit] if limit else out


def load_yahoo(ticker, start="2008-01-01"):
    import yfinance as yf
    df = yf.download(ticker, start=start, progress=False, auto_adjust=True)
    if df is None or len(df) < 260:
        return None
    df = df[["Open", "High", "Low", "Close"]].dropna()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df


def load_binance_daily(symbol, days=3200):
    bases = ["https://data-api.binance.vision", "https://api.binance.com"]
    end = int(datetime.now(timezone.utc).timestamp() * 1000)
    start = end - days * 86400_000
    rows, cursor = [], start
    while cursor < end:
        chunk = None
        for b in bases:
            try:
                url = (f"{b}/api/v3/klines?symbol={symbol}&interval=1d"
                       f"&startTime={cursor}&endTime={end}&limit=1000")
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=25) as r:
                    d = json.loads(r.read().decode())
                if isinstance(d, list) and d:
                    chunk = d; break
            except Exception:
                continue
        if not chunk:
            break
        rows.extend(chunk)
        nxt = chunk[-1][0] + 86400_000
        if nxt <= cursor:
            break
        cursor = nxt
        if len(chunk) < 1000:
            break
    if not rows:
        return None
    df = pd.DataFrame(rows, columns=["t","o","h","l","c","v","ct","qv","n","tb","tq","ig"])
    df["date"] = pd.to_datetime(df["t"], unit="ms")
    df = df.drop_duplicates("t").set_index("date")
    return df[["o","h","l","c"]].astype(float).rename(
        columns={"o":"Open","h":"High","l":"Low","c":"Close"})


def backtest_symbol(df, fast):
    """빠른선 fast × 200 골든크로스 후 피보 눌림 진입 거래들."""
    c, h, l = df["Close"], df["High"], df["Low"]
    n = len(df)
    fma, sma = c.rolling(fast).mean(), c.rolling(SLOW).mean()
    above = fma > sma
    crosses = list(np.where((above & ~above.shift(1).fillna(False)).values)[0])
    trades = []
    for cp in crosses:
        if cp < PRE_LOOKBACK or cp >= n - 2:
            continue
        low = float(l.iloc[max(0, cp - PRE_LOOKBACK):cp + 1].min())
        high = float(h.iloc[cp])
        for j in range(cp + 1, min(cp + GC_LOOKBACK, n)):
            high = max(high, float(h.iloc[j]))
            rng = high - low
            if rng <= 0:
                continue
            entry = high - ENTRY_FIB * rng
            stop = high - STOP_FIB * rng - 0.02 * rng
            if float(l.iloc[j]) <= entry and entry > stop:
                risk = entry - stop
                target = high
                exitp, out = None, None
                for k in range(j + 1, n):
                    if float(l.iloc[k]) <= stop:
                        exitp, out = stop, "loss"; break
                    if float(h.iloc[k]) >= target:
                        exitp, out = target, "win"; break
                if exitp is None:
                    exitp, out = float(c.iloc[-1]), "open"
                R = (exitp - entry - entry * COST * 2) / risk
                trades.append({"R": R})
                break
    return trades


def pool(trades):
    if not trades:
        return None
    R = np.array([t["R"] for t in trades])
    gw, gl = R[R > 0].sum(), -R[R < 0].sum()
    return {"n": len(R), "win": (R > 0).mean() * 100, "avgR": R.mean(),
            "sumR": R.sum(), "pf": gw / gl if gl > 0 else 99.9}


def run_market(label, loader, syms):
    print(f"\n{'='*70}\n{label}\n{'='*70}")
    # 각 종목 데이터 1회 로드 → 여러 fast에 재사용
    data = {}
    for i, sym in enumerate(syms):
        try:
            df = loader(sym)
            if df is not None:
                data[sym] = df
        except Exception:
            pass
        if (i + 1) % 20 == 0:
            print(f"  ...데이터 {i+1}/{len(syms)} 로드 (성공 {len(data)})")
        time.sleep(0.03)
    print(f"  데이터 확보: {len(data)}/{len(syms)} 종목\n")

    print(f"{'빠른선(×200)':<16}{'거래':>7}{'승률':>8}{'기대값':>9}{'합계R':>9}{'PF':>7}")
    print("-" * 70)
    best = None
    for fast in FAST_SWEEP:
        allt = []
        for df in data.values():
            allt += backtest_symbol(df, fast)
        st = pool(allt)
        if not st:
            print(f"{fast:>3}일 × 200        진입 0"); continue
        flag = "✅" if st["avgR"] > 0.1 and st["n"] >= 30 else ("⚠️표본<30" if st["n"] < 30 else "△")
        print(f"{str(fast)+'일 × 200':<16}{st['n']:>7}{st['win']:>7.1f}%{st['avgR']:>9.3f}{st['sumR']:>9.1f}{st['pf']:>7.2f}  {flag}")
        if st["n"] >= 30 and (best is None or st["avgR"] > best[1]):
            best = (fast, st["avgR"], st["n"])
    if best:
        print(f"\n★ {label} 최적: {best[0]}일 × 200 크로스 (기대값 {best[1]:.3f}R, {best[2]}건)")
    return best


def main():
    print("골든크로스 진입 신호 이평 길이 스윕 — 종목 발굴 최적 길이 검증")
    print(f"빠른선 {FAST_SWEEP} × 200 / 피보 0.5 진입 / 왕복비용 0.2%\n")
    results = {}

    # 미국
    us = read_universe("tickers_us.txt")
    results["미국"] = run_market("미국(나스닥100)", load_yahoo, us)
    # 한국
    kr = read_universe("tickers_kr.txt")
    results["한국"] = run_market("한국(코스피)", load_yahoo, kr)
    # 크립토
    cr = read_universe("tickers_crypto.txt")
    results["크립토"] = run_market("크립토", load_binance_daily, cr)

    print(f"\n{'='*70}\n종합: 시장별 최적 골든크로스 빠른선\n{'='*70}")
    print(f"{'시장':<10}{'최적 빠른선':<16}{'기대값':>9}{'거래':>7}")
    print("-" * 70)
    for k, b in results.items():
        if b:
            print(f"{k:<10}{str(b[0])+'일 × 200':<16}{b[1]:>8.3f}R{b[2]:>7}")
        else:
            print(f"{k:<10}{'표본부족/실패':<16}")
    print(f"\n{'='*70}")
    print("해석:")
    print("  · 시장별 최적 빠른선이 다르면(크립토 짧게·미국 길게) = 자산별 최적화 정당")
    print("  · 현재 대시보드는 4h200×일봉200. 일봉 기준 최적이 200보다 짧으면 크로스 개선 여지")
    print("  · 이 결과가 부족하면(표본·신뢰) 4h×일봉 정밀 백테스트로 재검증")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()
