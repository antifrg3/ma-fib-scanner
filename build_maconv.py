#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_maconv.py — 이평 수렴 스캐너 → site/maconv.html
─────────────────────────────────────────────────────────────────────────
1시간봉에서 MA 20/50/200이 좁은 폭에 모인 종목을 찾는다.

절대 기준(폭 자체)과 상대 기준(그 종목 자신의 과거 대비)을 함께 본다.
실측 결과 종목별 편차가 17배라 한 기준만으로는 저변동 자산이 상위를 독식한다.

섹션: 🎯 둘 다 · 📊 상대만 · 📏 절대만 · 👀 근접 관찰
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
import maconv as mc

BARS = 150          # 차트 표시 봉 수
NEAR_SHOW = 10      # 근접 관찰 표시 개수
SECTION_MAX = 20    # 섹션당 최대


def fetch_1h(symbol: str):
    try:
        return s._klines_to_df(s._binance_klines(symbol, "1h", 600))
    except Exception:
        return None


def scan():
    out = []
    for t in s.load_universe("crypto"):
        try:
            df = fetch_1h(t)
            if df is None or len(df) < 240:
                continue
            st = mc.compute(df)
            if st is None:
                continue
            out.append({"ticker": t, "state": st, "df": df})
        except Exception:
            continue
    return out


# ── 차트: 캔들 + 3개 MA + spread 패널 ────────────────────────────────────
def render_chart(c: dict) -> bytes:
    full = c["df"]
    st = c["state"]
    df = full.tail(BARS).copy()

    cols = {20: "#4fc3d2", 50: "#ffa726", 200: "#fe0d5f"}
    adds = []
    for n in mc.MAS:
        adds.append(mpf.make_addplot(full["Close"].rolling(n).mean().tail(BARS),
                                     color=cols[n], width=1.1))
    sp = mc.spread_series(full).tail(BARS)
    adds.append(mpf.make_addplot(sp, panel=2, color="#c77dff", width=1.2,
                                 ylabel="spread%"))

    mcolors = mpf.make_marketcolors(up="#26a69a", down="#ef5350", edge="inherit",
                                    wick="inherit", volume="in")
    style = mpf.make_mpf_style(base_mpf_style="nightclouds", marketcolors=mcolors,
                               facecolor="#0e0e12", edgecolor="#0e0e12",
                               figcolor="#0e0e12", gridcolor="#1c1c24")
    buf = io.BytesIO()
    fig, axes = mpf.plot(df, type="candle", style=style, addplot=adds,
                         figsize=(7.6, 5.4), returnfig=True, volume=True,
                         volume_panel=1, panel_ratios=(5.5, 1.3, 2.0),
                         tight_layout=True, xrotation=0, datetime_format="%m/%d %Hh")

    # spread 패널에 절대 기준선 표시
    if len(axes) > 4:
        ax = axes[4]
        ax.axhline(mc.ABS_MAX, color="#26a69a", lw=0.8, ls="--", alpha=0.8)
        ax.set_ylim(0, max(float(sp.max()) * 1.1, mc.ABS_MAX * 2))

    # 차트 제목은 폰트 없는 서버에서 이모지·한글이 깨지므로 ASCII만 쓴다.
    dir_txt = {"up": "UP-ALIGN", "down": "DOWN-ALIGN", "mixed": "MIXED"}[st.direction]
    extra = []
    if any("돌파" in t for t in st.tags):
        extra.append("BREAKOUT")
    if any("거래량" in t for t in st.tags):
        extra.append("VOL-DRY")
    if any("심화" in t for t in st.tags):
        extra.append("TIGHTENING")
    tagtxt = ("  " + " ".join(extra)) if extra else ""
    axes[0].set_title(
        f"{c['ticker']}  spread {st.spread:.2f}%  (low {st.rel_pct:.0f}%ile)  "
        f"{dir_txt}{tagtxt}  (MA20=cyan 50=orange 200=red)",
        fontsize=9.5, loc="left", color="#e8e8ee")
    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight", facecolor="#0e0e12")
    plt.close(fig)
    return buf.getvalue()


# ── HTML ───────────────────────────────────────────────────────────────────
def card_html(c: dict) -> str:
    t = c["ticker"]
    st = c["state"]
    lab, _ = mc.GRADE_LABEL[st.grade]
    cls = mc.GRADE_CLS[st.grade]
    chart_rel = f"charts/cv_{t.replace('.', '_')}.png"
    tags = "".join(f'<span class="cv-tag">{x}</span>' for x in st.tags)
    tighten = (f"<span>10봉 변화 <b>{st.tighten:+.0f}%</b></span>"
               if st.tighten else "")
    vol = (f"<span>거래량 <b>{st.vol_ratio:.2f}배</b></span>"
           if st.vol_ratio else "")
    return f"""
    <div class="card">
      <div class="card-head">
        <span class="tk">{t}</span>
        <span class="cv-badge {cls}">{lab}</span>
      </div>
      <div class="cv-tags">{tags}</div>
      <div class="cv-meta">
        <span>수렴 폭 <b>{st.spread:.2f}%</b></span>
        <span>자기 기록 하위 <b>{st.rel_pct:.0f}%</b></span>
        {tighten}{vol}
      </div>
      <a class="card-link" href="{bs.chart_url(t)}" target="_blank" rel="noopener">
        <img loading="lazy" src="{chart_rel}" alt="{t}"></a>
      <div class="card-foot">
        <a class="card-link" href="{bs.chart_url(t)}" target="_blank" rel="noopener">
          TradingView에서 차트 열기 ↗</a>
      </div>
    </div>"""


