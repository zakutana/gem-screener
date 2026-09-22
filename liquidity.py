"""
Liquidity — can a degen actually buy, and later sell, a $10K position?

The screener ranked a $4,5M protocol next to a $2 bn one with nothing to say
that the first may not have a pool deep enough to get in and out of. This
module answers it per coin, from two free sources:

    CoinGecko /coins/list?include_platform=true   contract addresses (1 call)
    DexScreener /tokens/v1/{chain}/{addr,...}      the token's main pair per
                                                   chain, 30 addresses a call

Price impact of a $10K buy in a constant-product pool whose quote side holds
L/2 dollars is ticket / (L/2) = 2 * ticket / L, so <= 3 % needs L >= $667K.
It is an order-of-magnitude figure and is always printed with "≈":
  - pessimistic: concentrated liquidity (v3, CLMM, DLMM) is deeper near the
    price than its total suggests, and an aggregator would split the order;
  - optimistic: out-of-range or one-sided positions, pool fees and MEV.
Coins listed on centralised exchanges often have thin DEX pools, so 24 h
CoinGecko volume of at least 200x the ticket also passes — optimistic where
volume is wash-traded, and said so in the tooltip.

Every source is cached (addresses 7 days, pairs 12 hours, a stale pair usable
up to 7 days with a flag), and every failure degrades to "likvidita neznámá",
never to a made-up number. All state lives on the ctx or in return values:
app.py calls the collector repeatedly inside one process.
"""
import os
import time
from collections import Counter

import themes

DAY = 86400
DEX = "https://api.dexscreener.com"
CG_LIST = "https://api.coingecko.com/api/v3/coins/list?include_platform=true"
TICKET = 10_000
MAX_IMPACT_PCT = 3.0
VOL_PASS = 200 * TICKET
PLATFORMS_CACHE = "platforms_cache.json"
PLATFORMS_MAX_AGE = 7 * DAY
DEX_CACHE = "dex_cache.json"
DEX_FRESH = 12 * 3600
DEX_MAX_STALE = 7 * DAY
BATCH = 30
MAX_FALLBACKS = 60

# CoinGecko platform key -> DexScreener chainId. Verified 2026-09-22 with a live
# pair lookup where a token had one (ethereum … pulsechain); the rest are the
# documented DexScreener ids. An unmapped platform only costs that one address,
# and the count is reported in liquidity_meta.
PLATFORM_TO_DS = {
    "ethereum": "ethereum", "base": "base", "solana": "solana", "binance-smart-chain": "bsc",
    "arbitrum-one": "arbitrum", "polygon-pos": "polygon", "optimistic-ethereum": "optimism",
    "avalanche": "avalanche", "hyperevm": "hyperevm", "robinhood": "robinhood",
    "hyperliquid": "hyperliquid", "fantom": "fantom", "sui": "sui", "aptos": "aptos",
    "cardano": "cardano", "abstract": "abstract", "tron": "tron", "pulsechain": "pulsechain",
    "sonic": "sonic", "berachain": "berachain", "zksync": "zksync", "linea": "linea",
    "mantle": "mantle", "scroll": "scroll", "blast": "blast", "unichain": "unichain",
    "the-open-network": "ton", "cronos": "cronos", "mode": "mode", "manta-pacific": "manta",
    "celo": "celo", "metis-andromeda": "metis", "sei-v2": "seiv2", "starknet": "starknet",
    "near-protocol": "near", "osmosis": "osmosis", "injective": "injective", "stellar": "stellar",
    "hedera-hashgraph": "hedera", "kava": "kava", "core": "core", "flare-network": "flare",
    "world-chain": "worldchain", "ink": "ink", "soneium": "soneium", "apechain": "apechain",
    "bob-network": "bob", "taiko": "taiko", "plasma": "plasma", "monad": "monad",
    "katana": "katana", "megaeth": "megaeth", "xdai": "gnosischain",
    "polygon-zkevm": "polygonzkevm", "opbnb": "opbnb",
}

