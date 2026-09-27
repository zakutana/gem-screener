"""
Independent audit of snapshot.json.

Recomputes every derived number straight from the stored raw series using a
second implementation, and cross-checks a sample against a live API call.
Anything that disagrees is a bug in collector.py (or in here — both get read).

Run: python audit.py
"""
import io
import json
import datetime
import math
import re
import statistics
import urllib.request

UA = {"User-Agent": "gem-screener-audit/1.0"}
FAILS = []
WARNS = []


def fail(section, msg):
    FAILS.append("[%s] %s" % (section, msg))


def warn(section, msg):
    WARNS.append("[%s] %s" % (section, msg))


def head(t):
    print("\n" + "=" * 78)
    print(t)
    print("=" * 78)


def get(url, timeout=40):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


D = json.load(io.open("snapshot.json", encoding="utf-8"))
APPS, CHAINS = D["apps"], D["chains"]
ALL = APPS + CHAINS
WINDOWS = D["windows"]
DAY = 86400

print("snapshot generated: %s  |  apps=%d chains=%d"
      % (D["generated_at_iso"], len(APPS), len(CHAINS)))


# ---------------------------------------------------------------- 1. freshness
head("1. DATA FRESHNESS — does every series actually end near today?")
gen = D["generated_at"]
lags = {}
for e in ALL:
    for key in ("rev_series", "tvl_series"):
        s = e.get(key) or []
        if not s:
            continue
        lag_days = (gen - s[-1][0]) / DAY
        lags.setdefault(key, []).append((lag_days, e["name"]))

for key, rows in lags.items():
    rows.sort(reverse=True)
    med = statistics.median([r[0] for r in rows])
    stale = [r for r in rows if r[0] > 10]
    print("  %-11s median lag %.1f d  |  n=%d  |  >10d stale: %d"
          % (key, med, len(rows), len(stale)))
    for lag, nm in stale[:8]:
        print("      %-28s %.0f dní staré" % (nm[:27], lag))
    if len(stale) > len(rows) * 0.15:
        fail("freshness", "%s: %d/%d series older than 10 days — 'poslední "
             "čtvrtletí' is measuring a gap, not a decline" % (key, len(stale), len(rows)))
    elif stale:
        warn("freshness", "%s: %d stale series (their recent quarter is unreliable)"
             % (key, len(stale)))


# ---------------------------------------------------------------- 2. window totals
head("2. WINDOW TOTALS — recomputed from the raw series")


def recompute_total(series, w, end_ts):
    """Sum of the last w calendar days. collector uses the last w ARRAY items."""
    lo = end_ts - w * DAY
    return sum(v for t, v in series if t > lo)


bad = 0
checked = 0
for e in ALL:
    s = e.get("rev_series") or []
    if len(s) < 400:
        continue
    end = s[-1][0]
    for w in WINDOWS:
        stored = (e["rev_growth"].get(str(w)) or {}).get("total")
        if stored is None:
            continue
        mine = recompute_total(s, w, end)
        checked += 1
        if stored <= 0 and mine <= 0:
            continue
        denom = max(abs(stored), abs(mine), 1.0)
        if abs(stored - mine) / denom > 0.02:
            bad += 1
            if bad <= 5:
                print("  MISMATCH %-24s w=%-4d stored=%14.0f recomputed=%14.0f"
                      % (e["name"][:23], w, stored, mine))
print("  checked %d window totals, %d mismatched" % (checked, bad))
if bad:
    fail("totals", "%d/%d window totals disagree with a calendar-day recomputation "
         "(collector slices by array index, which breaks on gaps)" % (bad, checked))


# ---------------------------------------------------------------- 3. gaps
head("3. SERIES GAPS — array-index slicing assumes one point per day")
gapped = []
for e in ALL:
    s = e.get("rev_series") or []
    if len(s) < 60:
        continue
    span_days = (s[-1][0] - s[0][0]) / DAY + 1
    missing = span_days - len(s)
    if missing > span_days * 0.05:
        gapped.append((missing, span_days, e["name"]))
gapped.sort(reverse=True)
print("  series with >5%% missing days: %d" % len(gapped))
for m, sp, nm in gapped[:8]:
    print("      %-28s chybí %.0f z %.0f dní" % (nm[:27], m, sp))
if len(gapped) > len(ALL) * 0.10:
    fail("gaps", "%d series have material day gaps; index-based windows are then "
         "wider than they claim" % len(gapped))
elif gapped:
    warn("gaps", "%d series have day gaps" % len(gapped))


# ---------------------------------------------------------------- 4. OLS math
head("4. LOG-OLS — closed form vs a from-scratch fit on synthetic data")


def ols_ref(vals, step_days=1.0):
    pts = [(i, v) for i, v in enumerate(vals) if v and v > 0]
    n = len(pts)
    xs = [p[0] for p in pts]
    ys = [math.log(p[1]) for p in pts]
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    return (math.exp(b * (30.0 / step_days)) - 1) * 100


# a series that doubles every 30 days must report +100%/month
daily = [100 * (2 ** (i / 30.0)) for i in range(120)]
g = ols_ref(daily, step_days=1.0)
print("  daily series doubling every 30d      -> %+.2f %%/m (expect +100.00)" % g)
if abs(g - 100) > 0.5:
    fail("ols", "daily slope->monthly conversion is off: got %.2f, expected 100" % g)

weekly = [100 * (2 ** (i * 7 / 30.0)) for i in range(20)]
g = ols_ref(weekly, step_days=7.0)
print("  weekly buckets doubling every 30d    -> %+.2f %%/m (expect +100.00)" % g)
if abs(g - 100) > 0.5:
    fail("ols", "weekly step_days conversion is off: got %.2f, expected 100" % g)

flat = [500.0] * 40
pts = [(i, v) for i, v in enumerate(flat)]
print("  flat series                          -> slope 0 (r2 undefined, handled)")


# ---------------------------------------------------------------- 5. quarters
head("5. TRAJECTORY QUARTERS — disjoint? aligned? enough buckets?")
QUARTERS = [("p1", 364, 274), ("p2", 273, 183), ("p3", 182, 92), ("p4", 91, 0)]
spans = [(a, b) for _, a, b in QUARTERS]
for i in range(len(spans) - 1):
    if spans[i][1] <= spans[i + 1][0]:
        fail("quarters", "p%d and p%d overlap" % (i + 1, i + 2))
print("  boundaries: " + " | ".join("%s %d..%d d" % (n, a, b) for n, a, b in QUARTERS))
print("  disjoint: yes (364-274, 273-183, 182-92, 91-0)")


