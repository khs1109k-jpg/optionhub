import io
import json
import math
import os
import uuid
import urllib.request
from datetime import datetime
import pandas as pd

CFG_PATH = os.path.expanduser("~/.telegram_config.json")
OI_PATH = os.path.expanduser("~/.optionhub_oi_history.json")
DEFAULT_CHART_TICKERS = ["SPY", "QQQ", "IWM", "NVDA"]


def load_tg():
    if os.path.exists(CFG_PATH):
        with open(CFG_PATH, "r", encoding="utf-8") as f:
            c = json.load(f)
            return c.get("token", ""), c.get("chat_id", "")
    return "", ""


def send_tg_photo(token, chat_id, img_bytes, caption=""):
    if not token or not chat_id:
        return False
    boundary = uuid.uuid4().hex
    parts = []
    for name, val in [("chat_id", str(chat_id)), ("caption", caption)]:
        parts.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{val}\r\n".encode("utf-8")
        )
    parts.append(
        (
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"photo\"; filename=\"gex.png\"\r\n"
            f"Content-Type: image/png\r\n\r\n"
        ).encode("utf-8")
        + img_bytes
        + b"\r\n"
    )
    parts.append(f"--{boundary}--\r\n".encode("utf-8"))
    body = b"".join(parts)
    url = f"https://api.telegram.org/bot{token}/sendPhoto"
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.status == 200


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


def fetch_chain_for_chart(ticker):
    import yfinance as yf
    t = yf.Ticker(ticker)
    exps = t.options
    if not exps:
        return [], 0.0
    spot = 0.0
    try:
        spot = float(t.fast_info.get("lastPrice", 0) or 0)
    except Exception:
        pass
    if spot <= 0:
        hist = t.history(period="1d")
        if not hist.empty:
            spot = float(hist["Close"].iloc[-1])

    now_dt = datetime.now()
    rows = []
    for exp in exps[:4]:
        try:
            exp_dt = datetime.strptime(exp, "%Y-%m-%d")
            T = max((exp_dt - now_dt).days / 365.0, 1.0 / 365.0)
        except Exception:
            T = 7.0 / 365.0
        chain = t.option_chain(exp)
        for is_c, df_side in [(True, chain.calls), (False, chain.puts)]:
            for _, r in df_side.iterrows():
                oi = 0 if pd.isna(r.get("openInterest")) else int(r.get("openInterest"))
                if oi <= 0:
                    continue
                K = float(r["strike"])
                iv_raw = r.get("impliedVolatility")
                iv = 0.30 if pd.isna(iv_raw) or float(iv_raw) <= 0.01 else float(iv_raw)
                s_ref = spot if spot > 0 else K
                _, gamma = bs_greeks(s_ref, K, T, 0.045, iv, is_call=is_c)
                sign = 1.0 if is_c else -1.0
                gex_m = (sign * gamma * oi * 100.0 * (s_ref ** 2) * 0.01) / 1_000_000.0
                rows.append({
                    "K": K,
                    "Call_OI": oi if is_c else 0,
                    "Put_OI": oi if not is_c else 0,
                    "GEX": gex_m,
                })
    return rows, round(spot, 2)


