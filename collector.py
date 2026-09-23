"""
Gem Screener collector — v11 (step 1: reusable run())

Pulls DeFiLlama (+ CoinGecko for market cap) once, builds a single JSON
snapshot with everything the viewer needs: revenue + adoption(TVL) time
series, growth scores over 1M/3M/6M/1Y windows, and sector aggregates.

Design decisions (per user brief, 2026-08-30):
  - Token-gated: an app/chain with no resolvable gecko_id is dropped entirely.
  - Tokenomics/unlocks: out of scope. Market cap is kept only for sorting.
  - Holders-revenue precision: not required; not attempted here.
  - Adoption proxy: chain stablecoin supply (price-neutral); protocol TVL.
  - Grouped by DeFiLlama parentProtocol so e.g. pump.fun + PumpSwap + the
    mobile app score as ONE investable entity (one token, one row).
  - Collection floor is deliberately low ($10k/30d revenue) so the UI slider
    has room to go down toward "gem" territory; default UI floor is higher.

Run as a script:   python collector.py
Run from a server: collector.run(log=my_log_fn, data_dir=r"C:\\...")

EVERY piece of mutable state lives on Ctx, never at module level. app.py calls
run() repeatedly inside one long-lived process, and module-level accumulators
(excluded counts, slug hints, market caps, logo failures) would carry over from
the previous run and double-count on the second Refresh.
"""
import base64
import concurrent.futures as cf
import io
import json
import math
import os
import re
import sys
import time
import urllib.parse

import requests

import liquidity
import themes
import unlocks

BASE = "https://api.llama.fi"
UA = {"User-Agent": "gem-screener/1.0 (+personal research tool)"}

COLLECTION_FLOOR_USD_30D = 10_000
WINDOWS = [30, 90, 180, 365]
MAX_SERIES_DAYS = 400          # keep charts snappy + payload small
WORKERS = 10
RETRIES = 2

SNAPSHOT_NAME = "snapshot.json"


def script_dir():
    return os.path.dirname(os.path.abspath(__file__))


class Ctx:
    """One collection run: its HTTP session, its logger, its accumulators."""

    def __init__(self, log=None, data_dir=None):
        self._log = log or (lambda m: print(m))
        self.data_dir = data_dir or script_dir()

        self.session = requests.Session()
        self.session.headers.update(UA)

        # --- bulk reference data, filled by fetch_bulk()
        self.protocols = []
        self.fee_protocols = []
        self.cfg_protocols = {}
        self.cfg_parents = {}
        self.chain_gecko = {}
        self.protocols_per_chain = {}
        self.stable_by_chain = {}
        self.parent_slug_hint = {}

        # --- accumulators (the reason Ctx exists)
        self.excluded_apps_count = 0
        self.excluded_chains = []
        self.excluded_doublecounted = []
        self.mcap_by_id = {}
        self.holders30 = {}
        self.logo_failures = []
        self.warnings = []
        self.dropped_untradeable = []

    def log(self, msg):
        self._log("[%s] %s" % (time.strftime("%H:%M:%S"), msg))

    def warn(self, msg):
        """Failures must reach the same stream as progress.

        They used to go to stderr, which under PyInstaller's --noconsole is
        None: every warning silently vanished. They are also kept, so the page
        can say when a refresh came back incomplete instead of only the log."""
        self._log("  ! %s" % msg)
        if not msg.startswith("logo failed"):          # cosmetic, not data
            self.warnings.append(msg[:200])

    def get(self, url, timeout=30, quiet_status=(400, 404), warn=True):
        """GET with retries. Any final failure is logged.

        It used to log only exceptions: three 429s in a row left last_err at
        None and returned None silently, so a rate-limited CoinGecko call looked
        exactly like an empty answer. `quiet_status` stays silent on purpose —
        400/404 are how DeFiLlama says "no such slug" during candidate probing.
        `warn=False` is for a caller that retries on its own and warns only if
        that fails too: otherwise a recovered request still lit the page's
        "neúplná data" chip (12 of them on 2026-09-22, with 515/515 back)."""
        last_err = None
        last_status = None
        # 429 gets its own, much longer schedule. With 1.5/3/4.5 s the retries
        # all landed inside DeFiLlama's limiter window: on 2026-09-22 that cost
        # X Layer its whole adoption series and two price-history chunks (~100
        # coins' Síla), with nothing on screen to say so.
        waits_429 = [3, 8, 20, 40]
        n429 = 0
        attempt = 0
        while attempt <= RETRIES or (last_status == 429 and n429 < len(waits_429)):
            attempt += 1
            try:
                r = self.session.get(url, timeout=timeout)
                if r.status_code == 200:
                    return r.json()
                last_status = r.status_code
                if r.status_code == 429 and n429 < len(waits_429):
                    ra = (r.headers.get("Retry-After") or "").strip()
                    time.sleep(min(60, int(ra)) if ra.isdigit() else waits_429[n429])
                    n429 += 1
                    continue
                break
            except Exception as e:
                last_err = e
                last_status = None
                time.sleep(0.5)
        if not warn:
            return None
        if last_err:
            self.warn("failed: %s (%s)" % (url[:160], last_err))
        elif last_status and last_status not in quiet_status:
            self.warn("HTTP %s: %s" % (last_status, url[:160]))
        return None


# ---------------------------------------------------------------- bulk fetch
def fetch_bulk(ctx):
    ctx.log("fetching bulk endpoints ...")
    ctx.protocols = ctx.get(BASE + "/protocols") or []
    config = ctx.get(BASE + "/config") or {}
    fees_rev = ctx.get(BASE + "/overview/fees?excludeTotalDataChart=true"
                       "&excludeTotalDataChartBreakdown=true&dataType=dailyRevenue") or {}
    stable_chains = ctx.get("https://stablecoins.llama.fi/stablecoinchains") or []
    # Pillar 4 of Adam's original framework — "do token holders get paid?" —
    # which the very first feasibility note said this endpoint answers directly,
    # and which the screener then never used. 32 of 86 trusted apps turned out
    # to pass under 5 % of revenue to holders, three of the top six at 0 %.
    fees_hold = ctx.get(BASE + "/overview/fees?excludeTotalDataChart=true"
                        "&excludeTotalDataChartBreakdown=true&dataType=dailyHoldersRevenue") or {}
    ctx.holders30 = {p.get("defillamaId"): (p.get("total30d") or 0)
                     for p in fees_hold.get("protocols", []) if p.get("defillamaId")}

    ctx.fee_protocols = fees_rev.get("protocols", [])
    ctx.cfg_protocols = {str(p["id"]): p for p in config.get("protocols", [])}
    ctx.cfg_parents = {p["id"]: p for p in config.get("parentProtocols", [])}
    ctx.chain_gecko = config.get("chainCoingeckoIds", {})

    # protocol name -> chains[] (for dev-adoption proxy on chains)
    ctx.protocols_per_chain = {}
    for p in ctx.protocols:
        for ch in (p.get("chains") or []):
            ctx.protocols_per_chain[ch] = ctx.protocols_per_chain.get(ch, 0) + 1

    ctx.stable_by_chain = {
        c["name"]: (c.get("totalCirculatingUSD") or {}).get("peggedUSD") or 0
        for c in stable_chains}

    # DeFiLlama's own slug for a parent, harvested from any of its children.
    # The parent's ID is NOT its API slug — "Sky" is parent#maker, and
    # /summary/fees/maker is a 400.
    ctx.parent_slug_hint = {}
    for p in ctx.protocols:
        pp, ps = p.get("parentProtocol"), p.get("parentProtocolSlug")
        if pp and ps:
            ctx.parent_slug_hint.setdefault(pp, ps)

    ctx.log("bulk endpoints: %d protocols, %d fee-adapters, %d stable-chains"
            % (len(ctx.protocols), len(ctx.fee_protocols), len(stable_chains)))


# ---------------------------------------------------------------- resolve token
def gecko_for_app(ctx, entry):
    p = ctx.cfg_protocols.get(str(entry.get("defillamaId")))
    if p:
        if p.get("gecko_id"):
            return p["gecko_id"]
        pp = ctx.cfg_parents.get(p.get("parentProtocol"))
        if pp and pp.get("gecko_id"):
            return pp["gecko_id"]
    pp = ctx.cfg_parents.get(entry.get("parentProtocol"))
    if pp and pp.get("gecko_id"):
        return pp["gecko_id"]
    return None


def gecko_for_chain(ctx, entry):
    v = ctx.chain_gecko.get(entry.get("name")) or ctx.chain_gecko.get(entry.get("displayName", ""))
    return v.get("geckoId") if v else None


def chain_sector(ctx, entry):
    """L1 vs L2 — the only chain split in this data that means anything.

    The VM families we used before put Solana, Tron, Stellar, TON, Aptos, Sui,
    ICP, Near and Filecoin into one bucket called "Other", which is not a peer
    group by any reading."""
    v = ctx.chain_gecko.get(entry.get("name")) or ctx.chain_gecko.get(entry.get("displayName", ""))
    types = ((v or {}).get("parent") or {}).get("types") or []
    if "L2" in types or "L3" in types:
        return "L2 / rollup"
    return "L1"


def slugify(name):
    s = (name or "").lower().strip()
    s = re.sub(r"[^a-z0-9.\- ]", "", s)
    return re.sub(r"\s+", "-", s)


# ---------------------------------------------------------------- group apps by parent
def group_apps(ctx, floor=COLLECTION_FLOOR_USD_30D):
    """Fee adapters grouped into investable entities.

    Entity key: parentProtocol id if set, else the leaf's own id, so pump.fun +
    PumpSwap + the app score as ONE token. Returns (groups, number dropped for
    having no token, names dropped as double counted) and changes nothing on
    ctx — backtest.py calls this with floor=0 to get dead adapters too."""
    app_groups = {}   # key -> {slug, name, category, gecko_id, members, total30d}
    no_token = 0
    doublecounted = []
    for e in ctx.fee_protocols:
        if e.get("protocolType") != "protocol":
            continue
        if (e.get("total30d") or 0) < floor:
            continue
        # An adapter DeFiLlama marks as double counted is already represented by
        # another row; keeping it inflates its sector total and everyone's share.
        if e.get("doublecounted"):
            doublecounted.append(e["name"])
            continue
        gecko = gecko_for_app(ctx, e)
        if not gecko:
            no_token += 1
            continue
        if e.get("parentProtocol"):
            key = e["parentProtocol"]
            parent_meta = ctx.cfg_parents.get(key, {})
            name = parent_meta.get("name") or e["name"]
            # Ordered candidates; the fetcher takes the first that returns data.
            slug = [c for c in (ctx.parent_slug_hint.get(key), slugify(name),
                                key.replace("parent#", "")) if c]
        else:
            key = "leaf#%s" % e.get("defillamaId")
            name = e["name"]
            slug = [c for c in (e.get("slug"), slugify(name)) if c]
        g = app_groups.setdefault(key, {
            "key": key, "slug": slug, "name": name, "gecko_id": gecko,
            "category": e.get("category"), "members": [], "total30d": 0.0,
            "logo": e.get("logo"), "holders30d": 0.0, "holders_leaves": 0,
        })
        g["members"].append(e["name"])
        g["total30d"] += e.get("total30d") or 0
        # a leaf missing from the holders feed means "no data", never "zero"
        did = e.get("defillamaId")
        if did in ctx.holders30:
            g["holders30d"] += ctx.holders30[did]
            g["holders_leaves"] += 1

    groups = [g for g in app_groups.values() if g["total30d"] >= floor]
    return groups, no_token, doublecounted


