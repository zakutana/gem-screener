"""
Themes — the twelve market narratives the Sektory tab is built from.

Each theme joins two things that used to live in two unconnected tabs:

    price side   a basket of coins taken from CoinGecko categories
    fundament    DeFiLlama revenue of the matching categories, or — for L1/L2 —
                 the stablecoin capital parked on those chains

and answers the two questions Adam asked:

    "what is running"                    relative strength vs BTC, 1M and 3M
    "what gets hottest if altseason      beta to BTC: "BTC +10 % -> theme +16 %"
     started now"

The year this was built in had no altseason: the best 6-week stretch saw the
median alt beat BTC by only +5 %. There is therefore no "how did it do in the
last alt rally" column — it would rank themes on noise — and the page says that
beta was measured on an ordinary market.

Every number here is stored alongside the raw weekly price grid it came from,
so audit_sectors.py can recompute all of it with a second implementation.
"""
import concurrent.futures as cf
import datetime
import hashlib
import io
import json
import math
import os
import re
import time
import urllib.parse

DAY = 86400
WEEK = 7 * DAY
N_STAMPS = 53                   # 52 weekly returns
CACHE_NAME = "baskets_cache.json"
CACHE_MAX_AGE = 7 * DAY         # stale means "refresh", never "delete"
CANDIDATES = 30                 # per CoinGecko category, for the start-of-window basket
BASKET_SIZE = 15
UNIVERSE_SIZE = 250             # for the altseason index history
ALTSEASON_N = 50
WEIGHT_CAP = 0.25
MIN_MEMBERS = 5
MIN_RETURNS = 40
PRICE_TOL = 12 * 3600
BETA_CLIP = math.log(4)         # one +300 % week must not move a 15-coin basket by 9 %
BREAK_JUMP = math.log(20)       # a week this large that does not reverse is a redenomination
TIER_STRONG_LOW = 1.15          # strong: beta - SE stays above this
TIER_WEAK_HIGH = 0.95           # weak:   beta + SE stays below this
CG = "https://api.coingecko.com/api/v3"

# ------------------------------------------------------------------ the crosswalk
# Price comes ONLY from CoinGecko categories; DeFiLlama supplies the fundament.
# Membership must not leak between the two, or DeFi tokens end up in "memes".
THEMES = [
    {"key": "ai", "name": "AI", "cg": ["artificial-intelligence", "ai-agents"],
     "dl": ["AI Agents", "Decentralized AI"],
     "blurb": "AI agenti, decentralizované výpočty a trénink modelů."},
    {"key": "memes", "name": "Memecoiny", "cg": ["meme-token"],
     "dl": ["Launchpad", "Telegram Bot", "Trading App"],
     "blurb": "Memecoiny. Fundament je revenue memecoinové ekonomiky — launchpady, "
              "trading boti a appky, na kterých se s nimi obchoduje."},
    {"key": "dex", "name": "DEX a perpy", "cg": ["decentralized-exchange", "decentralized-perpetuals"],
     "dl": ["Dexs", "DEX Aggregator", "Derivatives", "Options"],
     "blurb": "Decentralizované burzy, agregátory a perpetuals."},
    {"key": "rwa", "name": "RWA", "cg": ["real-world-assets-rwa"], "dl": ["RWA"],
     "blurb": "Tokenizace reálných aktiv — protokoly, ne samotné tokenizované dluhopisy."},
    {"key": "privacy", "name": "Privacy", "cg": ["privacy-coins"], "dl": ["Privacy"],
     "blurb": "Privacy coiny a protokoly pro soukromé transakce."},
    {"key": "prediction", "name": "Prediction markets", "cg": ["prediction-markets"],
     "dl": ["Prediction Market"], "blurb": "Sázky na výsledky událostí."},
    {"key": "depin", "name": "DePIN", "cg": ["depin"], "dl": ["DePIN"],
     "blurb": "Decentralizovaná fyzická infrastruktura — výpočty, úložiště, sítě."},
    {"key": "gaming", "name": "Gaming", "cg": ["gaming"], "dl": ["Gaming"],
     "blurb": "Blockchainové hry a herní ekosystémy."},
    {"key": "defi", "name": "DeFi úvěry a staking",
     "cg": ["lending-borrowing", "liquid-staking-governance-tokens"],
     "dl": ["Lending", "CDP", "Liquid Staking", "Liquid Restaking", "Restaking"],
     "blurb": "Půjčování, CDP a liquid staking — výnosová páteř DeFi."},
    {"key": "l1", "name": "L1", "cg": ["layer-1"], "dl": [], "chain_layer": "L1", "residual": True,
     "blurb": "Layer-1 blockchainy. Coiny, které už patří jinému tématu (ZEC, HYPE…), sem nepočítáme."},
    {"key": "l2", "name": "L2", "cg": ["layer-2"], "dl": [], "chain_layer": "L2", "residual": True,
     "blurb": "Layer-2 rollupy. Fundament počítá i chainy bez tokenu, hlavně Base."},
    # Residual like L1/L2, but for apps: bridges, oracles, wallets, domains and
    # services had no theme at all (67 of 213 apps were themeless before it).
    # Its basket drops coins a narrative owns (LINK is RWA) and chain tokens
    # (Kaspa sits in CoinGecko's "wallets") — see build_themes.
    {"key": "infra", "name": "Infrastruktura",
     "cg": ["oracle", "cross-chain-communication", "bridge-governance-tokens", "wallets", "name-service"],
     "dl": ["Bridge", "Cross Chain Bridge", "Canonical Bridge", "Bridge Aggregator", "Oracle", "Wallets",
            "Domains", "Services", "Developer Tools", "Payments", "Crypto Card Issuer", "Coins Tracker",
            "Interface", "DAO Service Provider", "Security Extension", "Block Builders"],
     "residual": True,
     "blurb": "Mosty, orákula, peněženky, domény a další služby, na kterých stojí ostatní projekty. "
              "Zbytkové téma: dostane jen to, co si nenárokuje konkrétnější narativ; tokeny chainů "
              "patří do L1/L2."},
]
# Coins CoinGecko files under several themes where one reading is clearly right.
THEME_OVERRIDES = {"pump-fun": "memes"}
# Row join only — never a fundament. DeFiLlama categories that feed no theme's
# revenue but have an obvious home; an app reaches this map only when neither
# its own category nor CoinGecko names a theme (see app_theme). Their revenue
# stays in `unmapped`: Yearn wears the DeFi chip, but Yield Aggregator revenue
# is not added to the lending/staking fundament.
NEAREST_THEME = {
    # the same money machine as lending and staking, filed separately
    "Yield": "defi", "Yield Aggregator": "defi", "Basis Trading": "defi", "Insurance": "defi",
    "Indexes": "defi", "Synthetics": "defi", "Staking Pool": "defi", "Restaked BTC": "defi",
    "Decentralized BTC": "defi", "Liquidity Manager": "defi", "Leveraged Farming": "defi",
    "Farm": "defi", "NFT Lending": "defi", "NftFi": "defi", "Dual-Token Stablecoin": "defi",
    "Algo-Stables": "defi", "Reserve Currency": "defi", "MEV": "defi", "CeDeFi": "defi",
    "Risk Curators": "defi", "Onchain Capital Allocator": "defi", "CDP Manager": "defi",
    "Uncollateralized Lending": "defi", "NFT Automated Strategies": "defi",
    "Stablecoin Issuer": "defi",
    # trading venues and execution tools
    "Interest Rate Derivatives": "dex", "DCA Tools": "dex", "OTC Marketplace": "dex",
    # games of chance, gamified mining and collectibles trading
    "Gamified Mining": "gaming", "Luck Games": "gaming", "NFT Marketplace": "gaming",
    # tokenized physical collectibles — CoinGecko files Collector Crypt as RWA too
    "Physical TCG": "rwa",
    # physical networks
    "Video Infrastructure": "depin",
    # services with no narrative of their own
    "SoFi": "infra", "Foundation": "infra", "Chain": "infra",
}
# Last-resort baskets if CoinGecko is down AND there is no cache or prior snapshot.
THEME_SEED = {
    "ai": ["near", "bittensor", "internet-computer", "venice-token", "render-token", "virtual-protocol", "fetch-ai"],
    "memes": ["dogecoin", "shiba-inu", "pepe", "pump-fun", "official-trump", "pudgy-penguins", "bonk"],
    "dex": ["hyperliquid", "uniswap", "aster-2", "lighter", "jupiter-exchange-solana", "pancakeswap-token", "aerodrome-finance"],
    "rwa": ["chainlink", "stellar", "ondo-finance", "plume", "centrifuge", "mantra-dao", "maple"],
    "privacy": ["zcash", "monero", "decred", "zano", "pirate-chain", "firo", "verge"],
    "prediction": ["rain", "drift-protocol", "overtime", "opinion", "polkamarkets", "limitless-3", "sx-network-2"],
    "depin": ["bittensor", "render-token", "bittorrent", "grass", "arweave", "the-graph", "theta-token"],
    "gaming": ["floki", "axie-infinity", "decentraland", "apecoin", "immutable-x", "the-sandbox", "gala"],
    "defi": ["aave", "morpho", "lido-dao", "jito-governance-token", "compound-governance-token", "kamino", "rocket-pool"],
    "l1": ["ethereum", "binancecoin", "ripple", "solana", "tron", "cardano", "avalanche-2"],
    "l2": ["okb", "mantle", "arbitrum", "polygon-ecosystem-token", "blockstack", "optimism", "starknet"],
    "infra": ["pyth-network", "layerzero", "ethereum-name-service", "trust-wallet-token", "wormhole",
              "debridge", "safe"],
}
# Word boundaries matter: "treasur" alone would drop Treasure (MAGIC, a gaming
# token) and "gold" would drop Goldfinch.
EXCLUDE_RE = re.compile(r"\b(wrapped|bridged|staked|tokeni[sz]ed|xstock|treasury|gold)\b", re.I)


