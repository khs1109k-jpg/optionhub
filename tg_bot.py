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
TG_ARCHIVE_PATH = os.path.expanduser("~/.optionhub_tg_archive.json")
BIG_FLOWS_PATH = os.path.expanduser("~/.optionhub_big_flows.json")
OPT_VAULT_PATH = os.path.expanduser("~/.optionhub_options_vault.json")
APP_PATH = os.path.expanduser("~/app.py")
SHEET_ID = "1_FWy_B9a6t1txau06PbeEMy9S9B1GsMgWZLGfMmMG7w"

INLINE_MENU = {
    "inline_keyboard": [
        [
            {"text": "☀️ 아침·최종 브리핑", "callback_data": "cmd:morning"},
            {"text": "📌 레벨알림", "callback_data": "cmd:levels"},
        ],
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
            {"text": "🚨 큰 옵션 체결", "callback_data": "cmd:big"},
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
        {"command": "big", "description": "🚨 큰 옵션 체결 생성·전송 (예: /big PLTR)"},
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

def send_photo_bytes(token, chat_id, img_bytes, caption=""):
    if not token or not chat_id or not img_bytes:
        return False
    try:
        import requests
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendPhoto",
            data={"chat_id": chat_id, "caption": (caption or "")[:1000]},
            files={"photo": ("bigflows.png", img_bytes, "image/png")},
            timeout=20,
        )
        return r.status_code == 200
    except Exception as _ep:
        print("send_photo_bytes err:", _ep, flush=True)
        return False

def _render_bigflows_card_png(items, tot_bull, tot_bear, tot_bias, tk_lines):
    if not items:
        return None
    try:
        import io
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.font_manager as fm
        from matplotlib.patches import FancyBboxPatch

        _font_set = False
        for _fp in ["/usr/share/fonts/truetype/nanum/NanumGothic.ttf", "/usr/share/fonts/truetype/nanum/NanumBarunGothic.ttf", "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"]:
            if os.path.exists(_fp):
                fm.fontManager.addfont(_fp)
                plt.rcParams["font.family"] = fm.FontProperties(fname=_fp).get_name()
                _font_set = True
                break
        if not _font_set:
            plt.rcParams["font.sans-serif"] = ["NanumGothic", "Noto Sans CJK KR", "Malgun Gothic", "DejaVu Sans"]
        plt.rcParams["axes.unicode_minus"] = False

        rows = sorted(items, key=lambda x: x["prem"], reverse=True)[:18]
        n_rows = len(rows)
        n_tk = min(len(tk_lines), 8)
        fig_h = max(6.5, 2.2 + n_rows * 0.42 + n_tk * 0.34)
        fig = plt.figure(figsize=(12.5, fig_h), facecolor="#0a111d")
        ax = fig.add_axes([0, 0, 1, 1], facecolor="#0a111d")
        ax.set_xlim(0, 100)
        ax.set_ylim(0, 100)
        ax.axis("off")

        cols = [(2, "종목"), (12, "EXP"), (22, "계약"), (37, "BUY/SELL"), (48, "수량"), (58, "총 PREM"), (70, "해석")]
        y_top = 96.5
        ax.text(2, y_top + 1.2, f"대형 옵션 체결 · 상위 {n_rows}건 (CBOE 실시간 집계)", color="#f8fafc", fontsize=13, fontweight="bold", va="center")
        y_hdr = y_top - 3.2
        ax.add_patch(FancyBboxPatch((1.5, y_hdr - 1.8), 97, 3.6, boxstyle="round,pad=0.2", facecolor="#101b2e", edgecolor="#1e3a5f", linewidth=0.8))
        for cx, cname in cols:
            ax.text(cx, y_hdr, cname, color="#94a3b8", fontsize=9.5, fontweight="bold", va="center")

        row_step = (y_hdr - 4.0 - (n_tk * 3.1 + 9.0)) / max(n_rows, 1)
        row_step = min(row_step, 4.1)
        y_cur = y_hdr - 3.8
        for idx, it in enumerate(rows):
            bg = "#0d1626" if idx % 2 == 0 else "#09111e"
            ax.add_patch(FancyBboxPatch((1.5, y_cur - row_step * 0.45), 97, row_step * 0.88, boxstyle="round,pad=0.1", facecolor=bg, edgecolor="#132238", linewidth=0.5))
            ax.text(2, y_cur, f"{it['tk']} ({it['kind'][:2]})", color="#e2e8f0", fontsize=9, fontweight="bold", va="center")
            ax.text(12, y_cur, it["exp"], color="#94a3b8", fontsize=8.8, va="center")
            cp_col = "#10b981" if it["cp"] == "C" else "#ef4444"
            cp_bg = "#0b2e26" if it["cp"] == "C" else "#2e1218"
            cp_nm = "CALL" if it["cp"] == "C" else "PUT"
            ax.text(22, y_cur, f" {it['strike']:g} {cp_nm} ", color=cp_col, fontsize=8.5, fontweight="bold", va="center", bbox=dict(boxstyle="round,pad=0.22", facecolor=cp_bg, edgecolor=cp_col, linewidth=0.6))
            sd_col = "#22c55e" if "BUY" in it["side"] else ("#f87171" if "SELL" in it["side"] else "#fbbf24")
            ax.text(37, y_cur, it["side"], color=sd_col, fontsize=9, fontweight="bold", va="center")
            ax.text(48, y_cur, f"{it['vol']:,}", color="#cbd5e1", fontsize=8.8, va="center")
            ax.text(58, y_cur, f"${it['prem']/1e6:.2f}M", color="#fbbf24", fontsize=9, fontweight="bold", va="center")
            if it["deep"]:
                note = "깊은 ITM · 헤지/대체 가능"
                nc = "#94a3b8"
            elif it["cp"] == "C" and "BUY" in it["side"]:
                note = f"상승 베팅 · {it['strike']:g} 위로 갈 거라 봄"
                nc = "#34d399"
            elif it["cp"] == "P" and "SELL" in it["side"]:
                note = f"하단 지지 · {it['strike']:g} 아래는 안 간다"
                nc = "#34d399"
            elif it["cp"] == "P" and "BUY" in it["side"]:
                note = f"하락 베팅·헤지 · {it['strike']:g} 아래 대비"
                nc = "#f87171"
            elif it["cp"] == "C" and "SELL" in it["side"]:
                note = f"상단 제한 · {it['strike']:g} 위는 어렵다(저항)"
                nc = "#f87171"
            else:
                note = "사고팔기 섞임 · 방향 불명"
                nc = "#94a3b8"
            ax.text(70, y_cur, note, color=nc, fontsize=8.5, va="center")
            y_cur -= row_step

        box_h = 4.5 + n_tk * 2.9
        y_box = 2.0
        ax.add_patch(FancyBboxPatch((1.5, y_box), 97, box_h, boxstyle="round,pad=0.3", facecolor="#0d1b2a", edgecolor="#1e3a5f", linewidth=1.0))
        ax.text(3, y_box + box_h - 2.2, f"종목별 해석 · 전체: 강세 ${tot_bull/1e6:.1f}M vs 약세 ${tot_bear/1e6:.1f}M → {tot_bias}", color="#38bdf8", fontsize=10, fontweight="bold", va="center")
        for ti, tline in enumerate(tk_lines[:n_tk]):
            tc = "#34d399" if "강세 우위" in tline else ("#f87171" if "약세 우위" in tline else "#cbd5e1")
            ax.text(3.2, y_box + box_h - 4.8 - ti * 2.8, tline, color=tc, fontsize=8.8, va="center")

        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=140, bbox_inches="tight", facecolor="#0a111d")
        plt.close(fig)
        return buf.getvalue()
    except Exception as _er:
        print("render_bigflows_card err:", _er, flush=True)
        return None


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

    # 7. 반도체 4종 텍스트 브리핑
    if "반도체 4종" in text or "반도체 기본군" in text:
        data["semi_note"] = text.strip()[:1200]

    # 8. M7 관심도
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
    try:
        syms_list = ["SPY","QQQ","SOXX","SOXL","SOXS","SMH","NVDA","TSLA","AAPL","MSFT","AMZN","META","GOOGL","AMD","MU","AVGO","AMAT","LRCX","KLAC","IBIT","NBIS","SNDK","VRT","LNG","BRKB","INTC"]
        found_syms = sorted(list({s for s in syms_list if re.search(rf"\b{s}\b", text.upper())}))
        arch = []
        if os.path.exists(TG_ARCHIVE_PATH):
            with open(TG_ARCHIVE_PATH, "r", encoding="utf-8") as fa:
                arch = json.load(fa)
        title_line = text.strip().splitlines()[0][:60] if text.strip() else "Telegram Briefing"
        arch.insert(0, {"date": data["updated_at"], "title": title_line, "symbols": ", ".join(found_syms), "content": text.strip()[:2000]})
        with open(TG_ARCHIVE_PATH, "w", encoding="utf-8") as fa:
            json.dump(arch[:200], fa, ensure_ascii=False, indent=2)
    except Exception:
        pass
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

    elif low.startswith("/fg"):
        parts = cmd.split()
        if len(parts) >= 2 and parts[1].replace(".", "", 1).isdigit():
            val = int(round(float(parts[1])))
            val = max(0, min(100, val))
            d_s = datetime.now().strftime("%m-%d")
            try:
                json.dump({"val": val, "date": d_s, "mode": "수동"}, open(FG_PATH, "w", encoding="utf-8"), ensure_ascii=False)
            except Exception:
                pass
            send_msg(token, chat_id, f"✅ CNN F&G 수동 갱신 완료: {val} ({fg_label_kr(val)}, {d_s})")
        else:
            v, lbl, dt_s, md_s = get_cnn_fg()
            send_msg(token, chat_id, f"현재 CNN F&G: {v} ({lbl}) ({md_s} {dt_s})\n갱신하려면: /fg 31")

    elif low in ("/아침", "/브리핑", "/morning") or cmd == "cmd:morning":
        send_msg(token, chat_id, "☀️ 대장 아침 브리핑 & 최종분석을 생성 중입니다...")
        send_msg(token, chat_id, build_morning_briefing())

    elif low in ("/레벨알림", "/levels") or cmd == "cmd:levels":
        send_msg(token, chat_id, build_level_alert())

    elif low in ("/장중변화", "/옵션변화", "/변화") or cmd == "cmd:intraday":
        send_msg(token, chat_id, "⏱ 장중 옵션 변화 (OI 기록 종목 · CBOE 지연) 스캔 중...")
        send_msg(token, chat_id, build_intraday_option_changes())

    elif low in ("/추세전환", "/신호체크", "/trend") or cmd == "cmd:trend":
        send_msg(token, chat_id, "🚦 추세전환 7대 신호 체크 중...")
        send_msg(token, chat_id, build_trend_reversal_7())

    elif low in ("/대량틱", "/틱", "/ticks") or cmd == "cmd:ticks":
        send_msg(token, chat_id, "🐋 무무 $100K+ 대량 틱·호가벽 불균형 스캔 중...")
        send_msg(token, chat_id, build_moomoo_big_ticks_alert(manual=True))

    elif low in ("/강한콜풋", "/풋콜스캔", "/스캔", "/abscan") or cmd == "cmd:abscan":
        send_msg(token, chat_id, "🚦 강한 풋·콜 스캔 (A·B 등급, 만기 14일 내) 실행 중...")
        _ab_txt, _ab_png = build_strong_cp_scan()
        if _ab_png:
            send_photo_bytes(token, chat_id, _ab_png, _ab_txt)
        else:
            send_msg(token, chat_id, _ab_txt)

    elif low in ("/콜풋강세", "/콜풋", "/무무수급", "/cp") or cmd == "cmd:cpdom":
        send_msg(token, chat_id, "📡 무무 실시간 콜/풋 강세 종목 스캔 중...")
        send_msg(token, chat_id, build_moomoo_cp_dominance())

    elif low in ("/대형체결", "/bigflows", "/체결요약") or cmd == "cmd:bigflows":
        send_msg(token, chat_id, "🧾 대형 옵션 체결 · 신규/증가 스캔 중...")
        _bf_txt, _bf_png = build_big_option_flows_summary()
        if _bf_png:
            send_photo_bytes(token, chat_id, _bf_png, "🧾 대형 옵션 체결 상위 표 & 종목별 해석")
        send_msg(token, chat_id, _bf_txt)

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

    elif low.startswith("/big") or cmd == "cmd:big":
        parts = cmd.split()
        tk_flt = parts[1].strip().upper() if (low.startswith("/big") and len(parts) >= 2) else ""
        try:
            sh_all = fetch_sheet_rows("전체") + fetch_sheet_rows("ES")
        except Exception:
            sh_all = []
        items_out = []
        seen_k = set()
        # 1) Google Sheets flows ($500K+)
        for sr in reversed(sh_all):
            tk = str(sr.get("Ticker (티커)", "")).strip().upper()
            if not tk or (tk_flt and tk != tk_flt):
                continue
            p_raw = str(sr.get("Premium (프리미엄)", "")).strip()
            p_usd = parse_prem_usd(p_raw)
            if p_usd < 500_000:
                continue
            k_s = str(sr.get("Strike Price (행사가)", "")).replace("$", "").replace(",", "").strip().rstrip(".")
            cp_s = str(sr.get("Option Type (구분)", "Call")).strip()
            cp_ch = "C" if "C" in cp_s.upper() else "P"
            exp_s = str(sr.get("Expiration Date (만기일)", "")).strip()
            exp_short = exp_s[5:10] if len(exp_s) >= 10 else exp_s
            ch_s = str(sr.get("Characteristics (주문유형/특징)", "")).strip()
            side_s = "BUY" if ("BUY" in ch_s.upper() or "ASK" in ch_s.upper() or "A" == ch_s.upper()[:1]) else ("SELL" if ("SELL" in ch_s.upper() or "BID" in ch_s.upper()) else "MID")
            is_bull = (cp_ch == "C" and side_s == "BUY") or (cp_ch == "P" and side_s == "SELL")
            is_bear = (cp_ch == "C" and side_s == "SELL") or (cp_ch == "P" and side_s == "BUY")
            emo = "🟢" if is_bull else ("🔴" if is_bear else "⚪")
            prem_lbl = f"${p_usd/1e6:.2f}M" if p_usd >= 1e6 else f"${p_usd/1e3:.1f}K"
            uk = f"{tk}|{k_s}{cp_ch}|{exp_short}|{side_s}|{prem_lbl}"
            if uk in seen_k:
                continue
            seen_k.add(uk)
            tag_lbl = "SWEEP" if "SWEEP" in ch_s.upper() else ("BLOCK" if "BLOCK" in ch_s.upper() else (ch_s[:24] or "LARGE FLOW"))
            items_out.append((p_usd, f"{emo} {tk} {k_s}{cp_ch} {exp_short} {side_s} {prem_lbl} · {tag_lbl}"))
        # 2) Also include saved BIG_FLOWS_PATH records if sheet has fewer than 12
        if os.path.exists(BIG_FLOWS_PATH):
            try:
                b_arr = json.load(open(BIG_FLOWS_PATH, "r", encoding="utf-8"))
                for blk in b_arr:
                    for r in blk.get("records", []):
                        tk = str(r.get("tk", "")).upper()
                        if tk_flt and tk != tk_flt:
                            continue
                        p_usd = float(r.get("prem_m", 0)) * 1e6
                        cp_ch = "C" if r.get("cp") == "Call" else "P"
                        uk = f"{tk}|{r.get('strike')}{cp_ch}|{r.get('exp')}|{r.get('side')}|{r.get('prem_str')}"
                        if uk in seen_k:
                            continue
                        seen_k.add(uk)
                        items_out.append((p_usd, f"{r.get('emoji','⚪')} {tk} {r.get('strike'):g}{cp_ch} {r.get('exp')} {r.get('side')} {r.get('prem_str')} · {r.get('qty',0):,}계약 · {r.get('tag','')}"))
            except Exception:
                pass
        items_out.sort(key=lambda x: x[0], reverse=True)
        top_items = [x[1] for x in items_out[:12]]
        if top_items:
            hdr = f"🚨 큰 옵션 체결 {len(top_items)}건" + (f" ({tk_flt})" if tk_flt else "")
            ftr = "(🟢 = 콜 매수·풋 매도 강세 · 🔴 = 약세 · 🟡 = 헤지 후보)"
            send_msg(token, chat_id, hdr + "\n" + "\n".join(top_items) + "\n" + ftr)
        else:
            send_msg(token, chat_id, f"🚨 {tk_flt or '전체'} 기준 $500K 이상 큰 옵션 체결이 아직 없습니다.")

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

    elif "큰 옵션 체결" in text or ("PREMIUM SALE" in text and "계약" in text) or ("DIRECTIONAL FLOW" in text and "계약" in text):
        pat = re.compile(
            r"([🟢🔴🟡])\s*([A-Z]{1,6})\s+(\d+(?:\.\d+)?)([CP])\s+(\d{2}-\d{2}(?:-\d{2})?)\s+(BUY|SELL)\s+\$([\d\.]+)([MK])\s*[·\-]\s*([\d,]+)계약\s*[·\-]\s*(.+)"
        )
        flip_m = re.search(r"플립\(([\d\.]+)\)", text)
        flip_v = float(flip_m.group(1)) if flip_m else None
        recs = []
        for ln in text.splitlines():
            s_ln = ln.strip()
            m_b = pat.search(s_ln)
            if m_b:
                emo, tk_b, k_s, cp_s, exp_s, side_s, pr_num, pr_unit, qty_s, tag_s = m_b.groups()
                prem_m = float(pr_num) if pr_unit == "M" else round(float(pr_num) / 1000.0, 3)
                recs.append({
                    "emoji": emo,
                    "tk": tk_b.upper(),
                    "strike": float(k_s),
                    "cp": "Call" if cp_s == "C" else "Put",
                    "exp": exp_s,
                    "side": side_s,
                    "prem_m": prem_m,
                    "prem_str": f"${pr_num}{pr_unit}",
                    "qty": int(qty_s.replace(",", "")),
                    "tag": tag_s.strip(),
                    "notes": [],
                })
            elif recs and (s_ln.startswith("📍") or s_ln.startswith("🛡")):
                recs[-1]["notes"].append(s_ln)
        if recs:
            from datetime import datetime
            arr_b = []
            if os.path.exists(BIG_FLOWS_PATH):
                try:
                    arr_b = json.load(open(BIG_FLOWS_PATH, "r", encoding="utf-8"))
                except Exception:
                    arr_b = []
            entry_b = {
                "ts": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "tk": recs[0]["tk"],
                "flip": flip_v,
                "items": recs,
            }
            arr_b.insert(0, entry_b)
            with open(BIG_FLOWS_PATH, "w", encoding="utf-8") as fb:
                json.dump(arr_b[:50], fb, ensure_ascii=False, indent=2)
            bull_m = round(sum(x["prem_m"] for x in recs if x["emoji"] == "🟢"), 2)
            bear_m = round(sum(x["prem_m"] for x in recs if x["emoji"] == "🔴"), 2)
            hedg_m = round(sum(x["prem_m"] for x in recs if x["emoji"] == "🟡"), 2)
            send_msg(
                token,
                chat_id,
                f"✅ [큰 옵션 체결 OptionHub 자동 저장 완료]\n"
                f"• 종목: {entry_b['tk']} ({len(recs)}건)" + (f" | 플립: ${flip_v}" if flip_v else "") + "\n"
                f"• 🟢강세: ${bull_m:,.2f}M | 🔴약세: ${bear_m:,.2f}M | 🟡헤지: ${hedg_m:,.2f}M\n"
                f"🌐 http://132.226.3.145:8501 (🎯 행사가별·동반 체결 탭)"
            )

    elif any(k in text for k in ("시장 브리핑", "프리미엄 흐름", "시장 자금 순포지션", "Conviction Scores", "아침 종합 브리핑", "다크풀 하루 정리", "핵심 레벨", "스마트머니", "M7 관심도", "반도체 4종", "반도체 기본군")):
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

    elif low.startswith("/옵션저장") or low.startswith("/자료저장"):
        from datetime import datetime
        body_v = text.split(None, 1)[1].strip() if len(text.split(None, 1)) > 1 else ""
        if not body_v:
            send_msg(token, chat_id, "사용법: /옵션저장 [저장할 옵션 리포트 또는 메모 내용]")
            return
        arr_v = []
        if os.path.exists(OPT_VAULT_PATH):
            try:
                arr_v = json.load(open(OPT_VAULT_PATH, "r", encoding="utf-8"))
            except Exception:
                arr_v = []
        tks_v = re.findall(r"\b[A-Z]{2,5}\b", body_v.upper())
        tk_v = ", ".join(list(dict.fromkeys(tks_v))[:3]) if tks_v else "공통"
        title_v = body_v.splitlines()[0][:50]
        arr_v.insert(0, {
            "id": f"op_{int(time.time()*1000)}",
            "날짜": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "카테고리": "스윕·블록",
            "종목": tk_v,
            "제목": title_v,
            "내용": body_v,
            "링크": "",
            "파일경로": "",
            "파일명": "",
        })
        with open(OPT_VAULT_PATH, "w", encoding="utf-8") as fv:
            json.dump(arr_v, fv, ensure_ascii=False, indent=2)
        send_msg(token, chat_id, f"✅ [📂 옵션자료실 자동 저장 완료]\n• 종목: {tk_v}\n• 제목: {title_v}\n🌐 http://132.226.3.145:8501")

    elif re.fullmatch(r"[A-Za-z]{1,5}", cmd):
        send_ticker_gex_with_chart(token, chat_id, cmd)


