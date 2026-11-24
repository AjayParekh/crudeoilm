import gzip
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote
import json
import os
import datetime as dt
import smtplib
from email.message import EmailMessage
import math

import pandas as pd
import pytz
import requests
import streamlit as st
from streamlit_autorefresh import st_autorefresh

# ==============================
# PAGE CONFIG
# ==============================
st.set_page_config(page_title="CRUDEOILM Ecosystem", page_icon="🛢️", layout="wide")
st_autorefresh(interval=15_000, key="crude_refresh")

IST = pytz.timezone("Asia/Kolkata")
now = dt.datetime.now(IST)
today = now.date()

# ==============================
# CSS STYLES (Nifty Ecosystem Style)
# ==============================
st.markdown("""
<style>
.card { background: #fff; padding: 20px; border-radius: 12px; border: 1px solid #e1e4e8; box-shadow: 0 4px 10px rgba(0,0,0,0.03); margin-bottom: 15px; color: #111; }
.big-price { font-size: 2.5rem; font-weight: 800; margin: 0; }
.metric-label { font-size: 0.9rem; color: #666; font-weight: 600; text-transform: uppercase; }
.pos { color: #00873c; font-weight: 600; font-size: 1rem;} 
.neg { color: #eb4444; font-weight: 600; font-size: 1rem;}
.decision-box { padding: 30px; border-radius: 15px; text-align: center; color: white; margin-bottom: 20px; }
.buy { background: linear-gradient(135deg, #11998e, #38ef7d); }
.sell { background: linear-gradient(135deg, #cb2d3e, #ef473a); }
.wait { background: linear-gradient(135deg, #f12711, #f5af19); }
.neutral { background: linear-gradient(135deg, #2c3e50, #4ca1af); }
.alert-box { padding: 15px; border-radius: 10px; margin-bottom: 15px; font-weight: bold; }
.alert-trap { background-color: #f8d7da; color: #721c24; border-left: 5px solid #dc3545; }
.alert-safe { background-color: #d4edda; color: #155724; border-left: 5px solid #28a745; }
.alert-info { background-color: #d1ecf1; color: #0c5460; border-left: 5px solid #17a2b8; }
.section-header { font-size: 1.2rem; font-weight: bold; margin-bottom: 10px; border-bottom: 2px solid #eee; padding-bottom: 5px; }
</style>
""", unsafe_allow_html=True)

# ==============================
# TOKEN & EMAIL ENGINE
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

def send_email_alert(subject, body):
    try:
        sender = st.secrets.get("EMAIL_SENDER")
        password = st.secrets.get("EMAIL_PASSWORD")
        smtp_server = st.secrets.get("SMTP_SERVER", "smtp.gmail.com")
        smtp_port = st.secrets.get("SMTP_PORT", 465)
        
        receivers_raw = st.secrets.get("EMAIL_RECEIVER")
        if not receivers_raw: return False, "No EMAIL_RECEIVER found."
        if isinstance(receivers_raw, str):
            receivers = [email.strip() for email in receivers_raw.split(",") if email.strip()]
        else:
            receivers = [str(email).strip() for email in receivers_raw]

        msg = EmailMessage()
        msg.set_content(body)
        msg['Subject'] = subject
        msg['From'] = sender
        msg['To'] = ", ".join(receivers)

        with smtplib.SMTP_SSL(smtp_server, smtp_port) as smtp:
            smtp.login(sender, password)
            smtp.send_message(msg)
        return True, "Success"
    except Exception as e:
        return False, str(e)

# ==============================
# SIDEBAR
# ==============================
with st.sidebar:
    st.title("🛢️ CRUDEOILM Settings")
    st.markdown(f"### 🕒 IST: {now.strftime('%H:%M:%S')}")
    
    st.markdown("---")
    if st.button("📧 Send Test Email"):
        with st.spinner("Sending..."):
            ok, msg = send_email_alert("Test Email from CRUDEOILM App", "Test email.")
            if ok: st.success("Test email sent!")
            else: st.error(f"Failed: {msg}")
    st.markdown("---")

    if not get_token():
        st.text_input("Upstox token (Bearer ...)", type="password", key="tok_input")
    
    buffer_pts = st.number_input("Trigger buffer (points)", 1, 200, 10, 1)
    min_gap = st.number_input("Min entry–exit gap (points)", 5, 500, 30, 5)
    delta_lo, delta_hi = st.slider("Delta band", 0.05, 0.95, (0.15, 0.75), 0.05)
    top_n = st.slider("Rows in OI tables", 5, 40, 20, 5)
    strike_window = st.slider("Strikes each side (OI/Greeks)", 5, 40, 20, 5)
    
    st.markdown("---")
    st.markdown("**Confluence Settings**")
    min_liquidity = st.number_input("Min Option Liquidity (OI/Vol >)", 0, 10000, 500, 100)
    
    st.markdown("**OI Flow**")
    flow_big_cr = st.number_input("Big OI value change (₹ crore)", 1.0, 500.0, 10.0, 1.0)
    flow_pct = st.slider("OI % change threshold", 2, 50, 10, 1)