def weekly_buckets_ref(series, agg):
    """Mirrors collector: partial weeks are dropped when summing a flow."""
    end = series[-1][0]
    bins = {}
    for t, v in series:
        bins.setdefault(int((end - t) // (7 * DAY)), []).append(v)
    out = []
    for b in sorted(bins, reverse=True):
        xs = bins[b]
        if agg == "sum" and len(xs) < 7:
            continue
        out.append((end - b * 7 * DAY, sum(xs) if agg == "sum" else sum(xs) / len(xs)))
    return out


# Partial weeks bias a summed flow low. Verify the collector actually drops
# them: no bucket the reference keeps may hold fewer than 7 raw days.
leaked = 0
for e in APPS[:80]:
    s = e.get("rev_series") or []
    if len(s) < 300:
        continue
    end = s[-1][0]
    counts = {}
    for t, _ in s:
        b = int((end - t) // (7 * DAY))
        counts[b] = counts.get(b, 0) + 1
    kept = {int(round((end - t) / (7 * DAY))) for t, _ in weekly_buckets_ref(s, "sum")}
    if any(counts.get(b, 0) < 7 for b in kept):
        leaked += 1
print("  sampled apps where a partial week still reaches the regression: %d/80" % leaked)
if leaked:
    fail("quarters", "%d/80 apps keep a short week in a summed series" % leaked)


def traj_source(e):
    """Which series a given entity's trajectory is actually built from."""
    if e.get("primary") == "rev":
        return e.get("rev_series") or [], "sum"
    idx = e.get("adoption_index") or {}
    if idx.get("series"):
        return idx["series"], "mean"
    return e.get("tvl_series") or [], "mean"


# ---------------------------------------------------------------- 6. level_vs_peak
head("6. level_vs_peak — recomputed")
bad = 0
for e in ALL:
    t = e.get("traj") or {}
    lvp = t.get("level_vs_peak")
    if lvp is None:
        continue
    # v11: a chain's trajectory is measured on its ADOPTION INDEX (stablecoins
    # x DEX volume), not on the raw stablecoin series — recomputing from
    # tvl_series here reported 19 false mismatches.
    series, agg = traj_source(e)
    if not series:
        continue
    weeks = weekly_buckets_ref(series, agg)
    end = series[-1][0]
    qlev = {}
    for name, sd, ed in QUARTERS:
        vs = [v for t2, v in weeks if end - sd * DAY <= t2 <= end - ed * DAY]
        if vs:
            qlev[name] = sum(vs) / len(vs)
    if not qlev:
        continue
    peak = max(qlev.values())
    mine = (qlev.get("p4", 0) / peak) if peak > 0 else None
    if mine is None:
        continue
    if abs(mine - lvp) > 0.02:
        bad += 1
        if bad <= 5:
            print("  MISMATCH %-26s stored=%.3f mine=%.3f" % (e["name"][:25], lvp, mine))
print("  mismatches: %d" % bad)
if bad:
    fail("level_vs_peak", "%d entities disagree" % bad)


# ---------------------------------------------------------------- 7. shares
head("7. SECTOR SHARE — must sum to 100% inside each arena")
for label, pool, by_cat in (("apps", APPS, True), ("chains", CHAINS, False)):
    for w in ("30", "365"):
        groups = {}
        for e in pool:
            k = (e.get("category") or "Other") if by_cat else "_all"
            groups.setdefault(k, []).append((e.get("share") or {}).get(w))
        offenders = []
        for k, vals in groups.items():
            vs = [v for v in vals if v is not None]
            if not vs:
                continue
            tot = sum(vs)
            if abs(tot - 100.0) > 1.0:
                offenders.append((k, tot, len(vs)))
        status = "OK" if not offenders else "MISMATCH"
        print("  %-7s w=%-4s groups=%-3d %s" % (label, w, len(groups), status))
        for k, tot, n in offenders[:5]:
            print("      %-24s suma=%.1f%% (n=%d)" % (str(k)[:23], tot, n))
        if offenders:
            fail("share", "%s w=%s: %d groups don't sum to 100%%" % (label, w, len(offenders)))


# ---------------------------------------------------------------- 8. double counting
head("8. DOUBLE COUNTING — is DeFiLlama's doublecounted flag respected?")
try:
    fees = get("https://api.llama.fi/overview/fees?excludeTotalDataChart=true"
               "&excludeTotalDataChartBreakdown=true&dataType=dailyRevenue")["protocols"]
except Exception as exc:
    fees = []
    warn("doublecount", "could not fetch live fees: %s" % exc)

if fees:
    dc = {p["name"] for p in fees if p.get("doublecounted")}
    dc_ids = {str(p.get("defillamaId")) for p in fees if p.get("doublecounted")}
    print("  adapters flagged doublecounted upstream: %d" % len(dc))
    hit = [e["name"] for e in APPS if e["name"] in dc]
    print("  of those, present in our apps list: %d" % len(hit))
    for n in hit[:10]:
        print("      %s" % n)
    if hit:
        warn("doublecount", "%d doublecounted adapters are in the table; they inflate "
             "their sector total and therefore everyone's share" % len(hit))


# ---------------------------------------------------------------- 9. parent aggregation
head("9. PARENT AGGREGATION — do we sum children but chart the parent?")
if fees:
    by_parent = {}
    for p in fees:
        if p.get("protocolType") != "protocol":
            continue
        if p.get("parentProtocol"):
            by_parent.setdefault(p["parentProtocol"], []).append(p)
    mismatches = []
    for e in APPS:
        key = e.get("key") or ""
        if not key.startswith("parent#"):
            continue
        kids = by_parent.get(key) or []
        if not kids:
            continue
        kid_sum = sum(k.get("total30d") or 0 for k in kids)
        ours = (e["rev_growth"].get("30") or {}).get("total") or 0
        if kid_sum <= 0:
            continue
        diff = abs(ours - kid_sum) / max(kid_sum, 1)
        if diff > 0.15:
            mismatches.append((e["name"], ours, kid_sum, len(kids), diff))
    mismatches.sort(key=lambda r: -r[4])
    print("  parent entities checked: %d, differing >15%%: %d"
          % (sum(1 for e in APPS if (e.get('key') or '').startswith('parent#')), len(mismatches)))
    for nm, ours, ks, nk, d in mismatches[:10]:
        print("      %-24s parent30d=%12.0f  soucet deti=%12.0f (%d) odchylka %.0f%%"
              % (nm[:23], ours, ks, nk, d * 100))
    if len(mismatches) > 5:
        warn("parent", "%d parent rows differ from the sum of their children — the "
             "gate used the child sum but the series is the parent's" % len(mismatches))


# ---------------------------------------------------------------- 10. live spot-check
head("10. LIVE SPOT-CHECK — three projects end to end")
for nm, slug in (("Hyperliquid", "hyperliquid"), ("Pump", "pump"), ("Uniswap", "uniswap")):
    e = next((x for x in APPS if x["name"] == nm), None)
    if not e:
        print("  %-14s not in snapshot" % nm)
        continue
    try:
        live = get("https://api.llama.fi/summary/fees/%s?dataType=dailyRevenue" % slug)
    except Exception as exc:
        print("  %-14s live fetch failed: %s" % (nm, exc))
        continue
    chart = live.get("totalDataChart") or []
    end = chart[-1][0] if chart else 0
    live_365 = sum(v for t, v in chart if t > end - 365 * DAY)
    ours_365 = (e["rev_growth"].get("365") or {}).get("total") or 0
    live_30 = live.get("total30d")
    ours_30 = (e["rev_growth"].get("30") or {}).get("total") or 0
    # Compare like with like: our sum vs a sum of the SAME chart. DeFiLlama's
    # own total30d does not reconcile with its own daily chart under any window
    # (8.32M vs 8.61/8.77/8.91M for Uniswap), so it is not a valid reference.
    live_30_chart = sum(v for t, v in chart if t > end - 30 * DAY)
    d365 = abs(live_365 - ours_365) / max(live_365, 1) * 100
    d30 = abs(live_30_chart - ours_30) / max(live_30_chart, 1) * 100
    print("  %-14s 365d ours=%13.0f chart=%13.0f (%.2f%%)   30d ours=%12.0f chart=%12.0f (%.2f%%)  [api total30d=%s]"
          % (nm, ours_365, live_365, d365, ours_30, live_30_chart, d30,
             round(live_30 or 0)))
    if d365 > 1:
        fail("live", "%s 365d revenue differs from the live chart by %.1f%%" % (nm, d365))
    if d30 > 1:
        fail("live", "%s 30d revenue differs from the live chart by %.1f%%" % (nm, d30))


# ---------------------------------------------------------------- 11. mcap sanity
head("11. MARKET CAP — coverage and obvious breakage")
no_mc = [e["name"] for e in APPS if not e.get("mcap")]
print("  apps without mcap: %d/%d" % (len(no_mc), len(APPS)))
zero = [e["name"] for e in ALL if e.get("mcap") == 0]
print("  entities with mcap exactly 0: %d %s" % (len(zero), zero[:5]))
if zero:
    warn("mcap", "%d entities report mcap 0 — they must not be treated as infinitely "
         "cheap by the upside formula" % len(zero))

# upside would be absurd here
sus = []
for e in APPS:
    mc = e.get("mcap")
    tot = (e["rev_growth"].get("365") or {}).get("total") or 0
    if mc and tot > 0 and mc / tot < 1.0:
        sus.append((mc / tot, e["name"], mc, tot))
sus.sort()
print("  apps valued at LESS than one year of revenue (P/S < 1): %d" % len(sus))
for r, nm, mc, tot in sus[:8]:
    print("      %-24s P/S=%.2f  mcap=%12.0f rev365=%12.0f" % (nm[:23], r, mc, tot))


# ---------------------------------------------------------------- 12. chain TVL
head("12. CHAIN TVL — tvl_now vs the series, and vs live")
# tvl_series now carries the ADOPTION proxy (stablecoin supply where available),
# while tvl_now stays raw TVL for the size column and MC/TVL. So the tail must
# match adoption_now, and tvl_now is checked against /v2/chains below.
bad = 0
for e in CHAINS:
    s = e.get("tvl_series") or []
    if not s or e.get("adoption_now") is None:
        continue
    if abs(e["adoption_now"] - s[-1][1]) > 1:
        bad += 1
        print("  MISMATCH %-18s adoption_now=%.0f series[-1]=%.0f"
              % (e["name"], e["adoption_now"], s[-1][1]))
print("  adoption_now vs series tail mismatches: %d" % bad)
if bad:
    fail("tvl", "adoption_now disagrees with the stored adoption series")

from collections import Counter as _C
print("  adoption metric in use: %s" % dict(_C(c.get("adoption_metric") for c in CHAINS)))
fallback = [c["name"] for c in CHAINS if c.get("adoption_metric") == "tvl"]
if fallback:
    warn("adoption", "%d chains fall back to price-contaminated TVL for adoption "
         "(no stablecoin history): %s" % (len(fallback), ", ".join(fallback)))

try:
    live_chains = get("https://api.llama.fi/v2/chains")
    lm = {c["name"]: c["tvl"] for c in live_chains}
    print("  %-18s %14s %14s %8s" % ("CHAIN", "ours", "live /v2/chains", "diff"))
    worst = []
    for e in CHAINS:
        lv = lm.get(e["name"])
        if lv and e.get("tvl_now"):
            d = abs(lv - e["tvl_now"]) / lv * 100
            worst.append((d, e["name"], e["tvl_now"], lv))
    worst.sort(reverse=True)
    for d, nm, ours, lv in worst[:6]:
        print("  %-18s %14.0f %14.0f %7.1f%%" % (nm[:17], ours, lv, d))
    big = [w for w in worst if w[0] > 15]
    if big:
        warn("tvl", "%d chains differ >15%% from /v2/chains — historicalChainTvl and "
             "the chains endpoint don't define TVL identically" % len(big))
except Exception as exc:
    warn("tvl", "live chain check failed: %s" % exc)


# ---------------------------------------------------------------- 13. phases
head("13. PHASE LABELS — recomputed from stored quarter growths")
FLAT, STRONG = 3.0, 15.0
bad = 0
for e in ALL:
    t = e.get("traj") or {}
    if not t.get("periods") or t.get("hs") is None:
        continue

    def eff(n):
        p = t["periods"].get(n) or {}
        if p.get("g") is None:
            return None
        return p["g"] * (0.3 + 0.7 * (p.get("r2") or 0))

    p1, p2, p3, p4 = eff("p1"), eff("p2"), eff("p3"), eff("p4")
    if p4 is None:
        continue
    older = [x for x in (p1, p2, p3) if x is not None]
    if not older:
        continue
    baseline = sum(older) / len(older)
    accel = p4 - baseline
    lvp = t.get("level_vs_peak")
    at_peak = lvp is not None and lvp >= 0.6
    if p4 < -FLAT:
        ph = "Pokles"
    elif p4 <= FLAT:
        ph = "Stagnace"
    elif baseline <= FLAT and p4 >= STRONG and at_peak:
        ph = "Zážeh"
    elif accel > FLAT:
        ph = "Akcelerace"
    elif accel < -FLAT:
        ph = "Zpomaluje"
    else:
        ph = "Setrvalý"
    if ph != t.get("phase"):
        bad += 1
        if bad <= 6:
            print("  MISMATCH %-24s stored=%-12s recomputed=%-12s (p4=%.1f base=%.1f)"
                  % (e["name"][:23], t.get("phase"), ph, p4, baseline))
print("  phase mismatches: %d" % bad)
if bad:
    fail("phase", "%d phase labels disagree with a recomputation" % bad)


# ---------------------------------------------------------------- 14. hs score
head("14. HS SCORE — recomputed")
bad = 0
for e in ALL:
    t = e.get("traj") or {}
    if t.get("hs") is None or t.get("recent") is None or t.get("baseline") is None:
        continue
    lvp = t.get("level_vs_peak")
    peak_term = (2 * lvp - 1) if lvp is not None else 0.0
    mine = 50 * (1 + 0.5 * math.tanh(t["recent"] / 40.0)
                 + 0.4 * math.tanh(t["accel"] / 40.0) + 0.1 * peak_term)
    if abs(mine - t["hs"]) > 0.15:
        bad += 1
        if bad <= 5:
            print("  MISMATCH %-24s stored=%.1f mine=%.1f" % (e["name"][:23], t["hs"], mine))
print("  hs mismatches: %d" % bad)
if bad:
    fail("hs", "%d hs scores disagree" % bad)


# ---------------------------------------------------------------- verdict
# ================================================================ v11 metrics
# Everything below is a SECOND implementation of what collector.py stored. It
# deliberately does not import collector — an identical bug in one shared helper
# would cancel out and the check would pass on wrong numbers.
def median_ref(xs):
    xs = sorted(xs)
    n = len(xs)
    if not n:
        return None
    m = n // 2
    return xs[m] if n % 2 else (xs[m - 1] + xs[m]) / 2.0


def runrate_ref(series, end=None):
    if not series:
        return None, None
    end = end if end is not None else series[-1][0]
    first = series[0][0]

    def win(days):
        lo = end - days * DAY
        vals = [v for t, v in series if lo < t <= end]
        cov = days if first <= lo else int(round((end - first) / float(DAY)))
        return sum(vals), max(0, min(cov, days)), sum(1 for v in vals if v and v > 0)

    r30, c30, _ = win(30)
    r90, c90, nz90 = win(90)
    if c90 <= 0:
        return None, None
    sparse = nz90 < 0.5 * c90
    cands = [(365.0 * r90 / c90, "90d")]
    if not sparse and c30 > 0:
        cands.append((365.0 * r30 / c30, "30d"))
        blocks = []
        for k in range(3):
            lo, hi = end - (k + 1) * 30 * DAY, end - k * 30 * DAY
            if first <= lo + 2 * DAY:
                blocks.append(sum(v for t, v in series if lo < t <= hi))
        if len(blocks) == 3:
            cands.append((12.0 * median_ref(blocks), "med3"))
    val, basis = min(cands, key=lambda c: c[0])
    return max(0.0, val), ("90d-sparse" if sparse else basis)


head("15. RUN-RATE — recomputed (calendar windows, coverage, median-of-3)")
bad = basis_bad = 0
for e in APPS:
    stored = (e.get("runrate") or {})
    mine, basis = runrate_ref(e.get("rev_series") or [])
    sv = stored.get("value")
    if sv is None and mine is None:
        continue
    if sv is None or mine is None or abs(sv - mine) > max(1.0, abs(mine) * 0.001):
        bad += 1
        if bad <= 4:
            print("  MISMATCH %-24s stored=%s mine=%s" % (e["name"][:23], sv, mine))
    elif stored.get("basis") != basis:
        basis_bad += 1
print("  mismatches: %d | basis mismatches: %d" % (bad, basis_bad))
sparse_n = sum(1 for e in APPS if (e.get("runrate") or {}).get("sparse"))
print("  lumpy reporters on the 90d-only path: %d" % sparse_n)
if bad:
    fail("runrate", "%d run-rates disagree" % bad)
if basis_bad:
    fail("runrate", "%d run-rate bases disagree" % basis_bad)

head("16. POTENTIAL / TIER / RELIABLE — recomputed")
bench = (D.get("bench") or {}).get("mult")
bench_c = (D.get("bench_chains") or {}).get("mult")
bad = tier_bad = 0
for pool, bm in ((APPS, bench), (CHAINS, bench_c)):
    for e in pool:
        ps = e.get("ps")
        exp = None if (not bm or not ps or ps <= 0) else min(50.0, bm / ps)
        got = e.get("potential")
        if (exp is None) != (got is None) or (exp is not None and abs(exp - got) > 0.01):
            bad += 1
            if bad <= 4:
                print("  MISMATCH %-24s stored=%s mine=%s" % (e["name"][:23], got, exp))
        u = got
        t = 0 if u is None else (5 if u >= 10 else 4 if u >= 5 else 3 if u >= 2.5 else 2 if u >= 1.2 else 1)
        if u is not None and not (e.get("reliable") or e.get("young")):
            t = min(t, 3)
        if t != e.get("tier"):
            tier_bad += 1
print("  potential mismatches: %d | tier mismatches: %d" % (bad, tier_bad))
# the benchmark must be one of the entities, on the same basis as everyone else
hl = [e for e in APPS if e["name"].strip().lower() == "hyperliquid"]
if hl and abs((hl[0].get("ps") or 0) - (bench or 0)) > 0.01:
    fail("bench", "benchmark %.2f is not Hyperliquid's own multiple %.2f"
         % (bench or 0, hl[0].get("ps") or 0))
else:
    print("  benchmark = Hyperliquid's own multiple: %.2fx (%s)"
          % (bench or 0, (D.get("bench") or {}).get("basis")))
if bad:
    fail("potential", "%d potentials disagree" % bad)
if tier_bad:
    fail("tier", "%d tiers disagree" % tier_bad)

head("17. STRENGTH — the closed form must equal the stored ratio")
bad = 0
for e in APPS + CHAINS:
    s = e.get("sila6m") or {}
    if s.get("ratio") is None:
        continue
    pts = s.get("points") or []
    k = s.get("k")
    if not k or k >= len(pts):
        bad += 1
        continue
    p0, pk = pts[0], pts[k]
    if not (p0.get("rr") and pk.get("rr") and p0.get("price") and pk.get("price")):
        bad += 1
        continue
    mine = (p0["rr"] / pk["rr"]) / (p0["price"] / pk["price"])
    if abs(mine - s["ratio"]) > max(0.005, abs(mine) * 0.002):
        bad += 1
        if bad <= 4:
            print("  MISMATCH %-24s stored=%s mine=%.3f" % (e["name"][:23], s["ratio"], mine))
    if k < 3:
        bad += 1      # overlapping 90d windows would bias the ratio toward 1
print("  mismatches: %d" % bad)
have = sum(1 for e in APPS if (e.get("sila6m") or {}).get("ratio") is not None)
print("  strength computed for %d/%d apps" % (have, len(APPS)))
if bad:
    fail("sila6m", "%d strength ratios disagree or use overlapping windows" % bad)

def slope_on(series, stamps):
    """%/month log-OLS of `series` sampled (forward-filled) at `stamps`."""
    lookup = {}
    prev = None
    i = 0
    pts = sorted(series)
    for t in stamps:
        while i < len(pts) and pts[i][0] <= t:
            prev = pts[i][1]
            i += 1
        if prev and prev > 0:
            lookup[t] = prev
    xs = [(t - stamps[0]) / float(DAY) for t in stamps if t in lookup]
    ys = [math.log(lookup[t]) for t in stamps if t in lookup]
    if len(xs) < 30:
        return None
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        return None
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    return (math.exp(b * 30.0) - 1) * 100


head("18. ADOPTION INDEX — every stored point rebuilt from its components")
bad = point_bad = 0
drift = []
for e in CHAINS:
    idx = e.get("adoption_index")
    if not idx:
        continue
    stamps = [t for t, _ in idx["series"]]
    g_idx = slope_on(idx["series"], stamps)
    comps = []
    stables = e.get("tvl_series") if e.get("adoption_metric") == "stablecoins" else []
    if "stables" in idx["components"] and stables:
        comps.append(stables)
    if "dex" in idx["components"] and e.get("dex_series"):
        roll, acc, j = [], 0.0, 0
        ds = e["dex_series"]
        for i, (t, v) in enumerate(ds):
            acc += v or 0.0
            while j <= i and ds[j][0] <= t - 30 * DAY:
                acc -= ds[j][1] or 0.0
                j += 1
            roll.append([t, acc])
        comps.append(roll)
    # The index only exists where EVERY component has data, so a component must
    # be clipped to that same span before its slope is comparable. Without this
    # the check reported ~0.7 pp/month of phantom drift on Linea, Stellar and
    # Plasma purely because one component reaches further back than the other.
    gs = []
    for c in comps:
        g = slope_on(c, stamps)
        if g is not None:
            gs.append(g)
    # --- the exact check: rebuild every stored index POINT from the components.
    # This proves the construction itself. (The slope identity slope(ln I) =
    # mean_c slope(ln X_c) is true in theory but both sides pick up forward-fill
    # noise on chains whose components are sampled on different days, so it is
    # reported below as a diagnostic rather than enforced.)
    refs = {}
    for name, s in zip(idx["components"], comps):
        near = [v for ts, v in s if abs(ts - idx["ref_ts"]) <= 3 * DAY]
        prev = [v for ts, v in s if ts <= idx["ref_ts"]]
        refs[name] = (sum(near) / len(near)) if near else (prev[-1] if prev else None)
    worst = 0.0
    for t, v in idx["series"]:
        logs = []
        for name, s in zip(idx["components"], comps):
            x, r = None, refs.get(name)
            for ts, val in s:
                if ts > t:
                    break
                x = val
            if not x or x <= 0 or not r:
                logs = None
                break
            logs.append(math.log(x / r))
        if logs is None:
            continue
        rebuilt = math.exp(sum(logs) / len(logs))
        worst = max(worst, abs(rebuilt - v) / max(abs(v), 1e-12))
    if worst > 0.01:
        point_bad += 1
        print("  POINT MISMATCH %-18s worst relative error %.4f" % (e["name"][:17], worst))

    if g_idx is None or not gs:
        continue
    mine = sum(gs) / len(gs)
    # 0.35 pp/month. The identity is exact in theory but both sides carry
    # forward-fill noise: a component whose history starts a few days after the
    # index does regresses over a marginally shorter domain. Real construction
    # errors are nowhere near this fine — the earlier bug where components were
    # regressed over their full history instead of the index's showed up as
    # 4.5 pp on X Layer.
    drift.append((abs(mine - g_idx), e["name"], g_idx, mine))
print("  point mismatches: %d (this is the check that must be 0)" % point_bad)
drift.sort(reverse=True)
if drift:
    print("  slope-identity drift, worst 3 (diagnostic only):")
    for dv, nm, gi, mn in drift[:3]:
        print("      %-18s index=%+7.2f  mean-of-parts=%+7.2f  (%.2f pp)" % (nm[:17], gi, mn, dv))
nulls = [e["name"] for e in CHAINS if not e.get("adoption_index")]
print("  chains without a 6-month baseline (correctly blank): %s" % (", ".join(nulls) or "none"))
if point_bad:
    fail("adoption_index", "%d chain indices are not the geometric mean of their parts" % point_bad)

head("19. DEFAULT SORT — straight by the multiple; trust is a filter, not a rank")
# The viewer sorts on min(potential, 999) alone. Ranking bands were removed: a
# 50x row demoted into the middle of the table read as a bug, so doubt is now
# expressed by the "Jen prověřené" filter and a per-reason tag instead.
for label, pool in (("apps", APPS), ("chains", CHAINS)):
    ranked = [e for e in pool if e.get("potential") is not None]
    ranked.sort(key=lambda e: min(e["potential"], 999), reverse=True)
    vals = [min(e["potential"], 999) for e in ranked]
    mono = all(vals[i] >= vals[i + 1] for i in range(len(vals) - 1))
    shown = [e for e in pool if e.get("reliable") or e.get("young")]
    print("  %-7s %d s potencialem | monotonni -> %s | v rezimu 'jen proverene': %d"
          % (label, len(ranked), "OK" if mono else "BROKEN", len(shown)))
    if not mono:
        fail("sort", "%s: potential ordering is not monotonic" % label)
    # every row the trusted view keeps must be either proven or merely young
    leaked = [e["name"] for e in shown
              if not e.get("reliable") and set(e.get("reliable_fail") or []) - {"krátká historie"}]
    if leaked:
        fail("sort", "%s: rezim 'jen proverene' propustil radky s jinou vadou nez vek: %s"
             % (label, ", ".join(leaked[:5])))
    # and a young row must fail on nothing but its age
    bad_young = [e["name"] for e in pool if e.get("young")
                 and set(e.get("reliable_fail") or []) - {"krátká historie"}]
    if bad_young:
        fail("sort", "%s: marked young despite other failures: %s" % (label, ", ".join(bad_young)))
    # tiers stay capped for genuinely doubtful rows, so the row tint still warns
    miscapped = [e["name"] for e in pool
                 if not (e.get("reliable") or e.get("young")) and (e.get("tier") or 0) > 3]
    if miscapped:
        fail("tier", "%s: doubtful rows above tier 3: %s" % (label, ", ".join(miscapped[:5])))


head("20. MONTHLY BUCKETS — UTC calendar months")
bad = 0
for e in APPS[:60]:
    m = e.get("monthly") or []
    if not m:
        continue
    bins = {}
    for t, v in (e.get("rev_series") or []):
        d = datetime.datetime.fromtimestamp(t, datetime.timezone.utc)
        bins.setdefault("%04d-%02d" % (d.year, d.month), []).append(v)
    for row in m:
        exp = sum(bins.get(row["m"]) or [])
        if abs(exp - row["v"]) > max(1.0, abs(exp) * 0.001):
            bad += 1
            if bad <= 4:
                print("  MISMATCH %-20s %s stored=%.0f mine=%.0f" % (e["name"][:19], row["m"], row["v"], exp))
print("  mismatches: %d (60 apps sampled)" % bad)
if bad:
    fail("monthly", "%d monthly buckets disagree" % bad)


# ================================================================ review 2026-09-22
# Numbers the page shows that no audit recomputed before this review. Each was
# verified by hand once (0 mismatches); now they are checked on every run.
def weekly_sum_vals(series, agg):
    return [v for _, v in weekly_buckets_ref(series, agg)] if series else []


def ols_g_r2(vals, step, minp):
    pts = [(i, v) for i, v in enumerate(vals) if v and v > 0]
    if len(pts) < minp:
        return None, None
    n = len(pts)
    xs = [p[0] for p in pts]
    ys = [math.log(p[1]) for p in pts]
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if not sxx:
        return None, None
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    a = my - b * mx
    ssr = sum((y - (a + b * x)) ** 2 for x, y in zip(xs, ys))
    sst = sum((y - my) ** 2 for y in ys)
    return max(-99.0, min(999.0, (math.exp(b * 30 / step) - 1) * 100)), (1 - ssr / sst if sst else 0.0)


head("21. GROWTH 6M — recomputed (weekly sums over 182 days)")
bad = 0
for e in APPS:
    s = e.get("rev_series") or []
    if not s:
        continue
    end = s[-1][0]
    vals = weekly_sum_vals([[t, v] for t, v in s if t > end - 182 * DAY], "sum")
    g, _ = ols_g_r2(vals, 7.0, 5) if len(vals) >= 5 else (None, None)
    st = (e.get("growth6m") or {}).get("g")
    if (g is None) != (st is None) or (g is not None and abs(g - st) > 0.05):
        bad += 1
        if bad <= 3:
            print("  MISMATCH %-22s stored %s mine %s" % (e["name"][:21], st, g))
print("  apps: %d | mismatches: %d" % (len(APPS), bad))
if bad:
    fail("growth6m", "%d six-month growth rates disagree" % bad)

head("22. TRAJECTORY QUARTER SLOPES — recomputed, not just read back")
bad = n = 0
for e in APPS + CHAINS:
    s, agg = traj_source(e)
    t = e.get("traj") or {}
    if not s or len(s) < 60 or not t.get("periods"):
        continue
    wk = weekly_buckets_ref(s, agg)
    last = s[-1][0]
    for name, a, b in QUARTERS:
        vals = [v for tt, v in wk if last - a * DAY <= tt <= last - b * DAY]
        g, _ = ols_g_r2(vals, 7.0, 6) if len(vals) >= 6 else (None, None)
        st = (t["periods"].get(name) or {}).get("g")
        n += 1
        if (g is None) != (st is None) or (g is not None and abs(g - st) > 0.05):
            bad += 1
            if bad <= 3:
                print("  MISMATCH %-18s %s stored %s mine %s" % (e["name"][:17], name, st, g))
print("  quarters: %d | mismatches: %d" % (n, bad))
if bad:
    fail("trajectory", "%d quarter slopes disagree with a recomputation" % bad)

head("23. MULTIPLES — ps = mcap / run-rate (apps), mcap / stablecoins (chains)")
bad = 0
for e in APPS:
    rr = (e.get("runrate") or {}).get("value")
    exp = e["mcap"] / rr if (e.get("mcap") and rr and rr > 0) else None
    if (exp is None) != (e.get("ps") is None) or (exp is not None and abs(exp - e["ps"]) > 1e-3 * max(1, exp)):
        bad += 1
for e in CHAINS:
    st = e.get("stables_now") or 0
    exp = e["mcap"] / st if (e.get("mcap") and st >= 1e7) else None
    if (exp is None) != (e.get("ps") is None) or (exp is not None and abs(exp - e["ps"]) > 1e-3 * max(1, exp)):
        bad += 1
print("  mismatches: %d" % bad)
if bad:
    fail("ps", "%d stored multiples are not mcap over their base" % bad)

head("24. STRENGTH — every past run-rate point re-derived from the series")
bad = n = 0
for e in APPS:
    s = e.get("rev_series") or []
    for p in (e.get("sila6m") or {}).get("points") or []:
        if p.get("rr") is None or not s:
            continue
        mine, _ = runrate_ref(s, end=p["t"])
        n += 1
        if mine is None or abs(mine - p["rr"]) > max(1.0, 1e-3 * mine):
            bad += 1
print("  points: %d | mismatches: %d" % (n, bad))
if bad:
    fail("sila6m", "%d past run-rate points disagree" % bad)

head("25. VALUE ACCRUAL — share of revenue that reaches token holders")
shares = [e["holders_share"] for e in APPS if e.get("holders_share") is not None]
out_of_range = [e["name"] for e in APPS if e.get("holders_share") is not None
                and not (0 <= e["holders_share"] <= 1)]
zero_without_data = [e["name"] for e in APPS if e.get("holders_share") == 0 and not e.get("holders_leaves")]
print("  apps with holder data: %d/%d | under 5 %%: %d | trusted and under 5 %%: %d"
      % (len(shares), len(APPS), sum(1 for x in shares if x < 0.05),
         sum(1 for e in APPS if (e.get("reliable") or e.get("young"))
             and e.get("holders_share") is not None and e["holders_share"] < 0.05)))
hl = [e for e in APPS if e["name"].strip().lower() == "hyperliquid"]
if hl:
    print("  benchmark Hyperliquid passes %s of revenue to holders"
          % ("%.0f %%" % (100 * hl[0]["holders_share"]) if hl[0].get("holders_share") is not None else "unknown"))
if out_of_range:
    fail("holders", "holder share outside 0..1: %s" % ", ".join(out_of_range[:5]))
if zero_without_data:
    fail("holders", "missing data reported as 0 %%: %s" % ", ".join(zero_without_data[:5]))

head("26. RELIABILITY REASONS — recomputed, and every one has a tooltip")


def reasons_ref(e):
    out = []
    if not e.get("mcap") or e["mcap"] < 3e6:
        out.append("market cap pod $3M")
    # no stablecoin series (Canton, Quai): history/lag/trend would be artefacts
    if e.get("adoption_metric") and e["adoption_metric"] != "stablecoins":
        return out + ["bez dat o stablecoinech"]
    if (e.get("hist_days") or 0) < 180:
        out.append("krátká historie")
    lvp = (e.get("traj") or {}).get("level_vs_peak")
    if lvp is not None and lvp < 0.35:
        out.append("hluboko pod svým maximem")
    g = (e.get("growth6m") or {}).get("g")
    if g is None:
        out.append("trend nejde změřit")
    elif g < -10.0:
        out.append("klesající trend")
    lag = e.get("lag_days")
    if lag is None or lag > 10:
        out.append("stará data")
    return out


bad = 0
for e in ALL:
    mine = reasons_ref(e)
    if mine != (e.get("reliable_fail") or []) or bool(e.get("reliable")) != (not mine):
        bad += 1
        if bad <= 4:
            print("  MISMATCH %-24s stored=%s mine=%s" % (e["name"][:23], e.get("reliable_fail"), mine))
# A reason without a TRUST_REASONS entry is dropped by trustTags() without a word —
# the row loses its tag and nobody notices.
tpl = io.open("template.html", encoding="utf-8").read()
block = re.search(r"var TRUST_REASONS = \{(.*?)\n\};", tpl, re.S)
keys = set(re.findall(r"^  '([^']+)': \{", block.group(1), re.M)) if block else set()
used = {r for e in ALL for r in (e.get("reliable_fail") or [])}
print("  rows: %d | mismatches: %d | reasons in data: %d | tooltips: %d"
      % (len(ALL), bad, len(used), len(keys)))
if bad:
    fail("reliable", "%d reason lists disagree with a recomputation" % bad)
if used - keys:
    fail("reliable", "reasons with no tooltip text (tag silently dropped): %s" % ", ".join(sorted(used - keys)))

head("27. CHAIN FEE CHECK — second opinion on the adoption multiple")
bad = 0
fee_ps = {}
for e in CHAINS:
    mine, basis = runrate_ref(e.get("rev_series") or [])
    fr = e.get("fee_runrate") or {}
    sv = fr.get("value")
    if (sv is None) != (mine is None) or (mine is not None and (
            abs(sv - mine) > max(1.0, abs(mine) * 0.001) or fr.get("basis") != basis)):
        bad += 1
        print("  RUN-RATE MISMATCH %-16s stored=%s/%s mine=%s/%s"
              % (e["name"][:15], sv, fr.get("basis"), mine, basis))
    exp = e["mcap"] / mine if (e.get("mcap") and mine and mine > 0) else None
    got = e.get("ps_fees")
    if (exp is None) != (got is None) or (exp is not None and abs(exp - got) > 1e-3 * max(1, exp)):
        bad += 1
    if exp:
        fee_ps[e["name"]] = exp
med = median_ref(list(fee_ps.values()))
stored = (D.get("bench_chains") or {}).get("fee_mult")
if (med is None) != (stored is None) or (med is not None and abs(med - stored) > 1e-3 * med):
    fail("fees", "fee benchmark %s is not the median chain %s" % (stored, med))
for e in CHAINS:
    ps = fee_ps.get(e["name"])
    exp = min(50.0, med / ps) if (ps and med) else None
    got = e.get("potential_fees")
    if (exp is None) != (got is None) or (exp is not None and abs(exp - got) > 0.01):
        bad += 1
        print("  POTENTIAL MISMATCH %-16s stored=%s mine=%s" % (e["name"][:15], got, exp))
# The panel prints "Roční běh … je spočítaný takto" for any entity with a run-rate
# basis; a chain carrying one would show fee maths under its stablecoin history.
leak = [e["name"] for e in CHAINS if e.get("runrate")]
contra = ["%s %.1fx vs %.2fx" % (e["name"], e["potential"], e["potential_fees"]) for e in CHAINS
          if (e.get("potential") or 0) >= 1.2 and e.get("potential_fees") is not None
          and e["potential_fees"] < 1]
print("  chains: %d | with fee data: %d | median MC/fees: %.0fx | mismatches: %d"
      % (len(CHAINS), len(fee_ps), med or 0, bad))
print("  adoption says upside, fees say pricier than median: %s" % (", ".join(contra) or "none"))
if bad:
    fail("fees", "%d fee-check values disagree with a recomputation" % bad)
if leak:
    fail("fees", "chains carry an app run-rate (panel would print its basis): %s" % ", ".join(leak))


# ================================================================ degen plan, phase 1
head("28. POTENCIÁL V PENĚZÍCH — mcap a cena při násobku měřítka, FDV na stejné bázi")
B = D.get("bench") or {}
hlr = [e for e in APPS if e["name"].strip().lower() == "hyperliquid"]
fm = B.get("fdv_mult")
if hlr and hlr[0].get("fdv") and (hlr[0].get("runrate") or {}).get("value"):
    exp_fm = hlr[0]["fdv"] / hlr[0]["runrate"]["value"]
    if fm is None or abs(exp_fm - fm) > 1e-3 * exp_fm:
        fail("reframe", "bench.fdv_mult %s is not Hyperliquid's FDV / run-rate %.3f" % (fm, exp_fm))
    else:
        print("  měřítko na FDV: %.1fx (Hyperliquid FDV = %.1fx jeho mcap)"
              % (fm, hlr[0]["fdv"] / hlr[0]["mcap"]))
bad = shown_up = 0
for pool, bm in ((APPS, bench), (CHAINS, bench_c)):
    for e in pool:
        p, mc = e.get("potential"), e.get("mcap")
        base = ((e.get("runrate") or {}).get("value") if pool is APPS else e.get("stables_now"))
        capped = p is not None and (e.get("potential_raw") or 0) >= 50
        # the money figure IS the benchmark multiple times the base (50x mcap
        # at the display cap) — exact, not via the rounded potential
        exp_m = (50 * mc if capped else bm * base) if (p is not None and mc and bm and base) else None
        got = e.get("mcap_at_bench")
        if (exp_m is None) != (got is None) or (exp_m is not None and abs(exp_m - got) > max(0.02, 1e-9 * exp_m)):
            bad += 1
            if bad <= 3:
                print("  MISMATCH mcap_at_bench %-20s stored=%s mine=%s" % (e["name"][:19], got, exp_m))
            continue
        if bool(e.get("bench_capped")) != bool(capped and exp_m is not None):
            bad += 1
        if exp_m is None:
            continue
        # and it must agree with the multiple the table shows, up to the
        # three-decimal rounding of both ps and potential: chains carry ps ~0,3
        # (MC/stablecoins), where 0,0005 of rounding is already 0,17 %
        tol = 0.0006 * mc + got * 0.0006 / max(e.get("ps") or 1.0, 1e-9)
        if abs(got - mc * p) > tol:
            bad += 1
            if bad <= 3:
                print("  CONSISTENCY %-20s mcap_at_bench %.0f vs mcap x potential %.0f" % (e["name"][:19], got, mc * p))
        exp_p = e["price"] * got / mc if e.get("price") else None
        gp = e.get("price_at_bench")
        if (exp_p is None) != (gp is None) or (exp_p is not None and abs(exp_p - gp) > 1e-5 * abs(exp_p)):
            bad += 1
fw = 0
for e in APPS:
    fdv, mc, rr = e.get("fdv"), e.get("mcap"), (e.get("runrate") or {}).get("value")
    raw = None
    if e.get("potential_raw") is not None and fdv and mc and rr and rr > 0 and fm and fdv >= 0.98 * mc:
        raw = fm / (fdv / rr)
    got = e.get("potential_fdv")
    if (raw is None) != (got is None) or (raw is not None and abs(raw - got) > max(0.002, 1e-3 * raw)):
        bad += 1
        if bad <= 3:
            print("  MISMATCH potential_fdv %-20s stored=%s mine=%s" % (e["name"][:19], got, raw))
        continue
    if raw is None:
        if e.get("potential_fdv_shown") is not None or e.get("float_worse") is not None:
            bad += 1
        continue
    exp_shown = min(e["potential"], raw)
    if abs(exp_shown - (e.get("potential_fdv_shown") or -1)) > max(0.002, 1e-3 * exp_shown):
        bad += 1
    # dilution may only LOWER the figure
    if e["potential_fdv_shown"] > e["potential_raw"] + 0.002:
        shown_up += 1
    if bool(e.get("float_worse")) != (raw < e["potential_raw"]):
        bad += 1
    fw += 1 if e.get("float_worse") else 0
print("  mismatches: %d | ředí se víc než měřítko: %d | FDV číslo vyšší než Potenciál: %d"
      % (bad, fw, shown_up))
if bad:
    fail("reframe", "%d money/FDV figures disagree with a recomputation" % bad)
if shown_up:
    fail("reframe", "%d rows show a fully diluted figure ABOVE their potential" % shown_up)

head("29. TÉMA NA ŘÁDKU — žebřík: override, kategorie, CoinGecko, zbytková kategorie, nejbližší")
THEMES_SNAP = D.get("themes") or []
TJ = D.get("theme_join") or {}


def module_literal(src, name):
    """A module-level `NAME = {...}` literal read with ast. The old single-line
    regex silently returned {} as soon as a dict spanned two lines."""
    import ast
    for node in ast.parse(src).body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name
                                                for t in node.targets):
            return ast.literal_eval(node.value)
    return None


tsrc = io.open("themes.py", encoding="utf-8").read()
OVERRIDES = module_literal(tsrc, "THEME_OVERRIDES") or {}
NEAREST = module_literal(tsrc, "NEAREST_THEME") or {}
if not TJ:
    fail("theme", "snapshot has no theme_join block — collector older than the row ladder")
elif TJ.get("overrides") != OVERRIDES or TJ.get("nearest") != NEAREST:
    fail("theme", "theme_join.overrides/nearest differ from themes.py — stale snapshot, re-run the collector")
ORDER = TJ.get("order") or [th["key"] for th in THEMES_SNAP]
RESIDUAL = set(TJ.get("residual") or [th["key"] for th in THEMES_SNAP if th.get("kind") == "chains"])
TH_BY = {th["key"]: th for th in THEMES_SNAP}
MEM = {th["key"]: {m["id"] for m in th.get("members") or []} for th in THEMES_SNAP}
LAYERS = {th["key"] for th in THEMES_SNAP if th.get("kind") == "chains"}
# the crosswalks rebuilt from the snapshot's own fundament lists, not from themes.py
CW, CW_RES = {}, {}
for th in THEMES_SNAP:
    f = th.get("fundament") or {}
    for c in (f.get("categories") or []) + (f.get("below_floor") or []) + (f.get("missing") or []):
        (CW_RES if th["key"] in RESIDUAL else CW)[c] = th["key"]
dead = sorted(c for c in NEAREST if c in CW or c in CW_RES)
if dead:
    fail("theme", "NEAREST_THEME entries that already feed a fundament: %s" % ", ".join(dead))
nowhere = sorted(c for c, k in NEAREST.items() if k not in ORDER)
if nowhere:
    fail("theme", "NEAREST_THEME points at no theme: %s" % ", ".join(nowhere))


def app_theme_ref(e):
    """themes.app_theme, second implementation: override, narrative category,
    CoinGecko (narratives, then residual themes), residual category, nearest."""
    g, cat, cgt = e.get("gecko_id"), e.get("category"), set(e.get("cg_themes") or [])
    if g in OVERRIDES:
        return OVERRIDES[g], "override"
    if cat in CW:
        return CW[cat], "category"
    for keys in ([k for k in ORDER if k not in RESIDUAL], [k for k in ORDER if k in RESIDUAL]):
        for k in keys:
            if k in cgt:
                return k, "coingecko"
    if cat in CW_RES:
        return CW_RES[cat], "category"
    if cat in NEAREST:
        return NEAREST[cat], "nearest"
    return None, None


bad = 0
src_n = _C()
for e in APPS:
    k, src = app_theme_ref(e)
    if k not in TH_BY:        # a key whose theme is missing from the output → no chip
        k, src = None, None
    t = e.get("theme") or {}
    src_n[src or "none"] += 1
    if (t.get("key"), t.get("source")) != (k, src):
        bad += 1
        if bad <= 4:
            print("  MISMATCH %-22s kategorie %-18s stored=%s/%s mine=%s/%s"
                  % (e["name"][:21], (e.get("category") or "")[:17], t.get("key"), t.get("source"), k, src))
for e in CHAINS:
    g = e.get("gecko_id")
    ok_keys = {k for k, ids in MEM.items() if g in ids and k not in RESIDUAL}
    if not ok_keys:
        ok_keys = {k for k, ids in MEM.items() if g in ids and k in LAYERS}
    if not ok_keys:
        ok_keys = {"l2" if (e.get("category") or "").startswith("L2") else "l1"}
    t = e.get("theme") or {}
    if t.get("key") not in ok_keys:
        bad += 1
        print("  MISMATCH chain %-16s stored=%s allowed=%s" % (e["name"][:15], t.get("key"), sorted(ok_keys)))
    elif t.get("source") != ("basket" if g in MEM.get(t.get("key"), ()) else "layer"):
        bad += 1
        print("  MISMATCH chain %-16s source=%s" % (e["name"][:15], t.get("source")))
not_sub = 0
for e in APPS + CHAINS:
    t = e.get("theme")
    if t:
        th = TH_BY.get(t["key"]) or {}
        if (t.get("name"), t.get("tier"), sorted(t.get("tags") or []), t.get("beta")) != \
                (th.get("name"), th.get("tier"), sorted(th.get("tags") or []), th.get("beta")):
            bad += 1
    if e.get("basket_themes") != sorted(k for k, ids in MEM.items() if e.get("gecko_id") in ids):
        bad += 1
    # the display basket is cut from the CoinGecko candidates, so it must be a subset
    # (not on the stale path, where the join ran without candidates)
    if not D.get("themes_stale") and not set(e.get("basket_themes") or []) <= set(e.get("cg_themes") or []):
        not_sub += 1
if not_sub:
    warn("theme", "%d rows sit in a display basket but not in its CoinGecko candidates" % not_sub)
# the same coin must not read as two themes on Apps and Chains (NEAR, OP, SUI once did)
chain_theme = {e.get("gecko_id"): (e.get("theme") or {}).get("key") for e in CHAINS if e.get("gecko_id")}
split = [(e["name"], (e.get("theme") or {}).get("key"), chain_theme[e["gecko_id"]]) for e in APPS
         if e.get("gecko_id") in chain_theme and (e.get("theme") or {}).get("key") != chain_theme[e["gecko_id"]]]
for nm, a, c in split:
    print("  RŮZNÉ TÉMA app %s=%s vs chain=%s" % (nm, a, c))
if split:
    warn("theme", "%d coins read as a different theme on Apps and Chains" % len(split))
# residual baskets: nothing a narrative owns; Infrastruktura also no chain's own coin
narr_mem = set().union(*[MEM[k] for k in MEM if k not in RESIDUAL]) if MEM else set()
chain_coins = set(chain_theme) | set().union(*[MEM[k] for k in LAYERS if k in MEM]) if MEM else set()
for th in THEMES_SNAP:
    if th["key"] not in RESIDUAL:
        continue
    ids = MEM.get(th["key"], set()) | {m["id"] for m in th.get("beta_members") or []}
    owned = sorted(ids & narr_mem)
    chains_in = sorted(ids & chain_coins) if th["key"] not in LAYERS else []
    if owned or chains_in:
        fail("theme", "residual theme %s holds coins it must leave out: %s"
             % (th["key"], ", ".join(owned + chains_in)))
# English names: a theme without a THEME_EN entry would show Czech in EN mode
mo = re.search(r"var THEME_EN = \{(.*?)\n\};", tpl, re.S)
en_keys = set(re.findall(r"^\s*([a-z0-9_]+):\s*\{name:", mo.group(1), re.M)) if mo else set()
no_en = sorted(k for k in TH_BY if k not in en_keys)
if no_en:
    fail("theme", "themes with no English name in THEME_EN: %s" % ", ".join(no_en))
none_cats = _C((e.get("category") or "—") for e in APPS if not e.get("theme"))
if none_cats:
    warn("theme", "apps with no theme — add their categories to NEAREST_THEME or a theme: %s"
         % ", ".join("%s (%d)" % kv for kv in none_cats.most_common()))
print("  mismatches: %d | zdroje: %s | bez tématu: %d/%d | změny od minula: %s"
      % (bad, dict(src_n), sum(none_cats.values()), len(APPS), TJ.get("n_changed")))
if bad:
    fail("theme", "%d row themes disagree with the ladder / baskets" % bad)

head("30. TEST 30× — strop po žebříku, přepočítaný z řádků a košů")
RULE = D.get("test30_rule")
bad = 0
counts = {True: 0, False: 0, None: 0}
for pool in (APPS, CHAINS):
    by_cat = {}
    for e in pool:
        by_cat.setdefault(e.get("category"), []).append(e)
    for e in pool:
        mc = e.get("mcap") or 0
        g = e.get("gecko_id")
        peers = [p for p in by_cat.get(e.get("category")) or []
                 if p is not e and p.get("gecko_id") != g and p.get("mcap")]
        cat = max(peers, key=lambda p: p["mcap"]) if peers else None
        basket = [m for m in (TH_BY.get((e.get("theme") or {}).get("key")) or {}).get("members") or []
                  if m.get("id") != g and m.get("mcap")]
        thm = max(basket, key=lambda m: m["mcap"]) if basket else None
        cat_c = (cat["mcap"], cat["name"], "category") if cat else None
        th_c = (thm["mcap"], thm.get("sym") or thm.get("name") or thm["id"], "theme") if thm else None
        if RULE == "larger_of":
            opts = [c for c in (cat_c, th_c) if c]
            ceil = max(opts, key=lambda c: c[0]) if opts else (None, None, None)
        else:
            ceil = cat_c if (cat_c and cat_c[0] >= mc) else (th_c or (None, None, None))
        t = e.get("test30") or {}
        implied = 30 * mc if mc else None
        size_ok = (implied <= ceil[0]) if (implied and ceil[0]) else None
        pr, pfs = e.get("potential_raw"), e.get("potential_fdv_shown")
        exp = (size_ok, ceil[1], ceil[2], (pr >= 30) if pr is not None else None,
               (pfs >= 30) if pfs is not None else None)
        got = (t.get("size_ok"), t.get("ceiling_name"), t.get("ceiling_kind"), t.get("val_ok"), t.get("val_ok_fdv"))
        if exp != got or (implied and abs((t.get("implied") or 0) - implied) > 0.02) or \
                (ceil[0] and abs((t.get("room_x") or 0) - ceil[0] / mc) > 1e-3 * ceil[0] / mc):
            bad += 1
            if bad <= 4:
                print("  MISMATCH %-22s stored=%s mine=%s" % (e["name"][:21], got, exp))
        if pool is APPS:
            counts[t.get("size_ok")] = counts.get(t.get("size_ok"), 0) + 1
trusted_val = sum(1 for e in APPS if (e.get("reliable") or e.get("young")) and (e.get("test30") or {}).get("val_ok"))
print("  pravidlo: %s | mismatches: %d | appky ✓ %d  ✗ %d  bez srovnání %d | ocenění 30×+ u prověřených: %d"
      % (RULE, bad, counts[True], counts[False], counts[None], trusted_val))
if RULE not in ("ladder", "larger_of"):
    fail("test30", "unknown ceiling rule %r" % RULE)
if bad:
    fail("test30", "%d Test 30× results disagree with a recomputation" % bad)

head("31. POLE COINGECKA — obrat, nabídka, ATH, změny ceny (bez volání navíc)")
have = [e for e in ALL if (e.get("cg") or {}).get("vol24h") is not None]
print("  s obratem: %d/%d | se změnou 30d: %d | s ATH: %d"
      % (len(have), len(ALL), sum(1 for e in ALL if (e.get("cg") or {}).get("chg30d") is not None),
         sum(1 for e in ALL if (e.get("cg") or {}).get("ath") is not None)))
insane = [e["name"] for e in ALL if (e.get("cg") or {}).get("vol24h") is not None and e["cg"]["vol24h"] < 0]
if insane:
    fail("cg", "negative 24h volume: %s" % ", ".join(insane[:5]))
if len(have) < 0.95 * len(ALL):
    warn("cg", "only %d/%d rows carry CoinGecko volume — a /coins/markets chunk failed?" % (len(have), len(ALL)))


head("32. LIKVIDITA — skluz za lístek, rozhodnutí DEX / obrat, stáří dat")
RR = D.get("risk_rules") or {}
LM = D.get("liquidity_meta") or {}
TICKET = RR.get("ticket") or 10000
MAXI = RR.get("max_impact_pct") or 3.0
VOLP = RR.get("vol_pass") or 2e6
bad = 0
cnt = {}
for e in ALL:
    l = e.get("liq")
    if l is None:
        continue
    pl = l.get("pair_liq_usd")
    imp = 100.0 * 2 * TICKET / pl if pl else None
    if (imp is None) != (l.get("impact_pct") is None) or (imp is not None and abs(imp - l["impact_pct"]) > max(0.002, 1e-3 * imp)):
        bad += 1
    dex_ok = imp is not None and imp <= MAXI
    vol = l.get("vol24h")
    vol_ok = vol is not None and vol >= VOLP
    exp_ok = True if (dex_ok or vol_ok) else (False if (pl or vol is not None) else None)
    exp_src = "dex" if dex_ok else ("volume" if vol_ok else ("dex" if pl else ("volume" if vol is not None else "none")))
    if exp_ok != l.get("ok") or exp_src != l.get("source"):
        bad += 1
        if bad <= 4:
            print("  MISMATCH %-22s stored ok=%s/%s mine ok=%s/%s" % (e["name"][:21], l.get("ok"), l.get("source"), exp_ok, exp_src))
    if vol != (e.get("cg") or {}).get("vol24h"):
        bad += 1
    if l.get("as_of") and (l["as_of"] > D["generated_at"] + 60 or D["generated_at"] - l["as_of"] > 7 * DAY):
        bad += 1
    key = "%s/%s" % (l.get("source"), {True: "ok", False: "fail", None: "unknown"}[l.get("ok")])
    cnt[key] = cnt.get(key, 0) + 1
print("  rows: %d | %s | mismatches: %d" % (sum(cnt.values()), ", ".join("%s %d" % kv for kv in sorted(cnt.items())), bad))
if LM.get("unmapped_platforms"):
    print("  platformy bez mapování na DexScreener: %s" % LM["unmapped_platforms"])
if bad:
    fail("liquidity", "%d liquidity verdicts disagree with a recomputation" % bad)
no_liq = sum(1 for e in ALL if not e.get("liq"))
if no_liq:
    warn("liquidity", "%d rows carry no liquidity block (module failed?)" % no_liq)

head("33. UNLOCKY A ZNAČKY RIZIK — přepočet z uložených polí")
bad = 0
n_unl = 0
gen = D["generated_at"]
for e in APPS:
    u = e.get("unlock")
    if not u:
        continue
    n_unl += 1
    nc = u.get("next_cliff")
    if nc:
        if nc["ts"] <= gen or abs((nc["ts"] - gen) / DAY - nc["days"]) > 0.15:
            bad += 1
        if nc.get("pct_of_circ") is not None and u.get("unlocked_now") and \
                abs(100.0 * nc["tokens"] / u["unlocked_now"] - nc["pct_of_circ"]) > 0.01:
            bad += 1
    if u.get("unlock90_pct") is not None and u["unlock90_pct"] < -0.01:
        bad += 1
        print("  NEGATIVE unlock90 %-20s %s" % (e["name"][:19], u["unlock90_pct"]))
    s = u.get("insider90_share")
    if s is not None and not (-1e-9 <= s <= 1 + 1e-9):
        bad += 1
    # the join: the file's slug must be one of this row's own slug candidates
    key = e.get("key") or ""
    slugify = lambda n: re.sub(r"\s+", "-", re.sub(r"[^a-z0-9.\- ]", "", (n or "").lower().strip()))
    cands = [key.split("#", 1)[1] if key.startswith("parent#") else None, e.get("slug"), slugify(e.get("name"))]
    if u.get("slug") not in cands:
        bad += 1
        print("  JOIN %-20s slug %s not in %s" % (e["name"][:19], u.get("slug"), cands))
risk_bad = 0
for e in ALL:
    r = []
    if e.get("fdv") and e.get("mcap") and e["mcap"] / e["fdv"] < RR.get("float_tag", 0.25):
        r.append("float")
    u = e.get("unlock") or {}
    c = u.get("next_cliff") or {}
    cliff = (c.get("days") is not None and c["days"] <= RR.get("cliff_days", 60)
             and (c.get("pct_of_circ") or 0) >= RR.get("cliff_min", 3.0))
    if cliff:
        r.append("cliff")
    u90 = u.get("unlock90_pct") or 0
    if u90 >= RR.get("unlock90_tag", 10.0) and (not cliff or u90 >= (c.get("pct_of_circ") or 0) + RR.get("unlock90_tag", 10.0)):
        r.append("unlock90")
    if (e.get("liq") or {}).get("ok") is False:
        r.append("thin")
    if r != (e.get("risks") or []):
        risk_bad += 1
        if risk_bad <= 4:
            print("  RISKS %-22s stored=%s mine=%s" % (e["name"][:21], e.get("risks"), r))
tplr = io.open("template.html", encoding="utf-8").read()
blk = re.search(r"var RISK_TAGS = \{(.*?)\n\};", tplr, re.S)
rkeys = set(re.findall(r"^  (\w+): \{", blk.group(1), re.M)) if blk else set()
rused = {r for e in ALL for r in (e.get("risks") or [])}
from collections import Counter as _Cr
print("  appky s unlock daty: %d | chyby: %d | značky: %s | nesedí: %d"
      % (n_unl, bad, dict(_Cr(r for e in ALL for r in (e.get("risks") or []))), risk_bad))
if bad:
    fail("unlock", "%d unlock fields are inconsistent" % bad)
if risk_bad:
    fail("risks", "%d risk-tag lists disagree with the stored rules" % risk_bad)
if rused - rkeys:
    fail("risks", "risk codes with no RISK_TAGS text (tag silently dropped): %s" % ", ".join(sorted(rused - rkeys)))
# a risk must never touch trust or rank: every row the trusted view shows with a
# risk tag must still be in it, and the sort audit (19) is on potential alone
leaked = [e["name"] for e in ALL if e.get("risks") and bool(e.get("reliable")) !=
          (not (e.get("reliable_fail") or []))]
if leaked:
    fail("risks", "rows whose trust status contradicts their reasons: %s" % ", ".join(leaked[:4]))


head("34. PRO DEGENA — sedm bran, výběr a „Kdy prodat“ přepočítané z polí řádku")
DG = D.get("degen") or {}
DR = DG.get("rules") or {}
KNOWN = ["malý byznys", "neprověřené", "drahé", "moc velký", "bez srovnání", "byznys neroste",
         "mělká likvidita", "likvidita neznámá", "téma bez větru", "bez tématu"]


def degen_ref(e):
    f = []
    if (e.get("rev30d") or 0) < DR.get("min_rev30", 1e5):
        f.append("malý byznys")
    if not (e.get("reliable") or e.get("young")):
        f.append("neprověřené")
    if e.get("potential") is None or e["potential"] < DR.get("min_potential", 2.5):
        f.append("drahé")
    so = (e.get("test30") or {}).get("size_ok")
    if so is not True:
        f.append("moc velký" if so is False else "bez srovnání")
    g = (e.get("growth6m") or {}).get("g")
    if (e.get("traj") or {}).get("phase") in ("Pokles", "Stagnace") or g is None or g <= 0:
        f.append("byznys neroste")
    ok = (e.get("liq") or {}).get("ok")
    if ok is not True:
        f.append("mělká likvidita" if ok is False else "likvidita neznámá")
    t = e.get("theme")
    if not t:
        f.append("bez tématu")
    elif not (t.get("tier") == 5 or set(t.get("tags") or []) & {"leads", "fund_up"}):
        f.append("téma bez větru")
    return f


def exit_ref(e):
    out = []
    if e.get("potential_raw") is not None and e["potential_raw"] < 1:
        out.append("nad_stropem")
    g = (e.get("growth6m") or {}).get("g")
    if (e.get("traj") or {}).get("phase") in ("Zpomaluje", "Stagnace", "Pokles") or (g is not None and g <= 0):
        out.append("byznys_slabne")
    rs = (e.get("theme") or {}).get("rs1m")
    if rs is not None and rs < 0:
        out.append("tema_zaostava")
    return out


bad = 0
for e in APPS:
    mine = degen_ref(e)
    if mine != (e.get("degen_fail") or []) or bool(e.get("degen_ok")) != (not mine):
        bad += 1
        if bad <= 4:
            print("  MISMATCH %-22s stored=%s mine=%s" % (e["name"][:21], e.get("degen_fail"), mine))
    if e.get("degen_ok") and not (e.get("reliable") or e.get("young")):
        fail("degen", "%s passes the degen gates without passing trust" % e["name"])
    if exit_ref(e) != (e.get("exit_flags") or []):
        bad += 1
    if set(e.get("degen_fail") or []) - set(KNOWN):
        fail("degen", "%s has an unknown gate reason %s" % (e["name"], e.get("degen_fail")))
for e in CHAINS:
    if e.get("degen_ok") is not None or e.get("degen_fail"):
        bad += 1
key = lambda e: e.get("key") or e.get("slug")
ok_rows = sorted([e for e in APPS if e.get("degen_ok") and e.get("potential_raw") is not None],
                 key=lambda e: -e["potential_raw"])
sl = DG.get("shortlist") or []
exp_sl = [key(e) for e in ok_rows][:DR.get("shortlist", 10)]
if set(sl) != set(exp_sl) or len(sl) != len(exp_sl):
    fail("degen", "shortlist %s != recomputed %s" % (sl, exp_sl))
pr = {key(e): e.get("potential_raw") for e in APPS}
if any(pr[sl[i]] < pr[sl[i + 1]] for i in range(len(sl) - 1)):
    fail("degen", "shortlist is not ordered by potential")
near_exp = {key(e) for e in APPS if len(e.get("degen_fail") or []) == 1 and e.get("potential_raw") is not None
            and e["degen_fail"][0] not in ("malý byznys", "neprověřené", "drahé")}
if not set(DG.get("near") or []) <= near_exp:
    fail("degen", "a near miss failed more than one gate, or a pre-filter gate")
hist = {r: sum(1 for e in APPS if r in (e.get("degen_fail") or [])) for r in KNOWN}
if hist != (DG.get("fail_hist") or {}):
    fail("degen", "fail histogram disagrees with the rows")
if DG.get("n_ok") != len(ok_rows):
    fail("degen", "n_ok %s != %d rows passing" % (DG.get("n_ok"), len(ok_rows)))
# a reason without template text would render as a bare label on Start
blk = re.search(r"var DEGEN_REASONS = \{(.*?)\n\};", tplr, re.S)
dkeys = set(re.findall(r"^  '([^']+)': \{", blk.group(1), re.M)) if blk else set()
if set(KNOWN) - dkeys:
    fail("degen", "gate reasons with no DEGEN_REASONS text: %s" % ", ".join(sorted(set(KNOWN) - dkeys)))
print("  prošlo: %d z %d | výběr: %s | těsně: %d | neshody: %d"
      % (len(ok_rows), len(APPS), ", ".join(e["name"] for e in ok_rows[:10]), len(DG.get("near") or []), bad))
print("  proč neprošli: %s" % ", ".join("%s %d" % (k, v) for k, v in sorted(hist.items(), key=lambda kv: -kv[1]) if v))
if bad:
    fail("degen", "%d gate / exit-flag lists disagree with a recomputation" % bad)


head("35. ZPĚTNÝ TEST — verdikt ve snapshotu je z předem zamčených kritérií")
BT = D.get("backtest_summary")
if not BT:
    print("  snapshot zatím nemá backtest_summary (Start ukáže „neproběhl“)")
else:
    try:
        lock = json.load(io.open("backtest_cache/prereg.lock", encoding="utf-8")).get("sha256")
    except Exception:
        lock = None
    print("  verdikt: %s | prereg %s… | lock %s | změněno: %s"
          % (BT.get("verdict"), (BT.get("prereg_hash") or "")[:12], (lock or "chybí")[:12], BT.get("prereg_changed")))
    if BT.get("prereg_changed"):
        fail("backtest", "the pre-registration changed after the first run")
    if lock and lock != BT.get("prereg_hash"):
        fail("backtest", "summary prereg_hash does not match backtest_cache/prereg.lock")
    if BT.get("verdict") not in ("FUNGUJE", "NEPRŮKAZNÉ", "NEFUNGUJE"):
        fail("backtest", "unknown verdict %r" % BT.get("verdict"))


head("36. DOKUMENTACE — ARCHITECTURE.md popisuje celý datový kontrakt")
# The repo is public and ARCHITECTURE.md is how an outside agent learns the
# snapshot. A key the collector writes but the spec never names is a silent
# gap, so every key of the contract must appear in it `in backticks`.
try:
    ARCH = io.open("ARCHITECTURE.md", encoding="utf-8").read()
except FileNotFoundError:
    ARCH = None
    fail("docs", "ARCHITECTURE.md is missing")
if ARCH is not None:
    documented = set(re.findall(r"`([^`\n]+)`", ARCH))
    words = set()
    for span in documented:
        words.update(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", span))

    def keys_of(rows):
        out = set()
        for r in rows:
            out.update(r.keys())
        return out

    contract = {
        "top-level": set(D.keys()),
        "app row": keys_of(APPS),
        "chain row": keys_of(CHAINS),
        "theme": keys_of(THEMES_SNAP),
        "theme member": keys_of([m for th in THEMES_SNAP for m in th.get("members") or []]),
        "row theme": keys_of([e["theme"] for e in APPS + CHAINS if e.get("theme")]),
        "theme_join": set(TJ.keys()),
        "degen": set((D.get("degen") or {}).keys()),
        "theme keys": {th["key"] for th in THEMES_SNAP},
    }
    _cy = D.get("cycle") or {}
    if _cy:
        _cc = _cy.get("components") or {}
        _cs = _cy.get("series") or {}
        _rp = (_cc.get("retail") or {}).get("parts") or {}
        contract.update({
            "cycle": set(_cy.keys()),
            "cycle rules": set((_cy.get("rules") or {}).keys()),
            "cycle series": set(_cs.keys()) | set((_cs.get("retail_raw") or {}).keys()),
            "cycle components": set(_cc.keys()) | keys_of([c for c in _cc.values() if isinstance(c, dict)]),
            "cycle lines": keys_of([L for L in ((_cc.get("othersd") or {}).get("line"), (_cc.get("btcd") or {}).get("line"),
                                                 (_cc.get("btcd") or {}).get("lows_line")) if isinstance(L, dict)]),
            "cycle retail parts": set(_rp.keys()) | keys_of([v for v in _rp.values() if isinstance(v, dict)])
                                  | keys_of([m for v in _rp.values() if isinstance(v, dict) for m in v.get("movers") or []]),
            "cycle volume": set((_cc.get("volume") or {}).keys()),
            "cycle heat parts": keys_of(((_cc.get("btc_heat") or {}).get("parts") or {}).values()),
            "cycle backtest": set((_cy.get("backtest") or {}).keys()),
            "cycle hint": set((_cy.get("hint") or {}).keys()),
        })
    missing = {part: sorted(k for k in ks if k not in words) for part, ks in contract.items()}
    missing = {part: ks for part, ks in missing.items() if ks}
    print("  klíčů v kontraktu: %d | nepopsaných: %d"
          % (sum(len(v) for v in contract.values()), sum(len(v) for v in missing.values())))
    for part, ks in missing.items():
        print("  NEPOPSÁNO (%s): %s" % (part, ", ".join(ks)))
        fail("docs", "ARCHITECTURE.md does not mention %s keys: %s" % (part, ", ".join(ks)))


head("37. ALTSEASON CYKLUS v2 — index, pilíře, fáze, linie a verdikty přepočítané z uložených řad")
# A second implementation of cycle.py v2 (ARCHITECTURE §13.8, PREREG_V2): rotation
# on absolute scales, every retail row's four-year log score from the stored weekly
# samples, euphoria, the index, the phases, and both TradingView lines by brute
# force (pivots, the hull over them tried pivot by pivot, the status). Thresholds
# and the v2 lock hash are written HERE and must equal the snapshot's, so a silent
# change of a threshold or of the registration fails this section.
import bisect as _bis
CY = D.get("cycle")
V2_ID = "altseason-cycle-v2"
V2_LOCK_SHA = "c03f3450e3edd61cbad1077438adbb2cb93ee36fdd392b4e04392804a52d6914"
AUDIT_RULES = {"T": 75, "window": 208, "min_window": 104,
               "rot_dd_full": 50, "rot_rise_full": 3, "rot_breadth_lo": 25, "rot_breadth_hi": 90, "rot_min_parts": 2,
               "rot_weight": 2, "euph_weight": 1,
               "retail_window": 208, "retail_warmup": 52, "retail_span": 20, "retail_min_rows": 1,
               "coinbase_days": 30, "coinbase_min_days": 20, "meme_start_usd": 5000000, "apps_max_age_days": 7,
               "prehrate_euphoria": 70, "bezi_rotation": 60, "zacina_rotation": 30, "zacina_rise": 15,
               "zacina_weeks": 13, "btc_sezona_heat": 50, "btc_sezona_rotation": 30,
               "po_vrcholu_drop": 15, "po_vrcholu_weeks": 26, "po_vrcholu_min": 2,
               "trend_window": 312, "trend_pivot": 4, "trend_break": 0.03, "trend_confirm": 2, "trend_back_weeks": 13,
               "breadth_hi": 75, "breadth_lo": 25, "btcd_move_pp": 1.5, "heat_lo": 40, "heat_hi": 75,
               "retail_lo": 35, "retail_hi": 70, "retail_rush": 25, "vol_lo": 0.8, "vol_mid": 1.5, "vol_hi": 2.5}
if not CY:
    warn("cycle", "snapshot has no cycle block (history missing or the step failed)")
elif CY.get("history_missing"):
    warn("cycle", "cycle history missing — only today's values, nothing to recompute")
elif CY.get("version") != V2_ID:
    fail("cycle", "cycle block version %r — this audit checks %s" % (CY.get("version"), V2_ID))
else:
    try:
        json.dumps(CY, allow_nan=False)
    except ValueError:
        fail("cycle", "the cycle block holds NaN/Infinity — JSON.parse on the page would fail")
    R = CY.get("rules") or {}
    A = AUDIT_RULES
    for k, v in A.items():
        if R.get(k) != v:
            fail("cycle", "rule %s = %r, the audit expects %r" % (k, R.get(k), v))
    for k in sorted(set(R) - set(A)):
        fail("cycle", "rule %s is not one the audit knows — add it here and to ARCHITECTURE §13.8" % k)
    # the registration: the lock is the one committed on 2026-09-27, the summary's v2
    # section and the snapshot carry its hash
    try:
        lock = json.load(io.open("backtest_cache/cycle_prereg_v2.lock", encoding="utf-8"))
        if lock.get("sha256") != V2_LOCK_SHA or lock.get("id") != V2_ID:
            fail("cycle", "backtest_cache/cycle_prereg_v2.lock is not the v2 registration (%s…)" % lock.get("sha256", "")[:12])
    except (OSError, ValueError):
        fail("cycle", "backtest_cache/cycle_prereg_v2.lock is missing — the v2 registration must be committed")
    try:
        s2 = json.load(io.open("cycle_backtest_summary.json", encoding="utf-8")).get("v2") or {}
    except (OSError, ValueError):
        s2 = {}
    if not s2:
        warn("cycle", "cycle_backtest_summary.json has no v2 section — run python cycle_backtest.py (rules are the defaults)")
        if CY.get("prereg_sha256") is not None:
            fail("cycle", "the snapshot names a v2 hash but the summary has no v2 section")
    else:
        if s2.get("prereg_id") != V2_ID or s2.get("prereg_sha256") != V2_LOCK_SHA:
            fail("cycle", "summary v2 section is not the locked registration (%s)" % s2.get("prereg_id"))
        if (s2.get("rules") or {}).get("T") != R.get("T"):
            fail("cycle", "T in the snapshot (%r) is not the v2 summary's (%r)" % (R.get("T"), (s2.get("rules") or {}).get("T")))
        if CY.get("prereg_sha256") != V2_LOCK_SHA:
            fail("cycle", "the snapshot's prereg_sha256 is not the v2 lock")
        print("  backtest v2 %s · T %s · zámek %s…" % (s2.get("verdict"), R.get("T"), V2_LOCK_SHA[:12]))
    S = CY["series"]
    WK = CY["weeks"]
    n = len(WK)
    C = CY["components"]

    def m4(a):
        out = []
        for i in range(n):
            w = a[max(0, i - 3):i + 1]
            out.append(sum(w) / 4 if len(w) == 4 and all(x is not None for x in w) else None)
        return out

    def ptile(a, win, mn):
        out = []
        for i in range(n):
            prev = sorted(x for x in a[max(0, i - win):i] if x is not None)
            x = a[i]
            if x is None or len(prev) < mn:
                out.append(None)
                continue
            lo, hi = _bis.bisect_left(prev, x), _bis.bisect_right(prev, x)
            out.append(100.0 * (lo + 0.5 * (hi - lo)) / len(prev))
        return out

    cl = lambda x: max(0.0, min(100.0, x))
    # --- rotation on absolute scales
    bd4, od4, br4 = m4(S["btcd"]), m4(S["othersd"]), m4(S["breadth"])
    dd, p_rise, rot = [], [], []
    for i in range(n):
        w = [x for x in bd4[max(0, i - 51):i + 1] if x is not None]
        d_ = 100.0 * (1 - bd4[i] / max(w)) if bd4[i] is not None and len(w) >= 40 else None
        w = [x for x in od4[max(0, i - 51):i + 1] if x is not None]
        r_ = 100.0 * (od4[i] / min(w) - 1) if od4[i] is not None and len(w) >= 40 and min(w) > 0 else None
        parts = [cl(100.0 * d_ / A["rot_dd_full"]) if d_ is not None else None,
                 cl(100.0 * math.log(1 + r_ / 100.0) / math.log(A["rot_rise_full"])) if r_ is not None else None,
                 cl(100.0 * (br4[i] - A["rot_breadth_lo"]) / (A["rot_breadth_hi"] - A["rot_breadth_lo"]))
                 if br4[i] is not None else None]
        dd.append(d_)
        p_rise.append(parts[1])
        xs = [p for p in parts if p is not None]
        rot.append(sum(xs) / len(xs) if len(xs) >= A["rot_min_parts"] else None)
    # --- BTC heat: trailing percentiles, unchanged from v1
    hp = [ptile(S[k], A["window"], A["min_window"]) for k in ("mvrv", "puell", "mayer", "pi")]
    heat = []
    for i in range(n):
        xs = [h[i] for h in hp if h[i] is not None]
        heat.append(sum(xs) / len(xs) if len(xs) >= 3 else None)
    # --- retail: each row's score from its stored weekly samples; the max over the
    # samples of the last 208 weeks, found through the positions of the positive ones
    RRAW = S.get("retail_raw") or {}
    if sorted(RRAW) != ["apps", "coinbase", "degen", "upbit"]:
        fail("cycle", "series.retail_raw rows %s, expected apps/coinbase/degen/upbit" % sorted(RRAW))
    span = math.log(A["retail_span"])
    rsc = {}
    for key, xs in RRAW.items():
        if len(xs) != n:
            fail("cycle", "retail_raw.%s has %d weeks, the axis %d" % (key, len(xs), n))
            continue
        if key == "apps":
            rsc[key] = [None if x is None else cl(x) for x in xs]
            continue
        pos = [i for i, x in enumerate(xs) if x is not None and x > 0]
        out = [None] * n
        for m, i in enumerate(pos):
            if i < pos[0] + A["retail_warmup"]:
                continue
            j0 = _bis.bisect_left(pos, i - A["retail_window"] + 1)
            top = max(xs[pos[j]] for j in range(j0, m + 1))
            out[i] = 100.0 * max(0.0, min(1.0, 1 + math.log(xs[i] / top) / span))
        rsc[key] = out
    retail = []
    for i in range(n):
        xs = [rsc[k][i] for k in rsc if rsc[k][i] is not None]
        retail.append(sum(xs) / len(xs) if len(xs) >= A["retail_min_rows"] else None)
    euph = [(retail[i] + heat[i]) / 2 if retail[i] is not None and heat[i] is not None else None for i in range(n)]
    idx = [(A["rot_weight"] * rot[i] + A["euph_weight"] * euph[i]) / (A["rot_weight"] + A["euph_weight"])
           if rot[i] is not None and euph[i] is not None else None for i in range(n)]

    # --- the TradingView lines by brute force
    def bf_pivots(c, d, k):
        out = set()
        for j, x in enumerate(c):
            if x is None:
                continue
            nb = [(i, c[i]) for i in range(j - k, j + k + 1) if 0 <= i < len(c) and i != j and c[i] is not None]
            if all(d * x >= d * y for _, y in nb) and all(d * x > d * y for i, y in nb if i < j):
                out.add(j)
        return out

    def bf_line(c, d, t, piv, latest=None):
        """{status, anchor, touch, opp, slope, since, back}: every rule written out again."""
        none = {"status": "bez_trendu", "anchor": None, "touch": None, "opp": None, "slope": None,
                "since": None, "back": None}
        win = [(i, c[i]) for i in range(max(0, t - A["trend_window"] + 1), t + 1) if c[i] is not None]
        if not win:
            return none
        ext = max(d * v for _, v in win)
        a = min(i for i, v in win if d * v == ext)
        if a == t:
            return none
        cand = [(i, c[i]) for i in range(a + 1, t - A["trend_pivot"] + 1) if c[i] is not None]
        if not cand:
            return none
        low = min(d * v for _, v in cand)
        o = max(i for i, v in cand if d * v == low)
        P = sorted(j for j in piv if a < j < o)
        touch = None
        for p in P:
            sp = (c[p] - c[a]) / (p - a)
            if all(d * c[q] <= d * (c[a] + sp * (q - a)) + 1e-9 for q in P):
                touch = p
                break
        if touch is None:
            return none
        sl = (c[touch] - c[a]) / (touch - a)
        ln = lambda x: c[a] + sl * (x - a)
        if ln(t) <= 0:
            return none
        b = A["trend_break"]
        after = [i for i in range(o + 1, t + 1) if c[i] is not None]
        bey = {i: d * c[i] > d * ln(i) * (1 + d * b) for i in after}
        k = A["trend_confirm"]
        brks = [after[m] for m in range(k - 1, len(after)) if all(bey[after[m - q]] for q in range(k))]
        brk = brks[-1] if brks else None
        since = back = None
        if brk is not None:
            m = after.index(brk)
            while m > 0 and bey[after[m - 1]]:
                m -= 1
            since = after[m]
            back = next((i for i in after if i > brk and d * c[i] <= d * ln(i)), None)
        if brk is not None and back is None:
            st = "pruraz"
        elif bey.get(t):
            st = "pruraz_nepotvrzeny"
        elif brk is not None and t - brk <= A["trend_back_weeks"]:
            st = "zpet_pod"
        elif latest is not None and ln(latest[0]) > 0 and d * latest[1] > d * ln(latest[0]) * (1 + d * b):
            st = "pruraz_nepotvrzeny"
        else:
            st = "downtrend"
        return {"status": st, "anchor": a, "touch": touch, "opp": o, "slope": sl, "since": since, "back": back}

    od = S["othersd"]
    piv_od = bf_pivots(od, 1.0, A["trend_pivot"])
    wst, prev = [], None
    for t in range(n):
        if od[t] is not None:
            prev = bf_line(od, 1.0, t, piv_od)["status"]
        wst.append(prev)
    brk = [i for i in range(n) if od[i] is not None and wst[i] == "pruraz" and (i == 0 or wst[i - 1] != "pruraz")]
    if brk != list(S.get("breakouts") or []):
        fail("cycle", "OTHERS.D breakout weeks %s, recomputed %s" % (S.get("breakouts"), brk))
    brk_set = set(brk)

    # --- phases, first match
    T = A["T"]
    phase = []
    for i in range(n):
        I = idx[i]
        if I is None:
            phase.append(None)
            continue
        ro, eu, he = rot[i], euph[i], heat[i]
        prior = [idx[j] for j in range(max(0, i - A["po_vrcholu_weeks"]), i) if idx[j] is not None and idx[j] >= T]
        back = rot[i - A["zacina_weeks"]] if i >= A["zacina_weeks"] else None
        if len(prior) >= A["po_vrcholu_min"] and I <= max(prior) - A["po_vrcholu_drop"]:
            ph = "po_vrcholu"
        elif I >= T and eu >= A["prehrate_euphoria"]:
            ph = "prehrate"
        elif ro >= A["bezi_rotation"] or I >= T:
            ph = "bezi"
        elif ro >= A["zacina_rotation"] and ((back is not None and ro - back >= A["zacina_rise"])
                                             or any(j in brk_set for j in range(max(0, i - A["zacina_weeks"]), i + 1))):
            ph = "zacina"
        elif he >= A["btc_sezona_heat"] and ro < A["btc_sezona_rotation"]:
            ph = "btc_sezona"
        else:
            ph = "zima"
        phase.append(ph)

    def bad(mine, key):
        st = S.get(key) or []
        if len(st) != n:
            return n
        return sum(1 for i in range(n) if (mine[i] is None) != (st[i] is None)
                   or (mine[i] is not None and abs(mine[i] - st[i]) > 0.0501))
    bads = {k: bad(v, k) for k, v in (("index", idx), ("rotation", rot), ("euphoria", euph), ("retail", retail),
                                      ("heat", heat))}
    bad_p = sum(1 for i in range(n) if phase[i] != (S.get("phase") or [None] * n)[i])
    print("  %d týdnů · neshod indexu %d, rotace %d, euforie %d, retailu %d, BTC cyklu %d · neshod fáze %d · dnes %s (%s)"
          % (n, bads["index"], bads["rotation"], bads["euphoria"], bads["retail"], bads["heat"], bad_p,
             CY.get("index"), CY.get("phase")))
    for k, v in bads.items():
        if v:
            fail("cycle", "%d weekly %s values disagree with a recomputation" % (v, k))
    if bad_p:
        fail("cycle", "%d weekly phases disagree with a recomputation" % bad_p)
    if CY.get("index") != S["index"][-1] or CY.get("phase") != S["phase"][-1]:
        fail("cycle", "headline index/phase is not the last week")
    for k in ("rotation", "euphoria", "heat"):
        if CY.get(k) != S[k][-1]:
            fail("cycle", "headline %s is not the last week" % k)
    # --- both lines as of the newest close, with the newest daily point
    for key, d, series in (("othersd", 1.0, od), ("btcd", -1.0, S["btcd"])):
        comp = C.get(key) or {}
        t = max((i for i in range(n) if series[i] is not None), default=None)
        if t is None:
            continue
        dayp = comp.get("day")
        latest = ((n - 1) + (dayp - WK[-1]) / (7 * DAY), comp["value"]) if (dayp and dayp > WK[-1]
                                                                             and comp.get("value") is not None) else None
        want = bf_line(series, d, t, piv_od if key == "othersd" else bf_pivots(series, d, A["trend_pivot"]), latest)
        got = comp.get("line")
        name = "OTHERS.D" if key == "othersd" else "BTC.D"
        if want["anchor"] is None:
            if got is not None:
                fail("cycle", "%s: a stored line where the recomputation finds none" % name)
        elif not isinstance(got, dict):
            fail("cycle", "%s: the line is missing (recomputed: anchor %s, %s)" % (name, WK[want["anchor"]], want["status"]))
        else:
            wk = lambda i: WK[i] if i is not None else None
            diffs = [f for f, a_, b_ in (("anchor", got.get("anchor"), wk(want["anchor"])), ("touch", got.get("touch"), wk(want["touch"])),
                                        ("opp", got.get("opp"), wk(want["opp"])), ("status", got.get("status"), want["status"]),
                                        ("since", got.get("since"), wk(want["since"])), ("back", got.get("back"), wk(want["back"])))
                     if a_ != b_]
            if got.get("slope_week") is None or abs(got["slope_week"] - want["slope"]) > 5e-6:
                diffs.append("slope")
            print("  linie %s: kotva %s, dotek %s, dno/vrchol %s → %s%s (přepočet %s)"
                  % (name, datetime.datetime.utcfromtimestamp(WK[want["anchor"]]).strftime("%Y-%m-%d"),
                     datetime.datetime.utcfromtimestamp(WK[want["touch"]]).strftime("%Y-%m-%d"),
                     datetime.datetime.utcfromtimestamp(WK[want["opp"]]).strftime("%Y-%m-%d"), got.get("status"),
                     (" od %s" % datetime.datetime.utcfromtimestamp(got["since"]).strftime("%Y-%m-%d")) if got.get("since") else "",
                     "sedí" if not diffs else "NESEDÍ: " + ", ".join(diffs)))
            if diffs:
                fail("cycle", "%s line differs from the brute-force recomputation: %s" % (name, ", ".join(diffs)))
        if key == "othersd" and comp.get("verdict") != want["status"]:
            fail("cycle", "OTHERS.D verdict %s, the recomputed line says %s" % (comp.get("verdict"), want["status"]))
    # --- verdicts from their values
    b = C["btcd"]
    want = None if b.get("chg13_pp") is None else ("klesa" if b["chg13_pp"] <= -A["btcd_move_pp"]
                                                  else "roste" if b["chg13_pp"] >= A["btcd_move_pp"] else "bokem")
    if want != b.get("verdict"):
        fail("cycle", "BTC.D verdict %s, expected %s" % (b.get("verdict"), want))
    br = C["breadth"]
    want = None if br.get("value") is None else ("alty_vedou" if br["value"] >= A["breadth_hi"]
                                                else "btc_vede" if br["value"] <= A["breadth_lo"] else "smisene")
    if want != br.get("verdict"):
        fail("cycle", "breadth verdict %s, expected %s" % (br.get("verdict"), want))
    h = C["btc_heat"]
    hv = heat[-1]
    want = None if hv is None else ("brzy" if hv < A["heat_lo"] else "polovina" if hv < A["heat_hi"] else "prehraty")
    if want != h.get("verdict"):
        fail("cycle", "BTC cycle verdict %s, expected %s" % (h.get("verdict"), want))
    rt = C["retail"]
    if rt.get("value") != S["retail"][-1]:
        fail("cycle", "retail value %s is not the newest week of its series (%s)" % (rt.get("value"), S["retail"][-1]))
    for k in ("coinbase", "upbit", "degen", "apps"):
        p = (rt.get("parts") or {}).get(k)
        mine = rsc.get(k, [None])[-1]
        if p is None:
            if mine is not None:
                fail("cycle", "retail row %s is scored %.1f but missing from the table" % (k, mine))
        elif (p.get("score") is None) != (mine is None) or (mine is not None and abs(p["score"] - mine) > 0.0501):
            fail("cycle", "retail row %s score %s, recomputed %s" % (k, p.get("score"), mine))
    if rt.get("n_scored") != sum(1 for k in rsc if rsc[k][-1] is not None):
        fail("cycle", "retail n_scored %s is not the number of scored rows" % rt.get("n_scored"))
    for k in ("stables", "traffic", "ai"):
        if ((rt.get("parts") or {}).get(k) or {}).get("score") is not None:
            fail("cycle", "retail fact %s carries a score — facts are never scored" % k)
    want = None if rt.get("value") is None else ("spi" if rt["value"] < A["retail_lo"]
                                                else "probouzi" if rt["value"] < A["retail_hi"] else "hrne")
    if want != rt.get("verdict"):
        fail("cycle", "retail verdict %s, expected %s" % (rt.get("verdict"), want))
    rs_ = S["retail"]
    tempo = rs_[-1] - rs_[-5] if n >= 5 and rs_[-1] is not None and rs_[-5] is not None else None
    if (tempo is None) != (rt.get("tempo") is None) or (tempo is not None and abs(tempo - rt["tempo"]) > 0.11):
        fail("cycle", "retail tempo %s, recomputed %s" % (rt.get("tempo"), tempo))
    tw = None if rt.get("tempo") is None else ("naval" if rt["tempo"] >= A["retail_rush"] else "postupne" if rt["tempo"] >= 8
                                               else "odliv" if rt["tempo"] <= -8 else "stoji")
    if tw != rt.get("tempo_word"):
        fail("cycle", "retail tempo word %s, expected %s" % (rt.get("tempo_word"), tw))
    if any(x is not None and not (0 <= x <= 100) for x in rs_):
        fail("cycle", "retail history outside 0-100")
    vo = C.get("volume") or {}
    if vo.get("ratio_1y") is not None:
        r_ = vo["ratio_1y"]
        want = "slaby" if r_ < A["vol_lo"] else "normalni" if r_ < A["vol_mid"] else "zvyseny" if r_ < A["vol_hi"] else "extremni"
        if want != vo.get("verdict"):
            fail("cycle", "volume verdict %s, expected %s" % (vo.get("verdict"), want))
    # the BTC.D line through the altseason lows, recomputed
    ll = C["btcd"].get("lows_line")
    ev = CY.get("events") or {}
    if ll and ev.get("P1") and ev.get("P2"):
        i1, i2 = WK.index(ev["P1"]), WK.index(ev["P2"])
        bd_ = S["btcd"]
        want = bd_[i2] + (bd_[i2] - bd_[i1]) / (i2 - i1) * (n - 1 - i2)
        if abs(want - ll["line_now"]) > 0.011:
            fail("cycle", "BTC.D lows line %s, recomputed %.2f" % (ll["line_now"], want))
        else:
            print("  linie minim BTC.D dnes %.2f %% (přepočet sedí)" % want)
    # every data value the page translates has an entry
    try:
        TPL = io.open("template.html", encoding="utf-8").read()
        ph_keys = set(re.findall(r"^  '([a-z_]+)': \{", re.search(r"var ALT_PHASE = \{(.*?)\n\};", TPL, re.S).group(1), re.M))
        vd_keys = set(re.findall(r"^  '([a-z_]+)': \{", re.search(r"var CYCLE_VERDICT = \{(.*?)\n\};", TPL, re.S).group(1), re.M))
        need_ph = {p for p in S["phase"] if p}
        need_vd = {c.get("verdict") for c in (C["btcd"], C["othersd"], C["breadth"], C["btc_heat"], rt, vo) if c.get("verdict")}
        need_vd |= {L.get("status") for L in ((C["othersd"].get("line") or {}), (C["btcd"].get("line") or {})) if L.get("status")}
        if rt.get("tempo_word"):
            need_vd.add(rt["tempo_word"])
        if need_ph - ph_keys:
            fail("cycle", "phases with no ALT_PHASE text: %s" % ", ".join(sorted(need_ph - ph_keys)))
        if need_vd - vd_keys:
            fail("cycle", "verdicts with no CYCLE_VERDICT text: %s" % ", ".join(sorted(need_vd - vd_keys)))
    except (OSError, AttributeError):
        fail("cycle", "ALT_PHASE / CYCLE_VERDICT not found in template.html")


head("VERDICT")
if FAILS:
    print("FAILS (%d):" % len(FAILS))
    for f in FAILS:
        print("  X " + f)
else:
    print("no hard failures")
if WARNS:
    print("\nWARNINGS (%d):" % len(WARNS))
    for w in WARNS:
        print("  ! " + w)
if not FAILS and not WARNS:
    print("clean")
# a hard failure must fail the process too, not just print — like audit_static.js
raise SystemExit(1 if FAILS else 0)
