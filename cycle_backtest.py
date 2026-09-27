"""
Pre-registered consistency check of the Altseason cyklus index.

    python cycle_backtest.py --selftest   synthetic checks only, no data
    python cycle_backtest.py              lock PREREG, evaluate on cycle_history.json

Adam's requirement (2026-09-26): the index must sit on the 2017/18 and 2021
altseason peaks. With two peaks there is no statistics to speak of, and the design
already knew both cycles — so this is called what it is, a consistency check, not
an out-of-sample test. What keeps it honest:

- PREREG below is hashed into backtest_cache/cycle_prereg.lock the first time the
  script runs, BEFORE any index value is computed on real data (the design was
  debugged on synthetic series only). A changed PREREG is refused and needs a new id.
- Peaks are dated by stated rules, not picked by eye.
- Four variants of two knobs that can mis-time a gate by a week (breadth gate on the
  raw weekly or its 4-week mean; T = 0.9 or 0.85 x the index at the 2018 peak) and the
  rule that picks one are fixed here; all four are reported.
- If no variant passes, the report says FAIL and nothing is tuned.

Writes cycle_backtest_summary.json (read by the collector: the chosen variant and T)
and cycle_backtest_report.html (charts for Adam).
"""
import datetime
import hashlib
import io
import json
import math
import os
import sys

import cycle

LOCK = os.path.join("backtest_cache", "cycle_prereg.lock")

PREREG = {
    "id": "altseason-cycle-v1",
    "registered": "2026-09-26",
    "weeks": "Monday 00:00 UTC; inputs from 2014-07-07",
    "components": {
        "rotation": ["BTC.D drawdown: 1 - mean4(BTC.D) / max(mean4(BTC.D), 52 w), trailing percentile",
                     "OTHERS.D rise: mean4(OTHERS.D) / min(mean4(OTHERS.D), 52 w) - 1, trailing percentile",
                     "breadth: share of top-50 alts beating BTC over 13 w, 4-week mean, used raw"],
        "heat": ["mean of trailing percentiles of MVRV ratio, Puell (issuance / 365-d mean), "
                 "Mayer (price / 200-d mean), Pi Cycle (111-d mean / 2 x 350-d mean); >= 3 of 4 present"],
    },
    "percentile": "mid-rank over the previous 208 weeks, current excluded, min 104 values",
    "index": "I = (rotation + heat) / 2; rotation needs >= 2 of 3 parts; None if a pillar is missing",
    "phases": {
        "order": ["po_vrcholu", "prehrate", "bezi", "zacina", "btc_sezona", "zima"],
        "po_vrcholu": "two consecutive prehrate weeks within the last 26 w and I <= their max - 15",
        "prehrate": "I >= T and breadth_gate >= 75 and BTC.D dd52 >= 25",
        "bezi": "rotation >= 60 and (gate >= 75 or (gate >= 50 and dd52 >= 25))",
        "zacina": "rotation >= 40 and (rotation up >= 15 over 13 w or an OTHERS.D breakout within 13 w)",
        "btc_sezona": "heat >= 50 and rotation < 40",
        "zima": "otherwise",
    },
    "T": "round(t_factor x max I over [P1 - 8 w, P1 + 2 w]), clamped to [80, 90]",
    "events": {
        "P0": "min weekly BTC.D in 2017-01-01..2017-09-30 (reported)",
        "P1": "min weekly BTC.D in [2017-12-17 - 26 w, + 13 w] (required)",
        "P2": "min weekly BTC.D in [2021-04-14 - 26 w, + 13 w] (required)",
        "P2b": "max OTHERS USD in 2021-07-01..2021-12-31 (reported)",
    },
    "evaluation_start": "first week where every component has >= 104 weeks of scores (index not None)",
    "pass": [
        "a prehrate week in [P - 8 w, P + 2 w] for P1 and for P2",
        "cycle 1 (eval start..2019-12-31) highest I week in [P1 - 12 w, P1 + 4 w]; "
        "cycle 2 (2020-01-01..2022-12-31) highest I week in [P2 - 12 w, P2 + 4 w]",
        "share of evaluated weeks with I >= T at most 10 %",
        "at most 2 prehrate episodes outside [P - 16 w, P + 8 w] of every event, not counting an episode "
        "followed by an OTHERS USD drawdown >= 40 % within 8 weeks (a caught local top)",
    ],
    "variants": [{"breadth_gate": g, "t_factor": f} for g in ("mean4", "raw") for f in (0.9, 0.85)],
    "selection": "passes all -> fewest false episodes -> fewest weeks >= T -> (mean4, 0.9)",
    "reported_only": ["forward 13/26-week OTHERS USD return and vs BTC per phase, by episode",
                      "window sensitivity 104/156/260 weeks"],
    # a literal: this used to read cycle.DEFAULT_RULES at import, so a v2 edit of the
    # defaults would have changed v1's hash and its lock would have refused every run
    "trendline": {"trend_break": 0.03, "trend_fail": 0.03, "trend_min_weeks": 40,
                  "trend_max_weeks": 156, "trend_pivot": 4, "trend_touch_gap": 8},
}
V1_SHA256 = "2fb9e3884563f40bcddbab7660595eb4a8b91b2119d59f07c0d82aad449917c7"   # = the v1 lock