TOKEN = get_token()
if not TOKEN: st.stop()
if not TOKEN.startswith("Bearer "): TOKEN = "Bearer " + TOKEN

HEADERS = {"Accept": "application/json", "Content-Type": "application/json", "Authorization": TOKEN}

def api_get(path, params):
    r = requests.get("https://api.upstox.com" + path, params=params, headers=HEADERS, timeout=15)
    try: return r.json()
    except Exception: return {"status": "error"}

# ==============================
# INSTRUMENT MASTERS
# ==============================
def ms_to_date(ms): return dt.datetime.fromtimestamp(ms / 1000, IST).date()

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
                "key": i.get("instrument_key"), "symbol": i.get("trading_symbol"),
                "type": i.get("instrument_type"), "expiry": ms_to_date(i["expiry"]).isoformat(),
                "underlying_key": i.get("underlying_key"), "lot_size": i.get("lot_size"), "strike": i.get("strike_price"),
            })
    return keep

try: ins = load_crude_instruments()
except Exception as e: st.error(f"Instrument Error: {e}"); st.stop()

today_iso = today.isoformat()
futs = sorted([i for i in ins if i["type"] == "FUT" and i["expiry"] >= today_iso], key=lambda x: x["expiry"])
valid_futs = [f for f in futs if any(i["type"] in ("CE", "PE") and i["underlying_key"] == f["key"] for i in ins)]
if valid_futs: futs = valid_futs

with st.sidebar:
    st.markdown("---")
    fut_labels = {f"{f['symbol']} (exp {f['expiry']})": f for f in futs}
    fut = fut_labels[st.selectbox("Futures contract", list(fut_labels.keys()), index=0)]

    opt_expiries = sorted({i["expiry"] for i in ins if i["type"] in ("CE", "PE") and i["underlying_key"] == fut["key"] and i["expiry"] >= today_iso})
    opt_expiry = st.selectbox("Option expiry", opt_expiries, index=0) if opt_expiries else None

FUT_KEY = fut["key"]

# ==============================
# DATA FETCHING
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
        return {"ltp": last, "chg": chg, "pct": pct, "prev": prev, "open": ohlc.get("open"), "high": ohlc.get("high"), "low": ohlc.get("low"), "oi": q.get("oi") or 0, "volume": q.get("volume") or 0}
    return None

@st.cache_data(ttl=10)
def get_macro_data():
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        r_wti = requests.get("https://query1.finance.yahoo.com/v8/finance/chart/CL=F", headers=headers, timeout=5)
        wti_meta = r_wti.json()['chart']['result'][0]['meta']
        r_inr = requests.get("https://query1.finance.yahoo.com/v8/finance/chart/USDINR=X", headers=headers, timeout=5)
        inr_meta = r_inr.json()['chart']['result'][0]['meta']
    except Exception: return None
    try:
        wti_ltp = wti_meta.get('regularMarketPrice', 0.0)
        wti_prev = wti_meta.get('chartPreviousClose', wti_ltp)
        inr_ltp = inr_meta.get('regularMarketPrice', 1.0)
        inr_prev = inr_meta.get('chartPreviousClose', inr_ltp)
        wti_chg = wti_ltp - wti_prev
        wti_pct = (wti_chg / wti_prev * 100) if wti_prev else 0
        inr_chg = inr_ltp - inr_prev
        inr_pct = (inr_chg / inr_prev * 100) if inr_prev else 0
        adjusted_wti_pct = (((1 + wti_pct/100) * (1 + inr_pct/100)) - 1) * 100
        is_closed = (wti_pct == 0.0 and wti_chg == 0.0)
        return {"wti_ltp": wti_ltp, "wti_pct": wti_pct, "wti_chg": wti_chg, "inr_ltp": inr_ltp, "inr_pct": inr_pct, "inr_chg": inr_chg, "adjusted_wti_pct": adjusted_wti_pct, "is_market_closed": is_closed, "last_update": dt.datetime.now(IST).strftime("%H:%M:%S")}
    except Exception: return None

