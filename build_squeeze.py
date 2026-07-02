#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_squeeze.py — 스퀴즈 스캐너 → site/squeeze.html
─────────────────────────────────────────────────────────────────────────
TTM Squeeze(볼린저⊂켈트너) + WMA 리본 수렴 + RSI50 방향으로 스캔.
상태별 섹션: 🟡 압축 중(대기) / 🟢 롱 돌파 / 🔴 숏 돌파.
데이터·유니버스·차트·HTML 뼈대는 기존 모듈 재활용.
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
import regime
import squeeze as sq


# ── 스캔 ──────────────────────────────────────────────────────────────────
def scan_market(market: str):
    cfg = s.Config()
    cfg.market = market
    out = []
    for t in s.load_universe(market):
        try:
            daily, _four = s.get_data(t, cfg)
            if daily is None or len(daily) < 80:
                continue
            st = sq.compute_squeeze(daily)
            if st is None or st.status == "none":
                continue
            out.append({"ticker": t, "state": st, "df": daily})
        except Exception:
            continue
    return out


# ── 차트: 캔들 + WMA 리본 + 볼린저/켈트너 ────────────────────────────────
def render_chart(ticker: str, df: pd.DataFrame, st: sq.SqueezeState) -> bytes:
    bars = 140
    d = df.tail(bars).copy()
    c = df["Close"]

    adds = []
    # WMA 리본 (단기 청록 / 장기 빨강)
    for n in sq.RIBBON_SHORT:
        adds.append(mpf.make_addplot(sq._wma(c, n).tail(bars), color="#4fc3d2", width=0.7))
    for n in sq.RIBBON_LONG:
        adds.append(mpf.make_addplot(sq._wma(c, n).tail(bars), color="#fe0d5f", width=0.7))
    # 볼린저(점선) · 켈트너(실선 옅게)
    basis = c.rolling(sq.BB_LEN).mean()
    dev = sq.BB_MULT * c.rolling(sq.BB_LEN).std()
    kc_mid = c.rolling(sq.KC_LEN).mean()
    atr = sq._atr(df, sq.KC_LEN)
    for line, style, col in [(basis + dev, "--", "#ffd54f"), (basis - dev, "--", "#ffd54f"),
                             (kc_mid + sq.KC_MULT * atr, "-", "#8888aa"),
                             (kc_mid - sq.KC_MULT * atr, "-", "#8888aa")]:
        adds.append(mpf.make_addplot(line.tail(bars), color=col, width=0.8, linestyle=style))

    mc = mpf.make_marketcolors(up="#26a69a", down="#ef5350", edge="inherit",
                               wick="inherit", volume="in")
    style = mpf.make_mpf_style(base_mpf_style="nightclouds", marketcolors=mc,
                               facecolor="#0e0e12", edgecolor="#0e0e12",
                               figcolor="#0e0e12", gridcolor="#1c1c24")
    buf = io.BytesIO()
    fig, axes = mpf.plot(d, type="candle", style=style, addplot=adds,
                         figsize=(7.6, 4.0), returnfig=True, volume=False,
                         tight_layout=True, xrotation=0, datetime_format="%m/%d")
    # 차트 제목은 폰트 없는 서버에서 한글이 깨지므로 ASCII만 사용
    ascii_status = {"fired_long": "LONG breakout", "fired_short": "SHORT breakout",
                    "squeeze_on": "SQUEEZE on", "none": "-"}.get(st.status, "-")
    axes[0].set_title(f"{ticker}   {ascii_status}   RSI {st.rsi:.0f}   width {st.ribbon_width_pct:.2f}% "
                      f"(BB=yellow dash, KC=gray)", fontsize=10, loc="left", color="#e8e8ee")
    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight", facecolor="#0e0e12")
    plt.close(fig)
    return buf.getvalue()


# ── HTML ───────────────────────────────────────────────────────────────────
def card_html(market: str, c: dict) -> str:
    t = c["ticker"]
    st = c["state"]
    lab, sub = sq.STATUS_LABEL[st.status]
    cls = sq.STATUS_CLS[st.status]
    name = s.display_name(t)
    code_badge = f"<span class='code'>{t}</span>" if name != t else ""
    chart_rel = f"charts/sq_{market}_{t.replace('.', '_')}.png"
    fired = ("압축 중" if st.status == "squeeze_on"
             else f"{st.fired_bars_ago}일 전 해제")
    return f"""
    <div class="card">
      <div class="card-head">
        <span class="tk">{name}</span>{code_badge}
        <span class="sq-badge {cls}">{lab}</span>
      </div>
      <div class="sq-meta">
        <span>RSI <b>{st.rsi:.0f}</b></span>
        <span>리본폭 <b>{st.ribbon_width_pct:.2f}%</b> (좁을수록 압축)</span>
        <span>압축순위 <b>{st.ribbon_pctile:.0f}퍼센타일</b></span>
        <span>{fired}</span>
      </div>
      <a class="card-link" href="{bs.chart_url(t)}" target="_blank" rel="noopener">
        <img loading="lazy" src="{chart_rel}" alt="{name}">
      </a>
      <div class="card-foot">
        <a class="card-link" href="{bs.chart_url(t)}" target="_blank" rel="noopener">
          TradingView에서 차트 열기 ↗</a>
      </div>
    </div>"""


