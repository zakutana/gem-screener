# Build request: the Degen level in the row and the redesigned coin detail on cymetica.com/gem-screener

**For:** the lead agent of the Cymetica SDLC pipeline
**From:** Adam (product owner, Gem Screener)
**Part 4 of 4** of one request — part 1 (the Altseason panel) is [`docs/altseason-panel/SPEC.md`](../altseason-panel/SPEC.md); do all four.
**Scope:** only (a) the **flag icons in the Project column of the Apps tab** and (b) the **coin detail panel** (the panel that opens when a row is clicked). Nothing else on the page changes: not the other columns, the sort, the gates, the filters, the tabs or the Chains tab.

> **English only.** **Method and data are your call** (paid data welcome). **Look: keep the reference** in this folder — `reference.html` and the screenshots — as exactly as your design system allows. It is a mock: the PHAR numbers are real (28 Sep 2026), the rows marked EXAMPLE are made up. Take the design, not the code; the repository is **not** a copy of what runs on your site, so build from what you see live plus this folder.

## Why

**The row.** Today a row can carry several small flag icons, each with its own tooltip (Micro, Thin liquidity, Cliff, Revenue bought with emissions, …). A degen has to hover and read them one by one, and does not. **One number per row instead: the Degen level (1–10), as a mini version of the Degen panel.** Every check runs in the background; nobody has to click anything.

**The detail.** It is a long stack, and the most useful pieces (Monthly revenue, Trajectory, "is the revenue real") are hard to find. New order, few words, big type, and **one table that shows which checks light up and which do not.**

**The report.** The existing Degen report button stays, but moves to the very bottom of the detail. It becomes the place that fills in what data alone cannot (team, audits, track record, token mechanics).

The Degen level is the one place where several checks become one number. In Part 3 "no composite score" is about the Sectors themes only. Here the level is **display only: it is never a sort key, a filter, a gate, or an input to Top Picks, Degen picks or any fund.**

## What to build

### A. The row (Apps tab)

1. **Every risk flag icon in the Project column is replaced by one mini meter:** the level as a number plus ten small segments — filled up to the level, **green 1–3, light blue 4–6, red 7–10**, hatched where the level is not fully certain (see B, range). The small "tradeable here" icon stays (it is a fact, not a risk).
2. **Hover or keyboard focus** on the meter shows a tooltip of at most 20 words: "Degen level 8/10 · Casino", the **three worst checks by name**, and one line with their numbers ("1 of 3 signers · 0 s timelock · 13.7× the float"). No formulas.
3. **Clicking the meter opens the coin's detail** like a click on the row.
4. **Nothing else is added to the row:** no report icon, no extra column. The report status lives in the detail only.
5. The Legend lists the meter, the 18 check icons of C.3 and the four colours, at most 8 words each.

### B. The Degen level (computed in the background)

Whole number 1–10: **how much of a casino a coin is.** Higher = riskier. It is not a score for attractiveness; Upside and Strength stay that. Three bands with one plain sentence each: **1–3 Blue chip** "Boring on purpose." · **4–6 Spicy** "Size it small." · **7–10 Casino** "Only money you can lose."

It is built from **18 checks in six areas.** Each check is green, light blue, red, or **not checked**. The backend runs all of them on every refresh (a visitor never triggers one, except the report). Thresholds below are our first proposal; calibrate them on your top ~30 apps and write down what you settle on.

