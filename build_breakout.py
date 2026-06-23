#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
돌파 스윙 스캐너 (Qullamaggie 스타일) → site/breakout.html
- 큰 상승(스테이지1) → 변동성 수축 베이스(스테이지2) → 종가 피벗 돌파(스테이지3)
- 데이터/테마/사이징/탭/배포는 ma_fib_scanner + build_site 의 인프라를 그대로 재사용.
- build_site.py 가 먼저 돌아 site/ 를 만든 뒤 실행되어야 함(같은 워크플로 다음 스텝).
"""
import io
import os
from datetime import datetime

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import mplfinance as mpf

import ma_fib_scanner as s
import build_site as bs

# ── 탐지 파라미터 ────────────────────────────────────────────────────────
MOVE_LOOKBACK = 90       # 선행 상승 탐색 창(거래일)
MIN_MOVE = 0.30          # 최소 선행 상승 +30%
BASE_MIN, BASE_MAX = 8, 50   # 베이스 기간(거래일) = 약 2주~2.5달
PIVOT_NEAR = 0.06        # 피벗 6% 이내 = '셋업 형성'(관찰)
MAX_EXTENDED = 0.12      # 돌파 후 피벗 대비 +12% 넘으면 과확장 → 제외
MIN_HISTORY = 130
CHART_BARS = 160


def _sma(c, n):
    return c.rolling(n).mean()


def _adr(df, n=20):
    return ((df["High"] / df["Low"] - 1) * 100).rolling(n).mean()


def detect_breakout(daily: pd.DataFrame, bench_ret):
    """일봉 데이터에서 돌파 셋업 탐지. 후보면 dict, 아니면 None."""
    try:
        if daily is None or len(daily) < MIN_HISTORY:
            return None
        df = daily[["Open", "High", "Low", "Close", "Volume"]].copy()
        c, h, l, v = df["Close"], df["High"], df["Low"], df["Volume"]
        price = float(c.iloc[-1])

        # 추세 전제: 50일선 위
        ma10, ma20, ma50 = _sma(c, 10), _sma(c, 20), _sma(c, 50)
        if np.isnan(ma50.iloc[-1]) or price < ma50.iloc[-1]:
            return None
        ma_aligned = bool(price > ma10.iloc[-1] > ma20.iloc[-1] > ma50.iloc[-1])

        # 스테이지1: 최근 창에서 선행 상승(저점→고점 +30%). 당일 봉은 피크 탐색에서 제외.
        win = df.iloc[-MOVE_LOOKBACK:]
        hi_ex = win["High"].iloc[:-1]
        peak_idx = hi_ex.idxmax()
        peak = float(hi_ex.max())
        pre = win.loc[:peak_idx]
        if len(pre) < 5:
            return None
        pre_low = float(pre["Low"].min())
        prior_move = (peak / pre_low - 1) if pre_low > 0 else 0
        if prior_move < MIN_MOVE:
            return None

        # 스테이지2: 피크 이후 베이스(수축 조정)
        base = df.loc[peak_idx:]
        base_len = len(base) - 1
        if base_len < BASE_MIN or base_len > BASE_MAX:
            return None
        pivot = float(base["High"].iloc[:-1].max())   # 베이스 고점(오늘 제외) = 돌파선
        base_low = float(base["Low"].min())

        # 변동성 수축 (ADR now vs 베이스 직전)
        adr = _adr(df)
        adr_now = float(adr.iloc[-1]) if not np.isnan(adr.iloc[-1]) else None
        seg = adr.iloc[-(base_len + 20):-base_len] if len(adr) > base_len + 20 else adr.iloc[:-base_len]
        adr_prior = float(np.nanmean(seg)) if len(seg) else None
        contraction = (adr_now / adr_prior) if (adr_now and adr_prior) else None

        # 거래량 마름
        vol_recent = float(v.iloc[-10:].mean())
        seg_v = v.iloc[-(base_len + 20):-base_len] if len(v) > base_len + 20 else v.iloc[:-base_len]
        vol_prior = float(seg_v.mean()) if len(seg_v) else None
        vol_ratio = (vol_recent / vol_prior) if vol_prior else None

        # 손절(베이스 저점) + 손절폭
        stop = base_low
        risk_pct = ((pivot - stop) / pivot * 100) if pivot > stop else None

        # 상대강도(60일)
        stock_ret = float((c.iloc[-1] / c.iloc[-61] - 1) * 100) if len(c) > 61 else None
        rs = (stock_ret - bench_ret) if (stock_ret is not None and bench_ret is not None) else None

        # 스테이지3: 돌파 여부
        broke = price > pivot
        dist = (pivot / price - 1) * 100      # +면 아직 피벗 아래
        if broke:
            if (price / pivot - 1) > MAX_EXTENDED:   # 너무 멀리 가버림 → 추격 금지
                return None
            stage = "breakout"
        elif abs(dist) <= PIVOT_NEAR * 100:
            stage = "forming"
        else:
            return None

        return {
            "stage": stage, "price": price, "pivot": pivot, "stop": stop,
            "prior_move": prior_move * 100, "base_len": base_len,
            "adr_now": adr_now, "contraction": contraction, "vol_ratio": vol_ratio,
            "risk_pct": risk_pct, "rs": rs, "dist": dist, "ma_aligned": ma_aligned,
            "ma": (float(ma10.iloc[-1]), float(ma20.iloc[-1]), float(ma50.iloc[-1])),
            "df": df,
        }
    except Exception:
        return None


def render_chart(ticker, df, setup):
    plot = df.tail(CHART_BARS).copy()
    c = plot["Close"]
    add = [
        mpf.make_addplot(c.rolling(10).mean(), color="#5FB89B", width=1.0),
        mpf.make_addplot(c.rolling(20).mean(), color="#C8A24B", width=1.0),
        mpf.make_addplot(c.rolling(50).mean(), color="#3B8BD4", width=1.1),
    ]
    style = mpf.make_mpf_style(base_mpf_style="yahoo", gridstyle=":", facecolor="white")
    fig, axes = mpf.plot(
        plot, type="candle", style=style, addplot=add, volume=False,
        returnfig=True, figsize=(11, 6.0), tight_layout=True,
        hlines=dict(hlines=[setup["pivot"], setup["stop"]],
                    colors=["#D8714F", "#111111"], linewidths=1.0, linestyle="--"),
        datetime_format="%m/%d", xrotation=0,
    )
    ax = axes[0]
    ax.text(0, setup["pivot"], " Pivot ", fontsize=8, color="#D8714F", va="bottom")
    ax.text(0, setup["stop"], " Stop ", fontsize=8, color="#111", va="top")
    state = "BREAKOUT" if setup["stage"] == "breakout" else "SETUP"
    ax.set_title(
        f"{ticker}   {state}   price {s.fmt_price(setup['price'], ticker)}   "
        f"prior +{setup['prior_move']:.0f}%   base {setup['base_len']}d   (MA10/20/50)",
        fontsize=11, loc="left")
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=120, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf.read()


# ── 스캔 ─────────────────────────────────────────────────────────────────
def scan_market(market: str):
    cfg = s.Config()
    cfg.market = market
    bench = s.bench_return(market, cfg)
    out = []
    for t in s.load_universe(market):
        try:
            daily, _four = s.get_data(t, cfg)
            res = detect_breakout(daily, bench)
            if res is None:
                continue
            res["ticker"] = t
            if res["stage"] == "breakout":
                res["img"] = render_chart(t, res["df"], res)
            out.append(res)
        except Exception:
            continue
    return out


# ── HTML ─────────────────────────────────────────────────────────────────
def _sig(good, bad):
    return "sig-good" if good else ("sig-bad" if bad else "")


def panel_html(c):
    fp = lambda x: s.fmt_price(x, c["ticker"])
    pm = c["prior_move"]
    con = c["contraction"]
    con_txt = f"{con:.2f}× (수축)" if (con is not None and con < 1) else (f"{con:.2f}×" if con is not None else "—")
    con_cls = _sig(con is not None and con < 0.9, con is not None and con > 1.1)
    vr = c["vol_ratio"]
    vr_txt = (f"{vr:.2f}× " + ("마름" if vr < 1 else "늘어남")) if vr is not None else "—"
    vr_cls = _sig(vr is not None and vr < 1.0, vr is not None and vr > 1.2)
    rs = c["rs"]
    rs_txt = (f"{rs:+.1f}%p vs 지수") if rs is not None else "—"
    rs_cls = _sig(rs is not None and rs > 0, rs is not None and rs < 0)
    adr = c["adr_now"]
    risk = c["risk_pct"]
    ma_txt = "정배열 (10>20>50)" if c["ma_aligned"] else "미정렬"
    ma_cls = _sig(c["ma_aligned"], not c["ma_aligned"])
    return f"""
      <div class="panel">
        <div class="panel-h">돌파 분석</div>
        <div class="mrow"><span>선행 상승</span><b class="sig-good">+{pm:.0f}%</b></div>
        <div class="mrow"><span>베이스 기간</span><b>{c['base_len']}일</b></div>
        <div class="mrow"><span>변동성 수축</span><b class="{con_cls}">{con_txt}</b></div>
        <div class="mrow"><span>거래량</span><b class="{vr_cls}">{vr_txt}</b></div>
        <div class="mrow"><span>ADR(변동성) · 손절폭</span><b>{(f'{adr:.1f}%' if adr else '—')} · {(f'{risk:.1f}%' if risk else '—')}</b></div>
        <div class="mrow"><span>상대강도(60일)</span><b class="{rs_cls}">{rs_txt}</b></div>
        <div class="mrow"><span>MA 정렬</span><b class="{ma_cls}">{ma_txt}</b></div>
        <div class="mrow"><span>포지션 사이징</span><b class="size-out">—</b></div>
      </div>"""


def card_html(market, c):
    t = c["ticker"]
    name = s.display_name(t)
    fp = lambda x: s.fmt_price(x, t)
    code_badge = f"<span class='code'>{t}</span>" if name != t else ""
    chart_rel = f"charts/bo_{market}_{t.replace('.', '_')}.png"
    return f"""
    <a class="card-link" href="{bs.chart_url(t)}" target="_blank" rel="noopener"
       data-entry="{c['pivot']:.4f}" data-stop="{c['stop']:.4f}">
    <article class="card reveal">
      <header class="card-h">
        <div class="ttl"><span class="nm">{name}</span>{code_badge}</div>
        <div class="px"><span class="px-num">{fp(c['price'])}</span></div>
      </header>
      <div class="label">🚀 돌파 발생 — 오늘 피벗 상향</div>
      <div class="levels">
        <div class="lv"><span>피벗(돌파선)</span><b>{fp(c['pivot'])}</b></div>
        <div class="lv"><span>진입 / 손절</span><b>{fp(c['pivot'])} / {fp(c['stop'])}</b></div>
        <div class="lv"><span>익절</span><b>3~5일 부분익절 → 손절 BE → MA 트레일</b></div>
      </div>
      {panel_html(c)}
      <div class="plate"><img loading="lazy" src="{chart_rel}" alt="{name} chart"></div>
      <div class="open">TradingView에서 차트 열기 ↗</div>
    </article>
    </a>"""


def forming_rows(market, items):
    if not items:
        return ""
    items = sorted(items, key=lambda r: abs(r["dist"]))
    rows = ""
    for c in items:
        t = c["ticker"]
        name = s.display_name(t)
        fp = s.fmt_price(c["pivot"], t)
        rs = c["rs"]
        rs_txt = "RS↑" if (rs is not None and rs > 0) else ("RS↓" if rs is not None else "")
        rs_cls = "sig-good" if (rs is not None and rs > 0) else ("sig-bad" if rs is not None else "")
        rows += (
            f"<a class='wl-row' href='{bs.chart_url(t)}' target='_blank' rel='noopener'>"
            f"<span class='wl-nm'>{name}</span>"
            f"<span class='wl-meta'>피벗까지 {c['dist']:.1f}% · 선행 +{c['prior_move']:.0f}% · 베이스 {c['base_len']}일</span>"
            f"<span class='wl-wk {rs_cls}'>{rs_txt}</span>"
            f"<span class='wl-px'>{fp}</span></a>")
    return (f"<div class='watch'><div class='watch-h'>⏳ 셋업 형성 · 피벗 근접 "
            f"<span class='muted'>{len(items)}</span> "
            f"<span class='muted'>— 피벗에 알림 걸어두기</span></div>"
            f"<div class='wl'>{rows}</div></div>")


def section_html(market, results):
    broke = [r for r in results if r.get("img")]
    broke.sort(key=lambda r: -r["prior_move"])
    forming = [r for r in results if r["stage"] == "forming"]
    active = "active" if market == "us" else ""

    if broke:
        body = "<div class='grid'>" + "".join(card_html(market, c) for c in broke) + "</div>"
    else:
        body = "<div class='empty'>오늘 종가 돌파가 발생한 종목이 없습니다. 아래 형성 중인 셋업을 확인하세요.</div>"

    cur = {"us": "USD", "kr": "KRW", "etf": "USD", "kretf": "KRW", "crypto": "USD"}.get(market, "USD")
    acct = {"us": "10000", "kr": "10000000", "etf": "10000", "kretf": "10000000", "crypto": "10000"}.get(market, "10000")
    sizer = (f"<div class='sizer'>포지션 사이징(피벗 진입 기준) — 계좌 "
             f"<input type='number' class='acct' value='{acct}'> · 리스크 "
             f"<input type='number' class='risk' value='1' step='0.1'>% "
             f"<span class='cur'>({cur} · 1회 손실 한도)</span></div>")

    return f"""
    <section id="sec-{market}" class="market {active}">
      <div class="sec-meta">
        <span class="cnt"><b>{len(broke)}</b> 돌파 발생</span>
        <span class="cnt"><b>{len(forming)}</b> 셋업 형성</span>
        <span class="cnt"><b>{len(results)}</b> 신호 종목</span>
      </div>
      {sizer if broke else ''}
      {body}
      {forming_rows(market, forming)}
    </section>"""


def page_html(stamp, sections, meta):
    tabs = "".join(
        f'<button class="tab" role="tab" data-m="{mid}">{label} '
        f'<span class="mono">{meta.get(mid + "_n", 0)}</span></button>'
        for mid, label in bs.MARKETS)
    secs = "".join(sections.get(mid, "") for mid, _ in bs.MARKETS)
    return f"""<!doctype html>
