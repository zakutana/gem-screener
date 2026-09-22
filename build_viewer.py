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
# Same trick for the language a first-time viewer gets. The published artifact
# is for an international audience, so the static build defaults to English;
# app.py (Adam's exe) keeps Czech. #en / #cs and a saved choice still win.
LANG_TOKEN = "/*__LANG__*/'cs'"
STATIC_LANG = "en"
# ...and the tab it opens on: Apps for the artifact, Start for app.py.
VIEW_TOKEN = "/*__VIEW__*/'start'"
STATIC_VIEW = "apps"
VIEWS = ("start", "apps", "chains", "sectors")


def inject(tpl, snap_text, served=False, lang="cs", view="start"):
    """Put the snapshot, the app-mode flag, the default language and the
    opening tab into the template.

    Every placeholder is required: a silent no-op replace would produce a page
    with an empty data block that only fails in the browser."""
    for token in (SNAPSHOT_TOKEN, SERVED_TOKEN, LANG_TOKEN, VIEW_TOKEN):
        if token not in tpl:
            raise ValueError("template is missing %s" % token)
    if lang not in ("cs", "en"):
        raise ValueError("unknown language %r" % lang)
    if view not in VIEWS:
        raise ValueError("unknown view %r" % view)
    # A literal "</script" anywhere in the JSON would close the data block early.
    safe = snap_text.replace("</script", "<\\/script")
    out = tpl.replace(SNAPSHOT_TOKEN, safe)
    out = out.replace(LANG_TOKEN, "'%s'" % lang).replace(VIEW_TOKEN, "'%s'" % view)
    return out.replace(SERVED_TOKEN, "true" if served else "false")


def read_text(path):
    return io.open(path, encoding="utf-8").read()


def main(data_dir=None, lang=STATIC_LANG, view=STATIC_VIEW):
    d = data_dir or os.getcwd()
    tpl = read_text(os.path.join(d, "template.html"))
    snap = read_text(os.path.join(d, "snapshot.json"))
    out_path = os.path.join(d, "gem_screener.html")
    io.open(out_path, "w", encoding="utf-8").write(
        inject(tpl, snap, served=False, lang=lang, view=view))
    print("wrote gem_screener.html (%.0f KB, language %s, opens on %s)"
          % (os.path.getsize(out_path) / 1024, lang, view))


def _opt(args, name, default):
    if name in args:
        i = args.index(name)
        val = args[i + 1] if i + 1 < len(args) else default
        del args[i:i + 2]
        return val
    return default


if __name__ == "__main__":
    # python build_viewer.py [data_dir] [--lang cs|en] [--view start|apps|chains|sectors]
    args = sys.argv[1:]
    lang = _opt(args, "--lang", STATIC_LANG)
    view = _opt(args, "--view", STATIC_VIEW)
    main(args[0] if args else None, lang=lang, view=view)