SENT_REVIEWS_PATH = os.path.expanduser("~/.optionhub_sent_reviews.json")


def format_emoji_review_tg(raw_txt):
    s = str(raw_txt or "").strip()
    if not s:
        return s
    s = re.sub(r"\s*(\[[^\]]+\])\s*", r"📣 \1\n\n", s, count=1)
    reps = [
        (r"\s*1\)\s*시장\s*총평\s*:?", "\n\n📌 1️⃣ 시장 총평\n• "),
        (r"\s*2\)\s*기관\s*수급\s*핵심\s*:?", "\n\n🏦 2️⃣ 기관 수급 핵심\n• "),
        (r"\s*3\)\s*섹터별\s*전략\s*:?", "\n\n🎯 3️⃣ 섹터별 전략\n• "),
        (r"\s*4\)\s*주목\s*종목\s*:?", "\n\n👀 4️⃣ 주목 종목\n• "),
        (r"\s*5\)\s*리스크\s*요인\s*:?", "\n\n⚠️ 5️⃣ 리스크 요인\n• "),
    ]
    for pat, rep in reps:
        s = re.sub(pat, rep, s)
    s = re.sub(r"\n{3,}", "\n\n", s).strip()
    return s



SENT_GEEKS_PATH = os.path.expanduser("~/.optionhub_sent_geeks.json")


def send_photo_url(token, chat_id, photo_url, caption=""):
    try:
        url = f"https://api.telegram.org/bot{token}/sendPhoto"
        payload = json.dumps({
            "chat_id": chat_id,
            "photo": photo_url,
            "caption": caption[:1000],
        }).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=15).read()
        return True
    except Exception:
        return False


def check_sheet_geeks(token, chat_id):
    """구글 시트(AI노트_뉴스시황)에 새 Geeks/Menthor/SpotGamma 리포트가 저장되면 차트 이미지+한글 요약 자동 텔레그램 전송"""
    try:
        first_run = not os.path.exists(SENT_GEEKS_PATH)
        sent = set()
        if not first_run:
            try:
                sent = set(json.load(open(SENT_GEEKS_PATH, "r", encoding="utf-8")))
            except Exception:
                sent = set()
        rows = fetch_sheet_rows("AI노트_뉴스시황")
        sub = [r for r in rows if any(k in str(r.get("섹션", "")) for k in ("Geeks", "맨도큐", "Menthor", "SpotGamma"))]
        if not sub:
            return
        today_kst = (datetime.utcnow() + timedelta(hours=9)).strftime("%Y-%m-%d")
        for r in sub:
            dt_s = str(r.get("날짜", "")).strip()
            tk_s = str(r.get("종목", "")).strip()
            sec_s = str(r.get("섹션", "")).strip()
            ko_s = str(r.get("한글 번역/해석", "")).strip()
            img_u = str(r.get("이미지URL", r.get("이미지", ""))).strip()
            uid = f"{dt_s}|{sec_s}|{tk_s}|{ko_s[:30]}"
            if uid in sent:
                continue
            sent.add(uid)
            # 첫 실행 시에는 오늘 날짜 리포트만 즉시 발송하고 과거 이력은 스킵
            if first_run and not dt_s.startswith(today_kst):
                continue
            cap = f"📐 [{sec_s}] {tk_s} ({dt_s})\n\n{ko_s}"
            if img_u.startswith("http"):
                ok_p = send_photo_url(token, chat_id, img_u, cap)
                if not ok_p:
                    send_msg(token, chat_id, cap + f"\n🖼 {img_u}")
            else:
                send_msg(token, chat_id, cap)
        json.dump(list(sent)[-500:], open(SENT_GEEKS_PATH, "w", encoding="utf-8"), ensure_ascii=False)
    except Exception:
        pass


def check_sheet_review(token, chat_id):
    try:
        sent_list = []
        if os.path.exists(SENT_REVIEWS_PATH):
            try:
                sent_list = json.load(open(SENT_REVIEWS_PATH, "r", encoding="utf-8"))
            except Exception:
                sent_list = []
        last_seen = open(STATE_PATH, "r", encoding="utf-8").read().strip() if os.path.exists(STATE_PATH) else ""
        rows = fetch_sheet_rows("AI노트_뉴스시황")
        reviews = [r for r in rows if "종합평" in str(r)]
        if reviews:
            latest = reviews[-1]
            key = f"{latest.get('날짜', '')}_{latest.get('한글 번역/해석', '')[:40]}"
            if key and key != last_seen and key not in sent_list:
                msg = (
                    f"📝 [OptionHub 자동 종합평] {latest.get('날짜', '')}\n\n"
                    f"{format_emoji_review_tg(latest.get('한글 번역/해석', ''))}\n\n"
                    f"🌐 http://132.226.3.145:8501"
                )
                send_msg(token, chat_id, msg)
                with open(STATE_PATH, "w", encoding="utf-8") as f:
                    f.write(key)
                sent_list.append(key)
                with open(SENT_REVIEWS_PATH, "w", encoding="utf-8") as fs:
                    json.dump(sent_list[-100:], fs, ensure_ascii=False, indent=2)
        try:
            ins_p = os.path.expanduser("~/.optionhub_insider_mails.json")
            ins_arr = json.load(open(ins_p, "r", encoding="utf-8")) if os.path.exists(ins_p) else []
            seen_t = {m.get("제목", "") for m in ins_arr}
            added_i = 0
            for r in reversed(rows[-20:]):
                bu = str(r).upper()
                stag = None
                if any(k in bu for k in ("INSIDER", "EVENING EDGE", "인사이더")): stag = "InsiderFinance"
                elif any(k in bu for k in ("GEEK", "GREEKS", "긱스", "그릭스")): stag = "Geeks of Finance"
                elif any(k in bu for k in ("MENTHOR", "멘토", "멘도")): stag = "Menthor Q"
                elif any(k in bu for k in ("SPOTGAMMA", "스팟감마")): stag = "SpotGamma"
                if not stag:
                    continue
                ttl = str(r.get("제목", r.get("섹션", f"{stag} 리포트"))).strip()
                if not ttl or ttl in seen_t:
                    continue
                body = str(r.get("한글 번역/해석", r.get("원문", r.get("내용", "")))).strip()
                dt_s = str(r.get("날짜", ""))[:16]
                ins_arr.insert(0, {
                    "id": f"bg_{stag[:4]}_{abs(hash(ttl + dt_s))}",
                    "날짜": dt_s, "출처": stag, "제목": ttl,
                    "원문": body, "요약": body, "종목": "공통",
                })
                seen_t.add(ttl)
                added_i += 1
            if added_i > 0:
                json.dump(ins_arr[:100], open(ins_p, "w", encoding="utf-8"), ensure_ascii=False)
        except Exception:
            pass
    except Exception:
        pass



