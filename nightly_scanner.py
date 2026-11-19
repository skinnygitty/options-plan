#!/usr/bin/env python3
"""
Nightly Options Scanner  (Yahoo Finance via yfinance — no API key needed)
=========================================================================
Run right after the close (4:20 pm ET, while option quotes are still live). Builds docs/index.html (and docs/check.html at 10 am) with a
trade plan for each ticker: earnings/event context, call & put walls,
unusual-flow lean (bought vs sold), and a 3:1–4:1 risk/reward plan.

IMPORTANT LIMITS OF FREE DATA
- Yahoo does not publish trade-by-trade prints, so NOTHING free can tell you
  for certain whether a contract was bought or sold. This script uses two
  proxies and labels them as a "lean", never a fact:
    1. Where the LAST trade printed inside the bid/ask (near ask = bought,
       near bid = sold).
    2. Next-day open-interest follow-up: if OI jumps by roughly the prior
       day's volume, the trades OPENED new positions (real conviction);
       if OI falls, they were closing trades (ignore them).
- Open interest on Yahoo updates once a day (morning), so walls reflect
  positioning as of the prior close.
- Gamma (GEX) walls assume the textbook dealer positioning (customers buy
  calls and buy puts). Treat them as zones, not exact prices.
"""

import csv
import datetime as dt
import html
import json
import math
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parent))
import site_render as SR

# ----------------------------------------------------------------------------
# SETTINGS — edit freely
# ----------------------------------------------------------------------------
HERE = Path(__file__).resolve().parent
WATCHLIST_FILE = HERE / "watchlist.txt"      # one ticker per line
EVENTS_FILE = HERE / "events.csv"            # date,ticker,event  (ticker * = market-wide)
SNAP_DIR = HERE / "snapshots"                # nightly chain snapshots (for OI follow-up)
REPORT_DIR = HERE / "reports"
SITE_DIR = Path(os.environ.get("SITE_DIR", HERE / "docs"))   # what GitHub Pages publishes (main branch, /docs)
KEEP_REPORT_DAYS = 30

DISCOVER_RECENT_EARNINGS = True   # add stocks that just reported (from Yahoo's earnings calendar)
DISCOVER_MIN_MCAP = 10e9          # only large caps with liquid options
DISCOVER_LOOKBACK_DAYS = 6        # calendar days back to look for reporters
MAX_DISCOVERED = 40

POST_EARNINGS_MAX_BARS = 7        # treat as "post-earnings" for up to 7 sessions after the reaction day
MIN_DTE, MAX_DTE = 0, 60          # expirations used for walls + flow (0 = include same-day / this-week contracts)
NEAR_EXPIRATIONS = 4              # nearest expirations (this week + next), where next-day flow usually shows up
FRIDAY_EXPIRATIONS = 4            # plus the next few Friday expirations out to MAX_DTE
PLAN_DTE_RANGE = (21, 60)         # expiration window for the suggested option trade
HOLD_DAYS_ASSUMED = 7             # option R:R estimates assume you hit target/stop within ~a week

UNUSUAL_MIN_VOLUME = 300
UNUSUAL_VOL_OI = 1.25             # volume / open interest
UNUSUAL_MIN_PREMIUM = 50_000      # $ notional (volume * mid * 100)
BIG_PREMIUM = 1_000_000           # any single contract with $1M+ traded is shown, even at a busy strike
TOP_PREMIUM_MIN = 250_000         # ...and each ticker's top 3 contracts by premium if at least this much
SURGE_X = 2.0                     # call or put premium this many times its 10-day average = a surge

MIN_RR, IDEAL_RR = 3.0, 4.0
MAX_SPREAD_PCT = 0.10             # contract bid/ask spread must be ≤ 10% of its mid price
MIN_CONTRACT_OI = 500             # ...and have at least this much open interest
HIGH_IV_X = 1.4                   # IV ≥ 1.4× the stock's 20-day realized volatility = high IV
SHOW_MIN_RANK = 51                # trades ranked 50 or below are hidden
RISK_FREE = 0.04
SLEEP = 0.35                      # seconds between Yahoo requests (be polite / avoid throttling)

DEFAULT_WATCHLIST = ["SPY", "QQQ", "IWM", "ANET", "LLY", "NVDA", "MU", "GOOGL", "AMD",
                     "AAPL", "AVGO", "MSFT", "TSLA", "NBIS", "PLTR", "META", "AMZN"]

# ----------------------------------------------------------------------------
# Small helpers
# ----------------------------------------------------------------------------
def log(*a):
    print(dt.datetime.now().strftime("%H:%M:%S"), *a, flush=True)


def retry(fn, *a, tries=4, **k):
    for i in range(tries):
        try:
            out = fn(*a, **k)
            time.sleep(SLEEP)
            return out
        except Exception as e:  # network hiccups / throttling
            if i == tries - 1:
                raise
            limited = "RateLimit" in type(e).__name__ or "Too Many Requests" in str(e)
            time.sleep((30 if limited else 2) * (i + 1))


def ncdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def npdf(x):
    return math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)


def bs(S, K, T, iv, cp, r=RISK_FREE):
    """Black-Scholes price, delta, gamma. cp = 'C' or 'P'."""
    T = max(T, 1 / 365)
    iv = max(iv, 0.01)
    d1 = (math.log(S / K) + (r + 0.5 * iv * iv) * T) / (iv * math.sqrt(T))
    d2 = d1 - iv * math.sqrt(T)
    if cp == "C":
        price = S * ncdf(d1) - K * math.exp(-r * T) * ncdf(d2)
        delta = ncdf(d1)
    else:
        price = K * math.exp(-r * T) * ncdf(-d2) - S * ncdf(-d1)
        delta = ncdf(d1) - 1
    gamma = npdf(d1) / (S * iv * math.sqrt(T))
    return price, delta, gamma


def fmt(x, nd=2, pre="$"):
    if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
        return "—"
    return f"{pre}{x:,.{nd}f}"


