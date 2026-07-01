#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
크립토 종목별 골든크로스 길이 스윕 — "30일이 BTC/ETH에도 맞나?"
──────────────────────────────────────────────────────────────────
문제의식: 크립토 전체 풀 최적이 30일이었지만, 이게 변동성 큰 알트 때문일 수도.
         대형(BTC/ETH)은 트렌드스윕에서 50일이 최적이었음 → 따로 확인 필요.

측정:
  1) BTC 단독 · ETH 단독 (표본 적어도 방향 확인)
  2) 대형 그룹(BTC·ETH·BNB·SOL·XRP) POOL
  3) 나머지(중형 알트) POOL
  각각 골든크로스 빠른선 30/50/100/150 × 200 스윕.

이러면 30일이 대형에도 맞는지, 아니면 알트발 착시인지 드러남.

실행:
  cd ~/GitHub/ma-fib-scanner
  python3 backtest_crypto_gc.py
"""
import warnings
warnings.filterwarnings("ignore")
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
FAST_SWEEP = [30, 50, 100, 150]

LARGE = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT"]
MID = ["ADAUSDT", "DOGEUSDT", "AVAXUSDT", "LINKUSDT", "DOTUSDT", "TRXUSDT",
       "LTCUSDT", "BCHUSDT", "ATOMUSDT", "UNIUSDT", "NEARUSDT", "APTUSDT",
       "ARBUSDT", "OPUSDT", "FILUSDT", "INJUSDT", "SUIUSDT", "ETCUSDT",
       "XLMUSDT", "HBARUSDT", "AAVEUSDT"]


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
                exitp = None
                for k in range(j + 1, n):
                    if float(l.iloc[k]) <= stop:
                        exitp = stop; break
                    if float(h.iloc[k]) >= target:
                        exitp = target; break
                if exitp is None:
                    exitp = float(c.iloc[-1])
                R = (exitp - entry - entry * COST * 2) / risk
                trades.append(R)
                break
    return trades


def pool(trades):
    if not trades:
        return None
    R = np.array(trades)
    gw, gl = R[R > 0].sum(), -R[R < 0].sum()
    return {"n": len(R), "win": (R > 0).mean() * 100, "avgR": R.mean(),
            "sumR": R.sum(), "pf": gw / gl if gl > 0 else 99.9}


def sweep_group(label, dfs):
    print(f"\n{'─'*66}\n{label}\n{'─'*66}")
    print(f"{'빠른선':<14}{'거래':>7}{'승률':>8}{'기대값':>9}{'합계R':>9}{'PF':>7}")
    best = None
    for fast in FAST_SWEEP:
        allt = []
        for df in dfs:
            allt += backtest_symbol(df, fast)
        st = pool(allt)
        if not st:
            print(f"{fast:>3}일×200      진입 0"); continue
        flag = "✅" if st["avgR"] > 0.1 and st["n"] >= 30 else ("⚠️표본<30" if st["n"] < 30 else "△")
        print(f"{str(fast)+'일×200':<14}{st['n']:>7}{st['win']:>7.1f}%{st['avgR']:>9.3f}{st['sumR']:>9.1f}{st['pf']:>7.2f}  {flag}")
        # 표본 15+ 면 후보(단독 코인은 거래가 적어 기준 낮춤)
        if st["n"] >= 15 and (best is None or st["avgR"] > best[1]):
            best = (fast, st["avgR"], st["n"])
    if best:
        print(f"  ★ 최적: {best[0]}일×200 (기대값 {best[1]:.3f}R, {best[2]}건)")
    return best


def main():
    print("크립토 종목별 골든크로스 길이 스윕 — 30일이 대형에도 맞나?")
    print(f"빠른선 {FAST_SWEEP} × 200 / 피보 0.5 / 왕복 0.2%")

    # 데이터 로드
    print("\n데이터 로드 중...")
    cache = {}
    for sym in LARGE + MID:
        df = load_binance_daily(sym)
        if df is not None and len(df) >= 260:
            cache[sym] = df
    print(f"확보: {len(cache)}종목")

    results = {}
    # 1) BTC·ETH 단독
    for sym in ["BTCUSDT", "ETHUSDT"]:
        if sym in cache:
            results[sym] = sweep_group(f"{sym} 단독", [cache[sym]])
    # 2) 대형 그룹
    large_dfs = [cache[s] for s in LARGE if s in cache]
    results["대형"] = sweep_group(f"대형 그룹 POOL ({len(large_dfs)}종목: BTC·ETH·BNB·SOL·XRP)", large_dfs)
    # 3) 중형 그룹
    mid_dfs = [cache[s] for s in MID if s in cache]
    results["중형"] = sweep_group(f"중형 알트 POOL ({len(mid_dfs)}종목)", mid_dfs)

    print(f"\n{'='*66}\n종합: 크립토 그룹별 최적 골든크로스 빠른선\n{'='*66}")
    print(f"{'그룹':<16}{'최적 빠른선':<14}{'기대값':>9}{'거래':>7}")
    print("-" * 66)
    for k, b in results.items():
        if b:
            print(f"{k:<16}{str(b[0])+'일×200':<14}{b[1]:>8.3f}R{b[2]:>7}")
        else:
            print(f"{k:<16}{'표본부족':<14}")
    print(f"\n{'='*66}")
    print("해석:")
    print("  · 대형(BTC/ETH)도 30이면 → 크립토 통째로 30 적용 OK")
    print("  · 대형이 50 이상이면 → '대형 50 / 중형 30'로 구분하거나, 유니버스 구성따라 결정")
    print("  · 우리 크립토 유니버스는 대형~중형 위주(잡알트 거의 없음)")
    print(f"{'='*66}")


if __name__ == "__main__":
    main()
