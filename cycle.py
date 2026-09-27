"""
Altseason cycle — "where are we in the altseason, and has it played out?"

The Start/Sektory panel used to show one number: the share of the top-50 alts
that beat BTC over 13 weeks (the Blockchaincenter convention). That answers "are
alts winning right now", not "is it early or late", it had seen 40 weeks of an
ordinary market, and it jumped ±10 points week to week. This module builds the
replacement (ARCHITECTURE §13.8):

    Altseason cyklus   0–100 cycle position from two pillars that both have free
                       history across the 2017/18 and 2021 altseasons:
                         rotation — BTC.D drawdown, OTHERS.D rise, breadth
                         heat     — BTC cycle heat (MVRV, Puell, Mayer, Pi Cycle)
    phase              zima · btc_sezona · zacina · bezi · prehrate · po_vrcholu
    tiles              BTC.D, OTHERS.D (+ its downtrend line and breakout),
                       Alt Season Index (breadth), BTC cyklus, Retail, Objem

Principle: only series with history across BOTH cycles enter the index;
everything else (retail, volume) is shown beside it. Retail measures what people
DO — Korean exchange turnover, the memecoin economy, the best-ranked crypto app,
new stablecoin dollars — not what they look up: in the AI era lookups moved into
chatbots, and a lookup series decays for reasons unrelated to crypto (Adam,
2026-09-26, on Wikipedia: "nikdo tam nechodí").

Inputs live in `cycle_history.json` (gitignored: CMC/DeFiLlama terms and Coin
Metrics' CC BY-NC forbid republishing the raw data; the page shows derived
numbers with sources named). `tools/cycle_seed.py` builds the long history once;
each collector run fetches only the missing tail. No module-level mutable state:
app.py calls the collector repeatedly in one process.

The thresholds are pre-registered in cycle_backtest.py (PREREG + lock); the
chosen variant and the derived threshold T come from cycle_backtest_summary.json.
"""
import datetime
import gzip
import io
import json
import math
import os
import re
import statistics
import time
import xml.etree.ElementTree as ET

DAY = 86400
WEEK = 7 * DAY
HISTORY_NAME = "cycle_history.json"
SUMMARY_NAME = "cycle_backtest_summary.json"
HISTORY_VERSION = 1
START_WEEK = 1404691200            # Monday 2014-07-07: scoring 2017 needs a 52-week window + 104 weeks
DAILY_START = 1451606400           # 2016-01-01 for CMC daily (volume needs a 1-year median before 2017)
CM_START = "2012-01-01"            # Coin Metrics BTC: Pi Cycle's 350-day mean needs a year before 2014-07
DISPLAY_FROM = 1451865600          # 2016-01-04: nothing earlier is drawn ("2013 me nezajímá")
MEME_START_USD = 5e6               # the memecoin economy is scored from its first $5M month (2023-05)
RETAIL_MIN_ROWS = 2                # the retail history is drawn where at least two rows exist

CMC = "https://api.coinmarketcap.com/data-api/v3"
CM = "https://community-api.coinmetrics.io/v4/timeseries/asset-metrics"
# Coinbase Exchange public candles: keyless, newest first, at most 300 per call
# (a wider range is an HTTP 400), `end` inclusive, 10 requests/s
COINBASE = "https://api.exchange.coinbase.com/products/%s/candles?granularity=86400&start=%s&end=%s"
COINBASE_PAIRS = (("BTC-USD", 1437350400), ("ETH-USD", 1463529600))   # first days: 2015-07-20, 2016-05-18
COINBASE_PAGE = 300
COINBASE_PACE = 0.15
COINBASE_TAIL_DAYS = 30            # re-fetched every run: the newest candles get revised
LISTING_LIMIT = 500                # deep enough that a top-50 coin 13 weeks later still has its old price
CMC_PACE = 1.6                     # CMC's web API throttles after ~10 fast calls
MAX_NEW_LISTINGS = 12              # per collector run; the long history is the seed's job

WINDOW = 208                       # trailing percentile window (weeks) — one halving cycle
MIN_WINDOW = 104
BREADTH_N = 50

# Coins that are not bets on an alt: stablecoins and wrapped/staked twins. Names go
# through themes' EXCLUDE_RE (word-bounded: "gold" must not drop Goldfinch), symbols
# through this list — "Lido Staked Ether" is caught by name, stETH's twins by symbol.
STABLE_SYMS = {"USDT", "USDC", "DAI", "BUSD", "TUSD", "USDP", "PAX", "GUSD", "FDUSD", "USDE", "PYUSD",
               "USDD", "FRAX", "LUSD", "USDS", "RLUSD", "USD1", "USDG", "EURC", "EURS", "USDX", "USTC",
               "UST", "HUSD", "SUSD", "USDB", "USDY", "USDF", "BFUSD", "USDTB", "USDO", "USD0", "SUSDE",
               "SUSDS", "CRVUSD", "GHO", "USDA", "XAUT", "PAXG", "BSC-USD", "USDJ", "USDK", "CUSD", "DUSD"}
WRAPPED_SYMS = {"WBTC", "WETH", "STETH", "WSTETH", "WEETH", "EETH", "CBBTC", "WBETH", "RETH", "METH",
                "JITOSOL", "MSOL", "BNSOL", "LBTC", "SOLVBTC", "EZETH", "RSETH", "CBETH", "TBTC",
                "BTCB", "RENBTC", "HBTC", "WBNB", "WTRX", "WAVAX", "WMATIC", "BETH", "OSETH", "SAVAX",
                "STSOL", "JUPSOL", "BBSOL", "SWETH", "PUFETH", "LSETH", "ETHX", "BTC.B", "FBTC", "UNIBTC",
                "CLBTC", "ENZOBTC", "PUMPBTC", "XSOLVBTC", "KHYPE", "STHYPE", "WHYPE", "BSOL"}
EXTRA_RE = re.compile(r"\b(wrapped|bridged|staked|tokeni[sz]ed|xstock|treasury|restaked|liquid staked)\b", re.I)

# US App Store: the crypto apps whose best rank feeds the App score. Robinhood,
# Cash App, Kalshi and Polymarket are shown, not scored — they are not crypto-first.
APPS = [  # (apple id, label, scored)
    ("886427730", "Coinbase", True), ("6741115427", "fomo", True), ("1598432977", "Phantom", True),
    ("6503993131", "Moonshot", True), ("1492670702", "Binance.US", True), ("1262148500", "Crypto.com", True),
    ("1481947260", "Kraken", True), ("1278383455", "Coinbase Wallet", True), ("1288339409", "Trust", True),
    ("6717572591", "pump.fun", True), ("938003185", "Robinhood", False), ("711923939", "Cash App", False),
    ("1632713844", "Kalshi", False), ("6648798962", "Polymarket", False)]
YT_CHANNELS = [  # retail-oriented crypto channels (ids verified 2026-09-26)
    ("UCbLhGKVY-bJPcawebgtNfbw", "Altcoin Daily"), ("UCN9Nj4tjXbVTLYWN0EKly_Q", "Crypto Banter"),
    ("UCqK_GSMbpiV8spgD3ZGloSw", "Coin Bureau"), ("UCl2oCaw8hdR_kbqyqd2klIA", "Lark Davis"),
    ("UCRvqjQPSeaWn-uEx-w0XOIg", "Benjamin Cowen"), ("UCjemQfjaXAzA-95RKoy9n_g", "Discover Crypto"),
    ("UCI7M65p3A-D3P4v5qW8POxQ", "CryptosRUs"), ("UCiUnrCUGCJTCC7KjuW493Ww", "Crypto Zombie"),
    ("UC4VPa7EOvObpyCRI4YKRQRw", "Paul Barron"), ("UClgJyzwGs-GyaNxUHcLZrkg", "InvestAnswers"),
    ("UCnMku7J_UtwlcSfZlIuQ3Kw", "Crypto Capital Venture")]
TRANCO_DOMAINS = ["coinbase.com", "binance.com", "crypto.com"]
MEME_CATS = ("Launchpad", "Telegram Bot", "Trading App")   # = the Memecoiny fundament (themes.THEMES)

# Anthropic Economic Index — the only published measure of how much people ask an
# AI about crypto (share of Claude.ai conversations; released every 2–4 months, the
# taxonomy changed in Jun 2026, so it is a fact on the page, never a live signal).
AI_CLAUDE = [["2025-03", 0.355], ["2025-08", 0.218], ["2025-11", 0.477], ["2026-02", 0.497]]

# v1's rules as literals. cycle_backtest's v1 PREREG is locked, and v1 is still
# evaluated and reported (FAIL), so trend_break, pick_lines and compute_index — v1's
# code path — read only these: a v2 edit of DEFAULT_RULES must not move v1's result.
V1_RULES = {
    "window": 208, "min_window": 104,
    "T": 85.0, "t_factor": 0.9, "breadth_gate": "mean4",
    "prehrate_breadth": 75, "prehrate_dd": 25.0,
    "bezi_rotation": 60, "bezi_breadth_hi": 75, "bezi_breadth_lo": 50, "bezi_dd": 25.0,
    "zacina_rotation": 40, "zacina_rise": 15, "zacina_weeks": 13,
    "btc_sezona_heat": 50, "btc_sezona_rotation": 40,
    "po_vrcholu_drop": 15, "po_vrcholu_weeks": 26,
    "breadth_hi": 75, "breadth_lo": 25,
    "btcd_move_pp": 1.5,
    "heat_lo": 40, "heat_hi": 75,
    "retail_lo": 35, "retail_hi": 70, "retail_rush": 25,
    "vol_lo": 0.8, "vol_mid": 1.5, "vol_hi": 2.5,
    "trend_break": 0.03, "trend_fail": 0.03, "trend_min_weeks": 40, "trend_max_weeks": 156,
    "trend_pivot": 4, "trend_touch_gap": 8,
}

# Default rules. The backtest's summary overrides `breadth_gate` and `T` with the
# pre-registered variant it picked; the page reads every threshold from `rules`.
DEFAULT_RULES = dict(V1_RULES)


