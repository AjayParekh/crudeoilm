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
# TOKEN  (never hardcode it)
# Put in .streamlit/secrets.toml:  UPSTOX_TOKEN = "eyJ0eXAi..."
# or set env var UPSTOX_TOKEN, or paste in the sidebar.
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
    st.markdown("**OI Flow score**")
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
# INSTRUMENT MASTER (MCX) -> futures + option expiries
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
    st.error("No active CRUDEOILM futures found in the instrument file.")
    st.stop()

with st.sidebar:
    st.markdown("---")
    fut_labels = {f"{f['symbol']}  (exp {f['expiry']})": f for f in futs}
    fut = fut_labels[st.selectbox("Futures contract (price)", list(fut_labels.keys()), index=0)]

    opt_expiries = sorted({i["expiry"] for i in ins
                           if i["type"] in ("CE", "PE")
                           and i["underlying_key"] == fut["key"]
                           and i["expiry"] >= today_iso})
    if opt_expiries:
        opt_expiry = st.selectbox("Option expiry (OI / Greeks)", opt_expiries, index=0)
    else:
        opt_expiry = None
        st.warning("No option expiries found for this futures contract.")

FUT_KEY = fut["key"]

# ==============================
# PRICE  (Upstox quote, TradingView fallback)
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


price = get_price()

