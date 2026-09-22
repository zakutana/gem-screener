"""
Independent audit of the sector aggregates and the eleven themes (v12).

App sectors are built from the FULL DeFiLlama universe — including the ~213
adapters with no token, which never appear as rows — so they cannot be checked
against D["apps"]. Instead the collector stores each sector's summed daily
series, and everything else (growth, MoM, share, monthly buckets) is recomputed
from that here with a second implementation.

Run: python audit_sectors.py
"""
import datetime
import io
import json
import math

D = json.load(io.open("snapshot.json", encoding="utf-8"))
SEC = D["sectors"]["apps"]
SEC_CHAINS = D["sectors"]["chains"]
CHAINS = D["chains"]
WINDOWS = D["windows"]
DAY = 86400
FAILS, WARNS = [], []


def head(t):
    print("\n" + "=" * 74 + "\n" + t + "\n" + "=" * 74)


def ols(vals, step_days=1.0, min_points=5):
    pts = [(i, v) for i, v in enumerate(vals) if v and v > 0]
    if len(pts) < min_points:
        return None
    n = len(pts)
    xs = [p[0] for p in pts]
    ys = [math.log(p[1]) for p in pts]
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        return None
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    return max(-99.0, min(999.0, (math.exp(b * (30.0 / step_days)) - 1) * 100))


