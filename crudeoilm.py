import gzip
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote
import json
import os
import datetime as dt
import math
import calendar
import time
import warnings

import pandas as pd
import pytz
import requests
import streamlit as st
from streamlit_autorefresh import st_autorefresh
import numpy as np

warnings.filterwarnings('ignore')

# ==============================
# PAGE CONFIG
# ==============================
st.set_page_config(page_title="CRUDEOILM Analytics Pro", page_icon="🛢️", layout="wide", initial_sidebar_state="expanded")
st_autorefresh(interval=15_000, key="global_sync_refresh")

IST = pytz.timezone("Asia/Kolkata")
now = dt.datetime.now(IST)
today = now.date()
today_str = now.strftime('%Y-%m-%d')

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

access_token = get_token()
if not access_token:
    st.warning("Add your Upstox token to continue.")
    st.stop()
if not access_token.startswith("Bearer "):
    access_token = "Bearer " + access_token

HEADERS = {"Accept": "application/json", "Content-Type": "application/json", "Authorization": access_token}

# ==============================
# STYLES
# ==============================
st.markdown("""
    <style>
    .main { background-color: #f4f7f9; }
    .market-box {
        background-color: white; padding: 18px; border-radius: 12px;
        border: 1px solid #e1e4e8; box-shadow: 0px 4px 10px rgba(0,0,0,0.03);
        margin-bottom: 15px;
    }
    .prediction-box {
        background: linear-gradient(135deg, #1e3a8a 0%, #3b82f6 100%);
        color: white; padding: 20px; border-radius: 15px; text-align: center;
        margin-bottom: 15px; position: relative;
    }
    .prediction-achieved { background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%) !important; }
    .confidence-tag {
        background: rgba(255,255,255,0.2); padding: 4px 12px; border-radius: 20px;
        font-size: 0.9rem; font-weight: bold; display: inline-block; margin-top: 10px;
        border: 1px solid rgba(255,255,255,0.3);
    }
    .divergence-alert {
        background-color: #f8d7da; color: #721c24; padding: 12px 20px; border-radius: 10px;
        border-left: 5px solid #dc3545; margin-bottom: 20px; font-weight: bold;
        font-size: 1.05rem; box-shadow: 0 4px 6px rgba(0,0,0,0.05);
    }
    .vix-alert {
        background-color: #fff3cd; color: #856404; padding: 10px 20px; border-radius: 10px;
        border-left: 5px solid #ffc107; margin-bottom: 15px; font-weight: bold;
    }
    .status-badge {
        position: absolute; top: 10px; right: 15px; background: rgba(255,255,255,0.25);
        color: white; padding: 2px 10px; border-radius: 8px; font-size: 0.75rem;
        font-weight: bold; text-transform: uppercase;
    }
    .prediction-card {
        padding: 30px; border-radius: 20px; text-align: center; color: white;
        margin-bottom: 15px; position: relative;
    }
    .bullish  { background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%); }
    .bearish  { background: linear-gradient(135deg, #cb2d3e 0%, #ef473a 100%); }
    .weak-bullish { background: linear-gradient(135deg, #2d6a4f 0%, #52b788 100%); }
    .weak-bearish { background: linear-gradient(135deg, #7b2d00 0%, #c05c2a 100%); }
    .neutral  { background: linear-gradient(135deg, #2c3e50 0%, #4ca1af 100%); }
    .price-large { font-size: 2.8rem; font-weight: 800; margin: 10px 0; }
    .move-text { font-size: 1.5rem; font-weight: 600; margin-bottom: 10px; opacity: 0.9; }
    .sl-badge  { font-size: 1.2rem; font-weight: 700; background: rgba(0,0,0,0.2);
                 padding: 8px 20px; border-radius: 10px; display: inline-block;
                 margin-top: 10px; border: 1px solid rgba(255,255,255,0.3); }
    .market-header { display: flex; justify-content: space-between; align-items: center;
                     border-bottom: 1px solid #eee; padding-bottom: 8px; margin-bottom: 10px; }
    .market-name  { font-weight: 700; font-size: 1.1rem; color: #1a1a1a; }
    .price-row    { display: flex; justify-content: space-between; align-items: baseline; }
    .price-value  { font-size: 1.5rem; font-weight: 800; color: #1a1a1a; }
    .change-value { font-size: 1rem; font-weight: 600; }
    .positive, .pos { color: #00873c; font-weight: bold; }
    .negative, .neg { color: #eb4444; font-weight: bold; }
    .neutral-color  { color: #6e7781; }
    .signal-score-bar {
        background: rgba(255,255,255,0.15); border-radius: 8px; padding: 8px 16px;
        margin-top: 10px; font-size: 0.95rem; display: inline-block;
    }
    .indicator-row { display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 12px; }
    .indicator-pill {
        padding: 4px 12px; border-radius: 20px; font-size: 0.8rem; font-weight: 600;
        border: 1px solid rgba(0,0,0,0.08);
    }
    .pill-green  { background:#d4edda; color:#155724; }
    .pill-red    { background:#f8d7da; color:#721c24; }
    .pill-yellow { background:#fff3cd; color:#856404; }
    .pill-gray   { background:#e9ecef; color:#495057; }
    .entry-box {
        padding: 15px 20px; border-radius: 12px; margin-bottom: 20px;
        color: #000000; border-left: 6px solid;
    }
    .entry-box .status-text { font-weight: bold; }
    .greeks-panel {
        background: white; padding: 12px 18px; border-radius: 10px;
        border-left: 5px solid; margin-bottom: 15px; color: #000;
    }
    .greeks-panel .badge-pass {
        background-color: #2e7d32; color: white; padding: 2px 10px;
        border-radius: 12px; font-weight: bold; font-size: 0.8rem;
    }
    .greeks-panel .badge-weak {
        background-color: #f9a825; color: #000; padding: 2px 10px;
        border-radius: 12px; font-weight: bold; font-size: 0.8rem;
    }
    .greeks-panel .greek-item { display: inline-block; margin-right: 20px; font-size: 0.9rem; }
    .greeks-panel .greek-item b { color: #1a1a1a; }
    </style>
""", unsafe_allow_html=True)