price = get_price()
macro = get_macro_data()

# ==============================
# OPTION CHAIN FULL LOGIC
# ==============================
def _chunks(lst, n):
    for i in range(0, len(lst), n): yield lst[i:i + n]

def _fetch_prev_oi(key, day_iso):
    frm = (dt.date.fromisoformat(day_iso) - dt.timedelta(days=10)).isoformat()
    j = api_get(f"/v2/historical-candle/{quote(key, safe='')}/day/{day_iso}/{frm}", {})
    if j.get("status") != "success": return False, None
    for c in (j.get("data") or {}).get("candles") or []:
        if str(c[0])[:10] < day_iso and len(c) > 6 and c[6] is not None: return True, c[6]
    return True, None

def chain_from_option_api():
    j = api_get("/v2/option/chain", {"instrument_key": FUT_KEY, "expiry_date": opt_expiry})
    rows = []
    if j.get("status") == "success":
        for it in j.get("data") or []:
            c, p = it.get("call_options") or {}, it.get("put_options") or {}
            cm, pm = c.get("market_data") or {}, p.get("market_data") or {}
            cg, pg = c.get("option_greeks") or {}, p.get("option_greeks") or {}
            rows.append({
                "strike": it["strike_price"], 
                "ce_key": c.get("instrument_key"), "pe_key": p.get("instrument_key"),
                "call_oi": cm.get("oi") or 0, "put_oi": pm.get("oi") or 0,
                "call_vol": cm.get("volume") or 0, "put_vol": pm.get("volume") or 0,
                "call_chg": (cm.get("oi") or 0) - (cm.get("prev_oi") or 0), "put_chg": (pm.get("oi") or 0) - (pm.get("prev_oi") or 0),
                "call_ltp": cm.get("ltp"), "put_ltp": pm.get("ltp"),
                "call_delta": cg.get("delta") or 0, "call_gamma": cg.get("gamma") or 0, "call_theta": cg.get("theta") or 0, "call_vega": cg.get("vega") or 0, "call_iv": cg.get("iv") or 0,
                "put_delta": pg.get("delta") or 0, "put_gamma": pg.get("gamma") or 0, "put_theta": pg.get("theta") or 0, "put_vega": pg.get("vega") or 0, "put_iv": pg.get("iv") or 0,
                "has_chg": True,
            })
    df = pd.DataFrame(rows).sort_values("strike").reset_index(drop=True) if rows else None
    return df, json.dumps(j)[:500]

def chain_from_instruments(spot):
    opts = [i for i in ins if i["type"] in ("CE", "PE") and i["underlying_key"] == FUT_KEY and i["expiry"] == opt_expiry and i.get("strike") is not None]
    if not opts: return None, "No CE/PE instruments found."
    by_strike = {}
    for o in opts: by_strike.setdefault(float(o["strike"]), {})[o["type"]] = o["key"]
    strikes = sorted(by_strike)

    quotes = {}
    for ch in _chunks([o["key"] for o in opts], 300):
        j = api_get("/v2/market-quote/quotes", {"instrument_key": ",".join(ch)})
        if j.get("status") != "success": return None, "quotes error"
        for v in (j.get("data") or {}).values(): quotes[v.get("instrument_token")] = v

    mid = min(range(len(strikes)), key=lambda i: abs(strikes[i] - spot)) if spot else len(strikes) // 2
    win = strikes[max(0, mid - strike_window): mid + strike_window + 1]
    wkeys = [k for s_ in win for k in by_strike[s_].values()]

    greeks = {}
    for ch in _chunks(wkeys, 50):
        j = api_get("/v3/market-quote/option-greek", {"instrument_key": ",".join(ch)})
        if j.get("status") == "success": greeks.update(j.get("data") or {})

    cache = st.session_state.setdefault("prev_oi", {})
    todo = [k for k in wkeys if (k, today_iso) not in cache]
    if todo:
        with ThreadPoolExecutor(8) as ex:
            for k, (ok, v) in zip(todo, ex.map(lambda k: _fetch_prev_oi(k, today_iso), todo)):
                if ok: cache[(k, today_iso)] = v

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
            "ce_key": ck, "pe_key": pk,
            "call_oi": c_oi, "put_oi": p_oi,
            "call_vol": cq.get("volume") or 0, "put_vol": pq.get("volume") or 0,
            "call_chg": (c_oi - c_prev) if has else 0, "put_chg": (p_oi - p_prev) if has else 0,
            "call_ltp": cq.get("last_price"), "put_ltp": pq.get("last_price"),
            "call_delta": cg.get("delta") or 0, "call_gamma": cg.get("gamma") or 0, "call_theta": cg.get("theta") or 0, "call_vega": cg.get("vega") or 0, "call_iv": cg.get("iv") or 0,
            "put_delta": pg.get("delta") or 0, "put_gamma": pg.get("gamma") or 0, "put_theta": pg.get("theta") or 0, "put_vega": pg.get("vega") or 0, "put_iv": pg.get("iv") or 0,
            "has_chg": has,
        })
    df = pd.DataFrame(rows).reset_index(drop=True)
    return df, None

