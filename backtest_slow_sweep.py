#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
골든크로스 '느린선' 스윕 — 200이 정말 최선인가?
──────────────────────────────────────────────────────────────────
앞서 빠른선만 검증(미국100·한국50·크립토30), 느린선은 관습대로 200 고정했음.
이번엔 빠른선을 그 최적값으로 고정하고 느린선만 150/200/250 스윕.
→ "200이 진짜 최선인지, 150/250이 나은지" 확인. (변수 1개만 → 과최적화 최소)

과최적화 경계:
  · 표본 30건+ 만 신뢰
  · 최고점 하나가 아니라 '전반적으로 어느 느린선 영역이 안정적인지' 판단
  · 미세차(<0.05R)는 무시, 확실한 차이만 반영

실행:
  cd ~/GitHub/ma-fib-scanner
  python3 backtest_slow_sweep.py
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
SLOW_SWEEP = [150, 200, 250]

# 앞서 검증된 시장별 최적 빠른선 (고정)
FIXED_FAST = {"미국": 100, "한국": 50, "크립토": 30}


def read_universe(path, limit=None):
    if not os.path.exists(path):
        return []
    out = [l.split("#")[0].strip() for l in open(path, encoding="utf-8")]
    out = [x for x in out if x]
    return out[:limit] if limit else out


def load_yahoo(ticker, start="2008-01-01"):
    import yfinance as yf
    df = yf.download(ticker, start=start, progress=False, auto_adjust=True)
    if df is None or len(df) < 300:
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


def backtest_symbol(df, fast, slow):
    c, h, l = df["Close"], df["High"], df["Low"]
    n = len(df)
    fma, sma = c.rolling(fast).mean(), c.rolling(slow).mean()
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


def run_market(label, loader, syms, fast):
    print(f"\n{'='*68}\n{label}  (빠른선 {fast} 고정 · 느린선 스윕)\n{'='*68}")
    data = {}
    for i, sym in enumerate(syms):
        try:
            df = loader(sym)
            if df is not None:
                data[sym] = df
        except Exception:
            pass
        if (i + 1) % 25 == 0:
            print(f"  ...데이터 {i+1}/{len(syms)} (성공 {len(data)})")
        time.sleep(0.03)
    print(f"  데이터 확보: {len(data)}/{len(syms)}\n")

    print(f"{'느린선':<16}{'거래':>7}{'승률':>8}{'기대값':>9}{'합계R':>9}{'PF':>7}")
    print("-" * 68)
    rows = []
    for slow in SLOW_SWEEP:
        if slow <= fast:
            continue
        allt = []
        for df in data.values():
            allt += backtest_symbol(df, fast, slow)
        st = pool(allt)
        if not st:
            print(f"{str(fast)+'×'+str(slow):<16} 진입 0"); continue
        flag = "✅" if st["avgR"] > 0.1 and st["n"] >= 30 else ("⚠️표본<30" if st["n"] < 30 else "△")
        print(f"{str(fast)+'×'+str(slow):<16}{st['n']:>7}{st['win']:>7.1f}%{st['avgR']:>9.3f}{st['sumR']:>9.1f}{st['pf']:>7.2f}  {flag}")
        rows.append((slow, st))
    # 판정: 표본 30+ 중 최고, 단 200과 차이 작으면 200 유지 권장
    valid = [(s, st) for s, st in rows if st["n"] >= 30]
    best = max(valid, key=lambda x: x[1]["avgR"]) if valid else None
    base = next((st for s, st in rows if s == 200), None)
    if best:
        bs, bst = best
        note = ""
        if base and abs(bst["avgR"] - base["avgR"]) < 0.05:
            note = "  (200과 차이 미미 → 200 유지 무방)"
        print(f"\n★ 최적 느린선: {bs} (기대값 {bst['avgR']:.3f}R, {bst['n']}건){note}")
        return (fast, bs, bst["avgR"], bst["n"], base["avgR"] if base else None)
    return None


def main():
    print("골든크로스 느린선 스윕 — 200이 정말 최선인가?")
    print(f"빠른선 고정(미국100·한국50·크립토30) · 느린선 {SLOW_SWEEP} 스윕\n")
    res = {}
    res["미국"] = run_market("미국(나스닥100)", load_yahoo, read_universe("tickers_us.txt"), FIXED_FAST["미국"])
    res["한국"] = run_market("한국(코스피)", load_yahoo, read_universe("tickers_kr.txt"), FIXED_FAST["한국"])
    res["크립토"] = run_market("크립토", load_binance_daily, read_universe("tickers_crypto.txt"), FIXED_FAST["크립토"])

    print(f"\n{'='*68}\n종합: 시장별 최적 (빠른선 × 느린선)\n{'='*68}")
    print(f"{'시장':<10}{'최적 조합':<14}{'기대값':>9}{'200대비':>10}{'거래':>7}")
    print("-" * 68)
    for k, b in res.items():
        if b:
            fast, slow, avgR, n, base200 = b
            delta = f"{avgR-base200:+.3f}" if base200 is not None else "—"
            print(f"{k:<10}{f'{fast}×{slow}':<14}{avgR:>8.3f}R{delta:>10}{n:>7}")
        else:
            print(f"{k:<10}{'표본부족':<14}")
    print(f"\n{'='*68}")
    print("해석:")
    print("  · '200대비'가 +0.05R 미만이면 → 200 유지 무방(느린선은 관습대로 OK)")
    print("  · +0.1R 이상 개선되는 느린선이 있으면 → 그 값으로 교체 정당")
    print("  · 크립토는 데이터 8년뿐 → 250은 워밍업 부담, 150이 나을 수 있음")
    print(f"{'='*68}")


if __name__ == "__main__":
    main()
