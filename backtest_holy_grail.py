#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
홀리 그레일(라쉬케) 백테스트 — 크립토 일봉.
진입: ADX(14)≥30 상승추세에서 가격이 20-EMA로 눌림(2% 이내).
청산 2모드(EXIT 환경변수):
  target = 고정 목표(최근 20일 스윙 고점) / 손절(최근 3일 저점)
  trail  = 20-EMA 트레일링(종가가 20-EMA 이탈 시 청산) / 손절 동일
비용(수수료+슬리피지) 포함. 결과는 R 기준. 대시보드 holy_grail 로직과 규칙 일치.

실행:
  python backtest_holy_grail.py              # EXIT=target
  EXIT=trail python backtest_holy_grail.py
  DAYS=1095 python backtest_holy_grail.py    # 3년
주의: 바이낸스 접속 되는 환경(한국)에서 실행.
"""
import os
import csv
import json
import time
import urllib.request
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import backtest_va_scalp as base   # klines_to_df, 비용, stats 재사용

COINS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
         "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "LTCUSDT"]
EXIT = os.environ.get("EXIT", "target").lower()   # 'target' | 'trail'
DAYS = int(os.environ.get("DAYS", "730"))
ADX_MIN = 30
NEAR = 0.02            # 20-EMA 2% 이내 = 눌림
FEE_PCT, SLIPPAGE_PCT = base.FEE_PCT, base.SLIPPAGE_PCT
RISK_PER_TRADE = base.RISK_PER_TRADE
OUT = "holygrail_out"


def klines_daily(symbol, days):
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days + 80)     # 지표 워밍업 여유
    url = (f"{base.BINANCE_BASES[0]}/api/v3/klines?symbol={symbol}&interval=1d"
           f"&startTime={int(start.timestamp()*1000)}&endTime={int(end.timestamp()*1000)}&limit=1000")
    last = None
    for b in base.BINANCE_BASES:
        try:
            u = url.replace(base.BINANCE_BASES[0], b)
            req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=25) as r:
                d = json.loads(r.read().decode())
            if isinstance(d, list):
                return base.klines_to_df(d)
        except Exception as e:
            last = e
    raise RuntimeError(f"일봉 klines 실패 {symbol}: {last}")


def _adx(df, n=14):
    h, l, c = df["High"], df["Low"], df["Close"]
    up, dn = h.diff(), -l.diff()
    pdm = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), index=df.index)
    mdm = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), index=df.index)
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / n, adjust=False).mean()
    pdi = 100 * pdm.ewm(alpha=1 / n, adjust=False).mean() / atr
    mdi = 100 * mdm.ewm(alpha=1 / n, adjust=False).mean() / atr
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return dx.ewm(alpha=1 / n, adjust=False).mean()


def backtest_symbol(symbol, days):
    df = klines_daily(symbol, days)
    if len(df) < 80:
        return []
    c, h, l, o = df["Close"], df["High"], df["Low"], df["Open"]
    ema20 = c.ewm(span=20, adjust=False).mean()
    ema50 = c.ewm(span=50, adjust=False).mean()
    adx = _adx(df)
    n = len(df)
    trades = []
    i = 55
    while i < n - 1:
        # 진입 조건 (봉 i 종가 기준)
        entry_ok = (adx.iloc[i] >= ADX_MIN
                    and ema20.iloc[i] > ema20.iloc[i - 5]
                    and c.iloc[i] > ema50.iloc[i]
                    and abs(c.iloc[i] / ema20.iloc[i] - 1) <= NEAR)
        if not entry_ok:
            i += 1
            continue
        ep = float(o.iloc[i + 1])                       # 다음 봉 시가 진입
        stop = float(l.iloc[i - 2:i + 1].min())         # 최근 3일 저점
        if ep <= stop:
            i += 1
            continue
        risk = ep - stop
        target = float(h.iloc[i - 19:i + 1].max()) if EXIT == "target" else None

        exit_price, outcome, j = None, None, i + 1
        while j < n:
            if l.iloc[j] <= stop:                       # 손절 우선(보수적)
                exit_price, outcome = stop, "loss"; break
            if EXIT == "target":
                if h.iloc[j] >= target:
                    exit_price, outcome = target, "win"; break
                if c.iloc[j] < ema20.iloc[j]:           # 추세 무효화 → 종가 청산
                    exit_price, outcome = float(c.iloc[j]), "be"; break
            else:  # trail
                if c.iloc[j] < ema20.iloc[j]:           # 20-EMA 이탈 트레일 청산
                    exit_price, outcome = float(c.iloc[j]), ("win" if c.iloc[j] > ep else "loss"); break
            j += 1
        if exit_price is None:
            exit_price, outcome, j = float(c.iloc[-1]), "open_end", n - 1

        raw = exit_price - ep
        cost = ep * (FEE_PCT + SLIPPAGE_PCT) / 100 * 2
        r_mult = (raw - cost) / risk
        rr = (target - ep) / risk if (EXIT == "target" and target) else (raw / risk)
        trades.append({"date": df.index[i + 1].date().isoformat(), "symbol": symbol,
                       "entry": ep, "stop": stop, "target": target, "exit": exit_price,
                       "adx": float(adx.iloc[i]), "outcome": outcome,
                       "rr_planned": rr, "R": r_mult})
        i = j + 1                                        # 청산 다음 봉부터 재탐색
    return trades


def main():
    os.makedirs(OUT, exist_ok=True)
    print(f"=== 홀리그레일 백테스트: 청산={EXIT.upper()}  기간={DAYS}일  "
          f"진입=ADX≥{ADX_MIN}+20EMA눌림  비용=편도 {FEE_PCT+SLIPPAGE_PCT:.2f}% ===\n")
    all_t = []
    print(f"{'종목':<10}{'거래':>5}{'승률':>8}{'합계R':>9}{'기대값R':>9}{'PF':>7}{'평균RR':>8}{'MDD(R)':>9}")
    for sym in COINS:
        try:
            tr = backtest_symbol(sym, DAYS)
        except Exception as e:
            print(f"{sym:<10} 에러: {e}"); continue
        all_t += tr
        st = base.stats(tr)
        if st:
            rr = np.mean([t["rr_planned"] for t in tr])
            print(f"{sym:<10}{st['n']:>5}{st['win%']:>7.1f}%{st['sumR']:>9.1f}"
                  f"{st['avgR']:>9.2f}{st['pf']:>7.2f}{rr:>8.1f}{st['mddR']:>9.1f}")
        else:
            print(f"{sym:<10}{'0':>5}{'  진입無':>8}")
        time.sleep(0.15)

    st = base.stats(all_t)
    print("-" * 65)
    if st:
        rr = np.mean([t["rr_planned"] for t in all_t])
        print(f"{'전체':<10}{st['n']:>5}{st['win%']:>7.1f}%{st['sumR']:>9.1f}"
              f"{st['avgR']:>9.2f}{st['pf']:>7.2f}{rr:>8.1f}{st['mddR']:>9.1f}")
        print(f"\n기대값 {st['avgR']:+.2f}R/거래 → 거래당 평균 {st['avgR']*RISK_PER_TRADE:+.0f}$ "
              f"(리스크 {RISK_PER_TRADE:.0f}$).")
        n = st["n"]
        if n < 30:
            print(f"⚠️ 표본 {n}건 — 통계적으로 신뢰 부족. 기간(DAYS) 늘려 재확인.")
        elif st["avgR"] > 0.1:
            print(f"✅ 표본 {n}건에서 기대값 {st['avgR']:+.2f}R — 유의미한 +. 다른 기간 재검증 후 알림봇 고려.")
        else:
            print(f"❌ 표본 {n}건에서도 기대값 {st['avgR']:+.2f}R — 비용 못 이김.")

    if all_t:
        all_t.sort(key=lambda t: t["date"])
        with open(os.path.join(OUT, f"trades_{EXIT}.csv"), "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(all_t[0].keys())); w.writeheader(); w.writerows(all_t)
        eq = np.cumsum([t["R"] for t in all_t])
        plt.figure(figsize=(10, 4.5)); plt.plot(eq, color="#5FB89B", lw=1.6)
        plt.axhline(0, color="#888", lw=0.8, ls="--")
        plt.title(f"홀리그레일 누적 R — 청산 {EXIT.upper()} · {len(all_t)}거래", loc="left")
        plt.xlabel("거래 #"); plt.ylabel("누적 R"); plt.tight_layout()
        plt.savefig(os.path.join(OUT, f"equity_{EXIT}.png"), dpi=120)
        print(f"저장: {OUT}/trades_{EXIT}.csv · {OUT}/equity_{EXIT}.png")


if __name__ == "__main__":
    main()
