#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
눌림목(골든크로스 + 피보 되돌림) 백테스트 — 대시보드 실제 로직 검증
──────────────────────────────────────────────────────────────────
지금까지 검증 안 했던 "네 대시보드의 핵심 진입 신호"를 처음으로 백테스트.

대시보드 로직(ma_fib_scanner.build_setup) 그대로:
  1. 골든크로스: (BTC) 4h 200선이 일봉 200선 상향돌파 / (주식) 일봉 50선이 200선 상향돌파(근사)
  2. 피보 앵커: 크로스 전 60봉 저점 ~ 크로스 후 고점
  3. 진입: 되돌림 0.382~0.618 구간 진입 시 (0.5 라인에서 체결 가정)
  4. 손절: 고점 - 0.618*range - 0.02*range
  5. 익절: 피보 고점(take_profit=high)
  6. 크로스 인정: 최근 120거래일 내

BTC   → 바이낸스 4h+일봉 (원본 로직 정확히)
주식  → 야후 일봉 50x200 크로스 근사 (야후가 4h 장기간 미제공)

비용: 진입/청산 편도 0.1%(왕복 0.2%). R = (청산-진입)/(진입-손절) - 비용.
룩어헤드 방지: 크로스·되돌림은 확정봉 기준, 진입은 그 다음 봉.

실행:
  pip3 install yfinance pandas numpy
  python3 backtest_pullback.py
