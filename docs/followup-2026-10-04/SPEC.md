# Build request: Gem Screener, changes after ET-28821 (cymetica.com/gem-screener/app)

**For:** the lead agent of the Cymetica SDLC pipeline
**From:** Adam (product owner, Gem Screener)
**Scope:** the Top Picks tab (the Hot sectors block with the Top Picks fund bar, and the Degen meter); the coin detail (the Supply tooltip and card, the Checks block as Guardians); the Apps project cell; the Sectors, Apps and Chains tabs (the bubble click, the year in a chart, the Memecoins launch chip, the fund picks tray, the Benchmark shield, column alignment, the rotation chart tint, Talked about); the data reliability behind the page; the CyMetica-managed funds the page names; and the phone layout (640 px and below). Build or change only what is named; leave the rest of the app as it is.

> **HOW TO READ THIS SPEC**
> 1. **Goals, not methods.** How you build it is your call. Where an item gives a rule or a number, it is the owner's decision unless the item says it is a default.
> 2. **Every number is read on 2026-10-04**, between 16:50 and 17:10 UTC, from the live page (its snapshot of 08:47 UTC, at 1360 × 900 and at 390 × 844), from its public API (`/api/v1/gem-screener`, `/status`, `/picks`, `/funds`) and from the fund pages. They move with every refresh; they are there so you can check that a change took effect, not as the requirement.
> 3. **English only**, degen-friendly: the number first, plain short words.
> 4. **Keep the look.** Change only what an item names. **On a phone, desktop stays exactly as it is:** items 19 to 22 apply at 640 px and below only.
> 5. **This spec starts from the page as it is live on 2026-10-04**: after ET-28821 (shipped 2026-10-01, 23:40 UTC) and ET-28934, the Supply Analyzer, which wired the Supply card and the Supply column into the page (shipped 2026-10-04, 08:38 UTC).
> 6. **It is filed in three requests**, because the platform takes one open request per app: items 1 to 8 first, items 9 to 18 when the first has shipped, items 19 to 22 when the second has shipped. Each request builds its own items, to the checklist lines with those numbers.
> 7. **The files are in this folder.** `reference/` holds a mockup per topic (an HTML page, its picture and a short spec): they are inspiration, not literal. Where a reference spec differs from an item here, the item wins; the reference specs that differ say so in their first line. There is no `assets/` folder this time: nothing here is ready to drop in.

## Reference files (`reference/`)

| Folder | For items | What it is |
|---|---|---|
| `reference/hot-sectors/` | 1, 2, 3, 4 | The Hot sectors panel with the three sector cards and the Top Picks fund as its flagship, desktop and 390 px. |
| `reference/degen-meter/` | 5 | The Degen meter on a pick card and in the Apps table. |
| `reference/supply-card/` | 6 | The Supply tooltip and the Supply card, numbers first, with the one expand. |
| `reference/guardians/` | 7 | The Guardians block; `before-checks.png` is the Checks block as it is today. |
| `reference/project-cell/` | 8 | The Apps project cell with its one badge, the single-circle green smiley. |
| `reference/launch-chip/` | 11 | The "Launch your own memecoin" chip on the Memecoins row (the yellow one is alternative B in the mock). |
| `reference/fund-picks-tray/` | 12 | The fund picks tray: sticky at the top on desktop, docked to the bottom on a phone, and at 30 picks. |
| `reference/sectors-tint/` | 15 | The rotation chart with the four stage tints at 6 %. |
| `reference/phone-apps-chains-sectors/` | 19, 20, 21, 22 | Apps, Chains and Sectors on a phone (390 px): picks first, cards, the short pinned header. |

## The rules that hold for every item

These are the owner's hard rules, as each request carries them.