def section_html(market: str, results: list) -> str:
    active = "active" if market == "us" else ""
    # 상태별 그룹
    order = {"fired_long": 0, "fired_short": 1, "squeeze_on": 2}
    groups = {"fired_long": [], "fired_short": [], "squeeze_on": []}
    for c in results:
        groups.setdefault(c["state"].status, []).append(c)

    blocks = ""
    titles = {"fired_long": "🟢 롱 돌파 (압축 해제 + RSI>50)",
              "fired_short": "🔴 숏 돌파 (압축 해제 + RSI<50)",
              "squeeze_on": "🟡 스퀴즈 압축 중 (방향 대기)"}
    for key in ["fired_long", "fired_short", "squeeze_on"]:
        items = groups.get(key, [])
        if not items:
            continue
        cards = "".join(card_html(market, c) for c in items)
        blocks += f"<h3 class='sq-h'>{titles[key]} <span class='mono'>{len(items)}</span></h3>"
        blocks += f"<div class='grid'>{cards}</div>"
    if not blocks:
        blocks = "<div class='empty'>지금 스퀴즈 신호가 없습니다.</div>"

    r = regime.regime_for_market(market)
    return f"""
    <section id="sec-{market}" class="market {active}">
      {regime.badge_html(r, "breakout")}
      {blocks}
    </section>"""


SQUEEZE_CSS = """
.sq-badge{padding:3px 10px;border-radius:6px;font-weight:700;font-size:13px;color:#fff}
.sq-long{background:#1b7a4b}.sq-short{background:#b23a3a}
.sq-wait{background:#b8862b}.sq-none{background:#555}
.sq-meta{display:flex;flex-wrap:wrap;gap:12px;font-size:13px;color:#b8b8c4;margin:6px 0 10px}
.sq-meta b{color:#e8e8ee}
.sq-h{margin:20px 0 10px;font-size:15px;color:#e8e8ee;font-weight:700}
.empty{color:#888;padding:24px;text-align:center}
"""


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
<title>스퀴즈 스캐너 · 변동성 압축 → 돌파</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;700&family=Inter:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<style>{bs.CSS}{SQUEEZE_CSS}</style>
</head><body>
<div class="wrap">
  <div class="top">
    <h1 class="brand">스퀴즈 스캐너<span class="dot">.</span></h1>
    <span class="sub">변동성 압축(볼린저⊂켈트너 + 리본 수렴) → 방향 돌파</span>
    <span class="stamp">갱신 <b>{stamp}</b> KST</span>
  </div>

  {bs.nav_html("squeeze")}

  <div class="tabs" role="tablist">
    {tabs}
  </div>

  {secs}

  <div class="how">
    <b>어떻게 고르나</b> · ① 볼린저밴드(20,2σ)가 켈트너채널(20,1.5ATR) 안으로 들어가면
    변동성 압축(스퀴즈 ON) · ② 12개 WMA 리본이 수렴할수록 압축 강함 ·
    ③ 압축이 풀리는(해제) 시점에 RSI가 50 위면 🟢롱, 아래면 🔴숏 방향.
    압축 중(🟡)은 방향이 정해지기 전 대기 구간.
  </div>
  <div class="foot">
    스퀴즈는 '방향'이 아니라 '변동성 압축 후 큰 움직임 임박'을 알려주는 신호입니다.
    돌파 방향(RSI)이 가짜일 수 있으니 확인이 필요하며, 투자 조언이 아닙니다.
    일봉 종가 기준이라 장중과 다를 수 있습니다.
  </div>
</div>
<script>{bs.JS}</script>
</body></html>"""


def main():
    os.makedirs(bs.CHARTS, exist_ok=True)
    sections, meta = {}, {}
    for market, _label in bs.MARKETS:
        print(f"=== 스퀴즈 스캔: {market} ===")
        results = scan_market(market)
        # 차트는 돌파(fired)만 렌더(압축 중은 목록만 — 수 많고 대기 상태)
        for c in results:
            if c["state"].status in ("fired_long", "fired_short"):
                img = render_chart(c["ticker"], c["df"], c["state"])
                fn = f"sq_{market}_{c['ticker'].replace('.', '_')}.png"
                with open(os.path.join(bs.CHARTS, fn), "wb") as f:
                    f.write(img)
        sections[market] = section_html(market, results)
        meta[f"{market}_n"] = len(results)

    stamp = datetime.now(bs.KST).strftime("%Y-%m-%d %H:%M")
    html = page_html(stamp, sections, meta)
    with open(os.path.join(bs.SITE, "squeeze.html"), "w", encoding="utf-8") as f:
        f.write(html)
    print(f"✅ {bs.SITE}/squeeze.html (" +
          " · ".join(f"{m} {meta[m + '_n']}" for m, _ in bs.MARKETS) + ")")


if __name__ == "__main__":
    main()