"""
import warnings
warnings.filterwarnings("ignore")
import json
import urllib.request
from datetime import datetime, timezone
import numpy as np
import pandas as pd

COST = 0.001                    # 편도 0.1%
GC_LOOKBACK = 120               # 크로스 인정 기간(거래일/봉)
PRE_LOOKBACK = 60               # 크로스 전 저점 탐색
ENTRY_FIB = 0.5                 # 진입 체결 가정 라인(0.382~0.618 중앙)
STOP_FIB = 0.618


def load_binance(symbol, interval, limit_days):
    bases = ["https://data-api.binance.vision", "https://api.binance.com"]
    per = {"1d": 86400_000, "4h": 14400_000}[interval]
    end = int(datetime.now(timezone.utc).timestamp() * 1000)
    start = end - limit_days * 86400_000
    rows, cursor = [], start
    while cursor < end:
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
        nxt = chunk[-1][0] + per
        if nxt <= cursor:
            break
        cursor = nxt
        if len(chunk) < 1000:
            break
    if not rows:
        raise RuntimeError(f"바이낸스 실패 {symbol} {interval}")
    df = pd.DataFrame(rows, columns=["t","o","h","l","c","v","ct","qv","n","tb","tq","ig"])
    df["date"] = pd.to_datetime(df["t"], unit="ms")
    df = df.drop_duplicates("t").set_index("date")
    return df[["o","h","l","c"]].astype(float).rename(
        columns={"o":"Open","h":"High","l":"Low","c":"Close"})


def load_yahoo(ticker, start="2010-01-01"):
    import yfinance as yf
    df = yf.download(ticker, start=start, progress=False, auto_adjust=True)
    df = df[["Open","High","Low","Close"]].dropna()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df


def find_golden_crosses(fast_ma, slow_ma):
    """fast가 slow를 상향돌파하는 지점들의 인덱스 위치."""
    above = fast_ma > slow_ma
    cross = above & (~above.shift(1).fillna(False))
    return list(np.where(cross.values)[0])


def backtest(daily, cross_positions, label):
    """각 골든크로스마다 피보 셋업 → 되돌림 진입 → 손절/익절 시뮬레이션."""
    c, h, l = daily["Close"], daily["High"], daily["Low"]
    n = len(daily)
    trades = []
    for cp in cross_positions:
        if cp < PRE_LOOKBACK or cp >= n - 2:
            continue
        # 피보 앵커: 크로스 전 저점 ~ 크로스 후 진행 고점(다음 봉부터 갱신)
        low = float(l.iloc[max(0, cp - PRE_LOOKBACK):cp + 1].min())
        # 크로스 후 되돌림 진입을 봉 단위로 추적 (최대 GC_LOOKBACK봉)
        high = float(h.iloc[cp])
        entered = False
        for j in range(cp + 1, min(cp + GC_LOOKBACK, n)):
            high = max(high, float(h.iloc[j]))
            rng = high - low
            if rng <= 0:
                continue
            entry_price = high - ENTRY_FIB * rng
            stop = high - STOP_FIB * rng - 0.02 * rng
            # 되돌림이 진입가에 닿았나 (저가가 진입선 이하로 내려옴)
            if float(l.iloc[j]) <= entry_price and entry_price > stop:
                # 진입! 이후 손절/익절 추적
                risk = entry_price - stop
                target = high
                exit_price, outcome = None, None
                for k in range(j + 1, n):
                    if float(l.iloc[k]) <= stop:
                        exit_price, outcome = stop, "loss"; break
                    if float(h.iloc[k]) >= target:
                        exit_price, outcome = target, "win"; break
                if exit_price is None:
                    exit_price, outcome = float(c.iloc[-1]), "open"
                cost = entry_price * COST * 2
                r_mult = (exit_price - entry_price - cost) / risk
                trades.append({"entry_i": j, "entry": entry_price, "stop": stop,
                               "target": target, "exit": exit_price,
                               "outcome": outcome, "R": r_mult})
                entered = True
                break
        # 진입 안 되면 그 크로스는 스킵
    return trades


def stats(trades, label):
    if not trades:
        print(f"{label:<28} 진입 0건")
        return
    R = np.array([t["R"] for t in trades])
    wins = (R > 0).sum()
    win_pct = wins / len(R) * 100
    avgR = R.mean()
    sumR = R.sum()
    gross_w = R[R > 0].sum()
    gross_l = -R[R < 0].sum()
    pf = gross_w / gross_l if gross_l > 0 else float("inf")
    eq = np.cumsum(R)
    mdd = (eq - np.maximum.accumulate(eq)).min()
    verdict = "✅ +기대값" if avgR > 0.05 else ("❌ 비용 못이김" if avgR < 0 else "△ 애매")
    print(f"{label:<28}{len(R):>5}{win_pct:>7.1f}%{sumR:>9.1f}{avgR:>9.2f}{pf:>7.2f}{mdd:>9.1f}  {verdict}")


def main():
    print("눌림목(골든크로스+피보) 백테스트 — 대시보드 실제 로직 첫 검증")
    print("진입=되돌림 0.5선 체결, 손절=0.618-2%, 익절=피보 고점, 비용 왕복 0.2%\n")
    print(f"{'대상':<28}{'거래':>5}{'승률':>8}{'합계R':>9}{'기대값':>9}{'PF':>7}{'MDD':>9}")
    print("-" * 82)

    # 1) BTC — 원본 4h×일봉 골든크로스
    try:
        d1 = load_binance("BTCUSDT", "1d", 3200)
        h4 = load_binance("BTCUSDT", "4h", 1200)
        # 4h 200선을 일봉 인덱스에 리샘플(각 일봉일의 마지막 4h 200MA)
        ma4h = h4["Close"].rolling(200).mean()
        ma4h_daily = ma4h.resample("1D").last().reindex(d1.index).ffill()
        ma_d = d1["Close"].rolling(200).mean()
        above = (ma4h_daily > ma_d)
        cross = list(np.where((above & ~above.shift(1).fillna(False)).values)[0])
        stats(backtest(d1, cross, "BTC"), "BTC 4h×일봉 골든크로스(원본)")
    except Exception as e:
        print(f"BTC 실패: {e}")

    # 2) 주식 — 일봉 50×200 크로스 근사
    for tk, nm in [("QQQ","QQQ"), ("SPY","SPY"), ("^KS11","코스피"), ("005930.KS","삼성전자")]:
        try:
            d = load_yahoo(tk)
            f, s = d["Close"].rolling(50).mean(), d["Close"].rolling(200).mean()
            cross = find_golden_crosses(f, s)
            stats(backtest(d, cross, nm), f"{nm} 일봉 50×200크로스(근사)")
        except Exception as e:
            print(f"{nm} 실패: {e}")

    print("-" * 82)
    print("\n해석:")
    print("  · 기대값 +0.1R 이상이면 = 대시보드 눌림목 신호가 실제로 유효")
    print("  · 마이너스면 = 신호 자체론 엣지 부족(국면필터·종목선정 병행 필요)")
    print("  · 주식은 4h 없어 일봉 50×200 근사 — BTC 원본 결과가 로직 유효성의 핵심")


if __name__ == "__main__":
    main()