# ==============================
# SIDEBAR
# ==============================
with st.sidebar:
    st.title("🛢️ CRUDEOILM Settings")
    st.markdown(f"### 🕒 IST: {now.strftime('%H:%M:%S')}")
    
    st.markdown("**🎯 Risk Management**")
    buffer_pts = st.number_input("Trigger buffer (points)", 1, 200, 10, 1)
    min_gap = st.number_input("Min entry–exit gap (points)", 5, 500, 30, 5)
    delta_lo, delta_hi = st.slider("Option Delta Band", 0.05, 0.95, (0.30, 0.75), 0.05)
    
    st.markdown("**🛡️ Entry Confirmation Gate**")
    gate_hold_min     = st.slider("Signal must hold (min)", 0, 30, 5, 1)
    gate_price_min    = st.slider("Price beyond trigger for (min)", 0, 15, 3, 1)
    gate_min_score    = st.slider("Min futures score to agree", 0.0, 0.9, 0.2, 0.05)
    gate_min_dom      = st.slider("Strike dominance (x vs next)", 1.0, 3.0, 1.3, 0.1)
    gate_max_dist_pct = st.slider("Max strike distance from spot %", 0.5, 5.0, 2.0, 0.5)
    gate_sl_buffer    = st.slider("Stop-loss buffer beyond strike (pts)", 5, 100, 20, 5)
    gate_time_filter  = st.checkbox("Block opening 15 min & last 30 min", value=True)
    gate_use_futures  = st.checkbox("Require futures score agreement", value=True)
    
    st.markdown("**🧭 OI Flip Meter**")
    meter_window_strikes = st.slider("Strikes each side of spot", 2, 12, 6, 1)
    meter_flip_threshold = st.slider("Flip strength threshold (±)", 10, 60, 20, 5)
    meter_flip_lookback  = st.slider("Flip look-back / validity (min)", 10, 90, 30, 5)
    gate_flip_override   = st.checkbox("Confirmed OI flip overrides hold-time", value=True)

    if st.button("🔄 Reset locked signals"):
        for _k in [k for k in list(st.session_state.keys()) if str(k).startswith("gate_state_")]:
            del st.session_state[_k]

# ==============================
# API & INSTRUMENT MASTER
# ==============================
def api_get(path, params):
    r = requests.get("https://api.upstox.com" + path, params=params, headers=HEADERS, timeout=15)
    try:
        return r.json()
    except Exception:
        return {"status": "error", "errors": [{"message": r.text[:300]}]}

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

# Auto-select nearest
fut = futs[0]
FUT_KEY = fut["key"]
LOT_SIZE = fut.get("lot_size", 10)

opt_expiries = sorted({i["expiry"] for i in ins if i["type"] in ("CE", "PE") and i["underlying_key"] == FUT_KEY and i["expiry"] >= today_iso})
opt_expiry = opt_expiries[0] if opt_expiries else None

# ==============================
# DATA FETCHING
# ==============================
def fetch_price():
    j = api_get("/v2/market-quote/quotes", {"instrument_key": FUT_KEY})
    if j.get("status") == "success" and j.get("data"):
        q = next(iter(j["data"].values()))
        last = q.get("last_price") or 0
        chg = q.get("net_change") or 0
        ohlc = q.get("ohlc") or {}
        prev = round(last - chg, 2) if last else (ohlc.get("close") or 0)
        pct = (chg / prev * 100) if prev else 0
        return {"ltp": last, "chg": chg, "pct": pct, "prev": prev, "open": ohlc.get("open"), "high": ohlc.get("high"), "low": ohlc.get("low")}
    return None

@st.cache_data(ttl=300)
def fetch_ema_20(fut_key):
    try:
        j = api_get(f"/v2/historical-candle/intraday/{quote(fut_key, safe='')}/5minute", {})
        if j.get("status") == "success":
            candles = j.get("data", {}).get("candles", [])
            if len(candles) >= 20:
                df = pd.DataFrame(candles, columns=["timestamp", "open", "high", "low", "close", "volume", "oi"])
                df = df.iloc[::-1]
                df["ema_20"] = df["close"].ewm(span=20, adjust=False).mean()
                return df["ema_20"].iloc[-1]
    except: pass
    return None

price = fetch_price()
if not price:
    st.error("Could not fetch CRUDEOILM price.")
    st.stop()

spot = price["ltp"]
ema_20 = fetch_ema_20(FUT_KEY)

def fetch_option_chain(instrument_key, expiry_date):
    return api_get('/v2/option/chain', {'instrument_key': instrument_key, 'expiry_date': expiry_date})

def parse_greeks_by_strike(option_chain_response):
    greeks_map = {}
    if option_chain_response.get("status") != "success": return greeks_map
    for item in option_chain_response.get("data", []):
        strike = item.get("strike_price")
        if strike is None: continue
        call_g = (item.get("call_options") or {}).get("option_greeks") or {}
        put_g  = (item.get("put_options")  or {}).get("option_greeks") or {}
        greeks_map[strike] = {
            "call_delta": call_g.get("delta", 0), "call_gamma": call_g.get("gamma", 0),
            "call_theta": call_g.get("theta", 0), "call_vega":  call_g.get("vega", 0), "call_iv": call_g.get("iv", 0),
            "put_delta":  put_g.get("delta", 0),  "put_gamma":  put_g.get("gamma", 0),
            "put_theta":  put_g.get("theta", 0),  "put_vega":   put_g.get("vega", 0),  "put_iv":  put_g.get("iv", 0),
        }
    return greeks_map

opt_chain_raw = fetch_option_chain(FUT_KEY, opt_expiry)
greeks_by_strike = parse_greeks_by_strike(opt_chain_raw)

def _fetch_prev_oi(key, day_iso):
    frm = (dt.date.fromisoformat(day_iso) - dt.timedelta(days=10)).isoformat()
    j = api_get(f"/v2/historical-candle/{quote(key, safe='')}/day/{day_iso}/{frm}", {})
    if j.get("status") != "success": return False, None
    for c in (j.get("data") or {}).get("candles") or []:
        if str(c[0])[:10] < day_iso and len(c) > 6 and c[6] is not None:
            return True, c[6]
    return True, None

