import gzip
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote
import json
import os
import datetime as dt

import pandas as pd
import pytz
import requests
import streamlit as st
from streamlit_autorefresh import st_autorefresh

# ==============================
# PAGE CONFIG
# ==============================
st.set_page_config(page_title="CRUDEOILM Analytics", page_icon="🛢️", layout="wide")
st_autorefresh(interval=15_000, key="crude_refresh")

IST = pytz.timezone("Asia/Kolkata")
now = dt.datetime.now(IST)
today = now.date()

# ==============================
# TOKEN
# ==============================
DEFAULT_TOKEN = "Bearer eyJ0eXAiOiJKV1QiLCJrZXlfaWQiOiJza192MS4wIiwiYWxnIjoiSFMyNTYifQ.eyJzdWIiOiIxMDM2NjciLCJqdGkiOiI2OWQyMzJlMWNjZDUyZDRjZDQzMzc5NjYiLCJpc011bHRpQ2xpZW50IjpmYWxzZSwiaXNQbHVzUGxhbiI6ZmFsc2UsImlzRXh0ZW5kZWQiOnRydWUsImlhdCI6MTc3NTM4MzI2NSwiaXNzIjoidWRhcGktZ2F0ZXdheS1zZXJ2aWNlIiwiZXhwIjoxODA2OTYyNDAwfQ.VFRZ5NP87NM1Vyn4-bCB2FAvanu4wsueNHo_POQtPv8"

def get_token():
    tok = None
    secret_files = [os.path.join(os.path.expanduser("~"), ".streamlit", "secrets.toml"),
                    os.path.join(os.getcwd(), ".streamlit", "secrets.toml")]
    if any(os.path.exists(p) for p in secret_files):
        try:
            tok = st.secrets.get("UPSTOX_TOKEN")
        except Exception:
            pass
    tok = DEFAULT_TOKEN or tok or os.environ.get("UPSTOX_TOKEN") or st.session_state.get("tok_input")
    return tok

st.markdown("""
<style>
.card{background:#fff;padding:16px 18px;border-radius:12px;border:1px solid #e1e4e8;
      box-shadow:0 4px 10px rgba(0,0,0,.03);margin-bottom:12px;color:#111}
.big{font-size:2rem;font-weight:800}
.pos{color:#00873c;font-weight:700}.neg{color:#eb4444;font-weight:700}
.pred{padding:20px;border-radius:16px;color:#fff;text-align:center;margin-bottom:12px}
.bullish{background:linear-gradient(135deg,#11998e,#38ef7d)}
.bearish{background:linear-gradient(135deg,#cb2d3e,#ef473a)}
.neutral{background:linear-gradient(135deg,#2c3e50,#4ca1af)}
.warning{background:linear-gradient(135deg,#f12711,#f5af19)}
.entry{padding:14px 18px;border-radius:12px;margin-bottom:14px;border-left:6px solid}
.pill{display:inline-block;padding:3px 12px;border-radius:20px;font-size:.8rem;font-weight:600;
      background:#e9ecef;color:#333;margin-right:6px}
</style>
""", unsafe_allow_html=True)

# ==============================
# SIDEBAR
# ==============================
with st.sidebar:
    st.title("🛢️ CRUDEOILM Settings")
    st.markdown(f"### 🕒 IST: {now.strftime('%H:%M:%S')}")
    if not get_token():
        st.text_input("Upstox token (Bearer ...)", type="password", key="tok_input")
    buffer_pts = st.number_input("Trigger buffer (points)", 1, 200, 10, 1)
    min_gap = st.number_input("Min entry–exit gap (points)", 5, 500, 30, 5)
    delta_lo, delta_hi = st.slider("Delta band", 0.05, 0.95, (0.15, 0.75), 0.05)
    top_n = st.slider("Rows in OI tables", 5, 40, 20, 5)
    strike_window = st.slider("Strikes each side of price (for change in OI / Greeks)", 5, 40, 20, 5)
    
    st.markdown("---")
    st.markdown("**Confluence Settings**")
    min_liquidity = st.number_input("Min Option Liquidity (OI/Vol >)", 0, 10000, 500, 100)
    
    st.markdown("**OI Flow score**")
    flow_big_cr = st.number_input("Big OI value change (₹ crore)", 1.0, 500.0, 10.0, 1.0)
    flow_pct = st.slider("OI % change threshold", 2, 50, 10, 1)

TOKEN = get_token()
if not TOKEN:
    st.warning("Add your Upstox token to continue.")
    st.stop()
if not TOKEN.startswith("Bearer "):
    TOKEN = "Bearer " + TOKEN

HEADERS = {"Accept": "application/json", "Content-Type": "application/json", "Authorization": TOKEN}

def api_get(path, params):
    r = requests.get("https://api.upstox.com" + path, params=params, headers=HEADERS, timeout=15)
    try:
        return r.json()
    except Exception:
        return {"status": "error", "errors": [{"message": r.text[:300]}]}

