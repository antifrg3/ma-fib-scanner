#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
flows.py — 시장별 수급·포지션 데이터 수집 및 해석
─────────────────────────────────────────────────────────────────────────
정찰(recon_flows.py) 결과 가용 확인된 항목만 사용한다.

① BTC (바이낸스 선물 — 7/7 가용)
   펀딩비 · 미결제약정(OI) · 롱숏 계정비율 · 대형트레이더 비율 · 테이커 비율
   → 선물 포지션 수급. 과열/쏠림과 신규자금 유입 여부를 읽는다.

②③ 나스닥 / S&P500 (야후 — 8/8 가용)
   VIX · 10년물 금리 · 달러인덱스 · HYG(하이일드) · 지수/ETF 거래량
   → 진짜 자금흐름(ETF 순유입)은 무료 소스가 없어 '위험선호 환경'으로 대용.

⚠️ 코스피는 pykrx(투자자별 순매수)가 막혀 이번 범위에서 제외.
"""
import json
import os
import urllib.request
from dataclasses import dataclass, field
from typing import Optional, List

import numpy as np
import pandas as pd

# 바이낸스 선물 API는 미국 서버(GitHub Actions)에서 지역 차단되므로
# CoinGecko를 경유해 바이낸스 선물 데이터를 받는다(미국에서도 정상 작동, 키 불필요).
CG = "https://api.coingecko.com/api/v3"


LAST_ERROR = {"btc": ""}


def _get(url: str, timeout: int = 15):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        LAST_ERROR["btc"] = str(e)[:120]
        return None


# ══════════════════════════════════════════════════════════════════════════
# 신호 판정 공통
# ══════════════════════════════════════════════════════════════════════════
@dataclass
class Metric:
    label: str
    value: str          # 표시용 문자열
    signal: str         # bull | bear | neutral | warn
    note: str = ""      # 해석 한 줄


SIGNAL_CLS = {"bull": "fl-bull", "bear": "fl-bear",
              "neutral": "fl-neutral", "warn": "fl-warn"}
SIGNAL_DOT = {"bull": "🟢", "bear": "🔴", "neutral": "🟡", "warn": "⚠️"}


@dataclass
class MarketFlow:
    key: str            # btc | nasdaq | sp500
    name: str
    verdict: str        # bull | bear | neutral
    headline: str       # 요약 한 줄
    metrics: List[Metric] = field(default_factory=list)


def _verdict(metrics: List[Metric]) -> str:
    """개별 지표 신호를 종합해 시장 판정."""
    b = sum(1 for m in metrics if m.signal == "bull")
    r = sum(1 for m in metrics if m.signal == "bear")
    if b >= r + 2:
        return "bull"
    if r >= b + 2:
        return "bear"
    return "neutral"


def _state_path(state_dir: str) -> str:
    return os.path.join(state_dir, "flows_state.json")


def _load_prev(state_dir: str):
    """직전 실행의 OI·가격. CoinGecko 무료는 이력을 안 주므로 자체 저장해 비교한다."""
    try:
        with open(_state_path(state_dir), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        # 배포된 사이트에서 읽기(로컬에 파일이 없을 때)
        d = _get("https://antifrg3.github.io/ma-fib-scanner/flows_state.json", timeout=10)
        return d if isinstance(d, dict) else None


def _save_state(state_dir: str, data: dict):
    try:
        os.makedirs(state_dir, exist_ok=True)
        with open(_state_path(state_dir), "w", encoding="utf-8") as f:
            json.dump(data, f)
    except Exception:
        pass



# ══════════════════════════════════════════════════════════════════════════
# ① BTC — 선물 포지션 수급
# ══════════════════════════════════════════════════════════════════════════
def fetch_btc_flow(symbol: str = "BTCUSDT", state_dir: str = "site") -> Optional[MarketFlow]:
    """CoinGecko 경유로 바이낸스 선물 펀딩비·미결제약정을 받아 해석.

    바이낸스 선물 API를 직접 호출하면 미국 서버에서 지역 차단되므로 CoinGecko를 쓴다.
    무료 티어는 현재값만 주므로, OI 추세는 이전 실행값을 저장해 비교한다.
    """
    ms: List[Metric] = []

    d = _get(f"{CG}/derivatives/exchanges/binance_futures"
             f"?include_tickers=unexpired")
    tick = None
    if isinstance(d, dict):
        for t in d.get("tickers", []):
            if t.get("symbol") == symbol and t.get("contract_type") == "perpetual":
                tick = t
                break
    if tick is None:
        err = LAST_ERROR.get("btc") or "BTCUSDT 무기한 항목을 찾지 못함"
        return MarketFlow("btc", "비트코인", "neutral",
                          "데이터 수집 실패 — 아래 사유 확인",
                          [Metric("수집 오류", err, "warn",
                                  "CoinGecko 파생상품 응답 확인 필요")])

    # ── 펀딩비 (CoinGecko는 % 단위로 제공) ──
    fr = tick.get("funding_rate")
    if fr is not None:
        fr = float(fr)
        if fr >= 0.03:
            sig, note = "warn", "롱 과열 — 되돌림 위험"
        elif fr <= -0.01:
            sig, note = "bull", "숏 과열 — 숏스퀴즈 여지"
        elif fr > 0:
            sig, note = "neutral", "롱 소폭 우위(정상 범위)"
        else:
            sig, note = "neutral", "숏 소폭 우위"
        ms.append(Metric("펀딩비", f"{fr:+.4f}%", sig, note))

    # ── 미결제약정 + 직전 실행 대비 변화 ──
    oi = tick.get("open_interest_usd")
    price = tick.get("last")
    if oi is not None:
        oi = float(oi)
        prev = _load_prev(state_dir)
        oi_txt = f"${oi/1e9:.2f}B"
        sig, note = "neutral", "직전 기록 없음(다음 갱신부터 추세 표시)"
        if prev and prev.get("oi"):
            oi_chg = (oi / float(prev["oi"]) - 1) * 100
            px_chg = 0.0
            if price and prev.get("price"):
                px_chg = (float(price) / float(prev["price"]) - 1) * 100
            # 가격·OI 조합 해석
            if px_chg > 0 and oi_chg > 0:
                sig, note = "bull", "가격↑ + OI↑ = 신규 매수 유입(건강한 상승)"
            elif px_chg > 0 and oi_chg <= 0:
                sig, note = "neutral", "가격↑ + OI↓ = 숏커버 반등(지속력 약함)"
            elif px_chg <= 0 and oi_chg > 0:
                sig, note = "bear", "가격↓ + OI↑ = 신규 매도 유입(하락 압력)"
            else:
                sig, note = "neutral", "가격↓ + OI↓ = 롱 청산 진행(바닥 탐색)"
            oi_txt += f" · 직전 대비 {oi_chg:+.1f}% (가격 {px_chg:+.1f}%)"
        ms.append(Metric("미결제약정", oi_txt, sig, note))
        _save_state(state_dir, {"oi": oi, "price": price})

    # ── 베이시스(선물-현물 괴리) ── 과열/저평가 참고
    basis = tick.get("index_basis_percentage")
    if basis is not None:
        b = float(basis)
        if b <= -0.1:
            sig, note = "bull", "선물이 현물보다 저평가 — 매수 심리 약함"
        elif b >= 0.1:
            sig, note = "warn", "선물 프리미엄 — 롱 과열 참고"
        else:
            sig, note = "neutral", "현물과 괴리 작음"
        ms.append(Metric("베이시스", f"{b:+.3f}%", sig, note))

    # ── 24시간 거래량 ──
    vol = tick.get("h24_volume")
    if vol:
        ms.append(Metric("24h 거래량", f"${float(vol)/1e9:.2f}B", "neutral",
                         "선물 거래 활성도"))

    if not ms:
        err = LAST_ERROR.get("btc") or "알 수 없는 오류"
        return MarketFlow("btc", "비트코인", "neutral",
                          "데이터 수집 실패 — 아래 사유 확인",
                          [Metric("수집 오류", err, "warn", "CoinGecko 응답 확인 필요")])

    v = _verdict(ms)
    head = {"bull": "매수 수급 우위", "bear": "매도 수급 우위",
            "neutral": "중립 — 뚜렷한 쏠림 없음"}[v]
    return MarketFlow("btc", "비트코인", v, head, ms)


# ══════════════════════════════════════════════════════════════════════════
# ②③ 미국 지수 — 위험선호 환경
# ══════════════════════════════════════════════════════════════════════════
def _scalar(x):
    """pandas 값 → float. Series/배열이면 첫 원소. NaN이면 None."""
    try:
        if hasattr(x, "item"):
            x = x.item()
        elif hasattr(x, "iloc"):
            x = x.iloc[0]
        v = float(x)
        return None if np.isnan(v) else v
    except Exception:
        return None


def _yf_last(sym: str, period: str = "2mo"):
    """(현재값, 전일대비%, 거래량배수) — 실패 시 None.
       야후는 장 시작 전/휴장일에 마지막 행이 NaN인 경우가 있어 반드시 정리한다."""
    try:
        import yfinance as yf
        df = yf.download(sym, period=period, progress=False, auto_adjust=True)
        if df is None or df.empty:
            return None
        # 멀티인덱스 컬럼(단일 심볼인데 2단으로 오는 경우) 평탄화
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        if "Close" not in df.columns:
            return None
        df = df[df["Close"].notna()]          # NaN 행 제거 ← nan 표시의 원인
        if len(df) < 2:
            return None
        last = _scalar(df["Close"].iloc[-1])
        prev = _scalar(df["Close"].iloc[-2])
        if last is None or prev is None or prev == 0:
            return None
        chg = (last / prev - 1) * 100
        volx = None
        if "Volume" in df.columns:
            vl = _scalar(df["Volume"].iloc[-1])
            va = float(df["Volume"].tail(20).mean())
            if vl is not None and va and va > 0:
                volx = vl / va
        return last, chg, volx
    except Exception:
        return None


def fetch_us_flow(key: str) -> Optional[MarketFlow]:
    """key: nasdaq | sp500. 공통 매크로 + 해당 지수 고유 항목."""
    idx_sym, etf_sym, name = {
        "nasdaq": ("^IXIC", "QQQ", "나스닥"),
        "sp500":  ("^GSPC", "SPY", "S&P 500"),
    }[key]

    ms: List[Metric] = []

    # 지수 자체
    r = _yf_last(idx_sym)
    if r:
        last, chg, _ = r
        sig = "bull" if chg > 0.3 else ("bear" if chg < -0.3 else "neutral")
        ms.append(Metric("지수", f"{last:,.2f} ({chg:+.2f}%)", sig, ""))

    # ETF 거래량 — 자금 이동 대용
    r = _yf_last(etf_sym)
    if r:
        last, chg, volx = r
        if volx is not None:
            if volx >= 1.5:
                sig, note = "warn", "거래량 급증 — 자금 이동/변동성 확대"
            elif volx <= 0.7:
                sig, note = "neutral", "거래 한산 — 방향성 약함"
            else:
                sig, note = "neutral", "평상 수준"
            ms.append(Metric(f"{etf_sym} 거래량", f"평균 대비 {volx:.2f}배", sig, note))

    # VIX — 공포
    r = _yf_last("^VIX")
    if r:
        vix, vchg, _ = r
        if vix >= 25:
            sig, note = "bear", "공포 구간 — 위험자산 회피"
        elif vix >= 20:
            sig, note = "warn", "불안 상승"
        elif vix <= 15:
            sig, note = "bull", "안정 — 위험선호"
        else:
            sig, note = "neutral", "보통"
        if vchg >= 8:
            note += f" (급등 {vchg:+.1f}% — 경계)"
            sig = "warn" if sig == "bull" else sig
        ms.append(Metric("VIX", f"{vix:.2f} ({vchg:+.1f}%)", sig, note))

    # 10년물 금리 — 밸류에이션 압박
    r = _yf_last("^TNX")
    if r:
        y, ychg, _ = r
        sig = "bear" if ychg > 1.5 else ("bull" if ychg < -1.5 else "neutral")
        note = ("금리 급등 — 주식 압박" if ychg > 1.5
                else "금리 하락 — 주식 우호" if ychg < -1.5 else "안정")
        ms.append(Metric("10년물 금리", f"{y:.2f}% ({ychg:+.2f}%)", sig, note))

    # 달러인덱스 — 강달러는 위험자산 압박
    r = _yf_last("DX-Y.NYB")
    if r:
        d, dchg, _ = r
        sig = "bear" if dchg > 0.4 else ("bull" if dchg < -0.4 else "neutral")
        note = ("강달러 — 위험자산 압박" if dchg > 0.4
                else "약달러 — 위험자산 우호" if dchg < -0.4 else "보합")
        ms.append(Metric("달러인덱스", f"{d:.2f} ({dchg:+.2f}%)", sig, note))

    # HYG — 신용 위험선호
    r = _yf_last("HYG")
    if r:
        h, hchg, _ = r
        sig = "bull" if hchg > 0.2 else ("bear" if hchg < -0.2 else "neutral")
        note = ("신용 위험선호 — 위험자산 우호" if hchg > 0.2
                else "신용 경계 — 위험자산 부담" if hchg < -0.2 else "보합")
        ms.append(Metric("하이일드(HYG)", f"{h:.2f} ({hchg:+.2f}%)", sig, note))

    if not ms:
        return None
    v = _verdict(ms)
    head = {"bull": "위험선호 우호", "bear": "위험회피 우세",
            "neutral": "중립 — 혼조"}[v]
    return MarketFlow(key, name, v, head, ms)


def fetch_all(state_dir: str = "site") -> List[MarketFlow]:
    out = []
    for f in (fetch_btc_flow(state_dir=state_dir),
              fetch_us_flow("nasdaq"), fetch_us_flow("sp500")):
        if f is not None:
            out.append(f)
    return out