def fetch_oi_data():
    rows = []
    if not opt_chain_raw or opt_chain_raw.get("status") != "success":
        return []
    
    cache = st.session_state.setdefault("prev_oi", {})
    
    for item in opt_chain_raw.get("data", []):
        strike = item.get("strike_price")
        c = item.get("call_options") or {}
        p = item.get("put_options") or {}
        cm = c.get("market_data") or {}
        pm = p.get("market_data") or {}
        
        c_oi = cm.get("oi") or 0
        p_oi = pm.get("oi") or 0
        
        c_key = c.get("instrument_key")
        p_key = p.get("instrument_key")
        
        c_prev = cache.get((c_key, today_iso))
        if c_key and c_prev is None:
            ok, v = _fetch_prev_oi(c_key, today_iso)
            if ok: cache[(c_key, today_iso)] = v
            c_prev = v
            
        p_prev = cache.get((p_key, today_iso))
        if p_key and p_prev is None:
            ok, v = _fetch_prev_oi(p_key, today_iso)
            if ok: cache[(p_key, today_iso)] = v
            p_prev = v
            
        c_chg = c_oi - c_prev if c_prev is not None else 0
        p_chg = p_oi - p_prev if p_prev is not None else 0
        
        rows.append({
            "strike_price": strike,
            "call_oi": c_oi, "put_oi": p_oi,
            "call_change_oi": c_chg, "put_change_oi": p_chg
        })
    return rows

oi_data = fetch_oi_data()

def compute_flow_score():
    keys = [f["key"] for f in futs]
    j = api_get("/v2/market-quote/quotes", {"instrument_key": ",".join(keys)})
    if j.get("status") != "success": return 0.0
    q = {v.get("instrument_token"): v for v in (j.get("data") or {}).values()}
    cache = st.session_state.setdefault("prev_oi", {})
    wsum, wtot = 0.0, 0.0
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
        if chg_abs > 1e7 and price_pct < -0.3: score = -0.9
        elif chg_abs > 1e7 and price_pct > 0.3: score = 0.9
        elif oi_pct > 30 and price_pct < -0.3: score = -0.6
        elif oi_pct > 10 and price_pct < -0.5: score = -0.4
        elif oi_pct > 10 and price_pct > 0.5: score = 0.4
        weight = cur_val / 1e9
        wsum += score * weight
        wtot += weight
    return max(-1, min(1, wsum / wtot)) if wtot else 0.0

macro_score = compute_flow_score()

# ==============================
# CORE LOGIC FUNCTIONS
# ==============================
def compute_greeks_confidence(entry_type, greeks):
    if not greeks: return 40.0, True, ["⚪ No Greeks data"]
    notes = []
    if entry_type == "HIGH PUT":
        delta, gamma, theta, iv = abs(greeks.get("put_delta", 0)), greeks.get("put_gamma", 0), greeks.get("put_theta", 0), greeks.get("put_iv", 0)
    else:
        delta, gamma, theta, iv = abs(greeks.get("call_delta", 0)), greeks.get("call_gamma", 0), greeks.get("call_theta", 0), greeks.get("call_iv", 0)
    
    delta_ok = 0.15 <= delta <= 0.75
    delta_score = max(0, 100 - abs(delta - 0.45) * 150)
    gamma_score = min(100, gamma * 5000)
    theta_penalty = min(30, max(0, -theta))
    confidence = round(max(0, min(100, 0.55 * delta_score + 0.35 * gamma_score - 0.10 * theta_penalty)), 1)
    return confidence, delta_ok, notes

def get_entry_signal_from_change_oi(change_oi_list, spot_price, buffer_points=27, greeks_map=None, max_candidates=5):
    if not change_oi_list: return None
    ranked = []
    for item in change_oi_list:
        call_oi = item.get("call_change_oi", 0)
        put_oi = item.get("put_change_oi", 0)
        ranked.append((abs(put_oi - call_oi), item, call_oi, put_oi))
    ranked.sort(key=lambda x: x[0], reverse=True)

    best_item, best_diff = None, -1
    best_call_oi = best_put_oi = 0
    best_conf, best_delta_ok = 40.0, True

    for diff, item, call_oi, put_oi in ranked[:max_candidates]:
        high_type = "HIGH PUT" if put_oi > call_oi else "HIGH CALL"
        strike = item["strike_price"]
        greeks = greeks_map.get(strike) if greeks_map else None
        conf, delta_ok, _ = compute_greeks_confidence(high_type, greeks)
        if delta_ok:
            best_item, best_diff, best_call_oi, best_put_oi = item, diff, call_oi, put_oi
            best_conf, best_delta_ok = conf, delta_ok
            break
        elif best_item is None:
            best_item, best_diff, best_call_oi, best_put_oi = item, diff, call_oi, put_oi
            best_conf, best_delta_ok = conf, delta_ok

    if best_item is None: return None
    strike = best_item["strike_price"]
    high_type = "HIGH PUT" if best_put_oi > best_call_oi else "HIGH CALL"
    if high_type == "HIGH PUT":
        trigger_price = strike + buffer_points
        signal = "BUY"
        reason = f"Support at {strike} (Put ΔOI > Call ΔOI). Trigger at {trigger_price}"
    else:
        trigger_price = strike - buffer_points
        signal = "SELL"
        reason = f"Resistance at {strike} (Call ΔOI > Put ΔOI). Trigger at {trigger_price}"

    active = (signal == "BUY" and spot_price >= trigger_price) or (signal == "SELL" and spot_price <= trigger_price)
    _others = [r[0] for r in ranked if r[1] is not best_item]
    _second = _others[0] if _others else 0
    dominance = (best_diff / _second) if _second > 0 else 99.0
    stop_loss = (strike - gate_sl_buffer) if signal == "BUY" else (strike + gate_sl_buffer)

    return {
        "strike": strike, "high_type": high_type, "signal": signal, "trigger_price": trigger_price,
        "active": active, "reason": f"{reason} | SL {stop_loss:,.0f}", "call_oi": best_call_oi,
        "put_oi": best_put_oi, "oi_diff": best_diff, "dominance": dominance, "stop_loss": stop_loss,
        "greeks": greeks_map.get(strike) if greeks_map else None,
        "greeks_confidence": best_conf, "delta_ok": best_delta_ok,
    }

