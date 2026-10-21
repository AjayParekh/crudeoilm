import gzip
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote
import json
import os
import datetime as dt
import math

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
.pill{display:inline-block;padding:3px 12px;border-radius:20px;font-size:.8rem;font-weight:600;
      background:#e9ecef;color:#333;margin-right:6px}
.trade-card{padding:20px;border-radius:12px;margin-bottom:14px;border-left:8px solid;color:white;box-shadow: 0 4px 15px rgba(0,0,0,0.2);}
.trade-header{font-size:1.8rem;font-weight:900;margin-bottom:10px;}
.trade-grid{display:grid; grid-template-columns: repeat(4, 1fr); gap: 15px; background: rgba(0,0,0,0.2); padding: 15px; border-radius: 8px; margin-top: 10px;}
.trade-item{text-align:center;}
.trade-label{font-size:0.8rem; opacity:0.8; text-transform:uppercase; letter-spacing:1px;}
.trade-value{font-size:1.3rem; font-weight:bold;}
.warn-badge{background: #f9a825; color: #000; padding: 4px 10px; border-radius: 5px; font-weight: bold; font-size: 0.9rem;}
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
    
    st.markdown("**💰 Position Sizing**")
    capital = st.number_input("Account Capital (₹)", min_value=10000, value=100000, step=10000)
    risk_pct = st.number_input("Risk per trade (%)", min_value=0.5, max_value=10.0, value=2.0, step=0.5)
    
    st.markdown("**🎯 Risk Management**")
    buffer_pts = st.number_input("Trigger buffer (points)", 1, 200, 10, 1, help="Distance from spot to trigger entry")
    min_gap = st.number_input("Stop Loss distance (points)", 5, 500, 30, 5, help="Fixed distance for SL and Target calculation")
    delta_lo, delta_hi = st.slider("Option Delta Band", 0.05, 0.95, (0.30, 0.75), 0.05, help="Select ATM/OTM strikes based on Delta")
    
    st.markdown("**📊 Analytics**")
    top_n = st.slider("Rows in OI tables", 5, 40, 20, 5)
    strike_window = st.slider("Strikes each side of price (for Greeks)", 5, 40, 20, 5)
    flow_big_cr = st.number_input("Big OI value change (₹ crore)", 1.0, 500.0, 10.0, 1.0)
    flow_pct = st.slider("OI % change threshold", 2, 50, 10, 1)

TOKEN = get_token()
if not TOKEN:
    st.warning("Add your Upstox token (st.secrets, env var UPSTOX_TOKEN, or sidebar) to continue.")
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

# AUTO-SELECT Futures and Options
with st.sidebar:
    st.markdown("---")
    fut_labels = {f"{f['symbol']} (exp {f['expiry']})": f for f in futs}
    if "fut_selector" in st.session_state and st.session_state.fut_selector not in fut_labels:
        del st.session_state.fut_selector
    sel_fut_label = st.selectbox("Futures contract (price)", list(fut_labels.keys()), index=0, key="fut_selector")
    fut = fut_labels[sel_fut_label]

    opt_expiries = sorted({i["expiry"] for i in ins if i["type"] in ("CE", "PE") and i["underlying_key"] == fut["key"] and i["expiry"] >= today_iso})
    if opt_expiries:
        if "opt_expiry_selector" in st.session_state and st.session_state.opt_expiry_selector not in opt_expiries:
            del st.session_state.opt_expiry_selector
        opt_expiry = st.selectbox("Option expiry (OI / Greeks)", opt_expiries, index=0, key="opt_expiry_selector")
    else:
        opt_expiry = None
        st.warning("No option expiries found.")

FUT_KEY = fut["key"]
LOT_SIZE = fut.get("lot_size", 10)

# ==============================
# PRICE & TREND (20 EMA)
# ==============================
@st.cache_data(ttl=300)
def get_trend_ema(fut_key):
    try:
        j = api_get(f"/v2/historical-candle/intraday/{quote(fut_key, safe='')}/5minute", {})
        if j.get("status") == "success":
            candles = j.get("data", {}).get("candles", [])
            if len(candles) >= 20:
                df = pd.DataFrame(candles, columns=["timestamp", "open", "high", "low", "close", "volume", "oi"])
                df = df.iloc[::-1]
                df["ema_20"] = df["close"].ewm(span=20, adjust=False).mean()
                return df["ema_20"].iloc[-1]
    except:
        pass
    
    try:
        end = dt.datetime.now(IST).date().isoformat()
        start = (dt.datetime.now(IST).date() - dt.timedelta(days=30)).isoformat()
        j = api_get(f"/v2/historical-candle/{quote(fut_key, safe='')}/day/{end}/{start}", {})
        if j.get("status") == "success":
            candles = j.get("data", {}).get("candles", [])
            if len(candles) >= 20:
                df = pd.DataFrame(candles, columns=["timestamp", "open", "high", "low", "close", "volume", "oi"])
                df = df.iloc[::-1]
                df["ema_20"] = df["close"].ewm(span=20, adjust=False).mean()
                return df["ema_20"].iloc[-1]
    except:
        pass
    return None

def get_price():
    j = api_get("/v2/market-quote/quotes", {"instrument_key": FUT_KEY})
    if j.get("status") == "success" and j.get("data"):
        q = next(iter(j["data"].values()))
        last = q.get("last_price") or 0
        chg = q.get("net_change") or 0
        ohlc = q.get("ohlc") or {}
        prev = round(last - chg, 2) if last else (ohlc.get("close") or 0)
        pct = (chg / prev * 100) if prev else 0
        return {"ltp": last, "chg": chg, "pct": pct, "prev": prev, "open": ohlc.get("open"), "high": ohlc.get("high"), "low": ohlc.get("low"), "oi": q.get("oi"), "volume": q.get("volume"), "src": "Upstox"}
    return None

price = get_price()
ema_20 = get_trend_ema(FUT_KEY)

# ==============================
# OPTION CHAIN
# ==============================
def _chunks(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]

def _fetch_prev_oi(key, day_iso):
    frm = (dt.date.fromisoformat(day_iso) - dt.timedelta(days=10)).isoformat()
    j = api_get(f"/v2/historical-candle/{quote(key, safe='')}/day/{day_iso}/{frm}", {})
    if j.get("status") != "success": return False, None
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
                "strike": it["strike_price"], "call_oi": c_oi, "put_oi": p_oi,
                "call_chg": c_oi - (cm.get("prev_oi") or 0), "put_chg": p_oi - (pm.get("prev_oi") or 0),
                "call_ltp": cm.get("ltp"), "put_ltp": pm.get("ltp"),
                "call_vol": cm.get("volume") or 0, "put_vol": pm.get("volume") or 0,
                "call_delta": cg.get("delta") or 0, "call_gamma": cg.get("gamma") or 0,
                "call_theta": cg.get("theta") or 0, "call_vega": cg.get("vega") or 0, "call_iv": cg.get("iv") or 0,
                "put_delta": pg.get("delta") or 0, "put_gamma": pg.get("gamma") or 0,
                "put_theta": pg.get("theta") or 0, "put_vega": pg.get("vega") or 0, "put_iv": pg.get("iv") or 0,
                "has_chg": True,
            })
    df = pd.DataFrame(rows).sort_values("strike").reset_index(drop=True) if rows else None
    if df is not None and (df["call_oi"].sum() + df["put_oi"].sum()) == 0: df = None
    return df, json.dumps(j)[:500]