# A pair only counts when its other side is money: a stablecoin or a chain's
# native asset. An inflated "liquidity" against a token nobody else holds is
# the cheapest thing to fake on a DEX.
QUOTES = {
    "USDC", "USDT", "USDC.E", "USDBC", "USDT0", "USD₮0", "USD₮", "DAI", "USDE", "USDS", "USD1",
    "FDUSD", "PYUSD", "USDB", "USDG", "USDH", "LUSD", "FRAX", "GHO", "CRVUSD", "RLUSD",
    "ETH", "WETH", "BNB", "WBNB", "SOL", "WSOL", "AVAX", "WAVAX", "POL", "WPOL", "MATIC",
    "WMATIC", "HYPE", "WHYPE", "BTC", "WBTC", "CBBTC", "BTCB", "S", "WS", "BERA", "WBERA",
    "SUI", "TON", "TRX", "WTRX", "APT", "MNT", "WMNT", "FTM", "WFTM", "PLS", "WPLS", "ADA",
    "CRO", "WCRO", "CELO", "METIS", "SEI", "WSEI", "NEAR", "WNEAR", "OSMO", "INJ", "XLM",
    "HBAR", "KAVA", "CORE", "FLR", "WFLR", "APE", "XPL", "WXPL", "MON", "WMON",
}


def _pair_summary(p, now):
    liq = (p.get("liquidity") or {}).get("usd") or 0
    return {"at": now, "dex": p.get("dexId"), "chain": p.get("chainId"), "url": p.get("url"),
            "liq": float(liq), "quote": ((p.get("quoteToken") or {}).get("symbol") or "").upper(),
            "vol24": float(((p.get("volume") or {}).get("h24")) or 0)}


def _best(pairs, addr_lower, now):
    """Deepest pair where OUR token is the base and the quote is money."""
    ok = [p for p in pairs or []
          if ((p.get("baseToken") or {}).get("address") or "").lower() == addr_lower
          and ((p.get("quoteToken") or {}).get("symbol") or "").upper() in QUOTES
          and ((p.get("liquidity") or {}).get("usd") or 0) > 0]
    if not ok:
        return None
    return _pair_summary(max(ok, key=lambda p: (p.get("liquidity") or {}).get("usd") or 0), now)


