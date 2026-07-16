#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_ssband.py — SS밴드+슈퍼트렌드 롱/숏 스캐너 → site/ssband.html
─────────────────────────────────────────────────────────────────────────
롱 = 5분봉>SMA200 + 1시간봉>SMA50 + SS밴드 녹색 + 슈퍼트렌드 파랑 (4/4)
숏 = 전부 반대 (4/4)
갱신: 4시간마다(00시 KST 기준). 사용자 Pine 지표 로직 이식.
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
import ssband as sbnd


def fetch(symbol: str, interval: str, limit: int) -> pd.DataFrame | None:
    try:
        df = s._klines_to_df(s._binance_klines(symbol, interval, limit))
        return df
    except Exception:
        return None


def scan():
    out = []
    for t in s.load_universe("crypto"):
        try:
            df5 = fetch(t, "5m", 300)     # 5분봉 300개 (SMA200 여유)
            df1 = fetch(t, "1h", 400)     # 1시간봉 400개 (SS밴드/ST/SMA50 여유)
            if df5 is None or df1 is None:
                continue
            st = sbnd.compute_signal(df5, df1)
            if st is None or st.signal == "none":
                continue
            out.append({"ticker": t, "state": st, "df1h": df1})
        except Exception:
            continue
    return out


# ── 차트: 1시간봉 캔들 + SMA50 + SS밴드 두 선 ────────────────────────────
def render_chart(ticker: str, df1h: pd.DataFrame, st: sbnd.SSState) -> bytes:
    bars = 160
    d = df1h.tail(bars).copy()
    c = df1h["Close"]
    o = df1h["Open"]

    sma50 = c.rolling(sbnd.SMA_1H).mean().tail(bars)
    # SS밴드 두 선 재계산 (표시용)
    ss_full = sbnd.compute_ssband(df1h)
    adds = [mpf.make_addplot(sma50, color="#ffd54f", width=1.1)]

    mc = mpf.make_marketcolors(up="#26a69a", down="#ef5350", edge="inherit",
                               wick="inherit", volume="in")
    style = mpf.make_mpf_style(base_mpf_style="nightclouds", marketcolors=mc,
                               facecolor="#0e0e12", edgecolor="#0e0e12",
                               figcolor="#0e0e12", gridcolor="#1c1c24")
    buf = io.BytesIO()
    fig, axes = mpf.plot(d, type="candle", style=style, addplot=adds,
                         figsize=(7.6, 4.0), returnfig=True, volume=False,
                         tight_layout=True, xrotation=0, datetime_format="%m/%d %Hh")
    sig = "LONG 4/4" if st.signal == "long" else "SHORT 4/4"
    band = "band GREEN" if st.band_green else "band ORANGE"
    stt = "ST BLUE" if st.st_blue else "ST RED"
    axes[0].set_title(f"{ticker}  {sig}  {band}  {stt}  (1h, SMA50=yellow)",
                      fontsize=10, loc="left", color="#e8e8ee")
    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight", facecolor="#0e0e12")
    plt.close(fig)
    return buf.getvalue()


# ── HTML ───────────────────────────────────────────────────────────────────
def card_html(c: dict) -> str:
    t = c["ticker"]
    st = c["state"]
    lab, sub = sbnd.SIGNAL_LABEL[st.signal]
    cls = sbnd.SIGNAL_CLS[st.signal]
    chart_rel = f"charts/ss_{t.replace('.', '_')}.png"
    ck = lambda b: "✓" if b else "✗"
    return f"""
    <div class="card">
      <div class="card-head">
        <span class="tk">{t}</span>
        <span class="ss-badge {cls}">{lab} 4/4</span>
      </div>
      <div class="ss-meta">
        <span>{ck(st.above_5m200)} 5분>SMA200</span>
        <span>{ck(st.above_1h50)} 1시간>SMA50</span>
        <span>{ck(st.band_green)} 밴드녹색</span>
        <span>{ck(st.st_blue)} ST파랑</span>
      </div>
      <a class="card-link" href="{bs.chart_url(t)}" target="_blank" rel="noopener">
        <img loading="lazy" src="{chart_rel}" alt="{t}"></a>
      <div class="card-foot">
        <a class="card-link" href="{bs.chart_url(t)}" target="_blank" rel="noopener">
          TradingView에서 차트 열기 ↗</a>
      </div>
    </div>"""