def get_exit_signal_from_change_oi(change_oi_list, spot_price, entry_signal, buffer_points=27, min_gap=100, greeks_map=None):
    if not change_oi_list: return None
    opposite_high_type = "HIGH CALL" if entry_signal["signal"] == "BUY" else "HIGH PUT"
    best_item, best_diff = None, -1
    for item in change_oi_list:
        call_oi = item.get("call_change_oi", 0)
        put_oi = item.get("put_change_oi", 0)
        high_type = "HIGH PUT" if put_oi > call_oi else "HIGH CALL"
        if high_type == opposite_high_type:
            diff = abs(put_oi - call_oi)
            if diff > best_diff: best_diff, best_item = diff, item
    if best_item is None: return None
    strike = best_item["strike_price"]
    if opposite_high_type == "HIGH PUT":
        trigger_price = strike + buffer_points
        exit_signal_type = "BUY"
    else:
        trigger_price = strike - buffer_points
        exit_signal_type = "SELL"
    if abs(entry_signal["trigger_price"] - trigger_price) < min_gap: return None
    active = (entry_signal["signal"] == "BUY" and spot_price >= trigger_price) or (entry_signal["signal"] == "SELL" and spot_price <= trigger_price)
    return {
        "strike": strike, "high_type": opposite_high_type, "signal": exit_signal_type, "trigger_price": trigger_price,
        "active": active, "reason": f"Exit {exit_signal_type} at {strike}", "call_oi": best_item.get("call_change_oi", 0),
        "put_oi": best_item.get("put_change_oi", 0), "oi_diff": best_diff, "greeks": greeks_map.get(strike) if greeks_map else None,
    }

# Gate Logic
def _fmt_t(dt_obj): return dt_obj.strftime("%H:%M:%S") if dt_obj else "—"
def _in_trade_window(now_dt, allow_opening=False):
    if now_dt.weekday() >= 5: return False, "Weekend — market closed"
    t = now_dt.time()
    if t < dt.time(9, 0) or t > dt.time(23, 30): return False, "Market closed"
    if not gate_time_filter: return True, "Market open"
    if t < dt.time(9, 15) and not allow_opening: return False, "Opening 15 min"
    if t > dt.time(23, 0): return False, "Last 30 min"
    return True, "Inside trading window"

def _beyond_trigger(sig, trig, spot): return (sig == "BUY" and spot >= trig) or (sig == "SELL" and spot <= trig)
def entry_status_text(sig): return sig.get("status_label") or ("ACTIVE" if sig.get("active") else "PENDING")

def apply_signal_gate(index_name, entry, spot_price, macro_score, flip=None):
    key = f"gate_state_{index_name}"
    now_dt = dt.datetime.now(IST) # FIXED HERE
    today_key = now_dt.strftime("%Y-%m-%d")
    state = st.session_state.get(key)
    if not state or state.get("date") != today_key:
        state = {"date": today_key, "cand_dir": None, "cand_since": None, "cross_since": None, "locked": None, "event": ""}
    status = {"verdict": "NONE", "checks": [], "time_label": "—", "warning": "", "event": state.get("event", "")}
    
    hist_key = f"gate_hist_{index_name}"
    hist = st.session_state.get(hist_key, [])
    hist.append((now_dt, macro_score))
    hist = [h for h in hist if (now_dt - h[0]).total_seconds() <= 900]
    st.session_state[hist_key] = hist
    ref = next((sc for t, sc in hist if (now_dt - t).total_seconds() <= 300), None)
    trend_txt = f", {macro_score - ref:+.2f} vs ~5 min ago" if (ref is not None and len(hist) > 1) else ""

    flip_dir = (flip or {}).get("flip")
    flip_sig = {"BULLISH": "BUY", "BEARISH": "SELL"}.get(flip_dir)

    locked = state.get("locked")
    if locked:
        sig = locked["signal"]
        stopped = (sig == "BUY" and spot_price <= locked["stop_loss"]) or (sig == "SELL" and spot_price >= locked["stop_loss"])
        flip_release = bool(gate_flip_override and flip_sig and flip_sig != sig)
        if stopped or flip_release:
            state["event"] = f"🛑 {sig} signal hit stop-loss or flip at {_fmt_t(now_dt)}"
            state.update({"locked": None, "cand_dir": None, "cand_since": None, "cross_since": None})
            locked = None
        else:
            out = dict(locked)
            beyond = _beyond_trigger(sig, out["trigger_price"], spot_price)
            out["active"] = beyond
            out["status_label"] = "🔒 CONFIRMED & ACTIVE" if beyond else "🔒 LOCKED — price back inside trigger"
            status.update({"verdict": "LOCKED", "time_label": f"Locked {_fmt_t(out['confirmed_at'])}", "event": state.get("event", "")})
            status["checks"] = [(True, f"Locked at {_fmt_t(out['confirmed_at'])} — ignores re-ranking")]
            st.session_state[key] = state
            return out, status

    if not entry:
        state.update({"cand_dir": None, "cand_since": None, "cross_since": None})
        status["event"] = state.get("event", "")
        st.session_state[key] = state
        return None, status

    sig = entry["signal"]
    if state["cand_dir"] != sig: state.update({"cand_dir": sig, "cand_since": now_dt, "cross_since": None})
    if _beyond_trigger(sig, entry["trigger_price"], spot_price):
        if state["cross_since"] is None: state["cross_since"] = now_dt
    else: state["cross_since"] = None

    held_s = (now_dt - state["cand_since"]).total_seconds()
    cross_s = (now_dt - state["cross_since"]).total_seconds() if state["cross_since"] else 0.0
    checks = []
    flip_ok = bool(gate_flip_override and flip_sig and flip_sig == sig)
    held_ok = held_s >= gate_hold_min * 60
    checks.append((held_ok or flip_ok, f"Signal held {held_s/60:.1f} / {gate_hold_min} min"))
    checks.append((state["cross_since"] is not None and cross_s >= gate_price_min * 60, f"Price beyond trigger for {cross_s/60:.1f} / {gate_price_min} min"))
    if gate_use_futures:
        agree = (macro_score >= gate_min_score) if sig == "BUY" else (macro_score <= -gate_min_score)
        checks.append((agree, f"Futures flow score {macro_score:+.2f}{trend_txt}"))
    dom = entry.get("dominance", 99.0)
    checks.append((dom >= gate_min_dom, f"Key strike dominance {min(dom, 99):.1f}x"))
    dist_pct = abs(entry["strike"] - spot_price) / spot_price * 100 if spot_price else 0
    checks.append((dist_pct <= gate_max_dist_pct, f"Key strike {dist_pct:.2f}% from spot"))
    checks.append((entry.get("delta_ok", True), "Strike passes Delta relevance filter"))
    win_ok, win_txt = _in_trade_window(now_dt, allow_opening=flip_ok)
    checks.append((win_ok, win_txt))

    passed = sum(1 for ok, _ in checks if ok)
    status["checks"] = checks

    if passed == len(checks):
        locked_entry = dict(entry)
        locked_entry["confirmed_at"] = now_dt
        state["locked"] = locked_entry
        state["event"] = f"✅ {sig} confirmed at {_fmt_t(now_dt)}"
        out = dict(locked_entry)
        out["active"] = True
        out["status_label"] = "🔒 CONFIRMED & ACTIVE"
        status.update({"verdict": "CONFIRMED", "time_label": f"Locked {_fmt_t(now_dt)}", "event": state["event"]})
    else:
        out = dict(entry)
        out["active"] = False
        out["status_label"] = f"⏳ WAITING — {passed}/{len(checks)} checks passed"
        out["reason"] = f"{out['reason']} | NOT CONFIRMED"
        status.update({"verdict": "WAITING", "time_label": f"First seen {_fmt_t(state['cand_since'])}", "event": state.get("event", "")})

    st.session_state[key] = state
    return out, status

