#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
recon_flows.py — 4개 시장 수급 데이터 가용성 정찰
─────────────────────────────────────────────────────────────────────────
목적: 수급 대시보드를 설계하기 전에, 각 시장에서 실제로 어떤 데이터를
      무료로 받을 수 있는지 확인한다. 되는 것만으로 설계해야 낭비가 없다.

검사 대상:
  ① BTC     — 바이낸스 선물: 펀딩비 / 미결제약정(OI) / 롱숏비율
  ② 코스피   — 투자자별 순매수 (pykrx · FinanceDataReader 순서로 시도)
  ③ 나스닥   — VIX, QQQ 거래량/자금흐름 대용
  ④ S&P500  — VIX, SPY 거래량/자금흐름 대용

실행:
  cd ~/GitHub/ma-fib-scanner
  python3 recon_flows.py
"""
import json
import urllib.request
from datetime import datetime, timedelta

OK = "✅"
NO = "❌"
WARN = "⚠️"


def _get_json(url, timeout=15):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        return {"__error__": str(e)}


def section(title):
    print(f"\n{'='*66}\n{title}\n{'='*66}")


# ══════════════════════════════════════════════════════════════════════════
def check_btc():
    section("① 비트코인 — 바이낸스 선물 수급")
    FAPI = "https://fapi.binance.com"
    results = {}

    # 1) 펀딩비 (현재 + 최근 이력)
    d = _get_json(f"{FAPI}/fapi/v1/premiumIndex?symbol=BTCUSDT")
    if "__error__" in d:
        print(f"{NO} 펀딩비: {d['__error__']}")
        results["funding"] = False
    else:
        fr = float(d.get("lastFundingRate", 0)) * 100
        mark = float(d.get("markPrice", 0))
        print(f"{OK} 펀딩비 (현재): {fr:+.4f}%  · 마크가격 ${mark:,.0f}")
        print(f"     해석: 양수=롱이 숏에게 지불(롱 과열) · 음수=숏 과열")
        results["funding"] = True

    # 2) 펀딩비 이력
    d = _get_json(f"{FAPI}/fapi/v1/fundingRate?symbol=BTCUSDT&limit=10")
    if isinstance(d, list) and d:
        rates = [float(x["fundingRate"]) * 100 for x in d]
        print(f"{OK} 펀딩비 이력 10회: 평균 {sum(rates)/len(rates):+.4f}% "
              f"(최근 {rates[-1]:+.4f}%)")
        results["funding_hist"] = True
    else:
        print(f"{NO} 펀딩비 이력")
        results["funding_hist"] = False

    # 3) 미결제약정(OI)
    d = _get_json(f"{FAPI}/fapi/v1/openInterest?symbol=BTCUSDT")
    if "__error__" not in d and "openInterest" in d:
        oi = float(d["openInterest"])
        print(f"{OK} 미결제약정(현재): {oi:,.0f} BTC")
        results["oi"] = True
    else:
        print(f"{NO} 미결제약정")
        results["oi"] = False

    # 4) OI 이력 (추세 판단용)
    d = _get_json(f"{FAPI}/futures/data/openInterestHist"
                  f"?symbol=BTCUSDT&period=1d&limit=7")
    if isinstance(d, list) and d:
        first = float(d[0]["sumOpenInterest"])
        last = float(d[-1]["sumOpenInterest"])
        chg = (last / first - 1) * 100 if first else 0
        print(f"{OK} OI 이력 7일: {chg:+.1f}% 변화")
        print(f"     해석: 가격↑+OI↑=신규매수 유입 · 가격↑+OI↓=숏커버(약함)")
        results["oi_hist"] = True
    else:
        print(f"{NO} OI 이력 (일부 지역 차단 가능)")
        results["oi_hist"] = False

    # 5) 롱숏 비율 (계정 기준)
    d = _get_json(f"{FAPI}/futures/data/globalLongShortAccountRatio"
                  f"?symbol=BTCUSDT&period=1d&limit=5")
    if isinstance(d, list) and d:
        r = float(d[-1]["longShortRatio"])
        print(f"{OK} 롱숏 계정비율: {r:.2f} "
              f"({'롱 우위' if r > 1 else '숏 우위'})")
        results["lsr"] = True
    else:
        print(f"{NO} 롱숏 비율")
        results["lsr"] = False

    # 6) 대형 트레이더 포지션 비율
    d = _get_json(f"{FAPI}/futures/data/topLongShortPositionRatio"
                  f"?symbol=BTCUSDT&period=1d&limit=5")
    if isinstance(d, list) and d:
        r = float(d[-1]["longShortRatio"])
        print(f"{OK} 대형트레이더 롱숏비: {r:.2f}  ← 개인과 반대면 주목")
        results["top_lsr"] = True
    else:
        print(f"{NO} 대형트레이더 비율")
        results["top_lsr"] = False

    # 7) 테이커 매수/매도 비율
    d = _get_json(f"{FAPI}/futures/data/takerlongshortRatio"
                  f"?symbol=BTCUSDT&period=1d&limit=5")
    if isinstance(d, list) and d:
        r = float(d[-1]["buySellRatio"])
        print(f"{OK} 테이커 매수/매도: {r:.2f}  ← 공격적 주문 방향")
        results["taker"] = True
    else:
        print(f"{NO} 테이커 비율")
        results["taker"] = False

    return results


# ══════════════════════════════════════════════════════════════════════════
def check_kospi():
    section("② 코스피 — 투자자별 수급 (외국인/기관/개인)")
    results = {}

    # 1) pykrx 시도
    try:
        from pykrx import stock
        today = datetime.now()
        start = (today - timedelta(days=10)).strftime("%Y%m%d")
        end = today.strftime("%Y%m%d")
        df = stock.get_market_trading_value_by_date(start, end, "KOSPI")
        if df is not None and not df.empty:
            print(f"{OK} pykrx 투자자별 순매수 — 최근 {len(df)}일")
            last = df.iloc[-1]
            print(f"     {df.index[-1].strftime('%Y-%m-%d')} 기준:")
            for col in df.columns[:6]:
                print(f"       {col:<12} {last[col]/1e8:>10,.0f}억")
            results["pykrx"] = True
        else:
            print(f"{WARN} pykrx 응답이 비어있음")
            results["pykrx"] = False
    except ImportError:
        print(f"{NO} pykrx 미설치 (pip3 install pykrx)")
        results["pykrx"] = False
    except Exception as e:
        print(f"{NO} pykrx 실패: {e}")
        results["pykrx"] = False

    # 2) FinanceDataReader 시도
    try:
        import FinanceDataReader as fdr
        df = fdr.DataReader("KS11", (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d"))
        if df is not None and not df.empty:
            print(f"{OK} FinanceDataReader 코스피 지수 — {len(df)}일 "
                  f"(종가 {df['Close'].iloc[-1]:,.2f})")
            print(f"     {WARN} 단, 투자자별 수급은 fdr에서 직접 제공 안 함")
            results["fdr_index"] = True
        else:
            print(f"{NO} FinanceDataReader 응답 없음")
            results["fdr_index"] = False
    except ImportError:
        print(f"{NO} FinanceDataReader 미설치 (pip3 install finance-datareader)")
        results["fdr_index"] = False
    except Exception as e:
        print(f"{NO} FinanceDataReader 실패: {e}")
        results["fdr_index"] = False

    # 3) 야후로 코스피 지수만이라도
    try:
        import yfinance as yf
        df = yf.download("^KS11", period="10d", progress=False, auto_adjust=True)
        if df is not None and not df.empty:
            print(f"{OK} yfinance 코스피 지수 — {len(df)}일 (수급 아님, 가격만)")
            results["yf_index"] = True
        else:
            print(f"{NO} yfinance 코스피")
            results["yf_index"] = False
    except Exception as e:
        print(f"{NO} yfinance 실패: {e}")
        results["yf_index"] = False

    return results


# ══════════════════════════════════════════════════════════════════════════
def check_us():
    section("③④ 나스닥 / S&P500 — 심리·자금흐름 대용지표")
    results = {}
    try:
        import yfinance as yf
    except ImportError:
        print(f"{NO} yfinance 미설치")
        return {"yf": False}

    targets = [
        ("^VIX",  "VIX 공포지수",        "20↑ 불안 · 15↓ 안정"),
        ("^GSPC", "S&P500 지수",         ""),
        ("^IXIC", "나스닥 종합",          ""),
        ("QQQ",   "나스닥 ETF(거래량)",   "거래량 급증=자금 이동"),
        ("SPY",   "S&P ETF(거래량)",      ""),
        ("^TNX",  "미국 10년물 금리",     "금리↑=위험자산 압박"),
        ("DX-Y.NYB", "달러인덱스",        "달러↑=위험자산 압박"),
        ("HYG",   "하이일드 채권 ETF",    "위험선호 대용지표"),
    ]
    for sym, label, note in targets:
        try:
            df = yf.download(sym, period="10d", progress=False, auto_adjust=True)
            if df is not None and not df.empty:
                last = float(df["Close"].iloc[-1])
                prev = float(df["Close"].iloc[-2]) if len(df) > 1 else last
                chg = (last / prev - 1) * 100 if prev else 0
                vol = ""
                if "Volume" in df.columns and float(df["Volume"].iloc[-1]) > 0:
                    v = float(df["Volume"].iloc[-1])
                    va = float(df["Volume"].tail(10).mean())
                    vol = f" · 거래량 평균대비 {v/va:.2f}배" if va else ""
                print(f"{OK} {label:<18} {last:>10,.2f} ({chg:+.2f}%){vol}")
                if note:
                    print(f"     {note}")
                results[sym] = True
            else:
                print(f"{NO} {label} — 데이터 없음")
                results[sym] = False
        except Exception as e:
            print(f"{NO} {label} — {str(e)[:50]}")
            results[sym] = False

    # 풋/콜 비율은 무료 API가 마땅치 않음 — 확인만
    print(f"\n{WARN} 풋/콜 비율, ETF 순유입(실제 자금) 은 무료 소스가 제한적")
    print(f"     → 거래량·VIX·금리·달러로 대용 가능")
    return results


# ══════════════════════════════════════════════════════════════════════════
def main():
    print("4개 시장 수급 데이터 가용성 정찰")
    print(f"실행 시각: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    btc = check_btc()
    kospi = check_kospi()
    us = check_us()

    section("종합 — 무엇을 만들 수 있나")
    nb = sum(1 for v in btc.values() if v)
    print(f"① BTC     : {nb}/{len(btc)} 항목 가용 "
          f"{'→ 대시보드 구축 가능' if nb >= 3 else '→ 제한적'}")
    kk = sum(1 for v in kospi.values() if v)
    kospi_flow = kospi.get("pykrx", False)
    print(f"② 코스피   : {kk}/{len(kospi)} 항목 가용 "
          f"{'→ 투자자별 수급 가능' if kospi_flow else '→ 수급 데이터 미확보(가격만)'}")
    ku = sum(1 for v in us.values() if v)
    print(f"③④ 미국   : {ku}/{len(us)} 항목 가용 "
          f"{'→ 심리지표 기반 구축 가능' if ku >= 4 else '→ 제한적'}")
    print("\n이 결과를 붙여넣어 주시면, 가능한 범위로 대시보드를 설계합니다.")


if __name__ == "__main__":
    main()
