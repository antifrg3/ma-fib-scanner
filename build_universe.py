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

import sys

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


if __name__ == "__main__":
    print("종목 파일 생성 중...")
    write_us()
    write_kr()
    print("끝. 이제 스캐너를 그대로 돌리면 확장된 목록으로 검색합니다.")
