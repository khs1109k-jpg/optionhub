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
LIVE_PATH = os.path.expanduser("~/.optionhub_intraday_live.json")
EARN_PATH = os.path.expanduser("~/.optionhub_earnings_scan.json")
TIDE_PATH = os.path.expanduser("~/.optionhub_tide_brief.json")
APP_PATH = os.path.expanduser("~/app.py")
SHEET_ID = "1_FWy_B9a6t1txau06PbeEMy9S9B1GsMgWZLGfMmMG7w"

INLINE_MENU = {
    "inline_keyboard": [
        [
            {"text": "📝 오늘의 종합평", "callback_data": "cmd:summary"},
            {"text": "📊 주요 GEX 요약", "callback_data": "cmd:gex"},
        ],
        [
            {"text": "🖼️ 차트 지금 받기", "callback_data": "cmd:chart"},
            {"text": "📐 Geeks·Menthor Q", "callback_data": "cmd:geeks"},
        ],
        [
            {"text": "⚡ 장중 Vol>OI", "callback_data": "cmd:live"},
            {"text": "📅 실발 예상변동폭", "callback_data": "cmd:em"},
        ],
        [
            {"text": "🔥 $10M+ 대형체결", "callback_data": "cmd:scan"},
            {"text": "🎯 조용한 OI 급증", "callback_data": "cmd:oi"}, {"text": "🚀 Top 10 문샷", "callback_data": "cmd:moon"},
        ],
    ]
}


def load_cfg():
    with open(CFG_PATH, "r", encoding="utf-8") as f:
        c = json.load(f)
    return c["token"], str(c["chat_id"])


def set_bot_commands(token):
    cmds = [
        {"command": "menu", "description": "📱 기능 메뉴 열기"},
        {"command": "summary", "description": "📝 오늘의 종합평"},
        {"command": "gex", "description": "📊 GEX·Zero Gamma 조회 (예: /gex NVDA)"},
        {"command": "chart", "description": "🖼️ 실시간 GEX 차트 받기"},
        {"command": "geeks", "description": "📐 최신 Geeks·Menthor Q 리포트"},
        {"command": "flow", "description": "🔥 종목별 옵션 플로우 (예: /flow TSLA)"},
        {"command": "oi", "description": "🎯 전일 대비 조용한 OI 급증 TOP 10"},
        {"command": "vol", "description": "⚡ 장중 실시간 Vol > OI 신규 매집 스캔"},
        {"command": "em", "description": "📅 실적 발표 D-10 예상 변동폭 · Wall"},
    ]
    try:
        url = f"https://api.telegram.org/bot{token}/setMyCommands"
        payload = json.dumps({"commands": cmds}).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=10).read()
    except Exception:
        pass


def send_msg(token, chat_id, text, reply_markup=None):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    chunks = [text[i : i + 3800] for i in range(0, len(text), 3800)] or ["(내용 없음)"]
    for idx, chunk in enumerate(chunks):
        body = {"chat_id": chat_id, "text": chunk, "disable_web_page_preview": True}
        if reply_markup is not None and idx == len(chunks) - 1:
            body["reply_markup"] = reply_markup
        payload = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            url, data=payload, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            resp.read()


def answer_callback(token, cb_id):
    try:
        url = f"https://api.telegram.org/bot{token}/answerCallbackQuery"
        payload = json.dumps({"callback_query_id": cb_id}).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=5).read()
    except Exception:
        pass


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
    lines.append("\n💡 특정 종목 상세+차트: 티커만 입력 (예: NVDA)")
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


def format_stealth_oi():
    if not os.path.exists(OI_PATH):
        return "저장된 OI 히스토리가 아직 없습니다."
    hist = json.load(open(OI_PATH, "r", encoding="utf-8"))
    hits = []
    for tk, snaps in hist.items():
        if len(snaps) < 2:
            continue
        prev = {(x["만기"], x["구분"], x["행사가"]): x["OI"] for x in snaps[-2].get("상세", [])}
        for x in snaps[-1].get("상세", []):
            p_oi = prev.get((x["만기"], x["구분"], x["행사가"]), 0)
            if p_oi >= 10 and x["OI"] >= 10:
                diff = x["OI"] - p_oi
                if abs(diff) >= 300:
                    hits.append((abs(diff), diff, tk, snaps[-1].get("Spot", 0), x["만기"], x["구분"], x["행사가"], p_oi, x["OI"]))
    if not hits:
        return "🕵️ 아직 2일치 이상 누적된 OI 비교 데이터가 부족합니다. 내일 오전 6:30 수집 후부터 자동 포착됩니다!"
    hits.sort(reverse=True)
    lines = ["🕵️ [전일 대비 OI 신규 오픈(+) · 대량 청산(-) TOP 12]\n"]
    for _, diff, tk, sp, exp, cp, k, p0, p1 in hits[:12]:
        tag = "🟢[신규]" if diff > 0 else "🔴[청산]"
        lines.append(f"{tag} {tk} (${sp}) {k:g}{cp[0]} ({exp}): {p0:,} → {p1:,} ({diff:+,})")
    return "\n".join(lines)