# ==============================
# INSTRUMENT MASTER
# ==============================
def ms_to_date(ms):
    return dt.datetime.fromtimestamp(ms / 1000, IST).date()

@st.cache_data(ttl=6 * 3600)
def load_crude_instruments():
    url = "https://assets.upstox.com/market-quote/instruments/exchange/MCX.json.gz"
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    allins = json.loads(gzip.decompress(r.content))
    keep = []
    for i in allins:
        sym = str(i.get("trading_symbol", "")) + " " + str(i.get("underlying_symbol", ""))
        if "CRUDEOILM" in sym and i.get("expiry"):
            keep.append({
                "key": i.get("instrument_key"),
                "symbol": i.get("trading_symbol"),
                "type": i.get("instrument_type"),
                "expiry": ms_to_date(i["expiry"]).isoformat(),
                "underlying_key": i.get("underlying_key"),
                "lot_size": i.get("lot_size"),
                "strike": i.get("strike_price"),
            })
    return keep

try:
    ins = load_crude_instruments()
except Exception as e:
    st.error(f"Could not load MCX instrument file: {e}")
    st.stop()

today_iso = today.isoformat()
futs = sorted([i for i in ins if i["type"] == "FUT" and i["expiry"] >= today_iso], key=lambda x: x["expiry"])
if not futs:
    st.error("No active CRUDEOILM futures found.")
    st.stop()

with st.sidebar:
    st.markdown("---")
    fut_labels = {f"{f['symbol']} (exp {f['expiry']})": f for f in futs}
    fut = fut_labels[st.selectbox("Futures contract", list(fut_labels.keys()), index=0)]

    opt_expiries = sorted({i["expiry"] for i in ins
                           if i["type"] in ("CE", "PE")
                           and i["underlying_key"] == fut["key"]
                           and i["expiry"] >= today_iso})
    if opt_expiries:
        opt_expiry = st.selectbox("Option expiry", opt_expiries, index=0)
    else:
        opt_expiry = None
        st.warning("No option expiries found.")

FUT_KEY = fut["key"]

# ==============================
# PRICE & WTI CRUDE (USOIL) DATA
# ==============================
def get_price():
    j = api_get("/v2/market-quote/quotes", {"instrument_key": FUT_KEY})
    if j.get("status") == "success" and j.get("data"):
        q = next(iter(j["data"].values()))
        last = q.get("last_price") or 0
        chg = q.get("net_change") or 0
        ohlc = q.get("ohlc") or {}
        prev = round(last - chg, 2) if last else (ohlc.get("close") or 0)
        pct = (chg / prev * 100) if prev else 0
        return {"ltp": last, "chg": chg, "pct": pct, "prev": prev,
                "open": ohlc.get("open"), "high": ohlc.get("high"), "low": ohlc.get("low"),
                "oi": q.get("oi"), "volume": q.get("volume"), "src": "Upstox"}
    try:
        r = requests.post("https://scanner.tradingview.com/global/scan",
                          json={"symbols": {"tickers": ["MCX:CRUDEOILM1!"], "query": {"types": []}},
                                "columns": ["close", "change", "change_abs", "open", "high", "low"]},
                          headers={"User-Agent": "Mozilla/5.0"}, timeout=5)
        d = r.json()["data"][0]["d"]
        return {"ltp": d[0], "chg": d[2], "pct": d[1], "prev": round(d[0] - d[2], 2),
                "open": d[3], "high": d[4], "low": d[5], "oi": None, "volume": None, "src": "TradingView"}
    except Exception:
        return None

@st.cache_data(ttl=10)  # Low TTL so USOIL updates quickly
def get_macro_data():
    try:
        t = int(dt.datetime.now().timestamp()) # Cache buster
        # Switched to TVC:USOIL (WTI Crude) instead of AMEX:BNO (Brent ETF)
        r = requests.post(f"https://scanner.tradingview.com/global/scan?t={t}",
                          json={"symbols": {"tickers": ["TVC:USOIL", "FX_IDC:USDINR"], "query": {"types": []}},
                                "columns": ["close", "change", "change_abs"]},
                          headers={"User-Agent": "Mozilla/5.0"}, timeout=5)
        data = r.json()["data"]
        
        # Handle case where TVC:USOIL API glitches and returns none
        if not data or not data[0] or "d" not in data[0]:
            return None
            
        wti_d = data[0]["d"]
        inr_d = data[1]["d"]
        
        wti_pct = wti_d[1]
        inr_pct = inr_d[1]
        
        # If WTI is exactly 0.00, the US market might be closed. We still calculate, but note it.
        is_market_closed = (wti_pct == 0.0 and wti_d[2] == 0.0)
        
        # Calculate Currency-Adjusted WTI % Change
        adjusted_wti_pct = (((1 + wti_pct/100) * (1 + inr_pct/100)) - 1) * 100
        
        return {
            "wti_ltp": wti_d[0], "wti_pct": wti_pct, "wti_chg": wti_d[2],
            "inr_ltp": inr_d[0], "inr_pct": inr_pct, "inr_chg": inr_d[2],
            "adjusted_wti_pct": adjusted_wti_pct,
            "is_market_closed": is_market_closed,
            "last_update": dt.datetime.now(IST).strftime("%H:%M:%S")
        }
    except Exception:
        return None