def platforms(ctx, now):
    """{gecko_id: {platform: address}} — one CoinGecko call a week."""
    path = os.path.join(ctx.data_dir, PLATFORMS_CACHE)
    cache = themes.load_cache(path)
    if cache.get("map") and now - cache.get("built_at", 0) < PLATFORMS_MAX_AGE:
        return cache["map"], "cache"
    rows = themes.cg_get(ctx, CG_LIST, timeout=120)
    if rows:
        mp = {}
        for r in rows:
            plats = {k: v for k, v in (r.get("platforms") or {}).items() if k and v}
            if r.get("id") and plats:
                mp[r["id"]] = plats
        themes.save_cache(path, {"built_at": now, "map": mp})
        return mp, "fresh"
    if cache.get("map"):
        ctx.warn("adresy tokenů z %d dní staré cache (CoinGecko coins/list neodpověděl)"
                 % ((now - cache.get("built_at", now)) // DAY))
        return cache["map"], "stale"
    ctx.warn("adresy tokenů nejsou k dispozici — likvidita jen podle obratu")
    return {}, "unavailable"


def fetch_pairs(ctx, wanted, now):
    """{(chain, addr_lower): pair summary | None}. wanted maps the same keys to
    the address as CoinGecko spells it (Solana is case-sensitive)."""
    path = os.path.join(ctx.data_dir, DEX_CACHE)
    cache = themes.load_cache(path)
    entries = cache.get("e") or {}

    def fresh(k):
        ent = entries.get("%s:%s" % k)
        return ent is not None and now - ent.get("at", 0) < DEX_FRESH

    todo = {}
    for k in wanted:
        if not fresh(k):
            todo.setdefault(k[0], []).append(k)
    calls = fallbacks = failed = 0
    for chain, keys in sorted(todo.items()):
        # sorted: rows arrive in thread-completion order, and unsorted batches
        # made every run ask DexScreener different URLs
        keys = sorted(keys)
        for i in range(0, len(keys), BATCH):
            part = keys[i:i + BATCH]
            url = "%s/tokens/v1/%s/%s" % (DEX, chain, ",".join(wanted[k] for k in part))
            data = ctx.get(url, timeout=30, quiet_status=(400, 404))
            calls += 1
            time.sleep(0.25)
            if data is None:
                failed += len(part)
                continue
            for k in part:
                best = _best(data, k[1], now)
                returned = any(((p.get("baseToken") or {}).get("address") or "").lower() == k[1]
                               for p in data or [])
                # the batch endpoint gives each token's MAIN pair; when that one
                # is quoted in something that is not money, ask for all pairs
                if best is None and returned and fallbacks < MAX_FALLBACKS:
                    allp = ctx.get("%s/token-pairs/v1/%s/%s" % (DEX, chain, wanted[k]),
                                   timeout=30, quiet_status=(400, 404))
                    fallbacks += 1
                    time.sleep(0.25)
                    best = _best(allp, k[1], now)
                entries["%s:%s" % k] = {"at": now, "pair": best}
    # an entry is kept up to DEX_MAX_STALE so a DexScreener outage degrades to
    # yesterday's depth with a flag, not to "unknown"
    entries = {k: v for k, v in entries.items() if now - v.get("at", 0) < DEX_MAX_STALE}
    themes.save_cache(path, {"e": entries})
    out = {}
    for k in wanted:
        ent = entries.get("%s:%s" % k)
        out[k] = ent.get("pair") if ent else None
    return out, {"calls": calls, "fallbacks": fallbacks, "failed_addresses": failed}


def build_liquidity(ctx, rows, now):
    """Attach `liq` to every row; returns liquidity_meta for the snapshot."""
    pmap, psrc = platforms(ctx, now)
    wanted, keys_of, unmapped = {}, {}, Counter()
    for e in rows:
        keys = []
        for plat, addr in sorted((pmap.get(e.get("gecko_id")) or {}).items()):
            chain = PLATFORM_TO_DS.get(plat)
            if not chain:
                unmapped[plat] += 1
                continue
            k = (chain, addr.lower())
            wanted[k] = addr
            keys.append(k)
        keys_of[id(e)] = keys
    pairs, stats = fetch_pairs(ctx, wanted, now) if wanted else ({}, {"calls": 0})
    src = Counter()
    for e in rows:
        best = max((pairs[k] for k in keys_of[id(e)] if pairs.get(k)),
                   key=lambda p: p["liq"], default=None)
        vol = (e.get("cg") or {}).get("vol24h")
        liq = {"ticket": TICKET, "impact_pct": None, "pair_liq_usd": None, "dex": None,
               "chain": None, "pair_url": None, "quote": None, "dex_vol24h": None,
               "vol24h": vol, "source": "none", "ok": None, "as_of": None, "stale": False}
        dex_ok = False
        if best:
            impact = 100.0 * 2 * TICKET / best["liq"]
            dex_ok = impact <= MAX_IMPACT_PCT
            liq.update(impact_pct=round(impact, 3), pair_liq_usd=round(best["liq"], 2),
                       dex=best["dex"], chain=best["chain"], pair_url=best["url"],
                       quote=best["quote"], dex_vol24h=round(best["vol24"], 2),
                       as_of=best["at"], stale=now - best["at"] >= DEX_FRESH)
        vol_ok = vol is not None and vol >= VOL_PASS
        if dex_ok:
            liq.update(source="dex", ok=True)
        elif vol_ok:
            liq.update(source="volume", ok=True)
        elif best or vol is not None:
            liq.update(source="dex" if best else "volume", ok=False)
        e["liq"] = liq
        src["%s/%s" % (liq["source"], {True: "ok", False: "fail", None: "unknown"}[liq["ok"]])] += 1
    meta = {"ticket": TICKET, "max_impact_pct": MAX_IMPACT_PCT, "vol_pass": VOL_PASS,
            "platforms": psrc, "addresses": len(wanted), "sources": dict(src),
            "unmapped_platforms": dict(unmapped.most_common(12)), **stats}
    ctx.log("likvidita: %d adres, %s, %d volání DexScreeneru"
            % (len(wanted), ", ".join("%s %d" % kv for kv in sorted(src.items())), stats.get("calls", 0)))
    return meta
