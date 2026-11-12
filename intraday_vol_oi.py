import json
import math
import os
import urllib.request
from datetime import datetime
import pandas as pd

CFG_PATH = os.path.expanduser("~/.telegram_config.json")
WL_PATH = os.path.expanduser("~/.optionhub_watchlist.json")
STATE_PATH = os.path.expanduser("~/.optionhub_vol_alerted.json")
LIVE_PATH = os.path.expanduser("~/.optionhub_intraday_live.json")
LEVEL_PATH = os.path.expanduser("~/.optionhub_level_state.json")

BASE_TICKERS = ["SOXL", "SOXS", "NVDA", "TSLA", "MU", "AMD", "SPY", "QQQ", "IWM", "META", "INTC", "SNDK"]
KEY_WALL_TICKERS = {"SPY", "QQQ", "IWM", "NVDA", "TSLA", "MU", "AMD", "SOXL", "SOXS"}


def load_tg():
    if os.path.exists(CFG_PATH):
        with open(CFG_PATH, "r", encoding="utf-8") as f:
            c = json.load(f)
            return c.get("token", ""), str(c.get("chat_id", ""))
    return "", ""


def send_tg(token, chat_id, text):
    if not token or not chat_id:
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    for i in range(0, len(text), 3800):
        payload = json.dumps({
            "chat_id": chat_id,
            "text": text[i:i + 3800],
            "disable_web_page_preview": True,
        }).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            if resp.status != 200:
                return False
    return True


def get_target_tickers():
    tks = list(BASE_TICKERS)
    if os.path.exists(WL_PATH):
        try:
            wl = json.load(open(WL_PATH, "r", encoding="utf-8"))
            if isinstance(wl, list):
                for x in wl:
                    x = str(x).strip().upper()
                    if x and x not in tks:
                        tks.append(x)
        except Exception:
            pass
    return tks[:25]


def fmt_usd(val):
    if val >= 1_000_000:
        return f"${val / 1_000_000:.2f}M"
    if val >= 1_000:
        return f"${val / 1_000:.0f}K"
    return f"${val:,.0f}"


def bs_gamma(S, K, T, r, sigma):
    if S <= 0 or K <= 0 or T <= 0 or sigma <= 0:
        return 0.0
    d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))
    pdf = math.exp(-0.5 * d1 * d1) / math.sqrt(2 * math.pi)
    return pdf / (S * sigma * math.sqrt(T))


def calc_zero_gamma(by_k, spot):
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


def infer_side_hint(r):
    try:
        lp = float(r.get("lastPrice") or 0)
        bid = float(r.get("bid") or 0)
        ask = float(r.get("ask") or 0)
        chg = float(r.get("percentChange") or 0)
        if ask > bid > 0 and lp > 0:
            mid = (bid + ask) / 2.0
            if lp >= ask * 0.98 or (lp > mid and chg > 0):
                return "📈 매수우위(BTO 추정)"
            if lp <= bid * 1.02 or (lp < mid and chg < 0):
                return "📉 매도우위(STO 추정)"
        if chg >= 15:
            return "📈 매수우위(BTO 추정)"
        if chg <= -15:
            return "📉 매도우위(STO 추정)"
    except Exception:
        pass
    return "⚖️ 방향혼합(BTO/STO)"


def scan_vol_gt_oi(tickers, check_levels=True):
    import yfinance as yf
    hits = []
    levels = {}
    now = datetime.now()

    for tk in tickers:
        try:
            t = yf.Ticker(tk)
            exps = t.options
            if not exps:
                continue
            spot = 0.0
            try:
                spot = round(float(t.fast_info.get("lastPrice", 0) or 0), 2)
            except Exception:
                pass

            gex_by_k = {}
            cw_best = (0.0, 0)
            pw_best = (0.0, 0)

            for exp in exps[:2]:
                d_exp = datetime.strptime(exp, "%Y-%m-%d")
                T = max((d_exp - now).days, 1) / 365.0
                ch = t.option_chain(exp)
                for cp, df_side in [("Call", ch.calls), ("Put", ch.puts)]:
                    sign = 1.0 if cp == "Call" else -1.0
                    for _, r in df_side.iterrows():
                        oi = 0 if pd.isna(r.get("openInterest")) else int(r.get("openInterest"))
                        vol = 0 if pd.isna(r.get("volume")) else int(r.get("volume"))
                        k = float(r["strike"])

                        if check_levels and tk in KEY_WALL_TICKERS and spot > 0 and oi > 0:
                            iv = 0.35 if pd.isna(r.get("impliedVolatility")) else float(r.get("impliedVolatility") or 0.35)
                            iv = max(0.05, min(iv, 3.0))
                            g = bs_gamma(spot, k, T, 0.045, iv)
                            gex_m = sign * g * oi * 100.0 * spot * spot * 0.01 / 1_000_000.0
                            gex_by_k[k] = gex_by_k.get(k, 0.0) + gex_m
                            if cp == "Call" and oi > cw_best[1]:
                                cw_best = (k, oi)
                            if cp == "Put" and oi > pw_best[1]:
                                pw_best = (k, oi)

                        if oi >= 10 and vol > oi and (vol - oi) >= 500:
                            lp = 0.0 if pd.isna(r.get("lastPrice")) else float(r.get("lastPrice") or 0)
                            prem = vol * lp * 100.0
                            hits.append({
                                "tk": tk,
                                "spot": spot,
                                "exp": exp,
                                "cp": cp,
                                "k": k,
                                "vol": vol,
                                "oi": oi,
                                "min_new": vol - oi,
                                "ratio": round(vol / oi, 2),
                                "price": round(lp, 2),
                                "prem_usd": round(prem, 0),
                                "prem_str": fmt_usd(prem),
                                "hint": infer_side_hint(r),
                            })

            if check_levels and tk in KEY_WALL_TICKERS and spot > 0 and gex_by_k:
                zg = calc_zero_gamma(gex_by_k, spot)
                levels[tk] = {
                    "spot": spot,
                    "zg": zg,
                    "cw": cw_best[0] if cw_best[1] > 0 else None,
                    "pw": pw_best[0] if pw_best[1] > 0 else None,
                }
        except Exception:
            continue

    hits.sort(key=lambda x: (x["prem_usd"], x["min_new"]), reverse=True)
    return hits, levels