<html lang="ko"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="dark">
<title>돌파 스캐너 · 큰 상승 후 수축 돌파</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;700&family=Inter:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<style>{bs.CSS}</style>
</head><body>
<div class="wrap">
  <div class="top">
    <h1 class="brand">돌파 스캐너<span class="dot">.</span></h1>
    <span class="sub">큰 상승 → 수축 베이스 → 종가 돌파</span>
    <span class="stamp">갱신 <b>{stamp}</b> KST</span>
  </div>

  {bs.nav_html("breakout")}

  <div class="tabs" role="tablist">
    {tabs}
  </div>

  {secs}

  <div class="how">
    <b>어떻게 고르나</b> · ① 최근 1~3개월 +30% 이상 큰 상승 → ② 2주~2.5달 수축 베이스
    (변동성·거래량 마름) → ③ 오늘 종가가 베이스 고점(피벗)을 상향 돌파. 손절은 베이스 저점,
    매수 후 3~5일 내 부분익절하고 손절을 본전으로 올린 뒤 나머지는 10/20일선 이탈 시 매도.
  </div>
  <div class="foot">
    돌파 스윙(Qullamaggie 스타일) 스크리너이며 투자 조언이 아닙니다. 이 전략은 승률이 낮고(대략 25%)
    소수의 큰 수익이 전체를 좌우하므로, 손절을 칼같이 지키는 규율이 핵심입니다. 강세장 전제이며 약세장에선
    가짜 돌파가 늘어납니다. 종가 돌파 기준이라 장중 실시간 돌파와는 다를 수 있어 최종 확인을 권장합니다.
  </div>
</div>
<script>{bs.JS}</script>
</body></html>"""


def main():
    os.makedirs(bs.CHARTS, exist_ok=True)
    sections, meta = {}, {}
    for market, _label in bs.MARKETS:
        print(f"=== 돌파 스캔: {market} ===")
        results = scan_market(market)
        for c in results:
            if c.get("img"):
                fn = f"bo_{market}_{c['ticker'].replace('.', '_')}.png"
                with open(os.path.join(bs.CHARTS, fn), "wb") as f:
                    f.write(c["img"])
        sections[market] = section_html(market, results)
        meta[f"{market}_n"] = len([r for r in results if r.get("img")])

    stamp = datetime.now(bs.KST).strftime("%Y-%m-%d %H:%M")
    html = page_html(stamp, sections, meta)
    with open(os.path.join(bs.SITE, "breakout.html"), "w", encoding="utf-8") as f:
        f.write(html)
    print(f"✅ {bs.SITE}/breakout.html (" +
          " · ".join(f"{m} {meta[m + '_n']}" for m, _ in bs.MARKETS) + ")")


if __name__ == "__main__":
    main()