price = get_price()
macro = get_macro_data()

# ==============================
# OPTION CHAIN
# ==============================
def _chunks(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]

def _fetch_prev_oi(key, day_iso):
    frm = (dt.date.fromisoformat(day_iso) - dt.timedelta(days=10)).isoformat()
    j = api_get(f"/v2/historical-candle/{quote(key, safe='')}/day/{day_iso}/{frm}", {})
    if j.get("status") != "success":
        return False, None
    for c in (j.get("data") or {}).get("candles") or []:
        if str(c[0])[:10] < day_iso and len(c) > 6 and c[6] is not None:
            return True, c[6]
    return True, None

def chain_from_option_api():
    j = api_get("/v2/option/chain", {"instrument_key": FUT_KEY, "expiry_date": opt_expiry})
    rows = []
    if j.get("status") == "success":
        for it in j.get("data") or []:
            c, p = it.get("call_options") or {}, it.get("put_options") or {}
            cm, pm = c.get("market_data") or {}, p.get("market_data") or {}
            cg, pg = c.get("option_greeks") or {}, p.get("option_greeks") or {}
            c_oi, p_oi = cm.get("oi") or 0, pm.get("oi") or 0
            rows.append({
                "strike": it["strike_price"],
                "call_oi": c_oi, "put_oi": p_oi,
                "call_vol": cm.get("volume") or 0, "put_vol": pm.get("volume") or 0,
                "call_chg": c_oi - (cm.get("prev_oi") or 0), "put_chg": p_oi - (pm.get("prev_oi") or 0),
                "call_ltp": cm.get("ltp"), "put_ltp": pm.get("ltp"),
                "call_delta": cg.get("delta") or 0, "call_gamma": cg.get("gamma") or 0,
                "call_theta": cg.get("theta") or 0, "call_vega": cg.get("vega") or 0, "call_iv": cg.get("iv") or 0,
                "put_delta": pg.get("delta") or 0, "put_gamma": pg.get("gamma") or 0,
                "put_theta": pg.get("theta") or 0, "put_vega": pg.get("vega") or 0, "put_iv": pg.get("iv") or 0,
                "has_chg": True,
            })
    df = pd.DataFrame(rows).sort_values("strike").reset_index(drop=True) if rows else None
    if df is not None and (df["call_oi"].sum() + df["put_oi"].sum()) == 0:
        df = None
    return df, json.dumps(j)[:500]

def chain_from_instruments(spot):
    opts = [i for i in ins if i["type"] in ("CE", "PE") and i["underlying_key"] == FUT_KEY
            and i["expiry"] == opt_expiry and i.get("strike") is not None]
    if not opts:
        return None, "No CE/PE instruments found."
    by_strike = {}
    for o in opts:
        by_strike.setdefault(float(o["strike"]), {})[o["type"]] = o["key"]
    strikes = sorted(by_strike)

    quotes = {}
    for ch in _chunks([o["key"] for o in opts], 300):
        j = api_get("/v2/market-quote/quotes", {"instrument_key": ",".join(ch)})
        if j.get("status") != "success":
            return None, "quotes error"
        for v in (j.get("data") or {}).values():
            quotes[v.get("instrument_token")] = v

    mid = min(range(len(strikes)), key=lambda i: abs(strikes[i] - spot)) if spot else len(strikes) // 2
    win = strikes[max(0, mid - strike_window): mid + strike_window + 1]
    wkeys = [k for s_ in win for k in by_strike[s_].values()]

    greeks = {}
    for ch in _chunks(wkeys, 50):
        j = api_get("/v3/market-quote/option-greek", {"instrument_key": ",".join(ch)})
        if j.get("status") == "success":
            greeks.update(j.get("data") or {})

    cache = st.session_state.setdefault("prev_oi", {})
    todo = [k for k in wkeys if (k, today_iso) not in cache]
    if todo:
        with ThreadPoolExecutor(8) as ex:
            for k, (ok, v) in zip(todo, ex.map(lambda k: _fetch_prev_oi(k, today_iso), todo)):
                if ok:
                    cache[(k, today_iso)] = v

    rows = []
    for s_ in strikes:
        ck, pk = by_strike[s_].get("CE"), by_strike[s_].get("PE")
        cq, pq = quotes.get(ck) or {}, quotes.get(pk) or {}
        cg, pg = greeks.get(ck) or {}, greeks.get(pk) or {}
        c_oi, p_oi = cq.get("oi") or 0, pq.get("oi") or 0
        c_prev, p_prev = cache.get((ck, today_iso)), cache.get((pk, today_iso))
        has = (s_ in win) and c_prev is not None and p_prev is not None
        rows.append({
            "strike": s_,
            "call_oi": c_oi, "put_oi": p_oi,
            "call_vol": cq.get("volume") or 0, "put_vol": pq.get("volume") or 0,
            "call_chg": (c_oi - c_prev) if has else 0, "put_chg": (p_oi - p_prev) if has else 0,
            "call_ltp": cq.get("last_price"), "put_ltp": pq.get("last_price"),
            "call_delta": cg.get("delta") or 0, "call_gamma": cg.get("gamma") or 0,
            "call_theta": cg.get("theta") or 0, "call_vega": cg.get("vega") or 0, "call_iv": cg.get("iv") or 0,
            "put_delta": pg.get("delta") or 0, "put_gamma": pg.get("gamma") or 0,
            "put_theta": pg.get("theta") or 0, "put_vega": pg.get("vega") or 0, "put_iv": pg.get("iv") or 0,
            "has_chg": has,
        })
    df = pd.DataFrame(rows).reset_index(drop=True)
    if (df["call_oi"].sum() + df["put_oi"].sum()) == 0:
        return None, "Quotes returned zero OI"
    return df, None