def get_chain():
    if not opt_expiry: return None, "No option expiry found", "none", ""
    df, raw = chain_from_option_api()
    if df is not None: return df, None, "Upstox option-chain API", raw
    df, err = chain_from_instruments(price["ltp"] if price else 0)
    return df, err, "Instrument master", raw

chain, chain_err, chain_src, chain_raw = get_chain()

if chain is not None:
    chain = chain[((chain["call_oi"] > min_liquidity) | (chain["put_oi"] > min_liquidity)) & ((chain["call_vol"] > min_liquidity) | (chain["put_vol"] > min_liquidity))].reset_index(drop=True)

# ==============================
# MATH & SCORING ENGINES
# ==============================
def compute_crude_flow():
    keys = [f["key"] for f in futs]
    j = api_get("/v2/market-quote/quotes", {"instrument_key": ",".join(keys)})
    if j.get("status") != "success": return {"score": 0.0, "rows": [], "err": "API Error"}
    q = {v.get("instrument_token"): v for v in (j.get("data") or {}).values()}
    cache = st.session_state.setdefault("prev_oi", {})
    for k in keys:
        if (k, today_iso) not in cache:
            ok, v = _fetch_prev_oi(k, today_iso)
            if ok: cache[(k, today_iso)] = v

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
        rows.append({"contract": f["symbol"], "price": last, "price_chg_%": round(price_pct, 2), "oi": oi, "prev_oi": prev_oi, "oi_chg_%": round(oi_pct, 2), "oi_value": cur_val, "oi_value_chg": chg_abs, "view": label, "score": score, "weight": round(weight, 3)})
    final = max(-1, min(1, wsum / wtot)) if wtot else 0.0
    return {"score": final, "rows": rows, "err": None}

def compute_directional_score(chain, spot, top_n_strikes=5, itm_count=3):
    if chain is None or chain.empty: return None
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

    norm = {"Top ΔOI diff": clip(top_raw / scale), "ATM": clip(atm_raw / scale), "1↑ OTM (call)": clip(up_raw / scale), "1↓ OTM (put)": clip(down_raw / scale), "ITM": clip(itm_raw / scale)}
    weights = {"Top ΔOI diff": 0.30, "ATM": 0.20, "1↑ OTM (call)": 0.15, "1↓ OTM (put)": 0.15, "ITM": 0.20}
    final = clip(sum(norm[k] * weights[k] for k in norm))

    return {"final": final, "pct": round(final * 100, 1), "atm": atm, "up_strike": up_strike, "down_strike": down_strike, "itm_call_strikes": itm_call_strikes, "itm_put_strikes": itm_put_strikes, "norm": norm, "weights": weights, "raw": {"Top ΔOI diff": top_raw, "ATM": atm_raw, "1↑ OTM (call)": up_raw, "1↓ OTM (put)": down_raw, "ITM": itm_raw}, "top_table": top[["strike", "call_chg", "put_chg", "pc_diff"]].reset_index(drop=True), "chain": d}

