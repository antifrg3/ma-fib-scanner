#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
notify_telegram.py — SS밴드 스캔 결과 텔레그램 전송
─────────────────────────────────────────────────────────────────────────
사용: build_ssband.py 실행 후 결과(롱/숏 신호)를 텔레그램으로.
  · 요약 메시지 1개 (신호 코인 목록 + 대시보드 링크)
  · 코인별 차트 이미지 + 트레이딩뷰 링크 (캡션)
  · 신호 0개면 아무것도 안 보냄 (스팸 방지)

환경변수(GitHub Secrets):
  TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID
없으면 조용히 스킵 (로컬 실행 시 전송 안 됨).
"""
import json
import os
import urllib.request
import urllib.parse

API = "https://api.telegram.org/bot{token}/{method}"
DASHBOARD_URL = "https://antifrg3.github.io/ma-fib-scanner/ssband.html"
STATE_URL = "https://antifrg3.github.io/ma-fib-scanner/ss_state.json"


def load_prev_signals() -> set:
    """이전 스캔의 신호 집합을 배포된 사이트에서 읽음. 실패 시 빈 set(전부 신규 취급)."""
    try:
        req = urllib.request.Request(STATE_URL, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            d = json.loads(r.read().decode())
        return set(d.get("signals", []))
    except Exception:
        return set()


def save_state(longs: list, shorts: list, site_dir: str, stamp: str):
    """이번 신호를 site/ss_state.json에 저장(배포되면 다음 실행이 읽음)."""
    sigs = ([f"long:{c['ticker']}" for c in longs] +
            [f"short:{c['ticker']}" for c in shorts])
    try:
        with open(os.path.join(site_dir, "ss_state.json"), "w", encoding="utf-8") as f:
            json.dump({"stamp": stamp, "signals": sigs}, f, ensure_ascii=False)
    except Exception as e:
        print(f"  상태 저장 실패(무시): {e}")


def _token_chat():
    return os.environ.get("TELEGRAM_BOT_TOKEN", ""), os.environ.get("TELEGRAM_CHAT_ID", "")


def _post(method: str, data: dict, files: dict | None = None) -> bool:
    token, _ = _token_chat()
    url = API.format(token=token, method=method)
    try:
        if files:
            # multipart/form-data 수동 구성 (사진 업로드)
            boundary = "----ssbandboundary7351"
            body = b""
            for k, v in data.items():
                body += (f"--{boundary}\r\nContent-Disposition: form-data; "
                         f"name=\"{k}\"\r\n\r\n{v}\r\n").encode()
            for k, (fname, fbytes) in files.items():
                body += (f"--{boundary}\r\nContent-Disposition: form-data; "
                         f"name=\"{k}\"; filename=\"{fname}\"\r\n"
                         f"Content-Type: image/png\r\n\r\n").encode() + fbytes + b"\r\n"
            body += f"--{boundary}--\r\n".encode()
            req = urllib.request.Request(url, data=body, headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}"})
        else:
            req = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode())
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode()).get("ok", False)
    except Exception as e:
        print(f"  텔레그램 전송 실패({method}): {e}")
        return False


def send_message(text: str) -> bool:
    token, chat = _token_chat()
    if not token or not chat:
        print("  텔레그램 미설정 — 전송 스킵")
        return False
    return _post("sendMessage", {"chat_id": chat, "text": text,
                                 "parse_mode": "HTML", "disable_web_page_preview": "true"})


def send_photo(png_bytes: bytes, caption: str) -> bool:
    token, chat = _token_chat()
    if not token or not chat:
        return False
    return _post("sendPhoto", {"chat_id": chat, "caption": caption, "parse_mode": "HTML"},
                 files={"photo": ("chart.png", png_bytes)})


def tv_link(symbol: str) -> str:
    return f"https://www.tradingview.com/chart/?symbol=BINANCE%3A{symbol}"


def notify_ssband(longs: list, shorts: list, charts_dir: str, stamp: str,
                  max_charts: int = 10):
    """SS밴드 결과 전송 — '신규 발생' 신호만. longs/shorts = [{'ticker','state',...}]."""
    token, chat = _token_chat()
    if not token or not chat:
        print("  텔레그램 미설정 — 전송 스킵")
        return

    prev = load_prev_signals()
    new_longs = [c for c in longs if f"long:{c['ticker']}" not in prev]
    new_shorts = [c for c in shorts if f"short:{c['ticker']}" not in prev]

    if not new_longs and not new_shorts:
        print(f"  신규 신호 0개 (전체 롱{len(longs)}/숏{len(shorts)}는 유지 중) — 전송 생략")
        return

    # 1) 요약: 신규 강조 + 전체 현황
    def names(items):
        return ", ".join(c["ticker"].replace("USDT", "") for c in items) or "—"
    lines = [f"🌊 <b>SS밴드 — 신규 신호</b>  {stamp} KST"]
    if new_longs:
        lines.append(f"🟢 신규 롱 {len(new_longs)}개: <b>{names(new_longs)}</b>")
    if new_shorts:
        lines.append(f"🔴 신규 숏 {len(new_shorts)}개: <b>{names(new_shorts)}</b>")
    lines.append(f"(전체 유지: 롱 {len(longs)} · 숏 {len(shorts)})")
    lines.append(f'<a href="{DASHBOARD_URL}">대시보드 열기</a>')
    send_message("\n".join(lines))

    # 2) 신규 코인 차트만
    sent = 0
    for c in new_longs + new_shorts:
        if sent >= max_charts:
            send_message(f"…외 신규 {len(new_longs) + len(new_shorts) - sent}개는 대시보드에서 확인")
            break
        t = c["ticker"]
        st = c["state"]
        sig = "🟢 신규 롱 4/4" if st.signal == "long" else "🔴 신규 숏 4/4"
        fn = os.path.join(charts_dir, f"ss_{t.replace('.', '_')}.png")
        caption = (f"{sig}  <b>{t}</b>\n"
                   f'<a href="{tv_link(t)}">TradingView 차트</a> · '
                   f'<a href="{DASHBOARD_URL}">대시보드</a>')
        try:
            with open(fn, "rb") as f:
                png = f.read()
            if send_photo(png, caption):
                sent += 1
        except FileNotFoundError:
            send_message(caption)
            sent += 1
    print(f"  텔레그램 전송: 신규 롱{len(new_longs)}/숏{len(new_shorts)} · 차트 {sent}")