CV_CSS = """
.card img{display:block;width:100%;height:auto;border-radius:6px;margin:4px 0}
.cv-badge{padding:3px 10px;border-radius:6px;font-weight:700;font-size:13px;color:#fff}
.cv-both{background:#1b7a4b}.cv-rel{background:#3a5a8a}
.cv-abs{background:#6a5a3a}.cv-near{background:#4a4a56}
.cv-tag{display:inline-block;padding:2px 8px;border-radius:5px;font-size:12px;
  background:#16161c;border:1px solid #23232c;color:#b8b8c4;margin:0 5px 4px 0}
.cv-tags{margin:8px 0 4px}
.cv-meta{display:flex;flex-wrap:wrap;gap:12px;font-size:13px;color:#b8b8c4;margin:6px 0 10px}
.cv-meta b{color:#e8e8ee}
.cv-h{margin:24px 0 8px;font-size:16px;color:#e8e8ee;font-weight:700}
.cv-sub{font-size:13px;color:#8a8a99;margin:0 0 10px}
.empty{color:#888;padding:20px;text-align:center}
"""


def page_html(stamp, groups, scanned):
    def block(grade, items):
        lab, desc = mc.GRADE_LABEL[grade]
        head = (f"<h3 class='cv-h'>{lab} <span class='mono'>{len(items)}</span></h3>"
                f"<div class='cv-sub'>{desc}</div>")
        if not items:
            return head + "<div class='empty'>해당 종목이 없습니다.</div>"
        return head + "<div class='grid'>" + "".join(card_html(c) for c in items) + "</div>"

    body = "".join(block(g, groups.get(g, [])) for g in ["both", "rel", "abs", "near"])
    return f"""<!doctype html>
<html lang="ko"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="dark">
<title>이평 수렴 · 크립토 1시간봉</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;700&family=Inter:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<style>{bs.CSS}{CV_CSS}</style>
</head><body>
<div class="wrap">
  <div class="top">
    <h1 class="brand">이평 수렴<span class="dot">.</span></h1>
    <span class="sub">크립토 1시간봉 · MA 20/50/200이 모이는 구간</span>
    <span class="stamp">갱신 <b>{stamp}</b> KST</span>
  </div>

  {bs.nav_html("maconv")}

  {body}

  <div class="how">
    <b>어떻게 보나</b> · 수렴 폭 = (MA20·50·200 중 최대−최소) ÷ 종가.
    좁을수록 세 선이 한곳에 모였다는 뜻이고, 방향이 정해지기 직전 구간으로 봅니다.
    기준이 둘인 이유는 <b>종목마다 평소 폭이 17배까지 차이</b>나기 때문입니다(실측).
    금·주식토큰은 원래 좁고 알트는 원래 넓어서, 절대 기준만 쓰면 저변동 자산이
    상위를 독식합니다. 그래서 <b>절대 폭({mc.ABS_MAX}% 이내)</b>과
    <b>자기 기록 대비(하위 {mc.REL_PCT:.0f}%)</b>를 나눠 봅니다.
    태그는 부가 정보입니다 — 정렬 방향, 돌파 여부, 거래량 마름, 수렴 심화.
  </div>
  <div class="foot">
    스캔 {scanned}종목. 수렴은 '곧 움직인다'는 압축 신호일 뿐 <b>방향을 알려주지 않습니다</b>.
    돌파 방향이 가짜일 수 있고, 수렴이 더 길어질 수도 있습니다.
    백테스트로 검증된 신호가 아니며 투자 조언이 아닙니다.
  </div>
</div>
<script>{bs.JS}</script>
</body></html>"""


def main():
    os.makedirs(bs.CHARTS, exist_ok=True)
    results = scan()

    groups = {}
    for g in ["both", "rel", "abs"]:
        items = [c for c in results if c["state"].grade == g]
        items.sort(key=lambda c: c["state"].rel_pct)
        groups[g] = items[:SECTION_MAX]
    near = [c for c in results if c["state"].grade == "near"]
    near.sort(key=lambda c: c["state"].rel_pct)
    groups["near"] = near[:NEAR_SHOW]

    shown = [c for items in groups.values() for c in items]
    for c in shown:
        try:
            img = render_chart(c)
            fn = f"cv_{c['ticker'].replace('.', '_')}.png"
            with open(os.path.join(bs.CHARTS, fn), "wb") as f:
                f.write(img)
        except Exception as e:
            print(f"  차트 실패 {c['ticker']}: {e}")

    stamp = datetime.now(bs.KST).strftime("%Y-%m-%d %H:%M")
    html = page_html(stamp, groups, len(results))
    with open(os.path.join(bs.SITE, "maconv.html"), "w", encoding="utf-8") as f:
        f.write(html)
    counts = " · ".join(f"{g} {len(groups.get(g, []))}" for g in ["both", "rel", "abs", "near"])
    print(f"✅ {bs.SITE}/maconv.html ({counts})")


if __name__ == "__main__":
    main()
