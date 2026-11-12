import json
import os
import urllib.request
from datetime import datetime
import pandas as pd

CFG_PATH = os.path.expanduser("~/.telegram_config.json")
WL_PATH = os.path.expanduser("~/.optionhub_watchlist.json")
STATE_PATH = os.path.expanduser("~/.optionhub_vol_alerted.json")
BASE_TICKERS = ["SOXL", "SOXS", "NVDA", "TSLA", "MU", "AMD", "SPY", "QQQ", "IWM", "META", "INTC", "SNDK"]


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


def scan_vol_gt_oi(tickers):
    import yfinance as yf
    hits = []
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
            for exp in exps[:2]:
                ch = t.option_chain(exp)
                for cp, df_side in [("Call", ch.calls), ("Put", ch.puts)]:
                    for _, r in df_side.iterrows():
                        oi = 0 if pd.isna(r.get("openInterest")) else int(r.get("openInterest"))
                        vol = 0 if pd.isna(r.get("volume")) else int(r.get("volume"))
                        if oi >= 10 and vol > oi and (vol - oi) >= 500:
                            k = float(r["strike"])
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
                            })
        except Exception:
            continue
    hits.sort(key=lambda x: x["min_new"], reverse=True)
    return hits


def main():
    token, chat_id = load_tg()
    if not token or not chat_id:
        print("Missing telegram config")
        return

    today_str = datetime.now().strftime("%Y-%m-%d")
    sent = {}
    if os.path.exists(STATE_PATH):
        try:
            sent = json.load(open(STATE_PATH, "r", encoding="utf-8"))
        except Exception:
            sent = {}
    if sent.get("date") != today_str:
        sent = {"date": today_str, "keys": []}
    sent_set = set(sent.get("keys", []))

    hits = scan_vol_gt_oi(get_target_tickers())
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
            f"• {h['tk']} (${h['spot']}) {h['k']:g}{h['cp'][0]} ({h['exp']})\n"
            f"  거래량 {h['vol']:,} > 기존 OI {h['oi']:,} ({h['ratio']}x) → 최소 +{h['min_new']:,}계약 신규 오픈!"
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