def prereg_hash():
    return hashlib.sha256(json.dumps(PREREG, sort_keys=True).encode("utf-8")).hexdigest()


def prereg_lock():
    h = prereg_hash()
    if os.path.exists(LOCK):
        lk = json.load(io.open(LOCK, encoding="utf-8"))
        return lk, lk.get("sha256") == h
    os.makedirs(os.path.dirname(LOCK), exist_ok=True)
    lk = {"id": PREREG["id"], "sha256": h,
          "locked_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    with io.open(LOCK, "w", encoding="utf-8") as f:
        json.dump(lk, f, indent=1)
    return lk, True


def file_sha(p):
    try:
        return hashlib.sha256(open(p, "rb").read()).hexdigest()
    except OSError:
        return None


# ================================================================== evaluation
def evaluate(weeks, s, ev, rules, eval_start, cycles):
    res = cycle.compute_index(weeks, s, rules)
    I, ph = res["index"], res["phase"]
    T = rules["T"]
    out = {"T": T}
    in_win = lambda i, P, lo, hi: P is not None and P - lo <= i <= P + hi
    # 1. prehrate around P1 and P2
    for P in ("P1", "P2"):
        p = ev.get(P)
        out["hit_" + P] = any(ph[i] == "prehrate" for i in range(len(weeks)) if in_win(i, p, 8, 2))
    # 2. cycle maxima
    for name, (lo, hi), P in (("c1", cycles[0], "P1"), ("c2", cycles[1], "P2")):
        idx = [i for i in range(len(weeks)) if lo <= weeks[i] <= hi and I[i] is not None]
        top = max(idx, key=lambda i: (I[i], -i)) if idx else None
        out["max_" + name] = top
        out["max_ok_" + name] = top is not None and in_win(top, ev.get(P), 12, 4)
    # 3. share of weeks >= T
    ev_idx = [i for i in range(len(weeks)) if weeks[i] >= eval_start and I[i] is not None]
    out["weeks_ge_T"] = sum(1 for i in ev_idx if I[i] >= T)
    out["share_ge_T"] = 100.0 * out["weeks_ge_T"] / max(1, len(ev_idx))
    # 4. false prehrate episodes
    eps = [e for e in cycle.phase_episodes(weeks, ph) if e[0] == "prehrate"]
    false, caught, near = [], [], []
    ou = s["others_usd"]
    for e in eps:
        a = e[1]
        if any(in_win(a, ev.get(P), 16, 8) for P in ("P0", "P1", "P2", "P2b")):
            near.append(e)
            continue
        base = ou[a]
        fut = [x for x in ou[a:a + 9] if x is not None]
        dd = (min(fut) / base - 1) * 100 if (base and fut) else None
        (caught if (dd is not None and dd <= -40) else false).append(e + [dd])
    out["episodes_near"] = [[weeks[e[1]], weeks[e[2]]] for e in near]
    out["episodes_caught"] = [[weeks[e[1]], weeks[e[2]], r1(e[3])] for e in caught]
    out["episodes_false"] = [[weeks[e[1]], weeks[e[2]], r1(e[3])] for e in false]
    out["pass"] = bool(out["hit_P1"] and out["hit_P2"] and out["max_ok_c1"] and out["max_ok_c2"]
                       and out["share_ge_T"] <= 10.0 and len(false) <= 2)
    out["_res"] = res
    return out


def r1(x):
    return None if x is None else round(x, 1)


def forward_by_phase(weeks, s, phase):
    """What alts did after each phase episode started: 13/26 weeks, OTHERS USD
    and OTHERS vs BTC. Episodes, not weeks — neighbouring weeks are one event."""
    ou, btc = s["others_usd"], s["btc"]
    out = {}
    for p, a, b in cycle.phase_episodes(weeks, phase):
        row = {"start": weeks[a], "end": weeks[b]}
        for h in (13, 26):
            j = a + h
            if j < len(weeks) and ou[a] and ou[j]:
                row["usd%d" % h] = round((ou[j] / ou[a] - 1) * 100, 1)
                if btc[a] and btc[j]:
                    row["vbtc%d" % h] = round(((ou[j] / ou[a]) / (btc[j] / btc[a]) - 1) * 100, 1)
        out.setdefault(p, []).append(row)
    return out


# ================================================================== selftest
def selftest():
    ok = True

    def check(cond, msg):
        nonlocal ok
        print(("  ok   " if cond else "  FAIL ") + msg)
        ok = ok and cond

    # v1 is locked and still reported: its registration and its rules must not move
    check(prereg_hash() == V1_SHA256, "v1 PREREG hash unchanged (%s…)" % prereg_hash()[:12])
    check(all(cycle.V1_RULES[k] == v for k, v in PREREG["trendline"].items()),
          "v1 trendline rules = the registered literals")
    # percentile: mid-rank, ties split
    check(cycle.pct_rank([1, 2, 3, 4], 3) == 62.5, "mid-rank percentile with a tie")
    tp = cycle.trailing_pct(list(range(300)), 208, 104)
    check(tp[103] is None and tp[104] == 100.0, "trailing percentile starts at 104 values, new high = 100")
    # a planted downtrend and breakout
    # anchor 12,0 at week 10, a lower high at week 30 sets the line (slope -0,035),
    # the line is at 9,9 on week 70; a close of 11,0 there is 11 % over it
    vals = [10.0] * 10 + [12.0] + [12.0 - 0.05 * k for k in range(1, 60)] + [11.0] * 5
    vals[30] = vals[30] + 0.3
    lines = cycle.trend_break(vals, "down")
    b = [L for L in lines if L["anchor"] == 10]
    check(bool(b) and b[0]["breakout"] == 70 and b[0]["touch"] == 30, "planted breakout found at its week")
    poke = [10.0] * 10 + [12.0] + [12.0 - 0.05 * k for k in range(1, 60)]
    poke[30] += 0.3
    line = poke[10] + max((poke[j] - poke[10]) / (j - 10) for j in range(11, 70)) * (70 - 10)
    poke.append(line * 1.02)
    check(not any(L["breakout"] == 70 for L in cycle.trend_break(poke, "down") if L["anchor"] == 10),
          "a 2 % poke is not a breakout")
    lu = cycle.trend_break([30 - v for v in vals], "up")
    check(any(L["anchor"] == 10 and L["breakout"] == 70 for L in lu), "mirror case (rising support) finds the breakdown")
    killed = [10.0] * 10 + [12.0] + [11.0] * 50 + [12.5] + [11.0] * 10
    check(not any(L["anchor"] == 10 for L in cycle.trend_break(killed, "down")), "an exceeded anchor is dropped")
    # the index on a synthetic cycle: flat, then a rotation + heat surge
    n = 400
    weeks = [cycle.START_WEEK + i * cycle.WEEK for i in range(n)]
    import random
    rnd = random.Random(7)
    bd = [70 + rnd.uniform(-1, 1) for _ in range(n)]
    od = [5 + rnd.uniform(-0.2, 0.2) for _ in range(n)]
    br = [30 + rnd.uniform(-5, 5) for _ in range(n)]
    heat = [1 + rnd.uniform(-0.1, 0.1) for _ in range(n)]
    for i in range(330, 345):                        # the planted altseason
        k = i - 329
        bd[i] = 70 - 3 * k
        od[i] = 5 + 0.8 * k
        br[i] = 95
        heat[i] = 1 + 0.3 * k
    s = {"btcd": bd, "othersd": od, "breadth": br, "others_usd": od, "btc": [1.0] * n,
         "mvrv": heat, "puell": heat, "mayer": heat, "pi": heat, "breakouts": [False] * n}
    res = cycle.compute_index(weeks, s, dict(cycle.DEFAULT_RULES, T=85))
    peak = max(range(n), key=lambda i: res["index"][i] or -1)
    check(330 <= peak <= 345, "synthetic peak lands in the planted altseason (week %d)" % peak)
    check("prehrate" in res["phase"][330:346], "the planted altseason reads prehrate")
    check("prehrate" not in res["phase"][:320], "no prehrate before it")
    check(res["phase"][200] in ("zima", "btc_sezona", "zacina", "bezi"), "a quiet week has a phase")
    # NaN must be refused before it reaches the page
    try:
        json.dumps({"x": float("nan")}, allow_nan=False)
        check(False, "NaN rejected")
    except ValueError:
        check(True, "NaN rejected by allow_nan=False")
    print("SELFTEST", "OK" if ok else "FAILED")
    return 0 if ok else 1


# ================================================================== report
def svg_line(weeks, series_list, w=980, h=260, y_fmt=lambda v: "%.0f" % v, bands=None, shade=None,
             lines=None, marks=None, ymin=None, ymax=None):
    xs = [i for i in range(len(weeks))]
    allv = [v for ser, _ in series_list for v in ser if v is not None]
    lo = min(allv) if ymin is None else ymin
    hi = max(allv) if ymax is None else ymax
    pad = 40
    X = lambda i: pad + (w - pad - 10) * i / max(1, len(weeks) - 1)
    Y = lambda v: 10 + (h - 30) * (1 - (v - lo) / ((hi - lo) or 1))
    out = ['<svg width="%d" height="%d" style="background:#1b1816;border-radius:8px">' % (w, h)]
    for y0, y1, col in bands or []:
        out.append('<rect x="%d" y="%.1f" width="%d" height="%.1f" fill="%s" opacity=".12"/>'
                   % (pad, Y(y1), w - pad - 10, Y(y0) - Y(y1), col))
    for a, b, col in shade or []:
        out.append('<rect x="%.1f" y="10" width="%.1f" height="%d" fill="%s" opacity=".25"/>'
                   % (X(a), max(2, X(b) - X(a)), h - 30, col))
    for v in (lo, (lo + hi) / 2, hi):
        out.append('<text x="4" y="%.1f" fill="#8c8175" font-size="10">%s</text>' % (Y(v) + 3, y_fmt(v)))
    yr = None
    for i, t in enumerate(weeks):
        y = datetime.datetime.fromtimestamp(t, datetime.timezone.utc).year
        if y != yr:
            yr = y
            out.append('<text x="%.1f" y="%d" fill="#8c8175" font-size="10">%d</text>' % (X(i), h - 6, y))
    for ser, col in series_list:
        d = []
        for i, v in enumerate(ser):
            if v is None:
                continue
            d.append(("M" if not d or ser[i - 1] is None else "L") + "%.1f %.1f" % (X(i), Y(v)))
        out.append('<path d="%s" fill="none" stroke="%s" stroke-width="1.6"/>' % ("".join(d), col))
    for (i0, v0, i1, v1, col) in lines or []:
        out.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" stroke-dasharray="5 4" stroke-width="1.5"/>'
                   % (X(i0), Y(v0), X(i1), Y(v1), col))
    for (i, v, col, label) in marks or []:
        out.append('<circle cx="%.1f" cy="%.1f" r="4" fill="%s"/><text x="%.1f" y="%.1f" fill="%s" font-size="11">%s</text>'
                   % (X(i), Y(v), col, X(i) + 6, Y(v) - 6, col, label))
    out.append("</svg>")
    return "".join(out)