SEMI_IMG_PATH = os.path.expanduser("~/.optionhub_semi_latest.jpg")
PHOTO_DIR = os.path.expanduser("~/.optionhub_tg_photos")

def save_forwarded_photo(token, chat_id, msg):
    from datetime import datetime
    try:
        photos = msg.get("photo") or []
        doc = msg.get("document") or {}
        file_id = None
        if photos:
            file_id = photos[-1].get("file_id")
        elif doc and str(doc.get("mime_type", "")).startswith("image/"):
            file_id = doc.get("file_id")
        if not file_id:
            return False
        info = json.loads(urllib.request.urlopen(f"https://api.telegram.org/bot{token}/getFile?file_id={file_id}", timeout=15).read().decode("utf-8"))
        fp = info.get("result", {}).get("file_path")
        if not fp:
            return False
        img_bytes = urllib.request.urlopen(f"https://api.telegram.org/file/bot{token}/{fp}", timeout=20).read()
        os.makedirs(PHOTO_DIR, exist_ok=True)
        fname = datetime.now().strftime("tg_%Y%m%d_%H%M%S_%f.jpg")
        with open(os.path.join(PHOTO_DIR, fname), "wb") as f:
            f.write(img_bytes)
        with open(SEMI_IMG_PATH, "wb") as f:
            f.write(img_bytes)
        # Keep only latest 5 photos
        files = sorted([x for x in os.listdir(PHOTO_DIR) if x.endswith(".jpg")])
        for old_f in files[:-5]:
            try:
                os.remove(os.path.join(PHOTO_DIR, old_f))
            except Exception:
                pass
        cnt = min(len(files), 5)
        send_msg(token, chat_id, f"✅ [OptionHub 이미지 반영 완료] (최근 {cnt}장 보관 중)\n🌐 http://132.226.3.145:8501")
        return True
    except Exception as e:
        send_msg(token, chat_id, f"이미지 저장 오류: {e}")
        return False


BIG_SEEN_PATH = os.path.expanduser("~/.optionhub_big_seen.json")
AUTO_OI_DATE_PATH = os.path.expanduser("~/.optionhub_auto_oi_date.txt")


def auto_collect_big_flows(token, chat_id):
    """구글 시트(전체/ES)에서 $1M+ 신규 대형 체결 자동 수집 → BIG_FLOWS_PATH 저장 + 텔레그램 푸시"""
    try:
        sh_all = fetch_sheet_rows("전체") + fetch_sheet_rows("ES")
    except Exception:
        return
    if not sh_all:
        return

    first_run = not os.path.exists(BIG_SEEN_PATH)
    seen = set()
    if not first_run:
        try:
            seen = set(json.load(open(BIG_SEEN_PATH, "r", encoding="utf-8")))
        except Exception:
            seen = set()

    new_lines = []
    new_recs_by_tk = {}
    for sr in sh_all:
        tk = str(sr.get("Ticker (티커)", "")).strip().upper()
        if not tk:
            continue
        p_raw = str(sr.get("Premium (프리미엄)", "")).strip()
        p_usd = parse_prem_usd(p_raw)
        if p_usd < 1_000_000:
            continue
        k_s = str(sr.get("Strike Price (행사가)", "")).replace("$", "").replace(",", "").strip().rstrip(".")
        cp_s = str(sr.get("Option Type (구분)", "Call")).strip()
        cp_ch = "C" if "C" in cp_s.upper() else "P"
        exp_s = str(sr.get("Expiration Date (만기일)", "")).strip()
        exp_short = exp_s[5:10] if len(exp_s) >= 10 else exp_s
        tm_s = str(sr.get("Time (시각)", "")).strip()
        ch_s = str(sr.get("Characteristics (주문유형/특징)", "")).strip()
        uid = f"{tk}|{k_s}{cp_ch}|{exp_s}|{tm_s}|{p_raw}"
        if uid in seen:
            continue
        seen.add(uid)
        if first_run:
            continue
        side_s = "BUY" if ("BUY" in ch_s.upper() or "ASK" in ch_s.upper()) else ("SELL" if ("SELL" in ch_s.upper() or "BID" in ch_s.upper()) else "MID")
        is_bull = (cp_ch == "C" and side_s == "BUY") or (cp_ch == "P" and side_s == "SELL")
        is_bear = (cp_ch == "C" and side_s == "SELL") or (cp_ch == "P" and side_s == "BUY")
        emo = "🟢" if is_bull else ("🔴" if is_bear else "⚪")
        prem_lbl = f"${p_usd/1e6:.2f}M"
        tag_lbl = "SWEEP" if "SWEEP" in ch_s.upper() else ("BLOCK" if "BLOCK" in ch_s.upper() else (ch_s[:24] or "LARGE FLOW"))
        new_lines.append(f"{emo} {tk} {k_s}{cp_ch} {exp_short} {side_s} {prem_lbl} · {tag_lbl}")
        try:
            k_num = float(k_s)
        except Exception:
            k_num = 0.0
        new_recs_by_tk.setdefault(tk, []).append({
            "emoji": emo, "tk": tk, "strike": k_num,
            "cp": "Call" if cp_ch == "C" else "Put",
            "exp": exp_short, "side": side_s,
            "prem_m": round(p_usd / 1e6, 2), "prem_str": prem_lbl,
            "qty": 0, "tag": tag_lbl, "notes": [],
        })

    try:
        json.dump(list(seen)[-1500:], open(BIG_SEEN_PATH, "w", encoding="utf-8"))
    except Exception:
        pass

    if new_lines:
        try:
            arr_b = json.load(open(BIG_FLOWS_PATH, "r", encoding="utf-8")) if os.path.exists(BIG_FLOWS_PATH) else []
        except Exception:
            arr_b = []
        now_s = datetime.now().strftime("%Y-%m-%d %H:%M")
        for btk, brecs in new_recs_by_tk.items():
            arr_b.insert(0, {"tk": btk, "ts": now_s, "flip": None, "records": brecs})
        try:
            json.dump(arr_b[:50], open(BIG_FLOWS_PATH, "w", encoding="utf-8"), ensure_ascii=False)
        except Exception:
            pass
        msg = f"🚨 큰 옵션 체결 {len(new_lines)}건 (자동 포착)\n" + "\n".join(new_lines[:12]) + "\n(🟢 = 강세 · 🔴 = 약세 · ⚪ = 중립)"
        send_msg(token, chat_id, msg)


def auto_collect_daily_oi(token, chat_id):
    """매일 오전 07:30 KST 이후 주요 종목 OI·GEX 스냅샷 자동 수집 및 저장"""
    from datetime import datetime as _dt_oi
    import math as _m_oi
    now_dt = _dt_oi.now()
    today_s = now_dt.strftime("%Y-%m-%d")
    if now_dt.hour < 21 or (now_dt.hour == 21 and now_dt.minute < 30):
        return
    if os.path.exists(AUTO_OI_DATE_PATH):
        try:
            if open(AUTO_OI_DATE_PATH, "r").read().strip() == today_s:
                return
        except Exception:
            pass
    try:
        import yfinance as yf
    except Exception:
        return
    tks = ["SPY", "QQQ", "NVDA", "TSLA", "PLTR", "SMH", "SOXL", "MU", "AMD", "AAPL"]
    try:
        hist = json.load(open(OI_PATH, "r", encoding="utf-8")) if os.path.exists(OI_PATH) else {}
    except Exception:
        hist = {}

    def _bs_dg(S, K, T, r, iv, is_c):
        d1 = (_m_oi.log(S / K) + (r + 0.5 * iv * iv) * T) / (iv * _m_oi.sqrt(T))
        nd1 = _m_oi.exp(-0.5 * d1 * d1) / _m_oi.sqrt(2 * _m_oi.pi)
        cdf = 0.5 * (1 + _m_oi.erf(d1 / _m_oi.sqrt(2)))
        return (cdf if is_c else cdf - 1), nd1 / (S * iv * _m_oi.sqrt(T))

    done_tks = []
    for tk in tks:
        try:
            rows = []
            spot = 0.0
            try:
                _cb_sym = {"SPX": "_SPX", "NDX": "_NDX", "VIX": "_VIX", "RUT": "_RUT"}.get(tk, tk)
                _cb_url = f"https://cdn.cboe.com/api/global/delayed_quotes/options/{_cb_sym}.json"
                _cb_raw = json.loads(urllib.request.urlopen(urllib.request.Request(_cb_url, headers={"User-Agent": "Mozilla/5.0"}), timeout=8).read().decode("utf-8"))
                _cb_d = _cb_raw.get("data") or {}
                spot = float(_cb_d.get("current_price") or _cb_d.get("close") or 0.0)
                _cb_opts = _cb_d.get("options") or []
                _cb_exps = sorted({f"20{m.group(1)[:2]}-{m.group(1)[2:4]}-{m.group(1)[4:6]}" for o in _cb_opts for m in [re.match(r"^[A-Z]+(\d{6})([CP])(\d{8})$", str(o.get("option") or ""))] if m and f"20{m.group(1)[:2]}-{m.group(1)[2:4]}-{m.group(1)[4:6]}" >= today_s})
                _wk_cb = [e for e in _cb_exps if (_dt_oi.strptime(e, "%Y-%m-%d").date() - now_dt.date()).days <= 7]
                _tgt_cb = set((_wk_cb if len(_wk_cb) >= 3 else _cb_exps[:3])[:7])
                for o in _cb_opts:
                    _m = re.match(r"^[A-Z]+(\d{6})([CP])(\d{8})$", str(o.get("option") or ""))
                    if not _m: continue
                    _yymmdd, _cpc, _kraw = _m.groups()
                    _exp_s = f"20{_yymmdd[:2]}-{_yymmdd[2:4]}-{_yymmdd[4:6]}"
                    if _exp_s not in _tgt_cb: continue
                    oi = int(o.get("open_interest") or 0)
                    vol = int(o.get("volume") or 0)
                    if oi <= 0 and vol <= 0: continue
                    K = int(_kraw) / 1000.0
                    is_c = (_cpc == "C")
                    iv = float(o.get("iv") or 0.30)
                    if iv <= 0.01: iv = 0.30
                    T = max((_dt_oi.strptime(_exp_s, "%Y-%m-%d") - now_dt).days / 365.0, 1.0 / 365.0)
                    s_ref = spot if spot > 0 else K
                    d, g = _bs_dg(s_ref, K, T, 0.045, iv, is_c)
                    rows.append({
                        "만기": _exp_s, "구분": "Call" if is_c else "Put", "행사가": K,
                        "OI": oi, "거래량": vol, "IV(%)": round(iv * 100, 1),
                        "Delta": round(d, 3), "Gamma": round(g, 4),
                        "GEX($M)": round((1 if is_c else -1) * g * oi * 100 * (s_ref ** 2) * 0.01 / 1e6, 3),
                        "DEX($M)": round(d * oi * 100 * s_ref / 1e6, 3),
                    })
            except Exception:
                rows = []
            if sum(x["OI"] for x in rows if x["구분"] == "Call") < 500 or sum(x["OI"] for x in rows if x["구분"] == "Put") < 500:
                rows = []
                t = yf.Ticker(tk)
                exps = list(t.options or [])
                week_exps = [e for e in exps if (_dt_oi.strptime(e, "%Y-%m-%d").date() - now_dt.date()).days <= 7]
                target_exps = (week_exps if len(week_exps) >= 3 else exps[:3])[:7]
                spot = float(t.fast_info.get("lastPrice", 0) or t.history(period="1d")["Close"].iloc[-1])
                rows = []
                for exp in target_exps:
                    T = max((_dt_oi.strptime(exp, "%Y-%m-%d") - now_dt).days / 365.0, 1.0 / 365.0)
                    ch = t.option_chain(exp)
                    for is_c, df in [(True, ch.calls), (False, ch.puts)]:
                        for _, r in df.iterrows():
                            oi = 0 if str(r.get("openInterest")) == "nan" else int(r.get("openInterest") or 0)
                            vol = 0 if str(r.get("volume")) == "nan" else int(r.get("volume") or 0)
                            if oi > 0 or vol > 0:
                                K = float(r["strike"]); iv = max(float(r.get("impliedVolatility") or 0.3), 0.05)
                                d, g = _bs_dg(spot, K, T, 0.045, iv, is_c)
                                rows.append({
                                    "만기": exp, "구분": "Call" if is_c else "Put", "행사가": K,
                                    "OI": oi, "거래량": vol, "IV(%)": round(iv * 100, 1),
                                    "Delta": round(d, 3), "Gamma": round(g, 4),
                                    "GEX($M)": round((1 if is_c else -1) * g * oi * 100 * (spot ** 2) * 0.01 / 1e6, 3),
                                    "DEX($M)": round(d * oi * 100 * spot / 1e6, 3),
                                })
            if rows:
                coi = sum(x["OI"] for x in rows if x["구분"] == "Call")
                poi = sum(x["OI"] for x in rows if x["구분"] == "Put")
                if coi < 500 or poi < 500:
                    continue
                hist.setdefault(tk, []).append({
                    "수집시각": now_dt.strftime("%Y-%m-%d %H:%M"),
                    "Spot": round(spot, 2), "Call_OI": coi, "Put_OI": poi,
                    "Put_Call_OI_Ratio": round(poi / coi, 2) if coi else 0,
                    "Net_GEX_M": round(sum(x["GEX($M)"] for x in rows), 2),
                    "Net_DEX_M": round(sum(x["DEX($M)"] for x in rows), 2),
                    "상세": rows,
                })
                done_tks.append(tk)
        except Exception:
            pass
    if done_tks:
        try:
            json.dump(hist, open(OI_PATH, "w", encoding="utf-8"), ensure_ascii=False)
            open(AUTO_OI_DATE_PATH, "w").write(today_s)
            send_msg(token, chat_id, f"✅ [아침 자동 OI·GEX 수집 완료] ({len(done_tks)}종목)\n{', '.join(done_tks)}")
        except Exception:
            pass



