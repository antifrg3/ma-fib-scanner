#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_outperform.py — BTC 대비 강세 코인 스캐너 → site/outperform.html
─────────────────────────────────────────────────────────────────────────
바이낸스 상위 100개 중 최근 30일/90일 BTC를 이긴 코인을 초과수익 순으로.
CMC 알트시즌 로직 자체 구현. 정배열이 놓치는 초기 강세 코인 포착.
표시: 상위 SHOW_TOP개(초과수익 순). 갱신: 하루 1회(정배열과 함께).
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

import build_site as bs
import outperform as op
import alignment as al

SCAN_TOP = 100    # 바이낸스 거래대금 상위 N개 스캔
SHOW_TOP = 30     # 표시할 상위 N개(초과수익 순)


def _ma(s, n):
    return s.rolling(n).mean()


# ── 차트: 캔들 + EMA 20/50/100/200 (정배열 확인) ──────────────────────────
def render_chart(st: op.OutperformState, period_days: int) -> bytes:
    bars = period_days + 10
    d = st.df.tail(bars).copy()
    c = st.df["Close"]
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
                         tight_layout=True, xrotation=0, datetime_format="%m/%d")
    r = st.ret30 if period_days == 30 else st.ret90
    e = st.excess30 if period_days == 30 else st.excess90
    astat = al.compute_alignment(st.df)
    astr = ("BULL" if astat and astat.status == "bull"
            else "BEAR" if astat and astat.status == "bear" else "MIX")
    axes[0].set_title(f"{st.symbol}  {period_days}d {r:+.1f}%  vs BTC {e:+.1f}%p  [{astr}]  "
                      f"(EMA 20/50/100/200)", fontsize=10, loc="left", color="#e8e8ee")
    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight", facecolor="#0e0e12")
    plt.close(fig)
    return buf.getvalue()


# ── HTML ───────────────────────────────────────────────────────────────────
def card_html(st: op.OutperformState, period: str) -> str:
    t = st.symbol
    r = st.ret30 if period == "30" else st.ret90
    e = st.excess30 if period == "30" else st.excess90
    chart_rel = f"charts/op{period}_{t.replace('.', '_')}.png"
    ecls = "op-pos" if (e or 0) > 0 else "op-neg"
    # 정배열 상태
    astat = al.compute_alignment(st.df)
    if astat:
        alab, _ = al.STATUS_LABEL[astat.status]
        acls = al.STATUS_CLS[astat.status]
    else:
        alab, acls = "⚪ 혼조", "al-mixed"
    return f"""
    <div class="card">
      <div class="card-head">
        <span class="tk">{t}</span>
        <span class="op-badge {ecls}">BTC 대비 {e:+.1f}%p</span>
        <span class="al-badge {acls}">{alab}</span>
      </div>
      <div class="op-meta">
        <span>{period}일 수익률 <b>{r:+.1f}%</b></span>
        <span>BTC 초과 <b>{e:+.1f}%p</b></span>
      </div>
      <a class="card-link" href="{bs.chart_url(t)}" target="_blank" rel="noopener">
        <img loading="lazy" src="{chart_rel}" alt="{t}"></a>
      <div class="card-foot">
        <a class="card-link" href="{bs.chart_url(t)}" target="_blank" rel="noopener">
          TradingView에서 차트 열기 ↗</a>
      </div>
    </div>"""


OP_CSS = """
.op-badge{padding:3px 10px;border-radius:6px;font-weight:700;font-size:13px;color:#fff}
.op-pos{background:#1b7a4b}.op-neg{background:#b23a3a}
.al-badge{padding:3px 10px;border-radius:6px;font-weight:700;font-size:13px;color:#fff}
.al-bull{background:#1b7a4b}.al-bear{background:#b23a3a}.al-mixed{background:#555}
.op-meta{display:flex;flex-wrap:wrap;gap:12px;font-size:13px;color:#b8b8c4;margin:6px 0 10px}
.op-meta b{color:#e8e8ee}
.op-h{margin:22px 0 10px;font-size:16px;color:#e8e8ee;font-weight:700}
.op-season{padding:14px 16px;border-radius:10px;margin:14px 0;font-size:14px;line-height:1.5}
.op-season b{font-size:16px}
.op-tabs{display:flex;gap:8px;margin:16px 0}
.op-tabs button{padding:7px 16px;border-radius:8px;border:1px solid #2a2a34;background:#16161c;
  color:#c8c8d0;font-weight:600;cursor:pointer;font-size:14px}
.op-tabs button.on{background:#4fc3d2;color:#0a0a0e;border-color:#4fc3d2}
.card-head{display:flex;flex-wrap:wrap;gap:6px;align-items:center}
.empty{color:#888;padding:24px;text-align:center}
"""

OP_JS = """
function opShow(p){
  document.querySelectorAll('[data-period]').forEach(function(el){
    el.style.display = el.getAttribute('data-period')===p ? '' : 'none';
  });
  document.querySelectorAll('.op-tabs button').forEach(function(b){
    b.classList.toggle('on', b.getAttribute('data-p')===p);
  });
}
window.addEventListener('DOMContentLoaded',function(){opShow('30');});
"""


