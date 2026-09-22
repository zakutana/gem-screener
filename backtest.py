"""
backtest.py — pre-registered, point-in-time backtest of the screener's Potenciál.

The question: had you bought what the screener ranked highest at the start of
each month since January 2024, would it have beaten BTC?

Everything the screener computes is reused, never re-derived: the same
grouping (group_apps), the same revenue measures (app_measures, trajectory,
strength), the same valuation and trust gates (apply_valuation). Only the
inputs are rewound: each revenue series is cut at the formation date t and the
market cap is rebuilt as today's supply x the price at t.

The hypotheses, thresholds and every judgement call live in PREREG below. It is
hashed into backtest_cache\\prereg.lock on the first run; a later edit shows up
as a banner in the report and `prereg_changed: true` in the summary.

Run:
    python backtest.py              primary run + every sensitivity, one go
    python backtest.py --selftest   the statistics on synthetic data only

Every HTTP response is cached under backtest_cache\\http, so a rerun costs
(almost) nothing. CoinGecko market caps are cached in backtest_cache\\cg_markets.json
with the date they were taken.
"""
import bisect
import concurrent.futures as cf
import datetime as dt
import gzip
import hashlib
import html
import json
import math
import os
import random
import sys
import threading
import time

# =====================================================================
# PRE-REGISTRATION — written before the first run that computed anything.
# Do not edit after results have been seen. The hash of json.dumps(PREREG,
# sort_keys=True) is locked in backtest_cache\prereg.lock.
# =====================================================================
PREREG = {
    "id": "gem-screener-potencial-backtest-v1",
    "registered_utc": "2026-09-22",
    "data_end_utc": "2026-09-22",
    "formations": {"rule": "first day of each month, 00:00 UTC",
                   "first": "2024-01-01", "last": "2026-06-01"},
    "horizons_days": {"3M": 91, "6M": 182},
    "horizon_rule": "a formation participates in a horizon only if t + horizon <= data_end",
    "universe": {
        "source": "collector.group_apps(ctx, 0): tokenized fee adapters grouped by "
                  "parentProtocol, double-counted adapters dropped",
        "rev30d_t": "sum of daily revenue with t - 30 d < ts <= t on the full untruncated "
                    "series (calendar window ending at t)",
        "min_rev30d_usd": 100000,
        "price_at_t": "a coins.llama.fi price at the stamp t (searchWidth 12h) must exist",
        "listed_filter_primary": "listedAt <= t. Leaf group: the /protocols entry with "
                                 "id == defillamaId. Parent group: min listedAt over its "
                                 "fee-adapter members found in /protocols, else over the "
                                 "/protocols entries whose parentProtocol == group key. "
                                 "Unknown listedAt: included and flagged.",
        "listed_filter_sensitivity": "the same universe without the listedAt filter",
        "dedupe": "groups resolving to one gecko_id in one formation: keep the one with "
                  "the largest rev30d_t (ties: smallest key); the count is reported",
        "rankable": "a current CoinGecko market cap > 0 and current price > 0. Other rows "
                    "enter base rates via their price path, not rankings; counted per formation",
    },
    "row_at_t": {
        "series": "full daily revenue series cut to ts <= t, then its last "
                  "collector.MAX_SERIES_DAYS (400) points, as the live screener stores it",
        "fields": "name, key, category, gecko_id, rev_series, mcap = mcap_t, "
                  "total30d = rev30d_t, holders30d = 0, holders_leaves = 0, primary = 'rev'",
        "primary_rev": "score_entity sets primary = 'rev' on every app; is_young reads it "
                       "(without it young never fires and trusted == reliable)",
        "measures": "collector.app_measures(e, t); e['traj'] = collector.trajectory(cut, 'sum'); "
                    "e['sila6m'] = collector.strength(cut, price points <= t, end=t, "
                    "measure='runrate'); collector.apply_valuation(universe_t, bench_t, t)",
        "mcap_t": "supply_now * p(t), supply_now = CoinGecko /coins/markets market_cap / "
                  "current_price (constant-supply proxy)",
        "holders_share": "skipped: dailyHoldersRevenue history not fetched",
    },
    "prices": {
        "fetch": "themes.fetch_grid on a weekly lattice anchored at t: t - 26 w .. t + 26 w, "
                 "stamps after data_end dropped",
        "why": "91 d = 13 w and 182 d = 26 w exactly; strength()'s points t - k * 30.33 d "
               "land within 2.33 d of a stamp (its tolerance is 3 d)",
        "btc": "themes.btc_row on the same lattice",
        "cleaning_primary": "none, raw prices; weekly moves > ln 20 are counted with "
                            "themes.clean_row",
    },
    "benchmark": "Hyperliquid's ps at t if a row named 'hyperliquid' is in the universe "
                 "with ps > 0, else the median ps of the universe rows with ps > 0",
    "trusted": "reliable or young, as apply_valuation marks them",
    "outcome": {
        "end_price": "price at the stamp t + horizon; if missing, the last available "
                     "weekly price inside (t, t + horizon]",
        "excess": "ln(p_end / p_t) - ln(btc_end / btc_t), BTC taken at the same stamp as p_end",
        "multiple": "p_end / p_t",
        "dead": "no price after t inside the window: multiple 0, excess -inf "
                "(ranks lowest, enters medians as -inf)",
        "dead_sensitivity": "the tests rerun with those rows excluded",
    },
    "stats": {
        "spearman": "Pearson correlation of average ranks (ties averaged)",
        "min_rows_per_formation": 10,
        "quintile": "within a formation rows sorted by potential_raw descending (ties by "
                    "key); top quintile = the ceil(n / 5) highest, bottom = the ceil(n / 5) lowest",
        "bootstrap": "moving-block over the participating formations in date order: "
                     "ceil(n / L) blocks, starts uniform on [0, n - L], concatenated, cut "
                     "to n; B = 5000; a fresh random.Random(20260922) per statistic; "
                     "CI90 = 5th / 95th percentile (linear interpolation); resamples with "
                     "an undefined or non-finite statistic are dropped and counted",
        "wilson": "Wilson score interval, z = 1.6448536 (90 %)",
    },
    "H1": {"role": "primary", "signal": "potential_raw",
           "rows": "trusted rows with potential_raw and a 3M outcome",
           "stat": "mean over formations of the Spearman IC of potential_raw vs 3M excess",
           "block": 3, "pass": "mean IC >= 0.05 and CI90 lower bound > 0"},
    "H2": {"role": "primary",
           "rows": "trusted rows with potential_raw and a 6M outcome",
           "stat": "lift = P(multiple >= 3 | top quintile) / P(multiple >= 3 | all these "
                   "rows), both pooled over formations",
           "block": 6, "pass": "lift >= 1.5 and CI90 lower bound > 1"},
    "H3": {"role": "secondary",
           "rows": "rankable rows with a 6M outcome",
           "gates": ["rev30d_t >= 100000 (every universe row)",
                     "trusted",
                     "potential >= 2.5",
                     "Test 30x size: 30 * mcap_t <= mcap_t of the biggest other-token "
                     "rankable row of the same DeFiLlama category in the same universe at t; "
                     "a category leader ('bez srovnani') fails",
                     "business: traj phase not in {Pokles, Stagnace} and growth6m.g > 0",
                     "theme: themes.theme_of_app(row) is not None"],
           "not_reconstructable": ["liquidity gate", "theme tier at t",
                                   "theme-basket fallback of Test 30x"],
           "stat": "median 6M excess of gate passers - median 6M excess of the other rows, pooled",
           "block": 6, "pass": "CI90 lower bound > 0",
           "variants": "reported with the theme gate; without it as a variant"},
    "verdict": {"FUNGUJE": "H1 and H2 pass",
                "NEFUNGUJE": "a point estimate on or below the null: mean IC <= 0 or lift <= 1",
                "NEPRUKAZNE": "everything else: positive estimates with a CI reaching the "
                              "null, positive estimates under the threshold, or an "
                              "undefined statistic"},
    "descriptive": {
        "signals": ["potential_raw on all rankable rows", "sila6m.ratio", "growth6m.g",
                    "ln(mcap_t), expected sign negative",
                    "momentum: 3M excess return up to t (ln p_t/p_t-91 - ln btc_t/btc_t-91)"],
        "rows": "H1 rows (3M) / H2 rows (6M) with the signal not None",
        "stats": "mean IC 3M (block 3) and 6M (block 6) with CI90; Q5 - Q1: mean over "
                 "formations of (median relative return of the top quintile - that of the "
                 "bottom quintile), relative return = exp(excess) - 1 (dead = -1), CI90 block 3",
    },
    "q4_2024": "formation 2024-10-01, 3M horizon, primary universe: top 15 trusted rows by "
               "potential_raw with their 3M multiple; the 10 largest 3M multiples of the "
               "whole universe with their Potencial rank among rankable rows and trust "
               "status; medians of the multiple for both",
    "base_rates": "6M multiple >= 3, >= 5, >= 10, pooled over formations, primary universe: "
                  "all rows (rankable or not) and the H2 rows; Wilson 90 %",
    "sensitivity": ["no listedAt filter: H1, H2, H3, verdict",
                    "dead-outcome rows excluded: H1, H2, verdict",
                    "prices cleaned with themes.clean_row: H1, H2, verdict"],
}

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "backtest_cache")
REPORT = os.path.join(HERE, "backtest_report.html")
SUMMARY = os.path.join(HERE, "backtest_summary.json")
CG = "https://api.coingecko.com/api/v3"
UTC = dt.timezone.utc
DAY = 86400
WEEK = 7 * DAY
I0 = 26                       # index of t on the anchored weekly lattice
H_WEEKS = {"3M": 13, "6M": 26}
MIN_REV = PREREG["universe"]["min_rev30d_usd"]
MIN_ROWS = PREREG["stats"]["min_rows_per_formation"]
B = 5000
SEED = 20260922
Z90 = 1.6448536
WORKERS = 6
CG_SPACING = 6.5


