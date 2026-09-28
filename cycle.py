"""
Altseason cycle — "is the altseason getting close to its end?"

Adam, 2026-09-27: "Hlavní point toho celého panelu je prostě uvidět aspoň zhruba,
že altseason se blíží konec, kdyby náhodou teď začal a trval rok." So the panel
is an exit gauge that works week by week (ARCHITECTURE §13.8):

    Altseason cyklus   0–100 = (2 x rotation + euphoria) / 3        (v2)
                         rotation  — BTC.D drawdown, OTHERS.D rise, breadth, on
                                     absolute scales
                         euphoria  — (retail + BTC heat) / 2
    phase              zima · btc_sezona · zacina · bezi · prehrate ("Blíží se
                       konec") · po_vrcholu
    tiles              Altseason cyklus, OTHERS (+ the TradingView line from the
                       2022 top), BTC.D, Retail, Objem

Retail measures what people DO — Coinbase and Upbit turnover, the memecoin
economy, the best-ranked crypto app — each row against its own four-year high on
a log scale; not what they look up: in the AI era lookups moved into chatbots
(Adam, 2026-09-26, on Wikipedia: "nikdo tam nechodí").

Inputs live in `cycle_history.json` (gitignored: CMC/DeFiLlama terms and Coin
Metrics' CC BY-NC forbid republishing the raw data; the page shows derived
numbers with sources named). `tools/cycle_seed.py` builds the long history once;
each collector run fetches only the missing tail. No module-level mutable state:
app.py calls the collector repeatedly in one process.

Every threshold is pre-registered in cycle_backtest.py (PREREG_V2 + lock,
2026-09-27). v1 (PREREG, percentile rotation, FAIL) stays locked and reported:
trend_break, pick_lines and compute_index are its code path and read V1_RULES.
"""
import bisect
import datetime
import gzip
import io
import json
import math
import os
import re
import statistics
import time

DAY = 86400
WEEK = 7 * DAY
HISTORY_NAME = "cycle_history.json"
SUMMARY_NAME = "cycle_backtest_summary.json"
HISTORY_VERSION = 1
START_WEEK = 1404691200            # Monday 2014-07-07: scoring 2017 needs a 52-week window + 104 weeks
DAILY_START = 1451606400           # 2016-01-01 for CMC daily (volume needs a 1-year median before 2017)
CM_START = "2012-01-01"            # Coin Metrics BTC: Pi Cycle's 350-day mean needs a year before 2014-07
DISPLAY_FROM = 1451865600          # 2016-01-04: nothing earlier is drawn ("2013 me nezajímá")
V2_ID = "altseason-cycle-v2"       # = cycle_backtest.PREREG_V2["id"]
V3_ID = "altseason-cycle-v3"       # = cycle_backtest.PREREG_V3["id"]; the page runs v3
LEDGER_NAME = "cycle_ledger.jsonl"

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

# v2 (cycle_backtest.PREREG_V2, locked 2026-09-27). The first block must equal the
# registration's "rules" — cycle_backtest refuses a drift; the second block only
# words the tiles and never enters the index.
V2_RULES = {
    "T": 75, "window": 208, "min_window": 104,
    "rot_dd_full": 50, "rot_rise_full": 3, "rot_breadth_lo": 25, "rot_breadth_hi": 90, "rot_min_parts": 2,
    "rot_weight": 2, "euph_weight": 1,
    "retail_window": 208, "retail_warmup": 52, "retail_span": 20, "retail_min_rows": 1,
    "coinbase_days": 30, "coinbase_min_days": 20, "meme_start_usd": 5000000, "apps_max_age_days": 7,
    "prehrate_euphoria": 70, "bezi_rotation": 60,
    "zacina_rotation": 30, "zacina_rise": 15, "zacina_weeks": 13,
    "btc_sezona_heat": 50, "btc_sezona_rotation": 30,
    "po_vrcholu_drop": 15, "po_vrcholu_weeks": 26, "po_vrcholu_min": 2,
    "trend_window": 312, "trend_pivot": 4, "trend_break": 0.03, "trend_confirm": 2, "trend_back_weeks": 13,
    "breadth_hi": 75, "breadth_lo": 25, "btcd_move_pp": 1.5, "heat_lo": 40, "heat_hi": 75,
    "retail_lo": 35, "retail_hi": 70, "retail_rush": 25, "vol_lo": 0.8, "vol_mid": 1.5, "vol_hi": 2.5,
}

# v3 (cycle_backtest.PREREG_V3, registered 2026-09-28 before any v3 number was
# computed on real data). Three independent reviews found that v2 could miss the
# NEXT altseason: BTC.D's floor rises every cycle (32,8 % in 2018, 37,9 % in 2022),
# so a real rotation from 65 % to 45 % is only a 31 % drawdown and scores 62 on
# v2's fixed "50 % = full" scale; and an altseason that ran flat for longer than a
# year would drift out of v2's one-year windows and read "Po vrcholu" with nothing
# turned. v3 measures BTC.D as the share of the way from its 52-week high down to
# the previous cycle's low, tolerates one missing week in a 4-week mean, lets
# "Blíží se konec" / "Po vrcholu" fire in an altseason that never reaches 75, and
# calls "Po vrcholu" only when alts have really fallen in dollars (25 % off their
# half-year high). The first block is the registration's "rules".
V3_RULES = {
    "T": 75, "window": 208, "min_window": 104, "roll_min": 3,
    "rot_floor_window": 312, "rot_floor_gap": 52, "rot_floor_min": 52,
    "rot_span_min": 25, "rot_rise_full": 3, "rot_breadth_lo": 25, "rot_breadth_hi": 90, "rot_min_parts": 2,
    "rot_weight": 2, "euph_weight": 1, "heat_max_age_days": 7,
    "retail_window": 208, "retail_warmup": 52, "retail_span": 20, "retail_min_rows": 1,
    "coinbase_days": 30, "coinbase_min_days": 20, "meme_start_usd": 5000000, "meme_max_age_days": 7,
    "apps_max_age_days": 7,
    "prehrate_euphoria": 70, "bezi_rotation": 60,
    "zacina_rotation": 30, "zacina_rise": 15, "zacina_weeks": 13,
    "btc_sezona_heat": 50, "btc_sezona_rotation": 30,
    "po_vrcholu_drop": 15, "po_vrcholu_weeks": 26, "po_vrcholu_min": 4, "po_vrcholu_usd_drop": 25,
    "trend_window": 312, "trend_pivot": 4, "trend_break": 0.03, "trend_confirm": 2, "trend_back_weeks": 13,
    "breadth_hi": 75, "breadth_lo": 25, "btcd_move_pp": 1.5, "heat_lo": 40, "heat_hi": 75,
    "retail_lo": 35, "retail_hi": 70, "retail_rush": 25, "vol_lo": 0.8, "vol_mid": 1.5, "vol_hi": 2.5,
}

# The rules the page runs: v3. load_rules lays the v3 section of the backtest
# summary over them (T, fixed at 75 by the registration); the page reads every
# threshold from the snapshot's `rules`.
DEFAULT_RULES = dict(V3_RULES)


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


