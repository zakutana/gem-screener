> **Note (2026-10-04):** items [19] to [22] of `../../SPEC.md` win where this differs: on Apps the card face also shows the Degen meter (item [20]), and the pinned header plus filters take at most 110 px (item [22]). Items 19 to 22 change nothing above 640 px: every desktop difference after this request comes from items 1 to 18, and all CSS of items 19 to 22 sits inside @media (max-width:640px) (this replaces the "pixel-identical" regression check below). The fund tray is item 12's tray; ignore the #pickBar/#pickFloat rules and the Mobile audit section.

# Gem Screener on a phone: Apps, Chains, Sectors (spec)

Mockup: `mobile-apps-chains-redesign.html` / `.png` (live snapshot of 2026-10-04; page tokens, fonts and cell renderers only).
Measured live at 390 × 844: Apps pins 262 px (header 125 + controls 137), its first pick is at 1,212 px, and the table is 1,329 px
wide in a 357 px box. Chains: 225 / 1,193 / 1,335. Sectors: first row at 1,479, table 872 px.

**Decisions.** (1) Picks first: each chart moves behind a "Year in a chart" / "Rotation map" button in the list header, drawn
only when opened. (2) One card per row, no sideways scroll. The face shows Upside, Revenue 30d, Market cap and Trajectory: Upside
is the sort key and is computed from revenue and market cap, so both sit beside it to check it; Trajectory says whether that
revenue grows. The rest goes behind "more". (3) ~100 px pinned instead of 262: the brand scrolls away; tabs + one 44 px row stay.

## Breakpoint, and Desktop unchanged
- Phone = `@media (max-width:640px)`; JS: `var PHONE = matchMedia('(max-width:640px)')` (the page already uses 640: `.sarow`, `.supstats`).
  **Phone layout from 640 px down; it stops at 641 px.** 641 px and up, including the existing 720/900 rules and landscape phones, stay as today.
- Not modified: every CSS rule outside the new query; row markup and handlers in `renderList`/`renderThemes`; the three tables;
  `.leaderboard`/`.herochart` DOM and order; the chart renderers' desktop values; `#trustSwitch #floorWrap #benchChip #pickBar #pickFloat` on desktop.
- New DOM ships `hidden`; only JS gated on `PHONE.matches` un-hides it. No new unscoped CSS. On a `PHONE` change, re-render the view.
- Regression check: screenshots of Top Picks, Apps, Chains and Sectors at 1336 px and 1920 px, before vs after, must be
  pixel-identical. At 1336 px, `document.body.innerHTML` must also be identical except for the new `[hidden]` nodes.

## Structure (new nodes, `hidden` until PHONE)
```html
<select id="mMode" class="m-mode" aria-label="Show"><option value="reliable">Vetted only</option><option value="degen">Degen picks</option>
  <option value="all">All by upside</option></select>       <!-- in #listControls before .search; #mFilt after it: -->
<button id="mFilt" class="m-filt" type="button" aria-label="Filters and sort" aria-haspopup="dialog">{sliders svg}</button>
<div class="m-head"><button class="m-sum" type="button" aria-haspopup="dialog"><b>76 projects</b><span>min $100K · Upside ↓</span></button>
  <button class="m-disc" type="button" aria-expanded="false">{icon} Year in a chart {chevron}</button></div>  <!-- before .leaderboard -->
<ol class="mcards" aria-label="Apps">                          <!-- after .tablewrap; Chains: "Chains" -->
 <li class="mcard" data-id="{id}" data-tier="{e.tier}">         <!-- li[data-id]: tipHostOf already treats it as a row -->
  <div class="mc-pick">{pickBtn(e)}<span class="mc-rank">{i+1}</span></div><div class="mc-id">{nameCell(e)}</div>
  <div class="mc-meter">{degenMeter(e)}</div><div class="mc-up">{potentialCell(e)}<span class="mc-k">upside</span></div>  <!-- meter: Apps only -->
  <dl class="mc-stats"><div><dt class="mc-k">Revenue 30d</dt><dd>{fmtUsd(e.rev30d)}</dd></div> <!-- Chains: Adoption, the table's own cell -->
   <div><dt class="mc-k">Market Cap</dt><dd>{fmtUsd(e.mcap)}</dd></div><div><dt class="mc-k">Trajectory</dt><dd>{trajCell(e.traj)}</dd></div></dl>
  <button class="mc-more" type="button" aria-expanded="false" aria-controls="mcd-{i}" aria-label="More about {name}">{chevron}</button>
  <div class="mc-det" id="mcd-{i}" hidden><dl class="mc-dl">{categoryCell} {monthlyCell} {chartCell} {supplyCell} {silaCell}</dl>
   <button class="mc-full" type="button">Full detail ›</button></div></li></ol>       <!-- Chains: Layer · theme -->
```
At the end of `<body>`: `<div id="mSheet" class="m-sheet" role="dialog" aria-modal="true" aria-labelledby="mSheetH" hidden>`.