# ================================================================== small helpers
def monday(ts):
    d = datetime.datetime.fromtimestamp(ts, datetime.timezone.utc)
    m = datetime.datetime(d.year, d.month, d.day, tzinfo=datetime.timezone.utc) - datetime.timedelta(days=d.weekday())
    return int(m.timestamp())


def day0(ts):
    return int(ts) // DAY * DAY


def iso(ts):
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime("%Y-%m-%d")


def last_week(now_ts):
    """The newest Monday whose 00:00 UTC snapshot CMC already serves: CMC refuses
    `date=today`, so on a Monday the stamp is the previous Monday."""
    m = monday(now_ts)
    return m if day0(now_ts) > m else m - WEEK


def week_axis(now_ts):
    return list(range(START_WEEK, last_week(now_ts) + 1, WEEK))


def mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def pct_rank(hist, x):
    """Mid-rank percentile: 100·(#{y<x} + ½·#{y=x}) / n. Ties (breadth moves in
    2-point steps, a drawdown sits at 0 while BTC.D makes highs) get the middle."""
    if x is None or not hist:
        return None
    lo = sum(1 for y in hist if y < x)
    eq = sum(1 for y in hist if y == x)
    return 100.0 * (lo + 0.5 * eq) / len(hist)


def trailing_pct(series, window=WINDOW, min_n=MIN_WINDOW):
    """Percentile of each value among the previous `window` values (the current one
    excluded, None skipped); None until `min_n` values exist. Look-ahead free."""
    out = []
    for i, x in enumerate(series):
        prev = [y for y in series[max(0, i - window):i] if y is not None]
        out.append(pct_rank(prev, x) if (x is not None and len(prev) >= min_n) else None)
    return out


def expanding_pct(series, min_n):
    out = []
    for i, x in enumerate(series):
        prev = [y for y in series[:i] if y is not None]
        out.append(pct_rank(prev, x) if (x is not None and len(prev) >= min_n) else None)
    return out


def roll_mean(series, n):
    out = []
    for i in range(len(series)):
        w = series[max(0, i - n + 1):i + 1]
        out.append(mean(w) if len(w) == n and all(v is not None for v in w) else None)
    return out


def r4(x, d=4):
    return None if x is None else round(x, d)


def is_excluded(sym, name, p_now=None, p_then=None):
    """Stablecoins and wrapped/staked twins are not bets on an alt."""
    s = (sym or "").upper()
    if s in STABLE_SYMS or s in WRAPPED_SYMS:
        return True
    if EXTRA_RE.search(name or ""):
        return True
    near1 = lambda p: p is not None and 0.97 <= p <= 1.03
    # decided from prices up to that week: $1 now AND 13 weeks ago
    return near1(p_now) and (p_then is None or near1(p_then))


# ================================================================== history store
def history_path(data_dir):
    return os.path.join(data_dir, HISTORY_NAME)


def empty_history():
    return {"v": HISTORY_VERSION, "weeks": {}, "prices": {}, "daily": {}, "upbit": {}, "upbit_markets": [],
            "meme": {}, "tranco": {"monthly": {}, "daily": {}}, "apps": [], "yt": [], "ai": None, "cbbi": None,
            "cbx": {}, "latest": None}


def load_history(data_dir, log=None):
    """Missing and corrupt are different things: a missing file is a fresh start, a
    corrupt one falls back to the .bak — the seed costs ~40 minutes of paced calls
    and must never be overwritten by an empty dict (themes.load_cache would turn a
    corrupt file into {} and the next save would erase it)."""
    p = history_path(data_dir)
    for cand in (p, p + ".bak"):
        if not os.path.exists(cand):
            continue
        try:
            h = json.load(io.open(cand, encoding="utf-8"))
            if isinstance(h, dict) and h.get("v") == HISTORY_VERSION:
                base = empty_history()
                base.update(h)
                return base, cand != p
        except Exception as exc:
            if log:
                log("cycle_history: %s nejde přečíst (%s)" % (os.path.basename(cand), exc))
    return None, False


def save_history(data_dir, h, loaded_weeks=0):
    """Atomic write + .bak; refuses to save fewer weeks than it loaded."""
    if len(h.get("weeks") or {}) < loaded_weeks:
        raise RuntimeError("cycle_history: odmítám uložit %d týdnů místo %d" % (len(h["weeks"]), loaded_weeks))
    p = history_path(data_dir)
    tmp = p + ".tmp"
    with io.open(tmp, "w", encoding="utf-8") as f:
        json.dump(h, f, ensure_ascii=False, separators=(",", ":"))
    if os.path.exists(p):
        try:
            if os.path.exists(p + ".bak"):
                os.remove(p + ".bak")
            os.replace(p, p + ".bak")
        except OSError:
            pass
    for _ in range(5):
        try:
            os.replace(tmp, p)
            return
        except PermissionError:
            time.sleep(0.2)
    raise RuntimeError("cycle_history: zápis selhal")


# ================================================================== fetchers
def cmc_get(ctx, url, what, warn=True):
    """CMC's web API answers HTTP 200 with an error inside the body; both count."""
    d = ctx.get(url, timeout=60, warn=False, quiet_status=())
    st = (d or {}).get("status") or {}
    if d is None or str(st.get("error_code", "0")) not in ("0", ""):
        if warn:
            ctx.warn("CMC %s: %s" % (what, (st.get("error_message") or "bez odpovědi")[:120]))
        return None
    return d.get("data")


def fetch_global_weekly(ctx):
    d = cmc_get(ctx, "%s/global-metrics/quotes/historical?format=chart&interval=weekly&timeStart=%d&timeEnd=%d"
                % (CMC, START_WEEK - WEEK, int(time.time()) + DAY), "globální týdenní data")
    out = {}
    for q in (d or {}).get("quotes") or []:
        try:
            t = int(datetime.datetime.strptime(q["timestamp"][:10], "%Y-%m-%d")
                    .replace(tzinfo=datetime.timezone.utc).timestamp())
            qq = q["quote"][0]
            out[t] = (q.get("btcDominance"), qq.get("totalMarketCap"), qq.get("altcoinMarketCap"))
        except Exception:
            continue
    return out


def fetch_global_daily(ctx, start, end):
    """≤ 2 200 days a call; `interval=1d` (the word `daily` is an HTTP 500)."""
    out = {}
    t = start
    while t <= end:
        t1 = min(end, t + 2000 * DAY)
        d = cmc_get(ctx, "%s/global-metrics/quotes/historical?format=chart&interval=1d&timeStart=%d&timeEnd=%d"
                    % (CMC, t, t1 + DAY - 1), "globální denní data")
        for q in (d or {}).get("quotes") or []:
            try:
                ts = int(datetime.datetime.strptime(q["timestamp"][:10], "%Y-%m-%d")
                         .replace(tzinfo=datetime.timezone.utc).timestamp())
                qq = q["quote"][0]
                out[ts] = (q.get("btcDominance"), qq.get("totalMarketCap"), qq.get("totalVolume24H"))
            except Exception:
                continue
        t = t1 + DAY
        time.sleep(CMC_PACE)
    return out


def fetch_listing(ctx, date_str, warn=True):
    """One CMC historical listing, reduced to what the panel needs:
    [[id, symbol, name, price, mcap, vol24h], …] in rank order."""
    d = cmc_get(ctx, "%s/cryptocurrency/listings/historical?date=%s&limit=%d&start=1&convertId=2781"
                % (CMC, date_str, LISTING_LIMIT), "žebříček %s" % date_str, warn=warn)
    if not d:
        return None
    rows = []
    for c in d:
        try:
            q = c["quotes"][0]
            rows.append([c["id"], c.get("symbol") or "", c.get("name") or "", q.get("price"),
                         q.get("marketCap") or 0, q.get("volume24h") or 0])
        except Exception:
            continue
    return rows


def fetch_cm(ctx, assets, metrics, start):
    """Coin Metrics community API, paged. {asset: {day_ts: {metric: float}}}."""
    url = ("%s?assets=%s&metrics=%s&frequency=1d&start_time=%s&page_size=10000"
           % (CM, assets, metrics, start))
    out = {}
    for _ in range(20):
        d = ctx.get(url, timeout=90, quiet_status=())
        if not d:
            return None
        for r in d.get("data") or []:
            ts = day0(int(datetime.datetime.strptime(r["time"][:10], "%Y-%m-%d")
                          .replace(tzinfo=datetime.timezone.utc).timestamp()))
            row = out.setdefault(r["asset"], {}).setdefault(ts, {})
            for k, v in r.items():
                if k not in ("asset", "time") and v is not None:
                    try:
                        row[k] = float(v)
                    except ValueError:
                        pass
        url = d.get("next_page_url")
        if not url:
            break
    return out


# ================================================================== listing → weekly record
def summarize_listing(rows, prices_then=None):
    """OTHERS.D (TradingView's definition: ranks 11–125 of the top 125, stablecoins
    in), OTHERS in USD, BTC vs alt volume, and breadth: the top 50 alts that beat
    BTC since `prices_then` (13 weeks earlier), Blockchaincenter's convention."""
    # CMC's order IS the ranking. With limit=500 it returns ranks 1–199 and then
    # appends unranked derivatives (stETH, WBTC, WETH…) with market caps: sorting by
    # market cap pulled them into the top 125 and read OTHERS.D 12,2 % instead of
    # 7,98 % on 2026-09-25. Keep the API order and stop at that appendix.
    cut = len(rows)
    for i in range(150, len(rows)):
        if rows[i][4] and rows[i - 1][4] and rows[i][4] > rows[i - 1][4] * 1.5:
            cut = i
            break
    rows = [r for r in rows[:cut] if r[4] and r[4] > 0]
    top = rows[:125]
    if len(top) < 100:
        return None
    tot = sum(r[4] for r in top)
    rec = {"od": round(100.0 * sum(r[4] for r in top[10:]) / tot, 4), "ou": round(sum(r[4] for r in top[10:])),
           "t125": round(tot)}
    btc = next((r for r in rows if r[1] == "BTC" and r[0] == 1), None)
    vb = btc[5] if btc else 0
    va = sum(r[5] for r in top if r is not btc and not is_excluded(r[1], r[2], r[3]))
    rec["vb"], rec["va"] = round(vb), round(va)
    if prices_then and btc and prices_then.get(str(btc[0])):
        b = btc[3] / prices_then[str(btc[0])]
        beat = n = miss = 0
        leaders = []
        for r in rows:
            if r is btc:
                continue
            pt = prices_then.get(str(r[0]))
            if is_excluded(r[1], r[2], r[3], pt):
                continue
            if n + miss >= BREADTH_N:
                break
            if not pt or not r[3]:
                miss += 1        # listed less than 13 weeks ago — skipped, as Blockchaincenter does
                continue
            n += 1
            rel = (r[3] / pt) / b - 1
            beat += 1 if rel > 0 else 0
            leaders.append([r[1], round(rel, 4), round((r[3] / pt) - 1, 4)])
        rec["br"] = [beat, n, miss]
        rec["lead"] = sorted(leaders, key=lambda x: -x[1])[:8]
    return rec