| Area (weight) | Check | Measures | Green | Light blue | Red | Data |
|---|---|---|---|---|---|---|
| **Control** (2.5) | Admin key | who can change the rules | Safe, 3+ signers | Safe, fewer | EOA, or a 1-signer Safe | contract scan |
| | Timelock | delay before a change lands | 48 h or more | under 48 h | none, or 0 s | contract scan |
| | Admin powers | mint, pause, upgrade | none, or gated | one | two or more | contract scan |
| **Supply** (2) | Hidden supply | tokens outside the float ÷ float | under 0.25× | 0.25–1× | over 1× | holders scan |
| | Emission rate | weekly emissions ÷ float | under 4% | 4–10% | over 10% | emission data |
| | Insider flow | insider wallets to DEX or CEX, 30 d | under 0.5% of float | 0.5–1.5% | over 1.5% | holders scan |
| | Unlocks | scheduled unlocks, next 90 d | under 3% | 3–8% | over 8%, or a cliff | **live today** |
| **Earnings** (2) | Real yield | revenue ÷ next-30-day emissions **at today's price** | 2× or more | 1–2× | under 1× | **live today** (re-priced) |
| | Trend | shape of the last 12 months | steady or accelerating | ignition, or a 2.5–4.5× spike | declining, post-crash, spike over 4.5× | **live today** |
| | Reaches you | does a buyer of this token get the revenue | directly | after a stake or lock | haircut, wrapper, or under 5% share | report |
| **Liquidity** (1.5) | Slippage | what a $10K buy costs | under 1% | 1–2.5% | over 2.5% | **live today** |
| | Market cap | today's "Micro" flag | over $20M | $3–20M | under $3M | **live today** |
| | Whales | fresh wallets or top holders, % of float | under 2% | 2–5% | over 5% | holders scan |
| **Heat** (1) | Price run | 30-day change, distance to ATH | under +30% | +30–70% | over +70%, or +55% near ATH | **live today** |
| | Strength 3M | revenue growth ÷ price growth | 1× or more | 0.5–1× | under 0.5× | **live today** |
| **History** (1) | Team | who ships it | public team or entity | anonymous | anonymous, with failed projects | report |
| | Audit | is the deployed code audited | yes | sister code only | none listed | report |
| | Track record | exploits, relaunches, sister forks | clean | old exploit, repaid | open exploit, or dead siblings | report |

Seven checks already exist on the live page in some form, seven are new and fully automatic, four need the report. Data for the automatic ones (contract owner, proxy admin, Safe threshold, timelock delay, holder lists, wallet age) is on-chain; public explorers and DeFiLlama (audits, hacks) cover most of it, paid feeds welcome. **A check that cannot be run is "not checked", never green.**

**Our proposed arithmetic** (yours to change; the reference implements it under "Behind the scenes"):
- each check → a risk from 0 to 1 (green up to 0.25, light blue 0.25–0.6, red from 0.6; not checked counts as 0.5);
- an area = 60% of its worst check + 40% of the average of its checks;
- level = the sum of weight × area, rounded, at least 1 (the weights add up to 10);
- floors: a source that is not verified, or a token an EOA can mint, gives at least 8;
- **range:** run it twice, with every "not checked" as best case and as worst case. If the two levels differ, the meter hatches the segments up to the higher one and the detail says "Range 8–9 · 3 checks not scanned". The report removes most of the range.

### C. The coin detail, top to bottom

1. **Header:** logo, name, symbol · category, one plain line, "web ↗", the Trade button as today, and a small **report status icon**: dashed = not researched, solid = ready, solid with a dot = outdated.
2. **Degen level strip:** the number big in its band colour ("8/10"), "Degen level", the band's sentence, the range line ("All 18 checks in" or "Range 8–9 · 3 checks not scanned"), and the ten-segment meter with "Blue chip" and "Casino" at its ends. **No breakdown by area under it.**
3. **Checks table.** A legend line (Good · Caution · Bad · Not checked). One row per area: the area name, one **circle per check** (its own icon, the colour of its verdict; dashed grey = not checked), and on the right the area's **worst reason** as "Check name value" in that colour, or "Needs the report" when nothing in the area is checked. Hover or focus on a circle shows a tooltip: check name, verdict word, the value in one line, one line of context, and where it came from (on-chain / data / inferred / AI report) with its date; at most 20 words. Every circle is keyboard-focusable. The 18 icons must be distinct (`reference.html`, section "The 18 checks").
4. **Six key numbers in tiles:** Market cap, Revenue 30d, Emissions 30d, FDV, Upside, Strength 3M. **Every big number is green, light blue or red** by its verdict (grey only when missing); one plain caption under each. Emissions also shows the next 30 days at today's price when it differs ("≈ $1.8M at today's price"). Upside also shows **the figure on the effective cap** when the revenue goes to a staked or locked form of the token rather than the listed one ("≈5× on effective cap"); how you value that form is your call, say how in the note.
5. **Earnings:** two bars, revenue 30 d against next-30-day emissions at today's price, and one line on the gap.
6. **Monthly revenue:** the chart as it is today (13 monthly bars, the latest one hatched as partial, the same caption).
7. **Trajectory**, redesigned: the phase as a stepper (Ignition → Accelerating → Slowing; your real phase names, the current one lit), **four bars = revenue growth per month in each quarter** with the number above each bar and the last quarter highlighted, and one plain sentence ("Flat for nine months, then +74% a month over the last three."). No table.
8. **Supply**, where the data exists: one stacked bar (float · insiders · others) and, as one big number, the weekly emissions as a share of the float.
9. **Degen report card, at the very bottom, three states:**
   - *Not researched:* a dashed card, the button "Ask for Degen report", and the four dashed circles it will fill in (Reaches you, Team, Audit, Track record).
   - *Generating:* a few plain steps ticking off.
   - *Ready:* the report's eight lines as on the live site today (What it is / Money / Real or printed / Numbers / Good / Shady / The bet / Verdict), then "The report filled in" listing the checks it just resolved, the date, and when it will be redone (admin change, contract upgrade, revenue ±2×, unlock under 14 days).
   When a report is ready its circles turn from dashed to coloured and the level's range disappears.

