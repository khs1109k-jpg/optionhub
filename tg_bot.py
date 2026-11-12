import csv
import io
import json
import os
import re
import subprocess
import time
import urllib.parse
import urllib.request

CFG_PATH = os.path.expanduser("~/.telegram_config.json")
STATE_PATH = os.path.expanduser("~/.last_tg_review.txt")
OI_PATH = os.path.expanduser("~/.optionhub_oi_history.json")
APP_PATH = os.path.expanduser("~/app.py")
SHEET_ID = "1_FWy_B9a6t1txau06PbeEMy9S9B1GsMgWZLGfMmMG7w"

MENU_KEYBOARD = {
    "keyboard": [
        [{"text": "📝 오늘의 종합평"}, {"text": "📊 주요 GEX 요약"}],
        [{"text": "🖼️ 차트 지금 받기"}, {"text": "📐 Geeks·Menthor Q"}],
        [{"text": "🔥 $10M+ 대형체결"}, {"text": "🚀 Top 10 문샷"}],
    ],
    "resize_keyboard": True,
    "is_persistent": True,
}


def load_cfg():
    with open(CFG_PATH, "r", encoding="utf-8") as f:
        c = json.load(f)
    return c["token"], str(c["chat_id"])


def set_bot_commands(token):
    cmds = [
        {"command": "menu", "description": "📱 하단 버튼 메뉴 열기"},
        {"command": "summary", "description": "📝 오늘의 종합평"},
        {"command": "gex", "description": "📊 GEX·Zero Gamma 조회 (예: /gex NVDA)"},
        {"command": "chart", "description": "🖼️ 실시간 GEX 차트 받기"},
        {"command": "geeks", "description": "📐 최신 Geeks·Menthor Q 리포트"},
        {"command": "flow", "description": "🔥 종목별 옵션 플로우 (예: /flow TSLA)"},
    ]
    try:
        url = f"https://api.telegram.org/bot{token}/setMyCommands"
        payload = json.dumps({"commands": cmds}).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=10).read()
    except Exception:
        pass


def send_msg(token, chat_id, text, with_menu=True):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    chunks = [text[i : i + 3800] for i in range(0, len(text), 3800)] or ["(내용 없음)"]
    for idx, chunk in enumerate(chunks):
        body = {"chat_id": chat_id, "text": chunk, "disable_web_page_preview": True}
        if with_menu and idx == len(chunks) - 1:
            body["reply_markup"] = MENU_KEYBOARD
        payload = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            url, data=payload, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            resp.read()


def get_app_flows():
    flows = []
    if not os.path.exists(APP_PATH):
        return flows
    with open(APP_PATH, "r", encoding="utf-8") as f:
        src = f.read()
    try:
        ns = {}
        part = src.split("DEFAULT_FLOWS = [")[1].split("]\n")[0]
        exec(f"DEFAULT_FLOWS = [{part}]", ns)
        flows = ns.get("DEFAULT_FLOWS", [])
    except Exception:
        pass
    return flows


def get_app_review():
    if not os.path.exists(APP_PATH):
        return "대시보드 파일(~/app.py)을 찾을 수 없습니다."
    with open(APP_PATH, "r", encoding="utf-8") as f:
        src = f.read()
    try:
        return src.split('DAILY_REVIEW_2026_11_11 = """')[1].split('"""')[0]
    except Exception:
        return "종합평 데이터를 불러오지 못했습니다."


def parse_prem_usd(p_str):
    s = str(p_str).replace("$", "").replace(",", "").strip().upper()
    try:
        if s.endswith("M"):
            return float(s[:-1]) * 1_000_000
        if s.endswith("K"):
            return float(s[:-1]) * 1_000
        return float(s)
    except Exception:
        return 0.0


def fetch_sheet_rows(sheet_name):
    url = (
        f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&sheet="
        + urllib.parse.quote(sheet_name)
    )
    data = urllib.request.urlopen(url, timeout=15).read().decode("utf-8")
    return list(csv.DictReader(io.StringIO(data)))


