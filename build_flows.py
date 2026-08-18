#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_flows.py — 시장 수급 대시보드 → site/flows.html
─────────────────────────────────────────────────────────────────────────
2층 구조:
  1층 요약 — 시장별 신호등 한 줄. "오늘 어디를 볼지" 한눈에.
  2층 상세 — 시장별 지표와 해석. 판단 근거 확인용.

대상: 비트코인(선물 포지션) · 나스닥 · S&P500(위험선호 환경)
코스피는 투자자별 수급 데이터 미확보로 이번 범위에서 제외.
"""
import os
from datetime import datetime

import build_site as bs
import flows as fl


FLOW_CSS = """
.fl-summary{display:grid;gap:10px;margin:18px 0 26px}
.fl-card{display:flex;align-items:center;gap:14px;padding:14px 16px;border-radius:10px;
  border:1px solid #23232c;background:#141419}
.fl-dot{font-size:20px}
.fl-name{font-weight:700;font-size:16px;color:#e8e8ee;min-width:96px}
.fl-head{font-size:14px;color:#b8b8c4}
.fl-bull{border-left:4px solid #1b7a4b}
.fl-bear{border-left:4px solid #b23a3a}
.fl-neutral{border-left:4px solid #b8862b}
.fl-sec{margin:26px 0 10px;font-size:17px;color:#e8e8ee;font-weight:700}
.fl-table{width:100%;border-collapse:collapse;font-size:14px}
.fl-table th{text-align:left;padding:8px 10px;color:#8a8a99;font-weight:600;
  border-bottom:1px solid #23232c;font-size:13px}
.fl-table td{padding:9px 10px;border-bottom:1px solid #1a1a20;color:#d8d8e0;vertical-align:top}
.fl-table td.v{font-family:'IBM Plex Mono',monospace;color:#e8e8ee;white-space:nowrap}
.fl-table td.n{color:#9a9aa8;font-size:13px}
.fl-badge{padding:2px 8px;border-radius:5px;font-size:12px;font-weight:700;color:#fff}
.fl-b-bull{background:#1b7a4b}.fl-b-bear{background:#b23a3a}
.fl-b-neutral{background:#5a5a66}.fl-b-warn{background:#b8862b}
.fl-note{color:#8a8a99;font-size:13px;margin:6px 0 18px}
"""

BADGE_CLS = {"bull": "fl-b-bull", "bear": "fl-b-bear",
             "neutral": "fl-b-neutral", "warn": "fl-b-warn"}
BADGE_TXT = {"bull": "강세", "bear": "약세", "neutral": "중립", "warn": "경계"}


def summary_html(markets):
    rows = ""
    for m in markets:
        dot = fl.SIGNAL_DOT[m.verdict]
        cls = fl.SIGNAL_CLS[m.verdict]
        rows += (f"<div class='fl-card {cls}'>"
                 f"<span class='fl-dot'>{dot}</span>"
                 f"<span class='fl-name'>{m.name}</span>"
                 f"<span class='fl-head'>{m.headline}</span></div>")
    return f"<div class='fl-summary'>{rows}</div>"


def detail_html(m):
    rows = ""
    for x in m.metrics:
        badge = (f"<span class='fl-badge {BADGE_CLS[x.signal]}'>"
                 f"{BADGE_TXT[x.signal]}</span>")
        rows += (f"<tr><td>{x.label}</td><td class='v'>{x.value}</td>"
                 f"<td>{badge}</td><td class='n'>{x.note}</td></tr>")
    return f"""
    <h3 class='fl-sec'>{fl.SIGNAL_DOT[m.verdict]} {m.name} — {m.headline}</h3>
    <table class='fl-table'>
      <tr><th>지표</th><th>값</th><th>신호</th><th>해석</th></tr>
      {rows}
    </table>"""


def page_html(stamp, markets):
    if not markets:
        body = "<div class='fl-note'>데이터를 가져오지 못했습니다.</div>"
    else:
        body = summary_html(markets) + "".join(detail_html(m) for m in markets)
    return f"""<!doctype html>
<html lang="ko"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="dark">
<title>시장 수급 · BTC / 나스닥 / S&P</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;700&family=Inter:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<style>{bs.CSS}{FLOW_CSS}</style>
</head><body>
<div class="wrap">
  <div class="top">
    <h1 class="brand">시장 수급<span class="dot">.</span></h1>
    <span class="sub">비트코인 포지션 · 미국 위험선호 환경</span>
    <span class="stamp">갱신 <b>{stamp}</b> KST</span>
  </div>

  {bs.nav_html("flows")}

  {body}

  <div class="how">
    <b>어떻게 보나</b> · 상단 신호등으로 오늘 어느 시장이 우호적인지 먼저 훑고,
    아래 표에서 근거를 확인하세요. <b>비트코인</b>은 선물 포지션 수급(펀딩비·미결제약정·
    롱숏비)으로 과열과 신규자금 유입을 봅니다. <b>나스닥·S&P</b>는 실제 자금흐름 대신
    VIX·금리·달러·하이일드로 위험선호 환경을 읽습니다.
    펀딩비 과열이나 개인 롱 쏠림은 <b>역방향 재료</b>로 해석합니다.
  </div>
  <div class="foot">
    수급은 방향을 보장하지 않으며 '환경'을 알려주는 참고 지표입니다.
    코스피는 투자자별 수급 데이터 확보 실패로 제외되어 있습니다.
    백테스트로 검증된 신호가 아니며 투자 조언이 아닙니다.
  </div>
</div>
<script>{bs.JS}</script>
</body></html>"""


def main():
    os.makedirs(bs.SITE, exist_ok=True)
    markets = fl.fetch_all()
    stamp = datetime.now(bs.KST).strftime("%Y-%m-%d %H:%M")
    html = page_html(stamp, markets)
    with open(os.path.join(bs.SITE, "flows.html"), "w", encoding="utf-8") as f:
        f.write(html)
    names = " · ".join(f"{m.name}={m.verdict}" for m in markets) or "실패"
    print(f"✅ {bs.SITE}/flows.html ({names})")


if __name__ == "__main__":
    main()
