#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_alignment.py — 크립토 1시간봉 정배열/역배열 스캐너 → site/alignment.html
─────────────────────────────────────────────────────────────────────────
20>50>100>200 정배열(상승) / 20<50<100<200 역배열(하락) 코인을 찾아
정렬 강도순으로 보여준다. 크립토 전용·1시간봉.
갱신: 6시간마다(별도 워크플로우). 데이터·차트·HTML 뼈대 재활용.
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
import alignment as al


# ── 1시간봉 수집 ───────────────────────────────────────────────────────────
def fetch_1h(symbol: str) -> pd.DataFrame | None:
    try:
        return s._klines_to_df(s._binance_klines(symbol, "1h", 1000))
    except Exception:
        return None


# ── 스캔 ──────────────────────────────────────────────────────────────────
def scan():
    out = []
    for t in s.load_universe("crypto"):
        try:
            df = fetch_1h(t)
            if df is None or len(df) < 210:
                continue
            st = al.compute_alignment(df)
            if st is None or st.status == "mixed":
                continue
            out.append({"ticker": t, "state": st, "df": df})
        except Exception:
            continue
    return out


# ── 차트: 캔들 + 4 EMA ─────────────────────────────────────────────────────
def render_chart(ticker: str, df: pd.DataFrame, st: al.AlignState) -> bytes:
    bars = 160
    d = df.tail(bars).copy()
    c = df["Close"]
    cols = {20: "#4fc3d2", 50: "#7e9cff", 100: "#c77dff", 200: "#fe0d5f"}
    adds = []
    for n in al.MAS:
        ema = c.ewm(span=n, adjust=False).mean().tail(bars)
        adds.append(mpf.make_addplot(ema, color=cols[n], width=1.0))
    mc = mpf.make_marketcolors(up="#26a69a", down="#ef5350", edge="inherit",
                               wick="inherit", volume="in")
    style = mpf.make_mpf_style(base_mpf_style="nightclouds", marketcolors=mc,
                               facecolor="#0e0e12", edgecolor="#0e0e12",
                               figcolor="#0e0e12", gridcolor="#1c1c24")
    buf = io.BytesIO()
    fig, axes = mpf.plot(d, type="candle", style=style, addplot=adds,
                         figsize=(7.6, 4.0), returnfig=True, volume=False,
                         tight_layout=True, xrotation=0, datetime_format="%m/%d %Hh")
    ascii_status = "BULL stack" if st.status == "bull" else "BEAR stack"
    axes[0].set_title(f"{ticker}  {ascii_status}  strength {st.strength:.1f}%  RSI {st.rsi:.0f}  "
                      f"(EMA 20/50/100/200)", fontsize=10, loc="left", color="#e8e8ee")
    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight", facecolor="#0e0e12")
    plt.close(fig)
    return buf.getvalue()


# ── HTML ───────────────────────────────────────────────────────────────────
def card_html(c: dict) -> str:
    t = c["ticker"]
    st = c["state"]
    lab, sub = al.STATUS_LABEL[st.status]
    cls = al.STATUS_CLS[st.status]
    chart_rel = f"charts/al_{t.replace('.', '_')}.png"
    pos = ("현재가 모든 이평 위" if st.above_all
           else "현재가 모든 이평 아래" if st.below_all else "이평 사이")
    return f"""
    <div class="card">
      <div class="card-head">
        <span class="tk">{t}</span>
        <span class="al-badge {cls}">{lab}</span>
      </div>
      <div class="al-meta">
        <span>정렬강도 <b>{st.strength:.1f}%</b></span>
        <span>RSI <b>{st.rsi:.0f}</b></span>
        <span>{pos}</span>
      </div>
      <a class="card-link" href="{bs.chart_url(t)}" target="_blank" rel="noopener">
        <img loading="lazy" src="{chart_rel}" alt="{t}"></a>
      <div class="card-foot">
        <a class="card-link" href="{bs.chart_url(t)}" target="_blank" rel="noopener">
          TradingView에서 차트 열기 ↗</a>
      </div>
    </div>"""


