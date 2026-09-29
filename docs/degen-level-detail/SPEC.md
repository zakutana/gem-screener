# Build request: the Degen level in the row and the redesigned coin detail on cymetica.com/gem-screener

**For:** the lead agent of the Cymetica SDLC pipeline
**From:** Adam (product owner, Gem Screener)
**Part 4 of 4** of one request — part 1 (the Altseason panel) is [`docs/altseason-panel/SPEC.md`](../altseason-panel/SPEC.md); do all four. The files of parts 1 to 3 say "three parts": this is the fourth, and it belongs to the same request.
**Scope:** only (a) the **flag icons in the Project column of the Apps tab**, (b) the **coin detail panel** (the panel that opens when a row is clicked) and (c) the **flag section of the Legend**. Nothing else on the page changes: not the other columns, the sort, the gates, the filters, the tabs or the Chains tab. **Part 1's "do not change anything else" limits part 1 only; this part changes the row, the detail and the Legend as written here.**

> **English only.** **Method and data are your call** (paid data welcome). **Look: keep the reference** in this folder — `reference.html` and the screenshots — as exactly as your design system allows. It is a mock: every name and number in it is made up. Take the design, not the code; the repository is **not** a copy of what runs on your site, so build from what you see live plus this folder.

## Why

**The row.** Today a row can carry several small flag icons, each with its own tooltip (Micro, Thin liquidity, Cliff, Revenue bought with emissions, …). A degen has to hover and read them one by one, and does not. **One number per row instead: the Degen level (1–10), as a mini version of the Degen panel.** Every check runs in the background; nobody has to click anything.

**The detail.** It is a long stack, and the most useful pieces (Monthly revenue, Trajectory, "is the revenue real") are hard to find. New order, few words, big type, and **one table that shows which checks light up and which do not.**

**The report.** The existing Degen report button stays, but moves to the very bottom of the detail. It does two things: it fills in the four checks that data alone cannot answer (team, audits, track record, token mechanics), and it shows a short write-up that reads at a glance: a calm card with the verdict, what it is, the good, the shady and the bet, and no table.

The Degen level is the one place where several checks become one number. In Part 3 "no composite score" is about the Sectors themes only. Here the level is **display only: it is never a sort key, a filter, a gate, or an input to Top Picks, Degen picks or any fund.** Higher means riskier, so a coin can have a high Degen level and still be a Degen pick: the level does not replace the Degen gates and does not change them.

## What to build

### A. The row (Apps tab)

1. **Every risk flag icon in the Project column is replaced by one mini meter:** the level as a number plus ten small segments — filled up to the level, **green 1–3, light blue 4–6, red 7–10**, and with **dashed outlines** on the segments where the level is not fully certain (see B, range; diagonal hatching stays reserved for the partial month in Monthly revenue). The small "tradeable here" icon stays (it is a fact, not a risk).
2. **Where the removed flags go; nothing is dropped silently.** Micro → Market cap · Thin liquidity → Slippage · Cliff and % in 90d → Unlocks · Revenue bought with emissions → Real yield · Post-crash, Declining and No trend → Trend · No holder share → Reaches you · New and Stale data → the data-quality rule in B. "No data" (no stablecoin data) is a Chains-tab flag and stays there.
3. **No tooltip on the meter.** It is a picture, not a control; the row's other tooltips stay as they are.
4. **Clicking the row (or the meter) opens the coin's detail**, and Enter does the same from the keyboard.
5. **Nothing else is added to the row:** no report icon, no extra column. The report status lives in the detail only.
6. **The Legend button and panel stay.** The flag section keeps the entries of every icon that still exists: the "tradeable here" icon and every flag still shown on the Chains tab. It gains the mini meter, the 18 check icons of C.3 and the colours (including "dashed = missing" and "solid grey = does not apply"), at most 8 words each. Columns, Tags and Trajectory words stay as they are. Clicking the "tradeable here" icon still opens the Legend on its entry, as a flag does today.

### B. The Degen level (computed in the background)

Whole number 1–10: **how much of a casino a coin is.** Higher = riskier. It is not a score for attractiveness; Upside and Strength stay that. Three bands with one plain sentence each: **1–3 Blue chip** "Boring on purpose." · **4–6 Spicy** "Size it small." · **7–10 Casino** "Only money you can lose."

It is built from **18 checks in six areas.** Each check is green, light blue, red, or **not checked**. The backend runs all of them on every refresh (a visitor never triggers one, except the report). Thresholds below are our first proposal; calibrate them on your top ~30 apps and write down what you settle on.

