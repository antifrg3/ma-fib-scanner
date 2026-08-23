#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sweep_triggers.py — 트리거 기준 민감도 측정
─────────────────────────────────────────────────────────────────────────
"엄격 vs 완화가 몇 개 차이인가"를 실제 데이터로 답한다.
장대양봉 배수 · 거래량 배수 · 횡보 폭을 바꿔가며 잡히는 종목 수를 센다.

실행:
  cd ~/GitHub/ma-fib-scanner
  python3 sweep_triggers.py
"""
import json
import urllib.request
import numpy as np
import pandas as pd

import setup_screen as ss

BASES = ["https://data-api.binance.vision", "https://api.binance.com"]


def _get(path):
    for b in BASES:
        try:
            req = urllib.request.Request(b + path, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15) as r:
                return json.loads(r.read().decode())
        except Exception:
            continue
    return None


def top_symbols(n=60):
    data = _get("/api/v3/ticker/24hr")
    if not data:
        return []
    STABLE = {"USDT","USDC","BUSD","TUSD","DAI","FDUSD","USDD","USDP","PYUSD","EUR"}
    WRAP = {"WBTC","WETH","WBETH","STETH","WSTETH","CBETH","RETH","BETH","WBNB"}
    rows = []
    for d in data:
        s = d.get("symbol", "")
        if not s.endswith("USDT"):
            continue
        b = s[:-4]
        if b in STABLE or b in WRAP or b.endswith(("UP","DOWN","BULL","BEAR")):
            continue
        try:
            rows.append((s, float(d.get("quoteVolume", 0))))
        except (TypeError, ValueError):
            pass
    rows.sort(key=lambda x: -x[1])
    return [s for s, _ in rows[:n]]


def klines(symbol, limit=400):
    d = _get(f"/api/v3/klines?symbol={symbol}&interval=1d&limit={limit}")
    if not isinstance(d, list) or len(d) < 230:
        return None
    idx = pd.to_datetime([k[0] for k in d], unit="ms")
    return pd.DataFrame({
        "Open":[float(k[1]) for k in d], "High":[float(k[2]) for k in d],
        "Low":[float(k[3]) for k in d], "Close":[float(k[4]) for k in d],
        "Volume":[float(k[5]) for k in d],
    }, index=idx)


def stock_frames(limit_each=40):
    out = {}
    try:
        import yfinance as yf
    except ImportError:
        return out
    for path, mkt in [("tickers_us.txt","미국"), ("tickers_kr.txt","한국")]:
        try:
            with open(path, encoding="utf-8") as f:
                syms = [l.split("#")[0].strip() for l in f]
                syms = [x for x in syms if x][:limit_each]
        except FileNotFoundError:
            continue
        for sym in syms:
            try:
                df = yf.download(sym, period="2y", progress=False, auto_adjust=True)
                if df is None or df.empty or len(df) < 230:
                    continue
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                out[(sym, mkt)] = df
            except Exception:
                continue
    return out


def count_triggers(frames, body_mult, vol_mult, tight_range, tight_len=15,
                   breakout_lb=60):
    """주어진 기준으로 트리거별 발생 종목 수."""
    n_break = n_high = n_tight = 0
    hits = {"break": [], "high": [], "tight": []}
    for (sym, _mkt), df in frames.items():
        c, o, h, l, v = df["Close"], df["Open"], df["High"], df["Low"], df["Volume"]
        body = (c - o).abs()
        body_avg = float(body.tail(50).mean())
        last_body = float(body.iloc[-1])
        last_up = float(c.iloc[-1]) > float(o.iloc[-1])
        vavg = float(v.rolling(50).mean().iloc[-1])
        last_vol = float(v.iloc[-1])
        price = float(c.iloc[-1])

        big_candle = last_up and body_avg > 0 and last_body >= body_avg * body_mult
        big_vol = vavg > 0 and last_vol >= vavg * vol_mult

        prior_high = float(h.iloc[-(breakout_lb + 1):-1].max())
        if big_candle and big_vol and price > prior_high:
            n_break += 1
            hits["break"].append(sym)

        hi52 = float(h.tail(252).max())
        if price >= hi52 * 0.999:
            n_high += 1
            hits["high"].append(sym)

        tw = df.iloc[-(tight_len + 1):-1]
        if len(tw) >= tight_len:
            t_hi, t_lo = float(tw["High"].max()), float(tw["Low"].min())
            if t_lo > 0 and (t_hi - t_lo) / t_lo <= tight_range:
                if big_candle and big_vol:
                    n_tight += 1
                    hits["tight"].append(sym)
    return n_break, n_high, n_tight, hits


def main():
    print("트리거 기준 민감도 측정 — 데이터 수집 중...\n")
    frames = {}
    for i, sym in enumerate(top_symbols(60), 1):
        df = klines(sym)
        if df is not None:
            frames[(sym, "크립토")] = df
        if i % 20 == 0:
            print(f"  크립토 ...{i} (수집 {len(frames)})")
    frames.update(stock_frames())
    n = len(frames)
    print(f"\n총 {n}개 종목 수집 완료\n")
    if n == 0:
        print("❌ 수집 실패")
        return

    print("=" * 70)
    print("① 전고점 돌파 장대양봉 — 몸통 배수 × 거래량 배수")
    print("=" * 70)
    header = "몸통 \\ 거래량"
    print(f"{header:<14}" + "".join(f"{v:>10.1f}배" for v in [1.2, 1.5, 2.0]))
    print("-" * 70)
    for bm in [1.2, 1.5, 2.0]:
        line = f"{bm:>8.1f}배   "
        for vm in [1.2, 1.5, 2.0]:
            nb, _, _, _ = count_triggers(frames, bm, vm, 0.10)
            line += f"{nb:>10}개"
        print(line)

    print("\n" + "=" * 70)
    print("② 횡보 후 돌파 — 횡보 폭 기준별 (몸통 1.5배·거래량 1.5배 고정)")
    print("=" * 70)
    for tr in [0.08, 0.10, 0.15, 0.20, 0.25]:
        _, _, nt, hits = count_triggers(frames, 1.5, 1.5, tr)
        names = ", ".join(hits["tight"][:5])
        print(f"  변동폭 {tr*100:>4.0f}% 이내 → {nt:>3}개  {names}")

    print("\n" + "=" * 70)
    print("③ 완화 조합 — 몸통 1.2 · 거래량 1.2 · 횡보 20%")
    print("=" * 70)
    nb2, nh2, nt2, hits2 = count_triggers(frames, 1.2, 1.2, 0.20)
    print(f"  🚀 전고점 돌파 {nb2:>3}개  {', '.join(hits2['break'][:6])}")
    print(f"  🏔️ 52주 신고가 {nh2:>3}개  {', '.join(hits2['high'][:6])}")
    print(f"  💥 횡보 후 돌파 {nt2:>3}개  {', '.join(hits2['tight'][:6])}")

    print("\n" + "=" * 70)
    print("④ 현재(엄격) 조합 — 몸통 1.5 · 거래량 1.5 · 횡보 10%")
    print("=" * 70)
    nb1, nh1, nt1, hits1 = count_triggers(frames, 1.5, 1.5, 0.10)
    print(f"  🚀 전고점 돌파 {nb1:>3}개  {', '.join(hits1['break'][:6])}")
    print(f"  🏔️ 52주 신고가 {nh1:>3}개  {', '.join(hits1['high'][:6])}")
    print(f"  💥 횡보 후 돌파 {nt1:>3}개  {', '.join(hits1['tight'][:6])}")

    print(f"\n{'='*70}\n요약: 엄격 → 완화 시 차이\n{'='*70}")
    print(f"  전고점 돌파 : {nb1}개 → {nb2}개  ({nb2-nb1:+d})")
    print(f"  횡보 후 돌파: {nt1}개 → {nt2}개  ({nt2-nt1:+d})")
    print(f"  (신고가는 기준 무관 — {nh1}개 고정)")
    print(f"\n  전체 {n}개 중 비율: 엄격 {(nb1+nt1)/n*100:.1f}% · 완화 {(nb2+nt2)/n*100:.1f}%")


if __name__ == "__main__":
    main()
