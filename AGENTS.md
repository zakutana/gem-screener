# AGENTS.md — working on Gem Screener

Instructions for coding agents (Codex, Cursor, Gemini, Claude Code via
`CLAUDE.md`) and for humans who want the short version. The full specification
is [ARCHITECTURE.md](ARCHITECTURE.md): read §3 (overview), §14 (the snapshot
contract) and §20 (traps) before changing anything.

## Setup

- Python 3.13 and `pip install -r requirements.txt` (only `requests`); Node 22 for
  `audit_static.js` (no packages).
- **Run everything from the repository root** — the collector, the audits and the
  page builder read and write files relative to the working directory.
- Optional `COINGECKO_DEMO_KEY` (free CoinGecko demo key) to reduce 429s.
- Console output is partly Czech: set `PYTHONIOENCODING=utf-8` on non-UTF-8 consoles.

## Commands

| Task | Command | Notes |
|---|---|---|
| Collect data | `python collector.py` | 3–6 min; writes `snapshot.json`, caches, one ledger line |
| Audits (acceptance tests) | `python audit.py` · `python audit_sectors.py` · `node audit_static.js` | exit 1 on a hard failure — judge by exit code |
| Build the static page | `python build_viewer.py [--lang cs\|en] [--view start\|apps\|chains\|sectors]` | → `gem_screener.html` (default EN + Apps) |
| Local app | `python app.py` | 127.0.0.1:8765, Czech + Start, Refresh button |
| Second instance for testing | `GEM_PORT=8790 GEM_NO_BROWSER=1 python app.py` | leaves a running copy on 8765 alone |
| Backtest | `python backtest.py` · `python backtest.py --selftest` | offline; see ARCHITECTURE §17 first |
| Windows exe | `build_exe.bat` | PyInstaller one-file; bundles `template.html` |
| Equivalence proof | `python tools/rr_harness.py record\|replay …` + `python tools/compare_snap.py` | ARCHITECTURE §18.3 |

## Definition of done

1. `python collector.py` on the changed code, then **all three audits exit 0**.
2. Logic changes: a record/replay diff (`tools/`) in which every difference is
   one you planned — say what changed and why in the commit or PR.
3. UI changes: checked in the browser in **Czech and English**, desktop and phone
   width. Verify layout by DOM measurement; screenshots under viewport emulation
   can come out black.
4. `ARCHITECTURE.md` updated. Audit §36 fails if a snapshot key is undocumented.
5. No secrets in the diff.

## Conventions

**Collector (Python)**
- All HTTP goes through `Ctx.get` (DeFiLlama, DexScreener, datasets, logos) or
  `themes.cg_get` (CoinGecko: one call at a time, 6 s pacing). Never call
  `requests` directly.
- Every final failure becomes `ctx.warn(...)` — it ends up in `fetch_warnings`
  and the page header. Silent `None` has lost data before.
- No module-level mutable state; everything per run lives on `Ctx`
  (`app.py` calls `collector.run()` repeatedly in one process).
- Decisions are made in Python and **stored on the row** (`reliable_fail`,
  `degen_fail`, `risks`, `theme.source`, …). The viewer renders, never re-decides.
- Every new stored number gets a second implementation in `audit.py`.
- Caches: atomic writes (tmp + `os.replace`), and a failed refresh keeps the old
  entry ("stale beats empty").
- Comments explain *why*, with the concrete case that forced the rule.

**Viewer (`template.html`)**
- One file, no framework, no build step, no new external scripts.
- Every user-visible string is `L(cs, en)`; both arguments are evaluated.
  Czech numbers via `czNum` / `fmtUsd` / `fmtPct` / `fmtMult` (decimal comma).
- Data values stay Czech keys (`reliable_fail`, `degen_fail`, phase names, theme
  names). A new value needs an entry in its lookup table (`TRUST_REASONS`,
  `DEGEN_REASONS`, `RISK_TAGS`, `THEME_EN`, `DROP_EN`, `INFO_TEXT`): the
  renderers silently skip unknown keys, and the audits fail on them.
- A new colour is a token defined in all three CSS blocks (light, media-dark,
  attribute-dark).
- `fetch` only inside the `GEM_SERVED` block.
- Explain with the row's own numbers; never label a row with the name of the rule
  it broke.

## Never

- Change what `themes.theme_of_app` returns — the pre-registered backtest (H3)
  rebuilt its theme gate on it. Extend `themes.app_theme` instead.
- Add a DeFiLlama category to a narrative theme's `dl` just to give rows a chip:
  `dl` is the theme's revenue fundament. Row-only mappings go to `NEAREST_THEME`.
- Put trust, float, unlocks, cliffs or the holders' share into the sort key or the
  gates. They are tags (product decisions, ARCHITECTURE §19).
- Show untokenized projects as rows, or add a time-window switch.
- Edit `PREREG` or `backtest_cache/prereg.lock` to fit a result, or tune gates on
  the backtest's descriptive statistics. Pre-register; judge on the picks ledger.
- Reintroduce a rejected alternative (ARCHITECTURE §19) without new evidence.
- Commit secrets. `agentic_scan/` is ignored and must stay out of the repo; keys
  come from the environment or CI secrets only.
- Overwrite a running `dist\GemScreener.exe` (Windows locks it): stage
  `GemScreener.new.exe` and swap it after the app is closed.

## Where to change what

| Task | Files |
|---|---|
| New theme | `themes.py` (`THEMES`, `THEME_SEED`), `template.html` (`THEME_EN`), ARCHITECTURE §13.1 |
| Map a DeFiLlama category to a theme | `themes.py`: a theme's `dl` (changes its fundament) or `NEAREST_THEME` (row chip only) |
| New table column | `template.html`: `COLS_*`, `sortValue`, the cell renderer, `INFO_TEXT` |
| New metric | `collector.py`, `audit.py` (second implementation), `template.html`, ARCHITECTURE §9 + §14 |
| Change a degen gate | `collector.py` (`DEGEN_*`, `degen_fails` — `gates_version` changes), audit §34, `DEGEN_REASONS` text |
| New data source | `collector.py` / a module like `liquidity.py`, via `Ctx.get` or `cg_get`, with a cache |
| Local server / exe | `app.py`, `build_exe.bat`, `GemScreener.spec` |
| CI / Pages | `.github/workflows/update.yml` |

## Testing notes

- The page's code runs in a strict IIFE: there is no `DATA` global — read
  `JSON.parse(document.getElementById('snapshot-data').textContent)`.
- Embedded browser panes may report `document.hidden = true`, which pauses the
  served-mode keep-alive.
- The exe serves its **bundled** template: rebuild it to see template edits there;
  `python app.py` re-reads `template.html` on every request.
- A cold CoinGecko basket rebuild (after editing `THEMES` or `THEME_OVERRIDES`)
  adds ~5 minutes of rate-limited calls to the next run.