def get_chain():
    if not opt_expiry:
        return None, "No option expiry found", "none", ""
    df, raw = chain_from_option_api()
    if df is not None:
        return df, None, "Upstox option-chain API", raw
    df, err = chain_from_instruments(price["ltp"] if price else 0)
    return df, err, "Instrument master", raw

chain, chain_err, chain_src, chain_raw = get_chain()

# LIQUIDITY FILTER
if chain is not None:
    chain = chain[
        ((chain["call_oi"] > min_liquidity) | (chain["put_oi"] > min_liquidity)) &
        ((chain["call_vol"] > min_liquidity) | (chain["put_vol"] > min_liquidity))
    ].reset_index(drop=True)

# ==============================
# OI FLOW MACRO SCORE
# ==============================
def compute_crude_flow():
    keys = [f["key"] for f in futs]
    j = api_get("/v2/market-quote/quotes", {"instrument_key": ",".join(keys)})
    if j.get("status") != "success":
        return {"score": 0.0, "rows": [], "err": "API Error"}
    q = {v.get("instrument_token"): v for v in (j.get("data") or {}).values()}

    cache = st.session_state.setdefault("prev_oi", {})
    for k in keys:
        if (k, today_iso) not in cache:
            ok, v = _fetch_prev_oi(k, today_iso)
            if ok:
                cache[(k, today_iso)] = v

    big = flow_big_cr * 1e7
    rows, wsum, wtot = [], 0.0, 0.0
    for f in futs:
        v = q.get(f["key"]) or {}
        last, chg, oi = v.get("last_price") or 0, v.get("net_change") or 0, v.get("oi") or 0
        prev_oi = cache.get((f["key"], today_iso))
        if not last or prev_oi is None: continue
        lot = float(f.get("lot_size") or 10)
        prev_px = last - chg
        price_pct = chg / prev_px * 100 if prev_px else 0
        cur_val = oi * lot * last
        chg_abs = (oi - prev_oi) * lot * last
        oi_pct = (oi - prev_oi) / prev_oi * 100 if prev_oi else 0
        if cur_val < 100_000_000: continue

        score = 0.0
        if chg_abs > big and price_pct < -0.3: score = -0.9
        elif chg_abs > big and price_pct > 0.3: score = 0.9
        elif oi_pct > flow_pct * 3 and price_pct < -0.3: score = -0.6
        elif oi_pct > flow_pct and price_pct < -0.5: score = -0.4
        elif oi_pct > flow_pct and price_pct > 0.5: score = 0.4

        label = "Long Buildup" if price_pct >= 0 else "Short Buildup" if oi_pct >= 0 else "Long Unwinding" if price_pct < 0 else "Short Covering"

        weight = cur_val / 1e9
        wsum += score * weight
        wtot += weight
        rows.append({"contract": f["symbol"], "price": last, "price_chg_%": round(price_pct, 2),
                     "oi": oi, "prev_oi": prev_oi, "oi_chg_%": round(oi_pct, 2),
                     "oi_value": cur_val, "oi_value_chg": chg_abs,
                     "view": label, "score": score, "weight": round(weight, 3)})
    final = max(-1, min(1, wsum / wtot)) if wtot else 0.0
    return {"score": final, "rows": rows, "err": None}

# ==============================
# ANALYTICS & SCORES
# ==============================
def max_pain(df):
    best, low = None, float("inf")
    for s in df["strike"]:
        pain = ((s - df["strike"]).clip(lower=0) * df["call_oi"]).sum() + \
               ((df["strike"] - s).clip(lower=0) * df["put_oi"]).sum()
        if pain < low: best, low = s, pain
    return best

