#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_mtfband.py — 멀티타임프레임 볼린저 역추세 스캐너 → site/mtfband.html
─────────────────────────────────────────────────────────────────────────
4시간봉 밴드 끝(꼬리 이탈+거부)에서 역추세 진입 후보를 찾고,
일봉/4시간/1시간 밴드를 한 차트에 겹쳐 그려 극단 정도를 시각화.
⭐ 순 정렬. 1시간 상태는 정보로만 표시(필터 아님).
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
import mtfband as mt

BARS = 120   # 차트에 그릴 4시간봉 개수


def fetch(symbol: str, interval: str, limit: int) -> pd.DataFrame | None:
    try:
        return s._klines_to_df(s._binance_klines(symbol, interval, limit))
    except Exception:
        return None


def scan():
    out = []
    for t in s.load_universe("crypto"):
        try:
            df1d = fetch(t, "1d", 200)
            df4h = fetch(t, "4h", 300)
            df1h = fetch(t, "1h", 400)
            st = mt.compute_mtf(df1d, df4h, df1h)
            if st is None:
                continue
            out.append({"ticker": t, "state": st,
                        "df1d": df1d, "df4h": df4h, "df1h": df1h})
        except Exception:
            continue
    return out


# ── 차트: 4시간 캔들 + 3개 시간봉 밴드 겹치기 ─────────────────────────────
def _align_to(src_bands, src_index, target_index):
    """상위/하위 시간봉 밴드를 4시간 축에 정렬.
       ffill은 계단이 생겨 밴드 관계가 안 보이므로 시간 기준 선형보간 사용."""
    ser = pd.Series(src_bands.values, index=src_index).dropna()
    if ser.empty:
        return pd.Series(np.nan, index=target_index)
    # 두 인덱스를 합쳐 보간한 뒤 목표 축만 추출 → 매끄러운 곡선
    merged = ser.reindex(ser.index.union(target_index)).interpolate(method="time")
    return merged.reindex(target_index).ffill().bfill()


def render_chart(c: dict) -> bytes:
    df4 = c["df4h"].tail(BARS).copy()
    st = c["state"]
    idx = df4.index

    # 4시간 밴드(실선)
    m4, u4, l4 = mt.bands(c["df4h"])
    # 일봉 밴드(굵은 점선) — 4시간 축에 정렬
    m1d, u1d, l1d = mt.bands(c["df1d"])
    u1d_a = _align_to(u1d, c["df1d"].index, idx)
    l1d_a = _align_to(l1d, c["df1d"].index, idx)
    # 1시간 밴드(가는 선) — 4시간 축에 정렬
    m1h, u1h, l1h = mt.bands(c["df1h"])
    u1h_a = _align_to(u1h, c["df1h"].index, idx)
    l1h_a = _align_to(l1h, c["df1h"].index, idx)

    adds = [
        # 일봉 밴드 — 가장 넓음, 굵은 점선
        mpf.make_addplot(u1d_a, color="#ff9f43", width=1.6, linestyle="--"),
        mpf.make_addplot(l1d_a, color="#ff9f43", width=1.6, linestyle="--"),
        # 4시간 밴드 — 메인, 실선
        mpf.make_addplot(u4.tail(BARS), color="#4fc3d2", width=1.3),
        mpf.make_addplot(l4.tail(BARS), color="#4fc3d2", width=1.3),
        mpf.make_addplot(m4.tail(BARS), color="#4fc3d2", width=0.7, linestyle=":"),
        # 1시간 밴드 — 가장 좁음, 가는 선
        mpf.make_addplot(u1h_a, color="#a0a0b0", width=0.8),
        mpf.make_addplot(l1h_a, color="#a0a0b0", width=0.8),
    ]

    mc = mpf.make_marketcolors(up="#26a69a", down="#ef5350", edge="inherit",
                               wick="inherit", volume="in")
    style = mpf.make_mpf_style(base_mpf_style="nightclouds", marketcolors=mc,
                               facecolor="#0e0e12", edgecolor="#0e0e12",
                               figcolor="#0e0e12", gridcolor="#1c1c24")
    buf = io.BytesIO()
    fig, axes = mpf.plot(df4, type="candle", style=style, addplot=adds,
                         figsize=(7.8, 4.2), returnfig=True, volume=False,
                         tight_layout=True, xrotation=0, datetime_format="%m/%d")
    sig = "LONG" if st.signal == "long" else "SHORT"
    ext = {"daily": "DAILY band", "h4": "4H band", "h1": "1H band"}[st.extremity]
    div = ("1H+4H div" if st.div_1h and st.div_4h
           else "1H div" if st.div_1h else "4H div" if st.div_4h else "no div")
    axes[0].set_title(f"{c['ticker']}  {sig} {'*' * st.stars}  {ext} pierced  {div}   "
                      f"(D=orange dash, 4H=cyan, 1H=gray)",
                      fontsize=9.5, loc="left", color="#e8e8ee")
    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight", facecolor="#0e0e12")
    plt.close(fig)
    return buf.getvalue()


