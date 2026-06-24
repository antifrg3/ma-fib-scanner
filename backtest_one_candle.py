#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
원캔들 단타매법 백테스트 (fade + 필터 2개)
- 첫 15분봉 고가/저가 = 박스
- 필터①: 박스 고저폭 ≥ 일봉 ATR(14) × 33%  (개미털기 인정한 날만)
- 필터②: 90분 내, 박스 밖에서 반전 캔들(망치형/역망치형/장악형)
- 진입: 되돌림 방향, 손절=반전캔들 끝, 익절=박스 반대선(=먼 목표 → 비용 비중↓)
- 비용 포함. fade 백테스트(backtest_va_scalp.py)의 데이터/비용 헬퍼 재사용.

실행:
  python backtest_one_candle.py
  ANCHOR=ny DAYS=120 python backtest_one_candle.py
주의: 바이낸스 접속 되는 환경(한국)에서 실행.
"""
import os
import csv
import json
import time
import urllib.request
from datetime import datetime, timedelta, timezone, time as dtime

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import backtest_va_scalp as base   # fetch/anchor/비용/stats 재사용

# ── 설정 ─────────────────────────────────────────────────────────────────
COINS = os.environ.get("COINS", ",".join([
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT",
    "AVAXUSDT", "LINKUSDT", "TRXUSDT", "DOTUSDT", "LTCUSDT", "BCHUSDT", "NEARUSDT", "APTUSDT",
])).split(",")
ANCHOR = os.environ.get("ANCHOR", "utc").lower()
DAYS = int(os.environ.get("DAYS", "365"))
BOX_MIN = 15               # 박스 = 첫 15분
ATR_LEN = 14
ATR_PCT = 0.33             # 필터①: 박스폭 ≥ ATR×33%
ENTRY_WINDOW_MIN = 90      # 필터②: 90분 골든타임
SESSION_MIN = 480          # 진입 후 이 시간까지 미청산 시 강제청산
HAMMER_RATIO = 2.0         # 꼬리 ≥ 몸통 × 2
STOP_BUF = float(os.environ.get("STOP_BUF", "0.05"))   # 손절 버퍼 %
FEE_PCT, SLIPPAGE_PCT = base.FEE_PCT, base.SLIPPAGE_PCT
RISK_PER_TRADE = base.RISK_PER_TRADE
OUT = "onecandle_out"


def klines(symbol, interval, start_ms, end_ms, limit=1000):
    last = None
    for b in base.BINANCE_BASES:
        try:
            url = (f"{b}/api/v3/klines?symbol={symbol}&interval={interval}"
                   f"&startTime={start_ms}&endTime={end_ms}&limit={limit}")
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=25) as r:
                d = json.loads(r.read().decode())
            if isinstance(d, list):
                return d
        except Exception as e:
            last = e
    raise RuntimeError(f"klines 실패 {symbol} {interval}: {last}")


def load_daily_atr(symbol, first_day, last_day):
    s = datetime.combine(first_day - timedelta(days=ATR_LEN + 12), dtime(0, 0), tzinfo=timezone.utc)
    e = datetime.combine(last_day + timedelta(days=1), dtime(0, 0), tzinfo=timezone.utc)
    df = base.klines_to_df(klines(symbol, "1d", int(s.timestamp() * 1000), int(e.timestamp() * 1000)))
    h, l, c = df["High"], df["Low"], df["Close"]
    pc = c.shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    atr = tr.rolling(ATR_LEN).mean().shift(1)    # 전일까지의 ATR(룩어헤드 방지)
    return {ts.date(): (float(v) if pd.notna(v) else None) for ts, v in atr.items()}


# ── 캔들 패턴 ────────────────────────────────────────────────────────────
def is_hammer(o, h, l, c):
    body = abs(c - o); lower = min(o, c) - l; upper = h - max(o, c)
    return (h - l) > 0 and body > 0 and lower >= HAMMER_RATIO * body and upper <= body

def is_star(o, h, l, c):   # 역망치/슈팅스타
    body = abs(c - o); lower = min(o, c) - l; upper = h - max(o, c)
    return (h - l) > 0 and body > 0 and upper >= HAMMER_RATIO * body and lower <= body

def bull_engulf(p, x):
    return x["Close"] > x["Open"] and p["Close"] < p["Open"] and x["Close"] >= p["Open"] and x["Open"] <= p["Close"]

def bear_engulf(p, x):
    return x["Close"] < x["Open"] and p["Close"] > p["Open"] and x["Open"] >= p["Close"] and x["Close"] <= p["Open"]


# ── 하루 백테스트 ────────────────────────────────────────────────────────
def backtest_day(symbol, a_utc, atr_map):
    start_ms = int(a_utc.timestamp() * 1000)
    end_ms = int((a_utc + timedelta(minutes=SESSION_MIN)).timestamp() * 1000)
    df = base.klines_to_df(klines(symbol, "1m", start_ms, end_ms))
    if len(df) < BOX_MIN + 10:
        return None

    box = df.iloc[:BOX_MIN]
    box_hi, box_lo = float(box["High"].max()), float(box["Low"].min())
    box_range = box_hi - box_lo

    atr = atr_map.get(a_utc.date())
    if not atr or box_range < ATR_PCT * atr:     # 필터① — 개미털기 아닌 날 제외
        return None

    five = df.resample("5min", origin=df.index[0]).agg(
        {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}).dropna()

    setup, prev = None, None
    for ts, b in five.iterrows():
        if ts <= a_utc + timedelta(minutes=BOX_MIN):
            prev = b; continue
        if ts > a_utc + timedelta(minutes=ENTRY_WINDOW_MIN):
            break
        o, h, l, c = float(b["Open"]), float(b["High"]), float(b["Low"]), float(b["Close"])
        if c < box_lo:    # 박스 아래 바깥 → 롱(되돌림)
            if is_hammer(o, h, l, c) or (prev is not None and bull_engulf(prev, b)):
                setup = ("long", c, ts, l, h); break
        if c > box_hi:    # 박스 위 바깥 → 숏(되돌림)
            if is_star(o, h, l, c) or (prev is not None and bear_engulf(prev, b)):
                setup = ("short", c, ts, l, h); break
        prev = b
    if setup is None:
        return None
    side, ep, et, clow, chigh = setup

    if side == "long":
        stop = clow * (1 - STOP_BUF / 100); target = box_hi; risk = ep - stop
    else:
        stop = chigh * (1 + STOP_BUF / 100); target = box_lo; risk = stop - ep
    if risk <= 0:
        return None

    fwd = df[df.index > et]
    exit_price, outcome = None, None
    for _, b in fwd.iterrows():
        if side == "long":
            if b["Low"] <= stop:
                exit_price, outcome = stop, "loss"; break
            if b["High"] >= target:
                exit_price, outcome = target, "win"; break
        else:
            if b["High"] >= stop:
                exit_price, outcome = stop, "loss"; break
            if b["Low"] <= target:
                exit_price, outcome = target, "win"; break
    if exit_price is None:
        exit_price = float(df["Close"].iloc[-1]); outcome = "timeout"

    raw = (exit_price - ep) if side == "long" else (ep - exit_price)
    cost = ep * (FEE_PCT + SLIPPAGE_PCT) / 100 * 2
    r_mult = (raw - cost) / risk
    return {"date": et.date().isoformat(), "symbol": symbol, "side": side,
            "entry": ep, "stop": stop, "target": target, "exit": exit_price,
            "box_hi": box_hi, "box_lo": box_lo, "rr_planned": (target - ep) / risk if side == "long" else (ep - target) / risk,
            "outcome": outcome, "R": r_mult}


def backtest(symbol, days, mode):
    today = datetime.now(timezone.utc).date()
    first = today - timedelta(days=days)
    atr_map = load_daily_atr(symbol, first, today)
    trades = []
    for i in range(days, 0, -1):
        day = today - timedelta(days=i)
        try:
            t = backtest_day(symbol, base.anchor_utc(day, mode), atr_map)
            if t:
                trades.append(t)
        except Exception:
            pass
        time.sleep(0.12)
    return trades


def main():
    os.makedirs(OUT, exist_ok=True)
    print(f"=== 원캔들 백테스트: 앵커={ANCHOR.upper()}  기간={DAYS}일  "
          f"필터=ATR×{ATR_PCT:.0%}+반전캔들  비용=편도 {FEE_PCT+SLIPPAGE_PCT:.2f}% ===\n")
    all_t = []
    print(f"{'종목':<10}{'거래':>5}{'승률':>8}{'합계R':>9}{'기대값R':>9}{'PF':>7}{'평균RR':>8}{'MDD(R)':>9}")
    for sym in COINS:
        tr = backtest(sym, DAYS, ANCHOR)
        all_t += tr
        st = base.stats(tr)
        if st:
            rr = np.mean([t["rr_planned"] for t in tr])
            print(f"{sym:<10}{st['n']:>5}{st['win%']:>7.1f}%{st['sumR']:>9.1f}"
                  f"{st['avgR']:>9.2f}{st['pf']:>7.2f}{rr:>8.1f}{st['mddR']:>9.1f}")
        else:
            print(f"{sym:<10}{'0':>5}{'  진입無':>8}")
    st = base.stats(all_t)
    print("-" * 65)
    if st:
        rr = np.mean([t["rr_planned"] for t in all_t])
        print(f"{'전체':<10}{st['n']:>5}{st['win%']:>7.1f}%{st['sumR']:>9.1f}"
              f"{st['avgR']:>9.2f}{st['pf']:>7.2f}{rr:>8.1f}{st['mddR']:>9.1f}")
        print(f"\n기대값 {st['avgR']:+.2f}R/거래 → 거래당 평균 {st['avgR']*RISK_PER_TRADE:+.0f}$ "
              f"(리스크 {RISK_PER_TRADE:.0f}$). fade 기준선 −0.76R 와 비교.")
        n = st["n"]
        if n < 30:
            print(f"⚠️ 표본 {n}건 — 통계적으로 신뢰 불가. 부호와 무관하게 '우연' 가능성이 큼. 판단 보류.")
        elif st["avgR"] > 0.1:
            print(f"✅ 표본 {n}건에서 기대값 {st['avgR']:+.2f}R — 의미 있는 양(+). 추가 검증(다른 기간) 후 봇 고려.")
        else:
            print(f"❌ 표본 {n}건에서도 기대값 {st['avgR']:+.2f}R — 필터 얹어도 비용 못 이김. 단타 종료 결론.")
    if all_t:
        all_t.sort(key=lambda t: t["date"])
        with open(os.path.join(OUT, "trades.csv"), "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(all_t[0].keys())); w.writeheader(); w.writerows(all_t)
        eq = np.cumsum([t["R"] for t in all_t])
        plt.figure(figsize=(10, 4.5)); plt.plot(eq, color="#5FB89B", lw=1.6)
        plt.axhline(0, color="#888", lw=0.8, ls="--")
        plt.title(f"원캔들(필터) 누적 R — 앵커 {ANCHOR.upper()} · {len(all_t)}거래", loc="left")
        plt.xlabel("거래 #"); plt.ylabel("누적 R"); plt.tight_layout()
        plt.savefig(os.path.join(OUT, "equity.png"), dpi=120)
        print(f"저장: {OUT}/trades.csv · {OUT}/equity.png")


if __name__ == "__main__":
    main()
