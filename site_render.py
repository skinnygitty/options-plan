"""
Renders the two pages of the site:
  docs/index.html  — tonight's plan (evening scan)
  docs/check.html  — the 10:00 am check
Mobile-first, light/dark aware, no build step. Everything is in one file per page.
"""
import datetime as dt
import html
import math

e = html.escape

FONTS = ("<link rel='preconnect' href='https://fonts.googleapis.com'><link rel='preconnect' href='https://fonts.gstatic.com' crossorigin>"
         "<link href='https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,500;12..96,700"
         "&family=Instrument+Sans:wght@400;500;600&display=swap' rel='stylesheet'>")

CSS = """
:root{--bg:#EDF0F3;--surface:#FFFFFF;--ink:#15202B;--muted:#5B6875;--line:#D9DEE4;
--long:#0B7A55;--long-soft:#DDF1E8;--short:#B93A32;--short-soft:#F8E3E0;--signal:#3346C8;--signal-soft:#E3E7FB;
--amber:#9A6200;--amber-soft:#FBEFD8;--radius-card:14px;--radius-pill:999px;
--display:'Bricolage Grotesque',ui-sans-serif,system-ui,sans-serif;--text:'Instrument Sans',ui-sans-serif,system-ui,-apple-system,sans-serif}
@media (prefers-color-scheme:dark){:root{--bg:#0E151C;--surface:#162029;--ink:#E6EBF0;--muted:#8D9AA6;--line:#26323D;
--long:#3CC48F;--long-soft:#12352A;--short:#F07167;--short-soft:#3B1E1C;--signal:#8C9BFF;--signal-soft:#202A55;--amber:#E8B04B;--amber-soft:#3A2C12}}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);font:400 15px/1.55 var(--text);font-variant-numeric:tabular-nums}
a{color:inherit}
.wrap{max-width:760px;margin:0 auto;padding:0 18px 64px}
header.top{position:sticky;top:0;z-index:5;background:color-mix(in srgb,var(--bg) 88%,transparent);backdrop-filter:blur(10px);
 -webkit-backdrop-filter:blur(10px);border-bottom:1px solid var(--line)}
header.top .wrap{display:flex;align-items:center;justify-content:space-between;gap:12px;padding-top:10px;padding-bottom:10px}
.brand{font:700 17px/1 var(--display);letter-spacing:-.01em}
nav.tabs{display:flex;gap:4px;background:var(--surface);border:1px solid var(--line);border-radius:var(--radius-pill);padding:3px}
nav.tabs a{text-decoration:none;font-weight:500;font-size:14px;padding:6px 12px;border-radius:var(--radius-pill);color:var(--muted)}
nav.tabs a[aria-current=page]{background:var(--ink);color:var(--surface)}
.hero{padding:34px 0 8px}
.hero .when{color:var(--muted);font-size:14px;margin:0 0 6px}
.hero h1{font:700 clamp(30px,7vw,46px)/1.05 var(--display);letter-spacing:-.025em;margin:0;max-width:18ch}
.hero p.sub{color:var(--muted);margin:12px 0 0;max-width:60ch}
.chips{display:flex;flex-wrap:wrap;gap:8px;margin:22px 0 6px}
.chips button{font:500 14px var(--text);color:var(--ink);background:var(--surface);border:1px solid var(--line);
 border-radius:var(--radius-pill);padding:7px 14px;cursor:pointer}
.chips button[aria-pressed=true]{background:var(--ink);color:var(--surface);border-color:var(--ink)}
.chips button .n{color:var(--muted);margin-left:4px}
.chips button[aria-pressed=true] .n{color:inherit;opacity:.7}
button:focus-visible,a:focus-visible,summary:focus-visible{outline:2px solid var(--signal);outline-offset:2px}
.list{display:flex;flex-direction:column;gap:12px;margin-top:14px}
.card{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius-card);padding:18px 18px 6px}
.card[hidden]{display:none}
.head{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap}
.sym{font:700 26px/1 var(--display);letter-spacing:-.02em}
.pill{font-size:13px;font-weight:600;padding:3px 10px;border-radius:var(--radius-pill);white-space:nowrap}
.pill.LONG{background:var(--long-soft);color:var(--long)}.pill.SHORT{background:var(--short-soft);color:var(--short)}
.pill.WATCH{background:var(--bg);color:var(--muted)}.pill.POST{background:var(--amber-soft);color:var(--amber)}
.pill.GOOD{background:var(--long-soft);color:var(--long)}.pill.BAD{background:var(--short-soft);color:var(--short)}
.pill.WAIT{background:var(--signal-soft);color:var(--signal)}
.rr{margin-left:auto;font-weight:600;font-size:14px}
.rr.ok{color:var(--long)}.rr.no{color:var(--muted)}
.enter{margin:14px 0 0;font-size:15px}
.enter b{font-weight:600}
.ladder{position:relative;height:74px;margin:10px 4px 2px}
.ladder .rail{position:absolute;left:0;right:0;top:36px;height:2px;background:var(--line);border-radius:2px}
.ladder .band{position:absolute;top:32px;height:10px;border-radius:3px}
.band.risk{background:var(--short-soft)}.band.reward{background:var(--long-soft)}.band.reward2{background:var(--long-soft);opacity:.5}
.band.orng{background:var(--signal-soft);top:30px;height:14px}
.mk{position:absolute;top:30px;width:2px;height:14px;transform:translateX(-1px);background:var(--muted)}
.mk.stop{background:var(--short)}.mk.t{background:var(--long)}.mk.wall{background:var(--line);height:10px;top:32px}
.mk.entry{width:12px;height:12px;top:31px;transform:translateX(-6px) rotate(45deg);background:var(--signal);border-radius:2px}
.mk.last{width:12px;height:12px;top:31px;transform:translateX(-6px);border-radius:50%;background:var(--surface);border:2px solid var(--ink)}
.mk.now{width:14px;height:14px;top:30px;transform:translateX(-7px);border-radius:50%;background:var(--ink)}
.lb{position:absolute;font-size:12px;line-height:1.1;color:var(--muted);white-space:nowrap;transform:translateX(-50%)}
.lb.up{top:6px}.lb.dn{top:52px}
.lb.edge-l{transform:none}.lb.edge-r{transform:translateX(-100%)}
.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin:8px 0 4px}
.stat span{display:block;font-size:12px;color:var(--muted)}
.stat b{font-weight:600;font-size:15px}
details.more{border-top:1px solid var(--line);margin-top:12px}
details.more summary{cursor:pointer;list-style:none;padding:12px 0;font-weight:500;color:var(--muted);font-size:14px}
details.more summary::-webkit-details-marker{display:none}
details.more summary::after{content:'+';float:right;font-size:18px;line-height:1}
details.more[open] summary::after{content:'–'}
details.more[open] summary{color:var(--ink)}
.body h3{font:700 16px/1.3 var(--display);margin:18px 0 6px}
.body h3:first-child{margin-top:0}
.body ul{margin:4px 0 8px;padding-left:18px}.body li{margin:2px 0}
.body p{margin:4px 0 8px}
.check{list-style:none;padding:0!important}.check li{display:flex;gap:8px}
.muted{color:var(--muted)}.warn{color:var(--short)}.good{color:var(--long)}
.scroll{overflow-x:auto;-webkit-overflow-scrolling:touch;margin:4px 0 10px}
table{border-collapse:collapse;width:100%;font-size:13.5px}
th,td{text-align:left;padding:7px 10px 7px 0;border-bottom:1px solid var(--line);vertical-align:top;white-space:nowrap}
th{font-weight:500;color:var(--muted)}
td.wrap-ok{white-space:normal;min-width:180px}
.tfc{display:inline-flex;gap:4px;vertical-align:middle;margin-left:6px}
.tfc i{font-style:normal;font-size:12px;font-weight:600;width:22px;height:22px;display:inline-grid;place-items:center;border-radius:6px}
.tfc i.G{background:var(--long-soft);color:var(--long)}.tfc i.R{background:var(--short-soft);color:var(--short)}
section.block{margin-top:40px}
section.block h2{font:700 22px/1.2 var(--display);letter-spacing:-.015em;margin:0 0 4px}
section.block > p{color:var(--muted);margin:0 0 12px;max-width:60ch}
.plain{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius-card);padding:6px 18px}
footer{color:var(--muted);font-size:13px;margin-top:48px;max-width:62ch}
.empty{background:var(--surface);border:1px dashed var(--line);border-radius:var(--radius-card);padding:28px 18px;color:var(--muted)}
@media (max-width:520px){.stats{grid-template-columns:repeat(2,1fr)}.sym{font-size:24px}.brand{display:none}
 header.top .wrap{justify-content:center}.card{padding:16px 14px 4px}}
@media (prefers-reduced-motion:no-preference){details.more[open] .body{animation:open .18s ease-out}
 @keyframes open{from{opacity:0;transform:translateY(-4px)}to{opacity:1;transform:none}}}
"""