def detect_level_crosses(levels):
    prev_state = {}
    if os.path.exists(LEVEL_PATH):
        try:
            prev_state = json.load(open(LEVEL_PATH, "r", encoding="utf-8"))
        except Exception:
            prev_state = {}

    alerts = []
    new_state = {}
    for tk, lv in levels.items():
        sp = lv["spot"]
        zg = lv["zg"]
        cw = lv["cw"]
        pw = lv["pw"]

        zg_pos = ("ABOVE" if sp >= zg else "BELOW") if zg else None
        cw_pos = ("ABOVE" if sp >= cw else "BELOW") if cw else None
        pw_pos = ("ABOVE" if sp >= pw else "BELOW") if pw else None

        old = prev_state.get(tk, {})
        if old:
            if zg_pos and old.get("zg_pos") and zg_pos != old["zg_pos"]:
                dir_txt = "상향 돌파 (+GEX 전환/안정)" if zg_pos == "ABOVE" else "하향 이탈 (-GEX 전환/변동성 경계)"
                alerts.append(f"• {tk} (${sp}) Zero Gamma ${zg:g} {dir_txt}")
            if cw_pos and old.get("cw_pos") and cw_pos != old["cw_pos"] and cw_pos == "ABOVE":
                alerts.append(f"• {tk} (${sp}) Call Wall ${cw:g} 상향 돌파 (감마 스퀴즈 주의)")
            if pw_pos and old.get("pw_pos") and pw_pos != old["pw_pos"] and pw_pos == "BELOW":
                alerts.append(f"• {tk} (${sp}) Put Wall ${pw:g} 하향 이탈 (하방 가속 주의)")

        new_state[tk] = {"zg_pos": zg_pos, "cw_pos": cw_pos, "pw_pos": pw_pos, "spot": sp}

    try:
        with open(LEVEL_PATH, "w", encoding="utf-8") as f:
            json.dump(new_state, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    return alerts


def main():
    token, chat_id = load_tg()
    if not token or not chat_id:
        print("Missing telegram config")
        return

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    today_str = datetime.now().strftime("%Y-%m-%d")

    hits, levels = scan_vol_gt_oi(get_target_tickers(), check_levels=True)

    # Save live cache for OptionHub Web & /vol bot command
    try:
        with open(LIVE_PATH, "w", encoding="utf-8") as f:
            json.dump({"updated": now_str, "items": hits[:30]}, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

    # 1. Level cross alerts
    lv_alerts = detect_level_crosses(levels)
    if lv_alerts:
        lv_msg = (
            f"⚡ [실시간 감마 레벨 돌파 경보] ({datetime.now().strftime('%H:%M')})\n\n"
            + "\n".join(lv_alerts)
            + "\n\n🌐 http://132.226.3.145:8501"
        )
        send_tg(token, chat_id, lv_msg)

    # 2. Vol > OI alerts (deduped daily)
    sent = {}
    if os.path.exists(STATE_PATH):
        try:
            sent = json.load(open(STATE_PATH, "r", encoding="utf-8"))
        except Exception:
            sent = {}
    if sent.get("date") != today_str:
        sent = {"date": today_str, "keys": []}
    sent_set = set(sent.get("keys", []))

    new_alerts = []
    for h in hits:
        key = f"{h['tk']}|{h['exp']}|{h['cp']}|{h['k']}|{h['vol'] // 1000}"
        if key not in sent_set:
            new_alerts.append((key, h))

    if not new_alerts:
        print("No new Vol > OI alerts.")
        return

    lines = [f"🚨 [장중 실시간 신규 오픈 확정 (Vol > OI)] ({datetime.now().strftime('%H:%M')})\n"]
    for key, h in new_alerts[:12]:
        lines.append(
            f"• {h['tk']} (${h['spot']}) {h['k']:g}{h['cp'][0]} ({h['exp']}) | {h['prem_str']}\n"
            f"  Vol {h['vol']:,} > OI {h['oi']:,} ({h['ratio']}x) → 최소 +{h['min_new']:,} | {h['hint']}"
        )
    lines.append("\n🌐 http://132.226.3.145:8501")

    if send_tg(token, chat_id, "\n".join(lines)):
        for key, _ in new_alerts[:12]:
            sent_set.add(key)
        sent["keys"] = list(sent_set)[-300:]
        with open(STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(sent, f, ensure_ascii=False, indent=2)
        print(f"Sent {len(new_alerts[:12])} Vol > OI alerts.")


if __name__ == "__main__":
    main()