def build_candidates(ctx):
    """Apps (grouped by parent) and chains above the collection floor.

    Also tracks what the token-gate excludes above the revenue floor, so the UI
    can be honest about it instead of silently dropping recognizable names."""
    apps_candidates, ctx.excluded_apps_count, ctx.excluded_doublecounted = \
        group_apps(ctx, COLLECTION_FLOOR_USD_30D)

    chain_candidates = []
    for e in ctx.fee_protocols:
        if e.get("protocolType") != "chain":
            continue
        if (e.get("total30d") or 0) < COLLECTION_FLOOR_USD_30D:
            continue
        gecko = gecko_for_chain(ctx, e)
        if not gecko:
            ctx.excluded_chains.append({"name": e["name"], "total30d": e.get("total30d") or 0})
            continue
        chain_candidates.append({
            "slug": e.get("slug") or e["name"].lower(), "name": e["name"],
            "gecko_id": gecko, "total30d": e.get("total30d") or 0,
            "category": chain_sector(ctx, e),
            # The logo URL the fees feed gives for chains is unusable: it points at
            # /chains/rsz_<raw name>.jpg, so "OP Mainnet" arrives with a literal
            # space and 404s even once encoded. The /icons/chains/rsz_<slug> route
            # does resolve, so try that first and keep the feed's URL as a fallback.
            "logo": [u for u in
                     ("https://icons.llamao.fi/icons/chains/rsz_%s" % slugify(e["name"]),
                      e.get("logo")) if u],
        })

    ctx.excluded_chains.sort(key=lambda c: -c["total30d"])
    ctx.log("candidates after token-gate + $%d floor: %d apps, %d chains "
            "(%d apps + %d chains excluded: no token)"
            % (COLLECTION_FLOOR_USD_30D, len(apps_candidates), len(chain_candidates),
               ctx.excluded_apps_count, len(ctx.excluded_chains)))
    return apps_candidates, chain_candidates


# ---------------------------------------------------------------- per-entity fetch
def first_hit(ctx, candidates, url_tmpl, extract):
    """Try each slug candidate; return (payload, slug) for the first with data."""
    for c in candidates:
        d = ctx.get(BASE + url_tmpl % urllib.parse.quote(str(c)))
        if d and extract(d):
            return d, c
    return None, (candidates[0] if candidates else None)


def fetch_rev_history(ctx, cands):
    """Full daily revenue history from the first slug candidate that has any.

    Untruncated: the snapshot keeps MAX_SERIES_DAYS, but a backtest that asks
    "what did the six-month trend look like a year ago" needs ~550 days."""
    rev, used = first_hit(ctx, cands, "/summary/fees/%s?dataType=dailyRevenue",
                          lambda d: d.get("totalDataChart"))
    return (rev or {}).get("totalDataChart") or [], used


def fetch_app_series(ctx, g):
    cands = g["slug"] if isinstance(g["slug"], list) else [g["slug"]]
    rev_series, used = fetch_rev_history(ctx, cands)
    # Reuse the slug that worked for fees; fall back to trying the rest.
    tvl, _ = first_hit(ctx, [used] + [c for c in cands if c != used],
                       "/protocol/%s", lambda d: d.get("tvl"))
    tvl_series = [[pt["date"], pt.get("totalLiquidityUSD") or 0]
                  for pt in ((tvl or {}).get("tvl") or [])]
    out = dict(g)
    out["slug"] = used
    out["description"] = (tvl or {}).get("description") or ""
    out["url"] = (tvl or {}).get("url") or ""
    out["chains"] = (tvl or {}).get("chains") or []
    out["rev_series"] = rev_series[-MAX_SERIES_DAYS:]
    out["tvl_series"] = tvl_series[-MAX_SERIES_DAYS:]
    return out


def fetch_chain_series(ctx, c):
    """Chain adoption is measured in stablecoin supply, not USD TVL.

    TVL is denominated in the chain's own volatile assets, so when ETH fell this
    year Ethereum's TVL 'growth' read 7 points per month worse than its actual
    capital base — that is a price chart, not an adoption chart. Stablecoin
    supply is pegged, so its movement is inflow and outflow only. Raw TVL is
    still kept for the size column and the MC/TVL multiple."""
    rev = ctx.get(BASE + "/summary/fees/%s?dataType=dailyRevenue"
                  % urllib.parse.quote(c["slug"]))
    rev_series = (rev or {}).get("totalDataChart") or []

    tvl = ctx.get(BASE + "/v2/historicalChainTvl/%s" % urllib.parse.quote(c["name"]))
    tvl_series = [[pt["date"], pt.get("tvl") or 0] for pt in (tvl or [])]

    sc = ctx.get("https://stablecoins.llama.fi/stablecoincharts/%s"
                 % urllib.parse.quote(c["name"]))
    stable_series = []
    for pt in (sc or []):
        v = (pt.get("totalCirculating") or {}).get("peggedUSD")
        if v:
            stable_series.append([int(pt["date"]), float(v)])

    # Activity, the half stablecoin supply cannot see: a chain can hold billions
    # of idle capital and be dead. Daily DEX volume is the broadest free proxy.
    dex = ctx.get(BASE + "/overview/dexs/%s?excludeTotalDataChartBreakdown=true"
                  "&dataType=dailyVolume" % urllib.parse.quote(c["name"]))
    dex_series = [[int(t), float(v or 0)] for t, v in ((dex or {}).get("totalDataChart") or [])]

    if len(stable_series) >= 120:
        adoption, metric = stable_series, "stablecoins"
    else:
        adoption, metric = tvl_series, "tvl"

    out = dict(c)
    out["rev_series"] = rev_series[-MAX_SERIES_DAYS:]
    out["tvl_series"] = adoption[-MAX_SERIES_DAYS:]      # what adoption is judged on
    out["raw_tvl_series"] = tvl_series[-MAX_SERIES_DAYS:]
    out["dex_series"] = dex_series[-MAX_SERIES_DAYS:]
    out["dex30d"] = round(sum(v for _, v in dex_series[-30:]), 2)
    out["adoption_metric"] = metric
    out["protocol_count"] = ctx.protocols_per_chain.get(c["name"], 0)
    out["stablecoin_supply"] = ctx.stable_by_chain.get(c["name"], 0)
    out["description"] = ""
    out["url"] = ""
    return out


def fetch_all_series(ctx, apps_candidates, chain_candidates):
    ctx.log("fetching per-entity time series (%d requests, %d workers) ..."
            % (2 * (len(apps_candidates) + len(chain_candidates)), WORKERS))

    apps_out, chains_out = [], []
    t0 = time.time()
    with cf.ThreadPoolExecutor(max_workers=WORKERS) as ex:
        fut_map = {}
        for g in apps_candidates:
            fut_map[ex.submit(fetch_app_series, ctx, g)] = ("app", g["name"])
        for c in chain_candidates:
            fut_map[ex.submit(fetch_chain_series, ctx, c)] = ("chain", c["name"])
        done = 0
        total = len(fut_map)
        for fut in cf.as_completed(fut_map):
            kind, name = fut_map[fut]
            done += 1
            try:
                res = fut.result()
            except Exception as e:
                ctx.warn("%s failed: %s" % (name, e))
                continue
            if kind == "app":
                apps_out.append(res)
            else:
                chains_out.append(res)
            if done % 25 == 0 or done == total:
                ctx.log("  %d/%d entities fetched (%.0fs elapsed)"
                        % (done, total, time.time() - t0))

    ctx.log("time series fetch done in %.0fs — apps=%d chains=%d"
            % (time.time() - t0, len(apps_out), len(chains_out)))
    return apps_out, chains_out


# ---------------------------------------------------------------- market caps
def fetch_market_caps(ctx, entities):
    all_gecko_ids = sorted({e["gecko_id"] for e in entities if e.get("gecko_id")})
    ctx.log("fetching market caps for %d gecko ids ..." % len(all_gecko_ids))

    chunk_size = 200
    for i in range(0, len(all_gecko_ids), chunk_size):
        if i:
            time.sleep(6)  # CoinGecko's free tier 429s even at 7 s spacing
        chunk = all_gecko_ids[i:i + chunk_size]
        # price_change_percentage adds 7d/30d/1y at no extra call. The call goes
        # through cg_get (15/30/60 s backoff, Retry-After) because liquidity now
        # reads its volume: a silently missing chunk would empty the degen view.
        url = ("https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&ids="
               + ",".join(chunk) + "&order=market_cap_desc&per_page=250&page=1"
               + "&price_change_percentage=7d,30d,1y")
        data = themes.cg_get(ctx, url, timeout=40)
        if not data:
            continue
        for row in data:
            ctx.mcap_by_id[row["id"]] = {
                "mcap": row.get("market_cap"),
                # shown next to Potenciál: a 10 % float trades at a mcap that
                # looks cheap against revenue while the FDV is ten times larger
                "fdv": row.get("fully_diluted_valuation"),
                "price": row.get("current_price"),
                "price_chg_24h_pct": row.get("price_change_percentage_24h"),
                "symbol": (row.get("symbol") or "").upper(),
                "cg": themes.market_fields(row),
            }

    ctx.log("market caps resolved for %d/%d ids" % (len(ctx.mcap_by_id), len(all_gecko_ids)))


# ---------------------------------------------------------------- logos
def fetch_logo(ctx, url):
    """The published artifact runs under a CSP that blocks every external host,
    so a remote <img src> would silently render nothing. Icons are fetched at
    48px and inlined as data URIs (~1.5 KB of webp each).

    url may be a single string or an ordered list of candidates."""
    cands = url if isinstance(url, list) else [url]
    last = None
    for cand in cands:
        if not cand:
            continue
        full = urllib.parse.quote(cand, safe=":/?&=%")
        # w/h are DeFiLlama's icon-resizer parameters; other hosts (CoinGecko's
        # CDN) serve fixed sizes and get their small variant from the path.
        if "icons.llamao.fi" in cand:
            full += ("&" if "?" in cand else "?") + "w=48&h=48"
        try:
            r = ctx.session.get(full, timeout=20)
            if r.status_code == 200 and r.content and len(r.content) <= 25000:
                ctype = r.headers.get("Content-Type", "image/webp").split(";")[0]
                return "data:%s;base64,%s" % (ctype,
                                              base64.b64encode(r.content).decode("ascii"))
            last = "%s -> HTTP %s / %s B" % (full, r.status_code, len(r.content or b""))
        except Exception as exc:
            last = "%s -> %s: %s" % (full, type(exc).__name__, str(exc)[:60])
    ctx.logo_failures.append((cands[0] if cands else "?", last))
    return None


def fetch_all_logos(ctx, apps_out, chains_out):
    targets = [e for e in apps_out + chains_out if e.get("logo")]
    ctx.log("fetching %d logos (%d apps, %d chains have a logo url) ..."
            % (len(targets),
               sum(1 for e in apps_out if e.get("logo")),
               sum(1 for e in chains_out if e.get("logo"))))
    got = 0
    with cf.ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(fetch_logo, ctx, e["logo"]): e for e in targets}
        for fut in cf.as_completed(futs):
            e = futs[fut]
            try:
                data = fut.result()
            except Exception:
                data = None
            e["logo_data"] = data
            if data:
                got += 1
    for e in apps_out + chains_out:
        e.pop("logo", None)          # keep only the inlined copy
    ctx.log("logos inlined: %d/%d" % (got, len(targets)))
    for u, why in ctx.logo_failures[:12]:
        ctx.warn("logo failed: %s -> %s" % (u, why))


# ------------------------------------------- drop what can't actually be bought
def tradeable(ctx, e):
    """A gecko_id alone isn't a tradeable market: some resolve to a dead listing
    with no price or a market cap of zero. Those aren't investments, so they're
    out."""
    mc = (ctx.mcap_by_id.get(e.get("gecko_id")) or {})
    return bool(mc.get("mcap")) and mc["mcap"] > 0 and bool(mc.get("price"))


