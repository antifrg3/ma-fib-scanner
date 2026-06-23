#!/usr/bin/env python3
"""
build_site.py
─────────────────────────────────────────────────────────────────────────
미국(나스닥) + 한국(코스피/코스닥)을 스캔해서 정적 대시보드(site/index.html)를 만든다.
GitHub Actions가 매일 장 마감 후 이걸 돌려 GitHub Pages로 배포 → 링크만 열면 됨.
(이메일과 별개. 서버 불필요, 무료, 손 안 댐.)

이 결과물은 조건 충족 종목을 찾아주는 스크리너이며 투자 조언이 아님.
"""

import os
import shutil
from datetime import datetime, timedelta, timezone

import ma_fib_scanner as s

SITE = "site"
CHARTS = os.path.join(SITE, "charts")
KST = timezone(timedelta(hours=9))


def chart_url(ticker: str) -> str:
    """종목 클릭 시 열릴 TradingView 차트 주소."""
    if s.is_krw(ticker):                      # 005930.KS / 247540.KQ → KRX:005930
        code = ticker.split(".")[0]
        return f"https://www.tradingview.com/chart/?symbol=KRX:{code}"
    return f"https://www.tradingview.com/chart/?symbol={ticker}"


# ── 시그니처: 되돌림 게이지 (0=고점 → 1=저점, 0.382~0.618 매수구간) ──────────
def gauge_html(setup: dict) -> str:
    r = setup["r_now"]
    cur = max(0.0, min(1.0, r)) * 100
    in_zone = 0.382 <= r <= 0.618
    cur_cls = "g-cur in" if in_zone else "g-cur"
    if r < 0:
        note = "신고가 · 되돌림 대기"
    elif r > 1:
        note = "저점 이탈"
    else:
        note = f"되돌림 {r*100:.0f}%"
    return f"""
    <div class="gauge">
      <div class="g-track">
        <div class="g-zone"></div>
        <div class="g-tick" style="left:38.2%"></div>
        <div class="g-tick" style="left:50%"></div>
        <div class="g-tick" style="left:61.8%"></div>
        <div class="{cur_cls}" style="left:{cur:.1f}%"></div>
      </div>
      <div class="g-ends"><span>고점 0</span><span class="g-note">{note}</span><span>저점 1.0</span></div>
    </div>"""


def card_html(market: str, c: dict) -> str:
    s_ = c["setup"]
    t = c["ticker"]
    name = s.display_name(t)
    bp = s_["buy_prices"]
    fp = lambda x: s.fmt_price(x, t)
    chart_rel = f"charts/{market}_{t.replace('.', '_')}.png"
    code_badge = f"<span class='code'>{t}</span>" if name != t else ""
    return f"""
    <a class="card-link" href="{chart_url(t)}" target="_blank" rel="noopener">
    <article class="card reveal">
      <header class="card-h">
        <div class="ttl">
          <span class="nm">{name}</span>{code_badge}
        </div>
        <div class="px"><span class="px-num">{fp(s_['price'])}</span></div>
      </header>
      <div class="label">{c['label']}</div>
      {gauge_html(s_)}
      <div class="levels">
        <div class="lv"><span>분할매수</span><b>{fp(bp[0.382])} · {fp(bp[0.5])} · {fp(bp[0.618])}</b></div>
        <div class="lv"><span>익절(고점)</span><b>{fp(s_['take_profit'])}</b></div>
        <div class="lv"><span>손절</span><b>{fp(s_['stop'])}</b></div>
        <div class="lv"><span>골든크로스</span><b>{str(s_['cross_date']).split(' ')[0]}</b></div>
      </div>
      <div class="plate"><img loading="lazy" src="{chart_rel}" alt="{name} chart"></div>
      <div class="open">TradingView에서 차트 열기 ↗</div>
    </article>
    </a>"""


