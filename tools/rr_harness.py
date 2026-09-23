"""Record/replay harness: run two collector versions on byte-identical inputs.

    python tools/rr_harness.py record <code_dir> <data_dir> <store.sqlite> <time_file>
    python tools/rr_harness.py replay <code_dir> <data_dir> <store.sqlite> <time_file> [--shim]

The equivalence proof for a refactor (ARCHITECTURE.md §18.3):

    1. copy the old code (git show HEAD:<file>) and the new code into two dirs,
       and seed three data dirs with the same snapshot.json + caches
    2. record ONE live run of the new code          (network, ~5-10 min)
    3. replay the old code and the new code on it   (no network, seconds)
    4. python tools/compare_snap.py old/snapshot.json new/snapshot.json
       -> every difference must be one you planned

`generated_at_iso` uses the wall clock (gmtime) and always differs. Seed the
OLD run's baskets_cache.json with a foreign "version" when the new code changes
THEMES — both then rebuild their baskets from the same recorded responses.

record  runs the collector in <code_dir> live, stores every HTTP response
        (last success per URL wins) and freezes time.time() at one instant,
        written to <time_file>.
        A URL already in the store is served from it (record-through), so a
        crashed run can be resumed without hitting the APIs again.
replay  serves every request from the store, never touches the network,
        freezes time.time() at the SAME instant and makes time.sleep a no-op.
        A request that is not in the store is a miss: it fails like a network
        error and is listed at the end.
--shim  (replay only) answers two kinds of misses from recorded per-coin data
        instead of failing them. Both endpoints take a LIST of coins and are
        chunked by the caller, so a version that prices a different coin set
        (a new theme adds candidates) asks for different chunks:
          CoinGecko /coins/markets?ids=…   -> the recorded object of each id
                                              (the latest recording wins)
          coins.llama.fi /batchHistorical  -> each coin's recorded price list
                                              for the same stamps + searchWidth

URL keys are normalised: CoinGecko's &price_change_percentage=… only ADDS fields
to /coins/markets, so the old code (without it) and the new code (with it) are
served the same recorded response.
"""
import json
import os
import re
import sqlite3
import sys
import threading
import time
import urllib.parse
import zlib

mode, code_dir, data_dir, store, tfile = sys.argv[1:6]
SHIM = "--shim" in sys.argv[6:]
sys.path.insert(0, os.path.abspath(code_dir))

import requests                                           # noqa: E402
from requests.structures import CaseInsensitiveDict       # noqa: E402

NORM = [re.compile(r"&price_change_percentage=[^&]*")]


def norm(url):
    for rx in NORM:
        url = rx.sub("", url)
    return url


LOCK = threading.Lock()
DB = sqlite3.connect(store, check_same_thread=False)
DB.execute("create table if not exists r (k text primary key, status int, ctype text,"
           " retry text, body blob, url text)")
DB.commit()
MISSES = []
STATS = {"live": 0, "cached": 0, "shimmed": 0}
_real_get = requests.Session.get


def _row(k):
    with LOCK:
        return DB.execute("select status, ctype, retry, body from r where k=?", (k,)).fetchone()


def _response(url, row):
    status, ctype, retry, body = row
    resp = requests.Response()
    resp.status_code = status
    resp._content = zlib.decompress(body) if body else b""
    resp.headers = CaseInsensitiveDict({"Content-Type": ctype or "application/json"})
    if retry:
        resp.headers["Retry-After"] = retry
    resp.url = url
    resp.encoding = None
    return resp


def record_get(self, url, *a, **kw):
    k = norm(url)
    row = _row(k)
    # record-through: a stored SUCCESS is reused, anything else is fetched again
    if row is not None and row[0] == 200:
        STATS["cached"] += 1
        return _response(url, row)
    STATS["live"] += 1
    r = _real_get(self, url, *a, **kw)
    with LOCK:
        prev = DB.execute("select status from r where k=?", (k,)).fetchone()
        if r.status_code == 200 or not prev or prev[0] != 200:
            DB.execute("insert or replace into r values (?,?,?,?,?,?)",
                       (k, r.status_code, r.headers.get("Content-Type"),
                        r.headers.get("Retry-After"), zlib.compress(r.content), url))
            DB.commit()
    return r