WHALE_VOL_PATH = os.path.expanduser("~/.optionhub_whale_vol.json")


def auto_scan_option_whales(token, chat_id):
    """무무 OpenD(1순위) + Yahoo Finance(폴백) 기반 실시간 $1M+ / $4M+ 옵션 고래 체결 스캐너"""
    tks = ["SPY", "QQQ", "IWM", "NVDA", "TSLA", "SOXL", "SMH", "MU", "AMD", "PLTR"]
    first_run = not os.path.exists(WHALE_VOL_PATH)
    prev_vols = {}
    if not first_run:
        try:
            prev_vols = json.load(open(WHALE_VOL_PATH, "r", encoding="utf-8"))
        except Exception:
            prev_vols = {}

    alerts = []
    new_recs_by_tk = {}
    mm_ok = False

    # 1순위: 무무 OpenD 실시간 옵션 체인 + 스냅샷 (Ask/Bid 체결 방향 판별 포함)
    qctx = None
    try:
        from moomoo import OpenQuoteContext, RET_OK
        qctx = OpenQuoteContext(host="127.0.0.1", port=11111)
        now_d = datetime.now()
        end_d = (now_d + timedelta(days=10)).strftime("%Y-%m-%d")
        start_d = now_d.strftime("%Y-%m-%d")
        opt_codes = []
        for tk in tks:
            ret_c, df_c = qctx.get_option_chain(code=f"US.{tk}", start=start_d, end=end_d)
            if ret_c == RET_OK and df_c is not None and not df_c.empty:
                opt_codes.extend(df_c["code"].tolist()[:40])
        for i in range(0, len(opt_codes), 100):
            batch = opt_codes[i:i+100]
            ret_s, df_s = qctx.get_market_snapshot(batch)
            if ret_s != RET_OK or df_s is None or df_s.empty:
                continue
            mm_ok = True
            for _, r in df_s.iterrows():
                code = str(r.get("code", ""))
                vol = int(r.get("volume", 0) or 0)
                px = float(r.get("last_price", 0) or 0)
                ask_p = float(r.get("ask_price", 0) or 0)
                bid_p = float(r.get("bid_price", 0) or 0)
                stk = float(r.get("option_strike_price", 0) or 0)
                cp_s = "C" if "CALL" in str(r.get("option_type", "")).upper() else "P"
                exp_s = str(r.get("strike_time", ""))[5:10]
                if vol <= 0 or px <= 0:
                    continue
                old_v = int(prev_vols.get(code, vol if first_run else 0))
                prev_vols[code] = vol
                if first_run:
                    continue
                d_vol = vol - old_v
                if d_vol <= 0:
                    continue
                d_usd = d_vol * px * 100.0
                if d_usd < 1_000_000:
                    continue
                side_s = "BUY" if (ask_p > 0 and px >= ask_p * 0.99) else ("SELL" if (bid_p > 0 and px <= bid_p * 1.01) else "FLOW")
                is_bull = (cp_s == "C" and side_s == "BUY") or (cp_s == "P" and side_s == "SELL")
                is_bear = (cp_s == "C" and side_s == "SELL") or (cp_s == "P" and side_s == "BUY")
                emo = "🐋🟢" if (is_bull and d_usd >= 4_000_000) else ("🐋🔴" if (is_bear and d_usd >= 4_000_000) else ("🟢" if is_bull else ("🔴" if is_bear else "⚪")))
                tk_name = code.split(".")[1][:4] if "." in code else code
                for cand in tks:
                    if code.startswith(f"US.{cand}"):
                        tk_name = cand; break
                prem_lbl = f"${d_usd/1e6:.2f}M"
                tag_lbl = "MEGA WHALE 4M+" if d_usd >= 4_000_000 else "MOOMOO LIVE"
                alerts.append(f"{emo} {tk_name} {stk:g}{cp_s} {exp_s} {side_s} {prem_lbl} ({d_vol:,}계약) · {tag_lbl}")
                new_recs_by_tk.setdefault(tk_name, []).append({
                    "emoji": "🟢" if is_bull else ("🔴" if is_bear else "⚪"),
                    "tk": tk_name, "strike": stk, "cp": "Call" if cp_s == "C" else "Put",
                    "exp": exp_s, "side": side_s, "prem_m": round(d_usd / 1e6, 2),
                    "prem_str": prem_lbl, "qty": d_vol, "tag": tag_lbl, "notes": [],
                })
    except Exception:
        pass
    finally:
        if qctx is not None:
            try:
                qctx.close()
            except Exception:
                pass

    # 2순위 폴백: 무무 옵션 권한 미지원 시 Yahoo Finance 실시간 거래량 급증 스캔
    if not mm_ok:
        try:
            import yfinance as yf
            for tk in tks[:6]:
                t_obj = yf.Ticker(tk)
                exps = list(t_obj.options or [])[:2]
                for ex in exps:
                    ch = t_obj.option_chain(ex)
                    for cp_s, df_opt in [("C", ch.calls), ("P", ch.puts)]:
                        if df_opt is None or df_opt.empty:
                            continue
                        for _, r in df_opt.iterrows():
                            vol = int(r.get("volume", 0) or 0) if str(r.get("volume", "")) != "nan" else 0
                            px = float(r.get("lastPrice", 0) or 0)
                            stk = float(r.get("strike", 0) or 0)
                            c_sym = str(r.get("contractSymbol", f"{tk}_{ex}_{stk}{cp_s}"))
                            if vol <= 0 or px <= 0:
                                continue
                            old_v = int(prev_vols.get(c_sym, vol if first_run else 0))
                            prev_vols[c_sym] = vol
                            if first_run:
                                continue
                            d_vol = vol - old_v
                            if d_vol <= 0:
                                continue
                            d_usd = d_vol * px * 100.0
                            if d_usd < 1_000_000:
                                continue
                            prem_lbl = f"${d_usd/1e6:.2f}M"
                            tag_lbl = "MEGA WHALE 4M+" if d_usd >= 4_000_000 else "LIVE FLOW"
                            emo = "🐋🚨" if d_usd >= 4_000_000 else ("🟢" if cp_s == "C" else "🔴")
                            alerts.append(f"{emo} {tk} {stk:g}{cp_s} {ex[5:10]} {prem_lbl} ({d_vol:,}계약) · {tag_lbl}")
                            new_recs_by_tk.setdefault(tk, []).append({
                                "emoji": "🟢" if cp_s == "C" else "🔴",
                                "tk": tk, "strike": stk, "cp": "Call" if cp_s == "C" else "Put",
                                "exp": ex[5:10], "side": "FLOW", "prem_m": round(d_usd / 1e6, 2),
                                "prem_str": prem_lbl, "qty": d_vol, "tag": tag_lbl, "notes": [],
                            })
        except Exception:
            pass

    try:
        if len(prev_vols) > 6000:
            prev_vols = dict(list(prev_vols.items())[-5000:])
        json.dump(prev_vols, open(WHALE_VOL_PATH, "w", encoding="utf-8"))
    except Exception:
        pass

    if alerts:
        try:
            arr_b = json.load(open(BIG_FLOWS_PATH, "r", encoding="utf-8")) if os.path.exists(BIG_FLOWS_PATH) else []
        except Exception:
            arr_b = []
        now_s = datetime.now().strftime("%Y-%m-%d %H:%M")
        for btk, brecs in new_recs_by_tk.items():
            arr_b.insert(0, {"tk": btk, "ts": now_s, "flip": None, "records": brecs})
        try:
            json.dump(arr_b[:50], open(BIG_FLOWS_PATH, "w", encoding="utf-8"), ensure_ascii=False)
        except Exception:
            pass
        msg = f"🐋 실시간 고래 옵션 체결 {len(alerts)}건 ($1M+)\n" + "\n".join(alerts[:12])
        send_msg(token, chat_id, msg)



FG_PATH = os.path.expanduser("~/.optionhub_fg.json")
AUTO_MORNING_DATE_PATH = os.path.expanduser("~/.optionhub_auto_morning_date.txt")


def fg_label_kr(v):
    if v <= 24: return "극단적 공포"
    if v <= 44: return "공포"
    if v <= 55: return "중립"
    if v <= 74: return "탐욕"
    return "극단적 탐욕"


def get_cnn_fg():
    today_s = datetime.now().strftime("%m-%d")
    try:
        if os.path.exists(FG_PATH):
            d = json.load(open(FG_PATH, "r", encoding="utf-8"))
            if d.get("date") == today_s and d.get("val") is not None:
                v = int(d["val"])
                return v, fg_label_kr(v), today_s, "수동"
    except Exception:
        pass
    try:
        req = urllib.request.Request(
            "https://production.dataviz.cnn.io/index/fearandgreed/graphdata",
            headers={"User-Agent": "Mozilla/5.0"}
        )
        raw = json.loads(urllib.request.urlopen(req, timeout=8).read().decode("utf-8"))
        fg = raw.get("fear_and_greed", {})
        sc = int(round(float(fg.get("score", 35))))
        ts_raw = str(fg.get("timestamp", ""))[:10]
        dt_s = ts_raw[5:10] if len(ts_raw) >= 10 else today_s
        return sc, fg_label_kr(sc), dt_s, "자동"
    except Exception:
        pass
    try:
        if os.path.exists(FG_PATH):
            d = json.load(open(FG_PATH, "r", encoding="utf-8"))
            v = int(d.get("val", 35))
            return v, fg_label_kr(v), str(d.get("date", today_s)), str(d.get("mode", "수동"))
    except Exception:
        pass
    return 35, "공포", today_s, "기본"


def get_seoul_weather():
    try:
        url = "https://api.open-meteo.com/v1/forecast?latitude=37.638&longitude=127.025&current=temperature_2m,apparent_temperature,weather_code&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max&timezone=Asia%2FSeoul&forecast_days=1"
        data = json.loads(urllib.request.urlopen(url, timeout=6).read().decode("utf-8"))
        cur = data.get("current", {})
        dly = data.get("daily", {})
        t_cur = round(float(cur.get("temperature_2m", 10)))
        t_app = round(float(cur.get("apparent_temperature", t_cur)))
        wcode = int(cur.get("weather_code", 3))
        t_min = round(float((dly.get("temperature_2m_min") or [t_cur])[0]))
        t_max = round(float((dly.get("temperature_2m_max") or [t_cur])[0]))
        pop = int((dly.get("precipitation_probability_max") or [0])[0])
        if wcode == 0: w_ico, w_txt = "☀️", "맑음"
        elif wcode in (1, 2): w_ico, w_txt = "⛅", "구름조금"
        elif wcode == 3: w_ico, w_txt = "☁️", "흐림"
        elif wcode in (45, 48): w_ico, w_txt = "🌫", "안개"
        elif 71 <= wcode <= 77: w_ico, w_txt = "❄️", "눈"
        elif wcode >= 51: w_ico, w_txt = "🌧", "비"
        else: w_ico, w_txt = "☁️", "흐림"
        return f"🌡 서울 {w_ico} {w_txt}  {t_cur}°C (체감 {t_app}°C) · {t_min}~{t_max}° · 강수 {pop}%"
    except Exception:
        return "🌡 서울 날씨 조회 대기중"


def _yf_last_chg(sym):
    try:
        import yfinance as yf
        h = yf.Ticker(sym).history(period="5d")
        if h is None or h.empty:
            return None, None
        c1 = float(h["Close"].iloc[-1])
        c0 = float(h["Close"].iloc[-2]) if len(h) >= 2 else c1
        chg = (c1 - c0) / c0 * 100.0 if c0 else 0.0
        return c1, chg
    except Exception:
        return None, None


def _yf_ma200(sym):
    try:
        import yfinance as yf
        h = yf.Ticker(sym).history(period="1y")
        if h is None or len(h) < 50:
            return None, None
        c = float(h["Close"].iloc[-1])
        ma200 = float(h["Close"].tail(200).mean())
        return c, ma200
    except Exception:
        return None, None


def _get_gex_line(tk, disp_name=None):
    lbl = disp_name or tk
    spot_yf, ma200 = _yf_ma200(tk)
    ma_txt = ("200MA위" if spot_yf >= ma200 else "200MA아래") if (spot_yf and ma200) else ""
    try:
        hist = json.load(open(OI_PATH, "r", encoding="utf-8")) if os.path.exists(OI_PATH) else {}
    except Exception:
        hist = {}
    snaps = hist.get(tk) or []
    if snaps:
        sn = snaps[-1]
        det = sn.get("상세", [])
        sp = spot_yf or float(sn.get("Spot", 0) or 0)
        net_g = sum(float(x.get("GEX($M)", 0) or 0) for x in det)
        reg = "롱감마" if net_g >= 0 else "숏감마"
        calls = [x for x in det if x.get("구분") == "Call"]
        puts = [x for x in det if x.get("구분") == "Put"]
        cw = max(calls, key=lambda x: x.get("OI", 0)).get("행사가") if calls else None
        pw = max(puts, key=lambda x: x.get("OI", 0)).get("행사가") if puts else None
        by_k = {}
        for x in det:
            k = float(x.get("행사가", 0) or 0)
            by_k[k] = by_k.get(k, 0.0) + float(x.get("GEX($M)", 0) or 0)
        zg = None
        ks = sorted(by_k.keys())
        cum = 0.0
        for idx_k, k in enumerate(ks):
            prev_c = cum
            cum += by_k[k]
            if idx_k > 0 and ((prev_c < 0 and cum >= 0) or (prev_c > 0 and cum <= 0)):
                zg = k
                break
        parts = [f"{sp:.2f}" if sp else "-", reg]
        if zg: parts.append(f"플립 {zg:g}")
        if cw: parts.append(f"콜월 {cw:g}")
        if pw: parts.append(f"풋월 {pw:g}")
        if ma_txt: parts.append(ma_txt)
        return f"- {lbl} : " + " · ".join(parts)
    return f"- {lbl} : {spot_yf:.2f}" + (f" · {ma_txt}" if ma_txt else "") if spot_yf else f"- {lbl} : 데이터 대기중"


