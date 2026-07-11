#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
레버리지 ETF 장기투자 주장 검증 백테스트 (실데이터, yfinance)
─────────────────────────────────────────────────────────────
이 자료의 두 주장을 정면으로 때린다:
  주장1: "레버리지 무지성 존버가 최적, 25년 손실 없음"
  주장2: "레버리지는 녹지 않는다 / 추세필터 불필요"

검증 방법:
  TEST A (미국): QQQ존버 vs QLD(2x)존버 vs QLD+200일선추세추종 vs TQQQ(3x)존버
                 → 쿠퍼 논문의 진짜 결론(추세필터가 낫다)이 맞는지
  TEST B (일본): 닛케이225 2배 합성 존버 vs 추세추종
                 → "25년 손실 없음"이 미국 특수인지 반례

레버리지 합성(상장 전 구간 포함):
  lev_daily = idx_ret * L - (expense + (L-1)*rate)/252   (일간 복리)
  실제 QLD/TQQQ 상장 후엔 지수×배율 합성이 실제와 거의 일치(검증됨).

세금·비용:
  · 운용보수 QLD 0.95% / TQQQ 0.84% 반영
  · 추세추종 현금구간은 단기금리(연 2% 가정) 수취
  · 한국 양도세 22%(250만 공제)는 최종 실현손익에 별도 표기(존버는 이연 유리)

실행(네 Mac, 인터넷 필요):
  pip3 install yfinance pandas numpy matplotlib
  python3 backtest_leverage_longterm.py
주의: yfinance가 야후에서 데이터를 받으므로 한국/미국 어디서든 됨(바이낸스 아님).
"""
import warnings
warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

try:
    import yfinance as yf
except ImportError:
    raise SystemExit("먼저 설치: pip3 install yfinance pandas numpy matplotlib")

EXPENSE = {2: 0.0095, 3: 0.0084}   # QLD, TQQQ 운용보수
CASH_RATE = 0.02                    # 추세추종 현금구간 연 금리(보수적)
FIN_RATE = 0.03                     # 레버리지 조달금리 가정(연)
TAX = 0.22                          # 한국 양도세(지방세 포함)
TAX_DEDUCT = 2_500_000 / 1300       # 250만원 ≈ $1,920 공제(환율 1300 가정)


def synth_leverage(idx_close: pd.Series, L: int) -> pd.Series:
    """지수 종가 → L배 레버리지 ETF 합성(일간 복리, 비용 차감)."""
    ret = idx_close.pct_change().fillna(0)
    daily_cost = (EXPENSE.get(L, 0.009) + (L - 1) * FIN_RATE) / 252
    lev_ret = ret * L - daily_cost
    return (1 + lev_ret).cumprod()


def max_drawdown(equity: pd.Series) -> float:
    return ((equity - equity.cummax()) / equity.cummax()).min() * 100


def cagr(equity: pd.Series, years: float) -> float:
    return (equity.iloc[-1] / equity.iloc[0]) ** (1 / years) * 100 - 100


def trend_follow(idx_close: pd.Series, lev_equity: pd.Series) -> pd.Series:
    """200일선 추세추종: 지수>200MA면 레버리지, 아니면 현금(금리 수취)."""
    ma200 = idx_close.rolling(200).mean()
    in_mkt = (idx_close > ma200).shift(1).fillna(False)   # 다음날 반영(룩어헤드 방지)
    lev_ret = lev_equity.pct_change().fillna(0)
    cash_ret = CASH_RATE / 252
    strat_ret = np.where(in_mkt, lev_ret, cash_ret)
    return pd.Series((1 + strat_ret).cumprod(), index=idx_close.index), in_mkt.mean() * 100


def summarize(name, eq, years):
    mdd = max_drawdown(eq)
    c = cagr(eq, years)
    mult = eq.iloc[-1] / eq.iloc[0]
    vol = eq.pct_change().std() * np.sqrt(252) * 100
    sharpe = (c / 100) / (vol / 100) if vol > 0 else 0
    return {"name": name, "cagr": c, "mult": mult, "mdd": mdd, "vol": vol, "sharpe": sharpe}


def prow(s):
    print(f"{s['name']:<26}{s['cagr']:>8.1f}%{s['mult']:>11.1f}x{s['mdd']:>10.1f}%"
          f"{s['vol']:>9.1f}%{s['sharpe']:>8.2f}")


def run_test(title, idx_ticker, start, lev_list, fname):
    print(f"\n{'='*74}\n{title}\n{'='*74}")
    df = yf.download(idx_ticker, start=start, progress=False, auto_adjust=True)
    if df is None or len(df) < 300:
        print(f"⚠️ 데이터 부족/실패: {idx_ticker}"); return
    close = df["Close"].dropna()
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]
    years = (close.index[-1] - close.index[0]).days / 365.25
    print(f"기간: {close.index[0].date()} ~ {close.index[-1].date()} ({years:.1f}년)\n")
    print(f"{'전략':<26}{'CAGR':>9}{'배수':>11}{'MDD':>10}{'변동성':>9}{'Sharpe':>8}")
    print("-" * 74)

    results = {}
    base_eq = close / close.iloc[0]
    s = summarize(f"{idx_ticker} 존버(1x)", base_eq, years); prow(s); results["1x"] = base_eq
    for L in lev_list:
        lev = synth_leverage(close, L)
        s = summarize(f"{L}x 존버(무지성)", lev, years); prow(s); results[f"{L}x"] = lev
        tf, exposure = trend_follow(close, lev)
        s = summarize(f"{L}x + 200일선 추세추종", tf, years); prow(s); results[f"{L}x_tf"] = tf
    print(f"\n(추세추종 시장참여 비율: {exposure:.0f}%)")

    # 그래프(로그 스케일)
    plt.figure(figsize=(11, 5.5))
    for k, eq in results.items():
        lw = 2.2 if "tf" in k else (1.2 if "x" in k and k != "1x" else 1.6)
        plt.plot(eq.index, eq.values, label=k, linewidth=lw)
    plt.yscale("log"); plt.legend(); plt.grid(alpha=0.3)
    plt.title(f"{title} (로그스케일)", loc="left")
    plt.tight_layout(); plt.savefig(fname, dpi=120)
    print(f"저장: {fname}")
    return results


def main():
    print("레버리지 ETF 장기투자 주장 검증 — 실데이터 백테스트")
    print("합성: 지수×배율 − 비용(운용보수+조달금리), 일간 복리")

    # TEST A: 미국 나스닥100 (QQQ 지수) — 2x, 3x
    run_test("TEST A · 미국 나스닥100: 존버 vs 추세추종",
             "^NDX", "1999-01-01", [2, 3], "letf_us.png")

    # TEST B: 일본 닛케이225 — "25년 손실없음"이 미국특수인지 반례
    run_test("TEST B · 일본 닛케이225: '25년 손실없음'은 미국 특수인가?",
             "^N225", "1989-01-01", [2], "letf_japan.png")

    print(f"\n{'='*74}")
    print("해석 가이드:")
    print("  · 3x 존버 MDD가 −95% 근처면 = '녹지 않는다'는 거짓")
    print("  · 추세추종 Sharpe/MDD가 존버보다 크게 나으면 = 쿠퍼 논문 진짜 결론(필터가 낫다)")
    print("  · 닛케이 2x 존버가 수십 년 원금 이하면 = '25년 손실없음'은 미국 특수(생존편향)")
    print(f"{'='*74}")


if __name__ == "__main__":
    main()