def compute_directional_score(chain, spot, top_n_strikes=5, itm_count=3):
    d = chain[chain["has_chg"]].copy()
    if d.empty or len(d) < 3: return None
    strikes = sorted(d["strike"].unique())
    atm = min(strikes, key=lambda s: abs(s - spot))
    atm_idx = strikes.index(atm)

    def get_row(s): return d[d["strike"] == s].iloc[0]

    d["pc_diff"] = d["put_chg"].astype(float) - d["call_chg"].astype(float)
    d["abs_diff"] = d["pc_diff"].abs()

    top = d.nlargest(top_n_strikes, "abs_diff")
    top_raw = (float((top["pc_diff"] * top["abs_diff"]).sum() / top["abs_diff"].sum()) if top["abs_diff"].sum() > 0 else 0.0)

    r = get_row(atm)
    atm_raw = float(r["put_chg"]) - float(r["call_chg"])

    up_strike = strikes[atm_idx + 1] if atm_idx + 1 < len(strikes) else None
    up_raw = (float(get_row(up_strike)["put_chg"]) - float(get_row(up_strike)["call_chg"])) if up_strike is not None else 0.0

    down_strike = strikes[atm_idx - 1] if atm_idx - 1 >= 0 else None
    down_raw = (float(get_row(down_strike)["put_chg"]) - float(get_row(down_strike)["call_chg"])) if down_strike is not None else 0.0

    itm_call_strikes = [s for s in strikes if s < spot][-itm_count:]
    itm_put_strikes  = [s for s in strikes if s > spot][:itm_count]
    itm_call_avg = (sum(float(get_row(s)["call_chg"]) for s in itm_call_strikes) / len(itm_call_strikes)) if itm_call_strikes else 0.0
    itm_put_avg  = (sum(float(get_row(s)["put_chg"]) for s in itm_put_strikes) / len(itm_put_strikes)) if itm_put_strikes else 0.0
    itm_raw = itm_put_avg - itm_call_avg

    scale = max(float(d["call_chg"].abs().max()), float(d["put_chg"].abs().max()), 1.0)
    def clip(x): return max(-1.0, min(1.0, x))

    norm = {
        "Top ΔOI diff": clip(top_raw / scale),
        "ATM": clip(atm_raw / scale),
        "1↑ OTM (call)": clip(up_raw / scale),
        "1↓ OTM (put)": clip(down_raw / scale),
        "ITM": clip(itm_raw / scale),
    }
    weights = {"Top ΔOI diff": 0.30, "ATM": 0.20, "1↑ OTM (call)": 0.15, "1↓ OTM (put)": 0.15, "ITM": 0.20}
    final = clip(sum(norm[k] * weights[k] for k in norm))

    return {
        "final": final, "pct": round(final * 100, 1),
        "atm": atm, "up_strike": up_strike, "down_strike": down_strike,
        "itm_call_strikes": itm_call_strikes, "itm_put_strikes": itm_put_strikes,
        "norm": norm, "weights": weights,
        "raw": {"Top ΔOI diff": top_raw, "ATM": atm_raw, "1↑ OTM (call)": up_raw, "1↓ OTM (put)": down_raw, "ITM": itm_raw},
        "top_table": top[["strike", "call_chg", "put_chg", "pc_diff"]].reset_index(drop=True),
        "chain": d,
    }

def oi_signal(df, spot):
    tc, tp = df["call_oi"].sum(), df["put_oi"].sum()
    pcr = tp / tc if tc else 1.0
    mp = max_pain(df)
    res = df.loc[df["call_oi"].idxmax(), "strike"]
    sup = df.loc[df["put_oi"].idxmax(), "strike"]
    hc = df[df["has_chg"]]
    net_c, net_p = hc["call_chg"].sum(), hc["put_chg"].sum()
    bull = bear = 0
    if spot > mp: bear += 1
    elif spot < mp: bull += 1
    if pcr > 1.3: bull += 1
    elif pcr < 0.7: bear += 1
    if spot > res: bull += 1
    elif spot < sup: bear += 1
    if net_p > net_c: bull += 1
    elif net_c > net_p: bear += 1
    direction = "BULLISH" if bull > bear else "BEARISH" if bear > bull else "NEUTRAL"
    return dict(pcr=pcr, max_pain=mp, resistance=res, support=sup, net_c=net_c, net_p=net_p, bull=bull, bear=bear, direction=direction)