def watch_html(watch: list) -> str:
    if not watch:
        return ""
    chips = "".join(f"<span class='chip'>{s.display_name(w['ticker'])}</span>" for w in watch)
    return f"""
    <div class="watch">
      <div class="watch-h">관찰 대상 <span class="muted">골든크로스 발생 · 눌림 대기 {len(watch)}</span></div>
      <div class="chips">{chips}</div>
    </div>"""


def section_html(market: str, results: list) -> str:
    charted = [r for r in results if r.get("img")]
    charted.sort(key=lambda r: r["setup"]["r_now"])
    watch = [r for r in results if r["tier"] == "watch"]
    mid = "us" if market == "us" else "kr"
    active = "active" if market == "us" else ""

    if charted:
        cards = "".join(card_html(market, c) for c in charted)
        body = f"<div class='grid'>{cards}</div>"
    else:
        body = ("<div class='empty'>오늘 분할매수 구간(0.382~0.618)에 들어온 종목이 없습니다. "
                "관찰 대상만 확인하세요.</div>")

    return f"""
    <section id="sec-{mid}" class="market {active}">
      <div class="sec-meta">
        <span class="cnt"><b>{len(charted)}</b> 매수구간</span>
        <span class="cnt"><b>{len(watch)}</b> 관찰</span>
        <span class="cnt"><b>{len(results)}</b> 신호 종목</span>
      </div>
      {body}
      {watch_html(watch)}
    </section>"""