PH_COL = {"zima": "#8c8175", "btc_sezona": "#5c82c4", "zacina": "#3fa37e", "bezi": "#b98a34",
          "prehrate": "#d97158", "po_vrcholu": "#a8432f"}


def report_html(summary, weeks, s, chosen, all_res):
    res = chosen["_res"]
    I = res["index"]
    ev = summary["events"]
    evi = {k: v for k, v in summary["events_idx"].items() if v is not None}
    shade = [(max(0, i - 8), min(len(weeks) - 1, i + 2), "#d97158") for k, i in evi.items() if k in ("P1", "P2")]
    shade += [(i, i, "#b98a34") for k, i in evi.items() if k in ("P0", "P2b")]
    first = next((i for i, t in enumerate(weeks) if t >= cycle.DISPLAY_FROM), 0)
    W = weeks[first:]
    cut = lambda a: a[first:]
    sh = [(a - first, b - first, c) for a, b, c in shade if b >= first]
    idx_svg = svg_line(W, [(cut(res["rotation"]), "#5c82c4"), (cut(res["heat"]), "#b98a34"), (cut(I), "#f3eee5")],
                       bands=[(chosen["T"], 100, "#d97158")], shade=sh, ymin=0, ymax=100)
    od = s["othersd"]
    n = len(weeks)
    lines = cycle.trend_break(od, "down")
    picked = cycle.pick_lines(lines, n)
    a0 = max(0, min([L["anchor"] for L in picked] or [n - 156]) - 26)
    W2 = weeks[a0:]
    ln = []
    mk = []
    for L in picked:
        i1 = n - 1
        v0 = od[L["anchor"]]
        v1 = v0 + L["slope"] * (i1 - L["anchor"])
        ln.append((L["anchor"] - a0, v0, i1 - a0, v1, "#d97158"))
        mk.append((L["touch"] - a0, od[L["touch"]], "#8fb0e6", "dotek"))
        if L["breakout"] is not None:
            mk.append((L["breakout"] - a0, od[L["breakout"]], "#3fa37e", "průlom %s" % cycle.iso(weeks[L["breakout"]])))
    od_svg = svg_line(W2, [(od[a0:], "#8fb0e6")], y_fmt=lambda v: "%.1f %%" % v, lines=ln, marks=mk)
    bd_svg = svg_line(W, [(cut(s["btcd"]), "#b98a34")], y_fmt=lambda v: "%.0f %%" % v)
    rows = []
    for k, v in summary["variants"].items():
        rows.append("<tr><td>%s</td><td>%s</td><td>%.0f</td><td>%s</td><td>%s</td><td>%s/%s</td><td>%.1f %%</td><td>%d</td></tr>" % (
            k, "PASS" if v["pass"] else "fail", v["T"], v["hit_P1"], v["hit_P2"], v["max_ok_c1"], v["max_ok_c2"],
            v["share_ge_T"], len(v["episodes_false"])))
    fwd = []
    for p, eps in summary["forward_by_phase"].items():
        for e in eps[-6:]:
            fwd.append("<tr><td style='color:%s'>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
                PH_COL.get(p, "#ccc"), p, cycle.iso(e["start"]), e.get("usd13"), e.get("vbtc13"), e.get("usd26")))
    evrows = "".join("<tr><td>%s</td><td>%s</td><td>%s</td></tr>" % (
        k, cycle.iso(v) if v else "—", r1(I[summary["events_idx"][k]]) if summary["events_idx"].get(k) is not None else "—")
        for k, v in ev.items())
    lines_txt = "".join("<li>kotva %s (%.2f %%), dotek %s, %s%s — linie dnes %.2f %%, poslední týden %+.1f %%</li>" % (
        cycle.iso(weeks[L["anchor"]]), od[L["anchor"]], cycle.iso(weeks[L["touch"]]),
        L["status"], (" " + cycle.iso(weeks[L["breakout"]])) if L["breakout"] is not None else "",
        L["line_now"], L["dist_pct"] or 0) for L in picked)
    return """<!doctype html><meta charset="utf-8"><title>Altseason cyklus — backtest</title>
<style>body{background:#131110;color:#f3eee5;font:14px 'IBM Plex Sans',system-ui;max-width:1040px;margin:24px auto;padding:0 16px}
td,th{padding:4px 10px;border-bottom:1px solid #2c2723;text-align:left}h1,h2{font-weight:600}.v{font-size:22px;font-weight:700}</style>
<h1>Altseason cyklus — pre-registrovaný backtest</h1>
<p class="v">Verdikt: %s · vybraná varianta %s (T = %.0f)</p>
<p>PREREG %s · sha256 %s… · zamčeno %s · %s</p>
<h2>Index 2016 → dnes</h2><p>bílá = index, modrá = rotace do altů, zlatá = BTC cyklus; červeně okna vrcholů 2018 a 2021, zlatě P0/P2b; pruh = práh T</p>%s
<table><tr><th>událost</th><th>týden</th><th>index</th></tr>%s</table>
<h2>Varianty</h2><table><tr><th>varianta</th><th>výsledek</th><th>T</th><th>P1</th><th>P2</th><th>max cyklů</th><th>týdnů ≥ T</th><th>falešné epizody</th></tr>%s</table>
<p>Falešné epizody vybrané varianty: %s · zachycené lokální vrcholy: %s</p>
<h2>OTHERS.D — downtrend a průlom</h2>%s<ul>%s</ul><p>poslední den: %s</p>
<h2>BTC dominance</h2>%s
<h2>Co alty udělaly po začátku fáze (13 t v USD · 13 t proti BTC · 26 t v USD)</h2><table>%s</table>
<h2>Citlivost na okno percentilu</h2><pre>%s</pre>
""" % (summary["verdict"], summary["chosen"], chosen["T"], summary["prereg_id"], summary["prereg_sha256"][:12],
       summary["locked_utc"], "PREREG beze změny" if summary["prereg_ok"] else "PREREG ZMĚNĚN",
       idx_svg, evrows, "".join(rows), summary["variants"][summary["chosen"]]["episodes_false"],
       summary["variants"][summary["chosen"]]["episodes_caught"], od_svg, lines_txt,
       json.dumps(summary.get("latest")), bd_svg, "".join(fwd), json.dumps(summary["sensitivity"], indent=1))