def format_live_vol_oi():
    from datetime import datetime
    data = {}
    if os.path.exists(LIVE_PATH):
        try:
            data = json.load(open(LIVE_PATH, "r", encoding="utf-8"))
        except Exception:
            data = {}
    fresh = False
    if data.get("updated"):
        try:
            dt = datetime.strptime(data["updated"], "%Y-%m-%d %H:%M")
            fresh = (datetime.now() - dt).total_seconds() <= 600
        except Exception:
            pass
    if not fresh:
        try:
            import sys
            sys.path.insert(0, os.path.expanduser("~"))
            import intraday_vol_oi as ivo
            hits, _ = ivo.scan_vol_gt_oi(ivo.get_target_tickers(), check_levels=False)
            data = {"updated": datetime.now().strftime("%Y-%m-%d %H:%M"), "items": hits[:30]}
            with open(LIVE_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            return f"장중 스캔 오류: {e}"
    items = data.get("items", [])
    if not items:
        upd = data.get('updated', '-')
        return f"⚡ [장중 Vol > OI 스캔] ({upd})\n현재 조건(Vol > OI & +500계약)에 해당하는 종목이 없습니다."
    upd = data.get('updated', '')
    lines = [f"⚡ [장중 실시간 Vol > OI TOP {min(12, len(items))}] ({upd})\n"]
    for h in items[:12]:
        prem_s = h.get('prem_str', '')
        hint_s = h.get('hint', '')
        lines.append(
            f"• {h['tk']} (${h['spot']}) {h['k']:g}{h['cp'][0]} ({h['exp']}) | {prem_s}\n"
            f"  Vol {h['vol']:,} > OI {h['oi']:,} ({h['ratio']}x) → +{h['min_new']:,} | {hint_s}"
        )
    return "\n".join(lines)


def format_earnings_em():
    if not os.path.exists(EARN_PATH):
        return "📅 저장된 실적 발표 스캔 데이터가 없습니다. (`auto_oi.py` 실행 후 자동 생성)"
    data = json.load(open(EARN_PATH, "r", encoding="utf-8"))
    items = data.get("items", [])
    if not items:
        upd = data.get('updated', '-')
        return f"📅 [실적 발표 D-10 스캔] ({upd})\n10일 이내 실적 발표 예정 종목이 없습니다."
    upd = data.get('updated', '')
    lines = [f"📅 [실적 발표 D-10 예상 변동폭 · Wall] ({upd})\n"]
    for it in items[:15]:
        tk_i = it.get('티커', '')
        sp_i = it.get('현재가($)', '-')
        ed_i = it.get('실발일', '')
        dd_i = it.get('D-Day', '')
        em_i = it.get('예상변동폭(±)', '-')
        cw_i = it.get('Call Wall', '-')
        pw_i = it.get('Put Wall', '-')
        lines.append(
            f"• {tk_i} (${sp_i}) | {ed_i} ({dd_i})\n"
            f"  예상변동폭: {em_i} | CW {cw_i} / PW {pw_i}"
        )
    return "\n".join(lines)


def parse_and_save_tide_brief(text):
    from datetime import datetime
    data = {}
    if os.path.exists(TIDE_PATH):
        try:
            data = json.load(open(TIDE_PATH, "r", encoding="utf-8"))
        except Exception:
            data = {}
    today_str = datetime.now().strftime("%Y-%m-%d")
    if data.get("date") != today_str:
        data = {
            "date": today_str, "updated": "", "tide": "",
            "flows": [], "warnings": [],
            "morning_head": "", "morning_bull": [], "morning_bear": [], "darkpool_note": ""
        }
    data["updated"] = datetime.now().strftime("%Y-%m-%d %H:%M")

    # 1. Market Tide
    m_cum = re.search(r"누적\s*([+\-]?\+?\$[\d.,]+[MBK]?|\$[+\-][\d.,]+[MBK]?)", text)
    m_30 = re.search(r"(?:후반)?30분\s*([+\-]?\+?\$[\d.,]+[MBK]?|\$[+\-][\d.,]+[MBK]?)", text)
    m_tr = re.search(r"추세\s*([A-Za-z_]+)", text)
    if m_cum or m_30:
        parts = []
        if m_cum:
            parts.append(f"누적 {m_cum.group(1)}")
        if m_30:
            parts.append(f"후반30분 {m_30.group(1)}")
        if m_tr:
            parts.append(f"추세 {m_tr.group(1)}")
        data["tide"] = " · ".join(parts)

    # 2. 시장 자금 순포지션
    flows = []
    for line in text.splitlines():
        m_f = re.search(r"^\s*([A-Z]{1,5})\s+[█░]+\s+([+\-]?[\d.,]+[MBK]?)\s*\[(콜\s*순매수|풋\s*순매수)\]", line.strip())
        if m_f:
            flows.append({"tk": m_f.group(1), "net": m_f.group(2), "dir": m_f.group(3)})
    if flows:
        data["flows"] = flows[:10]

    # 3. 커버드콜 / OI역행 경고 태그 (Conviction Scores)
    warns = list(data.get("warnings", []))
    seen_w = {w["tk"] for w in warns}
    for line in text.splitlines():
        m_w = re.search(r"^\s*\d+\.\s*([A-Z]{1,5})\s+.*?\[(.*?(?:커버드콜|OI역행|진짜매수).*?)\]", line.strip())
        if m_w and m_w.group(1) not in seen_w:
            warns.append({"tk": m_w.group(1), "tag": m_w.group(2)})
            seen_w.add(m_w.group(1))
    m_dir_sec = re.search(r"🆕\s*신규 포지션 방향.*?\n\s*이 데이터가 의미하는 것:\s*(.+)", text)
    if m_dir_sec:
        data["dir_note"] = m_dir_sec.group(1).strip()
    data["warnings"] = warns[:15]

    # 4. 아침 종합 브리핑 (반등 주목 / 약세 주목)
    if "아침 종합 브리핑" in text:
        if "──" in text:
            after_sep = text.split("──", 1)[1].lstrip("─\n ")
            head_block = after_sep.split("🟢", 1)[0].strip()
            data["morning_head"] = " ".join([x.strip() for x in head_block.splitlines() if x.strip()])[:260]
        bull_part = ""
        bear_part = ""
        if "🟢 반등 주목" in text:
            tmp = text.split("🟢 반등 주목", 1)[1]
            if "🔴 약세 주목" in tmp:
                bull_part, bear_part = tmp.split("🔴 약세 주목", 1)
            else:
                bull_part = tmp
        elif "🔴 약세 주목" in text:
            bear_part = text.split("🔴 약세 주목", 1)[1]

        def _extract_picks(sec_txt):
            picks = []
            for ln in sec_txt.splitlines():
                m_p = re.match(r"^\s*([A-Z]{1,5})\s*\(([^)]+)\)\s*—\s*(.+)", ln.strip())
                if m_p:
                    picks.append({"tk": m_p.group(1), "desc": m_p.group(2)})
            return picks[:6]

        mb = _extract_picks(bull_part)
        mr = _extract_picks(bear_part)
        if mb:
            data["morning_bull"] = mb
        if mr:
            data["morning_bear"] = mr

    # 5. 다크풀 하루 정리
    if "다크풀 하루 정리" in text:
        m_dp = re.search(r"정리하면\s*(.+)", text)
        if m_dp:
            data["darkpool_note"] = m_dp.group(1).strip()[:280]
        else:
            lines_dp = [ln.strip() for ln in text.splitlines() if " — " in ln]
            if lines_dp:
                data["darkpool_note"] = " | ".join([x.split(".")[0] for x in lines_dp[:4]])[:280]

    # 6. 개별 종목 브리핑 (예: TSLA  55.0/100  $390.8)
    m_tk_hdr = re.match(r"^\s*([A-Z]{1,5})\s+([\d.]+/100)\s+(\$[\d.,]+)", text.strip())
    if m_tk_hdr and "핵심 레벨" in text:
        tk_name = m_tk_hdr.group(1)
        tks_dict = data.get("tickers", {})
        m_dl = re.search(r"🎚️\s*딜러:\s*(.+)", text)
        m_oi = re.search(r"강세 베팅\s*(\d+%)\s*\|\s*약세 베팅\s*(\d+%)", text)
        m_sum = re.search(r"💡\s*한 줄 요약:\s*(.+)", text)
        tks_dict[tk_name] = {
            "score": m_tk_hdr.group(2),
            "spot": m_tk_hdr.group(3),
            "dealer": m_dl.group(1).strip() if m_dl else "",
            "oi": f"강세 {m_oi.group(1)} / 약세 {m_oi.group(2)}" if m_oi else "",
            "summary": m_sum.group(1).strip() if m_sum else "",
        }
        data["tickers"] = tks_dict

    # 7. M7 관심도
    if "M7 관심도" in text:
        m7 = []
        for ln in text.splitlines():
            m7_m = re.match(r"^\s*([A-Z]{1,5})\s+([\d.]+)", ln.strip())
            if m7_m:
                m7.append(f"{m7_m.group(1)} {m7_m.group(2)}")
        if m7:
            data["m7_note"] = " · ".join(m7[:7])

    with open(TIDE_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return data


def handle_command(token, chat_id, text):
    cmd = text.strip()
    low = cmd.lower()

    if low in ("/start", "/help", "/menu", "도움말", "메뉴"):
        # 기존 하단 고정 키보드 제거 후 깔끔한 인라인 버튼 메뉴 표시
        send_msg(token, chat_id, "📱 하단 고정 메뉴를 정리했습니다.", reply_markup={"remove_keyboard": True})
        send_msg(
            token,
            chat_id,
            "🤖 [OptionHub 메뉴] 원하는 기능을 눌러주세요!\n(종목명 예: NVDA, SOXL 입력 시 차트+GEX 즉시 전송)\n🌐 http://132.226.3.145:8501",
            reply_markup=INLINE_MENU,
        )

    elif low.startswith("/oi") or cmd == "cmd:oi":
        send_msg(token, chat_id, format_stealth_oi())

    elif low.startswith("/vol") or low.startswith("/scan") or cmd == "cmd:live":
        send_msg(token, chat_id, "⚡ 장중 실시간 Vol > OI 데이터를 조회 중입니다...")
        send_msg(token, chat_id, format_live_vol_oi())

    elif low.startswith("/em") or cmd == "cmd:em":
        send_msg(token, chat_id, format_earnings_em())

    elif low in ("/종합평", "/summary") or cmd == "cmd:summary":
        send_msg(token, chat_id, get_app_review())

    elif low in ("/문샷",) or cmd == "cmd:moon":
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

    elif low.startswith("/gex") or cmd == "cmd:gex":
        parts = cmd.split()
        tk = parts[1] if (low.startswith("/gex") and len(parts) >= 2) else None
        if tk:
            send_ticker_gex_with_chart(token, chat_id, tk)
        else:
            send_msg(token, chat_id, format_gex_summary(None))

    elif low.startswith("/chart") or cmd == "cmd:chart":
        send_msg(token, chat_id, "🖼️ 실시간 GEX·Zero Gamma 차트를 생성해 보내드리는 중입니다...")
        subprocess.Popen(["/home/ubuntu/venv/bin/python3", "/home/ubuntu/gex_chart_tg.py"])

    elif low.startswith("/geeks") or cmd == "cmd:geeks":
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

    elif low.startswith("/스캔") or cmd == "cmd:scan":
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

    elif any(k in text for k in ("시장 브리핑", "프리미엄 흐름", "시장 자금 순포지션", "Conviction Scores", "아침 종합 브리핑", "다크풀 하루 정리", "핵심 레벨", "스마트머니", "M7 관심도")):
        d = parse_and_save_tide_brief(text)
        msg = (
            f"✅ [OptionHub 반영 완료] ({d.get('updated', '')})\n"
            f"• Market Tide: {d.get('tide') or '-'}\n"
            f"• 자금 순포지션: {len(d.get('flows', []))}종목\n"
            f"• OI/커버드콜 경고: {len(d.get('warnings', []))}건\n"
            f"• 개별 종목 브리핑: {len(d.get('tickers', {}))}종목\n"
            f"🌐 http://132.226.3.145:8501"
        )
        send_msg(token, chat_id, msg)

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
    print("🤖 OptionHub Telegram Bot & Inline Menu started!")
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
                if "callback_query" in upd:
                    cb = upd["callback_query"]
                    cid = str(cb.get("message", {}).get("chat", {}).get("id", ""))
                    cb_data = cb.get("data", "")
                    answer_callback(token, cb.get("id", ""))
                    if cid == my_chat_id and cb_data:
                        handle_command(token, cid, cb_data)
                    continue
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