def themes_version():
    raw = json.dumps([THEMES, THEME_OVERRIDES], sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def validate_crosswalk():
    """A DeFiLlama category may feed at most one theme — otherwise its revenue
    is counted twice across the table. NEAREST_THEME is the row-only fallback:
    a category there must feed no fundament (the entry would be dead) and every
    target must be a real theme, or rows would silently lose their chip."""
    seen = {}
    for t in THEMES:
        for c in t["dl"]:
            if c in seen:
                raise ValueError("category %s mapped to both %s and %s" % (c, seen[c], t["key"]))
            seen[c] = t["key"]
    keys = {t["key"] for t in THEMES}
    for c, k in NEAREST_THEME.items():
        if c in seen:
            raise ValueError("category %s is in NEAREST_THEME but already feeds %s" % (c, seen[c]))
        if k not in keys:
            raise ValueError("NEAREST_THEME[%r] = %r is not a theme" % (c, k))
    for g, k in THEME_OVERRIDES.items():
        if k not in keys:
            raise ValueError("THEME_OVERRIDES[%r] = %r is not a theme" % (g, k))


# ------------------------------------------------------------------ small maths
def _mean(xs):
    return sum(xs) / len(xs) if xs else None


def _stdev(xs):
    if len(xs) < 2:
        return None
    m = _mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / len(xs))


def _median(xs):
    xs = sorted(xs)
    n = len(xs)
    if not n:
        return None
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2.0


def regress(xs, ys):
    """slope, correlation, SE of slope, n — population moments."""
    n = len(xs)
    if n < 3:
        return None
    mx, my = _mean(xs), _mean(ys)
    vx = sum((x - mx) ** 2 for x in xs) / n
    vy = sum((y - my) ** 2 for y in ys) / n
    if vx <= 0 or vy <= 0:
        return None
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / n
    slope = cov / vx
    rho = cov / math.sqrt(vx * vy)
    # SE = (sigma_y/sigma_x) * sqrt((1-rho^2)/(n-2)); written without 1/rho so a
    # near-zero correlation cannot blow it up
    se = math.sqrt(vy / vx) * math.sqrt(max(0.0, 1 - rho * rho) / (n - 2)) if n > 2 else None
    return {"slope": slope, "rho": rho, "se": se, "n": n}


def cap_weights(mcaps, cap=WEIGHT_CAP):
    """sqrt(mcap) weights capped at 25 %, excess spread over the rest.

    Equal weights gave coin #15 the same vote as DOGE; cap weights made Privacy
    a synonym for ZEC. sqrt with a cap sits between the two."""
    w = [math.sqrt(max(float(m or 0), 0.0)) for m in mcaps]
    s = sum(w)
    if s <= 0:
        return [1.0 / len(w)] * len(w) if w else []
    w = [x / s for x in w]
    if len(w) * cap < 1:
        return [1.0 / len(w)] * len(w)
    for _ in range(60):
        over = [i for i, x in enumerate(w) if x > cap + 1e-12]
        if not over:
            break
        excess = sum(w[i] - cap for i in over)
        for i in over:
            w[i] = cap
        free = [i for i, x in enumerate(w) if x < cap - 1e-12]
        fs = sum(w[i] for i in free)
        if fs <= 0:
            break
        for i in free:
            w[i] += excess * w[i] / fs
    s = sum(w)
    return [x / s for x in w]


# ------------------------------------------------------------------ fetching
def cg_headers():
    """A free CoinGecko Demo key, when the environment provides one (the GitHub
    Actions secret COINGECKO_DEMO_KEY): shared CI addresses get 429s far more
    often than a home connection. Without it the keyless tier is used, as
    before. The key is never logged."""
    h = {"Accept": "application/json"}
    key = os.environ.get("COINGECKO_DEMO_KEY", "").strip()
    if key:
        h["x-cg-demo-api-key"] = key
    return h


def cg_get(ctx, url, timeout=40):
    """CoinGecko's free tier answers 429 even at 7 s spacing. One request at a
    time, backing off 15/30/60 s and honouring Retry-After."""
    waits = [15, 30, 60]
    for attempt in range(len(waits) + 1):
        try:
            r = ctx.session.get(url, timeout=timeout, headers=cg_headers())
            if r.status_code == 200:
                return r.json()
            if r.status_code == 429 and attempt < len(waits):
                ra = (r.headers.get("Retry-After") or "").strip()
                wait = int(ra) if ra.isdigit() else waits[attempt]
                ctx.log("  CoinGecko 429 — čekám %d s" % min(wait, 90))
                time.sleep(min(wait, 90))
                continue
            ctx.warn("CoinGecko HTTP %s: %s" % (r.status_code, url[:140]))
            return None
        except Exception as e:
            if attempt < len(waits):
                time.sleep(5)
                continue
            ctx.warn("CoinGecko nedostupný: %s (%s)" % (url[:140], e))
            return None
    return None


