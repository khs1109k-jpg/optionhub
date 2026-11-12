import csv
import io
import json
import math
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime

import pandas as pd
import yfinance as yf

OI_PATH = os.path.expanduser("~/.optionhub_oi_history.json")
WL_PATH = os.path.expanduser("~/.optionhub_watchlist.json")
CFG_PATH = os.path.expanduser("~/.telegram_config.json")
APP_PATH = os.path.expanduser("~/app.py")
SHEET_ID = "1_FWy_B9a6t1txau06PbeEMy9S9B1GsMgWZLGfMmMG7w"


def calc_zero_gamma(oi_rows, spot=0.0):
    df = pd.DataFrame(oi_rows)
    if df.empty or "행사가" not in df.columns or "GEX($M)" not in df.columns:
        return None
    d = df.groupby("행사가", as_index=False)["GEX($M)"].sum().sort_values("행사가").reset_index(drop=True)
    flips = []
    for i in range(len(d) - 1):
        g1, g2 = float(d.loc[i, "GEX($M)"]), float(d.loc[i + 1, "GEX($M)"])
        k1, k2 = float(d.loc[i, "행사가"]), float(d.loc[i + 1, "행사가"])
        if (g1 < 0 and g2 > 0) or (g1 > 0 and g2 < 0):
            flips.append(round(k1 + (0.0 - g1) * (k2 - k1) / (g2 - g1), 2))
    if not flips:
        return None
    return min(flips, key=lambda x: abs(x - spot)) if spot > 0 else flips[len(flips) // 2]

def bs_greeks(S, K, T, r, sigma, is_call=True):
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


def collect_active_tickers():
    tickers = set(["NVDA", "TSLA", "SNDK", "MU", "META", "INTC", "AMD", "AMZN", "AAPL", "SPY", "IBIT", "KGC", "BW", "ACHR", "RIOT", "AMAT", "LITE"])
    # 1. Watchlist
    if os.path.exists(WL_PATH):
        try:
            tickers.update(json.load(open(WL_PATH, encoding="utf-8")))
        except Exception:
            pass
    # 2. Live Google Sheet '전체' tab (recent 80 rows)
    try:
        url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&sheet=" + urllib.parse.quote("전체")
        data = urllib.request.urlopen(url, timeout=15).read().decode("utf-8")
        rows = list(csv.DictReader(io.StringIO(data)))
        for r in rows[-80:]:
            tk = str(r.get("Ticker (티커)", "")).strip().upper()
            if tk and tk != "NAN" and tk not in ("SPX", "ES"):
                tickers.add(tk)
    except Exception:
        pass
    # 3. app.py DEFAULT_FLOWS
    if os.path.exists(APP_PATH):
        try:
            src = open(APP_PATH, encoding="utf-8").read()
            ns = {}
            part = src.split("DEFAULT_FLOWS = [")[1].split("]\n")[0]
            exec(f"DEFAULT_FLOWS = [{part}]", ns)
            for r in ns.get("DEFAULT_FLOWS", []):
                tk = str(r[1]).strip().upper()
                if tk and tk not in ("SPX", "ES"):
                    tickers.add(tk)
        except Exception:
            pass
    return sorted(tickers)


def fetch_oi_gex(ticker):
    t = yf.Ticker(ticker)
    exps = t.options
    if not exps:
        return None
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
        for is_c, df_side in [(True, chain.calls), (False, chain.puts)]:
            for _, r in df_side.iterrows():
                oi = 0 if pd.isna(r.get("openInterest")) else int(r.get("openInterest"))
                vol = 0 if pd.isna(r.get("volume")) else int(r.get("volume"))
                if oi > 0 or vol > 0:
                    K = float(r["strike"])
                    iv_raw = r.get("impliedVolatility")
                    iv = 0.30 if pd.isna(iv_raw) or float(iv_raw) <= 0.01 else float(iv_raw)
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
    if not rows:
        return None
    return rows, round(spot, 2)


def main():
    tickers = collect_active_tickers()
    history = {}
    if os.path.exists(OI_PATH):
        try:
            history = json.load(open(OI_PATH, encoding="utf-8"))
        except Exception:
            history = {}

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    summary_lines = []
    flip_alerts = []
    pc_spikes = []
    ok_cnt = 0

    for tk in tickers:
        try:
            res = fetch_oi_gex(tk)
            if not res:
                continue
            oi_rows, spot_px = res
            tot_c = sum(x["OI"] for x in oi_rows if x["구분"] == "Call")
            tot_p = sum(x["OI"] for x in oi_rows if x["구분"] == "Put")
            net_gex = round(sum(x["GEX($M)"] for x in oi_rows), 2)
            net_dex = round(sum(x["DEX($M)"] for x in oi_rows), 2)

            if tk not in history:
                history[tk] = []
            prev_snap = history[tk][-1] if history[tk] else None
            zg = calc_zero_gamma(oi_rows, spot_px)
            pc_ratio = round(tot_p / tot_c, 2) if tot_c > 0 else 0
            if prev_snap:
                prev_gex = float(prev_snap.get("Net_GEX_M", 0))
                if (prev_gex >= 0 and net_gex < 0):
                    flip_alerts.append(f"🔻 {tk} (${spot_px}): 양(+)→음(-) 감마 플립! ({prev_gex:+.2f}M → {net_gex:+.2f}M)")
                elif (prev_gex < 0 and net_gex >= 0):
                    flip_alerts.append(f"🔺 {tk} (${spot_px}): 음(-)→양(+) 감마 플립! ({prev_gex:+.2f}M → {net_gex:+.2f}M)")
                prev_pc = float(prev_snap.get("Put_Call_OI_Ratio", 0))
                if prev_pc > 0 and pc_ratio > 0:
                    pc_spikes.append((pc_ratio - prev_pc, tk, prev_pc, pc_ratio, spot_px))
            history[tk].append({
                "수집시각": now_str,
                "Spot": spot_px,
                "Call_OI": tot_c,
                "Put_OI": tot_p,
                "Put_Call_OI_Ratio": round(tot_p / tot_c, 2) if tot_c > 0 else 0,
                "Net_GEX_M": net_gex,
                "Net_DEX_M": net_dex,
                "상세": oi_rows,
            })
            # 최근 14일치만 유지해 파일 크기 최적화
            history[tk] = history[tk][-14:]
            ok_cnt += 1
            if tot_c + tot_p >= 5000:
                summary_lines.append(f"• {tk} (${spot_px}): Call {tot_c:,} / Put {tot_p:,} | Net GEX {net_gex:+.2f}M")
            time.sleep(0.5)
        except Exception:
            continue

    with open(OI_PATH, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False)
    print(f"Collected {ok_cnt}/{len(tickers)} tickers.")

    if os.path.exists(CFG_PATH) and ok_cnt > 0:
        try:
            cfg = json.load(open(CFG_PATH, encoding="utf-8"))
            header = [f"📊 [OptionHub 자동 OI·GEX 수집 완료] ({now_str})", ""]
            if flip_alerts:
                header.append("🚨 [감마 플립(부호 반전) 경보]")
                header.extend(flip_alerts[:8])
                header.append("")
            pc_top = sorted([x for x in pc_spikes if abs(x[0]) >= 0.1], reverse=True)[:5]
            if pc_top:
                header.append("⚡ [전일 대비 P/C 비율 급변 TOP 5]")
                for d_pc, tk_p, p0, p1, sp_p in pc_top:
                    header.append(f"• {tk_p} (${sp_p}): P/C {p0:.2f} → {p1:.2f} ({d_pc:+.2f})")
                header.append("")
            msg = "\n".join(header + summary_lines[:20]) + f"\n\n✅ 총 {ok_cnt}개 종목 저장 완료!\n🌐 http://132.226.3.145:8501"
            for i in range(0, len(msg), 3800):
                p = json.dumps({"chat_id": cfg["chat_id"], "text": msg[i:i+3800], "disable_web_page_preview": True}).encode("utf-8")
                req = urllib.request.Request(f"https://api.telegram.org/bot{cfg['token']}/sendMessage", data=p, headers={"Content-Type": "application/json"})
                urllib.request.urlopen(req, timeout=15)
        except Exception as e:
            print("TG err:", e)


if __name__ == "__main__":
    main()