def money(x):
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "—"
    for unit, div in (("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if abs(x) >= div:
            return f"${x / div:,.1f}{unit}"
    return f"${x:,.0f}"


# ----------------------------------------------------------------------------
# Universe & events
# ----------------------------------------------------------------------------
def load_watchlist():
    if WATCHLIST_FILE.exists():
        rows = [l.split("#")[0].strip().upper() for l in WATCHLIST_FILE.read_text().splitlines()]
        tick = [r for r in rows if r]
        if tick:
            return tick
    return list(DEFAULT_WATCHLIST)


def load_events():
    ev = []
    if EVENTS_FILE.exists():
        with open(EVENTS_FILE, newline="") as f:
            for row in csv.DictReader(l for l in f if not l.lstrip().startswith("#")):
                try:
                    d = dt.date.fromisoformat(row["date"].strip())
                    ev.append((d, row["ticker"].strip().upper(), row["event"].strip()))
                except Exception:
                    continue
    return ev


def discover_earnings(today):
    """Large caps that reported recently (to scan) and those reporting soon (to avoid)."""
    recent, upcoming = [], []
    if not DISCOVER_RECENT_EARNINGS:
        return recent, upcoming
    try:
        cal = yf.Calendars()
        df = retry(cal.get_earnings_calendar, market_cap=DISCOVER_MIN_MCAP, filter_most_active=False,
                   start=str(today - dt.timedelta(days=DISCOVER_LOOKBACK_DAYS)), end=str(today), limit=100)
        if df is not None and len(df):
            recent = [s for s in df.index.astype(str).unique() if s.isalpha()][:MAX_DISCOVERED]
        df2 = retry(cal.get_earnings_calendar, market_cap=DISCOVER_MIN_MCAP, filter_most_active=False,
                    start=str(today + dt.timedelta(days=1)), end=str(today + dt.timedelta(days=10)), limit=100)
        if df2 is not None and len(df2):
            for sym, r in df2.iterrows():
                d = pd.to_datetime(r.get("Event Start Date")).date() if r.get("Event Start Date") is not None else None
                upcoming.append((str(sym), d, str(r.get("Timing", "") or "")))
    except Exception as e:
        log("Earnings-calendar discovery skipped:", e)
    return recent, upcoming


# ----------------------------------------------------------------------------
# Price structure
# ----------------------------------------------------------------------------
def price_context(hist):
    h = hist.copy()
    pc = h["Close"].shift(1)
    tr = pd.concat([h["High"] - h["Low"], (h["High"] - pc).abs(), (h["Low"] - pc).abs()], axis=1).max(axis=1)
    atr = tr.rolling(14).mean().iloc[-1]
    rets = np.log(h["Close"]).diff()
    hv20 = rets.tail(20).std() * math.sqrt(252)
    wk = h["Close"].resample("W-FRI").last().dropna()
    e10, e21, e72 = (wk.ewm(span=s, adjust=False).mean().iloc[-1] for s in (10, 21, 72))
    if e21 > e72 and e10 >= e72 * 1.06:
        trend = "Weekly uptrend (21>72, 10 EMA ≥6% over 72)"
        tscore = 1
    elif e21 > e72:
        trend = "Weekly 21>72 but momentum not confirmed"
        tscore = 0.5
    elif e21 < e72:
        trend = "Weekly downtrend (21<72)"
        tscore = -1
    else:
        trend, tscore = "Flat", 0
    return dict(spot=float(h["Close"].iloc[-1]), atr=float(atr), hv20=float(hv20),
                swing_low=float(h["Low"].tail(10).min()), swing_high=float(h["High"].tail(10).max()),
                trend=trend, tscore=tscore, last_date=h.index[-1].date())


def earnings_context(tk, hist, today):
    out = dict(last_earn=None, next_earn=None, reaction=None)
    try:
        ed = retry(tk.get_earnings_dates, limit=8)
    except Exception:
        ed = None
    if ed is not None and len(ed):
        dates = sorted({pd.Timestamp(i).tz_localize(None).normalize() if pd.Timestamp(i).tzinfo else pd.Timestamp(i).normalize()
                        for i in ed.index})
        past = [d for d in dates if d.date() <= today]
        fut = [d for d in dates if d.date() > today]
        out["last_earn"] = past[-1].date() if past else None
        out["next_earn"] = fut[0].date() if fut else None
        if past:
            row = ed[[ (pd.Timestamp(i).tz_localize(None) if pd.Timestamp(i).tzinfo else pd.Timestamp(i)).normalize() == past[-1] for i in ed.index]]
            if len(row):
                r = row.iloc[0]
                out["eps_est"] = r.get("EPS Estimate")
                out["eps_act"] = r.get("Reported EPS")
                out["surprise"] = r.get("Surprise(%)")
    if out["next_earn"] is None:
        try:
            cal = retry(lambda: tk.calendar)
            ne = cal.get("Earnings Date") if isinstance(cal, dict) else None
            if ne:
                nd = [d for d in ne if d > today]
                out["next_earn"] = nd[0] if nd else None
            out["ex_div"] = cal.get("Ex-Dividend Date") if isinstance(cal, dict) else None
        except Exception:
            pass

    # Reaction day = whichever of (earnings day, next session) gapped most — robust to BMO/AMC ambiguity
    if out["last_earn"]:
        idx = hist.index.tz_localize(None).normalize() if hist.index.tz is not None else hist.index.normalize()
        e = pd.Timestamp(out["last_earn"])
        cands = [i for i in range(1, len(idx)) if idx[i] >= e][:2]
        best = None
        for i in cands:
            gap = hist["Open"].iloc[i] / hist["Close"].iloc[i - 1] - 1
            if best is None or abs(gap) > abs(best[1]):
                best = (i, gap)
        if best:
            i, gap = best
            prev = hist["Close"].iloc[i - 1]
            rday = hist.iloc[i]
            bars_since = len(hist) - 1 - i
            last = hist["Close"].iloc[-1]
            move = rday["Close"] / prev - 1
            mid = (rday["High"] + rday["Low"]) / 2
            if move > 0:
                held = last >= mid
            else:
                held = last <= mid
            out["reaction"] = dict(date=idx[i].date(), gap=gap, move=move, high=float(rday["High"]),
                                   low=float(rday["Low"]), prev_close=float(prev), bars_since=bars_since,
                                   held=bool(held), since=last / prev - 1)
    return out


# ----------------------------------------------------------------------------
# Options: chains, walls, flow
# ----------------------------------------------------------------------------
def load_chains(tk, spot, today):
    exps = []
    for e in retry(lambda: tk.options):
        d = dt.date.fromisoformat(e)
        dte = (d - today).days
        if MIN_DTE <= dte <= MAX_DTE:
            exps.append((e, dte))
    # nearest few (this week / next) + upcoming Fridays + one in the plan window
    near = [x for x in exps if x[1] <= 9][:NEAR_EXPIRATIONS]
    later = [x for x in exps if x[1] > 9 and dt.date.fromisoformat(x[0]).weekday() == 4][:FRIDAY_EXPIRATIONS]
    chosen = near + later
    if not any(PLAN_DTE_RANGE[0] <= d <= PLAN_DTE_RANGE[1] for _, d in chosen):
        extra = [x for x in exps if PLAN_DTE_RANGE[0] <= x[1] <= PLAN_DTE_RANGE[1]]
        if extra:
            chosen.append(extra[0])
    frames = []
    for e, dte in chosen:
        ch = retry(tk.option_chain, e)
        for side, df in (("C", ch.calls), ("P", ch.puts)):
            if df is None or not len(df):
                continue
            d = df.copy()
            d["cp"], d["expiry"], d["dte"] = side, e, dte
            frames.append(d)
    if not frames:
        return None
    df = pd.concat(frames, ignore_index=True)
    for c in ("volume", "openInterest", "bid", "ask", "lastPrice", "impliedVolatility"):
        df[c] = pd.to_numeric(df.get(c), errors="coerce").fillna(0.0)
    df = df[(df["strike"] > spot * 0.6) & (df["strike"] < spot * 1.4)].copy()
    df["mid"] = np.where((df["bid"] > 0) & (df["ask"] > 0), (df["bid"] + df["ask"]) / 2, df["lastPrice"])
    df["ivc"] = df["impliedVolatility"].clip(0.05, 3.0)
    T = df["dte"].clip(lower=1) / 365
    g = [bs(spot, k, t, iv, cp)[1:] for k, t, iv, cp in zip(df["strike"], T, df["ivc"], df["cp"])]
    df["delta"] = [x[0] for x in g]
    df["gamma"] = [x[1] for x in g]
    # dollar gamma per 1% move; calls +, puts – (textbook dealer assumption)
    df["gex"] = df["gamma"] * df["openInterest"] * 100 * spot * spot * 0.01 * np.where(df["cp"] == "C", 1, -1)
    return df


def walls(df, spot):
    near = df[(df["strike"] > spot * 0.8) & (df["strike"] < spot * 1.2)]
    by = near.groupby(["strike", "cp"]).agg(oi=("openInterest", "sum"), gex=("gex", "sum")).reset_index()
    calls = by[by.cp == "C"].set_index("strike")
    puts = by[by.cp == "P"].set_index("strike")
    res = {}
    c_up = calls[calls.index >= spot]
    p_dn = puts[puts.index <= spot]
    res["call_wall"] = float(c_up["gex"].idxmax()) if len(c_up) and c_up["gex"].max() > 0 else None
    res["put_wall"] = float(p_dn["gex"].idxmin()) if len(p_dn) and p_dn["gex"].min() < 0 else None
    res["call_wall_oi"] = float(c_up["oi"].idxmax()) if len(c_up) and c_up["oi"].max() > 0 else None
    res["put_wall_oi"] = float(p_dn["oi"].idxmax()) if len(p_dn) and p_dn["oi"].max() > 0 else None
    # second walls (for target 2)
    if res["call_wall"]:
        nxt = c_up[c_up.index > res["call_wall"] * 1.005]
        res["call_wall2"] = float(nxt["gex"].idxmax()) if len(nxt) and nxt["gex"].max() > 0 else None
    if res["put_wall"]:
        nxt = p_dn[p_dn.index < res["put_wall"] * 0.995]
        res["put_wall2"] = float(nxt["gex"].idxmin()) if len(nxt) and nxt["gex"].min() < 0 else None
    net = by["gex"].sum()
    res["net_gex"] = float(net)
    res["regime"] = ("Positive gamma — dealers dampen moves; expect pinning between walls"
                     if net > 0 else "Negative gamma — dealers amplify moves; breaks can run")
    tot_c, tot_p = df.loc[df.cp == "C", "volume"].sum(), df.loc[df.cp == "P", "volume"].sum()
    res["pc_vol"] = tot_p / tot_c if tot_c else None
    return res


def side_lean(r):
    b, a, l = r["bid"], r["ask"], r["lastPrice"]
    if b <= 0 or a <= 0 or a <= b or l <= 0:
        return "UNCLEAR", None
    pos = (l - b) / (a - b)
    if pos >= 0.65:
        return "BOUGHT", pos
    if pos <= 0.35:
        return "SOLD", pos
    return "MID", pos


MEANING = {("C", "BOUGHT"): ("Calls bought", 1), ("C", "SOLD"): ("Calls sold", -1),
           ("P", "BOUGHT"): ("Puts bought", -1), ("P", "SOLD"): ("Puts sold", 1)}


def contract_role(adelta):
    if adelta >= 0.80:
        return "Deep ITM"      # behaves like stock: replacement, hedge, or a spread leg — not a bet
    if adelta < 0.10:
        return "Lottery"       # far out of the money, tiny probability — low weight
    return "Directional"


def unusual_flow(df, today, spot=None):
    d = df.copy()
    d["premium"] = d["volume"] * d["mid"] * 100
    if "delta" not in d.columns:
        T = d["dte"].clip(lower=1) / 365
        ivs = pd.to_numeric(d.get("impliedVolatility"), errors="coerce").fillna(0.3).clip(0.05, 3.0)
        d["delta"] = [bs(spot, k, t, iv, cp)[1] for k, t, iv, cp in zip(d["strike"], T, ivs, d["cp"])]
    new_pos = (d["volume"] >= UNUSUAL_MIN_VOLUME) & (d["volume"] >= UNUSUAL_VOL_OI * d["openInterest"].clip(lower=1)) \
        & (d["premium"] >= UNUSUAL_MIN_PREMIUM)
    big = d["premium"] >= BIG_PREMIUM
    top = d["premium"].rank(ascending=False, method="first") <= 3
    top &= d["premium"] >= TOP_PREMIUM_MIN
    d["why"] = np.where(new_pos, "volume over open interest", np.where(big, "$1M+ premium", "top premium today"))
    u = d[new_pos | big | top].sort_values("premium", ascending=False).head(12)
    rows = []
    for _, r in u.iterrows():
        lean, pos = side_lean(r)
        label, sign = MEANING.get((r["cp"], lean), ("Unclear side", 0))
        delta = float(r["delta"])
        side_sign = 1 if lean == "BOUGHT" else -1 if lean == "SOLD" else 0
        rows.append(dict(contract=r.get("contractSymbol", ""), cp=r["cp"], strike=float(r["strike"]), expiry=r["expiry"],
                         dte=int(r["dte"]), volume=int(r["volume"]), oi=int(r["openInterest"]),
                         vol_oi=r["volume"] / max(r["openInterest"], 1), premium=float(r["premium"]),
                         lean=lean, label=label, sign=sign, pos=pos, bid=float(r["bid"]), ask=float(r["ask"]),
                         last=float(r["lastPrice"]), why=r["why"], delta=delta, role=contract_role(abs(delta)),
                         dnotional=side_sign * delta * r["volume"] * 100 * (spot or 0),
                         spread_pct=(r["ask"] - r["bid"]) / ((r["ask"] + r["bid"]) / 2) if r["bid"] > 0 and r["ask"] > 0 else None))
    # pair up likely spreads: same expiry and type, similar size, one bought and one sold
    for i, a in enumerate(rows):
        for b in rows[i + 1:]:
            if a["role"] == "Spread leg" or b["role"] == "Spread leg":
                continue
            if a["expiry"] == b["expiry"] and a["cp"] == b["cp"] and {a["lean"], b["lean"]} == {"BOUGHT", "SOLD"} \
                    and 0.8 <= a["volume"] / max(b["volume"], 1) <= 1.25:
                for x in (a, b):
                    x["role"] = "Spread leg"
                bought, sold = (a, b) if a["lean"] == "BOUGHT" else (b, a)
                bought["spread_net"] = bought["premium"] - sold["premium"]
                bought["pair"] = f"{sold['strike']:g}{sold['cp']}"
    bull = bear = 0.0
    for r in rows:
        if r["sign"] == 0:
            continue
        if r["role"] == "Directional":
            amt = r["premium"]
        elif r["role"] == "Spread leg" and r.get("spread_net"):
            amt = abs(r["spread_net"])
        else:
            continue
        if r["sign"] > 0:
            bull += amt
        else:
            bear += amt
    tot = bull + bear
    bias = (bull - bear) / tot if tot else 0.0
    return rows, bias, bull, bear


def institutional_read(rows, spot, bull, bear):
    """Plain-English read of the flagged flow, the way a desk would summarize it."""
    def short_exp(e):
        d = dt.date.fromisoformat(e)
        return f"{d.strftime('%b')} {d.day}"
    dirs = [r for r in rows if r["role"] in ("Directional", "Spread leg") and r["sign"] != 0]
    net_delta = sum(r["dnotional"] for r in rows if r["role"] in ("Directional", "Spread leg"))
    deep = sum(r["premium"] for r in rows if r["role"] == "Deep ITM")
    unclear = sum(r["premium"] for r in rows if r["sign"] == 0 and r["role"] != "Deep ITM")
    tot = bull + bear
    if tot < 250_000:
        stance = "Quiet"
    elif bull >= 2 * bear:
        stance = "Bullish"
    elif bear >= 2 * bull:
        stance = "Bearish"
    else:
        stance = "Mixed"
    out = dict(stance=stance, bull=bull, bear=bear, net_delta=net_delta, deep=deep, unclear=unclear, lines=[], follow=None)
    L = out["lines"]
    if stance == "Quiet":
        L.append("No meaningful one-sided options positioning.")
    elif stance == "Mixed":
        L.append(f"Mixed: {money(bull)} bullish vs {money(bear)} bearish. No clear institutional edge.")
    else:
        word = "bullish" if stance == "Bullish" else "bearish"
        L.append(f"Big money leans {word}: {money(bull)} bullish vs {money(bear)} bearish in directional bets.")
    if abs(net_delta) >= 1_000_000:
        L.append(f"Delta-adjusted, that's about {money(abs(net_delta))} of stock {'bought' if net_delta > 0 else 'sold'}.")
    want = 1 if stance == "Bullish" else -1 if stance == "Bearish" else 0
    if want:
        cands = [r for r in dirs if r["sign"] == want and r["lean"] == "BOUGHT" and r["role"] == "Directional"]
        if cands:
            t = max(cands, key=lambda r: r["premium"])
            kind = "calls" if t["cp"] == "C" else "puts"
            k_, ex_ = f"${t['strike']:g}", short_exp(t["expiry"])
            if t["cp"] == "C":
                aim = f"betting it holds above {k_} through {ex_}" if t["strike"] <= spot else f"positioned for {k_}+ by {ex_}"
            else:
                aim = f"betting it stays below {k_} through {ex_}" if t["strike"] >= spot else f"positioned for a drop below {k_} by {ex_}"
            L.append(f"Biggest bet: {ex_} {k_} {kind}, {money(t['premium'])} bought. They're {aim}.")
            out["follow"] = dict(expiry=t["expiry"], strike=t["strike"], cp=t["cp"])
        exps = {}
        for r in dirs:
            if r["sign"] == want:
                exps[r["expiry"]] = exps.get(r["expiry"], 0) + r["premium"]
        if exps:
            e_ = max(exps, key=exps.get)
            out["main_expiry"] = e_
    ign = []
    if deep >= 500_000:
        ign.append(f"{money(deep)} in deep in-the-money contracts (stock replacement or hedges)")
    if unclear >= 500_000:
        ign.append(f"{money(unclear)} where bought or sold couldn't be read")
    if ign:
        L.append("Not counted: " + "; ".join(ign) + ".")
    return out


def oi_followup(sym, df):
    """Compare today's OI with yesterday's flagged contracts → opened or closed?"""
    prev_file = [f for f in sorted(SNAP_DIR.glob(f"{sym}_*.json")) if not f.stem.endswith(dt.date.today().isoformat())]
    if not prev_file:
        return []
    try:
        prev = json.loads(prev_file[-1].read_text())
    except Exception:
        return []
    now_oi = dict(zip(df.get("contractSymbol", pd.Series(dtype=str)), df["openInterest"]))
    out = []
    for c in prev.get("unusual", []):
        cs = c.get("contract")
        if cs not in now_oi:
            continue
        chg = now_oi[cs] - c["oi"]
        ratio = chg / max(c["volume"], 1)
        verdict = "OPENED (new positions — conviction)" if ratio >= 0.5 else \
                  "Mostly CLOSED (ignore as signal)" if chg < 0 else "Mixed / day-traded"
        out.append(dict(contract=cs, label=c["label"], prev_vol=c["volume"], oi_change=int(chg),
                        verdict=verdict, snap=prev.get("date"), sign=c.get("sign", 0), opened=ratio >= 0.5))
    return out


def premium_totals(df, spot):
    d = df.copy()
    d["premium"] = d["volume"] * d["mid"] * 100
    c, p = d[d.cp == "C"], d[d.cp == "P"]
    quoted = ((d["bid"] > 0) & (d["ask"] > 0) & (d["volume"] > 0)).sum() / max((d["volume"] > 0).sum(), 1)
    return dict(call_prem=float(c["premium"].sum()), put_prem=float(p["premium"].sum()),
                otm_call_prem=float(c.loc[c.strike > spot, "premium"].sum()),
                otm_put_prem=float(p.loc[p.strike < spot, "premium"].sum()), quoted=float(quoted))


def premium_surge(sym, tot):
    """Today's call/put premium vs this ticker's own average over the last 10 scans."""
    hist = []
    for f in sorted(SNAP_DIR.glob(f"{sym}_*.json")):
        if f.stem.endswith(dt.date.today().isoformat()):
            continue
        try:
            t = json.loads(f.read_text()).get("totals")
            if t:
                hist.append(t)
        except Exception:
            pass
    out = dict(tot, days=len(hist), call_x=None, put_x=None)
    if len(hist) >= 3:
        ac = np.mean([h["call_prem"] for h in hist]); ap = np.mean([h["put_prem"] for h in hist])
        out["call_x"] = tot["call_prem"] / ac if ac else None
        out["put_x"] = tot["put_prem"] / ap if ap else None
    return out


def save_snapshot(sym, today, flow_rows, totals=None):
    SNAP_DIR.mkdir(exist_ok=True)
    (SNAP_DIR / f"{sym}_{today.isoformat()}.json").write_text(
        json.dumps(dict(date=today.isoformat(), unusual=flow_rows, totals=totals), default=float))
    old = sorted(SNAP_DIR.glob(f"{sym}_*.json"))[:-30]   # keep 30 nights (IV rank, premium averages)
    for f in old:
        f.unlink(missing_ok=True)


# ----------------------------------------------------------------------------
# The Strat (Rob Smith): candle types, combos, actionable signals, FTFC
# ----------------------------------------------------------------------------
STRAT_TFS = ["D", "2D", "3D", "5D", "9D", "W"]   # hybrid N-day candles are built from daily bars
TF_RANK = {tf: i for i, tf in enumerate(STRAT_TFS)}


def _agg(g):
    return pd.Series({"Open": g["Open"].iloc[0], "High": g["High"].max(), "Low": g["Low"].min(),
                      "Close": g["Close"].iloc[-1], "End": g.index[-1], "n": len(g)})


def make_bars(hist, tf):
    h = hist[["Open", "High", "Low", "Close"]].copy()
    h.index = h.index.tz_localize(None) if h.index.tz is not None else h.index
    if tf == "D":
        b = h.copy(); b["End"] = b.index; b["n"] = 1
        return b.reset_index(drop=True)
    if tf == "W":
        b = h.groupby(h.index.to_period("W-FRI")).apply(_agg).reset_index(drop=True)
        last = h.index[-1]
        if last.weekday() != 4:            # current week still in progress → keep it but mark it
            b.loc[b.index[-1], "n"] = -1
        return b
    n = int(tf[:-1])
    # rolling N-session candles anchored to the latest close, so every candle is complete
    k = (len(h) - 1 - np.arange(len(h))) // n
    b = h.groupby(k).apply(_agg).iloc[::-1].reset_index(drop=True)
    return b[b["n"] == n].reset_index(drop=True)


def strat_type(cur, prev):
    up, dn = cur["High"] > prev["High"], cur["Low"] < prev["Low"]
    if up and dn:
        return "3"
    if up:
        return "2U"
    if dn:
        return "2D"
    return "1"


def shape(bar):
    rng = bar["High"] - bar["Low"]
    if rng <= 0:
        return None
    body = abs(bar["Close"] - bar["Open"])
    lower = min(bar["Open"], bar["Close"]) - bar["Low"]
    upper = bar["High"] - max(bar["Open"], bar["Close"])
    pos = (bar["Close"] - bar["Low"]) / rng
    if lower >= 2 * max(body, rng * 0.05) and pos >= 0.6:
        return "Hammer"
    if upper >= 2 * max(body, rng * 0.05) and pos <= 0.4:
        return "Shooter"
    return None


def strat_scan(hist):
    """Returns per-timeframe sequence + actionable setups with trigger/stop."""
    out = {}
    for tf in STRAT_TFS:
        b = make_bars(hist, tf)
        in_prog = False
        if tf == "W" and len(b) and b["n"].iloc[-1] == -1:
            in_prog = True
            cur_w = b.iloc[-1]
            b = b.iloc[:-1].reset_index(drop=True)
        if len(b) < 4:
            continue
        types = [strat_type(b.iloc[i], b.iloc[i - 1]) for i in range(len(b) - 3, len(b))]
        L, P = b.iloc[-1], b.iloc[-2]
        green = L["Close"] > L["Open"]
        shp = shape(L)
        seq = "-".join(types)
        setups = []

        def add(name, side, trig, stop, note=""):
            setups.append(dict(tf=tf, name=name, side=side, trigger=float(trig), stop=float(stop), note=note))

        t1, t2 = types[-1], types[-2]
        if t1 == "1":
            lead = {"2U": "2U-1", "2D": "2D-1", "3": "3-1", "1": "1-1"}[t2]
            cont_l = "continuation" if t2 == "2U" else "reversal" if t2 == "2D" else ""
            cont_s = "continuation" if t2 == "2D" else "reversal" if t2 == "2U" else ""
            add(f"{lead}-2U {cont_l}".strip(), "LONG", L["High"], L["Low"], "Inside bar — take the break of its high")
            add(f"{lead}-2D {cont_s}".strip(), "SHORT", L["Low"], L["High"], "Inside bar — take the break of its low")
        if t1 == "2D" and t2 == "1":
            add("1-2D-2U RevStrat", "LONG", L["High"], L["Low"])
        if t1 == "2U" and t2 == "1":
            add("1-2U-2D RevStrat", "SHORT", L["Low"], L["High"])
        if t1 == "2D" and t2 == "3":
            add("3-2D-2U reversal", "LONG", L["High"], L["Low"])
        if t1 == "2U" and t2 == "3":
            add("3-2U-2D reversal", "SHORT", L["Low"], L["High"])
        if t1 == "2D" and t2 not in ("1", "3") and (green or shp == "Hammer"):
            add("2-2 reversal (2D→2U)", "LONG", L["High"], L["Low"],
                "Failed 2D (closed green)" if green else "Hammer on a 2D")
        if t1 == "2U" and t2 not in ("1", "3") and ((not green) or shp == "Shooter"):
            add("2-2 reversal (2U→2D)", "SHORT", L["Low"], L["High"],
                "Failed 2U (closed red)" if not green else "Shooter on a 2U")
        if t1 == "3":
            add("3 outside bar → 3-2U", "LONG", L["High"], L["Low"], "Wide stop — better to wait for a 3-1-2")
            add("3 outside bar → 3-2D", "SHORT", L["Low"], L["High"], "Wide stop — better to wait for a 3-1-2")
        if shp == "Hammer" and t1 != "2D":
            add("Hammer → 2U", "LONG", L["High"], L["Low"])
        if shp == "Shooter" and t1 != "2U":
            add("Shooter → 2D", "SHORT", L["Low"], L["High"])
        signal = []
        if t1 == "1": signal.append("Inside bar")
        if shp: signal.append(shp)
        if t1 == "2U" and not green: signal.append("Failed 2U (2U red)")
        if t1 == "2D" and green: signal.append("Failed 2D (2D green)")
        if t1 == "3": signal.append("Outside bar")
        out[tf] = dict(seq=seq, last=t1, color="green" if green else "red", signals=signal, setups=setups,
                       high=float(L["High"]), low=float(L["Low"]),
                       in_progress=(f"current week so far: {strat_type(cur_w, L)} "
                                    f"{'green' if cur_w['Close'] > cur_w['Open'] else 'red'}") if in_prog else "")
    return out


def ftfc(hist):
    """Full timeframe continuity: last close vs the open of the current Q / M / W / D."""
    h = hist.copy()
    h.index = h.index.tz_localize(None) if h.index.tz is not None else h.index
    last = h.index[-1]
    c = h["Close"].iloc[-1]
    res = {}
    for tf, key in (("Q", last.to_period("Q")), ("M", last.to_period("M")), ("W", last.to_period("W-FRI"))):
        per = h.index.to_period("Q" if tf == "Q" else "M" if tf == "M" else "W-FRI")
        o = h["Open"][per == key].iloc[0]
        res[tf] = "G" if c > o else "R"
    res["D"] = "G" if c > h["Open"].iloc[-1] else "R"
    s = "".join(res.values())
    state = "Bullish FTFC" if s == "GGGG" else "Bearish FTFC" if s == "RRRR" else "Mixed"
    return dict(tfs=res, state=state)


def strat_entries(strat, side, t1, t2, atr, spot):
    """Setups that agree with the plan side, with R:R measured trigger → strat stop → walls."""
    rows = []
    for tf, d in strat.items():
        for s in d["setups"]:
            if s["side"] != side:
                continue
            risk = abs(s["trigger"] - s["stop"])
            if risk <= 0:
                continue
            reward1 = (t1 - s["trigger"]) if side == "LONG" else (s["trigger"] - t1)
            reward2 = (t2 - s["trigger"]) if side == "LONG" else (s["trigger"] - t2)
            dist = (s["trigger"] - spot) / atr if side == "LONG" else (spot - s["trigger"]) / atr
            rows.append(dict(s, rr1=reward1 / risk, rr2=reward2 / risk, dist_atr=dist, risk=risk))
    # best = highest timeframe whose trigger is within ~1.5 daily ATR and gives ≥3:1 to T1 or T2
    ok = [r for r in rows if -0.25 <= r["dist_atr"] <= 1.5 and max(r["rr1"], r["rr2"]) >= MIN_RR and r["rr1"] > 0]
    best = max(ok, key=lambda r: (r["rr1"] >= MIN_RR, TF_RANK[r["tf"]], r["rr1"])) if ok else None
    return sorted(rows, key=lambda r: -TF_RANK[r["tf"]]), best


# ----------------------------------------------------------------------------
# Trade plan
# ----------------------------------------------------------------------------
def build_plan(sym, px, ear, w, bias, follow, df, today, events, strat=None, tfc=None, flowx=None):
    spot, atr = px["spot"], px["atr"]
    reasons, score = [], 0.0

    # 1. Earnings reaction (post-earnings = IV already crushed)
    re = ear.get("reaction")
    post = bool(re and 0 <= re["bars_since"] <= POST_EARNINGS_MAX_BARS)
    if post:
        if re["move"] > 0.02 and re["held"]:
            score += 1.5; reasons.append(f"Gapped {re['gap']:+.1%} on earnings and is holding the upper half of the reaction day")
        elif re["move"] < -0.02 and re["held"]:
            score -= 1.5; reasons.append(f"Gapped {re['gap']:+.1%} on earnings and is holding the lower half of the reaction day")
        elif abs(re["move"]) > 0.02:
            reasons.append(f"Earnings move {re['move']:+.1%} is fading — reversal risk, wait for direction")
        else:
            reasons.append("Muted earnings reaction")

    # 2. Weekly trend (your 21/72 EMA framework)
    score += px["tscore"]
    reasons.append(px["trend"])

    # 3. Flow lean (+ next-day confirmation counts double)
    if abs(bias) >= 0.3:
        score += 1 if bias > 0 else -1
        reasons.append(f"Unusual flow leans {'bullish' if bias > 0 else 'bearish'} ({bias:+.0%} of classified premium)")
    sg = flowx or {}
    if sg.get("call_x") and sg["call_x"] >= SURGE_X and bias > 0:
        score += 0.5; reasons.append(f"Call premium {sg['call_x']:.1f}× its 10-day average")
    if sg.get("put_x") and sg["put_x"] >= SURGE_X and bias < 0:
        score -= 0.5; reasons.append(f"Put premium {sg['put_x']:.1f}× its 10-day average")
    conf = [f for f in follow if f["opened"] and f["sign"]]
    if conf:
        s = sum(f["sign"] for f in conf)
        if s:
            score += 1 if s > 0 else -1
            reasons.append(f"Yesterday's flagged flow was confirmed as OPENING by today's OI ({len(conf)} contract(s))")

    if tfc and tfc["state"] != "Mixed":
        score += 0.5 if tfc["state"].startswith("Bull") else -0.5
        reasons.append(f"{tfc['state']} (Q/M/W/D all {'green' if tfc['state'].startswith('Bull') else 'red'})")

    direction = "LONG" if score >= 2 else "SHORT" if score <= -2 else "WATCH"

    cw, pw = w.get("call_wall"), w.get("put_wall")
    plan = dict(direction=direction, score=score, reasons=reasons, post_earnings=post)

    def stop_long():
        cands = []
        if pw: cands.append(pw - 0.25 * atr)
        if post and re["move"] > 0: cands.append(re["low"] - 0.1 * atr)
        cands.append(px["swing_low"] - 0.1 * atr)
        ok = [c for c in cands if c <= spot - 0.5 * atr]
        return max(ok) if ok else spot - 1.5 * atr

    def stop_short():
        cands = []
        if cw: cands.append(cw + 0.25 * atr)
        if post and re["move"] < 0: cands.append(re["high"] + 0.1 * atr)
        cands.append(px["swing_high"] + 0.1 * atr)
        ok = [c for c in cands if c >= spot + 0.5 * atr]
        return min(ok) if ok else spot + 1.5 * atr

    d = direction if direction != "WATCH" else ("LONG" if score >= 0 else "SHORT")
    if d == "LONG":
        stop = stop_long()
        t1 = cw if cw and cw > spot + 0.5 * atr else spot + 2 * atr
        t2 = w.get("call_wall2") or (t1 + atr)
        t2 = max(t2, t1 + 0.5 * atr)
        lvl = max(spot, re["high"]) if post and re["move"] > 0 else spot
        entry = lvl
        risk = entry - stop
        rr1, rr2 = (t1 - entry) / risk, (t2 - entry) / risk
        entry_3r = (t1 + MIN_RR * stop) / (1 + MIN_RR)     # price where T1 gives 3:1
        trig = (f"Break & hold above {fmt(lvl)} (reaction-day high)" if lvl > spot else f"Hold above {fmt(spot)} (last close)")
    else:
        stop = stop_short()
        t1 = pw if pw and pw < spot - 0.5 * atr else spot - 2 * atr
        t2 = w.get("put_wall2") or (t1 - atr)
        t2 = min(t2, t1 - 0.5 * atr)
        lvl = min(spot, re["low"]) if post and re["move"] < 0 else spot
        entry = lvl
        risk = stop - entry
        rr1, rr2 = (entry - t1) / risk, (entry - t2) / risk
        entry_3r = (t1 + MIN_RR * stop) / (1 + MIN_RR)
        trig = (f"Break & hold below {fmt(lvl)} (reaction-day low)" if lvl < spot else f"Hold below {fmt(spot)} (last close)")

    plan.update(side=d, entry=entry, stop=stop, t1=t1, t2=t2, rr1=rr1, rr2=rr2, trigger=trig)
    if rr1 >= MIN_RR:
        plan["entry_note"] = f"R:R {rr1:.1f}:1 to target 1 from the last close — valid at the trigger."
    elif rr2 >= MIN_RR:
        plan["entry_note"] = (f"Only {rr1:.1f}:1 to target 1 from the trigger, but {rr2:.1f}:1 to target 2. "
                              f"Take partial at T1, trail the rest. Better: limit entry at {fmt(entry_3r)} for 3:1 on T1.")
    else:
        far = abs(entry_3r - spot) / atr
        plan["entry_note"] = (f"R:R only {rr1:.1f}:1 from the trigger. Wait for a {'pullback' if d == 'LONG' else 'bounce'} to "
                              f"{fmt(entry_3r)} ({far:.1f} ATR away) to get 3:1 — otherwise pass.")
    plan["rr_ok"] = rr1 >= MIN_RR or rr2 >= MIN_RR
    plan["strat_rows"], plan["strat_best"] = strat_entries(strat or {}, d, t1, t2, atr, spot)
    _b = plan["strat_best"]
    plan["use_entry"] = _b["trigger"] if _b else plan["entry"]
    plan["use_stop"] = _b["stop"] if _b else plan["stop"]
    inst = (flowx or {}).get("inst") or {}
    side_stance = "Bullish" if d == "LONG" else "Bearish"
    prefer = inst.get("follow") if inst.get("stance") == side_stance else None
    plan["option"] = option_idea(d, plan["use_entry"], plan["use_stop"], t1, t2, df, today, ear, prefer)
    plan["inst"] = inst
    plan["flow_conflict"] = inst.get("stance") in ("Bullish", "Bearish") and inst.get("stance") != side_stance \
        and max(inst.get("bull", 0), inst.get("bear", 0)) >= BIG_PREMIUM
    ck = []
    if tfc:
        aligned = all(v == ("G" if d == "LONG" else "R") for k, v in tfc["tfs"].items() if k in ("M", "W"))
        ck.append((aligned, f"Continuity: Month & Week {'green' if d == 'LONG' else 'red'} at entry "
                            f"(now Q{tfc['tfs']['Q']} M{tfc['tfs']['M']} W{tfc['tfs']['W']} D{tfc['tfs']['D']}) (re-check at 9:50)"))
    b = plan["strat_best"]
    ck.append((b is not None, f"Strat trigger in force: {b['tf']} {b['name']} — enter only when price trades through "
                              f"{fmt(b['trigger'])}; stop {fmt(b['stop'])}" if b else
               "Strat trigger: none within reach that gives 3:1 — wait for a new inside bar / reversal on D–9D"))
    ck.append((plan["rr_ok"] or b is not None, "Risk:reward ≥ 3:1 to T1 (or T2 with a partial at T1)"))
    ck.append((any(f["opened"] and f["sign"] == (1 if d == "LONG" else -1) for f in follow),
               "Flow confirmation: flagged flow on your side opened new positions (OI up). The 9:50 morning check confirms it"))
    ck.append((None, "Don't chase: if price is more than ½ ATR past the trigger at the 9:50 check, wait for a re-test or skip"))
    plan["checklist"] = ck

    # event warnings
    warn = []
    ne = ear.get("next_earn")
    if ne and (ne - today).days <= 14:
        warn.append(f"Earnings in {(ne - today).days} days ({ne}) — IV is inflating; buying premium now pays for that.")
    for d0, t, e in events:
        if 0 <= (d0 - today).days <= 14 and t in (sym, "*"):
            warn.append(f"{d0}: {e}")
    if ear.get("ex_div") and isinstance(ear["ex_div"], dt.date) and 0 <= (ear["ex_div"] - today).days <= 14:
        warn.append(f"Ex-dividend {ear['ex_div']}")
    plan["warnings"] = warn
    plan["checklist"].insert(3, (not any("Earnings in" in x for x in warn),
                                 "No earnings inside the next 14 days / before your option's expiry"))
    return plan


def rank_plan(plan, px, flowx, follow, tfc, iv_info):
    """0–100 trade quality. Returns (rank, list of (points, reason))."""
    pts = []
    d = plan["side"]
    sg = 1 if d == "LONG" else -1
    # 1. Conviction (25): earnings reaction, weekly trend, flow, continuity combined
    conv = min(abs(plan["score"]) / 4.0, 1.0) * 25 if plan["score"] * sg > 0 else 0
    pts.append((conv, "Direction conviction"))
    # 2. Risk/reward (20)
    b = plan.get("strat_best")
    rr1 = b["rr1"] if b else plan["rr1"]
    rr = 20 if rr1 >= 4 else 15 if rr1 >= 3 else 8 if rr1 >= 2 else 3 if rr1 >= 1.5 else 0
    pts.append((rr, f"R:R {rr1:.1f} : 1 to T1"))
    # 3. Strat trigger + continuity (15)
    st = 10 if b else 0
    if tfc and all(v == ("G" if sg > 0 else "R") for k, v in tfc["tfs"].items() if k in ("M", "W")):
        st += 5
    pts.append((st, "Strat trigger and month/week continuity"))
    # 4. Flow on your side (15)
    fl = 0
    bias = (flowx or {}).get("bias", 0)
    if bias * sg >= 0.3:
        fl += 8
    if any(f["opened"] and f["sign"] == sg for f in follow):
        fl += 4
    x = (flowx or {}).get("call_x" if sg > 0 else "put_x")
    if x and x >= SURGE_X and bias * sg > 0:
        fl += 3
    pts.append((fl, "Options flow on your side"))
    # 5. Contract liquidity (15)
    o = (plan.get("option") or {}).get("single")
    if o:
        sp = o["spread_pct"]
        lq = 15 if sp <= 0.04 else 12 if sp <= 0.07 else 8 if sp <= MAX_SPREAD_PCT else 0
        if o["oi"] < MIN_CONTRACT_OI:
            lq = min(lq, 4)
        pts.append((lq, f"Contract spread {sp:.0%}, OI {o['oi']:,}"))
    else:
        pts.append((0, "No tradable contract"))
    # 6. Option pricing (10): cheaper IV vs realized is better
    ratio = (iv_info or {}).get("ratio")
    ivp = 10 if ratio is None else 10 if ratio <= 1.1 else 7 if ratio <= 1.25 else 4 if ratio <= HIGH_IV_X else 0
    pts.append((ivp, "Implied vs realized volatility"))
    rank = sum(p for p, _ in pts)
    # penalties and caps
    if plan.get("flow_conflict"):
        rank -= 15; pts.append((-15, "Big money is positioned the other way"))
    if any("Earnings in" in w for w in plan.get("warnings", [])):
        rank -= 15; pts.append((-15, "Earnings within 14 days"))
    if plan["direction"] == "WATCH":
        rank = min(rank, 60)
    if not o or not o.get("liquid"):
        rank = min(rank, 40)        # no liquid, tight-spread contract → hidden
    if max(rr1, (b or plan)["rr2"]) < MIN_RR:
        rank = min(rank, 50)        # can't reach 3:1 → hidden
    return int(round(max(0, min(100, rank)))), pts


def option_idea(side, entry, stop, t1, t2, df, today, ear, prefer=None):
    if df is None:
        return None
    cp = "C" if side == "LONG" else "P"
    win = df[(df.cp == cp) & (df.dte >= PLAN_DTE_RANGE[0]) & (df.dte <= PLAN_DTE_RANGE[1])
             & (df.bid > 0) & (df.ask > 0)]
    if not len(win):
        win = df[(df.cp == cp) & (df.bid > 0) & (df.ask > 0)]
        if not len(win):
            return None
    ne = ear.get("next_earn")
    # prefer an expiry BEFORE the next earnings (avoid paying the IV ramp)
    exps = sorted(win["expiry"].unique(), key=lambda e: abs((dt.date.fromisoformat(e) - today).days - 35))
    if ne:
        pre = [e for e in exps if dt.date.fromisoformat(e) < ne]
        exps = pre or exps
    cand = win[win.expiry.isin(exps)].copy()
    cand["adelta"] = cand["delta"].abs()
    cand["spread_pct"] = (cand["ask"] - cand["bid"]) / ((cand["ask"] + cand["bid"]) / 2)
    cand["liquid"] = (cand["spread_pct"] <= MAX_SPREAD_PCT) & (cand["openInterest"] >= MIN_CONTRACT_OI) \
        & cand["adelta"].between(0.45, 0.75)
    # closest to 0.60 delta and ~35 days, with a tight spread; liquid contracts first
    cand["fit"] = (cand["adelta"] - 0.60).abs() * 2 + cand["spread_pct"] * 3 + (cand["dte"] - 35).abs() / 60
    pool = cand[cand["liquid"]] if cand["liquid"].any() else cand
    longk = pool.sort_values("fit").iloc[0]
    source = "Closest liquid contract near 0.60 delta, about 5 weeks out"
    if prefer:
        # follow the money: use the exact contract institutions bought if it's liquid and a sensible delta/expiry
        pm = cand[(cand["expiry"] == prefer["expiry"]) & (cand["strike"] == prefer["strike"]) & (cand["cp"] == prefer["cp"])]
        if len(pm) and bool(pm.iloc[0]["liquid"] or (pm.iloc[0]["spread_pct"] <= MAX_SPREAD_PCT and pm.iloc[0]["adelta"] >= 0.30)):
            longk = pm.iloc[0]
            source = "Same contract the big money bought"
    exp = longk["expiry"]
    ch = win[win.expiry == exp].copy()
    dte = int(longk["dte"])
    iv = float(longk["ivc"])
    Th = max(dte - HOLD_DAYS_ASSUMED, 1) / 365
    cost = float(longk["ask"])  # assume you pay the ask (conservative)
    K = float(longk["strike"])
    v_t1 = bs(t1, K, Th, iv, cp)[0]
    v_t2 = bs(t2, K, Th, iv, cp)[0]
    v_st = bs(stop, K, Th, iv, cp)[0]
    # what the contract should cost when the stock reaches the entry trigger (~1 day out)
    v_en = max(bs(entry, K, max(dte - 1, 1) / 365, iv, cp)[0], 0.01)
    ed = dt.date.fromisoformat(exp)
    label = f"{ed.strftime('%b')} {ed.day} ${K:g} {'call' if cp == 'C' else 'put'}"
    single = dict(kind=f"Buy {exp} {K:g}{cp} (Δ≈{longk['delta']:+.2f})", label=label, delta=float(longk["delta"]),
                  bid=float(longk["bid"]), ask=cost, mid=(float(longk["bid"]) + cost) / 2, cost=cost,
                  at_entry=v_en, at_t1=v_t1, at_t2=v_t2, at_stop=v_st,
                  rr=(v_t1 - cost) / max(cost - v_st, 0.01),
                  rr_entry=(v_t1 - v_en) / max(v_en - v_st, 0.01), iv=iv, dte=dte, expiry=exp,
                  spread=cost - float(longk["bid"]), spread_pct=float(longk["spread_pct"]),
                  oi=int(longk["openInterest"]), vol=int(longk["volume"]),
                  liquid=bool(longk["liquid"] or longk["spread_pct"] <= MAX_SPREAD_PCT), source=source,
                  strike=float(longk["strike"]), cp=cp, contract=str(longk.get("contractSymbol", "")))

    # debit spread capped at the wall/target
    shorts = ch[(ch["strike"] > longk["strike"]) if cp == "C" else (ch["strike"] < longk["strike"])]
    spread = None
    if len(shorts):
        sk = shorts.iloc[(shorts["strike"] - t1).abs().argsort()].iloc[0]
        debit = float(longk["ask"] - sk["bid"])
        width = abs(sk["strike"] - longk["strike"])
        if 0 < debit < width:
            sv_t1 = bs(t1, longk["strike"], Th, iv, cp)[0] - bs(t1, sk["strike"], Th, float(sk["ivc"]), cp)[0]
            sv_st = bs(stop, longk["strike"], Th, iv, cp)[0] - bs(stop, sk["strike"], Th, float(sk["ivc"]), cp)[0]
            spread = dict(kind=f"{exp} {longk['strike']:g}/{sk['strike']:g}{cp} debit spread", cost=debit,
                          at_t1=sv_t1, at_stop=sv_st, max_profit=width - debit,
                          rr=(sv_t1 - debit) / max(debit - sv_st, 0.01), rr_max=(width - debit) / debit)
    return dict(single=single, spread=spread)


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------
def publish_housekeeping():
    SITE_DIR.mkdir(parents=True, exist_ok=True)
    (SITE_DIR / ".nojekyll").touch()            # tell GitHub Pages to serve files as-is
    cutoff = dt.date.today() - dt.timedelta(days=KEEP_REPORT_DAYS)
    for f in REPORT_DIR.glob("*_20*.*"):
        try:
            if dt.date.fromisoformat(f.stem.split("_")[-1]) < cutoff:
                f.unlink()
        except ValueError:
            pass


def scan_one(sym, today, events):
    tk = yf.Ticker(sym)
    hist = retry(tk.history, period="2y", interval="1d", auto_adjust=False)
    if hist is None or len(hist) < 120:
        raise RuntimeError("not enough price history")
    px = price_context(hist)
    ear = earnings_context(tk, hist, today)
    df = load_chains(tk, px["spot"], today)
    if df is None or not len(df):
        raise RuntimeError("no listed options in range")
    w = walls(df, px["spot"])
    flow, bias, bull, bear = unusual_flow(df, today, px["spot"])
    inst = institutional_read(flow, px["spot"], bull, bear)
    follow = oi_followup(sym, df)
    totals = premium_totals(df, px["spot"])
    flowx = premium_surge(sym, totals)
    flowx.update(bias=bias, bull=bull, bear=bear, inst=inst)
    atm = df[(df.cp == "C") & (df.dte >= 20)]
    iv_info = dict(atm_iv=None, hv=px["hv20"], ratio=None, level="", iv_rank=None)
    if len(atm):
        a = atm.iloc[(atm["strike"] - px["spot"]).abs().argsort()].iloc[0]
        iv_info["atm_iv"] = float(a["ivc"])
        iv_info["ratio"] = float(a["ivc"]) / px["hv20"] if px["hv20"] else None
        iv_hv = f"{a['ivc']:.0%} vs {px['hv20']:.0%}" + (" (cheap)" if a["ivc"] < px["hv20"] * 1.1 else " (rich)" if a["ivc"] > px["hv20"] * 1.5 else "")
    else:
        iv_hv = "—"
    # IV rank vs this ticker's own stored history (needs ~10 nights)
    past = []
    for f in sorted(SNAP_DIR.glob(f"{sym}_*.json")):
        try:
            t = json.loads(f.read_text()).get("totals") or {}
            if t.get("atm_iv"):
                past.append(t["atm_iv"])
        except Exception:
            pass
    if iv_info["atm_iv"] and len(past) >= 10:
        lo, hi = min(past + [iv_info["atm_iv"]]), max(past + [iv_info["atm_iv"]])
        iv_info["iv_rank"] = (iv_info["atm_iv"] - lo) / (hi - lo) * 100 if hi > lo else 50.0
    r_ = iv_info["ratio"]
    if (r_ and r_ >= HIGH_IV_X) or (iv_info["iv_rank"] is not None and iv_info["iv_rank"] >= 80):
        iv_info["level"] = "High IV"
    elif r_ and r_ >= 1.2:
        iv_info["level"] = "Elevated IV"
    totals["atm_iv"] = iv_info["atm_iv"]
    strat = strat_scan(hist)
    tfc = ftfc(hist)
    plan = build_plan(sym, px, ear, w, bias, follow, df, today, events, strat, tfc, flowx)
    o = (plan.get("option") or {}).get("single")
    if o:
        o["iv_ratio"] = o["iv"] / px["hv20"] if px["hv20"] else None
        o["high_iv"] = bool(o["iv_ratio"] and o["iv_ratio"] >= HIGH_IV_X)
    plan["iv"] = iv_info
    plan["rank"], plan["rank_parts"] = rank_plan(plan, px, flowx, follow, tfc, iv_info)
    save_snapshot(sym, today, flow, totals)
    return dict(sym=sym, px=px, ear=ear, walls=w, flow=flow, follow=follow, plan=plan, iv_hv=iv_hv, iv=iv_info,
                strat=strat, tfc=tfc, flowx=flowx)


def main():
    today = dt.date.today()
    REPORT_DIR.mkdir(exist_ok=True)
    events = load_events()
    universe = load_watchlist()
    recent, upcoming = discover_earnings(today)
    for s in recent:
        if s not in universe:
            universe.append(s)
    upcoming = [u for u in upcoming if u[0] not in recent]
    log(f"Scanning {len(universe)} tickers ({len(recent)} recent reporters added)")
    results, errors = [], []
    for i, sym in enumerate(universe, 1):
        try:
            log(f"[{i}/{len(universe)}] {sym}")
            results.append(scan_one(sym, today, events))
        except Exception as ex:
            errors.append((sym, str(ex)[:120]))
            log(f"  skipped {sym}: {ex}")
    page = SR.render_plan(results, upcoming, today, errors, MIN_RR, STRAT_TFS, SHOW_MIN_RANK)
    publish_housekeeping()
    (SITE_DIR / "index.html").write_text(page)
    if not (SITE_DIR / "check.html").exists():
        (SITE_DIR / "check.html").write_text(SR.placeholder_check(today))
    (REPORT_DIR / f"plan_{today.isoformat()}.html").write_text(page)
    keep = []
    for r in results:
        p = r["plan"]
        if p.get("rank", 0) < SHOW_MIN_RANK:
            continue
        keep.append(dict(rank=p.get("rank"), sym=r["sym"], direction=p["direction"], side=p["side"], entry=p["entry"], stop=p["stop"],
                         t1=p["t1"], t2=p["t2"], trigger=p["trigger"], atr=r["px"]["atr"], last=r["px"]["spot"],
                         d_high=r["strat"].get("D", {}).get("high"), d_low=r["strat"].get("D", {}).get("low"),
                         best=p.get("strat_best"), flow=r["flow"], post=p["post_earnings"],
                         contract=((p.get("option") or {}).get("single") or {}).get("label"),
                         option=(p.get("option") or {}).get("single"), use_entry=p.get("use_entry"), use_stop=p.get("use_stop"),
                         warnings=p.get("warnings", []), inst_lines=(p.get("inst") or {}).get("lines", []),
                         inst_stance=(p.get("inst") or {}).get("stance"), flow_conflict=p.get("flow_conflict", False)))
    (REPORT_DIR / "plans_latest.json").write_text(json.dumps(dict(date=today.isoformat(), generated=dt.datetime.now().isoformat(),
                                                                  after_close=dt.datetime.now().hour >= 16, plans=keep), default=float))
    with open(REPORT_DIR / f"plan_{today.isoformat()}.csv", "w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["ticker", "rank", "direction", "post_earnings", "score", "last", "trigger", "stop", "t1", "t2", "rr_t1", "rr_t2",
                     "put_wall", "call_wall", "next_earnings"])
        for r in results:
            p, w = r["plan"], r["walls"]
            wr.writerow([r["sym"], p.get("rank"), p["direction"], p["post_earnings"], round(p["score"], 1), round(r["px"]["spot"], 2), p["trigger"],
                         round(p["stop"], 2), round(p["t1"], 2), round(p["t2"], 2), round(p["rr1"], 2), round(p["rr2"], 2),
                         w.get("put_wall"), w.get("call_wall"), r["ear"].get("next_earn")])
    log(f"Done → {SITE_DIR / 'index.html'}  ({len(results)} plans, {len(errors)} skipped)")


# ----------------------------------------------------------------------------
# 9:50 am morning check: opening range vs last night's plans + overnight OI + early flow
# ----------------------------------------------------------------------------
def intraday(tk):
    h = retry(tk.history, period="1d", interval="1m")
    if h is None or not len(h):
        return None
    if h.index[-1].date() != dt.date.today():
        return None
    return h


def classify_open(p, h):
    """Status of last night's plan after the opening range."""
    atr, side = p["atr"], p["side"]
    b = p.get("best")
    trig = b["trigger"] if b else p["entry"]
    stop = b["stop"] if b else p["stop"]
    t1 = p["t1"]
    now = float(h["Close"].iloc[-1])
    first = h[h.index <= h.index[0] + pd.Timedelta(minutes=29)]
    orh, orl = float(first["High"].max()), float(first["Low"].min())
    hi, lo = float(h["High"].max()), float(h["Low"].min())
    gap = float(h["Open"].iloc[0]) / p["last"] - 1
    if p.get("d_high") and hi > p["d_high"] and p.get("d_low") and lo < p["d_low"]:
        candle = "3 so far"
    elif p.get("d_high") and hi > p["d_high"]:
        candle = "2U so far"
    elif p.get("d_low") and lo < p["d_low"]:
        candle = "2D so far"
    else:
        candle = "1 so far"
    sg = 1 if side == "LONG" else -1
    touched_trig = (hi >= trig) if sg > 0 else (lo <= trig)
    hit_stop = (lo <= stop) if sg > 0 else (hi >= stop)
    beyond = sg * (now - trig) / atr
    risk_now = sg * (now - stop)
    rr_now = sg * (t1 - now) / risk_now if risk_now > 0 else 0.0
    orx = orh if sg > 0 else orl
    if hit_stop and sg * (now - stop) <= 0:
        state, txt = "Stopped", f"Traded through the stop at {fmt(stop)}. Plan is off for today."
    elif sg * (now - t1) >= 0:
        state, txt = "At target", f"Already at target 1 ({fmt(t1)}). Don't chase it."
    elif touched_trig and beyond > 0.5:
        state, txt = "Extended", (f"Triggered at {fmt(trig)} and ran {beyond:.1f} ATR past it. "
                                  f"Wait for a pullback toward {fmt(trig)} or the opening-range {'high' if sg > 0 else 'low'} {fmt(orx)}.")
    elif touched_trig and beyond >= 0:
        state, txt = "Triggered", (f"Triggered at {fmt(trig)} and holding. Valid entry with the stop at {fmt(stop)}; "
                                   f"a break of the opening-range {'high' if sg > 0 else 'low'} {fmt(orx)} adds confirmation.")
    elif touched_trig:
        state, txt = "Failed", (f"Traded {'above' if sg > 0 else 'below'} {fmt(trig)} then fell back "
                                f"({'failed 2U' if sg > 0 else 'failed 2D'}). Skip unless it reclaims {fmt(trig)}.")
    else:
        state, txt = "Waiting", (f"Not triggered. Set an alert at {fmt(trig)}. Price is {abs(beyond):.1f} ATR away; "
                                 f"the opening range is {fmt(orl)} to {fmt(orh)}.")
    return dict(sym=p["sym"], dir=p["direction"], side=side, now=now, gap=gap, candle=candle, state=state, status=txt,
                contract=p.get("contract"), rank=p.get("rank"),
                trig=trig, stop=stop, t1=t1, orh=orh, orl=orl, rr_now=rr_now)


def plan_action(p, row, live):
    """One plain instruction for the morning, plus the ticket details."""
    opt = p.get("option") or {}
    sym, long_ = p["sym"], p["side"] == "LONG"
    name = f"{sym} {opt['label']}" if opt.get("label") else None
    px = live["mid"] if live and live["mid"] > 0 else None
    limit = f"limit {fmt(px)} or less" if px else "use a limit order at the mid price"
    st = row["state"]
    if not name:
        act, kind = "No liquid contract for this plan. Skip it.", "no"
    elif st == "Triggered":
        act, kind = f"BUY NOW: {name}, {limit}.", "go"
    elif st == "Waiting":
        act, kind = (f"WAIT: set an alert at {fmt(row['trig'])}. Buy {name} only when {sym} trades "
                     f"{'above' if long_ else 'below'} it."), "wait"
    elif st == "Extended":
        act, kind = f"DON'T CHASE: buy {name} only on a pullback toward {fmt(row['trig'])}.", "wait"
    else:
        act, kind = "NO TRADE today: the setup failed or already hit its level.", "no"
    am = row.get("inst_am") or {}
    want = "Bullish" if long_ else "Bearish"
    if kind in ("go", "wait") and am.get("stance") in ("Bullish", "Bearish") and am["stance"] != want:
        act += " Caution: this morning's options flow leans the other way."
    if kind in ("go", "wait") and p.get("flow_conflict"):
        act += " Last night's big money was positioned against this trade."
    return dict(action=act, action_kind=kind, opt=opt, live=live, t2=p.get("t2"),
                warnings=p.get("warnings", []), inst_lines=p.get("inst_lines", []))


def check():
    f = REPORT_DIR / "plans_latest.json"
    if not f.exists():
        log("No plans_latest.json yet — run the evening scan first."); return 1
    data = json.loads(f.read_text())
    today = dt.date.today()
    futs = []
    for sym, name in (("ES=F", "S&P futures"), ("NQ=F", "Nasdaq futures")):
        try:
            fi = yf.Ticker(sym).fast_info
            futs.append((name, fi["lastPrice"] / fi["previousClose"] - 1))
            time.sleep(SLEEP)
        except Exception:
            pass
    rows, oi_rows, early, stale = [], [], {}, True
    for p in data["plans"]:
        tk = yf.Ticker(p["sym"])
        try:
            h = intraday(tk)
        except Exception as ex:
            log(f"  {p['sym']}: {ex}"); continue
        if h is None:
            continue
        row = classify_open(p, h)
        rows.append(row)
        # OI follow-up on last night's flagged contracts + early flow on the same expirations
        flagged = p.get("flow") or []
        exps = list(dict.fromkeys(x["expiry"] for x in flagged))[:2]
        opt = p.get("option") or {}
        if opt.get("expiry") and opt["expiry"] not in exps:
            exps.append(opt["expiry"])
        if p["direction"] != "WATCH" and not exps:
            try:
                exps = [e for e in retry(lambda: tk.options)
                        if PLAN_DTE_RANGE[0] <= (dt.date.fromisoformat(e) - today).days <= PLAN_DTE_RANGE[1]][:1]
            except Exception:
                exps = []
        now_oi, frames = {}, []
        for ex in exps:
            try:
                ch = retry(tk.option_chain, ex)
            except Exception:
                continue
            dte = (dt.date.fromisoformat(ex) - today).days
            for side, d in (("C", ch.calls), ("P", ch.puts)):
                now_oi.update(dict(zip(d["contractSymbol"], d["openInterest"].fillna(0))))
                d = d.copy(); d["cp"], d["expiry"], d["dte"] = side, ex, dte
                frames.append(d)
        for x in flagged:
            if x["contract"] in now_oi:
                chg = int(now_oi[x["contract"]] - x["oi"])
                stale = stale and chg == 0
                ratio = chg / max(x["volume"], 1)
                oi_rows.append(dict(sym=p["sym"], c=f"{x['expiry']} {x['strike']:g}{x['cp']}", label=x["label"], vol=x["volume"],
                                    chg=chg, v="Opened, confirmed" if ratio >= 0.5 else "Closed, ignore" if chg < 0 else "Mixed"))
        live = None
        if frames:
            df = pd.concat(frames, ignore_index=True)
            for c in ("volume", "openInterest", "bid", "ask", "lastPrice", "impliedVolatility"):
                df[c] = pd.to_numeric(df.get(c), errors="coerce").fillna(0.0)
            df["mid"] = np.where((df["bid"] > 0) & (df["ask"] > 0), (df["bid"] + df["ask"]) / 2, df["lastPrice"])
            ef, _, eb, er = unusual_flow(df, today, row["now"])
            if ef:
                early[p["sym"]] = ef
                row["inst_am"] = institutional_read(ef, row["now"], eb, er)
            if opt.get("contract"):
                m = df[df["contractSymbol"] == opt["contract"]]
                if len(m):
                    q = m.iloc[0]
                    live = dict(bid=float(q["bid"]), ask=float(q["ask"]), last=float(q["lastPrice"]),
                                mid=float(q["mid"]), vol=int(q["volume"]))
        row.update(plan_action(p, row, live))
        now_str = dt.datetime.now().strftime("%-I:%M %p").lower()
    page = SR.render_check(rows, oi_rows, early, futs, stale and bool(oi_rows), data["date"], today, now_str)
    publish_housekeeping()
    (SITE_DIR / "check.html").write_text(page)
    (REPORT_DIR / f"check_{today.isoformat()}.html").write_text(page)
    log(f"Done → {SITE_DIR / 'check.html'}  ({len(rows)} checked)")
    return 0


if __name__ == "__main__":
    sys.exit(check() if ("--check" in sys.argv or "--morning" in sys.argv) else main())
