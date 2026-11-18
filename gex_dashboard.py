import math
import datetime as dt
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _bs_delta_gamma(spot: float, strike: float, t_years: float, iv: float, cp: str, r: float = 0.045):
    if spot <= 0 or strike <= 0 or t_years <= 0 or iv <= 0:
        return (1.0 if (cp == "C" and spot > strike) else (-1.0 if (cp == "P" and spot < strike) else 0.0)), 0.0
    t_eff = max(t_years, 1.0 / 365.0)
    iv_eff = max(iv, 0.01)
    sqrt_t = math.sqrt(t_eff)
    d1 = (math.log(spot / strike) + (r + 0.5 * iv_eff * iv_eff) * t_eff) / (iv_eff * sqrt_t)
    gamma = _norm_pdf(d1) / (spot * iv_eff * sqrt_t)
    delta = _norm_cdf(d1) if cp == "C" else (_norm_cdf(d1) - 1.0)
    return delta, gamma


def _fmt_usd(val: float) -> str:
    av = abs(val)
    sign = "+" if val > 0 else ("-" if val < 0 else "")
    if av >= 1e9:
        return f"{sign}${av / 1e9:.2f}B"
    if av >= 1e6:
        return f"{sign}${av / 1e6:.2f}M"
    if av >= 1e3:
        return f"{sign}${av / 1e3:.1f}K"
    return f"{sign}${av:.0f}"


def _fmt_num_short(val: float) -> str:
    av = abs(val)
    sign = "+" if val > 0 else ("-" if val < 0 else "")
    if av >= 1e9:
        return f"{sign}{av / 1e9:.2f}B"
    if av >= 1e6:
        return f"{sign}{av / 1e6:.2f}M"
    if av >= 1e3:
        return f"{sign}{av / 1e3:.1f}K"
    return f"{sign}{av:.0f}"


@st.cache_data(ttl=180, show_spinner=False)
def _fetch_cboe_chain_rows(tk: str, max_exps: int = 6):
    import urllib.request, json, re
    try:
        cboe_sym = {"SPX": "_SPX", "NDX": "_NDX", "VIX": "_VIX", "RUT": "_RUT"}.get(tk, tk)
        url = f"https://cdn.cboe.com/api/global/delayed_quotes/options/{cboe_sym}.json"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        raw = json.loads(urllib.request.urlopen(req, timeout=8).read().decode("utf-8"))
        data_d = raw.get("data") or {}
        opts = data_d.get("options") or []
        spot = float(data_d.get("current_price") or data_d.get("close") or 0.0)
        if not opts or spot <= 0:
            return 0.0, []
        today = dt.date.today()
        today_s = today.isoformat()
        parsed, exp_set = [], set()
        for o in opts:
            occ = str(o.get("option") or "")
            m = re.match(r"^[A-Z]+(\d{6})([CP])(\d{8})$", occ)
            if not m:
                continue
            yymmdd, cp_code, k_raw = m.groups()
            exp_str = f"20{yymmdd[:2]}-{yymmdd[2:4]}-{yymmdd[4:6]}"
            if exp_str < today_s:
                continue
            strike = int(k_raw) / 1000.0
            oi = int(o.get("open_interest") or 0)
            vol = int(o.get("volume") or 0)
            if oi == 0 and vol == 0:
                continue
            exp_set.add(exp_str)
            parsed.append((exp_str, cp_code, strike, oi, vol, o))
        sel_exps = set(sorted(exp_set)[:max_exps])
        rows = []
        for exp_str, cp_code, strike, oi, vol, o in parsed:
            if exp_str not in sel_exps:
                continue
            dte = max((dt.date.fromisoformat(exp_str) - today).days, 0)
            t_years = max(dte, 0.5) / 365.0
            iv = float(o.get("iv") or 0.30)
            if iv <= 0.01:
                iv = 0.30
            delta = o.get("delta")
            gamma = o.get("gamma")
            if delta is None or gamma is None or float(gamma or 0) == 0:
                delta, gamma = _bs_delta_gamma(spot, strike, t_years, iv, cp_code)
            else:
                delta, gamma = float(delta), float(gamma)
            last_px = float(o.get("last_trade_price") or 0.0)
            bid = float(o.get("bid") or 0.0)
            ask = float(o.get("ask") or 0.0)
            mid = (bid + ask) / 2.0 if (bid > 0 and ask > 0) else last_px
            prem = vol * mid * 100.0
            gex = (1.0 if cp_code == "C" else -1.0) * gamma * oi * 100.0 * (spot ** 2) * 0.01
            dex = delta * oi * 100.0 * spot
            rows.append({
                "exp": exp_str, "dte": dte, "cp": cp_code, "strike": strike,
                "oi": oi, "vol": vol, "iv": iv, "delta": delta, "gamma": gamma,
                "gex_abs": abs(gex), "net_gex": gex, "dex_val": dex, "prem": prem, "mid": mid,
            })
        if rows and sum(r["oi"] for r in rows) >= 100:
            return spot, rows
    except Exception:
        pass
    return 0.0, []