def build_level_alert():
    tks = ["SOXL", "SMH", "SPY", "QQQ", "NVDA", "TSLA"]
    lines = ["📌 주요 종목 GEX · 핵심 레벨"]
    for t in tks:
        lines.append(_get_gex_line(t))
    sk_p, sk_c = _yf_last_chg("000660.KS")
    if sk_p:
        lines.append(f"- 000660(SK하이닉스) : {int(round(sk_p)):,}원 ({sk_c:+.2f}%)")
    return "\n".join(lines)



def get_oi_delta_and_unwind_lines():
    """저장된 OI 히스토리에서 전일 대비 확정 ΔOI 급증 TOP3 및 -25% 이상 대량 청산(Unwind) 경보 추출"""
    surges, unwinds = [], []
    try:
        hist = json.load(open(OI_PATH, "r", encoding="utf-8")) if os.path.exists(OI_PATH) else {}
        for tk, snaps in hist.items():
            if not isinstance(snaps, list) or len(snaps) < 2:
                continue
            s0, s1 = snaps[-2], snaps[-1]
            m0 = {(float(x.get("행사가", 0) or 0), str(x.get("구분", ""))): int(x.get("OI", 0) or 0) for x in s0.get("상세", [])}
            m1 = {(float(x.get("행사가", 0) or 0), str(x.get("구분", ""))): int(x.get("OI", 0) or 0) for x in s1.get("상세", [])}
            for key, v1 in m1.items():
                v0 = m0.get(key, 0)
                dv = v1 - v0
                cp_c = "C" if "C" in key[1].upper() else "P"
                if dv >= 1000:
                    surges.append((dv, f"• {tk} {key[0]:g}{cp_c} (+{dv:,} → 총 {v1:,})"))
                elif v0 >= 1500 and dv <= -max(800, int(v0 * 0.25)):
                    unwinds.append((abs(dv), f"• {tk} {key[0]:g}{cp_c} ({dv:+,}, {dv/v0*100:.0f}%)"))
    except Exception:
        pass
    surges.sort(reverse=True)
    unwinds.sort(reverse=True)
    return [x[1] for x in surges[:3]], [x[1] for x in unwinds[:2]]



def build_trend_reversal_7():
    checks = []
    hist = {}
    if os.path.exists(OI_PATH):
        try:
            hist = json.load(open(OI_PATH, "r", encoding="utf-8"))
        except Exception:
            hist = {}
    put_ok, put_note = False, "OI 대기"
    for tk in ("SOXL", "SPY", "QQQ"):
        sn = hist.get(tk) or []
        if sn:
            last_s = sn[-1]
            pc = float(last_s.get("Put_Call_OI_Ratio") or 1.0)
            if len(sn) >= 2:
                dp = int(last_s.get("Put_OI", 0) or 0) - int(sn[-2].get("Put_OI", 0) or 0)
                put_ok = (dp < 0 and pc <= 1.0)
                put_note = f"{tk} ΔPut {dp:+,} · P/C {pc:.2f}"
            else:
                put_ok = (pc < 0.85)
                put_note = f"{tk} P/C {pc:.2f}"
            break
    checks.append(("1 PUT 세력이 빠졌는가?", put_ok, put_note))

    vix_p, _ = _yf_last_chg("^VIX")
    checks.append(("2 VIX 20 아래인가?", bool(vix_p and vix_p < 20.0), f"{vix_p:.2f}" if vix_p else "-"))

    fg_v, _, _, _ = get_cnn_fg()
    checks.append(("3 공포지수 1자리수인가?", (fg_v < 10), f"{fg_v}"))

    spy_ma_ok, spy_note = False, "-"
    rsi_min = 50.0
    try:
        import yfinance as yf
        h_spy = yf.Ticker("SPY").history(period="1y")["Close"].dropna()
        if len(h_spy) >= 200:
            sp_l = float(h_spy.iloc[-1]); ma2 = float(h_spy.tail(200).mean())
            spy_ma_ok = (sp_l > ma2)
            spy_note = f"${sp_l:.1f}/MA200 ${ma2:.1f}"
        h_hyg = yf.Ticker("HYG").history(period="2mo")["Close"].dropna()
        h_dxy = yf.Ticker("DX-Y.NYB").history(period="5d")["Close"].dropna()
        hyg_ok = (len(h_hyg) >= 20 and float(h_hyg.iloc[-1]) >= float(h_hyg.tail(20).mean()))
        dxy_v = float(h_dxy.iloc[-1]) if not h_dxy.empty else 0.0
        liq_ok = (hyg_ok and 0 < dxy_v < 103.0)
        liq_note = f"DXY {dxy_v:.1f}"
        for rtk in ("SOXL", "QQQ"):
            hc = yf.Ticker(rtk).history(period="3mo")["Close"].dropna()
            if len(hc) >= 16:
                dl = hc.diff()
                up = dl.clip(lower=0).rolling(14).mean()
                dn = (-dl.clip(upper=0)).rolling(14).mean()
                rs = float(up.iloc[-1]) / max(float(dn.iloc[-1]), 1e-6)
                rsi_min = min(rsi_min, round(100.0 - (100.0 / (1.0 + rs)), 1))
    except Exception:
        liq_ok, liq_note = False, "-"

    checks.append(("4 200MA 위인가? (SPY)", spy_ma_ok, spy_note))
    y10_p, _ = _yf_last_chg("^TNX")
    checks.append(("5 저금리인가? (10Y<4%)", bool(y10_p and y10_p < 4.0), f"{y10_p:.2f}%" if y10_p else "-"))
    checks.append(("6 유동성이 풍부한가?", liq_ok, liq_note))
    checks.append(("7 기술적 과매도인가?", (rsi_min <= 35.0), f"RSI {rsi_min:.1f}"))

    yes_n = sum(1 for _, ok_v, _ in checks if ok_v)
    verdict = "🟢 추세 전환 조건 충족" if yes_n >= 5 else ("🟡 추세 전환 혼조·관찰" if yes_n >= 3 else "🔴 추세가 전환될 만한 항목이 부족함")
    out = ["🚦 추세전환 신호 체크"]
    for nm, ok_v, nt in checks:
        out.append(f"{nm} {'YES' if ok_v else 'NO'} ({nt})")
    out.append(f"→ {verdict} ({yes_n}/7)")
    return "\n".join(out)

def build_morning_briefing():
    now_dt = datetime.utcnow() + timedelta(hours=9)
    wdays = ["월", "화", "수", "목", "금", "토", "일"]
    wday = wdays[now_dt.weekday()]
    date_title = f"{now_dt.month}월 {now_dt.day}일 {wday}요일"
    short_dt = f"{now_dt.month:02d}-{now_dt.day:02d} {wday}"

    weather_line = get_seoul_weather()
    vix_p, vix_c = _yf_last_chg("^VIX")
    fg_v, fg_lbl, fg_dt, fg_mode = get_cnn_fg()
    spx_p, spx_c = _yf_last_chg("^GSPC")
    ndx_p, ndx_c = _yf_last_chg("^IXIC")
    y10_p, _ = _yf_last_chg("^TNX")
    y3m_p, _ = _yf_last_chg("^IRX")
    kos_p, kos_c = _yf_last_chg("^KS11")
    krw_p, _ = _yf_last_chg("KRW=X")
    ewy_p, ewy_c = _yf_last_chg("EWY")
    wti_p, wti_c = _yf_last_chg("CL=F")

    vix_tag = "경계" if (vix_p or 0) >= 25 else ("주의" if (vix_p or 0) >= 20 else "정상")
    krw_tag = "주의" if (krw_p or 0) >= 1430 else "정상"
    macro_judge = "경계" if ((vix_p or 0) >= 25 or fg_v <= 24) else ("주의" if ((vix_p or 0) >= 20 or fg_v <= 44) else "정상")
    spr_s = f"{(y10_p - y3m_p):.2f}%p" if (y10_p is not None and y3m_p is not None) else "-"

    lines = [
        f"☀️ 대장 아침 브리핑 · {date_title}",
        "",
        weather_line,
        "",
        f"📊 매크로 : 종합판단 {macro_judge}",
        f"- VIX {vix_p:.2f} ({vix_c:+.2f}%) [{vix_tag}]" if vix_p is not None else "- VIX -",
        f"- CNN F&G {fg_v} ({fg_lbl}) ({fg_mode} {fg_dt})",
        f"- S&P500 {spx_p:.1f} ({spx_c:+.2f}%)  나스닥 {ndx_p:.1f} ({ndx_c:+.2f}%)" if (spx_p and ndx_p) else "- S&P500 / 나스닥 -",
        f"- 미국채 10Y {y10_p:.2f}%  3M {y3m_p:.2f}%  스프레드 {spr_s}" if (y10_p and y3m_p) else "- 미국채 10Y / 3M -",
        f"- KOSPI {kos_p:.1f} ({kos_c:+.2f}%)  USD/KRW {krw_p:.1f} [{krw_tag}]" if (kos_p and krw_p) else "- KOSPI / USD/KRW -",
        f"- EWY {ewy_p:.2f} ({ewy_c:+.2f}%)  유가(WTI) ${wti_p:.2f} ({wti_c:+.2f}%)" if (ewy_p and wti_p) else "- EWY / 유가 -",
        "",
        "📌 관심종목 GEX",
        _get_gex_line("SOXL"),
        _get_gex_line("SMH"),
    ]
    sk_p, sk_c = _yf_last_chg("000660.KS")
    lines.append(f"- 000660(SK하이닉스) : {int(round(sk_p)):,}원 ({sk_c:+.2f}%)" if sk_p else "- 000660(SK하이닉스) : -")
    _oi_surges, _oi_unwinds = get_oi_delta_and_unwind_lines()
    if _oi_surges:
        lines += ["", "🔥 전일 대비 확정 ΔOI 급증 TOP3"] + _oi_surges
    if _oi_unwinds:
        lines += ["", "⚠️ OPEX · 대형 OI 청산(Unwind) 경보"] + _oi_unwinds
    lines += [
        "",
        "최종 종목 판정은 /브리핑, 레벨은 /레벨알림, 7대 신호는 /추세전환 으로 볼 수 있어.",
        "",
        build_trend_reversal_7(),
        "",
        "━━━━━━━━━━",
        f"🌅 최종분석 브리핑 ({short_dt})",
        f"시장 환경: {'방어' if macro_judge == '경계' else ('선별' if macro_judge == '주의' else '공격')} — F&G {fg_v} {fg_lbl}",
    ]

    geeks_s, mq_s, sg_s = None, None, None
    try:
        nrows = fetch_sheet_rows("AI노트_뉴스시황")
        for r in reversed(nrows):
            src_n = str(r.get("출처", r.get("Source", ""))).upper()
            ttl_n = str(r.get("제목", r.get("Title", r.get("내용", "")))).strip().splitlines()[0][:70]
            dt_n = str(r.get("날짜", r.get("Date", "")))[5:10]
            if not ttl_n:
                continue
            if not geeks_s and ("GEEK" in src_n or "긱스" in src_n):
                geeks_s = f"🧬 긱스({dt_n}): {ttl_n}"
            elif not mq_s and ("MENTHOR" in src_n or "멘토" in src_n or "멘도" in src_n):
                mq_s = f"🧭 멘도큐({dt_n}): {ttl_n}"
            elif not sg_s and ("SPOT" in src_n or "스팟" in src_n):
                sg_s = f"🧲 스팟감마({dt_n}): {ttl_n}"
            if geeks_s and mq_s and sg_s:
                break
    except Exception:
        pass
    if geeks_s: lines.append(geeks_s)
    if mq_s: lines.append(mq_s)
    if sg_s: lines.append(sg_s)

    tk_scores = {}
    try:
        for r in get_app_flows()[-120:]:
            tk = str(r[1]).upper()
            cp = str(r[3]).upper()
            side = str(r[4]).upper()
            sc = 1 if (("C" in cp and "A" in side) or ("P" in cp and "B" in side)) else -1
            tk_scores[tk] = tk_scores.get(tk, [0, 0])
            tk_scores[tk][0] += 1
            tk_scores[tk][1] += sc
    except Exception:
        pass
    top_tks = sorted(tk_scores.items(), key=lambda x: x[1][0], reverse=True)[:8]
    buys = [k for k, v in top_tks if v[1] >= 2][:3]
    sells = [k for k, v in top_tks if v[1] <= -1][:3]
    holds = [k for k, v in top_tks if k not in buys and k not in sells][:3]

    lines.append("🎯 종목 (최근 5일 반복 등장 상위)")
    if buys: lines.append("🟢 매수: " + ", ".join(buys))
    if sells: lines.append("🔴 매도: " + ", ".join(sells))
    if holds: lines.append("⚪ 관망: " + ", ".join(holds))
    if not (buys or sells or holds): lines.append("⚪ 관망: SOXL, NVDA, MU")

    concl = "관망" if macro_judge != "정상" else "선별 매수"
    if sells:
        concl += f" (보유분 매도 점검: {', '.join(sells)})"
    lines += [
        "📝 내 규칙 체크 (차트에서 직접 확인)",
        "🟢 후행스팬이 캔들 뚫을때 매수신호",
        f"📌 결론: {concl}",
        f"한 줄 요약: {'시장 환경을 확인하며 선별해서 접근해.' if macro_judge != '정상' else '강세 수급 종목 위주로 눌림목 분할 접근해.'}",
        "※ F&G가 오래됐으면 /fg 숫자 로 갱신해줘 (CNN 페이지 확인).",
    ]
    return "\n".join(lines)


