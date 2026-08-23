#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_setup.py — 추세 템플릿 스크리너 → site/setup.html
─────────────────────────────────────────────────────────────────────────
미너비니 추세 템플릿 7조건 + 트리거 이벤트로 상승 초기 종목을 선별.
크립토(바이낸스) · 미국 · 한국 전부 대상.

섹션 구성:
  ⚡ 트리거 발생  — 조건 충족 + 오늘 뭔가 터진 종목(최우선)
  ✅ 통과(6/7+)  — 추세는 건강하나 아직 트리거 없음
  (미통과는 표시하지 않음)
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
import setup_screen as sc

BARS = 180          # 차트 표시 봉 수
SHOW_MAX = 40       # 섹션당 최대 표시 수


def _load(ticker: str, market: str):
    """시장별 일봉 로드."""
    try:
        cfg = s.Config()
        cfg.market = market
        daily, _ = s.get_data(ticker, cfg)
        return daily
    except Exception:
        return None


def scan():
    out = []
    for market in ("crypto", "us", "kr", "etf", "kretf"):
        try:
            universe = s.load_universe(market)
        except Exception:
            continue
        label = {"crypto": "크립토", "us": "미국", "kr": "한국",
                 "etf": "미국ETF", "kretf": "한국ETF"}.get(market, market)
        for t in universe:
            try:
                df = _load(t, market)
                if df is None or "Volume" not in df.columns:
                    continue
                r = sc.evaluate(t, df, label)
                if r is None:
                    continue
                # 통과했거나 트리거가 있으면 후보
                if r.passed or r.triggers:
                    out.append({"ticker": t, "market": market,
                                "result": r, "df": df})
            except Exception:
                continue
    return out


# ── 차트: 캔들 + 150/200일선 ──────────────────────────────────────────────
def render_chart(c: dict) -> bytes:
    df = c["df"].tail(BARS).copy()
    full = c["df"]
    r = c["result"]
    ma150 = full["Close"].rolling(sc.MA_MID).mean().tail(BARS)
    ma200 = full["Close"].rolling(sc.MA_LONG).mean().tail(BARS)

    adds = [
        mpf.make_addplot(ma150, color="#4fc3d2", width=1.1),
        mpf.make_addplot(ma200, color="#fe0d5f", width=1.3),
    ]
    mc = mpf.make_marketcolors(up="#26a69a", down="#ef5350", edge="inherit",
                               wick="inherit", volume="in")
    style = mpf.make_mpf_style(base_mpf_style="nightclouds", marketcolors=mc,
                               facecolor="#0e0e12", edgecolor="#0e0e12",
                               figcolor="#0e0e12", gridcolor="#1c1c24")
    buf = io.BytesIO()
    fig, axes = mpf.plot(df, type="candle", style=style, addplot=adds,
                         figsize=(7.6, 4.2), returnfig=True, volume=True,
                         tight_layout=True, xrotation=0, datetime_format="%m/%d")
    trig = " ".join(t.split()[0] for t in r.triggers)   # 이모지만
    axes[0].set_title(
        f"{c['ticker']}  {r.passed_count}/7  low+{r.gain_from_low:.0f}%  "
        f"high-{r.dist_from_high:.0f}%  {trig}  (150=cyan, 200=red)",
        fontsize=9.5, loc="left", color="#e8e8ee")
    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight", facecolor="#0e0e12")
    plt.close(fig)
    return buf.getvalue()


# ── HTML ───────────────────────────────────────────────────────────────────
def card_html(c: dict) -> str:
    t = c["ticker"]
    r = c["result"]
    name = s.display_name(t)
    code_badge = f"<span class='code'>{t}</span>" if name != t else ""
    chart_rel = f"charts/su_{t.replace('.', '_')}.png"

    checks = "".join(
        f"<span class='su-chk {'ok' if ok else 'no'}'>"
        f"{'✓' if ok else '✗'} {lab}<b>{val}</b></span>"
        for lab, ok, val in r.conds)
    trigs = "".join(f"<span class='su-trig'>{x}</span>" for x in r.triggers)
    cnt_cls = "su-full" if r.passed_count == 7 else "su-pass" if r.passed else "su-part"
    return f"""
    <div class="card">
      <div class="card-head">
        <span class="tk">{name}</span>{code_badge}
        <span class="su-badge {cnt_cls}">{r.passed_count}/7</span>
        <span class="su-mkt">{r.market}</span>
        {trigs}
      </div>
      <div class="su-checks">{checks}</div>
      <a class="card-link" href="{bs.chart_url(t)}" target="_blank" rel="noopener">
        <img loading="lazy" src="{chart_rel}" alt="{name}"></a>
      <div class="card-foot">
        <a class="card-link" href="{bs.chart_url(t)}" target="_blank" rel="noopener">
          TradingView에서 차트 열기 ↗</a>
      </div>
    </div>"""


