#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_rvwap.py — Rolling VWAP 돌파 스캐너 → site/rvwap.html
─────────────────────────────────────────────────────────────────────────
4시간봉(롤링 3일) RVWAP을 종가가 상향/하향 교차하는 종목을 찾는다.
단순 교차는 휩쏘가 많아 '그 봉의 거래량이 평균 이상'을 함께 요구한다.

상위 맥락으로 일봉 RVWAP(롤링 약 1개월) 대비 위치를 함께 표시한다.
4시간 기준은 뚫었는데 월 기준은 아직 아래 — 같은 판단이 가능해진다.
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
import rvwap as rv

BARS = 140          # 차트 표시 봉 수
FRESH = 3           # 최근 N봉 내 교차만


def fetch(symbol: str, interval: str, limit: int):
    try:
        return s._klines_to_df(s._binance_klines(symbol, interval, limit))
    except Exception:
        return None


def scan():
    out = []
    for t in s.load_universe("crypto"):
        try:
            df4 = fetch(t, "4h", 300)
            if df4 is None or len(df4) < 60:
                continue
            df1d = fetch(t, "1d", 120)
            st = rv.compute(df4, "4h", df_daily=df1d, fresh=FRESH)
            if st is None:
                continue
            out.append({"ticker": t, "state": st, "df": df4})
        except Exception:
            continue
    return out


# ── 차트: 캔들 + RVWAP + 편차 밴드 ───────────────────────────────────────
def render_chart(c: dict) -> bytes:
    full = c["df"]
    st = c["state"]
    df = full.tail(BARS).copy()

    r = rv.rolling_vwap(full, "4h")
    vwap = r["vwap"].tail(BARS)
    sd = r["sd"].tail(BARS)

    adds = [mpf.make_addplot(vwap, color="#ffa726", width=1.5)]
    for m, col in zip(rv.BAND_MULTS, ["#4caf50", "#ff5252"]):
        adds.append(mpf.make_addplot(vwap + sd * m, color=col, width=0.8,
                                     linestyle="--"))
        adds.append(mpf.make_addplot(vwap - sd * m, color=col, width=0.8,
                                     linestyle="--"))

    mc = mpf.make_marketcolors(up="#26a69a", down="#ef5350", edge="inherit",
                               wick="inherit", volume="in")
    style = mpf.make_mpf_style(base_mpf_style="nightclouds", marketcolors=mc,
                               facecolor="#0e0e12", edgecolor="#0e0e12",
                               figcolor="#0e0e12", gridcolor="#1c1c24")
    buf = io.BytesIO()
    fig, axes = mpf.plot(df, type="candle", style=style, addplot=adds,
                         figsize=(7.6, 4.6), returnfig=True, volume=True,
                         volume_panel=1, panel_ratios=(6, 1.6),
                         tight_layout=True, xrotation=0, datetime_format="%m/%d")
    lab = "CROSS UP" if st.signal == "up" else "CROSS DOWN"
    dctx = ""
    if st.d_above is not None:
        dctx = f"  D-VWAP {'above' if st.d_above else 'below'} ({st.d_dist:+.1f}%)"
    axes[0].set_title(
        f"{c['ticker']}  {lab}  {st.bars_ago}bar ago  {st.sd_pos:+.2f}sd  "
        f"vol {st.vol_ratio:.1f}x{dctx}  (4h, roll 3d)",
        fontsize=9.5, loc="left", color="#e8e8ee")
    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight", facecolor="#0e0e12")
    plt.close(fig)
    return buf.getvalue()


# ── HTML ───────────────────────────────────────────────────────────────────
def card_html(c: dict) -> str:
    t = c["ticker"]
    st = c["state"]
    lab, sub = rv.SIGNAL_LABEL[st.signal]
    cls = rv.SIGNAL_CLS[st.signal]
    chart_rel = f"charts/rv_{t.replace('.', '_')}.png"
    ago = "현재 봉" if st.bars_ago == 0 else f"{st.bars_ago * 4}시간 전"

    # 일봉 맥락 배지 — 4시간 신호와 같은 방향이면 강조
    dctx = ""
    if st.d_above is not None:
        aligned = (st.signal == "up" and st.d_above) or (st.signal == "down" and not st.d_above)
        dcls = "rv-align" if aligned else "rv-diverge"
        dtxt = ("일봉 VWAP 위" if st.d_above else "일봉 VWAP 아래")
        mark = "↑" if aligned else "↕"
        dctx = (f'<span class="rv-badge {dcls}">{mark} {dtxt} '
                f'({st.d_dist:+.1f}%)</span>')

    return f"""
    <div class="card">
      <div class="card-head">
        <span class="tk">{t}</span>
        <span class="rv-badge {cls}">{lab}</span>
        <span class="rv-ago">{ago}</span>
        {dctx}
      </div>
      <div class="rv-meta">
        <span>VWAP 이격 <b>{st.dist:+.2f}%</b></span>
        <span>편차 <b>{st.sd_pos:+.2f}σ</b></span>
        <span>돌파 거래량 <b>{st.vol_ratio:.2f}배</b></span>
        <span>롤링 <b>{st.window}</b></span>
      </div>
      <a class="card-link" href="{bs.chart_url(t)}" target="_blank" rel="noopener">
        <img loading="lazy" src="{chart_rel}" alt="{t}"></a>
      <div class="card-foot">
        <a class="card-link" href="{bs.chart_url(t)}" target="_blank" rel="noopener">
          TradingView에서 차트 열기 ↗</a>
      </div>
    </div>"""