SS_CSS = """
.card img{display:block;width:100%;height:auto;border-radius:6px;margin:4px 0}
.ss-badge{padding:3px 10px;border-radius:6px;font-weight:700;font-size:13px;color:#fff}
.ss-long{background:#1b7a4b}.ss-short{background:#b23a3a}.ss-none{background:#555}
.ss-meta{display:flex;flex-wrap:wrap;gap:12px;font-size:13px;color:#b8b8c4;margin:6px 0 10px}
.ss-h{margin:20px 0 10px;font-size:16px;color:#e8e8ee;font-weight:700}
.empty{color:#888;padding:24px;text-align:center}
"""


def page_html(stamp, longs, shorts):
    def block(title, items, empty_msg):
        if items:
            cards = "".join(card_html(c) for c in items)
            return (f"<h3 class='ss-h'>{title} <span class='mono'>{len(items)}</span></h3>"
                    f"<div class='grid'>{cards}</div>")
        return f"<h3 class='ss-h'>{title}</h3><div class='empty'>{empty_msg}</div>"

    long_block = block("🟢 롱 (4조건 전부 충족)", longs, "롱 조건 코인이 없습니다.")
    short_block = block("🔴 숏 (4조건 전부 충족)", shorts, "숏 조건 코인이 없습니다.")
    return f"""<!doctype html>
<html lang="ko"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="dark">
<title>SS밴드 스캐너 · 크립토</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;700&family=Inter:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<style>{bs.CSS}{SS_CSS}</style>
</head><body>
<div class="wrap">
  <div class="top">
    <h1 class="brand">SS밴드 스캐너<span class="dot">.</span></h1>
    <span class="sub">5분>200 · 1시간>50 · SS밴드 · 슈퍼트렌드 — 4조건 합류</span>
    <span class="stamp">갱신 <b>{stamp}</b> KST</span>
  </div>

  {bs.nav_html("ssband")}

  {long_block}
  {short_block}

  <div class="how">
    <b>어떻게 보나</b> · 🟢 롱 = ① 5분봉 종가&gt;SMA200 ② 1시간봉 종가&gt;SMA50
    ③ SS밴드 녹색(거래량가중 EMA&gt;시가 EMA) ④ 슈퍼트렌드 파랑 — <b>4개 전부</b> 충족.
    🔴 숏 = 전부 반대. 4시간마다 갱신되며, 5분봉 조건은 갱신 시점 스냅샷이라
    보는 순간과 다를 수 있음(TradingView에서 실시간 확인 권장).
  </div>
  <div class="foot">
    사용자 Pine 지표(SS Band) 로직을 이식한 후보 표시 도구입니다. 백테스트 미검증이며
    투자 조언이 아닙니다.
  </div>
</div>
<script>{bs.JS}</script>
</body></html>"""


def main():
    os.makedirs(bs.CHARTS, exist_ok=True)
    results = scan()
    longs = [c for c in results if c["state"].signal == "long"]
    shorts = [c for c in results if c["state"].signal == "short"]

    for c in longs + shorts:
        img = render_chart(c["ticker"], c["df1h"], c["state"])
        fn = f"ss_{c['ticker'].replace('.', '_')}.png"
        with open(os.path.join(bs.CHARTS, fn), "wb") as f:
            f.write(img)

    stamp = datetime.now(bs.KST).strftime("%Y-%m-%d %H:%M")
    html = page_html(stamp, longs, shorts)
    with open(os.path.join(bs.SITE, "ssband.html"), "w", encoding="utf-8") as f:
        f.write(html)
    print(f"✅ {bs.SITE}/ssband.html (롱 {len(longs)} · 숏 {len(shorts)})")


if __name__ == "__main__":
    main()
