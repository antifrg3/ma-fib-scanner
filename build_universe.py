#!/usr/bin/env python3
"""
build_universe.py
─────────────────────────────────────────────────────────────────────────
종목 파일을 '공식 구성종목'으로 자동 생성한다.
  - tickers_kr.txt : 코스피200 전체 (한글 종목명 포함)
  - tickers_us.txt : 나스닥100 (스크립트 내장 목록)

코스피200/나스닥100은 반기마다 종목이 바뀌므로, 가끔 이걸 한 번씩 돌려
목록을 최신으로 갱신하면 된다.

사용:
  pip install pykrx          # (또는: pip install finance-datareader)
  python3 build_universe.py
─────────────────────────────────────────────────────────────────────────
"""

import os
import sys
import json
import urllib.request

# ── 크립토 자동 유니버스 설정 ────────────────────────────────────────────
CRYPTO_TOP_N = int(os.environ.get("CRYPTO_TOP_N", "50"))   # 24h 거래대금 상위 N개
BINANCE_BASES = ["https://data-api.binance.vision", "https://api.binance.com"]

# 제외: 스테이블코인·법정화폐 토큰 (추세가 없음)
_STABLE = {"USDC", "FDUSD", "TUSD", "BUSD", "DAI", "USDP", "USDD", "PYUSD",
           "USTC", "EUR", "EURI", "AEUR", "GBP", "TRY", "BRL", "ARS", "ZAR"}
# 제외: 래핑·스테이킹 파생 토큰 (원본과 중복)
_WRAPPED = {"WBTC", "WETH", "WBETH", "WBNB", "BETH", "STETH", "WSTETH", "CBETH"}

# 표시용 한글명 (있으면 사용, 없으면 심볼 그대로)
_KR_NAMES = {
    "BTC": "비트코인", "ETH": "이더리움", "BNB": "BNB", "SOL": "솔라나", "XRP": "리플",
    "ADA": "에이다", "DOGE": "도지코인", "AVAX": "아발란체", "LINK": "체인링크", "DOT": "폴카닷",
    "TRX": "트론", "LTC": "라이트코인", "BCH": "비트코인캐시", "ATOM": "코스모스", "UNI": "유니스왑",
    "NEAR": "니어", "APT": "앱토스", "ARB": "아비트럼", "OP": "옵티미즘", "FIL": "파일코인",
    "INJ": "인젝티브", "SUI": "수이", "TON": "톤코인", "ICP": "인터넷컴퓨터", "ETC": "이더리움클래식",
    "XLM": "스텔라루멘", "HBAR": "헤데라", "AAVE": "아베", "SHIB": "시바이누", "PEPE": "페페",
    "MATIC": "폴리곤", "POL": "폴리곤", "RENDER": "렌더", "IMX": "이뮤터블", "STX": "스택스",
    "TAO": "비트텐서", "SEI": "세이", "TIA": "셀레스티아", "RUNE": "토르체인", "FET": "페치",
    "GRT": "더그래프", "ALGO": "알고랜드", "VET": "비체인", "MKR": "메이커", "LDO": "리도",
    "WLD": "월드코인", "JUP": "주피터", "ENA": "에테나", "ONDO": "온도", "PYTH": "피스",
}


def _is_leveraged(base: str) -> bool:
    """UP/DOWN/BULL/BEAR 레버리지 토큰 제외 (JUP 등 정상 토큰은 예외)."""
    if base in {"JUP", "MEME", "OP"}:
        return False
    return base.endswith(("UP", "DOWN", "BULL", "BEAR"))


# 나스닥100 (필요시 갱신). 이 목록으로 tickers_us.txt 를 만든다.
NASDAQ100 = [
    "NVDA","GOOGL","AAPL","MSFT","AMZN","AVGO","TSLA","META","MU","WMT",
    "AMD","ASML","INTC","CSCO","COST","LRCX","ARM","PLTR","AMAT","NFLX",
    "TXN","QCOM","KLAC","LIN","PANW","ADI","STX","TMUS","PEP","APP",
    "WDC","AMGN","CRWD","MRVL","GILD","ISRG","SHOP","HON","BKNG","PDD",
    "SBUX","VRTX","CEG","CDNS","MAR","ADBE","FTNT","SNPS","CMCSA","ADP",
    "INTU","MELI","MNST","CSX","NXPI","DDOG","MPWR","ABNB","MDLZ","ROST",
    "ORLY","DASH","AEP","CTAS","WBD","BKR","REGN","PCAR","FANG","MSTR",
    "MCHP","FAST","EA","XEL","FER","ODFL","EXC","ADSK","IDXX","TTWO",
    "CCEP","KDP","ALNY","PYPL","TRI","PAYX","AXON","WDAY","ROP","CPRT",
    "KHC","GEHC","DXCM","CTSH","TEAM","INSM","VRSK","ZS","CHTR","CSGP",
]


def write_us():
    with open("tickers_us.txt", "w", encoding="utf-8") as f:
        f.write("# 나스닥100 (build_universe.py 자동 생성)\n")
        for sym in NASDAQ100:
            f.write(sym + "\n")
    print(f"✅ tickers_us.txt : {len(NASDAQ100)}종목")


