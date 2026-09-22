"""
Float and unlock schedule — shown as a tag and text, never a filter.

Adam decided (2026-09-22, third time) that tokenomics must not exclude a row or
enter the sort. The degen persona still has to SEE it: "up" read 39x while 4 %
of its tokens circulate, and HumidiFi unlocks +46 % of its circulating supply
in a single cliff 72 days out.

Source: defillama-datasets.llama.fi (free; api.llama.fi/emissions is the paid
API). One file per protocol — Arbitrum's is 821 KB — so only a compact
extraction is cached (7 days): the daily cumulative unlock curve from 30 days
before the fetch to 400 days after, the insiders' part of it, future cliffs and
the supply metrics. Everything shown is RE-DERIVED from that on every run, so
"next cliff" cannot go stale inside the cache's life.

Rules:
  - the join is verified on gecko_id — "up" is a generic slug;
  - treasury ("noncirculating") unlocks are left out: tokens moving into a DAO
    treasury are not supply offered to the market;
  - no file is "no data", never zero.
"""
import concurrent.futures as cf
import os
import re

import themes

DAY = 86400
LIST_URL = "https://defillama-datasets.llama.fi/emissionsProtocolsList"
FILE_URL = "https://defillama-datasets.llama.fi/emissions/%s"
CACHE = "unlocks_cache.json"
MAX_AGE = 7 * DAY
BEFORE, AFTER = 30, 400                  # days of curve kept around the fetch
INSIDER_CATS = {"insiders", "privateSale"}
EXCLUDE_CATS = {"noncirculating"}


def _slugify(name):
    s = (name or "").lower().strip()
    s = re.sub(r"[^a-z0-9.\- ]", "", s)
    return re.sub(r"\s+", "-", s)


def slug_candidates(e):
    key = e.get("key") or ""
    return [c for c in dict.fromkeys([key.split("#", 1)[1] if key.startswith("parent#") else None,
                                      e.get("slug"), _slugify(e.get("name"))]) if c]


