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
    """SS밴드 결과 전송. longs/shorts = [{'ticker','state',...}]."""
    token, chat = _token_chat()
    if not token or not chat:
        print("  텔레그램 미설정 — 전송 스킵")
        return
    if not longs and not shorts:
        print("  신호 0개 — 텔레그램 전송 생략")
        return

    # 1) 요약 메시지
    def names(items):
        return ", ".join(c["ticker"].replace("USDT", "") for c in items) or "—"
    lines = [f"🌊 <b>SS밴드 스캔</b>  {stamp} KST",
             f"🟢 롱 {len(longs)}개: {names(longs)}",
             f"🔴 숏 {len(shorts)}개: {names(shorts)}",
             f'<a href="{DASHBOARD_URL}">대시보드 열기</a>']
    send_message("\n".join(lines))

    # 2) 코인별 차트 (많으면 상위 max_charts개만)
    sent = 0
    for c in longs + shorts:
        if sent >= max_charts:
            send_message(f"…외 {len(longs) + len(shorts) - sent}개는 대시보드에서 확인")
            break
        t = c["ticker"]
        st = c["state"]
        sig = "🟢 롱 4/4" if st.signal == "long" else "🔴 숏 4/4"
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
            send_message(caption)  # 차트 없으면 텍스트만
            sent += 1
    print(f"  텔레그램 전송 완료: 요약 1 + 차트 {sent}")