def _ts(s):
    return int(dt.datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=UTC).timestamp())


DATA_END = _ts(PREREG["data_end_utc"])


# ------------------------------------------------------------------ logging
_log_lock = threading.Lock()


def log(msg, stamp=True):
    line = "[%s] %s" % (time.strftime("%H:%M:%S"), msg) if stamp else msg
    with _log_lock:
        print(line, flush=True)
        try:
            os.makedirs(CACHE, exist_ok=True)
            with open(os.path.join(CACHE, "run.log"), "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass


# ------------------------------------------------------------------ import guard
def import_screener():
    """collector.py is being edited concurrently; a half-saved file must not
    kill the run, so retry the import for up to ten minutes."""
    last = None
    for attempt in range(10):
        try:
            import collector
            import themes
            return collector, themes
        except Exception as e:           # SyntaxError, ImportError, NameError ...
            last = e
            sys.modules.pop("collector", None)
            sys.modules.pop("themes", None)
            log("import collector selhal (%s) — zkusím znovu za 60 s" % e)
            time.sleep(60)
    raise RuntimeError("collector.py nejde importovat: %s" % last)


def sha256_file(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


# ------------------------------------------------------------------ HTTP cache
class Counter:
    def __init__(self):
        self.lock = threading.Lock()
        self.c = {}

    def inc(self, k, n=1):
        with self.lock:
            self.c[k] = self.c.get(k, 0) + n


MISS = object()


def _cpath(url):
    h = hashlib.sha1(url.encode("utf-8")).hexdigest()
    return os.path.join(CACHE, "http", h[:2], h + ".json.gz")


def cache_read(url):
    p = _cpath(url)
    if not os.path.exists(p):
        return MISS
    try:
        with gzip.open(p, "rt", encoding="utf-8") as f:
            return json.load(f).get("data")
    except Exception:
        return MISS


def cache_write(url, data):
    p = _cpath(url)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = "%s.%d.tmp" % (p, threading.get_ident())
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        json.dump({"url": url, "data": data}, f, separators=(",", ":"))
    os.replace(tmp, p)


def make_ctx(collector, counter):
    """collector.Ctx with a disk cache in front of get().

    A None answer is cached only when it was a quiet 400/404 (slug probing, a
    definitive "no such thing"); a failure that Ctx.get warns about (429s
    exhausted, 5xx, network) is not, so the next run retries it."""

    class CachedCtx(collector.Ctx):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            self._tl = threading.local()
            orig = self.session.get

            def counted(*aa, **kk):
                counter.inc("http_requests")
                return orig(*aa, **kk)
            self.session.get = counted

        def warn(self, msg):
            self._tl.warned = True
            super().warn(msg)

        def get(self, url, timeout=30, quiet_status=(400, 404), warn=True):
            hit = cache_read(url)
            if hit is not MISS:
                counter.inc("cache_hits")
                return hit
            counter.inc("cache_misses")
            self._tl.warned = False
            data = super().get(url, timeout=timeout, quiet_status=quiet_status, warn=warn)
            if data is not None or not getattr(self._tl, "warned", False):
                cache_write(url, data)
            return data

    return CachedCtx(log=lambda m: log(m, stamp=False))      # Ctx.log stamps its own lines


# ------------------------------------------------------------------ small maths
def median(xs):
    xs = sorted(xs)
    n = len(xs)
    if not n:
        return None
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2.0


def avg_ranks(xs):
    n = len(xs)
    order = sorted(range(n), key=lambda i: xs[i])
    r = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        a = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            r[order[k]] = a
        i = j + 1
    return r


def pearson(a, b):
    n = len(a)
    if n < 3:
        return None
    ma, mb = sum(a) / n, sum(b) / n
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((y - mb) ** 2 for y in b)
    if va <= 0 or vb <= 0:
        return None
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / math.sqrt(va * vb)


def spearman(xs, ys):
    return pearson(avg_ranks(xs), avg_ranks(ys))


def quantile(sv, q):
    n = len(sv)
    if not n:
        return None
    h = (n - 1) * q
    lo = int(math.floor(h))
    hi = min(lo + 1, n - 1)
    return sv[lo] + (h - lo) * (sv[hi] - sv[lo])


def mbb_indices(n, L, rng):
    L = max(1, min(L, n))
    k = -(-n // L)
    idx = []
    for _ in range(k):
        s = rng.randint(0, n - L)
        idx.extend(range(s, s + L))
    return idx[:n]


def bootstrap(units, stat, L):
    """Moving-block bootstrap over formations (date order). Returns (lo, hi, dropped)."""
    n = len(units)
    if n == 0:
        return None, None, 0
    rng = random.Random(SEED)
    vals, dropped = [], 0
    for _ in range(B):
        v = stat([units[i] for i in mbb_indices(n, L, rng)])
        if v is None or not math.isfinite(v):
            dropped += 1
            continue
        vals.append(v)
    vals.sort()
    return quantile(vals, 0.05), quantile(vals, 0.95), dropped


def wilson(k, n, z=Z90):
    if not n:
        return None, None
    p = k / float(n)
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    hw = z * math.sqrt(p * (1 - p) / n + z * z / (4.0 * n * n)) / den
    return max(0.0, c - hw), min(1.0, c + hw)


def mean(xs):
    return sum(xs) / len(xs) if xs else None


# ------------------------------------------------------------------ data
def formation_dates():
    out = []
    y, m = 2024, 1
    first, last = PREREG["formations"]["first"], PREREG["formations"]["last"]
    while True:
        s = "%04d-%02d-01" % (y, m)
        if s > last:
            break
        if s >= first:
            out.append(_ts(s))
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


def lattice(t):
    return [t + (k - I0) * WEEK for k in range(2 * I0 + 1) if t + (k - I0) * WEEK <= DATA_END]


def listed_at_map(ctx, collector, groups):
    """(listedAt, source) per group key. Leaf: its /protocols entry. Parent: the
    earliest of its fee-adapter members, else of its /protocols children."""
    prot = {str(p.get("id")): p for p in ctx.protocols}
    members = {}
    for e in ctx.fee_protocols:
        if e.get("protocolType") != "protocol" or e.get("doublecounted"):
            continue
        if not collector.gecko_for_app(ctx, e):
            continue
        key = e["parentProtocol"] if e.get("parentProtocol") else "leaf#%s" % e.get("defillamaId")
        members.setdefault(key, []).append(str(e.get("defillamaId")))
    children = {}
    for p in ctx.protocols:
        if p.get("parentProtocol"):
            children.setdefault(p["parentProtocol"], []).append(p)
    out = {}
    for g in groups:
        ts = [prot[i]["listedAt"] for i in members.get(g["key"], [])
              if i in prot and prot[i].get("listedAt")]
        src = "members"
        if not ts and g["key"].startswith("parent#"):
            ts = [p["listedAt"] for p in children.get(g["key"], []) if p.get("listedAt")]
            src = "children"
        out[g["key"]] = (int(min(ts)), src) if ts else (None, "unknown")
    return out


def fetch_histories(ctx, collector, groups):
    out, used = {}, {}
    t0 = time.time()

    def one(g):
        cands = g["slug"] if isinstance(g["slug"], list) else [g["slug"]]
        try:
            s, u = collector.fetch_rev_history(ctx, cands)
        except Exception as e:                  # a hole, said out loud, not a crash
            ctx.warn("revenue history %s failed: %s" % (g["key"], e))
            return g["key"], [], None
        clean = sorted([int(p[0]), float(p[1] or 0.0)] for p in s
                       if isinstance(p, (list, tuple)) and len(p) >= 2 and p[0] is not None)
        return g["key"], clean, u

    with cf.ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = [ex.submit(one, g) for g in groups]
        for i, fut in enumerate(cf.as_completed(futs), 1):
            k, s, u = fut.result()
            out[k], used[k] = s, u
            if i % 100 == 0 or i == len(futs):
                log("  revenue historie %d/%d (%.0f s)" % (i, len(futs), time.time() - t0))
    return out, used


def fetch_mcaps(ctx, themes, ids, counter):
    """Current market cap + price per gecko id, via themes.cg_get only, >= 6 s
    apart. Stored with the date; an id CoinGecko does not return is stored as
    None (no live market). A failed call stores nothing, so a rerun retries."""
    path = os.path.join(CACHE, "cg_markets.json")
    store = {"fetched_utc": None, "rows": {}}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            store = json.load(f)
    missing = [g for g in sorted(ids) if g not in store["rows"]]
    log("CoinGecko: %d id v cache, %d chybí" % (len(ids) - len(missing), len(missing)))
    last = 0.0
    for i in range(0, len(missing), 200):
        chunk = missing[i:i + 200]
        wait = CG_SPACING - (time.time() - last)
        if last and wait > 0:
            time.sleep(wait)
        url = (CG + "/coins/markets?vs_currency=usd&ids=" + ",".join(chunk)
               + "&order=market_cap_desc&per_page=250&page=1")
        data = themes.cg_get(ctx, url, timeout=40)
        last = time.time()
        counter.inc("coingecko_calls")
        if data is None:
            log("  ! CoinGecko dávka %d selhala — zkusí se při dalším běhu" % (i // 200))
            continue
        got = {r["id"]: {"mcap": r.get("market_cap"), "price": r.get("current_price"),
                         "symbol": (r.get("symbol") or "").upper(), "name": r.get("name")}
               for r in data if r.get("id")}
        for g in chunk:
            store["rows"][g] = got.get(g)
        store["fetched_utc"] = store["fetched_utc"] or dt.datetime.now(UTC).strftime("%Y-%m-%d %H:%M")
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(store, f)
        os.replace(tmp, path)
    return store


# ------------------------------------------------------------------ one formation
def outcome(row, btc, h):
    ie = I0 + h
    if ie >= len(row):
        return None
    p0, b0 = row[I0], btc[I0]
    j = next((k for k in range(ie, I0, -1) if row[k]), None)
    if j is None:
        return {"mult": 0.0, "excess": float("-inf"), "dead": True, "lag_w": None}
    if not btc[j] or not b0:
        raise RuntimeError("BTC price missing at lattice index %d" % j)
    return {"mult": row[j] / p0,
            "excess": math.log(row[j] / p0) - math.log(btc[j] / b0),
            "dead": False, "lag_w": ie - j}


def build_rows(t, cands, prices, btc, stamps, listed, mcaps, collector, themes, listed_filter):
    """Universe at t for one variant -> list of flat records (no series)."""
    pre = []
    for g, cut_full, rev30 in cands:
        prow = prices.get(g["gecko_id"])
        if not prow or not prow[I0]:
            continue
        la, src = listed[g["key"]]
        if listed_filter and la is not None and la > t:
            continue
        pre.append((g, cut_full, rev30, prow, la, src))
    # one token, one row
    best = {}
    for item in sorted(pre, key=lambda x: (-x[2], x[0]["key"])):
        best.setdefault(item[0]["gecko_id"], item)
    n_dupes = len(pre) - len(best)

    es = []
    for g, cut_full, rev30, prow, la, src in sorted(best.values(), key=lambda x: x[0]["key"]):
        mc = mcaps.get(g["gecko_id"]) or {}
        rankable = bool(mc.get("mcap") and mc["mcap"] > 0 and mc.get("price") and mc["price"] > 0)
        mcap_t = mc["mcap"] / mc["price"] * prow[I0] if rankable else None
        cut = cut_full[-collector.MAX_SERIES_DAYS:]
        e = {"name": g["name"], "key": g["key"], "category": g["category"],
             "gecko_id": g["gecko_id"], "rev_series": cut, "mcap": mcap_t,
             "total30d": rev30, "holders30d": 0, "holders_leaves": 0, "primary": "rev"}
        collector.app_measures(e, t)
        e["traj"] = collector.trajectory(cut, "sum")
        pts = [(stamps[k], prow[k]) for k in range(I0 + 1) if prow[k]]
        e["sila6m"] = collector.strength(cut, pts, end=t, measure="runrate")
        e["_x"] = (rev30, prow, la, src, rankable)
        es.append(e)

    hl = next((e for e in es if (e.get("name") or "").strip().lower() == "hyperliquid"), None)
    if hl and hl.get("ps") and hl["ps"] > 0:
        bench, bench_label = hl["ps"], "Hyperliquid"
    else:
        ms = [e["ps"] for e in es if e.get("ps") and e["ps"] > 0]
        bench, bench_label = (collector.median(ms) if ms else None), "medián"
    collector.apply_valuation(es, bench, t)

    rankable_rows = [e for e in es if e["_x"][4]]
    by_cat = {}
    for e in rankable_rows:
        by_cat.setdefault(e.get("category"), []).append(e)

    recs = []
    for e in es:
        rev30, prow, la, src, rankable = e["_x"]
        trusted = bool(e.get("reliable") or e.get("young"))
        size_ok, ceil_name = False, None
        if rankable:
            peers = [p for p in by_cat.get(e.get("category"), [])
                     if p is not e and p.get("gecko_id") != e["gecko_id"] and p.get("mcap")]
            top = max(peers, key=lambda p: p["mcap"], default=None)
            if top and top["mcap"] >= e["mcap"]:
                ceil_name = top["name"]
                size_ok = TEST_MULT * e["mcap"] <= top["mcap"]
            else:
                ceil_name = "bez srovnání"
        g6 = (e.get("growth6m") or {}).get("g")
        phase = (e.get("traj") or {}).get("phase")
        gate = {
            "trusted": trusted,
            "pot": (e.get("potential") or 0) >= 2.5,
            "size": size_ok,
            "business": phase not in ("Pokles", "Stagnace") and g6 is not None and g6 > 0,
            "theme": themes.theme_of_app(e) is not None,
        }
        mom = None
        if prow[I0 - 13] and btc[I0 - 13]:
            mom = math.log(prow[I0] / prow[I0 - 13]) - math.log(btc[I0] / btc[I0 - 13])
        recs.append({
            "t": t, "key": e["key"], "name": e["name"], "gecko": e["gecko_id"],
            "category": e.get("category"), "rankable": rankable,
            "listed_at": la, "listed_src": src, "rev30d": rev30, "mcap_t": e.get("mcap"),
            "ps": e.get("ps"), "potential_raw": e.get("potential_raw") if rankable else None,
            "potential": e.get("potential") if rankable else None,
            "reliable": bool(e.get("reliable")), "young": bool(e.get("young")),
            "trusted": trusted and rankable, "fails": list(e.get("reliable_fail") or []),
            "sila": (e.get("sila6m") or {}).get("ratio"), "g6m": g6, "phase": phase,
            "ln_mcap": math.log(e["mcap"]) if e.get("mcap") else None, "mom3m": mom,
            "theme": themes.theme_of_app(e), "ceiling": ceil_name, "gate": gate,
            "h3": rankable and all(gate.values()),
            "h3_notheme": rankable and all(v for k, v in gate.items() if k != "theme"),
            "out": {h: outcome(prow, btc, w) if t + PREREG["horizons_days"][h] * DAY <= DATA_END
                    else None for h, w in H_WEEKS.items()},
        })
    ranked = sorted([r for r in recs if r["potential_raw"] is not None],
                    key=lambda r: (-r["potential_raw"], r["key"]))
    for i, r in enumerate(ranked, 1):
        r["rank"] = i
    for r in recs:
        r.setdefault("rank", None)
    meta = {"bench": bench, "bench_label": bench_label, "n_dupes": n_dupes,
            "n_ranked": len(ranked)}
    return recs, meta


TEST_MULT = 30


# ------------------------------------------------------------------ tests
def h_rows(recs, horizon, signal="potential_raw", trusted_only=True, drop_dead=False):
    out = []
    for r in recs:
        o = r["out"].get(horizon)
        if not o or r.get(signal) is None:
            continue
        if trusted_only and not r["trusted"]:
            continue
        if not trusted_only and not r["rankable"]:
            continue
        if drop_dead and o["dead"]:
            continue
        out.append(r)
    return out


def participating(forms, horizon):
    return [t for t in forms if t + PREREG["horizons_days"][horizon] * DAY <= DATA_END]


def ic_test(by_f, forms, horizon, signal="potential_raw", trusted_only=True, drop_dead=False,
            block=3):
    per, units = [], []
    for t in participating(forms, horizon):
        rows = h_rows(by_f[t], horizon, signal, trusted_only, drop_dead)
        ic = None
        if len(rows) >= MIN_ROWS:
            ic = spearman([r[signal] for r in rows], [r["out"][horizon]["excess"] for r in rows])
        per.append({"t": t, "n": len(rows), "ic": ic})
        if ic is not None:
            units.append(ic)
    m = mean(units)
    lo, hi, dropped = bootstrap(units, mean, block)
    return {"ic_mean": m, "ci90": [lo, hi], "n_formations": len(units), "per": per,
            "dropped": dropped, "n_rows": sum(p["n"] for p in per if p["ic"] is not None)}


def top_n(n):
    return -(-n // 5)


def lift_units(by_f, forms, drop_dead=False):
    units, per = [], []
    for t in participating(forms, "6M"):
        rows = h_rows(by_f[t], "6M", drop_dead=drop_dead)
        if len(rows) < MIN_ROWS:
            per.append({"t": t, "n": len(rows), "top_hits": None})
            continue
        rows.sort(key=lambda r: (-r["potential_raw"], r["key"]))
        q = top_n(len(rows))
        th = sum(1 for r in rows[:q] if r["out"]["6M"]["mult"] >= 3)
        ah = sum(1 for r in rows if r["out"]["6M"]["mult"] >= 3)
        units.append((th, q, ah, len(rows)))
        per.append({"t": t, "n": len(rows), "top_hits": th, "top_n": q, "all_hits": ah})
    return units, per


def lift_stat(units):
    th, tn, ah, an = (sum(u[i] for u in units) for i in range(4))
    if not tn or not an or not ah:
        return None
    return (th / tn) / (ah / an)


def h2_test(by_f, forms, drop_dead=False):
    units, per = lift_units(by_f, forms, drop_dead)
    lift = lift_stat(units)
    lo, hi, dropped = bootstrap(units, lift_stat, 6)
    th, tn, ah, an = (sum(u[i] for u in units) for i in range(4)) if units else (0, 0, 0, 0)
    return {"lift": lift, "ci90": [lo, hi], "base_rate": ah / an if an else None,
            "top_rate": th / tn if tn else None, "top_hits": th, "top_n": tn,
            "all_hits": ah, "all_n": an, "n_formations": len(units), "per": per,
            "dropped": dropped}


def h3_test(by_f, forms, key="h3"):
    units = []
    for t in participating(forms, "6M"):
        rows = [r for r in by_f[t] if r["rankable"] and r["out"]["6M"]]
        units.append(([r["out"]["6M"]["excess"] for r in rows if r[key]],
                      [r["out"]["6M"]["excess"] for r in rows if not r[key]]))

    def stat(us):
        a = [x for u in us for x in u[0]]
        b = [x for u in us for x in u[1]]
        if not a or not b:
            return None
        d = median(a) - median(b)
        return d if not math.isnan(d) else None

    a = [x for u in units for x in u[0]]
    b = [x for u in units for x in u[1]]
    d = stat(units)
    lo, hi, dropped = bootstrap(units, stat, 6)
    tokens = {r["gecko"] for t in participating(forms, "6M") for r in by_f[t]
              if r["rankable"] and r["out"]["6M"] and r[key]}
    return {"diff_median": d, "ci90": [lo, hi], "n_pass_rows": len(a), "n_rest_rows": len(b),
            "n_pass_tokens": len(tokens),
            "median_pass": median(a) if a else None, "median_rest": median(b) if b else None,
            "pass": lo is not None and lo > 0, "dropped": dropped,
            "n_formations_with_pass": sum(1 for u in units if u[0])}


def q51_test(by_f, forms, signal, trusted_only=True):
    units = []
    for t in participating(forms, "3M"):
        rows = h_rows(by_f[t], "3M", signal, trusted_only)
        if len(rows) < MIN_ROWS:
            continue
        rows.sort(key=lambda r: (-r[signal], r["key"]))
        q = top_n(len(rows))
        rel = lambda r: math.exp(r["out"]["3M"]["excess"]) - 1.0   # dead -> -1
        units.append(median([rel(r) for r in rows[:q]]) - median([rel(r) for r in rows[-q:]]))
    lo, hi, _ = bootstrap(units, mean, 3)
    return {"q51": mean(units), "ci90": [lo, hi], "n_formations": len(units)}


def judge(h1, h2):
    h1["pass"] = h1["ic_mean"] is not None and h1["ic_mean"] >= 0.05 and \
        h1["ci90"][0] is not None and h1["ci90"][0] > 0
    h2["pass"] = h2["lift"] is not None and h2["lift"] >= 1.5 and \
        h2["ci90"][0] is not None and h2["ci90"][0] > 1
    if h1["pass"] and h2["pass"]:
        return "FUNGUJE"
    if h1["ic_mean"] is None or h2["lift"] is None:
        return "NEPRŮKAZNÉ"
    if h1["ic_mean"] <= 0 or h2["lift"] <= 1:
        return "NEFUNGUJE"
    return "NEPRŮKAZNÉ"


def base_rates(by_f, forms, rows_fn):
    out = {}
    rows = [r for t in participating(forms, "6M") for r in rows_fn(by_f[t])]
    n = len(rows)
    for k in (3, 5, 10):
        hits = sum(1 for r in rows if r["out"]["6M"]["mult"] >= k)
        lo, hi = wilson(hits, n)
        out["p%d" % k] = {"p": hits / n if n else None, "k": hits, "n": n, "ci90": [lo, hi]}
    return out


# ------------------------------------------------------------------ formatting (Czech)
NB = " "


def cz(x, d=2, sign=False):
    if x is None:
        return "—"
    if isinstance(x, float) and math.isinf(x):
        return "−∞" if x < 0 else "+∞"
    s = ("{:+,.%df}" % d if sign else "{:,.%df}" % d).format(x)
    return s.replace(",", " ").replace(".", ",").replace(" ", NB).replace("-", "−")


def pct(x, d=1, sign=False):
    return "—" if x is None else cz(100.0 * x, d, sign) + NB + "%"


def xmul(x, d=2):
    return "—" if x is None else cz(x, d) + "×"


def usd(x):
    if x is None:
        return "—"
    for div, suf in ((1e9, "mld."), (1e6, "mil."), (1e3, "tis.")):
        if abs(x) >= div:
            return "$" + cz(x / div, 1) + NB + suf
    return "$" + cz(x, 0)


def ci(c, f=cz, d=3):
    if not c or c[0] is None:
        return "—"
    return "[%s; %s]" % (f(c[0], d), f(c[1], d))


def rel_pct(excess):
    """log excess -> relative return in % for display."""
    if excess is None:
        return "—"
    return pct(math.exp(excess) - 1.0, 1, sign=True)


def day(t):
    d = dt.datetime.fromtimestamp(t, UTC)
    return "%d.%s%d.%s%d" % (d.day, NB, d.month, NB, d.year)


def mon(t):
    d = dt.datetime.fromtimestamp(t, UTC)
    return "%d/%d" % (d.month, d.year)


FAIL_CZ = {"market cap pod $3M": "mcap pod $3M", "krátká historie": "krátká historie",
           "hluboko pod svým maximem": "pod maximem", "trend nejde změřit": "bez trendu",
           "klesající trend": "klesá", "stará data": "stará data"}


def status(r):
    if not r["rankable"]:
        return "bez dnešního mcap — nehodnoceno"
    if r["reliable"]:
        return "prověřený"
    if r["young"]:
        return "prověřený (nový)"
    return "neprověřený: " + ", ".join(FAIL_CZ.get(f, f) for f in r["fails"])


# ------------------------------------------------------------------ selftest
def selftest():
    ok = True

    def check(name, cond):
        nonlocal ok
        print(("OK   " if cond else "FAIL ") + name)
        ok = ok and cond
    check("spearman monotone = 1", abs(spearman([1, 2, 3, 4, 5], [2, 4, 8, 16, 99]) - 1) < 1e-12)
    check("spearman reversed = -1", abs(spearman([1, 2, 3, 4], [4, 3, 2, 1]) + 1) < 1e-12)
    check("avg ranks with ties", avg_ranks([10, 20, 20, 5]) == [2.0, 3.5, 3.5, 1.0])
    ninf = float("-inf")
    check("-inf ranks lowest", avg_ranks([ninf, 0.0, ninf, 1.0]) == [1.5, 3.0, 1.5, 4.0])
    lo, hi = wilson(5, 20, 1.959964)
    check("wilson 95%% 5/20 = (0.1119, 0.4687): got (%.4f, %.4f)" % (lo, hi),
          abs(lo - 0.1119) < 5e-4 and abs(hi - 0.4687) < 5e-4)
    check("quantile type 7", quantile([1, 2, 3, 4], 0.5) == 2.5 and quantile([0, 10], 0.05) == 0.5)
    rng = random.Random(1)
    idx = mbb_indices(10, 3, rng)
    check("mbb length and contiguous blocks", len(idx) == 10 and all(
        idx[i + 1] == idx[i] + 1 for i in range(0, 9) if (i + 1) % 3))
    lo, hi, _ = bootstrap([0.2] * 30, mean, 3)
    check("bootstrap of a constant", abs(lo - 0.2) < 1e-12 and abs(hi - 0.2) < 1e-12)
    r2 = random.Random(7)
    units = [0.1 + r2.gauss(0, 0.1) for _ in range(30)]
    lo, hi, _ = bootstrap(units, mean, 3)
    check("bootstrap CI covers the sample mean (%.3f in [%.3f, %.3f])" % (mean(units), lo, hi),
          lo < mean(units) < hi)
    check("lift stat", abs(lift_stat([(2, 4, 5, 20)]) - 2.0) < 1e-12)
    check("cz formatting", cz(1234.5, 1) == "1" + NB + "234,5" and cz(-0.05, 2) == "−0,05")
    check("formations 30", len(formation_dates()) == 30)
    t = _ts("2024-10-01")
    st = lattice(t)
    check("lattice: t at I0, +13w = +91 d, +26w = +182 d",
          st[I0] == t and st[I0 + 13] - t == 91 * DAY and st[I0 + 26] - t == 182 * DAY)
    offs = [min(abs(s - (t - k * 182.0 / 6 * DAY)) for s in st) / DAY for k in range(7)]
    check("Síla points within 3 d of a stamp (max %.2f d)" % max(offs), max(offs) <= 3)
    print("SELFTEST", "PASSED" if ok else "FAILED")
    return ok


# ------------------------------------------------------------------ main
def prereg_lock():
    h = hashlib.sha256(json.dumps(PREREG, sort_keys=True).encode("utf-8")).hexdigest()
    p = os.path.join(CACHE, "prereg.lock")
    os.makedirs(CACHE, exist_ok=True)
    if not os.path.exists(p):
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"sha256": h, "locked_utc": dt.datetime.now(UTC).isoformat(timespec="seconds")}, f)
        log("PREREG uzamčen: %s" % h)
        return h, False, h
    with open(p, encoding="utf-8") as f:
        locked = json.load(f)["sha256"]
    if locked != h:
        log("!!! PREREG SE ZMĚNIL od uzamčení (%s -> %s)" % (locked[:12], h[:12]))
    return h, locked != h, locked


def main():
    t_start = time.time()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    prereg_hash, prereg_changed, prereg_locked = prereg_lock()

    collector, themes = import_screener()
    provenance = {"collector_sha256": sha256_file(os.path.join(HERE, "collector.py")),
                  "themes_sha256": sha256_file(os.path.join(HERE, "themes.py"))}
    counter = Counter()
    ctx = make_ctx(collector, counter)

    collector.fetch_bulk(ctx)
    groups, n_no_token, doublecounted = collector.group_apps(ctx, 0)
    groups.sort(key=lambda g: g["key"])
    log("skupiny s tokenem: %d (bez tokenu %d, double-counted %d)"
        % (len(groups), n_no_token, len(doublecounted)))
    listed = listed_at_map(ctx, collector, groups)
    log("listedAt: %d známých, %d neznámých"
        % (sum(1 for v in listed.values() if v[0]), sum(1 for v in listed.values() if not v[0])))

    hist, _used = fetch_histories(ctx, collector, groups)
    hist_ts = {k: [p[0] for p in s] for k, s in hist.items()}
    no_hist = sum(1 for k in hist if not hist[k])

    forms = formation_dates()
    cands_by_f = {}
    for t in forms:
        cands = []
        for g in groups:
            s, ts = hist.get(g["key"]), hist_ts.get(g["key"])
            if not s:
                continue
            j = bisect.bisect_right(ts, t)
            if not j:
                continue
            lo = bisect.bisect_right(ts, t - 30 * DAY)
            rev30 = sum(v for _, v in s[lo:j])
            if rev30 >= MIN_REV:
                cands.append((g, s[:j], rev30))
        cands_by_f[t] = cands
    all_ids = sorted({g["gecko_id"] for c in cands_by_f.values() for g, _, _ in c})
    log("kandidáti (rev30d(t) >= $100K): %d tokenů přes %d formací" % (len(all_ids), len(forms)))

    cg_store = fetch_mcaps(ctx, themes, all_ids, counter)
    mcaps = cg_store["rows"]

    variants = {"primary": {"listed": True, "clean": False},
                "no_listed": {"listed": False, "clean": False},
                "cleaned": {"listed": True, "clean": True}}
    by_f = {v: {} for v in variants}
    meta = {v: {} for v in variants}
    anomalies_all = []
    for i, t in enumerate(forms, 1):
        cands = cands_by_f[t]
        ids = sorted({g["gecko_id"] for g, _, _ in cands} | {"bitcoin"})
        stamps = lattice(t)
        grid = themes.fetch_grid(ctx, ids, stamps)
        btc = themes.btc_row(ctx, stamps, grid)
        if not btc[I0]:
            raise RuntimeError("BTC price missing at formation %s" % day(t))
        anomalies = []
        cleaned = {gid: themes.clean_row(gid, row, anomalies) for gid, row in grid.items()
                   if gid != "bitcoin"}
        for a in anomalies:
            a["t"] = t
        anomalies_all.extend(anomalies)
        raw = {gid: row for gid, row in grid.items() if gid != "bitcoin"}
        for v, cfg in variants.items():
            recs, m = build_rows(t, cands, cleaned if cfg["clean"] else raw, btc, stamps, listed,
                                 mcaps, collector, themes, cfg["listed"])
            m["n_cands"] = len(cands)
            m["n_priced"] = sum(1 for g, _, _ in cands if (raw.get(g["gecko_id"]) or [None] * 53)[I0])
            m["btc3"] = (btc[I0 + 13] / btc[I0] - 1.0) if len(btc) > I0 + 13 and btc[I0 + 13] else None
            by_f[v][t], meta[v][t] = recs, m
        p = by_f["primary"][t]
        log("formace %s (%d/%d): kandidátů %d, s cenou %d, vesmír %d, hodnotitelných %d, "
            "prověřených %d, benchmark %s %s"
            % (mon(t), i, len(forms), len(cands), meta["primary"][t]["n_priced"], len(p),
               sum(1 for r in p if r["rankable"]), sum(1 for r in p if r["trusted"]),
               meta["primary"][t]["bench_label"], cz(meta["primary"][t]["bench"] or 0, 1)))

    # ---------------------------------------------------------- statistics
    res = {}
    for v in variants:
        h1 = ic_test(by_f[v], forms, "3M", block=3)
        h2 = h2_test(by_f[v], forms)
        res[v] = {"h1": h1, "h2": h2, "verdict": judge(h1, h2)}
        if v != "cleaned":
            res[v]["h3"] = h3_test(by_f[v], forms, "h3")
            res[v]["h3_notheme"] = h3_test(by_f[v], forms, "h3_notheme")
    h1d = ic_test(by_f["primary"], forms, "3M", drop_dead=True, block=3)
    h2d = h2_test(by_f["primary"], forms, drop_dead=True)
    res["dead_excluded"] = {"h1": h1d, "h2": h2d, "verdict": judge(h1d, h2d)}

    P = by_f["primary"]
    desc = []
    for label, sig, tr in (("Potenciál (všechny hodnotitelné řádky)", "potential_raw", False),
                           ("Potenciál (prověřené = H1)", "potential_raw", True),
                           ("Síla 6M", "sila", True), ("Růst 6M", "g6m", True),
                           ("Velikost ln(mcap), čeká se záporné znaménko", "ln_mcap", True),
                           ("Cenová hybnost 3M vs BTC do t", "mom3m", True)):
        a = ic_test(P, forms, "3M", sig, tr, block=3)
        b = ic_test(P, forms, "6M", sig, tr, block=6)
        q = q51_test(P, forms, sig, tr)
        desc.append({"label": label, "signal": sig, "ic3": a, "ic6": b, "q51": q})

    br_all = base_rates(P, forms, lambda rs: [r for r in rs if r["out"]["6M"]])
    br_tr = base_rates(P, forms, lambda rs: h_rows(rs, "6M"))

    # Q4 2024
    tq = _ts("2024-10-01")
    qrecs = P[tq]
    q_tr = sorted([r for r in qrecs if r["trusted"] and r["potential_raw"] is not None],
                  key=lambda r: (-r["potential_raw"], r["key"]))
    q_top = q_tr[:15]
    q_uni = [r for r in qrecs if r["out"]["3M"]]
    q_win = sorted(q_uni, key=lambda r: -r["out"]["3M"]["mult"])[:10]
    q_top_med = median([r["out"]["3M"]["mult"] for r in q_top if r["out"]["3M"]])
    q_uni_med = median([r["out"]["3M"]["mult"] for r in q_uni])
    tr_rank = {r["key"]: i for i, r in enumerate(q_tr, 1)}
    n_ranked_q = meta["primary"][tq]["n_ranked"]
    if q_win:
        w = q_win[0]
        if w["rank"] is None:
            where = "nebyl v žebříčku (%s)" % ("bez dnešního mcap" if not w["rankable"] else "bez Potenciálu")
        else:
            where = "byl %d. z %d podle Potenciálu" % (w["rank"], n_ranked_q)
            where += (", mezi prověřenými %d. z %d" % (tr_rank[w["key"]], len(q_tr))
                      if w["key"] in tr_rank else ", " + status(w))
        q_note = "Největší vítěz Q4 2024 %s (%s) %s." % (w["name"], xmul(w["out"]["3M"]["mult"], 1), where)
    else:
        q_note = "—"

    # counts
    lost = {t: sum(1 for r in P[t] if not r["rankable"]) for t in forms}
    unknown_listed = {t: sum(1 for r in P[t] if r["listed_at"] is None) for t in forms}
    runtime = time.time() - t_start
    # every cached file is one successful network response; this is what the
    # fetching run cost (without its 429 retries), whatever this run cost
    n_cached = sum(len(fs) for _, _, fs in os.walk(os.path.join(CACHE, "http")))
    counter.c["cached_responses"] = n_cached
    counter.c["coingecko_batches_total"] = -(-len(cg_store["rows"]) // 200)
    hl_g = next((g for g in groups if (g.get("name") or "").strip().lower() == "hyperliquid"), None)
    hl_s = hist.get(hl_g["key"]) if hl_g else None
    first_hl = next((t for t in forms if meta["primary"][t]["bench_label"] == "Hyperliquid"), None)
    counter.notes = {"hl_rev_start": hl_s[0][0] if hl_s else None, "first_hl": first_hl}
    with open(os.path.join(CACHE, "runs.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps({"utc": dt.datetime.now(UTC).isoformat(timespec="seconds"),
                            "runtime_s": round(runtime), "prereg_hash": prereg_hash,
                            **counter.c}) + "\n")

    summary = build_summary(prereg_hash, prereg_changed, res, br_all, br_tr, q_top_med, q_uni_med,
                            q_note, forms, P, lost, counter, runtime, provenance, cg_store)
    with open(SUMMARY, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, separators=(",", ":"))
    html_out = build_report(summary, res, desc, br_all, br_tr, q_top, q_win, q_top_med, q_uni_med,
                            q_note, tr_rank, n_ranked_q, len(q_tr), forms, P, meta, lost,
                            unknown_listed, anomalies_all, counter, runtime, provenance,
                            prereg_hash, prereg_changed, prereg_locked, cg_store, groups,
                            n_no_token, doublecounted, listed, no_hist)
    with open(REPORT, "w", encoding="utf-8") as f:
        f.write(html_out)

    # rows for anyone who wants to audit a number (no series, just the records)
    with gzip.open(os.path.join(CACHE, "rows_primary.json.gz"), "wt", encoding="utf-8") as f:
        json.dump({str(t): P[t] for t in forms}, f, ensure_ascii=False, default=str)

    log("HOTOVO za %.0f s — verdikt %s | H1 IC %s %s | H2 lift %s %s | HTTP %d, cache hit %d"
        % (runtime, res["primary"]["verdict"], cz(res["primary"]["h1"]["ic_mean"], 3),
           ci(res["primary"]["h1"]["ci90"]), cz(res["primary"]["h2"]["lift"], 2),
           ci(res["primary"]["h2"]["ci90"], d=2), counter.c.get("http_requests", 0),
           counter.c.get("cache_hits", 0)))


def r3(x, d=4):
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return None
    return round(x, d)


def build_summary(prereg_hash, prereg_changed, res, br_all, br_tr, q_top_med, q_uni_med, q_note,
                  forms, P, lost, counter, runtime, provenance, cg_store):
    pr = res["primary"]
    h1, h2, h3, h3n = pr["h1"], pr["h2"], pr["h3"], pr["h3_notheme"]

    def brs(b):
        return {k: {"p": r3(v["p"]), "ci90": [r3(v["ci90"][0]), r3(v["ci90"][1])], "n": v["n"]}
                for k, v in b.items()}
    return {
        "generated_at": dt.datetime.now(UTC).isoformat(timespec="seconds"),
        "prereg_hash": prereg_hash, "prereg_changed": prereg_changed,
        "verdict": pr["verdict"],
        "verdict_text": VERDICT_TEXT[pr["verdict"]],
        "h1": {"ic_mean": r3(h1["ic_mean"]), "ci90": [r3(h1["ci90"][0]), r3(h1["ci90"][1])],
               "n_formations": h1["n_formations"], "pass": h1["pass"],
               "text": "IC %s, 90%% CI %s" % (cz(h1["ic_mean"], 3), ci(h1["ci90"]))},
        "h2": {"lift": r3(h2["lift"], 3), "ci90": [r3(h2["ci90"][0], 3), r3(h2["ci90"][1], 3)],
               "base_rate": r3(h2["base_rate"]), "top_rate": r3(h2["top_rate"]), "pass": h2["pass"],
               "text": "lift %s, 90%% CI %s" % (cz(h2["lift"], 2), ci(h2["ci90"], d=2))},
        "h3": {"diff_median": r3(h3["diff_median"]), "ci90": [r3(h3["ci90"][0]), r3(h3["ci90"][1])],
               "n_pass_rows": h3["n_pass_rows"], "pass": h3["pass"],
               "without_theme_gate": {"diff_median": r3(h3n["diff_median"]),
                                      "ci90": [r3(h3n["ci90"][0]), r3(h3n["ci90"][1])],
                                      "n_pass_rows": h3n["n_pass_rows"], "pass": h3n["pass"]},
               "n_pass_tokens": h3["n_pass_tokens"]},
        "base_rates": {"all": brs(br_all), "trusted": brs(br_tr)},
        "q4_2024": {"top_median_multiple": r3(q_top_med, 3),
                    "universe_median_multiple": r3(q_uni_med, 3),
                    "best_winner_rank_note": q_note},
        "sensitivity": {
            "no_listed_filter": {"verdict": res["no_listed"]["verdict"],
                                 "ic_mean": r3(res["no_listed"]["h1"]["ic_mean"]),
                                 "lift": r3(res["no_listed"]["h2"]["lift"], 3)},
            "dead_excluded": {"verdict": res["dead_excluded"]["verdict"],
                              "ic_mean": r3(res["dead_excluded"]["h1"]["ic_mean"]),
                              "lift": r3(res["dead_excluded"]["h2"]["lift"], 3)},
            "cleaned_prices": {"verdict": res["cleaned"]["verdict"],
                               "ic_mean": r3(res["cleaned"]["h1"]["ic_mean"]),
                               "lift": r3(res["cleaned"]["h2"]["lift"], 3)}},
        "counts": {"formations": len(forms),
                   "rows_per_formation_median": median([len(P[t]) for t in forms]),
                   "lost_no_mcap_total": sum(lost.values()),
                   "http_requests_this_run": counter.c.get("http_requests", 0),
                   "cached_responses": counter.c.get("cached_responses", 0),
                   "coingecko_batches": counter.c.get("coingecko_batches_total", 0),
                   "runtime_s": round(runtime)},
        "mcap_now_date": cg_store.get("fetched_utc"),
        "provenance": {k: v[:16] for k, v in provenance.items()},
    }


VERDICT_TEXT = {
    "FUNGUJE": "Potenciál historicky předpovídal výnos vs BTC (H1 i H2 prošly).",
    "NEPRŮKAZNÉ": "Odhady vyšly na kladné straně, ale intervaly nevylučují nulu — nelze tvrdit, že to funguje.",
    "NEFUNGUJE": "Historicky nefungovalo — Potenciál vítěze nepředpovídal.",
}
VERDICT_CLASS = {"FUNGUJE": "ok", "NEPRŮKAZNÉ": "mid", "NEFUNGUJE": "bad"}


# ------------------------------------------------------------------ report
def build_report(summary, res, desc, br_all, br_tr, q_top, q_win, q_top_med, q_uni_med, q_note,
                 tr_rank, n_ranked_q, n_trusted_q, forms, P, meta, lost, unknown_listed,
                 anomalies, counter, runtime, provenance, prereg_hash, prereg_changed,
                 prereg_locked, cg_store, groups, n_no_token, doublecounted, listed, no_hist):
    esc = html.escape
    pr = res["primary"]
    h1, h2, h3, h3n = pr["h1"], pr["h2"], pr["h3"], pr["h3_notheme"]
    v = pr["verdict"]
    out = []
    w = out.append

    def yes(b):
        return '<span class="pass">PROŠLO</span>' if b else '<span class="fail">NEPROŠLO</span>'

    w("""<!doctype html><html lang="cs"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Backtest Potenciálu</title>
<style>
:root{--bg:#f7f5f2;--fg:#1d1b19;--mut:#6b655e;--line:#ddd6cc;--card:#fff;--blue:#2f6fd0;--coral:#d8583f;--gold:#b8860b}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){--bg:#15130f;--fg:#ece6dc;--mut:#9d958a;--line:#332e28;--card:#1d1a16;--blue:#6ea0ff;--coral:#ff8a70;--gold:#e0b44a}}
:root[data-theme="dark"]{--bg:#15130f;--fg:#ece6dc;--mut:#9d958a;--line:#332e28;--card:#1d1a16;--blue:#6ea0ff;--coral:#ff8a70;--gold:#e0b44a}
body{background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif;margin:0;padding:24px 16px}
main{max-width:1040px;margin:0 auto}
h1{font-size:26px;margin:0 0 4px}h2{font-size:19px;margin:34px 0 8px;border-bottom:1px solid var(--line);padding-bottom:4px}
h3{font-size:16px;margin:20px 0 6px}
p,li{max-width:80ch}.mut{color:var(--mut)}
.banner{border-radius:10px;padding:16px 18px;margin:18px 0;border:2px solid}
.banner.ok{border-color:var(--blue)}.banner.mid{border-color:var(--gold)}.banner.bad{border-color:var(--coral)}
.banner .v{font-size:28px;font-weight:700;letter-spacing:.02em}
.banner.ok .v{color:var(--blue)}.banner.mid .v{color:var(--gold)}.banner.bad .v{color:var(--coral)}
.warn{border:2px solid var(--coral);border-radius:10px;padding:12px 16px;margin:14px 0;color:var(--coral);font-weight:600}
.tw{overflow-x:auto;margin:8px 0 14px}
table{border-collapse:collapse;background:var(--card);font-size:13.5px;min-width:100%}
th,td{border:1px solid var(--line);padding:5px 8px;text-align:right;white-space:nowrap}
th{background:var(--bg);font-weight:600}td.l,th.l{text-align:left;white-space:normal}
.pass{color:var(--blue);font-weight:700}.fail{color:var(--coral);font-weight:700}
code,pre{font-family:ui-monospace,Consolas,monospace;font-size:12.5px}
pre{background:var(--card);border:1px solid var(--line);padding:10px;overflow-x:auto;white-space:pre-wrap}
details{margin:10px 0}summary{cursor:pointer;font-weight:600}
</style></head><body><main>""")
    w("<h1>Backtest Potenciálu — předregistrovaný, k datu formace</h1>")
    w('<p class="mut">Vygenerováno %s UTC · formace %s–%s (%d) · data do %s · mcap dnes z CoinGecka %s</p>'
      % (summary["generated_at"][:16].replace("T", " "), mon(forms[0]), mon(forms[-1]), len(forms),
         day(DATA_END), esc(str(cg_store.get("fetched_utc")))))
    if prereg_changed:
        w('<div class="warn">POZOR: předregistrace (PREREG) se od uzamčení změnila. Uzamčený hash %s, '
          'současný %s. Výsledky níže neodpovídají původně předregistrovanému plánu.</div>'
          % (prereg_locked[:16], prereg_hash[:16]))
    w('<div class="banner %s"><div class="v">%s</div><div>%s</div>'
      '<div class="mut" style="margin-top:6px">H1 %s · H2 %s · H3 (sekundární) %s</div></div>'
      % (VERDICT_CLASS[v], v, esc(VERDICT_TEXT[v]), yes(h1["pass"]), yes(h2["pass"]), yes(h3["pass"])))

    w("<p>Otázka: kdyby sis na začátku každého měsíce od ledna 2024 koupil to, co screener řadil "
      "nahoru podle Potenciálu, porazilo by to BTC? Každý řádek je spočítaný tak, jak by ho "
      "screener ukázal tehdy: revenue uříznutá k datu formace, stejné funkce z collector.py, "
      "market cap = dnešní oběžná zásoba × tehdejší cena. Hypotézy a prahy byly zapsány a "
      "zahashovány před prvním během.</p>")

    # ---- primary hypotheses
    w("<h2>Primární hypotézy</h2>")
    w('<div class="tw"><table><tr><th class="l">Hypotéza</th><th>Odhad</th><th>90% CI</th>'
      '<th>Práh</th><th>Formací</th><th>Výsledek</th></tr>')
    w('<tr><td class="l"><b>H1</b> — průměrná měsíční Spearmanova korelace (IC) Potenciálu s výnosem '
      'vs BTC za 3 měsíce, jen prověřené řádky</td><td>%s</td><td>%s</td><td>IC ≥ 0,05 a dolní mez &gt; 0</td>'
      '<td>%d</td><td>%s</td></tr>' % (cz(h1["ic_mean"], 3), ci(h1["ci90"]), h1["n_formations"], yes(h1["pass"])))
    w('<tr><td class="l"><b>H2</b> — horní kvintil Potenciálu: podíl řádků s ≥ 3× za 6 měsíců '
      'vůči všem prověřeným (lift)</td><td>%s</td><td>%s</td><td>lift ≥ 1,5 a dolní mez &gt; 1</td>'
      '<td>%d</td><td>%s</td></tr>' % (cz(h2["lift"], 2), ci(h2["ci90"], d=2), h2["n_formations"], yes(h2["pass"])))
    w("</table></div>")
    w("<p>H1: %d řádků-formací, bootstrap v blocích po 3 formacích (B = 5 000). "
      "H2: horní kvintil %d z %d trefilo ≥ 3× (%s), všichni prověření %d z %d (%s); bloky po 6 formacích. "
      "Zásahů ≥ 3× je tak málo, že část převzorkování nemá v horním kvintilu žádný (lift 0) — "
      "proto tak široký interval.</p>"
      % (h1["n_rows"], h2["top_hits"], h2["top_n"], pct(h2["top_rate"]), h2["all_hits"], h2["all_n"],
         pct(h2["base_rate"])))
    w("<p>Obě primární hypotézy mají odhad na kladné straně, ale pod předregistrovaným prahem "
      "(IC %s &lt; 0,05; lift %s &lt; 1,5) a oba intervaly zasahují nulový efekt.</p>"
      % (cz(h1["ic_mean"], 3), cz(h2["lift"], 2)) if v == "NEPRŮKAZNÉ" else "")

    # ---- H3
    w("<h2>H3 (sekundární) — rekonstruovatelné brány „Pro degena“</h2>")
    w("<p>Brány v čase t: rev30d ≥ $100K; prověřený; Potenciál ≥ 2,5×; Test 30× na velikost "
      "(30 × mcap nesmí přerůst největšího jiného tokenu stejné kategorie DeFiLlamy; lídr kategorie "
      "= „bez srovnání“ = neprošel, protože záložní koš tématu nejde zpětně sestavit); byznys "
      "(fáze není Pokles/Stagnace a Růst 6M &gt; 0); téma (řádek patří do jednoho z 11 témat). "
      "<b>Bránu likvidity ani tier tématu v čase t rekonstruovat nejde</b> — nejsou použity.</p>")
    w('<div class="tw"><table><tr><th class="l">Varianta</th><th>Prošlo řádků (různých tokenů)</th><th>Medián prošlých</th>'
      '<th>Medián ostatních</th><th>Rozdíl mediánů (log)</th><th>90% CI</th><th>Výsledek</th></tr>')
    for lab, hh in (("s bránou tématu (H3)", h3), ("bez brány tématu", h3n)):
        w('<tr><td class="l">%s</td><td>%d (%d)</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>'
          % (lab, hh["n_pass_rows"], hh["n_pass_tokens"], rel_pct(hh["median_pass"]), rel_pct(hh["median_rest"]),
             cz(hh["diff_median"], 3, True), ci(hh["ci90"]), yes(hh["pass"])))
    w("</table></div><p class=\"mut\">Výnos = výnos vs BTC za 6 měsíců, mediány převedené na %%. "
      "Ostatní = všechny ostatní hodnotitelné řádky téže formace. Formací s aspoň jedním prošlým: %d.</p>"
      % h3["n_formations_with_pass"])

    # ---- base rates
    w("<h2>Base rates — jak často coin za 6 měsíců udělá násobek</h2>")
    w('<div class="tw"><table><tr><th class="l">Skupina</th><th>n</th><th>P(≥ 3×)</th><th>90% CI</th>'
      '<th>P(≥ 5×)</th><th>90% CI</th><th>P(≥ 10×)</th><th>90% CI</th></tr>')
    for lab, b in (("Celý vesmír (rev30d ≥ $100K, cena v t; i bez dnešního mcap)", br_all),
                   ("Prověřené řádky s Potenciálem", br_tr)):
        w('<tr><td class="l">%s</td><td>%d</td>' % (lab, b["p3"]["n"]))
        for k in ("p3", "p5", "p10"):
            w("<td>%s <span class=\"mut\">(%d)</span></td><td>%s</td>"
              % (pct(b[k]["p"]), b[k]["k"], ci(b[k]["ci90"], pct, 1)))
        w("</tr>")
    w("</table></div><p class=\"mut\">Sloučeno přes formace; sousední 6M okna se z 5/6 překrývají, "
      "takže Wilsonovy intervaly (předpokládají nezávislé řádky) jsou příliš úzké.</p>")

    # ---- descriptive
    w("<h2>Popisné signály (bez verdiktu)</h2>")
    w('<div class="tw"><table><tr><th class="l">Signál</th><th>IC 3M</th><th>90% CI</th><th>form.</th>'
      '<th>IC 6M</th><th>90% CI</th><th>Q5 − Q1 (3M)</th><th>90% CI</th></tr>')
    for d_ in desc:
        w('<tr><td class="l">%s</td><td>%s</td><td>%s</td><td>%d</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>'
          % (esc(d_["label"]), cz(d_["ic3"]["ic_mean"], 3), ci(d_["ic3"]["ci90"]), d_["ic3"]["n_formations"],
             cz(d_["ic6"]["ic_mean"], 3), ci(d_["ic6"]["ci90"]),
             pct(d_["q51"]["q51"], 1, True), ci(d_["q51"]["ci90"], lambda x, d: pct(x, 1, True))))
    w("</table></div><p class=\"mut\">IC = Spearmanova korelace signálu s výnosem vs BTC, průměr přes formace. "
      "Q5 − Q1 = medián relativního výnosu (vs BTC) horního kvintilu minus dolního, průměr přes formace. "
      "Podíl pro držitele (holders_share) přeskočen — historie dailyHoldersRevenue se nestahovala.</p>")

    # ---- Q4 2024
    w("<h2>Zvláštní případ: formace 1. 10. 2024 → 31. 12. 2024 (poslední skutečná altová rally)</h2>")
    w("<p>Medián 3M násobku: top 15 prověřených podle Potenciálu <b>%s</b>, celý vesmír <b>%s</b>. %s</p>"
      % (xmul(q_top_med), xmul(q_uni_med), esc(q_note)))
    w("<h3>Top 15 prověřených podle Potenciálu</h3>")
    w('<div class="tw"><table><tr><th>#</th><th class="l">Projekt</th><th class="l">Kategorie</th>'
      '<th>Potenciál</th><th>mcap(t)</th><th>3M násobek</th><th>vs BTC</th></tr>')
    for i, r in enumerate(q_top, 1):
        o = r["out"]["3M"]
        w('<tr><td>%d</td><td class="l">%s</td><td class="l">%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>'
          % (i, esc(r["name"]), esc(r["category"] or ""), xmul(r["potential_raw"], 1), usd(r["mcap_t"]),
             xmul(o["mult"]) if o else "—", rel_pct(o["excess"]) if o else "—"))
    w("</table></div>")
    w("<h3>10 největších vítězů celého vesmíru za to čtvrtletí</h3>")
    w('<div class="tw"><table><tr><th class="l">Projekt</th><th>3M násobek</th><th>vs BTC</th>'
      '<th>Pořadí podle Potenciálu</th><th>Potenciál</th><th class="l">Status v t</th></tr>')
    for r in q_win:
        o = r["out"]["3M"]
        rk = ("%d. z %d" % (r["rank"], n_ranked_q)) if r["rank"] else "—"
        if r["key"] in tr_rank:
            rk += " (prověř. %d. z %d)" % (tr_rank[r["key"]], n_trusted_q)
        w('<tr><td class="l">%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td class="l">%s</td></tr>'
          % (esc(r["name"]), xmul(o["mult"]), rel_pct(o["excess"]), rk, xmul(r["potential_raw"], 1),
             esc(status(r))))
    w("</table></div>")

    # ---- sensitivity
    w("<h2>Citlivostní varianty</h2>")
    w('<div class="tw"><table><tr><th class="l">Varianta</th><th>H1 IC</th><th>90% CI</th><th>H2 lift</th>'
      '<th>90% CI</th><th>H3 rozdíl</th><th>90% CI</th><th>Verdikt</th></tr>')
    for lab, key in (("Primární (jen projekty, které DeFiLlama v t znala)", "primary"),
                     ("Bez filtru listedAt", "no_listed"),
                     ("Bez řádků, jejichž cena po t zmizela (−100 %)", "dead_excluded"),
                     ("Ceny očištěné themes.clean_row", "cleaned")):
        rr = res[key]
        hh = rr.get("h3")
        w('<tr><td class="l">%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td><b>%s</b></td></tr>'
          % (lab, cz(rr["h1"]["ic_mean"], 3), ci(rr["h1"]["ci90"]), cz(rr["h2"]["lift"], 2),
             ci(rr["h2"]["ci90"], d=2), cz(hh["diff_median"], 3, True) if hh else "—",
             ci(hh["ci90"]) if hh else "—", rr["verdict"]))
    rows6 = [r["out"]["6M"] for t in forms for r in P[t] if r["out"]["6M"]]
    early = [o["lag_w"] for o in rows6 if not o["dead"] and o["lag_w"]]
    w("</table></div><p class=\"mut\">Žádný řádek neztratil po t cenu úplně (%d „mrtvých“ ze %d 6M "
      "výsledků), proto je varianta bez nich totožná s primární. %d výsledků použilo poslední týdenní "
      "cenu v okně (max. %d týdnů před koncem). Coin stažený uprostřed okna si tak drží poslední cenu "
      "místo nuly, což nejhorší řádky spíš nadhodnocuje. Očištění cen (%d anomálií) výsledky H1/H2 %s.</p>"
      % (sum(1 for o in rows6 if o["dead"]), len(rows6), len(early), max(early) if early else 0,
         len(anomalies),
         "nezměnilo" if (res["cleaned"]["h1"]["ic_mean"] == pr["h1"]["ic_mean"]
                         and res["cleaned"]["h2"]["lift"] == pr["h2"]["lift"]) else "posunulo (viz tabulka)"))

    # ---- per formation
    w("<h2>Po formacích (primární vesmír)</h2>")
    w('<div class="tw"><table><tr><th>Formace</th><th>Kandidátů</th><th>Vesmír</th><th>Bez dnešního mcap</th>'
      '<th>listedAt neznámé</th><th>Prověřených</th><th class="l">Benchmark (P/S)</th><th>IC 3M</th>'
      '<th>Top kvintil ≥ 3× (6M)</th><th>Prošlo H3</th><th>BTC 3M</th></tr>')
    per1 = {p["t"]: p for p in h1["per"]}
    per2 = {p["t"]: p for p in h2["per"]}
    for t in forms:
        m = meta["primary"][t]
        p1, p2 = per1.get(t), per2.get(t)
        th = ("%d/%d" % (p2["top_hits"], p2["top_n"])) if p2 and p2.get("top_hits") is not None else "—"
        rs = P[t]
        n_tr = sum(1 for r in rs if r["trusted"] and r["potential_raw"] is not None)
        h3n_ = sum(1 for r in rs if r["h3"])
        w('<tr><td>%s</td><td>%d</td><td>%d</td><td>%d</td><td>%d</td><td>%d</td><td class="l">%s %s</td>'
          '<td>%s</td><td>%s</td><td>%d</td><td>%s</td></tr>'
          % (mon(t), m["n_cands"], len(rs), lost[t], unknown_listed[t], n_tr, m["bench_label"],
             cz(m["bench"], 1) if m["bench"] else "—",
             cz(p1["ic"], 3) if p1 and p1["ic"] is not None else ("—" if not p1 else "n=%d" % p1["n"]),
             th, h3n_, pct(m.get("btc3"), 1, True)))
    w("</table></div>")

    # ---- caveats
    w("<h2>Výhrady — čtěte před jakýmkoli závěrem</h2><ol>")
    cav = [
        "<b>Market cap je proxy s konstantní nabídkou.</b> mcap(t) = dnešní oběžná zásoba × cena v t. "
        "Token, který od t ředil (unlocky, emise), měl v t ve skutečnosti <i>menší</i> oběžnou zásobu, "
        "takže proxy jeho tehdejší mcap <i>nadhodnocuje</i> — v backtestu vypadá dražší (nižší Potenciál), "
        "než ho screener tehdy ukázal. Tokeny se zpětnými odkupy/pálením naopak vypadají levnější. "
        "Protože ředící tokeny mívají slabší výnosy, tahle chyba spíš <i>pomáhá</i> H1/H2 (ředící slabochy "
        "tlačí dolů v žebříčku). Zadání uvádělo opačný směr — viz odchylky.",
        "<b>Revenue DeFiLlamy se zpětně doplňuje a přepočítává.</b> Adaptéry přidané později dostávají "
        "historii zpětně, metodiky se mění. Filtr listedAt (datum zalistování protokolu na DeFiLlamě, "
        "ne datum vzniku fee adaptéru) to řeší jen částečně.",
        "<b>Dnešní kategorie a mapování na CoinGecko.</b> Kategorie, rodičovské skupiny i gecko_id jsou "
        "z dneška. Projekt, který token v t ještě neměl, vypadne díky požadavku na cenu v t; jiné "
        "přejmenování či překategorizování ale backtest nevidí.",
        "<b>Jen jedna skutečná altová rally</b> (Q4 2024), takže pro tento režim je n ≈ 1. "
        "Výsledek o „altseason“ je anekdota, ne statistika.",
        "<b>Překrývající se okna.</b> 3M okna sousedních formací sdílejí 2/3 doby, 6M okna 5/6. "
        "Blokový bootstrap to zčásti bere v úvahu; Wilsonovy intervaly u base rates ne (jsou příliš úzké).",
        "<b>Brána likvidity a tier tématu v čase t nejdou rekonstruovat</b>; H3 je bez nich a lídr "
        "kategorie v Testu 30× neprošel (záložní koš tématu nejde sestavit zpětně).",
        "<b>Mrtvé tokeny bez dnešního mcap</b> nejdou ohodnotit (nelze odvodit zásobu), do žebříčků "
        "nevstupují, jen do base rates. Celkem %d řádků-formací (medián %s na formaci). Protože jde o "
        "tokeny, které spíš umřely, jejich vyřazení z žebříčků výsledky H1/H2 spíš <i>zlepšuje</i>."
        % (sum(lost.values()), cz(median(list(lost.values())), 0)),
        "<b>Revenue k datu t včetně bodu ts = t</b> (podle zadání): denní bod s časem 00:00 dne t pokrývá "
        "den t, tj. jeden den dopředu. U 91/182denních horizontů zanedbatelné.",
        "<b>Ceny v týdenní mřížce.</b> Když koncová cena chybí, bere se poslední týdenní cena v okně "
        "(až o 6 dní dřív) a BTC ke stejnému dni. Body Síly 6M jsou nejbližší týdenní ceny (≤ 2,33 dne "
        "od přesného data, tolerance funkce strength je 3 dny).",
        "<b>Seznam protokolů je dnešní.</b> Obsahuje i mrtvé adaptéry (proto group_apps s prahem 0), "
        "ale protokoly, které DeFiLlama úplně smazala, v datech nejsou.",
        "<b>Benchmark se mění.</b> Revenue Hyperliquidu má DeFiLlama až od %s (token od 29. 11. 2024), "
        "takže formace před %s mají benchmark medián P/S vesmíru, od ní dál P/S Hyperliquidu. Pořadí uvnitř "
        "formace (H1, H2) to neovlivní, práh brány Potenciál ≥ 2,5 v H3 ano."
        % (day(counter.notes["hl_rev_start"]) if counter.notes.get("hl_rev_start") else "—",
           mon(counter.notes["first_hl"]) if counter.notes.get("first_hl") else "—"),
    ]
    for c in cav:
        w("<li>%s</li>" % c)
    w("</ol>")

    w("<h2>Odchylky od zadání</h2><p class=\"mut\">Body 1 a 3–7 jsou zapsané v PREREG před prvním "
      "během; bod 2 je oprava textu zadání, bod 8 provozní událost.</p><ol>")
    for c in (
        "Řádek v čase t dostal navíc <code>primary = 'rev'</code>. Collector ho nastavuje každé appce "
        "a <code>is_young</code> ho čte; bez něj by se „nový“ nikdy nerozsvítil a prověřené = jen spolehlivé.",
        "Směr zkreslení proxy mcap je opačný, než uvádělo zadání: ředící tokeny vypadají v minulosti "
        "<i>dražší</i>, ne levnější (viz výhrada 1).",
        "Práh rev30d ≥ $100K se měří v kalendářním okně (t − 30 d, t], ne jako rev30d z app_measures "
        "(to se měří od posledního bodu řady) — jinak by mrtvý adaptér prošel se svým posledním dobrým měsícem.",
        "Ceny: themes.fetch_grid umí jen týdenní mřížku, proto je mřížka ukotvená v t (t ± 26 týdnů): "
        "91 a 182 dní padnou přesně na razítko, „poslední dostupná cena v okně“ je týdenní.",
        "Test 30×: srovnávací řádky = hodnotitelné řádky téhož vesmíru (rev30d ≥ $100K); živý screener "
        "srovnává se všemi appkami nad $10K/30d.",
        "Doplněná rozhodnutí: min. 10 řádků na formaci pro IC a kvintily; kvintil = ceil(n/5); H3 bootstrap "
        "v blocích po 6; jeden token = jeden řádek (sloučení podle gecko_id, dopad 0); Q5 − Q1 v relativním "
        "výnosu, aby −100 % nebylo −∞; navíc citlivostní varianta s očištěnými cenami.",
        "holders_share přeskočen (historie dailyHoldersRevenue se nestahovala).",
        "První běh spadl až při psaní reportu (chyba formátování znaku %); opraveno a přepočteno z cache "
        "— výpočet je deterministický, PREREG se neměnil.",
    ):
        w("<li>%s</li>" % c)
    w("</ol>")

    # ---- provenance
    w("<h2>Původ dat a běh</h2><ul>")
    w("<li>Skupin s tokenem z group_apps(ctx, 0): %d (bez tokenu vyřazeno %d, double-counted %d); "
      "bez jakékoli revenue historie %d.</li>" % (len(groups), n_no_token, len(doublecounted), no_hist))
    w("<li>listedAt: známé u %d skupin, neznámé u %d (zahrnuty a označeny).</li>"
      % (sum(1 for x in listed.values() if x[0]), sum(1 for x in listed.values() if not x[0])))
    w("<li>Duplicitní tokeny (víc skupin → jedno gecko_id) sloučeny: %d řádků-formací.</li>"
      % sum(meta["primary"][t]["n_dupes"] for t in forms))
    w("<li>Cenové anomálie (týdenní pohyb &gt; ln 20, themes.clean_row): %d (%d spike, %d break).</li>"
      % (len(anomalies), sum(1 for a in anomalies if a["kind"] == "spike"),
         sum(1 for a in anomalies if a["kind"] == "break")))
    w("<li>HTTP: v cache je %d odpovědí DeFiLlamy a coins.llama.fi — tolik úspěšných síťových volání "
      "stál stahovací běh a kontrolní dotazy (opakování po 429 se nepočítají); CoinGecko: dávky po 200 id, %d. Tento běh: %d "
      "skutečných požadavků, %d odpovědí z cache, doba běhu %s s. Historie běhů: "
      "<code>backtest_cache\\runs.jsonl</code>.</li>"
      % (counter.c.get("cached_responses", 0), counter.c.get("coingecko_batches_total", 0),
         counter.c.get("http_requests", 0), counter.c.get("cache_hits", 0), cz(runtime, 0)))
    w("<li>PREREG sha256 %s; collector.py %s; themes.py %s.</li>"
      % (prereg_hash[:16], provenance["collector_sha256"][:16], provenance["themes_sha256"][:16]))
    w("<li>Všechny řádky primárního vesmíru: <code>backtest_cache\\rows_primary.json.gz</code>.</li></ul>")
    w("<details><summary>Předregistrace (PREREG) — plné znění</summary><pre>%s</pre></details>"
      % esc(json.dumps(PREREG, indent=2, ensure_ascii=False)))
    w("</main></body></html>")
    return "\n".join(out)


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(0 if selftest() else 1)
    main()