## CSS (all inside `@media (max-width:640px){ … }`)
```css
.stickytop{top:calc(env(safe-area-inset-top,0px) - var(--gs-brand-h,0px))}   /* JS: --gs-brand-h = .top-row height + 8 */
.gs-logo img{width:auto;height:34px} nav.tabs>button{min-height:44px} .legendbtn{position:relative} .legendbtn::after{content:"";position:absolute;inset:-5px 0}
.controls{display:grid;grid-template-columns:auto minmax(0,1fr) 44px;gap:8px;min-height:0;padding-block:6px;padding-inline-end:var(--gutter)}
.controls>#trustSwitch,.controls>.count-badge,.controls>.benchline,.controls>.floorctl{display:none}
.m-mode{height:44px;font:600 16px "IBM Plex Sans";color:var(--accent);background:var(--surface-sunk);border:1px solid rgba(0,207,255,.45);border-radius:8px}
.search input{width:100%;height:44px;font-size:16px}   .m-filt{width:44px;height:44px;border:1px solid var(--rule);border-radius:8px}
.m-head:not([hidden]){display:flex;align-items:center;gap:8px;margin:0 0 8px} .m-sum{flex:1;height:44px;text-align:left}
.m-disc{height:44px;padding:0 12px;border-radius:22px;border:1px solid rgba(0,207,255,.45);color:var(--accent)} .m-disc[aria-expanded="true"]{background:var(--accent-soft)}
#view-apps .leaderboard,#view-chains .leaderboard,#view-sectors .leaderboard,.tablewrap{display:none}
.leaderboard.m-open{display:block} .herochart{padding:10px 12px} .chartbox{overflow:hidden}   /* once opened: no 2-D pan box */
.rank-row{min-height:44px} .rank-row.on::after{content:"open ›";color:var(--accent);font-weight:700} .mcards{list-style:none;padding:0;display:grid;gap:8px}
.mcard{display:grid;grid-template-columns:44px minmax(0,1fr) auto;grid-template-areas:"pick id up" "pick meter up" "stats stats more" "det det det";
  column-gap:6px;padding:8px 6px 6px 2px;background:var(--surface);border:1px solid var(--rule-soft);border-radius:12px}
.mcard.open{border-color:rgba(0,207,255,.55)} .mcard[data-tier="5"]{background:color-mix(in srgb,var(--gem) 9%,var(--surface))} /* 4: 5% · 3: 3% */
.mcard .pickbtn{width:44px;height:44px;margin:0;border:0;background:none;position:relative;isolation:isolate;line-height:44px}
.mcard .pickbtn::before{content:"";position:absolute;inset:9px;border:1.5px solid rgba(0,150,255,.5);border-radius:6px;z-index:-1}
.mcard .pickbtn.on{color:var(--paper)} .mcard .pickbtn.on::before{background:var(--gem);border-color:var(--gem)}
.mcard .namecell .nm{max-width:none;white-space:normal;font-size:15.5px} .mcard .upside{font-size:18px;font-weight:700}
.mc-stats{grid-area:stats;display:grid;grid-template-columns:.9fr .9fr 1.3fr;gap:8px;border-top:1px solid var(--rule-soft)}
.mc-stats .trajglyph{display:none} .mc-stats .trajcell{flex-direction:row} .mc-k{font:500 9.5px "IBM Plex Mono";text-transform:uppercase;color:var(--muted)} .mc-more,.mc-full{min-height:44px}
.pb-chip,#pickFloat{display:none!important} body:has(#pickBar:not([hidden])) main{padding-bottom:76px}  /* label unchanged; untick on the card */
#pickBar:not([hidden]){position:fixed;left:0;right:0;z-index:30;margin:0;border-radius:0;top:calc(var(--gs-vt,0px) + var(--gs-vh,100dvh));
  transform:translateY(-100%);display:grid;grid-template-columns:minmax(0,1fr) auto auto} .pb-clear{order:2;min-height:44px} .pb-launch{order:3;min-height:44px}
#tip.m-dock{left:8px!important;right:8px;top:auto!important;bottom:8px;max-width:none} .m-sheet .benchline{position:static;margin:0}
}
```