def compute_oi_flip_meter(index_name, change_oi_list, spot_price, greeks_map):
    now_dt = dt.datetime.now(IST) # FIXED HERE
    res = {"available": False, "score": 0.0, "state": "NO DATA", "flip": None, "flip_since": None, "flip_from": None, "msg": "", "atm": None, "history": [], "n_strikes": 0}
    if spot_price <= 0 or not change_oi_list:
        res["msg"] = "Change-in-OI data not available."
        return res

    rows = sorted(change_oi_list, key=lambda x: x["strike_price"])
    strikes = [r["strike_price"] for r in rows]
    atm_idx = min(range(len(strikes)), key=lambda i: abs(strikes[i] - spot_price))
    lo, hi = max(0, atm_idx - meter_window_strikes), min(len(rows), atm_idx + meter_window_strikes + 1)
    window = rows[lo:hi]
    greeks_map = greeks_map or {}

    use_gamma = any(((greeks_map.get(r["strike_price"]) or {}).get("call_gamma") or (greeks_map.get(r["strike_price"]) or {}).get("put_gamma")) for r in window)
    P = C = 0.0
    for i, r in enumerate(window):
        g = greeks_map.get(r["strike_price"]) or {}
        dist = abs((lo + i) - atm_idx)
        wc = g.get("call_gamma") or 0 if use_gamma else 1.0 / (1 + dist)
        wp = g.get("put_gamma") or 0 if use_gamma else 1.0 / (1 + dist)
        P += r.get("put_change_oi", 0) * wp
        C += r.get("call_change_oi", 0) * wc
    denom = abs(P) + abs(C)
    score = ((P - C) / denom * 100.0) if denom > 0 else 0.0

    hist_key = f"meter_hist_{index_name}"
    hist = st.session_state.get(hist_key, [])
    hist.append((now_dt, score))
    hist = [h for h in hist if (now_dt - h[0]).total_seconds() <= 5400]
    st.session_state[hist_key] = hist

    thr = meter_flip_threshold
    recent = [sc for _, sc in hist[-3:]]
    older = [sc for t, sc in hist[:-3] if (now_dt - t).total_seconds() <= meter_flip_lookback * 60]
    new_flip, from_val = None, None
    if len(recent) == 3 and older:
        if all(sc >= thr for sc in recent) and any(sc <= -thr for sc in older): new_flip, from_val = "BULLISH", min(older)
        elif all(sc <= -thr for sc in recent) and any(sc >= thr for sc in older): new_flip, from_val = "BEARISH", max(older)

    fkey = f"gate_state_flip_{index_name}"
    fstate = st.session_state.get(fkey)
    if fstate:
        age = (now_dt - fstate["since"]).total_seconds()
        crossed_back = (fstate["dir"] == "BULLISH" and score < 0) or (fstate["dir"] == "BEARISH" and score > 0)
        if age > meter_flip_lookback * 60 or crossed_back: fstate = None
    if new_flip and (not fstate or fstate["dir"] != new_flip):
        fstate = {"dir": new_flip, "since": now_dt, "from": from_val}
    st.session_state[fkey] = fstate

    if fstate:
        res["flip"], res["flip_since"], res["flip_from"] = fstate["dir"], fstate["since"], fstate.get("from")
        res["state"] = f"🔄 {fstate['dir']} FLIP"
    elif score >= thr: res["state"] = "BULLISH"
    elif score <= -thr: res["state"] = "BEARISH"
    else: res["state"] = "NEUTRAL"

    g = greeks_map.get(strikes[atm_idx]) or {}
    cg, pg = g.get("call_iv"), g.get("put_iv")
    res.update({
        "available": True, "score": score, "n_strikes": len(window),
        "history": [sc for _, sc in hist][-120:],
        "atm": {"strike": strikes[atm_idx], "call_delta": g.get("call_delta"), "put_delta": g.get("put_delta"),
                "gamma": g.get("call_gamma") or g.get("put_gamma"), "call_theta": g.get("call_theta"),
                "put_theta": g.get("put_theta"), "vega": g.get("call_vega") or g.get("put_vega"),
                "call_iv": cg, "put_iv": pg, "skew": (pg - cg) if (cg is not None and pg is not None) else None}
    })
    return res

# ==============================
# RUN LOGIC
# ==============================
oi_meter = compute_oi_flip_meter("Crude", oi_data, spot, greeks_by_strike)
entry_signal_raw = get_entry_signal_from_change_oi(oi_data, spot, buffer_pts, greeks_by_strike)
exit_signal_raw = get_exit_signal_from_change_oi(oi_data, spot, entry_signal_raw, buffer_pts, min_gap, greeks_by_strike) if entry_signal_raw else None
entry_signal, gate = apply_signal_gate("Crude", entry_signal_raw, spot, macro_score, oi_meter)
if not entry_signal: exit_signal_raw = None