def compute_master_confluence(price, chain, ds, macro):
    if chain is None: return None
    oi_score = ds["final"] if ds else 0.0
    tc_vol = chain["call_vol"].sum() if not chain.empty else 0
    tp_vol = chain["put_vol"].sum() if not chain.empty else 0
    tot_vol = tc_vol + tp_vol
    vol_score = ((tp_vol - tc_vol) / tot_vol) if tot_vol > 0 else 0.0
    
    pa_score = 0.0
    if price:
        ltp, open_px, prev_px = price["ltp"], price["open"] or price["ltp"], price["prev"] or price["ltp"]
        if ltp > open_px and ltp > prev_px: pa_score = 1.0
        elif ltp < open_px and ltp < prev_px: pa_score = -1.0
        elif ltp > open_px: pa_score = 0.5
        elif ltp < open_px: pa_score = -0.5

    wti_score = 0.0
    if macro and price and not macro["is_market_closed"]:
        adjusted = macro["adjusted_wti_pct"]
        gap = abs(price["pct"] - adjusted)
        if gap > 1.00:
            if adjusted > price["pct"]: wti_score = 1.0
            elif adjusted < price["pct"]: wti_score = -1.0

    final_score = (oi_score * 0.3) + (vol_score * 0.2) + (pa_score * 0.3) + (wti_score * 0.2)

    # UPDATED LOGIC: NIFTY STYLE THRESHOLD
    decision, reason = "NO TRADE", "Indicators mixed."
    if final_score > 0.3:
        decision, reason = "CONFIRM BUY", "Overall bias is strongly positive."
    elif final_score < -0.3:
        decision, reason = "CONFIRM SELL", "Overall bias is strongly negative."

    return {"decision": decision, "reason": reason, "final_score": final_score, "oi_score": oi_score, "vol_score": vol_score, "pa_score": pa_score, "wti_score": wti_score}

spot = price["ltp"] if price else 0
ds = compute_directional_score(chain, spot) if chain is not None else None
master = compute_master_confluence(price, chain, ds, macro)
flow = compute_crude_flow()

# ==============================
# GREEKS CALCULATOR FALLBACK
# ==============================
def calculate_greeks(spot, strike, t, r, vol, option_type="CE"):
    if t <= 0 or vol <= 0: return 0, 0, 0, 0, 0
    def norm_cdf(x): return (1.0 + math.erf(x / math.sqrt(2.0))) / 2.0
    def norm_pdf(x): return math.exp(-x**2 / 2.0) / math.sqrt(2.0 * math.pi)
    d1 = (math.log(spot / strike) + (r + 0.5 * vol**2) * t) / (vol * math.sqrt(t))
    d2 = d1 - vol * math.sqrt(t)
    if option_type == "CE":
        delta = norm_cdf(d1)
        theta = (- (spot * norm_pdf(d1) * vol) / (2 * math.sqrt(t)) - r * strike * math.exp(-r * t) * norm_cdf(d2)) / 365
    else:
        delta = norm_cdf(d1) - 1
        theta = (- (spot * norm_pdf(d1) * vol) / (2 * math.sqrt(t)) + r * strike * math.exp(-r * t) * norm_cdf(-d2)) / 365
    gamma = norm_pdf(d1) / (spot * vol * math.sqrt(t))
    vega = (spot * norm_pdf(d1) * math.sqrt(t)) / 100
    return delta, gamma, theta, vega, vol * 100

# ==============================
# UI RENDER
# ==============================
st.title("🛢️ CRUDEOILM Ecosystem — MCX")

# Top Cards
def render_card(label, value, chg, pct):
    cls = "pos" if chg >= 0 else "neg"
    arrow = "▲" if chg > 0 else "▼" if chg < 0 else "—"
    val_str = f"{value:,.2f}"
    chg_str = f"{arrow} {chg:+,.2f} ({pct:+.2f}%)"
    return f'<div class="card"><div class="metric-label">{label}</div><div class="big-price">{val_str}</div><div class="{cls}">{chg_str}</div></div>'

c1, c2, c3, c4 = st.columns(4)
with c1: st.markdown(render_card(f"CRUDEOILM ({fut['symbol']})", spot, price['chg'], price['pct']), unsafe_allow_html=True)
with c2: 
    st.markdown(f"""<div class="card"><div class="metric-label">CRUDEOILM FUTURES OI / VOLUME</div>
      <div class="big-price">{price['oi']:,.0f}</div>
      <div class="pos">Vol: {price['volume']:,.0f}</div></div>""", unsafe_allow_html=True)
with c3: 
    if macro: st.markdown(render_card("WTI Crude", macro['wti_ltp'], macro['wti_chg'], macro['wti_pct']), unsafe_allow_html=True)
    else: st.markdown('<div class="card">WTI Data Unavailable</div>', unsafe_allow_html=True)
with c4:
    if macro: st.markdown(render_card("USD/INR", macro['inr_ltp'], macro['inr_chg'], macro['inr_pct']), unsafe_allow_html=True)
    else: st.markdown('<div class="card">INR Data Unavailable</div>', unsafe_allow_html=True)