def auto_send_morning_briefing(token, chat_id):
    """매일 오전 07:10 KST 이후 1회 자동 아침 브리핑 전송"""
    try:
        now_kst = datetime.utcnow() + timedelta(hours=9)
        if now_kst.hour < 7 or (now_kst.hour == 7 and now_kst.minute < 10):
            return
        today_s = now_kst.strftime("%Y-%m-%d")
        if os.path.exists(AUTO_MORNING_DATE_PATH):
            if open(AUTO_MORNING_DATE_PATH, "r").read().strip() == today_s:
                return
        msg = build_morning_briefing()
        send_msg(token, chat_id, msg)
        open(AUTO_MORNING_DATE_PATH, "w").write(today_s)
    except Exception:
        pass



def _fmt_prem_short(v):
    if v >= 1e6:
        return f"${v/1e6:.1f}M"
    if v >= 1e3:
        return f"${v/1e3:.0f}K"
    return f"${v:.0f}"

def build_intraday_option_changes():
    import re as _re_ic
    hist = {}
    if os.path.exists(OI_PATH):
        try:
            with open(OI_PATH, "r", encoding="utf-8") as _f:
                hist = json.load(_f)
        except Exception:
            hist = {}
    base_tks = ["SOXL", "TSLA", "SOXS", "PLTR", "AAPL", "NVDA", "AVGO", "SMH", "SPY", "MU", "QQQ", "AMD", "ORCL"]
    tks = list(dict.fromkeys(list(hist.keys()) + base_tks))
    blocks = []
    for tk in tks[:18]:
        try:
            cboe_sym = {"SPX": "_SPX", "NDX": "_NDX", "VIX": "_VIX", "RUT": "_RUT"}.get(tk, tk)
            url = f"https://cdn.cboe.com/api/global/delayed_quotes/options/{cboe_sym}.json"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            raw = json.loads(urllib.request.urlopen(req, timeout=6).read().decode("utf-8"))
            data_d = raw.get("data") or {}
            opts = data_d.get("options") or []
            spot = float(data_d.get("current_price") or data_d.get("close") or 0.0)
            if not opts or spot <= 0:
                continue

            snaps = hist.get(tk) or []
            prev_snap = snaps[-1] if snaps else {}
            prev_cw = float(prev_snap.get("CallWall", 0) or 0)
            prev_pw = float(prev_snap.get("PutWall", 0) or 0)
            prev_put_oi = float(prev_snap.get("Put_OI", 0) or 0)
            prev_call_oi = float(prev_snap.get("Call_OI", 0) or 0)
            prev_put_pct = round(prev_put_oi / max(prev_put_oi + prev_call_oi, 1) * 100) if (prev_put_oi + prev_call_oi) > 0 else None

            call_oi_by_k, put_oi_by_k = {}, {}
            tot_c_vol, tot_p_vol = 0, 0
            new_pos_cands, rot_cands = [], []
            for o in opts:
                occ = str(o.get("option") or "")
                m = _re_ic.match(r"^[A-Z]+(\d{6})([CP])(\d{8})$", occ)
                if not m:
                    continue
                yymmdd, cp_ch, k_raw = m.groups()
                mm_dd = f"{yymmdd[2:4]}-{yymmdd[4:6]}"
                strike = int(k_raw) / 1000.0
                oi = int(o.get("open_interest") or 0)
                vol = int(o.get("volume") or 0)
                last_px = float(o.get("last_trade_price") or 0)
                bid = float(o.get("bid") or 0)
                ask = float(o.get("ask") or 0)
                mid = (bid + ask) / 2.0 if (bid > 0 and ask > 0) else last_px
                prem = vol * mid * 100.0
                if cp_ch == "C":
                    tot_c_vol += vol
                    if spot * 0.98 <= strike <= spot * 1.25:
                        call_oi_by_k[strike] = call_oi_by_k.get(strike, 0) + oi
                else:
                    tot_p_vol += vol
                    if spot * 0.80 <= strike <= spot * 1.02:
                        put_oi_by_k[strike] = put_oi_by_k.get(strike, 0) + oi

                if vol >= 1000 and oi >= 20 and vol > oi:
                    ratio = vol / float(oi)
                    new_pos_cands.append((ratio, vol, f"🆕 {strike:g}{cp_ch} {mm_dd} 거래 {vol:,} > OI {oi:,} ({ratio:.1f}배) → 새 포지션 가능성 · 내일 OI로 확인"))
                if oi >= 100 and vol / float(oi) >= 0.30 and prem >= 500_000:
                    pct = round(vol / float(oi) * 100)
                    if ask > 0 and last_px >= ask * 0.99:
                        side_txt = "매수 체결 쪽(신규·되사기 가능)"
                    elif bid > 0 and last_px <= bid * 1.01:
                        side_txt = "매도 체결 쪽(정리 가능)"
                    else:
                        side_txt = "호가 중간"
                    rot_cands.append((prem, f"🔄 큰 회전 {strike:g}{cp_ch} {mm_dd} · 거래 {vol:,} / OI {oi:,} ({pct}%) · 규모 {_fmt_prem_short(prem)} · {side_txt} — 신규/청산은 거래량만으로 구분 못 해요"))

            cur_cw = max(call_oi_by_k, key=call_oi_by_k.get) if call_oi_by_k else 0.0
            cur_pw = max(put_oi_by_k, key=put_oi_by_k.get) if put_oi_by_k else 0.0
            lines_tk = []
            for _, _, msg_n in sorted(new_pos_cands, reverse=True)[:2]:
                lines_tk.append(msg_n)
            for _, msg_r in sorted(rot_cands, reverse=True)[:4]:
                lines_tk.append(msg_r)
            if cur_cw > 0 and spot > cur_cw:
                lines_tk.append(f"🚀 현재가 ${spot:,.2f} Call Wall {cur_cw:g} 위로 돌파 → 과열·추격 주의")
            if cur_pw > 0 and spot < cur_pw:
                lines_tk.append(f"⚠️ 현재가 ${spot:,.2f} Put Wall {cur_pw:g} 아래로 이탈 → 변동성 확대 구간")
            if prev_cw > 0 and cur_cw > 0 and abs(cur_cw - prev_cw) >= max(1.0, prev_cw * 0.02):
                if cur_cw > prev_cw:
                    lines_tk.append(f"🧱 Call Wall 이동 {prev_cw:g} → {cur_cw:g} (어제 대비 위로 ↑) · 저항이 올라감 = 상단 열림")
                else:
                    lines_tk.append(f"🧱 Call Wall 이동 {prev_cw:g} → {cur_cw:g} (어제 대비 아래로 ↓) · 저항이 내려옴 = 상단 눌림")
            if prev_pw > 0 and cur_pw > 0 and abs(cur_pw - prev_pw) >= max(1.0, prev_pw * 0.02):
                if cur_pw < prev_pw:
                    lines_tk.append(f"🧱 Put Wall 이동 {prev_pw:g} → {cur_pw:g} (어제 대비 아래로 ↓) · 지지가 내려감 = 바닥 약해짐")
                else:
                    lines_tk.append(f"🧱 Put Wall 이동 {prev_pw:g} → {cur_pw:g} (어제 대비 위로 ↑) · 지지가 올라감 = 바닥 단단해짐")
            if prev_put_pct is not None and (tot_c_vol + tot_p_vol) >= 1000:
                cur_put_pct = round(tot_p_vol / float(tot_c_vol + tot_p_vol) * 100)
                if cur_put_pct - prev_put_pct >= 15:
                    lines_tk.append(f"🔻 풋 쪽으로 급쏠림: 풋 비중 {prev_put_pct}% → {cur_put_pct}%")
                elif prev_put_pct - cur_put_pct >= 15:
                    lines_tk.append(f"🔺 콜 쪽으로 급쏠림: 콜 비중 {100-prev_put_pct}% → {100-cur_put_pct}%")

            if lines_tk:
                blocks.append(f"🔎 {tk} ${spot:,.2f}\n" + "\n".join(lines_tk))
        except Exception:
            continue

    if not blocks:
        return "⏱ 장중 옵션 변화 (OI 기록 종목 · CBOE 지연)\n\n현재 특이 변화가 감지된 종목이 없습니다."
    return "⏱ 장중 옵션 변화 (OI 기록 종목 · CBOE 지연)\n\n" + "\n\n".join(blocks) + "\n\n(방향·신규는 추정 · 확인 후 판단)"

_LAST_INTRADAY_SCAN_TS = 0.0

def auto_scan_intraday_option_changes(token, chat_id):
    global _LAST_INTRADAY_SCAN_TS
    try:
        from datetime import datetime, timezone, timedelta
        kst = datetime.now(timezone(timedelta(hours=9)))
        # 미 증시 본장 시간대 (화~토 새벽 23:30 ~ 06:00 KST) 30분마다 자동 푸시
        hm = kst.hour * 100 + kst.minute
        wd = kst.weekday()
        in_session = ((wd in (0, 1, 2, 3, 4) and hm >= 2330) or (wd in (1, 2, 3, 4, 5) and hm <= 600))
        if not in_session:
            return
        now_ts = time.time()
        if now_ts - _LAST_INTRADAY_SCAN_TS < 1800:
            return
        _LAST_INTRADAY_SCAN_TS = now_ts
        msg = build_intraday_option_changes()
        if "🔎 " in msg:
            send_msg(token, chat_id, msg)
    except Exception:
        pass


def build_big_option_flows_summary():
    import re as _re_bf
    watch = ["NVDA", "TSLA", "AMD", "SOXL", "SOXS", "META", "TSM", "MU", "PLTR", "ORCL", "INTC", "AAPL", "AVGO", "SMH", "SPY", "QQQ"]
    items = []
    for tk in watch:
        try:
            url = f"https://cdn.cboe.com/api/global/delayed_quotes/options/{tk}.json"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            raw = json.loads(urllib.request.urlopen(req, timeout=6).read().decode("utf-8"))
            data_d = raw.get("data") or {}
            opts = data_d.get("options") or []
            spot = float(data_d.get("current_price") or data_d.get("close") or 0.0)
            if not opts or spot <= 0:
                continue
            for o in opts:
                occ = str(o.get("option") or "")
                m = _re_bf.match(r"^[A-Z]+(\d{6})([CP])(\d{8})$", occ)
                if not m:
                    continue
                yymmdd, cp_ch, k_raw = m.groups()
                mm_dd = f"{yymmdd[2:4]}-{yymmdd[4:6]}"
                strike = int(k_raw) / 1000.0
                oi = int(o.get("open_interest") or 0)
                vol = int(o.get("volume") or 0)
                if vol < 200:
                    continue
                last_px = float(o.get("last_trade_price") or 0)
                bid = float(o.get("bid") or 0)
                ask = float(o.get("ask") or 0)
                mid = (bid + ask) / 2.0 if (bid > 0 and ask > 0) else last_px
                prem = vol * mid * 100.0
                if prem < 1_500_000:
                    continue
                # 깊은 ITM(델타~1/-1) 노이즈 제외
                is_deep_itm = (cp_ch == "P" and strike > spot * 1.25) or (cp_ch == "C" and strike < spot * 0.75)
                if ask > 0 and last_px >= ask * 0.99:
                    side = "BUY" if last_px >= ask else "BUY?"
                elif bid > 0 and last_px <= bid * 1.01:
                    side = "SELL" if last_px <= bid else "SELL?"
                else:
                    side = "혼합"
                kind_tag = "단일 대량" if (oi > 0 and vol <= oi * 0.8) else "일간 분할"
                bull_p, bear_p = 0.0, 0.0
                if not is_deep_itm:
                    if cp_ch == "C" and "BUY" in side:
                        bull_p = prem
                    elif cp_ch == "P" and "SELL" in side:
                        bull_p = prem
                    elif cp_ch == "C" and "SELL" in side:
                        bear_p = prem
                    elif cp_ch == "P" and "BUY" in side:
                        bear_p = prem
                items.append({
                    "tk": tk, "cp": cp_ch, "strike": strike, "exp": mm_dd,
                    "vol": vol, "prem": prem, "side": side, "kind": kind_tag,
                    "bull_p": bull_p, "bear_p": bear_p, "deep": is_deep_itm,
                })
        except Exception:
            continue

    if not items:
        return "🧾 대형 옵션 체결 · 신규/증가\n\n현재 기준($1.5M+) 대형 체결이 없습니다.", None

    dir_items = [x for x in items if not x["deep"]]
    top_items = sorted(dir_items or items, key=lambda x: x["prem"], reverse=True)[:5]
    top_lines = [
        f"- {x['tk']} {x['strike']:g}{x['cp']} {x['exp']} ${x['prem']/1e6:.2f}M {x['side']} ({x['kind']})"
        for x in top_items
    ]

    tot_bull = sum(x["bull_p"] for x in dir_items)
    tot_bear = sum(x["bear_p"] for x in dir_items)
    if tot_bull > tot_bear * 1.35:
        tot_bias = "강세 쪽으로 쏠렸어요"
    elif tot_bear > tot_bull * 1.35:
        tot_bias = "약세 쪽으로 쏠렸어요"
    else:
        tot_bias = "한쪽으로 쏠리지 않았어요"

    by_tk = {}
    for x in dir_items:
        t = x["tk"]
        if t not in by_tk:
            by_tk[t] = {"bull": 0.0, "bear": 0.0, "sup": [], "res": [], "up": [], "dn": []}
        by_tk[t]["bull"] += x["bull_p"]
        by_tk[t]["bear"] += x["bear_p"]
        if x["cp"] == "C" and "BUY" in x["side"]:
            by_tk[t]["up"].append(x["strike"])
        elif x["cp"] == "C" and "SELL" in x["side"]:
            by_tk[t]["res"].append(x["strike"])
        elif x["cp"] == "P" and "SELL" in x["side"]:
            by_tk[t]["sup"].append(x["strike"])
        elif x["cp"] == "P" and "BUY" in x["side"]:
            by_tk[t]["dn"].append(x["strike"])

    tk_lines = []
    for t, d in sorted(by_tk.items(), key=lambda kv: kv[1]["bull"] + kv[1]["bear"], reverse=True)[:6]:
        if d["bull"] + d["bear"] < 1_000_000:
            continue
        bias_s = "강세 우위" if d["bull"] > d["bear"] * 1.15 else ("약세 우위" if d["bear"] > d["bull"] * 1.15 else "혼조")
        lv_parts = []
        if d["sup"]:
            lv_parts.append(f"지지 {sorted(set(d['sup']))[0]:g}")
        if d["res"]:
            lv_parts.append(f"저항 {sorted(set(d['res']))[0]:g}")
        if d["up"]:
            lv_parts.append(f"상방 목표 {sorted(set(d['up']))[-1]:g}")
        if d["dn"]:
            lv_parts.append(f"하방 대비 {sorted(set(d['dn']))[0]:g}")
        lv_str = f" → {' / '.join(lv_parts)}" if lv_parts else ""
        tk_lines.append(f"- {t} {bias_s} (강세 ${d['bull']/1e6:.1f}M · 약세 ${d['bear']/1e6:.1f}M){lv_str}")

    _txt_out = (
        f"🧾 대형 옵션 체결 · 신규/증가 {len(top_items)}건\n"
        + "\n".join(top_lines)
        + f"\n\n전체: 강세 ${tot_bull/1e6:.1f}M vs 약세 ${tot_bear/1e6:.1f}M → {tot_bias}\n"
        + "\n".join(tk_lines)
        + "\n\n(방향은 추정 · 확인 후 판단)"
    )
    _png_out = _render_bigflows_card_png(dir_items or items, tot_bull, tot_bear, tot_bias, tk_lines)
    return _txt_out, _png_out