def entry_exit(df, spot, buffer, gap, lo, hi, max_candidates=5):
    d = df[df["has_chg"]].copy()
    if d.empty: return None, None
    d["diff"] = (d["put_chg"] - d["call_chg"]).abs()
    d["type"] = d.apply(lambda r: "HIGH PUT" if r["put_chg"] > r["call_chg"] else "HIGH CALL", axis=1)
    d = d[d["diff"] > 0].sort_values("diff", ascending=False)
    if d.empty: return None, None

    def mk(row):
        strike = row["strike"]
        if row["type"] == "HIGH PUT":
            trig, sig, active = strike + buffer, "BUY", spot >= strike + buffer
            why = f"Support at {strike:g} (Put ΔOI > Call). Trigger {trig:g}"
        else:
            trig, sig, active = strike - buffer, "SELL", spot <= strike - buffer
            why = f"Resistance at {strike:g} (Call ΔOI > Put). Trigger {trig:g}"
        side = "put" if row["type"] == "HIGH PUT" else "call"
        g = {k: row[f"{side}_{k}"] for k in ("delta", "gamma", "theta", "vega", "iv")}
        return dict(strike=strike, type=row["type"], signal=sig, trigger=trig, active=active,
                    reason=why, diff=row["diff"], greeks=g, delta_ok=(g["delta"] == 0) or (lo <= abs(g["delta"]) <= hi))

    cands = d.head(max_candidates)
    pick = None
    for _, r in cands.iterrows():
        e = mk(r)
        if e["delta_ok"]:
            pick = e; break
        if pick is None: pick = e
    entry = pick
    opp = "HIGH CALL" if entry["signal"] == "BUY" else "HIGH PUT"
    o = d[d["type"] == opp]
    exit_ = None
    if not o.empty:
        ex = mk(o.iloc[0])
        if abs(ex["trigger"] - entry["trigger"]) >= gap:
            exit_ = ex
    if exit_ is None: return None, None
    return entry, exit_

# ==============================
# MASTER CONFLUENCE ENGINE
# ==============================
def compute_master_confluence(price, chain, ds, macro):
    oi_score = ds["final"] if ds else 0.0
    
    tc_vol = chain["call_vol"].sum()
    tp_vol = chain["put_vol"].sum()
    tot_vol = tc_vol + tp_vol
    vol_score = ((tp_vol - tc_vol) / tot_vol) if tot_vol > 0 else 0.0
    
    pa_score = 0.0
    if price:
        ltp = price["ltp"]
        open_px = price["open"] or ltp
        prev_px = price["prev"] or ltp
        if ltp > open_px and ltp > prev_px: pa_score = 1.0
        elif ltp < open_px and ltp < prev_px: pa_score = -1.0
        elif ltp > open_px: pa_score = 0.5
        elif ltp < open_px: pa_score = -0.5

    bno_score = 0.0
    if macro and price and not macro["is_market_closed"]: # Only calculate gap if US market has real moves
        adjusted_wti_pct = macro["adjusted_wti_pct"]
        gap = abs(price["pct"] - adjusted_wti_pct)
        if gap > 0.50:
            if adjusted_wti_pct > price["pct"]: bno_score = 1.0
            elif adjusted_wti_pct < price["pct"]: bno_score = -1.0

    final_score = (oi_score * 0.3) + (vol_score * 0.2) + (pa_score * 0.3) + (bno_score * 0.2)

    decision = "NO TRADE"
    reason = "Indicators are mixed."
    
    if oi_score > 0.2 and vol_score > 0 and pa_score > 0:
        decision = "STRONG BUY"
        reason = "Bullish OI + Bullish Volume + Bullish Price Action align perfectly."
    elif oi_score < -0.2 and vol_score < 0 and pa_score < 0:
        decision = "STRONG SELL"
        reason = "Bearish OI + Bearish Volume + Bearish Price Action align perfectly."
    elif final_score > 0.3:
        decision = "WEAK BUY"
        reason = "Overall bias is positive, but not all indicators are perfectly aligned."
    elif final_score < -0.3:
        decision = "WEAK SELL"
        reason = "Overall bias is negative, but not all indicators are perfectly aligned."
    else:
        decision = "NEUTRAL"
        reason = "Market is sideways or signals are conflicting. Wait for a clear breakout."

    return {
        "decision": decision, "reason": reason, "final_score": final_score,
        "oi_score": oi_score, "vol_score": vol_score, "pa_score": pa_score, "bno_score": bno_score
    }

# ==============================
# UI RENDER
# ==============================
st.title("🛢️ CRUDEOILM Analytics — MCX")
lot = fut.get("lot_size")
st.markdown(f'<span class="pill">Futures: {fut["symbol"]}</span><span class="pill">Exp: {fut["expiry"]}</span><span class="pill">Lot: {lot}</span>', unsafe_allow_html=True)

if not price:
    st.error("Could not fetch price.")
    st.stop()

spot = price["ltp"]

# Top Cards
c1, c2, c3, c4 = st.columns(4)
cls = "pos" if price["chg"] > 0 else "neg" if price["chg"] < 0 else ""
arrow = "▲" if price["chg"] > 0 else "▼" if price["chg"] < 0 else "—"
with c1:
    st.markdown(f"""<div class="card"><div style="color:#666">CRUDEOILM (Fut)</div>
      <div class="big">{spot:,.2f}</div>
      <div class="{cls}">{arrow} {price['chg']:+,.2f} ({price['pct']:+.2f}%)</div></div>""", unsafe_allow_html=True)
with c2:
    st.markdown(f"""<div class="card"><div style="color:#666">Day Range</div>
      <div style="font-size:1.1rem">O {price['open'] or 0:,.2f}<br>H {price['high'] or 0:,.2f}<br>L {price['low'] or 0:,.2f}</div></div>""", unsafe_allow_html=True)