- **No new columns are added to any table** (Apps, Chains, Sectors). Everything here changes existing elements only.
- **Keep every existing state and text**: no fund yet, new with no return yet, loading; and the data the page already shows.
- **No new data, per request.** Items 1 to 8 use the data the page already loads: no new data source. Items 9 to 17 add no new data field (item 17 may change where existing data comes from, as it asks). Item 18 is the one exception: it needs the funds' rebalance record it asks for. Items 19 to 22 add no new data.
- **Honest colour.** The stage (hot, emerging, fading, falling) colours only the card edge and the pill. The return colours only its own number, green or red by the existing rounding rule. A hot sector whose fund is down still shows a red negative number with a real minus sign. Never hide, mute, reorder by return, or invent data (no made-up sparklines). Colour is never the only cue.
- **Accessibility:** no interactive element nested in another, visible keyboard focus, AA contrast, tooltips on hover, focus and tap, reduced motion respected; nothing loops.
- **The page's own colours and fonts.** The single deliberate exception is the yellow launch chip of item 11.
- **Request 1 (items 1 to 8), scope on the Top Picks tab:** only the Hot sectors block with the Top Picks fund bar (items 1 to 4) and the Degen meter on the cards (item 5) change. Nothing else on the Top Picks tab changes: the Altseason Index, the Degen Picks funnel and the pick cards keep their layout. Items 6 to 8 apply to the coin detail and the Apps project cell only.
- **Requests 1 and 2, phone (390 px):** cards stack, no horizontal scroll, nothing pushed off screen; the flagship becomes name, number, then a full-width button.
- **Request 3 (items 19 to 22):** the desktop layout (above 640 px) must remain exactly as it is today: no change to its CSS, DOM order or behaviour. All phone rules apply at 640 px and below only. No new data and no change to any number or label that exists today; negative numbers keep their minus sign. The pick checkboxes and the fund tray keep working on a phone.

---

# Request 1: Top Picks and the coin detail (items 1 to 8)

Why: today the Hot sectors block and the "Gem Screener Top Picks (CyMetica-managed)" fund bar under it are plain text lines. Next to the Altseason Index panel above and the Degen Picks funnel below they look unfinished, and a visitor cannot read them in three seconds.

## 1. The Hot sectors panel

**[1] One framed panel, same visual weight and frame style as the Altseason Index, holding the sector cards and the Top Picks fund bar.** Live at 1360 px: the Altseason Index is a framed panel (1281 × 219 px, the cyan outline of ET-28688 item 3); under it "HOT SECTORS" is a plain heading, then three unframed cards (AI, L2, RWA, each 420 × 76 px), then the fund bar as a separate line (1281 × 54 px), then "DEGEN PICKS". The owner wants one panel, framed like the Altseason Index, with the sector cards and the fund bar inside it.

Reference: `reference/hot-sectors/` (hot-sectors-redesign.html, .png, hot-sectors-spec.md).

**[2] Each sector card reads name, then number, then action.** Live, a card is one row of small type: "AI ▲ HOT (i)" and under it "Gem Screener AI · −3.7% since launch · Fund →" (L2 +3.1 %, RWA +5.1 %). The owner wants the sector name large, the HOT pill, **the fund's return since launch as the biggest text on the card**, and a clear "Fund" button. The return keeps its colour rule and its real minus sign (AI's −3.7 % stays red and as large as a positive number).

Reference: `reference/hot-sectors/`.

**[3] The two trend arrows get words next to the icon: "Already leading", "Beaten down but turning".** Live, the trend signal on a card is an icon only (all three cards show "Already leading" today); its words exist only in its tooltip label. The owner wants the word next to the icon; **the existing tooltips stay.**

Reference: `reference/hot-sectors/`.

**[4] The Top Picks fund bar becomes the flagship of the panel.** Live: "Gem Screener Top Picks (CyMetica-managed) −2.0% since launch the Degen picks at equal weight · rebalanced weekly Fund performance →", one line. The owner wants it the same anatomy as a sector card, **one size larger, with the one solid button in the block.** At 390 px it becomes name, number, then a full-width button.

Reference: `reference/hot-sectors/`.

## 2. The Degen meter

**[5] The Degen meter keeps what it measures and its scale becomes readable.** It stays a risk level 1 to 10, higher is riskier. Live, on a Top Picks pick card (Collector Crypt) the meter is a lone "4" at the left and ten small segments (272 × 24 px), with no "/10", no name and no end labels; the empty segments are all one grey (`rgba(111,129,153,.16)`), so the zones show only once filled. In the Apps table it is the same: "6" and ten segments, 126 px wide, no "/10". The owner wants:

- **On the cards:** a full-width bar labelled "Degen meter", the value "4/10" at the end of the fill and **no band word above it (no "Spicy" label)**, end labels "Blue chip" and "Casino", empty segments faintly tinted by their zone, and the existing tooltip.
- **In the Apps table:** the compact bar followed by "N/10".

Reference: `reference/degen-meter/` (its spec still draws a band word; this item wins).

## 3. The Supply tooltip and card

