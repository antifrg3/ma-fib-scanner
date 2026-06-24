#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
가치영역 변위 스캘핑 백테스트 (크립토 / 바이낸스)
- 첫 15분 1분봉으로 거래량 프로파일(POC·VAH·VAL) 계산
- 5분봉 종가가 가치영역을 이탈하면 진입, 손절=POC, 익절=2:1
- 수수료·슬리피지 포함(정직한 검증). 결과는 R(리스크 배수) 기준.

실행:
  python backtest_va_scalp.py             # 앵커 00:00 UTC (한국 09:00)
  ANCHOR=ny python backtest_va_scalp.py   # 뉴욕 오픈 09:30 ET (DST 자동)
주의: 샌드박스에선 바이낸스 접속이 막혀 있어 사용자 PC(한국)에서 실행해야 합니다.
"""
import os
import csv
import json
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# ── 설정 ─────────────────────────────────────────────────────────────────
COINS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]
ANCHOR = os.environ.get("ANCHOR", "utc").lower()   # 'utc' | 'ny'
DAYS = int(os.environ.get("DAYS", "90"))           # 백테스트 기간(일)
VA_MIN = 15            # 가치영역 산출 구간(분)
ENTRY_DEADLINE_MIN = 240   # 진입 탐색 마감 (앵커 + 4h)
SESSION_MIN = 480          # 세션 종료 (앵커 + 8h) → 미청산 강제청산
RR = 2.0                   # 손익비 (2:1) — trend 모드에서만 사용
MODE = os.environ.get("MODE", "trend").lower()   # 'trend'(원본) | 'fade'(역방향)
STOP_BUFFER_PCT = float(os.environ.get("STOP_BUF", "0.05"))  # fade 손절 버퍼 %
VALUE_AREA_PCT = 0.70      # 가치영역 = 거래량 70%
PRICE_BINS = 40            # 볼륨 프로파일 가격 빈 수
RISK_PER_TRADE = 100.0     # 1회 리스크($) — 달러 곡선용
FEE_PCT = 0.04             # 편도 수수료 % (선물 테이커 ≈ 0.04%)
SLIPPAGE_PCT = 0.02        # 편도 슬리피지 %
OUT = "va_backtest_out"

BINANCE_BASES = ["https://data-api.binance.vision", "https://api.binance.com"]


# ── 데이터 ───────────────────────────────────────────────────────────────
def fetch_1m(symbol, start_ms, end_ms):
    last_err = None
    for base in BINANCE_BASES:
        try:
            url = (f"{base}/api/v3/klines?symbol={symbol}&interval=1m"
                   f"&startTime={start_ms}&endTime={end_ms}&limit=1000")
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=25) as r:
                data = json.loads(r.read().decode())
            if isinstance(data, list):
                return data
        except Exception as e:
            last_err = e
    raise RuntimeError(f"klines 실패 {symbol}: {last_err}")


def klines_to_df(data):
    rows = [(pd.to_datetime(k[0], unit="ms", utc=True),
             float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])) for k in data]
    return pd.DataFrame(rows, columns=["t", "Open", "High", "Low", "Close", "Volume"]).set_index("t")


# ── 가치영역(볼륨 프로파일) ──────────────────────────────────────────────
def value_area(df15, bins=PRICE_BINS, va_pct=VALUE_AREA_PCT):
    lo, hi = float(df15["Low"].min()), float(df15["High"].max())
    if hi <= lo:
        return None
    edges = np.linspace(lo, hi, bins + 1)
    centers = (edges[:-1] + edges[1:]) / 2
    vol = np.zeros(bins)
    for _, b in df15.iterrows():
        blo, bhi, bv = b["Low"], b["High"], b["Volume"]
        if bhi <= blo:
            i = min(max(np.searchsorted(edges, b["Close"]) - 1, 0), bins - 1)
            vol[i] += bv
            continue
        i0 = min(max(np.searchsorted(edges, blo) - 1, 0), bins - 1)
        i1 = min(max(np.searchsorted(edges, bhi) - 1, 0), bins - 1)
        vol[i0:i1 + 1] += bv / (i1 - i0 + 1)
    poc_i = int(np.argmax(vol))
    total = vol.sum()
    if total <= 0:
        return None
    inc, lo_i, hi_i = vol[poc_i], poc_i, poc_i
    target = total * va_pct
    while inc < target and (lo_i > 0 or hi_i < bins - 1):
        up = vol[hi_i + 1] if hi_i < bins - 1 else -1.0
        dn = vol[lo_i - 1] if lo_i > 0 else -1.0
        if up >= dn:
            hi_i += 1
            inc += vol[hi_i]
        else:
            lo_i -= 1
            inc += vol[lo_i]
    return float(centers[poc_i]), float(edges[hi_i + 1]), float(edges[lo_i])  # POC, VAH, VAL


# ── 하루 백테스트 ────────────────────────────────────────────────────────
def anchor_utc(day, mode):
    if mode == "ny":
        ny = datetime(day.year, day.month, day.day, 9, 30, tzinfo=ZoneInfo("America/New_York"))
        return ny.astimezone(timezone.utc)
    return datetime(day.year, day.month, day.day, 0, 0, tzinfo=timezone.utc)


def backtest_day(symbol, a_utc):
    start_ms = int(a_utc.timestamp() * 1000)
    end_ms = int((a_utc + timedelta(minutes=SESSION_MIN)).timestamp() * 1000)
    df = klines_to_df(fetch_1m(symbol, start_ms, end_ms))
    if len(df) < VA_MIN + 10:
        return None

    va = value_area(df.iloc[:VA_MIN])
    if va is None:
        return None
    poc, vah, val = va

    # 5분봉 종가(앵커 정렬)로 진입 탐색
    five = df.resample("5min", origin=df.index[0]).agg(
        {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}).dropna()
    deadline = a_utc + timedelta(minutes=ENTRY_DEADLINE_MIN)

    disp = None
    for ts, bar in five.iterrows():
        if ts <= a_utc + timedelta(minutes=VA_MIN):
            continue
        if ts > deadline:
            break
        if bar["Close"] > vah:
            disp = ("above", float(bar["Close"]), ts, float(bar["High"]), float(bar["Low"]))
            break
        if bar["Close"] < val:
            disp = ("below", float(bar["Close"]), ts, float(bar["High"]), float(bar["Low"]))
            break
    if disp is None:
        return None
    where, ep, et, bhi, blo = disp

    if MODE == "fade":
        # 가치영역 이탈 → POC로 되돌림에 베팅(역방향). 익절=POC, 손절=이탈 캔들 바깥.
        if where == "above":
            side, target = "short", poc
            stop = bhi * (1 + STOP_BUFFER_PCT / 100)
            risk = stop - ep
        else:
            side, target = "long", poc
            stop = blo * (1 - STOP_BUFFER_PCT / 100)
            risk = ep - stop
    else:
        # 추세(원본): 손절=POC, 익절=2R
        if where == "above":
            side, stop = "long", poc
            risk = ep - stop
            target = ep + RR * risk
        else:
            side, stop = "short", poc
            risk = stop - ep
            target = ep - RR * risk
    if risk <= 0:
        return None

    # 1분봉으로 진입 이후 시뮬레이션
    fwd = df[df.index > et]
    exit_price, outcome = None, None
    for _, b in fwd.iterrows():
        if side == "long":
            if b["Low"] <= stop:            # 손절 우선(보수적)
                exit_price, outcome = stop, "loss"; break
            if b["High"] >= target:
                exit_price, outcome = target, "win"; break
        else:
            if b["High"] >= stop:
                exit_price, outcome = stop, "loss"; break
            if b["Low"] <= target:
                exit_price, outcome = target, "win"; break
    if exit_price is None:                   # 세션 종료까지 미청산 → 종가 청산
        exit_price = float(df["Close"].iloc[-1])
        outcome = "timeout"

    # R 계산(수수료·슬리피지 포함)
    raw = (exit_price - ep) if side == "long" else (ep - exit_price)
    cost = ep * (FEE_PCT + SLIPPAGE_PCT) / 100 * 2     # 진입+청산 양편
    r_mult = (raw - cost) / risk
    return {"date": et.date().isoformat(), "symbol": symbol, "side": side,
            "entry": ep, "stop": stop, "target": target, "exit": exit_price,
            "poc": poc, "vah": vah, "val": val, "outcome": outcome, "R": r_mult}


def backtest(symbol, days, mode):
    today = datetime.now(timezone.utc).date()
    trades = []
    for i in range(days, 0, -1):
        day = today - timedelta(days=i)
        try:
            t = backtest_day(symbol, anchor_utc(day, mode))
            if t:
                trades.append(t)
        except Exception:
            pass
        time.sleep(0.12)
    return trades


# ── 리포트 ───────────────────────────────────────────────────────────────
def stats(trades):
    if not trades:
        return None
    R = np.array([t["R"] for t in trades])
    wins = R > 0
    gross_w = R[R > 0].sum()
    gross_l = -R[R < 0].sum()
    eq = np.cumsum(R)
    peak = np.maximum.accumulate(eq)
    mdd = float((peak - eq).max()) if len(eq) else 0.0
    return {"n": len(R), "win%": 100 * wins.mean(), "sumR": float(R.sum()),
            "avgR": float(R.mean()), "pf": (gross_w / gross_l if gross_l > 0 else float("inf")),
            "mddR": mdd}


def main():
    os.makedirs(OUT, exist_ok=True)
    print(f"=== 백테스트: 모드={MODE.upper()}  앵커={ANCHOR.upper()}  기간={DAYS}일  "
          f"비용=편도 {FEE_PCT+SLIPPAGE_PCT:.2f}% ===\n")
    all_trades, eq_all = [], []
    print(f"{'종목':<10}{'거래':>5}{'승률':>8}{'합계R':>9}{'기대값R':>9}{'PF':>7}{'MDD(R)':>9}")
    for sym in COINS:
        tr = backtest(sym, DAYS, ANCHOR)
        all_trades += tr
        st = stats(tr)
        if st:
            print(f"{sym:<10}{st['n']:>5}{st['win%']:>7.1f}%{st['sumR']:>9.1f}"
                  f"{st['avgR']:>9.2f}{st['pf']:>7.2f}{st['mddR']:>9.1f}")
        else:
            print(f"{sym:<10}{'0':>5}{'—':>8}")

    st = stats(all_trades)
    print("-" * 57)
    if st:
        print(f"{'전체':<10}{st['n']:>5}{st['win%']:>7.1f}%{st['sumR']:>9.1f}"
              f"{st['avgR']:>9.2f}{st['pf']:>7.2f}{st['mddR']:>9.1f}")
        print(f"\n기대값 {st['avgR']:+.2f}R/거래  →  거래당 평균 "
              f"{st['avgR']*RISK_PER_TRADE:+.0f}$ (리스크 {RISK_PER_TRADE:.0f}$ 기준)")
        print("※ 기대값이 0 이하면 비용 포함 시 수익이 안 나는 전략이라는 뜻.")

    # CSV
    if all_trades:
        all_trades.sort(key=lambda t: t["date"])
        with open(os.path.join(OUT, "trades.csv"), "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(all_trades[0].keys()))
            w.writeheader()
            w.writerows(all_trades)
        # 자본곡선(R)
        eq = np.cumsum([t["R"] for t in all_trades])
        plt.figure(figsize=(10, 4.5))
        plt.plot(eq, color="#C8A24B", lw=1.6)
        plt.axhline(0, color="#888", lw=0.8, ls="--")
        plt.title(f"누적 R 자본곡선 — {MODE.upper()} · 앵커 {ANCHOR.upper()} · {len(all_trades)}거래", loc="left")
        plt.xlabel("거래 #"); plt.ylabel("누적 R"); plt.tight_layout()
        plt.savefig(os.path.join(OUT, "equity.png"), dpi=120)
        print(f"\n저장: {OUT}/trades.csv · {OUT}/equity.png")


if __name__ == "__main__":
    main()
