#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
calibrate_assetpick.py — 자산 평가 기준 캘리브레이션
─────────────────────────────────────────────────────────────────────────
문제: ATR%·추세효율의 '좋은 값'이 얼마인지 감으로 정하면 엉터리 등급이 나온다.
해결: 바이낸스 실제 자산들의 분포를 먼저 측정하고, 그 분위수로 기준을 정한다.

실행:
  cd ~/GitHub/ma-fib-scanner
  python3 calibrate_assetpick.py

출력: ATR%·효율의 분위수(10/25/50/75/90%) → 이 값으로 assetpick.py 기준 조정
"""
import json
import urllib.request
import numpy as np
import pandas as pd

import assetpick as ap

BASES = ["https://data-api.binance.vision", "https://api.binance.com"]
TOP_N = 80


def _get(url):
    for b in BASES:
        try:
            req = urllib.request.Request(b + url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15) as r:
                return json.loads(r.read().decode())
        except Exception:
            continue
    return None


def top_symbols(n=TOP_N):
    data = _get("/api/v3/ticker/24hr")
    if not data:
        return []
    STABLE = {"USDT","USDC","BUSD","TUSD","DAI","FDUSD","USDD","USDP","PYUSD","EUR","EURT"}
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
            qv = float(d.get("quoteVolume", 0))
        except (TypeError, ValueError):
            qv = 0.0
        rows.append((s, qv))
    rows.sort(key=lambda x: -x[1])
    return rows[:n]


def klines(symbol, limit=150):
    d = _get(f"/api/v3/klines?symbol={symbol}&interval=1d&limit={limit}")
    if not isinstance(d, list) or len(d) < 60:
        return None
    idx = pd.to_datetime([k[0] for k in d], unit="ms")
    return pd.DataFrame({
        "Open": [float(k[1]) for k in d], "High": [float(k[2]) for k in d],
        "Low": [float(k[3]) for k in d], "Close": [float(k[4]) for k in d],
    }, index=idx)


def main():
    print(f"바이낸스 상위 {TOP_N}개 자산의 특성 분포 측정 중...\n")
    syms = top_symbols()
    if not syms:
        print("❌ 바이낸스 접근 실패")
        return

    rows = []
    for i, (sym, qv) in enumerate(syms, 1):
        df = klines(sym)
        if df is None:
            continue
        a = ap.atr_pct(df)
        e = ap.trend_efficiency(df)
        if a is None or e is None:
            continue
        rows.append({"symbol": sym, "qv": qv, "atr": a, "eff": e})
        if i % 20 == 0:
            print(f"  ...{i}/{len(syms)} (수집 {len(rows)})")

    if not rows:
        print("❌ 데이터 수집 실패")
        return
    df = pd.DataFrame(rows)

    print(f"\n{'='*62}\n측정 완료: {len(df)}개 자산\n{'='*62}")
    for col, label, unit in [("atr", "ATR% (일 평균 진폭)", "%"),
                             ("eff", "추세효율 (30일)", ""),
                             ("qv", "24h 거래대금(백만$)", "M")]:
        v = df[col] / (1e6 if col == "qv" else 1)
        print(f"\n■ {label}")
        for q in [10, 25, 50, 75, 90]:
            print(f"    {q:>2}% 분위: {np.percentile(v, q):8.2f}{unit}")
        print(f"    평균     : {v.mean():8.2f}{unit}")

    print(f"\n{'='*62}\n권장 기준 (이 값을 assetpick.py에 반영)\n{'='*62}")
    a25, a75 = np.percentile(df["atr"], 25), np.percentile(df["atr"], 75)
    e50, e75 = np.percentile(df["eff"], 50), np.percentile(df["eff"], 75)
    e10 = np.percentile(df["eff"], 10)
    print(f"VOL_SWEET = ({a25:.1f}, {a75:.1f})   # 중간 50%를 스윗스팟으로")
    print(f"효율 기준  : 하위10% {e10:.2f}(톱질) · 중앙 {e50:.2f} · 상위25% {e75:.2f}(우수)")
    print(f"  → _score_eff 를 (e - {e10:.2f}) / {e75-e10:.2f} 로 조정 권장")

    print(f"\n{'='*62}\n특성별 상위 자산\n{'='*62}")
    print("\n[추세효율 TOP 10 — 방향성 있게 움직임]")
    for _, r in df.nlargest(10, "eff").iterrows():
        print(f"  {r['symbol']:<12} 효율 {r['eff']:.2f} · ATR {r['atr']:5.1f}% · {r['qv']/1e6:7.0f}M")
    print("\n[톱질 BOTTOM 5 — 방향 없이 흔들림]")
    for _, r in df.nsmallest(5, "eff").iterrows():
        print(f"  {r['symbol']:<12} 효율 {r['eff']:.2f} · ATR {r['atr']:5.1f}% · {r['qv']/1e6:7.0f}M")


if __name__ == "__main__":
    main()