**[6] The Supply tooltip and the Supply card are numbers first, words second.** Live (Pharaoh Exchange): the Supply column's tooltip has the title "Supply pressure 1/10 · Flooding" and four lines under it ("The sellable pile changes +52% to +67% a year. The pile of tokens that can be sold grows 22.9M a month. Nothing measured goes out." / "Unknown: vesting schedule, staking flow, burns (…)" / "Pie: the tokens in play today by slice. Read Oct 4. Supply Analyzer by EventTrader."). The Supply card in the detail runs to about a hundred words: three tiles ($4.0M market cap, +16% new tokens a week, unknown next unlock), the legend, "+52% to +67% a year · the sellable pile", "1 / 10 · FLOODING", a sentence, a paragraph on what is unknown and assumed, the curve's two end points, "Open in Supply Analyzer ↗" and "SUPPLY SOURCES DISAGREE". The owner wants:

- **Tooltip:** a title, one line ("Sellable tokens grow +52% to +67% a year (estimate)") and one small line ("1 = most new supply · 3 parts not measured").
- **Card:** the big figure with a small "estimate" tag, the pressure badge "1/10 Flooding · 1 = most new supply", one plain sentence, then the pie and the curve.
- **Everything else goes behind one expand, "What we could not measure (3)"**: what could not be measured, the assumptions, sources that disagree, the formula, the date. Nothing is deleted; the range and the fact that parts are assumptions stay visible in the small "estimate" tag.
- **Pie:** hovering or tapping a slice or a legend row highlights both and shows a short line such as "Free to sell · 33.5M · 6% · can be sold now".
- **Four states stay supported:** measured, range, unknown, sources disagree. **Red stays red.**

Reference: `reference/supply-card/`.

## 4. Guardians

**[7] Coin detail: the "Checks" block becomes "Guardians", six of them.** Live (Collector Crypt), the block is titled "CHECKS", has a legend (Good, Caution, Bad, Not checked) and six rows by area, each with a sentence: Control ("Nobody can change the token"), Supply, Earnings ("Earns $13.9M a month · No clear revenue trend · holders get 0% of revenue"), Liquidity, Heat, Legit; then "Not checked yet · 0 of 4 ran for this coin". Every app's record carries 14 checks. The owner wants:

- **Six guardians, one row each**, showing only a short name and the page's existing icon ring with a small state mark (check = clear, ! = caution, x = bad, ? = no data or not scanned, dash = does not apply), so colour is never the only cue:
  - **Rug power**: can the owner mint, freeze, change taxes or upgrade the contract;
  - **Holders paid**: does revenue reach holders;
  - **Thin liquidity**: the price move on a $10K buy;
  - **Price run**: how far the price already ran;
  - **Security**: audit and past hacks, the worse of the two;
  - **Team**: who ships it.
- **One summary line** such as "2 red · 1 caution · 3 clear".
- **All numbers and explanations live only in each guardian's tooltip.**
- **The icons and rings the Checks block has today**; no characters or mascots.
- **A guardian never shows green without data** (a dashed ring instead).
- **Growing, Price vs revenue, New tokens and Revenue cover leave this block** (the first two exist as table columns, supply lives in the Supply card), and **Hidden supply, Insider flow and Whales stay out.**
- **Detail view only:** no table column.