@st.cache_data(ttl=60, show_spinner=False)
def _fetch_moomoo_chain_rows(tk: str, max_exps: int = 6):
    try:
        import socket as _sk_mg, concurrent.futures as _cf_mg
        with _sk_mg.create_connection(("127.0.0.1", 11111), timeout=0.25):
            pass
        def _mm_ch_w():
            from moomoo import OpenQuoteContext, RET_OK
            qc = OpenQuoteContext(host="127.0.0.1", port=11111)
            try:
                sym = f"US.{tk}"
                spot_mm = 0.0
                try:
                    rs_u, dfs_u = qc.get_market_snapshot([sym])
                    if rs_u == RET_OK and dfs_u is not None and not dfs_u.empty:
                        sr = dfs_u.iloc[0]
                        for sk in ("overnight_price", "after_price", "pre_price", "last_price", "cur_price"):
                            v = float(sr.get(sk) or 0)
                            if v > 0:
                                spot_mm = round(v, 2); break
                except Exception:
                    pass
                today_d = dt.date.today()
                end_d = (today_d + dt.timedelta(days=max(14, max_exps * 5))).isoformat()
                rc, dfc = qc.get_option_chain(code=sym, start=today_d.isoformat(), end=end_d)
                if rc != RET_OK or dfc is None or dfc.empty:
                    return 0.0, []
                if "strike_time" in dfc.columns:
                    exps_u = sorted(dfc["strike_time"].astype(str).str[:10].unique().tolist())[:max_exps]
                    dfc = dfc[dfc["strike_time"].astype(str).str[:10].isin(exps_u)]
                if spot_mm > 0 and "strike_price" in dfc.columns:
                    sp_s = pd.to_numeric(dfc["strike_price"], errors="coerce").fillna(0)
                    dfc = dfc[(sp_s >= spot_mm * 0.65) & (sp_s <= spot_mm * 1.35)]
                codes = dfc["code"].tolist()[:180]
                rows_mm = []
                for i in range(0, len(codes), 100):
                    rso, dfso = qc.get_market_snapshot(codes[i:i+100])
                    if rso != RET_OK or dfso is None or dfso.empty:
                        continue
                    for _, o in dfso.iterrows():
                        strike = float(o.get("option_strike_price") or 0)
                        if strike <= 0: continue
                        exp_str = str(o.get("strike_time") or "")[:10]
                        dte = max((dt.date.fromisoformat(exp_str) - today_d).days, 0) if len(exp_str) == 10 else 1
                        t_years = max(dte, 0.5) / 365.0
                        cp_code = "C" if "CALL" in str(o.get("option_type") or "").upper() else "P"
                        oi = float(o.get("option_open_interest") or 0)
                        vol = float(o.get("volume") or 0)
                        if oi <= 0 and vol <= 0: continue
                        iv = float(o.get("option_implied_volatility") or 0) / 100.0
                        if iv <= 0.01: iv = 0.35
                        s_ref = spot_mm if spot_mm > 0 else strike
                        delta = float(o.get("option_delta") or 0)
                        gamma = float(o.get("option_gamma") or 0)
                        if gamma == 0:
                            delta, gamma = _bs_delta_gamma(s_ref, strike, t_years, iv, cp_code)
                        lp = float(o.get("last_price") or 0)
                        bd = float(o.get("bid_price") or 0); ak = float(o.get("ask_price") or 0)
                        mid = (bd + ak) / 2.0 if (bd > 0 and ak > 0) else lp
                        prem = vol * mid * 100.0
                        gex = (1.0 if cp_code == "C" else -1.0) * gamma * oi * 100.0 * (s_ref ** 2) * 0.01
                        dex = delta * oi * 100.0 * s_ref
                        rows_mm.append({
                            "exp": exp_str, "dte": int(dte), "cp": cp_code, "strike": strike,
                            "oi": oi, "vol": vol, "iv": iv, "delta": delta, "gamma": gamma,
                            "gex_abs": abs(gex), "net_gex": gex, "dex_val": dex, "prem": prem, "mid": mid,
                        })
                if rows_mm and sum(r["oi"] for r in rows_mm) >= 100:
                    return spot_mm, rows_mm
                return 0.0, []
            finally:
                try: qc.close()
                except Exception: pass
        _ex_m = _cf_mg.ThreadPoolExecutor(max_workers=1)
        try:
            return _ex_m.submit(_mm_ch_w).result(timeout=3.5)
        finally:
            _ex_m.shutdown(wait=False)
    except Exception:
        return 0.0, []