def listing_prices(rows):
    return {str(r[0]): r[3] for r in rows if r[3]}


def rebuild_from_cache(H, cache_dir, log):
    """Recompute every weekly listing summary from the cached raw listings (after
    a change to summarize_listing) — no network."""
    done = 0
    for k in sorted(H["weeks"], key=int):
        w = int(k)
        path = os.path.join(cache_dir, "%s.json.gz" % iso(w))
        if not os.path.exists(path):
            continue
        rows = json.load(gzip.open(path, "rt", encoding="utf-8"))
        p13 = os.path.join(cache_dir, "%s.json.gz" % iso(w - 13 * WEEK))
        pt = listing_prices(json.load(gzip.open(p13, "rt", encoding="utf-8"))) if os.path.exists(p13) else None
        rec = summarize_listing(rows, pt)
        if rec:
            for key in ("od", "ou", "t125", "vb", "va", "br", "lead"):
                H["weeks"][k].pop(key, None)
            H["weeks"][k].update(rec)
            H["prices"][k] = listing_prices(rows)
            done += 1
    keep = sorted(H["prices"], key=int)[-14:]
    H["prices"] = {k: H["prices"][k] for k in keep}
    log("cycle: přepočteno %d týdnů z cache" % done)
    return done


# ================================================================== trendline
def trend_break(vals, mode="down", rules=None):
    """The downtrend line a trader draws on OTHERS.D, and whether it broke.

    Weekly closes, each week judged only on data up to itself. A pivot high is a
    close that is the highest of ±4 weeks (usable 4 weeks later). From each pivot
    that is still the highest close since it, the flattest line no close pierces
    is kept (slope = max (c_j − c_a)/(j − a)); a close more than 3 % over the line
    drawn through the previous week, at least 40 weeks after the anchor, is a
    breakout and freezes the line. A close 3 % under a frozen line within 26 weeks
    is a failed breakout. mode="up" mirrors it for BTC.D (rising support from lows).
    Returns every line found, oldest anchor first."""
    R = dict(V1_RULES, **(rules or {}))
    d = 1.0 if mode == "down" else -1.0      # all comparisons go through d: "higher" means "more extreme"
    c = list(vals)
    n = len(c)
    k = R["trend_pivot"]
    b, f = R["trend_break"], R["trend_fail"]
    pivots = [i for i in range(k, n) if c[i] is not None and all(
        c[j] is None or d * c[j] <= d * c[i] for j in range(max(0, i - k), min(n, i + k + 1)))
        and all(c[j] is None or d * c[j] < d * c[i] for j in range(max(0, i - k), i))]
    lines = []
    active = {}                           # anchor -> {"slope", "touch"}
    used = set()
    for t in range(n):
        if c[t] is None:
            continue
        # anchors become usable 4 weeks after the pivot
        for a in pivots:
            if a + k == t and a not in used and a not in active:
                active[a] = {"slope": None, "touch": None}
        broken = []
        for a in sorted(active):
            st = active[a]
            if d * c[t] > d * c[a]:                  # a new extreme kills the anchor
                used.add(a)
                broken.append(a)
                continue
            if st["slope"] is not None and d * st["slope"] < 0 and t - a >= R["trend_min_weeks"]                     and st["touch"] is not None and st["touch"] - a >= R["trend_touch_gap"]                     and t - a <= R["trend_max_weeks"]:
                line = c[a] + st["slope"] * (t - a)
                if line > 0 and d * c[t] > d * line * (1 + d * b):
                    lines.append({"anchor": a, "touch": st["touch"], "slope": st["slope"], "breakout": t})
                    used.add(a)
                    broken.append(a)
                    continue
            if t > a:
                sl = (c[t] - c[a]) / (t - a)
                if st["slope"] is None or d * sl > d * st["slope"]:
                    st["slope"], st["touch"] = sl, t
            if t - a > R["trend_max_weeks"]:
                used.add(a)
                broken.append(a)
        for a in broken:
            active.pop(a, None)
    # still-open trends at the end
    for a, st in active.items():
        if st["slope"] is not None and d * st["slope"] < 0 and n - 1 - a >= R["trend_min_weeks"]                 and st["touch"] is not None and st["touch"] - a >= R["trend_touch_gap"]:
            lines.append({"anchor": a, "touch": st["touch"], "slope": st["slope"], "breakout": None})
    out = []
    last = n - 1
    while last > 0 and c[last] is None:
        last -= 1
    for L in sorted(lines, key=lambda L: L["anchor"]):
        a, sl = L["anchor"], L["slope"]
        status, fail_at = "downtrend", None
        if L["breakout"] is not None:
            status = "breakout"
            for t in range(L["breakout"] + 1, min(n, L["breakout"] + 27)):
                ln = c[a] + sl * (t - a)
                if c[t] is not None and d * c[t] < d * ln * (1 - d * f):
                    status, fail_at = "failed", t
                    break
        line_now = c[a] + sl * (last - a)
        out.append({"anchor": a, "touch": L["touch"], "slope": sl, "breakout": L["breakout"],
                    "failed_at": fail_at, "status": status,
                    "weeks": (L["breakout"] if L["breakout"] is not None else last) - a,
                    "line_now": line_now,
                    "dist_pct": (c[last] / line_now - 1) * 100 if (c[last] is not None and line_now) else None})
    return out


def pick_lines(lines, n_weeks, recent=13):
    """At most two lines on the chart: the longest one broken recently or still
    active, and the most recent anchor's line."""
    # a line far from the price says nothing (on 2026-09-21 the one from the
    # 2024-01 high sat 33 % above OTHERS.D): drawn only within 15 % of it
    live = [L for L in lines if (L["status"] == "downtrend" and L["dist_pct"] is not None
                                 and abs(L["dist_pct"]) <= 15)
            or (L["breakout"] is not None and n_weeks - 1 - L["breakout"] <= recent)]
    if not live:
        return []
    longest = max(live, key=lambda L: L["weeks"])
    newest = max(live, key=lambda L: L["anchor"])
    return [longest] if longest is newest else [longest, newest]


# ================================================================== BTC heat
def heat_metrics(cm_btc, weeks):
    """MVRV ratio, Puell, Mayer, Pi Cycle ratio at each week (value of the day
    before the Monday stamp). MVRV ratio, not MVRV-Z: Z divides by the standard
    deviation of the WHOLE series, which leaks the future into the past."""
    days = sorted(cm_btc)
    if not days:
        return {k: [None] * len(weeks) for k in ("mvrv", "puell", "mayer", "pi")}
    t0 = days[0]
    nd = (days[-1] - t0) // DAY + 1
    price = [None] * nd
    mvrv = [None] * nd
    iss = [None] * nd
    for t in days:
        i = (t - t0) // DAY
        r = cm_btc[t]
        price[i] = r.get("PriceUSD")
        mvrv[i] = r.get("CapMVRVCur")
        iss[i] = r.get("IssTotUSD")

    def sma(arr, i, n):
        if i + 1 < n:
            return None
        w = arr[i - n + 1:i + 1]
        w = [x for x in w if x is not None]
        return sum(w) / len(w) if len(w) >= 0.9 * n else None

    out = {"mvrv": [], "puell": [], "mayer": [], "pi": []}
    for w in weeks:
        i = (w - DAY - t0) // DAY
        if i < 0 or i >= nd or price[i] is None:
            for k in out:
                out[k].append(None)
            continue
        out["mvrv"].append(mvrv[i])
        m365 = sma(iss, i, 365)
        out["puell"].append(iss[i] / m365 if (iss[i] and m365) else None)
        m200 = sma(price, i, 200)
        out["mayer"].append(price[i] / m200 if m200 else None)
        m111, m350 = sma(price, i, 111), sma(price, i, 350)
        out["pi"].append(m111 / (2 * m350) if (m111 and m350) else None)
    return out


