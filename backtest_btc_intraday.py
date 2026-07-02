#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BTC 분봉 골든크로스 백테스트 — 5/15/30/60분봉에서 골크가 되나?
──────────────────────────────────────────────────────────────────
질문: 비트코인은 24시간 거래 → 분봉 골든크로스 눌림목이 일봉보다 나을까?
예상: 분봉은 크로스가 잦아 왕복 0.2% 비용에 죽을 가능성 큼(스캘핑 5종의 교훈).
      진짜인지 데이터로 확인.

방식:
  · 5/15/30/60분봉 각각 바이낸스에서 수집(페이지네이션).
  · 각 시간봉에서 빠른선×느린선 조합 스윕(분봉 스케일).
  · 피보 0.382~0.618 눌림 진입(일봉 로직과 동일), 왕복 0.2% 비용.
  · 기준선: 일봉 30×150 = 0.593R (검증됨)와 비교.

주의: 분봉은 데이터가 많아 최근 구간만(시간봉별 봉 수 제한). 시간 좀 걸림.

실행:
  cd ~/GitHub/ma-fib-scanner
  python3 backtest_btc_intraday.py
"""
import warnings
warnings.filterwarnings("ignore")
import json
import time
import urllib.request
from datetime import datetime, timezone
import numpy as np
import pandas as pd

COST = 0.001          # 편도 0.1% (왕복 0.2%)
PRE_LOOKBACK = 60     # 크로스 전 저점 탐색(봉)
GC_LOOKBACK = 120     # 크로스 후 진입 대기(봉)
ENTRY_FIB = 0.5
STOP_FIB = 0.618

# 시간봉별 (빠른선, 느린선) 조합 스윕 — 분봉 스케일
MA_PAIRS = [(20, 50), (30, 100), (50, 150), (50, 200), (100, 200)]

# 시간봉별 수집할 봉 수(대략 최근 기간). 5분봉은 촘촘해 더 많이.
TF_BARS = {"5m": 60000, "15m": 40000, "30m": 30000, "1h": 25000}
TF_MS = {"5m": 300_000, "15m": 900_000, "30m": 1_800_000, "1h": 3_600_000}


def load_binance(symbol, interval, n_bars):
    """분봉 페이지네이션 수집 (1000개씩)."""
    bases = ["https://data-api.binance.vision", "https://api.binance.com"]
    per = TF_MS[interval]
    end = int(datetime.now(timezone.utc).timestamp() * 1000)
    start = end - n_bars * per
    rows, cursor = [], start
    calls = 0
    while cursor < end and calls < 200:
        chunk = None
        for b in bases:
            try:
                url = (f"{b}/api/v3/klines?symbol={symbol}&interval={interval}"
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
        calls += 1
        nxt = chunk[-1][0] + per
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


def backtest(df, fast, slow):
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


def run_tf(tf, df):
    span_days = (df.index[-1] - df.index[0]).days
    print(f"\n{'='*68}\nBTC {tf}봉  ({len(df):,}봉 · 약 {span_days}일: {df.index[0].date()}~{df.index[-1].date()})\n{'='*68}")
    print(f"{'빠른×느린':<14}{'거래':>7}{'승률':>8}{'기대값':>9}{'합계R':>9}{'PF':>7}")
    print("-" * 68)
    best = None
    for fast, slow in MA_PAIRS:
        st = pool(backtest(df, fast, slow))
        if not st:
            print(f"{f'{fast}×{slow}':<14} 진입 0"); continue
        flag = "✅" if st["avgR"] > 0.1 and st["n"] >= 30 else ("⚠️표본<30" if st["n"] < 30 else "△")
        print(f"{f'{fast}×{slow}':<14}{st['n']:>7}{st['win']:>7.1f}%{st['avgR']:>9.3f}{st['sumR']:>9.1f}{st['pf']:>7.2f}  {flag}")
        if st["n"] >= 30 and (best is None or st["avgR"] > best[1]):
            best = (f"{fast}×{slow}", st["avgR"], st["n"])
    if best:
        print(f"\n★ {tf}봉 최적: {best[0]} (기대값 {best[1]:.3f}R, {best[2]}건)")
    return best


def main():
    print("BTC 분봉 골든크로스 백테스트 — 5/15/30/60분봉")
    print(f"조합 스윕 {MA_PAIRS} / 피보 0.5 진입 / 왕복 0.2%")
    print("기준선(비교용): 일봉 30×150 = 0.593R\n")

    results = {}
    for tf in ["5m", "15m", "30m", "1h"]:
        print(f"\n[{tf}] 데이터 수집 중... (봉 많아 시간 걸림)")
        df = load_binance("BTCUSDT", tf, TF_BARS[tf])
        if df is None or len(df) < 300:
            print(f"  ⚠️ {tf} 데이터 수집 실패/부족"); continue
        results[tf] = run_tf(tf, df)
        time.sleep(0.2)

    print(f"\n{'='*68}\n종합: BTC 시간봉별 최적 골든크로스 vs 일봉\n{'='*68}")
    print(f"{'시간봉':<10}{'최적 조합':<14}{'기대값':>9}{'거래':>7}   {'일봉대비'}")
    print("-" * 68)
    print(f"{'일봉(기준)':<10}{'30×150':<14}{0.593:>8.3f}R{257:>7}   —")
    for tf, b in results.items():
        if b:
            delta = b[1] - 0.593
            mark = "🎯 더나음" if delta > 0.05 else ("비슷" if abs(delta) <= 0.05 else "일봉이 나음")
            print(f"{tf+'봉':<10}{b[0]:<14}{b[1]:>8.3f}R{b[2]:>7}   {mark}")
        else:
            print(f"{tf+'봉':<10}{'표본부족/실패':<14}")
    print(f"\n{'='*68}")
    print("해석:")
    print("  · 분봉 최적이 일봉(0.593R)보다 확실히 높으면 → 분봉 골크 가치 있음")
    print("  · 대부분 마이너스/저조하면 → 비용에 죽음(스캘핑 교훈 재확인), 일봉 유지")
    print("  · 거래수가 수백~수천이면 실제 실행 시 슬리피지·수수료 더 커짐 주의")
    print(f"{'='*68}")


if __name__ == "__main__":
    main()