def chain_from_instruments(spot):
    opts = [i for i in ins if i["type"] in ("CE", "PE") and i["underlying_key"] == FUT_KEY and i["expiry"] == opt_expiry and i.get("strike") is not None]
    if not opts: return None, "No CE/PE instruments with strike found"
    by_strike = {}
    for o in opts:
        by_strike.setdefault(float(o["strike"]), {})[o["type"]] = {"key": o["key"], "symbol": o["symbol"]}
    strikes = sorted(by_strike)

    quotes = {}
    for ch in _chunks([o["key"] for o in opts], 300):
        j = api_get("/v2/market-quote/quotes", {"instrument_key": ",".join(ch)})
        if j.get("status") != "success": return None, "quotes error: " + json.dumps(j)[:400]
        for v in (j.get("data") or {}).values():
            quotes[v.get("instrument_token")] = v

    mid = min(range(len(strikes)), key=lambda i: abs(strikes[i] - spot)) if spot else len(strikes) // 2
    win = strikes[max(0, mid - strike_window): mid + strike_window + 1]
    wkeys = [k for s_ in win for k in by_strike[s_].values()]

    greeks = {}
    for ch in _chunks([k["key"] for k in wkeys], 50):
        j = api_get("/v3/market-quote/option-greek", {"instrument_key": ",".join(ch)})
        if j.get("status") == "success": greeks.update(j.get("data") or {})

    cache = st.session_state.setdefault("prev_oi", {})
    todo = [k["key"] for k in wkeys if (k["key"], today_iso) not in cache]
    if todo:
        with ThreadPoolExecutor(8) as ex:
            for k, (ok, v) in zip(todo, ex.map(lambda k: _fetch_prev_oi(k, today_iso), todo)):
                if ok: cache[(k, today_iso)] = v

    rows = []
    for s_ in strikes:
        ck, pk = by_strike[s_].get("CE"), by_strike[s_].get("PE")
        cq = (quotes.get(ck["key"]) if ck else None) or {}
        pq = (quotes.get(pk["key"]) if pk else None) or {}
        cg = (greeks.get(ck["key"]) if ck else None) or {}
        pg = (greeks.get(pk["key"]) if pk else None) or {}
        
        c_oi = cq.get("oi") or 0
        p_oi = pq.get("oi") or 0
        c_prev = cache.get((ck["key"], today_iso)) if ck else None
        p_prev = cache.get((pk["key"], today_iso)) if pk else None
        has = (s_ in win) and c_prev is not None and p_prev is not None
        
        rows.append({
            "strike": s_, "call_oi": c_oi, "put_oi": p_oi,
            "call_chg": (c_oi - c_prev) if has else 0, "put_chg": (p_oi - p_prev) if has else 0,
            "call_ltp": cq.get("last_price"), "put_ltp": pq.get("last_price"),
            "call_vol": cq.get("volume") or 0, "put_vol": pq.get("volume") or 0,
            "call_symbol": ck["symbol"] if ck else "", "put_symbol": pk["symbol"] if pk else "",
            "call_delta": cg.get("delta") or 0, "call_gamma": cg.get("gamma") or 0,
            "call_theta": cg.get("theta") or 0, "call_vega": cg.get("vega") or 0, "call_iv": cg.get("iv") or 0,
            "put_delta": pg.get("delta") or 0, "put_gamma": pg.get("gamma") or 0,
            "put_theta": pg.get("theta") or 0, "put_vega": pg.get("vega") or 0, "put_iv": pg.get("iv") or 0,
            "has_chg": has,
        })
    df = pd.DataFrame(rows).reset_index(drop=True)
    if (df["call_oi"].sum() + df["put_oi"].sum()) == 0:
        return None, "Zero OI"
    return df, None