def drop_untradeable(ctx, apps_out, chains_out):
    ctx.dropped_untradeable = [e["name"] for e in apps_out + chains_out
                               if not tradeable(ctx, e)]
    apps_out = [e for e in apps_out if tradeable(ctx, e)]
    chains_out = [e for e in chains_out if tradeable(ctx, e)]
    ctx.log("dropped %d untradeable (no live market cap / price): %s"
            % (len(ctx.dropped_untradeable), ", ".join(ctx.dropped_untradeable[:10])))

    # A series we failed to fetch is a hole, not a fact — say so loudly.
    no_rev = [e["name"] for e in apps_out if not e.get("rev_series")]
    no_tvl = [e["name"] for e in chains_out if not e.get("tvl_series")]
    if no_rev:
        ctx.warn("%d apps ended up with NO revenue series: %s"
                 % (len(no_rev), ", ".join(no_rev[:12])))
    if no_tvl:
        ctx.warn("%d chains ended up with NO TVL series: %s"
                 % (len(no_tvl), ", ".join(no_tvl[:12])))
    return apps_out, chains_out


# ---------------------------------------------------------------- growth math
def smooth7(series_vals):
    out = []
    n = len(series_vals)
    for i in range(n):
        w = series_vals[max(0, i - 6):i + 1]
        out.append(sum(w) / len(w))
    return out


def ols_log_slope(vals, step_days=1.0, min_points=8):
    """Log-linear regression. step_days says how many days one element spans,
    so weekly buckets still report a monthly growth rate."""
    pts = [(i, v) for i, v in enumerate(vals) if v and v > 0]
    if len(pts) < min_points:
        return None, None
    n = len(pts)
    xs = [p[0] for p in pts]
    ys = [math.log(p[1]) for p in pts]
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        return None, None
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    a = my - b * mx
    ss_res = sum((y - (a + b * x)) ** 2 for x, y in zip(xs, ys))
    ss_tot = sum((y - my) ** 2 for y in ys)
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0
    monthly_pct = (math.exp(b * (30.0 / step_days)) - 1) * 100
    monthly_pct = max(-99.0, min(999.0, monthly_pct))
    return round(monthly_pct, 2), round(max(0.0, min(1.0, r2)), 3)


def window_growth(series):
    """series: [[ts,val],...] ascending. returns {window: {g, r2, total, days}}

    Windows are sliced by CALENDAR DAYS, not by array position — several
    adapters skip days, and index slicing silently made those windows longer
    than advertised (audit found 22 totals off by up to 7%)."""
    if not series:
        return {}
    end = series[-1][0]
    smoothed = smooth7([v for _, v in series])
    out = {}
    for w in WINDOWS:
        lo = end - w * 86400
        idx = [i for i, (t, _) in enumerate(series) if t > lo]
        seg = [smoothed[i] for i in idx] if len(idx) >= 10 else smoothed
        g, r2 = ols_log_slope(seg)
        total = sum(series[i][1] for i in idx)
        out[str(w)] = {"g": g, "r2": r2, "total": round(total, 2),
                       "days": len(idx)}
    return out


# ---------------------------------------------------------------- trajectory / hockey-stick
# Four DISJOINT quarters, oldest -> newest. Unlike the overlapping 1M/3M/6M/1Y
# windows above, these answer "how fast was it growing DURING that stretch", so
# their shape IS the growth curve and a bend in it is visible.
#
# Two robustness choices, both learned from real data:
#   * quarters, not months — a 30-day regression on daily data is mostly noise
#   * weekly buckets, not daily — a single freak day (Liquity once booked 18x its
#     normal daily revenue) otherwise drags the whole regression up and fakes a
#     hockey stick. Revenue is summed per week, TVL is averaged.
QUARTERS = [("p1", 364, 274), ("p2", 273, 183), ("p3", 182, 92), ("p4", 91, 0)]

FLAT_BAND = 3.0     # |growth| under this %/month counts as flat
STRONG = 15.0       # growth above this %/month counts as a real take-off
SQUASH_K = 40.0     # %/month that maps to tanh(1) in the score