def calc_zero_gamma(agg, spot=0.0):
    if agg.empty or len(agg) < 2:
        return None
    d = agg.sort_values("K").reset_index(drop=True)
    flips = []
    for i in range(len(d) - 1):
        g1, g2 = float(d.loc[i, "GEX"]), float(d.loc[i + 1, "GEX"])
        k1, k2 = float(d.loc[i, "K"]), float(d.loc[i + 1, "K"])
        if (g1 < 0 and g2 > 0) or (g1 > 0 and g2 < 0):
            flips.append(round(k1 + (0.0 - g1) * (k2 - k1) / (g2 - g1), 2))
    if not flips:
        return None
    return min(flips, key=lambda x: abs(x - spot)) if spot > 0 else flips[len(flips) // 2]

def render_gex_png(ticker, rows, spot):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    df = pd.DataFrame(rows)
    agg = df.groupby("K", as_index=False)[["GEX", "Call_OI", "Put_OI"]].sum()

    # Spot 기준 ±12% 구간만 확대 표시 (가독성 최적화)
    if spot > 0:
        sub = agg[(agg["K"] >= spot * 0.88) & (agg["K"] <= spot * 1.12)].copy()
        if len(sub) < 8:
            sub = agg.copy()
    else:
        sub = agg.copy()

    sub = sub.sort_values("K")
    strikes = sub["K"].values
    width = (strikes[1] - strikes[0]) * 0.7 if len(strikes) > 1 else 1.0

    plt.rcParams["axes.edgecolor"] = "#232733"
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 6.8), facecolor="#0b0e14", sharex=True)
    for ax in (ax1, ax2):
        ax.set_facecolor("#11141d")
        ax.tick_params(colors="#b0b8c4", labelsize=9)
        ax.grid(color="#1e222d", linestyle="--", linewidth=0.6, alpha=0.8)

    # Top: Net GEX
    gex_colors = ["#00e676" if v >= 0 else "#f23645" for v in sub["GEX"]]
    ax1.bar(strikes, sub["GEX"], width=width, color=gex_colors, alpha=0.9)
    ax1.axhline(0, color="#787b86", linewidth=0.8)
    zg = calc_zero_gamma(agg, spot)
    call_wall = float(agg.loc[agg["Call_OI"].idxmax(), "K"]) if agg["Call_OI"].max() > 0 else 0
    put_wall = float(agg.loc[agg["Put_OI"].idxmax(), "K"]) if agg["Put_OI"].max() > 0 else 0
    if spot > 0:
        ax1.axvline(spot, color="#fbbf24", linestyle="--", linewidth=1.4, label=f"Spot ${spot}")
    if zg:
        ax1.axvline(zg, color="#38bdf8", linestyle=":", linewidth=1.5, label=f"Zero Gamma ${zg:g}")
    if call_wall > 0:
        ax1.axvline(call_wall, color="#00e676", linestyle="-.", linewidth=1.0, alpha=0.7, label=f"Call Wall ${call_wall:g}")
    if put_wall > 0:
        ax1.axvline(put_wall, color="#f23645", linestyle="-.", linewidth=1.0, alpha=0.7, label=f"Put Wall ${put_wall:g}")
    ax1.legend(loc="upper right", facecolor="#161b26", edgecolor="#232733", labelcolor="#ffffff", fontsize=8)
    ax1.set_title(f"{ticker} Net GEX ($M) & Call/Put OI  |  Spot ${spot}", color="#ffffff", fontsize=13, fontweight="bold", pad=10)
    ax1.set_ylabel("Net GEX ($M)", color="#d1d4dc", fontsize=10)

    # Bottom: Call OI (+) vs Put OI (-)
    ax2.bar(strikes, sub["Call_OI"], width=width, color="#00e676", alpha=0.85, label="Call OI")
    ax2.bar(strikes, -sub["Put_OI"], width=width, color="#f23645", alpha=0.85, label="Put OI")
    ax2.axhline(0, color="#787b86", linewidth=0.8)
    if spot > 0:
        ax2.axvline(spot, color="#fbbf24", linestyle="--", linewidth=1.4)
    ax2.legend(loc="upper right", facecolor="#161b26", edgecolor="#232733", labelcolor="#ffffff", fontsize=9)
    ax2.set_ylabel("OI (Call + / Put -)", color="#d1d4dc", fontsize=10)
    ax2.set_xlabel("Strike ($)", color="#d1d4dc", fontsize=10)

    plt.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=140, facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)

    net_gex = float(df["GEX"].sum())
    call_wall = float(agg.loc[agg["Call_OI"].idxmax(), "K"]) if agg["Call_OI"].max() > 0 else 0
    put_wall = float(agg.loc[agg["Put_OI"].idxmax(), "K"]) if agg["Put_OI"].max() > 0 else 0
    c_tot = int(df["Call_OI"].sum())
    p_tot = int(df["Put_OI"].sum())
    pc = round(p_tot / max(c_tot, 1), 2)
    return buf.getvalue(), net_gex, call_wall, put_wall, pc, zg


def main():
    token, chat_id = load_tg()
    if not token or not chat_id:
        print("Missing telegram config")
        return

    for tk in DEFAULT_CHART_TICKERS:
        try:
            rows, spot = fetch_chain_for_chart(tk)
            if not rows:
                continue
            png_bytes, net_gex, cw, pw, pc, zg = render_gex_png(tk, rows, spot)
            cap = (
                f"📊 [{tk} 실시간 GEX · OI 차트]\n"
                f"• 현재가(Spot): ${spot}\n"
                f"• Net GEX: {net_gex:+.2f}M\n"
                f"• Zero Gamma: ${(f'{zg:g}' if zg else '-')} | Call Wall: ${cw:g} | Put Wall: ${pw:g}\n"
                f"• P/C 비율: {pc}"
            )
            ok = send_tg_photo(token, chat_id, png_bytes, caption=cap)
            print(f"{tk}: sent={ok}")
        except Exception as e:
            print(f"{tk}: error={e}")


if __name__ == "__main__":
    main()