# ================================================================== the index
def compute_index(weeks, series, rules):
    """Weekly scores, pillars, index and phase from the stored raw series.

    series: btcd, othersd, breadth (raw %, None when unknown), heat metrics.
    Returns a dict of lists aligned with `weeks`."""
    R = dict(V1_RULES, **(rules or {}))
    n = len(weeks)
    bd4 = roll_mean(series["btcd"], 4)
    od4 = roll_mean(series["othersd"], 4)
    dd = []
    rise = []
    for i in range(n):
        w = [x for x in bd4[max(0, i - 51):i + 1] if x is not None]
        dd.append(100.0 * (1 - bd4[i] / max(w)) if (bd4[i] is not None and len(w) >= 40) else None)
        w = [x for x in od4[max(0, i - 51):i + 1] if x is not None]
        rise.append(100.0 * (od4[i] / min(w) - 1) if (od4[i] is not None and len(w) >= 40 and min(w) > 0) else None)
    br = series["breadth"]
    br4 = roll_mean(br, 4)
    s_dd = trailing_pct(dd, R["window"], R["min_window"])
    s_rise = trailing_pct(rise, R["window"], R["min_window"])
    heat_parts = {k: trailing_pct(series[k], R["window"], R["min_window"]) for k in ("mvrv", "puell", "mayer", "pi")}
    heat = [mean([heat_parts[k][i] for k in heat_parts]) if sum(
        1 for k in heat_parts if heat_parts[k][i] is not None) >= 3 else None for i in range(n)]
    rot = []
    for i in range(n):
        parts = [s_dd[i], s_rise[i], br4[i]]
        rot.append(mean(parts) if sum(1 for p in parts if p is not None) >= 2 else None)
    idx = [(rot[i] + heat[i]) / 2 if (rot[i] is not None and heat[i] is not None) else None for i in range(n)]
    gate_br = br4 if R["breadth_gate"] == "mean4" else br
    phase = []
    pre_weeks = []                 # indexes of prehrate weeks
    for i in range(n):
        I, ro, he, g, d = idx[i], rot[i], heat[i], gate_br[i], dd[i]
        if I is None:
            phase.append(None)
            continue
        ph = None
        # po_vrcholu: two consecutive prehrate weeks within the last 26 weeks, index well below their max
        recent = [j for j in pre_weeks if i - j <= R["po_vrcholu_weeks"]]
        pairs = [j for j in recent if (j - 1) in pre_weeks]
        if pairs:
            top = max(idx[j] for j in recent)
            if I <= top - R["po_vrcholu_drop"]:
                ph = "po_vrcholu"
        if ph is None and I >= R["T"] and g is not None and g >= R["prehrate_breadth"] \
                and d is not None and d >= R["prehrate_dd"]:
            ph = "prehrate"
        if ph is None and ro is not None and ro >= R["bezi_rotation"] and g is not None and (
                g >= R["bezi_breadth_hi"] or (g >= R["bezi_breadth_lo"] and d is not None and d >= R["bezi_dd"])):
            ph = "bezi"
        if ph is None and ro is not None and ro >= R["zacina_rotation"]:
            back = rot[i - R["zacina_weeks"]] if i >= R["zacina_weeks"] else None
            brk = (series.get("breakouts") or [False] * n)
            recent_break = any(brk[j] for j in range(max(0, i - R["zacina_weeks"]), i + 1))
            if (back is not None and ro - back >= R["zacina_rise"]) or recent_break:
                ph = "zacina"
        if ph is None and he is not None and he >= R["btc_sezona_heat"] and ro is not None \
                and ro < R["btc_sezona_rotation"]:
            ph = "btc_sezona"
        if ph is None:
            ph = "zima"
        if ph == "prehrate":
            pre_weeks.append(i)
        phase.append(ph)
    return {"dd": dd, "rise": rise, "br4": br4, "s_dd": s_dd, "s_rise": s_rise, "heat_parts": heat_parts,
            "heat": heat, "rotation": rot, "index": idx, "phase": phase}


def phase_episodes(weeks, phase):
    """Contiguous runs of one phase: [(phase, first index, last index)]."""
    eps = []
    for i, p in enumerate(phase):
        if p is None:
            continue
        if eps and eps[-1][0] == p and eps[-1][2] == i - 1:
            eps[-1][2] = i
        else:
            eps.append([p, i, i])
    return eps


# ================================================================== retail
def app_score(overall, finance):
    """Published ranks are the anchors: Coinbase #1 overall at the 2017 and 2021
    tops = 100, overall #10 = 90, #100 = 60; Finance #10 = 50, #100 = 10; outside
    both = 5 (log map between anchors)."""
    if overall:
        if overall <= 10:
            return 100 - (overall - 1) * 10.0 / 9
        return 90 - 30 * math.log10(overall / 10.0)
    if finance:
        if finance <= 10:
            return 50 + (10 - finance)
        return max(10.0, 50 - 40 * math.log10(finance / 10.0))
    return 5.0


def parse_yt_feed(xml_bytes):
    """Views of the channel's last 15 videos; `views` sits in media:statistics."""
    ns = {"a": "http://www.w3.org/2005/Atom", "m": "http://search.yahoo.com/mrss/"}
    out = []
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return out
    for e in root.findall("a:entry", ns):
        pub = e.findtext("a:published", default="", namespaces=ns)
        st = e.find("m:group/m:community/m:statistics", ns)
        if st is None or not pub:
            continue
        try:
            t = int(datetime.datetime.fromisoformat(pub.replace("Z", "+00:00")).timestamp())
            out.append((t, int(st.get("views") or 0)))
        except ValueError:
            continue
    return out


# ================================================================== history update
def _dkey(ts):
    return str(int(ts))


def update_global(ctx, H, now_ts, log):
    """CMC weekly BTC.D (one call returns every week since 2013) and daily
    volume / BTC.D. Both are re-fetched every run: CMC revises recent points."""
    g = fetch_global_weekly(ctx)
    for t, (bd, tm, am) in g.items():
        if t < START_WEEK:
            continue
        rec = H["weeks"].setdefault(_dkey(t), {})
        # CMC's weekly series has garbage points (BTC.D = 0 on 2020-05-18)
        rec["bd"] = bd if (bd and 5 < bd < 100) else None
        rec["tm"] = tm
    daily = H["daily"].setdefault("cmc", {})
    have = sorted(int(k) for k in daily)
    start = DAILY_START if not have else max(DAILY_START, have[-1] - 60 * DAY)
    d = fetch_global_daily(ctx, start, day0(now_ts) - DAY)
    for t, (bd, mc, vol) in d.items():
        daily[_dkey(t)] = [bd if (bd and 5 < bd < 100) else None, mc, vol if (vol and vol > 0) else None]
    log("cycle: CMC globální %d týdnů, %d dní" % (len(g), len(d)))
    return bool(g)


def update_listings(ctx, H, now_ts, log, max_new=MAX_NEW_LISTINGS, cache_dir=None):
    """Weekly CMC listings -> OTHERS.D, OTHERS $, volume split, breadth. Past weeks
    are fixed; only missing weeks are fetched (the seed does the long history).
    Per-coin prices are kept for the last 14 weeks only — enough to compute next
    week's 13-week breadth."""
    weeks = week_axis(now_ts)
    need = [w for w in weeks if "od" not in H["weeks"].get(_dkey(w), {})]
    if max_new is not None:
        need = need[-max_new:]
    raw = {}

    def get_rows(w):
        if w in raw:
            return raw[w]
        rows = None
        path = os.path.join(cache_dir, "%s.json.gz" % iso(w)) if cache_dir else None
        if path and os.path.exists(path):
            try:
                rows = json.load(gzip.open(path, "rt", encoding="utf-8"))
            except Exception:
                rows = None
        if rows is None:
            rows = fetch_listing(ctx, iso(w))
            time.sleep(CMC_PACE)
            if rows and path:
                with gzip.open(path + ".tmp", "wt", encoding="utf-8") as f:
                    json.dump(rows, f, separators=(",", ":"))
                os.replace(path + ".tmp", path)
        raw[w] = rows
        return rows

    done = 0
    for w in need:
        rows = get_rows(w)
        if not rows:
            continue
        w13 = w - 13 * WEEK
        pt = H["prices"].get(_dkey(w13))
        if pt is None:
            r13 = get_rows(w13)
            pt = listing_prices(r13) if r13 else None
        rec = summarize_listing(rows, pt)
        if rec:
            H["weeks"].setdefault(_dkey(w), {}).update(rec)
            H["prices"][_dkey(w)] = listing_prices(rows)
            done += 1
        if done and done % 25 == 0:
            log("cycle: žebříčky %d/%d" % (done, len(need)))
        if cache_dir:
            # the seed walks 600+ weeks: drop what is no longer needed
            for k in [k for k in raw if k < w - 14 * WEEK]:
                raw.pop(k, None)
            for k in [k for k in H["prices"] if int(k) < w - 14 * WEEK]:
                H["prices"].pop(k, None)
    # keep per-coin prices only for the newest 14 weeks
    keep = sorted(H["prices"], key=int)[-14:]
    H["prices"] = {k: H["prices"][k] for k in keep}
    # the newest complete day: drawn as the unconfirmed point of the OTHERS.D chart
    # CMC serves a day only ~1–2 days later ("dates between … and yesterday 00:00")
    for back in (1, 2):
        yday = day0(now_ts) - back * DAY
        if not weeks or yday <= weeks[-1]:
            break
        rows = fetch_listing(ctx, iso(yday), warn=False)
        rec = summarize_listing(rows) if rows else None
        if rec:
            H["latest"] = {"day": yday, "od": rec["od"], "ou": rec["ou"]}
            break
    log("cycle: žebříčky +%d týdnů (chybí %d)" % (done, len(need) - done))
    return done


def update_coinmetrics(ctx, H, now_ts, log):
    cm = H["daily"].setdefault("cm", {})
    st = H["daily"].setdefault("st", {})
    have = sorted(int(k) for k in cm)
    start = CM_START if not have else iso(have[-1] - 10 * DAY)
    d = fetch_cm(ctx, "btc", "PriceUSD,CapMrktCurUSD,CapMVRVCur,IssTotUSD", start)
    for t, r in ((d or {}).get("btc") or {}).items():
        cm[_dkey(t)] = [r.get("PriceUSD"), r.get("CapMVRVCur"), r.get("IssTotUSD")]
    haves = sorted(int(k) for k in st)
    start = "2014-10-01" if not haves else iso(haves[-1] - 10 * DAY)
    s = fetch_cm(ctx, "usdt,usdc", "SplyCur", start)
    if s:
        days = set((s.get("usdt") or {}).keys()) | set((s.get("usdc") or {}).keys())
        for t in days:
            v = ((s.get("usdt") or {}).get(t) or {}).get("SplyCur", 0) + \
                ((s.get("usdc") or {}).get(t) or {}).get("SplyCur", 0)
            if v > 0:
                st[_dkey(t)] = v
    log("cycle: Coin Metrics BTC %d dní, stablecoiny %d dní" % (len(cm), len(st)))
    return bool(d)


