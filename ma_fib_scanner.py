#!/usr/bin/env python3
"""
ma_fib_scanner.py
─────────────────────────────────────────────────────────────────────────
일봉 200선 + 4시간봉 200선 '골든크로스' 후, 피보나치 되돌림 눌림목 구간에
들어온 종목을 찾아 차트를 그려 이메일로 보내주는 스캐너.

전략 출처: 사용자가 제공한 매매법 문서.
  - 조건1: 4시간봉 200선이 일봉 200선을 상향 돌파(골든크로스), 최근 N일 이내
  - 조건2: 크로스 이전 저점 ~ 이후 최근 고점으로 피보나치 되돌림
  - 조건3: 현재가가 0.382~0.618 눌림목 구간(분할매수 구간)에 위치
  - 대상: 나스닥100 / 대형주 등 건실한 종목 (기본 유니버스로 한정)

⚠️ 이 스크립트는 '조건에 맞는 후보를 찾아 차트로 보여주는 스크리너'다.
   매매 권유나 투자 조언이 아니며, 진입·손절·익절 판단은 전적으로 본인 몫이다.
   어떤 전략도 승률 100%는 없다(문서 본문에도 명시).
─────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import os
import io
import sys
import json
import time
import smtplib
import urllib.request
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage

import numpy as np
import pandas as pd

import matplotlib
matplotlib.use("Agg")  # 헤드리스(서버/크론) 환경용
import matplotlib.pyplot as plt
import mplfinance as mpf
import yfinance as yf


# ======================================================================
# 1) 설정 — 여기만 손대면 됨
# ======================================================================

# 검색할 종목 유니버스(기본: 나스닥100 + 문서에 언급된 대형주들).
# 같은 폴더에 tickers.txt(한 줄에 티커 하나)가 있으면 그걸 우선 사용.
DEFAULT_UNIVERSE = [
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "AMD",
    "NFLX", "ADBE", "COST", "PEP", "CSCO", "INTC", "QCOM", "TXN", "AMAT",
    "MU", "INTU", "ORCL", "CRM", "PLTR", "MSTR", "COIN", "HOOD", "UBER",
    "SHOP", "ARM", "SMCI", "PANW", "CRWD", "SNOW", "DDOG", "NET", "ABNB",
    "MELI", "LRCX", "KLAC", "ASML", "MRVL", "ADI", "NOW", "AMGN", "GILD",
    "BKNG", "REGN", "VRTX", "ISRG", "LIN", "HON", "SBUX", "MDLZ", "CMCSA",
    "TMUS", "CDNS", "SNPS", "FTNT", "ON", "MCHP",
]

# 한국 종목: yfinance는 코스피 ".KS", 코스닥 ".KQ" 접미사 사용.
# (티커 → 표시용 한글명) — 메일에는 한글명, 차트에는 폰트 안전을 위해 코드만 표시.
KR_NAME_MAP = {
    "005930.KS": "삼성전자", "000660.KS": "SK하이닉스", "373220.KS": "LG에너지솔루션",
    "207940.KS": "삼성바이오로직스", "005380.KS": "현대차", "000270.KS": "기아",
    "068270.KS": "셀트리온", "005490.KS": "POSCO홀딩스", "035420.KS": "NAVER",
    "006400.KS": "삼성SDI", "051910.KS": "LG화학", "035720.KS": "카카오",
    "012330.KS": "현대모비스", "105560.KS": "KB금융", "055550.KS": "신한지주",
    "086790.KS": "하나금융지주", "316140.KS": "우리금융지주", "138040.KS": "메리츠금융지주",
    "329180.KS": "HD현대중공업", "012450.KS": "한화에어로스페이스", "032830.KS": "삼성생명",
    "066570.KS": "LG전자", "010130.KS": "고려아연", "034020.KS": "두산에너빌리티",
    "011200.KS": "HMM", "259960.KS": "크래프톤", "009150.KS": "삼성전기",
    "033780.KS": "KT&G", "028260.KS": "삼성물산", "096770.KS": "SK이노베이션",
    # 코스닥
    "247540.KQ": "에코프로비엠", "086520.KQ": "에코프로",
    "196170.KQ": "알테오젠", "058470.KQ": "리노공업",
}
KR_UNIVERSE = list(KR_NAME_MAP.keys())

# 크립토(바이낸스 USDT 페어). 변동성·유동성 큰 시총 상위 위주.
CRYPTO_UNIVERSE = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT",
    "DOGEUSDT", "AVAXUSDT", "LINKUSDT", "DOTUSDT", "TRXUSDT", "LTCUSDT",
    "BCHUSDT", "ATOMUSDT", "UNIUSDT", "NEARUSDT", "APTUSDT", "ARBUSDT",
    "OPUSDT", "FILUSDT", "INJUSDT", "SUIUSDT", "TONUSDT", "ICPUSDT",
    "ETCUSDT", "XLMUSDT", "HBARUSDT", "AAVEUSDT",
]

# ETF (yfinance, 미국 상장). 유동성 큰 메이저 위주 — 브로드/섹터/테마/지역/원자재.
ETF_UNIVERSE = [
    "SPY", "QQQ", "IWM", "DIA", "VTI",                          # 브로드
    "XLK", "XLF", "XLE", "XLV", "XLY", "XLP", "XLI", "XLU",      # 섹터(SPDR)
    "XLB", "XLRE", "XLC",
    "SMH", "SOXX", "IGV", "XBI", "ARKK", "TAN", "ICLN",         # 테마/산업
    "GDX", "XRT", "KRE", "XHB", "JETS",
    "EEM", "FXI", "EWY", "EWJ", "INDA",                          # 지역
    "GLD", "SLV", "TLT", "HYG",                                  # 원자재/채권
]


def normalize_ticker(t: str) -> str:
    """6자리 숫자만 입력하면 코스피(.KS)로 간주. 코스닥은 직접 .KQ 붙여야 함."""
    t = t.strip().upper()
    if t.isdigit() and len(t) == 6:
        return t + ".KS"
    return t


def is_krw(ticker: str) -> bool:
    return ticker.upper().endswith((".KS", ".KQ"))


def is_crypto(ticker: str) -> bool:
    return ticker.upper().endswith("USDT")


def display_name(ticker: str) -> str:
    if is_crypto(ticker):
        return _FILE_NAMES.get(ticker.upper(), ticker[:-4])  # BTCUSDT → BTC
    return _FILE_NAMES.get(ticker.upper(), KR_NAME_MAP.get(ticker.upper(), ticker))


def fmt_price(price: float, ticker: str) -> str:
    if is_krw(ticker):
        return f"{price:,.0f}"
    if is_crypto(ticker):
        if price >= 100:
            return f"{price:,.2f}"
        if price >= 1:
            return f"{price:,.3f}"
        return f"{price:,.6f}".rstrip("0").rstrip(".")
    return f"{price:,.2f}"


@dataclass
class Config:
    # --- 이동평균 ---
    daily_ma: int = 200            # 일봉 200선
    intraday_ma: int = 200         # 4시간봉 200선
    intraday_interval: str = "4h"  # yfinance에서 1h 받아 4h로 리샘플

    # --- 골든크로스 신선도: 최근 N 거래일 이내 발생한 크로스만 유효 ---
    gc_lookback_days: int = 120
    fresh_days: int = 20           # 크로스 후 N일 이내 = '갓 크로스' 단계

    # --- 피보나치 앵커 ---
    pre_cross_lookback: int = 60   # 크로스 이전 저점 탐색 구간(거래일)

    # --- 눌림목(되돌림) 판정 ---
    zone_min: float = 0.30         # 차트+상세 리포트에 포함할 최소 되돌림
    zone_max: float = 0.70         # 최대 되돌림
    buy_levels: tuple = (0.382, 0.5, 0.618)  # 분할매수 라인
    fib_show: tuple = (0.0, 0.382, 0.5, 0.618, 1.0)  # 문서 기준 표시 라인

    # --- 데이터 ---
    daily_period: str = "2y"
    chart_bars: int = 180          # 차트에 표시할 최근 거래일 수

    # --- 이메일 (환경변수로 주입) ---
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 465
    gmail_address: str = field(default_factory=lambda: os.environ.get("GMAIL_ADDRESS", ""))
    gmail_app_password: str = field(default_factory=lambda: os.environ.get("GMAIL_APP_PASSWORD", ""))
    email_to: str = field(default_factory=lambda: os.environ.get("EMAIL_TO", os.environ.get("GMAIL_ADDRESS", "")))

    # --- 동작 ---
    market: str = field(default_factory=lambda: os.environ.get("MARKET", "us").lower())  # us / kr / all
    dry_run: bool = field(default_factory=lambda: os.environ.get("DRY_RUN", "0") == "1")
    out_dir: str = "scanner_out"
    sleep_between: float = 0.4     # 티커 간 딜레이(레이트리밋 완화)


# ======================================================================
# 2) 데이터 / 지표
# ======================================================================

MARKET_LABEL = {"us": "미국(나스닥)", "kr": "한국(코스피·코스닥)",
                "etf": "미국 ETF", "crypto": "크립토(바이낸스)", "all": "전체"}

# 종목 파일의 인라인 주석(코드 # 종목명)에서 읽어온 이름 저장소
_FILE_NAMES: dict = {}


def _read_ticker_file(path: str) -> list[str]:
    out = []
    with open(path) as f:
        for raw in f:
            code = raw.split("#", 1)[0].strip()
            if not code:
                continue
            t = normalize_ticker(code)
            out.append(t)
            if "#" in raw:  # 줄 끝 주석을 종목명으로 등록
                name = raw.split("#", 1)[1].strip()
                if name:
                    _FILE_NAMES[t] = name
    return out


def load_universe(market: str = "us") -> list[str]:
    """시장별 종목 목록. tickers_us/kr/crypto.txt 가 있으면 그걸 우선 사용."""
    here = os.path.dirname(os.path.abspath(__file__))
    us_file = os.path.join(here, "tickers_us.txt")
    kr_file = os.path.join(here, "tickers_kr.txt")
    cr_file = os.path.join(here, "tickers_crypto.txt")
    etf_file = os.path.join(here, "tickers_etf.txt")
    us = _read_ticker_file(us_file) if os.path.exists(us_file) else list(DEFAULT_UNIVERSE)
    kr = _read_ticker_file(kr_file) if os.path.exists(kr_file) else list(KR_UNIVERSE)
    cr = _read_ticker_file(cr_file) if os.path.exists(cr_file) else list(CRYPTO_UNIVERSE)
    etf = _read_ticker_file(etf_file) if os.path.exists(etf_file) else list(ETF_UNIVERSE)
    if market == "kr":
        return kr
    if market == "crypto":
        return cr
    if market == "etf":
        return etf
    if market == "all":
        return us + kr + etf + cr
    return us


def fetch_daily(ticker: str, period: str) -> pd.DataFrame:
    df = yf.download(ticker, period=period, interval="1d",
                     auto_adjust=False, progress=False, threads=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.dropna()
    df.index = pd.to_datetime(df.index).tz_localize(None)
    return df


def fetch_intraday_4h(ticker: str) -> pd.DataFrame | None:
    """yfinance 1h(최대 730일) → 4h 리샘플. 실패 시 None."""
    try:
        h = yf.download(ticker, period="730d", interval="1h",
                        auto_adjust=False, progress=False, threads=False)
    except Exception:
        return None
    if h is None or h.empty:
        return None
    if isinstance(h.columns, pd.MultiIndex):
        h.columns = h.columns.get_level_values(0)
    h = h.dropna()
    h.index = pd.to_datetime(h.index)
    if h.index.tz is not None:
        h.index = h.index.tz_convert("America/New_York").tz_localize(None)
    agg = {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}
    four = h.resample("4h").agg(agg).dropna()
    return four if not four.empty else None


# ── 크립토(바이낸스) ─────────────────────────────────────────────────────
# 미국 IP 차단을 피하려 지역제한 없는 공개 엔드포인트를 우선 사용
BINANCE_BASES = ["https://data-api.binance.vision", "https://api.binance.com"]


def _binance_klines(symbol: str, interval: str, limit: int = 1000):
    last_err = None
    for base in BINANCE_BASES:
        try:
            url = f"{base}/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=25) as r:
                data = json.loads(r.read().decode())
            if isinstance(data, list) and data:
                return data
        except Exception as e:
            last_err = e
            continue
    raise RuntimeError(f"Binance klines 실패 {symbol} {interval}: {last_err}")


def _klines_to_df(data) -> pd.DataFrame:
    rows = [(pd.to_datetime(k[0], unit="ms"), float(k[1]), float(k[2]),
             float(k[3]), float(k[4]), float(k[5])) for k in data]
    df = pd.DataFrame(rows, columns=["Date", "Open", "High", "Low", "Close", "Volume"])
    return df.set_index("Date")


def fetch_daily_crypto(symbol: str) -> pd.DataFrame | None:
    try:
        return _klines_to_df(_binance_klines(symbol, "1d", 1000))
    except Exception:
        return None


def fetch_4h_crypto(symbol: str) -> pd.DataFrame | None:
    try:
        return _klines_to_df(_binance_klines(symbol, "4h", 1000))
    except Exception:
        return None


def get_data(ticker: str, cfg: "Config"):
    """시장에 맞는 (일봉, 4시간봉) 데이터를 반환."""
    if cfg.market == "crypto" or is_crypto(ticker):
        return fetch_daily_crypto(ticker), fetch_4h_crypto(ticker)
    return fetch_daily(ticker, cfg.daily_period), fetch_intraday_4h(ticker)


def attach_indicators(daily: pd.DataFrame, four: pd.DataFrame | None, cfg: Config) -> pd.DataFrame:
    """일봉 프레임에 일봉200MA, (정렬된) 4h200MA 컬럼을 붙인다."""
    df = daily.copy()
    df["ma_daily"] = df["Close"].rolling(cfg.daily_ma).mean()

    if four is not None and len(four) >= cfg.intraday_ma:
        ma4 = four["Close"].rolling(cfg.intraday_ma).mean().dropna()
        ma4 = ma4.sort_index()
        # 각 일봉 종가 시점 기준, 그 날까지의 마지막 4h-200MA 값을 가져옴
        left = pd.DataFrame({"date": df.index + pd.Timedelta(hours=23, minutes=59)})
        right = pd.DataFrame({"date": ma4.index, "ma_intraday": ma4.values}).sort_values("date")
        merged = pd.merge_asof(left.sort_values("date"), right, on="date", direction="backward")
        df["ma_intraday"] = merged["ma_intraday"].values
    else:
        # 4h 데이터가 부족하면: 4시간봉 200선 ≈ 약 100 거래일 일봉MA로 근사(폴백)
        df["ma_intraday"] = df["Close"].rolling(100).mean()

    return df


def find_recent_golden_cross(df: pd.DataFrame, cfg: Config):
    """4h200MA가 일봉200MA를 상향 돌파한 가장 최근 시점(최근 N거래일 내)."""
    sub = df.dropna(subset=["ma_daily", "ma_intraday"])
    if len(sub) < 5:
        return None
    above = sub["ma_intraday"] > sub["ma_daily"]
    cross_up = above & (~above.shift(1).fillna(False))
    cross_dates = sub.index[cross_up]
    if len(cross_dates) == 0:
        return None
    cutoff = sub.index[-min(cfg.gc_lookback_days, len(sub))]
    recent = cross_dates[cross_dates >= cutoff]
    return recent[-1] if len(recent) else None


def build_setup(df: pd.DataFrame, cross_date, cfg: Config) -> dict | None:
    """피보나치 앵커(저점/고점), 되돌림 비율, 분할매수/손절/익절 가격 산출."""
    loc = df.index.get_loc(cross_date)
    pre = df.iloc[max(0, loc - cfg.pre_cross_lookback): loc + 1]
    post = df.iloc[loc:]
    if pre.empty or post.empty:
        return None

    low = float(pre["Low"].min())
    high = float(post["High"].max())
    rng = high - low
    if rng <= 0:
        return None

    price = float(df["Close"].iloc[-1])
    r_now = (high - price) / rng  # 되돌림 비율(0=고점, 1=저점)

    fib_prices = {r: high - r * rng for r in cfg.fib_show}
    buy_prices = {r: high - r * rng for r in cfg.buy_levels}
    zone_bottom = max(cfg.buy_levels)                 # 0.618 = 매수구간 하단
    stop = high - zone_bottom * rng - 0.02 * rng      # 0.618 라인 살짝 아래(원문 a 방식)
    take_profit = high                                # 문서: 익절은 피보 설정 시의 고점

    return {
        "low": low, "high": high, "range": rng, "price": price, "r_now": r_now,
        "fib_prices": fib_prices, "buy_prices": buy_prices,
        "stop": stop, "take_profit": take_profit, "cross_date": cross_date,
    }


def classify(r_now: float, cfg: Config) -> tuple[str, str]:
    """(라벨, tier) 반환. tier: 'in_zone' | 'approach' | 'deep' | 'no_pullback' | 'invalid'"""
    if r_now < 0:
        return ("🔼 신고가 갱신 중 (되돌림 대기)", "no_pullback")
    if r_now < 0.382:
        return (f"🟡 얕은 조정 {r_now*100:.0f}% (0.382 도달 전)", "approach")
    if r_now <= 0.618:
        return (f"✅ 분할매수 구간 {r_now*100:.0f}% (0.382~0.618)", "in_zone")
    if r_now <= 1.0:
        return (f"🟠 깊은 조정 {r_now*100:.0f}% (0.618 하회·주의)", "deep")
    return (f"🔴 되돌림 {r_now*100:.0f}% (저점 이탈·셋업 무효 가능)", "invalid")


# ── 정밀 분석 지표 (리스크 + 기술 확인) ──────────────────────────────────
def _rsi(close: pd.Series, n: int = 14) -> pd.Series:
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = up / dn.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def _atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    h, l, c = df["High"], df["Low"], df["Close"]
    pc = c.shift(1)
    tr = pd.concat([(h - l), (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def compute_metrics(df: pd.DataFrame, setup: dict, bench_ret: float | None = None) -> dict:
    price, stop, high = setup["price"], setup["stop"], setup["high"]
    r_mult = (high - price) / (price - stop) if price > stop else None
    risk_pct = (price - stop) / price * 100 if price > 0 else None

    atr_s = _atr(df).dropna()
    atr = float(atr_s.iloc[-1]) if len(atr_s) else None
    atr_stop = price - 2 * atr if atr else None

    rsi_s = _rsi(df["Close"]).dropna()
    rsi_v = float(rsi_s.iloc[-1]) if len(rsi_s) else None

    v = df["Volume"]
    vol_ratio = None
    if len(v) >= 60:
        recent = v.tail(10).mean()
        base = v.tail(60).head(50).mean()
        if base > 0:
            vol_ratio = float(recent / base)

    mad = df["ma_daily"].dropna()
    trend_slope = float((mad.iloc[-1] / mad.iloc[-21] - 1) * 100) if len(mad) > 21 else None

    c = df["Close"]
    stock_ret = float((c.iloc[-1] / c.iloc[-61] - 1) * 100) if len(c) > 61 else None
    rs60 = (stock_ret - bench_ret) if (stock_ret is not None and bench_ret is not None) else None

    # 다중 타임프레임: 주봉 추세 (주봉 종가 > 30주선 & 30주선 상승)
    weekly_up = None
    try:
        wk = df["Close"].resample("W").last().dropna()
        wma = wk.rolling(30).mean()
        if wma.notna().sum() > 5:
            weekly_up = bool(wk.iloc[-1] > wma.iloc[-1] and wma.iloc[-1] > wma.iloc[-5])
    except Exception:
        weekly_up = None

    # MA 컨플루언스: 50/100일선이 매수구간(0.382~0.618 가격대) 안에 있나
    conf = []
    zone_hi = setup["high"] - 0.382 * setup["range"]
    zone_lo = setup["high"] - 0.618 * setup["range"]
    for n in (50, 100):
        if len(c) >= n:
            ma_n = float(c.rolling(n).mean().iloc[-1])
            if zone_lo <= ma_n <= zone_hi:
                conf.append(f"{n}일선")

    return {"r_mult": r_mult, "risk_pct": risk_pct, "atr": atr, "atr_stop": atr_stop,
            "rsi": rsi_v, "vol_ratio": vol_ratio, "trend_slope": trend_slope,
            "stock_ret60": stock_ret, "rs60": rs60,
            "weekly_uptrend": weekly_up, "confluence": conf}


def bench_return(market: str, cfg: "Config") -> float | None:
    """상대강도용 벤치마크 60거래일 수익률. 미국=SPY, 한국=코스피지수, 크립토=BTC."""
    try:
        if market == "crypto":
            c = fetch_daily_crypto("BTCUSDT")
            c = c["Close"] if c is not None else None
        else:
            sym = "^KS11" if market == "kr" else "SPY"
            c = fetch_daily(sym, cfg.daily_period)["Close"]
        if c is not None and len(c) > 61:
            return float((c.iloc[-1] / c.iloc[-61] - 1) * 100)
    except Exception:
        return None
    return None


# ======================================================================
# 3) 차트
# ======================================================================

def render_chart(ticker: str, df: pd.DataFrame, setup: dict, label: str, cfg: Config) -> bytes:
    plot = df.tail(cfg.chart_bars).copy()
    plot = plot[["Open", "High", "Low", "Close", "Volume"]]

    add = []
    if df["ma_daily"].tail(cfg.chart_bars).notna().any():
        add.append(mpf.make_addplot(df["ma_daily"].tail(cfg.chart_bars), color="#1f77b4", width=1.3))
    if df["ma_intraday"].tail(cfg.chart_bars).notna().any():
        add.append(mpf.make_addplot(df["ma_intraday"].tail(cfg.chart_bars), color="#ff7f0e", width=1.1))

    fib_lines = list(setup["fib_prices"].values())
    fib_colors = ["#999999", "#2ca02c", "#9467bd", "#2ca02c", "#999999"]

    style = mpf.make_mpf_style(base_mpf_style="yahoo", gridstyle=":", facecolor="white")
    fig, axes = mpf.plot(
        plot, type="candle", style=style, addplot=add, volume=False,
        returnfig=True, figsize=(11, 6.2), tight_layout=True,
        hlines=dict(hlines=fib_lines, colors=fib_colors, linewidths=0.9, linestyle="--"),
        datetime_format="%m/%d", xrotation=0,
    )
    ax = axes[0]
    x_right = len(plot) - 1
    for r, p in setup["fib_prices"].items():
        ax.text(x_right, p, f"  {r:.3f}  {p:,.1f}", va="center", ha="left",
                fontsize=8, color="#444")
    ax.axhline(setup["take_profit"], color="#d62728", lw=0.8, ls="-", alpha=0.5)
    ax.axhline(setup["stop"], color="#111111", lw=0.8, ls="-", alpha=0.5)
    ax.text(0, setup["take_profit"], " Target(high) ", fontsize=8, color="#d62728", va="bottom")
    ax.text(0, setup["stop"], " Stop ", fontsize=8, color="#111", va="top")

    cross = setup["cross_date"]
    if cross in plot.index:
        cx = plot.index.get_loc(cross)
        ax.axvline(cx, color="#ff7f0e", lw=1.0, ls=":", alpha=0.8)
        ax.text(cx, plot["High"].max(), "GC", fontsize=9, color="#ff7f0e", ha="center", va="bottom")

    # 차트 제목은 폰트 없는 서버에서도 깨지지 않도록 ASCII만 사용
    ax.set_title(f"{ticker}   retrace {setup['r_now']*100:.0f}%   price {fmt_price(setup['price'], ticker)}   (MA200d=blue, MA200/4h=orange)",
                 fontsize=11, loc="left")

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=120, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf.read()


# ======================================================================
# 4) 스캔
# ======================================================================

def scan_one(ticker: str, cfg: Config, bench_ret: float | None = None) -> dict | None:
    daily, four = get_data(ticker, cfg)
    if daily is None or len(daily) < cfg.daily_ma + 5:
        return None
    df = attach_indicators(daily, four, cfg)

    cross = find_recent_golden_cross(df, cfg)
    if cross is None:
        return None

    setup = build_setup(df, cross, cfg)
    if setup is None:
        return None

    label, tier = classify(setup["r_now"], cfg)
    r_now = setup["r_now"]
    days_since = int((df.index[-1] - setup["cross_date"]).days)

    # 매수구간(눌림목) → 풀 카드 (차트 + 정밀 분석)
    if cfg.zone_min <= r_now <= cfg.zone_max:
        img = render_chart(ticker, df, setup, label, cfg)
        metrics = compute_metrics(df, setup, bench_ret)
        return {"ticker": ticker, "tier": tier, "stage": "buy", "label": label,
                "price": setup["price"], "df": df, "setup": setup, "img": img,
                "metrics": metrics, "days_since_cross": days_since}

    # 아직 눌림 전(상승 중) → 생애주기 관찰 단계 (갓 크로스 / 상승 대기)
    if r_now < cfg.zone_min:
        weekly_up = None
        try:
            wk = df["Close"].resample("W").last().dropna()
            wma = wk.rolling(30).mean()
            if wma.notna().sum() > 5:
                weekly_up = bool(wk.iloc[-1] > wma.iloc[-1] and wma.iloc[-1] > wma.iloc[-5])
        except Exception:
            weekly_up = None
        stage = "fresh" if days_since <= cfg.fresh_days else "wait"
        return {"ticker": ticker, "tier": "watch", "stage": stage, "label": label,
                "price": setup["price"], "df": None, "setup": setup,
                "r_now": r_now, "days_since_cross": days_since,
                "weekly_uptrend": weekly_up}

    # 되돌림이 너무 깊음(>zone_max) → 제외
    return None


def scan_all(cfg: Config) -> list[dict]:
    out = []
    universe = load_universe(cfg.market)
    bench = bench_return(cfg.market, cfg)  # 상대강도 기준(지수 60일 수익률)
    print(f"벤치마크 60일 수익률: {bench:.1f}%" if bench is not None else "벤치마크 수익률 없음")
    for i, t in enumerate(universe, 1):
        try:
            res = scan_one(t, cfg, bench)
            if res:
                out.append(res)
                print(f"[{i}/{len(universe)}] {t}: {res['tier']} · {res.get('label','')}")
            else:
                print(f"[{i}/{len(universe)}] {t}: -")
        except Exception as e:
            print(f"[{i}/{len(universe)}] {t}: ERROR {e}")
        time.sleep(cfg.sleep_between)
    return out


# ======================================================================
# 5) 이메일 / 리포트
# ======================================================================

def fmt_setup_row(c: dict) -> str:
    s = c["setup"]
    bp = s["buy_prices"]
    t = c["ticker"]
    return (
        f"<div style='margin:6px 0;font:13px/1.6 -apple-system,Segoe UI,sans-serif'>"
        f"&nbsp;&nbsp;분할매수 0.382 <b>{fmt_price(bp[0.382], t)}</b> · "
        f"0.5 <b>{fmt_price(bp[0.5], t)}</b> · 0.618 <b>{fmt_price(bp[0.618], t)}</b><br>"
        f"&nbsp;&nbsp;익절(고점) {fmt_price(s['take_profit'], t)} · 손절 {fmt_price(s['stop'], t)} · "
        f"골든크로스 {pd.Timestamp(s['cross_date']).date()}"
        f"</div>"
    )


def build_email(results: list[dict], cfg: Config) -> MIMEMultipart:
    charted = [r for r in results if r.get("img")]
    watch = [r for r in results if r["tier"] == "watch"]
    # 되돌림 깊은 순(매수구간 진입한 것 우선)
    charted.sort(key=lambda r: r["setup"]["r_now"], reverse=False)

    msg = MIMEMultipart("related")
    today = datetime.now().strftime("%Y-%m-%d")
    mlabel = MARKET_LABEL.get(cfg.market, cfg.market)
    msg["Subject"] = f"[눌림목·{mlabel}] {today} · 매수구간 {len(charted)}종목"
    msg["From"] = cfg.gmail_address
    msg["To"] = cfg.email_to

    html = [f"<div style='font:14px/1.6 -apple-system,Segoe UI,sans-serif;color:#222'>"]
    html.append(f"<h2 style='margin:0 0 4px'>{mlabel} · 골든크로스 후 피보나치 눌림목 스캔</h2>")
    html.append(f"<div style='color:#888;margin-bottom:14px'>{today} · 유니버스 {len(load_universe(cfg.market))}종목 · "
                f"차트 대상 {len(charted)} · 관찰 {len(watch)}</div>")

    if not charted:
        html.append("<p>오늘은 분할매수 구간(0.382~0.618)에 들어온 종목이 없음.</p>")

    for idx, c in enumerate(charted):
        cid = f"chart{idx}"
        html.append(
            f"<div style='border-top:1px solid #eee;padding-top:12px;margin-top:12px'>"
            f"<div style='font-size:15px;font-weight:700'>{display_name(c['ticker'])} "
            f"<span style='font-weight:500;color:#555'>({c['ticker']}) · {c['label']} · 현재가 {fmt_price(c['price'], c['ticker'])}</span></div>"
            f"{fmt_setup_row(c)}"
            f"<img src='cid:{cid}' style='width:100%;max-width:760px;border:1px solid #eee;border-radius:6px'/>"
            f"</div>"
        )
        img = MIMEImage(c["img"], _subtype="png")
        img.add_header("Content-ID", f"<{cid}>")
        img.add_header("Content-Disposition", "inline", filename=f"{c['ticker']}.png")
        msg.attach(img)

    if watch:
        names = ", ".join(display_name(w["ticker"]) for w in watch)
        html.append(f"<div style='border-top:1px solid #eee;padding-top:12px;margin-top:16px;color:#666'>"
                    f"<b>관찰 대상</b>(골든크로스 O, 눌림 대기): {names}</div>")

    html.append("<div style='color:#aaa;font-size:11px;margin-top:18px'>"
                "본 메일은 조건 충족 종목을 찾아주는 스크리너 알림이며 투자 조언이 아님. "
                "진입·손절·익절은 본인 판단. 데이터: Yahoo Finance.</div></div>")

    msg.attach(MIMEText("".join(html), "html", "utf-8"))
    return msg


def save_local(results: list[dict], cfg: Config):
    out_dir = os.path.join(cfg.out_dir, cfg.market)  # 시장별로 분리 저장
    os.makedirs(out_dir, exist_ok=True)
    charted = [r for r in results if r.get("img")]
    for c in charted:
        with open(os.path.join(out_dir, f"{c['ticker'].replace('.', '_')}.png"), "wb") as f:
            f.write(c["img"])
    # 메일 본문도 html로 저장
    msg = build_email(results, cfg)
    html_part = next((p for p in msg.walk() if p.get_content_type() == "text/html"), None)
    if html_part:
        with open(os.path.join(out_dir, "report.html"), "w", encoding="utf-8") as f:
            f.write(html_part.get_payload(decode=True).decode("utf-8"))
    print(f"[dry-run] {out_dir}/ 에 차트 {len(charted)}장 + report.html 저장")


def send_email(results: list[dict], cfg: Config):
    if not cfg.gmail_address or not cfg.gmail_app_password:
        print("⚠️ GMAIL_ADDRESS / GMAIL_APP_PASSWORD 환경변수 없음 → 로컬 저장으로 대체")
        save_local(results, cfg)
        return
    msg = build_email(results, cfg)
    with smtplib.SMTP_SSL(cfg.smtp_host, cfg.smtp_port) as server:
        server.login(cfg.gmail_address, cfg.gmail_app_password)
        server.sendmail(cfg.gmail_address, [cfg.email_to], msg.as_string())
    print(f"✅ 메일 발송 완료 → {cfg.email_to}")


# ======================================================================
# 6) main
# ======================================================================

def main():
    cfg = Config()
    print(f"스캔 시작 · market={cfg.market} · dry_run={cfg.dry_run}")
    results = scan_all(cfg)
    if cfg.dry_run:
        save_local(results, cfg)
    else:
        send_email(results, cfg)
    print("끝.")


if __name__ == "__main__":
    main()