def calc_zero_gamma_from_rows(oi_rows, spot=0.0):
    by_k = {}
    for x in oi_rows:
        k = float(x.get("행사가", 0))
        by_k[k] = by_k.get(k, 0.0) + float(x.get("GEX($M)", 0.0))
    pts = sorted(by_k.items())
    flips = []
    for i in range(len(pts) - 1):
        k1, g1 = pts[i]
        k2, g2 = pts[i + 1]
        if (g1 < 0 and g2 > 0) or (g1 > 0 and g2 < 0):
            flips.append(round(k1 + (0.0 - g1) * (k2 - k1) / (g2 - g1), 2))
    if not flips:
        return None
    return min(flips, key=lambda x: abs(x - spot)) if spot > 0 else flips[len(flips) // 2]


def format_gex_summary(target_tk=None):
    if not os.path.exists(OI_PATH):
        return "저장된 OI·GEX 데이터가 아직 없습니다. (`auto_oi.py` 실행 필요)"
    hist = json.load(open(OI_PATH, "r", encoding="utf-8"))
    if target_tk:
        tk = target_tk.upper()
        snaps = hist.get(tk)
        if not snaps:
            return f"'{tk}'의 저장된 OI·GEX 스냅샷이 없습니다."
        s = snaps[-1]
        zg = calc_zero_gamma_from_rows(s.get("상세", []), float(s.get("Spot", 0)))
        return (
            f"📊 [{tk} 최신 OI · GEX] ({s.get('수집시각', '')})\n"
            f"• 현재가(Spot): ${s.get('Spot', '-')}\n"
            f"• Net GEX: {s.get('Net_GEX_M', 0):+.2f}M\n"
            f"• Zero Gamma(플립): {f'${zg:g}' if zg else '-'}\n"
            f"• Call OI: {s.get('Call_OI', 0):,} / Put OI: {s.get('Put_OI', 0):,}\n"
            f"• P/C 비율: {s.get('Put_Call_OI_Ratio', 0)}"
        )

    lines = ["📊 [주요 종목 최신 GEX · Zero Gamma 요약]\n"]
    priority = ["SPY", "QQQ", "IWM", "NVDA", "TSLA", "MU", "AMD", "META", "INTC", "SNDK"]
    keys = [k for k in priority if k in hist] + [k for k in sorted(hist.keys()) if k not in priority]
    for tk in keys[:15]:
        s = hist[tk][-1]
        zg = calc_zero_gamma_from_rows(s.get("상세", []), float(s.get("Spot", 0)))
        zg_s = f" | ZG ${zg:g}" if zg else ""
        lines.append(f"• {tk} (${s.get('Spot', '-')}): GEX {s.get('Net_GEX_M', 0):+.2f}M{zg_s} | P/C {s.get('Put_Call_OI_Ratio', 0)}")
    lines.append("\n💡 특정 종목 상세 조회: 티커만 입력 (예: NVDA)")
    return "\n".join(lines)


def send_ticker_gex_with_chart(token, chat_id, raw_tk):
    tk = raw_tk.strip().upper()
    yf_tk = {"SPX": "^SPX", "NDX": "^NDX", "VIX": "^VIX", "RUT": "^RUT"}.get(tk, tk)
    try:
        import sys
        sys.path.insert(0, os.path.expanduser("~"))
        import gex_chart_tg as gc
        send_msg(token, chat_id, f"🔎 [{tk}] 실시간 GEX · Zero Gamma 차트를 생성 중입니다...")
        rows, spot = gc.fetch_chain_for_chart(yf_tk)
        if rows:
            png_bytes, net_gex, cw, pw, pc, zg = gc.render_gex_png(tk, rows, spot)
            cap = (
                f"📊 [{tk} 실시간 GEX · OI 차트]\n"
                f"• 현재가(Spot): ${spot}\n"
                f"• Net GEX: {net_gex:+.2f}M\n"
                f"• Zero Gamma(플립): {(f'${zg:g}' if zg else '-')}\n"
                f"• Call Wall(저항): ${cw:g} | Put Wall(지지): ${pw:g}\n"
                f"• P/C 비율: {pc}"
            )
            if gc.send_tg_photo(token, chat_id, png_bytes, caption=cap):
                return
    except Exception:
        pass
    send_msg(token, chat_id, format_gex_summary(tk))

def handle_command(token, chat_id, text):
    cmd = text.strip()
    low = cmd.lower()

    if low in ("/start", "/help", "/menu", "도움말", "메뉴"):
        help_txt = (
            "🤖 [OptionHub 텔레그램 메뉴 활성화 완료]\n\n"
            "아래 버튼을 누르거나 티커(예: NVDA, TSLA)를 바로 입력해 보세요!\n"
            "🌐 웹 대시보드: http://132.226.3.145:8501"
        )
        send_msg(token, chat_id, help_txt, with_menu=True)

    elif low in ("/종합평", "/summary") or cmd == "📝 오늘의 종합평":
        send_msg(token, chat_id, get_app_review())

    elif low in ("/문샷",) or cmd == "🚀 Top 10 문샷":
        ms = (
            "🚀 [OptionHub] Top 10 Moonshot Flows\n\n"
            "• INTC 85C (2026-11-27) @ $55K / $42K (Unusual · Sweep)\n"
            "• PDFS 50C (2026-11-20) @ $12K (Unusual · Sweep)\n"
            "• BW 7C (2026-12-18) @ $74K / 7.5C (2027-01-15) @ $75K\n"
            "• CIFR 9C (2027-01-15) @ $870K (Above Ask · Block)\n"
            "• FRVO 21C (2027-01-15) @ $134K (Top Position · Sweep)\n"
            "• AZTA 55C (2026-11-20) @ $11K (Unusual · Sweep)\n"
            "• LSCC 160C (2027-01-15) @ $133K (Top Position · Block)\n"
            "• ACHR 6C (2027-01-15) @ $71K (Sweep)\n\n"
            "⚡ 모멘텀 급증: KGC (11.2x), BW (6.0x), BZ (5.5x), ACHR (5.3x)"
        )
        send_msg(token, chat_id, ms)

    elif low.startswith("/gex") or cmd == "📊 주요 GEX 요약":
        parts = cmd.split()
        tk = parts[1] if (low.startswith("/gex") and len(parts) >= 2) else None
        if tk:
            send_ticker_gex_with_chart(token, chat_id, tk)
        else:
            send_msg(token, chat_id, format_gex_summary(None))

    elif low.startswith("/chart") or cmd == "🖼️ 차트 지금 받기":
        send_msg(token, chat_id, "🖼️ 실시간 GEX·Zero Gamma 차트를 생성해 보내드리는 중입니다...")
        subprocess.Popen(["/home/ubuntu/venv/bin/python3", "/home/ubuntu/gex_chart_tg.py"])

    elif low.startswith("/geeks") or cmd == "📐 Geeks·Menthor Q":
        try:
            rows = fetch_sheet_rows("AI노트_뉴스시황")
            sub = [r for r in rows if any(k in str(r.get("섹션", "")) for k in ("Geeks", "맨도큐", "Menthor", "SpotGamma"))][-5:][::-1]
            if not sub:
                send_msg(token, chat_id, "저장된 Geeks/Menthor Q 리포트가 없습니다.")
            else:
                lines = ["📐 [최신 Geeks · Menthor Q · SpotGamma 요약]\n"]
                for r in sub:
                    lines.append(f"🔹 [{r.get('날짜','')}] {r.get('종목','')}\n{r.get('한글 번역/해석','')}\n")
                send_msg(token, chat_id, "\n".join(lines))
        except Exception as e:
            send_msg(token, chat_id, f"조회 오류: {e}")

    elif low.startswith("/flow"):
        parts = cmd.split()
        if len(parts) < 2:
            send_msg(token, chat_id, "사용법: /flow NVDA  (조회할 티커를 함께 입력해 주세요)")
            return
        tk = parts[1].strip().upper()
        flows = [r for r in get_app_flows() if r[1] == tk]
        lines = [f"🔥 [{tk}] 옵션 플로우 조회 결과 ({len(flows)}건)\n"]
        for r in flows[:15]:
            lines.append(f"• [{r[0]} {r[2]}] {r[7]} {r[3]} ({r[5]}) @ {r[14]} [{r[13]}]")
        try:
            sh_rows = [r for r in fetch_sheet_rows("전체") if str(r.get("Ticker (티커)", "")).strip().upper() == tk]
            if sh_rows:
                lines.append(f"\n📊 구글 시트 누적 기록 (최근 {min(8, len(sh_rows))}건):")
                for sr in sh_rows[-8:][::-1]:
                    lines.append(
                        f"• [{sr.get('Section (섹션)','')}] {sr.get('Strike Price (행사가)','')} {sr.get('Option Type (구분)','')} ({sr.get('Expiration Date (만기일)','')}) @ {sr.get('Premium (프리미엄)','')}"
                    )
        except Exception:
            pass
        if len(lines) == 1:
            lines.append("해당 종목의 기록이 없습니다.")
        send_msg(token, chat_id, "\n".join(lines))

    elif low.startswith("/스캔") or cmd == "🔥 $10M+ 대형체결":
        parts = cmd.split()
        min_m = 10.0
        if low.startswith("/스캔") and len(parts) >= 2:
            try:
                min_m = float(parts[1])
            except Exception:
                pass
        threshold = min_m * 1_000_000
        hits = [r for r in get_app_flows() if parse_prem_usd(r[14]) >= threshold]
        lines = [f"🔍 [${min_m:g}M 이상 초대형 체결 스캔] ({len(hits)}건)\n"]
        for r in hits[:20]:
            lines.append(f"• [{r[0]}] {r[1]} {r[7]} {r[3]} ({r[5]}) @ {r[14]} [{r[13]}]")
        send_msg(token, chat_id, "\n".join(lines))

    elif re.fullmatch(r"[A-Za-z]{1,5}", cmd):
        send_ticker_gex_with_chart(token, chat_id, cmd)


def check_sheet_review(token, chat_id):
    try:
        last_seen = open(STATE_PATH, "r", encoding="utf-8").read().strip() if os.path.exists(STATE_PATH) else ""
        rows = fetch_sheet_rows("AI노트_뉴스시황")
        reviews = [r for r in rows if "종합평" in str(r)]
        if reviews:
            latest = reviews[-1]
            key = f"{latest.get('날짜', '')}_{latest.get('한글 번역/해석', '')[:40]}"
            if key and key != last_seen:
                msg = (
                    f"📝 [OptionHub 자동 종합평] {latest.get('날짜', '')}\n\n"
                    f"{latest.get('한글 번역/해석', '')}\n\n"
                    f"🌐 http://132.226.3.145:8501"
                )
                send_msg(token, chat_id, msg)
                with open(STATE_PATH, "w", encoding="utf-8") as f:
                    f.write(key)
    except Exception:
        pass


def main():
    token, my_chat_id = load_cfg()
    set_bot_commands(token)
    offset = 0
    last_sheet_check = 0
    print("🤖 OptionHub Telegram Bot & Menu started!")
    while True:
        try:
            now = time.time()
            if now - last_sheet_check >= 300:
                check_sheet_review(token, my_chat_id)
                last_sheet_check = now

            url = f"https://api.telegram.org/bot{token}/getUpdates?timeout=20&offset={offset}"
            data = json.loads(urllib.request.urlopen(url, timeout=30).read().decode("utf-8"))
            for upd in data.get("result", []):
                offset = upd["update_id"] + 1
                msg = upd.get("message") or {}
                txt = msg.get("text", "")
                cid = str(msg.get("chat", {}).get("id", ""))
                if txt and cid == my_chat_id:
                    handle_command(token, cid, txt)
        except Exception as e:
            print("Loop err:", e)
            time.sleep(5)


if __name__ == "__main__":
    main()