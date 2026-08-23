#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
calibrate_setup.py — 셋업 스크리너 기준값 검증
─────────────────────────────────────────────────────────────────────────
감으로 정한 기준(거래량 1.15배, 상승/하락 거래량비 1.0 등)이 실제 시장 분포에서
말이 되는지 확인한다. 너무 빡세면 아무것도 안 걸리고, 너무 헐거우면 의미가 없다.

실행:
  cd ~/GitHub/ma-fib-scanner
  python3 calibrate_setup.py
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
        s = d.get("symbol","")
        if not s.endswith("USDT"):
            continue
        base = s[:-4]
        if base in STABLE or base in WRAP or base.endswith(("UP","DOWN","BULL","BEAR")):
            continue
        try:
            rows.append((s, float(d.get("quoteVolume", 0))))
        except (TypeError, ValueError):
            pass
    rows.sort(key=lambda x: -x[1])
    return [s for s, _ in rows[:n]]


def klines(symbol, limit=400):
    d = _get(f"/api/v3/klines?symbol={symbol}&interval=1d&limit={limit}")
    if not isinstance(d, list) or len(d) < 220:
        return None
    idx = pd.to_datetime([k[0] for k in d], unit="ms")
    return pd.DataFrame({
        "Open":[float(k[1]) for k in d], "High":[float(k[2]) for k in d],
        "Low":[float(k[3]) for k in d], "Close":[float(k[4]) for k in d],
        "Volume":[float(k[5]) for k in d],
    }, index=idx)


def stock_frames():
    """미국·한국 유니버스 일부를 야후로."""
    out = {}
    try:
        import yfinance as yf
    except ImportError:
        print("  (yfinance 없음 — 주식 생략)")
        return out
    syms = []
    for path, mkt in [("tickers_us.txt","미국"), ("tickers_kr.txt","한국")]:
        try:
            with open(path, encoding="utf-8") as f:
                got = [l.split("#")[0].strip() for l in f]
                syms += [(x, mkt) for x in got if x][:40]
        except FileNotFoundError:
            pass
    for sym, mkt in syms:
        try:
            df = yf.download(sym, period="2y", progress=False, auto_adjust=True)
            if df is None or df.empty or len(df) < 220:
                continue
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            out[(sym, mkt)] = df
        except Exception:
            continue
    return out


def main():
    print("셋업 스크리너 기준값 검증 — 실제 분포 측정\n")
    rows = []

    print("크립토 수집 중...")
    for i, sym in enumerate(top_symbols(60), 1):
        df = klines(sym)
        if df is None:
            continue
        r = ss.evaluate(sym, df, "크립토")
        if r:
            rows.append(r)
        if i % 20 == 0:
            print(f"  ...{i} (수집 {len(rows)})")

    print("주식 수집 중...")
    for (sym, mkt), df in stock_frames().items():
        r = ss.evaluate(sym, df, mkt)
        if r:
            rows.append(r)

    if not rows:
        print("❌ 데이터 수집 실패")
        return

    n = len(rows)
    print(f"\n{'='*66}\n측정 완료: {n}개 종목\n{'='*66}")

    # 조건별 통과율 (7조건 각각)
    labels = [c[0] for c in rows[0].conds]
    print(f"\n■ 조건별 통과율")
    for i, lab in enumerate(labels):
        cnt = sum(1 for r in rows if r.conds[i][1])
        print(f"    {lab:<26} {cnt:>3}/{n} ({cnt/n*100:>5.1f}%)")

    # 충족 개수 분포
    print(f"\n■ 충족 개수 분포")
    for k in range(8):
        cnt = sum(1 for r in rows if r.passed_count == k)
        bar = "█" * int(cnt / max(n, 1) * 40)
        print(f"    {k}/7 : {cnt:>3}개 {bar}")

    # 통과 기준별 종목 수
    print(f"\n■ 기준별 통과 종목 수")
    for k in [5, 6, 7]:
        cnt = sum(1 for r in rows if r.passed_count >= k)
        print(f"    {k}개 이상: {cnt:>3}개 ({cnt/n*100:.1f}%)")

    # 트리거 발생
    trig_all = [t for r in rows for t in r.triggers]
    print(f"\n■ 트리거 발생")
    for t in ["🚀 전고점 돌파", "🏔️ 52주 신고가", "💥 횡보 후 돌파"]:
        print(f"    {t:<16} {trig_all.count(t):>3}건")

    # 주요 수치 분포
    for attr, lab in [("vol_ratio","거래량 비율(최근20/직전60)"),
                      ("updown_ratio","상승/하락 거래량비"),
                      ("gain_from_low","52주 저가 대비(%)"),
                      ("dist_from_high","52주 고가 대비(%)")]:
        vals = [getattr(r, attr) for r in rows
                if getattr(r, attr) not in (None, 0) and np.isfinite(getattr(r, attr))]
        if not vals:
            continue
        print(f"\n■ {lab}")
        for q in [25, 50, 75, 90]:
            print(f"    {q:>2}% 분위: {np.percentile(vals, q):8.2f}")

    # 상위 종목
    top = sorted(rows, key=lambda r: -r.score)[:15]
    print(f"\n{'='*66}\n점수 상위 15\n{'='*66}")
    for r in top:
        tg = " ".join(r.triggers)
        print(f"  {r.ticker:<12}[{r.market:<4}] {r.passed_count}/7 "
              f"점수{r.score:>7.1f} · 저가+{r.gain_from_low:>3.0f}% "
              f"고가-{r.dist_from_high:>3.0f}% {tg}")

    print(f"\n{'='*66}\n해석\n{'='*66}")
    p6 = sum(1 for r in rows if r.passed_count >= 6)
    if p6 == 0:
        print("  6/7 통과 0건 — 기준이 엄격하거나 지금 시장에 추세 종목이 없음")
        print("  → 5/7로 낮추거나, 실패율 높은 조건을 확인해 조정 검토")
    elif p6 > n * 0.4:
        print(f"  6/7 통과가 {p6/n*100:.0f}%로 많음 — 변별력이 약할 수 있음")
        print("  → 7/7로 올리거나 조건을 더 엄격히")
    else:
        print(f"  6/7 통과 {p6}개({p6/n*100:.0f}%) — 적정 수준으로 보임")


if __name__ == "__main__":
    main()