_LAST_BIGFLOW_SCAN_TS = 0.0

def auto_scan_big_flows_summary(token, chat_id):
    global _LAST_BIGFLOW_SCAN_TS
    try:
        from datetime import datetime, timezone, timedelta
        kst = datetime.now(timezone(timedelta(hours=9)))
        hm = kst.hour * 100 + kst.minute
        wd = kst.weekday()
        in_session = ((wd in (0, 1, 2, 3, 4) and hm >= 2330) or (wd in (1, 2, 3, 4, 5) and hm <= 600))
        if not in_session:
            return
        now_ts = time.time()
        if now_ts - _LAST_BIGFLOW_SCAN_TS < 1800:
            return
        _LAST_BIGFLOW_SCAN_TS = now_ts
        msg, png_b = build_big_option_flows_summary()
        if "전체: 강세" in msg:
            if png_b:
                send_photo_bytes(token, chat_id, png_b, "🧾 대형 옵션 체결 상위 표 & 종목별 해석")
            send_msg(token, chat_id, msg)
    except Exception:
        pass


def build_moomoo_cp_dominance():
    import socket as _sock_cp
    tks = ["SPY", "QQQ", "IWM", "NVDA", "TSLA", "SOXL", "SOXS", "SMH", "MU", "AMD", "PLTR", "AAPL", "META", "AMZN", "AVGO", "ORCL"]
    try:
        with _sock_cp.create_connection(("127.0.0.1", 11111), timeout=0.4):
            pass
    except Exception:
        return "📡 무무 콜/풋 강세 스캔\n\n⚠️ 무무 OpenD(11111 포트)가 꺼져 있거나 응답이 없습니다."

    qctx = None
    stats = {}
    try:
        from moomoo import OpenQuoteContext, RET_OK
        qctx = OpenQuoteContext(host="127.0.0.1", port=11111)
        now_d = datetime.now()
        start_d = now_d.strftime("%Y-%m-%d")
        end_d = (now_d + timedelta(days=10)).strftime("%Y-%m-%d")
        code_to_tk = {}
        opt_codes = []
        for tk in tks:
            ret_c, df_c = qctx.get_option_chain(code=f"US.{tk}", start=start_d, end=end_d)
            if ret_c == RET_OK and df_c is not None and not df_c.empty:
                c_list = df_c["code"].tolist()[:50]
                for oc in c_list:
                    code_to_tk[oc] = tk
                opt_codes.extend(c_list)
        for i in range(0, len(opt_codes), 100):
            batch = opt_codes[i:i+100]
            ret_s, df_s = qctx.get_market_snapshot(batch)
            if ret_s != RET_OK or df_s is None or df_s.empty:
                continue
            for _, r in df_s.iterrows():
                code = str(r.get("code", ""))
                tk = code_to_tk.get(code)
                if not tk:
                    continue
                vol = int(r.get("volume", 0) or 0)
                px = float(r.get("last_price", 0) or 0)
                if vol <= 0 or px <= 0:
                    continue
                ask_p = float(r.get("ask_price", 0) or 0)
                bid_p = float(r.get("bid_price", 0) or 0)
                stk = float(r.get("option_strike_price", 0) or 0)
                cp_s = "C" if "CALL" in str(r.get("option_type", "")).upper() else "P"
                exp_s = str(r.get("strike_time", ""))[5:10]
                prem = vol * px * 100.0
                d = stats.setdefault(tk, {"c_prem": 0.0, "p_prem": 0.0, "c_vol": 0, "p_vol": 0, "bull": 0.0, "bear": 0.0, "top_c": (0.0, ""), "top_p": (0.0, "")})
                if cp_s == "C":
                    d["c_prem"] += prem; d["c_vol"] += vol
                    if prem > d["top_c"][0]:
                        d["top_c"] = (prem, f"{stk:g}C({exp_s}, {_fmt_prem_short(prem)})")
                    if ask_p > 0 and px >= ask_p * 0.99: d["bull"] += prem
                    elif bid_p > 0 and px <= bid_p * 1.01: d["bear"] += prem
                else:
                    d["p_prem"] += prem; d["p_vol"] += vol
                    if prem > d["top_p"][0]:
                        d["top_p"] = (prem, f"{stk:g}P({exp_s}, {_fmt_prem_short(prem)})")
                    if bid_p > 0 and px <= bid_p * 1.01: d["bull"] += prem
                    elif ask_p > 0 and px >= ask_p * 0.99: d["bear"] += prem
    except Exception as _em:
        return f"📡 무무 콜/풋 강세 스캔 오류: {_em}"
    finally:
        if qctx:
            try: qctx.close()
            except Exception: pass

    call_dom, put_dom = [], []
    for tk, d in stats.items():
        tot_p = d["c_prem"] + d["p_prem"]
        if tot_p < 500_000:
            continue
        c_pct = round(d["c_prem"] / tot_p * 100)
        p_pct = 100 - c_pct
        if c_pct >= 62 or (d["bull"] > d["bear"] * 1.6 and d["bull"] >= 1_000_000):
            call_dom.append((d["c_prem"] - d["p_prem"], f"🟢 {tk}: 콜 {c_pct}% ({_fmt_prem_short(d['c_prem'])}) vs 풋 {p_pct}% ({_fmt_prem_short(d['p_prem'])}) | 대표 {d['top_c'][1]}"))
        elif p_pct >= 62 or (d["bear"] > d["bull"] * 1.6 and d["bear"] >= 1_000_000):
            put_dom.append((d["p_prem"] - d["c_prem"], f"🔴 {tk}: 풋 {p_pct}% ({_fmt_prem_short(d['p_prem'])}) vs 콜 {c_pct}% ({_fmt_prem_short(d['c_prem'])}) | 대표 {d['top_p'][1]}"))

    if not call_dom and not put_dom:
        return "📡 무무 실시간 콜/풋 쏠림 종목\n\n현재 콜/풋 한쪽으로 62% 이상 쏠린 종목이 없습니다."

    out = ["📡 무무 실시간 콜/풋 강세 종목"]
    if call_dom:
        out.append("\n🔥 [콜(상승) 우위 종목]")
        out.extend(x[1] for x in sorted(call_dom, reverse=True)[:6])
    if put_dom:
        out.append("\n🧊 [풋(하락·헷지) 우위 종목]")
        out.extend(x[1] for x in sorted(put_dom, reverse=True)[:6])
    return "\n".join(out)

_LAST_CPDOM_SCAN_TS = 0.0

def auto_scan_moomoo_cp_dominance(token, chat_id):
    global _LAST_CPDOM_SCAN_TS
    try:
        from datetime import datetime, timezone, timedelta
        kst = datetime.now(timezone(timedelta(hours=9)))
        hm = kst.hour * 100 + kst.minute
        wd = kst.weekday()
        in_session = ((wd in (0, 1, 2, 3, 4) and hm >= 2330) or (wd in (1, 2, 3, 4, 5) and hm <= 600))
        if not in_session:
            return
        now_ts = time.time()
        if now_ts - _LAST_CPDOM_SCAN_TS < 1800:
            return
        _LAST_CPDOM_SCAN_TS = now_ts
        msg = build_moomoo_cp_dominance()
        if "우위 종목]" in msg:
            send_msg(token, chat_id, msg)
    except Exception:
        pass


CP_BASE_PATH = os.path.expanduser("~/.optionhub_cp_baseline.json")

def _render_strong_cp_png(put_rows, call_rows, total_cnt, c_cnt, today_et):
    if not put_rows and not call_rows:
        return None
    try:
        import io
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.font_manager as fm
        from matplotlib.patches import FancyBboxPatch

        _font_set = False
        for _fp in ["/usr/share/fonts/truetype/nanum/NanumGothic.ttf", "/usr/share/fonts/truetype/nanum/NanumBarunGothic.ttf", "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"]:
            if os.path.exists(_fp):
                fm.fontManager.addfont(_fp)
                plt.rcParams["font.family"] = fm.FontProperties(fname=_fp).get_name()
                _font_set = True
                break
        if not _font_set:
            plt.rcParams["font.sans-serif"] = ["NanumGothic", "Noto Sans CJK KR", "Malgun Gothic", "DejaVu Sans"]
        plt.rcParams["axes.unicode_minus"] = False

        n_all = len(put_rows) + len(call_rows)
        fig_h = max(4.8, 2.5 + n_all * 0.72 + (0.7 if put_rows else 0) + (0.7 if call_rows else 0))
        fig = plt.figure(figsize=(13.2, fig_h), facecolor="#0a111d")
        ax = fig.add_axes([0, 0, 1, 1], facecolor="#0a111d")
        ax.set_xlim(0, 100)
        ax.set_ylim(0, 100)
        ax.axis("off")

        ax.text(2, 96.5, "강한 풋 · 강한 콜 스캔 (정확도 보정판)", color="#f8fafc", fontsize=14, fontweight="bold", va="center")
        ax.text(2, 93.2, f"{today_et} ET · 만기 14일 이내 · {total_cnt}종목 확인 · A·B 등급만 표시 (C {c_cnt}종목 생략)", color="#94a3b8", fontsize=9.2, va="center")

        y_cur = 88.5
        cols = [(2, "종목"), (11, "등급·점수"), (20, "쏠림"), (28, "평소 대비"), (39, "가장 큰 계약"), (61, "집중도"), (68, "거래량/OI"), (77, "큰 체결 방향"), (89, "방향 추정")]
        step = min(9.2, 78.0 / max(n_all + 2.5, 1))

        def _draw_sec(title_s, title_col, rlist, yc):
            if not rlist:
                return yc
            ax.text(2, yc, f"{title_s} · {len(rlist)}종목", color=title_col, fontsize=11, fontweight="bold", va="center")
            yc -= step * 0.48
            ax.add_patch(FancyBboxPatch((1.5, yc - step * 0.20), 97, step * 0.40, boxstyle="round,pad=0.1", facecolor="#101b2e", edgecolor="#1e3a5f", linewidth=0.6))
            for cx, cn in cols:
                ax.text(cx, yc, cn, color="#64748b", fontsize=8.3, fontweight="bold", va="center")
            yc -= step * 0.55
            for r in rlist:
                ax.add_patch(FancyBboxPatch((1.5, yc - step * 0.45), 97, step * 0.85, boxstyle="round,pad=0.1", facecolor="#0d1626", edgecolor="#132238", linewidth=0.5))
                ax.text(2, yc + step * 0.12, r["tk"], color="#f8fafc", fontsize=10, fontweight="bold", va="center")
                gcol = "#34d399" if r["grade"] == "A" else "#fbbf24"
                ax.text(11, yc + step * 0.12, f"{r['grade']} {r['score']}점", color=gcol, fontsize=9.2, fontweight="bold", va="center")
                ax.text(20, yc + step * 0.12, r["skew_str"], color=title_col, fontsize=9.2, fontweight="bold", va="center")
                ax.text(28, yc + step * 0.12, r["base_str"], color="#94a3b8", fontsize=8.5, va="center")
                ax.text(39, yc + step * 0.12, r["top_str"], color="#cbd5e1", fontsize=8.6, va="center")
                ax.text(61, yc + step * 0.12, f"{r['conc']}%", color="#cbd5e1", fontsize=8.8, va="center")
                ax.text(68, yc + step * 0.12, f"{r['voi']:.1f}x", color="#e2e8f0", fontsize=8.8, fontweight="bold", va="center")
                ax.text(77, yc + step * 0.12, r["big_dir"], color="#94a3b8", fontsize=8.5, va="center")
                ax.text(89, yc + step * 0.12, r["dir_est"], color=r["dir_col"], fontsize=9, fontweight="bold", va="center")
                ax.text(2, yc - step * 0.22, r["sub_note"], color="#64748b", fontsize=7.8, va="center")
                yc -= step * 0.96
            return yc - step * 0.35

        y_cur = _draw_sec("풋 쏠림 (거래대금 기준)", "#f87171", put_rows, y_cur)
        y_cur = _draw_sec("콜 쏠림 (거래대금 기준)", "#34d399", call_rows, y_cur)
        ax.text(2, 2.2, "쏠림 = 당일만기·먼 OTM 제외한 거래대금 기준 · 지원 자료 CBOE 약 15분 지연 · ※ 거래 쏠림일 뿐 방향 확정 아님", color="#64748b", fontsize=8.2, va="center")

        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=140, bbox_inches="tight", facecolor="#0a111d")
        plt.close(fig)
        return buf.getvalue()
    except Exception as _er:
        print("render_strong_cp_png err:", _er, flush=True)
        return None