ALIGN_CSS = """
.al-badge{padding:3px 10px;border-radius:6px;font-weight:700;font-size:13px;color:#fff}
.al-bull{background:#1b7a4b}.al-bear{background:#b23a3a}.al-mixed{background:#555}
.al-meta{display:flex;flex-wrap:wrap;gap:12px;font-size:13px;color:#b8b8c4;margin:6px 0 10px}
.al-meta b{color:#e8e8ee}
.al-h{margin:20px 0 10px;font-size:16px;color:#e8e8ee;font-weight:700}
.empty{color:#888;padding:24px;text-align:center}
"""


def page_html(stamp, bull, bear):
    def grid(items):
        return "".join(card_html(c) for c in items)
    bull_block = (f"<h3 class='al-h'>🟢 정배열 (상승 추세) <span class='mono'>{len(bull)}</span></h3>"
                  f"<div class='grid'>{grid(bull)}</div>") if bull else \
                 "<h3 class='al-h'>🟢 정배열</h3><div class='empty'>정배열 코인이 없습니다.</div>"
    bear_block = (f"<h3 class='al-h'>🔴 역배열 (하락 추세) <span class='mono'>{len(bear)}</span></h3>"
                  f"<div class='grid'>{grid(bear)}</div>") if bear else \
                 "<h3 class='al-h'>🔴 역배열</h3><div class='empty'>역배열 코인이 없습니다.</div>"
    return f"""<!doctype html>
<html lang="ko"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="dark">
<title>정배열 스캐너 · 크립토 1시간봉</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;700&family=Inter:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<style>{bs.CSS}{ALIGN_CSS}</style>
</head><body>
<div class="wrap">
  <div class="top">
    <h1 class="brand">정배열 스캐너<span class="dot">.</span></h1>
    <span class="sub">크립토 · 1시간봉 · EMA 20/50/100/200 정렬</span>
    <span class="stamp">갱신 <b>{stamp}</b> KST</span>
  </div>

  {bs.nav_html("alignment")}

  {bull_block}
  {bear_block}

  <div class="how">
    <b>어떻게 보나</b> · 🟢 정배열 = EMA 20&gt;50&gt;100&gt;200 (단기가 위, 상승 추세) ·
    🔴 역배열 = 20&lt;50&lt;100&lt;200 (하락 추세) · 정렬강도 = 이평 간 벌어진 정도(추세 강도) ·
    강도 높은 순 정렬. 1시간봉이라 6시간마다 갱신됩니다.
  </div>
  <div class="foot">
    정배열/역배열은 '추세 방향'을 보여주는 것이지 매수·매도 신호가 아닙니다.
    이미 강하게 정렬된 종목은 되돌림 위험, 갓 전환된 종목은 지속 불확실. 투자 조언이 아닙니다.
  </div>
</div>
<script>{bs.JS}</script>
</body></html>"""


def main():
    os.makedirs(bs.CHARTS, exist_ok=True)
    results = scan()
    bull = sorted([c for c in results if c["state"].status == "bull"],
                  key=lambda c: -c["state"].strength)
    bear = sorted([c for c in results if c["state"].status == "bear"],
                  key=lambda c: -c["state"].strength)

    for c in bull + bear:
        img = render_chart(c["ticker"], c["df"], c["state"])
        fn = f"al_{c['ticker'].replace('.', '_')}.png"
        with open(os.path.join(bs.CHARTS, fn), "wb") as f:
            f.write(img)

    stamp = datetime.now(bs.KST).strftime("%Y-%m-%d %H:%M")
    html = page_html(stamp, bull, bear)
    with open(os.path.join(bs.SITE, "alignment.html"), "w", encoding="utf-8") as f:
        f.write(html)
    print(f"✅ {bs.SITE}/alignment.html (정배열 {len(bull)} · 역배열 {len(bear)})")


if __name__ == "__main__":
    main()