# ================================================================== main
def main():
    lk, same = prereg_lock()          # FIRST: before any index value exists
    if not same:
        print("PREREG se změnil proti zámku %s — v1 je zamčená, změna potřebuje nové id" % LOCK)
        return 2
    H, _ = cycle.load_history(os.getcwd())
    if not H:
        print("cycle_history.json chybí — nejdřív python tools/cycle_seed.py")
        return 2
    import time
    now = int(time.time())
    weeks = cycle.week_axis(now)
    s = cycle.series_from_history(H, weeks)
    evi = cycle.find_events(weeks, s)
    base = dict(cycle.V1_RULES)
    probe = cycle.compute_index(weeks, s, base)
    I = probe["index"]
    eval_i = next((i for i, v in enumerate(I) if v is not None), None)
    eval_start = weeks[eval_i] if eval_i is not None else weeks[-1]
    p1 = evi.get("P1")
    p1max = max((I[i] for i in range(max(0, p1 - 8), min(len(weeks), p1 + 3)) if I[i] is not None),
                default=None) if p1 is not None else None
    cyc = [(eval_start, int(datetime.datetime(2019, 12, 31, tzinfo=datetime.timezone.utc).timestamp())),
           (int(datetime.datetime(2020, 1, 1, tzinfo=datetime.timezone.utc).timestamp()),
            int(datetime.datetime(2022, 12, 31, tzinfo=datetime.timezone.utc).timestamp()))]
    variants = {}
    for v in PREREG["variants"]:
        T = min(90.0, max(80.0, round(v["t_factor"] * p1max))) if p1max is not None else 85.0
        rules = dict(base, breadth_gate=v["breadth_gate"], t_factor=v["t_factor"], T=T)
        name = "%s/%s" % (v["breadth_gate"], v["t_factor"])
        variants[name] = evaluate(weeks, s, evi, rules, eval_start, cyc)
        variants[name]["rules"] = rules
    passing = [k for k, v in variants.items() if v["pass"]]
    order = lambda k: (len(variants[k]["episodes_false"]), variants[k]["weeks_ge_T"], k != "mean4/0.9")
    chosen = min(passing, key=order) if passing else "mean4/0.9"
    ch = variants[chosen]
    sens = {}
    for win in (104, 156, 260):
        r = cycle.compute_index(weeks, s, dict(ch["rules"], window=win, min_window=min(104, win)))
        sens[str(win)] = {k: r1(r["index"][i]) for k, i in evi.items() if i is not None}
    summary = {
        "prereg_id": PREREG["id"], "prereg_sha256": lk["sha256"], "locked_utc": lk["locked_utc"],
        "prereg_ok": same, "cycle_py_sha256": file_sha("cycle.py"),
        "generated_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "verdict": "PASS" if passing else "FAIL", "chosen": chosen,
        "rules": {k: ch["rules"][k] for k in ("breadth_gate", "t_factor", "T")},
        "events": {k: (weeks[i] if i is not None else None) for k, i in evi.items()},
        "events_idx": evi, "eval_start": eval_start, "p1_max": r1(p1max),
        "index_at": {k: r1(I[i]) for k, i in evi.items() if i is not None},
        "variants": {k: {kk: vv for kk, vv in v.items() if kk not in ("_res", "rules")} for k, v in variants.items()},
        "forward_by_phase": forward_by_phase(weeks, s, ch["_res"]["phase"]),
        "sensitivity": sens,
        "latest": {"week": weeks[-1], "index": r1(ch["_res"]["index"][-1]), "phase": ch["_res"]["phase"][-1]},
    }
    for k in ("max_c1", "max_c2"):
        for v in summary["variants"].values():
            v[k] = weeks[v[k]] if isinstance(v[k], int) else None
    with io.open("cycle_backtest_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1, allow_nan=False)
    with io.open("cycle_backtest_report.html", "w", encoding="utf-8") as f:
        f.write(report_html(summary, weeks, s, ch, variants))
    print("verdikt %s · varianta %s · T %.0f · index P1 %s P2 %s · dnes %s (%s)" % (
        summary["verdict"], chosen, ch["T"], summary["index_at"].get("P1"), summary["index_at"].get("P2"),
        summary["latest"]["index"], summary["latest"]["phase"]))
    return 0


if __name__ == "__main__":
    sys.exit(selftest() if "--selftest" in sys.argv else main())