def extract(j, now):
    """One emissions file -> the compact, date-anchored record kept in cache."""
    cats = j.get("categories") or {}
    label_cat = {lbl: c for c, lbls in cats.items() for lbl in (lbls or [])}
    d0 = int(now // DAY) - BEFORE
    n = BEFORE + AFTER + 1
    circ, ins = [0.0] * n, [0.0] * n
    for s in (j.get("documentedData") or {}).get("data") or []:
        cat = label_cat.get(s.get("label"))
        if cat in EXCLUDE_CATS:
            continue
        pts = sorted((int(p.get("timestamp") or 0), float(p.get("unlocked") or 0))
                     for p in s.get("data") or [])
        j_, last = 0, 0.0
        for i in range(n):
            t = (d0 + i) * DAY
            while j_ < len(pts) and pts[j_][0] <= t:
                last = pts[j_][1]
                j_ += 1
            circ[i] += last
            if cat in INSIDER_CATS:
                ins[i] += last
    cliffs = {}
    for ev in (j.get("metadata") or {}).get("events") or []:
        ts = int(ev.get("timestamp") or 0)
        if ev.get("unlockType") != "cliff" or ts < d0 * DAY or ev.get("category") in EXCLUDE_CATS:
            continue
        tok = sum(float(x or 0) for x in (ev.get("noOfTokens") or []))
        c = cliffs.setdefault(ts, {})
        c[ev.get("category") or "?"] = c.get(ev.get("category") or "?", 0.0) + tok
    sm = j.get("supplyMetrics") or {}
    return {"gecko_id": j.get("gecko_id"), "d0": d0,
            "circ": [round(x) for x in circ], "ins": [round(x) for x in ins],
            "cliffs": [[ts, {k: round(v) for k, v in c.items()}] for ts, c in sorted(cliffs.items())],
            "max_supply": sm.get("maxSupply"), "tbd": sm.get("tbdAmount")}


def derive(x, now):
    """What the page shows, recomputed from the cached record for `now`."""
    i0 = int(now // DAY) - x["d0"]
    circ, ins = x["circ"], x["ins"]
    if not (0 <= i0 < len(circ) - 90):
        return None
    c_now, c_90 = circ[i0], circ[i0 + 90]
    d_all = c_90 - c_now
    nxt = None
    for ts, parts in x.get("cliffs") or []:
        if ts <= now:
            continue
        tok = sum(parts.values())
        if tok <= 0:
            continue
        top = max(parts.items(), key=lambda kv: kv[1])[0]
        nxt = {"ts": ts, "days": round((ts - now) / DAY, 1), "tokens": tok,
               "pct_of_circ": round(100.0 * tok / c_now, 2) if c_now > 0 else None,
               "category": top, "insider_share": round(sum(v for k, v in parts.items()
                                                          if k in INSIDER_CATS) / tok, 3)}
        break
    ms, tbd = x.get("max_supply"), x.get("tbd")
    return {"unlocked_now": c_now,
            "unlock90_pct": round(100.0 * d_all / c_now, 2) if c_now > 0 else None,
            "insider90_share": (round((ins[i0 + 90] - ins[i0]) / d_all, 3) if d_all > 0 else None),
            "next_cliff": nxt,
            "tbd_pct": round(100.0 * tbd / ms, 1) if (ms and tbd and ms > 0) else None}


def build_unlocks(ctx, apps, now):
    """Attach `unlock` (dict or None) to every app row; returns unlocks_meta."""
    path = os.path.join(ctx.data_dir, CACHE)
    cache = themes.load_cache(path)
    lst = cache.get("list") or {}
    if not lst.get("slugs") or now - lst.get("at", 0) >= MAX_AGE:
        got = ctx.get(LIST_URL, timeout=40)
        if got:
            lst = {"at": now, "slugs": sorted(set(got))}
        elif lst.get("slugs"):
            ctx.warn("seznam unlocků DeFiLlamy neodpověděl, držím %d dní starý"
                     % ((now - lst.get("at", now)) // DAY))
    slugs = set(lst.get("slugs") or [])
    files = cache.get("files") or {}

    def fresh(s):
        f = files.get(s)
        return f is not None and now - f.get("at", 0) < MAX_AGE

    need = sorted({c for e in apps for c in slug_candidates(e) if c in slugs and not fresh(c)})

    def fetch(slug):
        d = ctx.get(FILE_URL % slug, timeout=60, quiet_status=(400, 403, 404))
        return slug, (extract(d, now) if isinstance(d, dict) else None), d is not None

    stale = []
    with cf.ThreadPoolExecutor(max_workers=6) as ex:
        for slug, x, ok in ex.map(fetch, need):
            if ok:
                files[slug] = {"at": now, "x": x}
            elif slug in files:
                stale.append(slug)            # keep the old extraction, flagged below
    themes.save_cache(path, {"list": lst, "files": files})

    matched = mismatch = 0
    for e in apps:
        e["unlock"] = None
        for c in slug_candidates(e):
            f = files.get(c)
            x = (f or {}).get("x")
            if not x:
                continue
            if x.get("gecko_id") != e.get("gecko_id"):
                mismatch += 1
                continue
            dv = derive(x, now)
            if dv is None:
                continue
            dv.update({"slug": c, "as_of": f["at"], "stale": now - f["at"] >= MAX_AGE})
            e["unlock"] = dv
            matched += 1
            break
    if stale:
        ctx.warn("unlocky %d protokolů z cache (DeFiLlama neodpověděla): %s"
                 % (len(stale), ", ".join(stale[:8])))
    ctx.log("unlocky: %d appek s daty, %d souborů nově staženo, %d odmítnutých joinů (jiný gecko_id)"
            % (matched, len(need), mismatch))
    return {"matched": matched, "fetched": len(need), "join_rejected": mismatch,
            "list_size": len(slugs), "list_at": lst.get("at")}