# Code 4 (OI Prediction Model)
def compute_oi_prediction(oi_list, spot_price, change_list, macro_flow):
    if not oi_list: return {"direction": "NEUTRAL", "target": 0, "stop_loss": 0, "confidence": 0, "bull_votes": 0, "bear_votes": 0, "max_pain": 0, "resistance": 0, "support": 0, "pcr": 0, "net_call_change": 0, "net_put_change": 0, "max_call_change_strike": None, "max_put_change_strike": None, "macro_flow_score": macro_flow}
    tc, tp = sum(i["call_oi"] for i in oi_list), sum(i["put_oi"] for i in oi_list)
    pcr = tp / tc if tc else 1.0
    max_c, max_p = max(oi_list, key=lambda x: x["call_oi"])["strike_price"], max(oi_list, key=lambda x: x["put_oi"])["strike_price"]
    
    strikes = [i["strike_price"] for i in oi_list]
    best, min_pain = strikes[0], float('inf')
    for s in strikes:
        pain = sum(i["call_oi"] * max(s - i["strike_price"], 0) + i["put_oi"] * max(i["strike_price"] - s, 0) for i in oi_list)
        if pain < min_pain: min_pain, best = pain, s
    max_pain = best

    net_c_chg, net_p_chg = 0, 0
    max_c_chg_st, max_p_chg_st = None, None
    max_c_chg_v, max_p_chg_v = 0, 0
    if change_list:
        for i in change_list:
            ccoi, pcoi = i.get("call_change_oi", 0), i.get("put_change_oi", 0)
            net_c_chg += ccoi; net_p_chg += pcoi
            if ccoi > max_c_chg_v: max_c_chg_v, max_c_chg_st = ccoi, i["strike_price"]
            if pcoi > max_p_chg_v: max_p_chg_v, max_p_chg_st = pcoi, i["strike_price"]

    bull, bear = 0, 0
    if spot_price > max_pain: bear += 1
    elif spot_price < max_pain: bull += 1
    if pcr > 1.5: bear += 1
    elif pcr < 0.7: bull += 1
    if spot_price > max_c: bull += 1
    elif spot_price < max_p: bear += 1
    if net_c_chg > net_p_chg: bull += 1
    elif net_p_chg > net_c_chg: bear += 1
    if max_c_chg_st and spot_price < max_c_chg_st: bear += 1
    if max_p_chg_st and spot_price > max_p_chg_st: bull += 1
    if macro_flow > 0.3: bull += 1
    elif macro_flow < -0.3: bear += 1

    direction = "BULLISH" if bull > bear else "BEARISH" if bear > bull else "NEUTRAL"
    
    if direction == "BULLISH":
        target = max([t for t in [max_pain, max_c_chg_st] if t and t > spot_price] or [spot_price * 1.005])
        sl = max([s for s in [max_p, max_p_chg_st] if s and s < spot_price] or [spot_price * 0.995])
    elif direction == "BEARISH":
        target = min([t for t in [max_pain, max_p_chg_st] if t and t < spot_price] or [spot_price * 0.995])
        sl = min([r for r in [max_c, max_c_chg_st] if r and r > spot_price] or [spot_price * 1.005])
    else: target, sl = (max_c + max_p) / 2, spot_price

    oi_conc = max(tc, tp) / (tc + tp + 1e-6)
    pcr_ext = abs(pcr - 1.0)
    chg_rat = abs(net_c_chg - net_p_chg) / (tc + tp + 1e-6) if (tc + tp) > 0 else 0
    conf = min(100, 30 + 20 * oi_conc + 20 * pcr_ext + 15 * min(chg_rat, 1) + 15 * abs(macro_flow))

    return {"direction": direction, "target": target, "stop_loss": sl, "confidence": conf, "bull_votes": bull, "bear_votes": bear, "max_pain": max_pain, "resistance": max_c, "support": max_p, "pcr": pcr, "net_call_change": net_c_chg, "net_put_change": net_p_chg, "max_call_change_strike": max_c_chg_st, "max_put_change_strike": max_p_chg_st, "macro_flow_score": macro_flow}

oi_prediction = compute_oi_prediction(oi_data, spot, oi_data, macro_score)

# ==============================
# UI RENDERING
# ==============================
st.title("🛢️ CRUDEOILM Analytics & Strategy Suite — Pro")

c1, c2, c3, c4 = st.columns([2, 1, 1, 1.5])
with c1:
    st.markdown(f"""<div class="market-box"><div style="color:#666">CRUDEOILM (Fut)</div>
      <div style="font-size:2rem;font-weight:800">{spot:,.2f}</div>
      <div class="{'pos' if price['chg']>0 else 'neg'}">{'▲' if price['chg']>0 else '▼'} {price['chg']:+,.2f} ({price['pct']:+.2f}%)</div>
      <div style="font-size:.8rem;color:#888">Prev: {price['prev']:,.2f}</div></div>""", unsafe_allow_html=True)
with c2:
    st.markdown(f"""<div class="market-box"><div style="color:#666">Day High</div><div style="font-size:1.2rem;font-weight:bold">{(price['high'] or 0):,.2f}</div></div>""", unsafe_allow_html=True)
with c3:
    st.markdown(f"""<div class="market-box"><div style="color:#666">Day Low</div><div style="font-size:1.2rem;font-weight:bold">{(price['low'] or 0):,.2f}</div></div>""", unsafe_allow_html=True)
with c4:
    is_below_open = spot < price["open"] if price["open"] else False
    t_color = "bearish" if is_below_open else "bullish"
    t_text = "BEARISH" if is_below_open else "BULLISH"
    ema_str = f"{ema_20:,.2f}" if ema_20 else "N/A"
    open_str = f"{price['open']:,.2f}" if price['open'] else "N/A"
    st.markdown(f"""<div class="prediction-card {t_color}" style="padding:10px;margin-bottom:0;border-radius:12px;"><div style="opacity:.8">Intraday Trend</div>
      <div style="font-size:1.2rem;font-weight:800">{t_text}</div>
      <div style="font-size:.85rem">Open: {open_str} | EMA: {ema_str}</div></div>""", unsafe_allow_html=True)

st.markdown("---")