def fetch_gex_chain_data(ticker: str, max_exps: int = 6, spot_override: float = 0.0):
    import yfinance as yf

    tk = (ticker or "SPY").strip().upper()
    _src_used = "Cboe 지연시세"
    _mm_spot, _mm_rows = _fetch_moomoo_chain_rows(tk, max_exps=max_exps)
    if _mm_rows:
        spot, rows = (_mm_spot if _mm_spot > 0 else float(spot_override or 0)), _mm_rows
        _src_used = "무무 OpenD 실시간"
    else:
        _cb_spot, _cb_rows = _fetch_cboe_chain_rows(tk, max_exps=max_exps)
        if _cb_rows:
            spot, rows = _cb_spot, _cb_rows
        else:
            spot, rows = 0.0, []
    if rows:
        spot, rows = _cb_spot, _cb_rows
        if spot_override and float(spot_override) > 0 and abs(float(spot_override) - spot) > 1e-4:
            spot = float(spot_override)
            for _r in rows:
                _t_y = max(float(_r.get("dte", 0)), 0.5) / 365.0
                _iv = float(_r.get("iv") or 0.30)
                _cp = _r.get("cp", "C")
                _st = float(_r.get("strike") or 0.0)
                _oi = float(_r.get("oi") or 0.0)
                if _st > 0:
                    _dl, _gm = _bs_delta_gamma(spot, _st, _t_y, _iv, _cp)
                    _gabs = (spot * spot * 0.01) * _gm * _oi * 100.0
                    _r["delta"] = _dl
                    _r["gamma"] = _gm
                    _r["gex_abs"] = _gabs
                    _r["net_gex"] = _gabs if _cp == "C" else -_gabs
                    _r["dex_val"] = _dl * _oi * 100.0 * spot
    else:
        t = yf.Ticker(tk)

        spot = 0.0
        try:
            fi = getattr(t, "fast_info", None)
            if fi:
                spot = float(fi.get("lastPrice") or fi.get("regularMarketPrice") or fi.get("previousClose") or 0.0)
        except Exception:
            spot = 0.0

        if spot <= 0:
            try:
                hist = t.history(period="5d")
                if not hist.empty:
                    spot = float(hist["Close"].dropna().iloc[-1])
            except Exception:
                pass
        if spot_override and float(spot_override) > 0:
            spot = float(spot_override)

        exps = list(getattr(t, "options", []) or [])
        if spot <= 0 or not exps:
            return {"ok": False, "error": f"'{tk}'의 현재가 또는 옵션 체인을 불러오지 못했습니다.", "ticker": tk}

        today = dt.date.today()
        sel_exps = exps[:max_exps]
        rows = []

        for exp_str in sel_exps:
            try:
                exp_dt = dt.date.fromisoformat(exp_str)
                dte = max((exp_dt - today).days, 0)
                t_years = max(dte, 0.5) / 365.0
                ch = t.option_chain(exp_str)
            except Exception:
                continue

            for cp_code, df_side in [("C", ch.calls), ("P", ch.puts)]:
                if df_side is None or df_side.empty:
                    continue
                for _, r in df_side.iterrows():
                    strike = float(r.get("strike") or 0.0)
                    if strike <= 0:
                        continue
                    # 노이즈 극단 행사가 필터 (현물 +-50% 이내)
                    if strike < spot * 0.5 or strike > spot * 1.5:
                        continue
                    oi = float(r.get("openInterest") or 0.0)
                    vol = float(r.get("volume") or 0.0)
                    iv = float(r.get("impliedVolatility") or 0.0)
                    if math.isnan(oi):
                        oi = 0.0
                    if math.isnan(vol):
                        vol = 0.0
                    if math.isnan(iv) or iv <= 0:
                        iv = 0.35

                    last_p = float(r.get("lastPrice") or 0.0)
                    bid_p = float(r.get("bid") or 0.0)
                    ask_p = float(r.get("ask") or 0.0)
                    if math.isnan(last_p):
                        last_p = 0.0
                    mid_p = ((bid_p + ask_p) / 2.0) if (bid_p > 0 and ask_p > 0) else last_p
                    prem = vol * mid_p * 100.0

                    delta, gamma = _bs_delta_gamma(spot, strike, t_years, iv, cp_code)
                    # Dealer GEX (Spot 1% 변동당 델타 헷지 금액): Spot^2 * 0.01 * Gamma * OI * 100
                    gex_abs = (spot * spot * 0.01) * gamma * oi * 100.0
                    net_gex = gex_abs if cp_code == "C" else -gex_abs
                    # Dealer DEX (Delta Exposure): Delta * OI * 100 * Spot
                    dex_val = delta * oi * 100.0 * spot

                    rows.append({
                        "exp": exp_str,
                        "dte": int(dte),
                        "cp": cp_code,
                        "strike": strike,
                        "oi": oi,
                        "vol": vol,
                        "iv": iv,
                        "mid": mid_p,
                        "prem": prem,
                        "delta": delta,
                        "gamma": gamma,
                        "gex_abs": gex_abs,
                        "net_gex": net_gex,
                        "dex": dex_val,
                    })

    if not rows:
        return {"ok": False, "error": f"'{tk}' 옵션 체인 유효 데이터가 없습니다.", "ticker": tk}

    df = pd.DataFrame(rows)
    if "net_gex" not in df.columns and "gex" in df.columns:
        df["net_gex"] = df["gex"]
    if "gex_abs" not in df.columns and "net_gex" in df.columns:
        df["gex_abs"] = df["net_gex"].abs()
    if "dex_val" not in df.columns and "dex" in df.columns:
        df["dex_val"] = df["dex"]

    # 행사가별 집계
    by_k = pd.DataFrame({"strike": sorted(df["strike"].unique())})
    c_df = df[df["cp"] == "C"].groupby("strike").agg(
        call_gex=("net_gex", "sum"),
        call_dex=("dex", "sum"),
        call_oi=("oi", "sum"),
        call_vol=("vol", "sum"),
        call_prem=("prem", "sum"),
        call_delta=("delta", "mean"),
        call_gamma=("gamma", "mean"),
    )
    p_df = df[df["cp"] == "P"].groupby("strike").agg(
        put_gex=("net_gex", "sum"),
        put_dex=("dex", "sum"),
        put_oi=("oi", "sum"),
        put_vol=("vol", "sum"),
        put_prem=("prem", "sum"),
        put_delta=("delta", "mean"),
        put_gamma=("gamma", "mean"),
    )
    by_k = by_k.merge(c_df, on="strike", how="left").merge(p_df, on="strike", how="left").fillna(0.0)
    by_k["net_gex"] = by_k["call_gex"] + by_k["put_gex"]
    by_k["gross_gex"] = by_k["call_gex"].abs() + by_k["put_gex"].abs()
    by_k["net_dex"] = by_k["call_dex"] + by_k["put_dex"]
    by_k["total_oi"] = by_k["call_oi"] + by_k["put_oi"]
    by_k["total_vol"] = by_k["call_vol"] + by_k["put_vol"]
    by_k["vol_oi"] = np.where(by_k["total_oi"] > 0, by_k["total_vol"] / by_k["total_oi"], 0.0)
    by_k["net_prem"] = by_k["call_prem"] - by_k["put_prem"]
    by_k["total_prem"] = by_k["call_prem"] + by_k["put_prem"]

    total_net_gex = float(by_k["net_gex"].sum())
    total_gross_gex = float(by_k["gross_gex"].sum())
    total_net_dex = float(by_k["net_dex"].sum())
    total_call_oi = float(by_k["call_oi"].sum())
    total_put_oi = float(by_k["put_oi"].sum())
    total_call_prem = float(by_k["call_prem"].sum())
    total_put_prem = float(by_k["put_prem"].sum())

    # Call Wall & Put Wall
    _bk_c = by_k[(by_k["strike"] >= spot * 0.98) & (by_k["strike"] <= spot * 1.25)]
    if _bk_c.empty: _bk_c = by_k[by_k["strike"] >= spot * 0.98]
    if _bk_c.empty: _bk_c = by_k
    _bk_p = by_k[(by_k["strike"] >= spot * 0.80) & (by_k["strike"] <= spot * 1.02)]
    if _bk_p.empty: _bk_p = by_k[by_k["strike"] <= spot * 1.02]
    if _bk_p.empty: _bk_p = by_k
    call_wall = float(_bk_c.loc[_bk_c["call_gex"].idxmax(), "strike"]) if _bk_c["call_gex"].max() > 0 else float(_bk_c.loc[_bk_c["call_oi"].idxmax(), "strike"])
    put_wall = float(_bk_p.loc[_bk_p["put_gex"].idxmin(), "strike"]) if _bk_p["put_gex"].min() < 0 else float(_bk_p.loc[_bk_p["put_oi"].idxmax(), "strike"])

    # 2차 지지/저항
    top_calls = by_k.sort_values("call_gex", ascending=False)["strike"].head(3).tolist()
    top_puts = by_k.sort_values("put_gex", ascending=True)["strike"].head(3).tolist()

    # GEX Flip (Zero Gamma): 누적 Net GEX 부호 전환 지점 선형 보간
    gex_flip = spot
    by_k_sorted = by_k.sort_values("strike").reset_index(drop=True)
    cum = by_k_sorted["net_gex"].cumsum().values
    ks = by_k_sorted["strike"].values
    flips = []
    for i in range(1, len(ks)):
        if (cum[i - 1] < 0 <= cum[i]) or (cum[i - 1] > 0 >= cum[i]):
            denom = cum[i] - cum[i - 1]
            frac = (-cum[i - 1] / denom) if denom != 0 else 0.5
            flips.append(float(ks[i - 1] + frac * (ks[i] - ks[i - 1])))
    if flips:
        gex_flip = min(flips, key=lambda x: abs(x - spot))
    else:
        # 차선책: 현물 근처 net_gex 절댓값 최소 지점
        near = by_k_sorted[(by_k_sorted["strike"] >= spot * 0.92) & (by_k_sorted["strike"] <= spot * 1.08)]
        if not near.empty:
            gex_flip = float(near.loc[near["net_gex"].abs().idxmin(), "strike"])

    # Max Pain (전체 집계 기준 행사가별 결제 손실 최소점)
    min_pain_val = None
    max_pain = spot
    for k_cand in ks:
        c_pay = float(((k_cand - by_k_sorted["strike"]).clip(lower=0) * by_k_sorted["call_oi"]).sum())
        p_pay = float(((by_k_sorted["strike"] - k_cand).clip(lower=0) * by_k_sorted["put_oi"]).sum())
        tot_pay = c_pay + p_pay
        if min_pain_val is None or tot_pay < min_pain_val:
            min_pain_val = tot_pay
            max_pain = float(k_cand)

    # OI 집중구간 Top 5
    top_oi = by_k.sort_values("total_oi", ascending=False).head(5)[["strike", "call_oi", "put_oi", "total_oi", "net_gex"]]

    # DTE별 요약
    by_dte = df.groupby(["exp", "dte"]).agg(
        net_gex=("net_gex", "sum"),
        gross_gex=("gex_abs", "sum"),
        net_dex=("dex", "sum"),
        total_oi=("oi", "sum"),
        total_vol=("vol", "sum"),
        total_prem=("prem", "sum"),
    ).reset_index().sort_values("dte")

    # AI 최종판정 점수 계산 (상승 / 횡보 / 하락 확률)
    bull_score = 0.0
    bear_score = 0.0
    flat_score = 20.0

    if total_net_gex > 0:
        flat_score += 12.0
        bull_score += 12.0
    else:
        bear_score += 14.0

    if spot >= gex_flip:
        bull_score += 16.0
    else:
        bear_score += 18.0

    if total_net_dex > 0:
        bull_score += 14.0
    elif total_net_dex < 0:
        bear_score += 14.0

    pc_oi = total_put_oi / max(total_call_oi, 1.0)
    if pc_oi < 0.85:
        bull_score += 12.0
    elif pc_oi > 1.15:
        bear_score += 12.0
    else:
        flat_score += 8.0

    if total_call_prem > total_put_prem * 1.15:
        bull_score += 12.0
    elif total_put_prem > total_call_prem * 1.15:
        bear_score += 12.0
    else:
        flat_score += 6.0

    if spot < call_wall and spot > put_wall:
        up_room = (call_wall - spot) / max(spot, 1.0)
        dn_room = (spot - put_wall) / max(spot, 1.0)
        if up_room > dn_room * 1.2:
            bull_score += 8.0
        elif dn_room > up_room * 1.2:
            bear_score += 8.0
        else:
            flat_score += 10.0

    tot_s = max(bull_score + flat_score + bear_score, 1.0)
    p_up = int(round(bull_score / tot_s * 100))
    p_flat = int(round(flat_score / tot_s * 100))
    p_down = max(0, 100 - p_up - p_flat)

    if p_up >= p_down + 10 and p_up >= p_flat:
        verdict_emoji, verdict_lbl, verdict_prob = "🟢", "강세", p_up
    elif p_down >= p_up + 10 and p_down >= p_flat:
        verdict_emoji, verdict_lbl, verdict_prob = "🔴", "약세", p_down
    else:
        verdict_emoji, verdict_lbl, verdict_prob = "🟡", "중립", max(p_up, p_flat, p_down)

    return {
        "ok": True,
        "ticker": tk,
        "spot": spot,
        "data_source": _src_used if "rows" in locals() and rows else "Yahoo Finance",
        "exps": sel_exps,
        "by_k": by_k_sorted,
        "by_dte": by_dte,
        "top_oi": top_oi,
        "net_gex": total_net_gex,
        "gross_gex": total_gross_gex,
        "net_dex": total_net_dex,
        "gex_flip": gex_flip,
        "call_wall": call_wall,
        "put_wall": put_wall,
        "top_calls": top_calls,
        "top_puts": top_puts,
        "max_pain": max_pain,
        "call_oi": total_call_oi,
        "put_oi": total_put_oi,
        "pc_oi": pc_oi,
        "call_prem": total_call_prem,
        "put_prem": total_put_prem,
        "dealer_pos": "양감마 (+GEX · 변동성 억제/박스권)" if total_net_gex >= 0 else "음감마 (-GEX · 변동성 확대/추세 가속)",
        "dealer_short": "양감마" if total_net_gex >= 0 else "음감마",
        "p_up": p_up,
        "p_flat": p_flat,
        "p_down": p_down,
        "verdict_emoji": verdict_emoji,
        "verdict_lbl": verdict_lbl,
        "verdict_prob": verdict_prob,
    }