FILTER_JS = """
<script>
(function(){var bs=document.querySelectorAll('.chips button'),cs=document.querySelectorAll('.card[data-dir]');
bs.forEach(function(b){b.addEventListener('click',function(){bs.forEach(function(x){x.setAttribute('aria-pressed','false')});
b.setAttribute('aria-pressed','true');var f=b.dataset.f;cs.forEach(function(c){var show=f==='all'||c.dataset.dir===f||(f==='post'&&c.dataset.post==='1');
c.hidden=!show;});});});})();
</script>"""


def money_fmt(x, nd=2):
    if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
        return "—"
    return f"${x:,.{nd}f}"


def money_short(x):
    if x is None:
        return "—"
    for unit, div in (("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if abs(x) >= div:
            return f"${x / div:,.1f}{unit}"
    return f"${x:,.0f}"


def nice_day(d):
    return d.strftime("%A, %B ") + str(d.day)


def next_session(d):
    n = d + dt.timedelta(days=1)
    while n.weekday() >= 5:
        n += dt.timedelta(days=1)
    return n


def page(title, active, body, script=""):
    tabs = (f"<a href='index.html' {'aria-current=page' if active == 'plan' else ''}>Tonight</a>"
            f"<a href='check.html' {'aria-current=page' if active == 'check' else ''}>10:00 check</a>")
    return (f"<!doctype html><html lang='en'><head><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width,initial-scale=1,viewport-fit=cover'><meta name='robots' content='noindex,nofollow'>"
            f"<meta name='theme-color' content='#EDF0F3' media='(prefers-color-scheme: light)'>"
            f"<meta name='theme-color' content='#0E151C' media='(prefers-color-scheme: dark)'>"
            f"<title>{e(title)}</title>{FONTS}<style>{CSS}</style></head><body>"
            f"<header class='top'><div class='wrap'><span class='brand'>Options plan</span><nav class='tabs'>{tabs}</nav></div></header>"
            f"<main class='wrap'>{body}</main>{script}</body></html>")


# ---------------------------------------------------------------------------
# The price ladder — the one visual idea on the page
# ---------------------------------------------------------------------------
def ladder(levels, bands=()):
    """levels: list of (label, price, kind). bands: list of (lo, hi, cls). Returns HTML."""
    pts = [p for _, p, _ in levels if p is not None] + [x for b in bands for x in b[:2] if x is not None]
    if len(pts) < 2:
        return ""
    lo, hi = min(pts), max(pts)
    pad = (hi - lo) * 0.06 or 1
    lo, hi = lo - pad, hi + pad
    pos = lambda p: (p - lo) / (hi - lo) * 100
    out = ["<div class='ladder' role='img' aria-label='Price levels: " +
           e(", ".join(f"{l} {money_fmt(p)}" for l, p, _ in levels if p is not None)) + "'><div class='rail'></div>"]
    for a, b, cls in bands:
        if a is None or b is None:
            continue
        x0, x1 = sorted((pos(a), pos(b)))
        out.append(f"<div class='band {cls}' style='left:{x0:.2f}%;width:{max(x1 - x0, .4):.2f}%'></div>")
    lv = [x for x in levels if x[1] is not None]
    for label, p, kind in lv:
        out.append(f"<div class='mk {kind}' style='left:{pos(p):.2f}%'></div>")
    # place labels by priority; each goes above or below, whichever side has room; low-priority labels drop if crowded
    prio = {"entry": 0, "stop": 1, "t": 2, "now": 2, "last": 3, "wall": 4}
    placed = {"up": [], "dn": []}
    pref = {"entry": "up", "stop": "dn", "t": "dn", "now": "up", "last": "up", "wall": "up"}
    for label, p, kind in sorted(lv, key=lambda x: prio.get(x[2], 5)):
        if not label:
            continue
        x = pos(p)
        wdt = 2.1 * len(label) + 1          # label width in % of the rail at phone width (~2% per character)
        edge = " edge-l" if x - wdt / 2 < 0 else " edge-r" if x + wdt / 2 > 100 else ""
        span = (x, x + wdt) if edge == " edge-l" else (x - wdt, x) if edge == " edge-r" else (x - wdt / 2, x + wdt / 2)
        first = pref.get(kind, "up")
        for side in (first, "dn" if first == "up" else "up"):
            if all(span[1] + 1.5 <= a0 or span[0] >= a1 + 1.5 for a0, a1 in placed[side]):
                placed[side].append(span)
                out.append(f"<div class='lb {side}{edge}' style='left:{x:.2f}%'>{e(label)}</div>")
                break
    out.append("</div>")
    return "".join(out)


def plan_ladder(r):
    p, w, px = r["plan"], r["walls"], r["px"]
    b = p.get("strat_best")
    entry = b["trigger"] if b else p["entry"]
    stop = b["stop"] if b else p["stop"]
    near = lambda a, c: a is not None and c is not None and abs(a - c) < px["atr"] * 0.15
    cw, pw = w.get("call_wall"), w.get("put_wall")
    t1_label = "T1"
    if p["side"] == "LONG" and near(p["t1"], cw):
        t1_label, cw = "T1 call wall", None
    if p["side"] == "SHORT" and near(p["t1"], pw):
        t1_label, pw = "T1 put wall", None
    lv = [("Stop", stop, "stop"), ("Entry", entry, "entry"), (t1_label, p["t1"], "t"), ("T2", p["t2"], "t")]
    if not near(px["spot"], entry):
        lv.append(("Last", px["spot"], "last"))
    if cw and not near(cw, p["t2"]):
        lv.append(("Call wall", cw, "wall"))
    if pw and not near(pw, stop):
        lv.append(("Put wall", pw, "wall"))
    bands = [(stop, entry, "risk"), (entry, p["t1"], "reward"), (p["t1"], p["t2"], "reward2")]
    return ladder(lv, bands), entry, stop


# ---------------------------------------------------------------------------
# Evening page
# ---------------------------------------------------------------------------
def card_body(r, MIN_RR, STRAT_TFS):
    p, w, px, ear = r["plan"], r["walls"], r["px"], r["ear"]
    re_ = ear.get("reaction")
    o = ["<div class='body'>"]
    o.append("<h3>Why</h3><ul>" + "".join(f"<li>{e(x)}</li>" for x in p["reasons"]) + "</ul>")
    if p["warnings"]:
        o.append("<ul>" + "".join(f"<li class='warn'>{e(x)}</li>" for x in p["warnings"]) + "</ul>")
    ck = p.get("checklist") or []
    if ck:
        o.append("<h3>Before you enter</h3><ul class='check'>")
        for okv, txt in ck:
            mark = "✅" if okv is True else "❌" if okv is False else "👀"
            o.append(f"<li><span aria-hidden='true'>{mark}</span><span>{e(txt)}</span></li>")
        o.append("</ul>")
    if re_:
        o.append(f"<h3>Earnings</h3><p>Reported {ear['last_earn']}. Reaction day {re_['date']}: gapped {re_['gap']:+.1%}, closed "
                 f"{re_['move']:+.1%}; now {re_['since']:+.1%} from the pre-earnings close, {re_['bars_since']} session(s) later. "
                 f"Reaction-day range {money_fmt(re_['low'])} to {money_fmt(re_['high'])}."
                 + (f" EPS {ear.get('eps_act')} vs {ear.get('eps_est')} expected." if ear.get("eps_act") is not None else "")
                 + (f" Next report {ear['next_earn']}." if ear.get("next_earn") else "") + "</p>")
    elif ear.get("next_earn"):
        o.append(f"<h3>Earnings</h3><p>Next report {ear['next_earn']}.</p>")

    # Strat
    tfc = r.get("tfc")
    chips = "".join(f"<i class='{v}' title='{k}'>{k}</i>" for k, v in tfc["tfs"].items()) if tfc else ""
    o.append(f"<h3>The Strat</h3><p>Continuity <span class='tfc'>{chips}</span> <b>{e(tfc['state']) if tfc else ''}</b></p>")
    o.append("<div class='scroll'><table><tr><th>TF</th><th>Last 3</th><th>Last candle</th><th>Signal</th><th>High</th><th>Low</th></tr>")
    for tf in STRAT_TFS:
        d = (r.get("strat") or {}).get(tf)
        if not d:
            continue
        extra = f" <span class='muted'>({e(d['in_progress'])})</span>" if d.get("in_progress") else ""
        o.append(f"<tr><td><b>{tf}</b></td><td>{e(d['seq'])}</td><td>{d['last']} {d['color']}{extra}</td>"
                 f"<td>{e(', '.join(d['signals']) or '—')}</td><td>{money_fmt(d['high'])}</td><td>{money_fmt(d['low'])}</td></tr>")
    o.append("</table></div>")
    rows = p.get("strat_rows") or []
    if rows:
        best = p.get("strat_best")
        o.append(f"<p class='muted'>{p['side'].title()} setups. R:R runs from the trigger to the Strat stop, with the walls as targets.</p>"
                 "<div class='scroll'><table><tr><th>TF</th><th>Combo</th><th>Trigger</th><th>Stop</th><th>Away</th><th>R:R T1</th><th>R:R T2</th></tr>")
        for x in rows[:8]:
            star = "★ " if best and x is best else ""
            cls = "good" if max(x["rr1"], x["rr2"]) >= MIN_RR and x["rr1"] > 0 else "muted"
            o.append(f"<tr><td>{star}{x['tf']}</td><td>{e(x['name'])}</td><td>{money_fmt(x['trigger'])}</td><td>{money_fmt(x['stop'])}</td>"
                     f"<td>{x['dist_atr']:+.1f} ATR</td><td class='{cls}'>{x['rr1']:.1f}</td><td class='{cls}'>{x['rr2']:.1f}</td></tr>")
        o.append("</table></div>")

    # levels & options context
    o.append("<h3>Levels</h3><div class='scroll'><table>"
             f"<tr><th>Put wall</th><td>{money_fmt(w.get('put_wall'))} by gamma, {money_fmt(w.get('put_wall_oi'))} by open interest</td></tr>"
             f"<tr><th>Call wall</th><td>{money_fmt(w.get('call_wall'))} by gamma, {money_fmt(w.get('call_wall_oi'))} by open interest</td></tr>"
             f"<tr><th>Dealer gamma</th><td class='wrap-ok'>{e(w.get('regime', ''))}</td></tr>"
             f"<tr><th>ATR (14 day)</th><td>{money_fmt(px['atr'])}</td></tr>"
             f"<tr><th>IV vs realized</th><td>{e(r['iv_hv'])}</td></tr>"
             f"<tr><th>Put/call volume</th><td>{'—' if w.get('pc_vol') is None else '{:.2f}'.format(w['pc_vol'])}</td></tr>"
             "</table></div>")
    o.append(f"<p class='muted'>{e(p['entry_note'])}</p>")

    opt = p.get("option")
    if opt:
        s = opt["single"]
        o.append(f"<h3>Option trade</h3><p class='muted'>Estimated values about a week out with IV unchanged, paying the ask. "
                 f"IV {s['iv']:.0%}, {s['dte']} days to expiry. Option R:R runs lower than the stock's because of time decay and the spread, "
                 f"so size the position off the stock stop.</p><div class='scroll'><table><tr><th>Trade</th><th>Cost</th><th>At T1</th><th>At stop</th><th>R:R</th></tr>"
                 f"<tr><td>{e(s['kind'])}</td><td>{money_fmt(s['cost'])}</td><td>{money_fmt(s['at_t1'])}</td><td>{money_fmt(s['at_stop'])}</td><td>{s['rr']:.1f}</td></tr>")
        if opt.get("spread"):
            sp = opt["spread"]
            o.append(f"<tr><td>{e(sp['kind'])}</td><td>{money_fmt(sp['cost'])}</td><td>{money_fmt(sp['at_t1'])}</td><td>{money_fmt(sp['at_stop'])}</td>"
                     f"<td>{sp['rr']:.1f} <span class='muted'>(max gain {money_fmt(sp['max_profit'])})</span></td></tr>")
        o.append("</table></div>")

    if r["flow"]:
        o.append("<h3>Unusual activity today</h3><div class='scroll'><table><tr><th>Contract</th><th>Volume</th><th>OI</th><th>Premium</th>"
                 "<th>Last trade</th><th>Lean</th></tr>")
        for f in r["flow"]:
            where = "—" if f["pos"] is None else f"{f['pos']:.0%} toward ask"
            o.append(f"<tr><td>{f['expiry']} {f['strike']:g}{f['cp']}</td><td>{f['volume']:,}</td><td>{f['oi']:,}</td>"
                     f"<td>{money_short(f['premium'])}</td><td>{where}</td><td>{e(f['label'])}</td></tr>")
        o.append("</table></div>")
    if r["follow"]:
        o.append("<h3>Did yesterday's flow stick?</h3><div class='scroll'><table><tr><th>Contract</th><th>Lean</th><th>Volume</th>"
                 "<th>OI change</th><th>Verdict</th></tr>")
        for f in r["follow"]:
            o.append(f"<tr><td>{e(f['contract'])}</td><td>{e(f['label'])}</td><td>{f['prev_vol']:,}</td><td>{f['oi_change']:+,}</td><td>{e(f['verdict'])}</td></tr>")
        o.append("</table></div>")
    o.append("</div>")
    return "".join(o)


def render_plan(results, upcoming, today, errors, MIN_RR, STRAT_TFS):
    order = sorted(results, key=lambda r: (r["plan"]["direction"] == "WATCH", not r["plan"]["post_earnings"],
                                           not r["plan"]["rr_ok"], -abs(r["plan"]["score"])))
    nL = sum(r["plan"]["direction"] == "LONG" for r in results)
    nS = sum(r["plan"]["direction"] == "SHORT" for r in results)
    nW = len(results) - nL - nS
    nP = sum(r["plan"]["post_earnings"] for r in results)
    sess = next_session(today)
    plural = lambda n, w: f"{n} {w}{'' if n == 1 else 's'}"
    if nL or nS:
        parts = [x for x in (f"{nL} long" if nL else "", f"{nS} short" if nS else "") if x]
        head = f"{' and '.join(parts)} {'setup' if nL + nS == 1 else 'setups'} for {sess.strftime('%A')}"
    else:
        head = f"Nothing clean for {sess.strftime('%A')}"
    b = [f"<section class='hero'><p class='when'>Plan for {nice_day(sess)}, from the {today.strftime('%b')} {today.day} close</p>"
         f"<h1>{e(head[0].upper() + head[1:])}</h1>"
         f"<p class='sub'>{plural(nW, 'more name')} on watch, {nP} just past earnings. Levels are on the line; tap a ticker for the full plan.</p></section>"]
    b.append("<div class='chips' role='group' aria-label='Filter'>"
             f"<button data-f='all' aria-pressed='true'>All<span class='n'>{len(results)}</span></button>"
             f"<button data-f='LONG' aria-pressed='false'>Long<span class='n'>{nL}</span></button>"
             f"<button data-f='SHORT' aria-pressed='false'>Short<span class='n'>{nS}</span></button>"
             f"<button data-f='post' aria-pressed='false'>Post-earnings<span class='n'>{nP}</span></button>"
             f"<button data-f='WATCH' aria-pressed='false'>Watch<span class='n'>{nW}</span></button></div>")
    b.append("<div class='list'>")
    if not results:
        b.append("<div class='empty'>No tickers scanned. Check watchlist.txt and reports/scanner.log.</div>")
    for r in order:
        p = r["plan"]
        lad, entry, stop = plan_ladder(r)
        best = p.get("strat_best")
        rr1 = best["rr1"] if best else p["rr1"]
        rr2 = best["rr2"] if best else p["rr2"]
        ok = max(rr1, rr2) >= MIN_RR and rr1 > 0
        verb = "above" if p["side"] == "LONG" else "below"
        how = (f"{best['tf']} {best['name']}" if best else p["trigger"])
        lean = "" if p["direction"] != "WATCH" else f" <span class='muted'>(watch; leaning {p['side'].lower()})</span>"
        b.append(f"<article class='card' data-dir='{p['direction']}' data-post='{1 if p['post_earnings'] else 0}'>"
                 f"<div class='head'><span class='sym'>{e(r['sym'])}</span><span class='pill {p['direction']}'>{p['direction'].title()}</span>"
                 + ("<span class='pill POST'>Post-earnings</span>" if p["post_earnings"] else "")
                 + f"<span class='rr {'ok' if ok else 'no'}'>R:R {rr1:.1f} : 1</span></div>"
                 f"<p class='enter'>Enter on a trade {verb} <b>{money_fmt(entry)}</b>, stop {money_fmt(stop)}. "
                 f"<span class='muted'>{e(how)}</span>{lean}</p>"
                 f"{lad}"
                 f"<div class='stats'><div class='stat'><span>Last</span><b>{money_fmt(r['px']['spot'])}</b></div>"
                 f"<div class='stat'><span>Target 1</span><b>{money_fmt(p['t1'])}</b></div>"
                 f"<div class='stat'><span>Target 2</span><b>{money_fmt(p['t2'])}</b></div>"
                 f"<div class='stat'><span>R:R to T2</span><b>{rr2:.1f} : 1</b></div></div>"
                 f"<details class='more'><summary>Full plan</summary>{card_body(r, MIN_RR, STRAT_TFS)}</details></article>")
    b.append("</div>")

    if upcoming:
        b.append("<section class='block'><h2>Reporting soon</h2><p>Implied volatility is high going into these. "
                 "Skip buying options until after the report.</p><div class='plain'><div class='scroll'><table>"
                 "<tr><th>Ticker</th><th>Date</th><th>Timing</th></tr>")
        for s, d, t in sorted(upcoming, key=lambda x: (x[1] or today)):
            b.append(f"<tr><td><b>{e(s)}</b></td><td>{d or ''}</td><td>{e(t)}</td></tr>")
        b.append("</table></div></div></section>")

    b.append("""<section class='block'><h2>Reading the flow</h2><p>Free data can't prove a trade was bought or sold.
The lean comes from where the last trade printed between bid and ask; open interest the next morning tells you whether it was new money.</p>
<div class='plain'><div class='scroll'><table>
<tr><th>What printed</th><th>Usually means</th></tr>
<tr><td>Calls bought, OI up next day</td><td class='wrap-ok'>Bullish, new money</td></tr>
<tr><td>Puts sold, OI up</td><td class='wrap-ok'>Bullish; the seller is happy to own lower</td></tr>
<tr><td>Puts bought, OI up</td><td class='wrap-ok'>Bearish, or a hedge on stock if price is at highs</td></tr>
<tr><td>Calls sold, OI up</td><td class='wrap-ok'>A cap overhead; often covered calls</td></tr>
<tr><td>Big volume, OI down</td><td class='wrap-ok'>Positions closing; not a new signal</td></tr>
</table></div></div>
<p class='muted' style='margin-top:12px'>On the line: the diamond is the entry, red is the stop and risk zone, green is the reward zone out to the targets,
the ring is the last close, and grey ticks are the call and put walls.</p></section>""")
    if errors:
        b.append("<section class='block'><h2>Skipped</h2><p>" + ", ".join(f"{e(s)} ({e(m)})" for s, m in errors) + "</p></section>")
    b.append(f"<footer>Updated {dt.datetime.now().strftime('%b %-d at %-I:%M %p').replace('AM','am').replace('PM','pm')} ET. Built from free Yahoo Finance data after the close. Check every level on your own chart before trading. Not financial advice.</footer>")
    return page(f"Plan for {sess}", "plan", "".join(b), FILTER_JS)


# ---------------------------------------------------------------------------
# 10:00 check page
# ---------------------------------------------------------------------------
STATUS_PILL = {"Triggered": "GOOD", "Waiting": "WAIT", "Extended": "WAIT", "Failed": "BAD", "Stopped": "BAD", "At target": "WAIT"}


def render_check(rows, oi_rows, early, futs, stale, plan_date, today, now_str):
    nT = sum(r["state"] == "Triggered" for r in rows)
    nX = sum(r["state"] == "Extended" for r in rows)
    nF = sum(r["state"] in ("Failed", "Stopped") for r in rows)
    nW = sum(r["state"] == "Waiting" for r in rows)
    bits = []
    if nT: bits.append(f"{nT} triggered and holding")
    if nX: bits.append(f"{nX} extended")
    if nF: bits.append(f"{nF} failed")
    if nW: bits.append(f"{nW} still waiting")
    head = ", ".join(bits) if bits else "No plans to check"
    fut = "  ".join(f"{n} {g:+.2%}" for n, g in futs)
    b = [f"<section class='hero'><p class='when'>{nice_day(today)} at {e(now_str)}, plans from the {dt.date.fromisoformat(plan_date).strftime('%b')} {dt.date.fromisoformat(plan_date).day} close</p>"
         f"<h1>{e(head[0].upper() + head[1:])}</h1>"
         f"<p class='sub'>The first 30 minutes are done; the shaded band on each line is that opening range. {e(fut)}</p></section>"]
    b.append("<div class='chips' role='group' aria-label='Filter'>"
             f"<button data-f='all' aria-pressed='true'>All<span class='n'>{len(rows)}</span></button>"
             f"<button data-f='Triggered' aria-pressed='false'>Triggered<span class='n'>{nT}</span></button>"
             f"<button data-f='Waiting' aria-pressed='false'>Waiting<span class='n'>{nW}</span></button>"
             f"<button data-f='Extended' aria-pressed='false'>Extended<span class='n'>{nX}</span></button></div>")
    b.append("<div class='list'>")
    if not rows:
        b.append("<div class='empty'>The 10:00 check hasn't run yet today. It reads last night's plan and runs at 10:00 am on weekdays.</div>")
    order = ["Triggered", "Extended", "Waiting", "At target", "Failed", "Stopped"]
    for r in sorted(rows, key=lambda r: (r["dir"] == "WATCH", order.index(r["state"]))):
        lv = [("Stop", r["stop"], "stop"), ("Entry", r["trig"], "entry"), ("T1", r["t1"], "t"), ("Now", r["now"], "now")]
        bands = [(r["orl"], r["orh"], "orng"), (r["stop"], r["trig"], "risk"), (r["trig"], r["t1"], "reward")]
        lad = ladder(lv, bands)
        b.append(f"<article class='card' data-dir='{r['state']}'>"
                 f"<div class='head'><span class='sym'>{e(r['sym'])}</span><span class='pill {STATUS_PILL[r['state']]}'>{r['state']}</span>"
                 f"<span class='pill {r['dir']}'>{r['dir'].title()}</span>"
                 f"<span class='rr {'ok' if r['rr_now'] >= 3 else 'no'}'>R:R {r['rr_now']:.1f} : 1 now</span></div>"
                 f"<p class='enter'>{e(r['status'])}</p>{lad}"
                 f"<div class='stats'><div class='stat'><span>Now</span><b>{money_fmt(r['now'])}</b></div>"
                 f"<div class='stat'><span>Open gap</span><b>{r['gap']:+.2%}</b></div>"
                 f"<div class='stat'><span>Opening range</span><b>{money_fmt(r['orl'], 2)}–{money_fmt(r['orh'], 2)}</b></div>"
                 f"<div class='stat'><span>Today's candle</span><b>{e(r['candle'])}</b></div></div>"
                 + (f"<details class='more'><summary>Early options flow</summary><div class='body'>{early_table(early.get(r['sym']))}</div></details>"
                    if early.get(r["sym"]) else "<div style='height:12px'></div>")
                 + "</article>")
    b.append("</div>")

    b.append("<section class='block'><h2>Did last night's flow stick?</h2>"
             "<p>Open interest updates overnight. Up by about the volume means new positions; down means they were closed.</p>")
    if not oi_rows:
        b.append("<div class='empty'>No unusual contracts were flagged last night.</div>")
    elif stale:
        b.append("<div class='empty'>Yahoo hasn't posted today's open interest yet. Run ./run_check.sh again in a few minutes.</div>")
    else:
        b.append("<div class='plain'><div class='scroll'><table><tr><th>Ticker</th><th>Contract</th><th>Lean</th><th>Volume</th>"
                 "<th>OI change</th><th>Verdict</th></tr>")
        for r in oi_rows:
            cls = "good" if r["v"].startswith("Opened") else "muted"
            b.append(f"<tr><td><b>{e(r['sym'])}</b></td><td>{e(r['c'])}</td><td>{e(r['label'])}</td><td>{r['vol']:,}</td>"
                     f"<td>{r['chg']:+,}</td><td class='{cls}'>{e(r['v'])}</td></tr>")
        b.append("</table></div></div>")
    b.append("</section>")
    b.append("<footer>Stock prices from Yahoo are close to real time; option quotes can lag by several minutes. "
             "A trigger counts when price trades through it and holds. Not financial advice.</footer>")
    return page(f"10:00 check {today}", "check", "".join(b), FILTER_JS)


def early_table(rows):
    o = ["<p class='muted'>Contracts with heavy volume in the first 30 minutes. Bid and ask are live now, so the bought/sold lean is more reliable than overnight.</p>"
         "<div class='scroll'><table><tr><th>Contract</th><th>Volume</th><th>OI</th><th>Premium</th><th>Lean</th></tr>"]
    for f in rows:
        o.append(f"<tr><td>{f['expiry']} {f['strike']:g}{f['cp']}</td><td>{f['volume']:,}</td><td>{f['oi']:,}</td>"
                 f"<td>{money_short(f['premium'])}</td><td>{e(f['label'])}</td></tr>")
    o.append("</table></div>")
    return "".join(o)


def placeholder_check(today):
    body = (f"<section class='hero'><p class='when'>{nice_day(next_session(today))}</p><h1>The 10:00 check runs after the open</h1>"
            "<p class='sub'>It reads tonight's plan and shows which triggers fired in the first 30 minutes.</p></section>")
    return page("10:00 check", "check", body)
