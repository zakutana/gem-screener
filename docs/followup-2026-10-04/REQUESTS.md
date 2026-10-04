# Build it Better: the three request texts for SPEC.md

App URL for all three: https://cymetica.com/gem-screener/app. Paste each block into the "improvements" field.

Before filing, replace `<COMMIT URL>` with the blob URL of SPEC.md at the pushed commit:
`https://github.com/zakutana/gem-screener/blob/<COMMIT HASH>/docs/followup-2026-10-04/SPEC.md`.
`<REQUEST 1 TICKET>` and `<REQUEST 2 TICKET>` are the ET numbers the platform gives requests 1 and 2.

Order: request 1 first. Request 2 only after request 1 has shipped, and request 3 only after request 2 has shipped: the platform refuses a second request while the app's ticket is open.

## Request 1: items 1 to 8 (Top Picks and the coin detail)

```
Follow-up to ET-28821 (Gem Screener, live at /gem-screener/app). Gem Screener is my own app and its source is this repo. The full spec is docs/followup-2026-10-04/SPEC.md at <COMMIT URL>: this request is its items 1 to 8 and their checklist lines, each checkable on the live page. Read it first and carry every numbered item into the spec as its own line, word for word. Summary: one framed Hot sectors panel with the Top Picks fund as its flagship; sector cards read name, return, Fund; the trend arrows get words; a readable Degen meter (N/10, no band word, Blue chip and Casino ends); the Supply tooltip and card numbers first, the rest behind one expand; the coin's Checks become six Guardians; the Apps project cell keeps one mark only, a green single-circle smiley for projects that share revenue with holders. Nothing else on Top Picks changes; no new columns.
```

## Request 2: items 9 to 18 (Sectors, Apps, Chains, data and funds), after request 1 has shipped

```
Follow-up to <REQUEST 1 TICKET> (Gem Screener, live at /gem-screener/app). Gem Screener is my own app and its source is this repo. The full spec is docs/followup-2026-10-04/SPEC.md at <COMMIT URL>: this request is its items 9 to 18 and their checklist lines, each checkable on the live page. Read it first and carry every numbered item into the spec as its own line, word for word. Summary: one click opens a sector on a mouse, the caption says the truth; the year in a chart follows the filter; a yellow "Launch your own memecoin" chip (a deliberate palette exception); a fund picks tray that never scrolls away; the Benchmark shield scaled uniformly; columns aligned; a 6% stage tint on the rotation chart; Talked about simplified, "too few" under 20 people; reliable data sources; the managed funds hold what their cards say, with rebalance dates. No new columns.
```

## Request 3: items 19 to 22 (phone), after request 2 has shipped

```
Follow-up to <REQUEST 2 TICKET> (Gem Screener, live at /gem-screener/app). Gem Screener is my own app and its source is this repo. The full spec is docs/followup-2026-10-04/SPEC.md at <COMMIT URL>: this request is its items 19 to 22 and their checklist lines, each checkable on the live page at 390 px. Read it first and carry every numbered item into the spec as its own line, word for word. Summary: on a phone (640 px and below) every tab shows its picks on the first screen and charts open on request; Apps and Chains become one card per project with no sideways scroll; Sectors become cards grouped by stage; the pinned header plus filters take at most 110 px and every tap target is at least 44 px. Desktop above 640 px stays exactly as it is: no change to its CSS, DOM order or behaviour.
```
