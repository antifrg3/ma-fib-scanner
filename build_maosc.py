#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_maosc.py — MA 오실레이터 신호 스캐너 → site/maosc.html
─────────────────────────────────────────────────────────────────────────
1시간봉에서 MA(50) 이격이 최근 50봉 최대(±100)를 찍고 꺾이는 지점을 찾는다.
🔴 상단 신호 = 과열 후 되돌림 후보 · 🟢 하단 신호 = 과매도 후 반등 후보

크립토 전용(바이낸스 1시간봉). 평균회귀 성격이라 강한 추세에서는
되돌림이 얕게 끝날 수 있다는 점을 감안해야 한다.
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
import maosc as mo

BARS = 150          # 차트 표시 봉 수
FRESH = 3           # 최근 N봉 내 신호만 표시


def fetch_1h(symbol: str):
    try:
        return s._klines_to_df(s._binance_klines(symbol, "1h", 400))
    except Exception:
        return None


def scan():
    out = []
    for t in s.load_universe("crypto"):
        try:
            df = fetch_1h(t)
            if df is None or len(df) < 120:
                continue
            st = mo.compute(df, fresh=FRESH)
            if st is None or st.signal == "none":
                continue
            out.append({"ticker": t, "state": st, "df": df})
        except Exception:
            continue
    return out


# ── 차트: 캔들 + MA + 오실레이터 패널 ────────────────────────────────────
def render_chart(c: dict) -> bytes:
    full = c["df"]
    st = c["state"]
    df = full.tail(BARS).copy()

    ma = mo._ma(full["Close"], mo.MA_LEN).tail(BARS)
    osc = mo.oscillator(full).tail(BARS)

    adds = [
        mpf.make_addplot(ma, color="#e8e8ee", width=1.1),
        mpf.make_addplot(osc, panel=2, color="#4fc3d2", width=1.2, ylabel="OSC"),
    ]
    mc = mpf.make_marketcolors(up="#26a69a", down="#ef5350", edge="inherit",
                               wick="inherit", volume="in")
    style = mpf.make_mpf_style(base_mpf_style="nightclouds", marketcolors=mc,
                               facecolor="#0e0e12", edgecolor="#0e0e12",
                               figcolor="#0e0e12", gridcolor="#1c1c24")
    buf = io.BytesIO()
    fig, axes = mpf.plot(df, type="candle", style=style, addplot=adds,
                         figsize=(7.6, 5.6), returnfig=True, volume=True,
                         volume_panel=1, panel_ratios=(5.5, 1.3, 2.2),
                         tight_layout=True, xrotation=0, datetime_format="%m/%d %Hh")

    # 오실레이터 패널: ±100 경계와 0선 표시
    if len(axes) > 4:
        ax = axes[4]
        ax.set_ylim(-115, 115)
        ax.set_yticks([-100, 0, 100])
        ax.axhline(100, color="#ef5350", lw=0.7, ls="--", alpha=0.75)
        ax.axhline(0, color="#6a6a78", lw=0.6, ls=":", alpha=0.7)
        ax.axhline(-100, color="#26a69a", lw=0.7, ls="--", alpha=0.75)

    lab = "UPPER (overheat)" if st.signal == "upper" else "LOWER (oversold)"
    axes[0].set_title(
        f"{c['ticker']}  {lab}  {st.bars_ago}h ago  osc {st.osc:.0f}  "
        f"MA dist {st.ma_dist:+.1f}%  (1h, MA{mo.MA_LEN})",
        fontsize=9.5, loc="left", color="#e8e8ee")
    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight", facecolor="#0e0e12")
    plt.close(fig)
    return buf.getvalue()


# ── HTML ───────────────────────────────────────────────────────────────────
def card_html(c: dict) -> str:
    t = c["ticker"]
    st = c["state"]
    lab, sub = mo.SIGNAL_LABEL[st.signal]
    cls = mo.SIGNAL_CLS[st.signal]
    chart_rel = f"charts/mo_{t.replace('.', '_')}.png"
    ago = "현재 봉" if st.bars_ago == 0 else f"{st.bars_ago}시간 전"
    lvl = f"<span>신호 레벨 <b>{st.level:,.4g}</b></span>" if st.level else ""
    return f"""
    <div class="card">
      <div class="card-head">
        <span class="tk">{t}</span>
        <span class="mo-badge {cls}">{lab}</span>
        <span class="mo-ago">{ago}</span>
      </div>
      <div class="mo-meta">
        <span>OSC <b>{st.osc:.0f}</b></span>
        <span>MA 이격 <b>{st.ma_dist:+.2f}%</b></span>
        {lvl}
      </div>
      <a class="card-link" href="{bs.chart_url(t)}" target="_blank" rel="noopener">
        <img loading="lazy" src="{chart_rel}" alt="{t}"></a>
      <div class="card-foot">
        <a class="card-link" href="{bs.chart_url(t)}" target="_blank" rel="noopener">
          TradingView에서 차트 열기 ↗</a>
      </div>
    </div>"""


