import gzip
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote
import json
import os
import datetime as dt
import smtplib
from email.message import EmailMessage

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
# CSS STYLES (Matching Nifty Reference)
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
.alert-safe-green { background-color: #d4edda; color: #155724; border-left: 5px solid #28a745; }
.alert-safe-red { background-color: #f8d7da; color: #721c24; border-left: 5px solid #dc3545; }
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
        if not receivers_raw:
            return False, "No EMAIL_RECEIVER found."
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
# DATA FETCHING & CALCULATIONS (UNTOUCHED LOGIC)
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

# Smart filter for futures with options
valid_futs = [f for f in futs if any(i["type"] in ("CE", "PE") and i["underlying_key"] == f["key"] for i in ins)]
if valid_futs: futs = valid_futs

with st.sidebar:
    st.markdown("---")
    fut_labels = {f"{f['symbol']} (exp {f['expiry']})": f for f in futs}
    fut = fut_labels[st.selectbox("Futures contract", list(fut_labels.keys()), index=0)]

    opt_expiries = sorted({i["expiry"] for i in ins if i["type"] in ("CE", "PE") and i["underlying_key"] == fut["key"] and i["expiry"] >= today_iso})
    opt_expiry = st.selectbox("Option expiry", opt_expiries, index=0) if opt_expiries else None

FUT_KEY = fut["key"]

def get_price():
    j = api_get("/v2/market-quote/quotes", {"instrument_key": FUT_KEY})
    if j.get("status") == "success" and j.get("data"):
        q = next(iter(j["data"].values()))
        last = q.get("last_price") or 0
        chg = q.get("net_change") or 0
        ohlc = q.get("ohlc") or {}
        prev = round(last - chg, 2) if last else (ohlc.get("close") or 0)
        pct = (chg / prev * 100) if prev else 0
        return {"ltp": last, "chg": chg, "pct": pct, "prev": prev, "open": ohlc.get("open"), "high": ohlc.get("high"), "low": ohlc.get("low"), "oi": q.get("oi"), "volume": q.get("volume")}
    return None

@st.cache_data(ttl=10)
def get_macro_data():
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        r_wti = requests.get("https://query1.finance.yahoo.com/v8/finance/chart/CL=F", headers=headers, timeout=5)
        wti_meta = r_wti.json()['chart']['result'][0]['meta']
        r_inr = requests.get("https://query1.finance.yahoo.com/v8/finance/chart/USDINR=X", headers=headers, timeout=5)
        inr_meta = r_inr.json()['chart']['result'][0]['meta']
    except Exception:
        return None
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

def _chunks(lst, n):
    for i in range(0, len(lst), n): yield lst[i:i + n]

def _fetch_prev_oi(key, day_iso):
    frm = (dt.date.fromisoformat(day_iso) - dt.timedelta(days=10)).isoformat()
    j = api_get(f"/v2/historical-candle/{quote(key, safe='')}/day/{day_iso}/{frm}", {})
    if j.get("status") != "success": return False, None
    for c in (j.get("data") or {}).get("candles") or []:
        if str(c[0])[:10] < day_iso and len(c) > 6 and c[6] is not None: return True, c[6]
    return True, None

def get_chain():
    if not opt_expiry: return None, "No option expiry found"
    # Using Option API first
    j = api_get("/v2/option/chain", {"instrument_key": FUT_KEY, "expiry_date": opt_expiry})
    rows = []
    if j.get("status") == "success":
        for it in j.get("data") or []:
            c, p = it.get("call_options") or {}, it.get("put_options") or {}
            cm, pm = c.get("market_data") or {}, p.get("market_data") or {}
            cg, pg = c.get("option_greeks") or {}, p.get("option_greeks") or {}
            rows.append({
                "strike": it["strike_price"], "call_oi": cm.get("oi") or 0, "put_oi": pm.get("oi") or 0,
                "call_vol": cm.get("volume") or 0, "put_vol": pm.get("volume") or 0,
                "call_chg": (cm.get("oi") or 0) - (cm.get("prev_oi") or 0), "put_chg": (pm.get("oi") or 0) - (pm.get("prev_oi") or 0),
                "call_ltp": cm.get("ltp"), "put_ltp": pm.get("ltp"),
                "call_delta": cg.get("delta") or 0, "call_gamma": cg.get("gamma") or 0, "call_theta": cg.get("theta") or 0, "call_vega": cg.get("vega") or 0, "call_iv": cg.get("iv") or 0,
                "put_delta": pg.get("delta") or 0, "put_gamma": pg.get("gamma") or 0, "put_theta": pg.get("theta") or 0, "put_vega": pg.get("vega") or 0, "put_iv": pg.get("iv") or 0,
                "has_chg": True,
            })
    df = pd.DataFrame(rows).sort_values("strike").reset_index(drop=True) if rows else None
    return df, None

chain, chain_err = get_chain()
if chain is not None:
    chain = chain[((chain["call_oi"] > min_liquidity) | (chain["put_oi"] > min_liquidity)) & ((chain["call_vol"] > min_liquidity) | (chain["put_vol"] > min_liquidity))].reset_index(drop=True)

def compute_directional_score(chain, spot):
    if chain is None or chain.empty: return None
    d = chain[chain["has_chg"]].copy()
    if len(d) < 3: return None
    strikes = sorted(d["strike"].unique())
    atm = min(strikes, key=lambda s: abs(s - spot))
    atm_idx = strikes.index(atm)
    def get_row(s): return d[d["strike"] == s].iloc[0]

    d["pc_diff"] = d["put_chg"].astype(float) - d["call_chg"].astype(float)
    d["abs_diff"] = d["pc_diff"].abs()
    top = d.nlargest(5, "abs_diff")
    top_raw = (float((top["pc_diff"] * top["abs_diff"]).sum() / top["abs_diff"].sum()) if top["abs_diff"].sum() > 0 else 0.0)
    atm_raw = float(get_row(atm)["put_chg"]) - float(get_row(atm)["call_chg"])
    up_strike = strikes[atm_idx + 1] if atm_idx + 1 < len(strikes) else None
    up_raw = (float(get_row(up_strike)["put_chg"]) - float(get_row(up_strike)["call_chg"])) if up_strike else 0.0
    down_strike = strikes[atm_idx - 1] if atm_idx - 1 >= 0 else None
    down_raw = (float(get_row(down_strike)["put_chg"]) - float(get_row(down_strike)["call_chg"])) if down_strike else 0.0
    
    itm_call_strikes = [s for s in strikes if s < spot][-3:]
    itm_put_strikes  = [s for s in strikes if s > spot][:3]
    itm_call_avg = (sum(float(get_row(s)["call_chg"]) for s in itm_call_strikes) / len(itm_call_strikes)) if itm_call_strikes else 0.0
    itm_put_avg  = (sum(float(get_row(s)["put_chg"]) for s in itm_put_strikes) / len(itm_put_strikes)) if itm_put_strikes else 0.0
    itm_raw = itm_put_avg - itm_call_avg

    scale = max(float(d["call_chg"].abs().max()), float(d["put_chg"].abs().max()), 1.0)
    def clip(x): return max(-1.0, min(1.0, x))
    norm = {"Top ΔOI": clip(top_raw / scale), "ATM": clip(atm_raw / scale), "1↑ OTM": clip(up_raw / scale), "1↓ OTM": clip(down_raw / scale), "ITM": clip(itm_raw / scale)}
    final = clip((norm["Top ΔOI"]*0.3) + (norm["ATM"]*0.2) + (norm["1↑ OTM"]*0.15) + (norm["1↓ OTM"]*0.15) + (norm["ITM"]*0.2))
    
    return {"final": final, "atm": atm, "up_strike": up_strike, "down_strike": down_strike, "norm": norm}

def compute_master_confluence(price, chain, ds, macro):
    oi_score = ds["final"] if ds else 0.0
    tc_vol = chain["call_vol"].sum() if chain is not None else 0
    tp_vol = chain["put_vol"].sum() if chain is not None else 0
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

    decision, reason = "NO TRADE", "Indicators mixed."
    if oi_score > 0.2 and vol_score > 0 and pa_score > 0: decision, reason = "STRONG BUY", "Bullish OI + Vol + PA align."
    elif oi_score < -0.2 and vol_score < 0 and pa_score < 0: decision, reason = "STRONG SELL", "Bearish OI + Vol + PA align."
    elif final_score > 0.3: decision, reason = "WEAK BUY", "Positive bias, not all align."
    elif final_score < -0.3: decision, reason = "WEAK SELL", "Negative bias, not all align."
    else: decision, reason = "NEUTRAL", "Sideways / conflicting."

    return {"decision": decision, "reason": reason, "final_score": final_score, "oi_score": oi_score, "vol_score": vol_score, "pa_score": pa_score, "wti_score": wti_score}

spot = price["ltp"] if price else 0
ds = compute_directional_score(chain, spot) if chain is not None else None
master = compute_master_confluence(price, chain, ds, macro) if chain is not None else None

# ==============================
# UI RENDER (NIFTY STYLE)
# ==============================
st.title("🛢️ CRUDEOILM Ecosystem — MCX")

# Top Cards
def render_card(label, value, chg, pct, is_inr=False):
    cls = "pos" if chg >= 0 else "neg"
    arrow = "▲" if chg > 0 else "▼" if chg < 0 else "—"
    val_str = f"{value:,.3f}" if is_inr else f"{value:,.2f}"
    chg_str = f"{arrow} {chg:+.3f} ({pct:+.2f}%)" if is_inr else f"{arrow} {chg:+,.2f} ({pct:+.2f}%)"
    return f'<div class="card"><div class="metric-label">{label}</div><div class="big-price">{val_str}</div><div class="{cls}">{chg_str}</div></div>'

c1, c2, c3, c4 = st.columns(4)
with c1: st.markdown(render_card(f"CRUDEOILM ({fut['symbol']})", spot, price['chg'], price['pct']), unsafe_allow_html=True)
with c2: st.markdown(render_card("Futures OI / Volume", price['oi'] or 0, price['volume'] or 0, 0), unsafe_allow_html=True)
with c3: 
    if macro: st.markdown(render_card("WTI Crude", macro['wti_ltp'], macro['wti_chg'], macro['wti_pct']), unsafe_allow_html=True)
    else: st.markdown('<div class="card">WTI Data Unavailable</div>', unsafe_allow_html=True)
with c4:
    if macro: st.markdown(render_card("USD/INR", macro['inr_ltp'], macro['inr_chg'], macro['inr_pct'], is_inr=True), unsafe_allow_html=True)
    else: st.markdown('<div class="card">INR Data Unavailable</div>', unsafe_allow_html=True)

st.markdown("---")

# External Alert Logic (Existing Logic Unchanged)
alert_status = "IN_SYNC"
gap_val = 0
if macro and price and not macro["is_market_closed"]:
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
    st.markdown(f'<div class="alert-box alert-safe-green">🚨 <b>SAFE GAP ALERT (Rise Expected)</b><br>WTI implies MCX should rise <b>{gap_val:.2f}%</b>. <b>⚠️ WAIT for Internal Engine to say CONFIRM.</b></div>', unsafe_allow_html=True)
elif alert_status == "SAFE_DROP":
    st.markdown(f'<div class="alert-box alert-safe-red">🚨 <b>SAFE GAP ALERT (Drop Expected)</b><br>WTI implies MCX should drop <b>{gap_val:.2f}%</b>. <b>⚠️ WAIT for Internal Engine to say CONFIRM.</b></div>', unsafe_allow_html=True)
else:
    st.markdown(f'<div class="alert-box alert-info">⚪ <b>EXTERNAL MACRO IN SYNC</b> — Gap is {gap_val:.2f}%.</div>', unsafe_allow_html=True)


# Large Decision Box
action = master["decision"] if master else "NO TRADE"
css_class = "neutral"
if "BUY" in action: css_class = "buy"
elif "SELL" in action: css_class = "sell"
elif action == "NEUTRAL": css_class = "wait"

st.markdown(f'<div class="decision-box {css_class}"><h1 style="margin:0; font-size: 3rem;">{action.replace("_", " ")}</h1><p style="font-size: 1.2rem; margin-top: 10px;">Direction: <b>{"BULLISH" if "BUY" in action else "BEARISH" if "SELL" in action else "SIDEWAYS"}</b> | Confluence Score: <b>{master["final_score"]:+.2f}</b></p></div>', unsafe_allow_html=True)


# Option Greeks (ATM Window)
st.markdown("### 📊 Option Greeks (ATM Window)")
if chain is not None and not chain.empty:
    atm_strike = ds["atm"] if ds else 0
    near_strikes = chain.iloc[(chain["strike"] - spot).abs().argsort()[:5]].sort_values("strike")
    
    ce_atm = chain[chain["strike"] == atm_strike].iloc[0] if atm_strike in chain["strike"].values else None
    
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


# OI Charts & Tables (Kept as requested)
st.markdown("---")
st.subheader("Open Interest by Strike")
if chain is not None: st.bar_chart(chain.set_index("strike")[["call_oi", "put_oi"]])

st.subheader("Change in OI by Strike")
if chain is not None: st.bar_chart(chain[chain["has_chg"]].set_index("strike")[["call_chg", "put_chg"]])

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

st.caption(f"Data Status: OK | Last updated: {now.strftime('%H:%M:%S IST')}")