st.markdown("---")

# External Alert Logic
alert_status = "IN_SYNC"
gap_val = 0
if macro and price and master and not macro["is_market_closed"]:
    adjusted = macro["adjusted_wti_pct"]
    gap_val = abs(price["pct"] - adjusted)
    expected_price = price["prev"] * (1 + adjusted / 100)
    gap_points = expected_price - spot

    if gap_val > 1.00:
        if adjusted > price["pct"]:
            if master["pa_score"] < 0 or master["final_score"] < -0.1: alert_status = "TRAP_RISE"
            else: alert_status = "SAFE_RISE"
        else:
            if master["pa_score"] > 0 or master["final_score"] > 0.1: alert_status = "TRAP_DROP"
            else: alert_status = "SAFE_DROP"

if alert_status == "TRAP_RISE" or alert_status == "TRAP_DROP":
    st.markdown(f'<div class="alert-box alert-trap">🛑 <b>TRAP ALERT ({alert_status.replace("_", " ")})</b><br>WTI implies MCX should move <b>{gap_val:.2f}%</b>, but Internal Trend is diverging. <b>DO NOT TRADE THE GAP.</b></div>', unsafe_allow_html=True)
elif alert_status == "SAFE_RISE":
    st.markdown(f'<div class="alert-box alert-safe">🚨 <b>SAFE GAP ALERT (Rise Expected)</b><br>WTI implies MCX should rise <b>{gap_val:.2f}%</b>. Target: {expected_price:,.2f} (Rise ~{abs(gap_points):.0f} pts).</div>', unsafe_allow_html=True)
elif alert_status == "SAFE_DROP":
    st.markdown(f'<div class="alert-box alert-trap">🚨 <b>SAFE GAP ALERT (Drop Expected)</b><br>WTI implies MCX should drop <b>{gap_val:.2f}%</b>. Target: {expected_price:,.2f} (Drop ~{abs(gap_points):.0f} pts).</div>', unsafe_allow_html=True)
else:
    st.markdown(f'<div class="alert-box alert-info">⚪ <b>EXTERNAL MACRO IN SYNC</b> — Gap is {gap_val:.2f}%.</div>', unsafe_allow_html=True)


# Large Decision Box
if master:
    action = master.get("decision", "NO TRADE")
    score_val = master.get("final_score", 0.0)
else:
    action = "NO TRADE"
    score_val = 0.0

direction_text = "BULLISH" if "BUY" in action else "BEARISH" if "SELL" in action else "SIDEWAYS"

css_class = "neutral"
if "BUY" in action: css_class = "buy"
elif "SELL" in action: css_class = "sell"
elif action == "NO TRADE": css_class = "neutral"

st.markdown(f'''
<div class="decision-box {css_class}">
    <h1 style="margin:0; font-size: 3rem;">{action.replace("_", " ")}</h1>
    <p style="font-size: 1.2rem; margin-top: 10px;">
        Direction: <b>{direction_text}</b> | Confluence Score: <b>{score_val:+.2f}</b>
    </p>
</div>
''', unsafe_allow_html=True)