def build_strong_cp_scan():
    import re as _re_ab
    from datetime import datetime, timezone, timedelta
    et_now = datetime.now(timezone(timedelta(hours=-5)))
    today_et = et_now.strftime("%Y-%m-%d")
    tks = ["SOXL", "SOXS", "KORU", "TSLA", "NVDA", "AAPL", "AMD", "MU", "PLTR", "SPCX", "SMH", "SPY", "QQQ", "AVGO", "META"]
    inv_tks = {"SOXS", "SQQQ", "SPXS", "NVD", "TSLQ"}

    base_hist = {}
    if os.path.exists(CP_BASE_PATH):
        try:
            base_hist = json.load(open(CP_BASE_PATH, "r", encoding="utf-8"))
        except Exception:
            base_hist = {}

    put_rows, call_rows = [], []
    c_cnt, checked = 0, 0
    for tk in tks:
        try:
            url = f"https://cdn.cboe.com/api/global/delayed_quotes/options/{tk}.json"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            raw = json.loads(urllib.request.urlopen(req, timeout=6).read().decode("utf-8"))
            dd = raw.get("data") or {}
            opts = dd.get("options") or []
            spot = float(dd.get("current_price") or dd.get("close") or 0.0)
            if not opts or spot <= 0:
                continue
            checked += 1
            c_prem, p_prem = 0.0, 0.0
            best_c, best_p = None, None
            for o in opts:
                m = _re_ab.match(r"^[A-Z]+(\d{6})([CP])(\d{8})$", str(o.get("option") or ""))
                if not m: continue
                ym, cp_ch, kr = m.groups()
                exp_s = f"20{ym[:2]}-{ym[2:4]}-{ym[4:6]}"
                try:
                    dte = (datetime.strptime(exp_s, "%Y-%m-%d").date() - et_now.date()).days
                except Exception:
                    continue
                if dte < 1 or dte > 14:
                    continue
                strike = int(kr) / 1000.0
                if strike < spot * 0.65 or strike > spot * 1.35:
                    continue
                vol = int(o.get("volume") or 0)
                oi = int(o.get("open_interest") or 0)
                if vol <= 0: continue
                lp = float(o.get("last_trade_price") or 0)
                bd = float(o.get("bid") or 0); ak = float(o.get("ask") or 0)
                mid = (bd + ak) / 2.0 if (bd > 0 and ak > 0) else lp
                prem = vol * mid * 100.0
                if prem <= 0: continue
                otm_pct = round(abs(strike - spot) / spot * 100)
                rec = {"exp": f"{ym[2:4]}-{ym[4:6]}", "dte": dte, "cp": cp_ch, "k": strike, "vol": vol, "oi": oi, "prem": prem, "otm": otm_pct}
                if cp_ch == "C":
                    c_prem += prem
                    if best_c is None or prem > best_c["prem"]:
                        best_c = rec
                else:
                    p_prem += prem
                    if best_p is None or prem > best_p["prem"]:
                        best_p = rec

            tot_prem = c_prem + p_prem
            if tot_prem < 300_000:
                continue
            # 평소 대비 기준 저장
            bh_list = [x for x in base_hist.get(tk, []) if x.get("d") != today_et][-19:]
            avg_prev = (sum(x["p"] for x in bh_list) / len(bh_list)) if len(bh_list) >= 3 else 0.0
            base_str = f"{tot_prem/avg_prev:.1f}x" if avg_prev > 0 else "기준 쌓는 중"
            bh_list.append({"d": today_et, "p": round(tot_prem, 0)})
            base_hist[tk] = bh_list

            c_pct = round(c_prem / tot_prem * 100)
            p_pct = 100 - c_pct
            if max(c_pct, p_pct) < 62:
                continue
            is_put_dom = p_pct >= c_pct
            dom_pct = p_pct if is_put_dom else c_pct
            best = best_p if is_put_dom else best_c
            if not best:
                continue
            conc = round(best["prem"] / tot_prem * 100)
            voi = best["vol"] / float(max(best["oi"], 1))
            score = (3 if dom_pct >= 85 else (2 if dom_pct >= 72 else 1)) + (2 if conc >= 25 else (1 if conc >= 15 else 0)) + (2 if voi >= 3.0 else (1 if voi >= 1.2 else 0)) + (2 if tot_prem >= 10_000_000 else (1 if tot_prem >= 3_000_000 else 0))
            grade = "A" if score >= 7 else ("B" if score >= 4 else "C")
            if grade == "C":
                c_cnt += 1
                continue

            is_inv = tk in inv_tks
            if is_put_dom:
                dir_est = "기초 상승 쪽" if is_inv else "하락 쪽"
                dir_col = "#34d399" if is_inv else "#f87171"
            else:
                dir_est = "기초 하락 쪽" if is_inv else "상승 쪽"
                dir_col = "#f87171" if is_inv else "#34d399"

            cp_kr = "풋" if best["cp"] == "P" else "콜"
            sub_note = f"거래량이 OI의 {voi:.1f}배 ({'새 포지션 가능' if voi >= 1.0 else '기존 포지션 회전'}) · 규모 {_fmt_prem_short(tot_prem)} · {base_str}"
            if is_inv:
                sub_note += " · 인버스 ETF"
            row_d = {
                "tk": tk, "grade": grade, "score": score,
                "skew_str": f"{dom_pct}% {'풋' if is_put_dom else '콜'}",
                "base_str": base_str,
                "top_str": f"{best['exp']} {best['k']:g}{cp_kr} · {best['dte']}일 · OTM {best['otm']}%",
                "conc": conc, "voi": voi, "big_dir": "-",
                "dir_est": dir_est, "dir_col": dir_col, "sub_note": sub_note,
            }
            if is_put_dom:
                put_rows.append(row_d)
            else:
                call_rows.append(row_d)
        except Exception:
            continue

    try:
        with open(CP_BASE_PATH, "w", encoding="utf-8") as _f:
            json.dump(base_hist, _f, ensure_ascii=False)
    except Exception:
        pass

    put_rows.sort(key=lambda x: x["score"], reverse=True)
    call_rows.sort(key=lambda x: x["score"], reverse=True)
    if not put_rows and not call_rows:
        return f"🚦 강한 풋·콜 스캔 (A·B 등급, 만기 14일 내)\n\n현재 조건에 맞는 종목이 없습니다. (C {c_cnt}종목 생략)", None

    p_str = ", ".join(f"{r['tk']}({r['grade']})" for r in put_rows) or "없음"
    c_str = ", ".join(f"{r['tk']}({r['grade']})" for r in call_rows) or "없음"
    txt = (
        f"🚦 강한 풋·콜 스캔 (A·B 등급, 만기 14일 내)\n"
        f"🔴 풋 쏠림: {p_str}\n"
        f"🟢 콜 쏠림: {c_str}\n"
        f"※ 거래 쏠림일 뿐 방향 확정 아님"
    )
    png_b = _render_strong_cp_png(put_rows, call_rows, checked, c_cnt, today_et)
    return txt, png_b

_LAST_ABSCAN_TS = 0.0

def auto_scan_strong_cp(token, chat_id):
    global _LAST_ABSCAN_TS
    try:
        from datetime import datetime, timezone, timedelta
        kst = datetime.now(timezone(timedelta(hours=9)))
        hm = kst.hour * 100 + kst.minute
        wd = kst.weekday()
        in_session = ((wd in (0, 1, 2, 3, 4) and hm >= 2330) or (wd in (1, 2, 3, 4, 5) and hm <= 600))
        if not in_session:
            return
        now_ts = time.time()
        if now_ts - _LAST_ABSCAN_TS < 1800:
            return
        _LAST_ABSCAN_TS = now_ts
        txt, png_b = build_strong_cp_scan()
        if png_b:
            send_photo_bytes(token, chat_id, png_b, txt)
        elif "쏠림:" in txt:
            send_msg(token, chat_id, txt)
    except Exception:
        pass


_SEEN_BIG_TICKS = set()

def build_moomoo_big_ticks_alert(manual=False):
    import socket as _sk_bt
    tks = ["SOXL", "NVDA", "TSLA", "SPY", "QQQ", "MU", "AMD"]
    try:
        with _sk_bt.create_connection(("127.0.0.1", 11111), timeout=0.3):
            pass
    except Exception:
        return "⚠️ 무무 OpenD(11111 포트)가 꺼져 있어 대량 틱 스캔을 건너뜁니다." if manual else ""

    qctx = None
    hits = []
    try:
        from moomoo import OpenQuoteContext, SubType, RET_OK
        qctx = OpenQuoteContext(host="127.0.0.1", port=11111)
        syms = [f"US.{t}" for t in tks]
        qctx.subscribe(syms, [SubType.TICKER, SubType.ORDER_BOOK], subscribe_push=False)
        for tk in tks:
            sym = f"US.{tk}"
            try:
                rt, dft = qctx.get_rt_ticker(sym, num=150)
                if rt == RET_OK and dft is not None and not dft.empty:
                    for _, r in dft.iterrows():
                        tv = float(r.get("turnover", 0) or 0)
                        if tv >= 100_000:
                            tm = str(r.get("time", ""))[-8:]
                            px = float(r.get("price", 0) or 0)
                            td = str(r.get("ticker_direction", "")).upper()
                            k_id = f"{tk}|{tm}|{px}|{int(tv)}"
                            if (not manual) and (k_id in _SEEN_BIG_TICKS):
                                continue
                            _SEEN_BIG_TICKS.add(k_id)
                            if len(_SEEN_BIG_TICKS) > 500:
                                _SEEN_BIG_TICKS.clear()
                            emo = "🟢매수긁기" if "BUY" in td else ("🔴매도투매" if "SELL" in td else "⚪체결")
                            hits.append(f"• {tk} {emo} ${px:,.2f} · {_fmt_prem_short(tv)} ({tm})")
            except Exception:
                pass
            try:
                rb, dfb = qctx.get_order_book(sym, num=10)
                if rb == RET_OK and isinstance(dfb, dict):
                    bids = dfb.get("Bid") or []; asks = dfb.get("Ask") or []
                    bt = sum(float(x[1]) for x in bids[:10] if len(x) >= 2)
                    at = sum(float(x[1]) for x in asks[:10] if len(x) >= 2)
                    if bt > 0 and at > 0:
                        if bt / at >= 2.5:
                            hits.append(f"• 🧱 {tk} 매수벽 {bt/at:.1f}배 우위 (Bid {int(bt):,} vs Ask {int(at):,})")
                        elif at / bt >= 2.5:
                            hits.append(f"• 🧱 {tk} 매도벽 {at/bt:.1f}배 우위 (Ask {int(at):,} vs Bid {int(bt):,})")
            except Exception:
                pass
    except Exception as _ebt:
        return f"대량 틱 스캔 오류: {_ebt}" if manual else ""
    finally:
        if qctx:
            try: qctx.close()
            except Exception: pass

    if not hits:
        return "🐋 무무 $100K+ 대량 틱·호가벽 특이사항 없음" if manual else ""
    return "🐋 *[무무 실시간 $100K+ 대량 틱 · 호가벽 경보]*\n\n" + "\n".join(hits[:15])

_LAST_BIGTICK_TS = 0.0

def auto_scan_moomoo_big_ticks(token, chat_id):
    global _LAST_BIGTICK_TS
    try:
        from datetime import datetime, timezone, timedelta
        kst = datetime.now(timezone(timedelta(hours=9)))
        hm = kst.hour * 100 + kst.minute
        wd = kst.weekday()
        in_session = ((wd in (0, 1, 2, 3, 4) and hm >= 2330) or (wd in (1, 2, 3, 4, 5) and hm <= 600))
        if not in_session:
            return
        now_ts = time.time()
        if now_ts - _LAST_BIGTICK_TS < 120:
            return
        _LAST_BIGTICK_TS = now_ts
        msg = build_moomoo_big_ticks_alert(manual=False)
        if msg:
            send_msg(token, chat_id, msg)
    except Exception:
        pass

def main():
    token, my_chat_id = load_cfg()
    set_bot_commands(token)
    offset = 0
    last_sheet_check = 0
    last_auto_collect = 0
    print("🤖 OptionHub Telegram Bot & Inline Menu started!")
    while True:
        try:
            now = time.time()
            if now - last_auto_collect >= 120:
                auto_collect_big_flows(token, my_chat_id)
                auto_scan_option_whales(token, my_chat_id)
                auto_collect_daily_oi(token, my_chat_id)
                auto_send_morning_briefing(token, my_chat_id)
                import threading as _th_bg
                _th_bg.Thread(target=auto_scan_intraday_option_changes, args=(token, my_chat_id), daemon=True).start()
                _th_bg.Thread(target=auto_scan_big_flows_summary, args=(token, my_chat_id), daemon=True).start()
                _th_bg.Thread(target=auto_scan_moomoo_cp_dominance, args=(token, my_chat_id), daemon=True).start()
                _th_bg.Thread(target=auto_scan_strong_cp, args=(token, my_chat_id), daemon=True).start()
                _th_bg.Thread(target=auto_scan_moomoo_big_ticks, args=(token, my_chat_id), daemon=True).start()
                last_auto_collect = now
            if now - last_sheet_check >= 300:
                check_sheet_review(token, my_chat_id)
                check_sheet_geeks(token, my_chat_id)
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
                txt = msg.get("text", "") or msg.get("caption", "")
                cid = str(msg.get("chat", {}).get("id", ""))
                if cid == my_chat_id:
                    if msg.get("photo") or (msg.get("document") and str(msg["document"].get("mime_type", "")).startswith("image/")):
                        save_forwarded_photo(token, cid, msg)
                    if txt:
                        handle_command(token, cid, txt)
        except Exception as e:
            print("Loop err:", e)
            time.sleep(5)


if __name__ == "__main__":
    main()