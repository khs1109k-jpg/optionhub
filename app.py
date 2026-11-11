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

# ================= 상단 1분 모닝 핵심 브리핑 배너 =================
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

# 7개 풀 탭 구성
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
            <div style='font-size:13px; color:#4ade80; margin-top:4px;'><strong>콜 저항선: $150</strong></div>
        </div>
        """, unsafe_allow_html=True)
    with col_g2:
        st.markdown("""
        <div class='gex-card'>
            <div style='font-size:16px; font-weight:800; color:#00e676;'>SPY / SPX</div>
            <div style='font-size:12px; color:#94a3b8; margin: 4px 0;'>현재가: $598.00</div>
            <div style='font-size:13px; color:#f87171;'><strong>풋 지지선: $580</strong></div>
            <div style='font-size:11px; color:#64748b;'>기관 대량 풋 헷지 바닥</div>
            <div style='font-size:13px; color:#4ade80; margin-top:4px;'><strong>콜 저항선: $600 / 7000</strong></div>
        </div>
        """, unsafe_allow_html=True)
    with col_g3:
        st.markdown("""
        <div class='gex-card'>
            <div style='font-size:16px; font-weight:800; color:#00e676;'>MU</div>
            <div style='font-size:12px; color:#94a3b8; margin: 4px 0;'>현재가: $795.20</div>
            <div style='font-size:13px; color:#f87171;'><strong>풋 지지선: $1050 (ITM)</strong></div>
            <div style='font-size:11px; color:#64748b;'>$62M 딥 ITM 헷지 블록</div>
            <div style='font-size:13px; color:#4ade80; margin-top:4px;'><strong>콜 저항선: $1100</strong></div>
        </div>
        """, unsafe_allow_html=True)
    with col_g4:
        st.markdown("""
        <div class='gex-card'>
            <div style='font-size:16px; font-weight:800; color:#00e676;'>MSFT</div>
            <div style='font-size:12px; color:#94a3b8; margin: 4px 0;'>현재가: $565.00</div>
            <div style='font-size:13px; color:#f87171;'><strong>풋 지지선: $550</strong></div>
            <div style='font-size:11px; color:#64748b;'>하방 방어선 확보</div>
            <div style='font-size:13px; color:#4ade80; margin-top:4px;'><strong>콜 저항선: $580</strong></div>
        </div>
        """, unsafe_allow_html=True)

# ================= TAB 4: AI OPTIONS PLAYS & NOTEWORTHY =================
with tab4:
    st.title("⚡ AI Options Plays & Noteworthy Trades")
    st.caption("출처: InsiderFinance AI Options Plays BETA & AI Noteworthy Trades (2026-11-10)")

    st.subheader("🎯 AI Options Plays BETA (기관 추천 실전 옵션 전략 6선)")
    plays = [
        ("1. NVDA Bear Put Spread (베어 풋 스프레드)", "Bearish (5/5 Strength)", False,
         "향후 1~3개월 만기의 약내가격(ITM) 또는 약외가격(OTM) 풋 스프레드를 활용하여 기술주 변동성이 진정되더라도 프리미엄 비용을 방어하면서 추가 하방 수익을 추구합니다.",
         "Use slightly in the money to modestly out of the money put spreads in the next 1-3 months to lean into further downside while containing premium if tech volatility cools.",
         "기술주 옵션의 약 70%가 풋옵션에 쏠려 있으며, NVDA 단일 종목에서만 주간 11억 달러 이상의 프리미엄이 하방으로 치우쳐 있고 오늘 5천만 달러 규모의 Above-Ask 원월물 풋 블록이 상단을 제한하고 있습니다. 이는 기술주 주식 매도세, 예상치를 웃돈 CPI, 매파적 연준 기조와 맞물려 헷지 수요가 높은 상태로 유지되는 한 AI 하드웨어 밸류에이션을 취약하게 만듭니다.",
         "Tech options are roughly seventy percent puts and NVDA alone carries over $1.1B of weekly premium tilted to downside, capped by today's $50M above ask long dated put block. That aligns with strong equity side distribution in technology and a hot CPI plus hawkish Fed tone, leaving AI hardware vulnerable if hedging demand remains elevated."),

        ("2. CCJ Long Call (우라늄 롱 콜 전략)", "Bullish (5/5 Strength)", True,
         "1~3개월 만기의 등가격(ATM) 또는 약외가격(OTM) 콜옵션을 매수하여 에너지 심리가 유가 하락을 따라 잠시 주춤하더라도 변동성을 견디면서 우라늄 강세 랠리에 동참합니다.",
         "Favor at the money to modestly out of the money calls 1-3 months out to ride uranium strength while allowing for volatility if energy sentiment briefly tracks softer crude.",
         "주간 CCJ 옵션은 압도적으로 콜옵션이 주도하고 있으며, 전반적인 에너지 섹터 약세 속에서도 최근 2,470만 달러 규모의 3월 만기 상방 콜 블록 체결 및 5일 연속 주가 상승을 기록했습니다. 이러한 지속적인 상방 포지셔닝은 인플레이션 및 지정학적 리스크 속에서 우라늄과 에너지 전환 테마를 선호하는 시장 테마에 완벽히 부합합니다.",
         "Weekly CCJ options are overwhelmingly call driven with a recent $24.7M top position March call block and five day price gains despite broader energy weakness. That persistent upside positioning fits our theme of inflation and geopolitical risk keeping uranium and transition energy in favor."),

        ("3. ASML Bull Call Spread (불 콜 스프레드)", "Bullish (4/5 Strength)", True,
         "1~3개월 만기의 등가격(ATM) 또는 약외가격(OTM) 콜 스프레드를 매수하여 첨단 반도체 장비의 상대적 강세에 참여하되 섹터 전반의 매도세가 가속될 경우 리스크를 제한합니다.",
         "Use at the money to modestly out of the money call spreads 1-3 months out to participate in relative strength in high end semicap while capping risk if sector wide tech distribution accelerates.",
         "ASML은 2,000만 달러 이상의 Above-Ask 최상위 콜 블록을 끌어모았으며 주간 플로우가 콜옵션에 크게 치우쳐 있고 약세 기술주 대비 5일 수익률이 플러스입니다. 광범위한 AI 하드웨어 헷지 압력 속에서도 독점적 노광 장비 리더에 대한 타겟 매집을 시사합니다.",
         "ASML has attracted over $20M in above ask top position call blocks with weekly flow heavily call skewed and five day performance positive against a weak tech sector. Points to targeted accumulation of upside in a key equipment leader."),

        ("4. VLO Bull Call Spread (정유주 불 콜 스프레드)", "Bullish (4/5 Strength)", True,
         "2~6주 만기의 약외가격(OTM) 콜 스프레드를 매수하여 건설적인 정유 상방을 취하되 유가나 정제마진이 추가 약세를 보일 경우 노출을 제한합니다.",
         "Consider slightly out of the money call spreads 2-6 weeks out to express constructive refinery upside while limiting exposure if crude prices or crack spreads soften further.",
         "에너지 옵션은 일간 및 주간 모두 콜 프리미엄이 지배하고 있으며, VLO는 약외가격에 531만 달러 규모의 Above-Ask 최상위 콜 스플릿을 기록했습니다. 인플레이션과 지정학적 리스크 속에서 기관들이 섹터 조정을 틈타 상방 레버리지를 추가하고 있습니다.",
         "Energy options show call premium dominating daily and weekly flow, and VLO just printed a $5.3M above ask top position call slightly out of the money. Suggests institutions adding refinery upside into sector weakness."),

        ("5. HIMS Long Put (롱 풋 하방 공략)", "Bearish (4/5 Strength)", False,
         "2~6주 만기의 약외가격(OTM) 풋옵션을 매수하여 하락 추세를 추종하되 변동성이 큰 소형주의 급격한 숏커버링 랠리 위험을 관리합니다.",
         "Favor slightly out of the money puts 2-6 weeks out to press the downtrend while allowing room for sharp short covering rallies in this volatile small cap.",
         "HIMS는 5일간 25% 이상 급락했으며 주간/일간 옵션 플로우 모두 풋옵션이 압도하고 있습니다. 시간대별 테이프에서도 일방적인 하방 포지셔닝이 관찰되어 트레이더들이 즉각적인 평균 회귀 반등보다는 지속적인 주가 압박을 예상하고 있습니다.",
         "HIMS is down more than 25% over 5 days with weekly/daily flow dominated by puts. Alignment of price momentum and protection demand indicates traders expect continued pressure rather than immediate mean reversion."),

        ("6. RIOT Long Call (비트코인 채굴주 롱 콜)", "Bullish (4/5 Strength)", True,
         "향후 1~2주 만기의 등가격(ATM) 또는 약외가격(OTM) 단기 콜옵션으로 가상자산 채굴주 모멘텀을 공략하되 위험 심리 악화 시 급격한 반락 위험을 감수합니다.",
         "Use at the money to modestly out of the money calls in the next 1-2 weeks to target ongoing crypto miner momentum, accepting the risk of sharp reversals if broader risk sentiment sours.",
         "RIOT은 5일 동안 20% 이상 급등했으며 주간 옵션이 전적으로 콜에 집중되어 있고 장마감 직전 신규 Above-Ask 최상위 콜 블록이 유입되었습니다. 매크로 헷지가 거센 상황에서도 고베타 주식 및 크립토 익스포저를 위한 레버리지 수단으로 채굴주를 활용하고 있습니다.",
         "RIOT has rallied over 20% in 5 days with weekly options entirely in calls and a fresh above ask top position call block hitting into the close. Traders using miners as leveraged vehicles for crypto exposure.")
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
        ("NVDA 140 PUT 2027-1-15 @ $50M", "2026-11-10 12:14 PM", "Hedge (5/5 Strength)", False, "Above Ask · Top Position · Block",
         "미결제약정을 초과하는 140달러 행사가의 5천만 달러($50M) 규모 Above-Ask 블록 매수는 NVDA의 장기 풋 하방 압력을 가중시킵니다. 뜨거운 CPI 발표와 연준의 매파적 금리인상 발언 이후 기술주 옵션이 이미 풋으로 심하게 기울어진 장세에서 대규모 포트폴리오를 지키기 위한 기관의 고확신 헷지입니다.",
         "A massive $50M above ask block at 140 strike with size exceeding open interest adds to the long dated NVDA put overhang. In a tape where tech options are already heavily put skewed after hot CPI and hawkish Fed remarks, this looks like high conviction protection on a large underlying book rather than a short term trade."),

        ("MU 1050 PUT 2027-1-15 @ $34.72M", "2026-11-10 10:56 AM", "Hedge (4/5 Strength)", False, "Split",
         "1,050달러 깊은 내가격(Deep ITM) 풋옵션 스플릿으로 단일 레그에 3,472만 달러가 지출되었으며 동일 만기/행사가에 2,770만 달러 트랜치가 추가되었습니다. 메모리 및 AI 투자 붐의 지속성에 의문을 품은 기관의 대규모 현물 위험 분산 헷지입니다.",
         "This deep in the money January MU put spends $34.7M on a single leg, layered alongside a second $27.7M tranche at the same strike and expiry. Suggests institutional hedging or de-risk of a substantial equity exposure as investors question the durability of the memory and AI spending boom."),

        ("ASML 1740 CALL 2027-2-19 @ $12.78M", "2026-11-10 12:06 PM", "Positioning (4/5 Strength)", True, "Above Ask · Top Position · Block",
         "미결제약정의 60배에 달하는 단일 1,278만 달러 콜 블록 체결. 독점적 반도체 노광장비 선도 기업에 대한 강력한 장기 상방 매집 포지션입니다.",
         "An above ask top position ASML call block roughly sixty times open interest targets moderate upside about three months out in a stock that is still outperforming the broader tech tape. That kind of size looks like a deliberate grab for upside convexity."),

        ("MSFT 580 CALL 2026-12-18 @ $12.92M", "2026-11-10 1:05 PM", "Positioning (4/5 Strength)", True, "Block",
         "만기까지 약 5주 남은 약외가격 580달러 행사가 콜 블록에 1,292만 달러가 유입되었습니다. CPI와 연준 쇼크가 흡수된 후 대형 소프트웨어의 스윙 롱 반등을 겨냥한 자금입니다.",
         "This $12.9M December MSFT call block sits just out of the money with around five weeks to expiry, aligning with call dominant weekly flow despite today's price weakness. Reads as a swing long bet on mega cap software stabilizing."),

        ("VLO 380 CALL 2027-1-15 @ $5.31M", "2026-11-10 2:13 PM", "Positioning (4/5 Strength)", True, "Above Ask · Top Position · Split",
         "정유 기업 발레로 에너지에 380달러 행사가로 531만 달러 규모의 콜 스플릿 매수가 집중 유입되었습니다. 정제마진 호조 및 지정학적 원유 인플레이션 노출을 겨냥한 기관 자금입니다.",
         "An above ask top position VLO call split adds over $5.3M of premium at only about ten percent out of the money into early next year, pointing to institutions adding refinery upside and inflation exposure into the recent energy drawdown."),

        ("AMD 510 CALL 2026-11-11 @ $2.48M", "2026-11-10 12:40 PM", "Short-Term (4/5 Strength)", True, "Golden Sweep",
         "만기가 단 1일 남은 초단기 골든 스윕으로 510달러 콜옵션에 248만 달러가 전격 매수되었습니다. 미결제약정의 2.9배 규모로 주중 즉각적인 모멘텀 랠리에 베팅하는 촉매 플레이입니다.",
         "This golden sweep spends about $2.5M on near dated AMD calls just above the money after a strong multi week rally. The 2.9x size over open interest and one day tenor flag a high conviction momentum or catalyst play.")
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
    st.caption("출처: InsiderFinance Evening Edge Options Top Tickers (2026-11-10)")
    
    col_c1, col_c2 = st.columns(2)
    
    with col_c1:
        st.subheader("🔵 Unusual OTM % (외가격 이상 급등 종목)")
        otm_data = {
            "Ticker": ["SOXL", "SMMT", "ONDS", "IREN", "HIMS", "SMH", "SQQQ", "APLD", "CRWG", "GME", "BRBR", "AAOI"],
            "OTM_Pct": [80, 71, 44, 38, 32, 30, 28, 28, 28, 27, 27, 24]
        }
        df_otm = pd.DataFrame(otm_data)
        fig_otm = px.bar(
            df_otm, x="Ticker", y="OTM_Pct", text="OTM_Pct",
            color_discrete_sequence=["#2979ff"]
        )
        fig_otm.update_traces(texttemplate='%{text}%', textposition='outside')
        fig_otm.update_layout(
            plot_bgcolor="#0e1117", paper_bgcolor="#0e1117",
            font_color="#d1d4dc", yaxis=dict(title="OTM %", range=[0, 95], gridcolor="#1e222d"),
            xaxis=dict(title="", gridcolor="#1e222d"), margin=dict(l=20, r=20, t=30, b=20)
        )
        st.plotly_chart(fig_otm, use_container_width=True)
        
        st.markdown("""
        <div class='chart-analysis'>
            <h4 style='color:#2979ff; margin:0 0 8px 0;'>💡 Unusual OTM % 데이터 해석</h4>
            <ul style='font-size:13px; color:#cfd8dc; margin-bottom:0; padding-left:18px; line-height:1.6;'>
                <li><strong>SOXL (80%) & SMH (30%):</strong> 반도체 3배 레버리지 ETF와 섹터 ETF에 현재가 대비 무려 80% 이상 떨어진 극단적 OTM 옵션 유입. 반도체 급반등에 대한 로또성 복권형 콜옵션 또는 극단적 꼬리위험(Tail Risk) 헷지가 공존함을 시사합니다.</li>
                <li><strong>SMMT (71%):</strong> 바이오텍 종목으로 71% 외가격 행사가에 콜 스윕이 집중되며 임상 데이터 발표나 라이선스 계약 등 돌발 촉매를 겨냥한 투기성 자금이 포착되었습니다.</li>
                <li><strong>ONDS (44%), IREN (38%), HIMS (32%):</strong> 고변동성 기술주 및 비트코인 채굴주에 단기 가격 급등을 노린 초외가격 옵션 공격적 매집이 지속되고 있습니다.</li>
            </ul>
        </div>
        """, unsafe_allow_html=True)
        
    with col_c2:
        st.subheader("🟣 Sweep Volume (기관 초강력 스윕 계약수)")
        sweep_data = {
            "Ticker": ["SPY", "QQQ", "NVDA", "IWM", "SPCX", "AMZN", "IREN", "TLT", "TSLA", "SOXL", "AAPL", "KWEB"],
            "Contracts_K": [2350, 1220, 500, 120, 50, 49, 35, 30, 27, 26, 25, 24]
        }
        df_swp = pd.DataFrame(sweep_data)
        fig_swp = px.bar(
            df_swp, x="Ticker", y="Contracts_K", text="Contracts_K",
            color_discrete_sequence=["#ab47bc"]
        )
        fig_swp.update_traces(texttemplate='%{text:,.0f}K', textposition='outside')
        fig_swp.update_layout(
            plot_bgcolor="#0e1117", paper_bgcolor="#0e1117",
            font_color="#d1d4dc", yaxis=dict(title="Sweep Contracts (천 건)", range=[0, 2600], gridcolor="#1e222d"),
            xaxis=dict(title="", gridcolor="#1e222d"), margin=dict(l=20, r=20, t=30, b=20)
        )
        st.plotly_chart(fig_swp, use_container_width=True)
        
        st.markdown("""
        <div class='chart-analysis' style='border-left-color: #ab47bc;'>
            <h4 style='color:#ab47bc; margin:0 0 8px 0;'>💡 Sweep Volume 데이터 해석</h4>
            <ul style='font-size:13px; color:#cfd8dc; margin-bottom:0; padding-left:18px; line-height:1.6;'>
                <li><strong>SPY (2.35M) & QQQ (1.22M):</strong> 지수 ETF에 수백만 계약 규모의 전광석화 같은 스윕 체결 집중. 매파적 연준 발언과 CPI 쇼크 이후 기관들이 시장 방향성에 즉각적으로 대응하기 위해 가장 유동성이 큰 지수 옵션을 대량 매수하고 있습니다.</li>
                <li><strong>NVDA (500K 계약):</strong> 개별 주식 중 유일하게 50만 건 이상의 압도적 스윕 볼륨 기록. 오늘 5천만 달러짜리 원월물 풋 블록과 맞물려 기관의 대규모 포트폴리오 헷지와 주가 변동성 베팅이 극에 달해 있습니다.</li>
                <li><strong>IWM (120K) & TLT (30K):</strong> 중소형주 지수(IWM)의 풋옵션 스윕과 금리 인하 기대 후퇴에 따른 채권(TLT) 방향성 베팅이 활발하게 전개 중입니다.</li>
            </ul>
        </div>
        """, unsafe_allow_html=True)

# ================= TAB 6: TREEMAP & THEMES =================
with tab6:
    st.title("🗺️ 섹터별 기관 수급 히트맵 & 핵심 테마 분석")
    st.caption("출처: InsiderFinance AI Market Insights BETA (2026-11-10)")

    tree_data = [
        {"Sector": "Technology", "Ticker": "NVDA", "Premium_M": 1115.6, "Call_Pct": 32, "Flow": "Put 68% (대규모 헷지)"},
        {"Sector": "Technology", "Ticker": "INTC", "Premium_M": 568.6, "Call_Pct": 20, "Flow": "Put 80% (하방 지속)"},
        {"Sector": "Technology", "Ticker": "MU", "Premium_M": 475.9, "Call_Pct": 49, "Flow": "Put 51% (수익 실현 헷지)"},
        {"Sector": "Technology", "Ticker": "AAPL", "Premium_M": 116.6, "Call_Pct": 50, "Flow": "Put 50% (중립)"},
        {"Sector": "Technology", "Ticker": "AMZN", "Premium_M": 81.4, "Call_Pct": 84, "Flow": "Call 84% (소프트웨어 강세)"},
        {"Sector": "Technology", "Ticker": "PLTR", "Premium_M": 80.2, "Call_Pct": 26, "Flow": "Put 74% (차익 매도)"},
        {"Sector": "Technology", "Ticker": "CRWV", "Premium_M": 76.7, "Call_Pct": 24, "Flow": "Put 76% (차입비용 부담)"},
        {"Sector": "Technology", "Ticker": "ASML", "Premium_M": 32.8, "Call_Pct": 85, "Flow": "Call 85% (독점 장비 롱)"},
        {"Sector": "Technology", "Ticker": "MSFT", "Premium_M": 28.5, "Call_Pct": 88, "Flow": "Call 88% (스윙 롱 매집)"},
        {"Sector": "Consumer Cyclical", "Ticker": "TSLA", "Premium_M": 294.9, "Call_Pct": 42, "Flow": "Put 58% (하방 우세)"},
        {"Sector": "Energy & Uranium", "Ticker": "CCJ", "Premium_M": 35.2, "Call_Pct": 92, "Flow": "Call 92% (우라늄 슈퍼사이클)"},
        {"Sector": "Energy & Uranium", "Ticker": "VLO", "Premium_M": 18.5, "Call_Pct": 86, "Flow": "Call 86% (정제마진 호조)"},
        {"Sector": "Crypto / High-Beta", "Ticker": "IREN", "Premium_M": 51.6, "Call_Pct": 41, "Flow": "Put 59% (단기 변동성)"},
        {"Sector": "Crypto / High-Beta", "Ticker": "RIOT", "Premium_M": 22.4, "Call_Pct": 100, "Flow": "Call 100% (비트코인 랠리)"},
        {"Sector": "Utilities & Defensives", "Ticker": "PCG", "Premium_M": 10.1, "Call_Pct": 100, "Flow": "Call 100% (경기방어 매수)"},
        {"Sector": "Small Caps", "Ticker": "SNDK", "Premium_M": 2.2, "Call_Pct": 100, "Flow": "Call 100% (반등 콜 스윕)"},
        {"Sector": "Small Caps", "Ticker": "HIMS", "Premium_M": 15.8, "Call_Pct": 12, "Flow": "Put 88% (마진 악화 급락)"}
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
        ("AI 하드웨어 및 반도체: 인플레이션 이후 대규모 하방 헷지 집중",
         "Bearish (5/5 Strength) · Established (최초 포착: 2026-10-05)", False,
         "기술주 옵션 플로우는 일간 및 주간 모두 약 70%가 풋옵션에 쏠려 있습니다. 특히 NVDA 단일 종목에서만 주간 11억 달러 이상의 프리미엄이 하방으로 기울어져 있으며, 오늘 5천만 달러 규모의 Above-Ask 원월물 풋 블록이 추가 체결되었습니다. 이는 기술주 현물 매도세, 예상치를 웃돈 CPI, 연준의 매파적 메시지와 맞물려 헷지 수요가 유지되는 한 AI 하드웨어 밸류에이션에 지속적인 하방 압력을 가하고 있습니다.",
         "Technology options flow is roughly seventy percent puts on both the day and week, with NVDA alone seeing over $1.1B in weekly premium skewed to downside and a new $50M above ask long dated put block today. That aligns with strong equity side distribution in technology and a hotter than expected CPI plus hawkish Fed messaging, keeping valuations for AI hardware under persistent pressure."),

        ("중소형주: 거시 경제 하방 리스크에 대한 핵심 헷지 수단으로 활용",
         "Bearish (5/5 Strength) · Established (최초 포착: 2026-11-04)", False,
         "러셀 2000(IWM) 옵션 플로우는 일간 및 주간 모두 90% 이상이 풋옵션이며, 중소형주가 대형 지수 대비 부진함에 따라 풋 프리미엄이 콜을 압도하고 있습니다. 이러한 집중적인 인덱스 헷지는 뜨거운 CPI와 월러 이사의 추가 긴축 지지 발언에 정확히 부합하며, 중소형주가 고금리 장기화(Higher-for-Longer) 리스크의 가장 확실한 헷지 수단이 되고 있습니다.",
         "IWM options are over ninety percent puts on both daily and weekly flow, with put premium overwhelming calls as small caps lag broad indices. This concentrated index protection fits the hot CPI and Waller's support for more tightening, making small caps the clean hedge for higher for longer risk."),

        ("경기방어 소비재 및 유틸리티: 금리 공포 속 지속적인 아웃퍼폼",
         "Bullish (4/5 Strength) · Established (최초 포착: 2026-11-10)", True,
         "필수소비재와 유틸리티 섹터는 5일간 약 3% 상승한 몇 안 되는 섹터 중 하나이며, 주간 옵션 프리미엄도 풋옵션이 극히 제한된 채 콜옵션이 지배하고 있습니다. 금일 발생한 단기 필수재 헷지 급증은 추세 반전이라기보다는 차익 실현 보호 성격이 강하며, 금리 불확실성 국면에서 경기방어주를 선호하는 시장 체제와 일치합니다.",
         "Consumer defensive and utilities are among the few sectors up roughly three percent over five days while weekly options premium is call dominated with limited puts. Today's spike in short term staple hedges looks more like profit protection than trend change, consistent with a regime that favors defensives under higher rate uncertainty."),

        ("에너지 및 우라늄: 최근 섹터 조정에도 불구하고 끈질긴 상방 포지셔닝 유지",
         "Bullish (4/5 Strength) · Established (최초 포착: 2026-11-06)", True,
         "에너지 옵션은 5일 동안 섹터가 약 6% 하락했음에도 불구하고 일간 및 주간 모두 콜 프리미엄이 풋을 압도하고 있습니다. CCJ, VLO, RIG에 대한 지속적인 상방 콜 블록(오늘 VLO의 신규 Above-Ask 최상위 콜 포함)은 기관 펀드들이 최근의 약세를 활용해 인플레이션 및 지정학적 상방 볼록성(Convexity)을 포트폴리오에 추가하고 있음을 보여줍니다.",
         "Energy options show call premium heavily outweighing puts on both daily and weekly flow even as the sector is down about six percent over five days. Persistent upside call blocks in CCJ, VLO and RIG suggest funds are using weakness to add inflation and geopolitical convexity.")
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
    st.title("📰 Evening Edge 트레이딩 뉴스 전문 (19선 전체)")
    st.caption("출처: InsiderFinance Trending News (2026-11-10 발행)")

    news_list = [
        ("🧲 USA Rare Earth (USAR)", "최초 상업용 NdFeB 자석 판매 및 Serra Verde MREC 선적을 기록하며 300만 달러 매출과 1억 2,600만 달러의 조정 순손실을 발표했습니다.", "Had recorded first commercial NdFeB magnet sales and Serra Verde MREC shipments and reported $3 million revenue and a $126 million adjusted net loss."),
        ("💾 Micron (MU)", "회계연도 4분기 매출 542억 달러와 약 1,500억 달러 규모의 잔여 이행 의무(RPO)를 발표하여, AI 메모리 수요가 유지될 경우 가치 상승 가설을 뒷받침했습니다.", "Had reported fiscal fourth-quarter revenue of $54.2 billion and approximately $150 billion in remaining performance obligations, underpinning a value-upside thesis if AI memory demand holds."),
        ("⚙️ D-Wave (QBTS)", "3분기 매출 450만 달러를 기록했으나 판관비 등 운영 비용이 5,590만 달러로 증가하면서 GAAP 순손실이 확대되었습니다. 4분기 2,000만 달러 규모 FAU 시스템 판매 매출 인식 여부에 관심이 쏠립니다.", "Had $4.5 million Q3 revenue but a wider GAAP loss as operating expenses rose to $55.9 million, leaving Q4 recognition of a $20 million FAU system sale in focus."),
        ("💸 CoreWeave (CRWV)", "3분기 매출 가이던스를 34억 5천만~36억 달러, 이자 비용을 8억 6천만~9억 4천만 달러, 자본지출(Capex)을 115억~135억 달러로 제시하여, 백로그 전환 속도가 높은 차입 비용을 상쇄할 수 있을지 시험대에 올랐습니다.", "Had guided Q3 revenue of $3.45B–$3.60B with interest expense of $860M–$940M and capex of $11.5B–$13.5B, testing whether backlog converts fast enough to offset higher borrowing costs."),
        ("✈️ Archer Aviation (ACHR)", "3분기 매출 510만 달러, 조정 EBITDA 손실 1억 7,850만 달러를 기록했습니다. 2억 700만 달러 현금 소진 후 보유 현금은 13억 5,360만 달러이며, Midnight 기체가 FAA 시장 조사 특별 감항 인증을 획득했다고 밝혔습니다.", "Had reported Q3 revenue of $5.1 million, an adjusted EBITDA loss of $178.5 million, cash of $1.3536 billion after a $207 million decline, and said Midnight received an FAA Market Survey Special Airworthiness Certificate."),
        ("🏛️ Fed (연방준비제도)", "12월 추가 금리 인상을 지지하면서 더 큰 폭의 인상 가능성도 배제하지 않아 긴축 확률을 끌어올렸습니다.", "Had signaled support for a December rate hike while leaving a larger move on the table, raising tightening odds."),
        ("📈 Digital Turbine (APPS)", "2분기 매출 1억 7,870만 달러(전년비 27% 증가)를 기록하고, 2027 회계연도 연간 매출 가이던스를 6억 7천만~6억 9천만 달러로 상향 조정하면서 조정 EBITDA 가이던스(1억 4,500만~1억 5,500만 달러)를 재확인했습니다.", "Had Q2 revenue of $178.7 million, up 27%, and raised fiscal-2027 revenue guidance to $670 million-$690 million while reaffirming adjusted EBITDA guidance."),
        ("📊 U.S. Macro October CPI (미국 10월 소비자물가지수)", "전월 대비 0.4% 상승하여 시장 전망치를 상회하였으며, 연방준비제도의 추가 금리 인상 기대감을 강화시켰습니다.", "October CPI had risen 0.4% m/m, above forecasts and reinforcing expectations for further Federal Reserve rate increases."),
        ("💊 Hims & Hers (HIMS)", "3분기 매출 8억 9,040만 달러를 발표했으나 3,300만 달러의 GAAP 순손실을 기록했고, 2026년 연간 조정 EBITDA 가이던스를 2억 5,700만~2억 7,700만 달러로 하향 조정했습니다.", "Had posted Q3 revenue of $890.4 million, recorded a $33.0 million GAAP loss and cut 2026 adjusted EBITDA guidance to $257 million-$277 million."),
        ("📝 Trump Media (DJT)", "11월 9일 Form 10-Q 및 8-K 보고서를 제출했으나, 공개된 SEC 발췌본에는 투자자들이 매출, 순이익 및 디지털 자산 평가이익을 검증하는 데 필요한 재무제표가 누락되어 있었습니다.", "Had filed Form 10-Q and Form 8-K on Nov. 9, 2026, but accessible SEC excerpts omit financial tables investors need to verify revenue, net income and digital-asset gains."),
        ("⚖️ Nvidia (NVDA)", "젠슨 황 CEO가 혼외 관계를 인정한 후 이사회 차원의 독립적인 조사가 시작되었습니다. 공시 미비 및 국가 안보 위험 노출을 이유로 연방 증권 집단소송이 제기되었습니다.", "Had an independent board probe opened after CEO Jensen Huang acknowledged an extramarital relationship; a proposed federal securities class action was filed alleging nondisclosure."),
        ("⚠️ GLP-1 비만 치료제 제약사", "FDA 합동 검토 결과 임상시험에서 GLP-1 투여군 10건 대 대조군 5건의 NAION(허혈성 시신경병증) 추정 사례가 발견됨에 따라, 미국 제품 라벨에 경고 문구를 추가하도록 의무화되었습니다.", "Had been required to add NAION warnings to U.S. labels following an FDA pooled review that found 10 probable trial cases with GLP-1s versus five in controls."),
        ("🎬 Skydance (SKYD)", "워너 브라더스 디스커버리 인수 종결에 앞서 3분기 실적을 발표하며 스트리밍 사업 계획과 60억 달러 규모의 비용 절감 목표를 공개했습니다.", "Had reported third-quarter results that preceded the Warner Bros. Discovery close, flagged streaming plans and a reported $6 billion cost-savings target."),
        ("📈 Plug Power (PLUG)", "매출 2억 100만 달러, 역대 최저 수준의 순현금 사용액(2,800만 달러)을 발표하고, 2026년 연간 매출 성장 및 4분기 EBITDAS 흑자 전환 목표를 재확인했습니다.", "Had reported $201 million of revenue, record-low net cash usage of $28 million and reaffirmed 2026 revenue growth and a Q4 positive EBITDAS target."),
        ("📉 Crude Oil (원유)", "트럼프 대통령이 미국의 이란 추가 공습 가능성이 낮다고 언급함에 따라 지정학적 프리미엄이 완화되며 하락했습니다. 브렌트유는 92.57달러, WTI는 86.85달러에 마감했습니다.", "Had fallen after President Trump said renewed U.S. strikes on Iran were unlikely, easing geopolitical premium; Brent settled at $92.57 and WTI at $86.85."),
        ("💸 Anthropic (ANT)", "11월 말 IPO를 목표로 하고 있으나, 시장에 돌았던 693억 달러 공모액 수치가 사실이 아닌 것으로 밝혀지며 실제 투자자들의 수요에 대한 불확실성이 남았습니다.", "Had targeted a late-November IPO; a circulated $69.3 billion proceeds figure was later described as inaccurate, leaving investor appetite uncertain."),
        ("🎬 Skydance - DC Studios", "1,100억 달러 규모의 인수 이후 DC 창작 부문을 통합하기 위해 제러미 래첨(Jeremy Latcham)을 2026년 12월 1일부로 DC 스튜디오 대표 겸 CCO로 임명했습니다.", "Named Jeremy Latcham president and chief creative officer of DC Studios effective Dec. 1, 2026, consolidating DC creative oversight after its $110.0 billion acquisition."),
        ("🛰️ AST SpaceMobile", "일본 저궤도 다이렉트-투-디바이스(D2D) 통신망 구축을 위해 라쿠텐과 합작법인 '라쿠텐 AST'를 설립한다고 발표했습니다. 일본 정부로부터 약 10억 달러 규모의 지원을 받는 것으로 알려졌으나 3분기 매출은 4,230만 달러로 시장 전망치를 하회했습니다.", "Announced a joint venture with Rakuten to form Rakuten AST for Japan LEO network; project reported government support near $1B while Q3 revenue of $42.3M missed consensus."),
        ("💸 Lucid Group (LCID)", "3분기 실적이 시장 전망치를 하회했으나, 사우디 국부펀드(PIF)와의 분할 인출 조건부 대출 한도를 17억 5천만 달러 증액하기로 발표하여 가용 유동성을 37억 5천만 달러로 확대하고 자금 조달 기간을 2027년 4분기까지 연장했습니다.", "Missed Q3 estimates and announced a $1.75B increase to PIF loan, lifting pro forma liquidity to $3.75B and extending funding into Q4 2027.")
    ]

    for title, ko, en in news_list:
        st.markdown(f"""
        <div class='news-box'>
            <div style='font-size:14px; font-weight:700; color:#ffffff; margin-bottom:4px;'>{title}</div>
            <div style='font-size:13px; color:#e0e0e0; line-height:1.6;'>{ko}</div>
            <div style='font-size:11px; color:#787b86; margin-top:4px;'>[EN] {en}</div>
        </div>
        """, unsafe_allow_html=True)