## Behaviour
- **Mode**: `#mMode` mirrors `state.trustMode`; change → `setTrustMode(v)`. Chains: remove the degen option (as `setView` hides `#degenBtn`).
- **Sheet** (`.m-sum`, `#mFilt`): 1) Min. revenue / 30d borrows `#floorWrap` while open and returns it on close (one slider, one state;
  hidden on Chains and in Degen picks, as today). 2) Sort by: one 44 px radio per `cols().filter(c=>c.sortable)`, column labels, Upside first;
  a radio calls `document.querySelector('#'+tableId+' th[data-key="'+k+'"]').click()` (`#tbl-apps`/`#tbl-chains`, Sectors `#tbl-themes`; re-query
  after every render, `renderHead` rebuilds the thead); "High → low / Low → high" clicks it again, so Degen three-state and `ownSort` work as today. 3) `#benchChip`, borrowed the same way. Closes on Done, scrim tap or Escape; focus trapped, then back to the opener.
- **Cards**: while `PHONE.matches`, `renderList` also fills `.mcards` from the same `list`. Empty: the table's "Nothing passed the
  filter" text. `.mc-more`, or a tap on the card outside `button, a, [data-legend]` (icon cards stop their own taps), toggles `.mc-det`,
  `aria-expanded` and `.open`. `.mc-full` calls `openPanel(id)`. `.pickbtn` binds as in tbody (`stopPropagation`, `togglePick`);
  its box is a `::before`, so `togglePick` rewriting `textContent` stays safe.
- **Charts**: `.m-disc` toggles `.leaderboard.m-open`, then calls `renderLeaderboard()` / `renderThemeScatter()`. They must
  draw on open: a hidden host has `clientWidth` 0, and the scatter would draw 900 px wide. In `renderHeroChart` only, when
  `PHONE.matches`: `H=210, padL=34, padR=12`. The two-tap stays: a tap lights a line or pins a bubble's card, and a second tap
  opens it. On a phone, for `#themeScatter g.pt`, `pinHost` adds `m-dock` to `#tip` and appends `<a class="tip-open" href="#">Open {sector} ›</a>` (calls
  `openThemePanel`; Tab already steps into `a[href]`). **Sticky**: a ResizeObserver on `.top-row` sets `--gs-brand-h` while `PHONE.matches`.
  Framed (/gem-screener) has no sticky today and keeps none; there the pick bar sits on `--gs-vt/--gs-vh` (`gsSyncViewport`), unframed on `0`/`100dvh`.

