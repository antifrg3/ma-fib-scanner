#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
추세추종 이동평균 길이 최적화 스윕 — 자산별 최적 시간봉/길이 찾기
──────────────────────────────────────────────────────────────────
질문: BTC·미국주식·코스피에서 추세추종은 어느 이평 길이가 최적인가?

방식 2가지 비교:
  · 단순(price>MA): 종가가 N일선 위면 보유, 아래면 현금
  · 크로스(fast>slow): 단기선이 장기선 위면 보유

자산 3종:
  · BTC   → 바이낸스 일봉
  · 미국  → 야후 (QQQ, SPY)
  · 코스피 → 야후 (^KS11, 005930.KS 삼성전자)

비용: 거래마다 왕복 0.1%(주식/BTC 현물 보수적). 현금구간 금리 0.
지표: CAGR·MDD·Sharpe·거래횟수(회전율)·시장참여%.
룩어헤드 방지: 신호는 전일 종가 기준, 익일 반영.

실행(네 Mac):
  pip3 install yfinance pandas numpy
  python3 backtest_trend_sweep.py
BTC만 바이낸스 접속 필요(한국 OK). 주식은 야후(어디서든).
"""
import warnings
warnings.filterwarnings("ignore")
import json
import urllib.request
from datetime import datetime, timezone
import numpy as np
import pandas as pd

COST = 0.001          # 왕복 거래비용 0.1%
MA_LENS = [10, 20, 50, 100, 150, 200]              # 단순 N일선 스윕
CROSSES = [(10, 50), (20, 100), (50, 200), (20, 200)]  # (fast, slow) 크로스


# ── 데이터 로더 ──────────────────────────────────────────────────────────
def load_binance_daily(symbol="BTCUSDT", days=2000):
    """바이낸스 일봉 — 1000개 제한을 페이지네이션으로 넘어 전체 기간 수집."""
    bases = ["https://data-api.binance.vision", "https://api.binance.com"]
    end_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    start_ms = end_ms - days * 86400_000
    day_ms = 86400_000
    all_rows = []
    cursor = start_ms
    while cursor < end_ms:
        chunk = None
        for b in bases:
            try:
                url = (f"{b}/api/v3/klines?symbol={symbol}&interval=1d"
                       f"&startTime={cursor}&endTime={end_ms}&limit=1000")
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=25) as r:
                    d = json.loads(r.read().decode())
                if isinstance(d, list) and d:
                    chunk = d
                    break
            except Exception:
                continue
        if not chunk:
            break
        all_rows.extend(chunk)
        last_open = chunk[-1][0]
        nxt = last_open + day_ms
        if nxt <= cursor:            # 진전 없으면 종료
            break
        cursor = nxt
        if len(chunk) < 1000:        # 마지막 페이지
            break
    if not all_rows:
        raise RuntimeError("바이낸스 실패")
    df = pd.DataFrame(all_rows, columns=["t", "o", "h", "l", "c", "v", "ct",
                                         "qv", "n", "tb", "tq", "ig"])
    df["date"] = pd.to_datetime(df["t"], unit="ms")
    df = df[~df.index.duplicated()].drop_duplicates("t").set_index("date")
    return df["c"].astype(float)


def load_yahoo(ticker, start="2005-01-01"):
    import yfinance as yf
    df = yf.download(ticker, start=start, progress=False, auto_adjust=True)
    c = df["Close"].dropna()
    return c.iloc[:, 0] if isinstance(c, pd.DataFrame) else c


# ── 백테스트 엔진 ────────────────────────────────────────────────────────
def bt(close, in_mkt):
    """in_mkt: bool 시리즈(당일 보유 여부, 이미 shift 반영). 거래비용 차감 자본곡선."""
    ret = close.pct_change().fillna(0)
    pos = in_mkt.astype(float)
    trades = pos.diff().abs().fillna(0)               # 포지션 변경 = 거래
    strat = pos * ret - trades * COST
    eq = (1 + strat).cumprod()
    n_trades = int(trades.sum())
    return eq, n_trades


def metrics(eq, close, n_trades):
    years = (close.index[-1] - close.index[0]).days / 365.25
    cagr = (eq.iloc[-1]) ** (1 / years) * 100 - 100
    mdd = ((eq - eq.cummax()) / eq.cummax()).min() * 100
    vol = eq.pct_change().std() * np.sqrt(252) * 100
    sharpe = (cagr / 100) / (vol / 100) if vol > 0 else 0
    return cagr, mdd, sharpe, n_trades, years


def sweep(name, close):
    print(f"\n{'='*72}\n{name}  ({close.index[0].date()}~{close.index[-1].date()}, "
          f"{(close.index[-1]-close.index[0]).days/365.25:.1f}년)\n{'='*72}")
    # 벤치마크: 존버
    bh = close / close.iloc[0]
    c, m, s, _, yr = metrics(bh, close, 0)
    print(f"{'전략':<22}{'CAGR':>8}{'MDD':>9}{'Sharpe':>8}{'거래수':>7}{'참여%':>7}")
    print("-" * 72)
    print(f"{'존버(buy&hold)':<22}{c:>7.1f}%{m:>8.1f}%{s:>8.2f}{'—':>7}{'100':>6}%")

    best = None
    # 단순 N일선
    for L in MA_LENS:
        ma = close.rolling(L).mean()
        in_mkt = (close > ma).shift(1).fillna(False)
        eq, nt = bt(close, in_mkt)
        c, m, s, nt, yr = metrics(eq, close, nt)
        expo = in_mkt.mean() * 100
        print(f"{'price>'+str(L)+'일선':<22}{c:>7.1f}%{m:>8.1f}%{s:>8.2f}{nt:>7}{expo:>6.0f}%")
        if best is None or s > best[1]:
            best = (f"price>{L}일선", s, c, m)
    # 크로스
    for f, sl in CROSSES:
        fma, sma = close.rolling(f).mean(), close.rolling(sl).mean()
        in_mkt = (fma > sma).shift(1).fillna(False)
        eq, nt = bt(close, in_mkt)
        c, m, s, nt, yr = metrics(eq, close, nt)
        expo = in_mkt.mean() * 100
        print(f"{f'{f}>{sl} 크로스':<22}{c:>7.1f}%{m:>8.1f}%{s:>8.2f}{nt:>7}{expo:>6.0f}%")
        if s > best[1]:
            best = (f"{f}>{sl} 크로스", s, c, m)
    print(f"\n★ 최고 Sharpe: {best[0]} (Sharpe {best[1]:.2f}, CAGR {best[2]:.1f}%, MDD {best[3]:.1f}%)")
    return best


def main():
    print("추세추종 이평 길이 스윕 — 자산별 최적 길이 찾기 (비용 0.1% 왕복 포함)")
    results = {}

    # 1) BTC (바이낸스) — 2017년 상장부터 전체 기간(페이지네이션)
    try:
        btc = load_binance_daily("BTCUSDT", 3300)
        results["BTC"] = sweep("BTC/USDT 일봉 (바이낸스, 전체기간)", btc)
    except Exception as e:
        print(f"\n⚠️ BTC 실패: {e}")

    # 2) 미국 (야후)
    for tk, nm in [("QQQ", "나스닥100 QQQ"), ("SPY", "S&P500 SPY")]:
        try:
            results[tk] = sweep(f"{nm} 일봉 (야후)", load_yahoo(tk))
        except Exception as e:
            print(f"\n⚠️ {tk} 실패: {e}")

    # 3) 코스피 (야후)
    for tk, nm in [("^KS11", "코스피 지수"), ("005930.KS", "삼성전자")]:
        try:
            results[tk] = sweep(f"{nm} 일봉 (야후)", load_yahoo(tk))
        except Exception as e:
            print(f"\n⚠️ {tk} 실패: {e}")

    # 종합
    print(f"\n{'='*72}\n종합: 자산별 최적 추세추종 세팅\n{'='*72}")
    print(f"{'자산':<14}{'최적 세팅':<20}{'Sharpe':>8}{'CAGR':>9}{'MDD':>9}")
    print("-" * 72)
    for k, b in results.items():
        if b:
            print(f"{k:<14}{b[0]:<20}{b[1]:>8.2f}{b[2]:>8.1f}%{b[3]:>8.1f}%")
    print(f"\n{'='*72}")
    print("해석: Sharpe(위험조정수익)가 높고 MDD(낙폭)가 얕은 세팅이 그 자산의 스위트스팟.")
    print("일반적으로 변동성 큰 자산(BTC)은 다소 짧은 이평, 주식은 긴 이평이 유리.")
    print("존버 대비 Sharpe가 크게 안 높으면 = 그 자산은 추세추종 이점이 약함.")
    print(f"{'='*72}")


if __name__ == "__main__":
    main()