def _get_mm_live_for_gex(tk):
    import os, json, sqlite3
    clean = str(tk or "").strip().upper().replace("US.", "")
    sym = f"US.{clean}"
    res = {"px": 0.0, "summary": ""}
    db_p = os.environ.get("MOOMOO_DB", os.path.expanduser("~/moomoo-hub/moomoo.db"))
    try:
        if os.path.exists(db_p):
            con = sqlite3.connect(f"file:{db_p}?mode=ro", uri=True, timeout=2)
            row = con.execute("SELECT data FROM quotes WHERE sym=?", (sym,)).fetchone()
            con.close()
            if row and row[0]:
                qd = json.loads(row[0])
                for ek in ("overnight_price", "after_price", "pre_price", "ext_price", "last_price", "px", "price"):
                    v = float(qd.get(ek) or 0)
                    if v > 0:
                        res["px"] = round(v, 2); break
    except Exception:
        pass
    if res["px"] <= 0:
        try:
            import urllib.request
            _u8 = f"http://127.0.0.1:8502/quote?sym={clean}"
            _j8 = json.loads(urllib.request.urlopen(_u8, timeout=0.5).read().decode("utf-8"))
            _raw8 = _j8.get("raw") if isinstance(_j8.get("raw"), dict) else {}
            for ek in ("overnight_price", "after_price", "pre_price", "ext_price", "last_price", "px", "price"):
                _v8 = float(_raw8.get(ek) or _j8.get(ek) or 0)
                if _v8 > 0:
                    res["px"] = round(_v8, 2); break
        except Exception:
            pass
    parts = []
    try:
        import socket, concurrent.futures
        with socket.create_connection(("127.0.0.1", 11111), timeout=0.2):
            pass
        def _gex_mm_w():
            out_p = []
            snap_px = 0.0
            from moomoo import OpenQuoteContext, SubType, RET_OK
            qc = OpenQuoteContext(host="127.0.0.1", port=11111)
            try:
                try:
                    r_sn, df_sn = qc.get_market_snapshot([sym])
                    if r_sn == RET_OK and df_sn is not None and not df_sn.empty:
                        sr = df_sn.iloc[0]
                        for sk in ("overnight_price", "after_price", "pre_price", "last_price", "cur_price", "nominal_price"):
                            try:
                                sv = float(sr.get(sk) or 0)
                                if sv > 0:
                                    snap_px = round(sv, 2); break
                            except Exception:
                                pass
                except Exception:
                    pass
                qc.subscribe([sym], [SubType.ORDER_BOOK, SubType.TICKER], subscribe_push=False)
                r_ob, df_ob = qc.get_order_book(sym, num=10)
                if r_ob == RET_OK and isinstance(df_ob, dict):
                    bids = df_ob.get("Bid") or []
                    asks = df_ob.get("Ask") or []
                    if bids:
                        tb = max(bids, key=lambda x: x[1])
                        out_p.append(f"매수벽 ${float(tb[0]):.2f}({int(tb[1]):,})")
                    if asks:
                        ta = max(asks, key=lambda x: x[1])
                        out_p.append(f"매도벽 ${float(ta[0]):.2f}({int(ta[1]):,})")
                r_tk, df_tk = qc.get_rt_ticker(sym, num=200)
                if r_tk == RET_OK and df_tk is not None and not df_tk.empty:
                    bv = sum(float(tr.get("turnover", 0) or 0) for _, tr in df_tk.iterrows() if "BUY" in str(tr.get("ticker_direction", "")).upper())
                    sv = sum(float(tr.get("turnover", 0) or 0) for _, tr in df_tk.iterrows() if "SELL" in str(tr.get("ticker_direction", "")).upper())
                    out_p.append(f"틱CVD {(bv-sv):+,.0f}$")
            finally:
                try: qc.close()
                except Exception: pass
            return snap_px, out_p
        _ex_g = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        try:
            _s_px, _s_out = _ex_g.submit(_gex_mm_w).result(timeout=1.2)
            if _s_px and _s_px > 0:
                res["px"] = _s_px
            parts.extend(_s_out)
        finally:
            _ex_g.shutdown(wait=False)
    except Exception:
        pass
    if res["px"] > 0:
        parts.insert(0, f"무무실시간 ${res['px']:,.2f}")
    res["summary"] = " | ".join(parts)
    return res