| Area (weight) | Check | Measures | Green | Light blue | Red | Data |
|---|---|---|---|---|---|---|
| **Control** (2.5) | Admin key | who can change the rules | Safe: 3+ signatures and at least half the owners | Safe: 2 signatures, or under half the owners | EOA, or 1 signature | contract scan |
| | Timelock | delay before a change lands | 48 h or more | 24–48 h | under 24 h, or none | contract scan |
| | Admin powers | mint, pause, upgrade | none, or gated | one | two or more | contract scan |
| **Supply** (2) | Hidden supply | tokens that can leave staking or locks on the holder's own request ÷ float | under 0.25× | 0.25–1× | over 1× | holders scan |
| | Emission rate | weekly emissions ÷ float | under 4% | 4–10% | over 10% | emission data |
| | Insider flow | insider wallets to DEX or CEX, 30 d | under 0.5% of float | 0.5–1.5% | over 1.5% | holders scan |
| | Unlocks | scheduled unlocks, next 90 d | under 3% | 3–8% | over 8%, or a cliff | **live today** |
| **Earnings** (2) | Real yield | revenue ÷ next-30-day emissions **at today's price** | 2× or more | 1–2× | under 1× | **live today** (re-priced) |
| | Trend | shape of the last 12 months | steady or accelerating | ignition, slowing, no clear trend, or a 2.5–4.5× spike | declining, post-crash, or a spike over 4.5× | **live today** |
| | Reaches you | does a buyer of this token get the revenue | directly | after a stake or lock | haircut, wrapper, or under 5% share | report |
| **Liquidity** (1.5) | Slippage | what a $10K buy costs | under 1% | 1–2.5% | over 2.5% | **live today** |
| | Market cap | today's "Micro" flag | over $20M | $3–20M | under $3M | **live today** |
| | Whales | fresh wallets (first transaction under 60 days ago) or top holders, % of float | under 2% | 2–5% | over 5% | holders scan |
| **Heat** (1) | Price run | 30-day change, distance to ATH | under +30% | +30–70% | over +70%, or +53% within 10% of the ATH | **live today** |
| | Strength 3M | revenue growth ÷ price growth | 1× or more | 0.5–1× | under 0.5× | **live today** |
| **History** (1) | Team | who ships it | public team or entity | anonymous | anonymous, with failed projects | report |
| | Audit | is the deployed code audited | yes | sister code only | none listed | DefiLlama list + report |
| | Track record | exploits, relaunches, sister forks | clean | old exploit, repaid | open exploit, or dead siblings | report |

