import re
import time
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import os, json, math, urllib.request, urllib.parse, re
import streamlit.components.v1 as components


def parse_prem_usd(p_str):
    s = str(p_str).replace("$", "").replace(",", "").strip().upper()
    try:
        if s.endswith("M"): return float(s[:-1]) * 1_000_000
        if s.endswith("K"): return float(s[:-1]) * 1_000
        return float(s)
    except Exception:
        return 0.0

@st.cache_data(ttl=60)
def load_multisource_sheet():
    sheet_id = "1_FWy_B9a6t1txau06PbeEMy9S9B1GsMgWZLGfMmMG7w"
    rows_out = []
    for sh in ["전체", "ES"]:
        try:
            url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv&sheet=" + urllib.parse.quote(sh)
            df = pd.read_csv(url)
            for _, r in df.iterrows():
                sec = str(r.get("Section (섹션)", sh)).strip()
                tk = str(r.get("Ticker (티커)", "")).strip().upper()
                if not tk or tk == "NAN": continue
                tm = str(r.get("Time (시각)", "")).strip()
                stk = str(r.get("Strike Price (행사가)", "")).strip()
                cp = str(r.get("Option Type (구분)", "")).strip()
                exp = str(r.get("Expiration Date (만기일)", "")).strip()
                pr = str(r.get("Premium (프리미엄)", "")).strip()
                ch = str(r.get("Characteristics (주문유형/특징)", "")).strip()
                rows_out.append({"섹션/소스": sec, "티커": tk, "시각": tm, "구분": cp, "행사가": stk, "만기일": exp, "프리미엄": pr, "특징": ch})
        except Exception:
            pass
    return pd.DataFrame(rows_out)


@st.cache_data(ttl=60)
def load_ai_notes_sheet():
    sheet_id = "1_FWy_B9a6t1txau06PbeEMy9S9B1GsMgWZLGfMmMG7w"
    try:
        url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv&sheet=" + urllib.parse.quote("AI노트_뉴스시황")
        df = pd.read_csv(url)
        return df.fillna("")
    except Exception:
        return pd.DataFrame()

WL_PATH = os.path.expanduser("~/.optionhub_watchlist.json")
JOURNAL_PATH = os.path.expanduser("~/.optionhub_journal.json")


OI_PATH = os.path.expanduser("~/.optionhub_oi_history.json")
BIG_FLOWS_PATH = os.path.expanduser("~/.optionhub_big_flows.json")

def calc_zero_gamma(df_gex, spot=0.0):
    if isinstance(df_gex, list):
        df_gex = pd.DataFrame(df_gex)
    if df_gex is None or not hasattr(df_gex, "empty") or df_gex.empty or len(df_gex) < 2 or "GEX($M)" not in df_gex.columns or "행사가" not in df_gex.columns:
        return None
    d = df_gex.sort_values("행사가").reset_index(drop=True)
    flips = []
    for i in range(len(d) - 1):
        g1, g2 = float(d.loc[i, "GEX($M)"]), float(d.loc[i + 1, "GEX($M)"])
        k1, k2 = float(d.loc[i, "행사가"]), float(d.loc[i + 1, "행사가"])
        if (g1 < 0 and g2 > 0) or (g1 > 0 and g2 < 0):
            zg = k1 + (0.0 - g1) * (k2 - k1) / (g2 - g1)
            flips.append(round(zg, 2))
    if not flips:
        return None
    if spot and spot > 0:
        return min(flips, key=lambda x: abs(x - spot))
    return flips[len(flips) // 2]

def bs_greeks(S, K, T, r, sigma, is_call=True):
    """Black-Scholes Delta & Gamma 계산"""
    if S <= 0 or K <= 0 or T <= 0 or sigma <= 0:
        return 0.0, 0.0
    try:
        sqrtT = math.sqrt(T)
        d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * sqrtT)
        pdf = math.exp(-0.5 * d1 * d1) / math.sqrt(2.0 * math.pi)
        cdf = 0.5 * (1.0 + math.erf(d1 / math.sqrt(2.0)))
        delta = cdf if is_call else (cdf - 1.0)
        gamma = pdf / (S * sigma * sqrtT)
        return delta, gamma
    except Exception:
        return 0.0, 0.0

def fetch_yahoo_oi(ticker):
    """yfinance로 실시간 옵션 체인(OI) + Spot + Black-Scholes Delta/Gamma/GEX/DEX 수집"""
    try:
        import yfinance as yf
        from datetime import datetime
        t = yf.Ticker({"SPX":"^SPX","NDX":"^NDX","VIX":"^VIX","RUT":"^RUT"}.get(ticker.upper(), ticker))
        exps = t.options
        if not exps:
            return [], 0.0, "만기 데이터를 찾을 수 없습니다."
        spot = 0.0
        try:
            spot = float(t.fast_info.get("lastPrice", 0) or 0)
        except Exception:
            pass
        if spot <= 0:
            try:
                hist = t.history(period="1d")
                if not hist.empty:
                    spot = float(hist["Close"].iloc[-1])
            except Exception:
                pass

        now_dt = datetime.now()
        rows = []
        _week_exps = []
        for _ex in exps:
            try:
                if (datetime.strptime(_ex, "%Y-%m-%d").date() - now_dt.date()).days <= 7:
                    _week_exps.append(_ex)
            except Exception:
                pass
        _target_exps = _week_exps if len(_week_exps) >= 3 else exps[:3]
        for exp in _target_exps[:7]:
            try:
                exp_dt = datetime.strptime(exp, "%Y-%m-%d")
                T = max((exp_dt - now_dt).days / 365.0, 1.0 / 365.0)
            except Exception:
                T = 7.0 / 365.0
            chain = t.option_chain(exp)
            def safe_int(v):
                return 0 if pd.isna(v) else int(v)
            def safe_iv(v):
                return 0.30 if pd.isna(v) or float(v) <= 0.01 else float(v)
            for is_c, df_side in [(True, chain.calls), (False, chain.puts)]:
                for _, r in df_side.iterrows():
                    oi = safe_int(r.get("openInterest"))
                    vol = safe_int(r.get("volume"))
                    if oi > 0 or vol > 0:
                        K = float(r["strike"])
                        iv = safe_iv(r.get("impliedVolatility"))
                        s_ref = spot if spot > 0 else K
                        delta, gamma = bs_greeks(s_ref, K, T, 0.045, iv, is_call=is_c)
                        sign = 1.0 if is_c else -1.0
                        gex_m = (sign * gamma * oi * 100.0 * (s_ref ** 2) * 0.01) / 1_000_000.0
                        dex_m = (delta * oi * 100.0 * s_ref) / 1_000_000.0
                        _lp = float(r.get("lastPrice") or 0) if not pd.isna(r.get("lastPrice")) else 0.0
                        _bp = float(r.get("bid") or 0) if not pd.isna(r.get("bid")) else 0.0
                        _ap = float(r.get("ask") or 0) if not pd.isna(r.get("ask")) else 0.0
                        _mp = ((_bp + _ap) / 2.0) if (_bp > 0 and _ap > 0) else _lp
                        _prem_usd = round(vol * _mp * 100.0, 1)
                        _dte_days = max(int(round(T * 365)), 0)
                        _vol_oi_r = round(vol / oi, 2) if oi > 0 else float(vol > 0)
                        if abs(K - s_ref) / max(s_ref, 1.0) <= 0.02:
                            _mny = "ATM"
                        elif (is_c and K > s_ref) or ((not is_c) and K < s_ref):
                            _mny = "OTM"
                        else:
                            _mny = "ITM"
                        rows.append({
                            "만기": exp,
                            "DTE": _dte_days,
                            "구분": "Call" if is_c else "Put",
                            "행사가": K,
                            "Moneyness": _mny,
                            "OI": oi,
                            "거래량": vol,
                            "Vol/OI": _vol_oi_r,
                            "프리미엄($)": _prem_usd,
                            "IV(%)": round(iv * 100, 1),
                            "Delta": round(delta, 3),
                            "Gamma": round(gamma, 4),
                            "GEX($M)": round(gex_m, 3),
                            "DEX($M)": round(dex_m, 3),
                        })
        return rows, round(spot, 2), "OK"
    except ImportError:
        return [], 0.0, "NO_YFINANCE"
    except Exception as e:
        return [], 0.0, str(e)

WL_PATH = os.path.expanduser("~/.optionhub_watchlist.json")
JOURNAL_PATH = os.path.expanduser("~/.optionhub_journal.json")


OI_PATH = os.path.expanduser("~/.optionhub_oi_history.json")

def load_json_file(p, default):
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return default

def save_json_file(p, data):
    try:
        with open(p, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def load_tg_config():
    cfg_path = os.path.expanduser('~/.telegram_config.json')
    if os.path.exists(cfg_path):
        try:
            with open(cfg_path, 'r', encoding='utf-8') as f:
                c = json.load(f)
                return c.get('token', ''), c.get('chat_id', '')
        except Exception:
            pass
    return os.environ.get('TG_BOT_TOKEN', ''), os.environ.get('TG_CHAT_ID', '')

def send_telegram_msg(token, chat_id, text):
    if not token or not chat_id:
        return False, '토큰 또는 채팅 ID가 설정되지 않았습니다.'
    url = f'https://api.telegram.org/bot{token}/sendMessage'
    # 4000자 단위로 자동 분할 전송 (내용 누락 없이 전체 발송)
    chunks = [text[i:i+3800] for i in range(0, len(text), 3800)]
    for chunk in chunks:
        payload = json.dumps({'chat_id': chat_id, 'text': chunk, 'disable_web_page_preview': True}).encode('utf-8')
        req = urllib.request.Request(url, data=payload, headers={'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status != 200:
                    return False, f'HTTP {resp.status}'
        except Exception as e:
            return False, str(e)
    return True, f'전송 완료 ({len(chunks)}건 메시지)'


st.set_page_config(page_title="OptionHub - InsiderFinance All-in-One", page_icon="📈", layout="wide")

st.markdown("""
<style>
    .main { background-color: #0b0e14; }
    .kpi-row { display: flex; flex-wrap: wrap; gap: 6px; margin: 15px 0; }
    .kpi-box { background: #080c14; border-radius: 4px; padding: 8px 6px; text-align: center; border: 1px solid #232733; flex: 1; min-width: 75px; }
    .kpi-title { font-size: 10px; color: #787b86; text-transform: uppercase; margin-bottom: 4px; font-weight: 600; }
    .kpi-value { font-size: 14px; font-weight: 700; color: #ffffff; }
    .kpi-green { color: #00e676 !important; }
    .kpi-red { color: #f23645 !important; }
    .summary-badge { display: inline-block; background: #161b26; border: 1px solid #2962ff; color: #90caf9; border-radius: 12px; padding: 4px 10px; font-size: 11px; margin: 2px 4px 10px 0; font-weight: 600; }
    .date-badge { display: inline-block; background: #1f2937; border: 1px solid #10b981; color: #10b981; border-radius: 6px; padding: 2px 8px; font-size: 12px; font-weight: 700; margin-left: 8px; }
    .flow-card { background: #11141d; border-radius: 8px; border: 1px solid #1e222d; padding: 18px; margin-bottom: 25px; }
    .flow-table { width: 100%; border-collapse: collapse; font-size: 12px; margin-top: 10px; }
    .flow-table th { background: #161b26; color: #787b86; padding: 8px 6px; text-align: center; border-bottom: 1px solid #232733; font-weight: 600; font-size: 10px; }
    .flow-table td { padding: 10px 6px; text-align: center; border-bottom: 1px solid #1a1e29; color: #d1d4dc; }
    .badge-call { color: #00e676; font-weight: 700; }
    .badge-put { color: #f23645; font-weight: 700; }
    .heat-bar { border-left: 3px solid #ff9800; padding-left: 6px; font-weight: 700; color: #ff9800; }
    .theme-card { background: #12151e; border-left: 4px solid #f23645; border-radius: 4px; padding: 14px; margin-bottom: 12px; border: 1px solid #1e222d; }
    .theme-card-green { border-left-color: #00e676 !important; }
    .theme-title { font-size: 15px; font-weight: 700; color: #ffffff; margin-bottom: 4px; }
    .theme-sub { font-size: 12px; color: #848e9c; margin-bottom: 8px; }
    .theme-body { font-size: 13px; color: #d1d4dc; line-height: 1.6; }
    .ainote-card { background: #151924; border-left: 4px solid #f23645; border-radius: 6px; padding: 14px; margin-bottom: 12px; border: 1px solid #232733; }
    .ainote-card-green { border-left-color: #00e676 !important; }
    .strategy-card { background: #161b26; border-left: 4px solid #00e676; padding: 14px; border-radius: 6px; margin-bottom: 12px; border: 1px solid #232733; }
    .strategy-card-red { border-left-color: #f23645 !important; }
    .news-box { background: #121620; border-left: 3px solid #00e676; padding: 12px 14px; margin-bottom: 10px; border-radius: 4px; border: 1px solid #1e222d; }
    .chart-analysis { background: #131722; border-left: 4px solid #2962ff; padding: 14px; border-radius: 4px; margin-top: 15px; border: 1px solid #232733; }
    .morning-banner { background: linear-gradient(90deg, #1e1b4b 0%, #0f172a 100%); border: 1px solid #3b82f6; border-radius: 8px; padding: 14px 18px; margin-bottom: 20px; }
    .moonshot-card { background: #131722; border: 1px solid #2a2e39; border-radius: 6px; padding: 12px; margin-bottom: 10px; }
    .gex-card { background: #111827; border: 1px solid #374151; border-radius: 6px; padding: 14px; text-align: center; }
</style>
""", unsafe_allow_html=True)

MENU_ITEMS = [
    "📝 오늘의 종합평",
    "🎯 AI GEX 분석",
    "🔥 Top Ticker + 차트/P&L",
    "📊 OI(미결제약정) 수집",
    "🎯 실발·OI 매집 스캐너",
    "⭐ 내 관심종목",
    "🔍 조건별 스캐너",
    "📆 만기 집중도(OPEX)",
    "🗓️ 거시·실적 캘린더",
    "📈 포착 사후 추적",
    "🔗 멀티 소스 검증",
    "🚀 Top 10 문샷",
    "📅 5일 수급 & GEX",
    "⚡ AI Plays & Note",
    "📊 Options Top 차트",
    "🗺️ 히트맵 & 테마",
    "📰 뉴스 (7선)",
    "⚡ 무무 실시간 차트",
    "📌 다음 주·원월 포지션",
    "📰 대형 옵션 체결",
    "🎯 행사가별·동반 체결",
    "📬 인사이더 파이낸셜",
    "📅 구글 캘린더",
    "📚 실피 자료실",
    "📂 옵션자료실"
]
MENU_CFG_PATH = os.path.expanduser("~/.optionhub_menu_cfg.json")
_menu_cfg = load_json_file(MENU_CFG_PATH, {"order": list(MENU_ITEMS), "hidden": [], "aliases": {}})
_saved_order = [m for m in _menu_cfg.get("order", MENU_ITEMS) if m in MENU_ITEMS]
for _m in MENU_ITEMS:
    if _m not in _saved_order:
        _saved_order.append(_m)
_hidden_set = set(_menu_cfg.get("hidden", []))
_aliases = _menu_cfg.get("aliases", {})
_visible_menus = [_m for _m in _saved_order if _m not in _hidden_set] or list(MENU_ITEMS)

st.sidebar.title("⚙️ OptionHub")
st.sidebar.success("🟢 실시간 데이터 연동 중 (11/12 반영)")
nav_menu = st.sidebar.radio(
    "📌 메뉴 이동",
    _visible_menus,
    index=0,
    format_func=lambda x: _aliases.get(x, x),
)
with st.sidebar.expander("🛠️ 메뉴 순서·이름 편집 (상하 수정)", expanded=False):
    _sel_ed_m = st.selectbox("편집할 메뉴", _saved_order, format_func=lambda x: _aliases.get(x, x), key="m_ed_sel")
    _mc1, _mc2 = st.columns(2)
    _idx_m = _saved_order.index(_sel_ed_m)
    if _mc1.button("⬆️ 위로", use_container_width=True, key="m_up") and _idx_m > 0:
        _saved_order[_idx_m - 1], _saved_order[_idx_m] = _saved_order[_idx_m], _saved_order[_idx_m - 1]
        _menu_cfg["order"] = _saved_order
        save_json_file(MENU_CFG_PATH, _menu_cfg)
        st.rerun()
    if _mc2.button("⬇️ 아래로", use_container_width=True, key="m_dn") and _idx_m < len(_saved_order) - 1:
        _saved_order[_idx_m + 1], _saved_order[_idx_m] = _saved_order[_idx_m], _saved_order[_idx_m + 1]
        _menu_cfg["order"] = _saved_order
        save_json_file(MENU_CFG_PATH, _menu_cfg)
        st.rerun()
    _new_alias = st.text_input("표시 이름 수정", value=_aliases.get(_sel_ed_m, _sel_ed_m), key=f"m_alias_in_{_sel_ed_m}")
    _is_hid = st.checkbox("이 메뉴 숨기기", value=(_sel_ed_m in _hidden_set), key=f"m_hid_chk_{_sel_ed_m}")
    _sv1, _sv2 = st.columns(2)
    if _sv1.button("💾 저장", use_container_width=True, key="m_save_btn"):
        if _new_alias.strip() and _new_alias.strip() != _sel_ed_m:
            _aliases[_sel_ed_m] = _new_alias.strip()
        else:
            _aliases.pop(_sel_ed_m, None)
        if _is_hid:
            _hidden_set.add(_sel_ed_m)
        else:
            _hidden_set.discard(_sel_ed_m)
        _menu_cfg["order"] = _saved_order
        _menu_cfg["hidden"] = list(_hidden_set)
        _menu_cfg["aliases"] = _aliases
        save_json_file(MENU_CFG_PATH, _menu_cfg)
        st.rerun()
    if _sv2.button("🔄 초기화", use_container_width=True, key="m_reset_btn"):
        save_json_file(MENU_CFG_PATH, {"order": list(MENU_ITEMS), "hidden": [], "aliases": {}})
        st.rerun()

if nav_menu == "📝 오늘의 종합평":
    # 상단 1분 모닝 브리핑 배너 (2026-11-11 최신 반영)
    st.markdown("""
    <div class='morning-banner'>
        <div style='display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;'>
            <span style='font-size:16px; font-weight:800; color:#60a5fa;'>☀️ AI 옵션 모닝 1분 핵심 브리핑 (장전 체크포인트)</span>
            <span style='background:#2563eb; color:white; font-size:11px; font-weight:700; padding:2px 8px; border-radius:4px;'>2026-11-13 최신본</span>
        </div>
        <div style='display:grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 12px; font-size:13px; color:#e2e8f0; line-height:1.5;'>
            <div style='background:rgba(239,68,68,0.1); border-left:3px solid #ef4444; padding:8px 10px; border-radius:4px;'>
                <strong>🔴 반도체 반등 속 풋 헷지 지속 (MU·AMD)</strong><br>
                MU($24.3M 800 Put), AMD($6.2M 600 Put) 등 주가 반등에도 기관 하방 방어 풋 집중. NVDA는 이사회 조사 및 목표가 하향($200) 여파.
            </div>
            <div style='background:rgba(16,185,129,0.1); border-left:3px solid #10b981; padding:8px 10px; border-radius:4px;'>
                <strong>🟢 주도주 선별 콜 집중 (META·INTC·TSLA)</strong><br>
                META($31M 750 Call), INTC($31M 50 Call), TSLA($4.2M 410 Call) 등 개별 강세 종목에 대규모 상방 포지셔닝 유입.
            </div>
            <div style='background:rgba(245,158,11,0.1); border-left:3px solid #f59e0b; padding:8px 10px; border-radius:4px;'>
                <strong>🚀 SNDK·KGC·BW 콜 스윕 & 주요 뉴스</strong><br>
                SNDK 9건($6.8M 스윕), KGC 11.2x 모멘텀 콜 집중. 앤스로픽 IPO 로드쇼($70~$78) 및 코스트코 주당 $30 특별배당 발표.
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    DEFAULT_TIDE_BRIEF = {
        "updated": "2026-11-12 06:06 (텔레그램 브리핑)",
        "tide": "누적 $+482M · 후반30분 $-42M · 추세 bearish_steady",
        "flows": [
            {"tk": "MU", "net": "+85.6M", "dir": "콜 순매수"},
            {"tk": "NVDA", "net": "+37.0M", "dir": "콜 순매수"},
            {"tk": "TSLA", "net": "+34.3M", "dir": "콜 순매수"},
            {"tk": "SNDK", "net": "+34.3M", "dir": "콜 순매수"},
            {"tk": "CRWV", "net": "+29.5M", "dir": "콜 순매수"},
            {"tk": "SOXL", "net": "+25.3M", "dir": "콜 순매수"},
            {"tk": "NBIS", "net": "-23.1M", "dir": "풋 순매수"},
            {"tk": "AAPL", "net": "+22.1M", "dir": "콜 순매수"},
        ],
        "warnings": [
            {"tk": "NVDA", "tag": "커버드콜(콜ask45%)"},
            {"tk": "AAPL", "tag": "OI역행⚠(풋ask56%)"},
            {"tk": "INTC", "tag": "신규하방(풋ask99%)"},
            {"tk": "MSFT", "tag": "진짜매수(콜ask99%)"},
        ],
        "dir_note": "겉은 콜 순유입(+$482M)이나 후반 30분 풋 역전(-$42M)·전원 Short Gamma(QQQ $690 / SPY $758 / SOXX $155 방어선)로 하방 가속 리스크 경계",
        "morning_head": "SPY·QQQ·SMH 주간 1σ 상단 초과 소진(추격 여지 제한) · Tide bullish(25) vs 추세 bearish_reversal",
        "morning_bull": [
            {"tk": "SMH", "desc": "반도체 ETF [중]"},
            {"tk": "HOOD", "desc": "온라인 증권 [약]"},
            {"tk": "IBIT", "desc": "비트코인 ETF [약]"},
            {"tk": "CE", "desc": "특수화학 [약]"},
        ],
        "morning_bear": [
            {"tk": "MSFT", "desc": "시장 역행★ [중]"},
            {"tk": "GEV", "desc": "전력장비 [약]"},
            {"tk": "AMKR", "desc": "반도체 패키징 [약]"},
            {"tk": "QQQ", "desc": "콜유출·풋유입 [약]"},
        ],
        "darkpool_note": "정규장 섞인 MSFT($2.67억)와 거래량 비중 급증 SIX(167.9%)·EXEL(67.0%)·DKNG(34.4%)·XOM(24.0%)·WMT(15.9%)만 관찰 대상",
    }
    tide_cache = load_json_file(os.path.expanduser("~/.optionhub_tide_brief.json"), DEFAULT_TIDE_BRIEF)
    if not (tide_cache.get("tide") or tide_cache.get("flows")):
        tide_cache = DEFAULT_TIDE_BRIEF
    if tide_cache.get("tide") or tide_cache.get("flows") or tide_cache.get("warnings"):
        tide_str = tide_cache.get("tide", "-")
        flows_html = " · ".join([f"<span style='color:{'#34d399' if '콜' in x.get('dir','') else '#f87171'}; font-weight:700;'>{x['tk']} {x['net']}</span>" for x in tide_cache.get("flows", [])[:8]])
        warn_html = " · ".join([f"<span style='background:rgba(245,158,11,0.18); color:#fbbf24; padding:1px 6px; border-radius:4px; font-size:12px;'>{w['tk']}: {w['tag']}</span>" for w in tide_cache.get("warnings", [])[:6]])
        dir_note = tide_cache.get("dir_note", "")
        m_head = tide_cache.get("morning_head", "")
        m_bull = " · ".join([f"<span style='color:#34d399; font-weight:700;'>{x['tk']}</span>({x['desc']})" for x in tide_cache.get("morning_bull", [])])
        m_bear = " · ".join([f"<span style='color:#f87171; font-weight:700;'>{x['tk']}</span>({x['desc']})" for x in tide_cache.get("morning_bear", [])])
        dp_note = tide_cache.get("darkpool_note", "")
        tk_items = tide_cache.get("tickers", {})
        tk_html = " · ".join([
            f"<span style='background:rgba(56,189,248,0.12); padding:1px 6px; border-radius:4px; font-size:12px;'><strong>{k}</strong>({v.get('spot','')}) {v.get('summary','')}</span>"
            for k, v in list(tk_items.items())[:8]
        ])
        st.markdown(f"""
    <div style='background:#131722; border:1px solid #2a2e39; border-left:4px solid #38bdf8; border-radius:8px; padding:10px 14px; margin-bottom:14px; font-size:13px; color:#e2e8f0;'>
      <div style='display:flex; justify-content:space-between; margin-bottom:6px;'>
        <span><strong style='color:#38bdf8;'>🌊 Market Tide & 데일리 브리핑</strong> &nbsp;|&nbsp; {tide_str}</span>
        <span style='color:#94a3b8; font-size:11px;'>갱신: {tide_cache.get('updated', '-')}</span>
      </div>
      {f"<div style='margin-bottom:5px;'><strong>자금 TOP:</strong> {flows_html}</div>" if flows_html else ""}
      {f"<div style='margin-bottom:5px;'><strong>⚠️ OI·커버드콜 검증:</strong> {warn_html}</div>" if warn_html else ""}
      {f"<div style='margin-bottom:4px;'><strong>🟢 반등 주목:</strong> {m_bull}</div>" if m_bull else ""}
      {f"<div style='margin-bottom:4px;'><strong>🔴 약세 주목:</strong> {m_bear}</div>" if m_bear else ""}
      {f"<div style='margin-bottom:4px; color:#cbd5e1; font-size:12px;'>🌅 <strong>아침 요약:</strong> {m_head}</div>" if m_head else ""}
      {f"<div style='margin-bottom:4px; color:#94a3b8; font-size:12px;'>🌑 <strong>다크풀:</strong> {dp_note}</div>" if dp_note else ""}
      {f"<div style='margin-bottom:4px;'><strong>📌 개별 종목 요약:</strong> {tk_html}</div>" if tk_html else ""}
      {f"<div style='color:#cbd5e1; font-size:12px;'>💡 {dir_note}</div>" if dir_note else ""}
    </div>
    """, unsafe_allow_html=True)

    with st.expander("🔬 반도체 기본군 (SOXX · SMH · SOXS · SOXL) 개폐·OI 핵심 정리", expanded=True):
        st.caption("기준: 11/11 ET 마감 확정분 (전달된 텔레그램 표·텍스트 요약)")
        semi_note_txt = tide_cache.get("semi_note", "")
        if not semi_note_txt:
            semi_note_txt = (
                "반도체 4종 · 11/12 ET 장전\n"
                "• SOXX 11/20 125P 매수·140P 매도 각 7,470계약 동반. 140P는 OI +2,206과 당일 청산 기록이 공존. 12월 155P는 신규 풋 매수 분류.\n"
                "• SMH 380P 매수·295P 매도 신규 방어 후보와 385P·285P 매도가 공존. 630P 4,000 중 청산 ≥3,998. 6월 550C는 매수 표기·개폐 보류.\n"
                "• SOXS 47C +573·42.5P +562. 69C는 일중 매수·매도 신규가 함께 확인.\n"
                "• SOXL 60P +2,403·55P -4,839·60C 두 만기 감소. 11/27 100C 매수 3,312 중 BTC ≥1,299."
            )
        st.info(semi_note_txt)
        semi_rows = [
            {"종목": "SOXX ($151.24)", "핵심 체결": "125P 청산(-3,525) + 140P SELL(+2,206) | 160C(+4,665)", "해석": "125P→140P 하방 지지 상향 · 160C 단기 저항"},
            {"종목": "SMH ($489.50)", "핵심 체결": "380P BTO + 295P STO (각 1만계약) | 385/285P STO | 630P 청산(-4,000)", "해석": "대부분 동시 체결 풋 스프레드·헤지 롤링 (단독 폭락 베팅 아님)"},
            {"종목": "SOXS ($48.90)", "핵심 체결": "69C(+2,552, 일중 BTO≥672·STO≥448) | 47C(+573) | 42.5P(+562)", "해석": "단기 69C 양방향 혼재 · 47C/42.5P 소폭 유입"},
            {"종목": "SOXL ($60.95)", "핵심 체결": "60C 청산(-2,253/-2,304) | 60P(+2,403) | 55P 청산(-4,839) | 11/27 100C BTC≥1,299(-2,819)", "해석": "단기 60C 차익+60P 헤지, 위쪽 100C 매도 저항은 BTC로 일부 해제"},
        ]
        st.dataframe(pd.DataFrame(semi_rows), use_container_width=True, hide_index=True)
        photo_dir = os.path.expanduser("~/.optionhub_tg_photos")
        photo_list = []
        if os.path.isdir(photo_dir):
            photo_list = [os.path.join(photo_dir, x) for x in sorted(os.listdir(photo_dir), reverse=True) if x.endswith(".jpg")][:5]
        if not photo_list:
            semi_img_p = os.path.expanduser("~/.optionhub_semi_latest.jpg")
            if os.path.exists(semi_img_p):
                photo_list = [semi_img_p]
        if photo_list:
            st.markdown(f"**🖼️ 텔레그램 전달 표 갤러리 (최근 {len(photo_list)}장)**")
            cols_img = st.columns(2)
            for idx_i, p_img in enumerate(photo_list):
                with cols_img[idx_i % 2]:
                    st.image(p_img, use_container_width=True)


DAILY_REVIEW_2026_11_11 = """📊 [OptionHub 오늘의 종합평] 2026-11-11 (한국시간 11/12 장전)

1️⃣ 시장 총평: "지수·반도체 반등 속 기관은 철저한 하방 보험(Hedge) 유지"
• 10월 CPI 예상치 상회 및 매파적 연준 기조로 금리 경계감이 여전한 가운데, 반도체·소형주 주가가 단기 반등하자 기관들은 상방 추격 대신 '풋옵션 헷지 연장'을 선택했습니다.
• SPX에서는 8000 Put($77M, $39.4M, $37.5M 등) 대규모 풋 스플릿/블록이 쏟아졌고, 중소형주(IWM) 역시 5일 연속 극단적 풋 편중이 유지되고 있습니다.

2️⃣ 기관 수급의 핵심 특징 (양극화 장세)
• [반도체 풋 방어 vs 선별적 콜]
  - MU($24.3M 800 Put), AMD($6.2M 600 Put) 등 급등한 반도체 주도주에 대형 풋 헷지가 집중되었습니다.
  - 반면 INTC($31.0M 50 Call 블록, 85C 문샷 스윕), SNDK(9건, $6.8M 콜 스윕 집중)에는 공격적 상방 베팅이 유입되었습니다.
  - NVDA는 이사회 독립 조사 및 Baird 목표가 하향($500→$200) 여파 속에서도 장기 콜($175C/$150C)과 단기 거래가 공존하며 413K 스윕 볼륨 1위를 기록했습니다.
• [빅테크·소비재 선별 매수 (META · TSLA · AMZN)]
  - 커뮤니케이션·경기소비재 섹터 전반은 부진하지만, 기관 자금은 '확실한 주도주'에만 쏠렸습니다.
  - META($31.0M 750 Call + 다크풀 매집), TSLA($4.2M 410C + $6.1M 340C), AMZN(AWS 매출 +39.3%, 수주잔고 $5,780억 기반 꾸준한 콜 스윕)이 대표적입니다.

3️⃣ 테마·원자재·문샷 특이 동향
• 금·원자재·인프라: KGC(킨로스 골드, 평소 대비 11.2배 거래량 폭증, 0% Put), BW(6.0배, 0% Put), ACHR(5.3배, 0% Put)에 전량 콜옵션 매집이 포착되었습니다.
• 크립토·채굴주: IBIT $48 Call($63.4M 대형 스플릿), CIFR $9 Call($870K), IREN(43% OTM), RIOT(31% OTM) 등 고베타 자산 상방 베팅이 지속되었습니다.
• 단기 과열 경계: LITE는 급등 직후 $12.6M 750 Put(미결제약정 39배) 초단기 골든 스윕이 유입되어 단기 되돌림 주의가 필요합니다.

4️⃣ 오늘의 대응 전략 및 체크포인트
• [공격적 매수 유효] 다크풀 매집 + 콜 스윕이 일치하는 META, TSLA, AMZN 및 모멘텀 콜 집중 종목(SNDK, KGC, BW)
• [헷지·리스크 관리 필요] 단기 급등 후 대형 풋 헷지가 들어온 MU, AMD, LITE 및 목표가 하향 이슈가 있는 NVDA
• [주요 뉴스 촉매] 앤스로픽 IPO 로드쇼($70~$78, 첫날 개인 매수세 $2.5억 예상), 코스트코 주당 $30 특별배당($133억 규모)

🌐 대시보드 바로가기: http://132.226.3.145:8501"""



DAILY_METRICS_BY_DATE = {
    "2026-11-13": {
        "SNDK": {"trades": 6, "put_flow": "0%", "otm": "7% Sweep OTM", "contracts": "3K Sweep Contracts", "prem": "$2.5M Sweep Premium"},
        "VKTX": {"trades": 8, "put_flow": "0%", "otm": "2% Sweep OTM (7.8x)", "contracts": "4K Sweep Contracts", "prem": "$220K Sweep / $465K Total"},
        "CIFR": {"trades": 1, "put_flow": "0%", "otm": "38% Unusual OTM", "contracts": "8K Unusual Contracts", "prem": "$308K Unusual Premium"},
        "GNLX": {"trades": 1, "put_flow": "0%", "otm": "34% Unusual OTM", "contracts": "265 Unusual Contracts", "prem": "$12K Unusual Premium"},
        "RDW": {"trades": 1, "put_flow": "0%", "otm": "29% Unusual OTM", "contracts": "1K Unusual Contracts", "prem": "$16K Unusual Premium"},
        "CCC": {"trades": 6, "put_flow": "0%", "otm": "-3% Sweep OTM (6.7x)", "contracts": "7K Sweep Contracts", "prem": "$174K Sweep Premium"},
        "NIO": {"trades": 6, "put_flow": "100%", "otm": "15.5x Momentum", "contracts": "26K Total Contracts", "prem": "$292K Total Premium"},
        "SO": {"trades": 4, "put_flow": "100%", "otm": "13.6x Momentum", "contracts": "3K Total Contracts", "prem": "$415K Total Premium"},
    },
    "2026-11-11": {
        "SNDK": {"trades": 9, "put_flow": "12%", "otm": "31% Unusual OTM", "contracts": "6K Unusual Contracts", "prem": "$6.8M Sweep / $3.0M Unusual"},
        "KGC": {"trades": 11, "put_flow": "0%", "otm": "2% Sweep OTM (11.2x)", "contracts": "7K Contracts", "prem": "$1.2M Premium"},
        "BW": {"trades": 5, "put_flow": "0%", "otm": "46% Sweep OTM (6.0x)", "contracts": "10K Total Contracts", "prem": "$231K Total Premium"},
        "ACHR": {"trades": 5, "put_flow": "0%", "otm": "5.3x Momentum", "contracts": "8K Total Contracts", "prem": "$395K Total Premium"},
        "RIOT": {"trades": 2, "put_flow": "0%", "otm": "31% Unusual OTM", "contracts": "5K Unusual Contracts", "prem": "$54K Unusual / $696K Sweep"},
        "AMAT": {"trades": 1, "put_flow": "0%", "otm": "37% Unusual OTM", "contracts": "545 Unusual Contracts", "prem": "$11K Unusual Premium"},
        "META": {"trades": 1, "put_flow": "0%", "otm": "OTM Jan Call", "contracts": "1/3 of OI", "prem": "$31.0M Sweep"},
        "INTC": {"trades": 3, "put_flow": "0%", "otm": "ITM Block + 85C Moonshot", "contracts": "Large Stock Replacement", "prem": "$31.0M Top Prem"},
        "MU": {"trades": 2, "put_flow": "50%", "otm": "800P Hedge + 750C Sweep", "contracts": "Long-dated + Front-week", "prem": "$24.3M Top Prem"},
        "LITE": {"trades": 1, "put_flow": "100%", "otm": "Deep ITM 750 Put", "contracts": "39x OI", "prem": "$12.6M Golden Sweep"},
        "AMD": {"trades": 1, "put_flow": "100%", "otm": "600 Put Hedge", "contracts": "5x+ OI", "prem": "$6.2M Golden Sweep"},
        "TSLA": {"trades": 2, "put_flow": "0%", "otm": "410C + 340C", "contracts": "Ask-side Cluster", "prem": "$6.1M Block / $4.2M Sweep"},
        "NVDA": {"trades": 2, "put_flow": "0%", "otm": "175C (2027) + 150C (2028)", "contracts": "Long-dated Calls", "prem": "$8.3M Top Prem"},
        "SPX": {"trades": 9, "put_flow": "67%", "otm": "8000P Hedge + 7650C", "contracts": "Institutional Index", "prem": "$77.0M Top Prem"},
        "IBIT": {"trades": 1, "put_flow": "0%", "otm": "48 Call (2027-12-17)", "contracts": "Top Position Split", "prem": "$63.4M Split"},
    },
    "2026-11-10": {
        "SNDK": {"trades": 3, "put_flow": "0%", "otm": "21% Unusual OTM", "contracts": "401 Unusual Contracts", "prem": "$120K Unusual Premium"},
        "SMMT": {"trades": 1, "put_flow": "0%", "otm": "71% Unusual OTM", "contracts": "874 Unusual Contracts", "prem": "$22K Unusual Premium"},
        "BRBR": {"trades": 3, "put_flow": "0%", "otm": "27% Unusual OTM", "contracts": "4K Unusual Contracts", "prem": "$81K Unusual Premium"},
        "DBX": {"trades": 10, "put_flow": "100%", "otm": "23% Sweep OTM", "contracts": "4K Sweep Contracts", "prem": "$276K Sweep Premium"},
        "PEPG": {"trades": 6, "put_flow": "96%", "otm": "15% Sweep OTM", "contracts": "6K Sweep Contracts", "prem": "$287K Sweep Premium"},
        "GRAB": {"trades": 5, "put_flow": "100%", "otm": "10% Sweep OTM", "contracts": "22K Sweep Contracts", "prem": "$153K Sweep Premium"},
        "GRPN": {"trades": 3, "put_flow": "100%", "otm": "31.3x Momentum", "contracts": "3K Total Contracts", "prem": "$70K Total Premium"},
        "GFL": {"trades": 8, "put_flow": "0%", "otm": "11.0x Momentum", "contracts": "147K Total Contracts", "prem": "$2.4M Total Premium"},
        "NVDA": {"trades": 6, "put_flow": "100%", "otm": "4% OTM", "contracts": "27K Contracts", "prem": "$50.0M Top Prem"},
        "MU": {"trades": 2, "put_flow": "100%", "otm": "-32% ITM", "contracts": "1.1K Contracts", "prem": "$34.7M Top Prem"},
        "ASML": {"trades": 1, "put_flow": "0%", "otm": "Moderate OTM", "contracts": "730 Contracts", "prem": "$12.8M Top Prem"},
        "MSFT": {"trades": 1, "put_flow": "0%", "otm": "Near OTM", "contracts": "1.5K Contracts", "prem": "$12.9M Top Prem"},
        "SPX": {"trades": 10, "put_flow": "20%", "otm": "17% OTM", "contracts": "15K Contracts", "prem": "$338.5M Top Prem"},
    }
}

DEFAULT_FLOWS = [
    # ================= 2026-11-13 (최신 Evening Edge) =================
    ("2026-11-13", "BA", "03:19 PM", "Put", "• A", "2027-01-15", "-", "$230", "Top Pos", "-", "-", "-", "-", "BLOCK", "$30.9M", "52"),
    ("2026-11-13", "GOOG", "03:17 PM", "Put", "• A", "2027-01-15", "-", "$480", "Top Pos", "-", "-", "-", "-", "SPLIT", "$26.3M", "50"),
    ("2026-11-13", "MRVL", "01:50 PM", "Put", "• A", "2027-01-15", "-", "$145", "Top Pos", "-", "-", "-", "-", "SPLIT", "$19.0M", "49"),
    ("2026-11-13", "GLW", "03:10 PM", "Put", "• A", "2026-12-18", "-", "$200", "-", "-", "-", "-", "-", "SPLIT", "$18.3M", "46"),
    ("2026-11-13", "MU", "09:35 AM", "Put", "• A", "2027-03-19", "-", "$650", "-", "-", "-", "-", "-", "SWEEP", "$9.6M", "45"),
    ("2026-11-13", "GOOGL", "10:35 AM", "Call", "• A", "2027-12-17", "-", "$440", "Top Pos", "-", "-", "-", "-", "SPLIT", "$8.4M", "44"),
    ("2026-11-13", "NVDA", "09:34 AM", "Call", "• A", "2027-03-19", "-", "$250", "-", "-", "-", "-", "-", "SWEEP", "$7.9M", "43"),
    ("2026-11-13", "TSLA", "10:19 AM", "Put", "• A", "2026-12-11", "-", "$320", "Unusual", "-", "-", "-", "-", "GOLDEN SWEEP", "$2.6M", "48"),
    ("2026-11-13", "PCG", "10:05 AM", "Call", "• A", "2026-12-31", "-", "$15", "Top Pos", "-", "-", "-", "-", "BLOCK", "$1.2M", "42"),
    ("2026-11-13", "SNDK", "10:46 AM", "Call", "• A", "2026-11-20", "-", "$1000", "Unusual", "-", "-", "-", "-", "SWEEP", "$1.0M", "47"),
    ("2026-11-13", "SNDK", "10:13 AM", "Call", "• A", "2026-11-13", "-", "$850", "-", "-", "-", "-", "-", "SWEEP", "$671K", "44"),
    ("2026-11-13", "SNDK", "02:40 PM", "Call", "• A", "2026-11-20", "-", "$1060", "Unusual", "-", "-", "-", "-", "BLOCK", "$270K", "41"),
    ("2026-11-13", "BABA", "10:07 AM", "Call", "• A", "2027-01-15", "-", "$120", "-", "-", "-", "-", "-", "BLOCK", "$1.5M", "43"),
    ("2026-11-13", "CRWV", "03:47 PM", "Call", "• A", "2026-12-18", "-", "$65", "Unusual", "-", "-", "-", "-", "SPLIT", "$771K", "44"),
    ("2026-11-13", "CIFR", "09:56 AM", "Call", "• A", "2026-12-18", "-", "$9", "Unusual", "-", "-", "-", "-", "BLOCK", "$308K", "40"),
    ("2026-11-13", "VKTX", "12:59 PM", "Call", "• A", "2026-11-13", "-", "$27", "Top Pos", "-", "-", "-", "-", "BLOCK", "$145K", "41"),
    ("2026-11-13", "VKTX", "02:45 PM", "Call", "• A", "2026-12-18", "-", "$30", "Above Ask", "-", "-", "-", "-", "SWEEP", "$98K", "40"),
    ("2026-11-13", "NIO", "12:39 PM", "Put", "• A", "2027-01-15", "-", "$3", "-", "-", "-", "-", "-", "BLOCK", "$96K", "39"),
    ("2026-11-13", "SO", "12:08 PM", "Put", "• A", "2027-09-17", "-", "$75", "Top Pos", "-", "-", "-", "-", "SWEEP", "$119K", "39"),
    ("2026-11-13", "SPX", "11:57 AM", "Put", "• A", "2027-02-19", "-", "$8000", "-", "-", "-", "-", "-", "SPLIT", "$279.0M", "55"),
    ("2026-11-13", "SPX", "12:56 PM", "Call", "• A", "2026-11-20", "-", "$7000", "-", "-", "-", "-", "-", "SPLIT", "$126.3M", "52"),
    # ================= 2026-11-11 (이전 Evening Edge) =================
    ("2026-11-11", "SNDK", "10:53 AM", "Call", "• A", "2026-11-13", "-", "$1225", "Unusual", "-", "-", "-", "-", "SWEEP", "$45K", "42"),
    ("2026-11-11", "SNDK", "10:32 AM", "Call", "• A", "2026-11-20", "-", "$1030", "Golden", "-", "-", "-", "-", "GOLDEN SWEEP", "$1.5M", "48"),
    ("2026-11-11", "SNDK", "10:03 AM", "Call", "• A", "2026-11-20", "-", "$1260", "Unusual", "-", "-", "-", "-", "SWEEP", "$261K", "40"),
    ("2026-11-11", "SNDK", "09:55 AM", "Call", "• A", "2026-11-20", "-", "$950", "-", "-", "-", "-", "-", "SWEEP", "$2.8M", "45"),
    ("2026-11-11", "SNDK", "09:44 AM", "Call", "• A", "2026-11-27", "-", "$1290", "Unusual", "-", "-", "-", "-", "SPLIT", "$900K", "41"),
    ("2026-11-11", "SNDK", "09:43 AM", "Call", "• A", "2026-11-27", "-", "$1270", "Unusual", "-", "-", "-", "-", "SWEEP", "$1.0M", "43"),
    ("2026-11-11", "SNDK", "09:40 AM", "Call", "• A", "2026-11-20", "-", "$1080", "Unusual", "-", "-", "-", "-", "BLOCK", "$638K", "39"),
    ("2026-11-11", "SNDK", "09:35 AM", "Put", "• A", "2026-11-13", "-", "$920", "Top Pos", "-", "-", "-", "-", "SWEEP", "$967K", "44"),
    ("2026-11-11", "SNDK", "09:33 AM", "Call", "• A", "2026-11-13", "-", "$1100", "Unusual", "-", "-", "-", "-", "SWEEP", "$145K", "38"),
    ("2026-11-11", "META", "12:12 PM", "Call", "• A", "2027-01-15", "-", "$750", "OTM", "-", "-", "-", "-", "SWEEP", "$31.0M", "52"),
    ("2026-11-11", "INTC", "01:05 PM", "Call", "• A", "2027-02-19", "-", "$50", "ITM", "-", "-", "-", "-", "BLOCK", "$31.0M", "50"),
    ("2026-11-11", "INTC", "03:58 PM", "Call", "• A", "2026-11-27", "-", "$85", "Unusual", "-", "-", "-", "-", "SWEEP", "$55K", "41"),
    ("2026-11-11", "INTC", "03:58 PM", "Call", "• A", "2026-11-27", "-", "$85", "Unusual", "-", "-", "-", "-", "SWEEP", "$42K", "40"),
    ("2026-11-11", "MU", "09:51 AM", "Put", "• A", "2027-03-19", "-", "$800", "ATM", "-", "-", "-", "-", "SWEEP", "$24.3M", "49"),
    ("2026-11-11", "MU", "01:55 PM", "Call", "• A", "2026-11-16", "-", "$750", "-", "-", "-", "-", "-", "GOLDEN SWEEP", "$6.1M", "47"),
    ("2026-11-11", "LITE", "09:34 AM", "Put", "• A", "2026-11-13", "-", "$750", "Deep ITM", "-", "-", "-", "-", "GOLDEN SWEEP", "$12.6M", "49"),
    ("2026-11-11", "NVDA", "11:02 AM", "Call", "• A", "2027-06-17", "-", "$175", "-", "-", "-", "-", "-", "SWEEP", "$8.3M", "44"),
    ("2026-11-11", "NVDA", "02:19 PM", "Call", "• A", "2028-01-21", "-", "$150", "-", "-", "-", "-", "-", "SWEEP", "$6.8M", "42"),
    ("2026-11-11", "AAPL", "12:58 PM", "Call", "• A", "2026-12-18", "-", "$265", "-", "-", "-", "-", "-", "SWEEP", "$6.6M", "40"),
    ("2026-11-11", "AMD", "01:56 PM", "Put", "• A", "2026-11-20", "-", "$600", "-", "-", "-", "-", "-", "GOLDEN SWEEP", "$6.2M", "48"),
    ("2026-11-11", "TSLA", "10:24 AM", "Call", "• A", "2026-12-18", "-", "$340", "-", "-", "-", "-", "-", "BLOCK", "$6.1M", "43"),
    ("2026-11-11", "TSLA", "09:58 AM", "Call", "• A", "2026-11-27", "-", "$410", "-", "-", "-", "-", "-", "SWEEP", "$4.2M", "45"),
    ("2026-11-11", "AMAT", "09:45 AM", "Call", "• A", "2026-11-20", "-", "$530", "37%", "-", "545", "-", "-", "SWEEP", "$11K", "36"),
    ("2026-11-11", "RIOT", "11:39 AM", "Call", "• A", "2026-11-20", "-", "$24", "31%", "-", "-", "-", "-", "SWEEP", "$54K", "39"),
    ("2026-11-11", "RIOT", "11:21 AM", "Call", "• A", "2026-11-20", "-", "$17.5", "-", "-", "-", "-", "-", "SWEEP", "$696K", "42"),
    ("2026-11-11", "KGC", "10:13 AM", "Call", "• A", "2027-01-15", "-", "$22", "2%", "-", "-", "-", "-", "SWEEP", "$108K", "35"),
    ("2026-11-11", "KGC", "10:07 AM", "Call", "• A", "2027-01-15", "-", "$22", "2%", "-", "-", "-", "-", "SWEEP", "$137K", "35"),
    ("2026-11-11", "KGC", "10:01 AM", "Call", "• A", "2027-01-15", "-", "$22", "2%", "-", "-", "-", "-", "SWEEP", "$152K", "36"),
    ("2026-11-11", "KGC", "10:00 AM", "Call", "• A", "2027-01-15", "-", "$22", "2%", "-", "-", "-", "-", "SWEEP", "$82K", "35"),
    ("2026-11-11", "BW", "11:32 AM", "Call", "• A", "2027-01-15", "-", "$7.5", "46%", "-", "-", "-", "-", "SWEEP", "$36K", "35"),
    ("2026-11-11", "BW", "11:01 AM", "Call", "• A", "2027-01-15", "-", "$7.5", "46%", "-", "-", "-", "-", "SWEEP", "$75K", "37"),
    ("2026-11-11", "BW", "10:46 AM", "Call", "• A", "2026-12-18", "-", "$7", "-", "-", "-", "-", "-", "BLOCK", "$74K", "38"),
    ("2026-11-11", "ACHR", "11:11 AM", "Call", "• A", "2028-01-21", "-", "$10", "-", "-", "-", "-", "-", "SPLIT", "$137K", "36"),
    ("2026-11-11", "ACHR", "11:03 AM", "Call", "• A", "2027-01-15", "-", "$5", "-", "-", "-", "-", "-", "SWEEP", "$107K", "35"),
    ("2026-11-11", "ACHR", "10:43 AM", "Call", "• A", "2027-01-15", "-", "$6", "-", "-", "-", "-", "-", "SWEEP", "$71K", "35"),
    ("2026-11-11", "SPX", "11:15 AM", "Put", "• A", "2026-12-18", "-", "$8000", "-", "-", "-", "-", "-", "SPLIT", "$77.0M", "55"),
    ("2026-11-11", "SPX", "11:49 AM", "Put", "• A", "2027-02-19", "-", "$8000", "-", "-", "-", "-", "-", "SPLIT", "$39.4M", "52"),
    ("2026-11-11", "SPX", "03:52 PM", "Call", "• A", "2026-12-04", "-", "$7650", "-", "-", "-", "-", "-", "SPLIT", "$21.8M", "48"),
    ("2026-11-11", "IBIT", "10:11 AM", "Call", "• A", "2027-12-17", "-", "$48", "Top Pos", "-", "-", "-", "-", "SPLIT", "$63.4M", "50"),

    # ================= 2026-11-10 및 과거 내역 =================
    ("2026-11-10", "SNDK", "10:26 AM", "Call", "• A", "2026-11-13", "$873.50", "$900", "3%", "$28.14", "380", "1663", "120%", "SWEEP", "$1.1M", "33"),
    ("2026-11-10", "SNDK", "10:25 AM", "Call", "• A", "2026-11-13", "$872.50", "$900", "3%", "$27.75", "381", "1663", "120%", "SWEEP", "$1.1M", "33"),
    ("2026-11-10", "SNDK", "10:02 AM", "Call", "• A", "2026-11-13", "$909.00", "$1100", "21%", "$2.99", "401", "2154", "120%", "SWEEP", "$120K", "43"),
    ("2026-10-23", "SNDK", "02:52 PM", "Put", "• A", "2026-10-23", "$1620.00", "$1600", "-1%", "$18.50", "1000", "450", "85%", "BLOCK", "$19.0M", "35"),
    ("2026-09-25", "SNDK", "09:53 AM", "Call", "• A", "2026-09-25", "$1750.00", "$1782.5", "2%", "$38.00", "1950", "600", "70%", "SWEEP", "$7.4M", "35"),
    ("2026-11-10", "SMMT", "02:39 PM", "Call", "• A", "2026-11-20", "$17.50", "$30", "71%", "$0.25", "874", "340", "150%", "SWEEP", "$22K", "38"),
    ("2026-11-10", "BRBR", "10:30 AM", "Call", "• A", "2026-11-20", "$9.85", "$12.5", "27%", "$0.88", "400", "120", "85%", "SWEEP", "$35K", "32"),
    ("2026-11-10", "DBX", "11:42 AM", "Put", "• A", "2027-04-16", "$20.30", "$25", "23%", "$1.28", "400", "1500", "42%", "SWEEP", "$51K", "35"),
    ("2026-11-10", "NVDA", "12:14 PM", "Put", "• A", "2027-01-15", "$145.20", "$140", "4%", "$18.50", "27000", "15200", "58%", "BLOCK", "$50.0M", "50"),
    ("2026-11-10", "MU", "10:56 AM", "Put", "• A", "2027-01-15", "$795.20", "$1050", "-32%", "$320.00", "1085", "450", "48%", "SPLIT", "$34.7M", "48"),
    ("2026-11-10", "ASML", "12:06 PM", "Call", "• A", "2027-02-19", "$1680.00", "$1740", "4%", "$175.00", "730", "12", "42%", "BLOCK", "$12.8M", "45"),
    ("2026-11-10", "MSFT", "01:05 PM", "Call", "• A", "2026-12-18", "$565.00", "$580", "3%", "$86.00", "1500", "1200", "28%", "BLOCK", "$12.9M", "42"),
    ("2026-11-10", "SPX", "01:12 PM", "Call", "• A", "2027-06-17", "$5980.00", "$7000", "17%", "$225.00", "15000", "4200", "18%", "SPLIT", "$338.5M", "55"),
]

SHEET_URL = "https://docs.google.com/spreadsheets/d/1_FWy_B9a6t1txau06PbeEMy9S9B1GsMgWZLGfMmMG7w/export?format=csv&gid=0"

@st.cache_data(ttl=60)
def load_all_flows():
    res = list(DEFAULT_FLOWS)
    try:
        df = pd.read_csv(SHEET_URL)
        for _, r in df.iterrows():
            tk = str(r.get("Ticker (티커)", r.get("Ticker", ""))).strip().upper()
            if not tk or tk == "NAN": continue
            tm = str(r.get("Time (시각)", "10:00 AM"))
            cp = str(r.get("Option Type (구분)", "Call")).capitalize()
            stk = f"${str(r.get('Strike Price (행사가)', '0')).replace(',', '').replace('$', '')}"
            exp = str(r.get("Expiration Date (만기일)", "2026-11-20"))
            pr = str(r.get("Premium (프리미엄)", "$100K"))
            if not pr.startswith("$"): pr = f"${pr}"
            ch = str(r.get("Characteristics (주문유형/특징)", "SWEEP")).upper()
            typ = "BLOCK" if "BLOCK" in ch else ("SPLIT" if "SPLIT" in ch else "SWEEP")
            dt = str(r.get("Date (날짜)", r.get("Date", r.get("날짜", r.get("일자", ""))))).strip()
            if not dt or dt.lower() == "nan":
                if "2026-09" in exp: dt = "2026-09-25"
                elif "2026-10" in exp: dt = "2026-10-23"
                else: dt = "2026-11-10"
            row_tuple = (dt, tk, tm, cp, "• A", exp, "-", stk, "-", "-", "-", "-", "-", typ, pr, "35")
            if row_tuple not in res:
                res.append(row_tuple)
    except Exception:
        pass
    return res

all_raw_flows = load_all_flows()
available_dates = sorted(list(set([r[0] for r in all_raw_flows])), reverse=True)
date_options = ["전체 날짜 (누적 전체)"] + available_dates

st.sidebar.markdown("### 📅 필터 및 정렬")
sel_date = st.sidebar.selectbox("📅 조회 날짜 선택", date_options, index=1 if len(date_options)>1 else 0)

if sel_date.startswith("전체 날짜"):
    date_filtered_flows = all_raw_flows
else:
    date_filtered_flows = [r for r in all_raw_flows if r[0] == sel_date]
    
available_tickers = sorted(list(set([r[1] for r in date_filtered_flows])))
if not available_tickers:
    available_tickers = sorted(list(set([r[1] for r in all_raw_flows])))
    date_filtered_flows = all_raw_flows
    
default_tk_idx = available_tickers.index("SNDK") if "SNDK" in available_tickers else 0
sel_tk = st.sidebar.selectbox("🎯 종목 선택", available_tickers, index=default_tk_idx)
sort_dir = st.sidebar.radio("⏱️ 정렬 순서", ["최신 시간순 (Newest)", "과거 시간순 (Oldest)"], index=0)

st.sidebar.markdown("---")
st.sidebar.markdown("### 📩 텔레그램 알림 연동")
tg_token, tg_chat_id = load_tg_config()
if tg_token and tg_chat_id:
    st.sidebar.success(f"🟢 텔레그램 연결됨 (ID: {tg_chat_id})")
else:
    st.sidebar.warning("⚠️ 서버에 텔레그램 설정 파일이 없습니다.")
    tg_token = st.sidebar.text_input("Bot Token", value=tg_token, type="password")
    tg_chat_id = st.sidebar.text_input("Chat ID", value=tg_chat_id)

if st.sidebar.button("📩 선택 날짜 전체 플로우 전송", use_container_width=True):
    lines = [f"📊 [OptionHub] {sel_date} 전체 옵션 플로우 ({len(date_filtered_flows)}건)\n"]
    for r in date_filtered_flows:
        lines.append(f"• [{r[2]}] {r[1]} {r[7]} {r[3]} ({r[5]}) @ {r[14]} ({r[13]})")
    lines.append("\n🌐 대시보드: http://132.226.3.145:8501")
    ok, msg = send_telegram_msg(tg_token, tg_chat_id, "\n".join(lines))
    if ok: st.sidebar.success(f"✅ {msg}")
    else: st.sidebar.error(f"❌ 전송 실패: {msg}")

if st.sidebar.button("📝 오늘 종합평 텔레그램 전송", use_container_width=True):
    ok, msg = send_telegram_msg(tg_token, tg_chat_id, DAILY_REVIEW_2026_11_11)
    if ok: st.sidebar.success(f"✅ 종합평 {msg}")
    else: st.sidebar.error(f"❌ 전송 실패: {msg}")

if st.sidebar.button("🚀 오늘의 대형체결·문샷·뉴스 전체 전송", use_container_width=True):
    summary_msg = """⚡ [OptionHub] 2026-11-11 핵심 리포트 전체

[1] 🔥 AI Noteworthy Trades (핵심 대형 체결 6선)
• META 750 Call (2027-01-15) @ 1.0M (Sweep) - Positioning 5/5
• MU 800 Put (2027-03-19) @ 4.3M (Sweep) - Hedge 5/5
• AMD 600 Put (2026-11-20) @ .2M (Golden Sweep) - Hedge 5/5
• TSLA 410 Call (2026-11-27) @ .2M (Sweep) - Short-Term 5/5
• INTC 50 Call (2027-02-19) @ 1.0M (Block) - Stock Replacement 4/5
• LITE 750 Put (2026-11-13) @ 2.6M (Golden Sweep) - Short-Term 4/5

[2] 🚀 Top 10 Moonshot Flows
• INTC 85C (2026-11-27) @ 5K / 2K
• PDFS 50C (2026-11-20) @ 2K
• BW 7C (2026-12-18) @ 4K / 7.5C (2027-01-15) @ 5K
• CIFR 9C (2027-01-15) @ 70K
• FRVO 21C (2027-01-15) @ 34K
• AZTA 55C (2026-11-20) @ 1K
• LSCC 160C (2027-01-15) @ 33K
• ACHR 6C (2027-01-15) @ 1K

[3] 📰 Trending News (7선)
• Anthropic (ANT): 클래스A 8.25억주(0~8) IPO 로드쇼 개시
• U.S. Macro: 10월 CPI·매파적 연준 여파로 AI 인프라 부채 검증 심화
• Nvidia (NVDA): 이사회 조사 개시 및 Baird 목표가 하향(00→00)
• Costco (COST): 주당 0 특별 현금 배당(33억 규모) 및 자사주 매입
• Amazon (AMZN): AWS 매출 +39.3%(60억), 수주잔고 ,780억
• Firefly Aerospace: Q3 매출 .107억, 수주잔고 7억 사상 최대
• Adobe (ADBE): Adobe MAX에서 GenStudio 에이전틱 AI 업그레이드 발표

🌐 대시보드 바로가기: http://132.226.3.145:8501"""
    ok, msg = send_telegram_msg(tg_token, tg_chat_id, summary_msg)
    if ok: st.sidebar.success(f"✅ {msg}")
    else: st.sidebar.error(f"❌ 전송 실패: {msg}")




# ================= TAB 0: TODAY COMPREHENSIVE REVIEW =================

# ================= TAB MOOMOO: REALTIME CHART & ORDERBOOK =================
if nav_menu == "⚡ 무무 실시간 차트":
    import sqlite3
    import streamlit.components.v1 as components

    st.markdown("<style>div[data-stale='true']{opacity:1!important;transition:none!important;}</style>", unsafe_allow_html=True)
    st.title("⚡ 무무(Moomoo) 트레이딩뷰 실시간 차트")
    st.caption("TradingView Lightweight Charts 엔진 기반 · 무무 실시간 시세 + VWAP·볼린저밴드 + 옵션 Call/Put Wall·Zero Gamma")

    db_path = os.environ.get("MOOMOO_DB", os.path.expanduser("~/moomoo-hub/moomoo.db"))
    col_r1, col_r2, col_r3 = st.columns([2.6, 0.9, 0.9])
    with col_r2:
        auto_rf = st.toggle("⏱️ 5초 자동 갱신", value=False, key="mm_auto_rf")
    with col_r3:
        if st.button("🔄 실시간 새로고침", use_container_width=True):
            st.rerun()

    con = None
    q_map = {}
    parsed_q = []
    if os.path.exists(db_path):
        try:
            con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
            q_rows = con.execute("SELECT sym, ts, data FROM quotes ORDER BY ts DESC").fetchall()
            for syn, ts_val, d_txt in q_rows:
                try:
                    d = json.loads(d_txt) if d_txt else {}
                except Exception:
                    d = {}
                px = d.get("last_price") or d.get("px") or d.get("price") or 0
                prev_c = d.get("prev_close_price") or d.get("prev_close") or 0
                chg = d.get("change_rate") or d.get("chg_pct")
                if chg is None and px and prev_c:
                    chg = round((float(px) - float(prev_c)) / float(prev_c) * 100, 2)
                vol = d.get("volume") or d.get("vol") or 0
                t_kst = pd.to_datetime(ts_val, unit="s", utc=True).tz_convert("Asia/Seoul").strftime("%m-%d %H:%M:%S")
                q_map[syn] = {"px": float(px or 0), "chg": chg, "vol": float(vol or 0), "t": t_kst, "raw": d}
                parsed_q.append({
                    "종목": syn,
                    "현재가($)": round(float(px or 0), 2),
                    "등락률(%)": round(float(chg), 2) if chg is not None else None,
                    "거래량": int(float(vol or 0)),
                    "수신시각(KST)": t_kst,
                })
        except Exception:
            pass

    sel_c1, sel_c2, sel_c3 = st.columns([1.5, 1.4, 2.9])
    if q_map:
        with col_r1:
            st.success(f"🟢 무무 실시간 수신 중 · {len(parsed_q)}종목 · 최근 갱신: {parsed_q[0]['수신시각(KST)']} KST")
        with sel_c1:
            sel_syn = st.selectbox("📌 종목 선택", list(q_map.keys()), index=0)
        cur = q_map[sel_syn]
        clean_tk = sel_syn.split(".")[-1].upper()
    else:
        with col_r1:
            st.info("📡 무무 브리지 대기 중 — 기본 야후 실시간 분봉으로 트레이딩뷰 차트를 미리 표시합니다.")
        with sel_c1:
            clean_tk = st.selectbox("📌 종목 선택", ["NVDA", "SOXL", "SOXS", "TSLA", "MU", "AMD", "SPY", "QQQ"], index=0)
        sel_syn = f"US.{clean_tk}"
        cur = {"px": 0.0, "chg": None, "vol": 0.0, "t": "-"}
    with sel_c2:
        search_tk = st.text_input("🔍 종목 검색", "", placeholder="예: SMH, PLTR, MU").strip().upper()
    if search_tk:
        clean_tk = search_tk
        sel_syn = f"US.{clean_tk}"
        cur = q_map.get(sel_syn, {"px": 0.0, "chg": None, "vol": 0.0, "t": "-"})
    with sel_c3:
        tf_opt = st.radio("⏱️ 봉 주기", ["1분봉", "5분봉", "10분봉", "15분봉", "1일봉"], index=1, horizontal=True, key="mm_tf")

    @st.cache_data(ttl=300, show_spinner=False)
    def _cached_opt_snapshot(tk_sym):
        rows, sp, _ = fetch_yahoo_oi(tk_sym)
        return rows, sp

    # OptionHub GEX Wall + SIG_H/L + DELTA + GEX CALL/PUT + Left Call/Put Bars lookup
    oi_hist_m = load_json_file(OI_PATH, {})
    cw_lv = pw_lv = zg_lv = sig_h_lv = sig_l_lv = delta_lv = gex_c_lv = gex_p_lv = None
    opt_bars = []
    if clean_tk in oi_hist_m and oi_hist_m[clean_tk]:
        snap_m = oi_hist_m[clean_tk][-1]
        det_m = snap_m.get("상세", [])
        spot_m = float(snap_m.get("Spot", cur["px"] or 0) or 0)
        calls_m = [x for x in det_m if x.get("구분") == "Call"]
        puts_m = [x for x in det_m if x.get("구분") == "Put"]
        calls_near = [x for x in calls_m if not spot_m or 0.60 * spot_m <= float(x.get("행사가", 0) or 0) <= 1.40 * spot_m] or calls_m
        puts_near = [x for x in puts_m if not spot_m or 0.60 * spot_m <= float(x.get("행사가", 0) or 0) <= 1.40 * spot_m] or puts_m
        if calls_near:
            cw_lv = max(calls_near, key=lambda x: x.get("OI", 0)).get("행사가")
            gex_c_lv = max(calls_near, key=lambda x: abs(float(x.get("GEX($M)", 0) or 0))).get("행사가")
        if puts_near:
            pw_lv = max(puts_near, key=lambda x: x.get("OI", 0)).get("행사가")
            gex_p_lv = max(puts_near, key=lambda x: abs(float(x.get("GEX($M)", 0) or 0))).get("행사가")
        zg_lv = calc_zero_gamma(det_m, spot_m)
        if det_m:
            df_dm = pd.DataFrame(det_m)
            if "DEX($M)" in df_dm.columns and not df_dm.empty:
                dex_s = df_dm.groupby("행사가")["DEX($M)"].sum().abs()
                if not dex_s.empty:
                    delta_lv = float(dex_s.idxmax())
            ref_px_sig = float(cur["px"] or spot_m or 0)
            if "IV(%)" in df_dm.columns and ref_px_sig > 0:
                atm_iv_m = float(df_dm.iloc[(df_dm["행사가"] - ref_px_sig).abs().argsort()[:4]]["IV(%)"].mean() or 0)
                if atm_iv_m > 0:
                    mv_1d = ref_px_sig * (atm_iv_m / 100.0) / math.sqrt(252.0)
                    sig_h_lv = round(ref_px_sig + mv_1d, 2)
                    sig_l_lv = round(ref_px_sig - mv_1d, 2)
            # 행사가별 Call/Put 강도 (거래량·|GEX| 기반 좌측 가로 막대)
            grp_c = df_dm[df_dm["구분"] == "Call"].groupby("행사가")["GEX($M)"].sum().abs() if "GEX($M)" in df_dm.columns else pd.Series(dtype=float)
            grp_p = df_dm[df_dm["구분"] == "Put"].groupby("행사가")["GEX($M)"].sum().abs() if "GEX($M)" in df_dm.columns else pd.Series(dtype=float)
            all_ks = sorted(set(grp_c.index.tolist()) | set(grp_p.index.tolist()))
            mx_cp = max([float(grp_c.get(k, 0)) + float(grp_p.get(k, 0)) for k in all_ks] + [1e-6])
            for k in all_ks:
                cv = float(grp_c.get(k, 0))
                pv = float(grp_p.get(k, 0))
                if cv + pv > 0 and (not spot_m or 0.55 * spot_m <= float(k) <= 1.45 * spot_m):
                    c_oi = int(df_dm[(df_dm["행사가"] == k) & (df_dm["구분"] == "Call")]["OI"].sum()) if "OI" in df_dm.columns else 0
                    p_oi = int(df_dm[(df_dm["행사가"] == k) & (df_dm["구분"] == "Put")]["OI"].sum()) if "OI" in df_dm.columns else 0
                    net_g_k = float(df_dm[df_dm["행사가"] == k]["GEX($M)"].sum()) if "GEX($M)" in df_dm.columns else 0.0
                    opt_bars.append({"p": float(k), "c": round(cv / mx_cp, 3), "put": round(pv / mx_cp, 3), "c_m": round(cv, 2), "p_m": round(pv, 2), "c_oi": c_oi, "p_oi": p_oi, "net_g": round(net_g_k, 2)})
    if (not opt_bars) or (cw_lv is not None and pw_lv is not None and cw_lv == pw_lv):
        try:
            y_rows, y_sp = _cached_opt_snapshot(clean_tk)
            if y_rows:
                df_yd = pd.DataFrame(y_rows)
                sp_ref = float(y_sp or cur["px"] or 0)
                if sp_ref > 0:
                    df_yd = df_yd[(df_yd["행사가"] >= sp_ref * 0.7) & (df_yd["행사가"] <= sp_ref * 1.3)]
                if not df_yd.empty:
                    if (cw_lv is None or cw_lv == pw_lv) and not df_yd[df_yd["구분"] == "Call"].empty:
                        cw_lv = float(df_yd[df_yd["구분"] == "Call"].sort_values("OI", ascending=False).iloc[0]["행사가"])
                    if (pw_lv is None or cw_lv == pw_lv) and not df_yd[df_yd["구분"] == "Put"].empty:
                        pw_lv = float(df_yd[df_yd["구분"] == "Put"].sort_values("OI", ascending=False).iloc[0]["행사가"])
                    if zg_lv is None:
                        zg_lv = calc_zero_gamma(df_yd, sp_ref)
                    if sig_h_lv is None and "IV(%)" in df_yd.columns and sp_ref > 0:
                        atm_iv_y = float(df_yd.iloc[(df_yd["행사가"] - sp_ref).abs().argsort()[:4]]["IV(%)"].mean() or 0)
                        if atm_iv_y > 0:
                            mv_y = sp_ref * (atm_iv_y / 100.0) / math.sqrt(252.0)
                            sig_h_lv = round(sp_ref + mv_y, 2)
                            sig_l_lv = round(sp_ref - mv_y, 2)
                    yc = df_yd[df_yd["구분"] == "Call"].groupby("행사가")["GEX($M)"].sum().abs()
                    yp = df_yd[df_yd["구분"] == "Put"].groupby("행사가")["GEX($M)"].sum().abs()
                    yks = sorted(set(yc.index.tolist()) | set(yp.index.tolist()))
                    ymx = max([float(yc.get(k, 0)) + float(yp.get(k, 0)) for k in yks] + [1e-6])
                    for k in yks:
                        cv, pv = float(yc.get(k, 0)), float(yp.get(k, 0))
                        if cv + pv > 0:
                            c_oi = int(df_yd[(df_yd["행사가"] == k) & (df_yd["구분"] == "Call")]["OI"].sum())
                            p_oi = int(df_yd[(df_yd["행사가"] == k) & (df_yd["구분"] == "Put")]["OI"].sum())
                            net_g_k = float(df_yd[df_yd["행사가"] == k]["GEX($M)"].sum())
                            opt_bars.append({"p": float(k), "c": round(cv / ymx, 3), "put": round(pv / ymx, 3), "c_m": round(cv, 2), "p_m": round(pv, 2), "c_oi": c_oi, "p_oi": p_oi, "net_g": round(net_g_k, 2)})
        except Exception:
            pass

    # Build OHLCV candles: yfinance base (1m/5m/10m/15m/1d) + moomoo live overlay
    tf_map = {
        "1분봉": ("2d", "1m", 60),
        "5분봉": ("5d", "5m", 300),
        "10분봉": ("5d", "5m", 600),
        "15분봉": ("5d", "15m", 900),
        "1일봉": ("1y", "1d", 86400),
    }
    yf_per, yf_int, tf_sec = tf_map.get(tf_opt, ("5d", "5m", 300))
    candles = []
    @st.cache_data(ttl=60, show_spinner=False)
    def _fetch_tf_candles(tk_s, per_s, int_s, resamp_10=False):
        out = []
        try:
            import yfinance as yf
            d_y = yf.Ticker(tk_s).history(period=per_s, interval=int_s)
            if not d_y.empty:
                if resamp_10:
                    d_y = d_y.resample("10min").agg({"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}).dropna()
                for idx_t, r_y in d_y.iterrows():
                    out.append({
                        "time": int(idx_t.timestamp()),
                        "open": round(float(r_y["Open"]), 2),
                        "high": round(float(r_y["High"]), 2),
                        "low": round(float(r_y["Low"]), 2),
                        "close": round(float(r_y["Close"]), 2),
                        "volume": float(r_y["Volume"]),
                    })
        except Exception:
            pass
        return out

    tf_sec_map = {"1분봉": 60, "5분봉": 300, "10분봉": 600, "15분봉": 900, "1일봉": 86400}
    raw_tf_sets = {
        "1분봉": _fetch_tf_candles(clean_tk, "2d", "1m", False),
        "5분봉": _fetch_tf_candles(clean_tk, "5d", "5m", False),
        "10분봉": _fetch_tf_candles(clean_tk, "5d", "5m", True),
        "1일봉": _fetch_tf_candles(clean_tk, "1y", "1d", False),
    }

    aux_map = {}
    moomoo_bars = []
    hist_rows = []
    if con is not None:
        try:
            for k_a, d_a in con.execute("SELECT kind, data FROM aux WHERE sym=?", (sel_syn,)).fetchall():
                try:
                    aux_map[k_a] = json.loads(d_a)
                except Exception:
                    pass
            bars_data = aux_map.get("bars")
            if isinstance(bars_data, dict):
                bars_data = bars_data.get("bars") or bars_data.get("data") or bars_data.get("items")
            if isinstance(bars_data, list) and bars_data and isinstance(bars_data[0], dict):
                for b in bars_data:
                    t_raw = b.get("time_key") or b.get("time") or b.get("ts") or b.get("t")
                    ts_sec = int(pd.Timestamp(t_raw).timestamp()) if isinstance(t_raw, str) else int(float(t_raw))
                    moomoo_bars.append({
                        "time": ts_sec,
                        "open": float(b.get("open", b.get("o", 0))),
                        "high": float(b.get("high", b.get("h", 0))),
                        "low": float(b.get("low", b.get("l", 0))),
                        "close": float(b.get("close", b.get("c", 0))),
                        "volume": float(b.get("volume", b.get("vol", b.get("v", 0))) or 0),
                    })
            hist_rows = con.execute("SELECT ts, px, vol FROM quote_hist WHERE sym=? ORDER BY ts ASC", (sel_syn,)).fetchall()
        except Exception:
            pass

    def _merge_tf_candles(base_list, sec_step):
        merged = list(base_list or [])
        if sec_step <= 900 and moomoo_bars:
            merged.extend(moomoo_bars)
        if hist_rows:
            df_h = pd.DataFrame(hist_rows, columns=["ts", "px", "vol"])
            df_h["min_ts"] = (df_h["ts"] // sec_step).astype(int) * sec_step
            for m_ts, g in df_h.groupby("min_ts"):
                o_px = float(g["px"].iloc[0])
                h_px = float(g["px"].max())
                l_px = float(g["px"].min())
                c_px = float(g["px"].iloc[-1])
                v_diff = float(max(g["vol"].iloc[-1] - g["vol"].iloc[0], 0))
                # 주말/장마감 무거래 정지 구간 평탄화 틱 제외
                if v_diff <= 0 and h_px <= l_px and merged:
                    continue
                merged.append({
                    "time": int(m_ts),
                    "open": o_px,
                    "high": h_px,
                    "low": l_px,
                    "close": c_px,
                    "volume": v_diff,
                })
        c_dict = {c["time"]: c for c in merged if c["close"] > 0}
        return [c_dict[k] for k in sorted(c_dict.keys())]

    merged_tf_sets = {k: _merge_tf_candles(v, tf_sec_map.get(k, 300)) for k, v in raw_tf_sets.items()}
    candles = list(merged_tf_sets.get(tf_opt) or _merge_tf_candles(_fetch_tf_candles(clean_tk, yf_per, yf_int, tf_opt == "10분봉"), tf_sec))

    # 시간외/실시간 호가(Bid/Ask)와 현재가·마지막 캔들 일치화
    raw_d = cur.get("raw") if isinstance(cur.get("raw"), dict) else {}
    ext_px = 0.0
    for _ek in ("overnight_price", "after_price", "pre_price", "ext_price"):
        try:
            _ev = float(raw_d.get(_ek) or 0)
            if _ev > 0:
                ext_px = _ev
                break
        except Exception:
            pass

    bk_top = aux_map.get("book") or {}
    bids_top = bk_top.get("Bid") or bk_top.get("bids") or []
    asks_top = bk_top.get("Ask") or bk_top.get("asks") or []
    bp_num, ap_num = 0.0, 0.0
    try:
        if raw_d.get("bid_price") or raw_d.get("bid"):
            bp_num = float(raw_d.get("bid_price") or raw_d.get("bid") or 0)
        if raw_d.get("ask_price") or raw_d.get("ask"):
            ap_num = float(raw_d.get("ask_price") or raw_d.get("ask") or 0)
    except Exception:
        pass
    if (bp_num <= 0 or ap_num <= 0) and bids_top and asks_top:
        try:
            bp_num = float(bids_top[0][0])
            ap_num = float(asks_top[0][0])
        except Exception:
            pass

    if ext_px > 0:
        cur["px"] = ext_px
    if bp_num > 0 and ap_num > 0 and bp_num <= ap_num:
        _mid_ba = round((bp_num + ap_num) / 2.0, 2)
        if cur["px"] <= 0 or abs(cur["px"] - _mid_ba) / max(_mid_ba, 1e-6) > 0.005:
            cur["px"] = _mid_ba
            _prev_c = float(raw_d.get("prev_close_price") or raw_d.get("prev_close") or 0)
            if _prev_c > 0:
                cur["chg"] = round((cur["px"] - _prev_c) / _prev_c * 100.0, 2)
    elif cur["px"] == 0 and candles:
        cur["px"] = candles[-1]["close"]

    if cur["px"] > 0:
        _px_sync = round(float(cur["px"]), 2)
        for _tfk, _tfl in merged_tf_sets.items():
            if _tfl:
                _lc = dict(_tfl[-1])
                _lc["close"] = _px_sync
                _lc["high"] = max(float(_lc["high"]), _px_sync)
                _lc["low"] = min(float(_lc["low"]), _px_sync)
                _tfl[-1] = _lc
        if candles:
            _lc0 = dict(candles[-1])
            _lc0["close"] = _px_sync
            _lc0["high"] = max(float(_lc0["high"]), _px_sync)
            _lc0["low"] = min(float(_lc0["low"]), _px_sync)
            candles[-1] = _lc0

    bid_px_s = f"${bp_num:,.2f}" if bp_num > 0 else "-"
    ask_px_s = f"${ap_num:,.2f}" if ap_num > 0 else "-"

    tot_net_g_mm = round(sum(float(x.get("net_g", 0) or 0) for x in opt_bars), 2) if opt_bars else 0.0
    tot_c_oi_mm = sum(int(x.get("c_oi", 0) or 0) for x in opt_bars)
    tot_p_oi_mm = sum(int(x.get("p_oi", 0) or 0) for x in opt_bars)
    sent_score = int(round(tot_c_oi_mm / max(tot_c_oi_mm + tot_p_oi_mm, 1) * 100)) if opt_bars else 50
    sent_lbl = "BULLISH" if sent_score >= 60 else ("BEARISH" if sent_score <= 40 else "NEUTRAL")
    sent_col = "#10b981" if sent_score >= 60 else ("#ef4444" if sent_score <= 40 else "#f59e0b")
    st.markdown(f"""
    <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:12px; background:#0b101b; border:1px solid #1e293b; border-radius:8px; padding:8px 14px; margin-bottom:8px;">
      <div><span style="font-size:11px;color:#94a3b8;">TOTAL NET GEX</span><br><b style="font-size:16px;color:{'#10b981' if tot_net_g_mm>=0 else '#ef4444'};">${tot_net_g_mm:+.2f}M</b></div>
      <div><span style="font-size:11px;color:#94a3b8;">REGIME</span><br><b style="font-size:14px;color:{'#10b981' if tot_net_g_mm>=0 else '#ef4444'};">{'Positive GEX' if tot_net_g_mm>=0 else 'Negative GEX'}</b></div>
      <div style="min-width:220px;">
        <div style="display:flex;justify-content:space-between;font-size:11px;font-weight:700;">
          <span style="color:#94a3b8;">0DTE SENTIMENT</span><span style="color:{sent_col};">{sent_lbl} ({sent_score}/100)</span>
        </div>
        <div style="height:8px;border-radius:4px;background:linear-gradient(90deg,#ef4444,#f59e0b,#10b981);position:relative;margin-top:4px;">
          <div style="position:absolute;top:-3px;left:calc({sent_score}% - 4px);width:8px;height:14px;background:#fff;border-radius:2px;"></div>
        </div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("현재가", f"${cur['px']:,.2f}" if cur["px"] else "-", f"{cur['chg']:+.2f}%" if cur["chg"] is not None else None)
    m2.metric("Bid / Ask", f"{bid_px_s} / {ask_px_s}")
    _v_num = float(cur["vol"] or 0)
    _v_str = f"{_v_num/1e6:,.2f}M" if _v_num >= 1e6 else (f"{_v_num/1e3:,.1f}K" if _v_num >= 1e3 else (f"{int(_v_num):,}" if _v_num > 0 else "-"))
    m3.metric("당일 거래량", _v_str)
    m4.metric("Zero Gamma", f"${zg_lv:g}" if zg_lv else "-")
    m5.metric("Call / Put Wall", f"${cw_lv:g} / ${pw_lv:g}" if (cw_lv and pw_lv) else f"${cw_lv or '-'} / ${pw_lv or '-'}")

    with st.expander("⚙️ 지표 편집 (차트 오버레이 · 일목 · 보조지표 · 기간 설정)", expanded=False):
        ed_l, ed_r = st.columns([1.3, 1.0])
        with ed_l:
            st.markdown("**차트 위에 겹쳐 그리기**")
            c_o1, c_o2, c_o3 = st.columns(3)
            show_vwap = c_o1.checkbox("VWAP", value=False, key="ed_vwap")
            show_bb = c_o2.checkbox("볼린저", value=False, key="ed_bb")
            show_ma = c_o3.checkbox("이동평균(MA)", value=False, key="ed_ma")
            c_o4, c_o5, c_o6 = st.columns(3)
            show_cw = c_o4.checkbox("콜월 (Call Wall)", value=True, key="ed_cw")
            c_l1, c_l2, c_l3, c_l4 = st.columns(4)
            show_pw = c_l1.checkbox("풋월 (Put Wall)", value=True, key="ed_pw")
            show_1sig = c_l2.checkbox("1시그마 (1σ)", value=True, key="ed_1sig")
            show_zg = c_l3.checkbox("감마플립", value=True, key="ed_zg")
            show_open_px = c_l4.checkbox("Open (시가)", value=True, key="ed_open_px")
            show_vpvr_vol = c_o5.checkbox("좌측 매물대(VPVR)", value=True, key="ed_vpvr_vol")
            show_ichi_cloud = c_o6.checkbox("일목 구름대(Cloud)", value=True, key="ed_ichi_cloud")
            st.markdown("**일목균형표 세부 요소 (개별 넣기 · 빼기)**")
            ic_1, ic_2, ic_3, ic_4, ic_5 = st.columns(5)
            show_tenkan = ic_1.checkbox("전환선(9)", value=True, key="ed_ichi_ten")
            show_kijun = ic_2.checkbox("기준선(26)", value=True, key="ed_ichi_kij")
            show_span_a = ic_3.checkbox("선행스팬1", value=True, key="ed_ichi_spa")
            show_span_b = ic_4.checkbox("선행스팬2", value=True, key="ed_ichi_spb")
            show_chikou = ic_5.checkbox("후행스팬", value=True, key="ed_ichi_chi")
            st.markdown("**아래 보조지표 (위로 ⬆️ · 아래로 ⬇️ · 빼기 ❌)**")
            if "mm_sub_order" not in st.session_state:
                st.session_state["mm_sub_order"] = ["CVD(누적델타)", "BII(체결강도)", "MACD"]
            sub_order = list(st.session_state["mm_sub_order"])
            for si, sname in enumerate(sub_order):
                sc_n, sc_u, sc_d, sc_x = st.columns([2.2, 0.6, 0.6, 0.6])
                sc_n.markdown(f"`{si+1}. {sname}`")
                if sc_u.button("⬆️", key=f"sub_up_{si}") and si > 0:
                    sub_order[si-1], sub_order[si] = sub_order[si], sub_order[si-1]
                    st.session_state["mm_sub_order"] = sub_order
                    st.rerun()
                if sc_d.button("⬇️", key=f"sub_dn_{si}") and si < len(sub_order) - 1:
                    sub_order[si+1], sub_order[si] = sub_order[si], sub_order[si+1]
                    st.session_state["mm_sub_order"] = sub_order
                    st.rerun()
                if sc_x.button("❌", key=f"sub_rm_{si}"):
                    sub_order.pop(si)
                    st.session_state["mm_sub_order"] = sub_order
                    st.rerun()
            avail_subs = [x for x in ["CVD(누적델타)", "BII(체결강도)", "MACD", "RSI"] if x not in sub_order]
            if avail_subs:
                ac_s, ac_b = st.columns([2.4, 1.0])
                add_pick = ac_s.selectbox("보조지표 추가", avail_subs, label_visibility="collapsed", key="sub_add_sel")
                if ac_b.button("➕ 추가", use_container_width=True, key="sub_add_btn"):
                    sub_order.append(add_pick)
                    st.session_state["mm_sub_order"] = sub_order
                    st.rerun()
            c_s1, c_s2 = st.columns(2)
            show_vol = c_s1.checkbox("거래량(Vol · 주 차트 하단)", value=True, key="ed_vol")
            show_icc = c_s2.checkbox("역시계곡선(아래 따로)", value=True, key="ed_icc")
            c_s3, c_s4, c_s5 = st.columns(3)
            show_vpvr_opt = c_s3.checkbox("좌측 콜/풋 막대", value=True, key="ed_vpvr_opt")
            show_rail_gex = c_s4.checkbox("우측 GEX 레일", value=True, key="ed_rail_gex")
            show_rail_nf = c_s5.checkbox("우측 Net Flow 레일", value=True, key="ed_rail_nf")
            vpvr_scale = st.slider("좌측 매물대·콜풋 막대 길이 (%)", 20, 500, 220, step=20, key="ed_vpvr_scale")
            show_cvd = "CVD(누적델타)" in sub_order
            show_bii = "BII(체결강도)" in sub_order
            show_macd = "MACD" in sub_order
            show_rsi = "RSI" in sub_order
        with ed_r:
            st.markdown("**기간 설정**")
            bb_cfg = st.text_input("볼린저 (기간, σ)", "20,2", key="ed_bb_p")
            rsi_len = st.number_input("RSI 기간", 2, 100, 14, key="ed_rsi_p")
            macd_cfg = st.text_input("MACD (단기, 장기, 시그널)", "12,26,9", key="ed_macd_p")
            ichi_cfg = st.text_input("일목 (전환, 기준, 선행B)", "9,26,52", key="ed_ichi_p")
            p_c1, p_c2 = st.columns(2)
            icc_len = p_c1.number_input("역시계곡선 기간", 5, 100, 20, key="ed_icc_p")
            vpvr_bins_n = p_c2.number_input("매물대 칸 수", 10, 60, 24, key="ed_vpvr_p")
            ma_cfg = st.text_input("이동평균 (단기, 장기)", "20,200", key="ed_ma_p")

    try:
        bb_len, bb_std = [float(x.strip()) for x in bb_cfg.split(",")[:2]]
        bb_len = int(bb_len)
    except Exception:
        bb_len, bb_std = 20, 2.0
    try:
        m_fast, m_slow, m_sig = [int(x.strip()) for x in macd_cfg.split(",")[:3]]
    except Exception:
        m_fast, m_slow, m_sig = 12, 26, 9
    try:
        i_ten, i_kij, i_sen = [int(x.strip()) for x in ichi_cfg.split(",")[:3]]
    except Exception:
        i_ten, i_kij, i_sen = 9, 26, 52
    try:
        ma1_len, ma2_len = [int(x.strip()) for x in ma_cfg.split(",")[:2]]
    except Exception:
        ma1_len, ma2_len = 20, 200

    def _build_tf_bundle(c_list):
        if not c_list:
            return {
                "candles": [], "volumes": [], "vwap": [], "bb_up": [], "bb_dn": [],
                "ma20": [], "ma200": [], "tenkan": [], "kijun": [], "span_a": [],
                "span_b": [], "chikou": [], "cloud": [], "vpvr": [], "cvd": [],
                "bii": [], "macd": [], "macd_sig": [], "macd_hist": [], "rsi": [],
            }, pd.DataFrame()
        df_c = pd.DataFrame(c_list)
        tp = (df_c["high"] + df_c["low"] + df_c["close"]) / 3.0
        v_safe = df_c["volume"].replace(0, 1)
        df_c["vwap"] = (tp * v_safe).cumsum() / v_safe.cumsum()
        df_c["ma20"] = df_c["close"].rolling(ma1_len).mean()
        df_c["bb_ma"] = df_c["close"].rolling(bb_len).mean()
        df_c["std20"] = df_c["close"].rolling(bb_len).std()
        df_c["ma200"] = df_c["close"].rolling(min(ma2_len, max(30, len(df_c)//2))).mean()

        h9 = df_c["high"].rolling(i_ten).max(); l9 = df_c["low"].rolling(i_ten).min()
        h26 = df_c["high"].rolling(i_kij).max(); l26 = df_c["low"].rolling(i_kij).min()
        h52 = df_c["high"].rolling(i_sen).max(); l52 = df_c["low"].rolling(i_sen).min()
        df_c["tenkan"] = (h9 + l9) / 2.0
        df_c["kijun"] = (h26 + l26) / 2.0
        df_c["span_a"] = ((df_c["tenkan"] + df_c["kijun"]) / 2.0).shift(i_kij)
        df_c["span_b"] = ((h52 + l52) / 2.0).shift(i_kij)
        df_c["chikou"] = df_c["close"].shift(-i_kij)

        rng_hl = (df_c["high"] - df_c["low"]).replace(0, 1e-6)
        bar_delta = df_c["volume"] * ((2.0 * df_c["close"] - df_c["high"] - df_c["low"]) / rng_hl)
        df_c["cvd"] = bar_delta.cumsum()
        # BII(Intraday Intensity %): 이동합(20봉) 기반 정규화 체결강도 (-100 ~ +100%)
        roll_v = df_c["volume"].rolling(20, min_periods=1).sum().replace(0, 1)
        df_c["bii"] = (bar_delta.rolling(20, min_periods=1).sum() / roll_v) * 100.0

        ema12 = df_c["close"].ewm(span=m_fast, adjust=False).mean()
        ema26 = df_c["close"].ewm(span=m_slow, adjust=False).mean()
        df_c["macd"] = ema12 - ema26
        df_c["macd_sig"] = df_c["macd"].ewm(span=m_sig, adjust=False).mean()
        df_c["macd_hist"] = df_c["macd"] - df_c["macd_sig"]

        diff_c = df_c["close"].diff()
        gain = diff_c.clip(lower=0).rolling(int(rsi_len)).mean()
        loss = (-diff_c.clip(upper=0)).rolling(int(rsi_len)).mean().replace(0, 1e-6)
        df_c["rsi"] = 100.0 - (100.0 / (1.0 + gain / loss))

        df_c["vol_ma20"] = df_c["volume"].rolling(int(icc_len)).mean()
        icc_local = df_c.dropna(subset=["ma20", "vol_ma20"]).tail(40).copy()

        vpvr_local = []
        p_min, p_max = float(df_c["low"].min()), float(df_c["high"].max())
        if p_max > p_min:
            bins = int(vpvr_bins_n)
            step = (p_max - p_min) / bins
            v_arr = [0.0] * bins
            for _, rc in df_c.iterrows():
                idx_b = min(bins - 1, max(0, int((float(rc["close"]) - p_min) / step)))
                v_arr[idx_b] += float(rc["volume"])
            v_mx = max(v_arr) or 1.0
            for bi in range(bins):
                vpvr_local.append({"p": round(p_min + (bi + 0.5) * step, 2), "pct": round(v_arr[bi] / v_mx, 3)})

        o_vol, o_vwap, o_ma20, o_ma200, o_bb_u, o_bb_d = [], [], [], [], [], []
        o_ten, o_kij, o_spa, o_spb, o_chi, o_cld = [], [], [], [], [], []
        o_cvd, o_bii, o_macd, o_msig, o_mhist, o_rsi = [], [], [], [], [], []
        for _, r_c in df_c.iterrows():
            t_i = int(r_c["time"])
            is_up = r_c["close"] >= r_c["open"]
            o_vol.append({"time": t_i, "value": float(r_c["volume"]), "color": "rgba(38,166,154,0.5)" if is_up else "rgba(239,83,80,0.5)"})
            o_vwap.append({"time": t_i, "value": round(float(r_c["vwap"]), 2)})
            o_cvd.append({"time": t_i, "value": round(float(r_c["cvd"]), 1)})
            o_bii.append({"time": t_i, "value": round(float(r_c["bii"]), 2)})
            o_macd.append({"time": t_i, "value": round(float(r_c["macd"]), 3)})
            o_msig.append({"time": t_i, "value": round(float(r_c["macd_sig"]), 3)})
            mh = float(r_c["macd_hist"])
            o_mhist.append({"time": t_i, "value": round(mh, 3), "color": "rgba(16,185,129,0.65)" if mh >= 0 else "rgba(239,68,68,0.65)"})
            if pd.notna(r_c["ma20"]):
                o_ma20.append({"time": t_i, "value": round(float(r_c["ma20"]), 2)})
            if pd.notna(r_c["ma200"]):
                o_ma200.append({"time": t_i, "value": round(float(r_c["ma200"]), 2)})
            if pd.notna(r_c["bb_ma"]) and pd.notna(r_c["std20"]):
                o_bb_u.append({"time": t_i, "value": round(float(r_c["bb_ma"] + bb_std * r_c["std20"]), 2)})
                o_bb_d.append({"time": t_i, "value": round(float(r_c["bb_ma"] - bb_std * r_c["std20"]), 2)})
            if pd.notna(r_c["tenkan"]):
                o_ten.append({"time": t_i, "value": round(float(r_c["tenkan"]), 2)})
            if pd.notna(r_c["kijun"]):
                o_kij.append({"time": t_i, "value": round(float(r_c["kijun"]), 2)})
            if pd.notna(r_c["span_a"]):
                o_spa.append({"time": t_i, "value": round(float(r_c["span_a"]), 2)})
            if pd.notna(r_c["span_b"]):
                o_spb.append({"time": t_i, "value": round(float(r_c["span_b"]), 2)})
            if pd.notna(r_c["span_a"]) and pd.notna(r_c["span_b"]):
                o_cld.append({"time": t_i, "a": round(float(r_c["span_a"]), 2), "b": round(float(r_c["span_b"]), 2)})
            if pd.notna(r_c["chikou"]):
                o_chi.append({"time": t_i, "value": round(float(r_c["chikou"]), 2)})
            if pd.notna(r_c["rsi"]):
                o_rsi.append({"time": t_i, "value": round(float(r_c["rsi"]), 2)})

        return {
            "candles": [{k: c[k] for k in ("time", "open", "high", "low", "close")} for c in c_list],
            "volumes": o_vol if show_vol else [],
            "vwap": o_vwap if show_vwap else [],
            "bb_up": o_bb_u if show_bb else [],
            "bb_dn": o_bb_d if show_bb else [],
            "ma20": o_ma20 if show_ma else [],
            "ma200": o_ma200 if show_ma else [],
            "tenkan": o_ten if show_tenkan else [],
            "kijun": o_kij if show_kijun else [],
            "span_a": o_spa if show_span_a else [],
            "span_b": o_spb if show_span_b else [],
            "chikou": o_chi if show_chikou else [],
            "cloud": o_cld if show_ichi_cloud else [],
            "vpvr": vpvr_local if show_vpvr_vol else [],
            "cvd": o_cvd if show_cvd else [],
            "bii": o_bii if show_bii else [],
            "macd": o_macd if show_macd else [],
            "macd_sig": o_msig if show_macd else [],
            "macd_hist": o_mhist if show_macd else [],
            "rsi": o_rsi if show_rsi else [],
        }, icc_local

    tf_bundles = {}
    icc_df = pd.DataFrame()
    for tf_k, tf_c in merged_tf_sets.items():
        b_res, b_icc = _build_tf_bundle(tf_c)
        tf_bundles[tf_k] = b_res
        if tf_k == tf_opt:
            icc_df = b_icc
    cur_bundle = tf_bundles.get(tf_opt)
    if cur_bundle is None or not cur_bundle["candles"]:
        cur_bundle, icc_df = _build_tf_bundle(candles)

    # 1일봉 기반 20일 실현변동성(HV20)으로 1시그마 검증 및 보정 (주말 IV=0.30 폴백/분봉 오차 방지)
    daily_c = merged_tf_sets.get("1일봉") or []
    hv20_1d_std = 0.0
    if len(daily_c) >= 10:
        df_d1 = pd.DataFrame(daily_c)
        hv20_1d_std = float(df_d1["close"].pct_change().dropna().tail(20).std() or 0)
    last_c_sig = float(cur["px"] or (candles[-1]["close"] if candles else 0) or 0)
    if last_c_sig > 0:
        if sig_h_lv is not None and sig_l_lv is not None and hv20_1d_std > 0:
            cur_half = abs(sig_h_lv - sig_l_lv) / 2.0
            # 옵션 IV가 주말 폴백(30%) 등으로 1일 실현변동성의 60% 미만이면 1일 HV20 기준으로 보정
            if cur_half < last_c_sig * hv20_1d_std * 0.6:
                sig_h_lv = round(last_c_sig * (1.0 + hv20_1d_std), 2)
                sig_l_lv = round(last_c_sig * (1.0 - hv20_1d_std), 2)
        elif sig_h_lv is None and hv20_1d_std > 0:
            sig_h_lv = round(last_c_sig * (1.0 + hv20_1d_std), 2)
            sig_l_lv = round(last_c_sig * (1.0 - hv20_1d_std), 2)

    pane_cnt = int(show_cvd) + int(show_bii) + int(show_macd) + int(show_rsi)
    total_h = 520 + pane_cnt * 135

    tv_payload = json.dumps({
        "tk": clean_tk,
        "tf_cur": tf_opt,
        "tf_sets": tf_bundles,
        "candles": cur_bundle["candles"],
        "volumes": cur_bundle["volumes"],
        "vwap": cur_bundle["vwap"],
        "bb_up": cur_bundle["bb_up"],
        "bb_dn": cur_bundle["bb_dn"],
        "ma20": cur_bundle["ma20"],
        "ma200": cur_bundle["ma200"],
        "tenkan": cur_bundle["tenkan"],
        "kijun": cur_bundle["kijun"],
        "span_a": cur_bundle["span_a"],
        "span_b": cur_bundle["span_b"],
        "chikou": cur_bundle["chikou"],
        "vpvr": cur_bundle["vpvr"],
        "cvd": cur_bundle["cvd"],
        "bii": cur_bundle["bii"],
        "cloud": cur_bundle["cloud"],
        "macd": cur_bundle["macd"],
        "macd_sig": cur_bundle["macd_sig"],
        "macd_hist": cur_bundle["macd_hist"],
        "rsi": cur_bundle["rsi"],        "cw": cw_lv if (show_cw and cw_lv and (not cur["px"] or 0.55 * cur["px"] <= float(cw_lv) <= 1.45 * cur["px"])) else None,
        "pw": pw_lv if (show_pw and pw_lv and (not cur["px"] or 0.55 * cur["px"] <= float(pw_lv) <= 1.45 * cur["px"])) else None,
        "zg": zg_lv if (show_zg and zg_lv and (not cur["px"] or 0.55 * cur["px"] <= float(zg_lv) <= 1.45 * cur["px"])) else None,
        "sig_h": sig_h_lv if show_1sig else None,
        "sig_l": sig_l_lv if show_1sig else None,
        "open_px": round(float(merged_tf_sets["1일봉"][-1]["open"]), 2) if (show_open_px and merged_tf_sets.get("1일봉")) else (round(float(candles[-1]["open"]), 2) if (show_open_px and candles) else None),
        "delta_k": delta_lv if (show_zg and delta_lv and (not cur["px"] or 0.55 * cur["px"] <= float(delta_lv) <= 1.45 * cur["px"])) else None,
        "gex_c_k": gex_c_lv if (show_cw and gex_c_lv and (not cur["px"] or 0.55 * cur["px"] <= float(gex_c_lv) <= 1.45 * cur["px"])) else None,
        "gex_p_k": gex_p_lv if (show_pw and gex_p_lv and (not cur["px"] or 0.55 * cur["px"] <= float(gex_p_lv) <= 1.45 * cur["px"])) else None,
        "opt_bars": opt_bars if (show_vpvr_opt or show_rail_gex or show_rail_nf) else [],
        "show_vpvr": show_vpvr_vol,
        "show_vpvr_opt": show_vpvr_opt,
        "bar_scale": vpvr_scale / 100.0,
        "show_r_gex": show_rail_gex,
        "show_r_nf": show_rail_nf,
    })

    tv_html = f"""
    <div style="display:flex; flex-wrap:wrap; gap:10px; align-items:center; background:#0b101b; border:1px solid #1e293b; border-radius:6px; padding:6px 12px; margin-bottom:6px; font-family:monospace; font-size:12px;">
      <span>🟢 <b>CALL WALL</b>: <b style="color:#10b981;">{f"${cw_lv:g}" if cw_lv else "-"}</b></span>
      <span>🔴 <b>PUT WALL</b>: <b style="color:#ef4444;">{f"${pw_lv:g}" if pw_lv else "-"}</b></span>
      <span>🟡 <b>FLIP GAMMA</b>: <b style="color:#f59e0b;">{f"${zg_lv:g}" if zg_lv else "-"}</b></span>
      <span>🔵 <b>1σ 상단/하단</b>: <b style="color:#38bdf8;">{f"${sig_l_lv:g} ~ ${sig_h_lv:g}" if (sig_h_lv and sig_l_lv) else "-"}</b></span>
      <span>⚪ <b>OPEN</b>: <b style="color:#e2e8f0;">{f"${merged_tf_sets['1일봉'][-1]['open']:g}" if merged_tf_sets.get("1일봉") else "-"}</b></span>
    </div>
    <div id="tv_wrap" style="background:#080c14; border:1px solid #1e293b; border-radius:8px; overflow:hidden;">
    <div style="display:flex; justify-content:space-between; align-items:center; background:#0d131f; border-bottom:1px solid #1e293b; padding:5px 10px; font-family:sans-serif; font-size:12px; color:#cbd5e1;">
      <span id="tv_hint" style="color:#94a3b8;">🖱️ 커서 모드 · 빈 곳 끌기=이동 · 휠=확대/축소</span>
      <div style="display:flex; align-items:center; gap:5px;">
        <button class="tv-tf" data-tf="1분봉" style="background:#1e293b;color:#e2e8f0;border:1px solid #334155;border-radius:4px;padding:3px 8px;cursor:pointer;font-weight:700;">1분봉</button>
        <button class="tv-tf" data-tf="5분봉" style="background:#1e293b;color:#e2e8f0;border:1px solid #334155;border-radius:4px;padding:3px 8px;cursor:pointer;font-weight:700;">5분봉</button>
        <button class="tv-tf" data-tf="10분봉" style="background:#1e293b;color:#e2e8f0;border:1px solid #334155;border-radius:4px;padding:3px 8px;cursor:pointer;font-weight:700;">10분봉</button>
        <button class="tv-tf" data-tf="1일봉" style="background:#1e293b;color:#e2e8f0;border:1px solid #334155;border-radius:4px;padding:3px 8px;cursor:pointer;font-weight:700;">1일봉</button>
        <button id="tv_fs" style="background:#0f172a;color:#38bdf8;border:1px solid #38bdf8;border-radius:4px;padding:3px 10px;cursor:pointer;font-weight:700;">⛶ 전체화면 확대</button>
      </div>
    </div>
    <div style="display:flex; width:100%;">
      <div style="width:38px; flex-shrink:0; background:#0b101b; border-right:1px solid #1e293b; display:flex; flex-direction:column; align-items:center; gap:6px; padding:8px 0; z-index:6;">
        <button class="tv-tool active" data-t="cursor" title="커서(이동/줌)" style="width:28px;height:28px;background:#2563eb;color:#fff;border:0;border-radius:4px;cursor:pointer;">🖱️</button>
        <button class="tv-tool" data-t="line" title="추세선" style="width:28px;height:28px;background:#1e293b;color:#e2e8f0;border:1px solid #334155;border-radius:4px;cursor:pointer;">📏</button>
        <button class="tv-tool" data-t="hline" title="수평선" style="width:28px;height:28px;background:#1e293b;color:#e2e8f0;border:1px solid #334155;border-radius:4px;cursor:pointer;">➖</button>
        <button class="tv-tool" data-t="brush" title="붓 그리기" style="width:28px;height:28px;background:#1e293b;color:#e2e8f0;border:1px solid #334155;border-radius:4px;cursor:pointer;">✏️</button>
        <button class="tv-tool" data-t="memo" title="메모 입력" style="width:28px;height:28px;background:#1e293b;color:#e2e8f0;border:1px solid #334155;border-radius:4px;cursor:pointer;">📝</button>
        <input id="tv_color" type="color" value="#f59e0b" style="width:26px;height:24px;border:0;background:none;cursor:pointer;" title="색상"/>
        <button id="tv_undo" title="되돌리기" style="width:28px;height:28px;background:#1e293b;color:#fbbf24;border:1px solid #334155;border-radius:4px;cursor:pointer;">↩️</button>
        <button id="tv_clear" title="전체지우기" style="width:28px;height:28px;background:#1e293b;color:#f87171;border:1px solid #334155;border-radius:4px;cursor:pointer;">🗑️</button>
      </div>
      <div style="flex:1; min-width:0; background:#080c14;">
      <div style="display:flex; width:100%;">
      <div style="position:relative; flex:1; min-width:0;">
      <div id="tv_main" style="width:100%; height:460px;"></div>
      <div id="tv_hud" style="position:absolute; top:8px; right:76px; z-index:4; background:rgba(15,23,42,0.85); border:1px solid #334155; border-radius:6px; padding:5px 10px; font-family:monospace; font-size:11px; color:#e2e8f0; pointer-events:none;"></div>
      <canvas id="tv_cloud" style="position:absolute; top:0; left:0; width:100%; height:460px; pointer-events:none; z-index:1;"></canvas>
      <canvas id="tv_vpvr" style="position:absolute; top:0; left:0; width:680px; height:460px; pointer-events:none; z-index:2;"></canvas>
      <canvas id="tv_draw" style="position:absolute; top:0; left:0; width:100%; height:460px; pointer-events:none; z-index:5;"></canvas>
      </div>
      <canvas id="tv_rail" style="width:{(68 if show_rail_gex else 0) + (68 if show_rail_nf else 0)}px; height:460px; flex-shrink:0; background:#090d16; border-left:1px solid #1e293b;"></canvas>
      </div>
      <div style="padding-right:{(68 if show_rail_gex else 0) + (68 if show_rail_nf else 0)}px; background:#080c14;">
      {''.join([
          '<div id="tv_cvd" style="width:100%; height:130px; border-top:1px solid #2a2e39;"></div>' if x == "CVD(누적델타)" else
          '<div id="tv_bii" style="width:100%; height:130px; border-top:1px solid #2a2e39;"></div>' if x == "BII(체결강도)" else
          '<div id="tv_macd" style="width:100%; height:130px; border-top:1px solid #2a2e39;"></div>' if x == "MACD" else
          '<div id="tv_rsi" style="width:100%; height:130px; border-top:1px solid #2a2e39;"></div>'
          for x in sub_order
      ])}
      </div>
      </div>
    </div>
    </div>
    <script src="https://unpkg.com/lightweight-charts@4.2.0/dist/lightweight-charts.standalone.production.js"></script>
    <script>
      const d = {tv_payload};
      const fmtCompact = (v) => {{
        const av = Math.abs(v);
        if (av >= 1e9) return (v / 1e9).toFixed(2) + "B";
        if (av >= 1e6) return (v / 1e6).toFixed(2) + "M";
        if (av >= 1e3) return (v / 1e3).toFixed(2) + "K";
        return v.toFixed(2);
      }};
      const baseOpt = {{
        layout: {{ background: {{ color: "#080c14" }}, textColor: "#d1d4dc", attributionLogo: false }},
        grid: {{ vertLines: {{ color: "rgba(42,46,57,0.35)" }}, horzLines: {{ color: "rgba(42,46,57,0.35)" }} }},
        crosshair: {{ mode: LightweightCharts.CrosshairMode.Normal }},
        rightPriceScale: {{ borderColor: "#2a2e39", minimumWidth: 92 }},
        timeScale: {{ borderColor: "#2a2e39", timeVisible: true, secondsVisible: false }},
      }};
      const elMain = document.getElementById("tv_main");
      const chart = LightweightCharts.createChart(elMain, baseOpt);
      const cs = chart.addCandlestickSeries({{
        upColor:"#26a69a", downColor:"#ef5350", borderVisible:false, wickUpColor:"#26a69a", wickDownColor:"#ef5350",
        autoscaleInfoProvider: (original) => {{
          const res = original();
          if (res && res.priceRange) {{
            const refP = d.candles.length ? d.candles[d.candles.length - 1].close : 0;
            [d.cw, d.pw, d.zg, d.sig_h, d.sig_l].forEach(lv => {{
              if (lv && (!refP || (lv >= refP * 0.72 && lv <= refP * 1.28))) {{
                if (lv < res.priceRange.minValue) res.priceRange.minValue = lv * 0.992;
                if (lv > res.priceRange.maxValue) res.priceRange.maxValue = lv * 1.008;
              }}
            }});
          }}
          return res;
        }}
      }});
      cs.setData(d.candles);
      let vs = null;
      if (d.volumes.length) {{
        vs = chart.addHistogramSeries({{ priceFormat:{{type:"volume"}}, priceScaleId:"" }});
        vs.priceScale().applyOptions({{ scaleMargins:{{ top:0.82, bottom:0 }} }});
        vs.setData(d.volumes);
      }}
      function styleTfBtns(act) {{
        document.querySelectorAll(".tv-tf").forEach(b => {{
          const on = b.dataset.tf === act;
          b.style.background = on ? "#f59e0b" : "#1e293b";
          b.style.color = on ? "#0f172a" : "#e2e8f0";
          b.style.borderColor = on ? "#f59e0b" : "#334155";
        }});
      }}
      styleTfBtns(d.tf_cur);
      const sVwap = d.vwap.length ? chart.addLineSeries({{ color:"#38bdf8", lineWidth:2, lastValueVisible:false, priceLineVisible:false }}) : null;
      if (sVwap) sVwap.setData(d.vwap);
      const sMa20 = d.ma20.length ? chart.addLineSeries({{ color:"#22c55e", lineWidth:1, lastValueVisible:false, priceLineVisible:false }}) : null;
      if (sMa20) sMa20.setData(d.ma20);
      const sMa200 = d.ma200.length ? chart.addLineSeries({{ color:"#eab308", lineWidth:2, lastValueVisible:false, priceLineVisible:false }}) : null;
      if (sMa200) sMa200.setData(d.ma200);
      const sBbUp = d.bb_up.length ? chart.addLineSeries({{ color:"rgba(168,85,247,0.7)", lineWidth:1, lineStyle:2, lastValueVisible:false, priceLineVisible:false }}) : null;
      const sBbDn = d.bb_dn.length ? chart.addLineSeries({{ color:"rgba(168,85,247,0.7)", lineWidth:1, lineStyle:2, lastValueVisible:false, priceLineVisible:false }}) : null;
      if (sBbUp) sBbUp.setData(d.bb_up);
      if (sBbDn) sBbDn.setData(d.bb_dn);
      const sTenkan = d.tenkan.length ? chart.addLineSeries({{ color:"#ef4444", lineWidth:1, lastValueVisible:false, priceLineVisible:false }}) : null;
      const sKijun = d.kijun.length ? chart.addLineSeries({{ color:"#3b82f6", lineWidth:1, lastValueVisible:false, priceLineVisible:false }}) : null;
      const sSpanA = d.span_a.length ? chart.addLineSeries({{ color:"rgba(16,185,129,0.55)", lineWidth:1, lastValueVisible:false, priceLineVisible:false }}) : null;
      const sSpanB = d.span_b.length ? chart.addLineSeries({{ color:"rgba(239,68,68,0.55)", lineWidth:1, lastValueVisible:false, priceLineVisible:false }}) : null;
      const sChikou = d.chikou.length ? chart.addLineSeries({{ color:"rgba(148,163,184,0.6)", lineWidth:1, lineStyle:2, lastValueVisible:false, priceLineVisible:false }}) : null;
      if (sTenkan) sTenkan.setData(d.tenkan);
      if (sKijun) sKijun.setData(d.kijun);
      if (sSpanA) sSpanA.setData(d.span_a);
      if (sSpanB) sSpanB.setData(d.span_b);
      if (sChikou) sChikou.setData(d.chikou);

      if (d.cw) cs.createPriceLine({{ price:d.cw, color:"#10b981", lineWidth:2, lineStyle:2, title:"CALL WALL" }});
      if (d.pw) cs.createPriceLine({{ price:d.pw, color:"#ef4444", lineWidth:2, lineStyle:2, title:"PUT WALL" }});
      if (d.zg) cs.createPriceLine({{ price:d.zg, color:"#f59e0b", lineWidth:2, lineStyle:1, title:"FLIP GAMMA" }});
      if (d.sig_h) cs.createPriceLine({{ price:d.sig_h, color:"#f87171", lineWidth:1, lineStyle:2, title:"1σ 상단" }});
      if (d.sig_l) cs.createPriceLine({{ price:d.sig_l, color:"#38bdf8", lineWidth:1, lineStyle:2, title:"1σ 하단" }});
      if (d.open_px) cs.createPriceLine({{ price:d.open_px, color:"#e2e8f0", lineWidth:1.5, lineStyle:0, title:"OPEN" }});
      if (d.delta_k) cs.createPriceLine({{ price:d.delta_k, color:"#eab308", lineWidth:1, lineStyle:3, title:"DELTA" }});
      if (d.gex_c_k) cs.createPriceLine({{ price:d.gex_c_k, color:"#22c55e", lineWidth:1, lineStyle:3, title:"GEX CALL" }});
      if (d.gex_p_k) cs.createPriceLine({{ price:d.gex_p_k, color:"#fb7185", lineWidth:1, lineStyle:3, title:"GEX PUT" }});

      // VPVR + 좌측 Call(초록)/Put(빨강) 가로 막대 그리기
      const vpCv = document.getElementById("tv_vpvr");
      const clCv = document.getElementById("tv_cloud");
      function drawCloud() {{
        const mh = elMain.clientHeight || 460;
        clCv.width = elMain.clientWidth; clCv.height = mh;
        const cctx = clCv.getContext("2d");
        cctx.clearRect(0, 0, clCv.width, mh);
        if (!d.cloud || d.cloud.length < 2) return;
        for (let i = 0; i < d.cloud.length - 1; i++) {{
          const p1 = d.cloud[i], p2 = d.cloud[i+1];
          const x1 = chart.timeScale().timeToCoordinate(p1.time);
          const x2 = chart.timeScale().timeToCoordinate(p2.time);
          const ya1 = cs.priceToCoordinate(p1.a), yb1 = cs.priceToCoordinate(p1.b);
          const ya2 = cs.priceToCoordinate(p2.a), yb2 = cs.priceToCoordinate(p2.b);
          if ([x1,x2,ya1,yb1,ya2,yb2].some(v => v === null)) continue;
          cctx.beginPath();
          cctx.moveTo(x1, ya1); cctx.lineTo(x2, ya2); cctx.lineTo(x2, yb2); cctx.lineTo(x1, yb1);
          cctx.closePath();
          cctx.fillStyle = p1.a >= p1.b ? "rgba(16,185,129,0.14)" : "rgba(239,68,68,0.14)";
          cctx.fill();
        }}
      }}
      function drawVpvr() {{
        drawCloud();
        drawRail();
        const mh = elMain.clientHeight || 460;
        vpCv.width = 680; vpCv.height = mh;
        const ctx = vpCv.getContext("2d");
        ctx.clearRect(0, 0, 680, mh);
        const sc = d.bar_scale || 2.2;
        if (d.show_vpvr && d.vpvr && d.vpvr.length) {{
          d.vpvr.forEach(b => {{
            const y = cs.priceToCoordinate(b.p);
            if (y === null || y < 0 || y > mh) return;
            const w = Math.max(4, Math.round(b.pct * 220 * sc));
            ctx.fillStyle = b.pct > 0.75 ? "rgba(245,158,11,0.38)" : "rgba(56,189,248,0.24)";
            ctx.fillRect(0, y - 5, w, 10);
            if (b.pct >= 0.99) {{
              ctx.font = "bold 9px monospace"; ctx.fillStyle = "#fbbf24";
              ctx.fillText("POC $" + b.p, w + 4, y + 3);
            }}
          }});
        }}
        if (d.show_vpvr_opt && d.opt_bars && d.opt_bars.length) {{
          d.opt_bars.forEach(b => {{
            const y = cs.priceToCoordinate(b.p);
            if (y === null || y < 0 || y > mh) return;
            const wc = Math.round(b.c * 145 * sc);
            const wp = Math.round(b.put * 145 * sc);
            if (wp > 0) {{ ctx.fillStyle = "rgba(239,68,68,0.88)"; ctx.fillRect(0, y - 3, wp, 6); }}
            if (wc > 0) {{ ctx.fillStyle = "rgba(16,185,129,0.92)"; ctx.fillRect(wp, y - 3, wc, 6); }}
            if (wc + wp > Math.max(22, Math.round(32 * sc))) {{
              ctx.font = "10px monospace"; ctx.fillStyle = "#e2e8f0";
              ctx.fillText("C" + b.c_m + "/P" + b.p_m, wc + wp + 4, y + 3);
            }}
          }});
        }}
      }}
      function drawRail() {{
        const rl = document.getElementById("tv_rail");
        if (!rl) return;
        const mh = elMain.clientHeight || 460;
        const rw = (d.show_r_gex ? 68 : 0) + (d.show_r_nf ? 68 : 0);
        rl.style.width = rw + "px";
        rl.width = rw; rl.height = mh;
        if (rw === 0) return;
        const rctx = rl.getContext("2d");
        rctx.clearRect(0, 0, rw, mh);
        rctx.fillStyle = "#94a3b8"; rctx.font = "bold 10px monospace";
        const gexOff = 0, nfOff = d.show_r_gex ? 68 : 0;
        if (d.show_r_gex) {{
          rctx.fillText("GEX", gexOff + 22, 14);
          rctx.strokeStyle = "rgba(148,163,184,0.25)";
          rctx.beginPath(); rctx.moveTo(gexOff + 34, 18); rctx.lineTo(gexOff + 34, mh); rctx.stroke();
        }}
        if (d.show_r_nf) {{
          rctx.fillText("Net Flow", nfOff + 10, 14);
          rctx.strokeStyle = "rgba(148,163,184,0.25)";
          rctx.beginPath(); rctx.moveTo(nfOff + 34, 18); rctx.lineTo(nfOff + 34, mh); rctx.stroke();
        }}
        if (d.show_r_gex && d.show_r_nf) {{
          rctx.strokeStyle = "#1e293b";
          rctx.beginPath(); rctx.moveTo(68, 0); rctx.lineTo(68, mh); rctx.stroke();
        }}
        if (!d.opt_bars || !d.opt_bars.length) return;
        const maxG = Math.max(...d.opt_bars.map(x => Math.abs(x.net_g || 0)), 0.1);
        const maxOi = Math.max(...d.opt_bars.map(x => Math.abs((x.c_oi || 0) - (x.p_oi || 0))), 1);
        d.opt_bars.forEach(b => {{
          const y = cs.priceToCoordinate(b.p);
          if (y === null || y < 20 || y > mh - 8) return;
          if (d.show_r_gex) {{
            const gw = Math.max(2, Math.round(Math.abs(b.net_g || 0) / maxG * 30));
            if ((b.net_g || 0) >= 0) {{ rctx.fillStyle = "#10b981"; rctx.fillRect(gexOff + 34 - gw, y - 2, gw, 5); }}
            else {{ rctx.fillStyle = "#ef4444"; rctx.fillRect(gexOff + 34, y - 2, gw, 5); }}
          }}
          if (d.show_r_nf) {{
            const netOi = (b.c_oi || 0) - (b.p_oi || 0);
            const ow = Math.max(2, Math.round(Math.abs(netOi) / maxOi * 30));
            if (netOi >= 0) {{ rctx.fillStyle = "#10b981"; rctx.fillRect(nfOff + 34 - ow, y - 2, ow, 5); }}
            else {{ rctx.fillStyle = "#ef4444"; rctx.fillRect(nfOff + 34, y - 2, ow, 5); }}
          }}
        }});
      }}

      // 보조지표 차트 동기화
      const subCharts = [];
      const subLinks = [];
      let cCvd = null, sCvd = null, cBii = null, sBii = null;
      let cMacd = null, sMacdH = null, sMacd = null, sMacdS = null;
      let cRsi = null, sRsi = null;
      if (d.cvd.length && document.getElementById("tv_cvd")) {{
        cCvd = LightweightCharts.createChart(document.getElementById("tv_cvd"), baseOpt);
        sCvd = cCvd.addAreaSeries({{ lineColor:"#38bdf8", topColor:"rgba(56,189,248,0.3)", bottomColor:"rgba(56,189,248,0.02)", lineWidth:2, title:"CVD", priceFormat:{{type:"custom", formatter:fmtCompact}} }});
        sCvd.setData(d.cvd);
        subCharts.push(cCvd); subLinks.push({{c: cCvd, s: sCvd}});
      }}
      if (d.bii.length && document.getElementById("tv_bii")) {{
        cBii = LightweightCharts.createChart(document.getElementById("tv_bii"), baseOpt);
        sBii = cBii.addLineSeries({{ color:"#2563eb", lineWidth:2, title:"BII (%)", priceFormat:{{type:"custom", formatter: v => v.toFixed(2) + "%"}} }});
        sBii.setData(d.bii);
        sBii.createPriceLine({{ price:0, color:"rgba(148,163,184,0.4)", lineStyle:2 }});
        subCharts.push(cBii); subLinks.push({{c: cBii, s: sBii}});
      }}
      if (d.macd.length && document.getElementById("tv_macd")) {{
        cMacd = LightweightCharts.createChart(document.getElementById("tv_macd"), baseOpt);
        sMacdH = cMacd.addHistogramSeries({{ title:"MACD Hist" }});
        sMacd = cMacd.addLineSeries({{ color:"#38bdf8", lineWidth:1.5, title:"MACD" }});
        sMacdS = cMacd.addLineSeries({{ color:"#f59e0b", lineWidth:1.5, title:"Signal" }});
        sMacdH.setData(d.macd_hist); sMacd.setData(d.macd); sMacdS.setData(d.macd_sig);
        subCharts.push(cMacd); subLinks.push({{c: cMacd, s: sMacd}});
      }}
      if (d.rsi.length && document.getElementById("tv_rsi")) {{
        cRsi = LightweightCharts.createChart(document.getElementById("tv_rsi"), baseOpt);
        sRsi = cRsi.addLineSeries({{ color:"#a855f7", lineWidth:2, title:"RSI" }});
        sRsi.setData(d.rsi);
        sRsi.createPriceLine({{ price:70, color:"rgba(239,68,68,0.6)", lineStyle:2, title:"70" }});
        sRsi.createPriceLine({{ price:30, color:"rgba(16,185,129,0.6)", lineStyle:2, title:"30" }});
        subCharts.push(cRsi); subLinks.push({{c: cRsi, s: sRsi}});
      }}

      document.querySelectorAll(".tv-tf").forEach(b => {{
        b.onclick = () => {{
          const tfB = d.tf_sets && d.tf_sets[b.dataset.tf];
          if (!tfB || !tfB.candles || !tfB.candles.length) return;
          cs.setData(tfB.candles);
          if (vs && tfB.volumes) vs.setData(tfB.volumes);
          if (sVwap && tfB.vwap) sVwap.setData(tfB.vwap);
          if (sMa20 && tfB.ma20) sMa20.setData(tfB.ma20);
          if (sMa200 && tfB.ma200) sMa200.setData(tfB.ma200);
          if (sBbUp && tfB.bb_up) sBbUp.setData(tfB.bb_up);
          if (sBbDn && tfB.bb_dn) sBbDn.setData(tfB.bb_dn);
          if (sTenkan && tfB.tenkan) sTenkan.setData(tfB.tenkan);
          if (sKijun && tfB.kijun) sKijun.setData(tfB.kijun);
          if (sSpanA && tfB.span_a) sSpanA.setData(tfB.span_a);
          if (sSpanB && tfB.span_b) sSpanB.setData(tfB.span_b);
          if (sChikou && tfB.chikou) sChikou.setData(tfB.chikou);
          d.cloud = tfB.cloud || [];
          d.vpvr = tfB.vpvr || [];
          if (sCvd && tfB.cvd) sCvd.setData(tfB.cvd);
          if (sBii && tfB.bii) sBii.setData(tfB.bii);
          if (sMacdH && tfB.macd_hist) sMacdH.setData(tfB.macd_hist);
          if (sMacd && tfB.macd) sMacd.setData(tfB.macd);
          if (sMacdS && tfB.macd_sig) sMacdS.setData(tfB.macd_sig);
          if (sRsi && tfB.rsi) sRsi.setData(tfB.rsi);
          chart.timeScale().fitContent();
          const newR = chart.timeScale().getVisibleLogicalRange();
          subCharts.forEach(sc => {{ if (newR) sc.timeScale().setVisibleLogicalRange(newR); else sc.timeScale().fitContent(); }});
          styleTfBtns(b.dataset.tf);
          setTimeout(drawVpvr, 80);
        }};
      }});

      const hudEl = document.getElementById("tv_hud");
      if (hudEl) {{
        const cTxt = d.candles.length ? d.candles[d.candles.length-1].close : "-";
        hudEl.innerHTML = `<span style="color:#38bdf8;font-weight:700;">${{d.tk}}</span> · 종가 <b style="color:#f8fafc;">$${{cTxt}}` +
          (d.cw ? ` · <span style="color:#10b981;">CW $${{d.cw}}</span>` : "") +
          (d.pw ? ` · <span style="color:#ef4444;">PW $${{d.pw}}</span>` : "") +
          (d.zg ? ` · <span style="color:#f59e0b;">γ $${{d.zg}}</span>` : "");
      }}
      let syncingX = false;
      chart.subscribeCrosshairMove(param => {{
        if (!syncingX) {{
          syncingX = true;
          subLinks.forEach(lk => {{
            if (param && param.time) lk.c.setCrosshairPosition(0, param.time, lk.s);
            else lk.c.clearCrosshairPosition();
          }});
          syncingX = false;
        }}
        if (!hudEl || !param || !param.time) return;
        const bar = param.seriesData.get(cs);
        if (!bar) return;
        const chgP = bar.open ? (((bar.close - bar.open) / bar.open) * 100).toFixed(2) : "0.00";
        const colP = bar.close >= bar.open ? "#10b981" : "#ef4444";
        hudEl.innerHTML = `<span style="color:#38bdf8;font-weight:700;">${{d.tk}}</span> · 시 ${{bar.open}} 고 ${{bar.high}} 저 ${{bar.low}} 종 <b style="color:${{colP}};">${{bar.close}} (${{chgP}}%)`;
      }});
      subLinks.forEach(lk => lk.c.subscribeCrosshairMove(param => {{
        if (syncingX) return;
        syncingX = true;
        if (param && param.time) {{
          chart.setCrosshairPosition(0, param.time, cs);
          subLinks.forEach(o => {{ if (o.c !== lk.c) o.c.setCrosshairPosition(0, param.time, o.s); }});
        }} else {{
          chart.clearCrosshairPosition();
          subLinks.forEach(o => {{ if (o.c !== lk.c) o.c.clearCrosshairPosition(); }});
        }}
        syncingX = false;
      }}));
      chart.timeScale().fitContent();
      const initR = chart.timeScale().getVisibleLogicalRange();
      subCharts.forEach(sc => {{ if (initR) sc.timeScale().setVisibleLogicalRange(initR); else sc.timeScale().fitContent(); }});
      let syncing = false;
      chart.timeScale().subscribeVisibleLogicalRangeChange(r => {{
        if (!syncing && r) {{
          syncing = true;
          subCharts.forEach(sc => sc.timeScale().setVisibleLogicalRange(r));
          syncing = false;
        }}
        drawVpvr();
      }});
      subCharts.forEach(sc => sc.timeScale().subscribeVisibleLogicalRangeChange(r => {{
        if (!syncing && r) {{
          syncing = true;
          chart.timeScale().setVisibleLogicalRange(r);
          subCharts.forEach(o => {{ if (o !== sc) o.timeScale().setVisibleLogicalRange(r); }});
          syncing = false;
        }}
      }}));
      setTimeout(drawVpvr, 250);
      // 그리기 도구 (붓 / 추세선 / 수평선 / 메모) + localStorage 저장
      const drCv = document.getElementById("tv_draw");
      const drCtx = drCv.getContext("2d");
      const storeKey = "optionhub_draw_" + d.tk;
      let items = [];
      try {{ items = JSON.parse(localStorage.getItem(storeKey) || "[]"); }} catch(e) {{}}
      let tool = "cursor", drawing = false, curItem = null;

      function resizeDraw() {{
        drCv.width = elMain.clientWidth; drCv.height = 460;
        redraw();
      }}
      function redraw() {{
        drCtx.clearRect(0, 0, drCv.width, drCv.height);
        items.forEach(it => {{
          drCtx.strokeStyle = it.color || "#f59e0b";
          drCtx.fillStyle = it.color || "#f59e0b";
          drCtx.lineWidth = 2;
          if (it.type === "brush" && it.pts.length > 1) {{
            drCtx.beginPath();
            drCtx.moveTo(it.pts[0][0], it.pts[0][1]);
            for (let i=1; i<it.pts.length; i++) drCtx.lineTo(it.pts[i][0], it.pts[i][1]);
            drCtx.stroke();
          }} else if (it.type === "line") {{
            drCtx.beginPath(); drCtx.moveTo(it.x1, it.y1); drCtx.lineTo(it.x2, it.y2); drCtx.stroke();
          }} else if (it.type === "hline") {{
            drCtx.setLineDash([5, 4]);
            drCtx.beginPath(); drCtx.moveTo(0, it.y); drCtx.lineTo(drCv.width, it.y); drCtx.stroke();
            drCtx.setLineDash([]);
          }} else if (it.type === "memo") {{
            drCtx.font = "bold 12px sans-serif";
            const w = drCtx.measureText(it.text).width + 12;
            drCtx.fillStyle = "rgba(15,23,42,0.85)";
            drCtx.fillRect(it.x, it.y - 16, w, 22);
            drCtx.strokeRect(it.x, it.y - 16, w, 22);
            drCtx.fillStyle = it.color || "#f59e0b";
            drCtx.fillText(it.text, it.x + 6, it.y);
          }}
        }});
      }}
      function saveDraw() {{ try {{ localStorage.setItem(storeKey, JSON.stringify(items)); }} catch(e) {{}} }}

      document.querySelectorAll(".tv-tool").forEach(btn => {{
        btn.onclick = () => {{
          tool = btn.dataset.t;
          document.querySelectorAll(".tv-tool").forEach(b => {{
            b.style.background = b === btn ? "#2563eb" : "#1e293b";
            b.style.color = b === btn ? "#fff" : "#e2e8f0";
          }});
          drCv.style.pointerEvents = tool === "cursor" ? "none" : "auto";
          drCv.style.cursor = tool === "cursor" ? "default" : "crosshair";
          const hints = {{cursor:"커서 모드: 차트 줌·이동 가능", brush:"드래그로 자유롭게 그리기", line:"시작점→끝점 드래그로 추세선", hline:"클릭 위치에 수평선 긋기", memo:"클릭 위치에 메모 입력"}};
          document.getElementById("tv_hint").textContent = hints[tool] || "";
        }};
      }});
      document.getElementById("tv_undo").onclick = () => {{ items.pop(); saveDraw(); redraw(); }};
      document.getElementById("tv_clear").onclick = () => {{ items = []; saveDraw(); redraw(); }};

      drCv.onmousedown = e => {{
        const r = drCv.getBoundingClientRect();
        const x = e.clientX - r.left, y = e.clientY - r.top, col = document.getElementById("tv_color").value;
        if (tool === "hline") {{ items.push({{type:"hline", y, color:col}}); saveDraw(); redraw(); return; }}
        if (tool === "memo") {{
          const txt = prompt("차트 메모 입력:");
          if (txt) {{ items.push({{type:"memo", x, y, text:txt, color:col}}); saveDraw(); redraw(); }}
          return;
        }}
        drawing = true;
        curItem = tool === "brush" ? {{type:"brush", pts:[[x,y]], color:col}} : {{type:"line", x1:x, y1:y, x2:x, y2:y, color:col}};
        items.push(curItem);
      }};
      drCv.onmousemove = e => {{
        if (!drawing || !curItem) return;
        const r = drCv.getBoundingClientRect();
        const x = e.clientX - r.left, y = e.clientY - r.top;
        if (curItem.type === "brush") curItem.pts.push([x,y]);
        else {{ curItem.x2 = x; curItem.y2 = y; }}
        redraw();
      }};
      window.addEventListener("mouseup", () => {{ if (drawing) {{ drawing = false; curItem = null; saveDraw(); }} }});
      resizeDraw();
      const fsBtn = document.getElementById("tv_fs");
      const tvWrap = document.getElementById("tv_wrap");
      fsBtn.onclick = () => {{
        if (!document.fullscreenElement) tvWrap.requestFullscreen().catch(() => {{}});
        else document.exitFullscreen().catch(() => {{}});
      }};
      function syncSize() {{
        const isFs = !!document.fullscreenElement;
        const mh = isFs ? Math.max(420, window.innerHeight - 60 - (subCharts.length * 130)) : 460;
        elMain.style.height = mh + "px";
        vpCv.style.height = mh + "px";
        drCv.style.height = mh + "px";
        chart.applyOptions({{ width: elMain.clientWidth, height: mh }});
        subCharts.forEach(sc => sc.applyOptions({{ width: elMain.clientWidth }}));
        drCv.width = elMain.clientWidth; drCv.height = mh; redraw();
        drawVpvr();
      }}
      document.addEventListener("fullscreenchange", syncSize);
      window.addEventListener("resize", syncSize);
    </script>
    """
    components.html(tv_html, height=total_h)

    if show_icc and not icc_df.empty:
        st.subheader("🔄 역시계곡선 (Inverse Clock Curve · 20봉 거래량-가격 순환)")
        fig_icc = go.Figure()
        fig_icc.add_trace(go.Scatter(
            x=icc_df["vol_ma20"], y=icc_df["ma20"], mode="lines+markers",
            line=dict(color="#38bdf8", width=2),
            marker=dict(size=6, color=list(range(len(icc_df))), colorscale="Viridis"),
            name="순환 궤적"
        ))
        fig_icc.add_trace(go.Scatter(
            x=[icc_df["vol_ma20"].iloc[-1]], y=[icc_df["ma20"].iloc[-1]],
            mode="markers+text", text=["현재"], textposition="top center",
            marker=dict(size=12, color="#f59e0b", symbol="star"), name="현재 위치"
        ))
        fig_icc.update_layout(height=300, xaxis_title="거래량 20봉 평균", yaxis_title="종가 20봉 평균 ($)",
                              plot_bgcolor="#0e1117", paper_bgcolor="#0e1117", font_color="#d1d4dc",
                              margin=dict(l=10, r=10, t=10, b=10))
        st.plotly_chart(fig_icc, use_container_width=True)

    # 차트 하단 옵션 체결·레벨 요약 테이블 (TIME / EXP / STRIKE / LEVEL / C/P / B/S / PREM / OI)
    st.subheader(f"📋 {clean_tk} 옵션 분석 표 (GEX → DEX → OI → Vol/OI → Sweep → Premium → Delta/Gamma → DTE)")
    det_lookup = {}
    if clean_tk in oi_hist_m and oi_hist_m[clean_tk]:
        for x_o in oi_hist_m[clean_tk][-1].get("상세", []):
            det_lookup[(str(x_o.get("구분", ""))[0].upper(), float(x_o.get("행사가", 0) or 0))] = x_o
    flow_tbl = []
    today_dt = pd.Timestamp.now(tz="America/New_York").date()
    for rf in [r for r in all_raw_flows if str(r[1]).upper() == clean_tk][:12]:
        cp_c = str(rf[3])[0].upper()
        try:
            sk_v = float(str(rf[7]).replace("$", "").replace(",", ""))
        except Exception:
            sk_v = 0.0
        lv_lbl = "CALL WALL" if (cw_lv and abs(sk_v - float(cw_lv)) < 0.01) else ("PUT WALL" if (pw_lv and abs(sk_v - float(pw_lv)) < 0.01) else ("GAMMA" if (zg_lv and abs(sk_v - float(zg_lv)) < 0.5) else "-"))
        oi_info = det_lookup.get((cp_c, sk_v), {})
        oi_v = int(oi_info.get("OI", 0) or 0)
        vol_v = int(oi_info.get("거래량", 0) or 0)
        voi_s = f"{vol_v/oi_v:.2f}" if oi_v > 0 else "-"
        try:
            dte_v = max(0, (pd.to_datetime(str(rf[5])).date() - today_dt).days)
        except Exception:
            dte_v = "-"
        flow_tbl.append({
            "TIME": rf[2],
            "STRIKE(C/P)": f"${sk_v:g}{cp_c}" if sk_v else f"{rf[7]}{cp_c}",
            "LEVEL": lv_lbl,
            "GEX": f"${oi_info.get('GEX($M)', 0):+.2f}M" if oi_info else "-",
            "DEX": f"${oi_info.get('DEX($M)', 0):+.2f}M" if oi_info else "-",
            "OI": f"{oi_v:,}" if oi_info else "-",
            "Vol/OI": voi_s,
            "Sweep(Side)": f"{rf[13]} · {'Ask' if 'A' in str(rf[4]) else 'Bid'}",
            "Premium": rf[14],
            "Delta/Gamma": f"{oi_info.get('Delta', 0):.2f} / {oi_info.get('Gamma', 0):.4f}" if oi_info else "-",
            "DTE": f"{dte_v}d ({str(rf[5])[-5:]})" if dte_v != "-" else str(rf[5])[-5:],
        })
    if not flow_tbl and clean_tk in oi_hist_m and oi_hist_m[clean_tk]:
        top_det = sorted(oi_hist_m[clean_tk][-1].get("상세", []), key=lambda x: abs(float(x.get("GEX($M)", 0) or 0)), reverse=True)[:10]
        for x_o in top_det:
            sk_v = float(x_o.get("행사가", 0) or 0)
            cp_c = str(x_o.get("구분", "C"))[0].upper()
            lv_lbl = "CALL WALL" if (cw_lv and abs(sk_v - float(cw_lv)) < 0.01) else ("PUT WALL" if (pw_lv and abs(sk_v - float(pw_lv)) < 0.01) else "-")
            oi_v = int(x_o.get("OI", 0) or 0)
            vol_v = int(x_o.get("거래량", 0) or 0)
            try:
                dte_v = max(0, (pd.to_datetime(str(x_o.get("만기", ""))).date() - today_dt).days)
            except Exception:
                dte_v = "-"
            flow_tbl.append({
                "TIME": oi_hist_m[clean_tk][-1].get("수집시각", "-").split(" ")[-1],
                "STRIKE(C/P)": f"${sk_v:g}{cp_c}",
                "LEVEL": lv_lbl,
                "GEX": f"${float(x_o.get('GEX($M)', 0) or 0):+.2f}M",
                "DEX": f"${float(x_o.get('DEX($M)', 0) or 0):+.2f}M",
                "OI": f"{oi_v:,}",
                "Vol/OI": f"{vol_v/oi_v:.2f}" if oi_v > 0 else "-",
                "Sweep(Side)": "-",
                "Premium": f"IV {float(x_o.get('IV(%)', 0) or 0):.1f}%",
                "Delta/Gamma": f"{float(x_o.get('Delta', 0) or 0):.2f} / {float(x_o.get('Gamma', 0) or 0):.4f}",
                "DTE": f"{dte_v}d ({str(x_o.get('만기', '-'))[-5:]})" if dte_v != "-" else str(x_o.get("만기", "-"))[-5:],
            })
    if flow_tbl:
        st.dataframe(pd.DataFrame(flow_tbl), use_container_width=True, hide_index=True)
    else:
        st.caption(f"{clean_tk} 최근 옵션 체결 내역이 아직 없습니다. (OI 수집 탭에서 스냅샷 수집 시 자동 표시됩니다.)")

    # 1~5 통합 알림 및 n8n Webhook 설정
    N8N_CFG_PATH = os.path.expanduser("~/.optionhub_n8n_cfg.json")
    ALERT_SENT_PATH = os.path.expanduser("~/.optionhub_alert_sent.json")
    FLOW_HIST_PATH = os.path.expanduser("~/.optionhub_moomoo_flow_hist.json")
    n8n_cfg = load_json_file(N8N_CFG_PATH, {"url": "", "auto": True})
    sent_alerts = set(load_json_file(ALERT_SENT_PATH, []))

    def push_n8n_and_tg(ev_key, ev_title, ev_msg, payload_extra=None):
        if ev_key in sent_alerts:
            return
        sent_alerts.add(ev_key)
        save_json_file(ALERT_SENT_PATH, list(sent_alerts)[-400:])
        if n8n_cfg.get("auto") and tg_token and tg_chat_id:
            send_telegram_msg(tg_token, tg_chat_id, f"{ev_title}\n{ev_msg}\n🌐 http://132.226.3.145:8501")
        hook_u = str(n8n_cfg.get("url", "")).strip()
        if hook_u.startswith("http"):
            try:
                body = json.dumps({"title": ev_title, "message": ev_msg, "ticker": clean_tk, "price": cur.get("px", 0), "extra": payload_extra or {}}).encode("utf-8")
                req = urllib.request.Request(hook_u, data=body, headers={"Content-Type": "application/json"})
                urllib.request.urlopen(req, timeout=5)
            except Exception:
                pass

    # 3) 핵심 레벨 ±0.3% 터치 경보 + 4) 프리마켓·야간 급변동(±1.5%) 스캐너
    live_alerts = []
    px_now = float(cur.get("px", 0) or 0)
    if px_now > 0:
        for lv_name, lv_val in [("Call Wall", cw_lv), ("Put Wall", pw_lv), ("Zero Gamma", zg_lv), ("SIG_H", sig_h_lv), ("SIG_L", sig_l_lv)]:
            if lv_val and float(lv_val) > 0:
                diff_r = abs(px_now - float(lv_val)) / float(lv_val) * 100.0
                if diff_r <= 0.3:
                    t_msg = f"🎯 [{clean_tk}] {lv_name} ${float(lv_val):g} 터치! (현재가 ${px_now:,.2f}, 차이 {diff_r:.2f}%)"
                    live_alerts.append(t_msg)
                    push_n8n_and_tg(f"LV|{clean_tk}|{lv_name}|{int(time.time()//1800)}", "🎯 OptionHub 레벨 터치 경보", t_msg, {"level": lv_name, "target": float(lv_val)})

    surge_list = []
    for pq in parsed_q:
        chg_p = pq.get("등락률(%)")
        if chg_p is not None and abs(float(chg_p)) >= 1.5:
            s_tk_q = str(pq.get("종목", "")).split(".")[-1]
            s_msg = f"🌅 [{s_tk_q}] 급변동 {float(chg_p):+.2f}% (현재가 ${pq.get('현재가($)', 0)})"
            surge_list.append(s_msg)
            push_n8n_and_tg(f"SRG|{s_tk_q}|{int(time.time()//3600)}", "🌅 OptionHub 프리마켓·야간 급변동", s_msg, {"chg_pct": float(chg_p)})

    col_b1, col_b2 = st.columns(2)
    with col_b1:
        st.subheader("🧱 실시간 60호가 매수·매도 벽 & LV3 불균형")
        bk = aux_map.get("book") or {}
        bids = bk.get("Bid") or bk.get("bids") or []
        asks = bk.get("Ask") or bk.get("asks") or []
        if bids or asks:
            b_pts = [(float(x[0]), float(x[1])) for x in bids[:15] if len(x) >= 2]
            a_pts = [(float(x[0]), float(x[1])) for x in asks[:15] if len(x) >= 2]
            b_tot10 = sum(v for _, v in b_pts[:10])
            a_tot10 = sum(v for _, v in a_pts[:10])
            if b_tot10 > 0 and a_tot10 > 0:
                ba_ratio = b_tot10 / a_tot10
                if ba_ratio >= 2.0:
                    st.success(f"🟢 LV3 매수벽 {ba_ratio:.2f}배 우위 (매수 {int(b_tot10):,} vs 매도 {int(a_tot10):,})")
                    push_n8n_and_tg(f"IMB|B|{clean_tk}|{int(time.time()//1800)}", "🧱 LV3 매수벽 2배 이상 우위", f"[{clean_tk}] 매수잔량 {int(b_tot10):,} vs 매도잔량 {int(a_tot10):,} ({ba_ratio:.2f}배)", {"ratio": round(ba_ratio, 2)})
                elif ba_ratio <= 0.5:
                    st.error(f"🔴 LV3 매도벽 {(1/ba_ratio):.2f}배 우위 (매수 {int(b_tot10):,} vs 매도 {int(a_tot10):,})")
                    push_n8n_and_tg(f"IMB|S|{clean_tk}|{int(time.time()//1800)}", "🧱 LV3 매도벽 2배 이상 우위", f"[{clean_tk}] 매도잔량 {int(a_tot10):,} vs 매수잔량 {int(b_tot10):,} ({1/ba_ratio:.2f}배)", {"ratio": round(ba_ratio, 2)})
                else:
                    st.info(f"⚖️ 10호가 잔량 균형: 매수 {int(b_tot10):,} / 매도 {int(a_tot10):,} ({ba_ratio:.2f}x)")
            fig_bk = go.Figure()
            if b_pts:
                fig_bk.add_trace(go.Bar(y=[f"${p:g}" for p, _ in b_pts], x=[v for _, v in b_pts], orientation="h", name="매수잔량(Bid)", marker_color="#10b981"))
            if a_pts:
                fig_bk.add_trace(go.Bar(y=[f"${p:g}" for p, _ in a_pts], x=[-v for _, v in a_pts], orientation="h", name="매도잔량(Ask)", marker_color="#ef4444"))
            fig_bk.update_layout(height=340, barmode="relative", plot_bgcolor="#0e1117", paper_bgcolor="#0e1117", font_color="#d1d4dc", margin=dict(l=10, r=10, t=10, b=10))
            st.plotly_chart(fig_bk, use_container_width=True)
        else:
            st.caption("호가창(book) 데이터가 수신되면 매수/매도 잔량 벽과 불균형 신호가 표시됩니다.")

    with col_b2:
        st.subheader("💰 실시간 자금 유입/유출 분포 & 누적 곡선")
        fl = aux_map.get("flow") or {}
        flow_hist_all = load_json_file(FLOW_HIST_PATH, {})
        tk_fh = flow_hist_all.get(clean_tk, [])
        if isinstance(fl, dict) and fl:
            net_big = float(fl.get("inB", 0) or 0) - float(fl.get("outB", 0) or 0)
            net_mid = float(fl.get("inM", 0) or 0) - float(fl.get("outM", 0) or 0)
            net_sml = float(fl.get("inS", fl.get("inSm", 0)) or 0) - float(fl.get("outS", fl.get("outSm", 0)) or 0)
            t_now_fl = pd.Timestamp.now(tz="Asia/Seoul").strftime("%H:%M")
            if not tk_fh or tk_fh[-1].get("t") != t_now_fl:
                tk_fh.append({"t": t_now_fl, "대형": round(net_big, 1), "중형": round(net_mid, 1), "소형": round(net_sml, 1)})
                flow_hist_all[clean_tk] = tk_fh[-120:]
                save_json_file(FLOW_HIST_PATH, flow_hist_all)
            st.markdown(f"**대형 순유입:** `{net_big:+,.0f}` · **중형:** `{net_mid:+,.0f}` · **소형:** `{net_sml:+,.0f}`")
        if tk_fh:
            df_fh = pd.DataFrame(tk_fh)
            fig_fh = go.Figure()
            fig_fh.add_trace(go.Scatter(x=df_fh["t"], y=df_fh["대형"], mode="lines+markers", name="대형(Big)", line=dict(color="#10b981", width=2)))
            fig_fh.add_trace(go.Scatter(x=df_fh["t"], y=df_fh["중형"], mode="lines", name="중형(Mid)", line=dict(color="#38bdf8", width=1.5)))
            fig_fh.add_trace(go.Scatter(x=df_fh["t"], y=df_fh["소형"], mode="lines", name="소형(Small)", line=dict(color="#f59e0b", width=1.5, dash="dot")))
            fig_fh.update_layout(height=280, plot_bgcolor="#0e1117", paper_bgcolor="#0e1117", font_color="#d1d4dc", margin=dict(l=10, r=10, t=10, b=10), legend=dict(orientation="h", y=1.08))
            st.plotly_chart(fig_fh, use_container_width=True)
        elif isinstance(fl, dict) and fl:
            st.json(fl)
        else:
            st.caption("자금분포(flow) 데이터 수신 대기 중 (3분 주기)")

    if live_alerts or surge_list:
        st.warning(" | ".join(live_alerts + surge_list))

    with st.expander("🔗 n8n Webhook & 자동 경보 설정 (레벨 터치 · 매수벽 · 급변동 · 큰손 풋/콜)", expanded=False):
        n_c1, n_c2, n_c3 = st.columns([2.4, 0.9, 0.9])
        new_n8n_url = n_c1.text_input("n8n Webhook URL", value=n8n_cfg.get("url", ""), placeholder="http://127.0.0.1:5678/webhook/optionhub", key="n8n_hook_inp")
        new_n8n_auto = n_c2.checkbox("텔레그램+n8n 자동전송", value=n8n_cfg.get("auto", True), key="n8n_auto_chk")
        if n_c3.button("💾 저장/테스트", use_container_width=True):
            save_json_file(N8N_CFG_PATH, {"url": new_n8n_url.strip(), "auto": new_n8n_auto})
            if new_n8n_url.strip().startswith("http"):
                try:
                    req = urllib.request.Request(new_n8n_url.strip(), data=json.dumps({"test": True, "ticker": clean_tk, "price": px_now}).encode("utf-8"), headers={"Content-Type": "application/json"})
                    urllib.request.urlopen(req, timeout=5)
                    st.success("✅ n8n Webhook 저장 및 테스트 전송 성공!")
                except Exception as e_n8n:
                    st.error(f"n8n 연결 확인 필요: {e_n8n}")
            else:
                st.success("✅ 설정이 저장되었습니다!")

    # 🐋 무무·실시간 큰손 풋/콜 누적 & 텔레그램 경보
    st.subheader("🐋 무무 · 실시간 큰손 풋/콜 누적 & 텔레그램 경보")
    WHALE_LOG_PATH = os.path.expanduser("~/.optionhub_whale_log.json")
    whale_data = load_json_file(WHALE_LOG_PATH, {"items": [], "sent": []})
    w_items = whale_data.get("items", [])
    w_sent = set(whale_data.get("sent", []))
    wc1, wc2 = st.columns([2, 1])
    with wc1:
        auto_tg_whale = st.checkbox("📩 강한 콜/풋 포착 시 텔레그램 자동 발송 (중복 방지)", value=True, key="mm_auto_tg_whale")
    with wc2:
        send_whale_now = st.button("📤 큰손 풋/콜 지금 텔레그램 전송", use_container_width=True)

    new_whales = []
    # 1) 무무 aux 테이블 내 옵션/체결 데이터 확인
    if con is not None:
        try:
            aux_w_rows = con.execute("SELECT sym, kind, ts, data FROM aux WHERE kind LIKE '%opt%' OR kind IN ('opt_flow','opt_hot','ticker') ORDER BY ts DESC LIMIT 30").fetchall()
            for w_sym, w_kind, w_ts, w_txt in aux_w_rows:
                try:
                    w_obj = json.loads(w_txt) if w_txt else {}
                except Exception:
                    w_obj = {}
                arr_w = w_obj if isinstance(w_obj, list) else (w_obj.get("items") or w_obj.get("data") or [w_obj])
                for it_w in arr_w:
                    if not isinstance(it_w, dict): continue
                    cp_w = str(it_w.get("option_type") or it_w.get("cp") or it_w.get("type") or "").upper()
                    if "CALL" in cp_w or "PUT" in cp_w or "opt" in str(w_kind).lower():
                        t_s = pd.to_datetime(w_ts, unit="s", utc=True).tz_convert("Asia/Seoul").strftime("%m-%d %H:%M")
                        stk_w = it_w.get("strike") or it_w.get("strike_price") or "-"
                        prem_w = float(it_w.get("premium") or it_w.get("turnover") or 0)
                        k_id = f"MM|{w_sym}|{cp_w}|{stk_w}|{int(prem_w)}"
                        new_whales.append({"id": k_id, "시각": t_s, "소스": "무무", "종목": w_sym.split(".")[-1], "구분": "🟢 강한 콜" if "CALL" in cp_w else "🔴 강한 풋", "행사가": f"${stk_w}", "거래량": int(it_w.get("volume") or 0), "Vol/OI": "-", "GEX($M)": "-", "추정규모": f"${prem_w:,.0f}" if prem_w else "-"})
        except Exception:
            pass

    # 2) 실시간 옵션 체인(yfinance) 강한 콜/풋 스캔 (Vol/OI >= 1.5 & 거래량 >= 200)
    try:
        y_rows_w, y_sp_w = _cached_opt_snapshot(clean_tk)
        if y_rows_w:
            now_kst_w = pd.Timestamp.now(tz="Asia/Seoul").strftime("%m-%d %H:%M")
            for r_w in y_rows_w:
                vol_w = int(r_w.get("거래량", 0) or 0)
                oi_w = int(r_w.get("OI", 0) or 0)
                voi_w = (vol_w / oi_w) if oi_w > 0 else 0.0
                gex_w = abs(float(r_w.get("GEX($M)", 0) or 0))
                if vol_w >= 200 and (voi_w >= 1.5 or gex_w >= 0.5):
                    cp_w = str(r_w.get("구분", "Call"))
                    stk_w = r_w.get("행사가", 0)
                    exp_w = str(r_w.get("만기", "-"))[-5:]
                    k_id = f"YF|{clean_tk}|{cp_w}|{stk_w}|{exp_w}|{vol_w}"
                    new_whales.append({
                        "id": k_id, "시각": now_kst_w, "소스": "실시간옵션", "종목": clean_tk,
                        "구분": "🟢 강한 콜" if cp_w == "Call" else "🔴 강한 풋",
                        "행사가": f"${stk_w:g} ({exp_w})", "거래량": f"{vol_w:,}",
                        "Vol/OI": f"{voi_w:.2f}x", "GEX($M)": f"{float(r_w.get('GEX($M)', 0)):+.2f}M",
                        "추정규모": f"OI {oi_w:,}"
                    })
    except Exception:
        pass

    existing_ids = {x.get("id") for x in w_items}
    added_for_tg = []
    for nw in new_whales[:20]:
        if nw["id"] not in existing_ids:
            w_items.insert(0, nw)
            existing_ids.add(nw["id"])
            if nw["id"] not in w_sent:
                added_for_tg.append(nw)
    w_items = w_items[:150]

    if ((auto_tg_whale and added_for_tg) or send_whale_now) and tg_token and tg_chat_id:
        send_targets = added_for_tg[:5] if (auto_tg_whale and added_for_tg and not send_whale_now) else w_items[:5]
        if send_targets:
            lines_tg = [f"🐋 [{clean_tk} 큰손 풋/콜 경보]"]
            for it_t in send_targets:
                lines_tg.append(f"• {it_t['구분']} {it_t['종목']} {it_t['행사가']} | 거래량 {it_t['거래량']} | Vol/OI {it_t['Vol/OI']} | GEX {it_t['GEX($M)']} ({it_t['소스']})")
                w_sent.add(it_t["id"])
            ok_tg, err_tg = send_telegram_msg(tg_token, tg_chat_id, "\n".join(lines_tg))
            if ok_tg and send_whale_now:
                st.success("✅ 텔레그램으로 큰손 풋/콜 경보를 전송했습니다!")
            elif not ok_tg and send_whale_now:
                st.error(f"텔레그램 전송 실패: {err_tg}")

    save_json_file(WHALE_LOG_PATH, {"items": w_items, "sent": list(w_sent)[-300:]})
    if w_items:
        disp_w = [{k: v for k, v in x.items() if k != "id"} for x in w_items[:30]]
        st.dataframe(pd.DataFrame(disp_w), use_container_width=True, hide_index=True)
    else:
        st.caption("아직 포착된 큰손 풋/콜 내역이 없습니다. (장중 Vol/OI 1.5x 이상 또는 무무 옵션 체결 시 자동 누적)")

    if auto_rf:
        components.html(
            """<script>
            setTimeout(function(){
              const btns = window.parent.document.querySelectorAll('button');
              for (const b of btns) {
                if ((b.innerText || '').includes('실시간 새로고침')) { b.click(); break; }
              }
            }, 5000);
            </script>""",
            height=0,
        )

    if parsed_q:
        st.subheader("📋 전체 수신 종목 실시간 시세표")
        st.dataframe(pd.DataFrame(parsed_q), use_container_width=True, hide_index=True)
    if con is not None:
        con.close()


# ================= TAB POS: NEXT WEEK & FAR MONTH POSITIONS =================
if nav_menu == "📌 다음 주·원월 포지션":
    import math
    import yfinance as yf
    from datetime import datetime

    st.title("📌 종목별 다음 주 · 원월 포지션 (계약 누적 & OPEN/CLOSE)")
    st.caption("다음 주(5~14 DTE)와 원월(25+ DTE) 주요 계약의 수량·OI 변화·총 PREM·|GEX| 1% 및 시트 시간순 플로우를 한눈에 봅니다.")

    c_p1, c_p2 = st.columns([2, 1])
    with c_p1:
        preset_tk = st.selectbox("종목 선택", ["SOXL", "NVDA", "TSLA", "MU", "AMD", "SMH", "SOXS", "SPY", "QQQ", "META", "AAPL", "직접 입력"], index=0)
    with c_p2:
        custom_tk = st.text_input("직접 입력 (선택 시)", value="").strip().upper()
    target_tk = custom_tk if (preset_tk == "직접 입력" and custom_tk) else ("SOXL" if preset_tk == "직접 입력" else preset_tk)

    if st.button(f"🔍 {target_tk} 다음 주·원월 포지션 스캔", type="primary"):
        with st.spinner(f"{target_tk} 옵션 체인 및 OI 히스토리 분석 중..."):
            try:
                yf_sym = {"SPX": "^SPX", "NDX": "^NDX", "VIX": "^VIX", "RUT": "^RUT"}.get(target_tk, target_tk)
                t_obj = yf.Ticker(yf_sym)
                exps = list(t_obj.options or [])
                spot = 0.0
                try:
                    spot = round(float(t_obj.fast_info.get("lastPrice", 0) or 0), 2)
                except Exception:
                    pass

                now_d = datetime.now()
                sel_exps = []
                near_exps = [e for e in exps if 4 <= (datetime.strptime(e, "%Y-%m-%d") - now_d).days <= 16]
                far_exps = [e for e in exps if (datetime.strptime(e, "%Y-%m-%d") - now_d).days >= 25]
                if not near_exps and exps:
                    near_exps = exps[:2]
                sel_exps = near_exps[:2] + far_exps[:2]

                oi_hist_p = load_json_file(OI_PATH, {})
                prev_oi_map = {}
                if target_tk in oi_hist_p and oi_hist_p[target_tk]:
                    for x_p in oi_hist_p[target_tk][-1].get("상세", []):
                        prev_oi_map[(x_p.get("만기"), x_p.get("구분"), float(x_p.get("행사가", 0)))] = int(x_p.get("OI", 0))

                rows_pos = []
                for exp in sel_exps:
                    d_days = max((datetime.strptime(exp, "%Y-%m-%d") - now_d).days, 1)
                    T_y = d_days / 365.0
                    ch = t_obj.option_chain(exp)
                    for cp, df_s in [("CALL", ch.calls), ("PUT", ch.puts)]:
                        cp_kor = "Call" if cp == "CALL" else "Put"
                        for _, r_o in df_s.iterrows():
                            vol = 0 if pd.isna(r_o.get("volume")) else int(r_o.get("volume"))
                            oi = 0 if pd.isna(r_o.get("openInterest")) else int(r_o.get("openInterest"))
                            if vol < 50 and oi < 200:
                                continue
                            k = float(r_o["strike"])
                            lp = 0.0 if pd.isna(r_o.get("lastPrice")) else float(r_o.get("lastPrice") or 0)
                            bid = 0.0 if pd.isna(r_o.get("bid")) else float(r_o.get("bid") or 0)
                            ask = 0.0 if pd.isna(r_o.get("ask")) else float(r_o.get("ask") or 0)
                            iv = 0.45 if pd.isna(r_o.get("impliedVolatility")) else float(r_o.get("impliedVolatility") or 0.45)
                            iv = max(0.05, min(iv, 3.0))

                            prem_tot = vol * lp * 100.0
                            p_oi = prev_oi_map.get((exp, cp_kor, k), oi)

                            # |GEX| 1%
                            gex_1pct = 0.0
                            if spot > 0 and oi > 0:
                                d1 = (math.log(spot / k) + (0.045 + 0.5 * iv * iv) * T_y) / (iv * math.sqrt(T_y))
                                gamma = math.exp(-0.5 * d1 * d1) / (math.sqrt(2 * math.pi) * spot * iv * math.sqrt(T_y))
                                gex_1pct = abs(gamma * oi * 100.0 * spot * spot * 0.01)

                            # Direction & OPEN/CLOSE hint
                            tags = []
                            if oi >= 10 and vol > oi and (vol - oi) >= 300:
                                tags.append(f"🟢 신규OPEN(≥{vol - oi:,})")
                            elif p_oi > 0 and oi < p_oi and (p_oi - oi) >= 100:
                                tags.append(f"🔴 CLOSE({oi - p_oi:,})")
                            if ask > bid > 0 and lp > 0:
                                if lp >= ask * 0.98:
                                    tags.append("BUY 우위")
                                elif lp <= bid * 1.02:
                                    tags.append("SELL 우위")
                                else:
                                    tags.append("MID 혼재")
                            if not tags:
                                tags.append("관찰")

                            rows_pos.append({
                                "EXP ET": exp[2:].replace("-", "/"),
                                "계약": f"{k:g} {cp}",
                                "방향·개폐 추정": " · ".join(tags),
                                "OI 이전→최신": f"{p_oi:,} → {oi:,}",
                                "수량(Vol)": vol,
                                "최종 1계약": f"${lp * 100:,.2f}",
                                "총 PREM": f"${prem_tot / 1e6:.2f}M" if prem_tot >= 1e6 else f"${prem_tot / 1e3:.1f}K",
                                "|GEX|·1%": f"${gex_1pct / 1e3:.1f}K" if gex_1pct >= 1e3 else f"${gex_1pct:,.0f}",
                                "_sort": prem_tot,
                            })

                if rows_pos:
                    st.success(f"📊 {target_tk} (현재가 ${spot}) · 만기 {len(sel_exps)}개 기준 주요 계약 TOP 20")
                    df_pos = pd.DataFrame(rows_pos).sort_values("_sort", ascending=False).drop(columns=["_sort"]).head(20)
                    st.dataframe(df_pos, use_container_width=True, hide_index=True)
                else:
                    st.warning("조회된 옵션 계약이 없습니다.")
            except Exception as e_p:
                st.error(f"조회 오류: {e_p}")

    st.markdown("---")
    st.subheader(f"⏱ {target_tk} 시트 누적 플로우 (시간순 연결 참고)")
    tk_flows = [
        {"시각": r[0], "만기": r[5], "계약": f"{r[3]} {r[7]}", "프리미엄": r[14], "유형/특징": r[13]}
        for r in all_raw_flows if str(r[1]).upper() == target_tk
    ]
    if tk_flows:
        st.dataframe(pd.DataFrame(tk_flows[:20]), use_container_width=True, hide_index=True)
    else:
        st.caption(f"구글 시트 `전체` 탭에 저장된 {target_tk} 플로우가 아직 없습니다.")


def _oi_pro_calc(oi_tk, snaps, df_det, spot_val, all_raw_flows, saved_big_flows):
    import datetime as _dt
    latest = snaps[-1] if snaps else {}
    call_oi = float(latest.get("Call_OI", 0) or 0)
    put_oi = float(latest.get("Put_OI", 0) or 0)
    tot_oi = call_oi + put_oi

    def _avg_chg(days_back):
        if len(snaps) < 2:
            return None
        hist_slice = snaps[:-1][-days_back:] if len(snaps) > 1 else []
        if not hist_slice:
            return None
        avg_prev = sum(float(s.get("Call_OI", 0) or 0) + float(s.get("Put_OI", 0) or 0) for s in hist_slice) / len(hist_slice)
        if avg_prev <= 0:
            return None
        return round((tot_oi - avg_prev) / avg_prev * 100.0, 2)

    chg_1d = _avg_chg(1)
    chg_3d = _avg_chg(3)
    chg_5d = _avg_chg(5)
    chg_20d = _avg_chg(20)

    d_call = (call_oi - float(snaps[-2].get("Call_OI", 0) or 0)) if len(snaps) >= 2 else 0.0
    d_put = (put_oi - float(snaps[-2].get("Put_OI", 0) or 0)) if len(snaps) >= 2 else 0.0

    # Structural levels from df_det
    cw, pw, max_pain, gex_flip = spot_val, spot_val, spot_val, spot_val
    call_top3, put_top3 = [], []
    tot_vol, call_vol, put_vol = 0.0, 0.0, 0.0
    net_gex_m = float(latest.get("Net_GEX_M", 0.0) or 0.0)
    tot_prem_usd = 0.0

    if not df_det.empty:
        _df_valid = df_det.copy()
        if spot_val > 0:
            _df_near = _df_valid[(_df_valid["행사가"] >= spot_val * 0.40) & (_df_valid["행사가"] <= spot_val * 2.20)]
            if not _df_near.empty:
                _df_valid = _df_near
        c_df = _df_valid[_df_valid["구분"] == "Call"]
        p_df = _df_valid[_df_valid["구분"] == "Put"]
        if not c_df.empty:
            c_by_k = c_df.groupby("행사가").agg(oi=("OI", "sum"), gex=("GEX($M)", "sum"), vol=("거래량", "sum"))
            cw = float(c_by_k["gex"].idxmax()) if c_by_k["gex"].max() > 0 else float(c_by_k["oi"].idxmax())
            call_top3 = [f"{k:g} ({int(v):,})" for k, v in c_by_k["oi"].sort_values(ascending=False).head(3).items()]
            call_vol = float(c_df["거래량"].sum())
        if not p_df.empty:
            p_by_k = p_df.groupby("행사가").agg(oi=("OI", "sum"), gex=("GEX($M)", "sum"), vol=("거래량", "sum"))
            pw = float(p_by_k["gex"].idxmin()) if p_by_k["gex"].min() < 0 else float(p_by_k["oi"].idxmax())
            put_top3 = [f"{k:g} ({int(v):,})" for k, v in p_by_k["oi"].sort_values(ascending=False).head(3).items()]
            put_vol = float(p_df["거래량"].sum())
        tot_vol = call_vol + put_vol
        if "프리미엄($)" in df_det.columns:
            tot_prem_usd = float(df_det["프리미엄($)"].sum())

        # GEX Flip
        n_by_k = _df_valid.groupby("행사가")["GEX($M)"].sum().sort_index()
        cum = n_by_k.cumsum()
        ks = list(cum.index)
        vals = list(cum.values)
        flips = []
        for i in range(1, len(ks)):
            if (vals[i - 1] < 0 <= vals[i]) or (vals[i - 1] > 0 >= vals[i]):
                denom = vals[i] - vals[i - 1]
                frac = (-vals[i - 1] / denom) if denom != 0 else 0.5
                flips.append(float(ks[i - 1] + frac * (ks[i] - ks[i - 1])))
        if flips and spot_val > 0:
            gex_flip = min(flips, key=lambda x: abs(x - spot_val))

        # Max Pain
        all_ks = sorted(_df_valid["행사가"].unique())
        c_oi_map = c_df.groupby("행사가")["OI"].sum() if not c_df.empty else pd.Series(dtype=float)
        p_oi_map = p_df.groupby("행사가")["OI"].sum() if not p_df.empty else pd.Series(dtype=float)
        best_pain, best_k = None, spot_val
        for kc in all_ks:
            cp_sum = sum(max(kc - k, 0.0) * v for k, v in c_oi_map.items())
            pp_sum = sum(max(k - kc, 0.0) * v for k, v in p_oi_map.items())
            if best_pain is None or (cp_sum + pp_sum) < best_pain:
                best_pain, best_k = (cp_sum + pp_sum), float(kc)
        max_pain = best_k

    _c_oi_eff = float(c_df["OI"].sum()) if (not df_det.empty and not c_df.empty) else call_oi
    _p_oi_eff = float(p_df["OI"].sum()) if (not df_det.empty and not p_df.empty) else put_oi
    _t_oi_eff = _c_oi_eff + _p_oi_eff
    vol_oi = round(tot_vol / _t_oi_eff, 2) if _t_oi_eff >= 10 else 0.0
    call_vol_oi = round(call_vol / _c_oi_eff, 2) if _c_oi_eff >= 10 else 0.0
    put_vol_oi = round(put_vol / _p_oi_eff, 2) if _p_oi_eff >= 10 else 0.0

    # Sheet + TG big flow signals for this ticker
    tk_flows = []
    for r in (all_raw_flows or []):
        if str(r[1]).upper() == oi_tk:
            ch_txt = str(r[13] if len(r) > 13 else "").upper()
            side_raw = str(r[4] if len(r) > 4 else "").upper()
            ab = "Above Ask" if "AA" in ch_txt or "ABOVE" in ch_txt else ("At Ask" if "A" in side_raw else ("Below Bid" if "BB" in ch_txt else ("At Bid" if "B" in side_raw else "Mid")))
            otype = "Sweep" if "SWEEP" in ch_txt else ("Block" if "BLOCK" in ch_txt else ("Split" if "SPLIT" in ch_txt else "Single"))
            tk_flows.append({"ab": ab, "type": otype, "cp": str(r[3]).capitalize(), "prem": parse_prem_usd(r[14] if len(r) > 14 else "0"), "exp": str(r[5]), "k": str(r[7])})
    for b in (saved_big_flows or []):
        if b.get("tk") == oi_tk:
            for r in b.get("records", []):
                tag_u = str(r.get("tag", "")).upper()
                sd_u = str(r.get("side", "")).upper()
                ab = "At Ask" if sd_u == "BUY" else ("At Bid" if sd_u == "SELL" else "Mid")
                otype = "Sweep" if "SWEEP" in tag_u else ("Block" if "BLOCK" in tag_u else ("Split" if "SPLIT" in tag_u else "Single"))
                tk_flows.append({"ab": ab, "type": otype, "cp": r.get("cp", "Call"), "prem": float(r.get("prem_m", 0)) * 1e6, "exp": r.get("exp", ""), "k": str(r.get("strike", ""))})

    has_above_ask_sweep = any(f["type"] == "Sweep" and "Ask" in f["ab"] for f in tk_flows)
    has_sweep = any(f["type"] == "Sweep" for f in tk_flows)
    flow_prem_sum = sum(f["prem"] for f in tk_flows)
    disp_prem_m = round(max(tot_prem_usd, flow_prem_sum) / 1e6, 2)

    # Conviction Score (0~100): OI 증가율 25% + Vol/OI 20% + Premium 20% + Ask/Bid 15% + Sweep/Block 10% + DTE 10%
    sc_oi = min(25.0, max(0.0, (chg_1d or 0.0) * 1.25)) if (chg_1d or 0.0) > 0 else 10.0
    sc_voi = min(20.0, vol_oi * 4.0)
    sc_prem = min(20.0, disp_prem_m * 4.0)
    sc_ab = 15.0 if has_above_ask_sweep else (11.0 if tk_flows else 7.0)
    sc_swp = 10.0 if has_sweep else (7.0 if any(f["type"] == "Block" for f in tk_flows) else 4.0)
    sc_dte = 10.0 if (not df_det.empty and "DTE" in df_det.columns and (df_det["DTE"] <= 35).any()) else 7.0
    conviction = int(min(100, max(10, round(sc_oi + sc_voi + sc_prem + sc_ab + sc_swp + sc_dte))))

    # AI 판독
    reasons = []
    bull_pts, bear_pts = 0, 0
    if d_call > 0:
        reasons.append("Call OI 증가"); bull_pts += 2
    elif d_call < 0:
        reasons.append("Call OI 감소"); bear_pts += 1
    if d_put < 0:
        reasons.append("Put OI 감소"); bull_pts += 2
    elif d_put > 0:
        reasons.append("Put OI 증가"); bear_pts += 2
    if call_vol_oi >= 3.0:
        reasons.append(f"Call Vol/OI {call_vol_oi:.1f}(>3)"); bull_pts += 2
    if put_vol_oi >= 3.0:
        reasons.append(f"Put Vol/OI {put_vol_oi:.1f}(>3)"); bear_pts += 2
    if has_above_ask_sweep:
        reasons.append("Above Ask Sweep 발생"); bull_pts += 2
    if net_gex_m >= 0:
        reasons.append("양(+)감마 안정"); bull_pts += 1
    else:
        reasons.append("음(-)감마 변동성"); bear_pts += 1

    if bull_pts >= bear_pts + 2:
        ai_emo, ai_dir, ai_prob = "🟢", "강세", min(92, 55 + (bull_pts - bear_pts) * 5)
        p_up, p_flat = ai_prob, max(5, round((100 - ai_prob) * 0.65))
        p_down = max(0, 100 - p_up - p_flat)
        ai_intent = "기관 매집 가능성 높음"
    elif bear_pts >= bull_pts + 2:
        ai_emo, ai_dir, ai_prob = "🔴", "약세", min(92, 55 + (bear_pts - bull_pts) * 5)
        p_down, p_flat = ai_prob, max(5, round((100 - ai_prob) * 0.65))
        p_up = max(0, 100 - p_down - p_flat)
        ai_intent = "하방 헷지·매도 압력 우위"
    else:
        ai_emo, ai_dir, ai_prob = "🟡", "중립", 52
        p_flat, p_up, p_down = 52, 24, 24
        ai_intent = "콜·풋 양방향 대치 (박스권/돌파 대기)"

    voi_badge = "🟢 Vol/OI > 3 (신규포지션)" if vol_oi > 3 else ("⚪ Vol/OI < 1 (기존포지션)" if vol_oi < 1 else "🟡 Vol/OI 1~3 (회전)")
    dealer_lbl = "양감마 (+GEX)" if net_gex_m >= 0 else "음감마 (-GEX)"

    return {
        "spot": spot_val,
        "chg_1d": chg_1d, "chg_3d": chg_3d, "chg_5d": chg_5d, "chg_20d": chg_20d,
        "vol_oi": vol_oi, "call_vol_oi": call_vol_oi, "put_vol_oi": put_vol_oi,
        "call_top3": call_top3, "put_top3": put_top3,
        "call_wall": cw, "put_wall": pw, "max_pain": max_pain, "gex_flip": gex_flip,
        "net_gex_m": net_gex_m, "disp_prem_m": disp_prem_m,
        "has_above_ask_sweep": has_above_ask_sweep, "has_sweep": has_sweep,
        "conviction": conviction,
        "p_up": p_up, "p_flat": p_flat, "p_down": p_down,
        "voi_badge": voi_badge, "dealer_lbl": dealer_lbl,
        "ai_emo": ai_emo, "ai_dir": ai_dir, "ai_prob": ai_prob,
        "ai_intent": ai_intent, "reasons": reasons or ["실시간 OI·Vol/OI 균형 유지"],
        "tk_flows": tk_flows,
    }


def _compute_top10_oi_surge(oi_hist, all_raw_flows, saved_big_flows):
    rows = []
    seen = set()
    # 1) Saved OI history tickers
    for tk, snaps in (oi_hist or {}).items():
        if not snaps:
            continue
        seen.add(tk)
        latest = snaps[-1]
        df_det = pd.DataFrame(latest.get("상세", []))
        m = _oi_pro_calc(tk, snaps, df_det, float(latest.get("Spot", 0) or 0), all_raw_flows, saved_big_flows)
        rows.append({
            "티커": tk,
            "현재가": f"${m['spot']:.2f}" if m["spot"] else "-",
            "전일대비": f"{m['chg_1d']:+.1f}%" if m["chg_1d"] is not None else "신규",
            "3일": f"{m['chg_3d']:+.1f}%" if m["chg_3d"] is not None else "-",
            "5일": f"{m['chg_5d']:+.1f}%" if m["chg_5d"] is not None else "-",
            "Vol/OI": f"{'🟢' if m['vol_oi']>3 else ('⚪' if m['vol_oi']<1 else '🟡')} {m['vol_oi']:.1f}",
            "프리미엄($M)": m["disp_prem_m"],
            "기관점수": m["conviction"],
            "AI 판정": f"{m['ai_emo']} {m['ai_dir']} {m['ai_prob']}%",
            "핵심 의도": m["ai_intent"],
        })
    # 2) Google Sheets & TG Big Flows tickers
    flow_agg = {}
    for r in (all_raw_flows or []):
        tk = str(r[1]).upper()
        if not tk or tk in seen:
            continue
        pm = parse_prem_usd(r[14] if len(r) > 14 else "0")
        g = flow_agg.setdefault(tk, {"prem": 0.0, "cnt": 0, "bull": 0.0, "bear": 0.0, "swp": False})
        g["prem"] += pm; g["cnt"] += 1
        cp_u = str(r[3]).upper(); sd_u = str(r[4]).upper(); ch_u = str(r[13] if len(r) > 13 else "").upper()
        if ("C" in cp_u and "A" in sd_u) or ("P" in cp_u and "B" in sd_u):
            g["bull"] += pm
        else:
            g["bear"] += pm
        if "SWEEP" in ch_u:
            g["swp"] = True
    for b in (saved_big_flows or []):
        tk = b.get("tk", "")
        if not tk or tk in seen:
            continue
        g = flow_agg.setdefault(tk, {"prem": 0.0, "cnt": 0, "bull": 0.0, "bear": 0.0, "swp": False})
        for r in b.get("records", []):
            pm = float(r.get("prem_m", 0)) * 1e6
            g["prem"] += pm; g["cnt"] += 1
            if r.get("emoji") == "🟢":
                g["bull"] += pm
            elif r.get("emoji") == "🔴":
                g["bear"] += pm
            if "SWEEP" in str(r.get("tag", "")).upper():
                g["swp"] = True
    for tk, g in flow_agg.items():
        prem_m = round(g["prem"] / 1e6, 2)
        conv = int(min(98, max(35, round(40 + min(30, prem_m * 3.0) + min(18, g["cnt"] * 2) + (10 if g["swp"] else 0)))))
        if g["bull"] >= g["bear"] * 1.2:
            ai_s, intent = f"🟢 강세 {min(88, 55 + conv // 4)}%", "콜 매수·풋 매도 기관 유입"
        elif g["bear"] >= g["bull"] * 1.2:
            ai_s, intent = f"🔴 약세 {min(88, 55 + conv // 4)}%", "대형 풋 매수·콜 매도 압력"
        else:
            ai_s, intent = "🟡 중립 54%", "양방향 대형 수급 교차"
        rows.append({
            "티커": tk,
            "현재가": "-",
            "전일대비": f"체결 {g['cnt']}건",
            "3일": "-",
            "5일": "-",
            "Vol/OI": f"{'🟢' if (1.5+min(6.0,g['cnt']*0.4))>3 else '🟡'} {round(1.5 + min(6.0, g['cnt'] * 0.4), 1):.1f}",
            "프리미엄($M)": prem_m,
            "기관점수": conv,
            "AI 판정": ai_s,
            "핵심 의도": intent,
        })
    rows.sort(key=lambda x: (x["기관점수"], x["프리미엄($M)"]), reverse=True)
    return rows[:10]

if nav_menu == "📝 오늘의 종합평":
    st.title("📝 오늘의 종합평 (2026-11-11 장마감 기준)")
    st.caption("InsiderFinance Evening Edge 옵션 플로우·AI 분석·뉴스·다크풀 종합 평가")

    with st.container(border=True):
        _hm_t1, _hm_t2 = st.columns([3, 1])
        _hm_t1.subheader("🔥 오늘의 OI 급증 TOP10")
        _hm_top10 = _compute_top10_oi_surge(load_json_file(OI_PATH, {}), all_raw_flows, load_json_file(BIG_FLOWS_PATH, []))
        if _hm_t2.button("📩 TOP10 텔레그램", use_container_width=True, key="btn_home_top10_tg_main"):
            if _hm_top10:
                _hm_msg = "🔥 *오늘의 OI 급증 TOP10*\n\n" + "\n".join(
                    f"{i+1}. *{r['티커']}* | {r['기관점수']}/100 | {r['Vol/OI']} | {r['AI 판정']}"
                    for i, r in enumerate(_hm_top10)
                )
                if send_telegram_msg(tg_token, tg_chat_id, _hm_msg)[0]:
                    st.toast("✅ TOP10 텔레그램 전송 완료!")
        if _hm_top10:
            st.dataframe(pd.DataFrame(_hm_top10), hide_index=True, use_container_width=True)


    col_r1, col_r2 = st.columns([4, 1])
    with col_r2:
        if st.button("📩 이 종합평 텔레그램으로 바로 보내기", type="primary", use_container_width=True):
            t_tok, t_cid = load_tg_config()
            ok, msg = send_telegram_msg(t_tok, t_cid, DAILY_REVIEW_2026_11_11)
            if ok: st.success(f"✅ {msg}")
            else: st.error(f"❌ {msg}")

    st.markdown("""
    <div class='flow-card' style='border-left: 4px solid #3b82f6;'>
        <h3 style='color:#60a5fa; margin-top:0;'>1️⃣ 시장 총평: "지수·반도체 반등 속 기관은 철저한 하방 보험(Hedge) 유지"</h3>
        <p style='color:#e2e8f0; font-size:14px; line-height:1.7;'>
            • 10월 CPI 예상치 상회 및 매파적 연준 기조로 금리 경계감이 여전한 가운데, 반도체·소형주 주가가 단기 반등하자 기관들은 상방 추격 대신 <strong>'풋옵션 헷지 연장'</strong>을 선택했습니다.<br>
            • <strong>SPX</strong>에서는 8000 Put($77M, $39.4M, $37.5M 등) 대규모 풋 스플릿/블록이 집중되었고, 중소형주(<strong>IWM</strong>) 역시 5일 연속 극단적 풋 편중이 유지되고 있습니다.
        </p>
    </div>
    """, unsafe_allow_html=True)

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("""
        <div class='flow-card' style='border-left: 4px solid #ef4444;'>
            <h4 style='color:#f87171; margin-top:0;'>2️⃣ 반도체 풋 방어 & 과열 경계</h4>
            <ul style='color:#d1d4dc; font-size:13px; line-height:1.7; padding-left:18px;'>
                <li><strong>MU ($24.3M 800 Put) · AMD ($6.2M 600 Put):</strong> 급등한 반도체 주도주에 대형 풋 헷지가 집중되어 단기 차익실현·방어 심리가 강합니다.</li>
                <li><strong>NVDA:</strong> 이사회 독립 조사 및 Baird 목표가 하향($500→$200) 여파 속에서도 장기 콜($175C/$150C)과 단기 거래가 공존하며 <strong>413K 스윕 볼륨 1위</strong>를 기록했습니다.</li>
                <li><strong>LITE ($12.6M 750 Put):</strong> 하루 두 자릿수 급등 직후 미결제약정 39배 규모의 단기 풋 골든 스윕이 유입되어 되돌림 주의가 필요합니다.</li>
            </ul>
        </div>
        """, unsafe_allow_html=True)
    with c2:
        st.markdown("""
        <div class='flow-card' style='border-left: 4px solid #10b981;'>
            <h4 style='color:#34d399; margin-top:0;'>3️⃣ 주도주 선별 콜 집중 & 모멘텀</h4>
            <ul style='color:#d1d4dc; font-size:13px; line-height:1.7; padding-left:18px;'>
                <li><strong>META ($31.0M 750C) · TSLA ($4.2M 410C) · AMZN:</strong> 섹터 전반의 약세 속에서도 기관 자금이 확실한 주도주에만 선별 집중되고 있습니다.</li>
                <li><strong>INTC ($31.0M 50C) · SNDK (9건, $6.8M 스윕):</strong> 인텔의 주식 대체형 초대형 콜 블록과 샌디스크의 9연속 콜 스윕이 포착되었습니다.</li>
                <li><strong>KGC (11.2x) · BW (6.0x) · ACHR (5.3x):</strong> 0% Put Flow로 전량 콜옵션 모멘텀 매집이 유입되었습니다.</li>
                <li><strong>IBIT ($63.4M 48C) · CIFR ($870K):</strong> 크립토·채굴주 장기 상방 베팅도 지속 중입니다.</li>
            </ul>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("""
    <div class='flow-card' style='border-left: 4px solid #f59e0b;'>
        <h4 style='color:#fbbf24; margin-top:0;'>4️⃣ 오늘의 대응 전략 및 핵심 뉴스 촉매</h4>
        <ul style='color:#d1d4dc; font-size:13px; line-height:1.7; padding-left:18px;'>
            <li><strong>공격적 매수 관심군:</strong> 다크풀 매집과 콜 스윕이 일치하는 <strong>META, TSLA, AMZN</strong> 및 모멘텀 콜 집중 종목(<strong>SNDK, KGC, BW</strong>)</li>
            <li><strong>리스크 관리 구간:</strong> 단기 급등 후 대형 풋 헷지가 유입된 <strong>MU, AMD, LITE</strong> 및 목표가 하향 이슈가 있는 <strong>NVDA</strong></li>
            <li><strong>핵심 뉴스 촉매:</strong> 앤스로픽 IPO 로드쇼($70~$78, 첫날 개인 매수세 $2.5억 예상), 코스트코 주당 $30 특별배당($133억 규모)</li>
        </ul>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("---")
    st.subheader("📊 Barchart 특이옵션 & Menthor Q 그릭스/GEX 리포트 (구글 시트 & 최신 메일 연동)")
    st.markdown("""
    <div style="background:#0f172a; border:1px solid #334155; border-radius:8px; padding:12px 16px; margin-bottom:10px; font-size:13px; color:#e2e8f0;">
      <div style="font-weight:800; color:#38bdf8; margin-bottom:6px;">📐 Menthor Q · Greeks 최신 리포트 (2026-11-13 메일 기준)</div>
      <ul style="margin:0; padding-left:18px; line-height:1.6;">
        <li><strong>NVDA ($166.19, -4.34%)</strong>: Net GEX <span style="color:#ef4444;">-$172.03M</span> (총 감마 $1.63B · Negative-Gamma) · HVL 감마 플립 <strong>$182</strong> · Put Support <strong>$150</strong> / Call Resistance <strong>$200</strong> · 1D 예상변동 <strong>$160.38~$172.00</strong> · 1M IV <strong>59.7%</strong> (HV 52.7%, IV Rank 92.4%)</li>
        <li><strong>QQQ ($688.17)</strong>: Net GEX <span style="color:#ef4444;">-$274.55M</span> (Bearish Swing) · 5일 상단밴드 <strong>$710.81</strong>(-3.3%) / 20일 상단밴드 <strong>$733.42</strong>(-6.6%) · 리스크 트리거 5일 <strong>$665.61</strong>(+3.3%) / 20일 <strong>$643.00</strong>(+6.6%)</li>
        <li><strong>SBUX (Barchart 최신 시트)</strong>: 12/18 <strong>75 Call</strong> $96.3M (Deep ITM Stock Replacement 29,500건, 델타 0.9933, 거래량 5배) · 11/20 100 Call $647K 블록 연속</li>
      </ul>
    </div>
    """, unsafe_allow_html=True)
    df_bm = load_ai_notes_sheet()
    if not df_bm.empty and "섹션" in df_bm.columns:
        df_bm_sub = df_bm[df_bm["섹션"].astype(str).str.contains("바차트|맨도큐|Barchart|Menthor|GeeksOfFinance|SpotGamma|UnusualWhales", case=False, na=False)].iloc[::-1].head(12)
        if not df_bm_sub.empty:
            c_mq, c_bc = st.columns(2)
            with c_mq:
                st.markdown("#### 📐 Menthor Q 그릭스 · GEX · 옵션 매트릭스")
                mq_rows = df_bm_sub[df_bm_sub["섹션"].astype(str).str.contains("맨도큐|Menthor|GeeksOfFinance|SpotGamma|UnusualWhales", case=False, na=False)]
                if not mq_rows.empty:
                    for _, r in mq_rows.iterrows():
                        img_u = str(r.get('이미지URL', '')).strip()
                        if img_u.startswith('http'):
                            st.image(img_u, use_container_width=True)
                        st.info(f"**[{r.get('날짜','')}] {r.get('종목','')}**\n\n{r.get('한글 번역/해석','')}")
                else:
                    st.caption("아직 저장된 Menthor Q 그릭스 내역이 없습니다.")
            with c_bc:
                st.markdown("#### 🚨 Barchart 특이옵션(Unusual Options)")
                bc_rows = df_bm_sub[df_bm_sub["섹션"].astype(str).str.contains("바차트|Barchart", case=False, na=False)]
                if not bc_rows.empty:
                    for _, r in bc_rows.iterrows():
                        st.warning(f"**[{r.get('날짜','')}] {r.get('종목','')}**\n\n{r.get('한글 번역/해석','')}")
                else:
                    st.caption("아직 저장된 Barchart 특이옵션 내역이 없습니다.")
        else:
            st.caption("구글 시트 AI노트_뉴스시황 탭에 바차트/맨도큐 데이터가 추가되면 여기에 자동 표시됩니다.")
    else:
        st.caption("구글 시트 AI노트_뉴스시황 탭을 불러오는 중입니다.")

# ================= TAB 1: TOP TICKER =================
if nav_menu == "🔥 Top Ticker + 차트/P&L":
    rows = [r for r in date_filtered_flows if r[1] == sel_tk]
    if sort_dir.startswith("과거"):
        rows = rows[::-1]
        
    n_t = len(rows)
    puts = sum(1 for r in rows if r[3] == "Put")
    put_p = f"{int(puts / n_t * 100)}%" if n_t > 0 else "0%"
    
    col_l, col_r = st.columns([3, 2])
    col_l.markdown(f"<h1 style='color:white; margin:0;'>Top Ticker <span style='color:#00e676;'>{sel_tk}</span> <span class='date-badge'>📅 {sel_date}</span></h1>", unsafe_allow_html=True)
    col_r.markdown("<div style='text-align:right;'><span style='background:#00e676; color:black; padding:6px 16px; border-radius:20px; font-weight:700;'>Flow ›</span></div>", unsafe_allow_html=True)
    
    if sel_date in DAILY_METRICS_BY_DATE and sel_tk in DAILY_METRICS_BY_DATE[sel_date]:
        m = DAILY_METRICS_BY_DATE[sel_date][sel_tk]
        st.markdown(f"""
        <div style='margin-top: 8px;'>
            <span class='summary-badge'>🎯 당일 체결: {m['trades']}건</span>
            <span class='summary-badge'>📉 Put Flow: {m['put_flow']}</span>
            <span class='summary-badge'>⚡ {m['otm']}</span>
            <span class='summary-badge'>📦 {m['contracts']}</span>
            <span class='summary-badge'>💰 {m['prem']}</span>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("<div class='flow-card'>", unsafe_allow_html=True)
    top_p = rows[0][14] if n_t > 0 else "$0"
    exp_d = rows[0][5] if n_t > 0 else "-"
    stk_d = rows[0][7] if n_t > 0 else "-"
    typ_d = rows[0][13] if n_t > 0 else "-"
    heat_d = rows[0][15] if n_t > 0 else "35"
    
    kpis = [("TRADES", str(n_t)), ("PUT FLOW", put_p), ("EXPIRY", exp_d), ("STRIKE", stk_d), ("TOP PREM", top_p), ("TYPE", typ_d), ("HEAT", heat_d)]
    k_html = "<div class='kpi-row'>" + "".join([f"<div class='kpi-box'><div class='kpi-title'>{k}</div><div class='kpi-value {'kpi-red' if k=='PUT FLOW' and int(put_p.replace('%',''))>50 else 'kpi-green'}'>{v}</div></div>" for k, v in kpis]) + "</div>"
    st.markdown(k_html, unsafe_allow_html=True)
    
    tb = "".join([f"<tr><td><strong>{d[0]}</strong></td><td>{d[2]}</td><td class='{'badge-call' if d[3]=='Call' else 'badge-put'}'>{d[3]}</td><td>{d[4]}</td><td>{d[5]}</td><td>{d[6]}</td><td><strong>{d[7]}</strong></td><td>{d[8]}</td><td>{d[9]}</td><td>{d[10]}</td><td>{d[11]}</td><td>{d[12]}</td><td>{d[13]}</td><td class='kpi-green'><strong>{d[14]}</strong></td><td><span class='heat-bar'>{d[15]}</span></td></tr>" for d in rows])
    st.markdown(f"<table class='flow-table'><thead><tr><th>DATE</th><th>TIME</th><th>C/P</th><th>SIDE</th><th>EXPIRY</th><th>SPOT</th><th>STRIKE</th><th>OTM</th><th>PRICE</th><th>SIZE</th><th>OI</th><th>IV</th><th>TYPE</th><th>PREMIUM</th><th>HEAT</th></tr></thead><tbody>{tb}</tbody></table>", unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)


    st.markdown("---")
    st.subheader(f"📈 {sel_tk} 실시간 TradingView 차트 & 옵션 손익(P&L) 시뮬레이터")
    col_tv, col_pnl = st.columns([3, 2])
    with col_tv:
        tv_html = f"""
        <div class="tradingview-widget-container" style="height:460px;width:100%;">
          <div id="tv_chart" style="height:460px;width:100%;"></div>
          <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
          <script type="text/javascript">
          new TradingView.widget({{
            "autosize": true,
            "symbol": "{"SPY" if sel_tk=="SPX" else sel_tk}",
            "interval": "D",
            "timezone": "Asia/Seoul",
            "theme": "dark",
            "style": "1",
            "locale": "kr",
            "toolbar_bg": "#0b0e14",
            "enable_publishing": false,
            "allow_symbol_change": true,
            "container_id": "tv_chart"
          }});
          </script>
        </div>
        """
        components.html(tv_html, height=470)

    with col_pnl:
        st.markdown("#### 🧮 옵션 만기 손익 시뮬레이터")
        def_strike = 100.0
        try:
            def_strike = float(str(stk_d).replace("$", "").replace(",", ""))
        except Exception:
            def_strike = 100.0
        sim_cp = st.radio("옵션 유형", ["Call (상승)", "Put (하락)"], horizontal=True, index=0 if (n_t==0 or rows[0][3]=="Call") else 1)
        sim_stk = st.number_input("행사가 ($)", min_value=0.5, value=def_strike, step=1.0)
        sim_prem = st.number_input("주당 프리미엄 ($)", min_value=0.05, value=5.0, step=0.5)
        sim_qty = st.number_input("계약 수 (1계약=100주)", min_value=1, value=1, step=1)
        sim_target = st.number_input("만기 시 예상 주가 ($)", min_value=0.5, value=round(def_strike * (1.1 if "Call" in sim_cp else 0.9), 2), step=1.0)

        cost = sim_prem * 100 * sim_qty
        if "Call" in sim_cp:
            bep = sim_stk + sim_prem
            intrinsic = max(0.0, sim_target - sim_stk)
        else:
            bep = sim_stk - sim_prem
            intrinsic = max(0.0, sim_stk - sim_target)
        pnl = (intrinsic * 100 * sim_qty) - cost
        roi = (pnl / cost * 100) if cost > 0 else 0.0

        st.markdown(f"""
        <div class='flow-card' style='padding:12px; margin-top:8px;'>
            <div style='font-size:13px; color:#94a3b8;'>총 투자금: <strong style='color:white;'>${cost:,.0f}</strong> | 손익분기점(BEP): <strong style='color:#fbbf24;'>${bep:,.2f}</strong></div>
            <div style='font-size:18px; font-weight:800; margin-top:6px; color:{"#00e676" if pnl>=0 else "#f23645"};'>
                예상 순손익: ${pnl:+,.0f} ({roi:+.1f}%)
            </div>
        </div>
        """, unsafe_allow_html=True)

        prices = [sim_stk * (0.7 + 0.03 * i) for i in range(21)]
        pnls = [((max(0.0, p - sim_stk) if "Call" in sim_cp else max(0.0, sim_stk - p)) * 100 * sim_qty) - cost for p in prices]
        fig_pnl = go.Figure()
        fig_pnl.add_trace(go.Scatter(x=prices, y=pnls, mode='lines', line=dict(color='#00e676' if pnl>=0 else '#f23645', width=3), name='만기 손익'))
        fig_pnl.add_hline(y=0, line_dash="dash", line_color="#64748b")
        fig_pnl.add_vline(x=bep, line_dash="dot", line_color="#fbbf24")
        fig_pnl.update_layout(height=210, plot_bgcolor="#0e1117", paper_bgcolor="#0e1117", font_color="#d1d4dc", margin=dict(l=10, r=10, t=10, b=10), xaxis_title="만기 주가 ($)", yaxis_title="손익 ($)")
        st.plotly_chart(fig_pnl, use_container_width=True)

# ================= TAB OI: OPEN INTEREST COLLECTOR & TRACKER =================
if nav_menu == "🎯 실발·OI 매집 스캐너":
    st.title("🎯 실적 발표 & 조용한 OI 매집 스캐너 (Stealth OI)")
    st.caption("단타 스윕(Flow)에 안 잡혀도 행사가별로 조용히 누적되는 OI 급증과 실적 발표 예상 변동폭(Expected Move)·Call/Put Wall을 포착합니다.")

    live_cache = load_json_file(os.path.expanduser("~/.optionhub_intraday_live.json"), {})
    st.subheader("⚡ 장중 실시간 Vol > OI 신규 오픈 TOP (10분 자동 갱신)")
    if live_cache.get("items"):
        st.caption(f"최근 장중 스캔 시각: {live_cache.get('updated', '-')}")
        df_live = pd.DataFrame([{
            "티커": h.get("tk"),
            "현재가($)": h.get("spot"),
            "만기": h.get("exp"),
            "구분": h.get("cp"),
            "행사가($)": h.get("k"),
            "추정금액": h.get("prem_str", "-"),
            "거래량": h.get("vol"),
            "기존 OI": h.get("oi"),
            "최소 신규(+)": h.get("min_new"),
            "Vol/OI": f"{h.get('ratio', 0)}x",
            "방향추정": h.get("hint", "-"),
        } for h in live_cache["items"][:20]])
        st.dataframe(df_live, use_container_width=True, hide_index=True)
    else:
        st.caption("장중 10분 스캐너(`intraday_vol_oi.py`) 실행 시 실시간 Vol > OI 포착 내역이 여기에 자동 표시됩니다.")
    st.markdown("---")

    oi_hist_s = load_json_file(OI_PATH, {})
    st.subheader("🕵️ 전일 대비 행사가별 OI 급증 TOP (조용한 매집 포착)")
    stealth_rows = []
    for tk_s, snaps_s in oi_hist_s.items():
        if len(snaps_s) >= 2:
            prev_det = {(x["만기"], x["구분"], x["행사가"]): x["OI"] for x in snaps_s[-2].get("상세", [])}
            for x in snaps_s[-1].get("상세", []):
                k_id = (x["만기"], x["구분"], x["행사가"])
                p_oi = prev_det.get(k_id, 0)
                diff = x["OI"] - p_oi
                if abs(diff) >= 300 and p_oi >= 10 and x["OI"] >= 10:
                    stealth_rows.append({
                        "포착유형": "🟢 신규 오픈(BTO/STO)" if diff > 0 else "🔴 대량 청산(BTC/STC)",
                        "티커": tk_s,
                        "현재가($)": snaps_s[-1].get("Spot", 0),
                        "만기": x["만기"],
                        "구분": x["구분"],
                        "행사가($)": x["행사가"],
                        "전일 OI": p_oi,
                        "현재 OI": x["OI"],
                        "OI 순증감": diff,
                        "변동규모": abs(diff),
                        "변동률(%)": round(diff / max(p_oi, 1) * 100, 1),
                        "GEX($M)": x.get("GEX($M)", 0),
                    })
    if stealth_rows:
        oi_flt = st.radio("포착 필터", ["전체 (신규+청산)", "🟢 신규 오픈(+)만", "🔴 대량 청산(-)만"], horizontal=True)
        df_st = pd.DataFrame(stealth_rows)
        if oi_flt.startswith("🟢"):
            df_st = df_st[df_st["OI 순증감"] > 0]
        elif oi_flt.startswith("🔴"):
            df_st = df_st[df_st["OI 순증감"] < 0]
        df_st = df_st.sort_values("변동규모", ascending=False).drop(columns=["변동규모"]).head(30)
        st.dataframe(df_st, use_container_width=True, hide_index=True)
    else:
        st.info("아직 2일치 이상 누적된 OI 비교 데이터가 부족합니다. 내일 오전 6:30 `auto_oi.py` 수집 후부터 전일 대비 OI 순증이 자동 표시됩니다!")

    st.markdown("---")
    st.subheader("📅 실적 발표 임박(D-10 이내) 자동 스캔 결과")
    earn_cache = load_json_file(os.path.expanduser("~/.optionhub_earnings_scan.json"), {})
    if earn_cache.get("items"):
        st.caption(f"자동 수집 기준 시각: {earn_cache.get('updated', '-')}")
        st.dataframe(pd.DataFrame(earn_cache["items"]), use_container_width=True, hide_index=True)
    else:
        st.caption("매일 오전 6:30 자동 스캔 시 실발 10일 이내 종목이 여기에 자동 표시됩니다.")

    st.subheader("🔍 원하는 종목 수동 실시간 스캔")
    default_scan_tks = ", ".join(sorted(list(oi_hist_s.keys()))[:12]) if oi_hist_s else "NVDA, TSLA, MU, AMD, OKTA, WMT, LUNR, INTC"
    scan_in = st.text_input("스캔할 종목 티커 (쉼표 구분)", value=default_scan_tks).strip().upper()
    if st.button("🔍 실발일 · 예상 변동폭 · Wall 실시간 스캔", type="primary"):
        tks = [t.strip() for t in scan_in.split(",") if t.strip()][:20]
        res_scan = []
        prog = st.progress(0)
        import yfinance as yf
        from datetime import datetime
        for i_t, tk_q in enumerate(tks):
            try:
                t_obj = yf.Ticker(tk_q)
                spot_q = float(t_obj.fast_info.get("lastPrice", 0) or 0)
                earn_dt = "-"
                try:
                    cal = t_obj.calendar
                    if isinstance(cal, dict) and "Earnings Date" in cal and cal["Earnings Date"]:
                        ed = cal["Earnings Date"][0]
                        earn_dt = str(ed)[:10]
                except Exception:
                    pass
                exps_q = t_obj.options
                em_pct, cw_q, pw_q = "-", "-", "-"
                if exps_q and spot_q > 0:
                    ch = t_obj.option_chain(exps_q[0])
                    calls_q, puts_q = ch.calls, ch.puts
                    if not calls_q.empty and not puts_q.empty:
                        cw_q = float(calls_q.loc[calls_q["openInterest"].fillna(0).idxmax(), "strike"])
                        pw_q = float(puts_q.loc[puts_q["openInterest"].fillna(0).idxmax(), "strike"])
                        atm_c = calls_q.iloc[(calls_q["strike"] - spot_q).abs().argsort()[:1]]["lastPrice"].values[0]
                        atm_p = puts_q.iloc[(puts_q["strike"] - spot_q).abs().argsort()[:1]]["lastPrice"].values[0]
                        if not pd.isna(atm_c) and not pd.isna(atm_p):
                            em_pct = f"±{round((float(atm_c) + float(atm_p)) / spot_q * 100, 1)}%"
                res_scan.append({
                    "티커": tk_q,
                    "현재가($)": round(spot_q, 2),
                    "실적 발표일": earn_dt,
                    "최근 만기": exps_q[0] if exps_q else "-",
                    "예상 변동폭": em_pct,
                    "Call Wall($)": cw_q,
                    "Put Wall($)": pw_q,
                })
            except Exception:
                pass
            prog.progress((i_t + 1) / max(len(tks), 1))
        if res_scan:
            st.dataframe(pd.DataFrame(res_scan), use_container_width=True, hide_index=True)
        else:
            st.warning("조회된 데이터가 없습니다.")

if nav_menu == "📊 OI(미결제약정) 수집":
    st.title("📊 OI · GEX(감마 익스포저) · Delta/Gamma 실시간 수집기")
    st.caption("종목별 행사가별 미결제약정(OI)과 Black-Scholes 기반 감마(Gamma)·델타(Delta)·GEX·DEX를 실시간 산출하고 누적 저장합니다.")

    with st.container(border=True):
        _t10_h1, _t10_h2 = st.columns([3, 1])
        _t10_h1.subheader("🔥 오늘의 OI 급증 TOP10")
        _oi_hist_home = load_json_file(OI_PATH, {})
        _big_home = load_json_file(BIG_FLOWS_PATH, [])
        _top10_rows = _compute_top10_oi_surge(_oi_hist_home, all_raw_flows, _big_home)
        if _t10_h2.button("📩 TOP10 텔레그램", use_container_width=True, key="btn_home_top10_tg"):
            if _top10_rows:
                _t10_msg = "🔥 *오늘의 OI 급증 TOP10*\n\n" + "\n".join(
                    f"{i+1}. *{r['티커']}* | 점수 {r['기관점수']}/100 | ${r['프리미엄($M)']}M | {r['AI 판정']}"
                    for i, r in enumerate(_top10_rows)
                )
                if send_telegram_msg(tg_token, tg_chat_id, _t10_msg)[0]:
                    st.toast("✅ TOP10 텔레그램 전송 완료!")
                else:
                    st.toast("⚠️ 텔레그램 설정을 확인해 주세요.")
        if _top10_rows:
            st.dataframe(pd.DataFrame(_top10_rows), hide_index=True, use_container_width=True)
        else:
            st.info("수집된 OI/대형 체결 데이터가 없습니다. `📊 OI(미결제약정) 수집`에서 스냅샷을 저장해 보세요.")

    oi_c1, oi_c2 = st.columns([2, 1])
    with oi_c1:
        oi_tk = st.text_input("수집할 종목 티커 입력 (예: NVDA, TSLA, SNDK, MU)", value=sel_tk).strip().upper()
    with oi_c2:
        st.write("")
        st.write("")
        collect_btn = st.button("🔄 지금 OI·GEX 스냅샷 수집 & 저장", type="primary", use_container_width=True)

    oi_history = load_json_file(OI_PATH, {})

    if collect_btn and oi_tk:
        with st.spinner(f"{oi_tk} 옵션 체인(OI · GEX · Delta · Gamma) 수집 중..."):
            oi_rows, spot_px, status = fetch_yahoo_oi(oi_tk)
        if status == "OK" and oi_rows:
            from datetime import datetime
            today_str = datetime.now().strftime("%Y-%m-%d %H:%M")
            if oi_tk not in oi_history:
                oi_history[oi_tk] = []
            tot_call_oi = sum(x["OI"] for x in oi_rows if x["구분"] == "Call")
            tot_put_oi = sum(x["OI"] for x in oi_rows if x["구분"] == "Put")
            net_gex_m = round(sum(x["GEX($M)"] for x in oi_rows), 2)
            net_dex_m = round(sum(x["DEX($M)"] for x in oi_rows), 2)
            oi_history[oi_tk].append({
                "수집시각": today_str,
                "Spot": spot_px,
                "Call_OI": tot_call_oi,
                "Put_OI": tot_put_oi,
                "Put_Call_OI_Ratio": round(tot_put_oi / tot_call_oi, 2) if tot_call_oi > 0 else 0,
                "Net_GEX_M": net_gex_m,
                "Net_DEX_M": net_dex_m,
                "상세": oi_rows
            })
            save_json_file(OI_PATH, oi_history)
            st.success(f"✅ {oi_tk} (현재가 ${spot_px}) OI·GEX 스냅샷 저장 완료! (Net GEX: {net_gex_m:+.2f}M / Net DEX: {net_dex_m:+.2f}M)")
        elif status == "NO_YFINANCE":
            st.warning("⚠️ 서버에 `yfinance` 패키지가 아직 설치되어 있지 않습니다.")
        else:
            st.error(f"수집 중 오류: {status}")

    if oi_tk in oi_history and oi_history[oi_tk]:
        snaps = oi_history[oi_tk]
        latest = snaps[-1]
        prev = snaps[-2] if len(snaps) >= 2 else None

        m1, m2, m3, m4, m5 = st.columns(5)
        d_call = latest["Call_OI"] - prev["Call_OI"] if prev else 0
        d_put = latest["Put_OI"] - prev["Put_OI"] if prev else 0
        net_gex_val = latest.get("Net_GEX_M", 0.0)
        net_dex_val = latest.get("Net_DEX_M", 0.0)
        spot_val = latest.get("Spot", 0.0)
        m1.metric("현재가 (Spot)", f"${spot_val:,.2f}" if spot_val else "-")
        m2.metric("Call OI (3만기)", f"{latest['Call_OI']:,}", f"{d_call:+,}" if prev else None)
        m3.metric("Put OI (3만기)", f"{latest['Put_OI']:,}", f"{d_put:+,}" if prev else None)
        m4.metric("Net GEX ($M)", f"{net_gex_val:+.2f}M", "양(+)감마 안정" if net_gex_val >= 0 else "음(-)감마 변동성")
        m5.metric("Net DEX ($M)", f"{net_dex_val:+.2f}M")

        df_det = pd.DataFrame(latest.get("상세", []))
        _saved_big_oi = load_json_file(BIG_FLOWS_PATH, [])
        _pro = _oi_pro_calc(oi_tk, snaps, df_det, spot_val, all_raw_flows, _saved_big_oi)

        # [UPGRADE] OI 급증 감지 (1일/3일/5일/20일) + Vol/OI 판정 + 구조 레벨 + AI 판독 + Conviction Score
        with st.container(border=True):
            st.markdown(f"### 🧠 {oi_tk} 세력 의도 · AI 판독 (기관매집점수 `{_pro['conviction']}/100`)")
            _sc_c1, _sc_c2, _sc_c3, _sc_c4 = st.columns(4)
            _sc_c1.metric("1일 평균 대비 OI", f"{_pro['chg_1d']:+.2f}%" if _pro["chg_1d"] is not None else "기준 수집됨")
            _sc_c2.metric("3일 평균 대비 OI", f"{_pro['chg_3d']:+.2f}%" if _pro["chg_3d"] is not None else "-")
            _sc_c3.metric("5일 평균 대비 OI", f"{_pro['chg_5d']:+.2f}%" if _pro["chg_5d"] is not None else "-")
            _sc_c4.metric("20일 평균 대비 OI", f"{_pro['chg_20d']:+.2f}%" if _pro["chg_20d"] is not None else "-")

            _gex_s_str = f"+{_pro['net_gex_m']/1000:.2f}B" if _pro['net_gex_m'] >= 1000 else (f"{_pro['net_gex_m']/1000:.2f}B" if _pro['net_gex_m'] <= -1000 else f"{_pro['net_gex_m']:+.1f}M")
            _gex_em = "🟢" if _pro["net_gex_m"] >= 0 else "🔴"
            st.markdown(
                f"**{_pro['ai_emo']} AI 판정: {_pro['ai_dir']}** (상승 `{_pro['p_up']}%` · 횡보 `{_pro['p_flat']}%` · 하락 `{_pro['p_down']}%`) — {' · '.join(_pro['reasons'])} → **{_pro['ai_intent']}**  \n"
                f"**Dealer**: `{_pro['dealer_lbl']}` ({_gex_em} Net GEX `{_gex_s_str}`) · **Volume/OI**: `{_pro['vol_oi']:.2f}` (`{_pro['voi_badge']}`)  \n"
                f"🟢 **Call Wall** `{_pro['call_wall']:g}` · 🔴 **Put Wall** `{_pro['put_wall']:g}` · 🎯 **Max Pain** `{_pro['max_pain']:g}` · 🟡 **GEX Flip** `{_pro['gex_flip']:.1f}`  \n"
                f"**Call OI 집중**: `{', '.join(_pro['call_top3']) or '-'}` | **Put OI 집중**: `{', '.join(_pro['put_top3']) or '-'}`"
            )
            _tg_oi_txt = (
                f"🎯 {oi_tk}\n"
                f"Spot {_pro['spot']:.2f}\n"
                f"{_gex_em} Net GEX {_gex_s_str}\n"
                f"🟢 Call Wall {_pro['call_wall']:g}\n"
                f"🔴 Put Wall {_pro['put_wall']:g}\n"
                f"🟡 GEX Flip {_pro['gex_flip']:.1f}\n"
                f"Vol/OI {_pro['vol_oi']:.1f}\n"
                f"Premium ${_pro['disp_prem_m']:.1f}M\n"
                + ("Above Ask Sweep\n" if _pro["has_above_ask_sweep"] else ("Sweep 포착\n" if _pro["has_sweep"] else ""))
                + f"기관매집점수\n{_pro['conviction']}/100\n"
                f"AI 최종판정\n{_pro['ai_dir']} (상승 {_pro['p_up']}% · 횡보 {_pro['p_flat']}% · 하락 {_pro['p_down']}%)"
            )
            _tg_b1, _tg_b2 = st.columns([2, 1])
            _tg_b1.code(_tg_oi_txt, language="text")
            if _tg_b2.button("📩 텔레그램 판독 전송", use_container_width=True, key="btn_oi_pro_tg"):
                if send_telegram_msg(tg_token, tg_chat_id, _tg_oi_txt)[0]:
                    st.toast("✅ 텔레그램 전송 완료!")
                else:
                    st.toast("⚠️ 텔레그램 설정을 확인해 주세요.")

        # [UPGRADE] 5종 거래 필터 (DTE / 대량체결 / Sweep·Block / Ask·Bid / OTM·ATM·ITM)
        if not df_det.empty:
            with st.expander("🔍 정밀 거래 필터 (DTE · 대량체결 · Sweep/Block · Ask/Bid · OTM/ATM/ITM)", expanded=False):
                _f1, _f2, _f3, _f4, _f5 = st.columns(5)
                _f_dte = _f1.selectbox("DTE", ["전체", "0DTE", "1주", "1개월", "3개월", "6개월+"], key="oi_f_dte")
                _f_prem = _f2.selectbox("대량체결", ["전체", "100K+", "500K+", "1M+", "5M+"], key="oi_f_prem")
                _f_type = _f3.selectbox("체결유형", ["전체", "Sweep", "Block", "Split", "Single"], key="oi_f_type")
                _f_ab = _f4.selectbox("Ask/Bid", ["전체", "Above Ask", "At Ask", "Mid", "At Bid", "Below Bid"], key="oi_f_ab")
                _f_mny = _f5.selectbox("OTM/ATM/ITM", ["전체", "OTM", "ATM", "ITM"], key="oi_f_mny")

                _df_flt = df_det.copy()
                if "DTE" in _df_flt.columns and _f_dte != "전체":
                    if _f_dte == "0DTE": _df_flt = _df_flt[_df_flt["DTE"] <= 1]
                    elif _f_dte == "1주": _df_flt = _df_flt[_df_flt["DTE"] <= 7]
                    elif _f_dte == "1개월": _df_flt = _df_flt[_df_flt["DTE"] <= 35]
                    elif _f_dte == "3개월": _df_flt = _df_flt[_df_flt["DTE"] <= 95]
                    elif _f_dte == "6개월+": _df_flt = _df_flt[_df_flt["DTE"] >= 180]
                if "프리미엄($)" in _df_flt.columns and _f_prem != "전체":
                    _min_p = {"100K+": 1e5, "500K+": 5e5, "1M+": 1e6, "5M+": 5e6}[_f_prem]
                    _df_flt = _df_flt[_df_flt["프리미엄($)"] >= _min_p]
                if "Moneyness" in _df_flt.columns and _f_mny != "전체":
                    _df_flt = _df_flt[_df_flt["Moneyness"] == _f_mny]
                st.caption(f"체인 필터 결과: {len(_df_flt)}건 (체결유형·Ask/Bid 연동 플로우 {len(_pro['tk_flows'])}건)")
                if not _df_flt.empty:
                    st.dataframe(_df_flt.sort_values("OI", ascending=False).head(30), hide_index=True, use_container_width=True)
                if _pro["tk_flows"]:
                    _tf_df = pd.DataFrame(_pro["tk_flows"])
                    if _f_type != "전체": _tf_df = _tf_df[_tf_df["type"] == _f_type]
                    if _f_ab != "전체": _tf_df = _tf_df[_tf_df["ab"] == _f_ab]
                    if not _tf_df.empty:
                        st.dataframe(_tf_df, hide_index=True, use_container_width=True)
        if not df_det.empty:
            exp_list = ["전체 3만기 합산"] + sorted(df_det["만기"].unique())
            sel_oi_exp = st.selectbox("만기일별 OI · GEX · 델타 분포 보기", exp_list)
            df_e = df_det if sel_oi_exp == "전체 3만기 합산" else df_det[df_det["만기"] == sel_oi_exp]

            # GEX 대시보드 차트 (Call/Put/Net GEX + 하단 PREM + 집중 가격 + EST HEDGE 게이지)
            if "GEX($M)" in df_e.columns:
                from plotly.subplots import make_subplots
                c_gex = df_e[df_e["구분"] == "Call"].groupby("행사가")["GEX($M)"].sum()
                p_gex = df_e[df_e["구분"] == "Put"].groupby("행사가")["GEX($M)"].sum()
                n_gex = df_e.groupby("행사가")["GEX($M)"].sum()
                v_sum = df_e.groupby("행사가")["거래량"].sum() if "거래량" in df_e.columns else pd.Series(dtype=float)
                strikes_all = sorted(n_gex.index.tolist())
                gex_by_k = pd.DataFrame({
                    "행사가": strikes_all,
                    "Call_GEX": [float(c_gex.get(k, 0.0)) for k in strikes_all],
                    "Put_GEX": [float(p_gex.get(k, 0.0)) for k in strikes_all],
                    "GEX($M)": [float(n_gex.get(k, 0.0)) for k in strikes_all],
                    "VOL": [float(v_sum.get(k, 0.0)) for k in strikes_all],
                })
                if spot_val and spot_val > 0:
                    gex_win = gex_by_k[(gex_by_k["행사가"] >= spot_val * 0.7) & (gex_by_k["행사가"] <= spot_val * 1.35)]
                    if len(gex_win) >= 5:
                        gex_by_k = gex_win.reset_index(drop=True)

                call_wall = gex_by_k.loc[gex_by_k["Call_GEX"].idxmax(), "행사가"] if not gex_by_k.empty else 0
                put_wall = gex_by_k.loc[gex_by_k["Put_GEX"].idxmin(), "행사가"] if not gex_by_k.empty else 0
                zero_g = calc_zero_gamma(gex_by_k, spot_val)
                tot_call_g = gex_by_k["Call_GEX"].sum()
                tot_put_g = gex_by_k["Put_GEX"].sum()
                tot_net_g = gex_by_k["GEX($M)"].sum()
                cw_vol = int(df_e[(df_e["행사가"] == call_wall) & (df_e["구분"] == "Call")]["거래량"].sum()) if "거래량" in df_e.columns else 0
                cw_oi = int(df_e[(df_e["행사가"] == call_wall) & (df_e["구분"] == "Call")]["OI"].sum()) if "OI" in df_e.columns else 0
                pw_vol = int(df_e[(df_e["행사가"] == put_wall) & (df_e["구분"] == "Put")]["거래량"].sum()) if "거래량" in df_e.columns else 0
                pw_oi = int(df_e[(df_e["행사가"] == put_wall) & (df_e["구분"] == "Put")]["OI"].sum()) if "OI" in df_e.columns else 0

                st.markdown(f"""
                <div style="background:#0b1220; border:1px solid #1e293b; border-radius:8px; padding:10px 14px; margin-bottom:8px; font-family:monospace;">
                  <div style="display:flex; justify-content:space-between; flex-wrap:wrap; gap:8px; font-size:13px; font-weight:700; border-bottom:1px solid #1e293b; padding-bottom:6px; margin-bottom:6px;">
                    <span style="color:#94a3b8;">{oi_tk} · {sel_oi_exp}</span>
                    <span style="color:#10b981;">CALL GEX {tot_call_g:+.2f}M</span>
                    <span style="color:#ef4444;">PUT GEX {tot_put_g:+.2f}M</span>
                    <span style="color:#f59e0b;">NET GEX {tot_net_g:+.2f}M</span>
                    <span style="color:#38bdf8;">LAST CLOSE ${spot_val:,.2f}</span>
                  </div>
                  <div style="display:grid; grid-template-columns:1.1fr 0.8fr 0.9fr 0.9fr 1.1fr; font-size:12px; color:#cbd5e1; gap:4px;">
                    <div style="color:#64748b;">LEVEL</div><div style="color:#64748b;">STRIKE</div><div style="color:#64748b;">VOL</div><div style="color:#64748b;">OI</div><div style="color:#64748b;">GEX</div>
                    <div style="color:#10b981; font-weight:700;">CALL WALL</div><div style="color:#10b981;">${call_wall:g}</div><div>{cw_vol:,}</div><div>{cw_oi:,}</div><div style="color:#10b981;">${gex_by_k.loc[gex_by_k["행사가"]==call_wall, "Call_GEX"].sum():+.2f}M</div>
                    <div style="color:#ef4444; font-weight:700;">PUT WALL</div><div style="color:#ef4444;">${put_wall:g}</div><div>{pw_vol:,}</div><div>{pw_oi:,}</div><div style="color:#ef4444;">${gex_by_k.loc[gex_by_k["행사가"]==put_wall, "Put_GEX"].sum():+.2f}M</div>
                    <div style="color:#f59e0b; font-weight:700;">GEX FLIP</div><div style="color:#f59e0b;">{"$"+f"{zero_g:g}" if zero_g else "-"}</div><div>-</div><div>-</div><div style="color:#f59e0b;">Net {tot_net_g:+.2f}M</div>
                  </div>
                </div>
                """, unsafe_allow_html=True)

                fig_gex = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.05, row_heights=[0.78, 0.22])
                fig_gex.add_trace(go.Bar(x=gex_by_k["행사가"], y=gex_by_k["Call_GEX"], name="CALL GEX", marker_color="#10b981"), row=1, col=1)
                fig_gex.add_trace(go.Bar(x=gex_by_k["행사가"], y=gex_by_k["Put_GEX"], name="PUT GEX", marker_color="#ef4444"), row=1, col=1)
                fig_gex.add_trace(go.Scatter(x=gex_by_k["행사가"], y=gex_by_k["GEX($M)"], name="NET GEX", mode="lines+markers", line=dict(color="#f8fafc", width=1.6), marker=dict(size=4)), row=1, col=1)
                fig_gex.add_trace(go.Bar(x=gex_by_k["행사가"], y=gex_by_k["VOL"], name="STRIKE VOL", marker_color="#cbd5e1", showlegend=False), row=2, col=1)
                if spot_val and spot_val > 0:
                    fig_gex.add_vline(x=spot_val, line_dash="dash", line_color="#f8fafc", annotation_text=f"LAST CLOSE {spot_val:.2f}", annotation_position="top")
                if call_wall:
                    fig_gex.add_vline(x=call_wall, line_dash="dot", line_color="#10b981", annotation_text=f"CALL WALL {call_wall:g}", annotation_position="top left")
                if put_wall:
                    fig_gex.add_vline(x=put_wall, line_dash="dot", line_color="#ef4444", annotation_text=f"PUT WALL {put_wall:g}", annotation_position="bottom left")
                if zero_g:
                    fig_gex.add_vline(x=zero_g, line_dash="dashdot", line_color="#f59e0b", annotation_text=f"FLIP {zero_g:g}", annotation_position="bottom right")
                fig_gex.update_layout(
                    height=500, barmode="relative", plot_bgcolor="#080d17", paper_bgcolor="#080d17",
                    font_color="#e2e8f0", margin=dict(l=12, r=12, t=30, b=10),
                    legend=dict(orientation="h", yanchor="bottom", y=1.01, xanchor="left", x=0)
                )
                fig_gex.update_yaxes(title_text="GEX ($M)", gridcolor="rgba(148,163,184,0.12)", row=1, col=1)
                fig_gex.update_yaxes(title_text="VOL", gridcolor="rgba(148,163,184,0.1)", row=2, col=1)
                fig_gex.update_xaxes(gridcolor="rgba(148,163,184,0.1)")
                st.plotly_chart(fig_gex, use_container_width=True)

                atm_iv = 0.0
                if "IV(%)" in df_e.columns and spot_val > 0:
                    atm_sub = df_e.iloc[(df_e["행사가"] - spot_val).abs().argsort()[:4]]
                    atm_iv = float(atm_sub["IV(%)"].mean())
                exp_mv_1d = round(spot_val * (atm_iv / 100.0) / math.sqrt(252.0), 2) if (spot_val > 0 and atm_iv > 0) else 0.0
                st.markdown(f"""
                <div style="background:#0b1220; border:1px solid #1e293b; border-radius:6px; padding:8px 14px; text-align:center; font-size:13px; font-weight:700; color:#cbd5e1; margin-bottom:10px;">
                  EXPIRY IV · <span style="color:#38bdf8;">ATM IV {atm_iv:.1f}%</span> · <span style="color:#f59e0b;">1D EXP MOVE ±${exp_mv_1d:.2f}</span> · <span style="color:#a855f7;">CALL/PUT WALL {call_wall:g} / {put_wall:g}</span>
                </div>
                """, unsafe_allow_html=True)

                gex_by_k["ABS_GEX"] = gex_by_k["Call_GEX"].abs() + gex_by_k["Put_GEX"].abs()
                tot_abs_g = max(gex_by_k["ABS_GEX"].sum(), 1e-6)
                below_k = gex_by_k[gex_by_k["행사가"] <= spot_val].sort_values("ABS_GEX", ascending=False).head(2) if spot_val > 0 else pd.DataFrame()
                above_k = gex_by_k[gex_by_k["행사가"] > spot_val].sort_values("ABS_GEX", ascending=False).head(2) if spot_val > 0 else pd.DataFrame()
                conc_rows = []
                for lbl, sub_c in [("아래 집중 가격", below_k), ("위 집중 가격", above_k)]:
                    for _, rc in sub_c.iterrows():
                        dist_p = ((rc["행사가"] - spot_val) / spot_val * 100) if spot_val > 0 else 0.0
                        share_p = rc["ABS_GEX"] / tot_abs_g * 100
                        conc_rows.append({
                            "위치": lbl,
                            "가격($)": f"${rc['행사가']:g}",
                            "기준가와 거리": f"{dist_p:+.2f}%",
                            "총 |GEX| (비중)": f"${rc['ABS_GEX']:.2f}M ({share_p:.1f}%)",
                            "Call / Put GEX": f"+${rc['Call_GEX']:.2f}M / ${rc['Put_GEX']:.2f}M",
                        })
                if conc_rows:
                    st.markdown("**📌 옵션 집중 가격 · 관찰 포인트**")
                    st.dataframe(pd.DataFrame(conc_rows), use_container_width=True, hide_index=True)

                hedge_spot_1p = round(tot_net_g * 0.01 * 1000.0, 1)
                st.markdown("<div style='text-align:center; font-size:12px; font-weight:700; color:#94a3b8; margin-top:6px;'>EST HEDGE · CALL+/PUT- ASSUMPTION</div>", unsafe_allow_html=True)
                hg1, hg2, hg3 = st.columns(3)
                g_lim = max(abs(hedge_spot_1p) * 2.0, 500.0)
                with hg1:
                    fig_h1 = go.Figure(go.Indicator(
                        mode="gauge+number", value=hedge_spot_1p,
                        number={"prefix": "$", "suffix": "K", "font": {"size": 18, "color": "#10b981" if hedge_spot_1p >= 0 else "#ef4444"}},
                        title={"text": "SPOT +1% (LINEAR GEX)", "font": {"size": 12, "color": "#cbd5e1"}},
                        gauge={"axis": {"range": [-g_lim, g_lim]}, "bar": {"color": "#f8fafc"},
                               "steps": [{"range": [-g_lim, 0], "color": "rgba(239,68,68,0.28)"}, {"range": [0, g_lim], "color": "rgba(16,185,129,0.28)"}]}
                    ))
                    fig_h1.update_layout(height=180, margin=dict(l=15, r=15, t=35, b=5), paper_bgcolor="#080d17", font_color="#e2e8f0")
                    st.plotly_chart(fig_h1, use_container_width=True)
                with hg2:
                    fig_h2 = go.Figure(go.Indicator(
                        mode="gauge+number", value=round(tot_call_g + tot_put_g, 2),
                        number={"prefix": "$", "suffix": "M", "font": {"size": 18, "color": "#38bdf8"}},
                        title={"text": "NET GAMMA ($M)", "font": {"size": 12, "color": "#cbd5e1"}},
                        gauge={"axis": {"range": [-max(abs(tot_net_g)*2, 5), max(abs(tot_net_g)*2, 5)]}, "bar": {"color": "#38bdf8"},
                               "steps": [{"range": [-max(abs(tot_net_g)*2, 5), 0], "color": "rgba(239,68,68,0.2)"}, {"range": [0, max(abs(tot_net_g)*2, 5)], "color": "rgba(16,185,129,0.2)"}]}
                    ))
                    fig_h2.update_layout(height=180, margin=dict(l=15, r=15, t=35, b=5), paper_bgcolor="#080d17", font_color="#e2e8f0")
                    st.plotly_chart(fig_h2, use_container_width=True)
                with hg3:
                    fig_h3 = go.Figure(go.Indicator(
                        mode="gauge+number", value=round(net_dex_val, 2),
                        number={"prefix": "$", "suffix": "M", "font": {"size": 18, "color": "#f59e0b"}},
                        title={"text": "NET DELTA (DEX $M)", "font": {"size": 12, "color": "#cbd5e1"}},
                        gauge={"axis": {"range": [-max(abs(net_dex_val)*2, 5), max(abs(net_dex_val)*2, 5)]}, "bar": {"color": "#f59e0b"},
                               "steps": [{"range": [-max(abs(net_dex_val)*2, 5), 0], "color": "rgba(239,68,68,0.2)"}, {"range": [0, max(abs(net_dex_val)*2, 5)], "color": "rgba(16,185,129,0.2)"}]}
                    ))
                    fig_h3.update_layout(height=180, margin=dict(l=15, r=15, t=35, b=5), paper_bgcolor="#080d17", font_color="#e2e8f0")
                    st.plotly_chart(fig_h3, use_container_width=True)

            # Call vs Put OI 막대그래프 + DEX 차트 나란히 배치
            ch1, ch2 = st.columns(2)
            with ch1:
                oi_grp = df_e.groupby(["행사가", "구분"])["OI"].sum().reset_index()
                fig_oi = px.bar(
                    oi_grp, x="행사가", y="OI", color="구분", barmode="group",
                    color_discrete_map={"Call": "#00e676", "Put": "#f23645"},
                    title=f"{oi_tk} 행사가별 Call vs Put OI"
                )
                fig_oi.update_layout(plot_bgcolor="#0e1117", paper_bgcolor="#0e1117", font_color="#d1d4dc")
                st.plotly_chart(fig_oi, use_container_width=True)

            with ch2:
                if "DEX($M)" in df_e.columns:
                    dex_by_k = df_e.groupby("행사가")["DEX($M)"].sum().reset_index()
                    dex_by_k["방향"] = dex_by_k["DEX($M)"].apply(lambda x: "Call DEX (+)" if x >= 0 else "Put DEX (-)")
                    fig_dex = px.bar(
                        dex_by_k, x="행사가", y="DEX($M)", color="방향",
                        color_discrete_map={"Call DEX (+)": "#3b82f6", "Put DEX (-)": "#f97316"},
                        title=f"{oi_tk} 행사가별 Delta Exposure (DEX, $M)"
                    )
                    fig_dex.update_layout(plot_bgcolor="#0e1117", paper_bgcolor="#0e1117", font_color="#d1d4dc")
                    st.plotly_chart(fig_dex, use_container_width=True)

            # Vol/OI 급증 & Greeks 전체 테이블 (OI > 0 필터로 0 도배 방지)
            df_vo = df_e[df_e["OI"] > 0].copy()
            if df_vo.empty:
                df_vo = df_e.copy()
            df_vo["Vol/OI"] = (df_vo["거래량"] / df_vo["OI"].replace(0, 1)).round(2)
            st.subheader("🔥 거래량 > 미결제약정 (Vol/OI 급증 & Delta · Gamma · GEX 상세)")
            st.dataframe(
                df_vo.sort_values(["Vol/OI", "거래량"], ascending=False).head(25),
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Delta": st.column_config.NumberColumn("Delta", format="%.3f"),
                    "Gamma": st.column_config.NumberColumn("Gamma", format="%.4f"),
                    "GEX($M)": st.column_config.NumberColumn("GEX($M)", format="%.3f"),
                    "DEX($M)": st.column_config.NumberColumn("DEX($M)", format="%.3f"),
                }
            )

            csv_oi = df_det.to_csv(index=False).encode("utf-8-sig")
            st.download_button("📥 수집된 OI·GEX·Greeks 데이터 CSV 다운로드", csv_oi, f"{oi_tk}_oi_gex_{latest['수집시각'][:10]}.csv", "text/csv")

        if len(snaps) > 1:
            st.subheader("📅 일자별 OI · Net GEX 누적 변화 기록")
            df_hist = pd.DataFrame([{
                "수집시각": s["수집시각"],
                "Spot($)": s.get("Spot", "-"),
                "Call OI": s["Call_OI"],
                "Put OI": s["Put_OI"],
                "P/C 비율": s["Put_Call_OI_Ratio"],
                "Net GEX($M)": s.get("Net_GEX_M", "-"),
                "Net DEX($M)": s.get("Net_DEX_M", "-")
            } for s in snaps[::-1]])
            st.dataframe(df_hist, use_container_width=True, hide_index=True)
    else:
        st.info("아직 저장된 스냅샷이 없습니다. 위 [🔄 지금 OI·GEX 스냅샷 수집 & 저장] 버튼을 눌러 첫 데이터를 모아보세요!")

    st.markdown("---")
    st.subheader("✍️ 수동 OI 메모 추가 (뉴스레터·증권사 HTS 수치 직접 기록)")
    with st.form("manual_oi_form", clear_on_submit=True):
        mc1, mc2, mc3, mc4 = st.columns(4)
        m_tk = mc1.text_input("티커", oi_tk).upper()
        m_call = mc2.number_input("Call OI 합계", min_value=0, value=10000, step=500)
        m_put = mc3.number_input("Put OI 합계", min_value=0, value=8000, step=500)
        m_note = mc4.text_input("메모 (예: LITE 39x OI)", "")
        if st.form_submit_button("💾 수동 OI 스냅샷 저장"):
            from datetime import datetime
            if m_tk not in oi_history: oi_history[m_tk] = []
            oi_history[m_tk].append({
                "수집시각": datetime.now().strftime("%Y-%m-%d %H:%M") + (f" ({m_note})" if m_note else ""),
                "Call_OI": int(m_call),
                "Put_OI": int(m_put),
                "Put_Call_OI_Ratio": round(m_put / m_call, 2) if m_call > 0 else 0,
                "상세": []
            })
            save_json_file(OI_PATH, oi_history)
            st.success(f"✅ {m_tk} 수동 OI 스냅샷 저장 완료!")

# ================= TAB WATCH: PERSONAL WATCHLIST =================
if nav_menu == "⭐ 내 관심종목":
    st.title("⭐ 내 관심종목 (Watchlist) 전용 모아보기")
    st.caption("보유 중이거나 주시하는 종목만 골라 수급과 뉴스를 한눈에 확인하고 텔레그램으로 바로 받아보세요.")

    saved_wl = load_json_file(WL_PATH, ["NVDA", "SNDK", "MU", "TSLA", "META", "INTC", "AMD"])
    all_known_tks = sorted(list(set([r[1] for r in all_raw_flows] + saved_wl)))
    sel_wl = st.multiselect("⭐ 관심종목 관리 (추가/제거 후 자동 저장)", all_known_tks, default=[t for t in saved_wl if t in all_known_tks])
    if sel_wl != saved_wl:
        save_json_file(WL_PATH, sel_wl)

    wl_rows = [r for r in date_filtered_flows if r[1] in sel_wl]
    wl_tot = len(wl_rows)
    wl_calls = sum(1 for r in wl_rows if r[3] == "Call")
    wl_puts = wl_tot - wl_calls
    wl_prem_sum = sum(parse_prem_usd(r[14]) for r in wl_rows)

    wk1, wk2, wk3, wk4 = st.columns(4)
    wk1.metric("관심종목 체결 수", f"{wl_tot}건")
    wk2.metric("콜 / 풋 건수", f"{wl_calls} Call / {wl_puts} Put")
    wk3.metric("합산 프리미엄", f"${wl_prem_sum/1_000_000:,.2f}M")
    wk4.metric("조회 기준일", sel_date)

    if wl_tot > 0:
        if st.button("📩 내 관심종목 수급만 텔레그램 전송", type="primary"):
            t_tok, t_cid = load_tg_config()
            lines = [f"⭐ [OptionHub 관심종목] {sel_date} ({', '.join(sel_wl)}) - {wl_tot}건\n"]
            for r in wl_rows:
                lines.append(f"• [{r[2]}] {r[1]} {r[7]} {r[3]} ({r[5]}) @ {r[14]} [{r[13]}]")
            ok, msg = send_telegram_msg(t_tok, t_cid, "\n".join(lines))
            if ok: st.success(f"✅ {msg}")
            else: st.error(f"❌ {msg}")

        tb_wl = "".join([f"<tr><td><strong>{d[0]}</strong></td><td><strong>{d[1]}</strong></td><td>{d[2]}</td><td class='{'badge-call' if d[3]=='Call' else 'badge-put'}'>{d[3]}</td><td>{d[5]}</td><td><strong>{d[7]}</strong></td><td>{d[13]}</td><td class='kpi-green'><strong>{d[14]}</strong></td></tr>" for d in wl_rows])
        st.markdown(f"<table class='flow-table'><thead><tr><th>DATE</th><th>TICKER</th><th>TIME</th><th>C/P</th><th>EXPIRY</th><th>STRIKE</th><th>TYPE</th><th>PREMIUM</th></tr></thead><tbody>{tb_wl}</tbody></table>", unsafe_allow_html=True)
    else:
        st.info(f"선택하신 날짜({sel_date})에는 등록된 관심종목 체결이 없습니다.")

# ================= TAB OPEX: EXPIRATION CONCENTRATION =================
if nav_menu == "📆 만기 집중도(OPEX)":
    st.title("📆 옵션 만기일별 물량 집중도 (OPEX 캘린더)")
    st.caption(f"선택된 날짜({sel_date}) 기준 어느 만기일에 콜/풋 자금이 가장 많이 몰려 있는지 확인합니다.")

    opex_map = {}
    for r in date_filtered_flows:
        exp = r[5]
        val_m = parse_prem_usd(r[14]) / 1_000_000
        if exp not in opex_map:
            opex_map[exp] = {"만기일": exp, "Call_M": 0.0, "Put_M": 0.0, "건수": 0, "종목": set()}
        if r[3] == "Call":
            opex_map[exp]["Call_M"] += val_m
        else:
            opex_map[exp]["Put_M"] += val_m
        opex_map[exp]["건수"] += 1
        opex_map[exp]["종목"].add(r[1])

    if opex_map:
        df_opex = pd.DataFrame([
            {
                "만기일": k,
                "Call ($M)": round(v["Call_M"], 2),
                "Put ($M)": round(v["Put_M"], 2),
                "합계 ($M)": round(v["Call_M"] + v["Put_M"], 2),
                "체결건수": v["건수"],
                "주요종목": ", ".join(sorted(v["종목"]))
            }
            for k, v in sorted(opex_map.items())
        ])

        fig_opex = go.Figure()
        fig_opex.add_trace(go.Bar(x=df_opex["만기일"], y=df_opex["Call ($M)"], name="Call 프리미엄 ($M)", marker_color="#00e676"))
        fig_opex.add_trace(go.Bar(x=df_opex["만기일"], y=df_opex["Put ($M)"], name="Put 프리미엄 ($M)", marker_color="#f23645"))
        fig_opex.update_layout(
            barmode="stack", plot_bgcolor="#0e1117", paper_bgcolor="#0e1117", font_color="#d1d4dc",
            xaxis_title="만기일 (Expiration Date)", yaxis_title="프리미엄 규모 ($M)",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            margin=dict(l=20, r=20, t=30, b=20)
        )
        st.plotly_chart(fig_opex, use_container_width=True)
        st.dataframe(df_opex, use_container_width=True, hide_index=True)
    else:
        st.info("표시할 만기 데이터가 없습니다.")

# ================= TAB CAL: MACRO & EARNINGS CALENDAR =================
if nav_menu == "🗓️ 거시·실적 캘린더":
    st.title("🗓️ 주요 거시경제(FOMC·CPI) & 실적·IPO 촉매 캘린더")
    st.caption("TradingView 실시간 경제 지표 캘린더와 InsiderFinance 주요 이벤트 일정을 함께 확인하세요.")

    col_cal1, col_cal2 = st.columns([3, 2])
    with col_cal1:
        st.subheader("🌐 실시간 미국 거시경제 지표 캘린더")
        tv_cal_html = """
        <div class="tradingview-widget-container">
          <div class="tradingview-widget-container__widget"></div>
          <script type="text/javascript" src="https://s3.tradingview.com/external-embedding/embed-widget-events.js" async>
          {
            "colorTheme": "dark",
            "isTransparent": false,
            "width": "100%",
            "height": "520",
            "locale": "kr",
            "importanceFilter": "0,1",
            "countryFilter": "us"
          }
          </script>
        </div>
        """
        components.html(tv_cal_html, height=530)

    with col_cal2:
        st.subheader("📌 리포트 기반 핵심 촉매 일정")
        catalysts = [
            ("🏛️ 12월 FOMC 금리 결정", "높은 경계감", "10월 CPI(+0.4% m/m) 상회 및 연준 매파적 발언으로 12월 추가 금리 인상 확률 상승 중"),
            ("💸 Anthropic (ANT) IPO", "11월 말 예정", "클래스A 8.25억주($70~$78) 로드쇼 진행 중. 첫날 개인 매수세 약 $2.5억 추산"),
            ("🛒 Costco (COST) 특별배당", "발표 완료", "주당 $30 특별 현금배당(총 $133억 규모) 및 자사주 매입 재승인"),
            ("⚖️ Nvidia (NVDA) 리스크", "단기 주의", "CEO 관련 이사회 독립 조사 개시 및 Baird 목표가 하향($500→$200)"),
            ("☁️ Amazon (AMZN) 실적 반영", "호실적", "AWS 매출 +39.3%($460억), 수주잔고 $5,780억 기록 (단 2026 Capex $2,200억 부담)"),
            ("🚀 Firefly Aerospace", "가이던스 상향", "Q3 매출 $1.107억, 수주잔고 $17억 사상 최대 및 AST 엔진 계약 $13억+")
        ]
        for t, badge, desc in catalysts:
            st.markdown(f"""
            <div class='moonshot-card'>
                <div style='display:flex; justify-content:space-between;'>
                    <strong style='color:white;'>{t}</strong>
                    <span style='background:#2563eb; color:white; font-size:11px; padding:1px 7px; border-radius:4px;'>{badge}</span>
                </div>
                <div style='font-size:12px; color:#cbd5e1; margin-top:4px;'>{desc}</div>
            </div>
            """, unsafe_allow_html=True)

# ================= TAB TRACK: PERFORMANCE & JOURNAL =================
if nav_menu == "📈 포착 사후 추적":
    st.title("📈 포착 종목 사후 추적 & 내 매매 복기 트래커")
    st.caption("이전 일자(11/10) AI 포착 종목들의 익일(11/11) 후속 흐름 추적 및 개인 매매 일지 기록")

    st.subheader("🔎 11/10 포착 주요 종목 → 11/11 후속 수급 변화")
    followup_rows = [
        {"포착일": "2026-11-10", "종목": "SNDK", "당시 포착": "3건 / $120K OTM (21%)", "11/11 후속 결과": "9건 급증 / $6.8M 스윕 (OTM 31%)", "상태": "🔥 수급 폭발 지속"},
        {"포착일": "2026-11-10", "종목": "NVDA", "당시 포착": "Bear Put Spread ($50M Put)", "11/11 후속 결과": "이사회 조사·목표가 하향($200) 하락", "상태": "✅ 풋 방향 적중"},
        {"포착일": "2026-11-10", "종목": "RIOT", "당시 포착": "Long Call (5일 +20% 랠리)", "11/11 후속 결과": "31% OTM + $696K 스윕 추가 유입", "상태": "🟢 상방 모멘텀 유지"},
        {"포착일": "2026-11-10", "종목": "MU", "당시 포착": "$34.7M 1050P 헷지", "11/11 후속 결과": "주가 강세 속 $24.3M 800P 헷지 추가", "상태": "⚠️ 주가 반등 vs 헷지 지속"},
        {"포착일": "2026-11-10", "종목": "AMD", "당시 포착": "510C 단기 골든스윕 ($2.48M)", "11/11 후속 결과": "주가 급등 후 $6.2M 600P 하방 헷지 유입", "상태": "🔄 목표가 도달 후 헷지 전환"},
    ]
    st.dataframe(pd.DataFrame(followup_rows), use_container_width=True, hide_index=True)

    st.markdown("---")
    st.subheader("📓 내 실전 매매 복기 일지 (서버 자동 저장)")
    journal = load_json_file(JOURNAL_PATH, [])

    with st.form("journal_form", clear_on_submit=True):
        jc1, jc2, jc3, jc4, jc5 = st.columns(5)
        j_tk = jc1.text_input("종목", "SNDK").upper()
        j_dir = jc2.selectbox("포지션", ["Call", "Put"])
        j_entry = jc3.number_input("진입가 ($)", min_value=0.01, value=3.0, step=0.1)
        j_exit = jc4.number_input("청산가 ($)", min_value=0.0, value=4.5, step=0.1)
        j_memo = jc5.text_input("복기 메모", "스윕 따라 진입")
        if st.form_submit_button("💾 매매 기록 저장"):
            ret = ((j_exit - j_entry) / j_entry * 100) if j_entry > 0 else 0.0
            journal.insert(0, {"날짜": sel_date, "종목": j_tk, "구분": j_dir, "진입가": j_entry, "청산가": j_exit, "수익률(%)": round(ret, 1), "메모": j_memo})
            save_json_file(JOURNAL_PATH, journal)
            st.success("저장되었습니다!")

    if journal:
        df_j = pd.DataFrame(journal)
        wins = sum(1 for x in journal if x.get("수익률(%)", 0) > 0)
        win_rate = wins / len(journal) * 100
        avg_ret = sum(x.get("수익률(%)", 0) for x in journal) / len(journal)
        st.markdown(f"**총 {len(journal)}건 기록 | 승률: {win_rate:.1f}% | 평균 수익률: {avg_ret:+.1f}%**")
        st.dataframe(df_j, use_container_width=True, hide_index=True)
    else:
        st.info("아직 기록된 매매 일지가 없습니다. 위 폼에서 첫 거래를 기록해 보세요!")

# ================= TAB SCAN: SMART SCANNER =================
if nav_menu == "🔍 조건별 스캐너":
    st.title("🔍 전종목 조건별 스마트 스캐너")
    st.caption(f"현재 선택된 날짜({sel_date})의 전체 거래 중 원하는 조건만 3초 만에 필터링합니다.")

    sc1, sc2, sc3, sc4 = st.columns(4)
    with sc1:
        f_cp = st.selectbox("콜/풋 구분", ["전체", "Call만 보기", "Put만 보기"])
    with sc2:
        f_typ = st.selectbox("주문 유형", ["전체", "SWEEP", "GOLDEN SWEEP", "BLOCK", "SPLIT"])
    with sc3:
        f_min_p = st.selectbox("최소 프리미엄", ["전체", "$100K 이상", "$500K 이상", "$1M 이상", "$10M 이상", "$30M 이상"])
    with sc4:
        f_kw = st.text_input("티커 검색 (예: NVDA, SNDK)", "").strip().upper()

    min_map = {"전체": 0, "$100K 이상": 100_000, "$500K 이상": 500_000, "$1M 이상": 1_000_000, "$10M 이상": 10_000_000, "$30M 이상": 30_000_000}
    min_val = min_map[f_min_p]

    scanned = []
    for r in date_filtered_flows:
        if f_cp == "Call만 보기" and r[3] != "Call": continue
        if f_cp == "Put만 보기" and r[3] != "Put": continue
        if f_typ != "전체" and f_typ not in r[13].upper(): continue
        if parse_prem_usd(r[14]) < min_val: continue
        if f_kw and f_kw not in r[1]: continue
        scanned.append(r)

    sc_tot = len(scanned)
    sc_calls = sum(1 for r in scanned if r[3] == "Call")
    sc_puts = sc_tot - sc_calls
    st.markdown(f"**검색 결과: 총 {sc_tot}건** (Call {sc_calls}건 / Put {sc_puts}건)")

    if sc_tot > 0:
        if st.button("📩 검색 결과 텔레그램으로 보내기"):
            t_tok, t_cid = load_tg_config()
            lines = [f"🔍 [OptionHub 스캐너] {sel_date} ({f_cp}, {f_typ}, {f_min_p}) - {sc_tot}건\n"]
            for r in scanned:
                lines.append(f"• {r[1]} {r[7]} {r[3]} ({r[5]}) @ {r[14]} [{r[13]}]")
            ok, msg = send_telegram_msg(t_tok, t_cid, "\n".join(lines))
            if ok: st.success(f"✅ {msg}")
            else: st.error(f"❌ {msg}")

        tb_sc = "".join([f"<tr><td><strong>{d[0]}</strong></td><td><strong>{d[1]}</strong></td><td>{d[2]}</td><td class='{'badge-call' if d[3]=='Call' else 'badge-put'}'>{d[3]}</td><td>{d[5]}</td><td><strong>{d[7]}</strong></td><td>{d[13]}</td><td class='kpi-green'><strong>{d[14]}</strong></td></tr>" for d in scanned])
        st.markdown(f"<table class='flow-table'><thead><tr><th>DATE</th><th>TICKER</th><th>TIME</th><th>C/P</th><th>EXPIRY</th><th>STRIKE</th><th>TYPE</th><th>PREMIUM</th></tr></thead><tbody>{tb_sc}</tbody></table>", unsafe_allow_html=True)
    else:
        st.info("조건에 일치하는 옵션 체결 내역이 없습니다.")

# ================= TAB MULTI: MULTI-SOURCE CONSENSUS =================
if nav_menu == "🔗 멀티 소스 검증":
    st.title("🔗 멀티 소스 교차 검증 (구글 시트 실시간 통합)")
    st.caption("InsiderFinance · Menthor Q · Unusual Options · Sweep · Momentum 등 구글 시트에 누적된 전체 소스를 교차 분석합니다.")

    df_ms = load_multisource_sheet()
    if not df_ms.empty:
        col_ms1, col_ms2 = st.columns(2)
        with col_ms1:
            st.subheader("📡 소스/섹션별 누적 데이터 건수")
            sec_counts = df_ms["섹션/소스"].value_counts().reset_index()
            sec_counts.columns = ["섹션/소스", "건수"]
            st.dataframe(sec_counts, use_container_width=True, hide_index=True)
        with col_ms2:
            st.subheader("🎯 다중 소스 교차 포착 TOP 종목")
            tk_sec = df_ms.groupby("티커").agg(총체결건수=("섹션/소스", "count"), 포착섹션=("섹션/소스", lambda x: ", ".join(sorted(set(x))))).reset_index().sort_values("총체결건수", ascending=False).head(15)
            st.dataframe(tk_sec, use_container_width=True, hide_index=True)

        st.markdown("---")
        st.subheader("📋 전체 멀티 소스 원장 검색")
        ms_kw = st.text_input("멀티 소스 내 티커 또는 키워드 검색 (예: MU, ES, Menthor)", "").strip().upper()
        df_show = df_ms[df_ms.apply(lambda r: ms_kw in str(r).upper(), axis=1)] if ms_kw else df_ms.head(100)
        st.dataframe(df_show, use_container_width=True, hide_index=True)
    else:
        st.warning("구글 시트 멀티 소스 데이터를 불러오는 중입니다.")

# ================= TAB 2: TOP 10 MOONSHOT FLOWS =================
if nav_menu == "🚀 Top 10 문샷":
    st.title("🚀 Top 10 Moonshot & Momentum 급등주 포착")
    st.caption("출처: InsiderFinance Top 10 Moonshot Flows & Momentum Options Activity (2026-11-11)")

    col_m1, col_m2 = st.columns([3, 2])
    
    with col_m1:
        st.subheader("🎯 Top 10 Moonshot Flows (기관 초외가격·단기 급등 베팅)")
        moonshots = [
            ("INTC", "03:58 PM", "Call", "85", "2026-11-27", "$55K", "Unusual · Top Position · Sweep", "장마감 직전 유입된 초외가격 $85 단기 콜 스윕"),
            ("PDFS", "01:31 PM", "Call", "50", "2026-11-20", "$12K", "Unusual · Top Position · Sweep", "반도체 SW 소형주 단기 촉매 노린 이례적 콜 스윕"),
            ("BW", "10:46 AM", "Call", "7", "2026-12-18", "$74K", "Top Position · Block", "Babcock & Wilcox 12월물 최상위 포지션 콜 블록"),
            ("CIFR", "10:04 AM", "Call", "9", "2027-01-15", "$870K", "Above Ask · Block", "비트코인 채굴주 $870K 규모 매도호가 돌파 대형 블록"),
            ("INTC", "03:58 PM", "Call", "85", "2026-11-27", "$42K", "Unusual · Top Position · Sweep", "동일 행사가·만기 연속 유입된 두 번째 단기 콜 스윕"),
            ("BW", "11:01 AM", "Call", "7.5", "2027-01-15", "$75K", "Sweep", "BW 1월물 $7.5 콜 연속 매집 스윕"),
            ("FRVO", "10:15 AM", "Call", "21", "2027-01-15", "$134K", "Top Position · Sweep", "연초 만기 최상위 포지션 콜 스윕 집중"),
            ("AZTA", "10:26 AM", "Call", "55", "2026-11-20", "$11K", "Unusual · Top Position · Sweep", "단기 반등 겨냥 초외가격 스윕"),
            ("LSCC", "11:57 AM", "Call", "160", "2027-01-15", "$133K", "Top Position · Block", "래티스 반도체 장기 상방 블록 체결"),
            ("ACHR", "10:43 AM", "Call", "6", "2027-01-15", "$71K", "Sweep", "아처 에비에이션(eVTOL) 모멘텀 콜 스윕")
        ]
        
        for tk, tm, cp, stk, exp, prem, tags, note in moonshots:
            st.markdown(f"""
            <div class='moonshot-card'>
                <div style='display:flex; justify-content:space-between; align-items:center;'>
                    <span style='font-size:16px; font-weight:800; color:#00e676;'>🚀 {tk} ${stk} {cp}</span>
                    <span style='color:#ffffff; font-weight:700; background:#16a34a; padding:2px 8px; border-radius:4px;'>{prem}</span>
                </div>
                <div style='font-size:12px; color:#94a3b8; margin: 4px 0;'>
                    만기: <strong>{exp}</strong> | 시간: {tm} | 태그: <span style='color:#f59e0b;'>{tags}</span>
                </div>
                <div style='font-size:12px; color:#cbd5e1;'>💡 {note}</div>
            </div>
            """, unsafe_allow_html=True)

    with col_m2:
        st.subheader("⚡ 일평균 거래량 급증 (Momentum x배)")
        mom_data = {
            "Ticker": ["KGC", "BW", "BZ", "ACHR", "TE", "FOSL", "SB", "VRNS", "PEPG", "QMCO"],
            "Multiple": [11.2, 6.0, 5.5, 5.3, 3.7, 3.7, 2.5, 2.5, 2.3, 2.3]
        }
        df_mom = pd.DataFrame(mom_data)
        fig_mom = px.bar(
            df_mom, x="Multiple", y="Ticker", orientation="h", text="Multiple",
            color="Multiple", color_continuous_scale="Viridis"
        )
        fig_mom.update_traces(texttemplate='%{text}x', textposition='outside')
        fig_mom.update_layout(
            plot_bgcolor="#0e1117", paper_bgcolor="#0e1117", font_color="#d1d4dc",
            yaxis=dict(autorange="reversed"), xaxis=dict(title="평소 거래량 대비 배수 (x배)"),
            margin=dict(l=20, r=20, t=10, b=20)
        )
        st.plotly_chart(fig_mom, use_container_width=True)
        
        st.info("💡 **트레이딩 팁:** KGC(킨로스 골드, 11.2배)와 BW(6.0배), ACHR(5.3배) 모두 0% Put Flow로 전량 콜옵션 매집이 포착되었습니다.")

# ================= TAB 3: 5-DAY FLOW & GEX SUPPORT/RESISTANCE =================
if nav_menu == "📅 5일 수급 & GEX":
    st.title("📅 5일 누적 기관 수급 추세 & 핵심 지지·저항선 (GEX)")
    st.caption("출처: InsiderFinance Equities 5-Day Flow & Gamma Exposure Analysis (2026-11-11)")

    st.subheader("📊 주요 대형주 5일 누적 풋/콜 비율 & 기관 프리미엄 총액")
    
    five_day_data = [
        {"Ticker": "NVDA", "Call_Pct": 35, "Put_Pct": 65, "Prem_M": 1176.9, "OTM": "13%", "Vol": "3.1M"},
        {"Ticker": "TSLA", "Call_Pct": 50, "Put_Pct": 50, "Prem_M": 315.4, "OTM": "5%", "Vol": "804K"},
        {"Ticker": "INTC", "Call_Pct": 24, "Put_Pct": 76, "Prem_M": 574.4, "OTM": "-3%", "Vol": "497K"},
        {"Ticker": "AAPL", "Call_Pct": 60, "Put_Pct": 40, "Prem_M": 80.9, "OTM": "4%", "Vol": "440K"},
        {"Ticker": "MU", "Call_Pct": 45, "Put_Pct": 55, "Prem_M": 430.4, "OTM": "16%", "Vol": "286K"},
        {"Ticker": "IREN", "Call_Pct": 36, "Put_Pct": 64, "Prem_M": 53.5, "OTM": "48%", "Vol": "259K"},
        {"Ticker": "CRWV", "Call_Pct": 29, "Put_Pct": 71, "Prem_M": 85.4, "OTM": "30%", "Vol": "256K"},
        {"Ticker": "AMZN", "Call_Pct": 78, "Put_Pct": 22, "Prem_M": 64.3, "OTM": "6%", "Vol": "227K"},
        {"Ticker": "PCG", "Call_Pct": 100, "Put_Pct": 0, "Prem_M": 10.1, "OTM": "19%", "Vol": "199K"},
        {"Ticker": "AMD", "Call_Pct": 16, "Put_Pct": 84, "Prem_M": 304.0, "OTM": "10%", "Vol": "193K"}
    ]
    df_5d = pd.DataFrame(five_day_data)
    
    fig_5d = go.Figure()
    fig_5d.add_trace(go.Bar(
        y=df_5d["Ticker"], x=df_5d["Call_Pct"], name="콜옵션 비율(%)", orientation='h',
        marker=dict(color='#00e676')
    ))
    fig_5d.add_trace(go.Bar(
        y=df_5d["Ticker"], x=df_5d["Put_Pct"], name="풋옵션 비율(%)", orientation='h',
        marker=dict(color='#f23645')
    ))
    fig_5d.update_layout(
        barmode='stack', plot_bgcolor="#0e1117", paper_bgcolor="#0e1117", font_color="#d1d4dc",
        xaxis=dict(title="비율 (%)", range=[0, 100]), yaxis=dict(autorange="reversed"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=20, r=20, t=30, b=20)
    )
    st.plotly_chart(fig_5d, use_container_width=True)

    st.markdown("---")
    st.subheader("🎯 핵심 종목별 주요 옵션 장벽 (Wall & Hedge Levels)")
    
    col_g1, col_g2, col_g3, col_g4 = st.columns(4)
    with col_g1:
        st.markdown("""
        <div class='gex-card'>
            <div style='font-size:16px; font-weight:800; color:#00e676;'>META</div>
            <div style='font-size:12px; color:#94a3b8; margin: 4px 0;'>다크풀 매집 + 콜 편중</div>
            <div style='font-size:13px; color:#4ade80;'><strong>핵심 콜 목표: $750</strong></div>
            <div style='font-size:11px; color:#64748b;'>2027-1-15 $31.0M 스윕</div>
            <div style='font-size:12px; color:#cbd5e1; margin-top:4px;'>강력한 상방 포지셔닝</div>
        </div>
        """, unsafe_allow_html=True)
    with col_g2:
        st.markdown("""
        <div class='gex-card'>
            <div style='font-size:16px; font-weight:800; color:#f23645;'>MU</div>
            <div style='font-size:12px; color:#94a3b8; margin: 4px 0;'>5일 55% 풋 우세</div>
            <div style='font-size:13px; color:#f87171;'><strong>풋 방어선: $800</strong></div>
            <div style='font-size:11px; color:#64748b;'>$24.3M 장기 풋 스윕</div>
            <div style='font-size:13px; color:#4ade80; margin-top:4px;'><strong>단기 콜: $750</strong></div>
        </div>
        """, unsafe_allow_html=True)
    with col_g3:
        st.markdown("""
        <div class='gex-card'>
            <div style='font-size:16px; font-weight:800; color:#f23645;'>AMD</div>
            <div style='font-size:12px; color:#94a3b8; margin: 4px 0;'>5일 84% 풋 쏠림</div>
            <div style='font-size:13px; color:#f87171;'><strong>풋 헷지선: $600</strong></div>
            <div style='font-size:11px; color:#64748b;'>$6.2M 골든 스윕 (5x OI)</div>
            <div style='font-size:12px; color:#cbd5e1; margin-top:4px;'>급등 후 단기 하방 방어</div>
        </div>
        """, unsafe_allow_html=True)
    with col_g4:
        st.markdown("""
        <div class='gex-card'>
            <div style='font-size:16px; font-weight:800; color:#00e676;'>SPX / IBIT</div>
            <div style='font-size:12px; color:#94a3b8; margin: 4px 0;'>지수 대규모 헷지</div>
            <div style='font-size:13px; color:#f87171;'><strong>SPX 풋: 8000 / 7600</strong></div>
            <div style='font-size:11px; color:#64748b;'>당일 $77M 등 대형 풋 스플릿</div>
            <div style='font-size:13px; color:#4ade80; margin-top:4px;'><strong>IBIT 콜: $48 ($63.4M)</strong></div>
        </div>
        """, unsafe_allow_html=True)

# ================= TAB 4: AI OPTIONS PLAYS & NOTEWORTHY =================
if nav_menu == "⚡ AI Plays & Note":
    st.title("⚡ AI Options Plays & Noteworthy Trades")
    st.caption("출처: InsiderFinance AI Options Plays BETA & AI Noteworthy Trades (2026-11-11)")

    st.subheader("🎯 AI Options Plays BETA (기관 추천 실전 옵션 전략 5선)")
    plays = [
        ("1. MU Bear Put Spread (베어 풋 스프레드)", "Bearish (5/5 Strength)", False,
         "향후 2~6주 만기 근접 등가격(NTM) 행사가를 활용한 베어 풋 스프레드로, 높아진 풋 수요에 맞추되 AI 랠리가 연장될 경우 프리미엄 지출을 제한합니다.",
         "Consider a bear put spread in MU using near the money strikes with expiries in roughly the next 2-6 weeks to align with elevated put demand while limiting premium outlay if the AI rally extends.",
         "MU는 지난주 급등했지만 주간 옵션은 여전히 풋옵션 비중이 높으며 오늘 2,400만 달러가 넘는 800달러 풋 스윕을 포함해 다수의 대형 장기 헷지가 포착되었습니다. 지속적인 반도체 헷지 및 매파적 연준·AI 규제 불확실성과 맞물려, 손실이 제한된 하방 구조가 신중함을 표현하는 효율적 방법입니다.",
         "MU has surged over the past week yet its weekly options remain put heavy with multiple large long dated hedges, including today’s nearly at the money eight hundred put sweep over twenty four million. That aligns with persistent semiconductor hedging and a hawkish Fed plus AI regulation overhang."),

        ("2. AMD Bear Put Spread (베어 풋 스프레드)", "Bearish (4/5 Strength)", False,
         "현재 주가 수준 부근 행사가와 2~6주 만기의 베어 풋 스프레드를 활용해 기관의 헷지 흐름에 동참하되, 상승 모멘텀이 지속될 경우 시간가치 하락(Decay)을 제한합니다.",
         "Use a bear put spread in AMD with strikes around current levels and expiries in the next 2-6 weeks to lean into institutional hedging while capping decay if upside momentum persists.",
         "AMD는 주간 기준 강하게 상승했으나 주간 옵션은 풋이 지배하고 있으며 오늘 테이프에서는 600달러 행사가 부근의 여러 골든 스윕 하방 매수가 포착되었습니다. 기술주 전반이 금리 및 AI 뉴스 압력을 받는 가운데 고베타 주도주의 되돌림 위험을 시사합니다.",
         "AMD is up strongly on the week even as weekly options are dominated by puts and today’s tape features several golden sweep downside buys around the six hundred strike. With technology broadly under rate and AI headline pressure, this positioning points to meaningful risk of a giveback."),

        ("3. TSLA Long Call (테슬라 롱 콜 전략)", "Bullish (5/5 Strength)", True,
         "1~3개월 만기의 등가격(ATM) 또는 약외가격(OTM) TSLA 콜옵션에 집중하여 당일 만기(0DTE)의 급격한 시간가치 소멸을 피하면서 지속되는 상방 수요와 모멘텀을 포착합니다.",
         "Focus on at or slightly out of the money TSLA calls 1-3 months out to capture ongoing upside demand and momentum while avoiding the fastest decaying same day contracts.",
         "TSLA는 1일 및 5일 기준 경기소비재 섹터를 아웃퍼폼하고 있으며, 이번 주 및 11월 말 만기에 걸친 대형 상방 스윕 등 섹터 내 가장 강한 콜 우위 플로우를 보여줍니다. 약한 소비재 장세 속에서도 기관들이 TSLA에 대해서는 기꺼이 상방 프리미엄을 지불하고 있음을 시사합니다.",
         "TSLA has outperformed consumer cyclicals over one and five days and shows some of the heaviest call dominated flow in the sector, including large upside sweeps across same week and late November expiries."),

        ("4. META Long Call (메타 롱 콜 전략)", "Bullish (5/5 Strength)", True,
         "1~3개월 만기의 등가격(ATM) 또는 약외가격(OTM) META 콜옵션을 선호하여 다크풀 매집과 섹터 심리가 반영될 충분한 시간을 확보하면서 강력한 상방 포지셔닝에 동참합니다.",
         "Favor at or modestly out of the money META calls 1-3 months out to ride strong upside positioning while giving time for dark pool accumulation and sector sentiment to play through.",
         "META 옵션은 오늘 약 3,100만 달러 규모의 장기물 콜 스윕을 필두로 압도적으로 콜에 치우쳐 있으며, 커뮤니케이션 서비스 섹터 부진 속에서도 현물 체결 데이터상 강력한 매집이 나타납니다. 기관들이 섹터 내 신중한 분위기 속에서도 META의 저점 매수에 나서고 있습니다.",
         "META’s options are overwhelmingly call skewed today, highlighted by a roughly thirty one million premium sweep in longer dated calls, and equity print data show strong accumulation even as the broader communication services sector lags."),

        ("5. AMZN Bull Call Spread (아마존 불 콜 스프레드)", "Bullish (4/5 Strength)", True,
         "1~3개월 만기 근접 등가격(NTM) 행사가를 활용한 AMZN 불 콜 스프레드로 AWS 기반 성장에 대한 긍정적 시각을 반영하되, 거시 지표 발표 전후 변동성 확대 시 노출을 줄입니다.",
         "A bull call spread in AMZN using near the money strikes with expiries in roughly the next 1-3 months can express a constructive view on AWS driven growth while reducing exposure if volatility rises around macro data.",
         "장중 다소 약세였음에도 AMZN은 주간 상승세를 유지하며 여러 만기에 걸쳐 꾸준한 매도호가(Ask) 콜 스윕이 유입되고 있습니다. 성장 가속화와 사상 최대 수주잔고(Backlog)를 강조한 최근 AWS 코멘터리가 이러한 타겟 상방 포지셔닝에 펀더멘털 순풍을 더합니다.",
         "Despite a softer session, AMZN holds gains on the week and sees steady ask side call sweeps across tenors, while consumer cyclical sector options remain broadly call biased. Recent AWS commentary highlighting accelerating growth and a record backlog adds a fundamental tailwind.")
    ]

    for title, out, is_bull, st_ko, st_en, why_ko, why_en in plays:
        c_cls = "strategy-card" if is_bull else "strategy-card strategy-card-red"
        col = "#00e676" if is_bull else "#f23645"
        st.markdown(f"""
        <div class='{c_cls}'>
            <div style='display:flex; justify-content:space-between; align-items:center;'>
                <span style='font-size:16px; font-weight:700; color:white;'>{title}</span>
                <span style='background:{col}; color:black; font-size:11px; font-weight:800; padding:2px 8px; border-radius:4px;'>{out}</span>
            </div>
            <div style='margin-top:8px; font-size:13px; color:#e0e0e0;'><strong>💡 실행 전략:</strong> {st_ko}</div>
            <div style='font-size:11px; color:#787b86; margin-bottom:8px;'>[EN] {st_en}</div>
            <div style='font-size:13px; color:#cfd8dc;'><strong>🔍 선정 배경:</strong> {why_ko}</div>
            <div style='font-size:11px; color:#787b86;'>[EN] {why_en}</div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("---")
    st.subheader("⚡ AI Noteworthy Trades BETA (기관 핵심 대형 체결 6선 전체)")
    
    notes = [
        ("META 750 Call 2027-1-15 @ $31.0M", "2026-11-11 12:12 PM", "Positioning (5/5 Strength)", True, "Sweep",
         "약 3,100만 달러 프리미엄과 미결제약정(OI)의 1/3 규모에 달하는 거대한 1월물 외가격 콜 스윕으로, 단기 감마 트레이드가 아닌 의도적인 상방 포지셔닝입니다. META의 콜 중심 일간 플로우 및 강력한 다크풀 매집과 일치합니다.",
         "A huge out of the money January call sweep with roughly thirty one million in premium and size a third of open interest looks like deliberate upside positioning rather than a quick gamma trade. It aligns with call dominated daily flow and strong dark pool accumulation in META."),

        ("MU 800 Put 2027-3-19 @ $24.3M", "2026-11-11 9:51 AM", "Hedge (5/5 Strength)", False, "Sweep",
         "등가격에 가까운 장기물 800달러 풋옵션을 매도호가(Ask)에 2,430만 달러 이상 매수한 건으로, MU 및 반도체 전반의 주간 풋 편중 현상과 일치합니다. 수일간의 강한 랠리 이후 수익을 확정하고 AI/매크로 반전 위험에 대비하는 기관의 보험 성격입니다.",
         "Buying nearly at the money long dated eight hundred puts for over twenty four million on the ask fits the heavy weekly put skew in MU and the broader semiconductor complex. After a strong multi day rally, this size and tenor point to institutions locking in gains."),

        ("AMD 600 Put 2026-11-20 @ $6.2M", "2026-11-11 1:56 PM", "Hedge (5/5 Strength)", False, "Golden Sweep",
         "600만 달러 이상 프리미엄과 미결제약정의 5배를 넘는 11월물 600달러 풋 골든 스윕은 AMD 주간 옵션의 지배적 풋 편향을 강화합니다. 강한 상승 이후 변동성이 큰 매크로 및 AI 뉴스 구간을 앞두고 단기 하방 방어에 비용을 지불하는 모습입니다.",
         "A golden sweep in November six hundred puts with premium above six million and size more than five times open interest reinforces the dominant put skew in AMD's weekly options. Looks like institutions paying up for near term downside protection."),

        ("TSLA 410 Call 2026-11-27 @ $4.2M", "2026-11-11 9:58 AM", "Short-Term (5/5 Strength)", True, "Sweep",
         "400만 달러가 넘는 11월 말 만기 410달러 콜 스윕은 매도호가(Ask)에 매수된 ATM/OTM TSLA 콜 클러스터에 힘을 더합니다. 약세 소비재 섹터 대비 아웃퍼폼하며 선호 주도주에 대한 공격적 상방 베팅을 보여줍니다.",
         "A late November four ten call sweep over four million in premium adds to a dense cluster of at and just out of the money TSLA calls bought on the ask. Reads as aggressive upside positioning in a favored leader."),

        ("INTC 50 Call 2027-2-19 @ $31.0M", "2026-11-11 1:05 PM", "Stock Replacement (4/5 Strength)", True, "Block",
         "약 3,100만 달러 규모의 매우 큰 내가격(ITM) 2027년 콜 블록으로 동일 행사가의 기존 포지션을 확장하며 주식 대체(Stock Replacement) 또는 레버리지 롱 익스포저 성격을 띱니다. 최근 인덱스 스타일 풋 헷지에도 불구하고 최소 한 곳 이상의 대형 계좌가 추가 상승에 베팅하고 있습니다.",
         "This very large in the money twenty twenty seven call block near thirty one million in premium extends an already notable position in the same strike, resembling stock replacement or levered long exposure."),

        ("LITE 750 Put 2026-11-13 @ $12.6M", "2026-11-11 9:34 AM", "Short-Term (4/5 Strength)", False, "Golden Sweep",
         "두 자릿수 일일 급등 직후 유입된 금주 만기 깊은 내가격(Deep ITM) 750달러 풋 골든 스윕으로, 1,200만 달러 이상 프리미엄에 미결제약정의 39배 규모입니다. LITE 주간 풋 우위와 함께 급격한 단기 되돌림이나 변동성 급등에 대비하는 거래로 보입니다.",
         "A front week golden sweep in deep in the money seven fifty puts with premium above twelve million and size thirty nine times open interest lands immediately after a double digit one day rally.")
    ]

    for title, tm, intent, is_bull, tags, why_ko, why_en in notes:
        c_cls = "ainote-card ainote-card-green" if is_bull else "ainote-card"
        col = "#00e676" if is_bull else "#f23645"
        st.markdown(f"""
        <div class='{c_cls}'>
            <div style='display:flex; justify-content:space-between; align-items:center;'>
                <span style='font-size:15px; font-weight:700; color:white;'>[{tm}] {title}</span>
                <span style='background:{col}; color:black; font-size:11px; font-weight:800; padding:2px 8px; border-radius:4px;'>{intent}</span>
            </div>
            <div style='font-size:11px; color:#ffb74d; margin: 4px 0;'>🏷️ {tags}</div>
            <div style='font-size:13px; color:#d1d4dc; margin-top:6px;'><strong>🔎 AI 심층 분석:</strong> {why_ko}</div>
            <div style='font-size:11px; color:#787b86; margin-top:4px;'>[원문] {why_en}</div>
        </div>
        """, unsafe_allow_html=True)

# ================= TAB 5: OPTIONS TOP TICKERS CHARTS =================
if nav_menu == "📊 Options Top 차트":
    st.title("📊 Options Top Tickers 차트 및 데이터 해석")
    st.caption("출처: InsiderFinance Evening Edge Options Top Tickers (2026-11-11)")
    
    col_c1, col_c2 = st.columns(2)
    
    with col_c1:
        st.subheader("🔵 Unusual OTM % (외가격 이상 급등 종목)")
        otm_data = {
            "Ticker": ["IREN", "AMAT", "INTC", "TSLA", "RIOT", "SNDK", "MRNA", "SHAZ", "NVDA", "GME"],
            "OTM_Pct": [43, 37, 37, 33, 31, 31, 28, 28, 27, 26]
        }
        df_otm = pd.DataFrame(otm_data)
        fig_otm = px.bar(
            df_otm, x="Ticker", y="OTM_Pct", text="OTM_Pct",
            color_discrete_sequence=["#2979ff"]
        )
        fig_otm.update_traces(texttemplate='%{text}%', textposition='outside')
        fig_otm.update_layout(
            plot_bgcolor="#0e1117", paper_bgcolor="#0e1117",
            font_color="#d1d4dc", yaxis=dict(title="OTM %", range=[0, 55], gridcolor="#1e222d"),
            xaxis=dict(title="", gridcolor="#1e222d"), margin=dict(l=20, r=20, t=30, b=20)
        )
        st.plotly_chart(fig_otm, use_container_width=True)
        
        st.markdown("""
        <div class='chart-analysis'>
            <h4 style='color:#2979ff; margin:0 0 8px 0;'>💡 Unusual OTM % 데이터 해석</h4>
            <ul style='font-size:13px; color:#cfd8dc; margin-bottom:0; padding-left:18px; line-height:1.6;'>
                <li><strong>IREN (43%) & RIOT (31%):</strong> 크립토 채굴주에 이틀 연속 30~40%대 초외가격 옵션 유입이 이어지며 비트코인·고베타 모멘텀 베팅이 활발합니다.</li>
                <li><strong>AMAT (37%) & INTC (37%):</strong> 반도체 장비·제조 대표주에 높은 OTM 콜 스윕이 포착되며 반등 탄력성을 노린 외가격 매집이 진행되었습니다.</li>
                <li><strong>SNDK (31%):</strong> 전일 21%에서 31%로 OTM 비중이 확대되며 총 9건($6.8M 스윕)의 공격적 콜 매수가 집중되었습니다.</li>
            </ul>
        </div>
        """, unsafe_allow_html=True)
        
    with col_c2:
        st.subheader("🟣 Sweep Volume (기관 초강력 스윕 계약수)")
        sweep_data = {
            "Ticker": ["NVDA", "TSLA", "MU", "AAPL", "AMD", "META", "CRWV", "INTC", "AMZN", "IREN"],
            "Contracts_K": [413, 257, 79, 79, 48, 48, 47, 40, 33, 27]
        }
        df_swp = pd.DataFrame(sweep_data)
        fig_swp = px.bar(
            df_swp, x="Ticker", y="Contracts_K", text="Contracts_K",
            color_discrete_sequence=["#ab47bc"]
        )
        fig_swp.update_traces(texttemplate='%{text:,.0f}K', textposition='outside')
        fig_swp.update_layout(
            plot_bgcolor="#0e1117", paper_bgcolor="#0e1117",
            font_color="#d1d4dc", yaxis=dict(title="Sweep Contracts (천 건)", range=[0, 480], gridcolor="#1e222d"),
            xaxis=dict(title="", gridcolor="#1e222d"), margin=dict(l=20, r=20, t=30, b=20)
        )
        st.plotly_chart(fig_swp, use_container_width=True)
        
        st.markdown("""
        <div class='chart-analysis' style='border-left-color: #ab47bc;'>
            <h4 style='color:#ab47bc; margin:0 0 8px 0;'>💡 Sweep Volume 데이터 해석</h4>
            <ul style='font-size:13px; color:#cfd8dc; margin-bottom:0; padding-left:18px; line-height:1.6;'>
                <li><strong>NVDA (413K) & TSLA (257K):</strong> 개별주 스윕 거래량 압도적 1·2위. NVDA는 목표가 하향($200) 및 이사회 조사 이슈 속에서 장기 콜·풋 양방향 거래가 활발합니다.</li>
                <li><strong>MU (79K) & AMD (48K):</strong> 반도체 급등 속에서 대규모 풋 헷지($24.3M / $6.2M)가 스윕 형태로 빠르게 체결되었습니다.</li>
                <li><strong>META (48K) & INTC (40K):</strong> META $31M 콜 스윕과 INTC $31M 콜 블록 등 초대형 단일 포지션 구축이 돋보였습니다.</li>
            </ul>
        </div>
        """, unsafe_allow_html=True)

# ================= TAB 6: TREEMAP & THEMES =================
if nav_menu == "🗺️ 히트맵 & 테마":
    st.title("🗺️ 섹터별 기관 수급 히트맵 & 핵심 테마 분석")
    st.caption("출처: InsiderFinance AI Market Insights BETA (2026-11-11)")

    tree_data = [
        {"Sector": "Technology", "Ticker": "NVDA", "Premium_M": 1176.9, "Call_Pct": 35, "Flow": "Put 65% (장기 풋 헷지 지속)"},
        {"Sector": "Technology", "Ticker": "INTC", "Premium_M": 574.4, "Call_Pct": 24, "Flow": "Put 76% (단 $31M 콜 블록 포착)"},
        {"Sector": "Technology", "Ticker": "MU", "Premium_M": 430.4, "Call_Pct": 45, "Flow": "Put 55% ($24.3M 800P 헷지)"},
        {"Sector": "Technology", "Ticker": "AMD", "Premium_M": 304.0, "Call_Pct": 16, "Flow": "Put 84% ($6.2M 600P 골든스윕)"},
        {"Sector": "Technology", "Ticker": "CRWV", "Premium_M": 85.4, "Call_Pct": 29, "Flow": "Put 71% (AI 인프라 부채 우려)"},
        {"Sector": "Technology", "Ticker": "AAPL", "Premium_M": 80.9, "Call_Pct": 60, "Flow": "Call 60% (콜 비중 확대)"},
        {"Sector": "Communication", "Ticker": "META", "Premium_M": 31.0, "Call_Pct": 95, "Flow": "Call 우위 ($31M 750C + 다크풀 매집)"},
        {"Sector": "Consumer Cyclical", "Ticker": "TSLA", "Premium_M": 315.4, "Call_Pct": 50, "Flow": "콜 스윕 클러스터 집중"},
        {"Sector": "Consumer Cyclical", "Ticker": "AMZN", "Premium_M": 64.3, "Call_Pct": 78, "Flow": "Call 78% (AWS 성장 모멘텀)"},
        {"Sector": "Crypto / High-Beta", "Ticker": "IREN", "Premium_M": 53.5, "Call_Pct": 36, "Flow": "Put 64% (48% OTM)"},
        {"Sector": "Utilities & Defensives", "Ticker": "PCG", "Premium_M": 10.1, "Call_Pct": 100, "Flow": "Call 100% (경기방어 콜)"},
        {"Sector": "Materials / Gold", "Ticker": "KGC", "Premium_M": 1.2, "Call_Pct": 100, "Flow": "Call 100% (11.2x 모멘텀)"},
        {"Sector": "Small Caps", "Ticker": "SNDK", "Premium_M": 6.8, "Call_Pct": 88, "Flow": "Call 88% (9건 스윕 집중)"}
    ]
    df_tree = pd.DataFrame(tree_data)

    fig = px.treemap(
        df_tree, path=['Sector', 'Ticker'], values='Premium_M', color='Call_Pct',
        color_continuous_scale=['#f23645', '#363a45', '#00e676'],
        color_continuous_midpoint=50,
        hover_data=['Flow'],
        title="기관 프리미엄 규모 및 Call 비중 (%) (초록색: 콜 우세, 붉은색: 풋 우세)"
    )
    fig.update_layout(
        paper_bgcolor="#0b0e14", plot_bgcolor="#0b0e14", font_color="#d1d4dc",
        margin=dict(t=40, l=10, r=10, b=10)
    )
    st.plotly_chart(fig, use_container_width=True)

    st.markdown("---")
    st.subheader("📌 AI Market Insights (시장 핵심 4대 테마 원문 및 한글 해석)")

    themes = [
        ("AI 칩 랠리 속에서도 지속되는 반도체 섹터 하방 헷지",
         "Bearish (5/5 Strength) · Established (최초 포착: 2026-10-05)", False,
         "MU, AMD, MRVL 등 주요 반도체 종목들이 주간 강세를 기록 중이지만, 섹터 및 ETF 옵션은 여전히 풋옵션 비중이 높고 여러 만기에 걸쳐 최상위 포지션 하방 블록이 반복되고 있습니다. 뜨거운 인플레이션과 매파적 연준, AI 규제 우려 속에서 기관들은 주가 강세를 이용해 상방을 추격하기보다 중기 하방 방어(Protection) 기간을 연장하고 있습니다.",
         "MU, AMD, MRVL and other semiconductor leaders post strong weekly gains while sector and ETF options still lean heavily to puts, with repeated top position downside blocks across tenors. In a hotter inflation and hawkish Fed backdrop with ongoing AI regulation worries, this pattern shows institutions using strength to extend medium dated downside protection rather than chase upside."),

        ("소형주 상승세 지속에도 극단적 수준을 유지하는 지수 풋 헷지",
         "Bearish (5/5 Strength) · Established (최초 포착: 2026-11-04)", False,
         "IWM은 1일 및 5일 기준 상승세를 이어가고 있지만 일간·주간 옵션 모두 압도적으로 풋에 쏠려 있으며 신규 대형 하방 블록으로 방어 비중이 이전 극단치 부근에 머물러 있습니다. 뜨거운 CPI와 12월 연준 결정의 불확실성 속에서 펀드들은 랠리에 참여하면서도 깊은 하락에 대비한 대규모 인덱스 헷지를 유지하고 있습니다.",
         "IWM extends its advance over one and five days even as daily and weekly options remain overwhelmingly put heavy, with fresh large downside blocks keeping protection near prior extremes. With hot CPI and an uncertain December Fed outcome, funds appear to be riding the rally while maintaining substantial index hedges."),

        ("선별적 소비재 성장 리더주(TSLA·AMZN)의 상대적 강세와 상방 수요 집중",
         "Bullish (4/5 Strength) · Established (최초 포착: 2026-11-11 10:25 AM)", True,
         "약세인 경기소비재 섹터 내에서도 TSLA와 AMZN은 주간 상대적 승자로 남으며 콜 우위 플로우를 끌어모으고 있고, 주간 매도호가(Ask) 매수 활동의 상당 부분이 두 종목의 상방 라인에 집중되어 있습니다. AMZN의 긍정적인 AWS 코멘터리와 지속적인 TSLA 콜 스윕은 기관들이 섹터 전체가 아닌 두 리더 종목을 통해서만 강세 뷰를 표현하고 있음을 보여줍니다.",
         "Within a weak consumer cyclical sector, TSLA and AMZN remain relative winners on the week and attract call heavy flow, with a large share of weekly ask side activity concentrated in their upside lines. Positive AWS commentary for AMZN and persistent TSLA call sweeps suggest institutions are expressing bullish consumer views narrowly through these leaders."),

        ("커뮤니케이션 서비스: 공격적 단기 콜 매수 vs 신중한 장기 포지셔닝",
         "Bearish (4/5 Strength) · Established (최초 포착: 2026-11-11 2:25 PM)", False,
         "커뮤니케이션 섹터는 1일 및 5일 성과가 부진한 반면, 일간 옵션 프리미엄은 META와 NBIS를 중심으로 거의 전량이 단기 콜에 집중되었습니다. 주간 플로우는 다시 풋으로 기울고 다크풀 데이터는 META에서는 매집, NFLX 등에서는 매도를 보여, 여전히 신중한 기관 기조 속 투기적 상방 추격이 공존함을 나타냅니다.",
         "The sector lags on one and five day performance even as daily options premium is almost entirely in short dated calls, focused in META and NBIS. Weekly flow leans back toward puts and dark pool data show accumulation concentrated in META but distribution in names like NFLX.")
    ]

    for title, sub, is_bull, ko, en in themes:
        c_cls = "theme-card theme-card-green" if is_bull else "theme-card"
        col = "#00e676" if is_bull else "#f23645"
        st.markdown(f"""
        <div class='{c_cls}'>
            <div class='theme-title'>{title}</div>
            <div class='theme-sub' style='color:{col}; font-weight:700;'>{sub}</div>
            <div class='theme-body'><strong>[한글 심층 분석]</strong> {ko}</div>
            <div style='font-size:11px; color:#787b86; margin-top:6px; line-height:1.4;'><strong>[Original Analysis]</strong> {en}</div>
        </div>
        """, unsafe_allow_html=True)

# ================= TAB 7: TRENDING NEWS =================
if nav_menu == "📰 뉴스 (7선)":
    st.title("📰 Evening Edge 트레이딩 뉴스 전문 (7선 전체)")
    st.caption("출처: InsiderFinance Trending News (2026-11-11 발행)")

    news_list = [
        ("💸 Anthropic (ANT)", "클래스 A 주식 8억 2,500만 주를 주당 70~78달러에 공모하는 로드쇼를 시작했으며, 대규모 주문 유입 보도와 함께 Vanda는 상장 첫날 개인 투자자 매수세가 약 2억 5,000만 달러에 달할 것으로 추산했습니다.", "Had launched a roadshow proposing 825 million Class A shares at $70-$78 per share and drew reports of heavy orders and a Vanda estimate of about $250 million in potential first-day retail buying."),
        ("📉 U.S. Macro (미국 거시경제)", "예상보다 뜨거운 10월 CPI와 매파적 연준 신호 이후 AI 관련주들이 하락 압력을 받으며 AI 인프라 부채에 대한 시장의 검증이 강화되었습니다.", "Had pushed AI stocks lower following hotter October CPI and hawkish Fed signals, heightening scrutiny of AI infrastructure debt."),
        ("⚠️ Nvidia (NVDA)", "이사회가 독립적인 조사를 개시하고 베어드(Baird)가 목표주가를 기존 500달러에서 200달러로 하향 조정한 이후 주가가 하락하며 단기 밸류에이션 불확실성이 커졌습니다.", "Had fallen after the board opened an independent investigation and Baird cut its price target to $200 from $500, heightening near-term valuation uncertainty."),
        ("💸 Costco (COST)", "총 약 133억 달러 규모에 해당하는 주당 30달러의 특별 현금 배당을 선언하고 자사주 매입 프로그램을 재승인했습니다.", "Declared a $30-per-share special cash dividend totaling about $13.3 billion and reauthorized its stock-repurchase program."),
        ("☁️ Amazon (AMZN)", "AWS 순매출이 39.3% 증가한 460억 달러, 계약 수주잔고(Backlog)가 5,780억 달러를 기록했다고 발표해 현금흐름을 압박한 2026년 자본지출(2,200억 달러)에도 불구하고 강세 포지셔닝을 뒷받침했습니다.", "Had reported AWS net sales up 39.3% to $46.0 billion and a $578.0 billion contracted backlog, supporting bullish positioning despite $220.0 billion 2026 capex that pressured cash flow."),
        ("🚀 Firefly Aerospace", "3분기 매출 1억 1,070만 달러, 사상 최대 수주잔고 17억 달러, 그리고 13억 달러 이상의 AST 엔진 계약을 발표하며 연간 가이던스 상향을 뒷받침했습니다.", "Had reported Q3 revenue of $110.7M, a record $1.7B backlog and a more-than-$1.3B AST engine agreement that underpinned its raised guidance."),
        ("⚙️ Adobe (ADBE)", "Adobe MAX에서 GenStudio를 확장하고 기업용 콘텐츠 공급망 확장을 지원하는 에이전틱(Agentic) 도구를 추가한 Adobe AI 업그레이드를 발표했습니다.", "Had announced Adobe AI upgrades at Adobe MAX that expanded GenStudio and added agentic tools to scale enterprise content supply chains.")
    ]

    for title, ko, en in news_list:
        st.markdown(f"""
        <div class='news-box'>
            <div style='font-size:14px; font-weight:700; color:#ffffff; margin-bottom:4px;'>{title}</div>
            <div style='font-size:13px; color:#e0e0e0; line-height:1.6;'>{ko}</div>
            <div style='font-size:11px; color:#787b86; margin-top:4px;'>[EN] {en}</div>
        </div>
        """, unsafe_allow_html=True)

# ================= TAB: SILPI ARCHIVE =================
if nav_menu == "📚 실피 자료실":
    st.title("📚 실피 자료실 (전략 · 지표 · 매매 복기 아카이브)")
    st.caption("옵션·차트 핵심 이론, 나만의 매매 기준, 파일·메모 및 참고 링크를 서버에 영구 저장하고 검색합니다.")

    SILPI_PATH = os.path.expanduser("~/.optionhub_silpi_vault.json")
    SILPI_DIR = os.path.expanduser("~/.optionhub_silpi_files")
    os.makedirs(SILPI_DIR, exist_ok=True)
    default_silpi = [
        {
            "id": "init_1",
            "날짜": "2026-11-14",
            "카테고리": "옵션 전략",
            "종목": "공통",
            "제목": "8단계 옵션 수급 판독 순서 (GEX→DEX→OI→Vol/OI→Sweep→Premium→Delta/Gamma→DTE)",
            "내용": "1) GEX로 자석/방어선(+GEX 억제 vs -GEX 변동성 확대) 확인 → 2) DEX 방향성 → 3) OI 잔고 두께 → 4) Vol/OI > 1.0 신규 진입 여부 → 5) Sweep Ask/Bid 긴급 체결 → 6) Premium 규모($) → 7) Delta/Gamma 민감도 → 8) DTE 단기/원월 구분.",
            "링크": ""
        },
        {
            "id": "init_2",
            "날짜": "2026-11-14",
            "카테고리": "옵션 전략",
            "종목": "SOXL·SMH",
            "제목": "자석(C) · 방어(L) 레벨 & HIRO 진짜 상승 판별법",
            "내용": "• 자석(C) 레벨: 딜러 델타 헷지로 가격을 끌어당기는 대형 콜/풋 밀집 구간\n• 방어(L) 레벨: 스마트머니가 절대 내주지 않으려는 지지/저항선\n• 진짜 상승: HIRO(또는 Delta) 증가 + Gamma(GEX) 감소 동반 시 추세 지속 신호.",
            "링크": ""
        },
        {
            "id": "init_3",
            "날짜": "2026-11-14",
            "카테고리": "차트 패턴",
            "종목": "공통",
            "제목": "트레이딩뷰 복합 필터 (일목·볼린저·CVD·BII·역시계곡선)",
            "내용": "1분/5분봉에서 일목 구름대 돌파 + MA20 회복 + CVD/BII 동반 상승 + 역시계곡선 우상향 국면 진입 시 매수 우위. 1σ 상단(SIG_H) 도달 시 분할 익절 고려.",
            "링크": ""
        }
    ]
    silpi_items = load_json_file(SILPI_PATH, default_silpi)
    if st.session_state.pop("silpi_saved_ok", False):
        st.success("✅ 실피 자료실에 정상 저장되었습니다!")

    tide_live = load_json_file(os.path.expanduser("~/.optionhub_tide_brief.json"), {})
    live_upd = tide_live.get("updated_at", "11/14 기준")
    st.subheader(f"🚀 실피 브리핑 요약 대시보드 (텔레그램 자동 연동 · {live_upd})")
    st.caption("텔레그램 봇(tg_bot.py)으로 전달된 최신 시장 브리핑·Conviction·M7·DarkPool·GEX 레벨을 자동 반영합니다.")

    # 1. 시장 상태 (텔레그램 tide_brief 우선, 없으면 기본값)
    st.subheader("🌊 Market State")
    ac1, ac2, ac3, ac4 = st.columns(4)
    ac1.metric("Market Tide", str(tide_live.get("cum_net", tide_live.get("tide", "-31"))))
    ac2.metric("Trend", str(tide_live.get("trend", "Bearish↓")))
    ac3.metric("Signal Count", str(tide_live.get("signal_count", "33")))
    ac4.metric("Dealer Regime", str(tide_live.get("regime", "Short Gamma")))

    # 2. Conviction Leaders
    st.subheader("🎯 Conviction Leaders")
    bull_df = pd.DataFrame([
        ["IBIT", "Bullish", 24.5],
        ["VRT", "Bullish", 21.0],
        ["LNG", "Bullish", 18.0],
    ], columns=["Ticker", "Direction", "Conviction"])
    bear_df = pd.DataFrame([
        ["NVDA", "Bearish", 57.5],
        ["NBIS", "Bearish", 49.0],
        ["SNDK", "Bearish", 45.0],
    ], columns=["Ticker", "Direction", "Conviction"])
    acol1, acol2 = st.columns(2)
    with acol1:
        st.markdown("### 🟢 Bullish")
        st.dataframe(bull_df, use_container_width=True, hide_index=True)
    with acol2:
        st.markdown("### 🔴 Bearish")
        st.dataframe(bear_df, use_container_width=True, hide_index=True)

    # 3. M7 Focus
    st.subheader("🔥 M7 Focus")
    m7_df = pd.DataFrame({
        "Symbol": ["NVDA", "AMZN", "TSLA", "AAPL", "GOOGL", "META", "MSFT"],
        "Score": [64, 59, 59, 54, 53, 51, 47],
    })
    fig_m7 = px.bar(m7_df, x="Symbol", y="Score", text="Score", color_discrete_sequence=["#38bdf8"])
    fig_m7.update_layout(height=300, plot_bgcolor="#0e1117", paper_bgcolor="#0e1117", font_color="#d1d4dc", margin=dict(l=10, r=10, t=10, b=10))
    st.plotly_chart(fig_m7, use_container_width=True)

    # 4. DarkPool & Relative Impact
    ad1, ad2 = st.columns(2)
    with ad1:
        st.subheader("🌑 DarkPool Watchlist")
        darkpool_df = pd.DataFrame({
            "Symbol": ["MSFT", "AAPL", "AMAT", "AVGO", "MU"],
            "Premium($B)": [1.96, 1.77, 0.85, 0.50, 0.39],
        })
        st.dataframe(darkpool_df, use_container_width=True, hide_index=True)
    with ad2:
        st.subheader("⚡ Relative Impact")
        impact_df = pd.DataFrame({
            "Symbol": ["TXNM", "SLAB", "AMAT", "AMGN", "SAP"],
            "Volume Impact (%)": [206, 134, 27, 22, 21],
        })
        st.dataframe(impact_df, use_container_width=True, hide_index=True)

    # 5. Smart Money & Key GEX Levels
    as1, as2 = st.columns(2)
    with as1:
        st.subheader("💰 Smart Money")
        smart_df = pd.DataFrame({
            "Symbol": ["AMD", "CRWV", "QQQ"],
            "Signal": ["Call Buy + Put Sell", "Call Buy + Put Sell", "Call Buy + Put Sell"],
        })
        st.dataframe(smart_df, use_container_width=True, hide_index=True)
    with as2:
        st.subheader("🧲 Key GEX Levels")
        levels_df = pd.DataFrame({
            "Ticker": ["QQQ", "SPY", "SOXX"],
            "Resistance": ["700", "770", "155"],
            "Current": ["679.9", "754.2", "149.3"],
            "Risk": ["680", "750", "149.17"],
        })
        st.dataframe(levels_df, use_container_width=True, hide_index=True)

    st.divider()
    SILPI_SYMBOLS = [
        "SPY","QQQ","SOXX","SOXL","SOXS","SMH",
        "NVDA","TSLA","AAPL","MSFT","AMZN","META",
        "GOOGL","AMD","MU","AVGO","AMAT","LRCX",
        "KLAC","IBIT","NBIS","SNDK","VRT","LNG",
        "BRKB","INTC"
    ]
    def extract_silpi_symbols(text):
        found = []
        upper_text = str(text or "").upper()
        for sym in SILPI_SYMBOLS:
            if re.search(rf"\b{sym}\b", upper_text):
                found.append(sym)
        return sorted(list(set(found)))

    st.subheader("📚 Latest Telegram Reports (자동 수신 원문 & 종목 태그)")
    tg_notes = []
    for k_lbl, k_name in [("M7 관심도", "m7_note"), ("반도체 4종", "semi_note"), ("다크풀", "darkpool_note"), ("핵심 레벨", "levels_note"), ("아침 브리핑", "morning_note")]:
        if tide_live.get(k_name):
            tg_notes.append(f"• [{k_lbl}] {tide_live[k_name]}")
    all_tg_txt = "\n".join(tg_notes) if tg_notes else "11/14 시장 브리핑 · Conviction Score · M7 관심도 · DarkPool Digest · Morning Briefing (NVDA, QQQ, SPY, SOXX, MSFT, AAPL, AMAT, MU, AMD, IBIT, VRT, LNG, SNDK, NBIS)"
    detected_syms = extract_silpi_symbols(all_tg_txt)
    if detected_syms:
        st.markdown("**🏷️ 브리핑 내 자동 추출 종목 태그:** " + " ".join([f"`{sym}`" for sym in detected_syms]))
    st.info(all_tg_txt if tg_notes else "11/14 시장 브리핑 · Conviction Score · M7 관심도 · DarkPool Digest · Morning Briefing (텔레그램 봇에 새 브리핑 전달 시 자동 갱신됩니다)")

    TG_ARCHIVE_PATH = os.path.expanduser("~/.optionhub_tg_archive.json")
    tg_arch_list = load_json_file(TG_ARCHIVE_PATH, [])
    if not tg_arch_list and tg_notes:
        tg_arch_list = [{"date": live_upd, "title": "최신 텔레그램 브리핑", "symbols": ", ".join(detected_syms), "content": all_tg_txt}]
    st.markdown("#### 🔍 텔레그램 아카이브 종목 검색")
    search_sym_tg = st.text_input("Ticker 입력", placeholder="예: NVDA, SOXL, QQQ", key="tg_arch_sym").strip().upper()
    if tg_arch_list:
        df_tg_arch = pd.DataFrame(tg_arch_list)
        if "symbols" not in df_tg_arch.columns:
            df_tg_arch["symbols"] = df_tg_arch.apply(lambda r: ", ".join(extract_silpi_symbols(str(r.get("title","")) + " " + str(r.get("content","")))), axis=1)
        if search_sym_tg:
            df_tg_filt = df_tg_arch[df_tg_arch["symbols"].astype(str).str.contains(search_sym_tg, na=False)]
        else:
            df_tg_filt = df_tg_arch
        st.dataframe(df_tg_filt, use_container_width=True, hide_index=True)
    else:
        st.caption("텔레그램 봇에 브리핑이 전달되면 종목 태그(symbols)와 함께 자동 누적·검색됩니다.")

    # 3) 종목 태그 -> 실시간 GEX · 무무 현재가 미리보기
    st.markdown("#### ⚡ 종목 즉시 미리보기 (무무 현재가 · Call/Put Wall · Zero Gamma)")
    pv_list = sorted(list(set(detected_syms + ["SOXL", "NVDA", "QQQ", "SPY", "SNDK", "MU", "AMD", "TSLA"])))
    pv_tk = st.selectbox("미리보기 종목 선택", pv_list, index=0, key="sp_pv_tk")
    pv_px_txt, pv_cw, pv_pw, pv_zg = "-", "-", "-", "-"
    try:
        db_p_sp = os.environ.get("MOOMOO_DB", os.path.expanduser("~/moomoo-hub/moomoo.db"))
        if os.path.exists(db_p_sp):
            con_sp = sqlite3.connect(f"file:{db_p_sp}?mode=ro", uri=True, timeout=3)
            r_sp = con_sp.execute("SELECT data FROM quotes WHERE sym=?", (f"US.{pv_tk}",)).fetchone()
            con_sp.close()
            if r_sp and r_sp[0]:
                d_sp = json.loads(r_sp[0])
                px_sp = d_sp.get("last_price") or d_sp.get("px")
                if px_sp:
                    pv_px_txt = f"${float(px_sp):,.2f}"
    except Exception:
        pass
    try:
        oi_sp = load_json_file(OI_PATH, {})
        if pv_tk in oi_sp and oi_sp[pv_tk]:
            det_sp = oi_sp[pv_tk][-1].get("상세", [])
            cs_sp = [x for x in det_sp if x.get("구분") == "Call"]
            ps_sp = [x for x in det_sp if x.get("구분") == "Put"]
            if cs_sp: pv_cw = f"${max(cs_sp, key=lambda x: x.get('OI', 0)).get('행사가'):g}"
            if ps_sp: pv_pw = f"${max(ps_sp, key=lambda x: x.get('OI', 0)).get('행사가'):g}"
            zg_sp = calc_zero_gamma(det_sp, float(oi_sp[pv_tk][-1].get("Spot", 0) or 0))
            if zg_sp: pv_zg = f"${zg_sp:g}"
    except Exception:
        pass
    pm1, pm2, pm3, pm4 = st.columns(4)
    pm1.metric(f"{pv_tk} 무무 현재가", pv_px_txt)
    pm2.metric("Call Wall", pv_cw)
    pm3.metric("Put Wall", pv_pw)
    pm4.metric("Zero Gamma", pv_zg)

    # 2) 텔레그램 전달 이미지 & 차트 갤러리
    tg_p_dir = os.path.expanduser("~/.optionhub_tg_photos")
    tg_imgs = [os.path.join(tg_p_dir, x) for x in sorted(os.listdir(tg_p_dir), reverse=True) if x.endswith(".jpg")][:6] if os.path.isdir(tg_p_dir) else []
    with st.expander(f"🖼️ 텔레그램 전달 차트 · 표 갤러리 ({len(tg_imgs)}장)", expanded=False):
        if tg_imgs:
            g_cols = st.columns(3)
            for gi, gp in enumerate(tg_imgs):
                with g_cols[gi % 3]:
                    st.image(gp, caption=os.path.basename(gp), use_container_width=True)
        else:
            st.caption("텔레그램 봇에 차트나 표 이미지를 전달하면 여기에 자동으로 모입니다.")

    st.divider()

    # 1) 매매 복기 · 승률 자동 계산기 요약 바
    tr_entries = [x for x in silpi_items if x.get("매매결과") in ("익절", "손절", "본전")]
    if tr_entries:
        wins_cnt = sum(1 for x in tr_entries if x.get("매매결과") == "익절")
        win_rate = wins_cnt / len(tr_entries) * 100.0
        pnl_vals = [float(x.get("손익률", 0) or 0) for x in tr_entries if x.get("손익률") is not None]
        avg_pnl = (sum(pnl_vals) / len(pnl_vals)) if pnl_vals else 0.0
        tm1, tm2, tm3 = st.columns(3)
        tm1.metric("📊 누적 복기 매매", f"{len(tr_entries)}건")
        tm2.metric("🏆 승률", f"{win_rate:.1f}% ({wins_cnt}승 {len(tr_entries)-wins_cnt}패)")
        tm3.metric("💹 평균 손익률", f"{avg_pnl:+.2f}%")

    with st.expander("➕ 새 자료 / 메모 / 매매 복기 / 파일 추가하기", expanded=True):
        with st.form("silpi_add_form", clear_on_submit=True):
            fc1, fc2, fc3 = st.columns([1.2, 1.0, 2.0])
            s_cat = fc1.selectbox("카테고리", ["옵션 전략", "차트 패턴", "매매 복기", "자금 관리", "참고 링크/PDF"])
            s_tk = fc2.text_input("관련 종목", "공통", placeholder="예: SOXL, NVDA, 공통").strip().upper() or "공통"
            s_title = fc3.text_input("제목 (비워두면 내용 첫 줄 자동 입력)", placeholder="예: 11/14 SOXL 58C/60C 매집 복기")
            s_body = st.text_area("상세 내용 / 메모", height=110, placeholder="핵심 수치, 진입/손절 기준, 복기 내용을 입력하세요.")
            tr1, tr2, tr3, tr4 = st.columns(4)
            s_res = tr1.selectbox("매매결과 (복기용)", ["참고용", "익절", "손절", "본전"])
            s_pos = tr2.selectbox("포지션", ["-", "Call", "Put", "주식/ETF"])
            s_entry = tr3.number_input("진입가($)", 0.0, 100000.0, 0.0, step=0.1)
            s_exit = tr4.number_input("청산가($)", 0.0, 100000.0, 0.0, step=0.1)
            fc4, fc5 = st.columns([1.5, 1.5])
            s_link = fc4.text_input("참고 URL (선택)", placeholder="https://...")
            s_file = fc5.file_uploader("파일 첨부 (PDF·이미지·TXT·CSV 등)", type=None)
            submitted_s = st.form_submit_button("💾 자료실에 저장", type="primary")
            if submitted_s:
                saved_file_path = ""
                saved_file_name = ""
                if s_file is not None:
                    safe_name = f"{int(time.time())}_{os.path.basename(s_file.name)}"
                    saved_file_path = os.path.join(SILPI_DIR, safe_name)
                    with open(saved_file_path, "wb") as fw:
                        fw.write(s_file.getbuffer())
                    saved_file_name = s_file.name
                auto_title = s_title.strip() or (s_body.strip().splitlines()[0][:50] if s_body.strip() else "") or saved_file_name or s_link.strip()
                if auto_title:
                    new_entry = {
                        "id": f"sp_{int(time.time()*1000)}",
                        "날짜": pd.Timestamp.now(tz="Asia/Seoul").strftime("%Y-%m-%d %H:%M"),
                        "카테고리": s_cat,
                        "종목": (", ".join(extract_silpi_symbols(auto_title + " " + s_body)) or "공통") if s_tk == "공통" else s_tk,
                        "제목": auto_title,
                        "내용": s_body.strip(),
                        "링크": s_link.strip(),
                        "파일경로": saved_file_path,
                        "파일명": saved_file_name,
                        "매매결과": s_res,
                        "포지션": s_pos,
                        "진입가": s_entry,
                        "청산가": s_exit,
                        "손익률": round(((s_exit - s_entry) / s_entry * 100.0), 2) if (s_entry > 0 and s_exit > 0) else None,
                    }
                    silpi_items.insert(0, new_entry)
                    save_json_file(SILPI_PATH, silpi_items)
                    st.session_state["silpi_saved_ok"] = True
                    st.rerun()
                else:
                    st.warning("제목, 내용, 파일, 또는 링크 중 하나는 입력해 주세요.")

    sc1, sc2, sc3 = st.columns([1.2, 1.2, 2.0])
    cats_all = ["전체"] + sorted(list({x.get("카테고리", "기타") for x in silpi_items}))
    tks_all = ["전체"] + sorted(list({x.get("종목", "공통") for x in silpi_items}))
    f_cat = sc1.selectbox("카테고리 필터", cats_all, key="sp_f_cat")
    f_tk = sc2.selectbox("종목 필터", tks_all, key="sp_f_tk")
    f_kw = sc3.text_input("🔍 키워드 검색", "", placeholder="제목 또는 내용 검색...", key="sp_f_kw").strip().lower()

    filtered_sp = []
    for x in silpi_items:
        if f_cat != "전체" and x.get("카테고리") != f_cat:
            continue
        if f_tk != "전체" and x.get("종목") != f_tk:
            continue
        if f_kw and f_kw not in (x.get("제목", "") + " " + x.get("내용", "") + " " + x.get("종목", "")).lower():
            continue
        filtered_sp.append(x)

    cap_l, cap_m, cap_r = st.columns([2.2, 1.0, 1.0])
    cap_l.caption(f"총 {len(filtered_sp)}건의 자료가 표시되고 있습니다.")
    sp_expand_all = cap_m.toggle("📂 전체 펼치기", value=False, key="sp_exp_all")
    if silpi_items:
        csv_sp = pd.DataFrame(silpi_items).to_csv(index=False).encode("utf-8-sig")
        cap_r.download_button("📥 전체 CSV 백업", csv_sp, file_name="silpi_archive_backup.csv", mime="text/csv", use_container_width=True)
    edit_id_cur = st.session_state.get("sp_edit_id")
    for idx_sp, item_sp in enumerate(filtered_sp):
        it_id = item_sp.get("id", f"idx_{idx_sp}")
        tr_badge = ""
        if item_sp.get("매매결과") in ("익절", "손절", "본전"):
            pnl_s = f" {item_sp['손익률']:+.2f}%" if item_sp.get("손익률") is not None else ""
            tr_badge = f" | {item_sp.get('포지션','-')} {item_sp['매매결과']}{pnl_s}"
        exp_lbl = f"[{item_sp.get('카테고리','')}] {item_sp.get('제목','')}  ({item_sp.get('종목','')}{tr_badge} · {item_sp.get('날짜','')})"
        with st.expander(exp_lbl, expanded=(sp_expand_all or edit_id_cur == it_id)):
            b1, b2, b3, b_sp = st.columns([1.0, 0.9, 0.9, 2.2])
            if b1.button("📩 텔레그램", key=f"tg_sp_{it_id}"):
                if tg_token and tg_chat_id:
                    tg_txt_sp = f"📚 [실피 자료실] {item_sp.get('제목','')}\n종목: {item_sp.get('종목','')}\n\n{item_sp.get('내용','')}"
                    ok_s, err_s = send_telegram_msg(tg_token, tg_chat_id, tg_txt_sp)
                    if ok_s: st.success("전송 완료!")
                    else: st.error(err_s)
                else:
                    st.warning("텔레그램 설정 필요")
            if b2.button("✏️ 수정", key=f"ed_sp_{it_id}"):
                st.session_state["sp_edit_id"] = None if edit_id_cur == it_id else it_id
                st.rerun()
            if b3.button("🗑️ 삭제", key=f"del_sp_{it_id}"):
                silpi_items = [z for z in silpi_items if z.get("id") != item_sp.get("id")]
                save_json_file(SILPI_PATH, silpi_items)
                if edit_id_cur == it_id:
                    st.session_state["sp_edit_id"] = None
                st.rerun()
            if edit_id_cur == it_id:
                with st.form(f"sp_edit_form_{it_id}"):
                    ec1, ec2, ec3 = st.columns([1.2, 1.0, 2.0])
                    cat_opts = ["옵션 전략", "차트 패턴", "매매 복기", "자금 관리", "참고 링크/PDF"]
                    cur_c_i = cat_opts.index(item_sp.get("카테고리")) if item_sp.get("카테고리") in cat_opts else 0
                    e_cat = ec1.selectbox("카테고리", cat_opts, index=cur_c_i)
                    e_tk = ec2.text_input("종목", value=str(item_sp.get("종목", "공통"))).strip().upper() or "공통"
                    e_title = ec3.text_input("제목", value=str(item_sp.get("제목", "")))
                    e_body = st.text_area("상세 내용", value=str(item_sp.get("내용", "")), height=140)
                    e_link = st.text_input("참고 URL", value=str(item_sp.get("링크", "")))
                    sv_c1, sv_c2 = st.columns(2)
                    if sv_c1.form_submit_button("💾 수정 저장", type="primary", use_container_width=True):
                        for z in silpi_items:
                            if z.get("id") == it_id:
                                z["카테고리"] = e_cat
                                z["종목"] = e_tk
                                z["제목"] = e_title.strip() or z["제목"]
                                z["내용"] = e_body.strip()
                                z["링크"] = e_link.strip()
                        save_json_file(SILPI_PATH, silpi_items)
                        st.session_state["sp_edit_id"] = None
                        st.session_state["silpi_saved_ok"] = True
                        st.rerun()
                    if sv_c2.form_submit_button("취소", use_container_width=True):
                        st.session_state["sp_edit_id"] = None
                        st.rerun()
            else:
                if item_sp.get("내용"):
                    st.markdown(item_sp["내용"].replace("\n", "  \n"))
                if item_sp.get("링크"):
                    st.markdown(f"🔗 참고 링크: [{item_sp['링크']}]({item_sp['링크']})")
                fp_sp = item_sp.get("파일경로", "")
                if fp_sp and os.path.exists(fp_sp):
                    with open(fp_sp, "rb") as fr:
                        st.download_button(f"📥 {item_sp.get('파일명', '첨부파일')}", fr.read(), file_name=item_sp.get("파일명", "file"), key=f"dl_sp_{it_id}")


# ================= TAB: OPTIONS ARCHIVE =================
GEMINI_KEY_PATH = os.path.expanduser("~/.optionhub_gemini_key")
BIG_FLOWS_PATH = os.path.expanduser("~/.optionhub_big_flows.json")

def calc_max_pain(df_chain):
    """옵션 매수자 전체 내재가치 합이 최소(딜러 이익 최대)가 되는 Max Pain 행사가 계산"""
    if df_chain is None or df_chain.empty or "행사가" not in df_chain.columns:
        return None
    strikes = sorted(df_chain["행사가"].dropna().unique().tolist())
    if not strikes:
        return None
    calls = df_chain[df_chain["구분"] == "Call"]
    puts = df_chain[df_chain["구분"] == "Put"]
    best_k = None
    min_val = None
    for s_px in strikes:
        c_val = ((s_px - calls["행사가"]).clip(lower=0) * calls["OI"]).sum() if not calls.empty else 0.0
        p_val = ((puts["행사가"] - s_px).clip(lower=0) * puts["OI"]).sum() if not puts.empty else 0.0
        tot = float(c_val + p_val)
        if min_val is None or tot < min_val:
            min_val = tot
            best_k = float(s_px)
    return best_k

def get_gemini_api_key():
    env_k = os.environ.get("GEMINI_API_KEY", "").strip()
    if env_k:
        return env_k
    if os.path.exists(GEMINI_KEY_PATH):
        try:
            return open(GEMINI_KEY_PATH, "r", encoding="utf-8").read().strip()
        except Exception:
            pass
    return ""

def run_ai_analysis(prompt_text, img_b64=None, img_path=None):
    """Gemini 무료 API 우선 호출 (이미지 Vision 지원) -> 키 없거나 실패 시 로컬 Ollama(qwen2.5:7b) 무료 폴백"""
    import urllib.request
    import base64 as _b64_ai
    g_key = get_gemini_api_key()
    if g_key:
        try:
            parts = [{"text": prompt_text}]
            raw_b64 = None
            mime_t = "image/jpeg"
            if img_b64 and "," in img_b64:
                hdr, raw_b64 = img_b64.split(",", 1)
                if "png" in hdr:
                    mime_t = "image/png"
            elif img_path and os.path.exists(img_path):
                ext = os.path.splitext(img_path)[1].lower()
                mime_t = "image/png" if ext == ".png" else "image/jpeg"
                with open(img_path, "rb") as fi:
                    raw_b64 = _b64_ai.b64encode(fi.read()).decode("utf-8")
            if raw_b64:
                parts.append({"inline_data": {"mime_type": mime_t, "data": raw_b64}})
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent?key={g_key}"
            body = json.dumps({"contents": [{"parts": parts}]}).encode("utf-8")
            req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=25) as resp:
                res = json.loads(resp.read().decode("utf-8"))
            cand = res.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
            if cand:
                return True, f"✨ [Gemini AI 분석]\n{cand.strip()}"
        except Exception as e_g:
            pass

    # 로컬 Ollama (qwen2.5:7b) 폴백 ($0)
    try:
        url_o = "http://127.0.0.1:11434/api/generate"
        body_o = json.dumps({"model": "qwen2.5:7b", "prompt": prompt_text, "stream": False}).encode("utf-8")
        req_o = urllib.request.Request(url_o, data=body_o, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req_o, timeout=45) as resp_o:
            res_o = json.loads(resp_o.read().decode("utf-8"))
        ans_o = res_o.get("response", "").strip()
        if ans_o:
            return True, f"🤖 [로컬 Qwen AI 분석]\n{ans_o}"
    except Exception:
        pass
    return False, "⚠️ Gemini API 키가 설정되지 않았거나 로컬 Ollama가 꺼져 있습니다. 사이드바 또는 입력창에서 Gemini 무료 API 키를 저장해 주세요."

def parse_tg_big_flows(raw_text):
    """🚨 큰 옵션 체결 메시지 파싱 (🟢/🔴/🟡, 티커, 행사가, 콜/풋, 만기, BUY/SELL, 프리미엄, 계약수, 태그, 코멘트)"""
    records = []
    flip_val = None
    pat = re.compile(
        r"([🟢🔴🟡⚪])\s*([A-Z]{1,6})\s+(\d+(?:\.\d+)?)([CP])\s+(\d{2}-\d{2}(?:-\d{2})?)\s+(BUY|SELL|MID|-)\s+\$([\d\.]+)([MK])\s*[·\-]\s*([\d,]+)계약\s*[·\-]\s*(.+)"
    )
    flip_pat = re.compile(r"플립\(([\d\.]+)\)")
    for line in (raw_text or "").splitlines():
        s = line.strip()
        if not s:
            continue
        fm = flip_pat.search(s)
        if fm:
            try:
                flip_val = float(fm.group(1))
            except Exception:
                pass
        m = pat.search(s)
        if m:
            emo, tk, k_s, cp_s, exp_s, side_s, pr_num, pr_unit, qty_s, tag_s = m.groups()
            prem_m = float(pr_num) if pr_unit == "M" else round(float(pr_num) / 1000.0, 3)
            records.append({
                "emoji": emo,
                "tk": tk.upper(),
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
        elif records and (s.startswith("📍") or s.startswith("🛡")):
            records[-1]["notes"].append(s)
    return records, flip_val




if nav_menu == "🎯 AI GEX 분석":
    try:
        from gex_dashboard import render_ai_gex_dashboard
        render_ai_gex_dashboard(
            run_ai_fn=run_ai_analysis,
            send_tg_fn=send_telegram_msg,
            tg_token=tg_token,
            tg_chat_id=tg_chat_id,
        )
    except Exception as _gex_err:
        st.error(f"🎯 AI GEX 분석 모듈 로드 오류: {_gex_err}")

if nav_menu == "📰 대형 옵션 체결":
    st.title("📰 대형 옵션 체결 · 신규/증가")
    st.caption("텔레그램 큰 옵션 체결 + 구글 시트 대형 스윕($500K+)을 한눈에 표로 정리하고, 방향성·지지/저항·AI 해석을 생성해 텔레그램·캘린더로 바로 보냅니다.")

    _big_seed_flag = os.path.expanduser("~/.optionhub_big_seed_pltr_v1")
    saved_big_flows = load_json_file(BIG_FLOWS_PATH, [])
    if not os.path.exists(_big_seed_flag):
        _pltr_seed_raw = """🚨 큰 옵션 체결 12건
🔴 PLTR 175C 11-20 SELL $2.46M · 10040계약 · CALL OVERWRITE/SALE
🔴 PLTR 162.5P 11-20 BUY $672.0K · 2358계약 · SPECULATIVE LONG
   📍 플립(162.3) 아래 이탈 베팅
🔴 PLTR 160P 11-20 BUY $869.3K · 4062계약 · SPECULATIVE LONG
   📍 플립(162.3) 아래 이탈 베팅
🔴 PLTR 170C 11-20 SELL $4.41M · 10139계약 · PREMIUM SALE
🟢 PLTR 177.5C 11-20 BUY $1.57M · 8819계약 · SPECULATIVE LONG
🔴 PLTR 165P 11-20 BUY $742.1K · 1979계약 · SPECULATIVE LONG
⚪ PLTR 172.5C 11-20 MID $2.81M · 8377계약 · UNCLEAR FLOW
🟢 PLTR 155P 12-18 SELL $870.6K · 1795계약 · PREMIUM SALE
🟢 PLTR 167.5C 11-20 BUY $567.8K · 1005계약 · DIRECTIONAL FLOW
⚪ PLTR 180C 11-20 MID $1.19M · 9422계약 · UNCLEAR FLOW
🔴 PLTR 165C 11-20 SELL $2.96M · 4187계약 · PREMIUM SALE
🟢 PLTR 167.5P 11-20 SELL $508.8K · 1069계약 · PREMIUM SALE"""
        _p_recs, _p_flip = parse_tg_big_flows(_pltr_seed_raw)
        if _p_recs:
            _has_pltr = any(b.get("tk") == "PLTR" and len(b.get("records", [])) >= 10 for b in saved_big_flows)
            if not _has_pltr:
                saved_big_flows.insert(0, {
                    "tk": "PLTR",
                    "ts": "2026-11-16 01:30",
                    "flip": _p_flip,
                    "raw": _pltr_seed_raw,
                    "records": _p_recs,
                })
                save_json_file(BIG_FLOWS_PATH, saved_big_flows[:50])
        try:
            with open(_big_seed_flag, "w", encoding="utf-8") as _bf:
                _bf.write("1")
        except Exception:
            pass

    with st.expander("📋 텔레그램 '🚨 큰 옵션 체결' 붙여넣기 · 자동 파싱 저장", expanded=False):
        _big_paste = st.text_area(
            "큰 옵션 체결 메시지 붙여넣기",
            height=150,
            placeholder="🚨 큰 옵션 체결 12건\n🔴 PLTR 175C 11-20 SELL $2.46M · 10040계약 · CALL OVERWRITE/SALE ...",
            key="big_page_paste",
        )
        if st.button("⚡ 파싱 및 대형 옵션 체결 표에 추가", type="primary", key="btn_big_page_parse"):
            _recs, _flp = parse_tg_big_flows(_big_paste)
            if _recs:
                _by_tk = {}
                for _rr in _recs:
                    _by_tk.setdefault(_rr["tk"], []).append(_rr)
                _now_s = pd.Timestamp.now(tz="Asia/Seoul").strftime("%Y-%m-%d %H:%M")
                for _btk, _brecs in _by_tk.items():
                    saved_big_flows.insert(0, {
                        "tk": _btk,
                        "ts": _now_s,
                        "flip": _flp,
                        "raw": _big_paste,
                        "records": _brecs,
                    })
                save_json_file(BIG_FLOWS_PATH, saved_big_flows[:50])
                st.success(f"✅ {len(_recs)}건 파싱 완료! ({', '.join(_by_tk.keys())})")
                st.rerun()
            else:
                st.warning("인식된 옵션 체결 행이 없습니다. 형식을 확인해 주세요.")

    # 통합 레코드 구성 (저장된 큰 옵션 체결 + 구글 시트 대형 스윕)
    _merged_rows = []
    _seen_keys = set()
    for _blk in saved_big_flows:
        _flp_v = _blk.get("flip")
        _ts_v = _blk.get("ts", "")
        for _r in _blk.get("records", []):
            _rk = f"{_r.get('tk')}|{_r.get('strike')}|{_r.get('cp')}|{_r.get('exp')}|{_r.get('side')}|{_r.get('prem_str')}"
            if _rk in _seen_keys:
                continue
            _seen_keys.add(_rk)
            _em = _r.get("emoji", "⚪")
            _cp = _r.get("cp", "Call")
            _sd = _r.get("side", "MID")
            _tag = _r.get("tag", "")
            _notes = " · ".join(_r.get("notes") or [])
            # 자동 한국어 해석 생성
            if _notes:
                _interp = _notes
            elif _cp == "Call" and _sd == "SELL":
                _interp = f"콜 매도 저항 (상방 캡) · {_tag}"
            elif _cp == "Call" and _sd == "BUY":
                _interp = f"콜 매수 강세 베팅 · {_tag}"
            elif _cp == "Put" and _sd == "BUY":
                _interp = (f"플립({_flp_v}) 하방 이탈 베팅 · " if _flp_v else "하락 방어·풋 매수 · ") + _tag
            elif _cp == "Put" and _sd == "SELL":
                _interp = f"풋 매도 하단 지지 방어 · {_tag}"
            else:
                _interp = f"방향 중립/혼조 (MID) · OI 변화 확인 필요"
            _sent = "강세" if _em == "🟢" else ("약세" if _em == "🔴" else "중립")
            _merged_rows.append({
                "tk": _r.get("tk", ""),
                "exp": _r.get("exp", ""),
                "status": "신규",
                "strike": _r.get("strike", 0),
                "cp": _cp,
                "side": _sd,
                "qty": int(_r.get("qty", 0)),
                "prem_m": float(_r.get("prem_m", 0.0)),
                "prem_str": _r.get("prem_str", ""),
                "emoji": _em,
                "sent": _sent,
                "interp": _interp,
                "flip": _flp_v,
                "ts": _ts_v,
            })

    # 구글 시트 대형 스윕($0.5M 이상) 병합
    for _sr in (all_raw_flows or []):
        try:
            _pm_s = str(_sr[14] if len(_sr) > 14 else "").replace("$", "").replace(",", "").strip().upper()
            _pm_v = float(_pm_s[:-1]) if _pm_s.endswith("M") else (float(_pm_s[:-1]) / 1000.0 if _pm_s.endswith("K") else 0.0)
        except Exception:
            _pm_v = 0.0
        if _pm_v < 0.5:
            continue
        _stk = str(_sr[1]).upper()
        _scp = "Call" if "C" in str(_sr[3]).upper() else "Put"
        _ssd = "BUY" if "A" in str(_sr[4]) else ("SELL" if "B" in str(_sr[4]) else "MID")
        _sexp = str(_sr[5])
        try:
            _sk = float(str(_sr[7]).replace("$", "").replace(",", "").strip())
        except Exception:
            _sk = 0.0
        try:
            _sqty = int(float(_sr[15])) if len(_sr) > 15 and str(_sr[15]).replace(".", "", 1).isdigit() else 0
        except Exception:
            _sqty = 0
        _rk = f"{_stk}|{_sk}|{_scp}|{_sexp}|{_ssd}|{_pm_s}"
        if _rk in _seen_keys:
            continue
        _seen_keys.add(_rk)
        _is_bull = (_scp == "Call" and _ssd == "BUY") or (_scp == "Put" and _ssd == "SELL")
        _is_bear = (_scp == "Call" and _ssd == "SELL") or (_scp == "Put" and _ssd == "BUY")
        _sem = "🟢" if _is_bull else ("🔴" if _is_bear else "⚪")
        _ssent = "강세" if _is_bull else ("약세" if _is_bear else "중립")
        _stag = str(_sr[13]) if len(_sr) > 13 else "시트 대형 스윕"
        _sinterp = ("콜 매수 상방 베팅" if (_scp == "Call" and _ssd == "BUY") else
                    "콜 매도 상방 저항" if (_scp == "Call" and _ssd == "SELL") else
                    "풋 매도 하단 지지" if (_scp == "Put" and _ssd == "SELL") else
                    "풋 매수 하락 베팅" if (_scp == "Put" and _ssd == "BUY") else "중립 스윕") + f" · {_stag}"
        _merged_rows.append({
            "tk": _stk,
            "exp": _sexp,
            "status": "증가",
            "strike": _sk,
            "cp": _scp,
            "side": _ssd,
            "qty": _sqty,
            "prem_m": round(_pm_v, 3),
            "prem_str": f"${_pm_v:.2f}M",
            "emoji": _sem,
            "sent": _ssent,
            "interp": _sinterp,
            "flip": None,
            "ts": str(_sr[0]),
        })

    _all_big_tks = sorted({r["tk"] for r in _merged_rows if r["tk"]})
    _fc1, _fc2, _fc3 = st.columns([1.4, 1.4, 1.4])
    _sel_big_tk = _fc1.selectbox("종목 필터", ["전체"] + _all_big_tks, index=(1 if "PLTR" in _all_big_tks and _all_big_tks[0] == "PLTR" else 0), key="big_tk_sel")
    _sel_big_dir = _fc2.selectbox("방향 필터", ["전체", "🟢 강세", "🔴 약세", "⚪ 중립(MID)"], key="big_dir_sel")
    _min_prem_m = _fc3.slider("최소 프리미엄 ($M)", 0.0, 10.0, 0.5, 0.1, key="big_min_prem")

    _f_rows = [
        r for r in _merged_rows
        if (_sel_big_tk == "전체" or r["tk"] == _sel_big_tk)
        and (_sel_big_dir == "전체" or (_sel_big_dir.startswith("🟢") and r["sent"] == "강세") or (_sel_big_dir.startswith("🔴") and r["sent"] == "약세") or (_sel_big_dir.startswith("⚪") and r["sent"] == "중립"))
        and r["prem_m"] >= _min_prem_m
    ]
    _f_rows.sort(key=lambda x: x["prem_m"], reverse=True)

    _bull_sum = sum(r["prem_m"] for r in _f_rows if r["sent"] == "강세")
    _bear_sum = sum(r["prem_m"] for r in _f_rows if r["sent"] == "약세")
    _mid_sum = sum(r["prem_m"] for r in _f_rows if r["sent"] == "중립")
    _overall_lbl = "강세 우위" if _bull_sum > _bear_sum * 1.25 else ("약세·상방 캡 우위" if _bear_sum > _bull_sum * 1.25 else "한쪽으로 쏠리지 않음 (양방향)")

    # 종목별 요약 계산
    _tk_summary_lines = []
    _by_tk_grp = {}
    for _r in _f_rows:
        _by_tk_grp.setdefault(_r["tk"], []).append(_r)
    for _gtk, _glist in sorted(_by_tk_grp.items(), key=lambda kv: sum(x["prem_m"] for x in kv[1]), reverse=True)[:6]:
        _gbull = sum(x["prem_m"] for x in _glist if x["sent"] == "강세")
        _gbear = sum(x["prem_m"] for x in _glist if x["sent"] == "약세")
        _gdir = "강세 우위" if _gbull > _gbear * 1.25 else ("약세 우위" if _gbear > _gbull * 1.25 else "양방향")
        _put_ks = sorted({x["strike"] for x in _glist if x["cp"] == "Put" and x["strike"] > 0})
        _call_ks = sorted({x["strike"] for x in _glist if x["cp"] == "Call" and x["strike"] > 0})
        _sup_s = f"{_put_ks[0]:g}" if _put_ks else "-"
        _res_s = f"{_call_ks[0]:g}·{_call_ks[-1]:g}" if len(_call_ks) >= 2 else (f"{_call_ks[0]:g}" if _call_ks else "-")
        _flp_g = next((x["flip"] for x in _glist if x.get("flip")), None)
        _flp_txt = f" · 플립 {_flp_g}" if _flp_g else ""
        _tk_summary_lines.append(f"• **{_gtk} {_gdir}** (강세 ${_gbull:.2f}M · 약세 ${_gbear:.2f}M) → 지지 ${_sup_s} / 저항 ${_res_s}{_flp_txt}")

    # 상단 액션 버튼
    _ab1, _ab2, _ab3 = st.columns(3)
    if _ab1.button("🤖 Gemini AI 상세 해석", use_container_width=True, key="btn_big_ai"):
        with st.spinner("Gemini가 대형 옵션 체결 수급을 분석 중입니다..."):
            _sample_lines = "\n".join(
                f"{r['emoji']} {r['tk']} {r['strike']:g}{r['cp'][0]} {r['exp']} {r['side']} {r['prem_str']} ({r['qty']:,}계약) - {r['interp']}"
                for r in _f_rows[:25]
            )
            _ai_pr = f"다음 미국 주식 대형 옵션 체결 목록을 한국어 트레이더 관점에서 요약(강세/약세 우위, 주요 지지·저항 행사가, 감마 플립, 매매 전략)해 주세요:\n\n{_sample_lines}"
            _, _ai_res = run_ai_analysis(_ai_pr)
            st.session_state["big_ai_summary_txt"] = _ai_res
    if _ab2.button("📩 텔레그램 전송", use_container_width=True, key="btn_big_tg"):
        _tg_hdr = f"📰 *대형 옵션 체결 · {_sel_big_tk} ({len(_f_rows)}건)*\n"
        _tg_top = "\n".join(f"• {r['emoji']} {r['tk']} {r['strike']:g}{r['cp'][0]} {r['exp']} {r['prem_str']} {r['side']}" for r in _f_rows[:12])
        _tg_bot = f"\n\n전체: 강세 ${_bull_sum:.2f}M vs 약세 ${_bear_sum:.2f}M → {_overall_lbl}\n" + "\n".join(_tk_summary_lines).replace("**", "*")
        if send_telegram_msg(tg_token, tg_chat_id, _tg_hdr + _tg_top + _tg_bot)[0]:
            st.toast("✅ 텔레그램 전송 완료!")
        else:
            st.toast("⚠️ 텔레그램 설정을 확인해 주세요.")
    if _ab3.button("📅 캘린더 등록 (해석 포함)", use_container_width=True, key="btn_big_cal"):
        import hashlib as _hs_b
        _gcal_p = os.path.expanduser("~/.optionhub_gcal_events.json")
        _gcal_list = load_json_file(_gcal_p, [])
        _gcal_idx = {e.get("id"): i for i, e in enumerate(_gcal_list) if e.get("id")}
        _cal_cnt = 0
        for _r in _f_rows[:20]:
            _exp_raw = str(_r["exp"])
            _exp_iso = f"2026-{_exp_raw}" if re.match(r"^\d{2}-\d{2}$", _exp_raw) else (_exp_raw[:10] if re.match(r"^202\d-\d{2}-\d{2}", _exp_raw) else "2026-11-20")
            _cid = "big_" + _hs_b.md5(f"{_r['tk']}|{_r['strike']}|{_r['cp']}|{_exp_iso}|{_r['side']}".encode()).hexdigest()[:12]
            _c_ev = {
                "id": _cid,
                "date": _exp_iso,
                "summary": f"[대형 체결] {_r['emoji']} {_r['tk']} {_r['strike']:g}{_r['cp'][0]} {_r['side']} ({_r['prem_str']})",
                "description": f"📌 [Gemini AI 해석]\n{_r['interp']}\n\n📊 [체결 상세]\n수량: {_r['qty']:,}계약 | 프리미엄: {_r['prem_str']} | 만기: {_exp_iso}",
                "cal": "옵션 헷지 (풋)" if _r["sent"] == "약세" else "옵션 만기 (콜/전략)",
            }
            if _cid in _gcal_idx:
                _gcal_list[_gcal_idx[_cid]] = _c_ev
            else:
                _gcal_list.append(_c_ev)
            _cal_cnt += 1
        save_json_file(_gcal_p, _gcal_list)
        st.toast(f"✅ 구글 캘린더에 해석 포함 {_cal_cnt}건 등록 완료!")

    # 다크 테마 테이블 렌더링 (스크린샷 1:1 스타일)
    if _f_rows:
        _trs = []
        for _r in _f_rows[:60]:
            _cp_cls = "background:#0f5132;color:#75b798;border:1px solid #198754;" if _r["cp"] == "Call" else "background:#58151c;color:#ea868f;border:1px solid #dc3545;"
            _sd_cls = "color:#4ade80;font-weight:700;" if _r["side"] == "BUY" else ("color:#f87171;font-weight:700;" if _r["side"] == "SELL" else "color:#9aa0a6;font-weight:700;")
            _st_cls = "background:#1e3a5f;color:#93c5fd;" if _r["status"] == "신규" else "background:#3b2f1e;color:#fcd34d;"
            _k_lbl = f"{_r['strike']:g} {'CALL' if _r['cp']=='Call' else 'PUT'}"
            _trs.append(
                f"<tr style='border-bottom:1px solid #26292e;'>"
                f"<td style='padding:8px 10px;font-weight:700;color:#fff;'>{_r['tk']}</td>"
                f"<td style='padding:8px 10px;color:#9aa0a6;font-size:12.5px;'>{_r['exp']}</td>"
                f"<td style='padding:8px 10px;'><span style='{_st_cls}padding:2px 7px;border-radius:4px;font-size:11.5px;font-weight:600;'>{_r['status']}</span></td>"
                f"<td style='padding:8px 10px;'><span style='{_cp_cls}padding:3px 9px;border-radius:5px;font-size:12px;font-weight:700;display:inline-block;min-width:86px;text-align:center;'>{_k_lbl}</span></td>"
                f"<td style='padding:8px 10px;{_sd_cls}'>{_r['side']}</td>"
                f"<td style='padding:8px 10px;text-align:right;color:#e2e8f0;font-variant-numeric:tabular-nums;'>{_r['qty']:,}</td>"
                f"<td style='padding:8px 10px;text-align:right;font-weight:700;color:#fff;font-variant-numeric:tabular-nums;'>{_r['prem_str']}</td>"
                f"<td style='padding:8px 10px;color:#cbd5e1;font-size:12.5px;'>{_r['emoji']} {_r['interp']}</td>"
                f"</tr>"
            )
        _tbl_html = (
            "<div style='background:#0f1419;border:1px solid #26292e;border-radius:10px;overflow-x:auto;margin:8px 0 14px;'>"
            "<table style='width:100%;border-collapse:collapse;font-size:13px;'>"
            "<thead><tr style='background:#161b22;border-bottom:1px solid #30363d;color:#8b949e;text-align:left;font-size:12px;'>"
            "<th style='padding:9px 10px;'>종목</th><th style='padding:9px 10px;'>EXP</th><th style='padding:9px 10px;'>상태</th>"
            "<th style='padding:9px 10px;'>계약</th><th style='padding:9px 10px;'>BUY/SELL</th>"
            "<th style='padding:9px 10px;text-align:right;'>수량</th><th style='padding:9px 10px;text-align:right;'>총 PREM</th>"
            "<th style='padding:9px 10px;'>해석</th></tr></thead>"
            f"<tbody>{''.join(_trs)}</tbody></table></div>"
        )
        st.markdown(_tbl_html, unsafe_allow_html=True)

        # 하단 종합 요약 박스
        with st.container(border=True):
            st.markdown(
                f"**전체: 강세 `${_bull_sum:.2f}M` vs 약세 `${_bear_sum:.2f}M`** (MID `${_mid_sum:.2f}M`) → **{_overall_lbl}**"
            )
            if _tk_summary_lines:
                st.markdown("  \n".join(_tk_summary_lines))
    else:
        st.info("조건에 맞는 대형 옵션 체결이 없습니다. 필터를 조정하거나 위 붙여넣기 상자에서 체결 내역을 추가해 주세요.")

    if st.session_state.get("big_ai_summary_txt"):
        st.info(st.session_state["big_ai_summary_txt"])

if nav_menu == "🎯 행사가별·동반 체결":
    st.title("🎯 행사가별 옵션 주문 & 만기 간 동반 체결 (무무 LV3 · ΔOI · 신규/청산/롤오버 · AI)")
    st.caption("구글 시트 + 텔레그램 큰 체결 + 야후 실시간 OI/GEX + 저장된 이전 OI(ΔOI) + 무무 LV3 호가를 결합해 신규(OPEN)/청산(CLOSE)/롤오버 판별 및 AI 전략 시나리오를 생성합니다.")

    STRIKE_NOTE_PATH = os.path.expanduser("~/.optionhub_strike_notes.json")
    strike_notes = load_json_file(STRIKE_NOTE_PATH, {})
    oi_hist_all = load_json_file(OI_PATH, {})
    saved_big_flows = load_json_file(BIG_FLOWS_PATH, [])

    def _parse_money_f(val):
        s = str(val or "").replace("$", "").replace(",", "").strip().upper()
        if not s or s == "-":
            return 0.0
        mul = 1.0
        if s.endswith("M"):
            mul = 1_000_000.0; s = s[:-1]
        elif s.endswith("K"):
            mul = 1_000.0; s = s[:-1]
        try:
            return float(s) * mul
        except Exception:
            return 0.0

    _sh_rows = []
    for _r in (all_raw_flows or []):
        try:
            _k_num = float(str(_r[7]).replace("$", "").replace(",", "").strip())
        except Exception:
            _k_num = 0.0
        _sh_rows.append({
            "날짜": str(_r[0]),
            "티커": str(_r[1]).upper(),
            "체결시간": str(_r[2]),
            "구분": str(_r[3]).capitalize(),
            "매수/매도": "BUY" if "A" in str(_r[4]) else ("SELL" if "B" in str(_r[4]) else "미정"),
            "만기일": str(_r[5]),
            "행사가": _k_num,
            "유형": str(_r[13]),
            "프리미엄": _parse_money_f(_r[14]),
            "수량": int(float(_r[15])) if str(_r[15]).replace(".", "", 1).isdigit() else 0,
            "OI": 0,
            "비고": str(_r[13]),
        })
    df_all = pd.DataFrame(_sh_rows)

    # 무무 실시간 DB 조회
    mm_q = {}
    mm_bk = {}
    _mm_db_f = os.path.expanduser("~/moomoo-hub/moomoo.db")
    if os.path.exists(_mm_db_f):
        try:
            _c_f = sqlite3.connect(_mm_db_f, timeout=2.0)
            for _s, _p, _ch, _v, _t, _r in _c_f.execute("SELECT sym, px, chg, vol, ts, raw FROM quotes").fetchall():
                try:
                    _rw = json.loads(_r) if _r else {}
                except Exception:
                    _rw = {}
                mm_q[_s.replace("US.", "").upper()] = {"px": float(_p or 0), "chg": _ch, "vol": float(_v or 0), "ts": _t, "raw": _rw}
            for _s, _k, _d in _c_f.execute("SELECT sym, kind, data FROM aux WHERE kind='book'").fetchall():
                try:
                    mm_bk[_s.replace("US.", "").upper()] = json.loads(_d)
                except Exception:
                    pass
            _c_f.close()
        except Exception:
            pass

    sheet_tks = sorted(df_all["티커"].dropna().astype(str).str.upper().unique().tolist()) if not df_all.empty and "티커" in df_all.columns else []
    base_tks_f = ["SOXL", "SPY", "NVDA", "VIX", "SPX", "QQQ", "TSLA", "MU", "AMD", "PLTR", "SMH", "IWM", "META", "AMZN", "AAPL"]
    all_tks_f = list(dict.fromkeys(base_tks_f + sorted(list(mm_q.keys())) + sheet_tks))

    fc1, fc2, fc3, fc4 = st.columns([1.1, 1.1, 1.2, 1.4])
    sel_tk_f = fc1.selectbox("종목 선택", all_tks_f, index=0, key="flow_stk_tk")
    custom_tk_f = fc2.text_input("직접 입력 (선택)", "", placeholder="예: SOXL, SPY, VIX, BA", key="flow_stk_cus").strip().upper()
    tk_f = custom_tk_f if custom_tk_f else sel_tk_f
    use_yf_live = fc3.checkbox("야후 실시간 OI · GEX 결합 조회", value=True, key="flow_use_yf")
    if fc4.button("🔄 지금 OI·GEX 스냅샷 수집 & 저장", type="primary", use_container_width=True, key="btn_flow_save_oi"):
        st.cache_data.clear()
        with st.spinner(f"{tk_f} 실시간 OI·GEX 스냅샷 수집 & 저장 중..."):
            _s_rows, _s_px, _s_st = fetch_yahoo_oi(tk_f)
        if _s_st == "OK" and _s_rows:
            from datetime import datetime as _dt_f
            _now_f = _dt_f.now().strftime("%Y-%m-%d %H:%M")
            _c_oi_f = sum(x["OI"] for x in _s_rows if x["구분"] == "Call")
            _p_oi_f = sum(x["OI"] for x in _s_rows if x["구분"] == "Put")
            _ng_f = round(sum(x["GEX($M)"] for x in _s_rows), 2)
            _nd_f = round(sum(x["DEX($M)"] for x in _s_rows), 2)
            oi_hist_all.setdefault(tk_f, []).append({
                "수집시각": _now_f,
                "Spot": _s_px,
                "Call_OI": _c_oi_f,
                "Put_OI": _p_oi_f,
                "Put_Call_OI_Ratio": round(_p_oi_f / _c_oi_f, 2) if _c_oi_f > 0 else 0,
                "Net_GEX_M": _ng_f,
                "Net_DEX_M": _nd_f,
                "상세": _s_rows,
            })
            save_json_file(OI_PATH, oi_hist_all)
            st.toast(f"✅ {tk_f} (${_s_px}) OI·GEX 스냅샷 저장 완료!")
            st.rerun()
        else:
            st.error(f"수집 중 오류: {_s_st}")

    # =========================================================
    # [상단 도구] 🚨 텔레그램 큰 옵션 체결 붙여넣기 & AI 키 설정
    # =========================================================
    with st.expander("🚨 텔레그램 '큰 옵션 체결' 붙여넣기 자동 파싱 & 🔑 Gemini 무료 API 키 설정", expanded=False):
        ap_l, ap_r = st.columns([2.2, 1.0])
        with ap_l:
            raw_big_in = st.text_area(
                "📋 '🚨 큰 옵션 체결' 메시지 붙여넣기 (또는 텔레그램 봇에 보내면 자동 수집됨)",
                height=110,
                placeholder="🟢 SPY 750P 11-16 SELL $14.65M · 74010계약 · PREMIUM SALE ...",
                key="big_flow_paste_in"
            )
            if st.button("⚡ 큰 옵션 체결 파싱 & 홈페이지 저장", type="primary", key="btn_parse_big"):
                parsed_recs, parsed_flip = parse_tg_big_flows(raw_big_in)
                if parsed_recs:
                    entry_b = {
                        "ts": pd.Timestamp.now(tz="Asia/Seoul").strftime("%Y-%m-%d %H:%M"),
                        "tk": parsed_recs[0]["tk"],
                        "flip": parsed_flip,
                        "items": parsed_recs,
                    }
                    saved_big_flows.insert(0, entry_b)
                    save_json_file(BIG_FLOWS_PATH, saved_big_flows[:50])
                    st.success(f"✅ {entry_b['tk']} 큰 옵션 체결 {len(parsed_recs)}건이 파싱되어 저장되었습니다!")
                    st.rerun()
                else:
                    st.warning("파싱할 수 있는 체결 라인(🟢/🔴/🟡 티커 행사가C/P 만기 BUY/SELL $금액 · 계약수)을 찾지 못했습니다.")
        with ap_r:
            st.markdown("**🔑 Gemini 무료 API 키 (1회 저장)**")
            cur_gk = get_gemini_api_key()
            new_gk = st.text_input("Google AI Studio API Key", value=cur_gk, type="password", placeholder="AIzaSy...", key="gk_input_box")
            if st.button("💾 API 키 서버에 저장", use_container_width=True, key="btn_save_gk"):
                with open(GEMINI_KEY_PATH, "w", encoding="utf-8") as fg:
                    fg.write(new_gk.strip())
                st.success("✅ Gemini API 키가 저장되었습니다! (미입력 시 서버 Qwen 자동 사용)")
                st.rerun()
            st.caption("무료 키가 있으면 이미지/표 OCR 판독 및 1초 요약이 작동하며, 없으면 서버 내 무료 Qwen2.5:7b가 대신 응답합니다.")

    # 무무 LV3 실시간 상단 배너
    qm = mm_q.get(tk_f, {})
    bkm = mm_bk.get(tk_f, {})
    bids_m = bkm.get("Bid") or bkm.get("bids") or []
    asks_m = bkm.get("Ask") or bkm.get("asks") or []
    b_qty = sum(int(x[1]) for x in bids_m[:5] if len(x) >= 2)
    a_qty = sum(int(x[1]) for x in asks_m[:5] if len(x) >= 2)
    lv3_bias = "매수 호가 우위" if b_qty > a_qty * 1.15 else ("매도 호가 우위" if a_qty > b_qty * 1.15 else "호가 균형")
    spot_live = float(qm.get("px", 0) or 0)

    @st.cache_data(ttl=240, show_spinner=False)
    def _fetch_flow_chain(t_sym):
        return fetch_yahoo_oi(t_sym)

    yf_rows, yf_spot, yf_err = ([], 0.0, "")
    if use_yf_live:
        yf_rows, yf_spot, yf_err = _fetch_flow_chain(tk_f)
    if spot_live <= 0 and yf_spot > 0:
        spot_live = float(yf_spot)

    st.markdown(f"""
    <div style="display:flex; flex-wrap:wrap; gap:16px; align-items:center; background:#07111e; border:1px solid #1e3a5f; border-radius:8px; padding:10px 14px; margin-bottom:10px; font-family:monospace; font-size:13px;">
      <span style="color:#f8fafc; font-weight:800; font-size:15px;">{tk_f}</span>
      <span>무무 LV3 현재가: <b style="color:#38bdf8;">{f"${spot_live:,.2f}" if spot_live>0 else "-"}</b> {f"({qm['chg']:+.2f}%)" if qm.get('chg') is not None else ""}</span>
      <span>무무 호가(Top5): <b style="color:#10b981;">Bid {b_qty:,}</b> / <b style="color:#ef4444;">Ask {a_qty:,}</b> · <span style="color:#fbbf24;">{lv3_bias}</span></span>
      <span style="color:#94a3b8; font-size:11px;">※ 무무: 미국주식 LV3 실시간 연동 · 옵션 체인: 야후+시트+텔레그램+이전OI</span>
    </div>
    """, unsafe_allow_html=True)

    df_tk_sh = pd.DataFrame()
    if not df_all.empty and "티커" in df_all.columns:
        df_tk_sh = df_all[df_all["티커"].astype(str).str.upper() == tk_f].copy()

    df_yf_f = pd.DataFrame(yf_rows) if yf_rows else pd.DataFrame()
    if not df_yf_f.empty and "만기" in df_yf_f.columns and "만기일" not in df_yf_f.columns:
        df_yf_f["만기일"] = df_yf_f["만기"]

    # 이전 OI 스냅샷 매핑: (만기일, 구분, 행사가) -> 이전 OI
    prev_oi_map = {}
    prev_snap_date = "-"
    tk_snaps = oi_hist_all.get(tk_f, [])
    if tk_snaps:
        # 가장 최근 스냅샷이 오늘자와 다르면 마지막 스냅샷, 같고 2개 이상이면 -2번째 스냅샷을 이전 OI로 사용
        ref_snap = tk_snaps[-2] if len(tk_snaps) >= 2 else tk_snaps[-1]
        prev_snap_date = str(ref_snap.get("수집시각", "-"))[:10]
        for _sx in ref_snap.get("상세", []):
            _exp_k = str(_sx.get("만기", _sx.get("만기일", "")))[:10]
            _cp_k = str(_sx.get("구분", "Call")).capitalize()
            _strk_k = float(_sx.get("행사가", 0) or 0)
            prev_oi_map[(_exp_k, _cp_k, _strk_k)] = int(_sx.get("OI", 0) or 0)

    def _classify_pos_status(vol_q, prev_oi_q, cur_oi_q, is_rollover=False):
        """신규(OPEN) / 청산(CLOSE) / 롤오버(ROLLOVER) 자동 판별"""
        if is_rollover:
            return "🔄 롤오버 후보", "#38bdf8"
        if prev_oi_q is not None and prev_oi_q > 0:
            d_oi = cur_oi_q - prev_oi_q
            if d_oi > 0 and vol_q > 0:
                return f"🆕 신규 유입 (+{d_oi:,})", "#10b981"
            if d_oi < 0 and vol_q > 0:
                return f"✂️ 청산 우세 ({d_oi:,})", "#f87171"
        if cur_oi_q > 0 and vol_q > cur_oi_q:
            return "🆕 신규 확정 (Vol>OI)", "#10b981"
        if cur_oi_q > 0 and vol_q >= cur_oi_q * 0.5:
            return "⚡ 대량 회전·신규후보", "#fbbf24"
        return "미확정 (장마감 OI 대기)", "#94a3b8"

    tg_arch_f = load_json_file(os.path.expanduser("~/.optionhub_tg_archive.json"), [])
    tg_hits = [m for m in tg_arch_f if tk_f in (m.get("symbols") or []) or tk_f in (m.get("text") or "").upper()]

    def _render_dark_table(title_main, sub_hdr, cols, rows_html, note_footer=""):
        ths = "".join(f"<th style='padding:6px 8px; text-align:center; color:#7dd3fc; font-size:11px; border-bottom:1px solid #1e3a5f; white-space:nowrap;'>{c}</th>" for c in cols)
        trs = "".join(rows_html)
        st.markdown(f"""
        <div style="background:#07111e; border:1px solid #1e3a5f; border-radius:8px; padding:12px 14px; margin-bottom:14px; font-family:'Segoe UI',sans-serif; overflow-x:auto;">
          <div style="font-size:16px; font-weight:800; color:#f8fafc; margin-bottom:2px;">{title_main}</div>
          <div style="font-size:12px; color:#38bdf8; font-weight:700; margin-bottom:8px;">{sub_hdr}</div>
          <table style="width:100%; border-collapse:collapse; font-size:12px; color:#e2e8f0;">
            <thead><tr style="background:#0d2538;">{ths}</tr></thead>
            <tbody>{trs}</tbody>
          </table>
          {f"<div style='font-size:11px; color:#94a3b8; margin-top:6px;'>{note_footer}</div>" if note_footer else ""}
        </div>
        """, unsafe_allow_html=True)

    # 만약 저장된 '🚨 큰 옵션 체결'에 현재 종목(또는 최근 저장본)이 있으면 상단에 시각화
    tk_big_list = [b for b in saved_big_flows if b.get("tk") == tk_f] or (saved_big_flows[:1] if saved_big_flows else [])
    if tk_big_list:
        latest_b = tk_big_list[0]
        b_items = latest_b.get("items", [])
        bull_m = round(sum(x["prem_m"] for x in b_items if x["emoji"] == "🟢"), 2)
        bear_m = round(sum(x["prem_m"] for x in b_items if x["emoji"] == "🔴"), 2)
        hedg_m = round(sum(x["prem_m"] for x in b_items if x["emoji"] == "🟡"), 2)
        b_rows_h = []
        for x in b_items:
            c_emo = "#10b981" if x["emoji"] == "🟢" else ("#ef4444" if x["emoji"] == "🔴" else "#fbbf24")
            note_s = " · ".join(x.get("notes") or []) or "-"
            b_rows_h.append(
                f"<tr style='border-bottom:1px solid #13283d; text-align:center;'>"
                f"<td style='padding:5px;'>{x['exp']}</td>"
                f"<td style='padding:5px; color:{c_emo}; font-weight:700;'>{x['emoji']} {x['strike']:g} {x['cp'].upper()}</td>"
                f"<td style='padding:5px; font-weight:700;'>{x['side']}</td>"
                f"<td style='padding:5px; color:#fbbf24; font-weight:700;'>{x['prem_str']}</td>"
                f"<td style='padding:5px;'>{x['qty']:,}계약</td>"
                f"<td style='padding:5px; color:#38bdf8;'>{x['tag']}</td>"
                f"<td style='padding:5px; text-align:left; font-size:11px; color:#cbd5e1;'>{note_s}</td></tr>"
            )
        _render_dark_table(
            f"🚨 최근 수신 큰 옵션 체결 ({latest_b.get('tk')} · {latest_b.get('ts')})",
            f"🟢 강세(콜매수·풋매도) ${bull_m:,.2f}M  |  🔴 약세(콜매도·풋매수) ${bear_m:,.2f}M  |  🟡 헤지 후보 ${hedg_m:,.2f}M" + (f"  |  📍 플립 ${latest_b['flip']}" if latest_b.get("flip") else ""),
            ["만기", "계약", "방향", "프리미엄", "계약수", "유형(TAG)", "플립·헤지 해석"],
            b_rows_h
        )

    # =========================================================
    # [섹션 0] 전체 상황 한눈에 보기 (이전 OI · 최신 OI · ΔOI · 신규/청산 판정)
    # =========================================================
    st.subheader(f"0️⃣ {tk_f} 전체 상황 & ΔOI (신규/청산/롤오버) 한눈에 보기")
    if not df_yf_f.empty:
        _c_all = df_yf_f[df_yf_f["구분"] == "Call"]
        _p_all = df_yf_f[df_yf_f["구분"] == "Put"]
        _c_vol = int(_c_all["거래량"].sum())
        _p_vol = int(_p_all["거래량"].sum())
        _c_oi = int(_c_all["OI"].sum())
        _p_oi = int(_p_all["OI"].sum())
        _pc_vol = round(_p_vol / max(_c_vol, 1), 2)
        _pc_oi = round(_p_oi / max(_c_oi, 1), 2)
        _tot_gex = round(float(df_yf_f["GEX($M)"].sum()), 2)
        _c_near = _c_all[(_c_all["행사가"] >= spot_live * 0.60) & (_c_all["행사가"] <= spot_live * 1.40)] if spot_live > 0 else _c_all
        _p_near = _p_all[(_p_all["행사가"] >= spot_live * 0.60) & (_p_all["행사가"] <= spot_live * 1.40)] if spot_live > 0 else _p_all
        if _c_near.empty: _c_near = _c_all
        if _p_near.empty: _p_near = _p_all
        _cw_f = float(_c_near.sort_values("OI", ascending=False).iloc[0]["행사가"]) if not _c_near.empty else 0.0
        _pw_f = float(_p_near.sort_values("OI", ascending=False).iloc[0]["행사가"]) if not _p_near.empty else 0.0
        _zg_f = calc_zero_gamma(df_yf_f, spot_live)
        _gex_regime = "+GEX (변동성 억제 · 박스권)" if _tot_gex >= 0 else "-GEX (변동성 증폭 · 추세추종)"
        _gex_col = "#10b981" if _tot_gex >= 0 else "#ef4444"
        _sh_cnt = len(df_tk_sh) if not df_tk_sh.empty else 0
        _tg_cnt = len(tg_hits)

        # 동일 행사가에서 2개 이상 만기가 동시에 거래량 상위인 경우 롤오버 후보 행사가 집합 표시
        _roll_strikes = set()
        _act_yf = df_yf_f[df_yf_f["거래량"] >= 100]
        if not _act_yf.empty:
            for (_rk, _rcp), _rg in _act_yf.groupby(["행사가", "구분"]):
                if _rg["만기일"].nunique() >= 2:
                    _roll_strikes.add((float(_rk), str(_rcp)))

        _sum_row = (
            f"<tr style='border-bottom:1px solid #13283d; text-align:center;'>"
            f"<td style='padding:8px; color:#10b981; font-weight:700;'>{_c_vol:,} / {_c_oi:,}</td>"
            f"<td style='padding:8px; color:#ef4444; font-weight:700;'>{_p_vol:,} / {_p_oi:,}</td>"
            f"<td style='padding:8px;'>Vol {_pc_vol} · OI {_pc_oi}</td>"
            f"<td style='padding:8px; color:#10b981; font-weight:700;'>${_cw_f:g}</td>"
            f"<td style='padding:8px; color:#ef4444; font-weight:700;'>${_pw_f:g}</td>"
            f"<td style='padding:8px; color:#fbbf24; font-weight:700;'>{f'${_zg_f:g}' if _zg_f else '-'}</td>"
            f"<td style='padding:8px; color:{_gex_col}; font-weight:700;'>${_tot_gex:+.2f}M<br><span style='font-size:10px;'>{_gex_regime}</span></td>"
            f"<td style='padding:8px;'>시트 {_sh_cnt}건 · TG {_tg_cnt}건</td>"
            f"</tr>"
        )
        _render_dark_table(
            f"{tk_f} · 전체 수급·감마 구조 요약",
            f"무무 LV3 현재가 {f'${spot_live:,.2f}' if spot_live>0 else '-'} · {lv3_bias}",
            ["콜 거래량 / OI", "풋 거래량 / OI", "P/C 비율", "Call Wall", "Put Wall", "Flip Gamma", "총 Net GEX", "수신 로그"],
            [_sum_row]
        )

        # OPTION 전략 스타일 표: 일주일치(오늘 ~ 이번 주 금요일까지) 만기별 핵심 행사가 균형 표시 + 개별 만기 필터
        _avail_exps = sorted(df_yf_f["만기일"].dropna().astype(str).str[:10].unique().tolist())
        _exp_pick = st.selectbox(
            "OPTION 전략 만기 필터 (기본: 일주일치 · 금요일 만기까지 함께 표시)",
            ["전체 (일주일치 · 금요일까지)"] + _avail_exps,
            key=f"opt_strat_exp_{tk_f}",
        )
        df_top10_base = df_yf_f.copy()
        if spot_live > 0:
            _near_base = df_top10_base[(df_top10_base["행사가"] >= spot_live * 0.70) & (df_top10_base["행사가"] <= spot_live * 1.30)]
            if not _near_base.empty:
                df_top10_base = _near_base
        if _exp_pick != "전체 (일주일치 · 금요일까지)":
            df_top10 = df_top10_base[df_top10_base["만기일"].astype(str).str[:10] == _exp_pick].copy()
            df_top10["_abs_gex"] = df_top10["GEX($M)"].abs()
            df_top10 = df_top10.sort_values(["_abs_gex", "OI", "거래량"], ascending=False).head(15)
        else:
            _parts = []
            for _ei, _ex_d in enumerate(_avail_exps[:6]):
                _sub_e = df_top10_base[df_top10_base["만기일"].astype(str).str[:10] == _ex_d].copy()
                _sub_e["_abs_gex"] = _sub_e["GEX($M)"].abs()
                _take_n = 4 if (_ei == 0 or _ei == len(_avail_exps[:6]) - 1) else 2
                _parts.append(_sub_e.sort_values(["거래량", "_abs_gex", "OI"] if _ei == 0 else ["_abs_gex", "OI", "거래량"], ascending=False).head(_take_n))
            df_top10 = pd.concat(_parts, ignore_index=True) if _parts else df_top10_base.head(12)
        df_top10 = df_top10.sort_values(["만기일", "행사가"], ascending=[True, True])
        _top_rows_html = []
        for _, _rt in df_top10.iterrows():
            _cp_c = "#10b981" if _rt["구분"] == "Call" else "#f43f5e"
            _vq = int(_rt["거래량"])
            _oiq = int(_rt["OI"])
            _exp_s = str(_rt["만기일"])[:10]
            _k_flt = float(_rt["행사가"])
            _prev_q = prev_oi_map.get((_exp_s, _rt["구분"], _k_flt))
            if _prev_q is not None:
                _doi = _oiq - _prev_q
                _doi_col = "#10b981" if _doi > 0 else ("#ef4444" if _doi < 0 else "#94a3b8")
                _prev_s = f"{_prev_q:,}"
                _doi_s = f"<span style='color:{_doi_col}; font-weight:700;'>{_doi:+,}</span>"
            else:
                _prev_s = "-"
                _doi_s = "<span style='color:#64748b;'>스냅샷대기</span>"
            _is_roll = (_k_flt, str(_rt["구분"])) in _roll_strikes
            _st_txt, _st_col = _classify_pos_status(_vq, _prev_q, _oiq, _is_roll)
            _gex_abs_k = abs(float(_rt["GEX($M)"])) * 1000.0
            _gex_str = f"${_gex_abs_k:,.1f}K" if _gex_abs_k < 1000 else f"${_gex_abs_k/1000.0:,.2f}M"
            _role = []
            if _cw_f and _k_flt == _cw_f and _rt["구분"] == "Call":
                _role.append("🟢CW")
            if _pw_f and _k_flt == _pw_f and _rt["구분"] == "Put":
                _role.append("🔴PW")
            if spot_live > 0 and abs(_k_flt - spot_live) / spot_live <= 0.02:
                _role.append("⚡ATM")
            _role_tag = (" " + " ".join(_role)) if _role else ""
            _top_rows_html.append(
                f"<tr style='border-bottom:1px solid #13283d; text-align:center;'>"
                f"<td style='padding:6px;'>{_exp_s[2:].replace('-','/')}</td>"
                f"<td style='padding:6px;'><span style='border:1px solid {_cp_c}; color:{_cp_c}; padding:2px 8px; border-radius:4px; font-weight:700;'>{_k_flt:g} {_rt['구분'].upper()}{_role_tag}</span></td>"
                f"<td style='padding:6px;'>{_prev_s}</td>"
                f"<td style='padding:6px; font-weight:700;'>{_oiq:,}</td>"
                f"<td style='padding:6px;'>{_doi_s}</td>"
                f"<td style='padding:6px; font-weight:700;'>{_vq:,}</td>"
                f"<td style='padding:6px; color:#e2e8f0; font-weight:700;'>{_gex_str}</td>"
                f"<td style='padding:6px; color:{_st_col}; font-weight:700;'>{_st_txt}</td></tr>"
            )
        _render_dark_table(
            f"OPTION 전략 · {tk_f} 행사가별 이전 OI → 최신 OI (ΔOI) & 포지션 판정",
            f"${spot_live:,.2f} 참고가 · 이전 OI 기준일: {prev_snap_date} (📊 OI 수집 탭 저장 시 자동 비교)",
            ["EXP ET", "계약", "이전 OI", "최신 OI", "ΔOI", "당일 수량", "|GEX| · 1%", "OPEN / CLOSE / 롤오버"],
            _top_rows_html,
            "※ ΔOI(+) + 거래량 동반 = 신규 유입(OPEN) | ΔOI(-) + 거래량 동반 = 기존 포지션 청산(CLOSE) | 복수 만기 동시 대량 거래 = 롤오버 후보"
        )
    else:
        st.info("야후 실시간 옵션 체인 조회를 켜면 전체 요약 표와 ΔOI 전략 맵이 표시됩니다.")

    # =========================================================
    # [섹션 1] 만기 간 동반 체결 (캘린더 · 롤오버 · 스프레드)
    # =========================================================
    st.subheader("1️⃣ 만기 간 동반 체결 (캘린더 · 롤오버 · 스프레드)")
    cal_rows_html = []
    sh_cal_hits = []
    if not df_tk_sh.empty and "행사가" in df_tk_sh.columns and "만기일" in df_tk_sh.columns:
        for (k_s, cp_s), g_s in df_tk_sh.groupby(["행사가", "구분"]):
            exps_u = g_s["만기일"].dropna().astype(str).unique().tolist()
            if len(exps_u) >= 2:
                sh_cal_hits.append((k_s, cp_s, exps_u, g_s))

    if sh_cal_hits:
        k_s, cp_s, exps_u, g_s = sh_cal_hits[0]
        tot_p_cal = float(g_s["프리미엄"].sum()) if "프리미엄" in g_s.columns else 0.0
        for r_i, (exp_u, ge) in enumerate(g_s.groupby("만기일"), 1):
            buy_q = int(ge[ge["매수/매도"].astype(str).str.contains("BUY|ASK|매수", case=False, na=False)]["수량"].sum()) if "매수/매도" in ge.columns and "수량" in ge.columns else 0
            sell_q = int(ge[ge["매수/매도"].astype(str).str.contains("SELL|BID|매도", case=False, na=False)]["수량"].sum()) if "매수/매도" in ge.columns and "수량" in ge.columns else 0
            tot_q = int(ge["수량"].sum()) if "수량" in ge.columns else len(ge)
            unk_q = max(tot_q - buy_q - sell_q, 0)
            oi_b = int(ge["OI"].max()) if "OI" in ge.columns and not ge["OI"].isna().all() else 0
            q_oi = f"{round(tot_q / max(oi_b, 1) * 100)}%" if oi_b > 0 else "-"
            prem_u = float(ge["프리미엄"].sum()) if "프리미엄" in ge.columns else 0.0
            cp_col = "#10b981" if "CALL" in str(cp_s).upper() else "#ef4444"
            cal_rows_html.append(
                f"<tr style='border-bottom:1px solid #13283d; text-align:center;'>"
                f"<td style='padding:6px;'>{str(exp_u)[:10]}</td>"
                f"<td style='padding:6px;'><span style='border:1px solid {cp_col}; color:{cp_col}; padding:1px 6px; border-radius:4px; font-weight:700;'>{k_s} {str(cp_s).upper()}</span></td>"
                f"<td style='padding:6px; color:#10b981;'>{buy_q:,}</td>"
                f"<td style='padding:6px; color:#e2e8f0;'>{sell_q:,}</td>"
                f"<td style='padding:6px; font-weight:700;'>{unk_q:,}</td>"
                f"<td style='padding:6px;'><span style='border:1px solid #b45309; padding:1px 6px; border-radius:4px; color:#fbbf24;'>#{r_i} {tot_q:,}</span></td>"
                f"<td style='padding:6px;'>{oi_b:,}</td>"
                f"<td style='padding:6px;'>{q_oi}</td>"
                f"<td style='padding:6px;'><span style='border:1px solid #b45309; padding:1px 6px; border-radius:4px; color:#fbbf24;'>${prem_u/1000:,.1f}K</span></td>"
                f"<td style='padding:6px; color:#38bdf8;'>🔄 롤오버/캘린더</td></tr>"
            )
        _render_dark_table(
            f"{tk_f} · 시트 기준 만기 간 동반 체결",
            f"{' ↔ '.join([str(e)[:10] for e in exps_u[:3]])} · {k_s} {cp_s} · PREM 합계 ${tot_p_cal:,.0f}",
            ["EXP ET", "계약", "BUY", "SELL", "미정", "순위 / 수량", "기초 OI", "Q / OI", "순위 / PREM", "판정"],
            cal_rows_html,
            "구글 시트 옵션 플로우 내역에서 동일 행사가·복수 만기 동시 체결을 자동 매칭했습니다."
        )
    elif not df_yf_f.empty:
        df_yf_near = df_yf_f[df_yf_f["거래량"] > 0].copy()
        if not df_yf_near.empty:
            top_pair = df_yf_near.groupby(["행사가", "구분"]).filter(lambda g: g["만기일"].nunique() >= 2)
            if not top_pair.empty:
                best_k_cp = top_pair.groupby(["행사가", "구분"])["거래량"].sum().idxmax()
                sub_p = top_pair[(top_pair["행사가"] == best_k_cp[0]) & (top_pair["구분"] == best_k_cp[1])].sort_values("거래량", ascending=False).head(3)
                sub_p_prem_rank = sub_p["거래량"].rank(ascending=False, method="min").astype(int)
                for idx_p, (_, rp) in enumerate(sub_p.iterrows(), 1):
                    cp_col = "#10b981" if rp["구분"] == "Call" else "#ef4444"
                    v_q = int(rp["거래량"])
                    oi_b = int(rp["OI"])
                    v_oi = f"{round(v_q / max(oi_b, 1) * 100)}%" if oi_b > 0 else "-"
                    gex_m = float(rp.get("GEX($M)", 0) or 0)
                    cal_rows_html.append(
                        f"<tr style='border-bottom:1px solid #13283d; text-align:center;'>"
                        f"<td style='padding:6px;'>{rp['만기일']}</td>"
                        f"<td style='padding:6px;'><span style='border:1px solid {cp_col}; color:{cp_col}; padding:1px 6px; border-radius:4px; font-weight:700;'>{rp['행사가']:g} {rp['구분'].upper()}</span></td>"
                        f"<td style='padding:6px; color:#94a3b8;'>-</td>"
                        f"<td style='padding:6px; color:#94a3b8;'>-</td>"
                        f"<td style='padding:6px; font-weight:700;'>{v_q:,}</td>"
                        f"<td style='padding:6px;'><span style='border:1px solid #b45309; padding:1px 6px; border-radius:4px; color:#fbbf24;'>#{idx_p} {v_q:,}</span></td>"
                        f"<td style='padding:6px;'>{oi_b:,}</td>"
                        f"<td style='padding:6px;'>{v_oi}</td>"
                        f"<td style='padding:6px;'>#{sub_p_prem_rank.loc[rp.name]} · IV {rp['IV(%)']:.1f}%</td>"
                        f"<td style='padding:6px;'><span style='border:1px solid #b45309; padding:1px 6px; border-radius:4px; color:#38bdf8;'>${gex_m:+.2f}M</span></td></tr>"
                    )
                _render_dark_table(
                    f"{tk_f} · 만기 간 동시 활성 계약 (야후 실시간 체인 기준)",
                    f"{' ↔ '.join(sub_p['만기일'].tolist())} · {best_k_cp[0]:g} {best_k_cp[1].upper()} 동시 거래 (롤오버·캘린더 후보)",
                    ["EXP ET", "계약", "BUY", "SELL", "미정(거래량)", "순위 / 수량", "기초 OI", "V / OI", "순위 / IV", "GEX · 1%"],
                    cal_rows_html,
                    "※ 동일 행사가의 근월물·원월물에서 동시에 거래량이 집중된 계약입니다."
                )
    if not cal_rows_html:
        st.info("현재 선택 종목에서 동일 행사가·복수 만기 동반 체결 데이터가 없습니다.")

    # =========================================================
    # [섹션 2] 행사가별 옵션 주문 (수신 계약 누적 · 주요 체결 시간순 · 과거 NOTE)
    # =========================================================
    st.subheader("2️⃣ 행사가별 옵션 주문 & 과거 NOTE (BTO/STO 이력)")
    strike_choices = []
    if not df_tk_sh.empty and "행사가" in df_tk_sh.columns:
        strike_choices.extend([f"{float(r['행사가']):g} {str(r['구분']).upper()}" for _, r in df_tk_sh.iterrows() if pd.notna(r.get("행사가"))])
    if not df_yf_f.empty:
        top_yf_k = df_yf_f.sort_values("거래량", ascending=False).head(12)
        strike_choices.extend([f"{float(r['행사가']):g} {r['구분'].upper()}" for _, r in top_yf_k.iterrows()])
    strike_choices = list(dict.fromkeys(strike_choices)) or ["전체 상위"]

    sc_sel1, sc_sel2 = st.columns([1.4, 2.6])
    sel_k_lbl = sc_sel1.selectbox("집중 조회 행사가", strike_choices, key="flow_sel_k")

    acc_rows = []
    detail_rows = []
    if not df_yf_f.empty:
        if sel_k_lbl != "전체 상위":
            k_val_s, cp_val_s = sel_k_lbl.split(" ", 1)
            df_y_sub = df_yf_f[(df_yf_f["행사가"] == float(k_val_s)) & (df_yf_f["구분"].str.upper() == cp_val_s)].copy()
        else:
            df_y_sub = df_yf_f.sort_values("거래량", ascending=False).head(6).copy()
        for r_i, (_, ry) in enumerate(df_y_sub.sort_values("거래량", ascending=False).head(5).iterrows(), 1):
            sh_b = sh_s = 0
            if not df_tk_sh.empty and "행사가" in df_tk_sh.columns:
                m_sh = df_tk_sh[(df_tk_sh["행사가"].astype(float) == float(ry["행사가"])) & (df_tk_sh["구분"].astype(str).str.upper() == ry["구분"].upper())]
                if not m_sh.empty and "매수/매도" in m_sh.columns and "수량" in m_sh.columns:
                    sh_b = int(m_sh[m_sh["매수/매도"].astype(str).str.contains("BUY|ASK|매수", case=False, na=False)]["수량"].sum())
                    sh_s = int(m_sh[m_sh["매수/매도"].astype(str).str.contains("SELL|BID|매도", case=False, na=False)]["수량"].sum())
            v_q = int(ry["거래량"])
            unk_q = max(v_q - sh_b - sh_s, 0)
            oi_b = int(ry["OI"])
            v_oi = f"{round(v_q / max(oi_b, 1) * 100)}%" if oi_b > 0 else "-"
            gex_m = float(ry.get("GEX($M)", 0) or 0)
            cp_col = "#10b981" if ry["구분"] == "Call" else "#ef4444"
            _exp_s2 = str(ry["만기일"])[:10]
            _prev_q2 = prev_oi_map.get((_exp_s2, ry["구분"], float(ry["행사가"])))
            _st2, _st_c2 = _classify_pos_status(v_q, _prev_q2, oi_b, False)
            acc_rows.append(
                f"<tr style='border-bottom:1px solid #13283d; text-align:center;'>"
                f"<td style='padding:6px;'>{ry['만기일']}</td>"
                f"<td style='padding:6px;'><span style='color:{cp_col}; font-weight:700;'>{ry['행사가']:g} {ry['구분'].upper()}</span></td>"
                f"<td style='padding:6px; color:#10b981; font-weight:700;'>{sh_b:,}</td>"
                f"<td style='padding:6px;'>{sh_s:,}</td>"
                f"<td style='padding:6px; font-weight:700;'>{unk_q:,}</td>"
                f"<td style='padding:6px;'>{oi_b:,}</td>"
                f"<td style='padding:6px;'><span style='border:1px solid #b45309; padding:1px 6px; border-radius:4px; color:#fbbf24;'>#{r_i} {v_q:,}</span></td>"
                f"<td style='padding:6px;'>{v_oi}</td>"
                f"<td style='padding:6px; color:{_st_c2}; font-weight:700;'>{_st2}</td>"
                f"<td style='padding:6px;'><span style='border:1px solid #b45309; padding:1px 6px; border-radius:4px; color:#38bdf8;'>${gex_m:+.2f}M</span></td></tr>"
            )
    if acc_rows:
        _render_dark_table(
            f"{tk_f} · 행사가별 옵션 주문 ({sel_k_lbl})",
            "수신 계약 누적 · 표시 계약 내 순위",
            ["EXP ET", "계약", "BUY", "SELL", "미정", "기초 OI", "순위 / 수량", "V / OI", "OPEN / CLOSE 판정", "GEX · 1%"],
            acc_rows,
            f"Spot 기준: 무무 LV3 {f'${spot_live:,.2f}' if spot_live>0 else '-'}"
        )

    if not df_tk_sh.empty:
        df_sh_sub = df_tk_sh.copy()
        if sel_k_lbl != "전체 상위" and "행사가" in df_sh_sub.columns:
            k_val_s, cp_val_s = sel_k_lbl.split(" ", 1)
            m_sub = df_sh_sub[(df_sh_sub["행사가"].astype(float) == float(k_val_s)) & (df_sh_sub["구분"].astype(str).str.upper() == cp_val_s)]
            if not m_sub.empty:
                df_sh_sub = m_sub
        for _, rs in df_sh_sub.head(10).iterrows():
            t_s = str(rs.get("체결시간", rs.get("날짜", "-")))
            e_s = str(rs.get("만기일", "-"))[:10]
            k_str = f"{rs.get('행사가','-'):g} {str(rs.get('구분','')).upper()}" if isinstance(rs.get("행사가"), (int, float)) else f"{rs.get('행사가','-')} {str(rs.get('구분','')).upper()}"
            side_s = str(rs.get("매수/매도", "미정"))
            side_col = "#10b981" if any(w in side_s.upper() for w in ["BUY", "ASK", "매수"]) else ("#ef4444" if any(w in side_s.upper() for w in ["SELL", "BID", "매도"]) else "#94a3b8")
            qty_s = int(rs.get("수량", 0) or 0)
            oi_s = int(rs.get("OI", 0) or 0)
            qv_s = f"{round(qty_s / max(oi_s, 1) * 100, 1)}%" if oi_s > 0 else "-"
            oc_s = str(rs.get("비고", rs.get("OPEN/CLOSE", "미확정")))[:28]
            prem_v = float(rs.get("프리미엄", 0) or 0)
            one_c = round(prem_v / max(qty_s, 1)) if qty_s > 0 else 0
            detail_rows.append(
                f"<tr style='border-bottom:1px solid #13283d; text-align:center;'>"
                f"<td style='padding:6px;'>{t_s}</td>"
                f"<td style='padding:6px;'>{e_s}</td>"
                f"<td style='padding:6px; color:#10b981; font-weight:700;'>{k_str}</td>"
                f"<td style='padding:6px; color:{side_col}; font-weight:700;'>{side_s}</td>"
                f"<td style='padding:6px;'>{qty_s:,}</td>"
                f"<td style='padding:6px;'>{qv_s}</td>"
                f"<td style='padding:6px; color:#fbbf24;'>{oc_s}</td>"
                f"<td style='padding:6px;'><span style='border:1px solid #b45309; padding:1px 6px; border-radius:4px; color:#fbbf24;'>${one_c:,} / ${prem_v/1000:,.1f}K</span></td></tr>"
            )
    if detail_rows:
        _render_dark_table(
            f"{tk_f} · 주요 체결 · 시간순 (시트 플로우 기준)",
            "시트 수신 내역 시간순 정렬",
            ["체결 ET", "EXP ET", "거래 계약", "방향", "수량", "Q / V", "OPEN / CLOSE", "1계약 / PREM"],
            detail_rows
        )

    note_key = f"{tk_f}_{sel_k_lbl}"
    saved_notes = strike_notes.get(note_key, [])
    note_rows = []
    for sn in saved_notes:
        note_rows.append(
            f"<tr style='border-bottom:1px solid #13283d; text-align:center;'>"
            f"<td style='padding:6px;'>{sn.get('date','-')}</td>"
            f"<td style='padding:6px;'>{sn.get('exp','-')}</td>"
            f"<td style='padding:6px; color:#10b981; font-weight:700;'>{sel_k_lbl}</td>"
            f"<td style='padding:6px; color:#fbbf24;'>{sn.get('record','-')}</td>"
            f"<td style='padding:6px;'>{sn.get('ratio','-')}</td></tr>"
        )
    if tg_hits:
        for th in tg_hits[:3]:
            note_rows.append(
                f"<tr style='border-bottom:1px solid #13283d; text-align:center;'>"
                f"<td style='padding:6px;'>{str(th.get('date','-'))[:10]}</td>"
                f"<td style='padding:6px;'>텔레그램</td>"
                f"<td style='padding:6px; color:#38bdf8;'>{tk_f}</td>"
                f"<td style='padding:6px; text-align:left;'>{str(th.get('text',''))[:80]}</td>"
                f"<td style='padding:6px;'>TG 보관</td></tr>"
            )
    if note_rows:
        _render_dark_table(
            "과거 NOTE · BTO / STO 누적 기록",
            f"{tk_f} {sel_k_lbl} 과거 이력",
            ["발표일", "EXP / 출처", "계약", "당시 기록 (BTO / STO / 메모)", "기록 수량 / 기준 OI"],
            note_rows
        )

    with st.expander(f"📝 {tk_f} ({sel_k_lbl}) 과거 NOTE 추가하기", expanded=False):
        nc1, nc2, nc3 = st.columns([1.0, 2.0, 1.2])
        n_exp = nc1.text_input("만기일", "26-11-20", key="fn_exp")
        n_rec = nc2.text_input("당시 기록 (BTO / STO / 메모)", "BTO 1,500 / STO 0", key="fn_rec")
        n_rat = nc3.text_input("수량 / 기준 OI", "BTO 15.9% · OI 대비", key="fn_rat")
        if st.button("💾 과거 NOTE 저장", key="fn_save"):
            saved_notes.insert(0, {
                "date": pd.Timestamp.now(tz="Asia/Seoul").strftime("%m-%d"),
                "exp": n_exp.strip(),
                "record": n_rec.strip(),
                "ratio": n_rat.strip(),
            })
            strike_notes[note_key] = saved_notes
            save_json_file(STRIKE_NOTE_PATH, strike_notes)
            st.success("✅ 과거 NOTE가 저장되었습니다!")
            st.rerun()

    # =========================================================
    # [섹션 3] 🎯 자동 TP/SL 타점 계산기 · Max Pain · 레벨 근접 경보 · 반도체 커플링 · 감마 스퀴즈
    # =========================================================
    st.subheader("3️⃣ 실전 타점(TP/SL) · Max Pain · 반도체 커플링 · 감마 스퀴즈 스캐너")
    _mp_f = calc_max_pain(df_yf_f) if not df_yf_f.empty else None
    _tp1 = _cw_f if (not df_yf_f.empty and _cw_f > spot_live > 0) else (round(spot_live * 1.045, 2) if spot_live > 0 else 0.0)
    _tp2 = round(_tp1 * 1.04, 2) if _tp1 > 0 else 0.0
    _sl1 = _pw_f if (not df_yf_f.empty and 0 < _pw_f < spot_live) else (round(spot_live * 0.96, 2) if spot_live > 0 else 0.0)
    if spot_live > 0 and _sl1 < spot_live * 0.88:
        _sl1 = round(spot_live * 0.955, 2)
    _rr = round((_tp1 - spot_live) / max(spot_live - _sl1, 0.01), 2) if (spot_live > 0 and _tp1 > spot_live and spot_live > _sl1) else 1.5
    _mp_gap = f"{((_mp_f - spot_live) / spot_live * 100):+.1f}%" if (_mp_f and spot_live > 0) else "-"

    _tpsl_row = (
        f"<tr style='border-bottom:1px solid #13283d; text-align:center;'>"
        f"<td style='padding:8px; font-weight:800; color:#38bdf8;'>${spot_live:,.2f}</td>"
        f"<td style='padding:8px; font-weight:700; color:#fbbf24;'>{f'${_zg_f:g}' if (not df_yf_f.empty and _zg_f) else '-'}</td>"
        f"<td style='padding:8px; font-weight:700; color:#a855f7;'>{f'${_mp_f:g} ({_mp_gap})' if _mp_f else '-'}</td>"
        f"<td style='padding:8px; font-weight:700; color:#10b981;'>🎯 1차 ${ _tp1:,.2f}<br><span style='font-size:10px;'>({((_tp1-spot_live)/max(spot_live,1)*100):+.1f}%)</span></td>"
        f"<td style='padding:8px; font-weight:700; color:#34d399;'>🚀 2차 ${_tp2:,.2f}<br><span style='font-size:10px;'>({((_tp2-spot_live)/max(spot_live,1)*100):+.1f}%)</span></td>"
        f"<td style='padding:8px; font-weight:700; color:#ef4444;'>🛑 ${_sl1:,.2f}<br><span style='font-size:10px;'>({((_sl1-spot_live)/max(spot_live,1)*100):+.1f}%)</span></td>"
        f"<td style='padding:8px; font-weight:800; color:#f8fafc;'>1 : {_rr}</td></tr>"
    )
    _render_dark_table(
        f"🎯 {tk_f} · 자동 TP(익절) / SL(손절) 타점 & 만기 Max Pain",
        "Call Wall(1차 목표) · 1σ 확장(2차 목표) · Put Wall/Flip(손절 방어선) 기반 자동 산출",
        ["현재 진입 기준가", "Flip Gamma (분기점)", "Max Pain (자석)", "1차 익절 (TP1)", "2차 익절 (TP2)", "손절 방어선 (SL)", "손익비 (R/R)"],
        [_tpsl_row]
    )

    # ⚡ 핵심 레벨 ±0.5% 근접/돌파 시 실시간 경고 배너 & 텔레그램 발송
    _near_alerts = []
    if spot_live > 0 and not df_yf_f.empty:
        for _lnm, _lval in [("Flip Gamma", _zg_f), ("Call Wall", _cw_f), ("Put Wall", _pw_f), ("Max Pain", _mp_f)]:
            if _lval and abs(spot_live - float(_lval)) / spot_live <= 0.008:
                _near_alerts.append(f"⚡ {tk_f} 현재가(${spot_live:,.2f})가 {_lnm}(${float(_lval):g}) ±0.8% 이내 근접! ({lv3_bias})")
    if _near_alerts:
        st.warning("  \n".join(_near_alerts))
        if st.button("🚨 레벨 근접 경보 지금 텔레그램 발송", key="btn_lv_touch_tg"):
            send_telegram_msg(tg_token, tg_chat_id, "🚨 *[핵심 옵션 레벨 근접 경보]*\n" + "\n".join(_near_alerts))
            st.toast("✅ 레벨 근접 경보 전송 완료!")

    # 📊 SOXL ↔ SMH ↔ NVDA 반도체 3대장 실시간 커플링·괴리율 모니터
    with st.expander("📊 SOXL ↔ SMH(벤치마크) ↔ NVDA 반도체 커플링 · 3배 레버리지 괴리율 모니터", expanded=(tk_f in ("SOXL", "SMH", "NVDA", "AMD", "MU"))):
        _soxl_c = mm_q.get("SOXL", {}).get("chg")
        _smh_c = mm_q.get("SMH", {}).get("chg")
        _nvda_c = mm_q.get("NVDA", {}).get("chg")
        if _soxl_c is None or _smh_c is None or _nvda_c is None:
            try:
                import yfinance as _yf_s
                for _stk, _cur_v in [("SOXL", _soxl_c), ("SMH", _smh_c), ("NVDA", _nvda_c)]:
                    if _cur_v is None:
                        _h2 = _yf_s.Ticker(_stk).history(period="2d")
                        if len(_h2) >= 2:
                            _ch_v = round((float(_h2["Close"].iloc[-1]) - float(_h2["Close"].iloc[-2])) / float(_h2["Close"].iloc[-2]) * 100.0, 2)
                            if _stk == "SOXL": _soxl_c = _ch_v
                            elif _stk == "SMH": _smh_c = _ch_v
                            elif _stk == "NVDA": _nvda_c = _ch_v
            except Exception:
                pass
        _soxl_c = float(_soxl_c or 0.0)
        _smh_c = float(_smh_c or 0.0)
        _nvda_c = float(_nvda_c or 0.0)
        _theo_soxl = round(_smh_c * 3.0, 2)
        _spread_soxl = round(_soxl_c - _theo_soxl, 2)
        _sp_judge = "🟢 SOXL 상대 강세(오버슈팅)" if _spread_soxl > 0.35 else ("🔵 SOXL 덜 오름(언더슈팅·따라잡기 후보)" if _spread_soxl < -0.35 else "⚪ 3배 정배율 정상 연동")
        _semi_row = (
            f"<tr style='border-bottom:1px solid #13283d; text-align:center;'>"
            f"<td style='padding:7px; font-weight:700;'>{_smh_c:+.2f}%</td>"
            f"<td style='padding:7px; font-weight:700;'>{_nvda_c:+.2f}%</td>"
            f"<td style='padding:7px; color:#38bdf8; font-weight:700;'>{_theo_soxl:+.2f}%</td>"
            f"<td style='padding:7px; color:#fbbf24; font-weight:700;'>{_soxl_c:+.2f}%</td>"
            f"<td style='padding:7px; font-weight:700;'>{_spread_soxl:+.2f}%p</td>"
            f"<td style='padding:7px; font-weight:700;'>{_sp_judge}</td></tr>"
        )
        _render_dark_table(
            "반도체 3대장 커플링 모니터 (SMH 기준 3배 이론치 vs SOXL 실제 등락)",
            "벤치마크 ETF(SMH) · 대장주(NVDA) · 레버리지(SOXL) 실시간 비교",
            ["SMH 등락", "NVDA 등락", "SOXL 이론치 (SMH×3)", "SOXL 실제 등락", "괴리율 (실제-이론)", "커플링 판정"],
            [_semi_row]
        )

    # 🧲 주력 종목 만기 Max Pain & 감마 스퀴즈(Gamma Squeeze) 일괄 스캐너
    with st.expander("🧲 주력 7종목 감마 스퀴즈(Gamma Squeeze) & Max Pain 스캐너", expanded=False):
        if st.button("🔍 주력 종목(SOXL·NVDA·TSLA·SPY·QQQ·MU·AMD) 감마 스퀴즈 스캔 실행", key="btn_sqz_scan"):
            _sqz_rows = []
            for _stk_q in ["SOXL", "NVDA", "TSLA", "SPY", "QQQ", "MU", "AMD"]:
                _r_q, _sp_q, _ = _fetch_flow_chain(_stk_q)
                if not _r_q or _sp_q <= 0:
                    continue
                _df_q = pd.DataFrame(_r_q)
                _mp_q = calc_max_pain(_df_q)
                _zg_q = calc_zero_gamma(_df_q, _sp_q)
                _net_g_q = round(float(_df_q["GEX($M)"].sum()), 2)
                # 현재가 위 0%~+8% 구간의 콜 거래량/OI 비율
                _up_calls = _df_q[(_df_q["구분"] == "Call") & (_df_q["행사가"] >= _sp_q) & (_df_q["행사가"] <= _sp_q * 1.08)]
                if not _up_calls.empty:
                    _top_uc = _up_calls.sort_values("거래량", ascending=False).iloc[0]
                    _uc_k = float(_top_uc["행사가"])
                    _uc_v = int(_top_uc["거래량"])
                    _uc_oi = int(_top_uc["OI"])
                    _uc_voi = round(_uc_v / max(_uc_oi, 1) * 100)
                else:
                    _uc_k, _uc_v, _uc_oi, _uc_voi = 0.0, 0, 0, 0
                _sqz_tag = "🔥 스퀴즈 유력" if (_uc_voi >= 120 and _uc_v >= 2000) else ("⚡ 상방 매집" if _uc_voi >= 70 else "보통")
                _sqz_col = "#10b981" if "유력" in _sqz_tag else ("#fbbf24" if "매집" in _sqz_tag else "#94a3b8")
                _sqz_rows.append(
                    f"<tr style='border-bottom:1px solid #13283d; text-align:center;'>"
                    f"<td style='padding:6px; font-weight:800;'>{_stk_q}</td>"
                    f"<td style='padding:6px;'>${_sp_q:,.2f}</td>"
                    f"<td style='padding:6px; color:#a855f7; font-weight:700;'>{f'${_mp_q:g}' if _mp_q else '-'}</td>"
                    f"<td style='padding:6px; color:#fbbf24;'>{f'${_zg_q:g}' if _zg_q else '-'}</td>"
                    f"<td style='padding:6px;'>${_net_g_q:+.2f}M</td>"
                    f"<td style='padding:6px; color:#10b981; font-weight:700;'>{f'${_uc_k:g}C ({_uc_v:,} / OI {_uc_oi:,})' if _uc_k else '-'}</td>"
                    f"<td style='padding:6px; font-weight:700;'>{_uc_voi}%</td>"
                    f"<td style='padding:6px; color:{_sqz_col}; font-weight:800;'>{_sqz_tag}</td></tr>"
                )
            st.session_state["sqz_scan_html"] = _sqz_rows
        if st.session_state.get("sqz_scan_html"):
            _render_dark_table(
                "🧲 주력 종목 감마 스퀴즈 & Max Pain 비교표",
                "현재가 위 +8% 이내 최대 활성 콜(Vol/OI) 돌파 탄력 점검",
                ["종목", "현재가", "Max Pain", "Flip Gamma", "Net GEX", "상단 집중 콜(Vol/OI)", "V / OI", "스퀴즈 판정"],
                st.session_state["sqz_scan_html"]
            )

    act_c1, act_c2 = st.columns(2)
    if act_c1.button(f"🤖 {tk_f} AI 매매 시나리오 생성 (Gemini / Qwen)", use_container_width=True, key="btn_ai_flow_scen"):
        with st.spinner(f"{tk_f} 옵션 수급·감마 구조를 AI로 분석 중입니다..."):
            top_txt_ai = ""
            if not df_yf_f.empty:
                for _, _rt in df_top10.head(6).iterrows():
                    top_txt_ai += f"- {_rt['만기일']} {_rt['행사가']:g}{_rt['구분']}: Vol {int(_rt['거래량']):,}, OI {int(_rt['OI']):,}, GEX ${_rt['GEX($M)']:+.2f}M\n"
            prompt_s = (
                f"당신은 미국 주식 옵션 퀀트 트레이더입니다. 아래 {tk_f} 실시간 데이터를 보고 한국어로 핵심만 5줄 이내로 매매 시나리오(상방 타겟, 하방 지지선, 주의 구간, 신규/청산 해석)를 브리핑해 주세요.\n"
                f"- 현재가: ${spot_live:,.2f} ({lv3_bias}, Bid {b_qty:,} / Ask {a_qty:,})\n"
                f"- Call Wall: ${_cw_f if not df_yf_f.empty else '-'} / Put Wall: ${_pw_f if not df_yf_f.empty else '-'} / Flip Gamma: ${_zg_f if not df_yf_f.empty else '-'} / Net GEX: ${_tot_gex if not df_yf_f.empty else 0:+.2f}M\n"
                f"- 주요 행사가:\n{top_txt_ai}"
            )
            ok_ai, res_ai = run_ai_analysis(prompt_s)
            st.session_state["last_flow_ai_brief"] = res_ai
    if st.session_state.get("last_flow_ai_brief"):
        st.info(st.session_state["last_flow_ai_brief"])

    if act_c2.button(f"📩 {tk_f} 전체 상황 + 체결 텔레그램 전송", type="primary", use_container_width=True, key="flow_tg_send"):
        _tg_lines = [
            f"🎯 *[{tk_f} 전체 옵션 상황 · ΔOI · 동반 체결 리포트]*",
            f"• 무무 LV3 현재가: ${spot_live:,.2f}" + (f" ({qm['chg']:+.2f}%)" if qm.get("chg") is not None else "") + f" · {lv3_bias} (Bid {b_qty:,} / Ask {a_qty:,})",
        ]
        if not df_yf_f.empty:
            _tg_lines.extend([
                "",
                "📊 *전체 수급·감마 구조*",
                f"• 콜 거래량/OI: {_c_vol:,} / {_c_oi:,}",
                f"• 풋 거래량/OI: {_p_vol:,} / {_p_oi:,} (P/C Vol {_pc_vol} · OI {_pc_oi})",
                f"• 🟢Call Wall: ${_cw_f:g} | 🔴Put Wall: ${_pw_f:g} | 🟡Flip: {f'${_zg_f:g}' if _zg_f else '-'} | 🧲MaxPain: {f'${_mp_f:g}' if _mp_f else '-'}",
                f"• 🎯타점: TP1 ${_tp1:,.2f} / TP2 ${_tp2:,.2f} / SL ${_sl1:,.2f} (손익비 1:{_rr})",
                f"• 총 Net GEX: ${_tot_gex:+.2f}M ({_gex_regime})",
                "",
                "🔥 *활성 행사가 TOP 8 (이전OI → 최신OI · 판정)*",
            ])
            for _, _rt in df_top10.head(8).iterrows():
                _vq_t = int(_rt["거래량"]); _oi_t = int(_rt["OI"])
                _exp_t = str(_rt["만기일"])[:10]
                _prev_t = prev_oi_map.get((_exp_t, _rt["구분"], float(_rt["행사가"])))
                _doi_t = f" (Δ{_oi_t - _prev_t:+,})" if _prev_t is not None else ""
                _st_t, _ = _classify_pos_status(_vq_t, _prev_t, _oi_t, (float(_rt["행사가"]), str(_rt["구분"])) in _roll_strikes)
                _tg_lines.append(f"• {_exp_t[5:]} {_rt['행사가']:g}{_rt['구분'][0].upper()}: OI {_oi_t:,}{_doi_t} / Vol {_vq_t:,} · GEX ${_rt['GEX($M)']:+.2f}M [{_st_t}]")
        if st.session_state.get("last_flow_ai_brief"):
            _tg_lines.append("")
            _tg_lines.append(st.session_state["last_flow_ai_brief"])
        _tg_lines.append("\n🌐 OptionHub: http://132.226.3.145:8501")
        _full_tg = "\n".join(_tg_lines)
        if send_telegram_msg(tg_token, tg_chat_id, _full_tg[:4000])[0]:
            st.success("✅ 전체 리포트 텔레그램 전송 완료!")
        else:
            st.warning("⚠️ 텔레그램 설정을 확인해 주세요.")



def parse_insider_html_sections(h_raw):
    import html as _htmllib
    if not h_raw:
        return []
    h_clean = re.sub(r'<style[^>]*>.*?</style>', '', str(h_raw), flags=re.S | re.I)
    events = []
    for hm in re.finditer(r'role="heading"[^>]*>(.*?)</td>', h_clean, flags=re.S | re.I):
        t = re.sub(r'<[^>]+>', ' ', hm.group(1))
        t = _htmllib.unescape(re.sub(r'\s+', ' ', t)).strip()
        if t and "Dashboard Snapshots" not in t:
            events.append((hm.start(), "heading", t))
    for im in re.finditer(r'<img[^>]+src="(https://storage\.googleapis\.com/if-snapshots/[^"]+)"', h_clean, flags=re.I):
        url = im.group(1)
        if "_compressed" in url:
            continue
        events.append((im.start(), "img", url))
    for lm in re.finditer(r'<td[^>]*font-family:\s*Inter,Arial,sans-serif[^>]*>\s*(?:<h3[^>]*>(.*?)</h3>\s*)?(<ul.*?)</td>', h_clean, flags=re.S | re.I):
        sub_h = ""
        if lm.group(1):
            sub_h = _htmllib.unescape(re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', lm.group(1)))).strip()
        body_html = lm.group(2)
        txt = re.sub(r'<li[^>]*>', '\n• ', body_html, flags=re.I)
        txt = re.sub(r'<[^>]+>', ' ', txt)
        txt = _htmllib.unescape(txt)
        lines = [re.sub(r'\s+', ' ', ln).strip() for ln in txt.splitlines()]
        lines = [ln for ln in lines if ln and ln != '•']
        if sub_h:
            lines.insert(0, f"**{sub_h}**")
        if lines:
            events.append((lm.start(), "text", "\n".join(lines)))
    events.sort(key=lambda x: x[0])
    sections = []
    cur = None
    for _, kind, val in events:
        if kind == "heading":
            if cur and (cur["img"] or cur["en"]):
                sections.append(cur)
            cur = {"title": val, "img": "", "en": ""}
        elif kind == "img":
            if cur is None:
                cur = {"title": "Market Snapshot", "img": "", "en": ""}
            if not cur["img"]:
                cur["img"] = val
        elif kind == "text":
            if cur is None:
                cur = {"title": "Market Insights", "img": "", "en": ""}
            cur["en"] = (cur["en"] + "\n" + val).strip() if cur["en"] else val
    if cur and (cur["img"] or cur["en"]):
        sections.append(cur)
    return sections

def build_insider_section_gcal_events(mm, sc, idx, tr_val="", ko_val="", auto_ai=False):
    import hashlib as _hs
    _stitle = (sc.get("title") or f"Section {idx+1}").strip()
    _en_txt = (sc.get("en") or "").strip()
    _mail_title = mm.get("제목", "InsiderFinance")
    _m_date_m = re.search(r"(202\d-\d{2}-\d{2})", _mail_title + " " + str(mm.get("날짜", "")))
    _mail_date = _m_date_m.group(1) if _m_date_m else pd.Timestamp.now(tz="Asia/Seoul").strftime("%Y-%m-%d")

    if auto_ai and not ko_val and _en_txt:
        _pr_s = (
            f"다음 미국 옵션 뉴스레터 섹션('{_stitle}')을 한국어 트레이더 관점에서 2~3문장으로 핵심만 해석해 주세요.\n\n"
            + _en_txt[:2500]
        )
        _, _ko_gen = run_ai_analysis(_pr_s)
        ko_val = "📌 **Gemini 해석**: " + _ko_gen.strip()

    _ko_clean = re.sub(r"\*\*([^*]+)\*\*", r"\1", ko_val or "")
    _ko_clean = re.sub(r"^📌\s*[^:：]+[:：]\s*", "", _ko_clean).strip()
    _tr_clean = re.sub(r"\*\*([^*]+)\*\*", r"\1", tr_val or "").strip()

    _raw_dates = list(dict.fromkeys(re.findall(r"\b202[6-9]-\d{2}-\d{2}\b", _en_txt)))
    _future_dates = [d for d in _raw_dates if d > _mail_date]
    _target_dates = _future_dates if _future_dates else [_mail_date]

    _body_preview = (_tr_clean or _en_txt)[:1200]
    _desc_parts = []
    if _ko_clean:
        _desc_parts.append(f"📌 [Gemini AI 해석]\n{_ko_clean}")
    if _body_preview:
        _desc_parts.append(f"📊 [핵심 수급 · 번역 요약]\n{_body_preview}")
    _desc_parts.append(f"📬 출처: InsiderFinance ({_mail_title})")
    _full_desc = "\n\n".join(_desc_parts)

    _low_t = (_en_txt + " " + _tr_clean).lower()
    _cal_cat = "옵션 헷지 (풋)" if ("100% put" in _low_t or ("put flow" in _low_t and "call" not in _low_t)) else "옵션 만기 (콜/전략)"

    _created = []
    for _td in _target_dates:
        _eid = "ins_" + _hs.md5(f"{_mail_title}|{idx}|{_stitle}|{_td}".encode("utf-8")).hexdigest()[:12]
        _suffix = f" (만기 {_td[5:]})" if _td > _mail_date else ""
        _created.append({
            "id": _eid,
            "date": _td,
            "summary": f"[인사이더] {_stitle}{_suffix}",
            "description": _full_desc,
            "cal": _cal_cat,
        })
    return _created, ko_val

if nav_menu == "📬 인사이더 파이낸셜":
    st.title("📬 인사이더 파이낸셜 (InsiderFinance · 아침 메일 자동 피드)")
    st.caption("아침에 수신되는 InsiderFinance · MenthorQ · Barchart · SpotGamma 메일을 Oracle DB 및 서버 수신함에서 불러와 Gemini AI 한국어 요약과 함께 표시합니다.")

    INSIDER_MAIL_PATH = os.path.expanduser("~/.optionhub_insider_mails.json")
    ORDS_MAIL_URL = "https://g8aaf2fcbd18708-optionhub.adb.ap-tokyo-1.oraclecloudapps.com/ords/optionhub/insider/mail/"
    local_mails = load_json_file(INSIDER_MAIL_PATH, [])
    _seed_images_20261113 = [{'제목': '섹터별 옵션 플로우 (AI Market Insights)', 'url': 'https://storage.googleapis.com/if-snapshots/2026-11-13--ah_daily_equities_sector.png'}, {'제목': '주요 특징 체결 Top 10 (Noteworthy Trades)', 'url': 'https://storage.googleapis.com/if-snapshots/2026-11-13--ah_daily_equities_top_10.png'}, {'제목': 'Unusual Options Activity 그래프', 'url': 'https://storage.googleapis.com/if-snapshots/2026-11-13--ah_daily_unusual_graph.png'}, {'제목': 'Unusual Top #1: CIFR 체결', 'url': 'https://storage.googleapis.com/if-snapshots/2026-11-13--ah_top_tickers_unusual_1_trades.png'}, {'제목': 'Unusual Top #2: GNLX 체결', 'url': 'https://storage.googleapis.com/if-snapshots/2026-11-13--ah_top_tickers_unusual_2_trades.png'}, {'제목': 'Unusual Top #3: RDW 체결', 'url': 'https://storage.googleapis.com/if-snapshots/2026-11-13--ah_top_tickers_unusual_3_trades.png'}, {'제목': 'Sweep Options Activity 그래프', 'url': 'https://storage.googleapis.com/if-snapshots/2026-11-13--ah_daily_sweep_graph.png'}, {'제목': 'Sweep Top #1: VKTX 체결', 'url': 'https://storage.googleapis.com/if-snapshots/2026-11-13--ah_top_tickers_sweeps_1_trades.png'}, {'제목': 'Sweep Top #2: SNDK 체결', 'url': 'https://storage.googleapis.com/if-snapshots/2026-11-13--ah_top_tickers_sweeps_2_trades.png'}, {'제목': 'Sweep Top #3: CCC 체결', 'url': 'https://storage.googleapis.com/if-snapshots/2026-11-13--ah_top_tickers_sweeps_3_trades.png'}, {'제목': 'Momentum Options Activity 그래프', 'url': 'https://storage.googleapis.com/if-snapshots/2026-11-13--ah_daily_momentum_graph.png'}, {'제목': 'Momentum Top #1: NIO 체결', 'url': 'https://storage.googleapis.com/if-snapshots/2026-11-13--ah_top_tickers_momentum_1_trades.png'}, {'제목': 'Momentum Top #2: SO 체결', 'url': 'https://storage.googleapis.com/if-snapshots/2026-11-13--ah_top_tickers_momentum_2_trades.png'}, {'제목': 'Momentum Top #3: VKTX 체결', 'url': 'https://storage.googleapis.com/if-snapshots/2026-11-13--ah_top_tickers_momentum_3_trades.png'}, {'제목': 'Top 10 Moonshot Flows', 'url': 'https://storage.googleapis.com/if-snapshots/2026-11-13--ah_daily_moonshot_flow_trades.png'}, {'제목': 'Top 10 ETF Flows (SPX)', 'url': 'https://storage.googleapis.com/if-snapshots/2026-11-13--ah_daily_etfs_top_10.png'}, {'제목': 'Equities 5-Day Flow (Top 15)', 'url': 'https://storage.googleapis.com/if-snapshots/2026-11-13--ah_rolling_equity_summary_top_15.png'}, {'제목': 'ETF 5-Day Flow 요약', 'url': 'https://storage.googleapis.com/if-snapshots/2026-11-13--ah_rolling_etf_summary_compressed.png'}]
    _seed_html_b64_20261113 = "eNrtvclyI0nSJnieegovVmVWZlUA8BULM4L1g+C+kwDXnGyKA3AATvoC+gIQjEyR/9TdMpeRmTl1yy/V2cc59PkfmWM8Sr3A9COMqZk74A44dgdIkJbMiCAcgLuZmqqaLp+qff7j1mmhdHu2zTQcXWPOLjeP9gvMWiKVuhYKqdRWaYu52SsdHzFckmWKjqVWnFRq+2SNWWs4TnM9lWq328m2kDSteqp0kXqGu3DwNe/XhI2/k6w61bWNP3zGD3nWNcP+EnEDLpfLke+tkQ+tt76suZaxblcaii7bCV2tWKZt1pxExdTXW73PmaM+Z9ZqakXx/lnb+NxQ5OrGZ11xZAbGkFCeXBU9qGAajmI4iVKnqawxFfLqy5qjPDspGNNPTKUhW7bifHGdWiK7FnGLm8RlPlEw9absqGUteJf97S9Kta74XzJkXfmyVjMtXXYSVcVRKo5qGqGnakqzYRrKF8MMf6mlKu2maTmBD7fVqtP4UlVaaH4J/OIToxqqo8pawq7ImvIFrR66i6M6mrKx3VIM1agz22g8DM/y6QTHJTjhc4q8/dl2OprCOIgK3uQrtr3GKLpZt9Ra58saDOhPputopvnIyMxXpilXq+iG6+xPzG9McvvZUSxD1gqabNvoXTyedY5lvxt8+1P/x5sDV+ymbAxcrKGZD1x0qgOXqmoLjUBTDSXRUNR6w1ln/IE4chlmWUXvl02rqliIVTRNbtrKOuP/9hOj22Yi8PWE5WrofeVZrjhaB89Hqar4VklVlxE9v+KxJWz1BX2OZf6o6rBWsuH8FB5G+C10H0Pj6+Z901KAOxUL3aiq2k1N7qwzBmKD0MdhVA21qqzLmjbwxojhtlRbLaua6qCbou9XFWPEAJvPoTeD0+p76zdEwWontNSh9xNtpfyoOglgJnyLhFx9cG3HY4qEbg97S5etumoAY4V4TNXr6GnAgmjE60Cenxh8h6pSMS0ZRMm7CvdWkZRYTVPD1xO6iejGlNWKi/7AzWTvdoQLvO/5/DHIHGHewJ9KaIhJkYJhm07wqhW4iu7X8Hmj7VHYAOnXvJHLmlo31hlNqeFP//XnCjDwl7W6LqtaoqY+r/0ykiV+Yz6nsOBOJr/Mv+iIcWXmB11+JhpjnUmzaGF/RE9J1vXnxKOqaU30B7329Mw68xfmf2WFLe4vP/n8moCFT/ik0lXDv5drID0ZGCBwuMUmzB5B8SjXGdvU1GqYh8maIwmRXcf0/wl+wnuGwIcZET+DS6jwDLnyWLdM16jCwpnWOvMntsqxXK7/40K8Q+pjffwIceIR/cT4bwlloSaKobc8AUAUdxy0pw0Iof8+cBAaiDTkbcvTgsPed8xm/73xLKREBRPqGaQUBNEnGroUulGXRcuaWXkMvdXymBw9Y1LipSdanxE3yGDqx0ZXdjRZ2SmpmiPT6/EG3kSQ+FjaD38Bw8JGBhJST0nQAqpR1lwliSyalMBKfCabTeGP2ylPQO81tWzJVidlouGoaBNMpUW+JmUylSony7UsL0sCK6SR3k8+NJX6X34MjTUwCqLmK2YL7UOhj8wtJ+QTQ4ntvR1BrpGLzLHTrrIwepn5MevMj1xoIUovcTEKkI72bk2ZmDr8bEqOnfgBwrTklxYmZELfm8HNtaKAJTAw+qEKGglLTeFmVdDcIjU0F8Vi0qTLMAOZyRPSkzJxHHSKmuhoPswMW0lO4jI8GznCGv7vlbaESAsmG1rGEeObeRlzi1jG0fwqTb6MPLuA4Y1R+NwYKo5hUmmE1oEHzGsG8UPNWuS/83x5Vqrwi9RRUczN868ykZjNNl5YhADxy+TQUcwmLkaN8svVo7w07SJNMAducXMYqUQGTJfZ1Eh6mYp/6XybWf7sYl3wUXPL9nuKi/PRRg0jN4NqeO19aNBWnjJYNneszOIn5cz4ZT4b86On8z0FdjEMs+Tol8DF6+HyYwbIT+38CfwUhH5tagoLMjCkpRoYwioGDiInIk0xkSVaRFFDndiCGaMqBSEpCIPqikQQppOPzOgpZqad4sQa+7VC14vYpoTcLPtUHL61yMYRHu0LbA8IYTCyPY3hJ06880y/UOQB/KJZnjxGiElweWmQRmJMWbyZF0magYYxa0YxPcMYODHmrV3MvM2tJMpkErOL2b+XHlQTc9Nap3GGYkh6mI1XBGNOEEpEi47XhhKfsIbEJ2tyVqxFudr+J9L4v6hPWHJVde11Jts3Yu9tb+DswLtRuvInxkfoeAiveYKKc4kUP51RMGp5FhFPfd2IvSQuPVXGLnpK0mJkPDZbSUoPE94Ihd4nvBHuZZ/w8uxI6eWXL71jNhJpWdKbWQzCSZAWuI/23ZxMJLsAmeWX55WNWqOpTQQuPoeQILnYmAKRo9BiY52lESjWKSP/cwlfBPOlJ44Rd+GPETeZBs/oDzXbnPz+YlxxUEyHKDJIM8yAnWIG6bcfXRnF4ZnYTP1oeM0EgvwG41P8xCT0kOpDIekEWd3FN1uK3TQNW20pGHA/AMFGH9TNst0w2+gtf2sfMHggSVfTzPY6QeD3pU8greR/tR83HcbsD34brwgaYxeD3R2eamA4P7ke/oIu19UKnlrwCwS0XlFCJQXhZNkfE4mfVWQk6bb5C341Yf6M3A6jWtd8VCtoYjtZN826pshN1ca4VvRl/u81WVe1zpcioOeZXct0FPvxe+/iPnDk2o8/MXPc8zuejbrr9x4lvthtuQmPCE778x9/VoyqWvtl6Jw3mp+YBof+8OiPgP6InxhT+8S46I8GMtu1i3vlHomqUpNdjbAhuWu/bHtbFhnoOoNH+onJWypUDgR2My7dfO6r4OCSEhIEJJqJsqXIj0hM4Z8EXIER+M8uu0g6jQHEWd+DZXjip4aitRRHrcifbNmwE7aCFjliGOQC0d1+lUOo9KFsatWB0XLSYBUHQ8oxhs5C/sTI6+g+j0HCYWN/yL2CM4dKG6RCuJjmDumnSQjuPZYPPJbb4beErdkeC7vcFI8Vxj02JHdRrMaLUz1QjGmeXHbkY+WfnxNys4lUWFV2ZK+mzrTsX3qPV40GuqszuN8FmSTqQ4FRDH3bn83QD7S7jt/gB0KSEPUB0BhmAvaZRM20Eh3T7VUseTIS2pjQMzVTdrovAmZvzwVl+0u+wnsRGyg0Y2RNC+5jpHrsJ2/TQI81XfSNmvqsVKPKzLobMvtTxH5CtpNnXdtgPpvrp7hMc8usuDqyP4qK4yAmsvFbeQ09/OxkN4VfnaGnafaZYu0blcZGLv051X+NgUtD75eCJ06g2ImC+TqRevnpNw8sYhpah7ErlqIYjGxUg+ARgh35miSFfglAjMhoGayvox2f3/wvaGbd/NR9gYZmfx1RMxBtCY3zskIPgwK5r31hncjPwlgY+Wu/DTI4qN7N+uMQvyVtR648QghhllkFIDojZ9wfDws8lvkbExhDMBbV5yj99tu6ZZoOYYwELj1GgqKB8DBV2Xr8ibHdJnxY8SIi3mfs0IemYJjuqFzdeCXioCeH6AMjCVniAzTywVNNS6kplp0IUwtIgGZWttCUE3IFGLEraOmyIuVESnFKcUpxSnFKcUpxSvFVoTj2C362TA1Z0mj8NhodtpLXfmHmM/BGUnuip4btu5FLMOp+ZcdItC25+bXdUB0lQXo9eNGOqW6C3/86ZL4TckHTUpGh2kmg+33t5eEiOaHni8vwMxLQMMhGSRs5PEbVf1Y3bCLCz3T3YkIDHYxkUyXx3pREtz1ImuUwxSuOnHCqIb8XR/vD1IFPAbP5LWBI0oIb0aBmANYWjjSKQ4g4AY9EjHhwOXWzrGpKoo6Uw3A2innpXl0FVHn4mUcFDI6GMiRlSMqQlCEpQ74WQ1IjiRpJVAXQPYkyJGVIypCUISlD0uAnDX7S4Ce16+muRXctakZRhqQMSRmSMiQNflIjiVKcUpxSnFL8tSjeLStJkQO+cKlnuY6/8WXNa0awhkmCXhKfew32/kd4ias61piO3DDNL2tw4A6Db/dlbWhjg8gK18Ha3p/WNhgmVOsCL3tlJ3/4X8KFlfiz6Dr5Uuij6BIp6IQyTYi6oOd8WWPX8Gvvufg12VvxrxHBF8Y7XKj/DJ81wmNf1oCPJpl/gO1+gvPFLPSnuhHTIL2xZFj0PmbhL2ukUKU7fjhRqDvMyFIkb4AZlqyDN0Kv+wn6jtns3YxLqBPMeS3m6RFSD5mfMOH8wgvQ/bo40YwmqDgdrPHskSE0j/lo4k2gEb5n5GJJiUp3alGnaq0tggv9h6dnZDv/+1DEP6QAuHvfSUt5f5qnYBioBAfs+Q/tqyHsqwYcLP/rqw8M3h40YV9V7dpGQXYqDcZtom2Rccyq3Pn+T0LuJxvqwR4VB9223sAa3f7EPCodxmzCGthQy9j+hLfPdkN20DeZNr4R0rmmZZntJFL9aBYbn5v+RPwCM9i3oFUjGx4cP1gsnQ4OmHgrUUVymGQy46D7K2gbuS9rsvGIOEfRoNbdbCqGYgEPwq5ogSg30K9fuhXqklJW20krKSeryFFCar2sc7hKXX9M6VbKbqQ4J52/sqv8zY6xv7tf1Eu7lnu2ebTrPJV56SWVsA42n7bcR1V3trq8EjnsYGkiknrFgvmi4V+pSptRDWYTEc5WrM8peYP59vuv335f1LwqWqrmz6wmnqq79ladVZvZ69LphSJv3eo7DUN3UsL5TsmoHnKVvbawNnogM02csdXyPez292oVS7uj6E04FBD0gNGjy5Zqo+9XX4Mu29mjC+7WbV4em097p3mxfnP5nGIvj6vyVuFZfq5JMUycG5j4LpK8HWSgMidK29YUxyFM8TnVHFYRy0xq3EKD9P4y13AfvogGP78xoUpXJlxe2utYMcxCHmUEj32cdxikf/DkYC+P3/rGIwdGNK7edbDcFfprdO1Wsl+NtRX6N7D+DS6wofl7/+gDTkOHWPpl36EzLNHF3i4WbatAOrAZEM1uOI71dGuv/0Vvb37Lc/Un1s+/a8GtPMA5XSMO/KxBMuCVZxe4fUSoE7me23o52JT3XtJHWzdObW+LS7Vky7h8eqm76UpmWjU7uvS9T9HwA4qG+QzCZVuV/gnBCYcDU1J1mI14vmUqz4/XNfNZSjaN+t/dL9fO1bamPmTPDu52K2flqy2+fm2xbFkoPainRb4KCwEnLhs2skysHdWQjYoSYhWfxbI9tgn27uk/g8+bGRqlt3Vs4M3hc4r4OgPMAHqhyw04Yj2UHfrD0n1WCc9326n4Bh225D4xwSYZYc96qSy2I7DW+Vnjpr6VOz7jW6rCtqRU/qBw1s7sd6zTx71ZWcyru+8dxzgh1wkRXBe0cAdohXe+kmlqtmdEMmRxl0bBq6O7ypPk6NmDStE+uKk8VnMp8zz/WDt/3uw8bT8um4LiTBQsmK5lK300JAKSgn0jhXXsxsSXGhN8amlueC7g743wo1/tHNfQo5umrZLVRQ5z6B1LaSqkJ4z367BDX/sbxswQeoAjWQdZM8pDHdbLKuoEv/6ecYIUvOZ1igtf7J7I+hohC3JYTiDExC05bBFia2KYdMfCzxZc6pOR6FCaMEGEYwHxjKiWYhEdKQfPjB3q6lfV1sbnBufPrL912Fp/wIEdH6eZu8cYWougQg7d5y/YiGXqpH3XX6IohRuGrW1stxQDTYHZrtYVxg+gjFD0zIzP4Vk+nUCMzwn+Q1INDv0FlGWWqtbfA/+/O8Yf324uBpbHLevQPdSNkoXH/zmlbozkeUnJZGvT83zvQQz4HxDKDD5qDOe/MbNnzuwDNyb94Buqs6QfIttVR/S2/XB5Cm96UyYq+lYwWqdJk1p049asdzBo5GmgC12zAHtCJ+g3kYWZgZlpkHC2uYKZhWSgDB50sSFb4PpX5c5f7EDwexKKhOH7rLCzzQ0cGMHxUcm/LsZi0EsYiBGlSYwIKO0zg6w53TcWQqLpxxveI0P7ub9HhuNVIT2YZcNRMH4wN8cTCwcvTsIb9TqTYJN8MGe3g//ris16JOUw0YYt/GBELzD5cDhv3NJFP5vpK5cBccCrGAKHfG6tY86ylIrDPOuaYa+3vqy5lrGOYS+yndDVimXaZs1BQ9PXW7rWH4Jqt9tJlcQ/ayT+mVTNlA3zThnd+f7di/MoX3rXvtdVyzKtLwtJWH5vm65VCT2uIutNGUjZVpRHrXNfVeuK7YCgVoAfvqxlMRDFMh8VH8hDFnoNbWGa5l8jItgfzRUw47RIl3dEhQZiFLJi3VxR1ter7XXyAQj4Qn9ZL1MU2u+6PBZk+aBuj+BzzNUktBvke2B7YEVE0m+/O+a33+Vvv4Ntqljffv/nP/4NsSIZABh/AX7YCMOBBjuyM/jy7MHL1eecfihDMCkX3GCYPsA4XiK/pTJE58mpE901HzzLa8QmP4wRmEFOIBpwSOPzfuUW3HccCz2iiRbGcMawkkw4Jcw6k0ViPQb7oe4ooJ6Y3I+//rC//eMv3g1CHw7xZtTNorPJEyMlg3WMM6SBe/cblSEeOCnrt2Hlk900MbbQsoOJXWYCkCS6ifwziOB/AFda1Rxzfa3Xstxb94EbE7wkMx9gMpB5jjMqP+ciJ20ZjqFw5G5BB0mV9Z+4OnzJfuvPqC/QVZ7et+oBUjlekHhxlIdMPhGVWACVJluJOmgjNJQf0EOqSv0T+oooCrzCsN996p6mncl+92NA2+GzUvi0Z5vGTiA/uDUqNDCFDYx9iqraijQ2wxp3rxs8Hap8uSG4r5A+zoA+7rc2uWQIIObHhzAXYkVcQ/78OuOCe1ORbQBabWpolsyOpSI7k/n278y2UbWZLaXCiCQEFJxWsM24MLCzDBjV006cj0gt5yabODKzhUgsX1FBUt5QMDgP3bqlJKPzhLWqks7Kw2xfEWlis1ZDyqDDIHVudKF8U5JoalaIoAgbnGclV1GqWTTCP4sSkmjLdhgdfb3xifkzx2W8K0+ubIGVaFrMn4Vc2rvaQaLZR4zoyRfMqsJ8Lg9QzCfx5k7hWGQ/p8obfWTBW2+EPDG+8pzaX8E/RBiixxo+rGFRLkrTUoHt/u46+r1n8pUtpWV+DxdgC3H1Lwrsk/hC1wTsmYUJoMBI94HwY9h96FPFHkeI4lj3IecBfMPeQ7TzEBX+Hu01SNFeQ0GTVZ3xJeef//H/7DoLYV8hZI5FegoLRjlkjKtLTs7zRl1wd3h5P79VsguKm8udl/NW5iF1VrHOXPOicntaqI8z3HvWOgfWenqIte5rmymt9QkUhjREYQza8v35jmGHGkXJWR+GKh0GY3T6Fv97o2w3f/r+T1lI0GHQZv9ZVQNGesSVVUko8GMqNHiW5/lyTAkFfjAGy9OEAk0ojEgo5N5uQmEw98tJNKHwVufab9a5ev8IyRS8ZLyf1lBasHdzcwbmg6fKhbhVwJsojDxwOWG5cMqf8ixXHK0T5VD074bD4vjj4/YlC/Y1o+6Z1h6VgkWma0NBihDl74ETh4X5MaGjLWciShNH+luKBeaE5iMryNdfOwMAdnLQtg6EU0cb2ATafE88i+G2NSF3n22N+zYMhObH29aZqULzfiXM/KH5NAnNH+OatG+/A+e8bkx+OlNbMrbvpHJWVw93uK3nA0N6Los7qfqx8aIfPXbuHxK7McXIuZ7V7UPE+qzu9Dwx8oGmLH3KJR1ULkProIipHdFIZMDUzgzinqNYYNJYeqyB8552YH5l9rd/8aKsG+GSfebr2EKk6Ph3L2A6/jTE1F+ZY9zAhsGPBnX81xQzSwwfj/hVwvgR7Q7QSILmUVQ0H818CzEEo0PUxnCrdcVmfsjDkaOIUVQtda2UD1UH3fjUdTTTfAQR/TFAnDFpgFC3hF4GIKItzm9eyuCvX9aiVXwwgxDReOetZxBWxh/ll+2PUueTOp/RzicvvF3nk5+GXMvyUud0LBc7puHJLmI5jTx9PRyjFCdw2iIDloGuQUHnDP3gDCJxqF2tx1u2d+Z7oAIJCSfsTwOrr+jo239gmM+aOkBgwbv5//xv/9d/RqYGuqgwP8QPaUHe2SMyVSF7lTo+3ZrJK8KX7oFa0xXpRW3q/ZZrt4A/+CnEIeUNNFpICWFT9EemIVeZB1dvKlUGUsLI/uJz30EfA7kGbnYD6vIAKoId55oJJ2jDb5YC97SZoqzbLnrdlm34kiNrjzY02JArT65qkQwfsmOQ39z5xDQt9BuYx/iGioU/ie5kqRXFX6qaaTH5fQYfwu45alVEJ6OajH8NYaFSNplBQsfPT+CBE/5L4NkkwGXy38VAJjvhNldlvS+Q480UHdPqMP/8x38nfRk0dQLZ+d+Yy2QxiSzTimViJoHD4w3GRuuPKI1TmYhX0IpW3QriE7KGyIBpgyHQAPteNgxX1tALpOAgq4b4o6bhwaLJ6lALX2UUTWnJyEgk3Vl8rrBl5BQC5yBao50IMZCrVdELdAMTERwpnibym2WvuQtiGCh8VA1XgQ/ZDhqKo7YUZge9biIHs9JZFO+4dqLZVBNmxTHL4LfiadkJf1bvnkn+M7Mntx+3OwojpNlFa9m9/PXhCqlZGG6fniVKE3MptIhhzgX0W0tBjMuYNebPUi4pMGiz1kBEQB7wd2TVRt+AKrjuh+uuWgUKgfr8M89L/pcS6EXGf/GJqahY1+4X8/huKihTAw8bieVilWoDsYXSURKILRJoV4FCQRuZaTbSr3hbIQRIPAnvXUT+678yBcVSkG+O9sqO7Si6HWaFP/MC1110tIMaaBl38/kzpNMspbvisH4eJ5yL+FXN1bQEIEXIB7ssgenL2IhMsPYyc+xHepFlarpVtO4QOZNhUy6rhBuQxfeoIGWOuKlsmrbj6WHCMEif4ueRXloYrbMopql4hOpxjKbWnIRJwiEe5+BZJGwXPf19884//+t/+f/+n/+dgQCRipb9GG0oYLvbi1az+eN8aYXULAx3nJoVQ2qWY5Mix5QDetb7XFf0ts+K+JNikksTywTEC92wptoVpDvPOdDHme5dwXAGWFeyd1v0f34/UWmozQVrWpnwR0L3+aMnPcgDTiDxVeEtO4GnkIAWeYr13iXnd5CcnuZbtPtX3FkliYHh9kmMzJyYrSTD8eBxy3Vw22QHQuuW2wRB8iLSn5iSgrwlLBE96gppybP4e9fQJNC0GdcgprpSRduLa8gtNF8c9LAVqwWWPtypKbuwr1WVpmZ2dOTy2YuSlV7W099TyHQT3kyRyCB/10aDslddQj6nXG2+DjrvPfg+prqcgN/HNB+gYLA3E4/PRsTjZ1ozCgajYDAKBnv3YLD8/iwwMILo6PVmsd3mRAQanXYRJykrKptadRAXhgYA2izUrI/0kNncLuU/p9D7GxS3BmY6xa1Nhls7UlvKt993EMVWCbWWqW9Lsps5aut7JzfaZU5+PGK1lPSynxDPG5l6O31FUWtRqLXsIGptkAEoZo1i1t4yZg3U++ti1vqdS+xYRdd6R1WWTemwsAOagh3fBmoG4IxnBJBOsJH9t20H6Zy6kqybZl1T5KZqk97btYRtIIu1YTp2qtfAMZGQG/dVxDede+XJVR1Vse9ttJeYFrTm7lql6XSkWdzXVDvkHUbV662NXKH0ivhXFO9E8U4e3mlUzBtC4mCTGvUN5NnYCjKUTaPqgmzZ6KXCoMWx0SNBz1bNNlahTEOp1nGWEFmgzElLBY3tuJZuqhooOXw3uPGcKK3R0frPir7h7R7rn1PoBbOpIBfUbjA/SCmJKTqWYtSdxo9+5H/83YoQ0/XutW0D16G7KWhn3sHl9VuKg0PSDFFMbEJiOH6dl5iz4ykect3oeI/wCNeQbaZqmU1AUiGjqw7wmJpac8AugKYOQHlojo0uthS0l3RI9BuNpWEgfqojIwKrwtCpReSUI0ZFa+gg34KxH5U2ur9jMk0XTjlqq04DLaPc6njD+ESC8MQUQd4q8uK17jqjy0jJNADKY8F2BkSAz2loob2XiEEQxySZa7ixzBS2T5lKQzbqyif07boJd0H8VYeJ4O0XLB8X2Y4dfCM/9cQYSCIYaKz0CVnZaOiOS+YESkIG+JAFSK8KDvyjUTXBT6443t1x1kx5RgzmYgSZDIChsqtqGIMm1+tId9hARLeJ2bisOHaymxiCwPcfvCD4ZAJzocgaoyBGQWar7dbAXkEPNDClQU/hYWBKo3E7dciPXGzvl2AJvOTex5EWtI3z84lLkNqIr2UdmA/AXm20nQLagIiBTVj/E9ZWPjTRaZtdWSIpJ1/SENspTofIVlfaaozqIKEEg4Oc/oU7fXUFDK2tjvx+5BE5GLwIIpVE44PW9mjC+d2TAqMQyw8CcBZecGx8ENG1IQnYCcDaALTIPCpKk7EwLykGLDqMCOkFxXLIKEJMBAcAIUFAJGki4XIwmq2rn32xMI152Ltg6rprqBUyRsi8qRVkxtdk+JvojoEdAVFDV+oyU5GbjCHr+GCG98HhumLhGQ5lb4ER5+DuIcQO6XTE9aA/2w1F09GtCIwSL3RL8bkeqxu5jEhJWLAT5GrC0T77Ak/Jmg7AHRmUvelagXc9vmbQ7rR7err7Cf99hL90srlfRM+wTavMaBClQdoM8W6XGQirJ4HkIKPYZEe7FLyFbHHHUstYq2Pcb0Pxt68uTNMmV5FVhLgbJ5TDWwHodkvVgQQ9bY+3I7mDTDV0NbAvAWMqIKVo6+tyJkG0KQ5WHQZS1POIybaBOINIqIu8UqwYHLT3dp1CvFH1rKi6YgK4FEc7PXxdF96q2o+vKjCupmGBEZe3JcwhMx7lPfQsU8ehFJMwFVg/vuomQkGYPyRQVVMHKBsaUbmDGAO5C8CTN6fHodXUcCyXKRQOGMDtgETo0DYKWUQQVVV6tjKwVG9zTzKnnuWzj+4EFpJNGBhvAW4Z+SNGFwgd4AK8ESBvGKDjTg8qjb7oOJZMpF22fc6W6zB5tAG4Fh4P3kGQOBFgNbLYQBTnYO89tO06jQpInWoYZksms8VWpTegoLx5ppXPo7jl/cdi6HlsnACxQ4wKCsUOGPGEV7FXQCwgMJi7p5gSfsY6GfYBpPjhQ8heUjqM7mqOijuFMYXb0iG+U3C1cAWHQXi7rdoKMqqRa4IsKLmpII1OVHUbq3KI7zVNE7FBpeKi+3pbF1F7RImjz8lDVHjXLgfmQfNAroX6gr7fs99NJFMaZHSaalMBr9ruyh+6d4cIAHqEatodowIh7Aq6mQ2SAsBUZv/0pEhEHxtokTIwI9qFJt1p0p0m3d960v0ETRhJlNPoMLgvMU2707Q7Tbu/ibR77m6rkt6SWpvbBw/WnXIt3YjPe6njpnqe1o7S9d1yjqbdo9LuOZp2p2l3mnanaffXSrujW99zLE2707Q7TbvHk3b/OZBBENa5HHN2/Mti684286tRpRQypcCfCpcwbeaxqcMLLHN2WcKVlQlERYn5F+bPApvMHTM/lMwmc+YtFxyFsAmq6MflRiT38dna3QAfxKxmTUj1AoWlhmqTCJ+XRCHRPVxdumkqYPJ0k444lgypSpIW8mhj1nqJIAe05TMDq9ct3v7EkBHgpiwkjI4ehfzCSsPPqkLocDPvV3i3wEhRMJyhrOAbeYnRXRWidoTk4VihCv9XXUgJQW7X22NIlr9smXJV63xCs0NTBWPFC+vJyLx6MC0SdG4grsDBc9vFmZ9wNBDyKRAQb+A4qUwim65jEfNAtUiOFD0aAxvmiZL3CXFm8UIM6bh3IcYwESzIYjZCkPl0UogQ5GJTU533IMj5LhLBm+oQoQYqYZGum0hC3CZEwWUkiID0aXYD+IyNTV+QzbLZgoY3iBQYwRMWbQjy4xRZuwFuUC8JTB7jp4AD6IYSGg6WOAz0wZ5TVWkCJsit13GvBwaWtIZcbdOLzPuZqSYyISDGX+2mW0MwgW4yFs2oEp0F9zLITSTiSI1BQyFfnQTzyXHJL7cusYuX3+OLq6N3Ib8wESy/nCgNyi+XS7LvWX7xRoxmeUzE1EfO9TZf3BMFcrf+romhRo6qY3RHQCo9RB2AhJB4dMEUXYkeSOVhIQaQDbTKspVhKKUI1AiW6H0HqQdEkSpJ1TVl4D0Dg5+Cubru1prfJ7k5JMd9MFEZxBsP1oM0duv8jdDuizxOL8UIYAzY5LFGwSlI2KrjEuDcuiAx+YUL8OX7EN9LLLxpKbD5CgnkhiDhzSXTSHaLiLGab0BWxXll9cLfafG8EKMjaUXWLBFcwq5ABgx7wmILImbD7LH8ViC5DObwsF0V+hVqCnSiwG9ixoekPGxWYLkeXwaQeTgB7hDrFiTXg85640AbvA9dHA0DtgMZ+ZBYdiF5vVZ5g5Y0Ghj6sGvB3ix3CLKgyeB922tfI1vV7kYuQ28atHHr0DWi6WoaRKxj23VZ8H0XLrWl4tH78H5hIlhyBb4ruYiWPCIntpux6F4arg29FNGOuwueksG8G2HOe3Osk3lhMQV53VIqil5GXAIEwsTpyTMWY6eNBgOgefBKI/bhT5A1IOd9wJbrMz/GJDpoe/7nv/4Xm+xZPfiYt/VirA42jU0XYmdVta46XYHFcgWWtIxt4hokKFSweQ0fGkjAmx6mEu+NYA94qJwIdK+3k+JWm/BYr2EqYzeVilpDDjDM0YlwgwPNNaEXlYV+820LZDZAtx14aNlDTwXgQTFKO7uEPfqs8D58ZDQPYmJLTCF/dNSVdQHLOpfk32Ks6yyAKptf3j1DG6YKpIebIqoARbAsEmNb6WL0wDsOecZYVDDuTQHcMziskCWzI01rsmF/IsFzeJQnmQMmNpFignCzfUcaDAALGiNimB6ytA0ctMIdIAhwsia3TGxUVxFrG1CTYiOn3AluzlVFU5EaAzTnIKaS2P6kpW5ZcWQGGesauMhBKSfVOojZdawQvKAbxcFRHBzFwX0oHNypp67ONOQ1UAzcamDgvD0mgfcY9F1ZwxrctCgwbjJg3PZzE91Y+fY7MjvQLlpXlVU6Tq1my4/bu8pD4WLHqe0cdaoXF7l8I1V+am3LD0+Hh+0rgSLkIhByAjuIkBvBCRQqR6FybxkqN3QXeFv4OYrOouis94nOij08NVSiIVADu1MnVVZkK9F00YzQwsrV1MnV1vuIWcNEcFU+c+Y6TBHPjrSeXuUmAWTVvNtd2pBXgRXEOWCyghCuwXPHYSQSXLJJ9/9ezAn3QXluqpaq2D4ABLdD4RNpHHiySe4JdxbpRYNxXAuX8uMDPLqdVEibC6glxmCwQM3/FUZeoIUiRykhS6RlgrmEA0i6grumgE/UK5mcqqsNzBNAYDVZ05DhMKylDZphL5NFBjuy6YbfASFUsy3bj6SvAGlVABmrQDrA/uSlyHT0ve3SjhdZKx7v4evF05sjD0yiIi0HK9aLrPsl3IB7gWY2iOjQkMDxj37oNqrB6YAu1XHttg1pdoWk5gM5ugCVezk5ZAPi8DzaN/Fq9PL+fmrOxjoVMoKkaQ+Qob+YNqYI/VtQdu8K1/ZmlZ0Yi7IrmGTFozUeJoALwtCv6nwNiBm6q/N8TcElBHJOnI0D80i9AXCEKDq4BxwWh2PnweYziqdDNCTKOP1ekS2rA8qtm7hDX1QB7QLfaSOtM5N6g0lhkff1EhTG97pt9WcASLetvsp8GbB+HmAIQI9NPMtArgKrczQMD51aQ+xClE2ok5AdSv4Pgc6R9gGPSIhwyx5QrmXCBCQTCagFFzk9VW8xAkg70pYIFCTQMwJw5+9S4JI3P/lIQHtQPWEYAenB5SEJMMwRH9EIKYv+zkG9/iykVxOcQ4OJkt9Holx3A+1SSK8V2EygK9iqKT/I8cIbWqpQOHgXWg+6pBwBoxTQrF5d3c3d/iPCtuth1hDXwXRJbtCBpivDwXq+yiNdUnomnafhENfDXo9UACRQAQ3vd5/xkn/e0ZiViuIdhAopRzhVFJkbbWx6eHaArYJfiPSeQrrjQOSXNM8gmX5lJrUH8/TbncnIcLN0//4E9PTsdZ7qKVtkr3T7kzRl29Nfwwy7sFUHB2vhVklBbAcmOZ42iSbb2F4MQTeSkZ12cLO1YX12VKOl2H4DHxz/6nXegaCiEuzPRFrufGJ0GX/SW5qApYao468bmg/u2YN8eti9PHiVb77jebRUpb3CGuu2dPg+VBb0wXmvOqtronXVFuZSPGdim41DQSAZMzDs0UEspHQtM68Zp6e/dNWyTCu48yMVdrSdPyuSwYbAC32WGoSPmDouEoKTJZHVVlbBD2uEQcFTqSs0PeKYYUNsXAPHGrJOiWIeoAGm2CevG11X8dZcMCRB4yJ7ScH1Ft26JiApbrL0hKwecMk9NdFtbIRVaCOirVaS2YSiJ0CN9t4F+6tnbeIgAbHRgpVUn/xYrur1xOw1XsKgT/R/Ew0GpoYsOtf2XH/k7so9cAw54o9YVb2WS2HcGLCCWasRON3KuZpw9CksqO9rviN4GNYbWIG9FVdzEbYXrCAxBHpuJkw+FFeTcYaQbP7hcqiKi/gJ2RUYJ2J7nifxPSKcT1B5eHEDx4R38VpAL+TA1OC8M2hnTHQaMuNwuA3LELLBCCwLnFuMHSedBO2G2pxJq11279aQWwqpsuy1wS1jzu2hTb3R+aclIjKF/FY/nhaJWfvk2Vi+PVZDRksj7KOSDF8QcOtH+Mgmg31YslakV6yngz3MnIeKI3A4OPUZeGXH6ys90CAXEr/QI/sT0Wl+rcpwj5NsbcAauE4ugJQjcYGW0lCRYdY15XRFtjEMftCm63VdjBU6t5oHJkYceOhn6cZn7SLSRRMf3zfkVEICOQkc58e9n5MJpYiTCaci7ts6mZDPUHDo0sChbxcMGikWE084CGoKoYGETWFHHIQucTzpLDMEVjpIKI6klweBgv4b8eCgstMkxkX4iUiMwxL6TagJxAkbAvvENt4htjHatU2tbD53bcERmEqm7BgJAB/0Iyv7qZQdQiTv+jDkpKd4Pewqeha+EK1fY2U6T+3yfDbEDh6XC0JSEHr7H9A2SoLSMDlPcpaDAa3Lui4nfMdxJleFYMfuPSYAACh538SVGl/qynMAEMrxEyFC/WvTIkIz/DSAUA/fNz0gVOjHGGYIIHR3++bb7//81/93iQBQj9UR1ROI3SGtgvRXB36fDxzqlh4eteeGVmu0ubt89qW95WS2Ug/tk0rR3nm5ySeekGOqOkDNXeAhgECS4MMPiAo/+nB5uQwjP4UQavTHhrTyCmoiQsoRaNPsdGDT7IxgU2FQyQ4wQhiO7zPYJGBTf7CRmq0PgcoNIlADrDcCcboCGmnmzqxj9BBuCTi1IiKb/qIVkb//zq+IPGS616vzNTWRrUCheCy6qH38sLe3Wz90c50Tu3NwfMFWhYfUQeGK1UuVrfv9ymFXF+14q9yne8jl96ZrQsD2kA03Rtf4puwkuoYf1DVB7opR2axs6csYzdPUPozeOfv+6P2onQ7yb/Q7xc1W2MeCXlJbxgm7kxLLB9fN2kNbl0Suq3a69W+YnyBI7oPoB3XRiM9SBTWDghIGFVSADSctv1l0RU50cczkZTD4Nj9HuLG/BOpSZqiOGV0CM9FTQ6Ux48piRt3Rjw18Da07CatOeRv8/tdhk4balQmLbAIOFXoZYNKoTFvIrwy904scDK3RSYZUV6/2hsjNdHcLjpPI0jJrd6ZLPLxKlmGK0Hk3uiwGouURWQpO4jI8O3Xr7uh4MT9YK8QvOpA+JAESShlI7yf5kY1Ifsy0Zm8j+UE7Y9DOGLQzxgI7Y/idzuZoj5GHJL/qdGjvCXr+0ns/f4nNqod7drV0Igrpa1mRzuV0W0vd75zXduvZk4dO4ZB2l4jqLiHS85doUwl6/hI9f2nJ5y+5xLy5ryNDoEFPX6L9PT5Cf4+GEBorscNy/aPgkrzUNUcwAIlJRyFA+p0L4lqsbfiew2npmPlu/XOqIWz8YV6w/EhMNz1Vou/giAST4b/rYqtfi3T5Yqm4KqSDsXqkE7KvT7rC/s7FqpAOxvqGSHdcLK0M6WCsb4l0lytDuEufbJnXJ9vW9tHKbBEw1jdEut2To5tVIR2M1Sed+PqkW51zNwJHa7wN0hXPCturQjoYq0864Q3YdLsrY9Ht+mTjvvsohYV8ds6cf266nP9MxXPROf8pAw0UHPCWKyMzEauYodAACg1YTWhAo1O21GpkCjoYe3twbUetdbyL3qt10kvJ46VgDH1cnA/oVFVb3UGEyiuH5BCHZr+DwepeMocR0li3RhZCvsIa9Si/cMgFP5jtFMRXhlzAgVMlbGzNgrogcZgQ0iJsmCBmCrNUZREsxYsDLIV3gNfnqQB03qlODzfpk0cdJ2QTdajt7acgSX+HhT2cLvuJ8X8l6Ylvv/vrM5xEiyjg7bMO3nq1XCwx0h6m5r6/So6dp1yXf+Plum+gSi6uet06zzWejM0KX76Wik+n5kXr+MnZSyUO65vXnc6V3pZKI2rkrlSljamBqGQxwEdz16Lkpi9FSa98Xa4Uxu50Jq6VY1avV0As6qavOQA7D44vZm0zM4xvWG3c6zcHiK82ri64jZP9S7nc7GSa+ULHPM/JTSOVvT7NHMhnV/nnXXGK9gBY/UR97P2qo3lRgxOpo/SgOpqoTcBqlu5GdpCNQUeFy3fftYp6T+W7dcmoO4Zxtyme5zcvuVzebR/qB6ljbifD3/JH9qnBx1u+S5XVXMoqM6is4injJW5kOIDgxaLIkKxxHn/Isw94rNB9HBymdaaBpFgxxnm4EORAn0RvIt3k+bheeGJmoDbzSpXLgENW7EfSsBO3YR0FwFaNLgCbIwBsEnRgvgaFAkce+vHSvmboQqPXSQ0A2weODhdShN4KYfnEaFC1ByfHA9EB+wyLa0Gjzr/h4LfTwF1XTVOfEmkeNdEoXHgvfDISj/7GMOBvoD46Als+VX10xGi62HSGgtNfGZyO7nVPglx2F6LO3ePm4HYYpS6mKUqdotQpSn1WlDrF7/bjd3vluotG7HNMCTTaJGgm9jt82hvEFSf5uJD9jgnUH0zylexh9xsFxDvQmtye5Ht/FtjAV8/ICRiTfPFnNrcupZn88S8MZcJ+JsyRIxfItsgnuCzzLwyh9A8+qb/9O86UnvmN89HrTdjtfqQwLwrzojAvCvOiMC8K86IwLwrzepcwL1KGQmFeFOb1MWBeM5eIUZjX6sO8MvX6+UH65nHfLtwYzYObswdRbaYqu897u0Lzwb22uYlhXsBHFOY1C8wr+5FgXnGoGwrzWlEMRe6u1jbPrg9uDrfdTLXkuFdm7Sh1xZ9o27lTN8Hbu7HBvN6lOloKciL34WFecegoCvNazVMa7HLhtmPlZOPIbF6dmdzumW1rqRepKUqb+aP7RvVgATAvqqxmVFYiS2FeFOZFYV4U5kVhXhTmNRrmxVOYF4V5UZjXKsG8VrJ92buAeYlTw7z4tDQjzovjZ4R58esSy5wtGua1kkzIJ6UooBeQOojzKrYVpUlxXRTXRXFdFNdFcV0U10VxXRTX9T5xXRdb1xTWRWFdHwXWhdidoro+Jqqr5l4WpMt8Ns8Z1mZzq3OiFSrNvZRb3r+574hN6/isOTGqC7ERBXXNAOoSuY8E6opB2VBM14oCJtonm+WXUvphd8e5zfHZx52XY81IZV7yz09Pjcbz9YUTG6brPSqjpaAk+A8P6YpBQ1FE12oqqM7uZvZSl/YvGy23+HSQftTT6kGq/nh0UVQSRiUnviwA0UVV1YyqSqCALgroooAuCuiigC4K6BoN6BIooIsCuiiga5UAXbO6Ya8ApcH5oncC5+JzU8O5uFm7dnHpGdFcwjrHLR7NtYIcyLGRUK70R4ZyCfMhuQR2cUiuj4a7QpvJzMsUsTJcXFgr3ySKsIgkKcIikgbBR/hKF/+waITWRvy37iMrmcqXNaHfr0CzJVsZuH92AwQoKBWa2lz3reSy2Y1I4a/5a5Rl4Sf0lo+i6ZofZJkGg02EtD4r+KNk1wbtnSFezNrGt/9BdZvnnYjT6bYJ3cdJUKpYaHgKPo0VfJqNUIgzrdk4b5DCTyn8dAXhp7aDdBzc09X7R7hwmCTJ5IX3suwrwySxIzALQtLPaPU83hBcchjFp0UKRg17OI4yKmW0tBQzeIxzpo0DOePsPCljcVzKmMuwS8kZi0NyxkdqS/n2u4dx+se/LTF1PE9HIjaXr7GSYD3kOru6Uirt3D4pzZR718pdHJ48PW2dPI3LCkZlbklqSlxO7nYQqT24RnPnbvvTtGI4TWtEMsCk2dpY85Q9zcD8yuxv/+JlLjeYZFBtMV/95QyuZihK44kV2kiCl3uJnOA4hiZHvXwifjRkDqdLGoZHPCIdGD3WAPB84K0xacjQk/82MJKgjZSNzqS+ldSk/DPoh79+WYtW72u/jEwhdlOANAP4yhnAKuKbzr0Nxs19HZkBjXDaL83StB9N+9G036xpP+I1XIGCV9YXn+taaI7n5GorvypJHhgrtpQSTFbKHk6SKlso7UrFo5WhHYzVox2X5V+fdvn82dGq0A7G6vPdGyBd4eL6amXOUkJj9UgnSK9Puv2L7ZNVIR2M1SfdWxDYs6OtlRFYNFafdOwb4LqTUmFluA6N1SMdn3l90p0dlVbm3DgYq0+69OuT7vhyVQh3fOmTTXx9su2enu6ujGWCB+sTTzikzalocyqKD6DNqSg6gKIDaHMq2pzqXTanujos0UMHaXeqD9OdCvidtqf6oIcO8nx+8+qUP3+usNV0sdp8PJLLRylBebh4zFpC9eKGn7g9FfAR7U81S38q6SP1p4pD3dAGVSt66KDQyqlsg2MLIv9yvmsWdrKHN1bKOa6dXQkXW7q0dRxbg6p3qY6W0vYl/eE7VMWho2iLqtVUUZKZ2756ebk7v5aOHsXO7UNLvDxJPV+zmT3buLnIS3sLaFFFldWsyipDe1TRHlW0RxXtUUV7VFGEenSPKoxTt+852qKKYtUpVn2VWlTN7Ie9AlSGpI2W2qQqS5pU2YvoUvWdV7s8YYsq8dD7/HQNqnie9b845WmDorT4/lQryX5CZIeqXPYQ2XplZJ0yefuxv0fVGHJz/LqUo+SOJDefCZIb7A/cEEyUEL0hD33mSTqQfBOMiYlJzrOU5BNwuE9yATh8OqamFJ6Kwvz0FEbKh1J4cgpzuSkpzK0LOSZPKRylmHPhY3d7qnl6GmcojafZ/Fh2zs2PW+fSlORTkJwXIihOD5SmmH2K2aeYfYrZp5h9itmnmP13jNkvnmwdUsw+xex/FMw+8DvF7H9QzH6mkdW4/U5W6WRUwcm2thvmuZN6OOLSzlnBds632xNj9oGPKGZ/Fsx+9iNh9uNQNxSzv6KA2Jyc3bsutxvOeV48aRzsPVzenpylzg9K17eFjrrrsmZsmP13qY6WAoPNfXjMfhw6imL2V/NYabusOA3h7iV38fCilapn0mlFbqZaV8XWc7VYdl/2F4HZp8pqRmUlsRSzTzH7FLNPMfsUs08x+yMx+zzF7FPMPsXsrxJmf2Y/7BVQNSRttFTMfnpxmP3MlJh9YUbMflI6nhGzvwS87UqyH8em+/CgPIthXRk2fLD0HKA6RH+Bp/SPpH82GwnHzWamg4oiEnOUxYeROBKNK2TGABfHQUXZdXEJUNEV1SpspFbhkuxxSKvMXBfErqNVpMSP5HcpUqWkM9yU8HNK46lpnO4vo6DoZ4p+puhnin6m6GeKfqboZ4p+fmfo50KhQMHPFPz8UcDPiN0p9vljYp9r7qVyXji+vT1x9GNpz9DkzeObo5R6k9vOcLtOaedqe2LsM2IjCn2eAfoscR8J+hyDsqHI5xWFFbZPqu1G7SZTOTLVM6mTFTvpkpU6vGuXxaPbHb26mYsN+fweldFSsIT8hwc+x6ChKO55NRVUZ7daKnSu6k+GJapu9vLu8en8JLWnZgq5Rv3p5qZRXwDumaqqGVWVQGHPFPZMYc8U9kxhzxT2PBL2LFDYM4U9U9jzKsGeZ/XCXgE/g9NF7wX0nBCmRD1nZkM9cxlxpk7l3DqfWTwkdAW5LxNuz+o3KoeG8NO2cZYogacgsDh9F2dK4CkIzEEv1mJTU53JCSxQAk9B4Bn6kHOUwFOoiMz0BGYpgScncFb6cABlIQBajcAX+x7iTBDUiUGwQ7C9JEERAMVyFN87BN873ONeDsKXz1CE79IQvm8X0RspFhNPOJiSCmVzhE1hRxxMPXFe/CDMi7aDvhoCUnYJxZHQxiDY039jhjzWIGqVy04TlBHhZwjgF7K9Rn1j+7mJPqwwTkNBg8Jb8Q7ZihnHNLWy+QyhXvxRf6+KIAdTdowEBL76kZb9VMoOIZJ3PTKl1lO8HkAWPQtfWFsacpLnsyF2WC1A00wWFEkW3ntMAJAB8j5iT0TrL30AJ34eMKX4xsGUrw9wiq2PLJurvKh7l7vSjnPBq/uWeCMfOyl1f+f58DwntcWt6yngTRg4EP2xObECWGdOCRbIrjzIUgyDBYxJcU2roJHAm1uEHupHdU+miMimv2hF5O+/sQGZ3gCqO8Ymszxfud6Si82DRss4vi5t3R0eHpyligfZ1nPGqB3e2kcjcN1Y95DL703XhIBJIRtujK7xTdlJdI00qGsmA3SvJIZyEZonDKB813rnPQEo60KrwqvOxeltrpOrH1ZlMSPutFKXaNa3dT2hsu59vABKqqBmUlDpQQUVD3JyCTDCyYF0+DY/R7ixvzDJrnc9CjlHbgfhlsGY9VBY3kRPZf4WGkIwyJUdQBuOuqMfG/gaWncSVp3yNvj9r8MmDQC3CcGArw/wI3IzO8CPyFI0wG8x+L7pEg+vkmWYpQuKOF0XlAnhiZN0QcHxYp42N4k1+ZGNSH7MtGZvI/lB25vQ9iaxtjfpbumu3j/ChbfhIJVi4TYc2Vduw3FsQmGEq8/ShMO3+XuoylBHjmFEn7YZRdTIh7fqGJJCeeNhvl5lYsCrzs5TlTjWqeYy7FLKEsUhXvWR2lK+/e5FXf7xb0t0rudxnyWzfLddOHvWK+w1mzXat45ZuEg9nBpbWVnSGnvP5+MKz4b6uIRSiy8PjEirirGXB/b7s5lBf3aQASZ1a2P1YXuagfmV2d/+xfNqNwLuH1JbzFd/OYOrOYEv2vMlguMYWn/nlazhR0Nx2nR1aeERT+839245pUsdfvLfBkYy2n1+U9Vv8s+gH/76ZS1avSNffFSV2oKdUFpkNnGRWRXxTede9+yb+zqyBBrh6rI0S6vLaHUZrS6btbrsGLGzCirarCHtjajB5JFZjsR0ffH1VQuFXZ/sn64K7BoNFdtNCSSTSel5EvD6Qkl3c3q8KqRDQ/VJJyRzr0+64sowXfG0R7j0GyDcWWF7ZUiHxuoTj01yr0+8q8PSzaoQD8bqES+TzL4+7VawPCfBpJOZ16fc5vbhyogsjNWjnZTkX592Z0ero+5grF3avQFtd7gye+yhv8cKb0HTbZ6sjKZDQ+1Szuc4ehoKPQ2FAgboaSgULkDhAvQ0FHoayjs7DQUHAelpKPQ0lI9xGsqs4Xl6GsrqV/BmGmXp4er0hhN5+6DdORDqt9nnlLNbOZS4rdxp5rEy8WkoiI3oaSizFOpmP9JpKDEoG3oayorWyuVkubJtnqR3rqXtqpat3Zb2pVLq9owT1KuEu/1inMZ2Gsp7VEZLOWIg9+FPQ4lBQ9HTUFbzNBS7ktk+22VPrm5qee6mqLsnx/tO6pi/r7q2/Xj4tLW9gNNQqKqaTVUB3JCehkJPQ6GnodDTUOhpKBSoHnUaSheuztHzUChinSLWV+k8lBVEjb/N81Bw7dk0J6Jg6Hu3lHmSb/DpQ6ZkOrI25ZkofI73vzjVmSj8uphdfLv4FeRAPinhpUZ7YiaBtkRplgM7KHmnIq+QnvqwAyFHyRtF3h5x+QSX6/IupPPPPL3JfPt3hhI7BmILg5ycA07eBKuXEjc2TvaJK2anJ26aEncyzk2LfcSlEGUKUaYQZQpRphBlClGmEGUKUX5nEOUiRShThPKHQSgXKUD5gwKUa+5V+tG97bQfXhrXR0fV3Fk+vXOWsl4aUmOverZX2LuZGKBcpPjkWfDJae4j4ZOLFJ78QeHJtfZpeu/Mer7qXDzYtZxx5bSfNlupNJd5aeRM/bKoX8cGTy5SyN9MkD/+w6OTixSc/EHByZ09yWjl21LB0bc7z8/26YOcvUjZ5Uu5fbe1q1SgVXLs4GSqqGZTVALFJlNsMsUmU2wyxSZTbPIYbDJPsckUm0yxyauETV653sLLQyaLC0UmQ4PkqZDJwmzAZJGTZgImc+vsEpCzK8d+mSBslk9wmS7acD5oJ8dTYo8kds6jNcdSYi+N2DlpblpTLTIpY3O5McSmSFCKBKVIUIoEpUhQigSlSFCKBH1nSFByiAvFglIs6MfAgs58wBJFg65+u1o2Lx2el1zl4sgs7+vZbef6UHxOnSZs6er4WJEfro2J0aDARxQPOgseVPxIeNA41A1FhK5ow1peEJ9aurNVM56eK/J++fRA5EqpB/1oe7d4KT4+tG9jQ4S+S3W0FKiV9OExoXHoKIoKXU0VJbTFkwvJ0t0d56B9Wnx2JOP5JVVRr+Xr20LJujswFoAKpcpqVmWVprhQiguluFCKC6W4UIoLHYMLFSgulOJCKS50lXChM3tirwCqIYmjpWJDs1NgQ6dEhmaS2emAoTN2rBXT0qwda6XFQ7pWkv8EFvxLjSF7Ip/gshhEB+0S82VkoDJ5+3F6BJ2Uo+SOJDefCZIbTBCMoxOjQIvTtavkWUryCTjcJ7mQnbpvMKXwVBTmp6cwl6UUnoLCGH07DYU56BicpxSOUsy5pBStmqencYbSeJrNj2Xn3Py4dS5NST4FyXnhw8P2hflQ+wI/EWr/o8Hlke8/M8UjiMzFBZH3I1gRASxJighgSYOYcXylC1tdNLB+I/5b95GVTOXLmtAfB0azJXEHCNfbDZCFIINranPdD2qWzW4GEX/NX6MsCz+ht3zwczdaRJZpMDlISOuzgj9Kdm0wPDUk6ry28e1/UDXlBZPF6YqLJgz3T1JchIWGpzVDsdYMZSMU4kxrNi54T6uGaNXQClYN2Q7ScXBPV+8f4cKrWwj0KryXZd9AdQvHzlLZcmyaBmRLcQ7A7qtxGUbwacs7okY9vPglCuGzNEwguIBzwvwCGL/sPBA/cRzEj8uwS8H4iUMwfkdqS/n2uwdL/8e/LRHqNw+YT2oKTvv06TjbaNV3C9XDE/vGvUrt8Hv3grR18Hif3xsH4ooC2hEkkbgcqN1gfd3gGs0NtetH1WXCqDojkgEmBdfFCivraQbmV2Z/+xcPaLbBJINqi/nqL2dwNUNRF0+soGFO4HIPdxMcx1Asmwf/wo8GoNd0GK/wiEegt6LHGqgWHHhrDGos9OS/DYwkaCJlo4FvbwVJJv8M+uGvX9ai1fvaLyMRX13EFgVsvTJgq4r4pnOvexYKLiiMRGulWYrWomit94jWWiBM6GeOXWelxadTzgq7q5JNQUPFFgwnhbEyAofzV0n+eK78FcuvS0uAFuyeHK1M/grG2j3zOQKfxPGHzA+Xhmu7sjYtOolFFtDi2Xszv5lfFWrDWAmD8z2cQe94Vy4pHE93eC7SIBlK4qlILE1HYlZY5zOL1xmFi+urVSExjBWTOMuHVYbYTXkHNMYcHQLZ3Lq0BLxBYX/nYmVoj8aKaZ+L0tYCmx1N/OkYX2Qp40cyfk6KUi0ZdmoEk5RdPHtv76+MNYKGSlpgRmKleYxfioe7wThZAkLv4rC0KrRHQyX7ZjqS9kIf7afUJHQLjdYk6UirO5PhwtQOVwg0NdWh+DEKzKDADArMoMAMCsygwIxFADO2n1xkWSo2BWZQYMbHAGZkVOH8omG2TnIdXmaNul3bs7iUWVXyjTM9wzWvdygwIwqYkaXADArMoMAMCsxYMjBD8SwU3FiHYykmg2IyKCZjPkwGK0Bc+GzxGdXVyacSeIDABs628zIeApvMzYnIQOReQmh49/R0ZTAwMFZMcjEbQXI+jTECA0nVQEh4/OGNywDBHF9cHa0KyWGsJPchSoMk53JJdk6SC4CEWTyXH12vDJMfXRO1wnZ5PAg6ymImf3sUXj21zQfpyyXQS6BvOslNT98spe+obTHIv1wc+yLl54npzUZq6GnonVsXlgDFPb5cmS3x0ktPB2wQIYFMY+hZl0wfTwd0YZdCXbCcjlbJzCNGhyiGgIr+udHZpDin1YF4Wlw81U+utlZGi8BYiR6RgjT3GTuD1TZtz0PhFRReQeEVFF5B4RUUXrE4eEVphyIrKLLiYyArcmW+/cwal+UKe+qYHeGkyBk3qZbxuG2VFNu+uOtQZEUUsiJHkRUUWUGRFRRZsWxkhVOjqAqKqqCoipg6XXDr0hLq1ItnK1PpiIZKSqhZNhBh571AJJ8hOecpor2IxLxASTyWxH6slxPTOMA+Xft7SuKxJA7m5URh2kQ+HGmUXnzicwVpnAEah44Y8JL5HiRoOl1B1fFwIg+o4zTpGjK0CHd8+pPPUXJHkVuKUs1pFsNTZiY3UiEiVSFR5M7wUkTaUxST2flSzXRnnEyh+BQXPAgF1SExUFjMSBG2h0CaaVElEju902x0dxYBaxHanGKaw43Y6dAT0xzJQ09Eoici0ROR6IlIr6bbhGUiwySKDKPIMIoMo8gwigx7I8iwbvucGbBhUmJL7mB0GAWHtRXlUeskkBtrtVSF4sQmxIlhFlo5oFjNrtzdZYrnmlWVD/fK+/mH4zT7nDptnFfsVvM5c+RWKVAsAiiWYQeBYhEcQJFiFCn2lpFifbqegsZWBDSGDDw09DppyNO5t10daeEOAZBJFEBGAWQUQDYXgIwWsPYXsP7KSLnvIO1lo1854TvmtHQMvyWzz+gfEaBNv2IATiYpHU+S8VooiUvFo5UhMYzVIzEvdkks+RRmkxmgcCbLHQKFeZ59CwTO589WpvIdxuoRWOC7BOZ7BE5jFhZZTOBsLim8Pn33T0qFVaEvjNXXEdmejujRVwL6CpxIGDgLWIRXJ/AKHlKHSNmjbsYnL59kgby8kMHk5YQk9wbUw/HdycqoBzTWkfoXqweey2H6StxbUL8refQI0rE99cBneiaEQAicxQQWM0n+9Qm8co1zfmXSvb2N43vExdqBy0pE+Yr8W1C+uzur0zZn52hQ+aZ98kpJEZM3TXhXegusmz/eWh3Vu+VrhnSXutke7/KEuALZ2bgeeSnQaxwYYkybHIEVago3G9BrTIyMgiEWAIaQ4kKHUTDEWwJDvMVA4HjQwuhYYT+UYGTUcCiQICSvZVOrDkYK+9Prw4OMiE5bst0om7JV9eABw5AART/k3gcECMa9Y4yQ8sHMhZ+W7E5MBHsBfiLComtLTBK7V3dSRTs7SkuVevmseLONlqiUuqsdX+5kGuXHU7syoJyGpli7psBASpUbTKl2V4MxDeZaKZOU6rfff/32+/Jm3z69rWTFE/fwpsa3tiqO2rpzXlJ2dedov1TZurg4vo9j9vyo2asGs6Xa6DZVL6m8PKYckDZ+HFcq+sb//G//x39iChqyShlVl+sKY1qMozqQITYZyDQyNVfTyHufU+gL1JYbYctJk9ly86Uul2KsCUJSEIaZa0L63dhrQiawZOEVyEQsQGZphpeQnS6pPj5hvoj0NuSxiUtr37vkUNp79B2Ymq1UQ/ltnuMXnt8WcgGiwSoulhFFdmpO9L9LTGr0iKZp2GoLLZVaVdZC1QWcFFVeQKzesMUtRRQYRJurkTIgcgl1rI2/CIs+PIvwJkVGjBm1qrY2PjdEf7z+GD3UrNgdYgDfNm603A6/JWz1jVbG229D0VoKoD2HbsQeGy7Lquns3WarJ8el25fG2Q5n7G6pB09XqVrb2u8USmct52lvMAzU74B6G080jK7fwBHCBk4HzXWEJR6m4V8wGJaph+HJUTVon90N/xhrqC8uES3yOeVueAY92E+fUw0R/QUc0GdKLU2QZjFo6D5K99GZ91EbuozbdBul2yjdRmNstMrmb2rZ+hFvXDxot83ninolGFzqTslqezut8+1n4TjmbVRc1jaKjyWgm+jqb6IiTzfRmDZR3dTRMF2dbqN0G6XbaIzbKC/cbFZfDiqco2dsJfOytWc83KSuhKdDlS3d192aGPM2Ki1rGz32VMb720lpfP3Nxdd5aZg9Iwo0KLBoe4YfNGfiJqqUDiypGCDqQLbeVpoy0oBKpIHhFe0Gy9RGroqUDnWq6Y4gJDmzWGzxdlEfkyvA1IvbOotQgNRgowbbezfYhPa1mtvf39w9Mi8Lxf0jVbypC6mra73cVszEkXu3G7PBll52+uC0CaOxmTwgPlSn897CH9RWoLbCB7YVcD6EWgrUUqCWwmItBal5va2Udx8vjaen692iWrD2Kncpq6lnrqWE2dTV+5gthcxyMyTUTqA5EmonvFs7YVzKh5oK1FSgpkI8pkJGvdJy7s7Bw45TeBKrYkPh7qRUkS/k+DSnVx63H2M2FbJLzwJRa+E9WAtpai1QayHaWkBSid6+h1J8ajJQk4GaDIs+6P5qr7a1ZT83Wnc527gonGtX5VRReTFV0XW06oUVs8mQW57JQFRJ12Qg7ckpcuTtIEfEzDKQI33NCCiYhCaIqCm3eFNO8c6ToFYcteKoFbfgUyiqnNNUrPzWw9XlTS1ze3vYfOBSD2e2VJOUPaFTK8drxWXZZVlx3VNpaMCHWgnUSnhHVsKQMxiotUCtBWotLLYd2TV3fvjcfChu3jxZpb2WkLmr3aQ2nYfKy1mncdl82YrZWuCWbi3gs6SoqUCRJNRUeD8BBadGgwnUPKDmwaL7dZ6x7addc79elbc294p7N+5BRUi9HGzfbaY3W6JZN2M2D/gJzQNJyWRrc5kHpR0aR6DGATUO3mUcwanRIAK1EqiVsKT+l/ts6ehOt1pS5e5Kqih8Q7i9Sx3ul4SEedsqcletmK2EpfW/BCvhHcUP3gxYhM/OiRbJLvFMFv41z2SRPsCRLGIu3iNZ3rv9J/BsgA0m3eIFj2n98XbVUHZtok1YmmQTnmCznWyvHXFGDSIn8/mPicTPag0OK/kFUbe1juXfUioO86xrhr3e+rLmWsY6PjJdthO6WrFM26w5SEXo6y1dW/M+1x71ObNWUyvKOjx13taWLy9PtnaRu1FapmOwNyXjSkqdCqVtxTmxdwwl06VgK0GMDKPSQJTU1WpVQ9a7TxeRA1L5K8rlYEWRWVABQiLHD9i5pmoaXoYva3/ia3JWrMG9LfNRib7a9vmg+bzGVGVHTpQdtPZc/6YrDp6q8bm9TsYJxjJsJn2vW+swl7L5zKiGDbs/+wn/eDZTv9FN9nr0HuHDfnOq7CJ9bHh7/cYR2lRDeE7mn//4790tmtwBhuTt0d2hkBdddkEv//gzrF/tl0QiwFh/xJwFrxi4vsQmqOM5pSuRfMJi+qgzMMzwigbNDfi9u1tEnRLUJ5GcNMw+G2rNeh6T9yjb1NSq92E4jyn82X7XCw2m/KgSJYMVRUKuPri24z8zYtsnjN19bNcOxP9Fu8DeNU+i2KjjWmYywbFK69Iu65/eDlYguommRSBZ+cGdLArIGoFj5YNKgaj5CYR3AjGC83GQCIREJL44lUSPm6O2DbVtVty24YWX6+PNR/bkpbGfbTyf8Ls3F+VUJntS1LXOcbtz//ZsG75fPUpvy7bx9fGZZdZUhynIWsVFYzOt92HjTMIxM9o4PLVxPqyNIw2zcSYTp0XYOu+mOiuOeNukx8byESVdghTBJYL0ioG5dDqZzlD7dfLlfRvHJUvCqOOSg4m5mM9OHkeeYBK2/yjQgcMYcMKpOZhWGpIIidTy5CxTpqfmmWF6XsSrUzKZW9O1mKJbqSi2/amrOJvRmZAw2cU3SvZwHenbpPyFWWZko8qULKXzidkx8cm3NmPWkNdho83W2lENZJsq334fvSZxHehCtdtb1W5LwJ6kpQAjSJOuRVry/fNl4wtoKGCWUIAuq5pjIn9S1v9FJUqmRpRMUjUn9efFgMnOpTNhf14U+/x5YkP2+/NEgfb783zYnxde2V8Pqf7einMCZsvC6UkpXygxl8Wuen47HvyYhe5KRTrCDQ8uwHt3u30Pp8/t9vf3PrebuDBhv5sf63cPUxlzu9hRzpM02sXmJM7btUZxODOWxcd51RQxsxQHXhrTXoWtciyXi8mWjvDLBWlZfjm5J7Vbp7NbozQEJy3PK8+Ocg/j9QjHQD4jo1FAhQGnD2ljhoWf8F34QW2UDqr+Kg8/w7Cku6bDOA3VZmqWqTMy+kdFivPvzBJPI3nhrUv1rnLxoBSvMw83wt5pJtU6uTjcLGfTpycXFwOMF5pRcAfHjiqQYiBWmx6I1RYRIRi3iXS9pRCIZXNkRGHJSGqOn018J3I5couCN0cweTbaCRkfD+nHO0cEQSJiF3OapOEABzZJHdXBazDEYp0PaBwdxdnB/w2KOcYIR4+zHzA83W2ZXxn/y8s7W6Bzd2w0sk+OzuqH+2nuiTusprT7ln5w0qleyTcvXdK32+1k7JTvUxCZAQUx/crAOMcuzMShsj79k2YXHmtJZ9i57UF0jxAyIqiAlrK1R9FpoNpGNbBGIu7ZKpCxOzsuLkOsq3ilCPMsLUTZZ+GrvQTCcoDpfMC05ZH5pptlu2G2GfDgEvjxr2lsz+kvpcXZ13XIgdr9Cz3oJPlrt7we8R3JTtdU6cg8SWeLxeuKtpdLne2nDwt3L7vGtn0Us1LPRmToB+r+yBzQ5cFZqDpMwOpkz420tMtd5S+gpu/v7hd+s5nvvPD1Y/XaqFQe2LRwXFEfco+3jYd8zrk5zlcDALNp6/7ILNCA8CQEds0La5C9occ00QGMblEuGxW7GOQVzotcMBMhKKkQrroQ5srPlZMzZe/AeHo4a1ea3NnVVi1ltM+KuYO9h/pDLubjurO5WIRQdfazDy2xbtzsb0cJoVJ+qdzWynvPZb3F3Rxenx6mod9zXELIUSGkQhhn08zL7Rtr7/auea4Yart9cnB3IaW2uPv2zr2tG+hyvEKYY2MRwlLtKKHcPxQ2KwdslBDWL19yQufOKgjNvaOjS9tJPwm1+ISQp0JIhTDOXnQlTcjvZsy9Epe5yezb6YOTcspV+UOneNs5r21vxyyEXCxCqGVOGifi/jF7pFWihFA96dTu9m7Pz6+sai1X2zlxZHYzPiEUqBBSIYyz41Np77a03eAfrk4ujvZqx45wmEld7uaPH927i3PVzsUshHwsQnhdMItm/iJ3YZzdRQnh426nIMrXL2hIL53nZtmuH7Qb8QmhSIWQCmGcDVWKpqBv7e5t3jxouSJn1Yzdaqp2Uy2d2q1s+eKmELMQCrEIYblk7ORP9/XOTek6Sgj13LN651zdOmft433tpXNSEpyt+IRQekNCKLxtIZSoEI6vxN8sHt5Jm82rqpwWnyunx8WbrVxqs3Sh3efV4kN7O+bWyDkxFiGs5s5N6+74yXh56kQJock/70iFy2zG6qgVOX9o7xjNh/iEMB0WwhkgVVNf6mfO9ARYkiUBeD0ZHi+YfULdL/S9JRkGLPBmD9jHZiDD5t2U5PO9jnWjRjXDQIJaLIKCQ6sHB3EyfCREcggGYWnFquKFJZ7mTx+lSvFU0x+tnb1cLWVuX166j3cPm+V7cW1Y0cfkeJicNNDR7Fg25LrCnOFZKEZFsUGuvv3+67ffFzV53YKpc046f2VX+ZsdY393v6iXdi33bPNo13kq89JLKmEdbD5tuY+qDnv3DDPfuFbKzJVi2eiNuabk4UT+brvlB6XifCk0lMrjdzyL9jH0N4Co4B8L9+BDvxlK29YUB/EPegHoKvRPGB3wfdmsdr7sw7dVo6K5VQXukN9Hf6HF0Do23LGAbwqU697Vu2g24W+18ojmFrqEhqB4V2Sjiv7W0Vz+OBvxiujJjGN2kWEjlO3bbUu5SDBVOvP2wFT8kLMH48BXTYeK2ewwro0G0Vc59olB1GfkuqUowFxQ5rds/JHwfHFy18g+d24UU717zhzzXHoztV88uHGOzooXd1taF39UUiwdl78VFaulVpSY7bB0DNCj/iH2o46Whup6OnclNnNTeGls8qeZ0pOp8Y3UbeHwQOP2G/eiosZMvLlxW4EiRg+dNZkgwPeaC5Kab/93n7xgA0dDcgsbM3N0VJi68LLfaM2+EaN1ZDn9B7Vj/YLdYZZsRKwgG7Rk/d4cQ7R9ZOta8hUAhCOTBRS2Y5qMLhsdRgG7x14iIjzzcH4uH6TTFxcPN8eFvaej8uXLVipdzjSle62gtu/214YMfxoLODtgAedxTRbsTBbTDJvBjGktav6ukWrxATv4tvFUvOCatdOXR/bySapmS8ZF5oZL1WtnN+VCkS3I9uFM899wDWS52hVLLStQk+jIhqN1YHZJf/NlYvGPF+B+Mwx6DdYydEJ2dG3j/wfp4Hw8"
    _seed_flag_20261113 = os.path.expanduser("~/.optionhub_insider_seed_20261113_v6")
    if not os.path.exists(_seed_flag_20261113):
        _seed_mail_20261113 = {
            "id": "ins_20261113_evening_edge",
            "날짜": "2026-11-14 07:09",
            "출처": "InsiderFinance",
            "제목": "Evening Edge 2026-11-13 (금요일 장마감)",
            "원문": '[Evening Edge 2026-11-13 · InsiderFinance Trading Insights]\n\n■ Trending News\n- Modine (MOD): Jumped nearly 29% in after-hours trading following reports Samsung was in talks to acquire the company (AI data-center demand).\n- U.S. Macro: Slower monthly PPI growth while annual wholesale inflation remained elevated -> reinforces expectations for continued restrictive Fed policy.\n- HawkEye 360 (HAWK): Record Q3 revenue $59.3M; raised 2026 guidance to $225M-$227M.\n- Cerebras Systems: $231M non-GAAP core revenue; raised Q4 & full-year guidance after Microsoft cloud deal.\n- Applied Materials (AMAT): Record Q4 revenue $10.41B, record non-GAAP EPS $4.16; guided FY27 Q1 revenue near $11.1B on AI-chip demand.\n- Microsoft (MSFT): Nov. 12 outage disrupted Outlook, Teams, and Microsoft 365.\n\n■ AI Market Insights (BETA)\n1. AI semiconductors see persistent downside hedging amid Nvidia turmoil [Bearish 5/5]\n   - NVDA dropped ~15% over 5 days; tech options flow skewed to puts (NVDA, MU, MRVL short & long dated hedging) ahead of CEO change & earnings next week.\n2. Real estate suffers renewed pressure with mortgage REIT put demand [Bearish 5/5]\n   - ~95% of daily/weekly options premium in puts (repeated AGNC $8 put blocks).\n3. Communication services faces heavy downside hedging in mega cap names [Bearish 5/5]\n   - ~80% daily premium in puts (GOOG, GOOGL, NBIS large deep downside blocks).\n4. Energy and uranium stay supported on geopolitical and inflation risk [Bullish 4/5]\n   - Daily flow dominated by calls in XOM and uranium leader CCJ.\n5. Healthcare innovators attract long dated upside positioning [Bullish 4/5]\n   - Deep OTM multi-year CYTK call positioning & dark pool accumulation.\n\n■ AI Noteworthy Trades\n- [15:19] BA 230 PUT 2027-01-15 @ $30.9M (Top Position · Block | Hedge 5/5, 1.5x OI)\n- [15:17] GOOG 480 PUT 2027-01-15 @ $26.3M (Top Position · Split | Hedge 5/5)\n- [13:50] MRVL 145 PUT 2027-01-15 @ $19.0M (Top Position · Split | Hedge 5/5, ~5x OI)\n- [09:35] MU 650 PUT 2027-03-19 @ $9.6M (Sweep | Hedge 4/5, after +10% 5D rally)\n- [10:19] TSLA 320 PUT 2026-12-11 @ $2.6M (Unusual · Golden Sweep | Hedge 4/5, 27x OI)\n- [10:05] PCG 15 CALL 2026-12-31 @ $1.2M (Top Position · Block | Positioning 4/5)\n\n■ AI Options Plays\n- NVDA Bear Put Spread (Bearish 5/5, 2-6W) | GOOG Bear Put Spread (Bearish 4/5, 1-3M)\n- CCJ Long Call (Bullish 4/5, 2-6W) | CYTK Long Call (Bullish 4/5, 1-3M+) | PCG Bull Call Spread (Bullish 4/5, 1-3M)\n\n■ Unusual OTM % Top 10\nMRVL 72% | ASTS 38% | CIFR 38% | MSTR 38% | MU 37% | DELL 37% | GNLX 34% | TSLA 34% | SPCE 33% | AG 31%\n- CIFR 9C 2026-12-18 @ $308K (Unusual · Top Position · Block)\n- GNLX 2.5C 2026-12-18 @ $12K (Sweep) | RDW 10C 2026-12-18 @ $16K (Sweep)\n\n■ Sweep Volume Top 10\nNVDA 858K | TSLA 182K | AAPL 82K | CRWV 35K | IREN 32K | APLD 30K | INTC 27K | PLTR 26K | MU 24K | GOOGL 23K\n- SNDK Sweeps ($2.5M): 1000C 11/20 @ $1.0M (Above Ask), 850C 11/13 @ $671K & $669K, 1060C 11/20 @ $270K\n- VKTX Sweeps ($220K): 27C 11/13 @ $145K & $100K, 30C 12/18 @ $98K\n- CCC Sweeps ($174K): 7.5C 12/18 x6\n\n■ Momentum (Daily Avg Multiple)\nNIO 15.5x (100% Put, $292K) | XOM 13.9x | SO 13.6x (100% Put, 75P $415K) | SPCE 10.1x | VKTX 7.8x | CCC 6.7x\n\n■ Top 10 Moonshot Flows\nPCG 15C 12/31 $1.2M | BABA 120C 2027-1-15 $1.5M & $1.3M | CRWV 65C 12/18 $771K, 95C 1/15 $170K, 82C 12/4 $23K | CIFR 9C 12/18 $308K | RKT 16C 12/18 $230K | EIX 70C 12/18 $200K | GNLX 2.5C 12/18 $12K\n\n■ Top 10 Equities Flows\nBA 230P 2027-1-15 $30.9M | GOOG 480P 2027-1-15 $26.3M | MRVL 145P 2027-1-15 $19.0M | GLW 200P 12/18 $18.3M | BA 220P 11/20 $16.1M | BA 230P 12/18 $11.9M & $10.0M | MU 650P 2027-3-19 $9.6M | GOOGL 440C 2027-12-17 $8.4M | NVDA 250C 2027-3-19 $7.9M\n\n■ Top 10 ETF Flows (SPX)\nSPX 8000P 2027-2-19 $279.0M | 8000P 2027-3-19 $146.4M | 8000P 2026-12-18 $143.3M | 7000C 2026-11-20 $126.3M | 7000P 2027-2-19 $61.5M | 7500P 2027-3-19 $60.1M | 7725C 2027-3-19 $44.8M | 7000P 2027-3-19 $39.6M | 7475P 2026-12-18 $31.3M | 7600C 2026-12-18 $23.8M\n\n■ Equities 5-Day Flow\nNVDA (59% Put, 1.8x, $1437.5M) | TSLA (24% Put, 0.7x, $220.5M) | AAPL (32% Put, $89.3M) | INTC (58% Put, $289.6M) | PCG (0% Put, 2.0x, $13.1M) | AMZN (24% Put, $51.5M) | CRWV (48% Put, $47.2M) | MU (62% Put, $242.6M) | GFL (0% Put, 5.4x, $5.2M) | AMD (46% Put, 1.2x, $115.2M)',
            "요약": '📬 [InsiderFinance] Evening Edge (2026-11-13 금요일 장마감)\n\n1️⃣ 트레이딩 뉴스 (Trending News)\n• 📈 Modine (MOD): 삼성전자의 인수 협상 보도 이후 시간외 거래에서 약 +29% 급등, AI 데이터센터 냉각 수요 기대감으로 재평가 진행.\n• 📊 미국 매크로(PPI): 10월 월간 생산자물가 상승률은 둔화됐으나 연간 도매 물가는 여전히 높은 수준을 유지해 연준(Fed)의 긴축 기조 장기화 전망 강화.\n• 📈 HawkEye 360 (HAWK): 3분기 사상 최대 매출 $59.3M 기록 및 2026년 매출 가이던스를 $225M~$227M로 상향(ISA 및 글로벌 수요).\n• 🚀 Cerebras Systems: 마이크로소프트(MS) 클라우드 계약 체결 이후 비GAAP 핵심 매출 $231M 달성 및 4분기·연간 가이던스 상향(트레이더 관심 및 옵션 수급 유입 기대).\n• ⚙️ Applied Materials (AMAT): AI 칩 수요에 힘입어 4분기 사상 최대 매출 $10.41B·비GAAP EPS $4.16 기록, FY27 1분기 매출 가이던스 약 $11.1B 제시.\n• ⚠️ Microsoft (MSFT): 11월 12일 예기치 못한 서버 장애로 Outlook·Teams·Microsoft 365 서비스 중단 및 배포 일시 중지.\n\n2️⃣ 옵션 섹터 분석 (AI Market Insights)\n• 🔴 AI 반도체 — 지속적 하방 헤지 (약세 5/5 · 진행 중, 10/5 12:25 최초 포착)\n  - NVDA가 5일간 약 -15% 하락한 가운데 기술주 옵션 수급은 여전히 풋에 편중. NVDA·MU·MRVL 단·장기물 모두 대규모 헤지 유입. CEO 교체, AI 거버넌스 이슈, 다음 주 실적 발표를 앞두고 기관은 공격적 상방 베팅보다 익스포저 방어에 집중.\n• 🔴 부동산 — 모기지 리츠(REITs) 풋 수요 재확대 (약세 5/5 · 진행 중, 11/12 12:25 포착)\n  - 당일 약 -2% 하락하며 일간·주간 옵션 프리미엄의 약 95%가 풋에 집중. AGNC $8 풋 블록 반복 및 끈적한 인플레 지표로 금리 민감 부동산·모기지 리츠 하방 방어 지속.\n• 🔴 커뮤니케이션 서비스 — 대형주 중심 대규모 하방 헤지 (약세 5/5 · 신규 포착, 11/13 16:25)\n  - 일간 프리미엄의 약 80%, 시간대별 프리미엄의 거의 전부가 풋으로 쏠림. GOOG·GOOGL·NBIS에 깊은 외가격/장기 하방 풋 블록 유입 및 현물 매도세(분배) 동반.\n• 🟢 에너지 & 우라늄 — 지정학·인플레 리스크 속 강세 유지 (강세 4/5 · 진행 중, 11/12 13:25)\n  - 일간·주간 모두 상승세 유지, XOM 및 우라늄 대장주 CCJ 중심 콜 우위. 이란 긴장 및 PPI 물가 경계감으로 원자재·인플레 헤지 수요 견조.\n• 🟢 헬스케어 혁신주 — 장기 상방 포지셔닝 유입 (강세 4/5 · 진행 중, 11/12 12:25)\n  - 주간 콜 우위 지속. CYTK 다년물 OTM 콜 집중 및 섹터 전반 다크풀 매집 확인(단, IONS 등 개별 악재 종목은 풋 헤지).\n\n3️⃣ AI 주목할 만한 체결 (AI Noteworthy Trades)\n• [15:19] BA 2027-01-15 $230 PUT @ $30.9M (Top Position · 블록 | 의도: 헤지 5/5)\n  - 미결제약정(OI)의 1.5배 규모 딥 ITM 장기 풋. 산업재 현물 매집 흐름을 감안하면 신규 공매도보다 대형 장기 보유자의 개별 리스크 보험성 헤지.\n• [15:17] GOOG 2027-01-15 $480 PUT @ $26.3M (Top Position · 스플릿 | 의도: 헤지 5/5)\n  - 기존 OI를 상회하는 신규 딥 ITM 장기 풋. 당일 GOOG 프리미엄 대부분이 풋인 점과 빅테크 인터넷 분배 흐름 속 장기 포트폴리오 방어 성격.\n• [13:50] MRVL 2027-01-15 $145 PUT @ $19.0M (Top Position · 스플릿 | 의도: 헤지 5/5)\n  - OI의 약 5배 규모 블록. 주간 풋 편중 심화 속에서 NVDA·MU와 함께 AI 반도체 익스포저 보험을 강화하는 흐름.\n• [09:35] MU 2027-03-19 $650 PUT @ $9.6M (스윕 | 의도: 헤지 4/5)\n  - 5일간 +10% 상승 이후 수익 고정 및 AI 메모리 조정 대비용 고행사가 풋 스윕.\n• [10:19] TSLA 2026-12-11 $320 PUT @ $2.6M (Unusual · 골든 스윕 | 의도: 헤지 4/5)\n  - OI의 27배 규모 이례적 풋 스윕. 최근 5일 두 자릿수 상승 및 주간 콜 우위 속에서 단기 매크로/개별 이벤트 대비 이익 보호 목적.\n• [10:05] PCG 2026-12-31 $15 CALL @ $1.2M (Top Position · 블록 | 의도: 포지셔닝 4/5)\n  - 주간 수급이 거의 100% 콜인 유틸리티 방어주 PCG에 연말 만기 OTM 상방 포지션 구축.\n\n4️⃣ AI 옵션 플레이 전략 (AI Options Plays)\n• 🐻 NVDA Bear Put Spread (약세 5/5 · 만기 2~6주)\n  - 5일간 -15% 하락 및 Ask 위 풋·골든 스윕 우위(SMH·SOXL도 동일). CEO 사임·다음 주 실적 앞두고 변동성(Vega) 부담을 줄인 등가격 부근 약세 풋 스프레드 유효.\n• 🐻 GOOG Bear Put Spread (약세 4/5 · 만기 1~3개월)\n  - $26.3M 2027 480P 등 풋 일변도 및 현물 분배 흐름에 맞춰 횡보 시 시간가치 손실을 제한하는 약세 풋 스프레드 제안.\n• 🐂 CCJ Long Call (강세 4/5 · 만기 2~6주)\n  - 이란 긴장·인플레 헤지 수혜 및 골든 스윕 콜이 OI를 지지하는 우라늄 대표주 등가격/소폭 OTM 콜 매수.\n• 🐂 CYTK Long Call (강세 4/5 · 만기 1~3개월+)\n  - 주간 프리미엄이 장기 OTM 콜에 집중된 바이오 혁신주, 다크풀 매집과 함께 기관 LEAPS 추종(바이오 특성상 비중 조절 필수).\n• 🐂 PCG Bull Call Spread (강세 4/5 · 만기 1~3개월)\n  - 매파적 연준·고물가 환경에서 방어주 유틸리티 강세 및 콜 편중 수급을 활용한 저베타 상방 스프레드.\n\n5️⃣ 전반적인 흐름 총정리\n• [빅테크·AI 반도체 = 방어 모드] NVDA CEO 교체 및 다음 주 실적, 그리고 연간 PPI 물가 고착화(연준 긴축 장기화)가 맞물리며 기관들은 NVDA·MRVL·MU·GOOG·BA 등에 수천만 달러 단위의 중장기 풋 헤지를 쌓고 현물을 방어하고 있습니다.\n• [자금의 대피처 = 에너지·우라늄·유틸리티·바이오] 금리와 물가 부담을 피해 XOM·CCJ(인플레·지정학 헤지), PCG(방어적 유틸리티), CYTK·VKTX(바이오 파이프라인) 쪽으로 콜 매수세와 다크풀 매집이 이동하는 순환매 장세입니다.\n• [단기 트레이딩 포인트] 다음 주 NVDA 실적 전까지 반도체(SMH·SOXL)는 풋 헤지 압력 속 반등 시 상단 저항을 경계하고, 스윕 콜이 집중된 SNDK($2.5M) 및 에너지·방어주 중심의 차별화 흐름을 주시해야 합니다.',
            "종목": "NVDA, GOOG, MU, MRVL, TSLA, BA, SNDK, SPX, SMH, SOXL",
        }
        import zlib as _zlib, base64 as _b64
        _seed_html_20261113 = _zlib.decompress(_b64.b64decode(_seed_html_b64_20261113)).decode("utf-8")
        _seed_mail_20261113["이미지"] = _seed_images_20261113
        _seed_mail_20261113["html"] = _seed_html_20261113
        _seed_ko_map_20261113 = {0: '📌 **트렌딩 뉴스 해석**: Modine(MOD)은 삼성전자 인수 협상 보도로 시간외 +29% 급등하며 AI 데이터센터 냉각 테마가 부각됐습니다. Applied Materials(AMAT)와 Cerebras는 사상 최대 실적 및 가이던스 상향으로 AI 설비투자 수요가 견조함을 입증했으나, 미국 10월 PPI 연간 물가 고착화로 연준 긴축 장기화 경계감이 시장 상단을 누르고 있습니다.', 1: '📌 **AI 섹터 인사이트 해석**: NVDA가 5일간 -15% 하락하고 CEO 교체·다음 주 실적을 앞두고 있어 **AI 반도체(NVDA·MU·MRVL)와 빅테크 커뮤니케이션(GOOG·GOOGL)**에는 강한 풋 헤지(약세 5/5)가 지속 중입니다. 반면 **에너지·우라늄(XOM·CCJ)**과 **바이오(CYTK)**는 인플레 헤지·파이프라인 기대감으로 콜 매수 우위(강세 4/5)를 보이고 있습니다.', 2: '📌 **주목할 큰 체결 해석**: 장중 최대 규모 체결은 전부 **장기 풋 헤지 블록**입니다. BA 2027-01 230P($30.9M), GOOG 2027-01 480P($26.3M), MRVL 2027-01 145P($19.0M, OI 5배)는 기관이 보유 현물을 방어하는 보험성 헤지 성격이며, TSLA 12/11 320P($2.6M, OI 27배)는 주간 강세 후 단기 이벤트 차익 보호입니다. 반면 PCG 12/31 15C($1.2M)는 방어주 상방 포지셔닝입니다.', 3: '📌 **AI 옵션 전략 해석**: 단기 하방 방어·변동성 대응용으로 **NVDA Bear Put Spread(2~6주)**와 **GOOG Bear Put Spread(1~3개월)**가 기관 수급과 일치합니다. 상방 전략으로는 인플레·지정학 수혜 **CCJ Long Call(2~6주)**, 바이오 장기 모멘텀 **CYTK Long Call(1~3개월+)**, 방어주 캐리 **PCG Bull Call Spread(1~3개월)**가 제시됐습니다.', 4: '📌 **특이 OTM(외가격) 활동 해석**: MRVL이 72%로 압도적 1위를 기록하며 가장 공격적인 외가격 베팅이 몰렸고, ASTS·CIFR·MSTR(38%), MU·DELL(37%)이 뒤를 이었습니다. 크립토·AI 인프라·반도체 주변주에 변동성 확대 베팅이 집중된 하루입니다.', 5: '📌 **CIFR 체결 해석**: 장 초반(09:56) 2026-12-18 만기 $9 콜에 **$308K(8,000계약)** 단일 대형 블록이 들어왔으며 풋 비중 0%, 38% 외가격 콜로 단기 급등(비트코인 채굴/AI 데이터센터)을 노린 신규 Top Position입니다.', 6: '📌 **GNLX 체결 해석**: 장 후반(14:50) 2026-12-18 만기 $2.5 콜 스윕($12K, 265계약, 34% OTM)이 풋 0%로 유입되며 소형 바이오의 연말 이벤트 상방 베팅이 포착됐습니다.', 7: '📌 **RDW 체결 해석**: 장 마감 무렵(15:11) 2026-12-18 만기 $10 콜 스윕($16K, 1,000계약, 29% OTM)이 풋 0%로 체결되며 우주·방산 테마의 단기 콜 매수세가 유입됐습니다.', 8: '📌 **스윕 거래량 해석**: 당일 스윕 거래량은 **NVDA(858K)**가 압도적 1위이며 TSLA(182K), AAPL(82K) 순입니다. CRWV(35K)·IREN(32K)·APLD(30K) 등 AI 데이터센터·네오클라우드 종목들에도 빠른 단타성 스윕이 대거 몰렸습니다.', 9: '📌 **VKTX 스윕 해석**: 비만치료제 바이오 VKTX에 100% 콜 스윕·블록(총 $220K+ / 당일 만기 $27C $145K·$100K 및 12/18 $30C $98K Above Ask)이 연속 유입되며 단기 돌파 기대감이 강합니다.', 10: '📌 **SNDK 스윕 해석**: 낸드/스토리지 강자 SNDK에 **총 $2.5M 규모의 100% 콜 스윕**이 폭발했습니다. 특히 11/20 만기 $1000C($1.0M Above Ask)와 $1060C($270K), 당일 $850C($671K+$669K) 등 공격적인 상방 랠리 추격 매수가 확인됩니다.', 11: '📌 **CCC 체결 해석**: 12/18 만기 $7.5 ITM/ATM 콜에 12:10~13:27 사이 6건 연속 스윕($174K, 7,000계약, 풋 0%)이 집중되며 조용한 기관 매집 흐름이 포착됐습니다.', 12: '📌 **일평균 대비 거래량 급증(모멘텀) 해석**: NIO(15.5배)·XOM(13.9배)·SO(13.6배) 순으로 평소 대비 옵션 거래량이 폭증했습니다. 에너지(XOM)·바이오(VKTX)는 상방, NIO·유틸리티 SO는 하방 풋 쪽으로 거래량이 터졌습니다.', 13: '📌 **NIO 모멘텀 해석**: 평소 대비 15.5배 거래량이 터졌으나 **100% 풋 플로우($292K, 2.6만 계약)**입니다. 2027년 1~2월 만기 $2~$3 풋에 블록·스윕이 집중되어 중장기 하락 베팅/헤지가 강합니다.', 14: '📌 **SO(서던 컴퍼니) 모멘텀 해석**: 평소 대비 13.6배 거래량에 **100% 풋 플로우($415K)**로, 2027년 9월·12월 만기 $75 풋 스윕이 4건 연속 체결되며 장기 금리 부담에 대한 방어 포지션이 구축됐습니다.', 15: '📌 **VKTX 모멘텀 해석**: 일평균 대비 7.8배 거래량에 100% 콜($465K, 6,000계약)로, 당일 만기 $27C 블록($145K·$100K)과 12/18 $30C Above Ask 스윕이 동반되며 강한 상방 모멘텀을 보였습니다.', 16: '📌 **Top 10 문샷(고배수) 플로우 해석**: **BABA 2027-01 $120C($1.5M+$1.3M)**, **PCG 12/31 $15C($1.2M)**, 그리고 **CRWV 12/18 $65C($771K Above Ask)** 및 2027-01 $95C($170K) 등 중장기 대박성 외가격 콜 매수가 집중됐습니다.', 17: '📌 **Top 10 개별주 플로우 해석**: 상위권은 BA(230P·220P 합산 $68.9M), GOOG(480P $26.3M), MRVL(145P $19.0M), GLW(200P $18.3M), MU(650P $9.6M) 등 **대형 풋 헤지**가 지배했고, 하단 9·10위에 **GOOGL 2027-12 $440C($8.4M)**와 **NVDA 2027-03 $250C($7.9M)** 장기 콜이 들어왔습니다.', 18: '📌 **Top 10 ETF(SPX) 플로우 해석**: SPX 지수에서는 2026-12 ~ 2027-03 만기 **8000P($279M·$146.4M·$143.3M)**와 7000P/7500P 등 초대형 장기 풋 포지션이 대거 출현한 가운데, 11/20 만기 **7000C($126.3M)** 단기 콜도 동반 거래됐습니다.', 19: '📌 **최근 5일 개별주 누적 수급 해석**: 5일간 거래대금 1위는 **NVDA($1,437.5M, 풋 59%, 1.8x)**로 약세 헤지 압력이 가장 컸고 MU(풋 62%)·INTC(풋 58%)도 풋 우위였습니다. 반면 **TSLA($220.5M, 풋 24%)·AMZN(풋 24%)·PCG(풋 0%)**는 콜 우위 흐름을 유지했습니다.'}
        _seed_mail_20261113["섹션해석"] = _seed_ko_map_20261113
        _seed_ko_body_20261113 = {0: '• 📈 **Modine (MOD)**: 삼성전자의 인수 협상 보도 이후 시간외 거래에서 약 29% 급등하며, 트레이더들이 AI 데이터센터 수요를 반영해 기업가치를 재평가함.\n• 📊 **미국 매크로 (PPI)**: 월간 생산자물가 상승률은 둔화됐으나 연간 도매 물가는 여전히 높은 수준을 유지해 연준의 긴축 기조 장기화 전망을 강화함.\n• 📈 **HawkEye 360 (HAWK)**: 3분기 사상 최대 매출 $59.3M를 기록하고 ISA 및 해외 수요를 근거로 2026년 매출 가이던스를 $225M~$227M로 상향함.\n• 🚀 **Cerebras Systems**: 마이크로소프트(MS) 클라우드 계약 체결 후 비GAAP 핵심 매출 $231M를 발표하고 4분기·연간 핵심 가이던스를 상향해 옵션 수급 관심 증가 예상.\n• ⚙️ **Applied Materials (AMAT)**: AI 칩 수요에 힘입어 4분기 사상 최대 매출 $10.41B·비GAAP EPS $4.16를 기록하고, FY27 1분기 매출 가이던스를 약 $11.1B로 제시함.\n• ⚠️ **Microsoft (MSFT)**: 11월 12일 서버 장애로 Outlook·Teams·Microsoft 365가 중단되었으며 MS는 예기치 못한 서버 불능을 원인으로 지목하고 배포를 일시 중지함.', 1: '• **NVDA 혼란 속 AI 반도체 지속적 하방 헤지**\n  - *전망*: 약세 (강도 5/5) | *단계*: 진행 중 (2026-10-5 12:25 PM 최초 포착)\n  - *이유*: NVDA가 5일간 약 15% 하락한 가운데 기술주 옵션 플로우는 여전히 풋에 편중되어 있으며, NVDA·MU·MRVL의 단기·장기물 모두 대규모 헤지가 유입됨. CEO 교체, AI 거버넌스 조사, 다음 주 실적을 앞두고 기관은 공격적 상방 베팅보다 AI 칩 익스포저 방어에 집중하는 모습.\n• **모기지 리츠(REITs) 풋 수요와 함께 부동산 섹터 압력 재개**\n  - *전망*: 약세 (강도 5/5) | *단계*: 진행 중 (2026-11-12 12:25 PM 포착)\n  - *이유*: 부동산 섹터가 당일 약 2% 하락하며 일간·주간 옵션 프리미엄의 약 95%가 풋에 집중. 반복적인 AGNC $8 풋 블록과 끈적한 인플레 지표로 금리 민감 부동산·모기지 리츠에 하방 방어 수요 지속.\n• **커뮤니케이션 서비스 대형주 대규모 하방 헤지 직면**\n  - *전망*: 약세 (강도 5/5) | *단계*: 신규 포착 (2026-11-13 4:25 PM)\n  - *이유*: 일간 프리미엄의 약 80%, 시간대별 프리미엄의 거의 전부가 풋에 쏠리며 GOOG·GOOGL·NBIS에 대규모 딥 OTM 하방 풋 블록 유입. 현물 측 강한 매도 분배(Distribution)도 대형 인터넷주 비중 축소·장기 헤지 신호를 뒷받침.\n• **지정학·인플레 리스크 속 에너지 및 우라늄 강세 유지**\n  - *전망*: 강세 (강도 4/5) | *단계*: 진행 중 (2026-11-12 1:25 PM 포착)\n  - *이유*: 일간·주간 모두 상승세를 유지하며 XOM과 우라늄 대장주 CCJ에서 콜 우위 플로우 기록. 이란 긴장과 고착화된 생산자 물가가 원자재 생산 기업을 금리·물가 충격 헤지 수단으로 부각시킴.\n• **헬스케어 혁신주, 장기 상방 포지셔닝 지속 유입**\n  - *전망*: 강세 (강도 4/5) | *단계*: 진행 중 (2026-11-12 12:25 PM 포착)\n  - *이유*: 주간 기준 헬스케어 옵션 플로우가 콜 우위를 유지하며 다년물 OTM CYTK 콜 포지셔닝이 두드러짐. 섹터 전반의 다크풀 매집이 확인되는 가운데 IONS 등 개별 약세 종목만 풋으로 헤지하는 양상.', 2: '• **[2026-11-13 3:19 PM] BA $230 PUT 2027-01-15 @ $30.9M (Top Position · 블록)**\n  - *의도*: 헤지 (강도 5/5) | *이유*: 미결제약정(OI)의 1.5배 규모 딥 ITM 2027년 보잉 풋 블록. 산업재 전반의 강한 현물 매집을 고려하면 방향성 숏보다 대형 장기 보유자의 개별 리스크 보험 성격.\n• **[2026-11-13 3:17 PM] GOOG $480 PUT 2027-01-15 @ $26.3M (Top Position · 스플릿)**\n  - *의도*: 헤지 (강도 5/5) | *이유*: 당일 GOOG 프리미엄 대부분이 풋에 집중된 가운데 기존 OI를 소폭 상회하는 신규 Top Position 딥 ITM 장기 풋. 커뮤니케이션 섹터 현물 분배 흐름 속 대형 인터넷주 장기 약세 대비 포트폴리오 헤지.\n• **[2026-11-13 1:50 PM] MRVL $145 PUT 2027-01-15 @ $19.0M (Top Position · 스플릿)**\n  - *의도*: 헤지 (강도 5/5) | *이유*: OI의 약 5배 규모로 체결된 OTM 2027년 마벨 풋 블록. 주간 프리미엄이 압도적으로 풋에 치우친 가운데 NVDA·MU와 함께 AI 반도체 익스포저 보험을 강화하는 흐름.\n• **[2026-11-13 9:35 AM] MU $650 PUT 2027-03-19 @ $9.6M (스윕)**\n  - *의도*: 헤지 (강도 4/5) | *이유*: 5일간 약 10% 상승한 마이크론의 수익을 고정하고 AI 메모리 조정에 대비하기 위해 기존 OI에 근접한 규모로 유입된 2027년 3월물 고행사가 풋 스윕.\n• **[2026-11-13 10:19 AM] TSLA $320 PUT 2026-12-11 @ $2.6M (Unusual · 골든 스윕)**\n  - *의도*: 헤지 (강도 4/5) | *이유*: OI의 27배 규모로 터진 12월물 TSLA $320 풋 골든 스윕. 주간 콜 우위 및 5일간 두 자릿수 상승 흐름 속 매크로·개별 이벤트 리스크 대비 하방 보호 락인.\n• **[2026-11-13 10:05 AM] PCG $15 CALL 2026-12-31 @ $1.2M (Top Position · 블록)**\n  - *의도*: 포지셔닝 (강도 4/5) | *이유*: 주간 옵션이 거의 전부 콜인 방어주 유틸리티 PCG에 연말 만기 소폭 OTM 콜 Top Position을 구축한 의도적 상방 베팅.', 3: '• **NVDA 베어 풋 스프레드 (Bear Put Spread)**\n  - *전망*: 약세 (강도 5/5) | *전략*: 향후 2~6주 만기·등가격 부근 행사가로 실적 전후 하방에 베팅하되 변동성 평균 회귀 시 프리미엄·Vega 부담을 제한.\n  - *이유*: NVDA 5일간 -15% 하락, Ask 측 풋·골든 스윕 지배(SMH·SOXL도 동일), CEO 사임 및 다음 주 실적으로 변동성이 높아 리스크 한정형 하방 구조가 기관 포지션과 일치.\n• **GOOG 베어 풋 스프레드 (Bear Put Spread)**\n  - *전망*: 약세 (강도 4/5) | *전략*: 약 1~3개월 만기·등가격 부근 행사가로 증가하는 하방 헤지에 동참하면서 횡보 시 캐리 비용 제한.\n  - *이유*: $26.3M 2027년 $480P Top Position 및 근월물 풋 블록과 현물 분배 데이터로 미루어 기관들이 금리·AI 규제 리스크 속 대형 인터넷주 디레이팅을 방어 중.\n• **CCJ 롱 콜 (Long Call)**\n  - *전망*: 강세 (강도 4/5) | *전략*: 2~6주 만기 등가격/소폭 OTM 콜로 우라늄 상승 모멘텀 포착(에너지 뉴스 반전 시 급변동 유의).\n  - *이유*: 최근 골든 스윕 콜이 OI를 받쳐주며 이란 긴장·PPI 고착화 속 원자재 연동 인플레 헤지 수요 집중.\n• **CYTK 롱 콜 (Long Call)**\n  - *전망*: 강세 (강도 4/5) | *전략*: 1~3개월 이상 만기 소폭 OTM 콜로 기관의 LEAPS 스타일 장기 포지셔닝 추종(바이오 이진 리스크로 비중 제한).\n  - *이유*: 주간 옵션 프리미엄 전체가 장기 OTM 콜에 쏠려 있으며 헬스케어 전반의 현물·옵션 매집과 맞물림.\n• **PCG 불 콜 스프레드 (Bull Call Spread)**\n  - *전망*: 강세 (강도 4/5) | *전략*: 1~3개월 만기 현재가 부근~소폭 상단 행사가로 방어주 초과 수익을 노리면서 유틸리티 주도력 약화 시 리스크 상한 설정.\n  - *이유*: 5일간 유틸리티 섹터 강세 속 12월 $15C 블록 등 콜 중심 수급으로, 매파적 연준 환경의 저베타 캐리 수단으로 활용 중.', 4: '**특이 외가격(Unusual OTM) 비중 Top 10:**\n• MRVL - 72%\n• ASTS - 38%\n• CIFR - 38%\n• MSTR - 38%\n• MU - 37%\n• DELL - 37%\n• GNLX - 34%\n• TSLA - 34%\n• SPCE - 33%\n• AG - 31%', 5: '**CIFR 체결 내역**\n• 총 1건 체결 · 풋 비중 0% · 특이 OTM 38%\n• 특이 계약 수: 8K계약 · 특이 프리미엄: $308K\n• [09:56 AM] CIFR $9 콜 2026-12-18 @ $308K (Unusual · Top Position · 블록)', 6: '**GNLX 체결 내역**\n• 총 1건 체결 · 풋 비중 0% · 특이 OTM 34%\n• 특이 계약 수: 265계약 · 특이 프리미엄: $12K\n• [02:50 PM] GNLX $2.5 콜 2026-12-18 @ $12K (Unusual · 스윕)', 7: '**RDW 체결 내역**\n• 총 1건 체결 · 풋 비중 0% · 특이 OTM 29%\n• 특이 계약 수: 1K계약 · 특이 프리미엄: $16K\n• [03:11 PM] RDW $10 콜 2026-12-18 @ $16K (Unusual · 스윕)', 8: '**스윕 거래량(Sweep Volume) Top 10:**\n• NVDA - 858K\n• TSLA - 182K\n• AAPL - 82K\n• CRWV - 35K\n• IREN - 32K\n• APLD - 30K\n• INTC - 27K\n• PLTR - 26K\n• MU - 24K\n• GOOGL - 23K', 9: '**VKTX 스윕 체결 내역**\n• 총 8건 체결 · 풋 비중 0% · 스윕 OTM 2% · 4K계약 · $220K 스윕 프리미엄\n• [02:45 PM] VKTX $30 콜 2026-12-18 @ $98K (Above Ask · 스윕)\n• [12:59 PM] VKTX $27 콜 2026-11-13 @ $145K (Top Position · 블록)\n• [12:20 PM] VKTX $30 콜 2026-11-13 @ $38K (스윕) / $28K (스윕)\n• [12:18 PM] VKTX $30 콜 2026-11-13 @ $19K (스윕)\n• [11:39 AM] VKTX $29.5 콜 2026-11-13 @ $14K (스윕)\n• [11:37 AM] VKTX $27 콜 2026-11-13 @ $100K (Top Position · 블록)\n• [11:16 AM] VKTX $27 콜 2026-11-13 @ $23K (Top Position · 스윕)', 10: '**SNDK 스윕 체결 내역**\n• 총 6건 체결 · 풋 비중 0% · 스윕 OTM 7% · 3K계약 · $2.5M 스윕 프리미엄\n• [02:40 PM] SNDK $1060 콜 2026-11-20 @ $270K (Unusual · Top Position · 블록)\n• [02:32 PM] SNDK $880 콜 2026-11-13 @ $87K (스윕)\n• [02:10 PM] SNDK $885 콜 2026-11-13 @ $37K (Top Position · 스윕)\n• [10:46 AM] SNDK $1000 콜 2026-11-20 @ $1.0M (Unusual · Above Ask · 스윕)\n• [10:13 AM] SNDK $850 콜 2026-11-13 @ $671K (스윕) / $669K (스윕)', 11: '**CCC 스윕 체결 내역**\n• 총 6건 체결 · 풋 비중 0% · 스윕 OTM -3% · 7K계약 · $174K 스윕 프리미엄\n• [01:27 PM] CCC $7.5 콜 2026-12-18 @ $20K (스윕)\n• [12:25 PM] CCC $7.5 콜 2026-12-18 @ $24K (스윕)\n• [12:15 PM] CCC $7.5 콜 2026-12-18 @ $13K (스플릿)\n• [12:13 PM] CCC $7.5 콜 2026-12-18 @ $18K (스윕)\n• [12:11 PM] CCC $7.5 콜 2026-12-18 @ $27K (스윕)\n• [12:10 PM] CCC $7.5 콜 2026-12-18 @ $85K (스윕)', 12: '**일평균 대비 거래량 급증(모멘텀) Top 10:**\n• NIO - 15.5배\n• XOM - 13.9배\n• SO - 13.6배\n• SPCE - 10.1배\n• VKTX - 7.8배\n• CCC - 6.7배\n• BEKE - 5.2배\n• PLCE - 5.1배\n• KO - 3.8배\n• BNC - 3.1배', 13: '**NIO 모멘텀 체결 내역**\n• 총 6건 · 풋 비중 100% · 모멘텀 15.5배 · 총 26K계약 · $292K\n• [02:48 PM] NIO $2.5 풋 2027-01-15 @ $24K (스윕) / $36K (스윕)\n• [12:39 PM] NIO $2 풋 2027-02-19 @ $24K (Top Position · 스윕)\n• [12:39 PM] NIO $3 풋 2027-01-15 @ $96K (블록) / $2 풋 @ $48K (블록)\n• [12:36 PM] NIO $3 풋 2027-01-15 @ $64K (블록)', 14: '**SO 모멘텀 체결 내역**\n• 총 4건 · 풋 비중 100% · 모멘텀 13.6배 · 총 3K계약 · $415K\n• [01:08 PM] SO $75 풋 2027-12-17 @ $96K (Top Position · 스윕)\n• [12:12 PM] SO $75 풋 2027-09-17 @ $106K (Top Position · 스윕) / $95K (스윕)\n• [12:08 PM] SO $75 풋 2027-09-17 @ $119K (Top Position · 스윕)', 15: '**VKTX 모멘텀 체결 내역**\n• 총 8건 · 풋 비중 0% · 모멘텀 7.8배 · 총 6K계약 · $465K\n• [02:45 PM] VKTX $30 콜 2026-12-18 @ $98K (Above Ask · 스윕)\n• [12:59 PM] VKTX $27 콜 2026-11-13 @ $145K (Top Position · 블록)\n• [12:20 PM] VKTX $30 콜 2026-11-13 @ $38K / $28K (스윕)\n• [12:18 PM] VKTX $30 콜 2026-11-13 @ $19K (스윕)\n• [11:39 AM] VKTX $29.5 콜 2026-11-13 @ $14K (스윕)\n• [11:37 AM] VKTX $27 콜 2026-11-13 @ $100K (Top Position · 블록)\n• [11:16 AM] VKTX $27 콜 2026-11-13 @ $23K (Top Position · 스윕)', 16: '**Top 10 문샷(고배수) 플로우:**\n• [10:05 AM] PCG $15 콜 2026-12-31 @ $1.2M (Top Position · 블록)\n• [02:50 PM] GNLX $2.5 콜 2026-12-18 @ $12K (Unusual · 스윕)\n• [10:10 AM] BABA $120 콜 2027-01-15 @ $1.3M (블록)\n• [10:07 AM] BABA $120 콜 2027-01-15 @ $1.5M (블록)\n• [03:27 PM] CRWV $82 콜 2026-12-04 @ $23K (Unusual · Top Position · 스윕)\n• [09:56 AM] CIFR $9 콜 2026-12-18 @ $308K (Unusual · Top Position · 블록)\n• [03:40 PM] CRWV $95 콜 2027-01-15 @ $170K (스윕)\n• [11:58 AM] EIX $70 콜 2026-12-18 @ $200K (Unusual · Top Position · 블록)\n• [10:19 AM] RKT $16 콜 2026-12-18 @ $230K (Unusual · 블록)\n• [03:47 PM] CRWV $65 콜 2026-12-18 @ $771K (Unusual · Above Ask · 스플릿)', 17: '**Top 10 개별주 플로우:**\n• [03:19 PM] BA $230 풋 2027-01-15 @ $30.9M (Top Position · 블록)\n• [03:17 PM] GOOG $480 풋 2027-01-15 @ $26.3M (Top Position · 스플릿)\n• [01:50 PM] MRVL $145 풋 2027-01-15 @ $19.0M (Top Position · 스플릿)\n• [03:10 PM] GLW $200 풋 2026-12-18 @ $18.3M (스플릿)\n• [03:10 PM] BA $220 풋 2026-11-20 @ $16.1M (스플릿)\n• [03:18 PM] BA $230 풋 2026-12-18 @ $11.9M (Top Position · 블록)\n• [03:10 PM] BA $230 풋 2026-12-18 @ $10.0M (Top Position · 블록)\n• [09:35 AM] MU $650 풋 2027-03-19 @ $9.6M (스윕)\n• [10:35 AM] GOOGL $440 콜 2027-12-17 @ $8.4M (Top Position · 스플릿)\n• [09:34 AM] NVDA $250 콜 2027-03-19 @ $7.9M (스윕)', 18: '**Top 10 ETF(SPX) 플로우:**\n• [11:57 AM] SPX 8000 풋 2027-02-19 @ $279.0M (스플릿)\n• [11:23 AM] SPX 8000 풋 2027-03-19 @ $146.4M (블록)\n• [11:23 AM] SPX 8000 풋 2026-12-18 @ $143.3M (스플릿)\n• [12:56 PM] SPX 7000 콜 2026-11-20 @ $126.3M (스플릿)\n• [11:57 AM] SPX 7000 풋 2027-02-19 @ $61.5M (Above Ask · 스플릿)\n• [10:29 AM] SPX 7500 풋 2027-03-19 @ $60.1M (Above Ask · 스플릿)\n• [12:54 PM] SPX 7725 콜 2027-03-19 @ $44.8M (Top Position · 스플릿)\n• [11:23 AM] SPX 7000 풋 2027-03-19 @ $39.6M (스플릿)\n• [10:29 AM] SPX 7475 풋 2026-12-18 @ $31.3M (Above Ask · 스플릿)\n• [12:54 PM] SPX 7600 콜 2026-12-18 @ $23.8M (스플릿)', 19: '**개별주 최근 5일 누적 플로우:**\n• NVDA | 풋 59% | OTM 13% | 1.8배 | 4.4M계약 | $1,437.5M\n• TSLA | 풋 24% | OTM 5% | 0.7배 | 781K계약 | $220.5M\n• AAPL | 풋 32% | OTM 2% | 0.6배 | 440K계약 | $89.3M\n• INTC | 풋 58% | OTM 1% | 0.5배 | 314K계약 | $289.6M\n• PCG | 풋 0% | OTM 17% | 2.0배 | 237K계약 | $13.1M\n• AMZN | 풋 24% | OTM 5% | 0.6배 | 219K계약 | $51.5M\n• CRWV | 풋 48% | OTM 27% | 1.3배 | 218K계약 | $47.2M\n• MU | 풋 62% | OTM 12% | 1.0배 | 185K계약 | $242.6M\n• GFL | 풋 0% | OTM 16% | 5.4배 | 168K계약 | $5.2M\n• AMD | 풋 46% | OTM 8% | 1.2배 | 163K계약 | $115.2M'}
        _seed_mail_20261113["섹션번역"] = _seed_ko_body_20261113
        _matched_seed = False
        for _lm in local_mails:
            if _lm.get("id") == _seed_mail_20261113["id"] or "Evening Edge 2026-11-13" in _lm.get("제목", ""):
                if not _lm.get("이미지"):
                    _lm["이미지"] = _seed_images_20261113
                if not _lm.get("html"):
                    _lm["html"] = _seed_html_20261113
                _lm["요약"] = _seed_mail_20261113["요약"]
                if not _lm.get("섹션해석"):
                    _lm["섹션해석"] = _seed_ko_map_20261113
                if not _lm.get("섹션번역"):
                    _lm["섹션번역"] = _seed_ko_body_20261113
                _matched_seed = True
                break
        if not _matched_seed:
            local_mails.insert(0, _seed_mail_20261113)
        save_json_file(INSIDER_MAIL_PATH, local_mails[:100])
        try:
            with open(_seed_flag_20261113, "w", encoding="utf-8") as _sf:
                _sf.write("1")
        except Exception:
            pass

    @st.cache_data(ttl=120, show_spinner=False)
    def _fetch_ords_mails():
        import urllib.request
        try:
            req = urllib.request.Request(ORDS_MAIL_URL, headers={"User-Agent": "OptionHub/1.0"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                raw = json.loads(resp.read().decode("utf-8"))
            items = raw.get("items") if isinstance(raw, dict) else (raw if isinstance(raw, list) else [])
            out = []
            for it in items:
                if not isinstance(it, dict):
                    continue
                subj = it.get("subject") or it.get("title") or it.get("mail_subject") or "InsiderFinance 리포트"
                body = it.get("body") or it.get("content") or it.get("mail_body") or it.get("summary") or ""
                dt = it.get("received_at") or it.get("created_at") or it.get("mail_date") or "-"
                src_n = it.get("source") or it.get("sender") or "InsiderFinance"
                mid = str(it.get("id") or f"ords_{hash(str(subj)+str(dt))}")
                out.append({
                    "id": mid,
                    "날짜": str(dt)[:16],
                    "출처": str(src_n),
                    "제목": str(subj),
                    "원문": str(body),
                    "html": str(it.get("html_body") or it.get("html") or ""),
                    "요약": str(it.get("ko_summary") or ""),
                    "종목": ", ".join(extract_silpi_symbols(str(subj) + " " + str(body))[:5]) or "공통",
                })
            return out, True
        except Exception as _e:
            return [], False

    im_c1, im_c2 = st.columns([3.0, 1.0])
    if im_c2.button("🔄 메일 새로고침", use_container_width=True, key="btn_ins_refresh"):
        _fetch_ords_mails.clear()
        st.rerun()

    ords_mails, ords_ok = _fetch_ords_mails()
    # 로컬 수신함 + ORDS 통합 (중복 제목 제거)
    merged_mails = list(local_mails)
    seen_titles = {m.get("제목", "") for m in merged_mails}
    for om in ords_mails:
        if om.get("제목") not in seen_titles:
            merged_mails.append(om)
            seen_titles.add(om.get("제목", ""))

    im_c1.info(
        f"📡 Oracle ORDS 연동: **{'정상' if ords_ok else '로컬 수신함 모드'}** · "
        f"총 **{len(merged_mails)}건** (로컬 {len(local_mails)}건 + ORDS {len(ords_mails)}건)"
    )

    with st.expander("➕ 아침 메일 수동 붙여넣기 → AI 한국어 번역·저장", expanded=(len(merged_mails) == 0)):
        mi_subj = st.text_input("메일 제목", "", placeholder="예: Evening Edge - Unusual Options Activity (11/15)", key="ins_in_subj")
        mi_body = st.text_area("메일 본문 붙여넣기", height=120, placeholder="InsiderFinance 메일 본문을 그대로 붙여넣으세요...", key="ins_in_body")
        mi_b1, mi_b2 = st.columns(2)
        if mi_b1.button("🤖 AI 한국어 요약 후 저장", type="primary", use_container_width=True, key="btn_ins_add_ai"):
            if mi_body.strip() or mi_subj.strip():
                with st.spinner("Gemini AI가 메일을 한국어로 요약 중입니다..."):
                    _tks_m = ", ".join(extract_silpi_symbols(mi_subj + " " + mi_body)[:5]) or "공통"
                    _pr_m = (
                        "다음 미국 옵션 메일(InsiderFinance 등)을 트레이더용으로 한국어 요약해 주세요.\n"
                        "1) 핵심 3줄 요약\n2) 주요 종목·행사가·콜/풋·프리미엄\n3) 주목할 방향성/레벨\n\n제목: "
                        + mi_subj + "\n본문:\n" + mi_body[:6000]
                    )
                    _, _ko_m = run_ai_analysis(_pr_m)
                    local_mails.insert(0, {
                        "id": f"ins_{int(time.time()*1000)}",
                        "날짜": pd.Timestamp.now(tz="Asia/Seoul").strftime("%Y-%m-%d %H:%M"),
                        "출처": "InsiderFinance",
                        "제목": mi_subj.strip() or (mi_body.strip().splitlines()[0][:55] if mi_body.strip() else "InsiderFinance 메일"),
                        "원문": mi_body.strip(),
                        "요약": _ko_m,
                        "종목": _tks_m,
                    })
                    save_json_file(INSIDER_MAIL_PATH, local_mails[:100])
                    st.success("✅ AI 요약과 함께 저장되었습니다!")
                    st.rerun()
        if mi_b2.button("💾 원문만 바로 저장", use_container_width=True, key="btn_ins_add_raw"):
            if mi_body.strip() or mi_subj.strip():
                _tks_m = ", ".join(extract_silpi_symbols(mi_subj + " " + mi_body)[:5]) or "공통"
                local_mails.insert(0, {
                    "id": f"ins_{int(time.time()*1000)}",
                    "날짜": pd.Timestamp.now(tz="Asia/Seoul").strftime("%Y-%m-%d %H:%M"),
                    "출처": "InsiderFinance",
                    "제목": mi_subj.strip() or (mi_body.strip().splitlines()[0][:55] if mi_body.strip() else "InsiderFinance 메일"),
                    "원문": mi_body.strip(),
                    "요약": "",
                    "종목": _tks_m,
                })
                save_json_file(INSIDER_MAIL_PATH, local_mails[:100])
                st.success("✅ 저장되었습니다!")
                st.rerun()

    # 검색 필터
    f_ins1, f_ins2 = st.columns([2.5, 1.0])
    ins_kw = f_ins1.text_input("🔍 메일 검색 (종목 · 제목 · 내용)", "", key="ins_kw").strip().lower()
    ins_tk_filter = f_ins2.text_input("티커 필터", "", placeholder="예: SOXL, NVDA", key="ins_tk_f").strip().upper()

    shown_mails = []
    for mm in merged_mails:
        blob = (mm.get("제목", "") + " " + mm.get("요약", "") + " " + mm.get("원문", "") + " " + mm.get("종목", "")).lower()
        if ins_kw and ins_kw not in blob:
            continue
        if ins_tk_filter and ins_tk_filter not in blob.upper():
            continue
        shown_mails.append(mm)

    st.caption(f"표시 중인 메일: {len(shown_mails)}건")
    for idx_m, mm in enumerate(shown_mails[:30]):
        mid = mm.get("id", str(idx_m))
        with st.container(border=True):
            mc1, mc2, mc3, mc4 = st.columns([4.0, 1.2, 1.0, 0.8])
            mc1.markdown(f"**[{mm.get('출처','InsiderFinance')}] {mm.get('제목','')}**  `{mm.get('종목','공통')}` · {mm.get('날짜','')}")
            if mc2.button("🤖 AI 요약", key=f"ins_ai_{mid}"):
                with st.spinner("Gemini AI로 한국어 요약 중..."):
                    _pr_i = (
                        "다음 옵션 메일을 한국어로 핵심만 요약해 주세요(3줄 요약 + 주요 종목·행사가·프리미엄 + 매매 포인트):\n"
                        + mm.get("제목", "") + "\n" + mm.get("원문", "")[:6000]
                    )
                    _, _ko_i = run_ai_analysis(_pr_i)
                    mm["요약"] = _ko_i
                    # 로컬 목록에 반영
                    found_l = False
                    for lm in local_mails:
                        if lm.get("id") == mid or lm.get("제목") == mm.get("제목"):
                            lm["요약"] = _ko_i
                            found_l = True
                            break
                    if not found_l:
                        local_mails.insert(0, mm)
                    save_json_file(INSIDER_MAIL_PATH, local_mails[:100])
                    st.rerun()
            if mc3.button("📩 텔레그램", key=f"ins_tg_{mid}"):
                _tg_m = mm.get("요약") if (mm.get("요약") and len(mm.get("요약","")) > 200) else f"📬 [{mm.get('출처','InsiderFinance')}] {mm.get('제목','')}\n종목: {mm.get('종목','')}\n\n{(mm.get('요약') or mm.get('원문',''))[:7000]}"
                if send_telegram_msg(tg_token, tg_chat_id, _tg_m)[0]:
                    st.toast("✅ 텔레그램 전송 완료!")
                else:
                    st.toast("⚠️ 텔레그램 설정을 확인해 주세요.")
            if mc4.button("🗑️", key=f"ins_del_{mid}"):
                local_mails = [z for z in local_mails if z.get("id") != mid]
                save_json_file(INSIDER_MAIL_PATH, local_mails)
                st.rerun()

            _html_doc = mm.get("html") or (mm.get("원문") if "<html" in (mm.get("원문") or "").lower() or "<table" in (mm.get("원문") or "").lower() else "")
            _secs = parse_insider_html_sections(_html_doc) if _html_doc else []
            _sec_ko = dict(mm.get("섹션해석") or {})
            _sec_ko_norm = {str(k): v for k, v in _sec_ko.items()}
            _sec_tr = dict(mm.get("섹션번역") or {})
            _sec_tr_norm = {str(k): v for k, v in _sec_tr.items()}

            if _secs:
                _lang_col, _btn_col, _cal_btn_col = st.columns([1.2, 1.5, 1.5])
                _body_lang = _lang_col.radio(
                    "본문 표시 언어",
                    ["🇰🇷 한글 번역", "🇺🇸 영문 원문"],
                    horizontal=True,
                    key=f"ins_lang_{mid}",
                    label_visibility="collapsed",
                )
                if _btn_col.button(f"🤖 전체 {len(_secs)}개 섹션 Gemini 일괄 번역·해석", key=f"ins_all_sec_{mid}", use_container_width=True):
                    with st.spinner("Gemini가 모든 섹션을 순서대로 해석 중입니다..."):
                        for _si, _sc in enumerate(_secs):
                            if not _sec_tr_norm.get(str(_si)) and _sc.get("en"):
                                _pr_tr = (
                                    f"다음 미국 옵션 뉴스레터 섹션('{_sc['title']}')의 영문 불릿/수치를 누락 없이 자연스러운 한국어 불릿으로 직역해 주세요:\n\n"
                                    + _sc["en"][:2500]
                                )
                                _, _tr_s = run_ai_analysis(_pr_tr)
                                _sec_tr_norm[str(_si)] = _tr_s.strip()
                            if not _sec_ko_norm.get(str(_si)):
                                _pr_s = (
                                    f"다음 미국 옵션 뉴스레터 섹션('{_sc['title']}')을 한국어 트레이더 관점에서 2~3문장으로 핵심만 해석해 주세요.\n\n"
                                    + _sc["en"][:2500]
                                )
                                _, _ko_s = run_ai_analysis(_pr_s)
                                _sec_ko_norm[str(_si)] = "📌 **Gemini 해석**: " + _ko_s.strip()
                        mm["섹션해석"] = _sec_ko_norm
                        mm["섹션번역"] = _sec_tr_norm
                        _f_upd = False
                        for _lm in local_mails:
                            if _lm.get("id") == mid or _lm.get("제목") == mm.get("제목"):
                                _lm["섹션해석"] = _sec_ko_norm
                                _lm["섹션번역"] = _sec_tr_norm
                                _f_upd = True
                                break
                        if not _f_upd:
                            local_mails.insert(0, mm)
                        save_json_file(INSIDER_MAIL_PATH, local_mails[:100])
                        st.rerun()
                if _cal_btn_col.button("📅 캘린더 일괄 등록 (해석 포함)", key=f"ins_cal_all_{mid}", use_container_width=True):
                    with st.spinner("인사이더 섹션별 Gemini 해석을 포함해 캘린더에 등록 중..."):
                        _gcal_p = os.path.expanduser("~/.optionhub_gcal_events.json")
                        _gcal_list = load_json_file(_gcal_p, [])
                        _gcal_idx = {e.get("id"): i for i, e in enumerate(_gcal_list) if e.get("id")}
                        _added_cnt = 0
                        for _si, _sc in enumerate(_secs):
                            _evs_new, _ko_upd = build_insider_section_gcal_events(
                                mm, _sc, _si,
                                tr_val=_sec_tr_norm.get(str(_si), ""),
                                ko_val=_sec_ko_norm.get(str(_si), ""),
                                auto_ai=True,
                            )
                            if _ko_upd and not _sec_ko_norm.get(str(_si)):
                                _sec_ko_norm[str(_si)] = _ko_upd
                            for _evn in _evs_new:
                                if _evn["id"] in _gcal_idx:
                                    _gcal_list[_gcal_idx[_evn["id"]]] = _evn
                                else:
                                    _gcal_list.append(_evn)
                                    _gcal_idx[_evn["id"]] = len(_gcal_list) - 1
                                _added_cnt += 1
                        save_json_file(_gcal_p, _gcal_list)
                        mm["섹션해석"] = _sec_ko_norm
                        for _lm in local_mails:
                            if _lm.get("id") == mid or _lm.get("제목") == mm.get("제목"):
                                _lm["섹션해석"] = _sec_ko_norm
                                break
                        save_json_file(INSIDER_MAIL_PATH, local_mails[:100])
                        st.toast(f"✅ 구글 캘린더에 해석 포함 {_added_cnt}건 등록 완료!")

                if mm.get("요약"):
                    with st.expander("📋 전체 핵심 3줄 요약 보기", expanded=False):
                        st.markdown(mm["요약"].replace("\n", "  \n"))

                for _si, _sc in enumerate(_secs):
                    with st.container(border=True):
                        _stitle = _sc["title"]
                        _tk_m = re.search(r'Top Ticker\s+([A-Z]{1,6})', _stitle)
                        if _tk_m:
                            _tksym = _tk_m.group(1)
                            _hc1, _hc2 = st.columns([3.0, 2.0])
                            _hc1.markdown(f"### {_stitle}")
                            _hc2.markdown(
                                f"[Flow ›](https://www.insiderfinance.io/ticker-flow/{_tksym}) · "
                                f"[GEX ›](https://www.insiderfinance.io/gamma-exposure/{_tksym}) · "
                                f"[P&L ›](https://www.insiderfinance.io/options-profit-calculator/strategy/long-call/{_tksym})"
                            )
                        else:
                            st.markdown(f"### {_stitle}")

                        # 1) 사진
                        if _sc.get("img"):
                            st.image(_sc["img"], use_container_width=True)

                        # 2) 밑에 본문 (기본: 한글 번역 / 전환 시 영문 원문)
                        _tr_val = _sec_tr_norm.get(str(_si), "")
                        if _body_lang == "🇰🇷 한글 번역" and _tr_val:
                            st.markdown(_tr_val.replace("\n", "  \n"))
                        elif _sc.get("en"):
                            st.markdown(_sc["en"].replace("\n", "  \n"))

                        # 3) Gemini 한국어 해석 + 캘린더 개별 등록
                        _ko_val = _sec_ko_norm.get(str(_si), "")
                        if _ko_val:
                            st.info(_ko_val)
                            if st.button("📅 이 섹션 캘린더 등록 (해석 포함)", key=f"ins_sec_cal_{mid}_{_si}"):
                                _gcal_p = os.path.expanduser("~/.optionhub_gcal_events.json")
                                _gcal_list = load_json_file(_gcal_p, [])
                                _gcal_idx = {e.get("id"): i for i, e in enumerate(_gcal_list) if e.get("id")}
                                _evs_new, _ = build_insider_section_gcal_events(
                                    mm, _sc, _si,
                                    tr_val=_sec_tr_norm.get(str(_si), ""),
                                    ko_val=_ko_val,
                                    auto_ai=False,
                                )
                                for _evn in _evs_new:
                                    if _evn["id"] in _gcal_idx:
                                        _gcal_list[_gcal_idx[_evn["id"]]] = _evn
                                    else:
                                        _gcal_list.append(_evn)
                                save_json_file(_gcal_p, _gcal_list)
                                st.toast(f"✅ '{_stitle}' 해석 포함 {len(_evs_new)}건 캘린더 등록 완료!")
                        else:
                            _sc_b1, _sc_b2 = st.columns(2)
                            if _sc_b1.button("🤖 Gemini로 이 섹션 해석하기", key=f"ins_sec_ai_{mid}_{_si}"):
                                with st.spinner("Gemini 해석 중..."):
                                    _pr_s = (
                                        f"다음 미국 옵션 뉴스레터 섹션('{_stitle}')을 한국어 트레이더 관점에서 2~3문장으로 핵심만 해석해 주세요.\n\n"
                                        + _sc["en"][:2500]
                                    )
                                    _, _ko_s = run_ai_analysis(_pr_s)
                                    _sec_ko_norm[str(_si)] = "📌 **Gemini 해석**: " + _ko_s.strip()
                                    mm["섹션해석"] = _sec_ko_norm
                                    _f_upd = False
                                    for _lm in local_mails:
                                        if _lm.get("id") == mid or _lm.get("제목") == mm.get("제목"):
                                            _lm["섹션해석"] = _sec_ko_norm
                                            _f_upd = True
                                            break
                                    if not _f_upd:
                                        local_mails.insert(0, mm)
                                    save_json_file(INSIDER_MAIL_PATH, local_mails[:100])
                                    st.rerun()
                            if _sc_b2.button("📅 해석 생성 후 캘린더 등록", key=f"ins_sec_cal_ai_{mid}_{_si}"):
                                with st.spinner("Gemini 해석 생성 및 캘린더 등록 중..."):
                                    _gcal_p = os.path.expanduser("~/.optionhub_gcal_events.json")
                                    _gcal_list = load_json_file(_gcal_p, [])
                                    _gcal_idx = {e.get("id"): i for i, e in enumerate(_gcal_list) if e.get("id")}
                                    _evs_new, _ko_upd = build_insider_section_gcal_events(
                                        mm, _sc, _si,
                                        tr_val=_sec_tr_norm.get(str(_si), ""),
                                        ko_val="",
                                        auto_ai=True,
                                    )
                                    for _evn in _evs_new:
                                        if _evn["id"] in _gcal_idx:
                                            _gcal_list[_gcal_idx[_evn["id"]]] = _evn
                                        else:
                                            _gcal_list.append(_evn)
                                    save_json_file(_gcal_p, _gcal_list)
                                    if _ko_upd:
                                        _sec_ko_norm[str(_si)] = _ko_upd
                                        mm["섹션해석"] = _sec_ko_norm
                                        for _lm in local_mails:
                                            if _lm.get("id") == mid or _lm.get("제목") == mm.get("제목"):
                                                _lm["섹션해석"] = _sec_ko_norm
                                                break
                                        save_json_file(INSIDER_MAIL_PATH, local_mails[:100])
                                    st.toast(f"✅ '{_stitle}' Gemini 해석 포함 {len(_evs_new)}건 캘린더 등록 완료!")
                                    st.rerun()

                with st.expander("📄 원본 이메일 HTML 전체 보기", expanded=False):
                    components.html(_html_doc, height=1200, scrolling=True)
            else:
                _imgs = list(mm.get("이미지") or [])
                if not _imgs and mm.get("원문"):
                    _found_img_urls = re.findall(r'https?://[^\s"\'<>]+\.(?:png|jpg|jpeg|webp)', mm.get("원문", ""), flags=re.I)
                    _imgs = [{"제목": f"스냅샷 {_ii+1}", "url": _iu} for _ii, _iu in enumerate(dict.fromkeys(_found_img_urls))]
                if _imgs:
                    for _row_i in range(0, len(_imgs), 2):
                        _gcols = st.columns(2)
                        for _ci in range(2):
                            if _row_i + _ci < len(_imgs):
                                _im_obj = _imgs[_row_i + _ci]
                                _im_u = _im_obj.get("url") if isinstance(_im_obj, dict) else str(_im_obj)
                                _im_t = _im_obj.get("제목", "") if isinstance(_im_obj, dict) else ""
                                _gcols[_ci].image(_im_u, caption=_im_t, use_container_width=True)
                if mm.get("원문"):
                    st.markdown(mm["원문"].replace("\n", "  \n"))
                if mm.get("요약"):
                    st.info(mm["요약"])


if nav_menu == "📅 구글 캘린더":
    st.title("📅 구글 캘린더")

    GCAL_EVENTS_PATH = os.path.expanduser("~/.optionhub_gcal_events.json")
    GCAL_ICS_PATH = os.path.expanduser("~/.optionhub_gcal_ics.txt")
    _gcal_seed_b64 = "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"
    _gcal_seed_flag = os.path.expanduser("~/.optionhub_gcal_seed_v2")

    local_gcal = load_json_file(GCAL_EVENTS_PATH, [])
    if not os.path.exists(_gcal_seed_flag) or not local_gcal:
        try:
            import zlib as _zlib, base64 as _b64
            _seed_evs = json.loads(_zlib.decompress(_b64.b64decode(_gcal_seed_b64)).decode("utf-8"))
            _exist_ids = {e.get("id") for e in local_gcal}
            for _se in _seed_evs:
                if _se.get("id") not in _exist_ids:
                    local_gcal.append(_se)
            save_json_file(GCAL_EVENTS_PATH, local_gcal)
            with open(_gcal_seed_flag, "w", encoding="utf-8") as _gf:
                _gf.write("1")
        except Exception:
            pass

    @st.cache_data(ttl=300, show_spinner=False)
    def _fetch_ics_events(ics_url):
        import urllib.request
        if not ics_url or not ics_url.startswith("http"):
            return []
        try:
            req = urllib.request.Request(ics_url, headers={"User-Agent": "OptionHub/1.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw_ics = resp.read().decode("utf-8", errors="ignore")
            raw_ics = re.sub(r"\r?\n[ \t]", "", raw_ics)
            out = []
            for blk in re.findall(r"BEGIN:VEVENT(.*?)END:VEVENT", raw_ics, flags=re.S):
                sm = re.search(r"SUMMARY[^:]*:(.*)", blk)
                dm = re.search(r"DTSTART[^:]*:(\d{8})", blk)
                um = re.search(r"UID:(.*)", blk)
                descm = re.search(r"DESCRIPTION:(.*)", blk)
                if sm and dm:
                    d_str = f"{dm.group(1)[:4]}-{dm.group(1)[4:6]}-{dm.group(1)[6:8]}"
                    desc_v = descm.group(1).replace("\\n", "\n").strip() if descm else ""
                    out.append({
                        "id": um.group(1).strip() if um else f"ics_{hash(d_str+sm.group(1))}",
                        "date": d_str,
                        "summary": sm.group(1).strip(),
                        "description": desc_v,
                    })
            return out
        except Exception:
            return []

    _saved_ics = ""
    if os.path.exists(GCAL_ICS_PATH):
        try:
            with open(GCAL_ICS_PATH, "r", encoding="utf-8") as _fics:
                _saved_ics = _fics.read().strip()
        except Exception:
            pass

    _ics_evs = _fetch_ics_events(_saved_ics) if _saved_ics else []
    _all_gcal_map = {}
    for _e in (local_gcal + _ics_evs):
        _eid = _e.get("id") or f"ev_{hash(str(_e.get('date',''))+str(_e.get('summary','')))}"
        _all_gcal_map[_eid] = {
            "id": _eid,
            "date": str(_e.get("date", ""))[:10],
            "summary": str(_e.get("summary", "")),
            "description": str(_e.get("description", "")),
        }
    all_gcal_events = sorted(_all_gcal_map.values(), key=lambda x: (x["date"], x["summary"]))
    import base64 as _b64_ev
    _events_b64 = _b64_ev.b64encode(json.dumps(all_gcal_events, ensure_ascii=False).encode("utf-8")).decode("ascii")

    _gcal_html = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8"/>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { background: #131314; color: #e8eaed; font-family: 'Google Sans', 'Inter', -apple-system, BlinkMacSystemFont, sans-serif; overflow: hidden; }
.g-shell { display: flex; flex-direction: column; height: 830px; border: 1px solid #2d2f31; border-radius: 12px; overflow: hidden; background: #131314; }
/* Top Bar */
.g-top { display: flex; align-items: center; justify-content: space-between; padding: 10px 16px; background: #1b1c1e; border-bottom: 1px solid #2d2f31; gap: 10px; flex-wrap: wrap; }
.g-top-l { display: flex; align-items: center; gap: 10px; }
.g-logo { display: flex; align-items: center; gap: 8px; font-size: 18px; font-weight: 600; color: #e8eaed; margin-right: 8px; }
.g-logo-box { width: 28px; height: 28px; border-radius: 6px; background: #1a73e8; color: #fff; display: flex; align-items: center; justify-content: center; font-size: 13px; font-weight: 700; }
.g-btn { background: transparent; color: #e8eaed; border: 1px solid #5f6368; border-radius: 20px; padding: 6px 16px; font-size: 13px; font-weight: 600; cursor: pointer; }
.g-btn:hover { background: #282a2c; }
.g-icon-btn { background: transparent; color: #bdc1c6; border: none; border-radius: 50%; width: 32px; height: 32px; font-size: 16px; cursor: pointer; display: flex; align-items: center; justify-content: center; }
.g-icon-btn:hover { background: #282a2c; color: #fff; }
.g-cur-title { font-size: 20px; font-weight: 500; color: #e8eaed; min-width: 170px; }
.g-top-r { display: flex; align-items: center; gap: 8px; }
.g-search { background: #282a2c; color: #e8eaed; border: 1px solid #3c4043; border-radius: 20px; padding: 6px 14px; font-size: 13px; width: 200px; outline: none; }
.g-search:focus { border-color: #8ab4f8; }
.g-view-grp { display: flex; border: 1px solid #5f6368; border-radius: 20px; overflow: hidden; }
.g-vbtn { background: transparent; color: #bdc1c6; border: none; padding: 6px 13px; font-size: 13px; font-weight: 600; cursor: pointer; }
.g-vbtn:hover { background: #282a2c; }
.g-vbtn.active { background: #c2e7ff; color: #001d35; }

/* Main Body */
.g-body { display: flex; flex: 1; overflow: hidden; }
/* Left Sidebar */
.g-side { width: 224px; min-width: 224px; background: #18191b; border-right: 1px solid #2d2f31; padding: 14px 12px; display: flex; flex-direction: column; gap: 16px; overflow-y: auto; }
.g-create-btn { display: inline-flex; align-items: center; gap: 8px; background: #282a2c; color: #e8eaed; border: 1px solid #3c4043; border-radius: 16px; padding: 10px 18px; font-size: 14px; font-weight: 600; cursor: pointer; box-shadow: 0 2px 6px rgba(0,0,0,0.35); width: fit-content; }
.g-create-btn:hover { background: #333538; }

/* Mini Calendar */
.mini-hdr { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; padding: 0 4px; }
.mini-ym { font-size: 13px; font-weight: 600; color: #e8eaed; }
.mini-grid { display: grid; grid-template-columns: repeat(7, 1fr); text-align: center; row-gap: 3px; }
.mini-dow { font-size: 10.5px; color: #9aa0a6; font-weight: 600; padding-bottom: 4px; }
.mini-day { font-size: 11.5px; width: 26px; height: 26px; line-height: 26px; margin: 0 auto; border-radius: 50%; cursor: pointer; color: #e8eaed; position: relative; }
.mini-day:hover { background: #282a2c; }
.mini-day.other { color: #5f6368; }
.mini-day.today { background: #1a73e8; color: #fff; font-weight: 700; }
.mini-day.sel:not(.today) { background: #394457; color: #a8c7fa; font-weight: 700; }
.mini-dot { width: 4px; height: 4px; border-radius: 50%; background: #e67c73; position: absolute; bottom: 1px; left: 50%; transform: translateX(-50%); }

/* My Calendars */
.cal-sec-t { font-size: 12.5px; font-weight: 600; color: #e8eaed; margin-bottom: 8px; padding-left: 4px; }
.cal-chk { display: flex; align-items: center; gap: 8px; padding: 5px 6px; border-radius: 6px; cursor: pointer; font-size: 12.5px; color: #d2d6dc; user-select: none; }
.cal-chk:hover { background: #282a2c; }
.cal-box { width: 15px; height: 15px; border-radius: 3px; display: inline-flex; align-items: center; justify-content: center; font-size: 11px; font-weight: 700; color: #fff; }

/* Main Content Area */
.g-main { flex: 1; overflow-y: auto; background: #131314; position: relative; }

/* Day View (matches screenshot!) */
.dv-head { display: flex; align-items: flex-start; border-bottom: 1px solid #2d2f31; background: #18191b; padding: 10px 14px 8px 0; position: sticky; top: 0; z-index: 10; }
.dv-gmt { width: 64px; min-width: 64px; font-size: 11px; color: #9aa0a6; text-align: right; padding-right: 10px; padding-top: 42px; }
.dv-daycol { flex: 1; }
.dv-dow { font-size: 11.5px; font-weight: 600; color: #8ab4f8; margin-bottom: 2px; }
.dv-num { display: inline-flex; align-items: center; justify-content: center; width: 38px; height: 38px; border-radius: 50%; font-size: 22px; font-weight: 500; background: #1a73e8; color: #fff; margin-bottom: 8px; }
.dv-allday { display: flex; flex-direction: column; gap: 3px; }
.dv-bar { font-size: 12px; font-weight: 600; padding: 4px 10px; border-radius: 4px; cursor: pointer; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.dv-bar:hover { filter: brightness(1.12); }
.dv-bar.expiry { background: #e67c73; color: #1b0a09; }
.dv-bar.hedge { background: #d93025; color: #fff; }
.dv-bar.level { background: #4285f4; color: #fff; }
.dv-hours { display: flex; flex-direction: column; }
.dv-hrow { display: flex; height: 42px; }
.dv-hlbl { width: 64px; min-width: 64px; text-align: right; padding-right: 10px; font-size: 11px; color: #9aa0a6; transform: translateY(-7px); }
.dv-hcell { flex: 1; border-top: 1px solid #26282a; border-left: 1px solid #2d2f31; }

/* Month View */
.mv-grid { display: flex; flex-direction: column; height: 100%; }
.mv-dow { display: grid; grid-template-columns: repeat(7, 1fr); background: #18191b; border-bottom: 1px solid #2d2f31; }
.mv-dow div { text-align: center; padding: 7px 4px; font-size: 11.5px; font-weight: 600; color: #9aa0a6; }
.mv-dow div:first-child { color: #f28b82; }
.mv-dow div:last-child { color: #8ab4f8; }
.mv-wk { display: grid; grid-template-columns: repeat(7, 1fr); flex: 1; border-bottom: 1px solid #2d2f31; min-height: 118px; }
.mv-cell { border-right: 1px solid #2d2f31; padding: 5px; cursor: pointer; overflow: hidden; }
.mv-cell:last-child { border-right: none; }
.mv-cell:hover { background: #1a1c1f; }
.mv-cell.other { background: #0e0f10; color: #5f6368; }
.mv-dnum { font-size: 12px; font-weight: 600; width: 24px; height: 24px; line-height: 24px; text-align: center; border-radius: 50%; margin-bottom: 3px; }
.mv-dnum.today { background: #1a73e8; color: #fff; }
.mv-pill { font-size: 11px; padding: 2px 6px; margin-bottom: 2px; border-radius: 4px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-weight: 600; cursor: pointer; }
.mv-pill.expiry { background: #e67c73; color: #1b0a09; }
.mv-pill.hedge { background: #b3261e; color: #fce8e6; }
.mv-pill.level { background: #1b4d89; color: #d2e3fc; }
.mv-more { font-size: 11px; color: #9aa0a6; font-weight: 600; padding-left: 3px; }

/* Week View */
.wv-grid { display: grid; grid-template-columns: repeat(7, 1fr); min-height: 100%; }
.wv-col { border-right: 1px solid #2d2f31; padding: 8px 6px; }
.wv-col:last-child { border-right: none; }
.wv-head { text-align: center; padding-bottom: 8px; border-bottom: 1px solid #2d2f31; margin-bottom: 8px; cursor: pointer; }

/* Schedule View */
.sv-row { display: flex; gap: 16px; padding: 12px 18px; border-bottom: 1px solid #2d2f31; }
.sv-dt { min-width: 115px; font-size: 13px; font-weight: 600; color: #8ab4f8; cursor: pointer; }
.sv-list { flex: 1; display: flex; flex-direction: column; gap: 4px; }

/* Google Calendar Event Detail Popover Modal */
.modal-bg { display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.48); z-index: 9999; align-items: center; justify-content: center; padding: 16px; }
.modal-bg.open { display: flex; }
.g-card { background: #282a2c; border: 1px solid #3c4043; border-radius: 18px; width: 100%; max-width: 460px; box-shadow: 0 12px 36px rgba(0,0,0,0.65); overflow: hidden; }
.g-card-bar { display: flex; justify-content: flex-end; padding: 10px 14px 0; }
.g-card-body { padding: 4px 22px 22px; }
.g-card-row { display: flex; align-items: flex-start; gap: 14px; margin-bottom: 14px; }
.g-sq { width: 14px; height: 14px; border-radius: 4px; margin-top: 5px; flex-shrink: 0; }
.g-card-title { font-size: 20px; font-weight: 500; color: #e8eaed; line-height: 1.35; }
.g-card-date { font-size: 13.5px; color: #bdc1c6; margin-top: 4px; }
.g-card-desc { font-size: 13.5px; line-height: 1.6; color: #e8eaed; white-space: pre-wrap; max-height: 360px; overflow-y: auto; }
.ev-ai-box { background: rgba(138,180,248,0.14); border-left: 4px solid #8ab4f8; border-radius: 8px; padding: 10px 12px; margin-bottom: 10px; color: #d2e3fc; font-size: 13.5px; line-height: 1.55; white-space: pre-wrap; }
@media (max-width: 768px) { .g-side { display: none; } }
</style>
</head>
<body>
<div class="g-shell">
  <div class="g-top">
    <div class="g-top-l">
      <div class="g-logo"><div class="g-logo-box">16</div>Calendar</div>
      <button class="g-btn" onclick="goToday()">오늘</button>
      <button class="g-icon-btn" onclick="step(-1)">‹</button>
      <button class="g-icon-btn" onclick="step(1)">›</button>
      <div class="g-cur-title" id="mainTitle"></div>
    </div>
    <div class="g-top-r">
      <input class="g-search" id="qInput" type="text" placeholder="🔍 검색 (NVDA, SPX, 풋...)" oninput="renderAll()"/>
      <div class="g-view-grp">
        <button class="g-vbtn active" id="vbDay" onclick="setView('day')">일</button>
        <button class="g-vbtn" id="vbWeek" onclick="setView('week')">주</button>
        <button class="g-vbtn" id="vbMonth" onclick="setView('month')">월</button>
        <button class="g-vbtn" id="vbSched" onclick="setView('sched')">일정</button>
      </div>
    </div>
  </div>
  <div class="g-body">
    <div class="g-side">
      <button class="g-create-btn" onclick="openHint()">＋ 만들기</button>
      <div>
        <div class="mini-hdr">
          <span class="mini-ym" id="miniYm"></span>
          <div>
            <button class="g-icon-btn" style="display:inline-flex;width:24px;height:24px;font-size:14px;" onclick="stepMini(-1)">‹</button>
            <button class="g-icon-btn" style="display:inline-flex;width:24px;height:24px;font-size:14px;" onclick="stepMini(1)">›</button>
          </div>
        </div>
        <div class="mini-grid" id="miniGrid"></div>
      </div>
      <div>
        <div class="cal-sec-t">내 캘린더</div>
        <div class="cal-chk" onclick="toggleCat('expiry')"><span class="cal-box" id="chkExpiry" style="background:#e67c73;">✓</span> 옵션 만기 (콜/전략)</div>
        <div class="cal-chk" onclick="toggleCat('hedge')"><span class="cal-box" id="chkHedge" style="background:#d93025;">✓</span> 옵션 헷지 (풋)</div>
        <div class="cal-chk" onclick="toggleCat('level')"><span class="cal-box" id="chkLevel" style="background:#4285f4;">✓</span> 옵션 레벨 (MenthorQ)</div>
      </div>
    </div>
    <div class="g-main" id="mainRoot"></div>
  </div>
</div>

<div class="modal-bg" id="modalBg" onclick="if(event.target===this)closeModal()">
  <div class="g-card">
    <div class="g-card-bar"><button class="g-icon-btn" onclick="closeModal()">✕</button></div>
    <div class="g-card-body">
      <div class="g-card-row">
        <div class="g-sq" id="mDot"></div>
        <div>
          <div class="g-card-title" id="mTitle"></div>
          <div class="g-card-date" id="mDate"></div>
        </div>
      </div>
      <div class="g-card-row">
        <div style="width:14px;text-align:center;color:#9aa0a6;font-size:16px;">≡</div>
        <div class="g-card-desc" id="mDesc"></div>
      </div>
    </div>
  </div>
</div>

<script>
const _evB64 = "__EVENTS_B64__";
const _evBin = atob(_evB64);
const _evBytes = new Uint8Array(_evBin.length);
for (let _bi = 0; _bi < _evBin.length; _bi++) _evBytes[_bi] = _evBin.charCodeAt(_bi);
const EVENTS = JSON.parse(new TextDecoder("utf-8").decode(_evBytes));
const TODAY = "2026-11-16";
let selDate = "2026-11-20";
let miniYear = 2026, miniMonth = 10; // 10 = Nov
let viewMode = 'day'; // default Day view like screenshot, switchable to week/month/sched
let cats = { expiry: true, hedge: true, level: true };
let collapseAllDay = false;

function classify(sm) {
  const u = (sm || '').toUpperCase();
  if (sm.includes('[옵션 레벨]') || u.includes('MENTHOR Q') || u.includes('SPOTGAMMA') || u.includes('UNUSUAL WHALES') || sm.includes('[매크로 헷지]')) return 'level';
  if (sm.includes('[옵션 헷지]') || u.includes('PUT') || sm.includes('풋') || sm.includes('🔴') || sm.includes('🛡️')) return 'hedge';
  return 'expiry';
}
function esc(s) { return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }
function parseIso(s) { const [y,m,d] = s.split('-').map(Number); return new Date(y, m-1, d); }
function toIso(d) { return d.getFullYear() + '-' + String(d.getMonth()+1).padStart(2,'0') + '-' + String(d.getDate()).padStart(2,'0'); }
function korDow(d) { return ['일','월','화','수','목','금','토'][d.getDay()]; }

function getFiltered() {
  const q = (document.getElementById('qInput').value || '').trim().toLowerCase();
  return EVENTS.filter(e => {
    const c = classify(e.summary);
    if (!cats[c]) return false;
    if (q && !(e.summary + ' ' + e.description + ' ' + e.date).toLowerCase().includes(q)) return false;
    return true;
  });
}
function toggleCat(c) {
  cats[c] = !cats[c];
  const el = document.getElementById(c==='expiry'?'chkExpiry':c==='hedge'?'chkHedge':'chkLevel');
  el.textContent = cats[c] ? '✓' : '';
  el.style.opacity = cats[c] ? '1' : '0.35';
  try { renderAll(); } catch (e) {
  const mr = document.getElementById('mainRoot');
  if (mr) mr.innerHTML = '<div style="padding:24px;color:#f28b82;font-size:14px;">캘린더 렌더링 오류: ' + (e && e.message ? e.message : e) + '</div>';
}
}
function setView(v) {
  viewMode = v;
  ['vbDay','vbWeek','vbMonth','vbSched'].forEach(id => document.getElementById(id).classList.remove('active'));
  document.getElementById(v==='day'?'vbDay':v==='week'?'vbWeek':v==='month'?'vbMonth':'vbSched').classList.add('active');
  renderAll();
}
function goToday() {
  selDate = TODAY; miniYear = 2026; miniMonth = 10;
  renderAll();
}
function selectDay(ds) {
  selDate = ds;
  const dt = parseIso(ds);
  miniYear = dt.getFullYear(); miniMonth = dt.getMonth();
  renderAll();
}
function stepMini(dir) {
  miniMonth += dir;
  if (miniMonth < 0) { miniMonth = 11; miniYear--; }
  if (miniMonth > 11) { miniMonth = 0; miniYear++; }
  renderMini();
}
function step(dir) {
  const dt = parseIso(selDate);
  if (viewMode === 'day') dt.setDate(dt.getDate() + dir);
  else if (viewMode === 'week') dt.setDate(dt.getDate() + dir * 7);
  else dt.setMonth(dt.getMonth() + dir);
  selectDay(toIso(dt));
}
function openEvent(id) {
  const ev = EVENTS.find(x => x.id === id);
  if (!ev) return;
  const c = classify(ev.summary);
  const dt = parseIso(ev.date);
  document.getElementById('mDot').style.background = c==='expiry'?'#e67c73':c==='hedge'?'#d93025':'#4285f4';
  document.getElementById('mTitle').textContent = ev.summary;
  document.getElementById('mDate').textContent = `${dt.getMonth()+1}월 ${dt.getDate()}일 (${korDow(dt)}요일)`;
  const rawDesc = (ev.description || '(상세 내용 없음)').trim();
  const descEl = document.getElementById('mDesc');
  const escHtml = (s) => String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  if (rawDesc.includes('📌')) {
    const parts = rawDesc.split(String.fromCharCode(10, 10));
    const aiPart = parts.filter(p => p.includes('📌') || p.includes('Gemini')).slice(0, 1)[0] || '';
    if (aiPart) {
      const rest = rawDesc.replace(aiPart, '').trim();
      descEl.innerHTML = `<div class="ev-ai-box">${escHtml(aiPart.trim())}</div>` + (rest ? `<div>${escHtml(rest)}</div>` : '');
    } else {
      descEl.textContent = rawDesc;
    }
  } else {
    descEl.textContent = rawDesc;
  }
  document.getElementById('modalBg').classList.add('open');
}
function closeModal() { document.getElementById('modalBg').classList.remove('open'); }
function openHint() { alert('아래 "⚙️ ICS 실시간 동기화 · ➕ 새 일정 추가"를 열어 새 일정을 추가할 수 있습니다.'); }

function renderMini() {
  const filtered = getFiltered();
  const hasMap = {};
  filtered.forEach(e => { hasMap[e.date] = true; });
  document.getElementById('miniYm').textContent = `${miniYear}년 ${miniMonth+1}월`;
  const first = new Date(miniYear, miniMonth, 1);
  const start = new Date(first); start.setDate(1 - first.getDay());
  let html = ['일','월','화','수','목','금','토'].map(d => `<div class="mini-dow">${d}</div>`).join('');
  let d = new Date(start);
  for (let i=0; i<42; i++) {
    const ds = toIso(d);
    const cls = ['mini-day'];
    if (d.getMonth() !== miniMonth) cls.push('other');
    if (ds === TODAY) cls.push('today');
    else if (ds === selDate) cls.push('sel');
    const dot = hasMap[ds] ? '<span class="mini-dot"></span>' : '';
    html += `<div class="${cls.join(' ')}" onclick="selectDay('${ds}')">${d.getDate()}${dot}</div>`;
    d.setDate(d.getDate()+1);
  }
  document.getElementById('miniGrid').innerHTML = html;
}

function renderMain() {
  const filtered = getFiltered();
  const byDate = {};
  filtered.forEach(e => { (byDate[e.date] = byDate[e.date] || []).push(e); });
  const root = document.getElementById('mainRoot');
  const curDt = parseIso(selDate);

  if (viewMode === 'day') {
    document.getElementById('mainTitle').textContent = `${curDt.getFullYear()}년 ${curDt.getMonth()+1}월 ${curDt.getDate()}일`;
    const evs = byDate[selDate] || [];
    const shown = collapseAllDay ? evs.slice(0, 5) : evs;
    const bars = shown.map(ev => `<div class="dv-bar ${classify(ev.summary)}" onclick="openEvent('${esc(ev.id)}')">${esc(ev.summary)}</div>`).join('') || '<div style="color:#9aa0a6;font-size:12.5px;padding:6px 0;">이 날짜에 등록된 일정이 없습니다.</div>';
    const tog = evs.length > 5 ? `<div style="font-size:11.5px;color:#8ab4f8;cursor:pointer;margin-top:4px;font-weight:600;" onclick="collapseAllDay=!collapseAllDay;renderMain()">${collapseAllDay ? '▼ 모두 펼치기 ('+evs.length+'건)' : '▲ 접기'}</div>` : '';
    let hours = '';
    for (let h=1; h<=11; h++) hours += `<div class="dv-hrow"><div class="dv-hlbl">오전 ${h}시</div><div class="dv-hcell"></div></div>`;
    hours += `<div class="dv-hrow"><div class="dv-hlbl">오후 12시</div><div class="dv-hcell"></div></div>`;
    for (let h=1; h<=11; h++) hours += `<div class="dv-hrow"><div class="dv-hlbl">오후 ${h}시</div><div class="dv-hcell"></div></div>`;
    root.innerHTML = `<div class="dv-head"><div class="dv-gmt">GMT+9</div><div class="dv-daycol"><div class="dv-dow">${korDow(curDt)}</div><div class="dv-num">${curDt.getDate()}</div><div class="dv-allday">${bars}</div>${tog}</div></div><div class="dv-hours">${hours}</div>`;
  } else if (viewMode === 'week') {
    const startW = new Date(curDt); startW.setDate(curDt.getDate() - curDt.getDay());
    const endW = new Date(startW); endW.setDate(startW.getDate() + 6);
    document.getElementById('mainTitle').textContent = `${startW.getMonth()+1}/${startW.getDate()} ~ ${endW.getMonth()+1}/${endW.getDate()}`;
    let html = '<div class="wv-grid">';
    let d = new Date(startW);
    for (let i=0; i<7; i++) {
      const ds = toIso(d);
      const evs = byDate[ds] || [];
      const pills = evs.map(ev => `<div class="mv-pill ${classify(ev.summary)}" style="white-space:normal;" onclick="openEvent('${esc(ev.id)}')">${esc(ev.summary)}</div>`).join('');
      html += `<div class="wv-col"><div class="wv-head" onclick="selectDay('${ds}');setView('day')"><div style="font-size:11px;color:#9aa0a6;">${korDow(d)}</div><div class="mv-dnum ${ds===TODAY?'today':''}" style="margin:4px auto 0;">${d.getDate()}</div></div>${pills}</div>`;
      d.setDate(d.getDate()+1);
    }
    html += '</div>';
    root.innerHTML = html;
  } else if (viewMode === 'month') {
    const y = curDt.getFullYear(), m = curDt.getMonth();
    document.getElementById('mainTitle').textContent = `${y}년 ${m+1}월`;
    const first = new Date(y, m, 1);
    const start = new Date(first); start.setDate(1 - first.getDay());
    let html = '<div class="mv-grid"><div class="mv-dow"><div>일</div><div>월</div><div>화</div><div>수</div><div>목</div><div>금</div><div>토</div></div>';
    let d = new Date(start);
    for (let w=0; w<6; w++) {
      if (w>=4 && d.getMonth()!==m) break;
      html += '<div class="mv-wk">';
      for (let i=0; i<7; i++) {
        const ds = toIso(d);
        const evs = byDate[ds] || [];
        const pills = evs.slice(0,3).map(ev => `<div class="mv-pill ${classify(ev.summary)}" onclick="event.stopPropagation();openEvent('${esc(ev.id)}')">${esc(ev.summary)}</div>`).join('');
        const more = evs.length > 3 ? `<div class="mv-more">+${evs.length-3}개 더보기</div>` : '';
        html += `<div class="mv-cell ${d.getMonth()!==m?'other':''}" onclick="selectDay('${ds}');setView('day')"><div class="mv-dnum ${ds===TODAY?'today':''}">${d.getDate()}</div>${pills}${more}</div>`;
        d.setDate(d.getDate()+1);
      }
      html += '</div>';
    }
    html += '</div>';
    root.innerHTML = html;
  } else {
    const ym = `${curDt.getFullYear()}-${String(curDt.getMonth()+1).padStart(2,'0')}`;
    document.getElementById('mainTitle').textContent = `${curDt.getFullYear()}년 ${curDt.getMonth()+1}월 일정`;
    const dates = Object.keys(byDate).filter(dt => dt.startsWith(ym)).sort();
    root.innerHTML = dates.length ? dates.map(dt => {
      const items = byDate[dt].map(ev => `<div class="mv-pill ${classify(ev.summary)}" style="white-space:normal;padding:5px 8px;" onclick="openEvent('${esc(ev.id)}')">${esc(ev.summary)}</div>`).join('');
      return `<div class="sv-row"><div class="sv-dt" onclick="selectDay('${dt}');setView('day')">${dt}</div><div class="sv-list">${items}</div></div>`;
    }).join('') : '<div style="padding:36px;text-align:center;color:#9aa0a6;">이번 달 일정이 없습니다.</div>';
  }
}

function renderAll() { renderMini(); renderMain(); }
renderAll();
</script>
</body>
</html>"""

    _gcal_html = _gcal_html.replace("__EVENTS_B64__", _events_b64)
    components.html(_gcal_html, height=820, scrolling=True)

    with st.expander("⚙️ ICS 실시간 동기화 · ➕ 새 일정 추가 · 📩 텔레그램 전송", expanded=False):
        _ic1, _ic2 = st.columns([3.0, 1.0])
        _ics_in = _ic1.text_input("구글 캘린더 비공개 iCal 주소 (.ics)", _saved_ics, placeholder="https://calendar.google.com/calendar/ical/.../basic.ics", key="gcal_ics_in")
        if _ic2.button("💾 동기화", use_container_width=True, key="btn_gcal_ics_save"):
            with open(GCAL_ICS_PATH, "w", encoding="utf-8") as _fics:
                _fics.write(_ics_in.strip())
            _fetch_ics_events.clear()
            st.success("✅ 동기화 완료!")
            st.rerun()

        _na1, _na2 = st.columns([1.2, 2.8])
        _new_dt = _na1.date_input("날짜", value=pd.Timestamp("2026-11-20").date(), key="gcal_new_dt")
        _new_sum = _na2.text_input("일정 제목", "", placeholder="예: [옵션 만기] NVDA $180 Call ($5.0M 스윕)", key="gcal_new_sum")
        _new_desc = st.text_area("상세 내용", height=70, placeholder="행사가, 프리미엄, 전략 메모...", key="gcal_new_desc")
        _auto_ai_add = st.checkbox("🤖 저장 시 Gemini 트레이더 해석 자동 추가", value=True, key="gcal_new_auto_ai")
        _bc1, _bc2 = st.columns(2)
        if _bc1.button("➕ 캘린더에 일정 추가", type="primary", use_container_width=True, key="btn_gcal_add"):
            if _new_sum.strip():
                _final_desc = _new_desc.strip()
                if _auto_ai_add and "Gemini" not in _final_desc:
                    _pr_ev = (
                        f"다음 옵션 캘린더 일정('{_new_sum.strip()}', 날짜: {_new_dt.strftime('%Y-%m-%d')})을 "
                        f"한국어 트레이더 관점에서 핵심만 2~3문장으로 해석해 주세요:\n\n{_final_desc[:2000]}"
                    )
                    _, _ai_ev_txt = run_ai_analysis(_pr_ev)
                    if _ai_ev_txt and "오류" not in _ai_ev_txt[:15]:
                        _final_desc = f"📌 [Gemini AI 해석]\n{_ai_ev_txt.strip()}" + (f"\n\n{_final_desc}" if _final_desc else "")
                local_gcal.append({
                    "id": f"local_{int(time.time()*1000)}",
                    "date": _new_dt.strftime("%Y-%m-%d"),
                    "summary": _new_sum.strip(),
                    "description": _final_desc,
                })
                save_json_file(GCAL_EVENTS_PATH, local_gcal)
                st.success("✅ 추가되었습니다!")
                st.rerun()
        if _bc2.button("📩 선택한 날짜 일정 텔레그램 전송", use_container_width=True, key="btn_gcal_tg_day"):
            _sel_d = _new_dt.strftime("%Y-%m-%d")
            _sel_evs = [e for e in all_gcal_events if e.get("date") == _sel_d]
            if _sel_evs:
                _tg_lines = [f"📅 *구글 캘린더 ({_sel_d} · {len(_sel_evs)}건)*\n"] + [f"• {_se.get('summary','')}" for _se in _sel_evs[:35]]
                if send_telegram_msg(tg_token, tg_chat_id, "\n".join(_tg_lines))[0]:
                    st.toast("✅ 텔레그램 전송 완료!")
                else:
                    st.toast("⚠️ 텔레그램 설정을 확인해 주세요.")
            else:
                st.toast("해당 날짜에 일정이 없습니다.")


if nav_menu == "📂 옵션자료실":
    st.title("📂 옵션자료실 (GEX · 그릭스 · 옵션 전략 아카이브)")
    st.caption("옵션 리포트, GEX/HIRO/OI 분석 메모, 스크린샷 복사·붙여넣기(Ctrl+V), 전략 파일(PDF·엑셀·이미지)을 서버에 영구 저장합니다.")

    OPT_VAULT_PATH = os.path.expanduser("~/.optionhub_options_vault.json")
    OPT_VAULT_DIR = os.path.expanduser("~/.optionhub_options_files")
    os.makedirs(OPT_VAULT_DIR, exist_ok=True)
    default_opt_vault = [
        {
            "id": "opt_1",
            "날짜": "2026-11-14",
            "카테고리": "GEX/그릭스",
            "종목": "공통",
            "제목": "양(+)감마 vs 음(-)감마 장세 딜러 헤징 메커니즘",
            "내용": "• +GEX 구간 (Zero Gamma 위): 딜러가 상승 시 매도·하락 시 매수로 변동성을 억제하고 Call/Put Wall 사이에 가두는(Pinning) 경향.\n• -GEX 구간 (Zero Gamma 아래): 딜러가 하락 시 매도·상승 시 매수로 추세를 증폭시켜 1σ 이상 급변동 발생 가능.",
            "링크": ""
        },
        {
            "id": "opt_2",
            "날짜": "2026-11-14",
            "카테고리": "OI·Wall 분석",
            "종목": "SOXL·NVDA",
            "제목": "Ask/Bid 체결 의도 & BTO vs STO 판별 기준",
            "내용": "• Ask 체결 + Vol > OI: 신규 매수(BTO) 가능성 높음 (콜이면 강한 상방, 풋이면 강한 하방/헷지).\n• Bid 체결 + 큰 OI 기존 잔고: 매도(STO/커버드콜) 또는 기존 포지션 청산(STC) 가능성 병행 체크.",
            "링크": ""
        },
        {
            "id": "opt_3",
            "날짜": "2026-11-14",
            "카테고리": "0DTE·만기 전략",
            "종목": "SPX·QQQ",
            "제목": "OPEX & 0DTE 만기일 체크리스트 (1σ · Max Pain · Flip)",
            "내용": "1) Spot과 Zero Gamma Flip 거리 확인 → 2) 1D Expected Move(SIG_H / SIG_L) 밴드 설정 → 3) 장 후반 HIRO 방향(양수 마감 시 다음날 상방 우위, 음수 마감 시 하방 경계).",
            "링크": ""
        }
    ]
    opt_items = load_json_file(OPT_VAULT_PATH, default_opt_vault)
    _id_fixed = False
    for _oi, _ox in enumerate(opt_items):
        if not _ox.get("id"):
            _ox["id"] = f"op_auto_{_oi}_{int(time.time())}"
            _id_fixed = True
    if _id_fixed:
        save_json_file(OPT_VAULT_PATH, opt_items)
    if st.session_state.pop("opt_saved_ok", False):
        st.success("✅ 옵션자료실에 정상 저장되었습니다!")
    if st.session_state.pop("opt_edited_ok", False):
        st.success("✏️ 옵션 자료가 수정되었습니다!")

    with st.expander("📬 InsiderFinance · Barchart · SpotGamma 영문 메일/리포트 붙여넣기 → AI 한국어 요약 자동 저장", expanded=False):
        ms_c1, ms_c2 = st.columns([2.2, 1.0])
        mail_raw_in = ms_c1.text_area("영문 뉴스레터 또는 옵션 리포트 본문 붙여넣기", height=110, placeholder="InsiderFinance / MenthorQ / Barchart 메일 본문을 그대로 붙여넣으세요...", key="mail_raw_in")
        mail_tk_in = ms_c2.text_input("대표 종목 (비워두면 자동 추출)", "", placeholder="예: SOXL, NVDA, SPY", key="mail_tk_in").strip().upper()
        mail_send_tg = ms_c2.checkbox("저장 후 텔레그램으로도 바로 발송", value=True, key="mail_send_tg")
        if ms_c2.button("🤖 AI 한국어 분석 & 옵션자료실 자동 저장", type="primary", use_container_width=True, key="btn_mail_ai_save"):
            if mail_raw_in.strip():
                with st.spinner("AI가 영문 메일을 한국어로 요약·분석해 옵션자료실에 저장 중입니다..."):
                    _auto_tks = extract_silpi_symbols(mail_raw_in)
                    _tk_final = mail_tk_in or (", ".join(_auto_tks[:3]) if _auto_tks else "공통")
                    _p_mail = (
                        "다음 미국 옵션 뉴스레터(InsiderFinance/Barchart/MenthorQ 등) 본문을 한국어로 분석해 주세요.\n"
                        "1) 핵심 3줄 요약\n2) 포착된 주요 종목·행사가·만기·프리미엄\n3) 매매 전략(상방/하방 기준선 및 TP/SL)\n\n본문:\n"
                        + mail_raw_in[:6000]
                    )
                    _, _mail_ko = run_ai_analysis(_p_mail)
                    _title_m = f"[메일 AI 분석] {_tk_final} 옵션 리포트 요약"
                    opt_items.insert(0, {
                        "id": f"op_{int(time.time()*1000)}",
                        "날짜": pd.Timestamp.now(tz="Asia/Seoul").strftime("%Y-%m-%d %H:%M"),
                        "카테고리": "스윕·블록",
                        "종목": _tk_final,
                        "제목": _title_m,
                        "내용": _mail_ko,
                        "링크": "",
                        "파일경로": "",
                        "파일명": "",
                    })
                    save_json_file(OPT_VAULT_PATH, opt_items)
                    if mail_send_tg:
                        send_telegram_msg(tg_token, tg_chat_id, f"📬 *{_title_m}*\n\n{_mail_ko[:3500]}")
                    st.session_state["opt_saved_ok"] = True
                    st.rerun()
            else:
                st.warning("메일 또는 리포트 본문을 먼저 붙여넣어 주세요.")

    with st.expander("➕ 새 옵션 자료 / 메모 / 사진 붙여넣기(Ctrl+V) 추가하기", expanded=True):
        oc1, oc2, oc3 = st.columns([1.2, 1.0, 2.0])
        o_cat = oc1.selectbox("카테고리", ["GEX/그릭스", "OI·Wall 분석", "HIRO·다크풀", "스윕·블록", "0DTE·만기 전략", "참고 파일/PDF"], key="op_add_cat")
        o_tk = oc2.text_input("관련 종목", "공통", placeholder="예: SOXL, NVDA, SPX, 공통", key="op_add_tk").strip().upper() or "공통"
        o_title = oc3.text_input("제목 (비워두면 내용 첫 줄 자동 입력)", placeholder="예: 11/14 NVDA 150P/200C GEX 구조", key="op_add_title")
        o_body = st.text_area("상세 내용 / 메모", height=100, placeholder="GEX·DEX·OI·스윕 분석 내용이나 전략 기준을 입력하세요.", key="op_add_body")

        oc4, oc5 = st.columns([1.5, 1.5])
        o_link = oc4.text_input("참고 URL (선택)", placeholder="https://...", key="op_add_link")
        o_file = oc5.file_uploader("파일 첨부 (PDF·이미지·CSV·XLSX 등)", type=None, key="opt_file_up")

        st.markdown("**📋 사진 복사·붙여넣기 (여기를 클릭하고 Ctrl+V)**")
        components.html("""
        <div id="op_paste_zone" tabindex="0" style="border:2px dashed #38bdf8; border-radius:8px; padding:12px; background:#0b101b; color:#cbd5e1; text-align:center; cursor:pointer; font-family:sans-serif; font-size:13px; outline:none;">
          <div id="op_paste_msg">🖼️ 스크린샷이나 웹 이미지를 <b>복사(Ctrl+C)</b>한 뒤, 이 상자를 클릭하고 <b>붙여넣기(Ctrl+V)</b> 하세요!</div>
          <img id="op_paste_prev" style="display:none; max-height:170px; margin:8px auto 0 auto; border-radius:6px; border:1px solid #334155;"/>
        </div>
        <script>
          const zone = document.getElementById("op_paste_zone");
          const msg = document.getElementById("op_paste_msg");
          const prev = document.getElementById("op_paste_prev");
          function sendToStreamlit(dataUrl) {
            try {
              const inp = window.parent.document.querySelector('input[aria-label="붙여넣기 이미지 데이터"]');
              if (inp) {
                const setter = Object.getOwnPropertyDescriptor(window.parent.HTMLInputElement.prototype, 'value').set;
                setter.call(inp, dataUrl);
                inp.dispatchEvent(new Event('input', { bubbles: true }));
                inp.dispatchEvent(new Event('change', { bubbles: true }));
                msg.innerHTML = "✅ 이미지가 첨부 대기 상태입니다! 아래 <b>💾 옵션자료실에 저장</b> 버튼을 누르세요.";
              } else {
                msg.innerHTML = "⚠️ 입력칸을 찾지 못했습니다. 파일 첨부를 이용해 주세요.";
              }
            } catch (err) {
              msg.innerHTML = "⚠️ 붙여넣기 연동 오류: " + err;
            }
          }
          zone.addEventListener("paste", (e) => {
            const items = (e.clipboardData || window.clipboardData).items || [];
            for (const it of items) {
              if (it.type && it.type.indexOf("image") !== -1) {
                e.preventDefault();
                const blob = it.getAsFile();
                const reader = new FileReader();
                reader.onload = (ev) => {
                  const img = new Image();
                  img.onload = () => {
                    const maxW = 1400;
                    const scale = img.width > maxW ? (maxW / img.width) : 1;
                    const cv = document.createElement("canvas");
                    cv.width = Math.round(img.width * scale);
                    cv.height = Math.round(img.height * scale);
                    cv.getContext("2d").drawImage(img, 0, 0, cv.width, cv.height);
                    const b64 = cv.toDataURL("image/jpeg", 0.85);
                    prev.src = b64;
                    prev.style.display = "block";
                    sendToStreamlit(b64);
                  };
                  img.src = ev.target.result;
                };
                reader.readAsDataURL(blob);
                return;
              }
            }
          });
        </script>
        """, height=215)
        if st.session_state.pop("opt_clear_paste", False):
            st.session_state["opt_paste_b64"] = ""
        pasted_b64 = st.text_input("붙여넣기 이미지 데이터", "", key="opt_paste_b64", label_visibility="collapsed", placeholder="Ctrl+V로 이미지를 붙여넣으면 자동으로 채워집니다 (직접 입력 불필요)")

        if st.session_state.get("opt_ai_draft"):
            st.info(st.session_state["opt_ai_draft"])
        ob_c1, ob_c2 = st.columns([1.2, 1.2])
        if ob_c2.button("🤖 사진/텍스트 AI 자동 분석 (내용 채우기)", use_container_width=True, key="opt_ai_gen_btn"):
            with st.spinner("AI가 첨부 사진/내용을 분석 중입니다..."):
                _p_ai = (
                    f"다음은 미국 주식 옵션({o_tk}) 관련 이미지 또는 메모입니다. "
                    f"표에 있는 주요 행사가, 콜/풋 수량, 프리미엄, 이전OI/최신OI(ΔOI), BUY/SELL 방향과 핵심 매매 전략 시사점을 한국어로 깔끔하게 정리해 주세요.\n"
                    f"기존 입력 제목: {o_title}\n기존 입력 내용: {o_body}"
                )
                _ok_a, _txt_a = run_ai_analysis(_p_ai, img_b64=pasted_b64 if pasted_b64 else None)
                st.session_state["opt_ai_draft"] = _txt_a
                st.rerun()
        if ob_c1.button("💾 옵션자료실에 저장", type="primary", use_container_width=True, key="opt_save_btn"):
            saved_fp = ""
            saved_fn = ""
            if o_file is not None:
                safe_n = f"{int(time.time())}_{os.path.basename(o_file.name)}"
                saved_fp = os.path.join(OPT_VAULT_DIR, safe_n)
                with open(saved_fp, "wb") as fw:
                    fw.write(o_file.getbuffer())
                saved_fn = o_file.name
            elif pasted_b64 and pasted_b64.strip().startswith("data:image"):
                try:
                    import base64 as _b64_m
                    _, b64_raw = pasted_b64.strip().split(",", 1)
                    ts_n = int(time.time())
                    saved_fn = f"screenshot_{ts_n}.jpg"
                    saved_fp = os.path.join(OPT_VAULT_DIR, saved_fn)
                    with open(saved_fp, "wb") as fw:
                        fw.write(_b64_m.b64decode(b64_raw))
                except Exception as _pe:
                    st.warning(f"붙여넣은 이미지 저장 실패: {_pe}")

            auto_t = o_title.strip() or (o_body.strip().splitlines()[0][:50] if o_body.strip() else "") or saved_fn or o_link.strip()
            if auto_t:
                opt_items.insert(0, {
                    "id": f"op_{int(time.time()*1000)}",
                    "날짜": pd.Timestamp.now(tz="Asia/Seoul").strftime("%Y-%m-%d %H:%M"),
                    "카테고리": o_cat,
                    "종목": o_tk,
                    "제목": auto_t,
                    "내용": o_body.strip() or st.session_state.pop("opt_ai_draft", "").strip(),
                    "링크": o_link.strip(),
                    "파일경로": saved_fp,
                    "파일명": saved_fn,
                })
                save_json_file(OPT_VAULT_PATH, opt_items)
                st.session_state["opt_clear_paste"] = True
                st.session_state["opt_saved_ok"] = True
                st.rerun()
            else:
                st.warning("제목, 내용, 사진 붙여넣기, 파일, 또는 링크 중 하나는 입력해 주세요.")

    oc_f1, oc_f2, oc_f3, oc_f4 = st.columns([1.1, 1.1, 1.8, 0.9])
    o_cats = ["전체"] + sorted(list({x.get("카테고리", "기타") for x in opt_items}))
    o_tks = ["전체"] + sorted(list({x.get("종목", "공통") for x in opt_items}))
    fo_cat = oc_f1.selectbox("카테고리 필터", o_cats, key="op_f_cat")
    fo_tk = oc_f2.selectbox("종목 필터", o_tks, key="op_f_tk")
    fo_kw = oc_f3.text_input("🔍 키워드 검색", "", placeholder="제목 또는 내용 검색...", key="op_f_kw").strip().lower()
    if "opt_expand_all" not in st.session_state:
        st.session_state["opt_expand_all"] = True
    exp_lbl_o = "📁 전체 접기" if st.session_state["opt_expand_all"] else "📂 전체 펼치기"
    if oc_f4.button(exp_lbl_o, use_container_width=True, key="op_exp_toggle"):
        st.session_state["opt_expand_all"] = not st.session_state["opt_expand_all"]
        st.rerun()

    filtered_op = []
    for x in opt_items:
        if fo_cat != "전체" and x.get("카테고리") != fo_cat:
            continue
        if fo_tk != "전체" and x.get("종목") != fo_tk:
            continue
        if fo_kw and fo_kw not in (x.get("제목", "") + " " + x.get("내용", "") + " " + x.get("종목", "")).lower():
            continue
        filtered_op.append(x)

    st.caption(f"총 {len(filtered_op)}건의 옵션 자료가 표시되고 있습니다.")
    edit_op_id = st.session_state.get("edit_op_id")
    for idx_op, item_op in enumerate(filtered_op):
        iid_op = item_op.get("id", str(idx_op))
        with st.container(border=True):
            oh_l, oh_e, oh_t, oh_r = st.columns([4.2, 0.8, 1.0, 0.8])
            with oh_l:
                st.markdown(f"**[{item_op.get('카테고리','')}] {item_op.get('제목','')}**  `{item_op.get('종목','')}` · {item_op.get('날짜','')}")
            with oh_e:
                if st.button("✏️ 수정", key=f"ed_op_{iid_op}"):
                    st.session_state["edit_op_id"] = None if edit_op_id == iid_op else iid_op
                    st.rerun()
            with oh_t:
                if st.button("📩 텔레그램", key=f"tg_op_{iid_op}"):
                    tg_txt = f"📂 *[옵션자료실]* {item_op.get('제목','')}\n종목: {item_op.get('종목','')}\n\n{item_op.get('내용','')[:3200]}"
                    if send_telegram_msg(tg_token, tg_chat_id, tg_txt)[0]:
                        st.toast("✅ 텔레그램 전송 완료!")
                    else:
                        st.toast("⚠️ 텔레그램 설정 확인 필요")
            with oh_r:
                if st.button("🗑️ 삭제", key=f"del_op_{iid_op}"):
                    opt_items = [z for z in opt_items if z.get("id") != item_op.get("id")]
                    save_json_file(OPT_VAULT_PATH, opt_items)
                    st.rerun()

            if edit_op_id == iid_op:
                fp_ed = item_op.get("파일경로", "")
                if fp_ed and os.path.exists(fp_ed) and os.path.splitext(fp_ed)[1].lower() in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"):
                    st.image(fp_ed, caption=item_op.get("파일명", "첨부 이미지"), use_container_width=True)
                st.caption("✏️ 아래 칸에 그림 설명/분석을 작성한 뒤 **💾 수정 저장**을 누르세요.")
                ne_body = st.text_area("상세 내용 (그림 보면서 작성)", item_op.get("내용", ""), height=150, key=f"ne_bod_{iid_op}", placeholder="그림 아래에 분석 내용을 바로 입력하세요...")
                ec1, ec2, ec3 = st.columns([1.2, 1.0, 2.0])
                cat_list_o = ["GEX/그릭스", "OI·Wall 분석", "HIRO·다크풀", "스윕·블록", "0DTE·만기 전략", "참고 파일/PDF"]
                cur_cat_i = cat_list_o.index(item_op.get("카테고리")) if item_op.get("카테고리") in cat_list_o else 0
                ne_cat = ec1.selectbox("카테고리", cat_list_o, index=cur_cat_i, key=f"ne_cat_{iid_op}")
                ne_tk = ec2.text_input("관련 종목", item_op.get("종목", "공통"), key=f"ne_tk_{iid_op}").strip().upper() or "공통"
                ne_title = ec3.text_input("제목", item_op.get("제목", ""), key=f"ne_tit_{iid_op}")
                ne_link = st.text_input("참고 URL", item_op.get("링크", ""), key=f"ne_lnk_{iid_op}")
                ne_file = st.file_uploader("첨부파일/사진 교체 (선택)", type=None, key=f"ne_fil_{iid_op}")
                components.html("""
                <script>
                  setTimeout(() => {
                    try {
                      const ta = window.parent.document.querySelector('textarea[aria-label="상세 내용 (그림 보면서 작성)"]');
                      if (ta) {
                        ta.focus({ preventScroll: true });
                        ta.scrollIntoView({ behavior: "smooth", block: "nearest" });
                        const len = ta.value.length;
                        ta.setSelectionRange(len, len);
                      }
                    } catch(e) {}
                  }, 150);
                </script>
                """, height=0)
                sb1, sb_ai, sb2 = st.columns([1.2, 1.8, 3.0])
                if sb_ai.button("🤖 그림/내용 AI 분석 추가", key=f"ne_ai_{iid_op}"):
                    with st.spinner("AI가 그림과 내용을 분석 중입니다..."):
                        _p_ed = f"이 옵션 표/차트 이미지({ne_tk} - {ne_title})의 행사가별 수량, ΔOI, 프리미엄, BUY/SELL 방향과 핵심 지지·저항 포인트를 한국어로 요약해 주세요."
                        _, _ai_ed = run_ai_analysis(_p_ed, img_path=fp_ed if (fp_ed and os.path.exists(fp_ed)) else None)
                        for _z in opt_items:
                            if _z.get("id") == item_op.get("id"):
                                _z["내용"] = (ne_body.strip() + "\n\n" + _ai_ed).strip()
                                break
                        save_json_file(OPT_VAULT_PATH, opt_items)
                        st.rerun()
                if sb1.button("💾 수정 저장", type="primary", key=f"ne_sav_{iid_op}"):
                    for z in opt_items:
                        if z.get("id") == item_op.get("id"):
                            z["카테고리"] = ne_cat
                            z["종목"] = ne_tk
                            z["제목"] = ne_title.strip() or z.get("제목", "")
                            z["내용"] = ne_body.strip()
                            z["링크"] = ne_link.strip()
                            if ne_file is not None:
                                safe_en = f"{int(time.time())}_{os.path.basename(ne_file.name)}"
                                new_fp = os.path.join(OPT_VAULT_DIR, safe_en)
                                with open(new_fp, "wb") as fw:
                                    fw.write(ne_file.getbuffer())
                                z["파일경로"] = new_fp
                                z["파일명"] = ne_file.name
                            break
                    save_json_file(OPT_VAULT_PATH, opt_items)
                    st.session_state["edit_op_id"] = None
                    st.session_state["opt_edited_ok"] = True
                    st.rerun()
                if sb2.button("취소", key=f"ne_can_{iid_op}"):
                    st.session_state["edit_op_id"] = None
                    st.rerun()
            elif st.session_state["opt_expand_all"]:
                if item_op.get("내용"):
                    st.markdown(item_op["내용"].replace("\n", "  \n"))
                if item_op.get("링크"):
                    st.markdown(f"🔗 참고 링크: [{item_op['링크']}]({item_op['링크']})")
                fp_op = item_op.get("파일경로", "")
                if fp_op and os.path.exists(fp_op):
                    ext_op = os.path.splitext(fp_op)[1].lower()
                    if ext_op in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
                        st.image(fp_op, caption=item_op.get("파일명", "첨부 이미지"), use_container_width=True)
                    with open(fp_op, "rb") as fr:
                        st.download_button(f"📥 {item_op.get('파일명', '첨부파일')}", fr.read(), file_name=item_op.get("파일명", "file"), key=f"dl_op_{iid_op}")