def update_meme(ctx, H, now_ts, log, breakdown=None):
    """The memecoin economy's 30-day revenue (Launchpad + Telegram Bot + Trading
    App). History: DeFiLlama's per-protocol daily breakdown (seed, one 23 MB call);
    each run adds today's value from the bulk fee overview the collector already
    fetched (`ctx.fee_protocols`, the same endpoint family)."""
    m = H.setdefault("meme30", {})
    if breakdown:
        cat = {}
        for p in breakdown.get("protocols") or []:
            for nm in (p.get("name"), p.get("displayName")):
                if nm:
                    cat[nm] = p.get("category")
        daily = {}
        for t, parts in breakdown.get("totalDataChartBreakdown") or []:
            daily[day0(int(t))] = sum(v for nm, v in parts.items() if cat.get(nm) in MEME_CATS and v)
        days = sorted(daily)
        for i, t in enumerate(days):
            if i >= 29 and days[i] - days[i - 29] == 29 * DAY:
                m[_dkey(t)] = round(sum(daily[days[j]] for j in range(i - 29, i + 1)))
    fp = getattr(ctx, "fee_protocols", None) or []
    if fp:
        v = sum((p.get("total30d") or 0) for p in fp if p.get("category") in MEME_CATS)
        if v > 0:
            m[_dkey(day0(now_ts) - DAY)] = round(v)
    return len(m)


def _iso_z(ts):
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def update_coinbase(ctx, H, now_ts, log, full=False):
    """US retail: Coinbase Exchange daily USD turnover of BTC-USD and ETH-USD,
    stored per pair as {day: base volume x close} under `cbx`.

    CI restores cycle_history.json from its cache and seeds only when the file is
    missing, so an old history without `cbx` must backfill itself here: a pair whose
    stored days do not reach back to its first day is paged backwards from yesterday
    to that day (~14 calls a pair); otherwise only the tail is re-fetched. Today's
    partial candle is dropped. An empty page (a gap in Coinbase's data) is not the
    end; a failed call is — what is stored stays (stale beats empty)."""
    C = H.setdefault("cbx", {})
    last = day0(now_ts) - DAY
    got = 0
    for pair, first in COINBASE_PAIRS:
        P = C.setdefault(pair, {})
        have = sorted(int(k) for k in P)
        if full or not have or have[0] > first + 30 * DAY:
            start = first
        else:
            start = max(first, min(have[-1], last) - COINBASE_TAIL_DAYS * DAY)
        t1 = last
        while t1 >= start:
            t0 = max(start, t1 - (COINBASE_PAGE - 1) * DAY)
            d = ctx.get(COINBASE % (pair, _iso_z(t0), _iso_z(t1)), timeout=30, warn=False, quiet_status=())
            time.sleep(COINBASE_PACE)
            if not isinstance(d, list):
                ctx.warn("Coinbase %s: svíčky %s–%s nedostupné, zůstávají uložená data" % (pair, iso(t0), iso(t1)))
                break
            for c in d:
                try:
                    t, close, vol = int(c[0]), float(c[4]), float(c[5])
                except (TypeError, ValueError, IndexError):
                    continue
                if t0 <= t <= last and t % DAY == 0 and close > 0 and vol >= 0:
                    P[_dkey(t)] = round(vol * close)
                    got += 1
            t1 = t0 - DAY
    log("cycle: Coinbase %d svíček, %s" % (got, ", ".join("%s %d dní" % (p, len(C.get(p) or {}))
                                                       for p, _ in COINBASE_PAIRS)))
    return got