MO_CSS = """
.card img{display:block;width:100%;height:auto;border-radius:6px;margin:4px 0}
.mo-badge{padding:3px 10px;border-radius:6px;font-weight:700;font-size:13px;color:#fff}
.mo-upper{background:#b23a3a}.mo-lower{background:#1b7a4b}.mo-none{background:#555}
.mo-ago{font-size:12px;color:#8a8a99;padding:2px 8px;border:1px solid #2a2a34;border-radius:5px}
.mo-meta{display:flex;flex-wrap:wrap;gap:12px;font-size:13px;color:#b8b8c4;margin:7px 0 10px}
.mo-meta b{color:#e8e8ee}
.mo-h{margin:22px 0 10px;font-size:16px;color:#e8e8ee;font-weight:700}
.empty{color:#888;padding:24px;text-align:center}
"""


def page_html(stamp, lowers, uppers):
    def block(title, items, empty_msg):
        if items:
            cards = "".join(card_html(c) for c in items)
            return (f"<h3 class='mo-h'>{title} <span class='mono'>{len(items)}</span></h3>"
                    f"<div class='grid'>{cards}</div>")
        return f"<h3 class='mo-h'>{title}</h3><div class='empty'>{empty_msg}</div>"

    b1 = block("🟢 하단 신호 (과매도 → 반등 후보)", lowers, "하단 신호가 없습니다.")
    b2 = block("🔴 상단 신호 (과열 → 되돌림 후보)", uppers, "상단 신호가 없습니다.")
    return f"""<!doctype html>
<html lang="ko"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="dark">
<title>MA 오실레이터 · 크립토 1시간봉</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;700&family=Inter:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<style>{bs.CSS}{MO_CSS}</style>
</head><body>
<div class="wrap">
  <div class="top">
    <h1 class="brand">MA 오실레이터<span class="dot">.</span></h1>
    <span class="sub">크립토 · 1시간봉 · MA{mo.MA_LEN} 이격 극단 반전</span>
    <span class="stamp">갱신 <b>{stamp}</b> KST</span>
  </div>

  {bs.nav_html("maosc")}

  {b1}
  {b2}

  <div class="how">
    <b>어떻게 보나</b> · 종가와 MA{mo.MA_LEN}의 이격을 최근 {mo.NORM_LEN}봉 중 최대 이격으로 나눠
    <b>-100~+100</b>으로 정규화합니다. ±100은 '지금 이격이 최근 {mo.NORM_LEN}봉 중 최대'라는 뜻이고,
    그 상태가 <b>풀리는 첫 봉</b>이 신호입니다. 🟢 하단은 과매도 후 반등, 🔴 상단은 과열 후
    되돌림 후보입니다. 최근 {FRESH}봉 내 발생한 것만 표시합니다.
  </div>
  <div class="foot">
    평균회귀 성격의 신호라 강한 추세 구간에서는 되돌림이 얕게 끝나거나
    극단이 더 연장될 수 있습니다. 백테스트로 검증된 신호가 아니며 투자 조언이 아닙니다.
  </div>
</div>
<script>{bs.JS}</script>
</body></html>"""


def main():
    os.makedirs(bs.CHARTS, exist_ok=True)
    results = scan()
    lowers = sorted([c for c in results if c["state"].signal == "lower"],
                    key=lambda c: c["state"].bars_ago)
    uppers = sorted([c for c in results if c["state"].signal == "upper"],
                    key=lambda c: c["state"].bars_ago)

    for c in lowers + uppers:
        try:
            img = render_chart(c)
            fn = f"mo_{c['ticker'].replace('.', '_')}.png"
            with open(os.path.join(bs.CHARTS, fn), "wb") as f:
                f.write(img)
        except Exception as e:
            print(f"  차트 실패 {c['ticker']}: {e}")

    stamp = datetime.now(bs.KST).strftime("%Y-%m-%d %H:%M")
    html = page_html(stamp, lowers, uppers)
    with open(os.path.join(bs.SITE, "maosc.html"), "w", encoding="utf-8") as f:
        f.write(html)
    print(f"✅ {bs.SITE}/maosc.html (하단 {len(lowers)} · 상단 {len(uppers)})")


if __name__ == "__main__":
    main()