# ── HTML ───────────────────────────────────────────────────────────────────
def card_html(c: dict) -> str:
    t = c["ticker"]
    st = c["state"]
    lab, sub = mt.SIGNAL_LABEL[st.signal]
    cls = mt.SIGNAL_CLS[st.signal]
    chart_rel = f"charts/mtf_{t.replace('.', '_')}.png"
    stars = "⭐" * st.stars
    ext_badge = mt.EXTREMITY_LABEL[st.extremity]
    div_badges = ""
    if st.div_1h:
        div_badges += '<span class="mtf-badge mtf-div">🔀 1H 다이버전스</span>'
    if st.div_4h:
        div_badges += '<span class="mtf-badge mtf-div4">🔀 4H 다이버전스</span>'
    return f"""
    <div class="card">
      <div class="card-head">
        <span class="tk">{t}</span>
        <span class="mtf-badge {cls}">{lab}</span>
        <span class="mtf-stars">{stars}</span>
      </div>
      <div class="mtf-badges">
        <span class="mtf-badge mtf-ext">{ext_badge}</span>
        {div_badges}
      </div>
      <div class="mtf-meta">
        <span>4H 밴드 위치 <b>{st.pct_b_4h:.0%}</b></span>
        <span>1H RSI <b>{st.rsi_1h:.0f}</b></span>
        <span class="mtf-note">1H: {st.h1_note}</span>
      </div>
      <a class="card-link" href="{bs.chart_url(t)}" target="_blank" rel="noopener">
        <img loading="lazy" src="{chart_rel}" alt="{t}"></a>
      <div class="card-foot">
        <a class="card-link" href="{bs.chart_url(t)}" target="_blank" rel="noopener">
          TradingView에서 차트 열기 ↗</a>
      </div>
    </div>"""


MTF_CSS = """
.card img{display:block;width:100%;height:auto;border-radius:6px;margin:4px 0}
.mtf-badge{padding:3px 9px;border-radius:6px;font-weight:700;font-size:12px;color:#fff;
  display:inline-block;margin-right:6px}
.mtf-long{background:#1b7a4b}.mtf-short{background:#b23a3a}
.mtf-ext{background:#3a4a6b}.mtf-div{background:#6b4a8a}.mtf-div4{background:#8a4a6b}
.mtf-stars{font-size:14px;letter-spacing:-1px}
.mtf-badges{margin:8px 0 6px}
.mtf-meta{display:flex;flex-wrap:wrap;gap:12px;font-size:13px;color:#b8b8c4;margin:6px 0 10px}
.mtf-meta b{color:#e8e8ee}
.mtf-note{color:#8a8a99}
.mtf-h{margin:22px 0 10px;font-size:16px;color:#e8e8ee;font-weight:700}
.empty{color:#888;padding:24px;text-align:center}
"""


def page_html(stamp, longs, shorts):
    def block(title, items, empty_msg):
        if items:
            cards = "".join(card_html(c) for c in items)
            return (f"<h3 class='mtf-h'>{title} <span class='mono'>{len(items)}</span></h3>"
                    f"<div class='grid'>{cards}</div>")
        return f"<h3 class='mtf-h'>{title}</h3><div class='empty'>{empty_msg}</div>"

    long_block = block("🟢 롱 후보 (밴드 하단 이탈 후 거부)", longs, "롱 후보가 없습니다.")
    short_block = block("🔴 숏 후보 (밴드 상단 이탈 후 거부)", shorts, "숏 후보가 없습니다.")
    return f"""<!doctype html>
<html lang="ko"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="dark">
<title>MTF 밴드 역추세 · 크립토</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;700&family=Inter:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<style>{bs.CSS}{MTF_CSS}</style>
</head><body>
<div class="wrap">
  <div class="top">
    <h1 class="brand">MTF 밴드 역추세<span class="dot">.</span></h1>
    <span class="sub">4시간 밴드 끝 · 일봉/4H/1H 겹쳐보기 · RSI 다이버전스</span>
    <span class="stamp">갱신 <b>{stamp}</b> KST</span>
  </div>

  {bs.nav_html("mtfband")}

  {long_block}
  {short_block}

  <div class="how">
    <b>어떻게 보나</b> · 4시간봉이 자기 밴드를 <b>꼬리로 뚫었다가 종가는 안으로 복귀</b>(=거부/소진)한
    코인을 찾습니다. ⭐는 극단 정도: 일봉 밴드까지 이탈 ⭐⭐⭐ · 4시간 ⭐⭐ · 1시간 ⭐,
    여기에 1H 다이버전스 +⭐, 4H 다이버전스 +⭐⭐. 차트는 <b>일봉(주황 점선) · 4시간(청록) ·
    1시간(회색)</b> 밴드를 겹쳐 그려 어디까지 뚫렸는지 보여줍니다.
    종가가 연속 3봉 이상 밴드 밖이면 '추세'로 보고 제외합니다(역추세 함정 방지).
  </div>
  <div class="foot">
    후보 표시 도구이며 백테스트 미검증입니다. 1H 상태는 참고 정보일 뿐 진입 신호가 아니며,
    실제 타점은 하위 시간봉에서 직접 확인하세요. 투자 조언이 아닙니다.
  </div>
</div>
<script>{bs.JS}</script>
</body></html>"""


def main():
    os.makedirs(bs.CHARTS, exist_ok=True)
    results = scan()
    longs = sorted([c for c in results if c["state"].signal == "long"],
                   key=lambda c: -c["state"].stars)
    shorts = sorted([c for c in results if c["state"].signal == "short"],
                    key=lambda c: -c["state"].stars)

    for c in longs + shorts:
        try:
            img = render_chart(c)
            fn = f"mtf_{c['ticker'].replace('.', '_')}.png"
            with open(os.path.join(bs.CHARTS, fn), "wb") as f:
                f.write(img)
        except Exception as e:
            print(f"  차트 실패 {c['ticker']}: {e}")

    stamp = datetime.now(bs.KST).strftime("%Y-%m-%d %H:%M")
    html = page_html(stamp, longs, shorts)
    with open(os.path.join(bs.SITE, "mtfband.html"), "w", encoding="utf-8") as f:
        f.write(html)
    print(f"✅ {bs.SITE}/mtfband.html (롱 {len(longs)} · 숏 {len(shorts)})")


if __name__ == "__main__":
    main()