def week_stamps(now):
    """53 stamps at Monday 00:00 UTC, oldest first. Anchoring to a fixed weekday
    makes past stamps stable between runs."""
    d = datetime.datetime.fromtimestamp(now, datetime.timezone.utc)
    midnight = datetime.datetime(d.year, d.month, d.day, tzinfo=datetime.timezone.utc)
    monday = midnight - datetime.timedelta(days=d.weekday())
    last = int(monday.timestamp())
    return [last - (N_STAMPS - 1 - k) * WEEK for k in range(N_STAMPS)]


def fetch_grid(ctx, ids, stamps):
    """{coin id: [price | None] * 53}.

    batchHistorical takes ~10 coins x 53 stamps before the URL hits 414. A chunk
    that fails is split in half until it goes through, so one bad id or one
    oversized URL costs a few extra calls instead of ten coins."""
    def call(chunk):
        q = {("coingecko:%s" % g): stamps for g in chunk}
        url = ("https://coins.llama.fi/batchHistorical?coins=%s&searchWidth=12h"
               % urllib.parse.quote(json.dumps(q, separators=(",", ":"))))
        d = ctx.get(url, timeout=60, quiet_status=(400, 404, 414))
        if d is None:
            if len(chunk) == 1:
                return {}
            h = len(chunk) // 2
            out = call(chunk[:h])
            out.update(call(chunk[h:]))
            return out
        res = {}
        for key, v in (d.get("coins") or {}).items():
            gid = key.split(":", 1)[1]
            row = [None] * len(stamps)
            for p in v.get("prices") or []:
                t, pr = int(p.get("timestamp") or 0), p.get("price")
                if not pr or pr <= 0:
                    continue
                k = int(round((t - stamps[0]) / float(WEEK)))
                if 0 <= k < len(stamps) and abs(stamps[k] - t) <= PRICE_TOL:
                    row[k] = float(pr)
            res[gid] = row
        return res

    chunks = [ids[i:i + 10] for i in range(0, len(ids), 10)]
    grid = {}
    with cf.ThreadPoolExecutor(max_workers=6) as ex:
        for part in ex.map(call, chunks):
            grid.update(part)
    return grid