def season_banner(n30, n90, scanned):
    """BTC 이긴 코인 수로 알트/BTC 시즌 힌트."""
    pct = (n90 / scanned * 100) if scanned else 0
    if pct >= 75:
        txt, col = "🔥 알트 시즌 (상위 코인 대부분이 BTC를 이김)", "#1b7a4b"
    elif pct <= 25:
        txt, col = "₿ 비트코인 시즌 (알트가 BTC에 약함 — 알트 신중)", "#b23a3a"
    else:
        txt, col = "⚖️ 중립 (혼조 — 선별 접근)", "#b8862b"
    return (f"<div class='op-season' style='background:{col}22;border:1px solid {col}'>"
            f"<b>{txt}</b><br>스캔 {scanned}개 중 BTC 이김: 30일 {n30}개 · 90일 {n90}개 "
            f"(90일 기준 {pct:.0f}%)</div>")


def page_html(stamp, top30, top90, n30, n90, scanned):
    def grid(items, period):
        if not items:
            return "<div class='empty'>BTC를 이긴 코인이 없습니다.</div>"
        return "<div class='grid'>" + "".join(card_html(c, period) for c in items) + "</div>"
    return f"""<!doctype html>
<html lang="ko"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="dark">
<title>BTC 강세 스캐너 · 알트시즌</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;700&family=Inter:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<style>{bs.CSS}{OP_CSS}</style>
</head><body>
<div class="wrap">
  <div class="top">
    <h1 class="brand">BTC 강세 스캐너<span class="dot">.</span></h1>
    <span class="sub">상위 {scanned}개 스캔 · BTC를 이긴 코인 · 초과수익 상위 {SHOW_TOP}</span>
    <span class="stamp">갱신 <b>{stamp}</b> KST</span>
  </div>

  {bs.nav_html("outperform")}

  {season_banner(n30, n90, scanned)}

  <div class="op-tabs">
    <button data-p="30" class="on" onclick="opShow('30')">30일 기준</button>
    <button data-p="90" onclick="opShow('90')">90일 기준</button>
  </div>

  <div data-period="30">
    <h3 class="op-h">🔥 30일 BTC 아웃퍼폼 상위 {len(top30)} <span class="mono">(30일 초과수익 순)</span></h3>
    {grid(top30, "30")}
  </div>
  <div data-period="90" style="display:none">
    <h3 class="op-h">🔥 90일 BTC 아웃퍼폼 상위 {len(top90)} <span class="mono">(90일 초과수익 순)</span></h3>
    {grid(top90, "90")}
  </div>

  <div class="how">
    <b>어떻게 보나</b> · 바이낸스 거래대금 상위 {scanned}개 중 최근 30·90일 <b>BTC보다 많이 오른</b>
    코인을 초과수익 순으로. 각 카드에 <b>정배열/역배열 배지 + EMA 20/50/100/200 차트</b>로 추세 정렬까지 확인.
    BTC를 이겼는데(강세) 정배열이면(추세 확인) 더 강한 후보. 상단 배너 개수로 알트시즌 판단.
  </div>
  <div class="foot">
    BTC 대비 강세는 '상대 성과'지 매수 신호가 아닙니다. 이미 많이 오른 코인은 되돌림 위험이 큽니다.
    CMC 알트시즌 인덱스와 같은 개념을 바이낸스 데이터로 자체 계산한 것이며, 투자 조언이 아닙니다.
  </div>
</div>
<script>{bs.JS}{OP_JS}</script>
</body></html>"""


def main():
    os.makedirs(bs.CHARTS, exist_ok=True)
    btc30, btc90, results = op.scan_outperformers(SCAN_TOP)
    if not results:
        print("❌ 아웃퍼폼 스캔 실패 (바이낸스 데이터 없음)")
        return

    beat30 = [r for r in results if r.beats_btc30]
    beat90 = [r for r in results if r.beats_btc90]
    top30 = sorted(beat30, key=lambda r: -r.excess30)[:SHOW_TOP]
    top90 = sorted(beat90, key=lambda r: -r.excess90)[:SHOW_TOP]

    for c in top30:
        img = render_chart(c, 30)
        with open(os.path.join(bs.CHARTS, f"op30_{c.symbol.replace('.', '_')}.png"), "wb") as f:
            f.write(img)
    for c in top90:
        img = render_chart(c, 90)
        with open(os.path.join(bs.CHARTS, f"op90_{c.symbol.replace('.', '_')}.png"), "wb") as f:
            f.write(img)

    stamp = datetime.now(bs.KST).strftime("%Y-%m-%d %H:%M")
    html = page_html(stamp, top30, top90, len(beat30), len(beat90), len(results))
    with open(os.path.join(bs.SITE, "outperform.html"), "w", encoding="utf-8") as f:
        f.write(html)
    print(f"✅ {bs.SITE}/outperform.html "
          f"(스캔 {len(results)} · BTC이김 30일 {len(beat30)}/90일 {len(beat90)} · 표시 상위 {SHOW_TOP})")


if __name__ == "__main__":
    main()