CSS = r"""
:root{
  --ink:#0F1115; --panel:#161922; --panel2:#1C2029; --line:#272C38;
  --tx:#E7E9EE; --mut:#8A93A6; --gold:#C8A24B; --jade:#5FB89B; --clay:#D8714F;
}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:
  radial-gradient(1200px 600px at 80% -10%, #1a1e29 0%, transparent 60%),
  var(--ink);
  color:var(--tx);
  font-family:"Inter","IBM Plex Sans",-apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo",sans-serif;
  line-height:1.55;}
.wrap{max-width:1080px;margin:0 auto;padding:28px 20px 80px}
.mono{font-family:"IBM Plex Mono",ui-monospace,Menlo,monospace}

/* header */
.top{display:flex;flex-wrap:wrap;align-items:baseline;gap:8px 16px;
  padding-bottom:18px;border-bottom:1px solid var(--line)}
.brand{font-family:"Space Grotesk","Inter",sans-serif;font-weight:700;
  font-size:23px;letter-spacing:-.02em;margin:0}
.brand .dot{color:var(--gold)}
.sub{color:var(--mut);font-size:13px}
.stamp{margin-left:auto;color:var(--mut);font-size:12.5px}
.stamp b{color:var(--tx);font-weight:600}

/* tabs */
.tabs{display:flex;gap:6px;margin:20px 0 8px}
.tab{appearance:none;border:1px solid var(--line);background:var(--panel);
  color:var(--mut);font:inherit;font-size:14px;font-weight:600;
  padding:9px 16px;border-radius:999px;cursor:pointer;transition:.18s}
.tab[aria-selected="true"]{color:var(--ink);background:var(--gold);border-color:var(--gold)}
.tab:hover{color:var(--tx)}
.tab[aria-selected="true"]:hover{color:var(--ink)}

.market{display:none}
.market.active{display:block}
.sec-meta{display:flex;gap:18px;margin:14px 2px 18px;color:var(--mut);font-size:13px}
.sec-meta .cnt b{color:var(--tx);font-family:"IBM Plex Mono",monospace}

/* grid + card */
.grid{display:grid;grid-template-columns:repeat(2,1fr);gap:16px}
@media(max-width:720px){.grid{grid-template-columns:1fr}}
a.card-link{display:block;text-decoration:none;color:inherit}
.card{background:linear-gradient(180deg,var(--panel2),var(--panel));
  border:1px solid var(--line);border-radius:14px;padding:16px 16px 14px;
  box-shadow:0 1px 0 rgba(255,255,255,.02) inset;
  transition:transform .16s ease,border-color .16s ease}
a.card-link:hover .card{border-color:var(--gold);transform:translateY(-2px)}
.open{margin-top:11px;text-align:right;font-size:11.5px;color:var(--mut);transition:color .16s}
a.card-link:hover .open{color:var(--gold)}
.card-h{display:flex;align-items:baseline;justify-content:space-between;gap:10px}
.ttl{display:flex;align-items:baseline;gap:8px;min-width:0}
.nm{font-weight:700;font-size:16px;letter-spacing:-.01em;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.code{font-family:"IBM Plex Mono",monospace;font-size:11px;color:var(--mut);
  border:1px solid var(--line);padding:1px 6px;border-radius:5px;flex:none}
.px-num{font-family:"IBM Plex Mono",monospace;font-size:16px;font-weight:600}
.label{margin:8px 0 2px;font-size:13px;color:var(--tx)}

/* signature gauge */
.gauge{margin:12px 0 6px}
.g-track{position:relative;height:8px;border-radius:6px;background:#0c0e13;
  border:1px solid var(--line);overflow:visible}
.g-zone{position:absolute;left:38.2%;width:23.6%;top:0;bottom:0;
  background:linear-gradient(90deg,rgba(200,162,75,.25),rgba(200,162,75,.45));
  border-left:1px solid var(--gold);border-right:1px solid var(--gold)}
.g-tick{position:absolute;top:-2px;width:1px;height:12px;background:var(--line)}
.g-cur{position:absolute;top:50%;width:12px;height:12px;border-radius:50%;
  background:var(--mut);transform:translate(-50%,-50%);
  box-shadow:0 0 0 3px var(--ink)}
.g-cur.in{background:var(--gold);box-shadow:0 0 0 3px var(--ink),0 0 12px rgba(200,162,75,.7)}
.g-ends{display:flex;justify-content:space-between;margin-top:7px;
  font-size:11px;color:var(--mut)}
.g-note{color:var(--gold);font-family:"IBM Plex Mono",monospace;font-weight:600}

/* levels */
.levels{display:grid;grid-template-columns:1fr 1fr;gap:4px 14px;margin:12px 0 4px}
.lv{display:flex;justify-content:space-between;gap:8px;font-size:12.5px;
  padding:3px 0;border-bottom:1px dashed rgba(255,255,255,.05)}
.lv span{color:var(--mut)}
.lv b{font-family:"IBM Plex Mono",monospace;font-weight:600}
.levels .lv:first-child{grid-column:1 / -1}

/* chart plate */
.plate{margin-top:12px;background:#fff;border-radius:10px;padding:6px;overflow:hidden}
.plate img{display:block;width:100%;height:auto;border-radius:6px}

/* watch + empty */
.watch{margin-top:22px;padding-top:16px;border-top:1px solid var(--line)}
.watch-h{font-weight:600;font-size:14px;margin-bottom:10px}
.muted,.watch-h .muted{color:var(--mut);font-weight:400;font-size:12.5px}
.chips{display:flex;flex-wrap:wrap;gap:7px}
.chip{font-size:12.5px;color:var(--tx);background:var(--panel);
  border:1px solid var(--line);padding:5px 11px;border-radius:999px}
.empty{padding:34px 20px;text-align:center;color:var(--mut);font-size:14px;
  background:var(--panel);border:1px dashed var(--line);border-radius:12px}

/* method + footer */
.how{margin-top:34px;padding:16px 18px;background:var(--panel);
  border:1px solid var(--line);border-radius:12px;color:var(--mut);font-size:12.5px}
.how b{color:var(--tx)}
.foot{margin-top:22px;color:var(--mut);font-size:11.5px;line-height:1.7}

/* motion */
.reveal{opacity:0;transform:translateY(8px);animation:rise .5s ease forwards}
@keyframes rise{to{opacity:1;transform:none}}
@media(prefers-reduced-motion:reduce){.reveal{animation:none;opacity:1;transform:none}}
"""