RV_CSS = """
.card img{display:block;width:100%;height:auto;border-radius:6px;margin:4px 0}
.rv-badge{padding:3px 10px;border-radius:6px;font-weight:700;font-size:12px;color:#fff;
  margin-right:5px;display:inline-block}
.rv-up{background:#1b7a4b}.rv-down{background:#b23a3a}
.rv-align{background:#3a5a8a}.rv-diverge{background:#6a5a3a}
.rv-ago{font-size:12px;color:#8a8a99;padding:2px 8px;border:1px solid #2a2a34;border-radius:5px}
.rv-meta{display:flex;flex-wrap:wrap;gap:12px;font-size:13px;color:#b8b8c4;margin:8px 0 10px}
.rv-meta b{color:#e8e8ee}
.rv-h{margin:22px 0 10px;font-size:16px;color:#e8e8ee;font-weight:700}
.empty{color:#888;padding:24px;text-align:center}
"""


def page_html(stamp, ups, downs):
    def block(title, items, empty_msg):
        if items:
            cards = "".join(card_html(c) for c in items)
            return (f"<h3 class='rv-h'>{title} <span class='mono'>{len(items)}</span></h3>"
                    f"<div class='grid'>{cards}</div>")
        return f"<h3 class='rv-h'>{title}</h3><div class='empty'>{empty_msg}</div>"

    b1 = block("🟢 상방 돌파 (매수세 우위 전환)", ups, "상방 돌파가 없습니다.")
    b2 = block("🔴 하방 이탈 (매도세 우위 전환)", downs, "하방 이탈이 없습니다.")
    return f"""<!doctype html>
<html lang="ko"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="dark">
<title>Rolling VWAP 돌파 · 크립토 4시간봉</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;700&family=Inter:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<style>{bs.CSS}{RV_CSS}</style>
</head><body>
<div class="wrap">
  <div class="top">
    <h1 class="brand">Rolling VWAP<span class="dot">.</span></h1>
    <span class="sub">크립토 · 4시간봉(롤링 3일) 돌파 · 일봉 맥락</span>
    <span class="stamp">갱신 <b>{stamp}</b> KST</span>
  </div>

  {bs.nav_html("rvwap")}

  {b1}
  {b2}

  <div class="how">
    <b>어떻게 보나</b> · Rolling VWAP은 세션이 아니라 <b>최근 3일</b>을 굴러가는 창으로
    거래량 가중 평균가를 계산합니다(4시간봉 기준). 종가가 이 선을 <b>거래량을 실어</b>
    넘으면 매수·매도세 우위가 바뀐 것으로 봅니다.
    <b>σ</b>는 VWAP에서 몇 표준편차 떨어졌는지 — 클수록 과열/과매도입니다.
    파란 <b>↑ 일봉 VWAP</b> 배지는 상위 시간봉(롤링 약 1개월)과 방향이 일치한다는 뜻이고,
    <b>↕</b>는 엇갈린다는 뜻입니다. 일치할 때가 더 신뢰할 만합니다.
  </div>
  <div class="foot">
    최근 {FRESH}봉 내 교차만 표시합니다. VWAP 돌파는 '평균 매수단가를 넘었다'는 뜻일 뿐
    방향을 보장하지 않으며, 백테스트로 검증된 신호가 아닙니다. 투자 조언이 아닙니다.
  </div>
</div>
<script>{bs.JS}</script>
</body></html>"""


def main():
    os.makedirs(bs.CHARTS, exist_ok=True)
    results = scan()
    ups = sorted([c for c in results if c["state"].signal == "up"],
                 key=lambda c: (c["state"].bars_ago, -c["state"].vol_ratio))
    downs = sorted([c for c in results if c["state"].signal == "down"],
                   key=lambda c: (c["state"].bars_ago, -c["state"].vol_ratio))

    for c in ups + downs:
        try:
            img = render_chart(c)
            fn = f"rv_{c['ticker'].replace('.', '_')}.png"
            with open(os.path.join(bs.CHARTS, fn), "wb") as f:
                f.write(img)
        except Exception as e:
            print(f"  차트 실패 {c['ticker']}: {e}")

    stamp = datetime.now(bs.KST).strftime("%Y-%m-%d %H:%M")
    html = page_html(stamp, ups, downs)
    with open(os.path.join(bs.SITE, "rvwap.html"), "w", encoding="utf-8") as f:
        f.write(html)
    print(f"✅ {bs.SITE}/rvwap.html (상방 {len(ups)} · 하방 {len(downs)})")


if __name__ == "__main__":
    main()