def weekly_buckets(series, agg):
    """Collapse a daily series into 7-day buckets, oldest first.

    Buckets holding fewer than 7 days are dropped when summing: a half-full
    oldest week reads as a low week and tilts the earliest quarter upward,
    which is exactly the fake hockey stick we are trying not to draw."""
    if not series:
        return []
    end = series[-1][0]
    bins = {}
    for t, v in series:
        bins.setdefault(int((end - t) // (7 * 86400)), []).append(v)
    out = []
    for b in sorted(bins.keys(), reverse=True):
        xs = bins[b]
        if agg == "sum" and len(xs) < 7:
            continue
        val = sum(xs) if agg == "sum" else sum(xs) / len(xs)
        out.append((end - b * 7 * 86400, val))
    return out


def trajectory(series, agg="sum"):
    """Growth per disjoint quarter + a phase label + a filter-independent score."""
    out = {"periods": {}, "phase": "Nový", "hs": None,
           "recent": None, "baseline": None, "accel": None}
    if not series or len(series) < 60:
        return out

    weeks = weekly_buckets(series, agg)
    if len(weeks) < 8:
        return out
    wts = [t for t, _ in weeks]
    wvals = [v for _, v in weeks]
    last = series[-1][0]

    for name, start_days, end_days in QUARTERS:
        lo = last - start_days * 86400
        hi = last - end_days * 86400
        idx = [i for i, t in enumerate(wts) if lo <= t <= hi]
        if len(idx) < 6:
            out["periods"][name] = {"g": None, "r2": None}
            continue
        g, r2 = ols_log_slope([wvals[i] for i in idx], step_days=7.0, min_points=6)
        out["periods"][name] = {"g": g, "r2": r2}

    def eff(name):
        """Growth damped by how clean its trend was — noise counts for less."""
        p = out["periods"].get(name) or {}
        g, r2 = p.get("g"), p.get("r2")
        if g is None:
            return None
        return g * (0.3 + 0.7 * (r2 if r2 is not None else 0.0))

    p1, p2, p3, p4 = eff("p1"), eff("p2"), eff("p3"), eff("p4")

    # "Recent" is the latest quarter only. Blending older quarters in here made
    # projects whose spike was 4 months ago look like they were spiking now.
    recent = p4
    if recent is None:
        return out
    older = [x for x in (p1, p2, p3) if x is not None]
    baseline = sum(older) / len(older) if older else None
    out["recent"] = round(recent, 2)

    # How big is the latest quarter compared with the best quarter this project
    # ever had? Separates "breaking out to new highs" from "bouncing off the
    # floor after a collapse" — both show huge log-growth, only one is a gem.
    qlevels = {}
    for name, start_days, end_days in QUARTERS:
        lo = last - start_days * 86400
        hi = last - end_days * 86400
        vs = [v for t, v in weeks if lo <= t <= hi]
        if vs:
            qlevels[name] = sum(vs) / len(vs)
    peak = max(qlevels.values()) if qlevels else 0
    q4_level = qlevels.get("p4", 0)
    lvp = (q4_level / peak) if peak > 0 else None
    out["level_vs_peak"] = round(lvp, 3) if lvp is not None else None
    at_peak = lvp is not None and lvp >= 0.6

    # Small third term so a project bouncing off the floor after a collapse
    # ranks below one making the same move at its own all-time best.
    peak_term = (2 * lvp - 1) if lvp is not None else 0.0

    if baseline is None:
        out["hs"] = round(50 * (1 + 0.5 * math.tanh(recent / SQUASH_K)
                                + 0.1 * peak_term), 1)
        return out

    accel = recent - baseline
    out["baseline"] = round(baseline, 2)
    out["accel"] = round(accel, 2)
    out["hs"] = round(50 * (1 + 0.5 * math.tanh(recent / SQUASH_K)
                            + 0.4 * math.tanh(accel / SQUASH_K)
                            + 0.1 * peak_term), 1)

    if recent < -FLAT_BAND:
        phase = "Pokles"
    elif recent <= FLAT_BAND:
        phase = "Stagnace"
    elif baseline <= FLAT_BAND and recent >= STRONG and at_peak:
        phase = "Zážeh"
    elif accel > FLAT_BAND:
        phase = "Akcelerace"
    elif accel < -FLAT_BAND:
        phase = "Zpomaluje"
    else:
        phase = "Setrvalý"
    out["phase"] = phase
    return out


# ================================================================ v11 metrics
# One fixed lens instead of a 1M/3M/6M/1Y switch. Everything below is computed
# here so the viewer never recomputes anything from UI state — that split is
# what let the table and the year chart disagree in v10.
DAY = 86400
STRENGTH_STEPS = 6              # 6 monthly points back = the 182d growth window
STRENGTH_STEP_DAYS = 182.0 / 6  # ~30.3d, so t_6 lands on the growth window edge


def median(xs):
    xs = sorted(xs)
    n = len(xs)
    if n == 0:
        return None
    mid = n // 2
    return xs[mid] if n % 2 else (xs[mid - 1] + xs[mid]) / 2.0


def runrate(series, end=None):
    """Annualised current revenue — the most conservative of three readings.

    Trailing-twelve-month punishes anything that grew: a project that went from
    nothing to $1M/month reads as $5M/yr when it is really earning $12M/yr, so
    it looks 2.4x more expensive than it is. Annualising the last 30 days alone
    goes wrong the other way, so we take the minimum of:

      365 * rev30 / cov30     what it earns right now
      365 * rev90 / cov90     the same over a quarter
      12  * median(m1,m2,m3)  the median of three disjoint months

    The median term is not redundant. min(30d*12, 90d*4) only neutralises a
    spike OLDER than 30 days: a protocol earning N/month that books 10N in the
    newest month gives min(120N, 48N) = 48N — four times its truth. The median
    of the three monthly blocks returns 12N.

    Dividing by coverage rather than the nominal window stops a 45-day-old
    project from being annualised as if it had a full quarter of history.

    Lumpy reporters (Chainlink, LayerZero, Safe — 14 of 217 today) post revenue
    in monthly lumps, so a 30-day window holds 0, 1 or 2 postings depending on
    the calendar and 12*rev30 swings between 0 and 24x the truth. Those drop to
    the 90-day reading alone."""
    out = {"value": None, "basis": None, "cov30": 0, "cov90": 0, "sparse": False}
    if not series:
        return out
    end = end if end is not None else series[-1][0]
    first = series[0][0]

    def window(days):
        lo = end - days * DAY
        vals = [v for t, v in series if lo < t <= end]
        cov = days if first <= lo else int(round((end - first) / float(DAY)))
        return sum(vals), max(0, min(cov, days)), sum(1 for v in vals if v and v > 0)

    rev30, cov30, _ = window(30)
    rev90, cov90, nz90 = window(90)
    out["cov30"], out["cov90"] = cov30, cov90
    if cov90 <= 0:
        return out

    sparse = nz90 < 0.5 * cov90
    out["sparse"] = sparse

    cands = [(365.0 * rev90 / cov90, "90d")]
    if not sparse and cov30 > 0:
        cands.append((365.0 * rev30 / cov30, "30d"))
        blocks = []
        for k in range(3):
            lo = end - (k + 1) * 30 * DAY
            hi = end - k * 30 * DAY
            # +2d of slack: a series holding exactly 90 days starts one day
            # inside the oldest block, and a strict test threw that block away —
            # which silently dropped the median term altogether.
            if first <= lo + 2 * DAY:
                blocks.append(sum(v for t, v in series if lo < t <= hi))
        if len(blocks) == 3:
            cands.append((12.0 * median(blocks), "med3"))

    val, basis = min(cands, key=lambda c: c[0])
    out["value"] = round(max(0.0, val), 2)
    out["basis"] = "90d-sparse" if sparse else basis
    return out


def growth6m(series, agg="sum"):
    """Six-month trend: log-OLS on weekly buckets, reported as %/month.

    Weekly first, always — a single freak day otherwise drags the regression up
    and fakes a hockey stick."""
    out = {"g": None, "r2": None, "weeks": 0, "days": 0, "label": "6M"}
    if not series:
        return out
    end = series[-1][0]
    lo = end - 182 * DAY
    seg = [[t, v] for t, v in series if t > lo]
    out["days"] = int(round((end - max(lo, series[0][0])) / float(DAY)))
    weeks = weekly_buckets(seg, agg)
    out["weeks"] = len(weeks)
    if len(weeks) >= 5:
        out["g"], out["r2"] = ols_log_slope([v for _, v in weeks], step_days=7.0,
                                            min_points=5)
    if out["days"] < 165:
        out["label"] = "%dM" % max(1, int(round(out["days"] / 30.0)))
    return out


def monthly_buckets(series, months=13, agg="sum"):
    """Calendar months in UTC, oldest first. The newest is normally partial —
    flagged so the chart can hatch it instead of drawing a fake collapse."""
    import calendar
    import datetime
    if not series:
        return []
    bins = {}
    for t, v in series:
        d = datetime.datetime.fromtimestamp(t, datetime.timezone.utc)
        bins.setdefault((d.year, d.month), []).append(v)
    out = []
    for (y, m) in sorted(bins)[-months:]:
        xs = bins[(y, m)]
        val = sum(xs) if agg == "sum" else sum(xs) / len(xs)
        full = calendar.monthrange(y, m)[1]
        out.append({"m": "%04d-%02d" % (y, m), "v": round(val, 2),
                    "days": len(xs), "partial": len(xs) < full})
    return out


def strength(series, price_points, end=None, measure="runrate"):
    """"Is its potential growing?" — revenue growth divided by price growth.

    The long way round is potential_t = bench / (mcap_t / rr_t) with the market
    cap proxied as mcap_now * price_t/price_now. Take the ratio of two such
    points and both bench and mcap_now cancel, leaving

        strength = (rr_now / rr_-6M) / (price_now / price_-6M)

    so no market-cap history and no pinned benchmark are needed at all. Above 1
    the business is outrunning its own token price — the market has not repriced
    it yet, which is the whole thesis of this screener.

    Assumes constant supply (tokenomics are explicitly out of scope), so an
    inflationary token's real mcap 6 months ago was lower than the proxy and its
    strength reads high.

    K >= 3 is required: adjacent points share 60 of their 90 days, so "now vs
    two months ago" is biased toward 1 and would report a fake "steady"."""
    out = {"ratio": None, "k": 0, "rev_factor": None, "price_factor": None, "points": []}
    if not series or not price_points:
        return out
    end = end if end is not None else series[-1][0]

    def price_at(t):
        best = None
        for ts, pr in price_points:
            d = abs(ts - t)
            if d <= 3 * DAY and (best is None or d < best[0]):
                best = (d, pr)
        return best[1] if best else None

    pts = []
    for k in range(STRENGTH_STEPS + 1):
        t = int(end - k * STRENGTH_STEP_DAYS * DAY)
        if measure == "level":
            # chains: the thing being valued is a stock (capital parked), so the
            # measure is its level then, not an annualised flow.
            val, basis = _level_at(series, t), "level"
        else:
            rr = runrate(series, end=t)
            val, basis = rr["value"], rr["basis"]
        pts.append({"t": t, "price": price_at(t), "rr": val, "basis": basis})
    out["points"] = pts

    if not (pts[0]["rr"] and pts[0]["price"]):
        return out
    # a run-rate at t needs a quarter of history behind t; a level only needs the
    # series to reach that far back
    need = 0 if measure == "level" else 90 * DAY
    usable = [k for k in range(1, len(pts))
              if pts[k]["rr"] and pts[k]["price"] and series[0][0] <= pts[k]["t"] - need]
    if not usable:
        return out
    k = max(usable)
    if k < 3:
        return out

    rev_f = pts[0]["rr"] / pts[k]["rr"]
    price_f = pts[0]["price"] / pts[k]["price"]
    if price_f <= 0:
        return out
    out["k"] = k
    out["rev_factor"] = round(rev_f, 3)
    out["price_factor"] = round(price_f, 3)
    out["ratio"] = round(rev_f / price_f, 3)
    return out


def fetch_price_history(ctx, gecko_ids, end):
    """One request per ~50 coins for the whole monthly price grid.

    coins.llama.fi/batchHistorical takes {coin: [timestamps]} and answers 60
    coins x 7 stamps in 0.2s, so the entire strength column costs 5 requests."""
    stamps = [int(end - k * STRENGTH_STEP_DAYS * DAY) for k in range(STRENGTH_STEPS + 1)]
    out = {}
    chunk = 50
    for i in range(0, len(gecko_ids), chunk):
        part = gecko_ids[i:i + chunk]
        q = {("coingecko:%s" % g): stamps for g in part}
        url = ("https://coins.llama.fi/batchHistorical?coins=%s&searchWidth=6h"
               % urllib.parse.quote(json.dumps(q, separators=(",", ":"))))
        d = ctx.get(url, timeout=60)
        for key, v in ((d or {}).get("coins") or {}).items():
            gid = key.split(":", 1)[1]
            pts = [(int(p["timestamp"]), float(p["price"]))
                   for p in (v.get("prices") or []) if p.get("price")]
            if pts:
                out[gid] = sorted(pts)
    ctx.log("price history: %d/%d coins over %d monthly points"
            % (len(out), len(gecko_ids), len(stamps)))
    return out


# -------------------------------------------------- chain adoption: capital x activity
ADOPTION_FLOOR = 1e6        # a component below this is noise, not a signal
CHAIN_STABLE_FLOOR = 1e7    # below this, mcap/stables is a division by nearly zero


def rolling_sum(series, days=30):
    """Trailing N-day sum — turns daily DEX volume into a level comparable with
    a stablecoin balance."""
    if not series:
        return []
    out, acc, j = [], 0.0, 0
    for i, (t, v) in enumerate(series):
        acc += v or 0.0
        lo = t - days * DAY
        while j <= i and series[j][0] <= lo:
            acc -= series[j][1] or 0.0
            j += 1
        out.append([t, acc])
    return out


def _level_at(series, t, tol=3 * DAY):
    near = [v for ts, v in series if abs(ts - t) <= tol]
    if near:
        return sum(near) / len(near)
    prev = [v for ts, v in series if ts <= t]
    return prev[-1] if prev else None


def _ffill(series, t):
    prev = None
    for ts, v in series:
        if ts > t:
            break
        prev = v
    return prev


def adoption_index(components, end):
    """Adoption = capital x activity, as one price-resistant series.

    Stablecoin supply alone is price-neutral but blind to whether anything is
    happening on the chain; DEX volume alone is activity but denominated in USD,
    so it carries price. The geometric mean of the two, each normalised to its
    own level six months ago, keeps half the price exposure and all of the
    signal.

    Because ln(geomean) = mean(ln), an OLS slope on this index is EXACTLY the
    mean of the components' slopes — the audit gets that identity for free.

    A component under ADOPTION_FLOOR is dropped rather than averaged in: Quai
    does $14k of DEX volume a month, and a $2k -> $14k move would otherwise
    dominate a flat multi-billion stablecoin base."""
    ref = end - 182 * DAY
    live = []
    for name, s in components:
        if not s:
            continue
        refv = _level_at(s, ref)
        nowv = s[-1][1] if s else None
        if not refv or refv < ADOPTION_FLOOR or not nowv or nowv < ADOPTION_FLOOR:
            continue
        if s[0][0] > ref:          # no six-month baseline at all
            continue
        live.append((name, s, refv))
    if not live:
        return None

    # The whole series, not just from `ref` onward. `ref` is only the base the
    # index is normalised to; cutting the series there left 26 weeks, which is
    # too short for the year chart (needs 30) and for the four-quarter
    # trajectory — every chain came out "Pokles" with an empty chart.
    first = max(s[0][0] for _, s, _ in live)
    stamps = sorted({t for _, s, _ in live for t, _ in s if t >= first})
    out = []
    for t in stamps:
        logs = []
        for _, s, refv in live:
            v = _ffill(s, t)
            if not v or v <= 0:
                logs = None
                break
            logs.append(math.log(v / refv))
        if logs:
            # SIGNIFICANT digits, not decimal places. A chain that grew a
            # thousandfold starts its index near 0.0007, and round(v, 6) left
            # that with one significant digit — the regression then ran on a
            # badly quantised first year for exactly the fastest-growing chains.
            out.append([t, float("%.9g" % math.exp(sum(logs) / len(logs)))])
    if len(out) < 30:
        return None

    ratios = {}
    for name, s, refv in live:
        now = s[-1][1]
        ratios[name] = round(now / refv, 3) if refv else None
    return {"series": out, "ref_ts": ref,
            "components": [n for n, _, _ in live], "ratios": ratios}


# -------------------------------------------------- valuation, reliability, tier
UPSIDE_CAP = 50.0
RELIABLE_MIN_MCAP = 3e6
RELIABLE_MIN_DAYS = 180
RELIABLE_MIN_LVP = 0.35
RELIABLE_MIN_G6M = -10.0
RELIABLE_MAX_LAG_DAYS = 10


def reliability(e, now):
    """Everything that has to be true before a big multiple means anything.

    Computed here, not in the viewer, so the table, the tooltip, the year chart
    and the audit all read one number instead of four re-derivations."""
    fails = []
    if not e.get("mcap") or e["mcap"] < RELIABLE_MIN_MCAP:
        fails.append("market cap pod $3M")
    # A chain DeFiLlama tracks no stablecoins for (Canton, Quai) has no series to
    # measure history, freshness or trend on. Running the checks anyway reported
    # "0 dní dat" and "poslední údaj je 0 dní starý" — three artefacts of one gap,
    # and false ones: Canton has four months of fresh data, just not stablecoins.
    if e.get("adoption_metric") and e["adoption_metric"] != "stablecoins":
        fails.append("bez dat o stablecoinech")
        return False, fails
    if (e.get("hist_days") or 0) < RELIABLE_MIN_DAYS:
        fails.append("krátká historie")
    # A missing level_vs_peak is not a collapse. trajectory() gives up under 60
    # data points, so a 57-day-old protocol got "hluboko pod svým maximem" on
    # top of "krátká historie" — the same fact punished twice, which pushed a
    # $18M/month project 40 places down the table.
    lvp = (e.get("traj") or {}).get("level_vs_peak")
    if lvp is not None and lvp < RELIABLE_MIN_LVP:
        fails.append("hluboko pod svým maximem")
    g = (e.get("growth6m") or {}).get("g")
    # An unmeasurable trend (lumpy reporting, too few usable weeks) still fails
    # the gate, but it is not a decline: the tooltip used to tell Optimism
    # Foundation "klesá o 0,0 % měsíčně".
    if g is None:
        fails.append("trend nejde změřit")
    elif g < RELIABLE_MIN_G6M:
        fails.append("klesající trend")
    lag = e.get("lag_days")
    if lag is None or lag > RELIABLE_MAX_LAG_DAYS:
        fails.append("stará data")
    return (not fails), fails


YOUNG_MIN_MCAP = 3e6
YOUNG_MIN_REV30 = 1e6


def is_young(e):
    """Big, cleanly growing, but too new to have proven anything.

    The reliability gate exists to sink micro-caps whose "revenue" was one
    liquidation. It was also sinking genuinely emerging projects, which is the
    opposite of what a gem screener is for: Pons showed $18M in 30 days — a
    quarter of its whole sector — tripling month over month, and sat at row 69
    of 104 next to dead shells, on the sole grounds of being 57 days old.

    So short history gets its own status instead of being lumped in with
    collapse and micro-caps: unproven, ranked on merit, and badged as unproven
    rather than quietly demoted."""
    if e.get("reliable"):
        return False
    fails = set(e.get("reliable_fail") or [])
    if fails - {"krátká historie"}:
        return False                      # something other than youth is wrong
    if (e.get("mcap") or 0) < YOUNG_MIN_MCAP:
        return False
    size = e.get("rev30d") if e.get("primary") == "rev" else e.get("stables_now")
    if (size or 0) < YOUNG_MIN_REV30:
        return False
    if ((e.get("growth6m") or {}).get("g") or 0) <= 0:
        return False
    # the months it does have must not be rolling over
    months = [m["v"] for m in (e.get("monthly") or e.get("monthly_stables") or [])
              if not m.get("partial")]
    if len(months) >= 2 and months[-1] < months[-2]:
        return False
    return True


def upside_tier(u, reliable, young=False):
    """Five hard steps. An unreliable row is capped at 3 so it can never sit in
    the coloured band; a merely YOUNG row keeps its tier but is ranked in its
    own band between reliable and unreliable."""
    if u is None:
        return 0
    t = 5 if u >= 10 else 4 if u >= 5 else 3 if u >= 2.5 else 2 if u >= 1.2 else 1
    if reliable or young:
        return t
    return min(t, 3)


def apply_valuation(entities, bench_mult, now):
    """potential = how many times could this re-rate to the benchmark's multiple,
    with revenue/adoption held still. Capped for display, kept raw for strength."""
    for e in entities:
        mult = e.get("ps")
        if not bench_mult or not mult or mult <= 0:
            e["potential"], e["potential_raw"] = None, None
        else:
            raw = bench_mult / mult
            e["potential_raw"] = round(raw, 3)
            e["potential"] = round(min(UPSIDE_CAP, raw), 3)
        ok, fails = reliability(e, now)
        e["reliable"] = ok
        e["reliable_fail"] = fails
        e["young"] = is_young(e)
        e["tier"] = upside_tier(e.get("potential"), ok, e["young"])


FDV_SANE = 0.98     # an FDV below this share of mcap is a CoinGecko data error


def apply_reframe(ctx, apps, chains, bench, bench_chains):
    """Potenciál restated in money, and corrected for dilution. Formula unchanged.

    A degen reads "39×" as a price target. `mcap_at_bench` / `price_at_bench`
    say what it really is: the market cap and price at which the row would
    carry the benchmark's multiple — "$12M -> $480M", and the "strop podle HL"
    the Start card quotes as a take-profit reference. Computed exactly as
    multiple × base (run-rate for apps, stablecoins for chains): going through
    the stored potential, rounded to three decimals, was off by up to 0,7 % on
    cheap rows. A row at the 50× display cap reads "more than 50×", never as
    a 209× price target.

    `potential_fdv` puts the row and the benchmark on the same fully diluted
    basis; `potential_fdv_shown = min(potential, potential_fdv)` because
    dilution can only LOWER the figure. Uncapped, a fully circulating coin would
    be credited for Hyperliquid's own future dilution and read 70× where it
    reads 16× today — the same trap, with a bigger number."""
    for pool, bm, base_of in (
            (apps, bench.get("mult"), lambda e: (e.get("runrate") or {}).get("value")),
            (chains, bench_chains.get("mult"), lambda e: e.get("stables_now"))):
        for e in pool:
            mc, base = e.get("mcap"), base_of(e)
            e["mcap_at_bench"] = e["price_at_bench"] = None
            e["bench_capped"] = False
            if e.get("potential") is None or not (mc and bm and base):
                continue
            capped = (e.get("potential_raw") or 0) >= UPSIDE_CAP
            m = UPSIDE_CAP * mc if capped else bm * base
            e["mcap_at_bench"] = round(m, 2)
            e["price_at_bench"] = float("%.6g" % (e["price"] * m / mc)) if e.get("price") else None
            e["bench_capped"] = capped
    fm = bench.get("fdv_mult")
    bad = []
    for e in apps:
        e["potential_fdv"] = e["potential_fdv_shown"] = e["float_worse"] = None
        fdv, mc = e.get("fdv"), e.get("mcap")
        rr = (e.get("runrate") or {}).get("value")
        if e.get("potential_raw") is None or not (fdv and mc and rr and rr > 0 and fm):
            continue
        if fdv < FDV_SANE * mc:
            bad.append(e["name"])
            continue
        raw = fm / (fdv / rr)
        e["potential_fdv"] = round(raw, 3)
        e["potential_fdv_shown"] = round(min(e["potential"], raw), 3)
        # the coin dilutes more than the benchmark does
        e["float_worse"] = raw < e["potential_raw"]
    if bad:
        # a data-quality note, not a failed request: logged, kept off the page's
        # "neúplná data" chip, which means "an API call failed"
        ctx.log("  FDV pod market capem (chyba dat CoinGecka), bez FDV potenciálu: %d — %s"
                % (len(bad), ", ".join(bad[:8])))


# ---------------------------------------------------------------- Test 30×
TEST_MULT = 30
# "ladder": the biggest direct rival (same DeFiLlama category, another token);
# only a category leader is measured against the biggest coin of its theme.
# "larger_of" (the bigger of the two, always) was rejected: HYPE ($21 bn, in the
# DEX basket) and ZEC ($25 bn) let almost any DEX or privacy app pass.
SIZE_CEILING_RULE = "ladder"


def size_ceiling(e, peers, basket, rule=SIZE_CEILING_RULE):
    """(mcap, name, kind) the row would have to outgrow at TEST_MULT×, or Nones."""
    mc = e.get("mcap") or 0
    g = e.get("gecko_id")
    cat = max((p for p in peers if p is not e and p.get("gecko_id") != g and p.get("mcap")),
              key=lambda p: p["mcap"], default=None)
    th = max((m for m in basket if m.get("id") != g and m.get("mcap")),
             key=lambda m: m["mcap"], default=None)
    cat_c = (cat["mcap"], cat["name"], "category") if cat else None
    th_c = (th["mcap"], th.get("sym") or th.get("name") or th["id"], "theme") if th else None
    if rule == "larger_of":
        opts = [c for c in (cat_c, th_c) if c]
        return max(opts, key=lambda c: c[0]) if opts else (None, None, None)
    if cat_c and cat_c[0] >= mc:
        return cat_c
    return th_c or (None, None, None)


def apply_test30(apps, chains, themes_out, rule=SIZE_CEILING_RULE):
    """Test 30×: would thirty times today's market cap outgrow the biggest
    direct rival? A reality check on size, not a forecast.

    Pons at 30× is $13 bn while Pump, the biggest launchpad, is $2,1 bn; Pump at
    30× would be four DOGEs. `room_x` is how far the row is from the ceiling
    ("do velikosti Pumpu 4,8×"). The valuation half — would it still be no
    pricier than Hyperliquid after 30× — is text only: as a gate it would
    empty the list (4 trusted apps pass it today)."""
    members = {th.get("key"): th.get("members") or [] for th in themes_out or []}
    for pool in (apps, chains):
        by_cat = {}
        for e in pool:
            by_cat.setdefault(e.get("category"), []).append(e)
        for e in pool:
            tk = (e.get("theme") or {}).get("key")
            ceil, name, kind = size_ceiling(e, by_cat.get(e.get("category")) or [],
                                            members.get(tk) or [], rule)
            mc = e.get("mcap")
            implied = TEST_MULT * mc if mc else None
            pr, pfs = e.get("potential_raw"), e.get("potential_fdv_shown")
            e["test30"] = {
                "mult": TEST_MULT,
                "implied": round(implied, 2) if implied else None,
                "ceiling": round(ceil, 2) if ceil else None,
                "ceiling_name": name, "ceiling_kind": kind,
                "size_ok": (implied <= ceil) if (implied and ceil) else None,
                # significant digits: Hyperliquid's room is 0,2587x, Gains' 1926x
                "room_x": float("%.4g" % (ceil / mc)) if (ceil and mc) else None,
                "val_ok": (pr >= TEST_MULT) if pr is not None else None,
                "val_ok_fdv": (pfs >= TEST_MULT) if pfs is not None else None,
            }


# ---------------------------------------------------------------- buy side: risk tags
# Owner decision (2026-09-22): float, unlocks and liquidity are SHOWN as tags and
# text; none of them excludes a row from any list or enters any sort. (Liquidity
# becomes a gate only inside the degen selection, where "can I get in and out"
# is part of the question.) Thresholds are chosen so a tag means something: at
# 50 % circulating, 24 of the 63 trusted rows would carry a float tag.
FLOAT_TAG = 0.25        # circulating share (mcap / FDV) under which "Odemčeno X %"
UNLOCK90_TAG = 10.0     # % of today's unlocked supply added within 90 days
CLIFF_DAYS = 60         # a cliff this close …
CLIFF_MIN = 3.0         # … and at least this big (% of unlocked supply)


def apply_risks(rows):
    """`risks`: codes the viewer turns into tags, each explained with the row's
    own numbers. A cliff that already accounts for most of the 90-day unlock
    is not tagged twice."""
    for e in rows:
        r = []
        if e.get("fdv") and e.get("mcap") and e["mcap"] / e["fdv"] < FLOAT_TAG:
            r.append("float")
        u = e.get("unlock") or {}
        c = u.get("next_cliff") or {}
        cliff = (c.get("days") is not None and c["days"] <= CLIFF_DAYS
                 and (c.get("pct_of_circ") or 0) >= CLIFF_MIN)
        if cliff:
            r.append("cliff")
        u90 = u.get("unlock90_pct") or 0
        if u90 >= UNLOCK90_TAG and (not cliff or u90 >= (c.get("pct_of_circ") or 0) + UNLOCK90_TAG):
            r.append("unlock90")
        if (e.get("liq") or {}).get("ok") is False:
            r.append("thin")
        e["risks"] = r


# ---------------------------------------------------------------- the degen selection
# Seven explicit gates, each with its own reason string, applied in this order.
# A FILTER, never a score (Gem Score died once): the selection is ranked by
# potential_raw alone, like the Apps table. Float, unlocks and the holders'
# share are shown on the cards but are never gates (Adam, 2026-09-22).
DEGEN_MIN_REV30 = 100_000        # the Apps table's default floor
DEGEN_MIN_POTENTIAL = 2.5        # the coloured band (tier >= 3)
DEGEN_SHORTLIST = 10
DEGEN_NEAR = 6
DEGEN_REASONS = ("malý byznys", "neprověřené", "drahé", "moc velký", "bez srovnání",
                 "byznys neroste", "mělká likvidita", "likvidita neznámá",
                 "téma bez větru", "bez tématu")
# a near miss must first be a real candidate: proven (or merely new), big
# enough and cheap — or Pharaoh at 209x would headline "Těsně neprošly"
NEAR_REQUIRES = {"malý byznys", "neprověřené", "drahé"}


def degen_fails(e):
    f = []
    if (e.get("rev30d") or 0) < DEGEN_MIN_REV30:
        f.append("malý byznys")
    if not (e.get("reliable") or e.get("young")):
        f.append("neprověřené")
    if e.get("potential") is None or e["potential"] < DEGEN_MIN_POTENTIAL:
        f.append("drahé")
    size_ok = (e.get("test30") or {}).get("size_ok")
    if size_ok is False:
        f.append("moc velký")
    elif size_ok is None:
        f.append("bez srovnání")
    g = (e.get("growth6m") or {}).get("g")
    if (e.get("traj") or {}).get("phase") in ("Pokles", "Stagnace") or g is None or g <= 0:
        f.append("byznys neroste")
    ok = (e.get("liq") or {}).get("ok")
    if ok is False:
        f.append("mělká likvidita")
    elif ok is None:
        f.append("likvidita neznámá")
    t = e.get("theme")
    if not t:
        f.append("bez tématu")
    elif not (t.get("tier") == 5 or set(t.get("tags") or []) & {"leads", "fund_up"}):
        f.append("téma bez větru")
    return f


def exit_flags(e):
    """The three "Kdy prodat" rules, per row: priced above the benchmark
    multiple, the business stopped growing, the theme fell behind BTC."""
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


def degen_version():
    """Stamped on every picks-ledger line. It covers the theme join too: which
    theme a row gets decides two gates (theme, Test 30× ceiling), so the
    2026-09-23 ladder that gave the 67 themeless apps a theme is a new cohort."""
    raw = json.dumps([DEGEN_MIN_REV30, DEGEN_MIN_POTENTIAL, TEST_MULT, SIZE_CEILING_RULE,
                      liquidity.TICKET, liquidity.MAX_IMPACT_PCT, liquidity.VOL_PASS,
                      DEGEN_REASONS, themes.row_join_version()], ensure_ascii=False)
    import hashlib
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def apply_degen(apps, chains, stale_theme, prev=None):
    """degen_ok / degen_fail on every app (chains: None — their multiple is
    against the median chain, a weaker yardstick), plus the snapshot block the
    Start tab reads."""
    for e in apps:
        e["degen_fail"] = degen_fails(e)
        e["degen_ok"] = not e["degen_fail"]
        e["exit_flags"] = exit_flags(e)
    for e in chains:
        e["degen_fail"], e["degen_ok"], e["exit_flags"] = [], None, exit_flags(e)

    def rank(rows):
        return [e.get("key") or e.get("slug") for e in
                sorted(rows, key=lambda e: -(e.get("potential_raw") or 0))]

    ok = [e for e in apps if e["degen_ok"] and e.get("potential_raw") is not None]
    near = [e for e in apps if len(e["degen_fail"]) == 1
            and e["degen_fail"][0] not in NEAR_REQUIRES and e.get("potential_raw") is not None]
    hist = {r: sum(1 for e in apps if r in e["degen_fail"]) for r in DEGEN_REASONS}
    shortlist = rank(ok)[:DEGEN_SHORTLIST]
    before = ((prev or {}).get("degen") or {}).get("shortlist") or []
    val30 = sum(1 for e in apps if (e.get("reliable") or e.get("young"))
                and (e.get("test30") or {}).get("val_ok"))
    return {"gates_version": degen_version(), "n_ok": len(ok), "n_total": len(apps),
            "fail_hist": hist, "shortlist": shortlist, "near": rank(near)[:DEGEN_NEAR],
            "val30_trusted": val30, "stale_theme": bool(stale_theme),
            "changes": {"entered": [k for k in shortlist if k not in before],
                        "left": [k for k in before if k not in shortlist]} if before else None,
            "rules": {"min_rev30": DEGEN_MIN_REV30, "min_potential": DEGEN_MIN_POTENTIAL,
                      "shortlist": DEGEN_SHORTLIST}}


# ---------------------------------------------------------------- picks ledger
# The forward test: every refresh appends the selection with its prices, and
# nothing is ever deleted — a pick that later disappears from the universe is
# priced from coins.llama.fi, so the record cannot quietly shed its losers.
LEDGER_NAME = "picks_ledger.jsonl"
LEDGER_DEDUP = 20 * 3600
LEDGER_READY_DAYS = 28


def read_ledger(ctx):
    path = os.path.join(ctx.data_dir, LEDGER_NAME)
    out = []
    try:
        with io.open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        out.append(json.loads(line))
                    except ValueError:
                        ctx.warn("záznam tipů: poškozený řádek přeskočen")
    except FileNotFoundError:
        pass
    return out


def ledger_summary(ctx, lines, rows, btc_now, now):
    """Median performance of each past selection vs BTC, from today's prices."""
    if not lines:
        return {"since": None, "cohorts": [], "ready": False, "n_lines": 0}
    price = {e.get("gecko_id"): e.get("price") for e in rows if e.get("gecko_id") and e.get("price")}
    missing = sorted({p["gecko_id"] for ln in lines for p in ln.get("picks") or []
                      if p.get("gecko_id") and p["gecko_id"] not in price})
    if missing:
        q = ",".join("coingecko:%s" % g for g in missing)
        d = ctx.get("https://coins.llama.fi/prices/current/%s" % urllib.parse.quote(q, safe=",:"),
                    timeout=40) or {}
        for k, v in (d.get("coins") or {}).items():
            if v.get("price"):
                price[k.split(":", 1)[1]] = float(v["price"])
    cohorts = []
    for ln in lines:
        rel = []
        for p in ln.get("picks") or []:
            p_now = price.get(p.get("gecko_id"))
            if p.get("price") and ln.get("btc") and btc_now:
                # a pick with no price anywhere today counts as a total loss
                r = (p_now / p["price"] if p_now else 0.0) / (btc_now / ln["btc"])
                rel.append(r - 1)
        rel.sort()
        med = (rel[len(rel) // 2] if len(rel) % 2 else (rel[len(rel) // 2 - 1] + rel[len(rel) // 2]) / 2) if rel else None
        cohorts.append({"ts": ln["ts"], "n": len(rel), "median_vs_btc": round(med, 4) if med is not None else None,
                        "best": round(max(rel), 4) if rel else None, "worst": round(min(rel), 4) if rel else None,
                        "gates_version": ln.get("gates_version")})
    since = lines[0]["ts"]
    return {"since": since, "cohorts": cohorts[-12:], "n_lines": len(lines),
            "ready": now - since >= LEDGER_READY_DAYS * DAY}


def append_ledger(ctx, lines, degen, rows, btc, now):
    picks = [e for e in rows if (e.get("key") or e.get("slug")) in set(degen.get("shortlist") or [])]
    keyset = sorted(e.get("key") or e.get("slug") for e in picks)
    last = lines[-1] if lines else None
    if last and now - last.get("ts", 0) < LEDGER_DEDUP and \
            sorted(p["key"] for p in last.get("picks") or []) == keyset:
        return False
    line = {"ts": now, "gates_version": degen.get("gates_version"), "btc": btc,
            "picks": [{"key": e.get("key") or e.get("slug"), "gecko_id": e.get("gecko_id"),
                       "name": e.get("name"), "price": e.get("price"), "mcap": e.get("mcap"),
                       "potential_raw": e.get("potential_raw"),
                       "potential_fdv": e.get("potential_fdv")} for e in picks]}
    with io.open(os.path.join(ctx.data_dir, LEDGER_NAME), "a", encoding="utf-8") as f:
        f.write(json.dumps(line, ensure_ascii=False, separators=(",", ":")) + "\n")
    return True


def score_entity(ctx, e, kind):
    e["rev_growth"] = window_growth(e["rev_series"]) if e["rev_series"] else {}
    e["tvl_growth"] = window_growth(e["tvl_series"]) if e["tvl_series"] else {}
    mc = ctx.mcap_by_id.get(e["gecko_id"], {})
    e["mcap"] = mc.get("mcap")
    e["fdv"] = mc.get("fdv")
    e["price"] = mc.get("price")
    e["price_chg_24h_pct"] = mc.get("price_chg_24h_pct")
    e["symbol"] = mc.get("symbol")
    e["cg"] = mc.get("cg")

    # Apps are judged on revenue (a flow -> sum per week), chains on adoption
    # via stablecoin supply (a stock -> average per week). One metric each.
    e["primary"] = "rev" if kind == "app" else "tvl"
    if kind == "app":
        e["traj"] = trajectory(e["rev_series"], agg="sum")
    else:
        e["traj"] = trajectory(e["tvl_series"], agg="mean")
    if kind == "chain":
        # Size and the MC/TVL multiple stay on real TVL, not the adoption proxy.
        raw = e.get("raw_tvl_series") or []
        e["tvl_now"] = raw[-1][1] if raw else None
        e["adoption_now"] = e["tvl_series"][-1][1] if e["tvl_series"] else None

    e.pop("members", None)
    return e


# ------------------------------------------------- dominance inside the sector
def add_sector_share(entities, metric_key, by_category=True):
    """What slice of its arena does this project take, per window?
    Lets a declining giant still read as a giant.

    Apps compete inside their category (Dexs vs Dexs). Chains are pooled into
    one arena instead: their 'category' is the VM family, and Ethereum's share
    of EVM is so total that every other chain rounded to 0%."""
    for w in WINDOWS:
        wk = str(w)
        totals = {}
        for e in entities:
            key = (e.get("category") or "Other") if by_category else "_all"
            v = max(0.0, ((e.get(metric_key) or {}).get(wk) or {}).get("total") or 0)
            totals[key] = totals.get(key, 0.0) + v
        for e in entities:
            key = (e.get("category") or "Other") if by_category else "_all"
            v = max(0.0, ((e.get(metric_key) or {}).get(wk) or {}).get("total") or 0)
            tot = totals.get(key, 0.0)
            e.setdefault("share", {})[wk] = round(100.0 * v / tot, 2) if tot > 0 else None


# ---------------------------------------------------------------- sector aggregates
def sum_series(series_list):
    """Add daily series together on their shared calendar, oldest first."""
    acc = {}
    for s in series_list:
        for t, v in (s or []):
            acc[t] = acc.get(t, 0.0) + (v or 0.0)
    return [[t, acc[t]] for t in sorted(acc)]


def build_sectors(entities, series_key, label_key="category", stock=False):
    """Sector growth is measured on the sector's TOTAL series, not on the median
    of its members' growth rates.

    "Is the pie growing?" is a question about the pie, so the right operation is
    a sum. A median of per-project rates needed a big sample to mean anything,
    which forced an n>=5 cut-off that deleted real sectors (Physical TCG) — and
    it weighted a $40k protocol the same as a $400M one. Summing works honestly
    at n=1, is size-weighted by construction, and answers the actual question.
    Breadth is reported alongside it so one giant carrying a dying sector is
    still visible."""
    by_cat = {}
    for e in entities:
        by_cat.setdefault(e.get(label_key) or "Other", []).append(e)

    out = []
    for cat, ents in by_cat.items():
        agg = sum_series([e.get(series_key) for e in ents])
        agg_growth = window_growth(agg) if agg else {}
        row = {
            "category": cat,
            "n": len(ents),
            "total_revenue_30d": round(sum((e["rev_growth"].get("30", {}).get("total") or 0)
                                           for e in ents), 2),
            "members": sorted((e["name"] for e in ents))[:12],
        }
        for w in WINDOWS:
            wk = str(w)
            d = agg_growth.get(wk) or {}
            row["g_%s" % wk] = d.get("g")
            row["r2_%s" % wk] = d.get("r2")
            row["total_%s" % wk] = d.get("total")
            # Revenue is a flow, so its window total is the sector's size.
            # TVL/stablecoins are a stock — summing 365 daily balances is
            # meaningless, so size there is the average level over the window.
            days = d.get("days") or 0
            row["size_%s" % wk] = (round(d["total"] / days, 2)
                                   if stock and days and d.get("total") is not None
                                   else d.get("total"))
            # How widely is that growth shared? One winner masking nine losers
            # reads very differently from a sector rising together.
            gs = [e[series_key.replace("_series", "_growth")].get(wk, {}).get("g")
                  for e in ents]
            gs = [g for g in gs if g is not None]
            row["breadth_%s" % wk] = (round(100.0 * sum(1 for g in gs if g > 0) / len(gs), 1)
                                      if gs else None)
            row["rated_%s" % wk] = len(gs)
        out.append(row)
    out.sort(key=lambda r: -(r.get("g_365") if r.get("g_365") is not None else -999))
    return out


# ================================================================ sectors v11
# "Is the pie growing?" has to be asked about the WHOLE pie. v10 summed only the
# tokenized survivors above the floor, so Robinhood Chain, Privacy Cash and 218
# other adapters never entered the answer.
SECTOR_SKIP_CATEGORIES = {
    # $687M/30d from five adapters (Tether, Circle) — 57.9% of the entire
    # universe. Left in, every sector share and every 6-month shift in share is
    # noise around Tether rather than a fact about the sector.
    "Stablecoin Issuer",
}
SECTOR_SMALL_USD_30D = 1_000_000   # below this a sector is listed, but greyed


def sector_universe(ctx):
    """Every fee adapter above the floor, whether or not it has a token."""
    out = []
    for e in ctx.fee_protocols:
        if e.get("protocolType") != "protocol":
            continue
        if (e.get("total30d") or 0) < COLLECTION_FLOOR_USD_30D:
            continue
        if e.get("doublecounted"):
            continue
        cat = e.get("category") or "Other"
        if cat in SECTOR_SKIP_CATEGORIES:
            continue
        out.append({
            "slug": e.get("slug") or slugify(e["name"]),
            "name": e["name"],
            "category": cat,
            "total30d": e.get("total30d") or 0,
            "tokenized": bool(gecko_for_app(ctx, e)),
        })
    return out


def _window_total(series, days, end):
    lo = end - days * DAY
    return sum(v for t, v in series if lo < t <= end)


def build_sectors_v11(ctx):
    """Sector rows from the full universe. Member series are summed and then
    thrown away — only the sector total is stored, which keeps the snapshot
    small while still letting the audit recompute every number offline."""
    members = sector_universe(ctx)
    ctx.log("sector universe: %d adapters (%d without a token), fetching series ..."
            % (len(members), sum(1 for m in members if not m["tokenized"])))

    def fetch_one(m, warn=True):
        d = ctx.get(BASE + "/summary/fees/%s?dataType=dailyRevenue"
                    % urllib.parse.quote(m["slug"]), warn=warn)
        # None = the request failed; {} with no chart = the adapter has no data.
        # Only the first is worth retrying.
        return m, d, ((d or {}).get("totalDataChart") or [])[-MAX_SERIES_DAYS:]

    results = {}
    failed = []
    with cf.ThreadPoolExecutor(max_workers=WORKERS) as ex:
        # quiet: every failure here gets the slow second pass below, which
        # warns about whatever is still missing after it
        for fut in cf.as_completed([ex.submit(fetch_one, m, False) for m in members]):
            try:
                m, d, series = fut.result()
            except Exception:
                continue
            results[m["slug"]] = (m, series)
            if d is None:
                failed.append(m)
    # 514 requests in one burst trips DeFiLlama's own rate limiter (seen
    # 2026-09-22: 70 adapters came back 429). A missing adapter silently
    # shrinks its sector's revenue, so the failures get a second, slow pass.
    if failed:
        ctx.log("sector series: %d requests failed, retrying slowly ..." % len(failed))
        time.sleep(20)
        still = []
        for i, m in enumerate(failed):
            _, d, series = fetch_one(m)
            if d is None:
                still.append(m["name"])
            else:
                results[m["slug"]] = (m, series)
            time.sleep(0.6)
        if still:
            ctx.warn("sector series: %d adapters still unreachable — their sectors are "
                     "understated: %s" % (len(still), ", ".join(still[:10])))
    by_cat = {}
    got = 0
    for m, series in results.values():
        if series:
            got += 1
        by_cat.setdefault(m["category"], []).append((m, series))
    ctx.log("sector series: %d/%d adapters returned data" % (got, len(members)))

    end = max((s[-1][0] for ents in by_cat.values() for _, s in ents if s),
              default=int(time.time()))
    rows = []
    for cat, ents in by_cat.items():
        agg = sum_series([s for _, s in ents])
        if not agg:
            continue
        g6 = growth6m(agg, agg="sum")
        now30 = _window_total(agg, 30, end)
        prev30 = _window_total(agg, 30, end - 30 * DAY)
        then30 = _window_total(agg, 30, end - 182 * DAY)
        member_g = [growth6m(s, agg="sum")["g"] for _, s in ents if s]
        member_g = [g for g in member_g if g is not None]
        rows.append({
            "category": cat,
            "n_all": len(ents),
            "n_tok": sum(1 for m, _ in ents if m["tokenized"]),
            "rev30d": round(now30, 2),
            "rev30d_prev": round(prev30, 2),
            "rev30d_6m_ago": round(then30, 2),
            "mom_pct": round(100.0 * (now30 - prev30) / prev30, 1) if prev30 > 0 else None,
            "g6m": g6["g"], "r2_6m": g6["r2"],
            "breadth6m_pct": (round(100.0 * sum(1 for g in member_g if g > 0) / len(member_g), 1)
                              if member_g else None),
            "rated": len(member_g),
            "monthly": monthly_buckets(agg, 13, agg="sum"),
            "series": clean_series(agg),
            "members_top": [m["name"] for m, _ in
                            sorted(ents, key=lambda x: -(x[0]["total30d"] or 0))[:8]],
        })

    total_now = sum(r["rev30d"] for r in rows) or 1.0
    total_then = sum(r["rev30d_6m_ago"] for r in rows) or 1.0
    for r in rows:
        share_now = 100.0 * r["rev30d"] / total_now
        share_then = 100.0 * r["rev30d_6m_ago"] / total_then
        r["share_pct"] = round(share_now, 2)
        # A sector taking share from the rest is the definition of "trending",
        # and unlike raw growth it cannot be faked by the whole market rising.
        r["share_d6m_pp"] = round(share_now - share_then, 2)
        r["small"] = r["rev30d"] < SECTOR_SMALL_USD_30D
    rows.sort(key=lambda r: -(r["g6m"] if r["g6m"] is not None else -999))
    ctx.log("sectors: %d kategorii, %d malych (<$1M/30d), celkem $%.0fM/30d"
            % (len(rows), sum(1 for r in rows if r["small"]), total_now / 1e6))
    return rows


# ---------------------------------------------------------------- v11 assembly
def app_measures(e, now):
    """Everything an app row derives from its own revenue series and mcap.

    A pure function of the row and `now`, so backtest.py can call it on a
    series cut off at any past date and get what the screener would have shown
    then."""
    s = e.get("rev_series") or []
    e["hist_days"] = int(round((s[-1][0] - s[0][0]) / float(DAY))) if len(s) > 1 else 0
    e["lag_days"] = round((now - s[-1][0]) / float(DAY), 1) if s else None
    e["rev30d"] = round(sum(v for t, v in s if t > s[-1][0] - 30 * DAY), 2) if s else 0.0
    e["runrate"] = runrate(s)
    e["growth6m"] = growth6m(s, agg="sum")
    e["monthly"] = monthly_buckets(s, 13, agg="sum")
    rr = e["runrate"]["value"]
    e["ps"] = round(e["mcap"] / rr, 3) if (e.get("mcap") and rr and rr > 0) else None
    # Share of revenue that reaches token holders (buybacks, burns, staking
    # payouts), from DeFiLlama's own 30-day totals so numerator and
    # denominator share a definition. Capped at 1: a few adapters book
    # incentives as holder revenue that were never protocol revenue.
    base = e.get("total30d") or 0
    e["holders_share"] = (round(min(1.0, (e.get("holders30d") or 0) / base), 4)
                          if (e.get("holders_leaves") and base > 0) else None)
    return e


def compute_metrics(ctx, apps, chains):
    """Everything the v11 viewer reads, computed once, here.

    The order matters: per-entity measures first, then price history (one batch
    for every token at once), then the benchmark, which is itself one of the
    entities and so can only be known after they are all measured."""
    now = int(time.time())

    ctx.log("computing app metrics ...")
    for e in apps:
        app_measures(e, now)

    ctx.log("computing chain adoption index ...")
    for e in chains:
        stables = e.get("tvl_series") if e.get("adoption_metric") == "stablecoins" else []
        dex_roll = rolling_sum(e.get("dex_series") or [], 30)
        end = max([s[-1][0] for s in (stables, dex_roll) if s] or [now])
        idx = adoption_index([("stables", stables), ("dex", dex_roll)], end)
        e["adoption_index"] = idx
        e["stables_now"] = stables[-1][1] if stables else None
        e["hist_days"] = (int(round((stables[-1][0] - stables[0][0]) / float(DAY)))
                          if len(stables) > 1 else 0)
        e["lag_days"] = round((now - stables[-1][0]) / float(DAY), 1) if stables else None
        e["monthly_stables"] = monthly_buckets(stables, 13, agg="mean")
        e["monthly_dex"] = monthly_buckets(e.get("dex_series") or [], 13, agg="sum")
        if idx:
            e["growth6m"] = growth6m(idx["series"], agg="mean")
            e["traj"] = trajectory(idx["series"], agg="mean")
        else:
            # No six-month baseline in either component (Canton 124d, Quai 59d).
            # Saying "—" is honest; inventing a trend from 8 weeks is not.
            e["growth6m"] = {"g": None, "r2": None, "weeks": 0, "days": 0, "label": "6M"}
            e["traj"] = {"periods": {}, "phase": "Nový", "hs": None,
                         "recent": None, "baseline": None, "accel": None}
        st = e.get("stables_now") or 0
        e["ps"] = (round(e["mcap"] / st, 3)
                   if (e.get("mcap") and st >= CHAIN_STABLE_FLOOR) else None)
        # A second opinion shown next to the adoption multiple, never ranked on.
        # DeFiLlama's chain "revenue" is the part of fees the chain keeps or burns
        # — not the revenue of apps running on it — annualised exactly like an
        # app's run-rate. Deliberately NOT stored as "runrate": the panel prints
        # the run-rate basis line for any entity that has one.
        e["fee_runrate"] = runrate(e.get("rev_series") or [])
        fv = e["fee_runrate"]["value"]
        e["ps_fees"] = round(e["mcap"] / fv, 3) if (e.get("mcap") and fv and fv > 0) else None

    ids = sorted({e["gecko_id"] for e in apps + chains if e.get("gecko_id")})
    prices = fetch_price_history(ctx, ids, now)

    for e in apps:
        e["sila6m"] = strength(e.get("rev_series") or [], prices.get(e["gecko_id"]) or [],
                               end=now, measure="runrate")
    for e in chains:
        base = e.get("tvl_series") if e.get("adoption_metric") == "stablecoins" else []
        e["sila6m"] = (strength(base, prices.get(e["gecko_id"]) or [], end=now, measure="level")
                       if e.get("adoption_index") else
                       {"ratio": None, "k": 0, "rev_factor": None,
                        "price_factor": None, "points": []})

    # Benchmark: Hyperliquid is the yardstick the user picked, on the same
    # run-rate basis as everyone else. Median is the fallback if it ever drops
    # out of the universe.
    app_mults = [e["ps"] for e in apps if e.get("ps") and e["ps"] > 0]
    hl = next((e for e in apps if (e.get("name") or "").strip().lower() == "hyperliquid"), None)
    if hl and hl.get("ps") and hl["ps"] > 0:
        bench = {"label": "Hyperliquid", "mult": hl["ps"], "basis": hl["runrate"]["basis"],
                 "mcap": hl.get("mcap"), "rr": hl["runrate"]["value"]}
    else:
        bench = {"label": "medián appek", "mult": median(app_mults) if app_mults else None,
                 "basis": "med", "mcap": None, "rr": None}
    # The same yardstick on FULLY DILUTED value, so a low-float coin can be set
    # against the benchmark on one basis. Hyperliquid itself has FDV ~4x its
    # mcap: dividing a coin's FDV multiple into HL's CIRCULATING multiple (the
    # first draft of the degen plan) made the benchmark 4x overpriced against
    # itself and quoted "up" at 1,6x instead of 6,9x.
    hl_rr = ((hl or {}).get("runrate") or {}).get("value")
    if bench["label"] == "Hyperliquid" and hl.get("fdv") and hl_rr:
        bench["fdv"] = hl["fdv"]
        bench["fdv_mult"] = round(hl["fdv"] / hl_rr, 3)
    else:
        fdv_mults = [e["fdv"] / e["runrate"]["value"] for e in apps
                     if e.get("fdv") and (e.get("runrate") or {}).get("value")]
        bench["fdv"] = None
        bench["fdv_mult"] = round(median(fdv_mults), 3) if fdv_mults else None

    chain_mults = [e["ps"] for e in chains if e.get("ps") and e["ps"] > 0]
    bench_chains = {"label": "medián chainů",
                    "mult": median(chain_mults) if chain_mults else None,
                    "basis": "mcap/stablecoiny"}

    apply_valuation(apps, bench["mult"], now)
    apply_valuation(chains, bench_chains["mult"], now)
    apply_reframe(ctx, apps, chains, bench, bench_chains)

    # The fee check, against the median chain on the same basis. Plasma is why it
    # exists: 12.9x on stablecoins parked there, ~0.5x on what the chain earns.
    fee_mults = [e["ps_fees"] for e in chains if e.get("ps_fees") and e["ps_fees"] > 0]
    bench_chains["fee_mult"] = median(fee_mults) if fee_mults else None
    for e in chains:
        m, fb = e.get("ps_fees"), bench_chains["fee_mult"]
        raw = fb / m if (m and m > 0 and fb) else None
        e["potential_fees_raw"] = round(raw, 3) if raw is not None else None
        e["potential_fees"] = round(min(UPSIDE_CAP, raw), 3) if raw is not None else None

    ctx.log("benchmark: %s %.1fx (%s) | chains %s %.1fx, on fees %.0fx"
            % (bench["label"], bench["mult"] or 0, bench["basis"],
               bench_chains["label"], bench_chains["mult"] or 0, bench_chains["fee_mult"] or 0))
    rel = sum(1 for e in apps if e.get("reliable"))
    t5 = sum(1 for e in apps if e.get("tier") == 5)
    ctx.log("apps: %d/%d spolehlivych, %d v tier 5" % (rel, len(apps), t5))
    return bench, bench_chains


# ---------------------------------------------------------------- write snapshot
def clean_series(series):
    return [[int(ts), round(float(v), 2)] for ts, v in series]


def write_snapshot(ctx, snapshot):
    """Write via a temp file so a reader never sees a half-written snapshot.

    os.replace is atomic, but on Windows it raises PermissionError if anything
    still holds the target open — Defender scans freshly written files — so it
    is retried a few times."""
    path = os.path.join(ctx.data_dir, SNAPSHOT_NAME)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, separators=(",", ":"), ensure_ascii=False)
    for attempt in range(5):
        try:
            os.replace(tmp, path)
            return path
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(0.2)
    return path


# ---------------------------------------------------------------- the run
def run(log=None, data_dir=None):
    """Collect everything and write snapshot.json. Returns the snapshot dict."""
    ctx = Ctx(log=log, data_dir=data_dir)
    t_start = time.time()

    fetch_bulk(ctx)
    apps_candidates, chain_candidates = build_candidates(ctx)
    apps_out, chains_out = fetch_all_series(ctx, apps_candidates, chain_candidates)
    fetch_market_caps(ctx, apps_out + chains_out)
    fetch_all_logos(ctx, apps_out, chains_out)
    apps_out, chains_out = drop_untradeable(ctx, apps_out, chains_out)

    ctx.log("scoring entities ...")
    apps_scored = [score_entity(ctx, e, "app") for e in apps_out]
    chains_scored = [score_entity(ctx, e, "chain") for e in chains_out]

    # The buy side. Either source failing costs its own column ("neznámá"),
    # never the refresh.
    now_ts = int(time.time())
    liquidity_meta = unlocks_meta = None
    try:
        liquidity_meta = liquidity.build_liquidity(ctx, apps_scored + chains_scored, now_ts)
    except Exception as exc:
        ctx.warn("likvidita selhala: %s" % exc)
        for e in apps_scored + chains_scored:
            e["liq"] = None
    try:
        unlocks_meta = unlocks.build_unlocks(ctx, apps_scored, now_ts)
    except Exception as exc:
        ctx.warn("unlocky selhaly: %s" % exc)
        for e in apps_scored:
            e["unlock"] = None
    apply_risks(apps_scored + chains_scored)

    # Apps compete on revenue inside their category, chains on adoption across all.
    add_sector_share(apps_scored, "rev_growth", by_category=True)
    add_sector_share(chains_scored, "tvl_growth", by_category=False)

    bench, bench_chains = compute_metrics(ctx, apps_scored, chains_scored)

    # Sectors come from the FULL universe (untokenized included), chains stay on
    # the same adoption index their rows are judged by.
    sectors_apps = build_sectors_v11(ctx)
    sectors_chains = build_sectors(chains_scored, "tvl_series", "category", stock=True)

    # The twelve themes of the Sektory tab. A CoinGecko outage must not cost
    # the refresh: themes.py falls back to its basket cache, then to the last
    # snapshot's members, then to seed baskets.
    prev = None
    try:
        prev = json.load(io.open(os.path.join(ctx.data_dir, SNAPSHOT_NAME), encoding="utf-8"))
    except Exception:
        pass
    try:
        th = themes.build_themes(ctx, sectors_apps, int(time.time()), prev_snapshot=prev)
    except Exception as exc:
        import traceback
        ctx.warn("témata selhala: %s" % exc)
        ctx._log(traceback.format_exc())
        th = {"themes": (prev or {}).get("themes") or [], "altseason": (prev or {}).get("altseason"),
              "theme_prices": (prev or {}).get("theme_prices"), "coin_meta": (prev or {}).get("coin_meta") or {},
              "theme_anomalies": [], "unmapped": (prev or {}).get("unmapped"), "stale": True}

    # Rows learn their theme only now: themes are measured after compute_metrics,
    # and Test 30× measures a category leader against its theme's biggest coin.
    # On the stale path there are no CoinGecko candidates, so the join skips its
    # CoinGecko steps and theme_join.changed shows who moved because of it.
    theme_join = themes.attach_themes(apps_scored, chains_scored, th["themes"],
                                      stale=bool(th.get("stale")), cg_members=th.get("cg_members"),
                                      prev_snapshot=prev)
    ctx.log("témata řádků: %s" % ", ".join("%s %d" % kv for kv in theme_join["counts"].items()))
    apply_test30(apps_scored, chains_scored, th["themes"])
    degen = apply_degen(apps_scored, chains_scored, bool(th.get("stale")), prev)
    ctx.log("pro degena: %d z %d appek splňuje všech 7 podmínek" % (degen["n_ok"], degen["n_total"]))

    # The forward record of past selections, and the backtest verdict if
    # backtest.py has produced one next to the snapshot (no network either way).
    btc_now = ((th.get("theme_prices") or {}).get("live") or {}).get("bitcoin")
    ledger_lines = read_ledger(ctx)
    try:
        picks_ledger = ledger_summary(ctx, ledger_lines, apps_scored + chains_scored, btc_now, now_ts)
    except Exception as exc:
        ctx.warn("záznam tipů nejde vyhodnotit: %s" % exc)
        picks_ledger = None
    backtest_summary = None
    try:
        backtest_summary = json.load(io.open(os.path.join(ctx.data_dir, "backtest_summary.json"),
                                             encoding="utf-8"))
    except FileNotFoundError:
        pass
    except Exception as exc:
        ctx.warn("backtest_summary.json nejde přečíst: %s" % exc)

    # An app's TVL series was ~2 MB of the snapshot and no apps-view code path
    # ever drew it (TVL columns and charts exist only for chains). The /protocol
    # call still happens — that is where description, url and chains come from.
    for e in apps_scored:
        e.pop("tvl_series", None)
        e.pop("tvl_growth", None)

    for e in apps_scored + chains_scored:
        e["rev_series"] = clean_series(e["rev_series"])
        if e.get("tvl_series"):
            e["tvl_series"] = clean_series(e["tvl_series"])
        if e.get("raw_tvl_series"):
            e["raw_tvl_series"] = clean_series(e["raw_tvl_series"])
        if e.get("dex_series"):
            e["dex_series"] = clean_series(e["dex_series"])

    snapshot = {
        "generated_at": int(time.time()),
        "generated_at_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "collection_floor_usd_30d": COLLECTION_FLOOR_USD_30D,
        "windows": WINDOWS,
        "bench": bench,
        "bench_chains": bench_chains,
        "test30_rule": SIZE_CEILING_RULE,
        "liquidity_meta": liquidity_meta,
        "unlocks_meta": unlocks_meta,
        "degen": degen,
        "picks_ledger": picks_ledger,
        "backtest_summary": backtest_summary,
        "risk_rules": {"float_tag": FLOAT_TAG, "unlock90_tag": UNLOCK90_TAG,
                       "cliff_days": CLIFF_DAYS, "cliff_min": CLIFF_MIN,
                       "ticket": liquidity.TICKET, "max_impact_pct": liquidity.MAX_IMPACT_PCT,
                       "vol_pass": liquidity.VOL_PASS},
        "apps": apps_scored,
        "chains": chains_scored,
        "sectors": {"apps": sectors_apps, "chains": sectors_chains},
        "themes": th["themes"],
        "altseason": th["altseason"],
        "theme_prices": th["theme_prices"],
        "coin_meta": th["coin_meta"],
        "theme_anomalies": th["theme_anomalies"],
        "unmapped": th["unmapped"],
        "themes_stale": bool(th.get("stale")),
        "theme_join": theme_join,
        "fetch_warnings": ctx.warnings[:40],
        "fetch_warning_count": len(ctx.warnings),
        "excluded": {
            "apps_no_token_count": ctx.excluded_apps_count,
            "chains_no_token": ctx.excluded_chains[:20],
            "untradeable_count": len(ctx.dropped_untradeable),
            "doublecounted_count": len(ctx.excluded_doublecounted),
        },
    }

    path = write_snapshot(ctx, snapshot)
    # only after the snapshot is safely on disk: a failed write must not log picks
    try:
        if append_ledger(ctx, ledger_lines, degen, apps_scored, btc_now, now_ts):
            ctx.log("záznam tipů: +%d coinů" % len(degen.get("shortlist") or []))
    except Exception as exc:
        ctx.warn("záznam tipů nejde zapsat: %s" % exc)
    size_kb = os.path.getsize(path) / 1024
    ctx.log("wrote %s (%.0f KB) — %d apps, %d chains, %d app sectors, %d chain sectors"
            % (SNAPSHOT_NAME, size_kb, len(apps_scored), len(chains_scored),
               len(sectors_apps), len(sectors_chains)))
    ctx.log("done in %.0fs" % (time.time() - t_start))
    return snapshot


if __name__ == "__main__":
    run(data_dir=os.getcwd())