Reference: `reference/guardians/` (`before-checks.png` is today's block; where its spec draws Security differently from this item, this item wins).

## 5. The Apps project cell

**[8] Apps table, project cell: no marks but one, a green single-circle smiley for projects that share rewards.** Live, the project cell holds the logo, the name and the symbol, and on 13 of the 113 rows under "All by upside" a round (i) "Supply sources disagree" icon next to the name; the page's code can also put a red "No holder share" mark there (none showed today). The owner wants:

- **Remove the round (i) badge next to the name and every other mark in that cell**, such as the red "No holder share" mark, because the Guardians in the detail (item 7) now cover them. The row and the name still open the detail.
- **Exactly one badge may appear in this cell:** a small, refined **green smiley** in the style of the page's icons: **one single circle outline that is the face itself, with two eyes and a smile, not a face inside a second ring** (one circle, not two), shown only for projects that share rewards with their community.
- It uses the figure the page already has (the holders' share of revenue behind the "Holders share" check), **shows only when that check is green**, and its tooltip gives the share in one short line ("Holders get 40% of revenue").
- When a project does not share, or there is no data, or its holders get little, **the cell shows nothing at all.** It sits in the existing project cell, not in a new column.

Today that check (`reaches_you` in each app's record) is green on 36 of the 211 apps, caution on 27, red on 98 and not checked on 50: the smiley would show on those 36 only.

Reference: `reference/project-cell/`.

---

# Request 2: Sectors, Apps and Chains, data and funds (items 9 to 18)

Why: these are the points where the tabs behave differently from what their own captions say, or where the page is hard to read at a glance; plus the data reliability behind the page, and the funds the page names.

## 6. The Sectors bubble chart

**[9] Sectors tab, bubble chart: one click with a mouse, two steps on touch, and a caption that tells the truth.** Live, the caption under the chart reads "Bubble size = market cap. Tail = where it stood 4 weeks ago. Click a bubble for the sector." The page's code already opens the sector on one click on a device that can hover (a comment names ET-29257), and a click on a bubble at 1360 px opened the sector's panel; on touch the first tap shows the card and the second opens the detail (ET-28990 #3), under the same caption. The owner wants:

- **With a mouse** (a device that can hover), one click on a bubble opens that sector's detail panel, since the hover already shows the card.
- **On touch**, today's two steps stay: the first tap shows the card, the second opens the detail.
- **The caption "Click a bubble for the sector" matches whichever behaviour a visitor gets.**

Reference: none; check on the live page.

## 7. The year in a chart

**[10] Apps and Chains, "The year in a chart" follows the filter above it.** Live on Apps: switching the filter changes the project list (75 rows under Vetted only, 7 under Degen picks, 113 under All by upside) but the chart and its caption stay the same: title "Top 10 by upside: their year", caption "Top 10 by upside of 87 vetted.", first line Pharaoh Exchange, also under Degen picks, where Pharaoh Exchange is not one of the 7. On Chains the caption is "Top 10 by upside of 24 vetted." The owner wants the chart to redraw for the selected filter (Vetted only, Degen picks, All by upside), **with the title and caption saying what it now shows** (for Degen picks, the 7 picks).

Reference: none; check on the live page.

## 8. Memecoins: the launch chip

**[11] Sectors tab, Memecoins row: the rocket becomes a clearly visible yellow call to action.** Live, the Memecoins row (stage Falling) carries an 18 × 18 px green rocket that links to https://cymetica.com/launchpad in a new tab, with the accessible name "Launch your own memecoin". The owner wants a chip reading **"Launch your own memecoin"** with a rocket disc and an external-link arrow, **in yellow** (a dark chip with a yellow outline, a yellow rocket disc and a yellow label), so that it stands out as the one marketing element on the page.

- **The palette exception is deliberate.** The owner knows the palette rule says "no amber, orange or yellow": this is an explicit, deliberate exception for this one chip only, requested by the owner of the request.
- **Under 560 px** the chip shows "Launch" and keeps the full name as its accessible name.

Reference: `reference/launch-chip/` (the mock's alternative B is the yellow one; its spec recommends cyan, and this item wins).

## 9. Your fund picks

**[12] Apps and Chains, "Your fund picks" becomes a tray that never scrolls out of view.** Live, ticking a project shows one low-key line in the sticky controls, 12 px type: "Your fund picks (1/30): FLY × Launch a fund with these → clear". The owner wants that bar replaced with a tray:

- **It appears as soon as the first project is ticked**, with one short entrance plus a brief highlight (reduced motion respected).
- **It never scrolls out of view:** on desktop it sticks to the top of the table, right under the sticky header, when the visitor scrolls down; on phones it docks to the bottom of the window.
- **It shows** a progress ring "N of 30", the picked projects as chips with logos, a clear button "Launch a fund with these N", and "Clear".
- **At 30** the ring turns the caution blue, a line says "30 is the limit: remove one to add another", and the remaining + buttons are disabled.
- **It never covers table rows** (bottom padding) and works at 390 px.

Reference: `reference/fund-picks-tray/`.

## 10. The Benchmark shield

**[13] Apps and Chains, the "Benchmark" shield is scaled uniformly.** Live at 1360 px both shields are 92 × 78 px: on Apps "Benchmark: Hyperliquid, 35x revenue", on Chains "Benchmark: the median of 19 large chains, 128x adoption". Before ET-28821 the shield was 92 × 110 px (ET-28821 item 8): after the request to make it smaller it was squashed from top to bottom while its width stayed the same, so it is now wide and flat and its proportions look wrong. The owner wants it **scaled uniformly**: the shield's original width-to-height ratio kept, the text and the icon undistorted, **at the smaller size that was asked for** (about 78 px tall, ET-28821 item 8). Note: ET-28821 measured that a uniform scale to 78 px makes the word BENCHMARK about 6 px high; keeping it readable without distorting the shield is yours to solve.

Reference: none; check on the live page.

## 11. Column alignment

**[14] Apps and Chains tables: each header and its values line up in one visual column.** Live on Apps, headers and values mix left alignment (Project, Degen meter, Category, 12 months, Chart, Upside, Trajectory) and right alignment (#, Market cap, Revenue 30D, Supply, Strength 3M), so some values sit too far right and some too far left of their header: the Chart scores, for example, sit about 44 px right of the centre of their header cell. The owner wants every value centred under its header, or each column aligned consistently, so each header and its numbers line up (for example Market Cap, Revenue 30D, Supply, Upside, Strength 3M and Trajectory). **Do not change widths or content of the columns; only the alignment.**

Reference: none; check on the live page.

## 12. The rotation chart

**[15] Sectors tab, rotation chart: a very soft stage tint in each corner, at about 6 %.** Live, the plot area is one flat dark blue (the plot frame has no fill). The owner wants a very soft tint in each corner that matches its stage colour: **Hot green at the top right, Emerging cyan at the top left, Fading blue at the bottom right, Falling red at the bottom left**, fading to the page background toward the centre, at the very subtle strength of **about 6 percent opacity (not stronger)**, so the four stages read at a glance. The median cross lines, bubbles, tails and labels keep their full contrast and positions; the tint is decoration and never changes what a colour means.

Reference: `reference/sectors-tint/`.

## 13. Talked about

**[16] Sectors table, "Talked about" shows a percentage and a plain arrow; "too few" below 20 people.** Live, the column shows a percentage, an arrow and a second figure, such as "3.5% ↑ +0.5 pts" (DEX & perps), "0.8% → −0.2 pts" (AI) or "0.6% ↓ −0.4 pts" (L1), and "too few" only under 5 people. Its tooltip says how many people: of 856 people in the chats over 7 days, 10 of the 12 sectors rest on fewer than 20 (L2 and L1 on 5, DeFi lending & staking on 6, AI on 7); only DEX & perps (30) and Gaming (23) have more. The owner wants:

- **Only the percentage and a plain arrow**; the points figure moves into the tooltip.
- **The arrow is neutral in colour.**
- **"too few" below 20 people instead of 5**, so a handful of chat messages never looks like a signal (today that would be 10 of the 12 rows).

Reference: none; check on the live page.

## 14. Data reliability

**[17] The data behind the Gem Screener is reliable: stale prices and fallbacks are rare, and a refresh does not leave the page hours old.** Live at 17:00 UTC, the page's status line (in the top bar) read "Updated 8 h ago · 211 apps · 33 chains · Live · collecting new data · 1 price not refreshed (18 h old) · 88 of 244 prices via DeFiLlama". `/api/v1/gem-screener/status` said why: the snapshot on the page is from 08:47 UTC, the next refresh was due at 14:47 UTC, and the last attempt (finished 15:03 UTC) stopped at its own audit (`last_attempt: ok false, stage audit:audit.py`), so the page stayed on the 08:47 snapshot; the snapshot carries 6 fetch warnings, in which CoinGecko answered 429 (rate limited) and 403. The owner wants:

- **Every data source the Gem Screener uses is reviewed.** Where one depends on a free public API with rate limits, switch to the most reliable source you have available, for example a paid or internal feed, so that stale prices and fallbacks become rare.
- **You do not need to say publicly which sources you use.**
- **Success:** the warning ("… not refreshed …", "… prices via DeFiLlama") almost never shows, and a snapshot refresh does not fail its own audit and leave the page hours old.

Reference: none; check `/api/v1/gem-screener/status` and the page's status line over several days.

## 15. The CyMetica-managed funds

**[18] The managed funds hold what their card says they hold.** The Top Picks tab names the funds and links to them: the flagship says the Top Picks fund holds "the Degen picks at equal weight · rebalanced weekly", and each Hot sectors card has a "Fund →". Live:

- **The Top Picks fund** (https://cymetica.com/fund-performance/aib-gs-picks, "Gem Screener Top Picks (CyMetica-managed)", live since 2026-09-27, −2.01 % since inception, index price $5.10) holds six components at 16.67 % each: **UP, NEST, SOLV, FXN, KNC, EDGE**. Its mandate reads "Gem Screener Degen picks, equal weight, rebalanced weekly" and its governance "AI model proposes · Human-In-The-Loop approves". The page says "This fund has not bought its assets yet", and shows no rebalance history and no date of a last or next rebalance.
- **The current Degen picks** (`/api/v1/gem-screener/picks`, as of 08:47 UTC; the page's headline "7 of 211 apps pass all 7 gates") are seven: **CARDS, SOLV, MNDE, O, GMX, EDGE, MET**. Only SOLV and EDGE are in the fund; UP, NEST, FXN and KNC are in the fund and not among the picks; CARDS, MNDE, O, GMX and MET are picks and not in the fund.
- **The dates exist in the API, not on the pages:** `/api/v1/gem-screener/funds` gives every fund `rebalanced_at` 2026-09-28 00:20 UTC and `next_rebalance_at` 2026-10-05 00:20 UTC. Whether the next rebalance will close the gap cannot be read anywhere today.
- **The three sector funds on the Hot sectors cards** (each "Gem Screener <sector> sector leaders, equal weight, rebalanced weekly", the same governance, live since 2026-09-27, 20 % each): **Gem Screener AI** (aib-gs-ai: NEAR, TAO, ICP, VVV, RENDER; −3.66 %), **Gem Screener L2** (aib-gs-l2: OKB, MNT, ARB, OP, STRK; +3.10 %), **Gem Screener RWA** (aib-gs-rwa: LINK, XLM, QNT, ONDO, ALGO; +5.06 %). The cards' tooltips name the sectors' "Leaders by upside": AI MorpheusAI, OpenLedger, Virtuals Protocol; L2 Polygon, Arbitrum, OP Mainnet; RWA Collector Crypt, Securitize, GAIB. Only Arbitrum and OP Mainnet are in a fund. Neither page says which kind of leader a sector fund holds, so whether the sector funds are stale cannot be verified from outside; no rebalance date is shown on them either.

The owner wants:

- **(a) The Top Picks fund's holdings equal the current Degen picks** (equal weight) after each weekly rebalance, and the page shows **the date of the last rebalance and the next one, with what was swapped in and out** (a small rebalance history on the fund page).
- **(b) The same for the three sector funds** (Gem Screener AI, L2, RWA): **holdings are that sector's current leading coins as the Hot sectors card says**, with the last and next rebalance date.
- **(c) A rebalance waiting for approval says so.** If a rebalance is waiting for the human approval the governance text mentions, the fund page and the Top Picks card say so ("rebalance proposed, waiting for approval since <date>") instead of showing old holdings as current.
- **(d) Success is checkable:** on any day, a fund's holdings differ from the current picks (or the sector's leaders) by at most what a pending, dated, disclosed rebalance explains.

Reference: none; check the fund pages against `/api/v1/gem-screener/picks` and the Hot sectors cards.

---

# Request 3: the Gem Screener on a phone (items 19 to 22)

Why: on a phone the Apps, Chains and Sectors tabs are hard to use. Read at 390 × 844 px on 2026-10-04: on Apps the pinned header and controls take 263 px, the year chart (864 px tall) comes first and the first pick row starts at 1,215 px; the table is 1,330 px wide in a 356 px box, so only 2 of its 12 columns are fully in view. Chains: 227 px pinned, first row at 1,197 px, table 1,335 px wide, 2 of 11 columns in view. Sectors: the first table row is at 1,485 px, below the rotation map, and the table is 873 px wide in the same 356 px box; the map (312 × 476 px) sits in a box that scrolls on its own (`overflow: auto`) and fits at 390 px today. Every rule here applies at **640 px and below only**; desktop stays exactly as it is.

**[19] Every tab shows its picks on the first screen; charts open on request.** The owner wants the picks on the first screen of every tab. The charts open on request, behind a clear "Year in a chart" / "Rotation map" control, **fit the screen and never pan inside the page.**

Reference: `reference/phone-apps-chains-sectors/`.

**[20] Apps and Chains: one card per project, readable without sideways scrolling.** The owner wants one card per project. **The card face shows the Degen meter, Upside, Revenue 30d, Market Cap and Trajectory; the other columns sit behind a "more" control.** Sorting and filters stay one tap away: one control, one sheet.

Reference: `reference/phone-apps-chains-sectors/` (its spec lists the card face without the Degen meter; this item wins).

**[21] Sectors: sectors as cards grouped by stage.** The owner wants each sector as a card, grouped by stage, each with **3M and 1M against the median sector and the fundamentals.** On the map, **the first tap on a bubble shows its card and the second opens the sector**, as it does today.

Reference: `reference/phone-apps-chains-sectors/`.

**[22] The pinned header plus filters take at most 110 px; every tap target is at least 44 px.** Live at 390 px: 263 px pinned on Apps, 227 px on Chains, 126 px on Sectors and Top Picks; the tabs are 35 px tall, Legend 68 × 29 px, the (i) buttons 16 × 16 px.

Reference: `reference/phone-apps-chains-sectors/`.

---

## Checklist (one line each; done when all are true)

### Request 1

- [ ] 1 On Top Picks, the Hot sectors cards and the Top Picks fund bar sit inside one framed panel, with the same visual weight and frame style as the Altseason Index.
- [ ] 1 Nothing else on the Top Picks tab moved: the Altseason Index, the Degen Picks funnel and the pick cards keep their layout.
- [ ] 2 Each sector card reads name, then number, then action: the sector name large, the HOT pill, the fund's return since launch as the biggest text on the card, and a clear "Fund" button.
- [ ] 2 The stage colours only the card edge and the pill; the return colours only its own number by the existing rounding rule; a negative return is red with a real minus sign, as large as a positive one; no card is hidden, muted or reordered by return; no sparkline is drawn.
- [ ] 2 The states "no fund yet", "new, no return yet" and loading still show.
- [ ] 3 The trend signals show their words next to the icon ("Already leading", "Beaten down but turning"); their tooltips are unchanged.
- [ ] 4 The Top Picks fund bar has the anatomy of a sector card, one size larger, and carries the one solid button of the block.
- [ ] 4 At 390 px the cards stack with no horizontal scroll and nothing pushed off screen, and the flagship reads name, number, then a full-width button.
- [ ] 5 On a pick card the Degen meter is a full-width bar labelled "Degen meter", with the value "N/10" at the end of the fill, no band word ("Spicy" or other) above it, the end labels "Blue chip" and "Casino", and the existing tooltip.
- [ ] 5 The empty segments are faintly tinted by their zone (green, blue, red), so the whole scale is visible before it fills.
- [ ] 5 In the Apps table the meter is the compact bar followed by "N/10"; the level it shows is the same as before.
- [ ] 6 The Supply tooltip is a title, one line ("Sellable tokens grow … a year (estimate)") and one small line ("1 = most new supply · N parts not measured").
- [ ] 6 The Supply card shows the big figure with a small "estimate" tag, the pressure badge ("1/10 Flooding · 1 = most new supply"), one plain sentence, then the pie and the curve.
- [ ] 6 What could not be measured, the assumptions, sources that disagree, the formula and the date are behind one expand, "What we could not measure (N)"; nothing that was on the card is lost.
- [ ] 6 Hovering or tapping a pie slice or a legend row highlights both and shows a short line ("Free to sell · 33.5M · 6% · can be sold now").
- [ ] 6 The measured, range, unknown and sources-disagree states all still show; red stays red.
- [ ] 7 The coin detail's Checks block is titled "Guardians" and has six rows: Rug power, Holders paid, Thin liquidity, Price run, Security, Team; each shows only its short name and the existing icon ring with a state mark (check, !, x, ?, dash).
- [ ] 7 One summary line counts them ("2 red · 1 caution · 3 clear"); every number and explanation is in the guardian's tooltip (hover, focus, tap), not on the row.
- [ ] 7 Security shows the worse of audit and past hacks; a guardian without data never shows green (dashed ring).
- [ ] 7 Growing, Price vs revenue, New tokens and Revenue cover are not in the block; Hidden supply, Insider flow and Whales are not in it either; no table gained a column.
- [ ] 8 The Apps project cell has no (i) badge, no "No holder share" mark and no other mark; the row and the name still open the detail.
- [ ] 8 The only badge in the cell is a green smiley drawn as one single circle that is the face (two eyes, a smile, no second ring), shown only when the Holders share check is green (36 of 211 apps on 2026-10-04's data).
- [ ] 8 The smiley's tooltip is one line with the share ("Holders get 40% of revenue"); a project that does not share, has no data or whose holders get little shows nothing in the cell.

### Request 2

- [ ] 9 With a mouse, one click on a bubble in the Sectors chart opens that sector's detail panel.
- [ ] 9 On touch, the first tap on a bubble shows its card and the second opens the detail.
- [ ] 9 The chart's caption says what a click or tap does on the device the visitor uses.
- [ ] 10 On Apps and Chains, switching between Vetted only, Degen picks and All by upside redraws "The year in a chart" for that selection.
- [ ] 10 The chart's title and caption say what it shows; under Degen picks it shows the picks (7 on 2026-10-04) and no project that is not one of them.
- [ ] 11 The Memecoins row in Sectors has a chip "Launch your own memecoin" with a rocket disc and an external-link arrow: dark chip, yellow outline, yellow disc, yellow label; it opens https://cymetica.com/launchpad in a new tab.
- [ ] 11 Yellow appears nowhere else on the page; under 560 px the chip reads "Launch" and its accessible name is still "Launch your own memecoin".
- [ ] 12 On Apps and Chains, ticking the first project brings in the fund picks tray with one short entrance and a brief highlight; with reduced motion there is no motion.
- [ ] 12 On desktop the tray sticks to the top of the table, right under the sticky header, while the table scrolls; on a phone it docks to the bottom of the window.
- [ ] 12 The tray shows a ring "N of 30", the picks as chips with logos, "Launch a fund with these N" and "Clear"; it never covers a table row, and works at 390 px.
- [ ] 12 At 30 picks the ring is the caution blue, the line "30 is the limit: remove one to add another" shows, and the remaining + buttons are disabled.
- [ ] 13 Both Benchmark shields (Apps and Chains) have the shield's original width-to-height ratio (92 : 110), at the smaller size asked for (about 78 px tall); the text and the icon are not distorted.
- [ ] 14 On Apps and Chains every header and its values line up in one visual column (centred, or each column aligned consistently); no column's width or content changed.
- [ ] 15 The rotation chart's plot area has a soft tint in each corner in its stage colour (Hot green top right, Emerging cyan top left, Fading blue bottom right, Falling red bottom left) at about 6 % opacity, fading toward the centre.
- [ ] 15 The median cross lines, bubbles, tails and labels keep their contrast and positions.
- [ ] 16 "Talked about" shows only the percentage and a plain, neutral-coloured arrow; the points figure is in the tooltip.
- [ ] 16 A sector talked about by fewer than 20 people shows "too few".
- [ ] 17 Every data source of the Gem Screener is reviewed, and those on rate-limited free public APIs are moved to the most reliable source available (which ones need not be public).
- [ ] 17 Over the days after the build, the page's "not refreshed" / "prices via DeFiLlama" warning almost never shows, and `/status` shows no refresh that failed its audit and left the page hours old.
- [ ] 18 The Top Picks fund holds the current Degen picks at equal weight after each weekly rebalance.
- [ ] 18 The Top Picks fund page shows the date of the last and the next rebalance and a small history of what was swapped in and out.
- [ ] 18 Gem Screener AI, L2 and RWA hold their sector's current leading coins as the Hot sectors card says, and show their last and next rebalance date.
- [ ] 18 A rebalance waiting for approval shows on the fund page and on the Top Picks card as "rebalance proposed, waiting for approval since <date>", not as current holdings.
- [ ] 18 On any day, a fund's holdings differ from the current picks (or its sector's leaders) by at most what a pending, dated, disclosed rebalance explains.

### Request 3

- [ ] 19 At 390 px, on Apps, Chains and Sectors, picks are on the first screen without scrolling.
- [ ] 19 The charts open on request ("Year in a chart" / "Rotation map"), fit the screen and do not pan inside the page.
- [ ] 20 On a phone, Apps and Chains show one card per project with no sideways scrolling; the face shows the Degen meter, Upside, Revenue 30d, Market Cap and Trajectory, and the other columns are behind "more".
- [ ] 20 Sorting and filters are one tap away, in one control that opens one sheet.
- [ ] 21 On a phone, Sectors shows the sectors as cards grouped by stage, each with 3M and 1M against the median sector and the fundamentals.
- [ ] 21 On the map, the first tap on a bubble shows its card and the second opens the sector.
- [ ] 22 At 390 px the pinned header plus filters take at most 110 px on every tab.
- [ ] 22 Every tap target at 640 px and below is at least 44 px.
- [ ] 22 The pick checkboxes and the fund tray work on a phone; negative numbers keep their minus sign; nothing loops; reduced motion is respected; no number or label changed.
- [ ] 22 Above 640 px the page is unchanged: the same CSS, DOM order and behaviour as before this request.