def weekly(series, agg="sum"):
    if not series:
        return []
    end = series[-1][0]
    bins = {}
    for t, v in series:
        bins.setdefault(int((end - t) // (7 * DAY)), []).append(v)
    out = []
    for b in sorted(bins, reverse=True):
        xs = bins[b]
        if agg == "sum" and len(xs) < 7:
            continue
        out.append(sum(xs) if agg == "sum" else sum(xs) / len(xs))
    return out


def window_total(series, days, end):
    lo = end - days * DAY
    return sum(v for t, v in series if lo < t <= end)


# ---------------------------------------------------------------- 1. growth
head("1. SEKTORY — rust, MoM a mesicni kose prepoctene ze slozene rady")
g_bad = mom_bad = m_bad = rev_bad = 0
examples = []
# ONE calendar window for every sector, exactly as the collector does it. Using
# each sector's own last timestamp instead makes a sector whose adapters lag by
# a few days look 3-4 % smaller, and then the shares are no longer comparable.
GLOBAL_END = max((r["series"][-1][0] for r in SEC if r.get("series")), default=0)
for r in SEC:
    s = r.get("series") or []
    if not s:
        FAILS.append("sektor %s nema ulozenou radu" % r["category"])
        continue
    end = GLOBAL_END

    # Growth is measured on the sector's OWN timeline — it is a question about
    # the shape of that series, and weekly buckets are aligned to its last day.
    # The 30-day windows below deliberately use the shared calendar instead,
    # because those feed shares, which only mean something at one moment.
    own_end = s[-1][0]
    seg = [[t, v] for t, v in s if t > own_end - 182 * DAY]
    mine_g = ols(weekly(seg, "sum"), step_days=7.0)
    if r["g6m"] is None and mine_g is None:
        pass
    elif r["g6m"] is None or mine_g is None or abs(r["g6m"] - mine_g) > 0.2:
        g_bad += 1
        if len(examples) < 5:
            examples.append("%s: rust %s vs %s" % (r["category"], r["g6m"], mine_g))

    now30 = window_total(s, 30, end)
    prev30 = window_total(s, 30, end - 30 * DAY)
    if abs(now30 - r["rev30d"]) > max(1.0, abs(now30) * 0.001):
        rev_bad += 1
        if len(examples) < 5:
            examples.append("%s: rev30d %.0f vs %.0f" % (r["category"], r["rev30d"], now30))
    exp_mom = round(100.0 * (now30 - prev30) / prev30, 1) if prev30 > 0 else None
    if (exp_mom is None) != (r["mom_pct"] is None) or \
       (exp_mom is not None and abs(exp_mom - r["mom_pct"]) > 0.2):
        mom_bad += 1
        if len(examples) < 5:
            examples.append("%s: MoM %s vs %s" % (r["category"], r["mom_pct"], exp_mom))

    bins = {}
    for t, v in s:
        d = datetime.datetime.fromtimestamp(t, datetime.timezone.utc)
        bins.setdefault("%04d-%02d" % (d.year, d.month), []).append(v)
    for row in (r.get("monthly") or []):
        exp = sum(bins.get(row["m"]) or [])
        if abs(exp - row["v"]) > max(1.0, abs(exp) * 0.001):
            m_bad += 1
            break

print("  sektoru: %d" % len(SEC))
print("  neshod — rust: %d | rev30d: %d | MoM: %d | mesicni: %d"
      % (g_bad, rev_bad, mom_bad, m_bad))
for x in examples:
    print("      " + x)
for label, n in (("rust", g_bad), ("rev30d", rev_bad), ("MoM", mom_bad), ("mesicni kose", m_bad)):
    if n:
        FAILS.append("%d sektorovych hodnot '%s' nesedi na prepocet" % (n, label))


# ---------------------------------------------------------------- 2. shares
head("2. SEKTORY — podily musi dat 100 %, jejich zmeny 0 p.b.")
tot_share = sum(r["share_pct"] for r in SEC)
tot_delta = sum(r["share_d6m_pp"] for r in SEC)
print("  suma podilu:      %.2f %%   (ocekavano 100)" % tot_share)
print("  suma zmen podilu: %+.2f p.b. (ocekavano 0)" % tot_delta)
if abs(tot_share - 100) > 0.5:
    FAILS.append("podily sektoru davaji %.2f %% misto 100" % tot_share)
if abs(tot_delta) > 0.5:
    FAILS.append("zmeny podilu davaji %+.2f p.b. misto 0" % tot_delta)

# a sector that gained share must have grown faster than the market did
market_now = sum(r["rev30d"] for r in SEC)
market_then = sum(r["rev30d_6m_ago"] for r in SEC)
mkt = market_now / market_then if market_then else None
wrong = 0
for r in SEC:
    if not r["rev30d_6m_ago"]:
        continue
    own = r["rev30d"] / r["rev30d_6m_ago"]
    if (own > mkt) != (r["share_d6m_pp"] > 0) and abs(r["share_d6m_pp"]) > 0.01:
        wrong += 1
print("  trh za 6 M: x%.3f | sektoru, kde znamenko zmeny podilu neodpovida: %d" % (mkt or 0, wrong))
if wrong:
    FAILS.append("%d sektoru ma zmenu podilu s opacnym znamenkem, nez odpovida jejich rustu" % wrong)


# ---------------------------------------------------------------- 3. universe
head("3. SEKTORY — universum a vyloucene kategorie")
print("  clenu celkem: %d | s tokenem: %d"
      % (sum(r["n_all"] for r in SEC), sum(r["n_tok"] for r in SEC)))
bad_n = [r["category"] for r in SEC if r["n_tok"] > r["n_all"]]
if bad_n:
    FAILS.append("n_tok > n_all u: %s" % ", ".join(bad_n))
if any(r["category"] == "Stablecoin Issuer" for r in SEC):
    FAILS.append("Stablecoin Issuer je v sektorech — Tether a Circle prebiji kazdy podil")
else:
    print("  Stablecoin Issuer spravne vynechan")
privacy = [r for r in SEC if r["category"] == "Privacy"]
print("  Privacy pritomne: %s" % (("ano, $%.0fK/30d, oznaceno jako maly=%s"
      % (privacy[0]["rev30d"] / 1e3, privacy[0]["small"])) if privacy else "NE"))
if not privacy:
    WARNS.append("Privacy chybi v sektorech")
small = [r for r in SEC if r["small"]]
print("  malych sektoru (<$1M/30d): %d z %d — zobrazuji se, jen ztlumene" % (len(small), len(SEC)))


# ---------------------------------------------------------------- 4. chain layers
head("4. CHAINY — L1 vs L2 agregace")
by_cat = {}
for c in CHAINS:
    by_cat.setdefault(c.get("category") or "Other", []).append(c)
n_bad = 0
for r in SEC_CHAINS:
    ents = by_cat.get(r["category"], [])
    if r["n"] != len(ents):
        n_bad += 1
        print("  %s: n=%d vs %d clenu" % (r["category"], r["n"], len(ents)))
print("  vrstev: %d | neshod v poctu clenu: %d" % (len(SEC_CHAINS), n_bad))
if n_bad:
    FAILS.append("%d vrstev ma spatny pocet chainu" % n_bad)
worst = max((r.get("size_365") or 0) for r in SEC_CHAINS) if SEC_CHAINS else 0
print("  nejvetsi size_365: %.0f (%s)" % (worst, "realne" if worst < 1e13 else "NEREALNE — soucet stavu"))
if worst >= 1e13:
    FAILS.append("size_365 vypada jako soucet denniho TVL, ne prumer")


# ---------------------------------------------------------------- 5. themes
# A SECOND implementation of themes.py — deliberately not imported, so a bug in
# one shared helper cannot cancel itself out and pass on wrong numbers.
THEMES_D = D.get("themes") or []
TP = D.get("theme_prices") or {}
ALT = D.get("altseason") or {}
GRID = TP.get("coins") or {}
LIVE = TP.get("live") or {}
STAMPS = TP.get("stamps") or []
NS = len(STAMPS)
LN4 = math.log(4)


def a_simple_returns(p):
    r = [None] * len(p)
    first = next((k for k, v in enumerate(p) if v), None)
    if first is None:
        return r
    skip = first + 2 if first > 0 else 0
    for k in range(1, len(p)):
        if p[k] and p[k - 1] and k > skip:
            r[k] = p[k] / p[k - 1] - 1
    return r


def a_basket(rets, weights, clip=False):
    n = len(rets)
    need = max(3, (n + 1) // 2)
    out = [None] * NS
    for k in range(NS):
        num = den = 0.0
        cnt = 0
        for w, r in zip(weights, rets):
            x = r[k]
            if x is None:
                continue
            if clip:
                x = math.exp(max(-LN4, min(LN4, math.log(1 + x)))) - 1
            num += w * x
            den += w
            cnt += 1
        if cnt >= need:
            out[k] = num / den
    return out


def a_regress(xs, ys):
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    b = sxy / sxx
    rho = sxy / math.sqrt(sxx * syy)
    se = math.sqrt(syy / sxx) * math.sqrt(max(0.0, 1 - rho * rho) / (n - 2))
    return b, rho, se, n


head("5. TEMATA — 11 radku, krizova mapa kategorii")
print("  temat: %d" % len(THEMES_D))
if not THEMES_D:
    FAILS.append("snapshot nema zadna temata")
if len(THEMES_D) > 12:
    WARNS.append("%d temat — Adam chtel kolem deseti" % len(THEMES_D))
cat_owner, bad_map = {}, []
sec_by = {r["category"]: r for r in SEC}
for th in THEMES_D:
    f = th.get("fundament") or {}
    for c in f.get("missing") or []:
        FAILS.append("tema %s: kategorie DeFiLlamy '%s' v datech neexistuje (tise by pricitala nulu)" % (th["name"], c))
    for c in f.get("below_floor") or []:
        print("  %-22s kategorie '%s' tento mesic pod prahem $10K/30d — prispiva legitimne nulou"
              % (th["name"][:21], c))
    for c in f.get("categories") or []:
        if c in cat_owner:
            bad_map.append("%s v %s i %s" % (c, cat_owner[c], th["name"]))
        cat_owner[c] = th["name"]
    if f.get("kind") == "revenue" and f.get("categories"):
        exp = sum(sec_by[c]["rev30d"] for c in f["categories"] if c in sec_by)
        if abs(exp - (f.get("rev30d") or 0)) > max(1.0, exp * 1e-6):
            FAILS.append("tema %s: revenue %.0f != soucet kategorii %.0f" % (th["name"], f.get("rev30d") or 0, exp))
if bad_map:
    FAILS.append("kategorie ve dvou tematech (revenue by se pocitalo dvakrat): " + "; ".join(bad_map))
else:
    print("  kazda kategorie DeFiLlamy patri nejvys jednomu tematu, revenue = soucet kategorii")

head("6. TEMATA — beta, korelace, chyba odhadu (druha implementace)")
if len(STAMPS) >= 2:
    gaps = {STAMPS[i + 1] - STAMPS[i] for i in range(len(STAMPS) - 1)}
    if gaps != {7 * DAY}:
        FAILS.append("razitka nejsou po 7 dnech: %s" % sorted(gaps)[:4])
    else:
        print("  %d razitek, rozestup presne 7 dni" % len(STAMPS))
rb = a_simple_returns(GRID.get("bitcoin") or [None] * NS)
beta_bad = tier_bad = w_bad = 0
for th in THEMES_D:
    if th.get("status") != "ok":
        print("  %-22s status %s — beta se nepocita" % (th["name"][:21], th.get("status")))
        continue
    # beta is measured on the basket AS IT STOOD a year ago (no look-ahead), so
    # that is the basket to rebuild — not today's display members
    mem = th.get("beta_members") or []
    if not mem:
        FAILS.append("tema %s: chybi beta_members" % th["name"])
        continue
    ws = [m["w"] for m in mem]
    if abs(sum(ws) - 1) > 1e-3:
        w_bad += 1
    if max(ws) > 0.25 + 1e-3:
        FAILS.append("tema %s: vaha coinu %.3f nad stropem 25 %%" % (th["name"], max(ws)))
    no_start = [m["id"] for m in mem if not (GRID.get(m["id"]) or [None])[0]]
    if no_start:
        FAILS.append("tema %s: clen beta kose bez ceny na zacatku roku: %s" % (th["name"], ", ".join(no_start[:4])))
    # weights must be sqrt of the mcap they had AT THE START, capped at 25 %
    mc0 = []
    for m in mem:
        row = GRID.get(m["id"]) or []
        now_p = LIVE.get(m["id"]) or (row[-1] if row else None)
        mc0.append((m.get("mcap") or 0) * row[0] / now_p if (row and row[0] and now_p) else 0)
    sw = [math.sqrt(max(x, 0)) for x in mc0]
    tot = sum(sw) or 1
    exp_w = [x / tot for x in sw]
    for _ in range(60):
        over = [i for i, x in enumerate(exp_w) if x > 0.25 + 1e-12]
        if not over:
            break
        ex = sum(exp_w[i] - 0.25 for i in over)
        for i in over:
            exp_w[i] = 0.25
        free = [i for i, x in enumerate(exp_w) if x < 0.25 - 1e-12]
        fs = sum(exp_w[i] for i in free)
        if fs <= 0:
            break
        for i in free:
            exp_w[i] += ex * exp_w[i] / fs
    tot = sum(exp_w) or 1
    exp_w = [x / tot for x in exp_w]
    if any(abs(a - b) > 1e-4 for a, b in zip(exp_w, ws)):
        FAILS.append("tema %s: vahy beta kose neodpovidaji sqrt(mcap na zacatku roku)" % th["name"])
    rets = [a_simple_returns(GRID.get(m["id"]) or [None] * NS) for m in mem]
    rt = a_basket(rets, ws, clip=True)
    wk = [k for k in range(1, NS) if rt[k] is not None and rb[k] is not None]
    if len(wk) < 30:
        FAILS.append("tema %s: jen %d tydnu bety" % (th["name"], len(wk)))
        continue
    b, rho, se, n = a_regress([rb[k] for k in wk], [rt[k] for k in wk])
    ok = (abs(b - th["beta"]) <= 1e-3 and abs(rho - th["rho"]) <= 1e-3
          and abs(se - th["beta_se"]) <= 1e-3 and n == th["n_weeks"])
    if not ok:
        beta_bad += 1
        print("  MISMATCH %-20s beta %.4f vs %.4f  rho %.4f vs %.4f  se %.4f vs %.4f  n %d vs %d"
              % (th["name"][:19], th["beta"], b, th["rho"], rho, th["beta_se"], se, th["n_weeks"], n))
    # tier from the stored numbers, by the confidence rule
    exp_tier = 5 if b - se >= 1.15 else (1 if b + se < 0.95 else 3)
    if exp_tier != th.get("tier"):
        tier_bad += 1
    print("  %-22s beta %.2f ±%.2f  rho %.2f  n=%d  tier %s" % (th["name"][:21], b, se, rho, n, th.get("tier")))
if beta_bad:
    FAILS.append("%d temat ma betu/korelaci/SE, ktera nesedi na prepocet" % beta_bad)
if tier_bad:
    FAILS.append("%d temat ma pasmo, ktere neodpovida pravidlu beta±SE" % tier_bad)
if w_bad:
    FAILS.append("%d temat ma vahy, ktere nedavaji 1" % w_bad)

head("7. TEMATA — relativni sila vs BTC (kos ze zacatku okna)")
btc_row = GRID.get("bitcoin") or []
btc_live = (LIVE["bitcoin"] / btc_row[-1] - 1) if (LIVE.get("bitcoin") and btc_row and btc_row[-1]) else None
rs_bad = 0
for th in THEMES_D:
    for W, lbl in ((4, "1m"), (13, "3m")):
        rsm = th.get("rs_members_" + lbl) or []
        if not rsm or th.get("rs" + lbl) is None:
            continue
        k0 = NS - 1 - W
        ids = [m["id"] for m in rsm]
        ws = [m["w"] for m in rsm]
        br = a_basket([a_simple_returns(GRID.get(g) or [None] * NS) for g in ids], ws)
        acc = sum(math.log(1 + br[k]) for k in range(k0 + 1, NS) if br[k] is not None)
        bacc = sum(math.log(1 + rb[k]) for k in range(k0 + 1, NS) if rb[k] is not None)
        lp = [(w, LIVE[g] / GRID[g][-1] - 1) for g, w in zip(ids, ws)
              if LIVE.get(g) and GRID.get(g) and GRID[g][-1]]
        if lp:
            acc += math.log(1 + sum(w * x for w, x in lp) / sum(w for w, _ in lp))
            if btc_live is not None:
                bacc += math.log(1 + btc_live)
        mine = math.exp(acc - bacc) - 1
        if abs(mine - th["rs" + lbl]) > 1e-3:
            rs_bad += 1
            print("  MISMATCH %-20s rs%s %.4f vs %.4f" % (th["name"][:19], lbl, th["rs" + lbl], mine))
    # how much picking TODAY's winners would flatter the quarter
    if th.get("status") == "ok" and th.get("rs3m") is not None:
        k0 = NS - 1 - 13
        mem = th.get("members") or []
        br = a_basket([a_simple_returns(GRID.get(m["id"]) or [None] * NS) for m in mem], [m["w"] for m in mem])
        acc = sum(math.log(1 + br[k]) for k in range(k0 + 1, NS) if br[k] is not None)
        bacc = sum(math.log(1 + rb[k]) for k in range(k0 + 1, NS) if rb[k] is not None)
        today = math.exp(acc - bacc) - 1
        gap = 100 * (today - th["rs3m"])
        print("  %-22s rs1m %+6.1f %%  rs3m %+6.1f %%  | dnesni kos by dal %+6.1f %% (zkresleni %+5.1f p.b.)"
              % (th["name"][:21], 100 * (th.get("rs1m") or 0), 100 * th["rs3m"], 100 * today, gap))
        if abs(gap) > 15:
            WARNS.append("tema %s: vyber dnesnich viteztu by ctvrtleti zkreslil o %+.0f p.b." % (th["name"], gap))
if rs_bad:
    FAILS.append("%d hodnot relativni sily nesedi na prepocet" % rs_bad)

head("8. ALTSEASON INDEX — prepocitany z ulozene mrizky")
uni = ALT.get("universe") or []
print("  univerzum %d altu (BTC venku: %s, ETH uvnitr: %s)"
      % (len(uni), "bitcoin" not in uni, "ethereum" in uni))
if "bitcoin" in uni:
    FAILS.append("BTC je v univerzu altseason indexu")
if "ethereum" not in uni:
    FAILS.append("ETH chybi v univerzu altseason indexu (konvence Blockchaincenter ho pocita)")
hist = ALT.get("history") or []
mcap_now = {}
for th in THEMES_D:
    for m in th.get("members") or []:
        mcap_now[m["id"]] = m.get("mcap") or 0
idx_bad = 0
# the ranking inside each history point needs every coin's mcap; the audit only
# has members' mcaps, so it verifies the COUNT logic on the stored top-50 of the
# latest point and the header identity
if hist:
    if abs(hist[-1][1] - (ALT.get("index") or -1)) > 1e-9:
        FAILS.append("posledni bod historie (%.1f) != cislo v pasu (%s)" % (hist[-1][1], ALT.get("index")))
    else:
        print("  posledni bod historie = cislo v pasu: %.1f %%" % hist[-1][1])
    print("  historie: %d bodu, rozsah %.0f–%.0f %%" % (len(hist), min(h[1] for h in hist), max(h[1] for h in hist)))
    if len(hist) < 30:
        WARNS.append("altseason historie ma jen %d bodu" % len(hist))
    if any(h[2] != 50 for h in hist):
        WARNS.append("nektery bod historie ma mene nez 50 altu: %s" % sorted({h[2] for h in hist}))
    # every history point re-ranked and re-counted from the stored grid
    umc = ALT.get("universe_mcap") or {}
    if not umc:
        WARNS.append("snapshot nema universe_mcap — index nejde prepocitat, jen zkontrolovat")
    else:
        by_t = {h[0]: h for h in hist}
        mine_pts = 0
        for j in range(13, NS):
            if not (btc_row[j] and btc_row[j - 13]):
                continue
            pool = [g for g in uni if GRID.get(g) and GRID[g][j] and GRID[g][j - 13]]
            pool.sort(key=lambda g: -((umc.get(g) or 0) * GRID[g][j]
                                      / (LIVE.get(g) or GRID[g][-1] or GRID[g][j])))
            pool = pool[:50]
            if len(pool) < 30:
                continue
            b = btc_row[j] / btc_row[j - 13]
            pct = round(100.0 * sum(1 for g in pool if GRID[g][j] / GRID[g][j - 13] > b) / len(pool), 1)
            mine_pts += 1
            st = by_t.get(STAMPS[j])
            if not st or abs(st[1] - pct) > 1e-9:
                idx_bad += 1
                if idx_bad <= 3:
                    print("  MISMATCH %s ulozeno %s, prepocet %.1f" % (STAMPS[j], st[1] if st else None, pct))
        print("  prepocitano %d bodu historie, neshod %d" % (mine_pts, idx_bad))
        if mine_pts != len(hist):
            FAILS.append("historie ma %d bodu, prepocet %d" % (len(hist), mine_pts))
        if idx_bad:
            FAILS.append("%d bodu altseason historie nesedi na prepocet" % idx_bad)

head("9. TEMATA — znacky z ulozenych cisel")
tag_bad = 0
for th in THEMES_D:
    exp = set()
    if th.get("status") == "ok":
        if th.get("z1") is not None and th["z1"] >= 1.5 and th.get("beat_median_alt_1m"):
            exp.add("leads")
        if th.get("tier") == 5 and th.get("z3") is not None and th["z3"] <= 0.5:
            exp.add("waiting")
        if th.get("rho") is not None and th["rho"] < 0.5:
            exp.add("own_story")
    f = th.get("fundament") or {}
    if (f.get("kind") == "revenue" and not f.get("small") and (f.get("g6m") or 0) >= 5
            and (f.get("r2") or 0) >= 0.25):
        exp.add("fund_up")
    if exp != set(th.get("tags") or []):
        tag_bad += 1
        print("  MISMATCH %-20s ulozeno %s, pravidla davaji %s" % (th["name"][:19], sorted(th.get("tags") or []), sorted(exp)))
    # the z-scores themselves
    te = th.get("te_week")
    if te and th.get("rs1m") is not None and th.get("z1") is not None:
        if abs(math.log(1 + th["rs1m"]) / (2 * te) - th["z1"]) > 1e-2:
            tag_bad += 1
            print("  MISMATCH %-20s z1" % th["name"][:19])
if tag_bad:
    FAILS.append("%d temat ma znacky nebo z-skore, ktere neodpovidaji pravidlum" % tag_bad)
else:
    print("  znacky vsech temat odpovidaji pravidlum")

head("10. TEMATA — anomalie, prekryvy, zalohy")
anoms = D.get("theme_anomalies") or []
print("  anomalie v cenach: %d" % len(anoms))
for a in anoms[:10]:
    print("      %-24s %-6s tyden %2d  skok %+.2f (x%.1f)" % (a["id"][:23], a["kind"], a["k"], a["jump"], math.exp(abs(a["jump"]))))
for th in THEMES_D:
    if th.get("shared_with"):
        print("  %-22s sdili: %s" % (th["name"][:21], ", ".join("%s (%d)" % (s["name"], s["n"]) for s in th["shared_with"])))
    if th.get("basket_source") in ("seed", "snapshot", "unavailable"):
        WARNS.append("tema %s bezi na zaloze: %s" % (th["name"], th.get("basket_source")))
    if th.get("n", 0) < 5 and th.get("status") == "ok":
        FAILS.append("tema %s je 'ok' s mene nez 5 cleny" % th["name"])
if D.get("themes_stale"):
    WARNS.append("temata jsou z minuleho behu (tentokrat selhala)")


head("11. TEMATA — trzni pole clenu (jen z ziveho volani) a tema na radcich")
MKT_KEYS = ("chg7d", "chg30d", "vol24h", "ath_chg_pct")
mem_all = [m for th in THEMES_D for m in th.get("members") or []]
no_keys = [m["id"] for m in mem_all if any(k not in m for k in MKT_KEYS)]
with_vol = [m for m in mem_all if m.get("vol24h") is not None]
live_mem = [m for m in mem_all if m["id"] in LIVE]
print("  clenu kosu: %d | s obratem: %d | s zivou cenou: %d" % (len(mem_all), len(with_vol), len(live_mem)))
if no_keys:
    FAILS.append("%d clenu kosu nema trzni pole (%s)" % (len(no_keys), ", ".join(no_keys[:4])))
if live_mem and len(with_vol) < 0.9 * len(live_mem):
    WARNS.append("obrat ma jen %d z %d clenu s zivou cenou" % (len(with_vol), len(live_mem)))
# a value without a live price can only have come from somewhere stale
stale_vals = [m["id"] for m in with_vol if m["id"] not in LIVE]
if stale_vals:
    WARNS.append("%d clenu ma obrat bez zive ceny: %s" % (len(stale_vals), ", ".join(stale_vals[:4])))
rows = D.get("apps", []) + CHAINS
flag_bad = [e["name"] for e in rows if e.get("theme")
            and bool(e["theme"].get("stale")) != bool(D.get("themes_stale"))]
print("  radku s tematem: %d | priznak 'z minuleho behu' nesedi: %d"
      % (sum(1 for e in rows if e.get("theme")), len(flag_bad)))
if flag_bad:
    FAILS.append("%d radku ma spatny priznak stale u tematu: %s" % (len(flag_bad), ", ".join(flag_bad[:4])))


head("VERDIKT")
if FAILS:
    print("CHYBY (%d):" % len(FAILS))
    for f in FAILS:
        print("  X " + f)
else:
    print("sektory i temata sedi na nezavisly prepocet")
if WARNS:
    print("\nVAROVANI:")
    for w in WARNS:
        print("  ! " + w)
# a hard failure must fail the process too, not just print — like audit_static.js
raise SystemExit(1 if FAILS else 0)
