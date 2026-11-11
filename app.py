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

# 상단 모닝 브리핑 배너
st.markdown("""
<div class='morning-banner'>
    <div style='display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;'>
        <span style='font-size:16px; font-weight:800; color:#60a5fa;'>☀️ AI 옵션 모닝 1분 핵심 브리핑 (장전 체크포인트)</span>
        <span style='background:#2563eb; color:white; font-size:11px; font-weight:700; padding:2px 8px; border-radius:4px;'>2026-11-10 기준</span>
    </div>
    <div style='display:grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 12px; font-size:13px; color:#e2e8f0; line-height:1.5;'>
        <div style='background:rgba(239,68,68,0.1); border-left:3px solid #ef4444; padding:8px 10px; border-radius:4px;'>
            <strong>🔴 반도체/빅테크 풋 헷지 지속</strong><br>
            NVDA 주간 $1.1B 풋 쏠림 및 $50M 장기 풋 블록 추가. CPI 쇼크 후 기관 포트폴리오 하방 방어 압력 최고조.
        </div>
        <div style='background:rgba(16,185,129,0.1); border-left:3px solid #10b981; padding:8px 10px; border-radius:4px;'>
            <strong>🟢 에너지 & 우라늄 독자적 콜 집중</strong><br>
            유가 조정에도 CCJ($24.7M) 및 VLO($5.3M)에 강력한 상방 콜 유입. 인플레이션 헷지 자금 유입 지속.
        </div>
        <div style='background:rgba(245,158,11,0.1); border-left:3px solid #f59e0b; padding:8px 10px; border-radius:4px;'>
            <strong>⚠️ 지수 스윕(350만건) & 소형주 90% 풋</strong><br>
            SPY/QQQ에 수백만 계약 긴급 스윕 체결. 12월 금리 인상 가능성으로 중소형주(IWM)를 핵심 매크로 헷지로 사용 중.
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
    "📰 트레이딩 뉴스 전문 (19선)"
])

DAILY_METRICS = {
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

DEFAULT_FLOWS = [
    ("2026-11-10", "SNDK", "10:26 AM", "Call", "• A", "2026-11-13", "$873.50", "$900", "3%", "$28.14", "380", "1663", "120%", "SWEEP", "$1.1M", "33"),
    ("2026-11-10", "SNDK", "10:25 AM", "Call", "• A", "2026-11-13", "$872.50", "$900", "3%", "$27.75", "381", "1663", "120%", "SWEEP", "$1.1M", "33"),
    ("2026-11-10", "SNDK", "10:02 AM", "Call", "• A", "2026-11-13", "$909.00", "$1100", "21%", "$2.99", "401", "2154", "120%", "SWEEP", "$120K", "43"),
    ("2026-10-23", "SNDK", "02:52 PM", "Put", "• A", "2026-10-23", "$1620.00", "$1600", "-1%", "$18.50", "1000", "450", "85%", "BLOCK", "$19.0M", "35"),
    ("2026-10-23", "SNDK", "02:52 PM", "Put", "• A", "2026-10-23", "$1620.00", "$1600", "-1%", "$18.50", "1000", "450", "85%", "BLOCK", "$19.0M", "35"),
    ("2026-10-16", "SNDK", "10:21 AM", "Call", "• A", "2027-01-15", "$1680.00", "$1720", "2%", "$95.00", "980", "220", "55%", "SWEEP", "$9.3M", "35"),
    ("2026-09-25", "SNDK", "09:53 AM", "Call", "• A", "2026-09-25", "$1750.00", "$1782.5", "2%", "$38.00", "1950", "600", "70%", "SWEEP", "$7.4M", "35"),
    ("2026-11-10", "SMMT", "02:39 PM", "Call", "• A", "2026-11-20", "$17.50", "$30", "71%", "$0.25", "874", "340", "150%", "SWEEP", "$22K", "38"),
    ("2026-11-10", "BRBR", "10:30 AM", "Call", "• A", "2026-11-20", "$9.85", "$12.5", "27%", "$0.88", "400", "120", "85%", "SWEEP", "$35K", "32"),
    ("2026-11-10", "BRBR", "10:30 AM", "Call", "• A", "2026-11-20", "$9.85", "$12.5", "27%", "$0.80", "300", "120", "85%", "SWEEP", "$24K", "32"),
    ("2026-11-10", "BRBR", "10:30 AM", "Call", "• A", "2026-11-20", "$9.85", "$12.5", "27%", "$0.73", "300", "120", "85%", "SWEEP", "$22K", "32"),
    ("2026-11-10", "DBX", "11:42 AM", "Put", "• A", "2027-04-16", "$20.30", "$25", "23%", "$1.28", "400", "1500", "42%", "SWEEP", "$51K", "35"),
    ("2026-11-10", "DBX", "11:42 AM", "Put", "• A", "2027-04-16", "$20.30", "$25", "23%", "$1.28", "265", "1500", "42%", "SWEEP", "$34K", "35"),
    ("2026-11-10", "DBX", "11:39 AM", "Put", "• A", "2027-04-16", "$20.30", "$25", "23%", "$1.27", "370", "1500", "42%", "SWEEP", "$47K", "35"),
    ("2026-11-10", "PEPG", "02:46 PM", "Put", "• A", "2026-11-20", "$4.35", "$5", "15%", "$0.70", "600", "220", "110%", "SWEEP", "$42K", "34"),
    ("2026-11-10", "PEPG", "02:32 PM", "Call", "• A", "2026-11-20", "$4.35", "$5", "15%", "$0.18", "610", "310", "110%", "SWEEP", "$11K", "30"),
    ("2026-11-10", "GRAB", "03:42 PM", "Put", "• A", "2026-11-20", "$2.72", "$3", "10%", "$0.38", "500", "1200", "75%", "SWEEP", "$19K", "31"),
    ("2026-11-10", "GRPN", "11:21 AM", "Put", "• A", "2027-01-15", "$6.10", "$8", "31%", "$1.33", "300", "850", "95%", "SWEEP", "$40K", "40"),
    ("2026-11-10", "GFL", "12:59 PM", "Call", "• A", "2026-11-20", "$40.50", "$45", "11%", "$3.55", "450", "1200", "45%", "BLOCK", "$160K", "35"),
    ("2026-11-10", "NVDA", "12:14 PM", "Put", "• A", "2027-01-15", "$145.20", "$140", "4%", "$18.50", "27000", "15200", "58%", "BLOCK", "$50.0M", "50"),
    ("2026-11-10", "MU", "10:56 AM", "Put", "• A", "2027-01-15", "$795.20", "$1050", "-32%", "$320.00", "1085", "450", "48%", "SPLIT", "$34.7M", "48"),
    ("2026-11-10", "ASML", "12:06 PM", "Call", "• A", "2027-02-19", "$1680.00", "$1740", "4%", "$175.00", "730", "12", "42%", "BLOCK", "$12.8M", "45"),
    ("2026-11-10", "MSFT", "01:05 PM", "Call", "• A", "2026-12-18", "$565.00", "$580", "3%", "$86.00", "1500", "1200", "28%", "BLOCK", "$12.9M", "42"),
    ("2026-11-10", "SPX", "01:12 PM", "Call", "• A", "2027-06-17", "$5980.00", "$7000", "17%", "$225.00", "15000", "4200", "18%", "SPLIT", "$338.5M", "55"),
]

SHEET_URL = "https://docs.google.com/spreadsheets/d/1_FWy_B9a6t1txau06PbeEMy9S9B1GsMgWZLGfMmMG7w/export?format=csv&gid=0"

@st.cache_data(ttl=60)
def load_all_flows():
    try:
        df = pd.read_csv(SHEET_URL)
        res = []
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
            res.append((dt, tk, tm, cp, "• A", exp, "-", stk, "-", "-", "-", "-", "-", typ, pr, "35"))
        if len(res) >= 3: return res[::-1]
    except Exception: pass
    return DEFAULT_FLOWS

# ================= TAB 1: TOP TICKER =================
with tab1:
    st.sidebar.title("⚙️ OptionHub")
    st.sidebar.success("🟢 실시간 데이터 연동 중")
    
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
    
    if sel_date == "2026-11-10" and sel_tk in DAILY_METRICS:
        m = DAILY_METRICS[sel_tk]
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
    st.caption("출처: InsiderFinance Top 10 Moonshot Flows & Momentum Options Activity (2026-11-10)")

    col_m1, col_m2 = st.columns([3, 2])
    
    with col_m1:
        st.subheader("🎯 Top 10 Moonshot Flows (기관 로또성 대박 콜옵션)")
        moonshots = [
            ("GME", "12:49 PM", "Call", "32", "2026-11-27", "$35K", "Unusual · Top Position · Sweep", "단기 밈주식 폭발적 변동성 노린 초외가격 스윕"),
            ("CLSK", "01:52 PM", "Call", "8", "2026-12-18", "$323K", "Top Position · Block", "비트코인 채굴주 대형 콜 블록 체결"),
            ("GFL", "09:47 AM", "Call", "50", "2026-11-20", "$1.0M", "Unusual · Split", "폐기물/환경 기업에 100만 달러 규모 이례적 콜 스플릿"),
            ("XENE", "02:41 PM", "Call", "50", "2027-01-15", "$66K", "Top Position · Sweep", "바이오텍 임상 파이프라인 촉매 기대 상방 베팅"),
            ("ORCL", "02:35 PM", "Call", "165", "2026-12-18", "$280K", "Sweep", "클라우드 인프라 성장 기대감 속 콜 스윕 집중"),
            ("BRBR", "10:30 AM", "Call", "12.5", "2026-11-20", "$35K", "Unusual · Top Position · Sweep", "음료 기업 실적 발표 직전 연속 콜 스윕"),
            ("HNRG", "01:30 PM", "Call", "15", "2027-01-15", "$11K", "Sweep", "에너지 원자재 상승 사이클 롱 콜"),
            ("SUPN", "09:44 AM", "Call", "30.87", "2026-12-18", "$23K", "Top Position · Sweep", "제약 바이오 소형주 타겟 포지셔닝"),
            ("IONQ", "02:20 PM", "Call", "70", "2027-01-15", "$42K", "Sweep", "양자컴퓨팅 테마 대장주 초장기 콜 스윕"),
            ("GFL", "09:58 AM", "Call", "50", "2026-11-20", "$171K", "Unusual · Block", "당일 연속 유입된 두 번째 대형 콜 블록")
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
            "Ticker": ["GRPN", "GFL", "DBX", "PEPG", "JRVR", "HIMS", "XENE", "SBET", "BRBR", "BP"],
            "Multiple": [31.3, 11.0, 10.4, 6.6, 6.1, 4.2, 4.1, 3.7, 3.4, 3.2]
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
        
        st.info("💡 **트레이딩 팁:** 평소 대비 5~30배 이상 옵션 거래량이 폭증한 종목은 2~3일 내 주가에 대형 뉴스나 급격한 방향성 슈팅이 나타날 확률이 매우 높습니다.")

# ================= TAB 3: 5-DAY FLOW & GEX SUPPORT/RESISTANCE =================
with tab3:
    st.title("📅 5일 누적 기관 수급 추세 & 핵심 지지·저항선 (GEX)")
    st.caption("출처: InsiderFinance Equities 5-Day Flow & Gamma Exposure Analysis")

    st.subheader("📊 주요 대형주 5일 누적 풋/콜 비율 & 기관 프리미엄 총액")
    
    five_day_data = [
        {"Ticker": "NVDA", "Call_Pct": 32, "Put_Pct": 68, "Prem_M": 1115.6, "OTM": "13%", "Vol": "2.8M"},
        {"Ticker": "TSLA", "Call_Pct": 42, "Put_Pct": 58, "Prem_M": 294.9, "OTM": "6%", "Vol": "679K"},
        {"Ticker": "AAPL", "Call_Pct": 50, "Put_Pct": 50, "Prem_M": 116.6, "OTM": "4%", "Vol": "595K"},
        {"Ticker": "INTC", "Call_Pct": 20, "Put_Pct": 80, "Prem_M": 568.6, "OTM": "-3%", "Vol": "499K"},
        {"Ticker": "AMZN", "Call_Pct": 84, "Put_Pct": 16, "Prem_M": 81.4, "OTM": "5%", "Vol": "280K"},
        {"Ticker": "IREN", "Call_Pct": 41, "Put_Pct": 59, "Prem_M": 51.6, "OTM": "50%", "Vol": "254K"},
        {"Ticker": "CRWV", "Call_Pct": 24, "Put_Pct": 76, "Prem_M": 76.7, "OTM": "31%", "Vol": "252K"},
        {"Ticker": "MU", "Call_Pct": 49, "Put_Pct": 51, "Prem_M": 475.9, "OTM": "16%", "Vol": "247K"},
        {"Ticker": "PCG", "Call_Pct": 100, "Put_Pct": 0, "Prem_M": 10.1, "OTM": "19%", "Vol": "204K"},
        {"Ticker": "PLTR", "Call_Pct": 26, "Put_Pct": 74, "Prem_M": 80.2, "OTM": "12%", "Vol": "179K"}
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
    st.subheader("🎯 핵심 종목별 감마 익스포저 (GEX) 지지 & 저항 마지노선")
    
    col_g1, col_g2, col_g3, col_g4 = st.columns(4)
    with col_g1:
        st.markdown("""
        <div class='gex-card'>
            <div style='font-size:16px; font-weight:800; color:#00e676;'>NVDA</div>
            <div style='font-size:12px; color:#94a3b8; margin: 4px 0;'>현재가: $145.20</div>
            <div style='font-size:13px; color:#f87171;'><strong>풋 지지선: $135 / $140</strong></div>
            <div style='font-size:11px; color:#64748b;'>$50M 대형 풋 벽 형성</div>