# Option Greeks (ATM Window) - FIXED WITH BLACK-SCHOLES FALLBACK
st.markdown("### 📊 Option Greeks (ATM Window)")
if chain is not None and not chain.empty:
    atm_strike = ds["atm"] if ds else 0
    near_strikes = chain.iloc[(chain["strike"] - spot).abs().argsort()[:5]].sort_values("strike").copy()
    
    # Force fetch Greeks to ensure no zeros
    greek_keys = []
    for _, row in near_strikes.iterrows():
        if row.get("ce_key"): greek_keys.append(row["ce_key"])
        if row.get("pe_key"): greek_keys.append(row["pe_key"])
        
    if greek_keys:
        gk_res = api_get("/v3/market-quote/option-greek", {"instrument_key": ",".join(greek_keys)})
        if gk_res.get("status") == "success":
            gk_data = gk_res.get("data") or {}
            for idx, row in near_strikes.iterrows():
                ck, pk = row.get("ce_key"), row.get("pe_key")
                if ck in gk_data:
                    near_strikes.at[idx, "call_delta"] = gk_data[ck].get("delta", 0) or 0
                    near_strikes.at[idx, "call_theta"] = gk_data[ck].get("theta", 0) or 0
                    near_strikes.at[idx, "call_iv"] = gk_data[ck].get("iv", 0) or 0
                    near_strikes.at[idx, "call_gamma"] = gk_data[ck].get("gamma", 0) or 0
                    near_strikes.at[idx, "call_vega"] = gk_data[ck].get("vega", 0) or 0
                if pk in gk_data:
                    near_strikes.at[idx, "put_delta"] = gk_data[pk].get("delta", 0) or 0
                    near_strikes.at[idx, "put_theta"] = gk_data[pk].get("theta", 0) or 0
                    near_strikes.at[idx, "put_iv"] = gk_data[pk].get("iv", 0) or 0
                    near_strikes.at[idx, "put_gamma"] = gk_data[pk].get("gamma", 0) or 0
                    near_strikes.at[idx, "put_vega"] = gk_data[pk].get("vega", 0) or 0

    # Black-Scholes Fallback if API returns 0
    exp_date = dt.datetime.strptime(opt_expiry, "%Y-%m-%d").date()
    days_to_expiry = max((exp_date - today).days, 1)
    t = days_to_expiry / 365.0
    r = 0.07
    vol = 0.25 # Assume 25% IV

    for idx, row in near_strikes.iterrows():
        s = float(row["strike"])
        if near_strikes.at[idx, "call_delta"] == 0:
            cd, cg, ct, cv, civ = calculate_greeks(spot, s, t, r, vol, "CE")
            near_strikes.at[idx, "call_delta"] = cd
            near_strikes.at[idx, "call_gamma"] = cg
            near_strikes.at[idx, "call_theta"] = ct
            near_strikes.at[idx, "call_vega"] = cv
            near_strikes.at[idx, "call_iv"] = civ

        if near_strikes.at[idx, "put_delta"] == 0:
            pd, pg, pt, pv, piv = calculate_greeks(spot, s, t, r, vol, "PE")
            near_strikes.at[idx, "put_delta"] = pd
            near_strikes.at[idx, "put_gamma"] = pg
            near_strikes.at[idx, "put_theta"] = pt
            near_strikes.at[idx, "put_vega"] = pv
            near_strikes.at[idx, "put_iv"] = piv

    ce_atm = near_strikes[near_strikes["strike"] == atm_strike]
    ce_atm = ce_atm.iloc[0] if not ce_atm.empty else None
    
    if ce_atm is not None:
        greek_text = f"**ATM Greeks @ {atm_strike:,.0f}:** Δ Call/Put: {ce_atm['call_delta']:.2f} / {ce_atm['put_delta']:.2f} &nbsp;|&nbsp; Γ Gamma: {ce_atm['call_gamma']:.5f} &nbsp;|&nbsp; Θ Theta C/P: {ce_atm['call_theta']:.1f} / {ce_atm['put_theta']:.1f} &nbsp;|&nbsp; V Vega: {ce_atm['call_vega']:.2f} &nbsp;|&nbsp; IV Call/Put: {ce_atm['call_iv']:.1f}% / {ce_atm['put_iv']:.1f}%"
        st.info(greek_text)
        
        greeks_table = []
        for _, row in near_strikes.iterrows():
            greeks_table.append({
                "Strike": row["strike"], "Type": "ATM" if row["strike"] == atm_strike else ("ITM" if row["strike"] < atm_strike else "OTM"),
                "CE Premium": row["call_ltp"], "CE Vol": row["call_vol"], "CE Delta": row["call_delta"], "CE Theta": row["call_theta"], "CE IV": row["call_iv"],
                "PE Premium": row["put_ltp"], "PE Vol": row["put_vol"], "PE Delta": row["put_delta"], "PE Theta": row["put_theta"], "PE IV": row["put_iv"]
            })
        st.dataframe(pd.DataFrame(greeks_table).style.format({"CE Premium": "{:.2f}", "PE Premium": "{:.2f}", "CE Delta": "{:.3f}", "PE Delta": "{:.3f}", "CE IV": "{:.2f}", "PE IV": "{:.2f}"}), use_container_width=True)
else:
    st.warning("Option Greeks data not available.")


# Engine Breakdown (External vs Internal)
st.markdown("### ⚖️ Engine Breakdown (External vs Internal)")
ecol1, ecol2 = st.columns(2)

with ecol1:
    st.markdown('<div class="section-header">🌍 External Engine (Macro)</div>', unsafe_allow_html=True)
    if macro:
        st.metric("WTI Impact", f"{macro['wti_pct']:+.2f}%", "Bullish" if macro['wti_pct'] > 0 else "Bearish", delta_color="normal")
        st.metric("INR Impact", f"{macro['inr_pct']:+.2f}%", "Bullish" if macro['inr_pct'] > 0 else "Bearish", delta_color="normal")
        st.metric("Expected MCX Move", f"{macro['adjusted_wti_pct']:+.2f}%", f"Actual: {price['pct']:+.2f}%")
        st.metric("WTI Correlation Score", f"{master['wti_score']:+.2f}")