with c3:
    st.markdown(f"""<div class="card"><div style="color:#666">Futures OI / Volume</div>
      <div style="font-size:1.1rem">OI {price['oi'] if price['oi'] is not None else '—'}<br>
      Vol {price['volume'] if price['volume'] is not None else '—'}</div></div>""", unsafe_allow_html=True)
with c4:
    if macro:
        b_cls = "pos" if macro["wti_chg"] > 0 else "neg" if macro["wti_chg"] < 0 else ""
        i_cls = "pos" if macro["inr_chg"] > 0 else "neg" if macro["inr_chg"] < 0 else ""
        st.markdown(f"""<div class="card"><div style="color:#666">US WTI & USD/INR <span style="font-size:0.7rem;float:right">Upd: {macro['last_update']}</span></div>
          <div style="font-size:1.1rem;display:flex;justify-content:space-between">
            <span>WTI: <b class="{b_cls}">{macro['wti_pct']:+.2f}%</b></span>
            <span>INR: <b class="{i_cls}">{macro['inr_pct']:+.2f}%</b></span>
          </div>
          <div style="font-size:.8rem;color:#888;margin-top:4px">Adj. Expected: {macro['adjusted_wti_pct']:+.2f}%</div>
          </div>""", unsafe_allow_html=True)
    else:
        st.markdown(f"""<div class="card"><div style="color:#666">Macro Data</div><div>Unavailable</div></div>""", unsafe_allow_html=True)

# Currency Adjusted WTI Gap Alert
if macro and price:
    adjusted_wti_pct = macro["adjusted_wti_pct"]
    gap_val = abs(price["pct"] - adjusted_wti_pct)
    
    # Calculate exact points gap
    expected_price = price["prev"] * (1 + adjusted_wti_pct / 100)
    gap_points = expected_price - spot
    
    st.markdown("---")
    
    if macro["is_market_closed"]:
         st.info(f"⚪ **US MARKET CLOSED / FLAT**: WTI is showing 0.00% change. Gap alerts are paused until the US session resumes.")
    elif gap_val > 0.50:
        if adjusted_wti_pct < price["pct"]:
            st.error(f"🚨 **GAP ALERT (Drop Expected)**: WTI is **{macro['wti_pct']:.2f}%**, Adjusted for INR is **{adjusted_wti_pct:.2f}%**. MCX is at **{price['pct']:.2f}%**. Gap is **{gap_val:.2f}%**.\n\n"
                     f"👉 **Trade Plan:** Expect MCX to drop to fill the gap.\n"
                     f"🎯 **Target Price:** ~**{expected_price:,.2f}** (Drop of ~{abs(gap_points):.0f} points).")
        else:
            st.success(f"🚨 **GAP ALERT (Rise Expected)**: WTI is **{macro['wti_pct']:.2f}%**, Adjusted for INR is **{adjusted_wti_pct:.2f}%**. MCX is at **{price['pct']:.2f}%**. Gap is **{gap_val:.2f}%**.\n\n"
                     f"👉 **Trade Plan:** Expect MCX to rise to fill the gap.\n"
                     f"🎯 **Target Price:** ~**{expected_price:,.2f}** (Rise of ~{abs(gap_points):.0f} points).")
    else:
        st.info(f"✅ WTI and MCX are in sync (Gap: {gap_val:.2f}%). No catch-up trade available.")
    st.markdown("---")

if chain is None or chain.empty:
    st.error("Could not build the option chain (or Liquidity Filter removed all strikes).")
    with st.expander("Debug details"):
        st.write("Fut Key:", FUT_KEY, "| Expiry:", opt_expiry)
        st.code(chain_raw or "—")
        st.code(chain_err or "—")
    st.stop()

sig = oi_signal(chain, spot)

# Compute Scores
ds = compute_directional_score(chain, spot)
master = compute_master_confluence(price, chain, ds, macro)

# ==============================
# MASTER CONFLUENCE DASHBOARD
# ==============================
st.subheader("🔥 Master Confluence Dashboard")
st.markdown(f"**{master['reason']}**")

mc1, mc2, mc3, mc4, mc5 = st.columns(5)
mc1.metric("OI Direction", f"{master['oi_score']:+.2f}", "Bullish" if master['oi_score']>0 else "Bearish", delta_color="normal")
mc2.metric("Volume Flow", f"{master['vol_score']:+.2f}", "Put dominant" if master['vol_score']>0 else "Call dominant", delta_color="normal")
mc3.metric("Price Action", f"{master['pa_score']:+.2f}", "Bullish" if master['pa_score']>0 else "Bearish", delta_color="normal")
mc4.metric("WTI Correlation", f"{master['bno_score']:+.2f}", "Catch-up" if master['bno_score']!=0 else "Aligned", delta_color="normal")
mc5.metric("Confluence Score", f"{master['final_score']:+.2f}")

if master["decision"] in ("STRONG BUY", "STRONG SELL"):
    st.success(f"✅ **{master['decision']}** — All indicators align perfectly. High probability setup.")