# Render OI Meter
if oi_meter.get("available"):
    score, thr = oi_meter["score"], meter_flip_threshold
    color = "#2e7d32" if score >= thr else ("#c62828" if score <= -thr else "#f9a825")
    pos = max(0.0, min(100.0, (score + 100) / 2))
    atm = oi_meter["atm"]
    flip_html = ""
    if oi_meter.get("flip"):
        arrow = "🟢" if oi_meter["flip"] == "BULLISH" else "🔴"
        flip_html = f'<div style="margin-top:8px; font-weight:bold;">{arrow} {oi_meter["flip"]} FLIP — OI bias swung to {score:+.0f}</div>'
    
    items = [("Δ Call/Put", f"{atm['call_delta'] or 0:.2f} / {atm['put_delta'] or 0:.2f}"), ("Γ Gamma", f"{atm['gamma'] or 0:.5f}"), ("Θ Theta C/P", f"{atm['call_theta'] or 0:.1f} / {atm['put_theta'] or 0:.1f}"), ("V Vega", f"{atm['vega'] or 0:.2f}"), ("IV Call/Put", f"{atm['call_iv'] or 0:.1f}% / {atm['put_iv'] or 0:.1f}%")]
    greeks_html = "".join(f'<span style="margin-right:18px;">{k}: <b>{v}</b></span>' for k, v in items)
    
    st.markdown(f'''
        <div class="greeks-panel" style="border-left-color: {color};">
        <b>🧭 CRUDEOILM OI Flip Meter</b> &nbsp;|&nbsp; <b>{oi_meter["state"]}</b> &nbsp;|&nbsp; 
        Live: <b>{spot:,.2f}</b> &nbsp;|&nbsp; ATM strike: <b>{atm["strike"]:,.0f}</b>
        <div style="position:relative; height:14px; border-radius:7px; margin:16px 4px 4px 4px; background:linear-gradient(90deg,#c62828 0%,#f9a825 50%,#2e7d32 100%);">
        <div style="position:absolute; left:{pos:.1f}%; top:-5px; width:4px; height:24px; background:#000; border-radius:2px;"></div></div>
        <div style="display:flex; justify-content:space-between; font-size:0.75rem; color:#555;">
        <span>−100 Bearish</span><span>Score {score:+.0f}</span><span>Bullish +100</span></div>
        {flip_html}
        <div style="margin-top:8px; font-size:0.9rem;">ATM Greeks @ {atm["strike"]:,.0f}: {greeks_html}</div>
        </div>''', unsafe_allow_html=True)

# Render Gate
if gate.get("verdict") != "NONE":
    color = {"CONFIRMED": "#2e7d32", "LOCKED": "#2e7d32", "WAITING": "#f9a825"}.get(gate["verdict"], "#6e7781")
    title = {"CONFIRMED": "✅ CONFIRMED — signal locked", "LOCKED": "🔒 LOCKED SIGNAL", "WAITING": "⏳ WAITING FOR CONFIRMATION"}.get(gate["verdict"], gate["verdict"])
    rows = "".join(f"<div>{'✅' if ok else '❌'} {txt}</div>" for ok, txt in gate["checks"])
    extra = f'<div style="margin-top:6px; font-size:0.85rem;">{gate["event"]}</div>' if gate.get("event") else ""
    st.markdown(f'<div class="greeks-panel" style="border-left-color: {color};"><b>🛡️ Entry Gate — {title}</b><div style="margin-top:6px; font-size:0.9rem;">{rows}</div>{extra}</div>', unsafe_allow_html=True)

# Code 1 Entry/Exit
st.subheader("📊 Code 1 — CRUDEOILM OI Change Entry Signal")
if entry_signal:
    sig = entry_signal["signal"]
    active = entry_signal["active"]
    emoji = "🟢" if sig == "BUY" else "🔴"
    status_text = entry_status_text(entry_signal)
    bg_color = "#2e7d32" if active and sig=="BUY" else ("#c62828" if active and sig=="SELL" else "#f9a825")
    text_color = "white" if active else "black"
    border_color = "#2e7d32" if sig=="BUY" else "#c62828"
    st.markdown(f'''
    <div class="entry-box" style="background: {bg_color}; border-left-color: {border_color}; color: {text_color};">
    <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap;">
    <div><span style="font-size: 1.8rem; font-weight: 800;">{emoji} {sig} ENTRY</span>
    <span style="margin-left: 15px; font-size: 1.2rem;">at {entry_signal['trigger_price']:,.2f}</span>
    <span style="margin-left: 15px; background: rgba(0,0,0,0.15); padding: 2px 10px; border-radius: 20px;">{entry_signal['high_type']}</span></div>
    <div style="font-weight: bold;"><span class="status-text" style="background: rgba(0,0,0,0.3); padding: 2px 10px; border-radius: 8px;">{status_text}</span></div></div>
    <div style="margin-top: 8px; font-size: 0.95rem; opacity: 0.9;"><span>📊 Current: <b>{spot:,.2f}</b> | Strike: <b>{entry_signal['strike']}</b> | OI Diff: <b>{entry_signal['oi_diff']:,.0f}</b></span>
    <span style="margin-left: 20px;">📌 {entry_signal['reason']}</span></div></div>''', unsafe_allow_html=True)
    
    if entry_signal.get("greeks"):
        g = entry_signal["greeks"]
        leg = "PUT" if entry_signal["high_type"] == "HIGH PUT" else "CALL"
        delta = g.get(f"{leg.lower()}_delta", 0)
        gamma = g.get(f"{leg.lower()}_gamma", 0)
        theta = g.get(f"{leg.lower()}_theta", 0)
        vega = g.get(f"{leg.lower()}_vega", 0)
        iv = g.get(f"{leg.lower()}_iv", 0)
        conf = entry_signal.get("greeks_confidence", 0)
        color = "#2e7d32" if conf >= 60 else "#f9a825"
        badge = "badge-pass" if entry_signal.get("delta_ok") else "badge-weak"
        st.markdown(f'''
        <div class="greeks-panel" style="border-left-color: {color};">
        <b>{leg} Greeks @ {entry_signal['strike']}</b> &nbsp;|&nbsp; <span class="{badge}">{'✅ PASSES DELTA' if entry_signal.get('delta_ok') else '⚠️ WEAK DELTA'}</span>
        <div style="display:flex; gap:20px; margin-top:6px; font-size:0.9rem; flex-wrap:wrap;">
        <span class="greek-item">Δ Delta: <b>{delta:.3f}</b></span><span class="greek-item">Γ Gamma: <b>{gamma:.5f}</b></span>
        <span class="greek-item">Θ Theta: <b>{theta:.2f}</b></span><span class="greek-item">V Vega: <b>{vega:.2f}</b></span>
        <span class="greek-item">IV: <b>{iv:.1f}%</b></span><span class="greek-item">Confidence: <b>{conf:.0f}%</b></span></div></div>''', unsafe_allow_html=True)