## Sectors
- `#altStrip` collapses behind a 52 px button, `class="m-alt" aria-expanded="false"`: "Altseason 28/100 · No altseason yet",
  from `CYC.index` and `CYC.words.cycle.label`. Top Picks keeps its panel. `#hotNow` is hidden: the Hot group says the same.
- `.m-head`: "12 sectors · by stage, then 3M ↓" opens the sheet with the `COLS_THEMES` sorts (`th` click); "Stage, then 3M"
  resets `themeSort={key:'sens',dir:-1}`. "Rotation map" is the `.m-disc`: the live narrow map (W 333, H 470), no scroll box.
- Cards by `STAGE_ORDER` like the table: `<h3 class="sgroup st-hot">▲ HOT 5 · 3M ↑ 1M ↑</h3><ol class="scards"><li class="scard st-{stage}" data-key>`
  with `themeNameCell`, `stageCell` and a `<dl>`: 3M `vsMedCell(th,'3m')`, 1M `vsMedCell(th,'1m')`, Fundamentals 30d `fundRecentCell` + `growth3Cell`;
  3 px stage edge = hot-sectors `.hs-card::before`. A tap → `openThemePanel(key)` (Talked about is there). Add `.scard` to `tipHostOf`'s containers.

## Accessibility
- Native buttons, select and links, all ≥ 44 × 44; card Tab order: pick → flags → upside → more → Full detail. `aria-expanded` on `.mc-more`, `.m-disc`, `.m-alt`; `aria-pressed` on the pick; the sheet is a labelled modal dialog.
- Colour is never the only cue: "−" (U+2212) and arrows on numbers, glyph + word on stages, a number on the meter. Motion: chevron
  rotation and border fades only, removed by the page's `prefers-reduced-motion` blanket. Nothing loops.

## Mobile audit (other views, 390 px)
1. Top Picks: the first Degen pick is at 1,248 px (Altseason 413 + Hot sectors 243 + the funnel). Fix: the collapsed Altseason row from Sectors.
2. Degen-picks funnel `.gaterow`: an SVG with `min-width:1040px` scrolls sideways; 2 of 7 gates show. Fix: draw it top-to-bottom, one row per gate.
3. Near-miss queue `.nq-scroll`: 1,010 px in 233 px, sideways; `nqRail`/`nqDoor`/`nqChev` loop forever. Fix: two cubes per row, `animation:none`.
4. Targets under 44 px: tabs 35 tall, Legend 67 × 28, `.cardi` 16 × 16, warning icons 20, Altseason "Expand" 29 tall, `.ap-scale` 8 tall. Fix: 44 px via `::after`.
5. Legend: there is no scrim, so the page behind it still takes taps; close is 28 × 28. Fix: reuse `.scrim`, 44 px close.
6. Detail panel: `min(840px,96vw)` leaves a 16 px sliver; `.panel-up` is absolute and forces `padding-right:132px`, so the name wraps. Fix: 100vw, Upside in flow.
7. Detail panel: `.panel-head` is `flex:none` and stays 291 px tall, so 553 px is left to scroll. Fix: scroll the whole `.panel`, with a sticky 44 px close.
8. Detail panel: link chips are 26 px tall, `.xinfo` 16 × 24, the monthly bars 22 px wide. Fix: 44 px chips; bars take taps on the whole column.
9. iOS (Safari and Brave): the 13 px search box zooms the page on focus. Fix: 16 px for every input and select at 640 px and below.

## Request text
```
Goal: on a phone (640 px wide and below), every Gem Screener tab shows its picks on the first screen.
Apps and Chains: one card per project, readable without sideways scrolling; sort and filters stay one tap away.
Charts on a phone open on request, fit the screen, and never pan inside the page.
Sectors: sectors as cards by stage with 3M and 1M against the median; a tapped map bubble shows its card, then opens.
Pinned header and filters take at most 110 px; every tap target is at least 44 px; nothing loops; colour is never the only cue.
Desktop layout (above 640px) must remain exactly as it is today.
```