def get_chain():
    if not opt_expiry: return None, "No expiry", "none", ""
    try:
        df, raw = chain_from_option_api()
        if df is not None: return df, None, "Upstox option-chain API", raw
    except Exception as e:
        raw = f"Option Chain API Error: {e}"
        
    try:
        df, err = chain_from_instruments(price["ltp"] if price else 0)
        return df, err, "Instrument master + quotes", raw
    except Exception as e:
        return None, str(e), "Error", raw

chain, chain_err, chain_src, chain_raw = get_chain()

# ==============================
# FUTURES OI FLOW
# ==============================
def compute_crude_flow():
    keys = [f["key"] for f in futs]
    j = api_get("/v2/market-quote/quotes", {"instrument_key": ",".join(keys)})
    if j.get("status") != "success":
        return {"score": 0.0, "rows": [], "err": json.dumps(j)[:300]}
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
        if not last or prev_oi is None:
            continue
        lot = float(f.get("lot_size") or 10)
        prev_px = last - chg
        price_pct = chg / prev_px * 100 if prev_px else 0
        cur_val = oi * lot * last
        chg_abs = (oi - prev_oi) * lot * last
        oi_pct = (oi - prev_oi) / prev_oi * 100 if prev_oi else 0
        if cur_val < 100_000_000:
            continue

        score = 0.0
        if chg_abs > big and price_pct < -0.3: score = -0.9
        elif chg_abs > big and price_pct > 0.3: score = 0.9
        elif oi_pct > flow_pct * 3 and price_pct < -0.3: score = -0.6
        elif oi_pct > flow_pct and price_pct < -0.5: score = -0.4
        elif oi_pct > flow_pct and price_pct > 0.5: score = 0.4

        if oi_pct >= 0: label = "Long Buildup" if price_pct >= 0 else "Short Buildup"
        else: label = "Short Covering" if price_pct >= 0 else "Long Unwinding"

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
# SIGNALS & ANALYTICS
# ==============================
def max_pain(df):
    best, low = None, float("inf")
    for s in df["strike"]:
        pain = ((s - df["strike"]).clip(lower=0) * df["call_oi"]).sum() + ((df["strike"] - s).clip(lower=0) * df["put_oi"]).sum()
        if pain < low: best, low = s, pain
    return best