# ------------------------------------------------------------------ the shim
_IDX = {}


def _index():
    """Per-coin views of every recorded id-list response, built once."""
    if _IDX:
        return _IDX
    markets, hist = {}, {}
    with LOCK:
        rows = DB.execute("select k, status, body from r order by rowid").fetchall()
    for k, status, body in rows:
        if status != 200 or not body:
            continue
        if "api.coingecko.com" in k and "/coins/markets?" in k and "ids=" in k:
            try:
                for c in json.loads(zlib.decompress(body)):
                    if c.get("id"):
                        markets[c["id"]] = c          # rowid order: the latest recording wins
            except Exception:
                pass
        elif "coins.llama.fi/batchHistorical?" in k:
            sig = _hist_sig(k)
            if sig is None:
                continue
            try:
                d = json.loads(zlib.decompress(body))
            except Exception:
                continue
            bucket = hist.setdefault(sig[0], {})
            for key, v in (d.get("coins") or {}).items():
                bucket[key] = v
    _IDX.update({"markets": markets, "hist": hist})
    return _IDX


def _hist_sig(url):
    """(stamps + searchWidth, requested coin keys) of a batchHistorical URL."""
    q = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
    try:
        coins = json.loads(q["coins"][0])
    except Exception:
        return None
    stamps = {json.dumps(v) for v in coins.values()}
    if len(stamps) != 1:
        return None
    return (stamps.pop(), (q.get("searchWidth") or [""])[0]), list(coins)


def _synth(url):
    """A 200 body for a chunk nobody recorded, or None."""
    if "api.coingecko.com" in url and "/coins/markets?" in url and "ids=" in url:
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        ids = [x for x in (q.get("ids") or [""])[0].split(",") if x]
        m = _index()["markets"]
        out = [m[g] for g in ids if g in m]
        out.sort(key=lambda c: -(c.get("market_cap") or 0))
        return json.dumps(out).encode("utf-8")
    if "coins.llama.fi/batchHistorical?" in url:
        sig = _hist_sig(url)
        if sig is None:
            return None
        bucket = _index()["hist"].get(sig[0]) or {}
        return json.dumps({"coins": {k: bucket[k] for k in sig[1] if k in bucket}}).encode("utf-8")
    return None


def replay_get(self, url, *a, **kw):
    row = _row(norm(url))
    if row is None and SHIM:
        body = _synth(url)
        if body is not None:
            STATS["shimmed"] += 1
            return _response(url, (200, "application/json", None, zlib.compress(body)))
    if row is None:
        MISSES.append(url)
        raise requests.exceptions.ConnectionError("replay miss: %s" % url[:200])
    STATS["cached"] += 1
    return _response(url, row)


if mode == "record":
    if os.path.exists(tfile):
        T = float(open(tfile).read().strip())
    else:
        T = float(int(time.time()))
        open(tfile, "w").write(str(T))
    requests.Session.get = record_get
elif mode == "replay":
    T = float(open(tfile).read().strip())
    requests.Session.get = replay_get
    time.sleep = lambda s: None
else:
    raise SystemExit("mode must be record or replay")

time.time = lambda: T

import collector                                          # noqa: E402

t0 = time.monotonic()
collector.run(data_dir=os.path.abspath(data_dir))
print("\n[harness] mode=%s code=%s T=%d live=%d cached=%d shimmed=%d misses=%d (%.0f s)"
      % (mode, code_dir, T, STATS["live"], STATS["cached"], STATS["shimmed"], len(MISSES),
         time.monotonic() - t0))
if MISSES:
    with open(os.path.join(data_dir, "replay_misses.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(MISSES))
    for u in MISSES[:15]:
        print("  MISS " + u[:180])
