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
    if df_gex.empty or len(df_gex) < 2:
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
    .kpi-box { background: #131722; border-radius: 4px; padding: 8px 6px; text-align: center; border: 1px solid #232733; flex: 1; min-width: 75px; }
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

# 상단 1분 모닝 브리핑 배너 (2026-11-11 최신 반영)
st.markdown("""
<div class='morning-banner'>
    <div style='display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;'>
        <span style='font-size:16px; font-weight:800; color:#60a5fa;'>☀️ AI 옵션 모닝 1분 핵심 브리핑 (장전 체크포인트)</span>
        <span style='background:#2563eb; color:white; font-size:11px; font-weight:700; padding:2px 8px; border-radius:4px;'>2026-11-11 최신본</span>
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
}
tide_cache = load_json_file(os.path.expanduser("~/.optionhub_tide_brief.json"), DEFAULT_TIDE_BRIEF)
if not (tide_cache.get("tide") or tide_cache.get("flows")):
    tide_cache = DEFAULT_TIDE_BRIEF
if tide_cache.get("tide") or tide_cache.get("flows") or tide_cache.get("warnings"):
    tide_str = tide_cache.get("tide", "-")
    flows_html = " · ".join([f"<span style='color:{'#34d399' if '콜' in x.get('dir','') else '#f87171'}; font-weight:700;'>{x['tk']} {x['net']}</span>" for x in tide_cache.get("flows", [])[:8]])
    warn_html = " · ".join([f"<span style='background:rgba(245,158,11,0.18); color:#fbbf24; padding:1px 6px; border-radius:4px; font-size:12px;'>{w['tk']}: {w['tag']}</span>" for w in tide_cache.get("warnings", [])[:6]])
    dir_note = tide_cache.get("dir_note", "")
    st.markdown(f"""
<div style='background:#131722; border:1px solid #2a2e39; border-left:4px solid #38bdf8; border-radius:8px; padding:10px 14px; margin-bottom:14px; font-size:13px; color:#e2e8f0;'>
  <div style='display:flex; justify-content:space-between; margin-bottom:6px;'>
    <span><strong style='color:#38bdf8;'>🌊 Market Tide & 순자금 흐름</strong> &nbsp;|&nbsp; {tide_str}</span>
    <span style='color:#94a3b8; font-size:11px;'>갱신: {tide_cache.get('updated', '-')}</span>
  </div>
  {f"<div style='margin-bottom:5px;'><strong>자금 TOP:</strong> {flows_html}</div>" if flows_html else ""}
  {f"<div style='margin-bottom:4px;'><strong>⚠️ OI·커버드콜 검증:</strong> {warn_html}</div>" if warn_html else ""}
  {f"<div style='color:#cbd5e1; font-size:12px;'>💡 {dir_note}</div>" if dir_note else ""}
</div>
""", unsafe_allow_html=True)


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
    "📰 뉴스 (7선)"
]
st.sidebar.title("⚙️ OptionHub")
st.sidebar.success("🟢 실시간 데이터 연동 중 (11/12 반영)")
nav_menu = st.sidebar.radio("📌 메뉴 이동", MENU_ITEMS, index=0)


DAILY_METRICS_BY_DATE = {
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
    # ================= 2026-11-11 (최신 Evening Edge) =================
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
    st.subheader("📊 Barchart 특이옵션 & Menthor Q 그릭스/GEX 리포트 (구글 시트 실시간 연동)")
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

            # GEX 차트 (행사가별 Net GEX)
            if "GEX($M)" in df_e.columns:
                gex_by_k = df_e.groupby("행사가")["GEX($M)"].sum().reset_index()
                call_wall = gex_by_k.loc[gex_by_k["GEX($M)"].idxmax(), "행사가"] if not gex_by_k.empty else 0
                put_wall = gex_by_k.loc[gex_by_k["GEX($M)"].idxmin(), "행사가"] if not gex_by_k.empty else 0
                zero_g = calc_zero_gamma(gex_by_k, spot_val)
                zg_txt = f"**${zero_g:g}**" if zero_g else "없음(단일 부호)"
                st.info(f"🧱 **핵심 감마 레벨** — Zero Gamma(감마 플립): {zg_txt} | Call Wall(저항): **${call_wall:g}** | Put Wall(지지): **${put_wall:g}**")

                gex_by_k["색상"] = gex_by_k["GEX($M)"].apply(lambda x: "Positive (+GEX)" if x >= 0 else "Negative (-GEX)")
                fig_gex = px.bar(
                    gex_by_k, x="행사가", y="GEX($M)", color="색상",
                    color_discrete_map={"Positive (+GEX)": "#00e676", "Negative (-GEX)": "#f23645"},
                    title=f"<b>{oi_tk} ({sel_oi_exp}) 행사가별 Net GEX (감마 익스포저, $M)</b>"
                )
                if spot_val and spot_val > 0:
                    fig_gex.add_vline(x=spot_val, line_dash="dash", line_color="#fbbf24", annotation_text=f"Spot ${spot_val}")
                if zero_g:
                    fig_gex.add_vline(x=zero_g, line_dash="dot", line_color="#38bdf8", annotation_text=f"Zero Gamma ${zero_g:g}")
                fig_gex.update_layout(plot_bgcolor="#0e1117", paper_bgcolor="#0e1117", font_color="#d1d4dc")
                st.plotly_chart(fig_gex, use_container_width=True)

            # Call vs Put OI 막대그래프 + DEX 차트 나란히 배치
            ch1, ch2 = st.columns(2)
            with ch1:
                oi_grp = df_e.groupby(["행사가", "구분"])["OI"].sum().reset_index()
                fig_oi = px.bar(
                    oi_grp, x="행사가", y="OI", color="구분", barmode="group",
                    color_discrete_map={"Call": "#00e676", "Put": "#f23645"},
                    title=f"<b>{oi_tk} 행사가별 Call vs Put OI</b>"
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
                        title=f"<b>{oi_tk} 행사가별 Delta Exposure (DEX, $M)</b>"
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
        title="<b>기관 프리미엄 규모 및 Call 비중 (%)</b> (초록색: 콜 우세, 붉은색: 풋 우세)"
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