else:
    st.info("ℹ️ No entry signal (gap < min or no opposite OI).")

st.subheader("📊 Code 1 — CRUDEOILM OI Change Exit Signal")
if exit_signal_raw:
    sig = exit_signal_raw["signal"]
    active = exit_signal_raw["active"]
    emoji = "🟢" if sig == "BUY" else "🔴"
    status_text = "🎯 TARGET REACHED" if active else "PENDING"
    bg_color = "#2e7d32" if active and sig=="BUY" else ("#c62828" if active and sig=="SELL" else "#f9a825")
    text_color = "white" if active else "black"
    border_color = "#0277bd" if sig=="BUY" else "#d84315"
    st.markdown(f'''
    <div class="entry-box" style="background: {bg_color}; border-left-color: {border_color}; color: {text_color};">
    <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap;">
    <div><span style="font-size: 1.8rem; font-weight: 800;">{emoji} EXIT ({'BUY to cover' if sig=='BUY' else 'SELL to close'})</span>
    <span style="margin-left: 15px; font-size: 1.2rem;">at {exit_signal_raw['trigger_price']:,.2f}</span>
    <span style="margin-left: 15px; background: rgba(0,0,0,0.15); padding: 2px 10px; border-radius: 20px;">{exit_signal_raw['high_type']}</span></div>
    <div style="font-weight: bold;"><span class="status-text" style="background: rgba(0,0,0,0.3); padding: 2px 10px; border-radius: 8px;">{status_text}</span></div></div>
    <div style="margin-top: 8px; font-size: 0.95rem; opacity: 0.9;"><span>📊 Current: <b>{spot:,.2f}</b> | Strike: <b>{exit_signal_raw['strike']}</b> | OI Diff: <b>{exit_signal_raw['oi_diff']:,.0f}</b></span>
    <span style="margin-left: 20px;">📌 {exit_signal_raw['reason']}</span></div></div>''', unsafe_allow_html=True)
else:
    st.info("ℹ️ No exit signal available (opposite OI build-up not found or gap < min).")

st.markdown("---")

st.subheader("CRUDEOILM Open Interest Data")
if oi_data:
    df_oi = pd.DataFrame(oi_data)
    df_oi["OI Difference"] = (df_oi["put_oi"] - df_oi["call_oi"]).abs()
    df_oi = df_oi.sort_values("OI Difference", ascending=False).head(20).reset_index(drop=True)
    st.dataframe(df_oi.style.apply(lambda row: ["background-color: #ffd700; font-weight: bold; color: #000000;"] * len(row) if row.name < 5 else [""] * len(row), axis=1))
else:
    st.info("No OI data available.")

st.markdown("---")
st.subheader("📊 Prediction Models")
col2, col3, col4 = st.columns(3)

with col2:
    st.subheader("📊 Code 2 — Global Weighted")
    st.markdown(f'''
        <div class="prediction-box" style="min-height: 240px;">
        <div class="status-badge">ACTIVE</div>
        <p style="margin:0; opacity:0.8; font-size:0.9rem;">Weighted Sentiment</p>
        <h2 style="margin:5px 0; font-size:2rem;">NEUTRAL (0.00)</h2>
        <div style="display:flex; justify-content:center; gap:20px; margin-top:12px; font-weight:bold; font-size:1.1rem;">
        <span>🎯 Target: {spot:,.2f}</span><span>↕️ 0.00 pts</span></div>
        <div class="confidence-tag">Confidence: 40.0%</div></div>''', unsafe_allow_html=True)

with col3:
    st.subheader("⚖️ Code 3 — Signal Engine")
    direction = oi_prediction["direction"]
    card_class = "bullish" if direction == "BULLISH" else "bearish" if direction == "BEARISH" else "neutral"
    st.markdown(f'''
        <div class="prediction-card {card_class}" style="min-height:240px; padding:20px;">
        <div class="status-badge">FLOW</div>
        <h2 style="margin:0; font-size:2rem;">{direction}</h2>
        <div class="signal-score-bar">Score: {oi_prediction['bull_votes']} / {oi_prediction['bear_votes']}</div>
        <div class="price-large" style="font-size:2.1rem; margin:6px 0;">Target: {oi_prediction['target']:,.2f}</div>
        <div class="move-text" style="font-size:1.1rem; margin-bottom:5px;">Move: {oi_prediction['target'] - spot:+,.2f} pts</div>
        <div class="sl-badge" style="font-size:1rem; padding:4px 15px;">STOP LOSS: {oi_prediction['stop_loss']:,.2f}</div></div>''', unsafe_allow_html=True)

with col4:
    st.subheader("📊 Code 4 — OI Flow")
    oi_card_class = "bullish" if oi_prediction["direction"] == "BULLISH" else ("bearish" if oi_prediction["direction"] == "BEARISH" else "neutral")
    st.markdown(f'''
        <div class="prediction-card {oi_card_class}" style="min-height:240px; padding:20px;">
        <div class="status-badge">MACRO SCORE</div>
        <h2 style="margin:0; font-size:2rem;">{oi_prediction['direction']}</h2>
        <div style="margin:6px 0; font-size:0.9rem;">Max Pain: {oi_prediction['max_pain']:,.2f} | PCR: {oi_prediction['pcr']:.2f}</div>
        <div class="price-large" style="font-size:2.1rem; margin:6px 0;">Target: {oi_prediction['target']:,.2f}</div>
        <div style="font-size:0.9rem; margin-bottom:5px;">S: {oi_prediction['support']:,.2f} | R: {oi_prediction['resistance']:,.2f}</div>
        <div class="sl-badge" style="font-size:1rem; padding:4px 15px;">STOP: {oi_prediction['stop_loss']:,.2f}</div></div>''', unsafe_allow_html=True)