def oi_signal(df, spot):
    tc, tp = df["call_oi"].sum(), df["put_oi"].sum()
    pcr = tp / tc if tc else 1.0
    total_cv = df["call_vol"].sum()
    total_pv = df["put_vol"].sum()
    vol_pcr = total_pv / total_cv if total_cv else 1.0

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
    
    return dict(pcr=pcr, vol_pcr=vol_pcr, total_cv=total_cv, total_pv=total_pv,
                max_pain=mp, resistance=res, support=sup, net_c=net_c, net_p=net_p, 
                bull=bull, bear=bear, direction=direction)

def get_trade_setup(df, spot, buffer, min_gap, lo, hi, capital, risk_pct, trend_ema, flow_score):
    d = df[df["has_chg"]].copy()
    if d.empty: return None

    # 1. STRICT DIRECTION FILTER based on Macro Trend
    if flow_score < -0.2 or (trend_ema and spot < trend_ema):
        trade_dir = "PE"
        reason = f"Bearish Macro Flow ({flow_score:.2f}) or Below EMA. Looking for PE."
    elif flow_score > 0.2 or (trend_ema and spot > trend_ema):
        trade_dir = "CE"
        reason = f"Bullish Macro Flow ({flow_score:.2f}) or Above EMA. Looking for CE."
    else:
        # Neutral trend, look at nearest strong OI change
        near = df[(df["strike"] >= spot - 200) & (df["strike"] <= spot + 200)].copy()
        if near.empty: near = df.copy()
        near["diff"] = (near["put_chg"] - near["call_chg"]).abs()
        top = near.sort_values("diff", ascending=False).iloc[0]
        if top["put_chg"] > top["call_chg"]:
            trade_dir = "CE"
            reason = f"Neutral trend, but strong Put buildup at {top['strike']:g}."
        else:
            trade_dir = "PE"
            reason = f"Neutral trend, but strong Call buildup at {top['strike']:g}."

    # 2. CALCULATE TRIGGER, SL, TARGET based on Current Spot
    if trade_dir == "CE":
        trigger_spot = spot + buffer
        sl_spot = spot - min_gap  # Fixed risk distance
        # Target: Next Call OI wall above, or fixed distance
        target_candidates = df[(df["strike"] > trigger_spot) & (df["call_oi"] > 0)].sort_values("strike")
        if not target_candidates.empty and target_candidates.iloc[0]["strike"] <= spot + 400:
            target_spot = target_candidates.iloc[0]["strike"]
        else:
            target_spot = trigger_spot + (min_gap * 2)
            
        opt_type = "CE"
        opt_delta_col, opt_symbol_col, opt_ltp_col, opt_iv_col = "call_delta", "call_symbol", "call_ltp", "call_iv"
        opt_vol_col = "call_vol"
        is_bullish = True
    else:
        trigger_spot = spot - buffer
        sl_spot = spot + min_gap  # Fixed risk distance
        # Target: Next Put OI wall below, or fixed distance
        target_candidates = df[(df["strike"] < trigger_spot) & (df["put_oi"] > 0)].sort_values("strike", ascending=False)
        if not target_candidates.empty and target_candidates.iloc[0]["strike"] >= spot - 400:
            target_spot = target_candidates.iloc[0]["strike"]
        else:
            target_spot = trigger_spot - (min_gap * 2)
            
        opt_type = "PE"
        opt_delta_col, opt_symbol_col, opt_ltp_col, opt_iv_col = "put_delta", "put_symbol", "put_ltp", "put_iv"
        opt_vol_col = "put_vol"
        is_bullish = False

    # 3. FIND BEST OPTION STRIKE (Delta band)
    best_opt = None
    min_dist = float("inf")
    for _, row in df.iterrows():
        delta = abs(row[opt_delta_col])
        if lo <= delta <= hi:
            dist = abs(row["strike"] - spot)
            if dist < min_dist:
                min_dist = dist
                best_opt = row

    if best_opt is None:
        best_opt = df.iloc[(df["strike"] - spot).abs().argsort()[:1]].iloc[0]
        
    opt_premium = best_opt[opt_ltp_col] if not pd.isna(best_opt[opt_ltp_col]) else 0.0
    opt_delta = best_opt[opt_delta_col] if not pd.isna(best_opt[opt_delta_col]) else 0.0
    if opt_delta == 0: opt_delta = 0.5
    opt_iv = best_opt[opt_iv_col] if not pd.isna(best_opt[opt_iv_col]) else 0.0
    opt_symbol = best_opt[opt_symbol_col] if best_opt[opt_symbol_col] else "Unknown"
    opt_vol = best_opt[opt_vol_col]
    
    # 4. PREMIUM SL & TARGET
    spot_risk = abs(trigger_spot - sl_spot)
    premium_risk = spot_risk * opt_delta
    premium_sl = max(1.0, opt_premium - premium_risk)
    
    spot_reward = abs(target_spot - trigger_spot)
    premium_target = opt_premium + (spot_reward * opt_delta)

    # 5. POSITION SIZING
    risk_amount = capital * (risk_pct / 100)
    risk_per_lot = (opt_premium - premium_sl) * LOT_SIZE
    if risk_per_lot > 0:
        lots = math.floor(risk_amount / risk_per_lot)
        if lots < 1 and risk_amount >= risk_per_lot: lots = 1
    else:
        lots = 0

    avg_vol = df[opt_vol_col].mean()
    vol_confirm = "🔥 HIGH VOL" if opt_vol > avg_vol * 1.5 else "Normal"
    
    risk = abs(trigger_spot - sl_spot)
    reward = abs(target_spot - trigger_spot)
    rr = round(reward / risk, 2) if risk > 0 else 0

    return {
        "type": opt_type, "symbol": opt_symbol, "strike": best_opt["strike"],
        "premium": opt_premium, "delta": opt_delta, "iv": opt_iv,
        "opt_vol": opt_vol, "vol_confirm": vol_confirm,
        "premium_sl": premium_sl, "premium_target": premium_target,
        "lots": lots,
        "entry_spot": trigger_spot, "sl_spot": sl_spot, "target_spot": target_spot,
        "rr": rr, "reason": reason, "is_bullish": is_bullish,
        "counter_trend": False # Removed because we strictly enforce trend now
    }