SETUP_CSS = """
.card img{display:block;width:100%;height:auto;border-radius:6px;margin:4px 0}
.su-badge{padding:3px 10px;border-radius:6px;font-weight:700;font-size:13px;color:#fff}
.su-full{background:#1b7a4b}.su-pass{background:#2e7d32}.su-part{background:#5a5a66}
.su-mkt{font-size:12px;color:#8a8a99;padding:2px 8px;border:1px solid #2a2a34;border-radius:5px}
.su-trig{padding:3px 9px;border-radius:6px;font-size:12px;font-weight:700;
  background:#b8862b;color:#fff;margin-left:4px}
.su-checks{display:flex;flex-wrap:wrap;gap:6px;margin:9px 0 10px}
.su-chk{font-size:12px;padding:3px 8px;border-radius:5px;background:#16161c;
  border:1px solid #23232c;color:#9a9aa8}
.su-chk.ok{color:#7fd1a8;border-color:#1b5e3a}
.su-chk.no{color:#7a7a88}
.su-chk b{color:#d8d8e0;font-weight:600;margin-left:5px}
.su-h{margin:24px 0 10px;font-size:16px;color:#e8e8ee;font-weight:700}
.empty{color:#888;padding:24px;text-align:center}
"""


def page_html(stamp, trig_items, pass_items, scanned):
    def block(title, items, empty_msg):
        if items:
            cards = "".join(card_html(c) for c in items)
            return (f"<h3 class='su-h'>{title} <span class='mono'>{len(items)}</span></h3>"
                    f"<div class='grid'>{cards}</div>")
        return f"<h3 class='su-h'>{title}</h3><div class='empty'>{empty_msg}</div>"

    b1 = block("⚡ 트리거 발생 (돌파·신고가·횡보이탈)", trig_items,
               "오늘 트리거가 발생한 종목이 없습니다.")
    b2 = block(f"✅ 추세 템플릿 통과 ({sc.PASS_MIN_DEFAULT}/7 이상)", pass_items,
               "조건을 통과한 종목이 없습니다.")
    return f"""<!doctype html>
<html lang="ko"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="dark">
<title>셋업 스크리너 · 추세 템플릿</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;700&family=Inter:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<style>{bs.CSS}{SETUP_CSS}</style>
</head><body>
<div class="wrap">
  <div class="top">
    <h1 class="brand">셋업 스크리너<span class="dot">.</span></h1>
    <span class="sub">추세 템플릿 7조건 + 돌파 트리거 · 크립토/미국/한국</span>
    <span class="stamp">갱신 <b>{stamp}</b> KST</span>
  </div>

  {bs.nav_html("setup")}

  {b1}
  {b2}

  <div class="how">
    <b>7조건</b> · ① 150/200일선 위 ② 150일선&gt;200일선 ③ 200일선 우상향
    ④ 고점·저점 연속 상승 ⑤ 상승 시 거래량↑·하락 시↓ ⑥ 거래량 실린 상승봉 우위
    ⑦ 52주 저가 +25%↑ 이면서 고가 -25% 이내.
    <b>{sc.PASS_MIN_DEFAULT}개 이상</b> 충족하면 통과로 봅니다(실측 결과 6/7은 상위 10% 수준).
    <b>트리거</b>는 그 위에 얹히는 '오늘의 사건' — 전고점 돌파 장대양봉, 52주 신고가,
    횡보 후 돌파. 트리거가 있는 종목을 맨 위에 둡니다.
  </div>
  <div class="foot">
    스캔 대상 {scanned}종목. 조건 충족이 수익을 보장하지 않으며, 이미 크게 오른 종목은
    되돌림 위험이 큽니다. 백테스트로 검증된 신호가 아니며 투자 조언이 아닙니다.
  </div>
</div>
<script>{bs.JS}</script>
</body></html>"""


def main():
    os.makedirs(bs.CHARTS, exist_ok=True)
    results = scan()

    trig_items = sorted([c for c in results if c["result"].triggers],
                        key=lambda c: -c["result"].score)[:SHOW_MAX]
    trig_tickers = {c["ticker"] for c in trig_items}
    pass_items = sorted([c for c in results
                         if c["result"].passed and c["ticker"] not in trig_tickers],
                        key=lambda c: -c["result"].score)[:SHOW_MAX]

    for c in trig_items + pass_items:
        try:
            img = render_chart(c)
            fn = f"su_{c['ticker'].replace('.', '_')}.png"
            with open(os.path.join(bs.CHARTS, fn), "wb") as f:
                f.write(img)
        except Exception as e:
            print(f"  차트 실패 {c['ticker']}: {e}")

    stamp = datetime.now(bs.KST).strftime("%Y-%m-%d %H:%M")
    html = page_html(stamp, trig_items, pass_items, len(results))
    with open(os.path.join(bs.SITE, "setup.html"), "w", encoding="utf-8") as f:
        f.write(html)
    print(f"✅ {bs.SITE}/setup.html (트리거 {len(trig_items)} · 통과 {len(pass_items)})")


if __name__ == "__main__":
    main()