elif master["decision"] in ("WEAK BUY", "WEAK SELL"):
    st.warning(f"⚠️ **{master['decision']}** — Bias exists, but not all indicators align. Trade with strict stop-loss.")
else:
    st.info("⚪ **NO TRADE** — Indicators are conflicting. The market might be trapping OI writers. Wait for alignment.")

# ==============================
# OI CHARTS & TABLES
# ==============================
st.subheader("Open Interest by Strike")
st.bar_chart(chain.set_index("strike")[["call_oi", "put_oi"]])
st.subheader("Change in OI by Strike")
st.bar_chart(chain[chain["has_chg"]].set_index("strike")[["call_chg", "put_chg"]])

def hl_top5(row):
    return (["background-color:#ffd700;font-weight:bold;color:#000"] * len(row)) if row.name < 5 else [""] * len(row)

oi_tbl = chain[["strike", "call_oi", "put_oi"]].copy()
oi_tbl["HIGH OI"] = oi_tbl.apply(lambda r: "HIGH PUT" if r.put_oi > r.call_oi else "HIGH CALL", axis=1)
oi_tbl["OI Difference"] = (oi_tbl["put_oi"] - oi_tbl["call_oi"]).abs()
st.subheader("Open Interest Data (top by difference)")
st.dataframe(oi_tbl.sort_values("OI Difference", ascending=False).head(top_n).reset_index(drop=True).style.apply(hl_top5, axis=1), use_container_width=True)

chg_tbl = chain.loc[chain["has_chg"], ["strike", "call_chg", "put_chg"]].copy()
chg_tbl["HIGH OI"] = chg_tbl.apply(lambda r: "HIGH PUT" if r.put_chg > r.call_chg else "HIGH CALL", axis=1)
chg_tbl["OI Difference"] = (chg_tbl["put_chg"] - chg_tbl["call_chg"]).abs()
st.subheader("Change in OI (top by difference)")
st.dataframe(chg_tbl.sort_values("OI Difference", ascending=False).head(top_n).reset_index(drop=True).style.apply(hl_top5, axis=1), use_container_width=True)

# ==============================
# DETAILED SCORE BREAKDOWN
# ==============================
st.subheader("🎯 Directional OI Score Breakdown")
if ds:
    st.markdown(f"**OI Score:** {ds['final']:+.2f} (ATM {ds['atm']:g} | 1↑ OTM {ds['up_strike']} | 1↓ OTM {ds['down_strike']})")
    
    col_a, col_b = st.columns([3, 2])
    with col_a:
        breakdown = pd.DataFrame([
            {"Component": k, "Raw ΔPut−ΔCall": round(ds["raw"][k], 0), 
             "Normalized": round(ds["norm"][k], 2), "Weight": ds["weights"][k]}
            for k in ds["norm"]
        ])
        st.dataframe(breakdown, use_container_width=True)
    with col_b:
        st.markdown("""
        **How to read:**
        - **Put ΔOI ↑** → Bullish
        - **Call ΔOI ↑** → Bearish
        - **ITM Call ΔOI ↑** → Bearish
        - **ITM Put ΔOI ↑** → Bullish
        """)

# ==============================
# FUTURES OI FLOW
# ==============================
flow = compute_crude_flow()
if flow["rows"]:
    st.subheader(f"CRUDEOILM Futures OI Flow — Macro Score: {flow['score']:.2f}")
    st.markdown("**Weighted Macro Score (-1 to +1)**: Based on OI value change and price change across active CRUDEOILM futures.")
    bias = "Bullish" if flow["score"] > 0 else ("Bearish" if flow["score"] < 0 else "Sideways")
    st.write(f"Market Bias: {bias}")
    st.dataframe(pd.DataFrame(flow["rows"]), use_container_width=True)
else:
    st.info("OI flow not available.")

# ==============================
# ENTRY / EXIT & OPTION CHAIN
# ==============================
st.subheader("📊 Entry/Exit Signal (OI Change)")
entry, exit_ = entry_exit(chain, spot, buffer_pts, min_gap, delta_lo, delta_hi)
if entry:
    st.markdown(f"**ENTRY ({entry['signal']}):** Strike {entry['strike']:g} | Trigger {entry['trigger']:.2f} | {entry['reason']}")
    st.markdown(f"**EXIT ({exit_['signal']}):** Strike {exit_['strike']:g} | Trigger {exit_['trigger']:.2f} | {exit_['reason']}")
else:
    st.info("No clear entry/exit signal from OI change.")

st.subheader("Option Chain + Volume (Nearest to Price)")
near = chain.iloc[(chain["strike"] - spot).abs().argsort()[:15]].sort_values("strike")
st.dataframe(near[["strike", "call_ltp", "call_oi", "call_vol", "call_chg", "put_ltp", "put_oi", "put_vol", "put_chg"]].reset_index(drop=True), use_container_width=True)

st.caption(f"Last refresh: {now.strftime('%H:%M:%S IST')} · Auto-refresh every 15s")