JS = r"""
const tabs=[...document.querySelectorAll('.tab')];
const secs={us:document.getElementById('sec-us'),kr:document.getElementById('sec-kr')};
function sel(m){tabs.forEach(t=>t.setAttribute('aria-selected', t.dataset.m===m));
  Object.entries(secs).forEach(([k,el])=>el&&el.classList.toggle('active',k===m));
  try{localStorage.setItem('mkt',m)}catch(e){}}
tabs.forEach(t=>t.addEventListener('click',()=>sel(t.dataset.m)));
let init='us';try{init=localStorage.getItem('mkt')||'us'}catch(e){}
sel(init);
// staggered reveal
[...document.querySelectorAll('.reveal')].forEach((el,i)=>el.style.animationDelay=(i%8*40)+'ms');
"""


def page_html(stamp: str, us_html: str, kr_html: str, meta: dict) -> str:
    return f"""<!doctype html>
<html lang="ko"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="dark">
<title>눌림목 스캐너 · 골든크로스 + 피보나치</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;700&family=Inter:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<style>{CSS}</style>
</head><body>
<div class="wrap">
  <div class="top">
    <h1 class="brand">눌림목 스캐너<span class="dot">.</span></h1>
    <span class="sub">골든크로스 후 피보나치 되돌림</span>
    <span class="stamp">갱신 <b>{stamp}</b> KST</span>
  </div>

  <div class="tabs" role="tablist">
    <button class="tab" role="tab" data-m="us">🇺🇸 미국 <span class="mono">{meta['us_n']}</span></button>
    <button class="tab" role="tab" data-m="kr">🇰🇷 한국 <span class="mono">{meta['kr_n']}</span></button>
  </div>

  {us_html}
  {kr_html}

  <div class="how">
    <b>어떻게 고르나</b> · ① 4시간봉 200선이 일봉 200선을 상향 돌파(골든크로스, 최근 120거래일 내)
    → ② 직전 저점~이후 고점 피보나치 되돌림에서 현재가가 0.382~0.618 구간에 들어온 종목.
    게이지의 금색 구간이 분할매수 구간, 점은 현재 위치. 차트의 파란선=일봉200, 주황선=4시간봉200.
  </div>
  <div class="foot">
    스캔 대상: 나스닥100 · 코스피200 · 데이터 Yahoo Finance · 매 거래일 장 마감 후 자동 갱신.<br>
    본 페이지는 조건 충족 종목을 찾아주는 스크리너이며 투자 조언이 아닙니다.
    진입·손절·익절 판단은 본인 책임입니다. 4시간봉 값은 TradingView와 다를 수 있어 최종 확인을 권장합니다.
  </div>
</div>
<script>{JS}</script>
</body></html>"""


def main():
    # site 폴더 초기화
    if os.path.exists(SITE):
        shutil.rmtree(SITE)
    os.makedirs(CHARTS, exist_ok=True)

    sections = {}
    meta = {}
    for market in ["us", "kr"]:
        cfg = s.Config()
        cfg.market = market
        print(f"=== 스캔: {market} ===")
        results = s.scan_all(cfg)
        # 차트 저장
        for c in results:
            if c.get("img"):
                fn = f"{market}_{c['ticker'].replace('.', '_')}.png"
                with open(os.path.join(CHARTS, fn), "wb") as f:
                    f.write(c["img"])
        sections[market] = section_html(market, results)
        meta[f"{market}_n"] = len([r for r in results if r.get("img")])

    stamp = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
    html = page_html(stamp, sections["us"], sections["kr"], meta)
    with open(os.path.join(SITE, "index.html"), "w", encoding="utf-8") as f:
        f.write(html)
    print(f"✅ {SITE}/index.html 생성 (미국 {meta['us_n']} · 한국 {meta['kr_n']} 매수구간)")


if __name__ == "__main__":
    main()