# ==============================
# UI LAYOUT
# ==============================
st.title("🛢️ CRUDEOILM Analytics & Options Setup")

if not price:
    st.error("Could not fetch CRUDEOILM price.")
    st.stop()

spot = price["ltp"]
cls = "pos" if price["chg"] > 0 else "neg" if price["chg"] < 0 else ""
arrow = "▲" if price["chg"] > 0 else "▼" if price["chg"] < 0 else "—"

# Calculate Flow first to pass to Trade Setup
flow = compute_crude_flow()

# Top Row: Price & Trend
c1, c2, c3, c4 = st.columns([2, 1, 1, 1.5])
with c1:
    st.markdown(f"""<div class="card"><div style="color:#666">CRUDEOILM (Fut) · {price['src']}</div>
      <div class="big">{spot:,.2f}</div>
      <div class="{cls}">{arrow} {price['chg']:+,.2f} ({price['pct']:+.2f}%)</div>
      <div style="font-size:.8rem;color:#888">Prev: {price['prev']:,.2f}</div></div>""", unsafe_allow_html=True)
with c2:
    st.markdown(f"""<div class="card"><div style="color:#666">Day High</div><div style="font-size:1.2rem;font-weight:bold">{price['high'] or 0:,.2f}</div></div>""", unsafe_allow_html=True)