def roll_mean_min(series, n, k):
    """Mean of the values present among the last n weeks, at least k of them (v3).
    v2's roll_mean needed all four: one lost CMC listing blanked the index for four
    weeks, and a held-back newest week (clean_spikes) would blank it for this week."""
    out = []
    for i in range(len(series)):
        w = [v for v in series[max(0, i - n + 1):i + 1] if v is not None]
        out.append(sum(w) / len(w) if (i >= n - 1 and len(w) >= k) else None)
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
            "meme": {}, "tranco": {"monthly": {}, "daily": {}}, "apps": [], "ai": None, "cbbi": None,
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
                # YouTube's API policy forbids keeping its statistics past 30 days
                # and aggregating them across channels: the ledger goes on load
                base.pop("yt", None)
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
    """OTHERS.D (CMC's ranked list: ranks 11–125 of the top 125, stablecoins in;
    TradingView also counts the unranked derivatives and reads higher), OTHERS in USD, BTC vs alt volume, and breadth: the top 50 alts that beat
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


# ================================================================== trendline v2
def pivot_flags(c, mode="down", k=4):
    """A pivot high (mode down; a pivot low for up) is a close that is the most
    extreme of ±k weeks and strictly more extreme than the k weeks before it (a
    plateau's first week). It reads k weeks after itself; trend_line only ever uses
    pivots that old, so flagging them over the whole series looks nothing ahead."""
    d = 1.0 if mode == "down" else -1.0
    n = len(c)
    out = [False] * n
    for j in range(n):
        if c[j] is None:
            continue
        ok = True
        for x in range(max(0, j - k), min(n, j + k + 1)):
            if x == j or c[x] is None:
                continue
            if d * c[x] > d * c[j] or (x < j and d * c[x] >= d * c[j]):
                ok = False
                break
        out[j] = ok
    return out


def trend_line(vals, mode="down", t=None, rules=None, latest=None, pivots=None):
    """The line Adam draws on TradingView, as of week t (closes up to t only).

    OTHERS.D (mode down, resistance): the anchor is the highest weekly close of the
    last 312 weeks — six years, because with 260 the 2022-01-03 top (20,43 %) would
    drop out on 2026-12-28 and the status would change with no price move. The line
    runs from it over the confirmed pivot highs down to the bottom: the lowest close
    since the anchor that is at least 4 weeks old, so the bounce highs after it are
    not in the hull and a breakout does not redraw its own line. A new bottom after a
    failed break puts the false-break highs inside the hull and redraws the line over
    them. BTC.D (mode up) mirrors it: support from the lowest close (2022-11-28,
    37,88 %) under the higher lows up to the top.

    Status (PREREG_V2): bez_trendu (no line: the week is itself the extreme, no
    bottom yet, no pivot) · pruraz (two consecutive closes > 3 % beyond, and no close
    back inside the line since — a retest that holds keeps it) · pruraz_nepotvrzeny
    (one close beyond; or only the newest daily point `latest` = (fractional week
    index, value)) · zpet_pod (a break within 13 weeks, then a close back inside) ·
    downtrend. Returns indexes; `_line_out_v2` turns them into week stamps."""
    R = dict(V2_RULES, **(rules or {}))
    c = vals
    n = len(c)
    d = 1.0 if mode == "down" else -1.0
    k = R["trend_pivot"]
    if t is None:
        t = max((i for i in range(n) if c[i] is not None), default=None)
    res = {"status": "bez_trendu", "t": t, "anchor": None, "touch": None, "opp": None, "slope": None,
           "line_t": None, "break_first": None, "break_at": None, "back_at": None}
    if t is None:
        return res
    a = None
    for i in range(max(0, t - R["trend_window"] + 1), t + 1):
        if c[i] is not None and (a is None or d * c[i] > d * c[a]):
            a = i
    if a is None or a == t:
        return res
    o = None
    for i in range(a + 1, t - k + 1):
        if c[i] is not None and (o is None or d * c[i] <= d * c[o]):
            o = i
    if o is None:
        return res
    if pivots is None:
        pivots = pivot_flags(c[:t + 1], mode, k)
    best = None
    for j in range(a + 1, o):
        if pivots[j]:
            sl = (c[j] - c[a]) / (j - a)
            if best is None or d * sl > d * best[0]:
                best = (sl, j)
    if best is None:
        return res
    s, touch = best
    line = lambda x: c[a] + s * (x - a)
    if line(t) <= 0:
        return res
    b = R["trend_break"]
    beyond = lambda i: c[i] is not None and d * c[i] > d * line(i) * (1 + d * b)
    inside = lambda i: c[i] is not None and d * c[i] <= d * line(i)
    after = [i for i in range(o + 1, t + 1) if c[i] is not None]
    brk, first, run = None, None, 0
    for i in after:
        if beyond(i):
            run += 1
            if run == 1:
                start = i
            if run >= R["trend_confirm"]:
                brk, first = i, start
        else:
            run = 0
    back = next((i for i in after if brk is not None and i > brk and inside(i)), None)
    if brk is not None and back is None:
        status = "pruraz"
    elif beyond(t):
        status = "pruraz_nepotvrzeny"
    elif brk is not None and t - brk <= R["trend_back_weeks"]:
        status = "zpet_pod"
    elif latest is not None and latest[1] is not None and line(latest[0]) > 0 \
            and d * latest[1] > d * line(latest[0]) * (1 + d * b):
        status = "pruraz_nepotvrzeny"
    else:
        status = "downtrend"
    res.update({"status": status, "anchor": a, "touch": touch, "opp": o, "slope": s, "line_t": line(t),
                "break_first": first, "break_at": brk, "back_at": back})
    return res


def trend_weekly(vals, mode="down", rules=None):
    """The weekly status at every week (each on closes up to it, no daily point) and
    the breakout events the index uses: weeks whose status is pruraz after a week
    that was not. A week without a close (a dropped spike) carries the status over."""
    R = dict(V2_RULES, **(rules or {}))
    piv = pivot_flags(vals, mode, R["trend_pivot"])
    st, prev = [], None
    for t in range(len(vals)):
        if vals[t] is not None:
            prev = trend_line(vals, mode, t, R, pivots=piv)["status"]
        st.append(prev)
    ev = [vals[t] is not None and st[t] == "pruraz" and (t == 0 or st[t - 1] != "pruraz") for t in range(len(vals))]
    return st, ev


# ================================================================== BTC heat
def heat_metrics(cm_btc, weeks, max_age=1):
    """MVRV ratio, Puell, Mayer, Pi Cycle ratio at each week (value of the day
    before the Monday stamp; with max_age > 1 the newest day with a price among the
    max_age days before it — v3: one late Coin Metrics day must not blank the week).
    MVRV ratio, not MVRV-Z: Z divides by the standard deviation of the WHOLE series,
    which leaks the future into the past."""
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
        i = next((j for j in ((w - a * DAY - t0) // DAY for a in range(1, max_age + 1))
                  if 0 <= j < nd and price[j] is not None), -1)
        if i < 0:
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


PHASES_V2 = ("po_vrcholu", "prehrate", "bezi", "zacina", "btc_sezona", "zima")


def clamp100(x):
    return None if x is None else max(0.0, min(100.0, x))


def rotation_v2(s, R):
    """Rotation on absolute scales (v2). v1 ranked each part against its own trailing
    four years: 2022–24 held no altseason, so a 3–12 % BTC.D dip scored 60–70 and the
    index read 64 in 2024-03 and 2024-12 with no altseason at all. Here a 50 % BTC.D
    drawdown, OTHERS.D at 3x its 52-week low and 90 % breadth each score 100."""
    n = len(s["btcd"])
    bd4, od4, br4 = roll_mean(s["btcd"], 4), roll_mean(s["othersd"], 4), roll_mean(s["breadth"], 4)
    dd, rise, p_dd, p_rise, p_br, rot = [], [], [], [], [], []
    for i in range(n):
        w = [x for x in bd4[max(0, i - 51):i + 1] if x is not None]
        dd.append(100.0 * (1 - bd4[i] / max(w)) if (bd4[i] is not None and len(w) >= 40) else None)
        w = [x for x in od4[max(0, i - 51):i + 1] if x is not None]
        rise.append(100.0 * (od4[i] / min(w) - 1) if (od4[i] is not None and len(w) >= 40 and min(w) > 0) else None)
        p_dd.append(clamp100(100.0 * dd[i] / R["rot_dd_full"]) if dd[i] is not None else None)
        p_rise.append(clamp100(100.0 * math.log(1 + rise[i] / 100.0) / math.log(R["rot_rise_full"]))
                      if rise[i] is not None else None)
        p_br.append(clamp100(100.0 * (br4[i] - R["rot_breadth_lo"]) / (R["rot_breadth_hi"] - R["rot_breadth_lo"]))
                    if br4[i] is not None else None)
        parts = [p for p in (p_dd[i], p_rise[i], p_br[i]) if p is not None]
        rot.append(sum(parts) / len(parts) if len(parts) >= R["rot_min_parts"] else None)
    return {"dd": dd, "rise": rise, "br4": br4, "p_dd": p_dd, "p_rise": p_rise, "p_breadth": p_br, "rotation": rot}


def compute_index_v2(weeks, s, rows, rules=None):
    """The v2 index (PREREG_V2) from the stored raw weekly series.

    s: btcd, othersd, breadth, mvrv, puell, mayer, pi (as series_from_history);
    rows: the retail rows' raw weekly samples (retail_rows). Rotation on absolute
    scales; euphoria = (retail + BTC heat) / 2; I = (2 x rotation + euphoria) / 3.
    Phases, first match: po_vrcholu · prehrate · bezi · zacina · btc_sezona · zima."""
    R = dict(V2_RULES, **(rules or {}))
    n = len(weeks)
    ro = rotation_v2(s, R)
    rot = ro["rotation"]
    heat_parts, heat, rs, retail, euph = euphoria_parts(s, rows, R, n)
    wr, we = R["rot_weight"], R["euph_weight"]
    idx = [(wr * rot[i] + we * euph[i]) / (wr + we) if (rot[i] is not None and euph[i] is not None) else None
           for i in range(n)]
    od_status, brk = trend_weekly(s["othersd"], "down", R)
    T = R["T"]
    phase = []
    for i in range(n):
        I = idx[i]
        if I is None:
            phase.append(None)
            continue
        r, eu, he = rot[i], euph[i], heat[i]
        prior = [idx[j] for j in range(max(0, i - R["po_vrcholu_weeks"]), i) if idx[j] is not None and idx[j] >= T]
        back = rot[i - R["zacina_weeks"]] if i >= R["zacina_weeks"] else None
        if len(prior) >= R["po_vrcholu_min"] and I <= max(prior) - R["po_vrcholu_drop"]:
            ph = "po_vrcholu"
        elif I >= T and eu >= R["prehrate_euphoria"]:
            ph = "prehrate"
        elif r >= R["bezi_rotation"] or I >= T:
            ph = "bezi"
        elif r >= R["zacina_rotation"] and ((back is not None and r - back >= R["zacina_rise"])
                                            or any(brk[max(0, i - R["zacina_weeks"]):i + 1])):
            ph = "zacina"
        elif he >= R["btc_sezona_heat"] and r < R["btc_sezona_rotation"]:
            ph = "btc_sezona"
        else:
            ph = "zima"
        phase.append(ph)
    out = dict(ro)
    out.update({"heat_parts": heat_parts, "heat": heat, "retail_scores": rs, "retail": retail, "euphoria": euph,
                "index": idx, "phase": phase, "od_status": od_status, "breakouts": brk})
    return out


def euphoria_parts(s, rows, R, n):
    """BTC heat, the retail rows' scores, retail and euphoria — the same in v2 and v3."""
    heat_parts = {k: trailing_pct(s[k], R["window"], R["min_window"]) for k in ("mvrv", "puell", "mayer", "pi")}
    heat = [mean([heat_parts[k][i] for k in heat_parts]) if sum(
        1 for k in heat_parts if heat_parts[k][i] is not None) >= 3 else None for i in range(n)]
    rs = retail_scores(rows, R)
    retail = []
    for i in range(n):
        xs = [rs[k][i] for k in rs if rs[k][i] is not None]
        retail.append(sum(xs) / len(xs) if len(xs) >= R["retail_min_rows"] else None)
    euph = [(retail[i] + heat[i]) / 2 if (retail[i] is not None and heat[i] is not None) else None for i in range(n)]
    return heat_parts, heat, rs, retail, euph


def rotation_v3(s, R):
    """Rotation v3 (PREREG_V3): v2's one-year view with the BTC.D part rescaled to
    the rising floor.

    - BTC.D path: how much of the way from its 52-week high P down to the previous
      cycle's low F BTC.D has travelled: (P - B) / max(P - F, 25); 100 = at or under
      F. F = the lowest 4-week mean of the weeks t-311..t-52 (the last cycle's low,
      not this year's). The span is at least 25 pp, so a dip just above an old low
      (2022, when the stablecoins' share pushed BTC.D down in a bear market) does
      not read as a full rotation.
    - OTHERS.D rise from its 52-week low, breadth: as in v2.
    - 4-week means need 3 of the 4 weeks.
    Tried and rejected before registration (synthetic history): anchoring P at the
    previous cycle's low instead of a rolling year kept 2022's bear market at a
    rotation of 85 ("Altseason jede" for half a year), because BTC.D stayed far
    under 2019's high. The one-year view stays; a long flat altseason is handled in
    the phases (po_vrcholu needs alts to have fallen in dollars)."""
    n = len(s["btcd"])
    k = R["roll_min"]
    bd4, od4, br4 = roll_mean_min(s["btcd"], 4, k), roll_mean_min(s["othersd"], 4, k), roll_mean_min(s["breadth"], 4, k)
    fw, fg = R["rot_floor_window"], R["rot_floor_gap"]
    out = {k_: [None] * n for k_ in ("peak_at", "floor", "floor_at", "path", "low_at", "rise", "p_dd", "p_rise",
                                     "p_breadth", "rotation")}
    for i in range(n):
        fl = [(bd4[j], -j) for j in range(max(0, i - fw + 1), i - fg + 1) if bd4[j] is not None]
        if len(fl) >= R["rot_floor_min"]:
            f, fa = min(fl)
            out["floor"][i], out["floor_at"][i] = f, -fa                # ties: the latest week
        w = [(bd4[j], -j) for j in range(max(0, i - 51), i + 1) if bd4[j] is not None]
        if bd4[i] is not None and len(w) >= 40 and out["floor"][i] is not None:
            pa = -max(w)[1]                                             # ties: the earliest week
            out["peak_at"][i] = pa
            out["path"][i] = 100.0 * (bd4[pa] - bd4[i]) / max(bd4[pa] - out["floor"][i], R["rot_span_min"])
            out["p_dd"][i] = clamp100(out["path"][i])
        w = [(od4[j], j) for j in range(max(0, i - 51), i + 1) if od4[j] is not None]
        if od4[i] is not None and len(w) >= 40 and min(w)[0] > 0:
            lv, la = min(w)                                             # ties: the earliest week
            out["low_at"][i] = la
            out["rise"][i] = 100.0 * (od4[i] / lv - 1)
            out["p_rise"][i] = clamp100(100.0 * math.log(1 + out["rise"][i] / 100.0) / math.log(R["rot_rise_full"]))
        if br4[i] is not None:
            out["p_breadth"][i] = clamp100(100.0 * (br4[i] - R["rot_breadth_lo"]) / (R["rot_breadth_hi"] - R["rot_breadth_lo"]))
        parts = [p for p in (out["p_dd"][i], out["p_rise"][i], out["p_breadth"][i]) if p is not None]
        out["rotation"][i] = sum(parts) / len(parts) if len(parts) >= R["rot_min_parts"] else None
    out.update({"bd4": bd4, "od4": od4, "br4": br4})
    return out


def compute_index_v3(weeks, s, rows, rules=None):
    """The v3 index (PREREG_V3): rotation_v3, euphoria as in v2, I = (2 x rotation +
    euphoria) / 3. Phases, first match:
      po_vrcholu  at least 4 of the 26 weeks before t in bezi or prehrate, I at
                  least 15 under the highest index of those 26 weeks, and OTHERS in
                  dollars (4-week mean) at least 25 % under its high of the 26 weeks
                  before t and t — alts have really fallen, not only the one-year
                  windows drifted on a long plateau
      prehrate    euphoria >= 70 and (I >= 75 or rotation >= 60)
      bezi        rotation >= 60 or I >= 75
      zacina      rotation >= 30 and (up 15 in 13 weeks or an OTHERS.D breakout in
                  the 13 weeks t-12..t)
      btc_sezona  heat >= 50 and rotation < 30
      zima        otherwise
    v2 needed I >= 75 for both exit phases; an altseason whose rotation stops short
    of v2's scale would have run to the end without either."""
    R = dict(V3_RULES, **(rules or {}))
    n = len(weeks)
    ro = rotation_v3(s, R)
    rot = ro["rotation"]
    heat_parts, heat, rs, retail, euph = euphoria_parts(s, rows, R, n)
    wr, we = R["rot_weight"], R["euph_weight"]
    idx = [(wr * rot[i] + we * euph[i]) / (wr + we) if (rot[i] is not None and euph[i] is not None) else None
           for i in range(n)]
    od_status, brk = trend_weekly(s["othersd"], "down", R)
    ou4 = roll_mean_min(s.get("others_usd") or [None] * n, 4, R["roll_min"])
    T, W = R["T"], R["zacina_weeks"]
    phase = []
    for i in range(n):
        I = idx[i]
        if I is None:
            phase.append(None)
            continue
        r, eu, he = rot[i], euph[i], heat[i]
        j0 = max(0, i - R["po_vrcholu_weeks"])
        on = sum(1 for p in phase[j0:i] if p in ("bezi", "prehrate"))
        top = max((x for x in idx[j0:i] if x is not None), default=None)
        back = rot[i - W] if i >= W else None
        uh = max((x for x in ou4[j0:i + 1] if x is not None), default=None)
        fell = ou4[i] is not None and uh is not None and ou4[i] <= uh * (1 - R["po_vrcholu_usd_drop"] / 100.0)
        if on >= R["po_vrcholu_min"] and top is not None and I <= top - R["po_vrcholu_drop"] and fell:
            ph = "po_vrcholu"
        elif eu >= R["prehrate_euphoria"] and (I >= T or r >= R["bezi_rotation"]):
            ph = "prehrate"
        elif r >= R["bezi_rotation"] or I >= T:
            ph = "bezi"
        elif r >= R["zacina_rotation"] and ((back is not None and r - back >= R["zacina_rise"])
                                            or any(brk[max(0, i - W + 1):i + 1])):
            ph = "zacina"
        elif he >= R["btc_sezona_heat"] and r < R["btc_sezona_rotation"]:
            ph = "btc_sezona"
        else:
            ph = "zima"
        phase.append(ph)
    out = dict(ro)
    out.update({"heat_parts": heat_parts, "heat": heat, "retail_scores": rs, "retail": retail, "euphoria": euph,
                "index": idx, "phase": phase, "od_status": od_status, "breakouts": brk})
    return out


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


RETAIL_ROWS = ("coinbase", "upbit", "degen", "apps")


def retail_rows(H, weeks, rules=None):
    """The retail rows' raw weekly samples, each read on the day before the stamp.
    Weekly only, so audit §37 can recompute every score and every four-year max from
    exactly the stored numbers (v1 mixed daily points in). Returns (rows, picks):
    picks[i] = (label, overall, finance, day) of the app behind the apps sample."""
    R = dict(V2_RULES, **(rules or {}))
    # Coinbase: BTC-USD + ETH-USD; a day counts when BTC-USD has it and, from ETH-USD's
    # first day (2016-05-18), ETH-USD too — a failed ETH page used to count as $0 and
    # pulled the row down with no warning
    cb = H.get("cbx") or {}
    btc, eth = cb.get("BTC-USD") or {}, cb.get("ETH-USD") or {}
    eth0 = COINBASE_PAIRS[1][1]
    daily = {int(k): v + (eth.get(k) or 0) for k, v in btc.items()
             if v is not None and (int(k) < eth0 or eth.get(k) is not None)}
    coin = []
    for w in weeks:
        xs = [daily[t] for t in range(w - R["coinbase_days"] * DAY, w, DAY) if t in daily]
        coin.append(sum(xs) / len(xs) if len(xs) >= R["coinbase_min_days"] else None)
    # Upbit: the 4 weekly candles before the stamp. A candle is keyed by its UTC start
    # date; the nearest Monday aligns it whether the week opens at 00:00 UTC or KST.
    U = {monday(int(k) + 3 * DAY): v for k, v in (H.get("upbit") or {}).items()}
    up = []
    for w in weeks:
        xs = [U.get(w - j * WEEK) for j in range(1, 5)]
        up.append(sum(xs) if all(x is not None for x in xs) else None)
    # the memecoin economy from its first $5M day: before it the category barely
    # existed, and a series growing from nothing would read its own high every week
    M = {int(k): v for k, v in (H.get("meme30") or {}).items() if v is not None}
    m0 = min((t for t, v in M.items() if v >= R["meme_start_usd"]), default=None)
    # (v3: the newest of the meme_max_age_days days before the stamp — only a run on
    # the day adds that day's value, so a Monday without a run lost the week)
    age = R.get("meme_max_age_days", 1)
    meme = [next((M[w - a * DAY] for a in range(1, age + 1) if (w - a * DAY) in M and w - a * DAY >= m0), None)
            if (m0 is not None and w - DAY >= m0) else None for w in weeks]
    # App Store: the newest ledger entry of the 7 days before the stamp
    led = sorted(H.get("apps") or [], key=lambda x: x[0])
    days = [x[0] for x in led]
    apps, picks = [], []
    for w in weeks:
        j = bisect.bisect_right(days, w - DAY) - 1
        if j < 0 or days[j] < w - R["apps_max_age_days"] * DAY:
            apps.append(None)
            picks.append(None)
            continue
        day, ent = led[j]
        best = None
        for aid, label, scored in APPS:
            if scored:
                o, fin = (ent.get(aid) or [None, None])[:2]
                sc = app_score(o, fin)
                if best is None or sc > best[0]:
                    best = (sc, label, o, fin, day)
        apps.append(best[0])
        picks.append(best[1:])
    return {"coinbase": coin, "upbit": up, "degen": meme, "apps": apps}, picks


def retail_scores(rows, rules=None):
    """Row score = 100 x clamp(1 + ln(x / M) / ln 20, 0, 1), M = the row's max over
    the last 208 weekly samples: 100 = at its four-year high, 0 = at a twentieth of
    it. Log, because retail activity moves 10–30x between a bear market and a mania;
    trailing, so the past reads as it read then (the causal version of Cowen's
    min–max). The first 52 weeks of a row are warm-up — Upbit, from 2017-10, would
    otherwise read 100 at the 2017-12 top while it was still growing from launch.
    Zero and missing samples are skipped, never passed to ln (the memecoin series
    has 1 262 zero days). The App Store row is already 0–100 and is used as is."""
    R = dict(V2_RULES, **(rules or {}))
    span = math.log(R["retail_span"])
    out = {}
    for key, xs in rows.items():
        if key == "apps":
            out[key] = [clamp100(x) for x in xs]
            continue
        sc = [None] * len(xs)
        first = next((i for i, x in enumerate(xs) if x is not None and x > 0), None)
        if first is not None:
            for i in range(first + R["retail_warmup"], len(xs)):
                x = xs[i]
                if x is None or x <= 0:
                    continue
                m = max(y for y in xs[max(0, i - R["retail_window"] + 1):i + 1] if y is not None and y > 0)
                sc[i] = 100.0 * max(0.0, min(1.0, 1 + math.log(x / m) / span))
        out[key] = sc
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
    """Weekly KRW turnover of one market back to `since`: {monday: krw}, or None
    when a call fails (an empty answer is a market with no candles, not a failure)."""
    out = {}
    to = None
    for _ in range(6):
        url = "https://api.upbit.com/v1/candles/weeks?market=%s&count=%d%s" % (
            market, count, ("&to=" + to) if to else "")
        d = ctx.get(url, timeout=30, warn=False, quiet_status=())
        time.sleep(0.13)
        if d is None:
            return None
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
    coins are missing from old weeks, so old levels are understated (mostly
    2018–19, outside today's four-year window).

    The sum is only as good as its markets: a market whose call failed would make
    the week read low and overwrite a good stored value, and the retail score would
    sink with nobody told. So a run with failed markets writes nothing and warns
    (stale beats empty); the next run tries again."""
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
    failed = []
    for i, m in enumerate(markets):
        wk = upbit_weeks(ctx, m, since, count=200 if first else 5)
        if wk is None:
            failed.append(m)
            continue
        for t, v in wk.items():
            if t <= last_complete:
                sums[t] = sums.get(t, 0) + v
        if first and i % 50 == 49:
            log("cycle: Upbit %d/%d trhů" % (i + 1, len(markets)))
    if failed:
        ctx.warn("Upbit: %d z %d trhů nedostupných (%s…) — týdenní obrat se neuložil, zůstávají starší data"
                 % (len(failed), len(markets), ", ".join(failed[:3])))
        return 0
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
        entries = ((d or {}).get("feed") or {}).get("entry") or []
        # a chart that did not come back is not "no crypto app in the top 100": an
        # entry with empty ranks scores 5 and dragged retail down with no warning
        if len(entries) < 50:
            ctx.warn("cycle: App Store žebříček %s nepřišel (%d položek) — den se nezapisuje" % (key, len(entries)))
            return False
        for i, e in enumerate(entries, 1):
            try:
                ranks.setdefault(e["id"]["attributes"]["im:id"], {})[key] = i
            except (KeyError, TypeError):
                continue
    ids = ",".join(a for a, _, _ in APPS)
    lk = ctx.get("https://itunes.apple.com/lookup?id=%s&country=us" % ids, timeout=30, quiet_status=())
    ratings = {str(r.get("trackId")): r.get("userRatingCount") for r in (lk or {}).get("results") or []}
    entry = {a: [(ranks.get(a) or {}).get("o"), (ranks.get(a) or {}).get("f"), ratings.get(a)] for a, _, _ in APPS}
    day = day0(now_ts)
    led = H.setdefault("apps", [])
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
    """Raw weekly inputs of the index, aligned with `weeks`. `rules` carries v3's
    heat_max_age_days (v1/v2: the day before the stamp only)."""
    W = H.get("weeks") or {}
    g = lambda w, k: (W.get(str(w)) or {}).get(k)
    br = []
    for w in weeks:
        b = g(w, "br")
        br.append(100.0 * b[0] / b[1] if (b and b[1] >= 30) else None)
    s = {"btcd": [g(w, "bd") for w in weeks], "othersd": [g(w, "od") for w in weeks],
         "others_usd": [g(w, "ou") for w in weeks], "breadth": br,
         "btc": btc_weekly(H, weeks)}
    s.update(heat_metrics(cm_days(H), weeks, (rules or {}).get("heat_max_age_days", 1)))
    s["anomalies"] = clean_spikes(weeks, s)
    return s


def v1_breakouts(od):
    """v1's OTHERS.D breakout weeks (trend_break), for the locked v1 report only;
    v2's come from trend_weekly."""
    brk = [False] * len(od)
    for L in trend_break(od, "down"):
        if L["breakout"] is not None:
            brk[L["breakout"]] = True
    return brk


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
        # the newest week has no right-hand neighbour: judged by the two before it,
        # a spike is held back ("held") and the week is judged again, with both
        # neighbours, once the next week exists. It used to pass unchecked into the
        # tile and the ledger, and the history rewrote it a week later.
        L = len(v) - 1
        if L >= 2 and None not in (v[L - 2], v[L - 1], v[L]) and v[L - 2] > 0 and v[L - 1] > 0:
            a, c, b = v[L - 2], v[L - 1], v[L]
            if abs(a / c - 1) <= agree and abs(b / ((a + c) / 2) - 1) > jump:
                out.append({"week": weeks[L], "series": key, "value": round(b, 4),
                            "neighbours": [round(a, 4), round(c, 4)], "held": True})
                v[L] = None
                if key == "othersd":
                    s["others_usd"][L] = None
                    s["breadth"][L] = None
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
    """v3's rules with the v3 section of the backtest summary laid over them (T,
    which PREREG_V3 fixes at 75). v1's and v2's sections belong to their locked
    reports and never reach the page. Returns (rules, the summary's v3 section or
    None, the whole summary or None)."""
    rules = dict(DEFAULT_RULES)
    summ = None
    try:
        summ = json.load(io.open(os.path.join(data_dir, SUMMARY_NAME), encoding="utf-8"))
    except (OSError, ValueError):
        pass
    v3 = (summ or {}).get("v3")
    if isinstance(v3, dict) and v3.get("prereg_id") == V3_ID:
        rules.update(v3.get("rules") or {})
    else:
        v3 = None
    return rules, v3, summ


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
    # weekly samples of the 7-day average for the chart (2016 ->, as every chart), BTC price beside it
    pos = {d: i for i, d in enumerate(ds)}
    chart_w = [w for w in weeks if w >= DISPLAY_FROM]
    ser = [_r(avg7[pos[w - DAY]] / 1e9, 1) if (w - DAY) in pos and avg7[pos[w - DAY]] else None for w in chart_w]
    btc = s["btc"]
    wi = {w: i for i, w in enumerate(weeks)}
    return {"day": ds[last], "vol24h": _r(vs[last] / 1e9, 1), "avg7": _r(avg7[last] / 1e9, 1) if avg7[last] else None,
            "ratio_1y": _r(rt, 2), "verdict": verdict,
            "alt_share": _r(sh4[-1], 1), "alt_share_13w": _r(sh4[-14] if len(sh4) > 14 else None, 1),
            "alt_share_2021": _r(max((x for w, x in zip(weeks, sh4) if x is not None
                                      and 1609459200 <= w <= 1640995199), default=None), 1),
            "chart": {"weeks": chart_w, "avg7_bn": ser, "btc": [_r(btc[wi[w]], 0) for w in chart_w]},
            "fake_volume_span": [1546300800, 1609459199]}


def retail_block(ctx, H, weeks, rows, picks, res, R):
    """Retail v2 for the tile and the table. The value, the verdict and the tempo
    are the weekly index at the newest week — the number the euphoria pillar used.
    Each scored row shows its newest weekly sample against its own four-year max;
    the score is the one at the newest week (none when the row has no sample
    there, and then it is not in the value). Facts beside it are never scored."""
    last = len(weeks) - 1
    rs, ser = res["retail_scores"], res["retail"]

    def newest(key):
        xs = rows[key]
        i = next((j for j in range(last, -1, -1) if xs[j] is not None and xs[j] > 0), None)
        if i is None:
            return None
        win = [(xs[j], j) for j in range(max(0, i - R["retail_window"] + 1), i + 1) if xs[j] is not None and xs[j] > 0]
        top, jt = max(win, key=lambda p: (p[0], -p[1]))
        return i, xs[i], top, jt
    parts = {}
    x = newest("coinbase")
    if x:
        i, v, top, jt = x
        parts["coinbase"] = {"score": _r(rs["coinbase"][last], 1), "week": weeks[i], "usd30_bn": _r(v / 1e9, 2),
                             "max_bn": _r(top / 1e9, 2), "max_week": weeks[jt], "pct_of_max": _r(100.0 * v / top, 1)}
    x = newest("upbit")
    if x:
        i, v, top, jt = x
        parts["upbit"] = {"score": _r(rs["upbit"][last], 1), "week": weeks[i], "sum4_t_krw": _r(v / 1e12, 1),
                          "max_t_krw": _r(top / 1e12, 1), "max_week": weeks[jt], "pct_of_max": _r(100.0 * v / top, 1)}
    x = newest("degen")
    if x:
        i, v, top, jt = x
        movers = []
        fp = getattr(ctx, "fee_protocols", None) or []
        for p in sorted((p for p in fp if p.get("category") in MEME_CATS), key=lambda p: -(p.get("total30d") or 0))[:3]:
            prev = p.get("total60dto30d") or 0
            movers.append({"name": p.get("displayName") or p.get("name"), "rev30d": p.get("total30d") or 0,
                           "chg_pct": _r(((p.get("total30d") or 0) / prev - 1) * 100, 0) if prev > 0 else None})
        parts["degen"] = {"score": _r(rs["degen"][last], 1), "week": weeks[i], "rev30d": round(v), "max": round(top),
                          "max_week": weeks[jt], "pct_of_max": _r(100.0 * v / top, 1), "movers": movers}
    i = next((j for j in range(last, -1, -1) if rows["apps"][j] is not None), None)
    if i is not None:
        label, o, fin, day = picks[i]
        parts["apps"] = {"score": _r(rs["apps"][last], 1), "week": weeks[i], "best": label, "best_overall": o,
                         "best_finance": fin, "day": day, "ledger_days": len(H.get("apps") or [])}
    # --- facts: shown, never scored
    S = _daily_series((H.get("daily") or {}).get("st", {}), 0)
    if S:
        sd = dict(S)
        d1 = S[-1][0]
        a, b = sd.get(d1), sd.get(d1 - 91 * DAY)
        parts["stables"] = {"score": None, "day": d1, "supply_bn": _r(a / 1e9, 1),
                            "new13_bn": _r((a - b) / 1e9, 1) if (a and b) else None}
    T = H.get("tranco") or {}
    if T.get("daily"):
        dk = sorted(T["daily"])
        cur = T["daily"][dk[-1]]
        back = next((T["daily"][k] for k in reversed(dk) if k <= (datetime.date.fromisoformat(dk[-1])
                     - datetime.timedelta(days=28)).isoformat()), None)
        parts["traffic"] = {"score": None, "day": dk[-1], "ranks": cur, "ranks_4w": back,
                            "best": {"coinbase.com": [818, "2021-11"]}}
    parts["ai"] = {"score": None, "claude": AI_CLAUDE, "cloudflare": H.get("ai"),
                   "needs": None if os.environ.get("CLOUDFLARE_API_TOKEN") else "CLOUDFLARE_API_TOKEN"}
    value = ser[last]
    back4 = ser[last - 4] if last >= 4 else None
    tempo = (value - back4) if (value is not None and back4 is not None) else None
    verdict = None
    if value is not None:
        verdict = "spi" if value < R["retail_lo"] else ("probouzi" if value < R["retail_hi"] else "hrne")
    tword = None
    if tempo is not None:
        tword = ("naval" if tempo >= R["retail_rush"] else "postupne" if tempo >= 8
                 else "odliv" if tempo <= -8 else "stoji")
    return {"value": _r(value, 1), "verdict": verdict, "tempo": _r(tempo, 1), "tempo_word": tword,
            "n_scored": sum(1 for k in rs if rs[k][last] is not None), "parts": parts}


# how old each source may get before the page says so: weekly ones get a week and a
# half, daily ones four days (CMC serves a day only 1–2 days later)
FRESH_DAYS = {"cmc_weekly": 10, "cmc_daily": 4, "coinmetrics": 4, "coinbase": 4, "upbit": 10, "memecoins": 4,
              "app_store": 10}
# the sources the weekly index reads (cmc_daily only feeds the newest daily points)
LEDGER_SOURCES = ("cmc_weekly", "coinmetrics", "coinbase", "upbit", "memecoins", "app_store")


def freshness(H, now_ts):
    """The newest data day of every source the panel reads, and whether it is stale.
    A source that breaks mid-altseason must show on the page, not only in a log:
    the index keeps being drawn from what is stored (stale beats empty)."""
    daily = H.get("daily") or {}
    newest = lambda d: max((int(k) for k in (d or {})), default=None)
    up = newest(H.get("upbit"))
    days = {"cmc_weekly": newest({k: 1 for k, v in (H.get("weeks") or {}).items() if v.get("od") is not None}),
            "cmc_daily": newest(daily.get("cmc")), "coinmetrics": newest(daily.get("cm")),
            # both pairs: a stuck ETH-USD drops days from the row (retail_rows)
            "coinbase": min((newest((H.get("cbx") or {}).get(p)) or 0 for p, _ in COINBASE_PAIRS), default=0) or None,
            "upbit": up + WEEK if up is not None else None,           # a candle is keyed by its week's start
            "memecoins": newest(H.get("meme30")),
            "app_store": max((x[0] for x in H.get("apps") or []), default=None)}
    return {k: {"day": d, "age_days": None if d is None else int((day0(now_ts) - day0(d)) // DAY),
                "stale": d is None or (day0(now_ts) - day0(d)) // DAY > FRESH_DAYS[k]} for k, d in days.items()}


def _line_out_v2(L, weeks, vals, latest=None):
    """A trend_line result with week stamps for the page and audit §37; None when
    there is no line (the status is then bez_trendu)."""
    if L["anchor"] is None:
        return None
    a, t, f = L["anchor"], L["t"], L["break_first"]
    out = {"anchor": weeks[a], "anchor_v": _r(vals[a], 3), "touch": weeks[L["touch"]],
           "touch_v": _r(vals[L["touch"]], 3), "opp": weeks[L["opp"]], "opp_v": _r(vals[L["opp"]], 3),
           "slope_week": _r(L["slope"], 6), "status": L["status"], "week": weeks[t],
           "line_now": _r(L["line_t"], 3), "dist_pct": _r((vals[t] / L["line_t"] - 1) * 100, 1),
           "since": weeks[f] if f is not None else None, "since_v": _r(vals[f], 3) if f is not None else None,
           "back": weeks[L["back_at"]] if L["back_at"] is not None else None,
           "latest_line": None, "latest_dist_pct": None}
    if latest is not None:
        ln = vals[a] + L["slope"] * (latest[0] - a)
        out["latest_line"] = _r(ln, 3)
        out["latest_dist_pct"] = _r((latest[1] / ln - 1) * 100, 1) if ln > 0 else None
    return out


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


def append_ledger(data_dir, block, now_ts):
    """The forward test PREREG_V2 names: one line per closed week in
    cycle_ledger.jsonl (week, index, phase, pillars), written by the collector after
    the snapshot is on disk and committed by CI like the picks ledger. v2 passes the
    backtest by construction, so only weeks it has not seen can test it. A line is
    added only when `as_of` is newer than the ledger's last week — never from a
    stale fallback block or without history. Returns True when a line was written.

    Each line names the index's sources that were stale (`stale`) and the retail rows
    that were scored (`rows`): retail needs only one row, so a week read without
    Upbit is a different mix and must say so. While the newest line's week is still
    the newest, a later run with fewer stale sources replaces it — the line becomes
    final when the next week is written."""
    if not block or block.get("stale") or block.get("history_missing") or block.get("index") is None:
        return False
    path = os.path.join(data_dir, LEDGER_NAME)
    lines = []
    if os.path.exists(path):
        for raw in io.open(path, encoding="utf-8"):
            raw = raw.strip()
            if raw:
                try:
                    lines.append((int(json.loads(raw)["week"]), json.loads(raw), raw))
                except (ValueError, KeyError, TypeError):
                    lines.append((None, None, raw))
    known = [w for w, _, _ in lines if w is not None]
    last = max(known) if known else None
    fr = block.get("freshness") or {}
    stale = sorted(k for k in LEDGER_SOURCES if (fr.get(k) or {}).get("stale"))
    rt = (block.get("components") or {}).get("retail") or {}
    rows = sorted(k for k in RETAIL_ROWS if (((rt.get("parts") or {}).get(k) or {}).get("score")) is not None)
    line = {"week": block["as_of"], "index": block["index"], "phase": block["phase"],
            "rotation": block.get("rotation"), "euphoria": block.get("euphoria"), "retail": rt.get("value"),
            "heat": block.get("heat"), "version": block.get("version"), "stale": stale, "rows": rows,
            "written": int(now_ts)}
    text = json.dumps(line, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    if last is not None and block["as_of"] < last:
        return False
    if last is not None and block["as_of"] == last:
        w, old, _ = lines[-1]
        if w != last or old is None or len(stale) >= len(old.get("stale") or []):
            return False
        lines[-1] = (w, line, text)
        tmp = path + ".tmp"
        with io.open(tmp, "w", encoding="utf-8") as f:
            f.write("".join(raw + "\n" for _, _, raw in lines))
        os.replace(tmp, path)
        return True
    with io.open(path, "a", encoding="utf-8") as f:
        f.write(text + "\n")
    return True


def build_cycle(ctx, prev, now_ts, log=None, data_dir=None, fetch=True):
    """The snapshot's `cycle` block (v3). `fetch=False` rebuilds from the stored
    history only; cycle_backtest runs the same compute_index_v3 on the same series."""
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
    if fetch:
        steps = [("CMC globální data", lambda: update_global(ctx, H, now_ts, log)),
                 ("CMC žebříčky", lambda: update_listings(ctx, H, now_ts, log)),
                 ("Coin Metrics", lambda: update_coinmetrics(ctx, H, now_ts, log)),
                 ("memecoinová ekonomika", lambda: update_meme(ctx, H, now_ts, log)),
                 ("Upbit", lambda: update_upbit(ctx, H, now_ts, log)),
                 ("Coinbase", lambda: update_coinbase(ctx, H, now_ts, log)),
                 ("App Store", lambda: update_apps(ctx, H, now_ts, log)),
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
    R, v3sum, summ = load_rules(data_dir)
    weeks = week_axis(now_ts)
    s = series_from_history(H, weeks, R)
    rows, picks = retail_rows(H, weeks, R)
    res = compute_index_v3(weeks, s, rows, R)
    ev = find_events(weeks, s)
    last = len(weeks) - 1
    I, ph = res["index"], res["phase"]
    # the headline's "před 3 měsíci": the week 13 weeks back
    i3 = last - 13
    # a daily point after the newest week, as a fractional week index for trend_line
    frac = lambda day: last + (day - weeks[last]) / WEEK

    # --- BTC.D: the 13-week word on the tile; the support line from the 2022 low and
    # the line through the altseason lows on the chart
    daily = _daily_series((H.get("daily") or {}).get("cmc", {}), 0)
    bd_now = daily[-1] if daily else None
    bd = s["btcd"]
    bd4 = roll_mean(bd, 4)
    chg13 = (bd4[last] - bd4[last - 13]) if (bd4[last] is not None and last >= 13 and bd4[last - 13] is not None) else None
    bd_verdict = None if chg13 is None else ("klesa" if chg13 <= -R["btcd_move_pp"]
                                             else "roste" if chg13 >= R["btcd_move_pp"] else "bokem")
    # the green line (Adam, 2026-09-27): from the 2018 altseason low (P1, 32,8 %)
    # through the 2022 bear-market low (37,9 %) — the rising floor under BTC.D —
    # extended to today. It used to run through the May 2021 low (40,1 %) and sat
    # too high. Display only: nothing in the index reads it.
    y22 = [i for i, w in enumerate(weeks) if 1640995200 <= w <= 1672444800 and bd[i] is not None]
    i22 = min(y22, key=lambda i: bd[i]) if y22 else None
    lows = {}
    for P, i in (("P1", ev.get("P1")), ("L2022", i22)):
        if i is not None:
            lows[P] = [weeks[i], _r(bd[i], 2)]
    lows_line = None
    if ev.get("P1") is not None and i22 is not None:
        i1, i2 = ev["P1"], i22
        sl = (bd[i2] - bd[i1]) / (i2 - i1)
        now_v = bd[i2] + sl * (last - i2)
        cur = bd_now[1] if bd_now else bd[last]
        lows_line = {"t0": weeks[i1], "v0": _r(bd[i1], 3), "t1": weeks[i2], "v1": _r(bd[i2], 3),
                     "slope_week": _r(sl, 5), "line_now": _r(now_v, 2),
                     "dist_pp": _r(cur - now_v, 2) if cur is not None else None}
    bd_latest = (frac(bd_now[0]), bd_now[1]) if (bd_now and bd_now[0] > weeks[last]) else None
    bd_line = trend_line(bd, "up", None, R, latest=bd_latest)
    # the tile's word: a broken support is the story the chart tells, so it wins
    # over the 13-week direction (a review: the tile said "sideways" under a chart
    # whose support had broken months ago)
    bd_word = "podpora_prolomena" if bd_line["status"] == "pruraz" else bd_verdict
    # the rotation's BTC.D part in plain numbers: from the high to the old low
    pk, fa = res["peak_at"][last], res["floor_at"][last]
    bd_path = None
    if res["path"][last] is not None:
        bd_path = {"pct": _r(res["path"][last], 1), "score": _r(res["p_dd"][last], 1),
                   "peak": _r(res["bd4"][pk], 2), "peak_week": weeks[pk],
                   "floor": _r(res["floor"][last], 2), "floor_week": weeks[fa], "now": _r(res["bd4"][last], 2)}

    # --- OTHERS.D: the TradingView line; its status is the tile's word
    od = s["othersd"]
    latest = H.get("latest")
    od_latest = (frac(latest["day"]), latest["od"]) if (latest and latest.get("od")
                                                         and (latest.get("day") or 0) > weeks[last]) else None
    od_line = trend_line(od, "down", None, R, latest=od_latest)
    ou = s["others_usd"]
    ou_peak21 = max((x for w, x in zip(weeks, ou) if x and 1609459200 <= w <= 1640995199), default=None)
    ou_low = min((x for x in ou[-26:] if x), default=None)
    ou_now = (latest or {}).get("ou") or ou[last]
    la = res["low_at"][last]
    usd_bn = lambda x: _r(x / 1e9, 0) if x else None

    # --- breadth (inside the rotation; no tile)
    Wl = (H.get("weeks") or {}).get(str(weeks[last])) or {}
    br = s["breadth"]
    br_now = br[last]
    br_verdict = None if br_now is None else ("alty_vedou" if br_now >= R["breadth_hi"]
                                              else "btc_vede" if br_now <= R["breadth_lo"] else "smisene")

    # --- BTC heat (inside the euphoria; no tile)
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
        hrows = []
        for e in reversed(prior):
            a = e[1]
            if any(abs(weeks[a] - r["start"]) < 26 * WEEK for r in hrows):
                continue
            j = a + 13
            r = {"start": weeks[a]}
            if j < len(weeks) and ou[a] and ou[j]:
                r["usd13"] = _r((ou[j] / ou[a] - 1) * 100, 0)
                if s["btc"][a] and s["btc"][j]:
                    r["vbtc13"] = _r(((ou[j] / ou[a]) / (s["btc"][j] / s["btc"][a]) - 1) * 100, 0)
            hrows.append(r)
            if len(hrows) == 2:
                break
        hint = {"phase": ph[last], "episodes": hrows, "n_prior": len(prior)}

    retail = retail_block(ctx, H, weeks, rows, picks, res, R)
    vol = volume_block(H, weeks, s, now_ts, R)
    r1 = lambda xs: [_r(x, 1) for x in xs]
    block = {
        "version": V3_ID,
        "prereg_sha256": (v3sum or {}).get("prereg_sha256"),
        "as_of": weeks[last], "generated": int(now_ts), "history_missing": missing or loaded == 0,
        "rules": R,
        "index": _r(I[last], 1), "phase": ph[last], "index_3m_ago": _r(I[i3], 1) if i3 >= 0 else None,
        "rotation": _r(res["rotation"][last], 1), "euphoria": _r(res["euphoria"][last], 1), "heat": _r(hv, 1),
        # full series from 2014-07, inputs unrounded: audit §37 recomputes every week
        # (every window, every four-year max) from exactly these numbers
        "weeks": weeks, "display_from": DISPLAY_FROM,
        "series": {"index": r1(I), "rotation": r1(res["rotation"]), "euphoria": r1(res["euphoria"]),
                   "retail": r1(res["retail"]), "heat": r1(res["heat"]), "phase": ph,
                   "btcd": list(bd), "othersd": list(od), "breadth": list(br),
                   "others_usd": [_r(x, 0) for x in ou], "btc": [_r(x, 2) for x in s["btc"]],
                   "mvrv": list(s["mvrv"]), "puell": list(s["puell"]), "mayer": list(s["mayer"]), "pi": list(s["pi"]),
                   "breakouts": [i for i, b in enumerate(res["breakouts"]) if b],
                   "retail_raw": {k: list(rows[k]) for k in RETAIL_ROWS}},
        "components": {
            "btcd": {"value": _r(bd_now[1], 2) if bd_now else _r(bd[last], 2), "day": bd_now[0] if bd_now else None,
                     "week": _r(bd[last], 2), "chg13_pp": _r(chg13, 2), "path": bd_path,
                     "verdict": bd_verdict, "word": bd_word, "lows": lows, "lows_line": lows_line,
                     "line": _line_out_v2(bd_line, weeks, bd, bd_latest), "source": "cmc"},
            "othersd": {"value": _r((latest or {}).get("od") or od[last], 3), "day": (latest or {}).get("day"),
                        "week": _r(od[last], 3), "verdict": od_line["status"],
                        "line": _line_out_v2(od_line, weeks, od, od_latest),
                        "usd_bn": usd_bn(ou_now), "usd_peak_2021_bn": usd_bn(ou_peak21),
                        "usd_low_26w_bn": usd_bn(ou_low), "rise_score": _r(res["p_rise"][last], 1),
                        "rise_pct": _r(res["rise"][last], 1), "low_week": weeks[la] if la is not None else None,
                        "low_v": _r(res["od4"][la], 3) if la is not None else None,
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
        # the rotation's parts at the past altseason ends: the breakdown compares this
        # week's numbers with them instead of with a range written by hand
        "rotation_at_events": {k: {"path": _r(res["path"][i], 0), "rise": _r(res["rise"][i], 0),
                                   "breadth": _r(res["br4"][i], 0)}
                               for k, i in ev.items() if i is not None and k in ("P1", "P2")},
        "hint": hint,
        "backtest": dict({k: v3sum.get(k) for k in ("verdict", "index_at", "eval_start", "lead_weeks", "share_ge_T",
                                                     "max_since_2023")},
                         generated_utc=(summ or {}).get("generated_utc")) if v3sum else None,
        "freshness": freshness(H, now_ts),
        "anomalies": s.get("anomalies", []),
    }
    json.dumps(block, allow_nan=False)        # one NaN would kill JSON.parse on the page
    return block
