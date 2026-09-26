"""
Build cycle_history.json once — the long history the Altseason panel needs.

    python tools/cycle_seed.py            (run from the repository root)

~630 weekly CMC listings (paced, ~25 min), CMC daily global data, Coin Metrics
BTC and stablecoins, DeFiLlama's per-protocol fee breakdown (one 23 MB call),
Upbit weekly candles for every KRW market (~300-900 calls), Tranco monthly lists
since 2019-03. Resumable: raw listings are cached in cycle_cache/listings/ and the
history is saved after every step, so a rerun only fetches what is missing.
A collector Refresh never does this; it only adds the missing tail.
"""
import datetime
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import collector  # noqa: E402
import cycle      # noqa: E402


def main():
    data_dir = os.getcwd()
    ctx = collector.Ctx(log=print, data_dir=data_dir)
    now = int(time.time())
    H, from_bak = cycle.load_history(data_dir, ctx.log)
    if H is None:
        H = cycle.empty_history()
    loaded = len(H["weeks"])
    cache = os.path.join(data_dir, "cycle_cache", "listings")
    os.makedirs(cache, exist_ok=True)
    steps = sys.argv[1:] or ["global", "cm", "meme", "tranco", "upbit", "listings"]

    def save():
        cycle.save_history(data_dir, H, loaded)
        ctx.log("uloženo: %d týdnů" % len(H["weeks"]))

    if "global" in steps:
        cycle.update_global(ctx, H, now, ctx.log)
        save()
    if "cm" in steps:
        cycle.update_coinmetrics(ctx, H, now, ctx.log)
        save()
    if "meme" in steps:
        bd = ctx.get("https://api.llama.fi/overview/fees?dataType=dailyRevenue"
                     "&excludeTotalDataChart=true&excludeTotalDataChartBreakdown=false", timeout=180)
        n = cycle.update_meme(ctx, H, now, ctx.log, breakdown=bd)
        ctx.log("memecoinová ekonomika: %d dní" % n)
        save()
    if "tranco" in steps:
        months = []
        d = datetime.date(2019, 3, 1)
        today = datetime.date.today()
        while d < today.replace(day=1):
            months.append(d.strftime("%Y-%m"))
            d = (d.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)
        cycle.update_tranco(ctx, H, now, ctx.log, months=months)
        ctx.log("Tranco: %d měsíců" % len(H["tranco"]["monthly"]))
        save()
    if "upbit" in steps:
        cycle.update_upbit(ctx, H, now, ctx.log, full=True)
        save()
    if "rebuild" in steps:
        cycle.rebuild_from_cache(H, cache, ctx.log)
        for back in (1, 2):
            rows = cycle.fetch_listing(ctx, cycle.iso(cycle.day0(now) - back * cycle.DAY), warn=False)
            rec = cycle.summarize_listing(rows) if rows else None
            if rec:
                H["latest"] = {"day": cycle.day0(now) - back * cycle.DAY, "od": rec["od"], "ou": rec["ou"]}
                break
        save()
    if "listings" in steps:
        # in chunks, saving between them: 600+ paced calls must survive an interruption
        while True:
            n = cycle.update_listings(ctx, H, now, ctx.log, max_new=40, cache_dir=cache)
            save()
            missing = [w for w in cycle.week_axis(now) if "od" not in H["weeks"].get(str(w), {})]
            ctx.log("chybí týdnů: %d" % len(missing))
            if not n or not missing:
                break
    if ctx.warnings:
        ctx.log("varování: %d (prvních 10 níže)" % len(ctx.warnings))
        for w in ctx.warnings[:10]:
            ctx.log("  " + w)


if __name__ == "__main__":
    main()