with c3:
    st.markdown(f"""<div class="card"><div style="color:#666">Day Low</div><div style="font-size:1.2rem;font-weight:bold">{price['low'] or 0:,.2f}</div></div>""", unsafe_allow_html=True)
with c4:
    if ema_20:
        t_color = "bullish" if spot > ema_20 else "bearish"
        t_text = "BULLISH (Above EMA)" if spot > ema_20 else "BEARISH (Below EMA)"
        st.markdown(f"""<div class="pred {t_color}" style="padding:10px;margin-bottom:0"><div style="opacity:.8">Trend Filter (20 EMA)</div>
          <div style="font-size:1.2rem;font-weight:800">{t_text}</div>
          <div style="font-size:.85rem">EMA: {ema_20:,.2f}</div></div>""", unsafe_allow_html=True)
    else:
        st.markdown(f"""<div class="card" style="text-align:center; background:#f9a825; color:black;">
        <div style="font-weight:bold;">Trend EMA Data Unavailable</div>
        <div style="font-size:0.9rem;">Relying on Macro Flow Score only</div>
        </div>""", unsafe_allow_html=True)

st.markdown("---")

# ==============================
# TRADE SETUP (CALL/PUT)
# ==============================
st.subheader("🎯 Actionable Options Trade Setup")

if chain is None or chain.empty:
    st.error("Could not build option chain. Cannot generate trade setup.")
else:
    setup = get_trade_setup(chain, spot, buffer_pts, min_gap, delta_lo, delta_hi, capital, risk_pct, ema_20, flow["score"])
    
    if setup:
        bg = "linear-gradient(135deg, #11998e, #38ef7d)" if setup["is_bullish"] else "linear-gradient(135deg, #cb2d3e, #ef473a)"
        border = "#11998e" if setup["is_bullish"] else "#cb2d3e"
        
        card_html = f'''<div class="trade-card" style="background:{bg}; border-left-color:{border};">
<div class="trade-header">🟢 BUY {setup["symbol"]} @ {setup["premium"]:.2f}</div>
<div><b>Strategy:</b> {setup["reason"]}</div>
<div class="trade-grid">
<div class="trade-item"><div class="trade-label">Entry Premium</div><div class="trade-value">₹ {setup["premium"]:.2f}</div></div>
<div class="trade-item"><div class="trade-label">Premium SL</div><div class="trade-value">₹ {setup["premium_sl"]:.2f}</div></div>
<div class="trade-item"><div class="trade-label">Premium Target</div><div class="trade-value">₹ {setup["premium_target"]:.2f}</div></div>
<div class="trade-item"><div class="trade-label">Position Size</div><div class="trade-value">{setup["lots"]} Lots</div></div>
</div>
<div style="margin-top:15px; font-size:0.9rem; display:flex; flex-wrap:wrap; gap:20px; opacity:0.9;">
<div>📊 <b>Spot Entry:</b> {setup["entry_spot"]:,.2f}</div>
<div>🛑 <b>Spot SL:</b> {setup["sl_spot"]:,.2f}</div>
<div>🎯 <b>Spot Target:</b> {setup["target_spot"]:,.2f}</div>
<div>⚖️ <b>Risk/Reward:</b> 1 : {setup["rr"]}</div>
<div>📈 <b>IV:</b> {setup["iv"]:.1f}%</div>
<div>📦 <b>Vol:</b> {setup["opt_vol"]:,} ({setup["vol_confirm"]})</div>
</div>
</div>'''
        
        st.markdown(card_html, unsafe_allow_html=True)
        
        if (spot >= setup["entry_spot"] and setup["is_bullish"]) or (spot <= setup["entry_spot"] and not setup["is_bullish"]):
            st.success("🔥 **ENTRY ACTIVE:** Spot price has hit the trigger! You can enter this trade now.")
        else:
            st.info("⏳ **PENDING:** Waiting for Spot price to hit the Entry Trigger.")
            
    else:
        st.info("ℹ️ No high-confidence OI change detected for a Call/Put setup right now.")

