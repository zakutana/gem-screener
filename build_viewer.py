"""
Rebuilds gem_screener.html from the current template.html + snapshot.json.
Run this AFTER collector.py has produced a fresh snapshot.json.

    python collector.py       # ~3 min, hits DeFiLlama + CoinGecko
    python build_viewer.py    # instant, just re-embeds the JSON

The resulting gem_screener.html is the STATIC build (published as an Artifact).
app.py serves the same template with served=True so the page shows its Refresh
button; the static build leaves it off, because a published artifact has no
server to refresh against.
"""
import io
import os
import sys

SNAPSHOT_TOKEN = "/*__SNAPSHOT_JSON__*/"
# The token swallows its own default, so the raw template is valid JS on its own
# (`= /*__SERVED__*/false;` -> false) and a replacement yields `= true;` rather
# than the `= falsefalse;` you get from replacing only the comment.
SERVED_TOKEN = "/*__SERVED__*/false"


def inject(tpl, snap_text, served=False):
    """Put the snapshot (and the app-mode flag) into the template.

    Both placeholders are required: a silent no-op replace would produce a page
    with an empty data block that only fails in the browser."""
    if SNAPSHOT_TOKEN not in tpl:
        raise ValueError("template is missing %s" % SNAPSHOT_TOKEN)
    if SERVED_TOKEN not in tpl:
        raise ValueError("template is missing %s" % SERVED_TOKEN)
    # A literal "</script" anywhere in the JSON would close the data block early.
    safe = snap_text.replace("</script", "<\\/script")
    out = tpl.replace(SNAPSHOT_TOKEN, safe)
    return out.replace(SERVED_TOKEN, "true" if served else "false")


def read_text(path):
    return io.open(path, encoding="utf-8").read()


def main(data_dir=None):
    d = data_dir or os.getcwd()
    tpl = read_text(os.path.join(d, "template.html"))
    snap = read_text(os.path.join(d, "snapshot.json"))
    out_path = os.path.join(d, "gem_screener.html")
    io.open(out_path, "w", encoding="utf-8").write(inject(tpl, snap, served=False))
    print("wrote gem_screener.html (%.0f KB)" % (os.path.getsize(out_path) / 1024))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
