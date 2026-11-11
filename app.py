import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

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

tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
    "🔥 Top Ticker 전종목 플로우",
    "🚀 Top 10 문샷(Moonshot) 급등주",
    "📅 5일 누적 기관 수급 & GEX",
    "⚡ AI Options Plays & Noteworthy",
    "📊 Options Top Tickers 차트",
    "🗺️ 기관 수급 히트맵 & 테마 분석",
    "📰 트레이딩 뉴스 전문 (7선)"
])

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

# ================= TAB 1: TOP TICKER =================
with tab1:
    st.sidebar.title("⚙️ OptionHub")
    st.sidebar.success("🟢 실시간 데이터 연동 중 (11/11 반영)")
    
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

# ================= TAB 2: TOP 10 MOONSHOT FLOWS =================
with tab2:
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
with tab3:
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
with tab4:
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
with tab5:
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
with tab6:
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
with tab7:
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