# ==============================
# OPTION CHAIN -> OI, change OI, Greeks
# 1) Upstox option-chain API
# 2) Fallback (if empty): instrument master + quotes + greeks + previous-day OI
# ==============================
def _chunks(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


def _fetch_prev_oi(key, day_iso):
    """(ok, OI at the last completed daily candle before day_iso)."""
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
        return None, "No CE/PE instruments with strike found for this expiry in the instrument file"
    by_strike = {}
    for o in opts:
        by_strike.setdefault(float(o["strike"]), {})[o["type"]] = o["key"]
    strikes = sorted(by_strike)

    # OI + LTP for every strike (bulk quotes)
    quotes = {}
    for ch in _chunks([o["key"] for o in opts], 300):
        j = api_get("/v2/market-quote/quotes", {"instrument_key": ",".join(ch)})
        if j.get("status") != "success":
            return None, "quotes error: " + json.dumps(j)[:400]
        for v in (j.get("data") or {}).values():
            quotes[v.get("instrument_token")] = v

    # window of strikes around price for Greeks + change in OI
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
        return None, f"Quotes returned zero OI for all {len(opts)} option contracts"
    return df, None


def get_chain():
    if not opt_expiry:
        return None, "No option expiry found", "none", ""
    df, raw = chain_from_option_api()
    if df is not None:
        return df, None, "Upstox option-chain API", raw
    df, err = chain_from_instruments(price["ltp"] if price else 0)
    return df, err, "Instrument master + quotes + prev-day OI", raw


chain, chain_err, chain_src, chain_raw = get_chain()


# ==============================
# CRUDEOILM OI FLOW – macro score (-1 to +1) across active futures contracts
# Same scoring idea as the Nifty flow: OI value change + price move, weighted by OI value.
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

    big = flow_big_cr * 1e7          # crore -> rupees
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
        if cur_val < 100_000_000:    # ignore tiny contracts
            continue

        score = 0.0
        if chg_abs > big and price_pct < -0.3:
            score = -0.9
        elif chg_abs > big and price_pct > 0.3:
            score = 0.9
        elif oi_pct > flow_pct * 3 and price_pct < -0.3:
            score = -0.6
        elif oi_pct > flow_pct and price_pct < -0.5:
            score = -0.4
        elif oi_pct > flow_pct and price_pct > 0.5:
            score = 0.4

        if oi_pct >= 0:
            label = "Long Buildup" if price_pct >= 0 else "Short Buildup"
        else:
            label = "Short Covering" if price_pct >= 0 else "Long Unwinding"

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
# ANALYTICS
# ==============================
def max_pain(df):
    best, low = None, float("inf")
    for s in df["strike"]:
        pain = ((s - df["strike"]).clip(lower=0) * df["call_oi"]).sum() + \
               ((df["strike"] - s).clip(lower=0) * df["put_oi"]).sum()
        if pain < low:
            best, low = s, pain
    return best


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
    if pcr > 1.3: bull += 1          # put-heavy = support
    elif pcr < 0.7: bear += 1
    if spot > res: bull += 1
    elif spot < sup: bear += 1
    if net_p > net_c: bull += 1
    elif net_c > net_p: bear += 1
    direction = "BULLISH" if bull > bear else "BEARISH" if bear > bull else "NEUTRAL"
    return dict(pcr=pcr, max_pain=mp, resistance=res, support=sup, net_c=net_c, net_p=net_p,
                bull=bull, bear=bear, direction=direction)


def greeks_for(row, high_type):
    side = "put" if high_type == "HIGH PUT" else "call"
    return {k: row[f"{side}_{k}"] for k in ("delta", "gamma", "theta", "vega", "iv")}


def entry_exit(df, spot, buffer, gap, lo, hi, max_candidates=5):
    d = df[df["has_chg"]].copy()
    if d.empty:
        return None, None
    d["diff"] = (d["put_chg"] - d["call_chg"]).abs()
    d["type"] = d.apply(lambda r: "HIGH PUT" if r["put_chg"] > r["call_chg"] else "HIGH CALL", axis=1)
    d = d[d["diff"] > 0].sort_values("diff", ascending=False)
    if d.empty:
        return None, None

    def mk(row, kind):
        strike = row["strike"]
        if row["type"] == "HIGH PUT":
            trig, sig = strike + buffer, "BUY"
            active = spot >= trig
            why = f"Support at {strike:g} (Put ΔOI > Call ΔOI). Trigger {trig:g}"
        else:
            trig, sig = strike - buffer, "SELL"
            active = spot <= trig
            why = f"Resistance at {strike:g} (Call ΔOI > Put ΔOI). Trigger {trig:g}"
        g = greeks_for(row, row["type"])
        return dict(strike=strike, type=row["type"], signal=sig, trigger=trig, active=active,
                    reason=why, diff=row["diff"], greeks=g,
                    delta_ok=(g["delta"] == 0) or (lo <= abs(g["delta"]) <= hi))

    cands = d.head(max_candidates)
    pick = None
    for _, r in cands.iterrows():
        e = mk(r, "entry")
        if e["delta_ok"]:
            pick = e
            break
        if pick is None:
            pick = e          # fallback: top OI-diff strike
    entry = pick

    opp = "HIGH CALL" if entry["signal"] == "BUY" else "HIGH PUT"
    o = d[d["type"] == opp]
    exit_ = None
    if not o.empty:
        ex = mk(o.iloc[0], "exit")
        if abs(ex["trigger"] - entry["trigger"]) >= gap:
            exit_ = ex
    if exit_ is None:
        return None, None
    return entry, exit_


def signal_box(title, s, spot, label):
    emoji = "🟢" if s["signal"] == "BUY" else "🔴"
    if s["active"]:
        bg, fg = ("#2e7d32", "white") if s["signal"] == "BUY" else ("#c62828", "white")
    else:
        bg, fg = "#f9a825", "black"
    status = "ACTIVE" if s["active"] else "PENDING (waiting for trigger)"
    g = s["greeks"]
    flt = "✅ passes delta filter" if s["delta_ok"] else "⚠️ outside delta band"
    st.markdown(f"""
    <div class="entry" style="background:{bg};color:{fg};border-left-color:{'#2e7d32' if s['signal']=='BUY' else '#c62828'}">
      <span style="font-size:1.5rem;font-weight:800">{emoji} {label} {s['signal']} @ {s['trigger']:,.2f}</span>
      <span class="pill" style="margin-left:10px">{s['type']}</span>
      <span class="pill">{status}</span><br>
      <span style="font-size:.9rem">Spot {spot:,.2f} | Key strike {s['strike']:g} | ΔOI diff {s['diff']:,.0f}<br>
      📌 {s['reason']}<br>
      Δ {g['delta']:.3f} · Γ {g['gamma']:.5f} · Θ {g['theta']:.2f} · V {g['vega']:.2f} · IV {g['iv']:.1f}% — {flt}</span>
    </div>""", unsafe_allow_html=True)


# ==============================
# UI
# ==============================
st.title("🛢️ CRUDEOILM Analytics — MCX")
lot = fut.get("lot_size")
st.markdown(
    f'<span class="pill">Futures: {fut["symbol"]}</span>'
    f'<span class="pill">Fut expiry: {fut["expiry"]}</span>'
    f'<span class="pill">Option expiry: {opt_expiry or "—"}</span>'
    f'<span class="pill">Lot: {lot if lot else "—"}</span>',
    unsafe_allow_html=True)

if not price:
    st.error("Could not fetch CRUDEOILM price.")
    st.stop()

spot = price["ltp"]
cls = "pos" if price["chg"] > 0 else "neg" if price["chg"] < 0 else ""
arrow = "▲" if price["chg"] > 0 else "▼" if price["chg"] < 0 else "—"

c1, c2, c3, c4 = st.columns(4)
with c1:
    st.markdown(f"""<div class="card"><div style="color:#666">CRUDEOILM (Fut) · {price['src']}</div>
      <div class="big">{spot:,.2f}</div>
      <div class="{cls}">{arrow} {price['chg']:+,.2f} ({price['pct']:+.2f}%)</div>
      <div style="font-size:.8rem;color:#888">Prev: {price['prev']:,.2f}</div></div>""", unsafe_allow_html=True)
with c2:
    st.markdown(f"""<div class="card"><div style="color:#666">Day range</div>
      <div style="font-size:1.1rem">O {price['open'] or 0:,.2f}<br>H {price['high'] or 0:,.2f}<br>L {price['low'] or 0:,.2f}</div></div>""",
                unsafe_allow_html=True)
with c3:
    st.markdown(f"""<div class="card"><div style="color:#666">Futures OI / Volume</div>
      <div style="font-size:1.1rem">OI {price['oi'] if price['oi'] is not None else '—'}<br>
      Vol {price['volume'] if price['volume'] is not None else '—'}</div></div>""", unsafe_allow_html=True)

if chain is None or chain.empty:
    st.error("Could not build the CRUDEOILM option chain.")
    with st.expander("Debug details (send me this if it still fails)", expanded=True):
        st.write("Futures key:", FUT_KEY, "| Option expiry:", opt_expiry)
        st.write("Option-chain API raw response:")
        st.code(chain_raw or "—")
        st.write("Fallback result:")
        st.code(chain_err or "—")
    st.stop()

st.caption(f"OI source: {chain_src} · expiry {opt_expiry}")
if not chain["has_chg"].any():
    st.warning("Change-in-OI is unavailable (previous-day OI not returned), so entry/exit signals are off.")
sig = oi_signal(chain, spot)
with c4:
    kls = {"BULLISH": "bullish", "BEARISH": "bearish"}.get(sig["direction"], "neutral")
    st.markdown(f"""<div class="pred {kls}"><div style="opacity:.8">OI Signal</div>
      <div style="font-size:1.6rem;font-weight:800">{sig['direction']}</div>
      <div style="font-size:.85rem">🟢 {sig['bull']} vs 🔴 {sig['bear']}</div></div>""", unsafe_allow_html=True)

m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("PCR", f"{sig['pcr']:.2f}")
m2.metric("Max Pain", f"{sig['max_pain']:,.0f}")
m3.metric("Support (max Put OI)", f"{sig['support']:,.0f}")
m4.metric("Resistance (max Call OI)", f"{sig['resistance']:,.0f}")
m5.metric("Net ΔOI  Calls / Puts", f"{sig['net_c']:+,.0f} / {sig['net_p']:+,.0f}")

# ---- Entry / Exit ----
st.subheader("📊 OI Change Entry Signal")
entry, exit_ = entry_exit(chain, spot, buffer_pts, min_gap, delta_lo, delta_hi)
if entry:
    signal_box("Entry", entry, spot, "ENTRY")
    st.subheader("📊 OI Change Exit Signal")
    signal_box("Exit", exit_, spot, "EXIT")
else:
    st.info("ℹ️ No entry/exit signal (no OI change, or entry–exit gap below the minimum).")

# ---- OI chart ----
st.subheader("Open Interest by Strike")
st.bar_chart(chain.set_index("strike")[["call_oi", "put_oi"]])
st.subheader("Change in OI by Strike")
st.bar_chart(chain[chain["has_chg"]].set_index("strike")[["call_chg", "put_chg"]])

# ---- Tables ----
def hl_top5(row):
    return (["background-color:#ffd700;font-weight:bold;color:#000"] * len(row)) if row.name < 5 else [""] * len(row)

oi_tbl = chain[["strike", "call_oi", "put_oi"]].copy()
oi_tbl["HIGH OI"] = oi_tbl.apply(lambda r: "HIGH PUT" if r.put_oi > r.call_oi else "HIGH CALL", axis=1)
oi_tbl["OI Difference"] = (oi_tbl["put_oi"] - oi_tbl["call_oi"]).abs()
st.subheader("Open Interest Data (top by difference)")
st.dataframe(oi_tbl.sort_values("OI Difference", ascending=False).head(top_n).reset_index(drop=True)
             .style.apply(hl_top5, axis=1))

chg_tbl = chain.loc[chain["has_chg"], ["strike", "call_chg", "put_chg"]].copy()
chg_tbl["HIGH OI"] = chg_tbl.apply(lambda r: "HIGH PUT" if r.put_chg > r.call_chg else "HIGH CALL", axis=1)
chg_tbl["OI Difference"] = (chg_tbl["put_chg"] - chg_tbl["call_chg"]).abs()
st.subheader("Change in OI (top by difference)")
st.dataframe(chg_tbl.sort_values("OI Difference", ascending=False).head(top_n).reset_index(drop=True)
             .style.apply(hl_top5, axis=1))

# ---- OI Flow / Macro score ----
flow = compute_crude_flow()
if flow["rows"]:
    st.subheader(f"CRUDEOILM OI Flow Details — Macro Score: {flow['score']:.2f}")
    st.markdown("**Weighted Macro Score (-1 to +1)**: Based on OI value change and price change across active CRUDEOILM futures.")
    bias = "Bullish" if flow["score"] > 0 else ("Bearish" if flow["score"] < 0 else "Sideways")
    st.write(f"Market Bias: {bias}")
    st.dataframe(pd.DataFrame(flow["rows"]))
else:
    st.info("OI flow not available (no futures contract met the OI-value threshold, or previous-day OI was not returned).")
    if flow.get("err"):
        st.code(flow["err"])

# ---- Option chain with Greeks around spot ----
st.subheader("Option Chain + Greeks (strikes nearest to price)")
near = chain.iloc[(chain["strike"] - spot).abs().argsort()[:15]].sort_values("strike")
st.dataframe(near[["strike", "call_ltp", "call_oi", "call_delta", "call_gamma", "call_theta", "call_iv",
                   "put_ltp", "put_oi", "put_delta", "put_gamma", "put_theta", "put_iv"]].reset_index(drop=True))

st.caption(f"Last refresh: {now.strftime('%Y-%m-%d %H:%M:%S IST')} · auto-refresh every 15s")