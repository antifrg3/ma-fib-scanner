#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
눌림목 유니버스 전체 백테스트 — 표본 대량 확보판
──────────────────────────────────────────────────────────────────
지수 1개당 3건 → 유니버스 전 종목을 돌려 시장별 수백 건으로 통계 검증.

대시보드 실제 로직(golden cross 50×200 + 피보 0.382~0.618 눌림) 그대로,
tickers_us.txt / tickers_kr.txt / tickers_etf.txt 전 종목에 적용해
거래를 시장별로 POOL(합산)해서 승률·기대값·PF를 낸다.

+ 국면필터 비교: 진입 시점에 지수가 200일선 위(강세)일 때만 거래한 경우도 병행,
  "필터 얹으면 개선되나"를 같이 확인.

실행:
  pip3 install yfinance pandas numpy
  python3 backtest_pullback_universe.py
주의: 종목 많아 수 분 소요. 야후 레이트리밋 시 자동 대기.
"""
import warnings
warnings.filterwarnings("ignore")
import os
import time
import numpy as np
import pandas as pd

COST = 0.001
GC_LOOKBACK = 120
PRE_LOOKBACK = 60
ENTRY_FIB = 0.5
STOP_FIB = 0.618
FAST, SLOW = 50, 200


def read_universe(path, limit=None):
    if not os.path.exists(path):
        return []
    out = []
    for line in open(path, encoding="utf-8"):
        line = line.split("#")[0].strip()
        if line:
            out.append(line)
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


def golden_crosses(close):
    f, s = close.rolling(FAST).mean(), close.rolling(SLOW).mean()
    above = f > s
    return list(np.where((above & ~above.shift(1).fillna(False)).values)[0]), s


def backtest_symbol(df, bench_ma_at=None):
    """단일 종목 눌림목 거래 리스트. bench_ma_at: 진입봉 인덱스→강세여부(dict) 있으면 필터."""
    c, h, l = df["Close"], df["High"], df["Low"]
    n = len(df)
    crosses, _ = golden_crosses(c)
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
                exitp, outcome = None, None
                for k in range(j + 1, n):
                    if float(l.iloc[k]) <= stop:
                        exitp, outcome = stop, "loss"; break
                    if float(h.iloc[k]) >= target:
                        exitp, outcome = target, "win"; break
                if exitp is None:
                    exitp, outcome = float(c.iloc[-1]), "open"
                cost = entry * COST * 2
                R = (exitp - entry - cost) / risk
                trades.append({"entry_i": j, "R": R, "outcome": outcome,
                               "date": df.index[j]})
                break
    return trades


def pool_stats(name, trades):
    if not trades:
        print(f"{name:<24} 진입 0건"); return None
    R = np.array([t["R"] for t in trades])
    win = (R > 0).mean() * 100
    avgR, sumR = R.mean(), R.sum()
    gw, gl = R[R > 0].sum(), -R[R < 0].sum()
    pf = gw / gl if gl > 0 else float("inf")
    eq = np.cumsum(R)
    mdd = (eq - np.maximum.accumulate(eq)).min()
    n = len(R)
    if n < 30:
        vd = f"⚠️표본{n}<30"
    elif avgR > 0.1:
        vd = "✅ +기대값"
    elif avgR < 0:
        vd = "❌ 마이너스"
    else:
        vd = "△ 애매"
    print(f"{name:<24}{n:>6}{win:>7.1f}%{sumR:>9.1f}{avgR:>9.3f}{pf:>7.2f}{mdd:>9.1f}  {vd}")
    return {"n": n, "avgR": avgR, "win": win, "pf": pf}


def run_market(label, path, bench_ticker, limit=None):
    print(f"\n{'='*78}\n{label}  (유니버스: {path})\n{'='*78}")
    syms = read_universe(path, limit)
    if not syms:
        print("종목 없음"); return
    # 벤치마크 200일선(국면필터용)
    bench = load_yahoo(bench_ticker)
    bench_ma = None
    if bench is not None:
        bench_ma = (bench["Close"] > bench["Close"].rolling(200).mean())

    all_tr, filt_tr = [], []
    done, fail = 0, 0
    for i, sym in enumerate(syms):
        try:
            df = load_yahoo(sym)
            if df is None:
                fail += 1; continue
            tr = backtest_symbol(df)
            all_tr += tr
            # 국면필터: 진입일에 벤치가 200일선 위였던 거래만
            if bench_ma is not None:
                for t in tr:
                    d = t["date"]
                    if d in bench_ma.index and bool(bench_ma.loc[d]):
                        filt_tr.append(t)
                    elif d not in bench_ma.index:
                        # 가장 가까운 이전 영업일
                        prev = bench_ma.loc[:d]
                        if len(prev) and bool(prev.iloc[-1]):
                            filt_tr.append(t)
            done += 1
        except Exception:
            fail += 1
        if (i + 1) % 20 == 0:
            print(f"  ...{i+1}/{len(syms)} 처리 (거래 {len(all_tr)}건)")
        time.sleep(0.05)

    print(f"\n종목 {done}개 처리(실패 {fail}) · 총 거래 {len(all_tr)}건")
    print(f"{'구분':<24}{'거래':>6}{'승률':>8}{'합계R':>9}{'기대값':>9}{'PF':>7}{'MDD':>9}")
    print("-" * 78)
    pool_stats(f"{label} 전체", all_tr)
    if bench_ma is not None:
        pool_stats(f"{label} +국면필터(강세만)", filt_tr)


def main():
    print("눌림목 유니버스 전체 백테스트 — 표본 대량 확보")
    print(f"로직: 골든크로스 {FAST}×{SLOW} + 피보 0.5 진입 / 0.618-2% 손절 / 고점 익절")
    print("국면필터: 진입일 지수>200일선(강세)일 때만 거래한 경우 병행 비교\n")

    run_market("미국(나스닥100)", "tickers_us.txt", "QQQ")
    run_market("미국ETF", "tickers_etf.txt", "SPY")
    run_market("한국(코스피)", "tickers_kr.txt", "^KS11")

    print(f"\n{'='*78}")
    print("해석:")
    print("  · 표본 30건+ 에서 기대값 +0.1R 이상 = 눌림목 신호 실제 유효")
    print("  · '+국면필터' 행이 '전체'보다 나으면 = regime 필터가 실제로 개선")
    print("  · 한국이 미국보다 나쁘면 = 우리 리포트(한국=모멘텀 약함) 재확인")
    print(f"{'='*78}")


if __name__ == "__main__":
    main()