def upbit_weeks(ctx, market, since, count=200):
    """Weekly KRW turnover of one market back to `since`: {monday: krw}."""
    out = {}
    to = None
    for _ in range(6):
        url = "https://api.upbit.com/v1/candles/weeks?market=%s&count=%d%s" % (
            market, count, ("&to=" + to) if to else "")
        d = ctx.get(url, timeout=30, warn=False, quiet_status=())
        time.sleep(0.13)
        if not d:
            break
        for c in d:
            t = int(datetime.datetime.strptime(c["candle_date_time_utc"][:10], "%Y-%m-%d")
                    .replace(tzinfo=datetime.timezone.utc).timestamp())
            out[t] = c.get("candle_acc_trade_price") or 0
        oldest = min(out) if out else None
        if len(d) < count or oldest is None or oldest <= since:
            break
        to = datetime.datetime.fromtimestamp(oldest, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    return out


def update_upbit(ctx, H, now_ts, log, full=False):
    """Korean retail: Upbit's weekly KRW turnover summed over every listed KRW
    market. Refreshed once a week (~300 calls at Upbit's 10/s limit). Delisted
    coins are missing from old weeks, so old levels are understated — the retail
    score therefore uses the 13-week CHANGE, never the level."""
    U = H.setdefault("upbit", {})
    last_complete = monday(now_ts) - WEEK
    have = sorted(int(k) for k in U)
    if not full and have and have[-1] >= last_complete:
        return 0
    mk = ctx.get("https://api.upbit.com/v1/market/all?isDetails=false", warn=False)
    markets = [m["market"] for m in (mk or []) if m.get("market", "").startswith("KRW-")]
    if not markets:
        ctx.warn("Upbit: seznam trhů nedostupný")
        return 0
    first = full or not have
    since = 1506816000 if first else have[-1] - 3 * WEEK     # 2017-10-01
    sums = {}
    for i, m in enumerate(markets):
        for t, v in upbit_weeks(ctx, m, since, count=200 if first else 5).items():
            if t <= last_complete:
                sums[t] = sums.get(t, 0) + v
        if first and i % 50 == 49:
            log("cycle: Upbit %d/%d trhů" % (i + 1, len(markets)))
    for t, v in sums.items():
        U[_dkey(t)] = round(v)
    H["upbit_markets"] = len(markets)
    log("cycle: Upbit %d trhů, %d týdnů" % (len(markets), len(sums)))
    return len(sums)


def update_apps(ctx, H, now_ts, log):
    """US App Store: overall and Finance top-100 ranks (Apple's RSS stops at 100
    even when asked for 200) plus rating counts from the lookup API — the weekly
    growth of ratings stands in for downloads, which Apple does not publish."""
    ranks = {}
    for key, url in (("o", "https://itunes.apple.com/us/rss/topfreeapplications/limit=100/json"),
                     ("f", "https://itunes.apple.com/us/rss/topfreeapplications/limit=100/genre=6015/json")):
        d = ctx.get(url, timeout=30, quiet_status=())
        for i, e in enumerate(((d or {}).get("feed") or {}).get("entry") or [], 1):
            try:
                ranks.setdefault(e["id"]["attributes"]["im:id"], {})[key] = i
            except (KeyError, TypeError):
                continue
    ids = ",".join(a for a, _, _ in APPS)
    lk = ctx.get("https://itunes.apple.com/lookup?id=%s&country=us" % ids, timeout=30, quiet_status=())
    ratings = {str(r.get("trackId")): r.get("userRatingCount") for r in (lk or {}).get("results") or []}
    if not ranks and not ratings:
        return False
    entry = {a: [(ranks.get(a) or {}).get("o"), (ranks.get(a) or {}).get("f"), ratings.get(a)] for a, _, _ in APPS}
    day = day0(now_ts)
    led = H.setdefault("apps", [])
    led[:] = [x for x in led if x[0] != day] + [[day, entry]]
    led.sort(key=lambda x: x[0])
    return True


def update_youtube(ctx, H, now_ts, log):
    """Views per day across the retail crypto channels: the difference of each
    channel's cumulative views (YouTube Data API, optional free key). Without the
    key: the median views of the channels' week-old videos from their RSS feeds."""
    key = os.environ.get("YOUTUBE_API_KEY", "").strip()
    day = day0(now_ts)
    entry = None
    if key:
        d = ctx.get("https://www.googleapis.com/youtube/v3/channels?part=statistics&id=%s"
                    % ",".join(c for c, _ in YT_CHANNELS), timeout=30, quiet_status=(),
                    headers={"X-Goog-Api-Key": key})
        tot = {it["id"]: int((it.get("statistics") or {}).get("viewCount") or 0)
               for it in (d or {}).get("items") or []}
        if tot:
            entry = {"kind": "total", "v": tot}
    if entry is None:
        med = {}
        for cid, _ in YT_CHANNELS:
            raw = ctx.get("https://www.youtube.com/feeds/videos.xml?channel_id=%s" % cid, timeout=30,
                          warn=False, raw=True)
            vids = parse_yt_feed(raw) if raw else []
            old = [v for t, v in vids if now_ts - t >= 7 * DAY]
            if old:
                med[cid] = statistics.median(old)
        if med:
            entry = {"kind": "rss", "v": med}
    if not entry:
        return False
    led = H.setdefault("yt", [])
    led[:] = [x for x in led if x[0] != day] + [[day, entry]]
    led.sort(key=lambda x: x[0])
    return True


def update_tranco(ctx, H, now_ts, log, months=None):
    """Exchange web+app traffic ranks. Recent days from the per-domain endpoint;
    the monthly history (seed) from the top-10k slice of one list per month."""
    T = H.setdefault("tranco", {"monthly": {}, "daily": {}})
    for dom in TRANCO_DOMAINS:
        d = ctx.get("https://tranco-list.eu/api/ranks/domain/%s" % dom, timeout=30, warn=False)
        time.sleep(1.2)
        for r in (d or {}).get("ranks") or []:
            T["daily"].setdefault(r["date"], {})[dom] = r["rank"]
    keep = sorted(T["daily"])[-60:]
    T["daily"] = {k: T["daily"][k] for k in keep}
    for ym in months or []:
        if ym in T["monthly"]:
            continue
        lst = ctx.get("https://tranco-list.eu/api/lists/date/%s-15" % ym, timeout=30, warn=False)
        time.sleep(1.2)
        lid = (lst or {}).get("list_id")
        if not lid:
            continue
        raw = ctx.get("https://tranco-list.eu/download/%s/10000" % lid, timeout=60, warn=False, raw=True)
        time.sleep(1.2)
        if not raw:
            continue
        ranks = {}
        for line in raw.decode("utf-8", "replace").splitlines():
            parts = line.strip().split(",")
            if len(parts) == 2 and parts[1] in TRANCO_DOMAINS:
                ranks[parts[1]] = int(parts[0])
        T["monthly"][ym] = ranks
    return True


def update_cbbi(ctx, H, log):
    """CBBI as one reference line: its bands are refitted through known tops every
    day, so its history is in-sample and never enters the index."""
    d = ctx.get("https://colintalkscrypto.com/cbbi/data/latest.json", timeout=60, warn=False)
    conf = (d or {}).get("Confidence") or {}
    if conf:
        t = max(conf, key=int)
        H["cbbi"] = {"day": int(t), "v": conf[t]}
        return True
    return False


def update_ai(ctx, H, now_ts, log):
    """Cloudflare Radar: AI assistants fetching Cryptocurrency-industry sites on a
    user's behalf ("User Action" crawls), weekly share. Needs a free API token
    (Radar Read) in CLOUDFLARE_API_TOKEN; without it the row says so."""
    tok = os.environ.get("CLOUDFLARE_API_TOKEN", "").strip()
    if not tok:
        H["ai"] = None
        return False
    url = ("https://api.cloudflare.com/client/v4/radar/ai/bots/timeseries_groups/INDUSTRY"
           "?crawlPurpose=User%20Action&aggInterval=1w&dateRange=52w&limitPerGroup=20&format=json")
    d = ctx.get(url, timeout=60, quiet_status=(), headers={"Authorization": "Bearer " + tok})
    res = (d or {}).get("result") or {}
    ser = res.get("serie_0") or {}
    ts = ser.get("timestamps") or []
    key = next((k for k in ser if "crypto" in k.lower()), None)
    if not ts or not key:
        H["ai"] = {"error": "v datech Cloudflare chybí kryptoměnový obor" if ts else "bez dat"}
        return False
    H["ai"] = {"weeks": ts, "share": [float(x) for x in ser[key]], "label": key, "at": day0(now_ts)}
    return True


# ================================================================== history -> weekly series
def cm_days(H):
    """Coin Metrics rows as {day: {metric: value}} for heat_metrics."""
    out = {}
    for k, v in (H.get("daily") or {}).get("cm", {}).items():
        out[int(k)] = {"PriceUSD": v[0], "CapMVRVCur": v[1], "IssTotUSD": v[2]}
    return out


def btc_weekly(H, weeks):
    cm = (H.get("daily") or {}).get("cm", {})
    return [(cm.get(str(w - DAY)) or [None])[0] for w in weeks]


def series_from_history(H, weeks, rules=None):
    """Raw weekly inputs of the index, aligned with `weeks`."""
    W = H.get("weeks") or {}
    g = lambda w, k: (W.get(str(w)) or {}).get(k)
    br = []
    for w in weeks:
        b = g(w, "br")
        br.append(100.0 * b[0] / b[1] if (b and b[1] >= 30) else None)
    s = {"btcd": [g(w, "bd") for w in weeks], "othersd": [g(w, "od") for w in weeks],
         "others_usd": [g(w, "ou") for w in weeks], "breadth": br,
         "btc": btc_weekly(H, weeks)}
    s.update(heat_metrics(cm_days(H), weeks))
    s["anomalies"] = clean_spikes(weeks, s)
    # an OTHERS.D breakout is known at the week it happens (trend_break looks back only)
    lines = trend_break(s["othersd"], "down", rules)
    brk = [False] * len(weeks)
    for L in lines:
        if L["breakout"] is not None:
            brk[L["breakout"]] = True
    s["breakouts"] = brk
    return s


def clean_spikes(weeks, s, jump=0.25, agree=0.10):
    """One bad CMC snapshot must not become a data point. A week that sits more than
    25 % off two neighbours which agree within 10 % is a spike: 2020-11-30 read
    OTHERS.D 5,95 % between 10,75 and 10,83 and "6 of 49 alts beat BTC". A listing
    spike drops that week's OTHERS.D, OTHERS $ and breadth, and the breadth 13 weeks
    later (it was measured against that week's prices). Listed in `anomalies`."""
    out = []
    for key in ("othersd", "btcd"):
        v = s[key]
        for i in range(1, len(v) - 1):
            a, b, c = v[i - 1], v[i], v[i + 1]
            if None in (a, b, c) or a <= 0 or c <= 0:
                continue
            if abs(a / c - 1) <= agree and abs(b / ((a + c) / 2) - 1) > jump:
                out.append({"week": weeks[i], "series": key, "value": round(b, 4), "neighbours": [round(a, 4), round(c, 4)]})
                v[i] = None
                if key == "othersd":
                    s["others_usd"][i] = None
                    s["breadth"][i] = None
                    if i + 13 < len(weeks):
                        s["breadth"][i + 13] = None
    return out


def week_index(weeks, ts):
    """Index of the week containing `ts` (Monday stamps)."""
    m = monday(ts)
    return (m - weeks[0]) // WEEK if weeks and weeks[0] <= m <= weeks[-1] else None


def find_events(weeks, s):
    """Peak weeks by the pre-registered rules — derived from the data, not by eye.
    Not "BTC.D minimum per halving epoch": that would pick 2022-09, when the
    stablecoins' share inflated everything that is not BTC in a bear market."""
    def ts(y, m, d):
        return int(datetime.datetime(y, m, d, tzinfo=datetime.timezone.utc).timestamp())

    def argext(lo, hi, arr, fn):
        idx = [i for i, w in enumerate(weeks) if lo <= w <= hi and arr[i] is not None]
        return fn(idx, key=lambda i: arr[i]) if idx else None
    bd = s["btcd"]
    ev = {
        "P0": argext(ts(2017, 1, 1), ts(2017, 9, 30), bd, min),
        "P1": argext(ts(2017, 12, 17) - 26 * WEEK, ts(2017, 12, 17) + 13 * WEEK, bd, min),
        "P2": argext(ts(2021, 4, 14) - 26 * WEEK, ts(2021, 4, 14) + 13 * WEEK, bd, min),
        "P2b": argext(ts(2021, 7, 1), ts(2021, 12, 31), s["others_usd"], max),
    }
    return ev


# ================================================================== the snapshot block
def load_rules(data_dir):
    """The variant and T the pre-registered backtest picked; defaults otherwise."""
    rules = dict(DEFAULT_RULES)
    summ = None
    try:
        summ = json.load(io.open(os.path.join(data_dir, SUMMARY_NAME), encoding="utf-8"))
        rules.update(summ.get("rules") or {})
    except (OSError, ValueError):
        pass
    return rules, summ


def _r(x, d=2):
    if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
        return None
    return round(x, d)


def _daily_series(obj, idx):
    """{day_key: [..]} -> sorted [(day, value at position idx)]."""
    out = []
    for k in sorted(obj, key=int):
        v = obj[k]
        v = v[idx] if isinstance(v, list) else v
        if v is not None:
            out.append((int(k), v))
    return out


def volume_block(H, weeks, s, now_ts, R):
    days = _daily_series((H.get("daily") or {}).get("cmc", {}), 2)
    if len(days) < 400:
        return None
    ds = [d for d, _ in days]
    vs = [v for _, v in days]
    avg7 = [None] * len(vs)
    for i in range(6, len(vs)):
        if ds[i] - ds[i - 6] == 6 * DAY:
            avg7[i] = sum(vs[i - 6:i + 1]) / 7
    ratio = [None] * len(vs)
    for i in range(372, len(vs)):
        base = [v for v in vs[i - 372:i - 7] if v]
        if avg7[i] and len(base) >= 300:
            ratio[i] = avg7[i] / statistics.median(base)
    last = len(vs) - 1
    rt = ratio[last]
    verdict = None
    if rt is not None:
        verdict = ("slaby" if rt < R["vol_lo"] else "normalni" if rt < R["vol_mid"]
                   else "zvyseny" if rt < R["vol_hi"] else "extremni")
    W = H.get("weeks") or {}

    def share(w):
        r = W.get(str(w)) or {}
        return 100.0 * r["va"] / (r["va"] + r["vb"]) if r.get("va") and r.get("vb") else None
    shares = [share(w) for w in weeks]
    sh4 = roll_mean(shares, 4)
    # weekly samples of the 7-day average for the chart (2017 ->), BTC price beside it
    pos = {d: i for i, d in enumerate(ds)}
    chart_w = [w for w in weeks if w >= 1483315200]
    ser = [_r(avg7[pos[w - DAY]] / 1e9, 1) if (w - DAY) in pos and avg7[pos[w - DAY]] else None for w in chart_w]
    btc = s["btc"]
    wi = {w: i for i, w in enumerate(weeks)}
    return {"day": ds[last], "vol24h": _r(vs[last] / 1e9, 1), "avg7": _r((avg7[last] or 0) / 1e9, 1),
            "ratio_1y": _r(rt, 2), "verdict": verdict,
            "alt_share": _r(sh4[-1], 1), "alt_share_13w": _r(sh4[-14] if len(sh4) > 14 else None, 1),
            "alt_share_2021": _r(max((x for w, x in zip(weeks, sh4) if x is not None
                                      and 1609459200 <= w <= 1640995199), default=None), 1),
            "chart": {"weeks": chart_w, "avg7_bn": ser, "btc": [_r(btc[wi[w]], 0) for w in chart_w]},
            "fake_volume_span": [1546300800, 1609459199]}


def _trail_scores(pairs, window=WINDOW, min_n=52):
    """[(t, value)] oldest first -> {t: trailing percentile of the value}."""
    vals = [v for _, v in pairs]
    sc = trailing_pct(vals, window, min_n)
    return {t: s for (t, _), s in zip(pairs, sc) if s is not None}


def retail_block(ctx, H, weeks, now_ts, R):
    """Retail = what people DO, each row scored 0–100 against its own trailing four
    years (the same percentile as the index), so the index has a history to draw
    next to BTC and OTHERS since 2016. The history holds the rows that existed at
    each week: Upbit from 2018, stablecoins from 2019, the memecoin economy from
    2019 (tiny until 2023), the App Store ledger from the day the panel shipped."""
    parts = {}
    hist = {}                                   # row -> {week stamp: score}
    # --- Upbit: 4-week KRW turnover. Level, not change: the chart must show retail
    # waves. Delisted coins are missing from old weeks; they were delisted mostly in
    # 2018–19, outside today's four-year window.
    U = sorted((int(k), v) for k, v in (H.get("upbit") or {}).items())
    if len(U) >= 60:
        s4 = [(U[i][0] + WEEK, sum(v for _, v in U[i - 3:i + 1])) for i in range(3, len(U))]
        hist["upbit"] = _trail_scores(s4)
        peak = max(s4, key=lambda x: x[1])
        last = s4[-1]
        parts["upbit"] = {"score": _r(hist["upbit"].get(last[0]), 1), "week": last[0],
                          "sum4_t_krw": _r(last[1] / 1e12, 1), "peak_t_krw": _r(peak[1] / 1e12, 1),
                          "peak_week": peak[0], "pct_of_peak": _r(100.0 * last[1] / peak[1], 1) if peak[1] else None}
    # --- memecoin economy: 30-day revenue (Launchpad + Telegram Bot + Trading App)
    # Scored only from the first 30 days above $5M (2023-05, the Telegram bots): before
    # that the category barely existed, and a percentile of zeros read 50 through 2019–22
    # while a series growing from nothing read 100 every week after.
    M = sorted((int(k), v) for k, v in (H.get("meme30") or {}).items())
    m0 = next((t for t, v in M if v >= MEME_START_USD), None)
    if len(M) >= 120 and m0 is not None:
        md = dict(M)
        wk = [(w, md.get(w - DAY)) for w in weeks if w - DAY >= m0 and md.get(w - DAY) is not None]
        pairs = wk + ([M[-1]] if M[-1][0] > (wk[-1][0] if wk else 0) else [])
        hist["degen"] = _trail_scores(pairs)
        peak = max(M, key=lambda x: x[1])
        movers = []
        fp = getattr(ctx, "fee_protocols", None) or []
        for p in sorted((p for p in fp if p.get("category") in MEME_CATS), key=lambda p: -(p.get("total30d") or 0))[:3]:
            prev = p.get("total60dto30d") or 0
            movers.append({"name": p.get("displayName") or p.get("name"), "rev30d": p.get("total30d") or 0,
                           "chg_pct": _r(((p.get("total30d") or 0) / prev - 1) * 100, 0) if prev > 0 else None})
        parts["degen"] = {"score": _r(hist["degen"].get(pairs[-1][0]), 1), "day": M[-1][0], "rev30d": M[-1][1],
                          "peak": peak[1], "peak_day": peak[0],
                          "pct_of_peak": _r(100.0 * M[-1][1] / peak[1], 1) if peak[1] else None, "movers": movers}
    # --- stablecoins: 90-day growth of USDT + USDC
    S = _daily_series((H.get("daily") or {}).get("st", {}), 0)
    if len(S) > 800:
        sd = dict(S)
        pairs = []
        for w in weeks:
            a, b = sd.get(w - DAY), sd.get(w - DAY - 90 * DAY)
            if a and b:
                pairs.append((w, (a / b - 1) * 100))
        last_d = S[-1][0]
        a, b = sd.get(last_d), sd.get(last_d - 90 * DAY)
        if a and b and last_d > pairs[-1][0]:
            pairs.append((last_d, (a / b - 1) * 100))
        hist["stables"] = _trail_scores(pairs)
        parts["stables"] = {"score": _r(hist["stables"].get(pairs[-1][0]), 1), "day": last_d,
                            "supply_bn": _r(a / 1e9, 1) if a else None,
                            "g90": _r((a / b - 1) * 100 if (a and b) else None, 1)}
    # --- App Store: the best-ranked crypto app, scored by published anchors
    led = H.get("apps") or []
    if led:
        hist["apps"] = {}
        for day, ent in led:
            sc = max(app_score(*(ent.get(a) or [None, None])[:2]) for a, _, s_ in APPS if s_)
            hist["apps"][day] = sc
        day, ent = led[-1]
        apps = []
        best = None
        for aid, label, scored in APPS:
            o, fin, rat = (ent.get(aid) or [None, None, None])
            prev = next((x[1].get(aid) for x in reversed(led) if x[0] <= day - 6 * DAY), None)
            grow = (rat - prev[2]) if (rat and prev and prev[2]) else None
            sc = app_score(o, fin)
            apps.append({"id": aid, "name": label, "overall": o, "finance": fin, "ratings": rat,
                         "ratings_7d": grow, "scored": scored})
            if scored and (best is None or sc > best[0]):
                best = (sc, label, o, fin)
        parts["apps"] = {"score": _r(best[0], 1), "best": best[1], "best_overall": best[2], "best_finance": best[3],
                         "day": day, "apps": apps, "ledger_days": len(led)}
    # --- facts
    T = H.get("tranco") or {}
    if T.get("daily"):
        dk = sorted(T["daily"])
        cur = T["daily"][dk[-1]]
        back = next((T["daily"][k] for k in reversed(dk) if k <= (datetime.date.fromisoformat(dk[-1])
                     - datetime.timedelta(days=28)).isoformat()), None)
        parts["traffic"] = {"score": None, "day": dk[-1], "ranks": cur, "ranks_4w": back,
                            "best": {"coinbase.com": [818, "2021-11"]}}
    yt = H.get("yt") or []
    if yt:
        day, ent = yt[-1]
        rate = None
        if ent["kind"] == "total":
            prev = next((x for x in reversed(yt[:-1]) if x[1]["kind"] == "total"), None)
            if prev and day > prev[0]:
                rate = sum(ent["v"].get(c, 0) - prev[1]["v"].get(c, 0) for c in ent["v"]) / ((day - prev[0]) / DAY)
        parts["youtube"] = {"score": None, "day": day, "kind": ent["kind"], "views_per_day": _r(rate, 0),
                            "median_views": _r(statistics.median(list(ent["v"].values())), 0) if ent["kind"] == "rss" else None,
                            "channels": len(ent["v"]), "ledger_days": len(yt)}
    parts["ai"] = {"score": None, "claude": AI_CLAUDE, "cloudflare": H.get("ai"),
                   "needs": None if os.environ.get("CLOUDFLARE_API_TOKEN") else "CLOUDFLARE_API_TOKEN"}

    # --- the weekly history of the index: rows present at each week (a score dated
    # inside the week before the stamp counts for that stamp), drawn only where at
    # least two rows exist — before Upbit's first scored week (2018-10) the stablecoin
    # row alone jumped 20 ↔ 85 with Tether's batch prints
    series = []
    for w in weeks:
        if w < DISPLAY_FROM:
            continue
        xs = []
        for row, h in hist.items():
            best_t = None
            for t in h:
                if w - WEEK < t <= w and (best_t is None or t > best_t):
                    best_t = t
            if best_t is not None:
                xs.append(h[best_t])
        series.append(_r(mean(xs), 1) if len(xs) >= RETAIL_MIN_ROWS else None)
    scored = [p["score"] for k, p in parts.items() if k in ("upbit", "degen", "apps", "stables") and p.get("score") is not None]
    value = mean(scored)
    back4 = next((x for x in reversed(series[:-4]) if x is not None), None) if len(series) > 4 else None
    tempo = (value - back4) if (value is not None and back4 is not None) else None
    verdict = None
    if value is not None:
        verdict = "spi" if value < R["retail_lo"] else ("probouzi" if value < R["retail_hi"] else "hrne")
    tword = None
    if tempo is not None:
        tword = ("naval" if tempo >= R["retail_rush"] else "postupne" if tempo >= 8
                 else "odliv" if tempo <= -8 else "stoji")
    return {"value": _r(value, 1), "verdict": verdict, "tempo": _r(tempo, 1), "tempo_word": tword,
            "n_scored": len(scored), "parts": parts, "series": series}


def _line_out(L, weeks, vals):
    return {"anchor": weeks[L["anchor"]], "anchor_v": _r(vals[L["anchor"]], 3),
            "touch": weeks[L["touch"]], "touch_v": _r(vals[L["touch"]], 3), "slope_week": _r(L["slope"], 5),
            "breakout": weeks[L["breakout"]] if L["breakout"] is not None else None,
            "breakout_v": _r(vals[L["breakout"]], 3) if L["breakout"] is not None else None,
            "failed_at": weeks[L["failed_at"]] if L["failed_at"] is not None else None,
            "status": L["status"], "weeks": L["weeks"], "line_now": _r(L["line_now"], 3),
            "dist_pct": _r(L["dist_pct"], 1)}


def heat_block(res, s, weeks, ev, H):
    last = len(weeks) - 1
    names = {"mvrv": "MVRV", "puell": "Puell", "mayer": "Mayer", "pi": "Pi Cycle"}
    parts = {}
    hits = 0
    for k in ("mvrv", "puell", "mayer", "pi"):
        ser = s[k]

        def top(P):
            i = ev.get(P)
            if i is None:
                return None
            w = [ser[j] for j in range(max(0, i - 12), min(len(ser), i + 3)) if ser[j] is not None]
            return max(w) if w else None
        t17, t21 = top("P1"), top("P2")
        v = ser[last]
        hit = v is not None and t21 is not None and v >= t21
        hits += 1 if hit else 0
        parts[k] = {"name": names[k], "value": _r(v, 3), "score": _r(res["heat_parts"][k][last], 1),
                    "top2017": _r(t17, 3), "top2021": _r(t21, 3), "hit": hit}
    cb = H.get("cbbi")
    return {"parts": parts, "hits": hits, "of": 4,
            "cbbi": {"value": _r(cb["v"] * 100, 0), "day": cb["day"]} if cb else None}


def build_cycle(ctx, prev, now_ts, log=None, data_dir=None, fetch=True):
    """The snapshot's `cycle` block. `fetch=False` rebuilds from the stored history
    only (the audit and the backtest use the same code path)."""
    log = log or ctx.log
    data_dir = data_dir or ctx.data_dir
    H, from_bak = load_history(data_dir, log)
    missing = H is None
    if missing:
        H = empty_history()
        log("cycle: cycle_history.json chybí — spusť python tools/cycle_seed.py; panel ukáže jen dnešní hodnoty")
    if from_bak:
        ctx.warn("cycle_history.json byl poškozený — použita záloha .bak")
    loaded = len(H["weeks"])
    anomalies = []
    if fetch:
        steps = [("CMC globální data", lambda: update_global(ctx, H, now_ts, log)),
                 ("CMC žebříčky", lambda: update_listings(ctx, H, now_ts, log)),
                 ("Coin Metrics", lambda: update_coinmetrics(ctx, H, now_ts, log)),
                 ("memecoinová ekonomika", lambda: update_meme(ctx, H, now_ts, log)),
                 ("Upbit", lambda: update_upbit(ctx, H, now_ts, log)),
                 ("Coinbase", lambda: update_coinbase(ctx, H, now_ts, log)),
                 ("App Store", lambda: update_apps(ctx, H, now_ts, log)),
                 ("YouTube", lambda: update_youtube(ctx, H, now_ts, log)),
                 ("Tranco", lambda: update_tranco(ctx, H, now_ts, log)),
                 ("CBBI", lambda: update_cbbi(ctx, H, log)),
                 ("Cloudflare Radar", lambda: update_ai(ctx, H, now_ts, log))]
        for name, fn in steps:
            try:
                fn()
            except Exception as exc:
                ctx.warn("cycle: %s selhalo: %s" % (name, exc))
        try:
            save_history(data_dir, H, loaded)
        except Exception as exc:
            ctx.warn("cycle: historie nejde uložit: %s" % exc)
    R, summ = load_rules(data_dir)
    weeks = week_axis(now_ts)
    s = series_from_history(H, weeks, R)
    res = compute_index(weeks, s, R)
    ev = find_events(weeks, s)
    last = len(weeks) - 1
    I, ph = res["index"], res["phase"]
    # the headline's "před 3 měsíci": the week 13 weeks back
    i3 = last - 13
    first = next((i for i, w in enumerate(weeks) if w >= DISPLAY_FROM), 0)

    # --- BTC.D
    daily = _daily_series((H.get("daily") or {}).get("cmc", {}), 0)
    bd_now = daily[-1] if daily else None
    bd = s["btcd"]
    bd4 = roll_mean(bd, 4)
    chg13 = (bd4[last] - bd4[last - 13]) if (bd4[last] is not None and last >= 13 and bd4[last - 13] is not None) else None
    bd_verdict = None if chg13 is None else ("klesa" if chg13 <= -R["btcd_move_pp"]
                                             else "roste" if chg13 >= R["btcd_move_pp"] else "bokem")
    lows = {}
    for P in ("P1", "P2"):
        i = ev.get(P)
        if i is not None:
            lows[P] = [weeks[i], _r(bd[i], 2)]
    # the line through BTC.D's two altseason lows, extended to today: how far BTC.D
    # would have to fall to reach the level the last two altseasons topped at
    lows_line = None
    if ev.get("P1") is not None and ev.get("P2") is not None:
        i1, i2 = ev["P1"], ev["P2"]
        sl = (bd[i2] - bd[i1]) / (i2 - i1)
        now_v = bd[i2] + sl * (last - i2)
        cur = bd_now[1] if bd_now else bd[last]
        lows_line = {"t0": weeks[i1], "v0": _r(bd[i1], 3), "t1": weeks[i2], "v1": _r(bd[i2], 3),
                     "slope_week": _r(sl, 5), "line_now": _r(now_v, 2),
                     "dist_pp": _r(cur - now_v, 2) if cur is not None else None}

    # --- OTHERS.D
    od = s["othersd"]
    od_lines_all = trend_break(od, "down", R)
    od_lines = pick_lines(od_lines_all, len(weeks))
    latest = H.get("latest")
    od_out = [_line_out(L, weeks, od) for L in od_lines]
    unconfirmed = False
    for L, Lo in zip(od_lines, od_out):
        if latest and L["status"] == "downtrend":
            ln = od[L["anchor"]] + L["slope"] * ((latest["day"] - weeks[L["anchor"]]) / WEEK)
            Lo["latest_line"] = _r(ln, 3)
            Lo["latest_dist_pct"] = _r((latest["od"] / ln - 1) * 100, 1) if ln else None
            if ln and latest["od"] > ln * (1 + R["trend_break"]):
                unconfirmed = True
    recent_break = [L for L in od_lines if L["breakout"] is not None and last - L["breakout"] <= 13]
    if recent_break:
        L = max(recent_break, key=lambda L: L["weeks"])
        od_verdict = "zpet_pod" if L["status"] == "failed" else "pruraz"
    elif unconfirmed:
        od_verdict = "pruraz_nepotvrzeny"
    elif any(L["status"] == "downtrend" for L in od_lines):
        od_verdict = "downtrend"
    else:
        od_verdict = "bez_trendu"
    ou = s["others_usd"]
    ou_peak21 = max((x for w, x in zip(weeks, ou) if x and 1609459200 <= w <= 1640995199), default=None)
    ou_low = min((x for x in ou[-26:] if x), default=None)
    ou_now = (latest or {}).get("ou") or ou[last]

    # --- breadth
    Wl = (H.get("weeks") or {}).get(str(weeks[last])) or {}
    br = s["breadth"]
    br_now = br[last]
    br_verdict = None if br_now is None else ("alty_vedou" if br_now >= R["breadth_hi"]
                                              else "btc_vede" if br_now <= R["breadth_lo"] else "smisene")

    # --- heat
    heat = heat_block(res, s, weeks, ev, H)
    hv = res["heat"][last]
    heat_verdict = None if hv is None else ("brzy" if hv < R["heat_lo"] else "polovina" if hv < R["heat_hi"] else "prehraty")

    # --- history line: the same phase earlier, and what alts did next
    hint = None
    # not for the catch-all phase: "last time in no particular phase" is noise
    # dressed as evidence
    if ph[last] and ph[last] != "zima":
        eps = [e for e in phase_episodes(weeks, ph) if e[0] == ph[last]]
        cur = eps[-1] if eps and eps[-1][2] == last else None
        prior = [e for e in eps if e is not cur and weeks[e[1]] >= DISPLAY_FROM]
        rows = []
        for e in reversed(prior):
            a = e[1]
            if any(abs(weeks[a] - r["start"]) < 26 * WEEK for r in rows):
                continue
            j = a + 13
            r = {"start": weeks[a]}
            if j < len(weeks) and ou[a] and ou[j]:
                r["usd13"] = _r((ou[j] / ou[a] - 1) * 100, 0)
                if s["btc"][a] and s["btc"][j]:
                    r["vbtc13"] = _r(((ou[j] / ou[a]) / (s["btc"][j] / s["btc"][a]) - 1) * 100, 0)
            rows.append(r)
            if len(rows) == 2:
                break
        hint = {"phase": ph[last], "episodes": rows, "n_prior": len(prior)}

    retail = retail_block(ctx, H, weeks, now_ts, R)
    vol = volume_block(H, weeks, s, now_ts, R)
    disp = slice(0, len(weeks))          # full series: the audit recomputes every window from them
    block = {
        "version": (summ or {}).get("prereg_id") or "altseason-cycle-v1",
        "prereg_sha256": (summ or {}).get("prereg_sha256"),
        "as_of": weeks[last], "generated": int(now_ts), "history_missing": missing or loaded == 0,
        "rules": R,
        "index": _r(I[last], 1), "phase": ph[last], "index_3m_ago": _r(I[i3], 1) if i3 >= 0 else None,
        "rotation": _r(res["rotation"][last], 1), "heat": _r(hv, 1),
        # index inputs unrounded: a rounded input moves a percentile tie by 0,1 and
        # audit §37 recomputes every week from exactly these numbers
        "weeks": weeks[disp], "display_from": DISPLAY_FROM,
        "series": {"index": [_r(x, 1) for x in I[disp]], "rotation": [_r(x, 1) for x in res["rotation"][disp]],
                   "heat": [_r(x, 1) for x in res["heat"][disp]], "phase": ph[disp],
                   "btcd": list(bd[disp]), "othersd": list(od[disp]),
                   "breadth": list(br[disp]), "breadth4": [_r(x, 1) for x in res["br4"][disp]],
                   "dd52": [_r(x, 2) for x in res["dd"][disp]],
                   "others_usd": [_r(x, 0) for x in s["others_usd"][disp]], "btc": [_r(x, 2) for x in s["btc"][disp]],
                   "mvrv": list(s["mvrv"][disp]), "puell": list(s["puell"][disp]),
                   "mayer": list(s["mayer"][disp]), "pi": list(s["pi"][disp]),
                   "breakouts": [i for i, b in enumerate(s["breakouts"]) if b]},
        "components": {
            "btcd": {"value": _r(bd_now[1], 2) if bd_now else _r(bd[last], 2), "day": bd_now[0] if bd_now else None,
                     "week": _r(bd[last], 2), "chg13_pp": _r(chg13, 2), "dd52": _r(res["dd"][last], 1),
                     "verdict": bd_verdict, "lows": lows, "lows_line": lows_line,
                     "trend": [_line_out(L, weeks, bd) for L in pick_lines(trend_break(bd, "up", R), len(weeks))],
                     "source": "cmc"},
            "othersd": {"value": _r((latest or {}).get("od") or od[last], 3), "day": (latest or {}).get("day"),
                        "week": _r(od[last], 3), "verdict": od_verdict, "trend": od_out, "unconfirmed": unconfirmed,
                        "usd_bn": _r((ou_now or 0) / 1e9, 0), "usd_peak_2021_bn": _r((ou_peak21 or 0) / 1e9, 0),
                        "usd_low_26w_bn": _r((ou_low or 0) / 1e9, 0), "rise_score": _r(res["s_rise"][last], 1),
                        "source": "cmc"},
            "breadth": {"value": _r(br_now, 0), "mean4": _r(res["br4"][last], 1),
                        "beat": (Wl.get("br") or [None, None])[0], "n": (Wl.get("br") or [None, None])[1],
                        "leaders": Wl.get("lead") or [], "verdict": br_verdict, "source": "cmc"},
            "btc_heat": dict(heat, value=_r(hv, 0), verdict=heat_verdict),
            "retail": retail,
            "volume": vol,
        },
        "events": {k: weeks[i] for k, i in ev.items() if i is not None},
        "index_at_events": {k: _r(I[i], 1) for k, i in ev.items() if i is not None},
        "hint": hint,
        "backtest": {k: (summ or {}).get(k) for k in ("verdict", "chosen", "index_at", "eval_start", "generated_utc")}
        if summ else None,
        "anomalies": anomalies + s.get("anomalies", []),
    }
    json.dumps(block, allow_nan=False)        # one NaN would kill JSON.parse on the page
    return block
