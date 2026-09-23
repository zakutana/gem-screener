"""Compare two snapshots produced from identical inputs (see tools/rr_harness.py).

    python tools/compare_snap.py <old.json> <new.json>

Every key the OLD snapshot has must exist in the new one with the same value
(floats within 1e-9 relative — thread completion order changes summation
order). Keys only the new snapshot has are listed, generalised to a path
pattern. Lists whose order is thread-dependent are compared as keyed maps or
as multisets.
"""
import io
import json
import sys
from collections import Counter

old = json.load(io.open(sys.argv[1], encoding="utf-8"))
new = json.load(io.open(sys.argv[2], encoding="utf-8"))

DIFFS = []
NEW_KEYS = Counter()
KEYED = {  # path pattern -> key field of each element
    "apps": ("key", "slug", "name"), "chains": ("key", "slug", "name"),
    "sectors.apps": ("category",), "sectors.chains": ("category",),
    "themes": ("key",), "themes[*].members": ("id",),
}
MULTISET = {"fetch_warnings", "excluded.chains_no_token"}


def ident(e, fields):
    for f in fields:
        if isinstance(e, dict) and e.get(f) is not None:
            return str(e[f])
    return json.dumps(e, sort_keys=True)[:80]


def num_eq(a, b):
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    if isinstance(a, int) and isinstance(b, int):
        return a == b
    return abs(a - b) <= 1e-9 * max(1.0, abs(a), abs(b))


def cmp(a, b, path, pattern):
    if len(DIFFS) > 60:
        return
    if isinstance(a, dict):
        if not isinstance(b, dict):
            DIFFS.append("%s: dict -> %s" % (path, type(b).__name__))
            return
        for k in a:
            if k not in b:
                DIFFS.append("%s.%s: key missing in new" % (path, k))
            else:
                cmp(a[k], b[k], path + "." + k, (pattern + "." + k).lstrip("."))
        for k in b:
            if k not in a:
                NEW_KEYS[(pattern + "." + k).lstrip(".")] += 1
        return
    if isinstance(a, list):
        if not isinstance(b, list):
            DIFFS.append("%s: list -> %s" % (path, type(b).__name__))
            return
        pat = pattern.lstrip(".")
        if pat in MULTISET:
            ca = Counter(json.dumps(x, sort_keys=True) for x in a)
            cb = Counter(json.dumps(x, sort_keys=True) for x in b)
            if ca != cb:
                DIFFS.append("%s: multiset differs (%d vs %d items)" % (path, len(a), len(b)))
            return
        if pat in KEYED:
            fa = {ident(x, KEYED[pat]): x for x in a}
            fb = {ident(x, KEYED[pat]): x for x in b}
            for k in fa:
                if k not in fb:
                    DIFFS.append("%s[%s]: element missing in new" % (path, k))
                else:
                    cmp(fa[k], fb[k], "%s[%s]" % (path, k), pat + "[*]")
            for k in fb:
                if k not in fa:
                    DIFFS.append("%s[%s]: element only in new" % (path, k))
            return
        if len(a) != len(b):
            DIFFS.append("%s: length %d -> %d" % (path, len(a), len(b)))
            return
        for i, (x, y) in enumerate(zip(a, b)):
            cmp(x, y, "%s[%d]" % (path, i), pat + "[]")
        return
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        if not num_eq(a, b):
            DIFFS.append("%s: %r -> %r" % (path, a, b))
        return
    if a != b:
        DIFFS.append("%s: %r -> %r" % (path, str(a)[:80], str(b)[:80]))


cmp(old, new, "", "")
print("old apps %d chains %d | new apps %d chains %d"
      % (len(old["apps"]), len(old["chains"]), len(new["apps"]), len(new["chains"])))
print("\nDIFFERENCES IN EXISTING KEYS: %d" % len(DIFFS))
for d in DIFFS[:60]:
    print("  " + d)
print("\nNEW KEYS (pattern: occurrences):")
for k, n in sorted(NEW_KEYS.items()):
    print("  %-40s %d" % (k, n))
raise SystemExit(1 if DIFFS else 0)