def get_kospi200():
    """(코드, 종목명) 리스트. pykrx → FinanceDataReader 순서로 시도."""
    # 1) pykrx
    try:
        from pykrx import stock
        codes = stock.get_index_portfolio_deposit_file("1028")  # 1028 = 코스피200
        out = []
        for c in codes:
            try:
                name = stock.get_market_ticker_name(c)
            except Exception:
                name = ""
            out.append((str(c).zfill(6), name))
        if out:
            print("  (pykrx 사용)")
            return out
    except Exception as e:
        print("  pykrx 사용 불가:", e)

    # 2) FinanceDataReader
    try:
        import re
        import FinanceDataReader as fdr
        df = fdr.SnapDataReader("KRX/INDEX/STOCK/1028")
        # 6자리 코드 컬럼 / 한글 종목명 컬럼 자동 탐색
        code_col = next((col for col in df.columns
                         if df[col].astype(str).str.fullmatch(r"\d{6}").mean() > 0.5), None)
        name_col = next((col for col in df.columns
                         if df[col].astype(str).str.contains(r"[가-힣]").mean() > 0.5), None)
        if code_col is None:
            print("  FinanceDataReader: 코드 컬럼을 못 찾음. 컬럼:", list(df.columns))
            return []
        out = []
        for _, r in df.iterrows():
            code = str(r[code_col]).zfill(6)
            name = str(r[name_col]) if name_col else ""
            out.append((code, name))
        if out:
            print("  (FinanceDataReader 사용)")
            return out
    except Exception as e:
        print("  FinanceDataReader 사용 불가:", e)

    return []


def write_kr():
    rows = get_kospi200()
    if not rows:
        print("❌ 코스피200 목록을 가져오지 못했습니다.")
        print("   먼저:  pip install pykrx   (또는 pip install finance-datareader)")
        return
    with open("tickers_kr.txt", "w", encoding="utf-8") as f:
        f.write("# 코스피200 전체 (build_universe.py 자동 생성)\n")
        for code, name in rows:
            line = f"{code}.KS"
            if name:
                line += f"   # {name}"
            f.write(line + "\n")
    print(f"✅ tickers_kr.txt : {len(rows)}종목")


def write_crypto(top_n: int = CRYPTO_TOP_N):
    """바이낸스 24h 거래대금 상위 USDT 페어로 tickers_crypto.txt 생성."""
    data = None
    for base_url in BINANCE_BASES:
        try:
            req = urllib.request.Request(base_url + "/api/v3/ticker/24hr",
                                         headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.loads(r.read().decode())
            if data:
                break
        except Exception as e:
            print("  24hr 티커 실패:", base_url, e)
    if not data:
        print("❌ 크립토 유니버스 생성 실패 — 기존 tickers_crypto.txt 유지")
        return

    rows = []
    for d in data:
        sym = d.get("symbol", "")
        if not sym.endswith("USDT"):
            continue
        base = sym[:-4]
        if base in _STABLE or base in _WRAPPED or _is_leveraged(base):
            continue
        try:
            qv = float(d.get("quoteVolume", 0))   # USDT 환산 거래대금
        except (TypeError, ValueError):
            qv = 0.0
        rows.append((sym, base, qv))

    rows.sort(key=lambda x: x[2], reverse=True)
    top = rows[:top_n]

    with open("tickers_crypto.txt", "w", encoding="utf-8") as f:
        f.write("# 크립토 스캔 대상 — 바이낸스 24h 거래대금 상위 (build_universe.py 자동 생성)\n")
        f.write(f"# 상위 {top_n}개 · 스테이블/래핑/레버리지 제외 · 히스토리 부족분은 스캔 시 자동 제외\n")
        for sym, base, _qv in top:
            name = _KR_NAMES.get(base, base)
            f.write(f"{sym}  # {name}\n")
    print(f"✅ tickers_crypto.txt : {len(top)}종목 (24h 거래대금 TOP {top_n})")


def write_kr_etf(top_n: int = 40):
    """pykrx로 한국 ETF 거래대금 상위 N개 생성 (레버리지/인버스 제외)."""
    try:
        from pykrx import stock
        date = stock.get_nearest_business_day_in_a_week()
        codes = stock.get_etf_ticker_list(date)
        try:
            ohlcv = stock.get_etf_ohlcv_by_ticker(date)
            val_col = next((c for c in ohlcv.columns if "거래대금" in c), None)
        except Exception:
            ohlcv, val_col = None, None

        skip = ("레버리지", "인버스", "2X", "3X", "곱버스", "선물인버스")
        rows = []
        for c in codes:
            try:
                name = stock.get_etf_ticker_name(c)
            except Exception:
                name = ""
            if any(k in name for k in skip):
                continue
            val = 0.0
            if ohlcv is not None and val_col and c in ohlcv.index:
                try:
                    val = float(ohlcv.loc[c, val_col])
                except Exception:
                    val = 0.0
            rows.append((str(c).zfill(6), name, val))

        if val_col:
            rows.sort(key=lambda x: x[2], reverse=True)
        top = rows[:top_n]
        if not top:
            print("❌ 한국 ETF 목록 비어있음 — 기존 tickers_kr_etf.txt 유지")
            return
        with open("tickers_kr_etf.txt", "w", encoding="utf-8") as f:
            f.write("# 한국 ETF — pykrx 거래대금 상위 (build_universe.py 자동 생성)\n")
            f.write(f"# 상위 {top_n}개 · 레버리지/인버스 제외\n")
            for code, name, _v in top:
                line = f"{code}.KS"
                if name:
                    line += f"   # {name}"
                f.write(line + "\n")
        print(f"✅ tickers_kr_etf.txt : {len(top)}종목 (거래대금 TOP {top_n})")
    except Exception as e:
        print("❌ 한국 ETF 생성 실패 — 기존 파일 유지:", e)


if __name__ == "__main__":
    print("종목 파일 생성 중...")
    write_us()
    write_kr()
    write_kr_etf()
    write_crypto()
    print("끝. 이제 스캐너를 그대로 돌리면 확장된 목록으로 검색합니다.")