st.markdown("---")

# ==============================
# FUTURES OI FLOW UI
# ==============================
if flow["rows"]:
    st.subheader(f"🌊 CRUDEOILM Futures OI Flow — Macro Score: {flow['score']:.2f}")
    bias = "Bullish" if flow["score"] > 0 else ("Bearish" if flow["score"] < 0 else "Sideways")
    st.markdown(f"**Market Bias:** {bias}")
    st.dataframe(pd.DataFrame(flow["rows"]))
else:
    st.info("Futures OI flow not available (no futures contract met the OI-value threshold).")

st.markdown("---")

# ==============================
# CHARTS & TABLES
# ==============================
if chain is not None and not chain.empty:
    sig = oi_signal(chain, spot)
    kls = {"BULLISH": "bullish", "BEARISH": "bearish"}.get(sig["direction"], "neutral")
    
    col_a, col_b = st.columns([1, 3])
    with col_a:
        st.markdown(f"""<div class="pred {kls}" style="padding:10px;margin-bottom:12px"><div style="opacity:.8">Macro Option Signal</div>
          <div style="font-size:1.4rem;font-weight:800">{sig['direction']}</div>
          <div style="font-size:.85rem">🟢 {sig['bull']} vs 🔴 {sig['bear']}</div></div>""", unsafe_allow_html=True)
    
    with col_b:
        m1, m2, m3, m4, m5, m6 = st.columns(6)
        m1.metric("OI PCR", f"{sig['pcr']:.2f}")
        m2.metric("Vol PCR", f"{sig['vol_pcr']:.2f}")
        m3.metric("Max Pain", f"{sig['max_pain']:,.0f}")
        m4.metric("Support (Put OI)", f"{sig['support']:,.0f}")
        m5.metric("Resistance (Call OI)", f"{sig['resistance']:,.0f}")
        m6.metric("Total C/P Vol", f"{sig['total_cv']:,} / {sig['total_pv']:,}")

    st.subheader("Open Interest by Strike")
    st.bar_chart(chain.set_index("strike")[["call_oi", "put_oi"]])
    
    st.subheader("Trading Volume by Strike")
    st.bar_chart(chain.set_index("strike")[["call_vol", "put_vol"]])
    
    st.subheader("Change in OI by Strike")
    st.bar_chart(chain[chain["has_chg"]].set_index("strike")[["call_chg", "put_chg"]])

    def hl_top5(row):
        return (["background-color:#ffd700;font-weight:bold;color:#000"] * len(row)) if row.name < 5 else [""] * len(row)

    col1, col2 = st.columns(2)
    with col1:
        oi_tbl = chain[["strike", "call_oi", "put_oi", "call_vol", "put_vol"]].copy()
        oi_tbl["OI Difference"] = (oi_tbl["put_oi"] - oi_tbl["call_oi"]).abs()
        st.subheader("Top OI & Volume")
        st.dataframe(oi_tbl.sort_values("OI Difference", ascending=False).head(top_n).reset_index(drop=True).style.apply(hl_top5, axis=1))
    
    with col2:
        chg_tbl = chain.loc[chain["has_chg"], ["strike", "call_chg", "put_chg", "call_vol", "put_vol"]].copy()
        chg_tbl["OI Difference"] = (chg_tbl["put_chg"] - chg_tbl["call_chg"]).abs()
        st.subheader("Top ΔOI & Volume")
        st.dataframe(chg_tbl.sort_values("OI Difference", ascending=False).head(top_n).reset_index(drop=True).style.apply(hl_top5, axis=1))

    st.subheader("Option Chain + Greeks (Nearest to Spot)")
    near = chain.iloc[(chain["strike"] - spot).abs().argsort()[:15]].sort_values("strike")
    st.dataframe(near[["strike", "call_ltp", "call_oi", "call_vol", "call_delta", "call_iv", "put_ltp", "put_oi", "put_vol", "put_delta", "put_iv"]].reset_index(drop=True))

st.caption(f"Last refresh: {now.strftime('%H:%M:%S IST')} · auto-refresh every 15s")
