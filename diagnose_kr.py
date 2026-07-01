#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
한국 눌림목 미노출 원인 진단 — 단계별 깔때기(funnel) 추적
──────────────────────────────────────────────────────────────────
대시보드 실제 로직(fetch_daily / fetch_intraday_4h)을 그대로 써서,
미국 vs 한국을 나란히 놓고 각 단계에서 몇 종목이 탈락하는지 센다.

깔때기 단계:
  1. 일봉 데이터 수신 (210봉 이상)
  2. 4시간봉 수신 (1h→4h 리샘플 성공)  ← 야후 한국 데이터의 유력 병목
  3. 4h 200선 × 일봉 200선 골든크로스가 '최근 120일 내' 존재
  4. (참고) 현재가가 되돌림 0.382~0.618 구간

각 단계 통과 수를 미국/한국 비교 → 어디서 한국이 막히는지 즉시 판별.

실행:
  cd ~/GitHub/ma-fib-scanner
  python3 diagnose_kr.py
(같은 폴더의 ma_fib_scanner.py, tickers_*.txt 사용. yfinance 필요.)
"""
import warnings
warnings.filterwarnings("ignore")
import os
import sys

# 대시보드 로직 재사용
import ma_fib_scanner as s

GC_LOOKBACK = 120


def read_universe(path, limit=None):
    if not os.path.exists(path):
        return []
    out = []
    for line in open(path, encoding="utf-8"):
        t = line.split("#")[0].strip()
        if t:
            out.append(t)
    return out[:limit] if limit else out


def golden_cross_recent(daily, four):
    """4h 200선이 일봉 200선을 최근 GC_LOOKBACK일 내 상향돌파했는지."""
    try:
        ma_d = daily["Close"].rolling(200).mean()
        ma_4 = four["Close"].rolling(200).mean()
        # 4h 200선을 일봉에 정렬
        ma_4_daily = ma_4.resample("1D").last().reindex(daily.index).ffill()
        above = ma_4_daily > ma_d
        cross = above & (~above.shift(1).fillna(False))
        cross_idx = daily.index[cross.fillna(False)]
        if len(cross_idx) == 0:
            return False, None
        cutoff = daily.index[-min(GC_LOOKBACK, len(daily))]
        recent = cross_idx[cross_idx >= cutoff]
        return (len(recent) > 0), (recent[-1].date().isoformat() if len(recent) else
                                   cross_idx[-1].date().isoformat())
    except Exception:
        return False, None


def diagnose(label, path, limit=None):
    syms = read_universe(path, limit)
    n = len(syms)
    print(f"\n{'='*68}\n{label}  (유니버스 {n}종목{' · 앞 '+str(limit)+'개만' if limit else ''})\n{'='*68}")
    cnt = {"daily": 0, "four": 0, "gc": 0, "no_daily": [], "no_four": [], "gc_dates": []}
    for i, t in enumerate(syms):
        # 1) 일봉
        try:
            daily = s.fetch_daily(t, "2y")
        except Exception:
            daily = None
        if daily is None or len(daily) < 210:
            cnt["no_daily"].append(t)
            continue
        cnt["daily"] += 1
        # 2) 4h
        four = s.fetch_intraday_4h(t)
        if four is None or len(four) < 200:
            cnt["no_four"].append(t)
            continue
        cnt["four"] += 1
        # 3) 골든크로스 최근
        gc, gd = golden_cross_recent(daily, four)
        if gc:
            cnt["gc"] += 1
            cnt["gc_dates"].append((t, gd))
        if (i + 1) % 15 == 0:
            print(f"  ...{i+1}/{n} (일봉 {cnt['daily']} · 4h {cnt['four']} · 크로스 {cnt['gc']})")

    print(f"\n── {label} 깔때기 ──")
    print(f"  전체 종목            : {n}")
    print(f"  1) 일봉 수신(210봉+)  : {cnt['daily']:>3}  (실패 {len(cnt['no_daily'])})")
    print(f"  2) 4h 리샘플 성공     : {cnt['four']:>3}  (실패 {len(cnt['no_four'])})  ← 야후 한국 병목 의심")
    print(f"  3) 최근 골든크로스    : {cnt['gc']:>3}  (최근 {GC_LOOKBACK}일 내)")
    if cnt["no_four"]:
        ex = ", ".join(cnt["no_four"][:8])
        print(f"     · 4h 실패 예시: {ex}{' ...' if len(cnt['no_four'])>8 else ''}")
    if cnt["gc_dates"]:
        ex = ", ".join(f"{t}({d})" for t, d in cnt["gc_dates"][:6])
        print(f"     · 최근 크로스 예시: {ex}")
    return cnt


def main():
    print("한국 눌림목 미노출 원인 진단 — 미국 vs 한국 깔때기 비교")
    print("(대시보드 fetch_daily / fetch_intraday_4h 그대로 사용)")
    # 시간 절약 위해 앞 25개씩만(원하면 limit 제거)
    lim = int(sys.argv[1]) if len(sys.argv) > 1 else 25
    us = diagnose("미국(나스닥100)", "tickers_us.txt", lim)
    kr = diagnose("한국(코스피)", "tickers_kr.txt", lim)

    print(f"\n{'='*68}\n진단 결론\n{'='*68}")
    def pct(a, b): return f"{a/b*100:.0f}%" if b else "—"
    print(f"{'단계':<22}{'미국':>10}{'한국':>10}")
    print("-" * 44)
    print(f"{'일봉 수신률':<22}{pct(us['daily'], lim):>10}{pct(kr['daily'], lim):>10}")
    print(f"{'4h 리샘플 성공률':<20}{pct(us['four'], max(us['daily'],1)):>10}{pct(kr['four'], max(kr['daily'],1)):>10}")
    print(f"{'크로스 발생(4h성공중)':<19}{pct(us['gc'], max(us['four'],1)):>10}{pct(kr['gc'], max(kr['four'],1)):>10}")
    print()
    # 자동 해석
    if kr["daily"] < us["daily"] * 0.7:
        print("→ 원인: 한국 '일봉' 수신부터 실패 많음. 야후 한국 데이터 자체가 불안정.")
    elif kr["four"] < max(kr["daily"], 1) * 0.5:
        print("→ 원인 확정: 한국 '4h 리샘플' 실패가 병목. 야후가 한국 1h 데이터를 잘 안 줌.")
        print("  → 눌림목은 4h 골든크로스가 필수라, 4h 없으면 종목 통째로 스킵됨.")
        print("  → 해결책: (A)한국은 4h 대신 일봉 크로스로 완화, (B)토스 API로 4h 확보.")
    elif kr["gc"] < max(kr["four"], 1) * 0.15:
        print("→ 원인: 데이터는 정상인데 '최근 골든크로스'가 적음(정상 현상).")
        print("  → 한국 종목들이 이미 오래전 크로스(120일 초과)라 눌림목 대상이 아님. 버그 아님.")
    else:
        print("→ 데이터·크로스 모두 정상 범위. 눌림 구간(0.382~0.618) 진입 타이밍 문제일 수 있음.")
    print(f"{'='*68}")


if __name__ == "__main__":
    main()