with ecol2:
    st.markdown('<div class="section-header">🔥 Internal Engine (Flow)</div>', unsafe_allow_html=True)
    if chain is not None:
        tc_oi, tp_oi = chain["call_oi"].sum(), chain["put_oi"].sum()
        pcr = tp_oi / tc_oi if tc_oi > 0 else 0
        atm_strike = ds["atm"] if ds else 0
        near_atm = chain[(chain["strike"] >= atm_strike - 200) & (chain["strike"] <= atm_strike + 200)]
        near_c_chg = near_atm["call_chg"].sum()
        near_p_chg = near_atm["put_chg"].sum()
        
        st.write(f"**Status:** {master['decision']} | **OI Score:** {master['oi_score']:+.2f}")
        st.markdown(f"""
        **Volume Flow:** {master['vol_score']:+.2f}  
        **Price Action:** {master['pa_score']:+.2f}  
        **ATM Strike:** {atm_strike:,.0f}  
        **Near-ATM Call ΔOI:** {near_c_chg:+,}  
        **Near-ATM Put ΔOI:** {near_p_chg:+,}  
        **Overall PCR:** {pcr:.2f}  
        **Futures Volume:** {price['volume']:,} | **Futures OI:** {price['oi']:,}
        """)


# ==============================
# OI TABLES
# ==============================
st.markdown("---")

def hl_top5(row): return (["background-color:#ffd700;font-weight:bold;color:#000"] * len(row)) if row.name < 5 else [""] * len(row)

if chain is not None:
    oi_tbl = chain[["strike", "call_oi", "put_oi"]].copy()
    oi_tbl["HIGH OI"] = oi_tbl.apply(lambda r: "HIGH PUT" if r.put_oi > r.call_oi else "HIGH CALL", axis=1)
    oi_tbl["OI Difference"] = (oi_tbl["put_oi"] - oi_tbl["call_oi"]).abs()
    st.subheader("Open Interest Data (Top by difference)")
    st.dataframe(oi_tbl.sort_values("OI Difference", ascending=False).head(top_n).reset_index(drop=True).style.apply(hl_top5, axis=1), use_container_width=True)

    chg_tbl = chain.loc[chain["has_chg"], ["strike", "call_chg", "put_chg"]].copy()
    chg_tbl["HIGH OI"] = chg_tbl.apply(lambda r: "HIGH PUT" if r.put_chg > r.call_chg else "HIGH CALL", axis=1)
    chg_tbl["OI Difference"] = (chg_tbl["put_chg"] - chg_tbl["call_chg"]).abs()
    st.subheader("Change in OI (Top by difference)")
    st.dataframe(chg_tbl.sort_values("OI Difference", ascending=False).head(top_n).reset_index(drop=True).style.apply(hl_top5, axis=1), use_container_width=True)

# Directional OI Score Breakdown
st.subheader("🎯 Directional OI Score Breakdown")
if ds:
    st.markdown(f"**OI Score:** {ds['final']:+.2f} (ATM {ds['atm']:g} | 1↑ OTM {ds['up_strike']} | 1↓ OTM {ds['down_strike']})")
    col_a, col_b = st.columns([3, 2])
    with col_a:
        breakdown = pd.DataFrame([{"Component": k, "Raw ΔPut−ΔCall": round(ds["raw"][k], 0), "Normalized": round(ds["norm"][k], 2), "Weight": ds["weights"][k]} for k in ds["norm"]])
        st.dataframe(breakdown, use_container_width=True)
    with col_b:
        st.markdown("""
        **How to read:**
        - **Put ΔOI ↑** → Bullish
        - **Call ΔOI ↑** → Bearish
        - **ITM Call ΔOI ↑** → Bearish
        - **ITM Put ΔOI ↑** → Bullish
        """)

# Futures OI Flow
if flow["rows"]:
    st.subheader(f"CRUDEOILM Futures OI Flow — Macro Score: {flow['score']:.2f}")
    st.dataframe(pd.DataFrame(flow["rows"]), use_container_width=True)

st.caption(f"Data Status: OK | Last updated: {now.strftime('%H:%M:%S IST')}")