def btc_row(ctx, stamps, grid):
    """BTC is the yardstick; a hole in it would silently corrupt every theme.
    If batchHistorical left more than 3 stamps empty, rebuild it from the
    single-coin daily chart, which does work."""
    row = grid.get("bitcoin") or [None] * len(stamps)
    if sum(1 for p in row if p) >= len(stamps) - 3:
        return row
    d = ctx.get("https://coins.llama.fi/chart/coingecko:bitcoin?start=%d&span=%d&period=1d"
                % (stamps[0] - DAY, (stamps[-1] - stamps[0]) // DAY + 3), timeout=60)
    pts = list((((d or {}).get("coins") or {}).get("coingecko:bitcoin") or {}).get("prices") or [])
    fixed = list(row)
    for k, s in enumerate(stamps):
        if fixed[k]:
            continue
        near = [p for p in pts if abs(int(p["timestamp"]) - s) <= PRICE_TOL]
        if near:
            fixed[k] = float(min(near, key=lambda p: abs(int(p["timestamp"]) - s))["price"])
    ctx.log("BTC doplněno z denního grafu: %d/%d razítek"
            % (sum(1 for p in fixed if p), len(stamps)))
    return fixed


# ------------------------------------------------------------------ cleaning
def clean_row(gid, row, anomalies):
    """Remove spikes and redenominations before any return is taken.

    A week whose |log move| exceeds ln 20 either reverses within two weeks (a
    bad print: drop that point) or does not (a redenomination such as MKR->SKY:
    drop everything before it). Both are recorded so the audit lists them."""
    p = list(row)
    for k in range(1, len(p)):
        if not p[k] or not p[k - 1]:
            continue
        jump = math.log(p[k] / p[k - 1])
        if abs(jump) <= BREAK_JUMP:
            continue
        back = any(k + j < len(p) and p[k + j] and abs(math.log(p[k + j] / p[k - 1])) < BREAK_JUMP / 2
                   for j in (1, 2))
        if back:
            anomalies.append({"id": gid, "k": k, "kind": "spike", "jump": round(jump, 3)})
            p[k] = None
        else:
            anomalies.append({"id": gid, "k": k, "kind": "break", "jump": round(jump, 3)})
            for j in range(k):
                p[j] = None
    return p


def simple_returns(p):
    """R_k = P_k / P_(k-1) - 1. A coin listed inside the window loses its first
    two returns — fresh listings swing wildly for reasons unrelated to the theme."""
    r = [None] * len(p)
    first = next((k for k, v in enumerate(p) if v), None)
    if first is None:
        return r
    skip_until = first + 2 if first > 0 else 0
    for k in range(1, len(p)):
        if p[k] and p[k - 1] and k > skip_until:
            r[k] = p[k] / p[k - 1] - 1
    return r


def hard_exclusion(gid, name, p, r, rb):
    """Why this coin can never be a theme member, or None."""
    if gid == "bitcoin":
        return "BTC je měřítko, ne člen"
    if EXCLUDE_RE.search(name or "") or EXCLUDE_RE.search(gid):
        return "wrapped / staked / tokenizované aktivum"
    avail = [x for x in p if x]
    # the HISTORY decides, not today's price — ONDO and ENA have traded near $1
    if avail and sum(1 for x in avail if 0.97 <= x <= 1.03) >= 0.9 * len(avail):
        return "stablecoin"
    pairs = [(math.log(1 + a), math.log(1 + b)) for a, b in zip(r, rb) if a is not None and b is not None]
    if len(pairs) >= 20:
        vol = _stdev([a for a, _ in pairs]) * math.sqrt(52)
        rg = regress([b for _, b in pairs], [a for a, _ in pairs])
        rho = rg["rho"] if rg else 0.0
        # both conditions: ZEC/XMR have low correlation but high volatility and
        # are the very "own story" movers we want to keep
        if vol < 0.40 and abs(rho) < 0.3:
            return "nechová se jako rizikové aktivum (zlato, dluhopis)"
    return None


# ------------------------------------------------------------------ baskets
def basket_returns(rets, weights, clip=None):
    """Weighted SIMPLE returns, weights renormalised over the members present.

    A mean of log returns tracks a "typical coin", not a basket you could hold —
    it trails by ~half the cross-sectional variance, most in memes and AI."""
    n = len(rets)
    if not n:
        return []
    need = max(3, (n + 1) // 2)
    out = [None] * len(rets[0])
    for k in range(len(out)):
        pres = [(w, r[k]) for w, r in zip(weights, rets) if r[k] is not None]
        if len(pres) < need:
            continue
        sw = sum(w for w, _ in pres)
        acc = 0.0
        for w, x in pres:
            if clip is not None:
                x = math.exp(max(-clip, min(clip, math.log(1 + x)))) - 1
            acc += w * x
        out[k] = acc / sw
    return out


def window_return(rets_basket, start_k, live=None):
    """Compound basket returns over stamps start_k+1..end, plus an optional live
    partial week."""
    acc = 0.0
    for k in range(start_k + 1, len(rets_basket)):
        if rets_basket[k] is not None:
            acc += math.log(1 + rets_basket[k])
    if live is not None:
        acc += math.log(1 + live)
    return acc


def beta_tier(beta, se):
    """Tier by what the estimate can SUPPORT, not by the point value alone.

    With 52 weekly returns a beta carries a standard error of 0.1-0.3. Privacy
    came out at 1.31 +/- 0.28: a plain >= 1.3 cut-off would have painted it
    the top altseason pick when its true value could sit anywhere from 0.76
    to 1.86. So "strong" requires the beta to stay high after subtracting its
    error, and "weak" to stay low after adding it; everything in between is
    honestly the same group."""
    if beta is None:
        return None
    se = se or 0.0
    if beta - se >= TIER_STRONG_LOW:
        return 5
    if beta + se < TIER_WEAK_HIGH:
        return 1
    return 3


def pick_basket(cands, key_mcap, size=BASKET_SIZE):
    ranked = sorted(cands, key=lambda c: -(key_mcap(c) or 0))[:size]
    return ranked, cap_weights([key_mcap(c) for c in ranked])


# ------------------------------------------------------------------ cache
def load_cache(path):
    try:
        return json.load(io.open(path, encoding="utf-8"))
    except Exception:
        return {}


def save_cache(path, cache):
    tmp = path + ".tmp"
    with io.open(tmp, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, separators=(",", ":"))
    for attempt in range(5):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            time.sleep(0.2)


def _meta(c):
    return {"id": c["id"], "symbol": (c.get("symbol") or "").upper(), "name": c.get("name") or c["id"],
            "image": c.get("image"), "mcap": c.get("market_cap") or 0}


def market_fields(c):
    """Columns /coins/markets already returns at no extra call: volume, supply,
    ATH, and — with &price_change_percentage=7d,30d,1y — three price changes.

    Take them ONLY from a live call. `_meta` feeds baskets_cache.json, and a
    volume read back from a 7-day-old cache would pass for today's."""
    def num(k):
        v = c.get(k)
        return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None
    return {"vol24h": num("total_volume"), "circ": num("circulating_supply"),
            "total": num("total_supply"), "max": num("max_supply"),
            "ath": num("ath"), "ath_chg_pct": num("ath_change_percentage"),
            "ath_date": c.get("ath_date"), "rank": c.get("market_cap_rank"),
            "chg7d": num("price_change_percentage_7d_in_currency"),
            "chg30d": num("price_change_percentage_30d_in_currency"),
            "chg1y": num("price_change_percentage_1y_in_currency")}


def refresh_baskets(ctx, cache, now):
    """Rebuild only the parts of the cache that are missing or older than 7
    days. A theme whose fetch fails keeps its old entry: stale beats empty."""
    version = themes_version()
    if cache.get("version") != version:
        ctx.log("definice témat se změnila — koše se přestaví")
        cache = {"version": version, "themes": {}, "universe": None, "history": cache.get("history", [])}
    cache.setdefault("themes", {})
    cache.setdefault("history", [])
    rebuilt = []
    for t in THEMES:
        ent = cache["themes"].get(t["key"])
        if ent and now - ent.get("built_at", 0) < CACHE_MAX_AGE:
            continue
        found = {}
        for cid in t["cg"]:
            rows = cg_get(ctx, "%s/coins/markets?vs_currency=usd&category=%s&order=market_cap_desc"
                               "&per_page=%d&page=1" % (CG, cid, CANDIDATES))
            time.sleep(6)
            for c in rows or []:
                if c.get("id") and (c.get("market_cap") or 0) > 0:
                    found.setdefault(c["id"], _meta(c))
        if found:
            coins = sorted(found.values(), key=lambda c: -c["mcap"])[:CANDIDATES * 2]
            cache["themes"][t["key"]] = {"built_at": now, "coins": coins}
            rebuilt.append(t["key"])
        elif ent:
            ctx.warn("koš %s se nepodařilo obnovit, držím %d dní starý"
                     % (t["name"], (now - ent.get("built_at", now)) // DAY))
    uni = cache.get("universe")
    if not uni or now - uni.get("built_at", 0) >= CACHE_MAX_AGE:
        rows = cg_get(ctx, "%s/coins/markets?vs_currency=usd&order=market_cap_desc&per_page=%d&page=1"
                           % (CG, UNIVERSE_SIZE))
        time.sleep(6)
        if rows:
            cache["universe"] = {"built_at": now, "coins": [_meta(c) for c in rows if c.get("id")]}
            rebuilt.append("universe")
    if rebuilt:
        # dated membership, kept so survivorship can be studied later
        cache["history"] = (cache["history"] + [{
            "at": now, "themes": {k: [c["id"] for c in v["coins"][:BASKET_SIZE]]
                                  for k, v in cache["themes"].items()}}])[-30:]
    return cache, rebuilt


def fallback_members(key, prev_snapshot):
    """Order of retreat when there is no cache entry: last snapshot, then seed."""
    for th in (prev_snapshot or {}).get("themes") or []:
        if th.get("key") == key and th.get("members"):
            return [{"id": m["id"], "symbol": m.get("sym", ""), "name": m.get("name", m["id"]),
                     "image": None, "mcap": m.get("mcap") or 0} for m in th["members"]], "snapshot"
    if key in THEME_SEED:
        return [{"id": g, "symbol": "", "name": g, "image": None, "mcap": 0}
                for g in THEME_SEED[key]], "seed"
    return [], "unavailable"


# ------------------------------------------------------------------ rows <-> themes
# Every DeFiLlama category belongs to at most one theme (validate_crosswalk), so
# these maps are functions: category -> theme key. A narrative category names
# the coin's story outright; a residual one (Infrastruktura) only claims what
# nothing more specific does — the same rule the residual price baskets follow.
CAT2THEME = {c: t["key"] for t in THEMES if not t.get("residual") for c in t["dl"]}
RESIDUAL_CAT2THEME = {c: t["key"] for t in THEMES if t.get("residual") for c in t["dl"]}
NARRATIVES = [t["key"] for t in THEMES if not t.get("residual")]
RESIDUALS = [t["key"] for t in THEMES if t.get("residual")]
LAYERS = [t["key"] for t in THEMES if t.get("chain_layer")]
# app_theme's steps, in order; part of row_join_version()
LADDER = ("override", "category", "coingecko", "coingecko-residual", "category-residual", "nearest")
JOIN_SOURCES = ("override", "category", "coingecko", "nearest")


def theme_of_app(e):
    """Steps 1-2 of the row ladder in `app_theme`: an override (exactly as when
    the baskets are built, PUMP -> Memecoiny), else a category that feeds a
    narrative theme's fundament.

    FROZEN: backtest.py rebuilt its pre-registered H3 gate on exactly this join,
    so changing what it returns silently changes a locked result. Extend the
    ladder in `app_theme` instead."""
    g = e.get("gecko_id")
    if g in THEME_OVERRIDES:
        return THEME_OVERRIDES[g]
    return CAT2THEME.get(e.get("category"))


def app_theme(e, cg_members):
    """Which theme an app row belongs to — `(key, source)` or `(None, None)`.

    The most specific evidence about the row's coin wins (THEMES order within a
    step):

        1 override    THEME_OVERRIDES, a reading fixed by hand
        2 category    its DeFiLlama category feeds a narrative theme
        3 coingecko   CoinGecko files the coin under a narrative theme
        4 coingecko   ... or under a residual one (L1, L2, Infrastruktura)
        5 category    its category feeds a residual theme (Infrastruktura)
        6 nearest     NEAREST_THEME: the closest theme to a category that
                      feeds no fundament (row only, the revenue is not added)

    Before this ladder only steps 1-2 existed and 67 of 213 apps had no theme
    (bridges, wallets, yield, Physical TCG…). Residual themes coming after
    CoinGecko keeps Apps and Chains consistent: NEAR's app is a DeFiLlama
    "Bridge", but NEAR trades as an AI coin and is AI on the Chains tab too.

    Consequence, by design: the chip is about the COIN, the fundament about
    the CATEGORY. Chainlink shows RWA (CoinGecko) while its "Services" revenue
    counts in Infrastruktura's fundament.

    `cg_members` = {theme key: coin ids} — the cached CoinGecko candidates the
    baskets are built from, after override exclusivity."""
    k = theme_of_app(e)
    if k:
        return k, ("override" if e.get("gecko_id") in THEME_OVERRIDES else "category")
    g = e.get("gecko_id")
    if g:
        for keys in (NARRATIVES, RESIDUALS):
            for k in keys:
                if g in (cg_members or {}).get(k, ()):
                    return k, "coingecko"
    cat = e.get("category")
    if cat in RESIDUAL_CAT2THEME:
        return RESIDUAL_CAT2THEME[cat], "category"
    if cat in NEAREST_THEME:
        return NEAREST_THEME[cat], "nearest"
    return None, None


def theme_of_chain(e, members):
    """Chains join through the price basket their token trades in (NEAR is an AI
    coin before it is an L1, HYPE a DEX coin before it is a chain), then through
    the L1/L2 baskets (POL sits in CoinGecko's layer-2 basket although
    DeFiLlama files Polygon as L1), and only then by layer. Within each pass
    the first theme in THEMES order wins. Only chain-layer themes take part in
    the second pass: Infrastruktura is residual too, but a chain is a chain."""
    g = e.get("gecko_id")
    for keys in (NARRATIVES, LAYERS):
        for k in keys:
            if g in members.get(k, ()):
                return k
    return "l2" if (e.get("category") or "").startswith("L2") else "l1"


def row_join_version():
    """Changes whenever a rule that decides a row's theme changes. The collector
    folds it into gates_version: the theme decides two of the seven degen gates
    (the theme itself and the Test 30× ceiling), so a picks-ledger cohort must
    say which join it was selected under."""
    raw = json.dumps([[(t["key"], t["cg"], t["dl"], bool(t.get("residual")), t.get("chain_layer"))
                       for t in THEMES], THEME_OVERRIDES, NEAREST_THEME, LADDER],
                     sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def attach_themes(apps, chains, themes_out, stale=False, cg_members=None, prev_snapshot=None):
    """Copy each row's theme onto it — the join the Sektory tab never made — and
    return the `theme_join` block of the snapshot.

    Sektory said which theme amplifies an altseason; no Apps row said which
    theme it belonged to, so connecting the two was left to the reader. The
    copy is deliberately small (the viewer finds the full theme by key) and says
    where it came from (`source`). `basket_themes` lists every display basket
    the row's coin sits in and `cg_themes` every theme whose CoinGecko
    candidates contain it, so the audit can check the join without importing
    this module.

    A CoinGecko-sourced theme can change when the weekly basket refresh moves a
    coin in or out of a category's top 30 (a category-sourced one cannot);
    `changed` lists every row whose theme differs from the previous snapshot."""
    by_key = {th.get("key"): th for th in themes_out or []}
    members = {k: {m["id"] for m in (th.get("members") or [])} for k, th in by_key.items()}
    cg = {k: set(v) for k, v in (cg_members or {}).items()}

    def summary(k, source):
        th = by_key.get(k)
        if not th:
            return None
        return {"key": k, "name": th.get("name"), "tier": th.get("tier"),
                "tags": list(th.get("tags") or []), "beta": th.get("beta"),
                # the "Kdy prodat" rule reads it: a theme falling behind BTC
                "rs1m": th.get("rs1m"), "stale": bool(stale), "source": source}

    counts = dict.fromkeys(JOIN_SOURCES + ("none",), 0)
    none_categories = {}
    for e in apps:
        k, source = app_theme(e, cg)
        e["theme"] = summary(k, source)
        if e["theme"]:
            counts[source] += 1
        else:
            counts["none"] += 1
            cat = e.get("category") or "—"
            none_categories[cat] = none_categories.get(cat, 0) + 1
    for e in chains:
        k = theme_of_chain(e, members)
        e["theme"] = summary(k, "basket" if e.get("gecko_id") in members.get(k, ()) else "layer")
    for e in apps + chains:
        e["basket_themes"] = sorted(k for k, ids in members.items() if e.get("gecko_id") in ids)
        e["cg_themes"] = sorted(k for k, ids in cg.items() if e.get("gecko_id") in ids)

    before = {}
    for e in ((prev_snapshot or {}).get("apps") or []) + ((prev_snapshot or {}).get("chains") or []):
        before[e.get("key") or e.get("slug")] = (e.get("theme") or {}).get("key")
    changed = []
    for e in apps + chains:
        rid = e.get("key") or e.get("slug")
        now_k = (e.get("theme") or {}).get("key")
        if rid in before and before[rid] != now_k:
            changed.append({"key": rid, "name": e.get("name"), "from": before[rid], "to": now_k,
                            "source": (e.get("theme") or {}).get("source")})
    changed.sort(key=lambda c: str(c["key"]))     # rows arrive in thread-completion order
    return {"version": row_join_version(), "ladder": list(LADDER),
            "order": [t["key"] for t in THEMES], "residual": list(RESIDUALS),
            "chain_layers": list(LAYERS), "overrides": dict(THEME_OVERRIDES),
            "nearest": dict(NEAREST_THEME), "counts": counts,
            "none_categories": none_categories, "changed": changed[:100],
            "n_changed": len(changed)}


# ------------------------------------------------------------------ fundament
def fundament_apps(theme, sectors_apps, C, feed_cats):
    """`missing` = the category name does not exist in DeFiLlama at all (a typo
    or a rename — "RWA Lending" never existed and would silently add zero).
    `below_floor` = it exists but no adapter clears $10k/30d this month, which
    is legitimate and changes month to month (Restaking, 2026-09)."""
    by = {r["category"]: r for r in sectors_apps}
    rows = [by[c] for c in theme["dl"] if c in by]
    missing = [c for c in theme["dl"] if c not in by and c not in feed_cats]
    below = [c for c in theme["dl"] if c not in by and c in feed_cats]
    out = {"kind": "revenue", "categories": [r["category"] for r in rows], "missing": missing,
           "below_floor": below,
           "rev30d": None, "g6m": None, "r2": None, "monthly": [], "share_pct": None,
           "by_category": [], "small": True}
    if not rows:
        return out
    series = C.sum_series([r.get("series") or [] for r in rows])
    g = C.growth6m(series, agg="sum")
    rev = sum(r.get("rev30d") or 0 for r in rows)
    out.update({
        "rev30d": round(rev, 2), "g6m": g.get("g"), "r2": g.get("r2"),
        "monthly": C.monthly_buckets(series, 13, agg="sum"),
        "share_pct": round(sum(r.get("share_pct") or 0 for r in rows), 2),
        "by_category": sorted([{"category": r["category"], "rev30d": r.get("rev30d") or 0,
                                "n_all": r.get("n_all"), "n_tok": r.get("n_tok")} for r in rows],
                              key=lambda x: -x["rev30d"]),
        "small": rev < 1e6,
        "series": C.clean_series(series),
    })
    return out


def fundament_chains(ctx, layer, C):
    """Stablecoin capital on every chain of the layer — including chains with no
    token. Base alone is 38 % of all L2 stablecoins; leaving it out made the L2
    fundament a proxy for X Layer. This is a STOCK, so weekly buckets are means."""
    rows = []
    for name, st in ctx.stable_by_chain.items():
        if (st or 0) < 1e7:
            continue
        v = ctx.chain_gecko.get(name) or {}
        types = ((v.get("parent") or {}).get("types")) or []
        lay = "L2" if ("L2" in types or "L3" in types) else "L1"
        if lay == layer:
            rows.append((name, st, bool(v.get("geckoId"))))
    rows.sort(key=lambda r: -r[1])
    total = sum(r[1] for r in rows) or 1.0
    picked, cum = [], 0.0
    for r in rows:
        picked.append(r)
        cum += r[1]
        if cum >= 0.98 * total or len(picked) >= 20:
            break

    def one(name):
        d = ctx.get("https://stablecoins.llama.fi/stablecoincharts/%s" % urllib.parse.quote(name), timeout=40)
        s = []
        for pt in d or []:
            val = (pt.get("totalCirculating") or {}).get("peggedUSD")
            if val:
                s.append([int(pt["date"]), float(val)])
        return name, s[-C.MAX_SERIES_DAYS:]

    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        got = dict(ex.map(lambda r: one(r[0]), picked))
    # levels on the SAME date add up to the layer's supply; each chain is
    # forward-filled onto the union of dates so a missing day is not a dip
    stamps = sorted({t for s in got.values() for t, _ in s})
    summed = []
    ptr = {n: 0 for n in got}
    last = {n: None for n in got}
    for t in stamps:
        for n, s in got.items():
            while ptr[n] < len(s) and s[ptr[n]][0] <= t:
                last[n] = s[ptr[n]][1]
                ptr[n] += 1
        vals = [v for v in last.values() if v is not None]
        if vals:
            summed.append([t, sum(vals)])
    g = C.growth6m(summed, agg="mean")
    level = summed[-1][1] if summed else None
    top = [{"chain": r[0], "stables": r[1], "share_pct": round(100.0 * r[1] / total, 1),
            "tokenized": r[2]} for r in rows[:6]]
    return {"kind": "stables", "level": level, "g6m": g.get("g"), "r2": g.get("r2"),
            "monthly": C.monthly_buckets(summed, 13, agg="mean"),
            "chains": len(rows), "covered": len(picked), "top": top,
            "top2_share": round(sum(x["share_pct"] for x in top[:2]), 1),
            "untokenized_share": round(100.0 * sum(r[1] for r in rows if not r[2]) / total, 1),
            "small": False, "series": C.clean_series(summed)}


# ------------------------------------------------------------------ the build
def build_themes(ctx, sectors_apps, now, prev_snapshot=None):
    import collector as C          # lazy: collector imports this module
    validate_crosswalk()
    feed_cats = {p.get("category") for p in ctx.fee_protocols if p.get("category")}
    cache_path = os.path.join(ctx.data_dir, CACHE_NAME)
    cache, rebuilt = refresh_baskets(ctx, load_cache(cache_path), now)
    save_cache(cache_path, cache)
    ctx.log("koše témat: %s" % ("obnoveno " + ", ".join(rebuilt) if rebuilt else "z cache"))

    # --- candidate lists, with a documented retreat when a theme has nothing
    cands, source, age = {}, {}, {}
    for t in THEMES:
        ent = cache["themes"].get(t["key"])
        if ent and ent.get("coins"):
            cands[t["key"]] = ent["coins"]
            source[t["key"]] = "cache" if t["key"] not in rebuilt else "fresh"
            age[t["key"]] = round((now - ent.get("built_at", now)) / DAY, 1)
        else:
            cands[t["key"]], source[t["key"]] = fallback_members(t["key"], prev_snapshot)
            age[t["key"]] = None
            ctx.warn("koš %s: %s" % (t["name"], source[t["key"]]))
    # exclusive assignments
    for gid, owner in THEME_OVERRIDES.items():
        for k in cands:
            if k != owner:
                cands[k] = [c for c in cands[k] if c["id"] != gid]
    # which themes CoinGecko files a coin under — step 3-4 of app_theme's
    # ladder. The same candidate lists the baskets are built from, no deeper:
    # at rank 200 CoinGecko tags liberally and "AI" would claim half the market
    cg_members = {k: sorted({c["id"] for c in v}) for k, v in cands.items()}
    # a chain's own coin is a chain, whatever else CoinGecko files it under
    # (Kaspa sits in "wallets", ZetaChain in "cross-chain-communication"), so
    # a residual theme without a layer leaves it to L1/L2
    chain_coins = ({v.get("geckoId") for v in (getattr(ctx, "chain_gecko", None) or {}).values()
                    if isinstance(v, dict) and v.get("geckoId")}
                   | {c["id"] for k in LAYERS for c in cands.get(k) or []})

    universe = ((cache.get("universe") or {}).get("coins")) or []
    all_ids = sorted({c["id"] for v in cands.values() for c in v} | {c["id"] for c in universe} | {"bitcoin"})

    # --- live market data: one or two CoinGecko calls, never fatal
    live, meta, mkt = {}, {}, {}
    for c in universe + [c for v in cands.values() for c in v]:
        meta.setdefault(c["id"], dict(c))
    for i in range(0, len(all_ids), 250):
        rows = cg_get(ctx, "%s/coins/markets?vs_currency=usd&ids=%s&per_page=250&page=1"
                           "&price_change_percentage=7d,30d,1y"
                           % (CG, ",".join(all_ids[i:i + 250])))
        time.sleep(6)
        for c in rows or []:
            meta[c["id"]] = _meta(c)
            mkt[c["id"]] = market_fields(c)
            if c.get("current_price"):
                live[c["id"]] = float(c["current_price"])
    live_ts = int(time.time())
    ctx.log("živé ceny: %d/%d coinů" % (len(live), len(all_ids)))

    # --- the weekly grid
    stamps = week_stamps(now)
    raw = fetch_grid(ctx, all_ids, stamps)
    raw["bitcoin"] = btc_row(ctx, stamps, raw)
    anomalies = []
    grid = {g: clean_row(g, row, anomalies) for g, row in raw.items()}
    rb = simple_returns(grid["bitcoin"])
    rets = {g: simple_returns(p) for g, p in grid.items()}
    ctx.log("týdenní ceny: %d/%d coinů, %d anomálií" % (len(grid), len(all_ids), len(anomalies)))

    def mcap(g):
        return (meta.get(g) or {}).get("mcap") or 0

    def excl(g):
        return hard_exclusion(g, (meta.get(g) or {}).get("name"), grid.get(g) or [], rets.get(g) or [], rb)

    btc_live = None
    if live.get("bitcoin") and grid["bitcoin"][-1]:
        btc_live = live["bitcoin"] / grid["bitcoin"][-1] - 1
    # BTC's own index, once — it does not depend on any theme
    btc_index, bacc = [], 1.0
    for k in range(N_STAMPS):
        if k and rb[k] is not None:
            bacc *= 1 + rb[k]
        btc_index.append(round(bacc * 100, 3))

    # --- the altseason universe and its index (stamp-based so the header and
    # the last history point are the same number)
    eligible_u = [c["id"] for c in universe if c["id"] != "bitcoin" and not excl(c["id"])]
    history = []
    for j in range(13, N_STAMPS):
        if not (grid["bitcoin"][j] and grid["bitcoin"][j - 13]):
            continue
        pool = [g for g in eligible_u if grid.get(g) and grid[g][j] and grid[g][j - 13]]
        # top 50 by the mcap they had THEN (constant-supply proxy), not today's
        pool.sort(key=lambda g: -(mcap(g) * grid[g][j] / (live.get(g) or grid[g][-1] or grid[g][j])))
        pool = pool[:ALTSEASON_N]
        if len(pool) < 30:
            continue
        b = grid["bitcoin"][j] / grid["bitcoin"][j - 13]
        beat = sum(1 for g in pool if grid[g][j] / grid[g][j - 13] > b)
        history.append([stamps[j], round(100.0 * beat / len(pool), 1), len(pool)])
    # r_ALT for gamma: equal-weighted simple return of the top-50-by-mcap alts
    alt50 = sorted(eligible_u, key=lambda g: -mcap(g))[:ALTSEASON_N]
    r_alt = [None] * N_STAMPS
    for k in range(1, N_STAMPS):
        xs = [rets[g][k] for g in alt50 if rets.get(g) and rets[g][k] is not None]
        if len(xs) >= 20:
            r_alt[k] = sum(xs) / len(xs)
    alt_4w_median = _median([
        math.exp(window_return(rets[g], N_STAMPS - 1 - 4,
                               (live[g] / grid[g][-1] - 1) if (live.get(g) and grid[g][-1]) else None)) - 1
        for g in alt50 if rets.get(g) and grid[g][N_STAMPS - 1 - 4]])

    # --- per theme
    out, member_of = [], {}
    order = [t for t in THEMES if not t.get("residual")] + [t for t in THEMES if t.get("residual")]
    for t in order:
        key = t["key"]
        dropped, pool = [], []
        for c in cands[key]:
            g = c["id"]
            if g not in grid:
                dropped.append({"id": g, "sym": c.get("symbol", ""), "reason": "bez cenové historie"})
                continue
            why = excl(g)
            if not why and t.get("residual") and g in member_of:
                why = "patří tématu %s" % member_of[g]
            if not why and t.get("residual") and not t.get("chain_layer") and g in chain_coins:
                why = "token chainu"
            if why:
                dropped.append({"id": g, "sym": (meta.get(g) or c).get("symbol", ""), "reason": why})
                continue
            pool.append(g)

        # DISPLAY basket: today's top 15 among coins with enough history — what
        # the theme looks like now (logos, mcap, the member list in the panel)
        eligible = [g for g in pool if sum(1 for x in rets[g] if x is not None) >= MIN_RETURNS]
        for g in pool:
            if g not in eligible:
                dropped.append({"id": g, "sym": (meta.get(g) or {}).get("symbol", ""),
                                "reason": "méně než %d týdnů historie" % MIN_RETURNS})
        members, weights = pick_basket(eligible, mcap)
        if not t.get("residual"):
            for g in members:
                member_of.setdefault(g, t["name"])

        # BETA basket: the top 15 as they stood at the START of the year being
        # measured. Beta is a historical statistic, and estimating it on today's
        # survivors is look-ahead: on 2026-09-22 it moved Prediction markets from
        # 0.82 to 0.62 — enough to change its tier. Same rule relative strength
        # already uses. No 40-week requirement here: that filter would quietly
        # drop exactly the coins that died during the year.
        def mc_start(g):
            now_p = live.get(g) or grid[g][-1]
            return mcap(g) * grid[g][0] / now_p if (now_p and grid[g][0]) else 0
        beta_pool = [g for g in pool if grid[g][0]]
        beta_members, beta_weights = pick_basket(beta_pool, mc_start)

        th = {"key": key, "name": t["name"], "blurb": t["blurb"], "kind": "chains" if t.get("chain_layer") else "apps",
              "basket_source": source[key], "basket_age_days": age[key], "dropped": dropped[:40]}

        if len(members) < MIN_MEMBERS or len(beta_members) < MIN_MEMBERS:
            th.update({"status": "few_members", "n": len(members), "members": [], "beta": None,
                       "tier": None, "tags": []})
        else:
            # the year chart and beta both describe the PAST, so both use the
            # basket as it stood at the start of that past
            rt_raw = basket_returns([rets[g] for g in beta_members], beta_weights)
            rt_clip = basket_returns([rets[g] for g in beta_members], beta_weights, clip=BETA_CLIP)
            wk = [k for k in range(1, N_STAMPS) if rt_clip[k] is not None and rb[k] is not None]
            st = regress([rb[k] for k in wk], [rt_clip[k] for k in wk]) if len(wk) >= 30 else None
            up = [k for k in wk if rb[k] > 0]
            st_up = regress([rb[k] for k in up], [rt_clip[k] for k in up]) if len(up) >= 12 else None
            gk = [k for k in wk if r_alt[k] is not None]
            st_g = regress([r_alt[k] - rb[k] for k in gk], [rt_clip[k] - rb[k] for k in gk]) if len(gk) >= 30 else None
            te = _stdev([math.log(1 + rt_clip[k]) - math.log(1 + rb[k]) for k in wk]) if wk else None
            beta = st["slope"] if st else None
            tier = beta_tier(beta, st["se"] if st else None)

            idx, acc = [], 1.0
            for k in range(N_STAMPS):
                if k and rt_raw[k] is not None:
                    acc *= 1 + rt_raw[k]
                idx.append(round(acc * 100, 3))

            mem_out = []
            for g, w in zip(members, weights):
                cr = regress([rb[k] for k in wk if rets[g][k] is not None],
                             [rets[g][k] for k in wk if rets[g][k] is not None])
                lv = (live[g] / grid[g][-1] - 1) if (live.get(g) and grid[g][-1]) else None
                c1 = window_return(rets[g], N_STAMPS - 1 - 4, lv) - window_return(rb, N_STAMPS - 1 - 4, btc_live)
                c3 = window_return(rets[g], N_STAMPS - 1 - 13, lv) - window_return(rb, N_STAMPS - 1 - 13, btc_live)
                m = meta.get(g) or {}
                mk = mkt.get(g) or {}
                mem_out.append({"id": g, "sym": m.get("symbol", ""), "name": m.get("name", g),
                                "w": round(w, 5), "mcap": m.get("mcap") or 0,
                                "rs1m": round(math.exp(c1) - 1, 4), "rs3m": round(math.exp(c3) - 1, 4),
                                "beta": round(cr["slope"], 3) if cr else None,
                                # live call only (see market_fields); None when it failed
                                "chg7d": mk.get("chg7d"), "chg30d": mk.get("chg30d"),
                                "vol24h": mk.get("vol24h"), "ath_chg_pct": mk.get("ath_chg_pct")})

            th.update({"status": "ok", "n": len(members), "members": mem_out,
                       "beta": round(beta, 4) if beta is not None else None,
                       "beta_se": round(st["se"], 4) if st else None,
                       "rho": round(st["rho"], 4) if st else None,
                       "n_weeks": st["n"] if st else 0,
                       "beta_up": round(st_up["slope"], 3) if st_up else None,
                       "gamma": round(st_g["slope"], 3) if st_g else None,
                       "te_week": round(te, 5) if te else None,
                       "tier": tier, "index": idx, "mcap": sum(m["mcap"] for m in mem_out),
                       "top3": [m["id"] for m in sorted(mem_out, key=lambda m: -m["w"])[:3]],
                       "beta_members": [{"id": g, "w": round(w, 6), "mcap": mcap(g)}
                                        for g, w in zip(beta_members, beta_weights)],
                       "beta_basket_overlap": len(set(beta_members) & set(members))})

        # --- relative strength on the basket as it stood at the window START
        for W, label in ((4, "1m"), (13, "3m")):
            k0 = N_STAMPS - 1 - W
            at0 = [g for g in pool if grid[g][k0] and (live.get(g) or grid[g][-1])]

            def mc0(g, k0=k0):
                now_p = live.get(g) or grid[g][-1]
                return mcap(g) * grid[g][k0] / now_p if now_p else 0

            rs_mem, rs_w = pick_basket(at0, mc0)
            if len(rs_mem) < MIN_MEMBERS:
                th["rs" + label] = None
                th["rs_members_" + label] = []
                continue
            br = basket_returns([rets[g] for g in rs_mem], rs_w)
            lp = [(w, live[g] / grid[g][-1] - 1) for g, w in zip(rs_mem, rs_w) if live.get(g) and grid[g][-1]]
            t_live = (sum(w * x for w, x in lp) / sum(w for w, _ in lp)) if lp else None
            rel = window_return(br, k0, t_live) - window_return(rb, k0, btc_live if t_live is not None else None)
            th["rs" + label] = round(math.exp(rel) - 1, 4)
            th["rs_members_" + label] = [{"id": g, "w": round(w, 5)} for g, w in zip(rs_mem, rs_w)]
            if label == "3m":
                beats = 0
                for g in rs_mem:
                    lv = (live[g] / grid[g][-1] - 1) if (live.get(g) and grid[g][-1]) else None
                    own = window_return(rets[g], k0, lv) - window_return(rb, k0, btc_live if lv is not None else None)
                    beats += 1 if own > 0 else 0
                th["breadth"] = round(100.0 * beats / len(rs_mem), 1)
            if label == "1m":
                th["theme_4w"] = round(math.exp(window_return(br, k0, t_live)) - 1, 4)

        # --- fundament
        if t.get("chain_layer"):
            th["fundament"] = fundament_chains(ctx, t["chain_layer"], C)
        else:
            th["fundament"] = fundament_apps(t, sectors_apps, C, feed_cats)
            for c in th["fundament"]["missing"]:
                ctx.warn("téma %s: kategorie DeFiLlamy '%s' neexistuje — překlep nebo "
                         "přejmenování, přispívá nulou" % (t["name"], c))
        out.append(th)

    # --- tags, now that every theme is measured
    for th in out:
        tags = []
        te, beta, rho = th.get("te_week"), th.get("beta"), th.get("rho")
        z1 = z3 = None
        if te and th.get("rs1m") is not None:
            z1 = math.log(1 + th["rs1m"]) / (2.0 * te)
        if te and th.get("rs3m") is not None:
            z3 = math.log(1 + th["rs3m"]) / (math.sqrt(13) * te)
        th["z1"] = round(z1, 3) if z1 is not None else None
        th["z3"] = round(z3, 3) if z3 is not None else None
        beat_alts = (th.get("theme_4w") is not None and alt_4w_median is not None
                     and th["theme_4w"] > alt_4w_median)
        th["beat_median_alt_1m"] = bool(beat_alts)
        if th.get("status") == "ok":
            if z1 is not None and z1 >= 1.5 and beat_alts:
                tags.append("leads")
            if th.get("tier") == 5 and z3 is not None and z3 <= 0.5:
                tags.append("waiting")
            if rho is not None and rho < 0.5:
                tags.append("own_story")
        f = th.get("fundament") or {}
        if (f.get("kind") == "revenue" and not f.get("small") and (f.get("g6m") or 0) >= 5
                and (f.get("r2") or 0) >= 0.25):
            tags.append("fund_up")
        th["tags"] = tags

    # --- shared coins (theme mcaps are never added together)
    for a in out:
        mine = {m["id"] for m in a.get("members") or []}
        a["shared_with"] = [{"key": b["key"], "name": b["name"],
                             "n": len(mine & {m["id"] for m in b.get("members") or []})}
                            for b in out if b is not a and mine & {m["id"] for m in b.get("members") or []}]

    out.sort(key=lambda th: -(th["beta"] if th.get("beta") is not None else -9))

    # --- revenue no theme claims
    mapped = {c for t in THEMES for c in t["dl"]}
    un = [r for r in sectors_apps if r["category"] not in mapped]
    tot = sum(r.get("rev30d") or 0 for r in sectors_apps) or 1.0
    unmapped = {"rev30d": round(sum(r.get("rev30d") or 0 for r in un), 2),
                "share_pct": round(100.0 * sum(r.get("rev30d") or 0 for r in un) / tot, 1),
                "top": [r["category"] for r in sorted(un, key=lambda r: -(r.get("rev30d") or 0))[:6]]}

    # --- logos for every basket member (shared across themes, deduped)
    need = sorted({m["id"] for th in out for m in th.get("members") or []})
    logos = {}

    def logo(g):
        img = (meta.get(g) or {}).get("image")
        if not img:
            return g, None
        return g, C.fetch_logo(ctx, img.replace("/large/", "/small/"))

    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        for g, data in ex.map(logo, need):
            if data:
                logos[g] = data
    coin_meta = {g: {"sym": (meta.get(g) or {}).get("symbol", ""), "name": (meta.get(g) or {}).get("name", g),
                     "logo": logos.get(g)} for g in need}

    # every coin ANY stored number was computed from — the beta basket is the
    # year-ago composition and includes coins that have since dropped out of
    # today's top 15 (Helium, Ronin, dYdX…); leaving those out made beta
    # impossible to recompute from the snapshot
    used = sorted(set(need) | {"bitcoin"} | set(alt50) | set(eligible_u)
                  | {m["id"] for th in out for lbl in ("1m", "3m") for m in th.get("rs_members_" + lbl) or []}
                  | {m["id"] for th in out for m in th.get("beta_members") or []})
    theme_prices = {"stamps": stamps, "live_ts": live_ts,
                    "coins": {g: grid[g] for g in used if g in grid},
                    "live": {g: live[g] for g in used if g in live}}
    idx_now = history[-1][1] if history else None
    three_months_ago = next((h[1] for h in history if h[0] <= stamps[-1] - 13 * WEEK), None) if history else None
    altseason = {"index": idx_now, "history": history, "n": ALTSEASON_N,
                 "three_months_ago": three_months_ago, "universe": eligible_u, "alt50": alt50,
                 # today's mcaps, so the audit can re-rank every history point itself
                 "universe_mcap": {g: mcap(g) for g in eligible_u},
                 "alt_4w_median": round(alt_4w_median, 4) if alt_4w_median is not None else None,
                 "btc_1m": round(math.exp(window_return(rb, N_STAMPS - 1 - 4, btc_live)) - 1, 4),
                 "btc_3m": round(math.exp(window_return(rb, N_STAMPS - 1 - 13, btc_live)) - 1, 4),
                 "btc_index": btc_index}
    ok = sum(1 for th in out if th.get("status") == "ok")
    ctx.log("témata: %d/%d změřených, altseason index %s %%"
            % (ok, len(out), ("%.0f" % idx_now) if idx_now is not None else "—"))
    return {"themes": out, "altseason": altseason, "theme_prices": theme_prices,
            "coin_meta": coin_meta, "theme_anomalies": anomalies, "unmapped": unmapped,
            "cg_members": cg_members}
