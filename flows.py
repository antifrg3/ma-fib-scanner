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
import urllib.request
from dataclasses import dataclass, field
from typing import Optional, List

import numpy as np
import pandas as pd

# 선물 API 도메인 — 앞에서부터 시도(일부 서버에서 지역 차단될 수 있음)
FAPI_HOSTS = [
    "https://fapi.binance.com",
    "https://fapi1.binance.com",
    "https://fapi2.binance.com",
]
FAPI = FAPI_HOSTS[0]


LAST_ERROR = {"btc": ""}


def _get(url: str, timeout: int = 10):
    """단일 URL 요청. 선물 도메인이면 대체 호스트까지 순차 시도."""
    candidates = [url]
    for h in FAPI_HOSTS:
        if url.startswith(h):
            path = url[len(h):]
            candidates = [alt + path for alt in FAPI_HOSTS]
            break
    last_err = ""
    for u in candidates:
        try:
            req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode())
        except Exception as e:
            last_err = str(e)[:120]
            continue
    LAST_ERROR["btc"] = last_err
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


# ══════════════════════════════════════════════════════════════════════════
# ① BTC — 선물 포지션 수급
# ══════════════════════════════════════════════════════════════════════════
def fetch_btc_flow(symbol: str = "BTCUSDT") -> Optional[MarketFlow]:
    ms: List[Metric] = []

    # 펀딩비 — 현재 + 최근 평균
    prem = _get(f"{FAPI}/fapi/v1/premiumIndex?symbol={symbol}")
    hist = _get(f"{FAPI}/fapi/v1/fundingRate?symbol={symbol}&limit=24")
    if prem and "lastFundingRate" in prem:
        fr = float(prem["lastFundingRate"]) * 100
        avg = None
        if isinstance(hist, list) and hist:
            avg = float(np.mean([float(x["fundingRate"]) for x in hist])) * 100
        # 해석: 과열은 역방향 재료. 0.03%↑ 롱 과열 / -0.01%↓ 숏 과열
        if fr >= 0.03:
            sig, note = "warn", "롱 과열 — 되돌림 위험"
        elif fr <= -0.01:
            sig, note = "bull", "숏 과열 — 숏스퀴즈 여지"
        elif fr > 0:
            sig, note = "neutral", "롱 소폭 우위(정상 범위)"
        else:
            sig, note = "neutral", "숏 소폭 우위"
        val = f"{fr:+.4f}%" + (f" (24회 평균 {avg:+.4f}%)" if avg is not None else "")
        ms.append(Metric("펀딩비", val, sig, note))

    # 미결제약정 — 7일 변화 + 가격 변화 조합
    oi_hist = _get(f"{FAPI}/futures/data/openInterestHist?symbol={symbol}&period=1d&limit=8")
    kl = _get(f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=1d&limit=8")
    if isinstance(oi_hist, list) and len(oi_hist) >= 2:
        o0, o1 = float(oi_hist[0]["sumOpenInterest"]), float(oi_hist[-1]["sumOpenInterest"])
        oi_chg = (o1 / o0 - 1) * 100 if o0 else 0.0
        px_chg = 0.0
        if isinstance(kl, list) and len(kl) >= 2:
            px_chg = (float(kl[-1][4]) / float(kl[0][4]) - 1) * 100
        # 고전적 해석: 가격↑+OI↑=신규 매수(강세) · 가격↑+OI↓=숏커버(약함)
        #             가격↓+OI↑=신규 매도(약세) · 가격↓+OI↓=롱청산(바닥 신호)
        if px_chg > 0 and oi_chg > 0:
            sig, note = "bull", "가격↑ + OI↑ = 신규 매수 유입(건강한 상승)"
        elif px_chg > 0 and oi_chg <= 0:
            sig, note = "neutral", "가격↑ + OI↓ = 숏커버 반등(지속력 약함)"
        elif px_chg <= 0 and oi_chg > 0:
            sig, note = "bear", "가격↓ + OI↑ = 신규 매도 유입(하락 압력)"
        else:
            sig, note = "neutral", "가격↓ + OI↓ = 롱 청산 진행(바닥 탐색)"
        ms.append(Metric("미결제약정(7일)", f"{oi_chg:+.1f}% · 가격 {px_chg:+.1f}%", sig, note))

    # 롱숏 계정비율(개인) vs 대형트레이더 — 엇갈리면 주목
    lsr = _get(f"{FAPI}/futures/data/globalLongShortAccountRatio?symbol={symbol}&period=1d&limit=2")
    top = _get(f"{FAPI}/futures/data/topLongShortPositionRatio?symbol={symbol}&period=1d&limit=2")
    r_all = float(lsr[-1]["longShortRatio"]) if isinstance(lsr, list) and lsr else None
    r_top = float(top[-1]["longShortRatio"]) if isinstance(top, list) and top else None
    if r_all is not None:
        sig = "warn" if r_all >= 2.0 else ("neutral" if r_all >= 1.0 else "bull")
        note = ("개인 롱 쏠림 — 역방향 주의" if r_all >= 2.0
                else "롱 우위" if r_all >= 1.0 else "숏 우위 — 반등 여지")
        ms.append(Metric("롱숏비(개인)", f"{r_all:.2f}", sig, note))
    if r_top is not None and r_all is not None:
        diverge = (r_top - r_all)
        if abs(diverge) >= 0.3:
            sig = "bull" if diverge > 0 else "bear"
            note = ("큰손이 개인보다 롱 — 주목" if diverge > 0
                    else "큰손이 개인보다 숏 — 경계")
        else:
            sig, note = "neutral", "큰손·개인 방향 일치(판단 재료 약함)"
        ms.append(Metric("롱숏비(큰손)", f"{r_top:.2f} (개인차 {diverge:+.2f})", sig, note))

    # 테이커 매수/매도 — 공격적 주문 방향
    tk = _get(f"{FAPI}/futures/data/takerlongshortRatio?symbol={symbol}&period=1d&limit=3")
    if isinstance(tk, list) and tk:
        b = float(tk[-1]["buySellRatio"])
        sig = "bull" if b >= 1.05 else ("bear" if b <= 0.95 else "neutral")
        note = ("공격적 매수 우위" if b >= 1.05
                else "공격적 매도 우위" if b <= 0.95 else "균형")
        ms.append(Metric("테이커 매수/매도", f"{b:.2f}", sig, note))

    if not ms:
        # 전부 실패 — 원인을 표시해 진단 가능하게(서버 지역 차단 등)
        err = LAST_ERROR.get("btc") or "알 수 없는 오류"
        return MarketFlow("btc", "비트코인", "neutral",
                          "데이터 수집 실패 — 아래 사유 확인",
                          [Metric("수집 오류", err, "warn",
                                  "바이낸스 선물 API 접근 불가(서버 지역 제한 가능)")])
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


def fetch_all() -> List[MarketFlow]:
    out = []
    for f in (fetch_btc_flow(), fetch_us_flow("nasdaq"), fetch_us_flow("sp500")):
        if f is not None:
            out.append(f)
    return out