Seven checks already exist on the live page in some form, seven are new and fully automatic, four use the report (Audit starts from DefiLlama's audit list; the report adds what the audits cover). Data for the automatic ones (contract owner, proxy admin, Safe threshold, timelock delay, holder lists, wallet age) is on-chain; public explorers and DeFiLlama (audits, hacks) cover most of it, paid feeds welcome. **A check that cannot be run is "not checked", never green.**

**Reading the table**
- **Cells are literal.** "Under X" and "over X" exclude X, "X or more" includes X, "A–B" includes both ends. So a real yield of exactly 2× is green and an emission rate of exactly 10% is light blue. Decide the colour on the raw value, not on a computed score, so the edges are not left to rounding.
- **Definitions.** *Float* is the circulating supply behind today's market cap. An *insider* is a wallet provably tied to the project, on-chain or in its own docs (the deployer, the owners of the admin Safe, the recipients of the founding allocation), never a guess; a tooltip says "inferred" when any doubt is left. Vesting unlocks belong to Unlocks and are not counted twice in Hidden supply.
- **Other chains.** Admin key and Admin powers have equivalents outside EVM (upgrade, mint and freeze authority); use them. A check that does not exist for an app (for example a timelock on a chain without one) is **n/a**: grey with a solid outline, left out of its area, and it does not widen the range.
- **Data quality** (the job of today's "New" and "Stale data" flags). With under six months of data, Trend, Price run and Strength 3M are "not checked: under six months of data". If the latest data point is over 10 days old, Real yield, Trend, Slippage, Market cap, Price run and Strength 3M are "not checked: stale data". Both widen the range like any missing check, and the level strip says why.

**Our proposed arithmetic** (yours to change; the reference implements it under "Behind the scenes"):
- each check → a risk from 0 to 1 (green up to 0.25, light blue 0.25–0.6, red from 0.6; not checked counts as 0.5);
- an area = 60% of its worst check + 40% of the average of its checks;
- level = the sum of weight × area, rounded, at least 1 (the weights add up to 10);
- floors: two facts from the contract scan give at least 8 — the source of the main token or staking contract is not verified, or an EOA can mint without a cap. They are not checks of their own; the Admin powers tooltip names them;
- **range:** run it twice, with every "not checked" as best case and as worst case. If the two levels differ, the meter outlines the segments up to the higher one with dashes and the detail says "Range 8–9 · 3 checks need the report". The report removes most of the range.
- **Before it goes live,** run the level on every app and put the distribution in your note: how many apps at each level, how many with a range wider than two levels. If more than a third are that uncertain, tell us; we would rather pre-generate reports for the top apps than show a wall of dashed meters.

### C. The coin detail, top to bottom

1. **Header:** logo, name, symbol · category, one plain line, "web ↗", the Trade button as today, and a small **report status icon**: dashed = not researched, solid = ready, solid with a dot = outdated. **Keep every link other parts of this request add to the detail** (for example the CoinGecko and DEXTools links of part 3).
2. **Degen level strip:** the number big in its band colour ("8/10"), "Degen level", the band's sentence, the range line ("All 18 checks in" or "Range 8–9 · 3 checks need the report"), and the ten-segment meter with "Blue chip" and "Casino" at its ends. **No breakdown by area under it.**
3. **Checks table.** A legend line (Good · Caution · Bad · Needs report). One row per area: the area name, one **circle per check** (its own icon, the colour of its verdict; dashed grey = missing: "Needs report" for the report checks, "Needs history" or "Stale data" from the data-quality rule, "Not scanned" for an automatic check that could not run; solid grey = does not apply), and on the right the area's **worst reason** as "Check name value" in that colour, or "Needs the report" when nothing in the area is checked. Hover or focus on a circle shows a tooltip: check name, verdict word, the value in one line, one line of context, and where it came from (on-chain / data / inferred / AI report) with its date; at most 20 words. Every circle is keyboard-focusable. The 18 icons must be distinct (`reference.html`, section "The 18 checks").
4. **Six key numbers in tiles:** Market cap, Revenue 30d, Emissions 30d, FDV, Upside, Strength 3M. **Every big number is green, light blue or red** by its verdict (grey only when missing); one plain caption under each. Emissions also shows the next 30 days at today's price when it differs ("≈ $1.5M at today's price"). Upside also shows **the figure on the effective cap** when the revenue goes to a staked or locked form of the token rather than the listed one ("≈6× on effective cap"); how you value that form is your call, say how in the note. Upside keeps its live tier colour in the row and in the tile, and its effective-cap line is light blue. **The effective-cap figure is only shown: the sort, the gates and Top Picks keep using the headline Upside exactly as today.**
5. **Earnings:** two bars, revenue 30 d against next-30-day emissions at today's price, and one line on the gap.
6. **Monthly revenue:** the chart as it is today (13 monthly bars, the latest one hatched as partial, the same caption).
7. **Trajectory**, redesigned: the phase as a stepper (Ignition → Accelerating → Slowing; your real phase names, the current one lit), **four bars = revenue growth per month in each quarter** with the number above each bar and the last quarter highlighted, and one plain sentence ("Flat for nine months, then +61% a month over the last three."). No table. The stepper and the bars use the colour of the Trend check (light blue for Ignition), not a colour of their own.
8. **Supply**, where the data exists: one stacked bar (float · insiders · others) and, as one big number, the weekly emissions as a share of the float.
9. **Degen report card, at the very bottom, three states:**
   - *Not researched:* a dashed card, the button "Ask for Degen report", and the four dashed circles it will fill in (Reaches you, Team, Audit, Track record).
   - *Generating:* a few plain steps ticking off.
   - *Ready:* **calm, not colourful, and a little more text is welcome.** No table and no coloured boxes: one neutral card, sections stacked with a small label above each text, thin lines between them, a date in the corner. Colour only where it carries meaning: a rule in the level's band colour beside the Verdict, green ✓ and red ✕ marks in front of the Good and Shady lines, and the four small icons in "Filled in above". Sections, top to bottom: **Verdict** (one line, big), **What it is** (two sentences, including where the money comes from), **Good** (up to 3 sentences), **Shady** (up to 3 sentences), **The bet** (one or two sentences and the one metric to watch), **Filled in above** (the four checks the report just resolved, one line each with the check's icon; each has the same tooltip as its circle). About 150 words in total. One small line says when it will be redone (admin change, contract upgrade, revenue ±2×, unlock nearby). Do not repeat what the tiles and Earnings already show (the numbers).
   **Sources and cost.** Every claim about a project, a team or a wallet links its source (in the tooltip or a footnote) and is worded as what the source says ("no team is listed"), never as an accusation. Limit how often a visitor can ask (rate limit or sign-in, your call) and cache the result.
   When the report is ready, the four circles in the checks table turn from dashed to coloured (their tooltips say "AI report" and the date) and the level's range disappears.

Sections of today's detail that are not listed (Weekly history, Upside over time, the Growth windows table, "How it's calculated") are not part of this redesign. Keep any you find useful as **collapsed rows between Supply and the report**, and make sure nothing runs past the panel's edge (today the last columns of the quarter table and the Growth windows table are cut off).

### D. Colour rule

Green = good for a buyer, **light blue = caution** (as in today's Legend: amber is off Cymetica's palette), red = bad, grey or dashed = missing. These colours judge one coin for a buyer of that coin; the Altseason panel (part 1) colours its words for the market. They share a palette, not a meaning. The same number has the same colour in the row, the tiles, the table and the charts. **Do not use the brand accent for anything that carries a verdict**: it is close to light blue. Charts without a verdict (Monthly revenue) may use it. Use your own palette and fonts; keep the look: dark, big readable type (body text 16 px or more, key numbers 28 px or more), few words.

### E. Agents

The coin endpoint returns the level (`level`, `low`, `high`, `band`) and all 18 checks (`id`, `area`, `verdict`, `value`, `unit`, `source`, `as_of`), with machine codes in English (one vocabulary for the whole API, for example `insufficient_history`, `stale_data`, `needs_report`, `not_scanned`, `not_applicable`; part 3 already asks for `insufficient_history`), units and as-of times on every number. The compact ranked list carries the level only. The report endpoint keeps the full eight lines (What it is / Money / Real or printed / Numbers / Good / Shady / The bet / Verdict) for agents; the detail shows the sections listed in C.9. If the site publishes llms.txt or an MCP coin tool, they mention them.

## Acceptance — check each point

1. **Apps rows:** no risk flag icons; one mini meter (number + ten segments, band colours, dashed-outline range) plus the "tradeable here" icon; **no tooltip on the meter**; a click or Enter on the row opens the detail; every removed flag has its place as in A.2; the Chains tab is unchanged.
2. **The level is 1–10 from the 18 checks**, computed in the background on every refresh, deterministic, with the rules and thresholds written down and read literally at the edges (B). A check that cannot run is "not checked" and widens the range; it is never counted as good. The two floors and the n/a rule are implemented as written.
3. **Display only:** the level is not in the sort, a filter, a gate, Top Picks, Degen picks or any fund, and neither is the effective-cap Upside.
4. **The detail is in the order of C**, with no area breakdown under the level strip.
5. **The checks table** has 18 checks with 18 distinct icons, five states (green, light blue, red, dashed = missing, solid grey = n/a), the tooltips of C.3, and the worst reason per area.
6. **One colour rule** on every number in the row, the tiles, the table and the charts (D).
7. **Emissions at today's price** is shown; **Upside on the effective cap** is shown where the revenue goes to a staked or locked form of the token, with the valuation method in the note.
8. **Monthly revenue** looks as today; **Trajectory** is the stepper with four quarter bars; **Supply** appears where data exists.
9. **The Degen report** sits at the bottom with the three states; when ready it is one calm card (Verdict, What it is, Good, Shady, The bet, about 150 words, colour only on the verdict rule, the ✓/✕ marks and the four icons), lists the four checks it filled in, turns their circles from dashed to coloured and firms up the level.
10. **The Legend** stays and is updated as in A.6: it keeps the entries for every icon that still exists (including the Chains tab's flags), and lists the meter, the 18 icons and the colours, at most 8 words each.
11. **The API and agent files** carry the level and the checks as in E.
12. **Look:** the reference's look on desktop, big readable type, few words; nothing overflows the panel.
13. **Data quality:** an app with under six months of data, or with stale data, shows the affected checks as not checked, and the level strip says why.
14. **A short note:** what you changed and why; for each of the 18 checks the data and rule you used and any you could not run; the distribution of levels over all apps (B); the level of the top 20 apps with how many checks were not scanned; a screenshot of the row and of the detail (not researched and ready).

## Reference

In this folder: [`reference.html`](reference.html) (open it in a browser: click the first row, switch the report state above the detail, hover the circles, open "Behind the scenes" for the 18-check catalogue and the level function) and the screenshots [`row.png`](row.png), [`detail-not-researched.png`](detail-not-researched.png), [`detail-report-ready.png`](detail-report-ready.png), [`checks-table-tooltip.png`](checks-table-tooltip.png). Public repo `zakutana/gem-screener`, branch `spec-degen-level-detail`. The reference is a design mock, not code to copy.