Sections of today's detail that are not listed (Weekly history, Upside over time, the Growth windows table, "How it's calculated") are not part of this redesign. Keep any you find useful as **collapsed rows between Supply and the report**, and make sure nothing runs past the panel's edge (today the last columns of the quarter table and the Growth windows table are cut off).

### D. Colour rule

Green = good for a buyer, **light blue = caution** (as in today's Legend: amber is off Cymetica's palette), red = bad, grey or dashed = missing. The same number has the same colour in the row, the tiles, the table and the charts. Use your own palette and fonts; keep the look: dark, big readable type (body text 16 px or more, key numbers 28 px or more), few words.

### E. Agents

The coin endpoint returns the level (`level`, `low`, `high`, `band`) and all 18 checks (`id`, `area`, `verdict`, `value`, `unit`, `source`, `as_of`), with machine codes in English, units and as-of times on every number. The compact ranked list carries the level only. llms.txt and the MCP coin tool mention them.

## Acceptance — check each point

1. **Apps rows:** no risk flag icons; one mini meter (number + ten segments, band colours, hatched range) plus the "tradeable here" icon; tooltip names the three worst checks in at most 20 words; keyboard focus works; a click opens the detail; the Chains tab is unchanged.
2. **The level is 1–10 from the 18 checks**, computed in the background on every refresh, deterministic, with the rules and thresholds written down. A check that cannot run is "not checked" and widens the range; it is never counted as good.
3. **Display only:** the level is not in the sort, a filter, a gate, Top Picks, Degen picks or any fund.
4. **The detail is in the order of C**, with no area breakdown under the level strip.
5. **The checks table** has 18 checks with 18 distinct icons, four states, the tooltips of C.3, and the worst reason per area.
6. **One colour rule** on every number in the row, the tiles, the table and the charts (D).
7. **Emissions at today's price** is shown; **Upside on the effective cap** is shown where the revenue goes to a staked or locked form of the token, with the valuation method in the note.
8. **Monthly revenue** looks as today; **Trajectory** is the stepper with four quarter bars; **Supply** appears where data exists.
9. **The Degen report** sits at the bottom with the three states, fills the dashed circles when ready and firms up the level.
10. **The Legend** lists the meter, the 18 icons and the four colours, at most 8 words each.
11. **The API and agent files** carry the level and the checks as in E.
12. **Look:** the reference's look on desktop, big readable type, few words; nothing overflows the panel.
13. **A short note:** what you changed and why; for each of the 18 checks the data and rule you used and any you could not run; the level of the top 20 apps with how many checks were not scanned; a screenshot of the row and of the detail (not researched and ready).

## Reference

In this folder: [`reference.html`](reference.html) (open it in a browser: hover the meter, click the PHAR row, switch the report state above the detail, open "Behind the scenes" for the 18-check catalogue and the level function) and the screenshots [`row.png`](row.png), [`detail-not-researched.png`](detail-not-researched.png), [`detail-report-ready.png`](detail-report-ready.png), [`checks-table-tooltip.png`](checks-table-tooltip.png). Public repo `zakutana/gem-screener`, branch `spec-degen-level-detail`. The reference is a design mock, not code to copy.