def render_ai_gex_dashboard(run_ai_fn=None, send_tg_fn=None, tg_token="", tg_chat_id=""):
    st.title("🎯 AI GEX 분석")
    st.caption("종목 입력 → GEX → DEX → OI → Volume/OI → Premium → Delta/Gamma → DTE 순서로 분석하고 AI 최종판정을 자동 출력합니다.")

    c1, c2, c3 = st.columns([1.4, 2.2, 1.0])
    quick_tks = ["SPY", "QQQ", "NVDA", "TSLA", "PLTR", "SMH", "SOXL", "MU"]
    if "ai_gex_tk" not in st.session_state:
        st.session_state["ai_gex_tk"] = "NVDA"

    tk_in = c1.text_input("종목 티커 입력", value=st.session_state["ai_gex_tk"], key="ai_gex_tk_input").strip().upper()
    if tk_in:
        st.session_state["ai_gex_tk"] = tk_in

    max_exps = c2.slider("분석 만기 개수 (가까운 순)", 2, 10, 6, key="ai_gex_max_exps")
    if c3.button("🔄 실시간 새로고침", use_container_width=True, key="btn_ai_gex_refresh"):
        _fetch_moomoo_chain_rows.clear(); _fetch_cboe_chain_rows.clear()
        st.rerun()

    qcols = st.columns(len(quick_tks))
    for i, qtk in enumerate(quick_tks):
        if qcols[i].button(qtk, use_container_width=True, key=f"btn_gex_q_{qtk}"):
            st.session_state["ai_gex_tk"] = qtk
            st.rerun()

    tk_target = st.session_state.get("ai_gex_tk", "NVDA")
    _mm_gex = _get_mm_live_for_gex(tk_target)
    with st.spinner(f"{tk_target} 실시간 옵션 체인 GEX·DEX·OI·Greeks 계산 중..."):
        res = fetch_gex_chain_data(tk_target, max_exps=max_exps, spot_override=_mm_gex["px"])

    if not res.get("ok"):
        st.error(res.get("error", "데이터 조회 실패"))
        return

    spot = _mm_gex["px"] if _mm_gex["px"] > 0 else res["spot"]
    _ds_lbl = res.get("data_source", "Cboe")
    if _mm_gex["summary"]:
        st.caption(f"📡 옵션 체인: **{_ds_lbl}** | 무무 실시간: {_mm_gex['summary']}")
    else:
        st.caption(f"📡 옵션 체인 소스: **{_ds_lbl}**")
    cw = res["call_wall"]
    pw = res["put_wall"]
    flip = res["gex_flip"]
    mp = res["max_pain"]
    net_gex = res["net_gex"]
    gross_gex = res["gross_gex"]
    net_dex = res["net_dex"]
    up_next = round(cw * 1.04, 1) if cw > 0 else round(spot * 1.05, 1)

    gex_dot = "🟢" if net_gex >= 0 else "🔴"
    flip_dot = "🟢" if spot >= flip else "🟡"

    # 대장님 스타일 1줄 핵심 브리핑 카드
    summary_text = (
        f"**{tk_target} 현재가 `{spot:.2f}`**\n\n"
        f"{gex_dot} **Net GEX** `{_fmt_num_short(net_gex)}` &nbsp;|&nbsp; "
        f"⚪ **Gross GEX** `{_fmt_num_short(gross_gex)}` &nbsp;|&nbsp; "
        f"🟢 **Call Wall** `{cw:g}` &nbsp;|&nbsp; "
        f"🔴 **Put Wall** `{pw:g}` &nbsp;|&nbsp; "
        f"{flip_dot} **GEX Flip** `{flip:.1f}` &nbsp;|&nbsp; "
        f"🎯 **Max Pain** `{mp:g}`\n\n"
        f"**Dealer**: `{res['dealer_pos']}`\n\n"
        f"**시나리오**: `{cw:g}` 돌파 시 `{up_next:g}` 타겟 / `{flip:.1f}` 이탈 시 `{pw:g}` 방어선 테스트\n\n"
        f"### {res['verdict_emoji']} AI 최종판정: **{res['verdict_lbl']} {res['verdict_prob']}%** "
        f"(상승 `{res['p_up']}%` · 횡보 `{res['p_flat']}%` · 하락 `{res['p_down']}%`)"
    )
    with st.container(border=True):
        st.markdown(summary_text)

    # 주요 KPI 메트릭
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("현재가 (Spot)", f"${spot:.2f}")
    m2.metric("Net GEX", _fmt_num_short(net_gex), res["dealer_short"])
    m3.metric("Net DEX", _fmt_usd(net_dex))
    m4.metric("Call / Put Wall", f"{cw:g} / {pw:g}")
    m5.metric("Max Pain / Flip", f"{mp:g} / {flip:.1f}")

    # 주요 지지/저항 & OI 집중구간 요약
    sc1, sc2 = st.columns(2)
    with sc1:
        with st.container(border=True):
            st.markdown("#### 🛡️ 주요 지지 / 저항 레벨")
            st.markdown(
                f"- **1차 저항 (Call Wall)**: `{cw:g}` (상위 콜 밀집: `{', '.join(f'{x:g}' for x in res['top_calls'])}`)\n"
                f"- **감마 플립 (변곡점)**: `{flip:.2f}` ({'현재가 상회 → 안정' if spot >= flip else '현재가 하회 → 변동성 주의'})\n"
                f"- **Max Pain (만기 자석)**: `{mp:g}`\n"
                f"- **1차 지지 (Put Wall)**: `{pw:g}` (상위 풋 밀집: `{', '.join(f'{x:g}' for x in res['top_puts'])}`)"
            )
    with sc2:
        with st.container(border=True):
            st.markdown("#### 🎯 옵션 OI 집중구간 Top 5")
            df_oi_top = res["top_oi"].copy()
            df_oi_top["행사가"] = df_oi_top["strike"].map(lambda x: f"{x:g}")
            df_oi_top["콜 OI"] = df_oi_top["call_oi"].map(lambda x: f"{int(x):,}")
            df_oi_top["풋 OI"] = df_oi_top["put_oi"].map(lambda x: f"{int(x):,}")
            df_oi_top["총 OI"] = df_oi_top["total_oi"].map(lambda x: f"{int(x):,}")
            df_oi_top["Net GEX"] = df_oi_top["net_gex"].map(_fmt_num_short)
            st.dataframe(df_oi_top[["행사가", "콜 OI", "풋 OI", "총 OI", "Net GEX"]], hide_index=True, use_container_width=True)

    # 액션 버튼: Gemini 심층 해석 & 텔레그램 전송
    ac1, ac2 = st.columns(2)
    if ac1.button("🤖 Gemini AI 최종판정·매매시나리오 생성", use_container_width=True, key="btn_gex_gemini"):
        if run_ai_fn:
            with st.spinner("Gemini가 GEX·DEX·OI·Premium·DTE를 종합 판정 중..."):
                _prompt = (
                    f"{tk_target} 옵션 구조 데이터입니다. GEX → DEX → OI → Volume/OI → Premium → Delta/Gamma → DTE 순서로 핵심만 짚고 "
                    f"진입 타점, 목표가(TP), 손절선(SL)을 제시해 주세요.\n"
                    f"- 현재가: {spot:.2f}\n"
                    f"- Net GEX: {_fmt_num_short(net_gex)} ({res['dealer_pos']}), Gross GEX: {_fmt_num_short(gross_gex)}\n"
                    f"- Net DEX: {_fmt_usd(net_dex)}\n"
                    f"- Call Wall: {cw:g}, Put Wall: {pw:g}, GEX Flip: {flip:.1f}, Max Pain: {mp:g}\n"
                    f"- Call OI: {int(res['call_oi']):,}, Put OI: {int(res['put_oi']):,} (P/C={res['pc_oi']:.2f})\n"
                    f"- Call Prem: {_fmt_usd(res['call_prem'])}, Put Prem: {_fmt_usd(res['put_prem'])}\n"
                    f"- 확률 판정: 상승 {res['p_up']}% / 횡보 {res['p_flat']}% / 하락 {res['p_down']}%"
                    + (f"\n- 무무 실시간 수급(60호가·틱CVD): {_mm_gex['summary']}" if _mm_gex["summary"] else "")
                )
                _ok_g, _ai_out = run_ai_fn(_prompt)
                if not _ok_g or "API 키가 설정되지" in str(_ai_out):
                    _reg_k = "포지티브 감마(+GEX · 박스권/반등 억제)" if net_gex >= 0 else "네거티브 감마(-GEX · 변동성 확대/추세 추종)"
                    _bias_k = "상방(롱) 우위" if spot >= flip else "하방(숏·관망) 주의"
                    _ai_out = (
                        f"### 🎯 {tk_target} 정량 GEX · 무무 수급 매매 시나리오 (자체 엔진)\n"
                        f"- **1. 구조 요약**: 현재가 `${spot:.2f}` | Net GEX `{_fmt_num_short(net_gex)}` (**{_reg_k}**) | GEX Flip `${flip:.1f}` (**{_bias_k}**) | Max Pain `${mp:g}`\n"
                        f"- **2. 핵심 벽**: 🟢 1차 저항 Call Wall `${cw:g}` (돌파 시 `${up_next:g}`) / 🔴 1차 지지 Put Wall `${pw:g}`\n"
                        f"- **3. 수급·실전 타점**:\n"
                        f"  - **롱(매수) 타점**: Put Wall `${pw:g}` 지지 확인 또는 Flip `${flip:.1f}` 상향 돌파 안착 시 진입 → 목표 `${cw:g}` / 손절 `${pw*0.985:.2f}`\n"
                        f"  - **숏(방어) 타점**: Flip `${flip:.1f}` 하향 이탈 또는 `${cw:g}` 저항 리젝션 시 → 목표 `${pw:g}` / 손절 `${cw*1.015:.2f}`\n"
                        f"  - **최종 판정**: {res['verdict_emoji']} **{res['verdict_lbl']} {res['verdict_prob']}%** (상승 {res['p_up']}% · 횡보 {res['p_flat']}% · 하락 {res['p_down']}%)"
                        + (f"\n- **4. 무무 실시간**: {_mm_gex['summary']}" if _mm_gex.get("summary") else "")
                    )
                st.session_state["ai_gex_gemini_out"] = _ai_out
        else:
            st.warning("AI 분석 함수가 연결되지 않았습니다.")

    if ac2.button("📩 텔레그램으로 AI GEX 브리핑 전송", use_container_width=True, key="btn_gex_tg"):
        if send_tg_fn:
            _top3_oi = res["by_k"].sort_values("total_oi", ascending=False).head(3)
            _top3_lines = "\n".join(
                f"  • `{r['strike']:g}` | 콜 {int(r['call_oi']):,} · 풋 {int(r['put_oi']):,} | Net GEX `{_fmt_num_short(r['net_gex'])}`"
                for _, r in _top3_oi.iterrows()
            )
            _gem_txt = str(st.session_state.get("ai_gex_gemini_out") or "").strip()
            _scen_extra = f"\n\n🤖 *상세 시나리오*\n{_gem_txt[:1500]}" if _gem_txt else (
                f"\n\n🧭 *실전 매매 타점*\n"
                f"• 롱(상방): Put Wall `${pw:g}` 지지 또는 Flip `${flip:.1f}` 돌파 안착 시 → 목표 `${cw:g}` (돌파 시 `${up_next:g}`) / 손절 `${pw*0.985:.2f}`\n"
                f"• 숏(하방): Flip `${flip:.1f}` 하향 이탈 또는 `${cw:g}` 리젝션 시 → 목표 `${pw:g}` / 손절 `${cw*1.015:.2f}`"
            )
            _mm_line = f"\n📡 무무 실시간: `{_mm_gex['summary']}`" if _mm_gex.get("summary") else ""
            _tg_msg = (
                f"🎯 *[AI GEX 심층 분석] {tk_target}*\n"
                f"💵 현재가: `${spot:.2f}` | Dealer: `{res['dealer_pos']}`\n"
                f"{gex_dot} Net GEX: `{_fmt_num_short(net_gex)}` | Gross GEX: `{_fmt_num_short(gross_gex)}`\n"
                f"📐 Net DEX: `{_fmt_usd(net_dex)}` | P/C(OI): `{res['pc_oi']:.2f}` (콜 {int(res['call_oi']):,} · 풋 {int(res['put_oi']):,})\n"
                f"💰 프리미엄: Call `{_fmt_usd(res['call_prem'])}` vs Put `{_fmt_usd(res['put_prem'])}`\n"
                f"🧱 핵심 레벨: 🟢 Call Wall `${cw:g}` · 🔴 Put Wall `${pw:g}` · {flip_dot} Flip `${flip:.1f}` · 🎯 Max Pain `${mp:g}`"
                f"{_mm_line}\n\n"
                f"📊 *OI 밀집 상위 TOP3*\n{_top3_lines}"
                f"{_scen_extra}\n\n"
                f"{res['verdict_emoji']} *AI 최종판정: {res['verdict_lbl']} {res['verdict_prob']}%*\n"
                f"(상승 {res['p_up']}% · 횡보 {res['p_flat']}% · 하락 {res['p_down']}%)"
            )
            if send_tg_fn(tg_token, tg_chat_id, _tg_msg)[0]:
                st.toast("✅ 텔레그램 전송 완료!")
            else:
                st.toast("⚠️ 텔레그램 설정을 확인해 주세요.")

    if st.session_state.get("ai_gex_gemini_out"):
        st.info(st.session_state["ai_gex_gemini_out"])

    # 현물 +-18% 범위로 차트 가독성 필터링
    df_k = res["by_k"]
    df_plot = df_k[(df_k["strike"] >= spot * 0.82) & (df_k["strike"] <= spot * 1.18)].copy()
    if df_plot.empty:
        df_plot = df_k.copy()

    def _add_ref_lines(fig):
        fig.add_vline(x=spot, line_dash="dash", line_color="#ffffff", annotation_text=f"Spot {spot:.1f}", annotation_position="top")
        fig.add_vline(x=cw, line_dash="dot", line_color="#4ade80", annotation_text=f"CW {cw:g}", annotation_position="top right")
        fig.add_vline(x=pw, line_dash="dot", line_color="#f87171", annotation_text=f"PW {pw:g}", annotation_position="top left")
        fig.add_vline(x=flip, line_dash="dashdot", line_color="#facc15", annotation_text=f"Flip {flip:.1f}", annotation_position="bottom")
        fig.update_layout(template="plotly_dark", height=360, margin=dict(l=20, r=20, t=35, b=20), paper_bgcolor="#0e1117", plot_bgcolor="#0e1117")
        return fig

    st.markdown("---")
    st.subheader("📐 단계별 구조 분석 (GEX → DEX → OI → Volume/OI → Premium → Delta/Gamma → DTE)")

    tabs = st.tabs(["1. GEX", "2. DEX", "3. OI", "4. Volume/OI", "5. Premium", "6. Delta/Gamma", "7. DTE"])

    with tabs[0]:
        fig1 = go.Figure()
        fig1.add_trace(go.Bar(x=df_plot["strike"], y=df_plot["call_gex"], name="Call GEX (+)", marker_color="#22c55e"))
        fig1.add_trace(go.Bar(x=df_plot["strike"], y=df_plot["put_gex"], name="Put GEX (-)", marker_color="#ef4444"))
        fig1.add_trace(go.Scatter(x=df_plot["strike"], y=df_plot["net_gex"], name="Net GEX", line=dict(color="#60a5fa", width=2)))
        fig1.update_layout(barmode="relative", title=f"{tk_target} 행사가별 Call/Put & Net GEX")
        st.plotly_chart(_add_ref_lines(fig1), use_container_width=True)

    with tabs[1]:
        fig2 = go.Figure()
        fig2.add_trace(go.Bar(x=df_plot["strike"], y=df_plot["call_dex"], name="Call DEX", marker_color="#38bdf8"))
        fig2.add_trace(go.Bar(x=df_plot["strike"], y=df_plot["put_dex"], name="Put DEX", marker_color="#fb923c"))
        fig2.update_layout(barmode="relative", title=f"{tk_target} 행사가별 Delta Exposure (DEX)")
        st.plotly_chart(_add_ref_lines(fig2), use_container_width=True)

    with tabs[2]:
        fig3 = go.Figure()
        fig3.add_trace(go.Bar(x=df_plot["strike"], y=df_plot["call_oi"], name="Call OI", marker_color="#4ade80"))
        fig3.add_trace(go.Bar(x=df_plot["strike"], y=df_plot["put_oi"], name="Put OI", marker_color="#f87171"))
        fig3.update_layout(barmode="group", title=f"{tk_target} 미결제약정 (OI) 분포 · P/C Ratio {res['pc_oi']:.2f}")
        st.plotly_chart(_add_ref_lines(fig3), use_container_width=True)

    with tabs[3]:
        fig4 = go.Figure()
        fig4.add_trace(go.Bar(x=df_plot["strike"], y=df_plot["vol_oi"], name="Volume / OI", marker_color="#a78bfa"))
        fig4.update_layout(title=f"{tk_target} 행사가별 Volume / OI 비율 (신규 자금 유입 포착)")
        st.plotly_chart(_add_ref_lines(fig4), use_container_width=True)

    with tabs[4]:
        fig5 = go.Figure()
        fig5.add_trace(go.Bar(x=df_plot["strike"], y=df_plot["call_prem"], name="Call Premium", marker_color="#10b981"))
        fig5.add_trace(go.Bar(x=df_plot["strike"], y=-df_plot["put_prem"], name="Put Premium (-)", marker_color="#f43f5e"))
        fig5.update_layout(barmode="relative", title=f"{tk_target} 콜 vs 풋 유입 프리미엄 (Call {_fmt_usd(res['call_prem'])} / Put {_fmt_usd(res['put_prem'])})")
        st.plotly_chart(_add_ref_lines(fig5), use_container_width=True)

    with tabs[5]:
        fig6 = go.Figure()
        fig6.add_trace(go.Scatter(x=df_plot["strike"], y=df_plot["call_gamma"], name="Call Gamma", line=dict(color="#34d399", width=2)))
        fig6.add_trace(go.Scatter(x=df_plot["strike"], y=df_plot["call_delta"], name="Call Delta", line=dict(color="#60a5fa", width=2, dash="dot"), yaxis="y2"))
        fig6.update_layout(
            title=f"{tk_target} 행사가별 Gamma & Delta 민감도",
            yaxis=dict(title="Gamma"),
            yaxis2=dict(title="Delta", overlaying="y", side="right"),
        )
        st.plotly_chart(_add_ref_lines(fig6), use_container_width=True)

    with tabs[6]:
        df_dte = res["by_dte"].copy()
        fig7 = go.Figure()
        fig7.add_trace(go.Bar(
            x=df_dte["exp"] + " (" + df_dte["dte"].astype(str) + "D)",
            y=df_dte["net_gex"],
            marker_color=["#22c55e" if v >= 0 else "#ef4444" for v in df_dte["net_gex"]],
            name="만기별 Net GEX",
        ))
        fig7.update_layout(template="plotly_dark", height=340, title=f"{tk_target} 만기(DTE)별 Net GEX 분포", paper_bgcolor="#0e1117", plot_bgcolor="#0e1117")
        st.plotly_chart(fig7, use_container_width=True)
        df_dte_show = df_dte.copy()
        df_dte_show["Net GEX"] = df_dte_show["net_gex"].map(_fmt_num_short)
        df_dte_show["Gross GEX"] = df_dte_show["gross_gex"].map(_fmt_num_short)
        df_dte_show["Net DEX"] = df_dte_show["net_dex"].map(_fmt_usd)
        df_dte_show["총 OI"] = df_dte_show["total_oi"].map(lambda x: f"{int(x):,}")
        df_dte_show["프리미엄"] = df_dte_show["total_prem"].map(_fmt_usd)
        st.dataframe(df_dte_show[["exp", "dte", "Net GEX", "Gross GEX", "Net DEX", "총 OI", "프리미엄"]].rename(columns={"exp": "만기일", "dte": "DTE"}), hide_index=True, use_container_width=True)