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
        for exp in exps[:3]:
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
                        rows.append({
                            "만기": exp,
                            "구분": "Call" if is_c else "Put",
                            "행사가": K,
                            "OI": oi,
                            "거래량": vol,
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
    "📚 실피 자료실",
    "📂 옵션자료실"
]
st.sidebar.title("⚙️ OptionHub")
st.sidebar.success("🟢 실시간 데이터 연동 중 (11/12 반영)")
nav_menu = st.sidebar.radio("📌 메뉴 이동", MENU_ITEMS, index=0)

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
        if calls_m:
            cw_lv = max(calls_m, key=lambda x: x.get("OI", 0)).get("행사가")
            gex_c_lv = max(calls_m, key=lambda x: abs(float(x.get("GEX($M)", 0) or 0))).get("행사가")
        if puts_m:
            pw_lv = max(puts_m, key=lambda x: x.get("OI", 0)).get("행사가")
            gex_p_lv = max(puts_m, key=lambda x: abs(float(x.get("GEX($M)", 0) or 0))).get("행사가")
        zg_lv = calc_zero_gamma(det_m, spot_m)
        if det_m:
            df_dm = pd.DataFrame(det_m)
            if "DEX($M)" in df_dm.columns and not df_dm.empty:
                dex_s = df_dm.groupby("행사가")["DEX($M)"].sum().abs()
                if not dex_s.empty:
                    delta_lv = float(dex_s.idxmax())
            if "IV(%)" in df_dm.columns and spot_m > 0:
                atm_iv_m = float(df_dm.iloc[(df_dm["행사가"] - spot_m).abs().argsort()[:4]]["IV(%)"].mean() or 0)
                if atm_iv_m > 0:
                    mv_1d = spot_m * (atm_iv_m / 100.0) / math.sqrt(252.0)
                    sig_h_lv = round(spot_m + mv_1d, 2)
                    sig_l_lv = round(spot_m - mv_1d, 2)
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
    if not opt_bars:
        try:
            y_rows, y_sp = _cached_opt_snapshot(clean_tk)
            if y_rows:
                df_yd = pd.DataFrame(y_rows)
                sp_ref = float(y_sp or cur["px"] or 0)
                if sp_ref > 0:
                    df_yd = df_yd[(df_yd["행사가"] >= sp_ref * 0.7) & (df_yd["행사가"] <= sp_ref * 1.3)]
                if not df_yd.empty:
                    if cw_lv is None and not df_yd[df_yd["구분"] == "Call"].empty:
                        cw_lv = float(df_yd[df_yd["구분"] == "Call"].sort_values("OI", ascending=False).iloc[0]["행사가"])
                    if pw_lv is None and not df_yd[df_yd["구분"] == "Put"].empty:
                        pw_lv = float(df_yd[df_yd["구분"] == "Put"].sort_values("OI", ascending=False).iloc[0]["행사가"])
                    if zg_lv is None:
                        zg_lv = calc_zero_gamma(df_yd, sp_ref)
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
    try:
        import yfinance as yf
        df_yf = yf.Ticker(clean_tk).history(period=yf_per, interval=yf_int)
        if not df_yf.empty:
            if tf_opt == "10분봉":
                df_yf = df_yf.resample("10min").agg({"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}).dropna()
            for idx_t, r_y in df_yf.iterrows():
                candles.append({
                    "time": int(idx_t.timestamp()),
                    "open": round(float(r_y["Open"]), 2),
                    "high": round(float(r_y["High"]), 2),
                    "low": round(float(r_y["Low"]), 2),
                    "close": round(float(r_y["Close"]), 2),
                    "volume": float(r_y["Volume"]),
                })
            if cur["px"] == 0 and candles:
                cur["px"] = candles[-1]["close"]
    except Exception:
        pass

    aux_map = {}
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
                    candles.append({
                        "time": ts_sec,
                        "open": float(b.get("open", b.get("o", 0))),
                        "high": float(b.get("high", b.get("h", 0))),
                        "low": float(b.get("low", b.get("l", 0))),
                        "close": float(b.get("close", b.get("c", 0))),
                        "volume": float(b.get("volume", b.get("vol", b.get("v", 0))) or 0),
                    })
            hist_rows = con.execute("SELECT ts, px, vol FROM quote_hist WHERE sym=? ORDER BY ts ASC", (sel_syn,)).fetchall()
            if hist_rows:
                df_h = pd.DataFrame(hist_rows, columns=["ts", "px", "vol"])
                df_h["min_ts"] = (df_h["ts"] // tf_sec).astype(int) * tf_sec
                for m_ts, g in df_h.groupby("min_ts"):
                    candles.append({
                        "time": int(m_ts),
                        "open": float(g["px"].iloc[0]),
                        "high": float(g["px"].max()),
                        "low": float(g["px"].min()),
                        "close": float(g["px"].iloc[-1]),
                        "volume": float(max(g["vol"].iloc[-1] - g["vol"].iloc[0], 0)),
                    })
        except Exception:
            pass

    # Deduplicate & sort candles strictly ascending by time
    c_dict = {c["time"]: c for c in candles if c["close"] > 0}
    candles = [c_dict[k] for k in sorted(c_dict.keys())]

    bk_top = aux_map.get("book") or {}
    bids_top = bk_top.get("Bid") or bk_top.get("bids") or []
    asks_top = bk_top.get("Ask") or bk_top.get("asks") or []
    bid_px_s = f"${float(bids_top[0][0]):,.2f} ({int(bids_top[0][1])})" if bids_top and len(bids_top[0]) >= 2 else "-"
    ask_px_s = f"${float(asks_top[0][0]):,.2f} ({int(asks_top[0][1])})" if asks_top and len(asks_top[0]) >= 2 else "-"
    if bid_px_s == "-" and isinstance(cur.get("raw"), dict):
        bp = cur["raw"].get("bid_price") or cur["raw"].get("bid")
        ap = cur["raw"].get("ask_price") or cur["raw"].get("ask")
        if bp: bid_px_s = f"${float(bp):,.2f}"
        if ap: ask_px_s = f"${float(ap):,.2f}"

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("현재가", f"${cur['px']:,.2f}" if cur["px"] else "-", f"{cur['chg']:+.2f}%" if cur["chg"] is not None else None)
    m2.metric("Bid / Ask", f"{bid_px_s} / {ask_px_s}")
    m3.metric("당일 거래량", f"{int(cur['vol']):,}" if cur["vol"] else "-")
    m4.metric("Zero Gamma", f"${zg_lv:g}" if zg_lv else "-")
    m5.metric("Call / Put Wall", f"${cw_lv or '-'} / ${pw_lv or '-'}")

    with st.expander("⚙️ 지표 편집 (차트 오버레이 · 일목 · 보조지표 · 기간 설정)", expanded=False):
        ed_l, ed_r = st.columns([1.3, 1.0])
        with ed_l:
            st.markdown("**차트 위에 겹쳐 그리기**")
            c_o1, c_o2, c_o3 = st.columns(3)
            show_vwap = c_o1.checkbox("VWAP", value=False, key="ed_vwap")
            show_bb = c_o2.checkbox("볼린저", value=False, key="ed_bb")
            show_ma = c_o3.checkbox("이동평균(MA)", value=False, key="ed_ma")
            c_o4, c_o5, c_o6 = st.columns(3)
            show_walls = c_o4.checkbox("옵션 레벨(벽·플립·1σ)", value=True, key="ed_walls")
            show_vpvr = c_o5.checkbox("매물대·콜풋막대", value=True, key="ed_vpvr")
            show_ichi = c_o6.checkbox("일목 구름·후행", value=True, key="ed_ichi")
            st.markdown("**아래 보조지표 창**")
            c_s1, c_s2, c_s3 = st.columns(3)
            show_vol = c_s1.checkbox("거래량(Vol)", value=True, key="ed_vol")
            show_cvd = c_s2.checkbox("CVD(누적델타)", value=True, key="ed_cvd")
            show_bii = c_s3.checkbox("BII(체결강도)", value=True, key="ed_bii")
            c_s4, c_s5, c_s6 = st.columns(3)
            show_macd = c_s4.checkbox("MACD", value=True, key="ed_macd")
            show_rsi = c_s5.checkbox("RSI", value=False, key="ed_rsi")
            show_icc = c_s6.checkbox("역시계곡선", value=True, key="ed_icc")
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

    vwap_pts, bb_up_pts, bb_dn_pts, vol_pts = [], [], [], []
    ma20_pts, ma200_pts = [], []
    tenkan_pts, kijun_pts, span_a_pts, span_b_pts, chikou_pts = [], [], [], [], []
    cvd_pts, bii_pts, macd_pts, macd_sig_pts, macd_hist_pts, rsi_pts, cloud_pts = [], [], [], [], [], [], []
    vpvr_bins = []
    icc_df = pd.DataFrame()

    if candles:
        df_c = pd.DataFrame(candles)
        tp = (df_c["high"] + df_c["low"] + df_c["close"]) / 3.0
        v_safe = df_c["volume"].replace(0, 1)
        df_c["vwap"] = (tp * v_safe).cumsum() / v_safe.cumsum()
        df_c["ma20"] = df_c["close"].rolling(ma1_len).mean()
        df_c["std20"] = df_c["close"].rolling(bb_len).std()
        df_c["ma200"] = df_c["close"].rolling(min(ma2_len, max(30, len(df_c)//2))).mean()

        # 일목균형표 (9, 26, 52)
        h9 = df_c["high"].rolling(i_ten).max(); l9 = df_c["low"].rolling(i_ten).min()
        h26 = df_c["high"].rolling(i_kij).max(); l26 = df_c["low"].rolling(i_kij).min()
        h52 = df_c["high"].rolling(i_sen).max(); l52 = df_c["low"].rolling(i_sen).min()
        df_c["tenkan"] = (h9 + l9) / 2.0
        df_c["kijun"] = (h26 + l26) / 2.0
        df_c["span_a"] = ((df_c["tenkan"] + df_c["kijun"]) / 2.0).shift(i_kij)
        df_c["span_b"] = ((h52 + l52) / 2.0).shift(i_kij)
        df_c["chikou"] = df_c["close"].shift(-i_kij)

        # CVD (캔들 내 매수/매도 압력 추정 델타 누적)
        rng_hl = (df_c["high"] - df_c["low"]).replace(0, 1e-6)
        bar_delta = df_c["volume"] * ((2.0 * df_c["close"] - df_c["high"] - df_c["low"]) / rng_hl)
        df_c["cvd"] = bar_delta.cumsum()
        df_c["bii"] = bar_delta.cumsum() * 100.0

        # MACD (12, 26, 9)
        ema12 = df_c["close"].ewm(span=m_fast, adjust=False).mean()
        ema26 = df_c["close"].ewm(span=m_slow, adjust=False).mean()
        df_c["macd"] = ema12 - ema26
        df_c["macd_sig"] = df_c["macd"].ewm(span=m_sig, adjust=False).mean()
        df_c["macd_hist"] = df_c["macd"] - df_c["macd_sig"]

        # RSI (14)
        diff_c = df_c["close"].diff()
        gain = diff_c.clip(lower=0).rolling(int(rsi_len)).mean()
        loss = (-diff_c.clip(upper=0)).rolling(int(rsi_len)).mean().replace(0, 1e-6)
        df_c["rsi"] = 100.0 - (100.0 / (1.0 + gain / loss))

        # 역시계곡선 (20봉 종가 MA vs 거래량 MA)
        df_c["vol_ma20"] = df_c["volume"].rolling(int(icc_len)).mean()
        icc_df = df_c.dropna(subset=["ma20", "vol_ma20"]).tail(40).copy()

        # VPVR (매물대 24구간)
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
                vpvr_bins.append({"p": round(p_min + (bi + 0.5) * step, 2), "pct": round(v_arr[bi] / v_mx, 3)})

        for _, r_c in df_c.iterrows():
            t_i = int(r_c["time"])
            is_up = r_c["close"] >= r_c["open"]
            vol_pts.append({"time": t_i, "value": float(r_c["volume"]), "color": "rgba(38,166,154,0.5)" if is_up else "rgba(239,83,80,0.5)"})
            vwap_pts.append({"time": t_i, "value": round(float(r_c["vwap"]), 2)})
            cvd_pts.append({"time": t_i, "value": round(float(r_c["cvd"]), 1)})
            bii_pts.append({"time": t_i, "value": round(float(r_c["bii"]), 0)})
            macd_pts.append({"time": t_i, "value": round(float(r_c["macd"]), 3)})
            macd_sig_pts.append({"time": t_i, "value": round(float(r_c["macd_sig"]), 3)})
            mh = float(r_c["macd_hist"])
            macd_hist_pts.append({"time": t_i, "value": round(mh, 3), "color": "rgba(16,185,129,0.65)" if mh >= 0 else "rgba(239,68,68,0.65)"})
            if pd.notna(r_c["ma20"]):
                ma20_pts.append({"time": t_i, "value": round(float(r_c["ma20"]), 2)})
            if pd.notna(r_c["ma200"]):
                ma200_pts.append({"time": t_i, "value": round(float(r_c["ma200"]), 2)})
            if pd.notna(r_c["ma20"]) and pd.notna(r_c["std20"]):
                bb_up_pts.append({"time": t_i, "value": round(float(r_c["close"].rolling(bb_len).mean().loc[r_c.name] if False else r_c["ma20"] + bb_std * r_c["std20"]), 2)})
                bb_dn_pts.append({"time": t_i, "value": round(float(r_c["ma20"] - bb_std * r_c["std20"]), 2)})
            if pd.notna(r_c["tenkan"]):
                tenkan_pts.append({"time": t_i, "value": round(float(r_c["tenkan"]), 2)})
            if pd.notna(r_c["kijun"]):
                kijun_pts.append({"time": t_i, "value": round(float(r_c["kijun"]), 2)})
            if pd.notna(r_c["span_a"]):
                span_a_pts.append({"time": t_i, "value": round(float(r_c["span_a"]), 2)})
            if pd.notna(r_c["span_b"]):
                span_b_pts.append({"time": t_i, "value": round(float(r_c["span_b"]), 2)})
            if pd.notna(r_c["span_a"]) and pd.notna(r_c["span_b"]):
                cloud_pts.append({"time": t_i, "a": round(float(r_c["span_a"]), 2), "b": round(float(r_c["span_b"]), 2)})
            if pd.notna(r_c["chikou"]):
                chikou_pts.append({"time": t_i, "value": round(float(r_c["chikou"]), 2)})
            if pd.notna(r_c["rsi"]):
                rsi_pts.append({"time": t_i, "value": round(float(r_c["rsi"]), 2)})

    if sig_h_lv is None and candles and len(candles) >= 20:
        df_tmp_s = pd.DataFrame(candles)
        rv_std = float(df_tmp_s["close"].pct_change().dropna().tail(20).std() or 0)
        last_c = float(df_tmp_s["close"].iloc[-1])
        if rv_std > 0 and last_c > 0:
            sig_h_lv = round(last_c * (1.0 + rv_std * 2.0), 2)
            sig_l_lv = round(last_c * (1.0 - rv_std * 2.0), 2)

    pane_cnt = int(show_cvd) + int(show_bii) + int(show_macd) + int(show_rsi)
    total_h = 520 + pane_cnt * 135

    tv_payload = json.dumps({
        "tk": clean_tk,
        "candles": [{k: c[k] for k in ("time", "open", "high", "low", "close")} for c in candles],
        "volumes": vol_pts if show_vol else [],
        "vwap": vwap_pts if show_vwap else [],
        "bb_up": bb_up_pts if show_bb else [],
        "bb_dn": bb_dn_pts if show_bb else [],
        "ma20": ma20_pts if show_ma else [],
        "ma200": ma200_pts if show_ma else [],
        "tenkan": tenkan_pts if show_ichi else [],
        "kijun": kijun_pts if show_ichi else [],
        "span_a": span_a_pts if show_ichi else [],
        "span_b": span_b_pts if show_ichi else [],
        "chikou": chikou_pts if show_ichi else [],
        "vpvr": vpvr_bins if show_vpvr else [],
        "cvd": cvd_pts if show_cvd else [],
        "bii": bii_pts if show_bii else [],
        "cloud": cloud_pts if show_ichi else [],
        "macd": macd_pts if show_macd else [],
        "macd_sig": macd_sig_pts if show_macd else [],
        "macd_hist": macd_hist_pts if show_macd else [],
        "rsi": rsi_pts if show_rsi else [],
        "cw": cw_lv if (show_walls and cw_lv and (not cur["px"] or 0.55 * cur["px"] <= float(cw_lv) <= 1.45 * cur["px"])) else None,
        "pw": pw_lv if (show_walls and pw_lv and (not cur["px"] or 0.55 * cur["px"] <= float(pw_lv) <= 1.45 * cur["px"])) else None,
        "zg": zg_lv if (show_walls and zg_lv and (not cur["px"] or 0.55 * cur["px"] <= float(zg_lv) <= 1.45 * cur["px"])) else None,
        "sig_h": sig_h_lv if show_walls else None,
        "sig_l": sig_l_lv if show_walls else None,
        "delta_k": delta_lv if (show_walls and delta_lv and (not cur["px"] or 0.55 * cur["px"] <= float(delta_lv) <= 1.45 * cur["px"])) else None,
        "gex_c_k": gex_c_lv if (show_walls and gex_c_lv and (not cur["px"] or 0.55 * cur["px"] <= float(gex_c_lv) <= 1.45 * cur["px"])) else None,
        "gex_p_k": gex_p_lv if (show_walls and gex_p_lv and (not cur["px"] or 0.55 * cur["px"] <= float(gex_p_lv) <= 1.45 * cur["px"])) else None,
        "opt_bars": opt_bars if show_vpvr else [],
    })

    tv_html = f"""
    <div id="tv_wrap" style="background:#080c14; border:1px solid #1e293b; border-radius:8px; overflow:hidden;">
    <div style="display:flex; justify-content:space-between; align-items:center; background:#0d131f; border-bottom:1px solid #1e293b; padding:5px 10px; font-family:sans-serif; font-size:12px; color:#cbd5e1;">
      <span id="tv_hint" style="color:#94a3b8;">🖱️ 커서 모드 · 빈 곳 끌기=이동 · 휠=확대/축소</span>
      <button id="tv_fs" style="background:#0f172a;color:#38bdf8;border:1px solid #38bdf8;border-radius:4px;padding:3px 10px;cursor:pointer;font-weight:700;">⛶ 전체화면 확대</button>
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
      <div style="position:relative; flex:1; min-width:0; background:#080c14;">
      <div id="tv_main" style="width:100%; height:460px;"></div>
      <div id="tv_hud" style="position:absolute; top:8px; right:76px; z-index:4; background:rgba(15,23,42,0.85); border:1px solid #334155; border-radius:6px; padding:5px 10px; font-family:monospace; font-size:11px; color:#e2e8f0; pointer-events:none;"></div>
      <canvas id="tv_cloud" style="position:absolute; top:0; left:0; width:100%; height:460px; pointer-events:none; z-index:1;"></canvas>
      <canvas id="tv_vpvr" style="position:absolute; top:0; left:0; width:130px; height:460px; pointer-events:none; z-index:2;"></canvas>
      <canvas id="tv_draw" style="position:absolute; top:0; left:0; width:100%; height:460px; pointer-events:none; z-index:5;"></canvas>
      <div id="tv_cvd" style="width:100%; height:{130 if show_cvd else 0}px; border-top:{'1px solid #2a2e39' if show_cvd else '0'};"></div>
      <div id="tv_bii" style="width:100%; height:{130 if show_bii else 0}px; border-top:{'1px solid #2a2e39' if show_bii else '0'};"></div>
      <div id="tv_macd" style="width:100%; height:{130 if show_macd else 0}px; border-top:{'1px solid #2a2e39' if show_macd else '0'};"></div>
      <div id="tv_rsi" style="width:100%; height:{130 if show_rsi else 0}px; border-top:{'1px solid #2a2e39' if show_rsi else '0'};"></div>
      </div>
      <canvas id="tv_rail" style="width:86px; height:460px; flex-shrink:0; background:#090d16; border-left:1px solid #1e293b;"></canvas>
    </div>
    </div>
    <script src="https://unpkg.com/lightweight-charts@4.2.0/dist/lightweight-charts.standalone.production.js"></script>
    <script>
      const d = {tv_payload};
      const baseOpt = {{
        layout: {{ background: {{ color: "#131722" }}, textColor: "#d1d4dc" }},
        grid: {{ vertLines: {{ color: "rgba(42,46,57,0.35)" }}, horzLines: {{ color: "rgba(42,46,57,0.35)" }} }},
        crosshair: {{ mode: LightweightCharts.CrosshairMode.Normal }},
        rightPriceScale: {{ borderColor: "#2a2e39", minimumWidth: 68 }},
        timeScale: {{ borderColor: "#2a2e39", timeVisible: true, secondsVisible: false }},
      }};
      const elMain = document.getElementById("tv_main");
      const chart = LightweightCharts.createChart(elMain, baseOpt);
      const cs = chart.addCandlestickSeries({{ upColor:"#26a69a", downColor:"#ef5350", borderVisible:false, wickUpColor:"#26a69a", wickDownColor:"#ef5350" }});
      cs.setData(d.candles);
      if (d.volumes.length) {{
        const vs = chart.addHistogramSeries({{ priceFormat:{{type:"volume"}}, priceScaleId:"" }});
        vs.priceScale().applyOptions({{ scaleMargins:{{ top:0.82, bottom:0 }} }});
        vs.setData(d.volumes);
      }}
      if (d.vwap.length) chart.addLineSeries({{ color:"#38bdf8", lineWidth:2, lastValueVisible:false, priceLineVisible:false }}).setData(d.vwap);
      if (d.ma20.length) chart.addLineSeries({{ color:"#22c55e", lineWidth:1, lastValueVisible:false, priceLineVisible:false }}).setData(d.ma20);
      if (d.ma200.length) chart.addLineSeries({{ color:"#eab308", lineWidth:2, lastValueVisible:false, priceLineVisible:false }}).setData(d.ma200);
      if (d.bb_up.length) {{
        chart.addLineSeries({{ color:"rgba(168,85,247,0.7)", lineWidth:1, lineStyle:2, lastValueVisible:false, priceLineVisible:false }}).setData(d.bb_up);
        chart.addLineSeries({{ color:"rgba(168,85,247,0.7)", lineWidth:1, lineStyle:2, lastValueVisible:false, priceLineVisible:false }}).setData(d.bb_dn);
      }}
      if (d.tenkan.length) {{
        chart.addLineSeries({{ color:"#ef4444", lineWidth:1, lastValueVisible:false, priceLineVisible:false }}).setData(d.tenkan);
        chart.addLineSeries({{ color:"#3b82f6", lineWidth:1, lastValueVisible:false, priceLineVisible:false }}).setData(d.kijun);
        chart.addLineSeries({{ color:"rgba(16,185,129,0.55)", lineWidth:1, lastValueVisible:false, priceLineVisible:false }}).setData(d.span_a);
        chart.addLineSeries({{ color:"rgba(239,68,68,0.55)", lineWidth:1, lastValueVisible:false, priceLineVisible:false }}).setData(d.span_b);
        chart.addLineSeries({{ color:"rgba(148,163,184,0.6)", lineWidth:1, lineStyle:2, lastValueVisible:false, priceLineVisible:false }}).setData(d.chikou);
      }}
      if (d.cw) cs.createPriceLine({{ price:d.cw, color:"#10b981", lineWidth:2, lineStyle:2, title:"CALL WALL" }});
      if (d.pw) cs.createPriceLine({{ price:d.pw, color:"#ef4444", lineWidth:2, lineStyle:2, title:"PUT WALL" }});
      if (d.zg) cs.createPriceLine({{ price:d.zg, color:"#f59e0b", lineWidth:2, lineStyle:1, title:"GAMMA" }});
      if (d.sig_h) cs.createPriceLine({{ price:d.sig_h, color:"#f87171", lineWidth:1, lineStyle:2, title:"SIG_H" }});
      if (d.sig_l) cs.createPriceLine({{ price:d.sig_l, color:"#38bdf8", lineWidth:1, lineStyle:2, title:"SIG_L" }});
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
        vpCv.width = 160; vpCv.height = mh;
        const ctx = vpCv.getContext("2d");
        ctx.clearRect(0, 0, 160, mh);
        if (d.opt_bars && d.opt_bars.length) {{
          d.opt_bars.forEach(b => {{
            const y = cs.priceToCoordinate(b.p);
            if (y === null || y < 0 || y > mh) return;
            const wc = Math.round(b.c * 130);
            const wp = Math.round(b.put * 130);
            if (wp > 0) {{ ctx.fillStyle = "rgba(239,68,68,0.8)"; ctx.fillRect(0, y - 4, wp, 8); }}
            if (wc > 0) {{ ctx.fillStyle = "rgba(16,185,129,0.85)"; ctx.fillRect(wp, y - 4, wc, 8); }}
            if (wc + wp > 38) {{
              ctx.font = "10px monospace"; ctx.fillStyle = "#e2e8f0";
              ctx.fillText("C " + b.c_m + "M · P " + b.p_m + "M", wc + wp + 3, y + 3);
            }}
          }});
          return;
        }}
        if (!d.vpvr.length) return;
        d.vpvr.forEach(b => {{
          const y = cs.priceToCoordinate(b.p);
          if (y === null || y < 0 || y > mh) return;
          const w = Math.max(2, b.pct * 115);
          ctx.fillStyle = b.pct > 0.75 ? "rgba(245,158,11,0.55)" : "rgba(56,189,248,0.35)";
          ctx.fillRect(0, y - 4, w, 8);
        }});
      }}
      function drawRail() {{
        const rl = document.getElementById("tv_rail");
        if (!rl) return;
        const mh = elMain.clientHeight || 460;
        rl.width = 86; rl.height = mh;
        const rctx = rl.getContext("2d");
        rctx.clearRect(0, 0, 86, mh);
        rctx.fillStyle = "#64748b"; rctx.font = "bold 10px monospace";
        rctx.fillText("Net γ", 6, 14); rctx.fillText("P/C", 52, 14);
        rctx.strokeStyle = "#1e293b"; rctx.beginPath(); rctx.moveTo(44, 0); rctx.lineTo(44, mh); rctx.stroke();
        if (!d.opt_bars || !d.opt_bars.length) return;
        const maxG = Math.max(...d.opt_bars.map(x => Math.abs(x.net_g || 0)), 0.1);
        d.opt_bars.forEach(b => {{
          const y = cs.priceToCoordinate(b.p);
          if (y === null || y < 20 || y > mh - 8) return;
          const gw = Math.max(2, Math.round(Math.abs(b.net_g || 0) / maxG * 34));
          rctx.fillStyle = (b.net_g || 0) >= 0 ? "#10b981" : "#ef4444";
          rctx.fillRect(6, y - 3, gw, 6);
          const totOi = Math.max((b.c_oi || 0) + (b.p_oi || 0), 1);
          const cw2 = Math.round((b.c_oi || 0) / totOi * 32);
          const pw2 = Math.round((b.p_oi || 0) / totOi * 32);
          rctx.fillStyle = "#10b981"; rctx.fillRect(48, y - 3, cw2, 6);
          rctx.fillStyle = "#ef4444"; rctx.fillRect(48 + cw2, y - 3, pw2, 6);
        }});
      }}

      // 보조지표 차트 동기화
      const subCharts = [];
      if (d.cvd.length) {{
        const cCvd = LightweightCharts.createChart(document.getElementById("tv_cvd"), baseOpt);
        const sCvd = cCvd.addAreaSeries({{ lineColor:"#38bdf8", topColor:"rgba(56,189,248,0.3)", bottomColor:"rgba(56,189,248,0.02)", lineWidth:2, title:"CVD" }});
        sCvd.setData(d.cvd);
        subCharts.push(cCvd);
      }}
      if (d.bii.length) {{
        const cBii = LightweightCharts.createChart(document.getElementById("tv_bii"), baseOpt);
        const sBii = cBii.addLineSeries({{ color:"#2563eb", lineWidth:2, title:"BII (Intraday Intensity)" }});
        sBii.setData(d.bii);
        sBii.createPriceLine({{ price:0, color:"rgba(148,163,184,0.4)", lineStyle:2 }});
        subCharts.push(cBii);
      }}
      if (d.macd.length) {{
        const cMacd = LightweightCharts.createChart(document.getElementById("tv_macd"), baseOpt);
        cMacd.addHistogramSeries({{ title:"MACD Hist" }}).setData(d.macd_hist);
        cMacd.addLineSeries({{ color:"#38bdf8", lineWidth:1.5, title:"MACD" }}).setData(d.macd);
        cMacd.addLineSeries({{ color:"#f59e0b", lineWidth:1.5, title:"Signal" }}).setData(d.macd_sig);
        subCharts.push(cMacd);
      }}
      if (d.rsi.length) {{
        const cRsi = LightweightCharts.createChart(document.getElementById("tv_rsi"), baseOpt);
        const sRsi = cRsi.addLineSeries({{ color:"#a855f7", lineWidth:2, title:"RSI(14)" }});
        sRsi.setData(d.rsi);
        sRsi.createPriceLine({{ price:70, color:"rgba(239,68,68,0.6)", lineStyle:2, title:"70" }});
        sRsi.createPriceLine({{ price:30, color:"rgba(16,185,129,0.6)", lineStyle:2, title:"30" }});
        subCharts.push(cRsi);
      }}
      const hudEl = document.getElementById("tv_hud");
      if (hudEl) {{
        const cTxt = d.candles.length ? d.candles[d.candles.length-1].close : "-";
        hudEl.innerHTML = `<span style="color:#38bdf8;font-weight:700;">${{d.tk}}</span> · 종가 <b style="color:#f8fafc;">$${{cTxt}}` +
          (d.cw ? ` · <span style="color:#10b981;">CW $${{d.cw}}</span>` : "") +
          (d.pw ? ` · <span style="color:#ef4444;">PW $${{d.pw}}</span>` : "") +
          (d.zg ? ` · <span style="color:#f59e0b;">γ $${{d.zg}}</span>` : "");
      }}
      chart.subscribeCrosshairMove(param => {{
        if (!hudEl || !param || !param.time) return;
        const bar = param.seriesData.get(cs);
        if (!bar) return;
        const chgP = bar.open ? (((bar.close - bar.open) / bar.open) * 100).toFixed(2) : "0.00";
        const colP = bar.close >= bar.open ? "#10b981" : "#ef4444";
        hudEl.innerHTML = `<span style="color:#38bdf8;font-weight:700;">${{d.tk}}</span> · 시 ${{bar.open}} 고 ${{bar.high}} 저 ${{bar.low}} 종 <b style="color:${{colP}};">${{bar.close}} (${{chgP}}%)`;
      }});
      chart.timeScale().fitContent();
      subCharts.forEach(sc => sc.timeScale().fitContent());
      chart.timeScale().subscribeVisibleLogicalRangeChange(r => {{
        if (r) subCharts.forEach(sc => sc.timeScale().setVisibleLogicalRange(r));
        drawVpvr();
      }});
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

    col_b1, col_b2 = st.columns(2)
    with col_b1:
        st.subheader("🧱 실시간 60호가 매수·매도 벽")
        bk = aux_map.get("book") or {}
        bids = bk.get("Bid") or bk.get("bids") or []
        asks = bk.get("Ask") or bk.get("asks") or []
        if bids or asks:
            b_pts = [(float(x[0]), float(x[1])) for x in bids[:15] if len(x) >= 2]
            a_pts = [(float(x[0]), float(x[1])) for x in asks[:15] if len(x) >= 2]
            fig_bk = go.Figure()
            if b_pts:
                fig_bk.add_trace(go.Bar(y=[f"${p:g}" for p, _ in b_pts], x=[v for _, v in b_pts], orientation="h", name="매수잔량(Bid)", marker_color="#10b981"))
            if a_pts:
                fig_bk.add_trace(go.Bar(y=[f"${p:g}" for p, _ in a_pts], x=[-v for _, v in a_pts], orientation="h", name="매도잔량(Ask)", marker_color="#ef4444"))
            fig_bk.update_layout(height=340, barmode="relative", plot_bgcolor="#0e1117", paper_bgcolor="#0e1117", font_color="#d1d4dc", margin=dict(l=10, r=10, t=10, b=10))
            st.plotly_chart(fig_bk, use_container_width=True)
        else:
            st.caption("호가창(book) 데이터가 수신되면 매수/매도 잔량 벽이 표시됩니다.")

    with col_b2:
        st.subheader("💰 실시간 자금 유입/유출 분포")
        fl = aux_map.get("flow") or {}
        if isinstance(fl, dict) and fl:
            st.json(fl)
        else:
            st.caption("자금분포(flow) 데이터 수신 대기 중 (3분 주기)")

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
        if con is not None:
            con.close()
        time.sleep(5)
        st.rerun()

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

if nav_menu == MENU_ITEMS[0]:
    st.title("📝 오늘의 종합평 (2026-11-11 장마감 기준)")
    st.caption("InsiderFinance Evening Edge 옵션 플로우·AI 분석·뉴스·다크풀 종합 평가")

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
if nav_menu == MENU_ITEMS[1]:
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
if nav_menu == MENU_ITEMS[4]:
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
if nav_menu == MENU_ITEMS[6]:
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
if nav_menu == MENU_ITEMS[7]:
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
if nav_menu == MENU_ITEMS[8]:
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
if nav_menu == MENU_ITEMS[5]:
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
if nav_menu == MENU_ITEMS[9]:
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
if nav_menu == MENU_ITEMS[10]:
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
if nav_menu == MENU_ITEMS[11]:
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
if nav_menu == MENU_ITEMS[12]:
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
if nav_menu == MENU_ITEMS[13]:
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
if nav_menu == MENU_ITEMS[14]:
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
if nav_menu == MENU_ITEMS[15]:
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

    st.divider()


    with st.expander("➕ 새 자료 / 메모 / 파일 추가하기", expanded=True):
        with st.form("silpi_add_form", clear_on_submit=True):
            fc1, fc2, fc3 = st.columns([1.2, 1.0, 2.0])
            s_cat = fc1.selectbox("카테고리", ["옵션 전략", "차트 패턴", "매매 복기", "자금 관리", "참고 링크/PDF"])
            s_tk = fc2.text_input("관련 종목", "공통", placeholder="예: SOXL, NVDA, 공통").strip().upper() or "공통"
            s_title = fc3.text_input("제목 (비워두면 내용 첫 줄 자동 입력)", placeholder="예: 11/14 SOXL 58C/60C 매집 복기")
            s_body = st.text_area("상세 내용 / 메모", height=110, placeholder="핵심 수치, 진입/손절 기준, 복기 내용을 입력하세요.")
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

    st.caption(f"총 {len(filtered_sp)}건의 자료가 표시되고 있습니다.")
    for idx_sp, item_sp in enumerate(filtered_sp):
        with st.container(border=True):
            h_l, h_r = st.columns([5, 1])
            with h_l:
                st.markdown(f"**[{item_sp.get('카테고리','')}] {item_sp.get('제목','')}**  `{item_sp.get('종목','')}` · {item_sp.get('날짜','')}")
            with h_r:
                if st.button("🗑️ 삭제", key=f"del_sp_{item_sp.get('id', idx_sp)}"):
                    silpi_items = [z for z in silpi_items if z.get("id") != item_sp.get("id")]
                    save_json_file(SILPI_PATH, silpi_items)
                    st.rerun()
            if item_sp.get("내용"):
                st.markdown(item_sp["내용"].replace("\n", "  \n"))
            if item_sp.get("링크"):
                st.markdown(f"🔗 참고 링크: [{item_sp['링크']}]({item_sp['링크']})")
            fp_sp = item_sp.get("파일경로", "")
            if fp_sp and os.path.exists(fp_sp):
                with open(fp_sp, "rb") as fr:
                    st.download_button(f"📥 {item_sp.get('파일명', '첨부파일')}", fr.read(), file_name=item_sp.get("파일명", "file"), key=f"dl_sp_{item_sp.get('id', idx_sp)}")


# ================= TAB: OPTIONS ARCHIVE =================
if nav_menu == "📂 옵션자료실":
    st.title("📂 옵션자료실 (GEX · 그릭스 · 옵션 전략 아카이브)")
    st.caption("옵션 리포트, GEX/HIRO/OI 분석 메모, 전략 파일(PDF·엑셀·이미지) 및 참고 링크를 서버에 영구 저장합니다.")

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
    if st.session_state.pop("opt_saved_ok", False):
        st.success("✅ 옵션자료실에 정상 저장되었습니다!")

    with st.expander("➕ 새 옵션 자료 / 메모 / 파일 추가하기", expanded=True):
        with st.form("opt_add_form", clear_on_submit=True):
            oc1, oc2, oc3 = st.columns([1.2, 1.0, 2.0])
            o_cat = oc1.selectbox("카테고리", ["GEX/그릭스", "OI·Wall 분석", "HIRO·다크풀", "스윕·블록", "0DTE·만기 전략", "참고 파일/PDF"])
            o_tk = oc2.text_input("관련 종목", "공통", placeholder="예: SOXL, NVDA, SPX, 공통").strip().upper() or "공통"
            o_title = oc3.text_input("제목 (비워두면 내용 첫 줄 자동 입력)", placeholder="예: 11/14 NVDA 150P/200C GEX 구조")
            o_body = st.text_area("상세 내용 / 메모", height=110, placeholder="GEX·DEX·OI·스윕 분석 내용이나 전략 기준을 입력하세요.")
            oc4, oc5 = st.columns([1.5, 1.5])
            o_link = oc4.text_input("참고 URL (선택)", placeholder="https://...")
            o_file = oc5.file_uploader("파일 첨부 (PDF·이미지·CSV·XLSX 등)", type=None, key="opt_file_up")
            submitted_o = st.form_submit_button("💾 옵션자료실에 저장", type="primary")
            if submitted_o:
                saved_fp = ""
                saved_fn = ""
                if o_file is not None:
                    safe_n = f"{int(time.time())}_{os.path.basename(o_file.name)}"
                    saved_fp = os.path.join(OPT_VAULT_DIR, safe_n)
                    with open(saved_fp, "wb") as fw:
                        fw.write(o_file.getbuffer())
                    saved_fn = o_file.name
                auto_t = o_title.strip() or (o_body.strip().splitlines()[0][:50] if o_body.strip() else "") or saved_fn or o_link.strip()
                if auto_t:
                    opt_items.insert(0, {
                        "id": f"op_{int(time.time()*1000)}",
                        "날짜": pd.Timestamp.now(tz="Asia/Seoul").strftime("%Y-%m-%d %H:%M"),
                        "카테고리": o_cat,
                        "종목": o_tk,
                        "제목": auto_t,
                        "내용": o_body.strip(),
                        "링크": o_link.strip(),
                        "파일경로": saved_fp,
                        "파일명": saved_fn,
                    })
                    save_json_file(OPT_VAULT_PATH, opt_items)
                    st.session_state["opt_saved_ok"] = True
                    st.rerun()
                else:
                    st.warning("제목, 내용, 파일, 또는 링크 중 하나는 입력해 주세요.")

    oc_f1, oc_f2, oc_f3 = st.columns([1.2, 1.2, 2.0])
    o_cats = ["전체"] + sorted(list({x.get("카테고리", "기타") for x in opt_items}))
    o_tks = ["전체"] + sorted(list({x.get("종목", "공통") for x in opt_items}))
    fo_cat = oc_f1.selectbox("카테고리 필터", o_cats, key="op_f_cat")
    fo_tk = oc_f2.selectbox("종목 필터", o_tks, key="op_f_tk")
    fo_kw = oc_f3.text_input("🔍 키워드 검색", "", placeholder="제목 또는 내용 검색...", key="op_f_kw").strip().lower()

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
    for idx_op, item_op in enumerate(filtered_op):
        with st.container(border=True):
            oh_l, oh_r = st.columns([5, 1])
            with oh_l:
                st.markdown(f"**[{item_op.get('카테고리','')}] {item_op.get('제목','')}**  `{item_op.get('종목','')}` · {item_op.get('날짜','')}")
            with oh_r:
                if st.button("🗑️ 삭제", key=f"del_op_{item_op.get('id', idx_op)}"):
                    opt_items = [z for z in opt_items if z.get("id") != item_op.get("id")]
                    save_json_file(OPT_VAULT_PATH, opt_items)
                    st.rerun()
            if item_op.get("내용"):
                st.markdown(item_op["내용"].replace("\n", "  \n"))
            if item_op.get("링크"):
                st.markdown(f"🔗 참고 링크: [{item_op['링크']}]({item_op['링크']})")
            fp_op = item_op.get("파일경로", "")
            if fp_op and os.path.exists(fp_op):
                with open(fp_op, "rb") as fr:
                    st.download_button(f"📥 {item_op.get('파일명', '첨부파일')}", fr.read(), file_name=item_op.get("파일명", "file"), key=f"dl_op_{item_op.get('id', idx_op)}")