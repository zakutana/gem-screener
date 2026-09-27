# Build request: Altseason Panel for cymetica.com/gem-screener

**For:** the lead agent of the Cymetica SDLC pipeline
**From:** Adam (product owner, Gem Screener)
**Scope:** rebuild ONE component, the Altseason panel with all its subsections, on Cymetica's infrastructure at https://cymetica.com/gem-screener.

Screenshots of the working reference are attached (two also sit next to this file: `tiles-collapsed.webp`, `cycle-breakdown.webp`; they show the Czech version of the reference — English copy is in §7). **The result must look and behave like the screenshots.** There are two deliberate differences:

1. **Language:** all texts in English. Exact copy is in §7.
2. **Colours and fonts:** use your platform's existing design system. The screenshots show layout, hierarchy and chart style, not a palette to copy.

Everything else (layout, tiles, the slider, chart style and the logic behind every number) should match. The owner is very satisfied with this version, so treat it as the target, not a draft.

---

## 0. How to use this spec

- **A reference implementation exists.** It is public on GitHub: `zakutana/gem-screener`, branch `altseason-cycle-2r6d3t`. Read these files:
  - `cycle.py`: data, index, phases, trend lines, retail;
  - `cycle_backtest.py`: the locked rules `PREREG_V2` and the historical validation;
  - `audit.py` §37: an independent second implementation used as an acceptance test;
  - `template.html`: search for "Altseason panel (cycle.py)" through `function cycleChart`;
  - `ARCHITECTURE.md` §13.8 and §17.1: the written specification.

  **To see the reference UI running** (the look to match), from the repo root on that branch: `pip install -r requirements.txt`, `python tools/cycle_seed.py` (one-time history build, ~40 min, resumable), `python collector.py` (3–6 min), then `python app.py` and open the Start tab (switch to EN top-right, expand the panel, click each tile). `python build_viewer.py --lang en --view start` writes a static `gem_screener.html` instead.
  Where this document and the code disagree, **this document states intent and the code states exact arithmetic.** Ask if they conflict.
- **You own engineering choices:** stack, data vendors (paid APIs are welcome), storage, scheduling and caching. §4 says what the data must satisfy, not where it must come from.
- **You are invited to review and improve.** Do a full independent review (method, data, UI, robustness) and fix what you find. Constraints:
  - the visible result and its meaning stay as specified;
  - any change to the index or phase rules must be written down before you compute it on history, and then pass the acceptance checks in §9. Do not tune thresholds until the backtest looks good.
- Known weak spots worth your attention are listed in §10.

---

## 1. What the panel is for

The panel is an **informative map of the altseason cycle.** It is not a trading signal and it does not predict pumps. Adam's words: "the main point of the whole panel is to see, at least roughly, that the altseason is approaching its end, if one started now and lasted a year."

A user must understand the panel **at a glance**. It is aimed at crypto traders ("degens"), not analysts. Rules:
- A tile is a name, a number and one plain word. No paragraphs on tiles.
- A click opens one tall chart, TradingView-style, plus at most a few short rows.
- Explanations live behind an "i" button: at most 20 plain words, then "How it is calculated".
- Every threshold and verdict word is decided on the backend. The frontend only draws.

---

## 2. Layout (see screenshots)

A card containing, top to bottom:

1. **Five tiles in one row** (first tile wider), plus an **Expand ▾ / Collapse ▴** button on the right. Each tile is a button; clicking it opens that tile's detail, clicking it again collapses the panel.

   | Tile | Big number | Word under it |
   |---|---|---|
   | **Altseason cycle** | index, e.g. `23/100` | phase name (§5.4) |
   | **OTHERS** | OTHERS.D today, e.g. `8.04%` | status of the OTHERS.D trend line (§5.5) |
   | **BTC.D** | BTC dominance today, e.g. `58.5%` | 13-week direction: falling / rising / sideways |
   | **Retail** | retail index, e.g. `55/100` | asleep (<35) / waking up / rushing in (≥70) |
   | **Volume** | 7-day average market volume, e.g. `$105bn` | weak / normal / elevated / extreme |

   Word colours are semantic: good for alts, caution, bad/late, neutral. Use your palette.
   - Tablet: first tile full width, the others 2×2.
   - Phone: the same, with the toggle as a full-width button.

2. **The slider (always visible, collapsed too).** A horizontal bar filled to the index value (0–100) with a red tick at **T = 75**. Labels:
   - left: `CALM`;
   - under the tick: `TOP ZONE · 75`;
   - right: `WEEK OF <date>`, the date of the data. On a phone it goes on a second line.

3. **Notes** (small warning text, only when true):
   - `Stale data: Upbit (14d), …` when any source is stale (§4.3);
   - a note when the whole panel shows the previous run's data;
   - `History missing` when there is no history at all.

4. **Detail area** (when expanded): the chart of the selected tile (§6), an "i" button top-right, and for some tiles a short table.

The panel may appear on more than one page. If two instances are in the DOM at once, no id may collide (gradient ids included).

---

## 3. Time base

- **Weekly axis:** Monday 00:00 UTC stamps from 2014-07-07.
  - A stamp's daily inputs are read on the day before it (Sunday).
  - The "current" week is the newest Monday whose data is complete. In practice, week W becomes available on Tuesday.
- Charts start in **2016** (`display_from` = 2016-01-04); earlier data exists only to warm up windows.
- **Every computation at week t uses only data up to t.** No look-ahead, including the trend lines.
- **Spike cleaner:** a weekly value more than 25% away from two neighbours that agree within 10% is bad vendor data and is dropped. Example: 2020-11-30, OTHERS.D 5.95% between 10.75 and 10.83. Dropping it removes:
  - that week's OTHERS.D, OTHERS $ and breadth;
  - the breadth 13 weeks later.

  Dropped points are listed in an `anomalies` field.

---

## 4. Data: what is needed and what it must satisfy (you choose vendors)

### 4.1 Inputs

| Input | Definition | History needed | Reference source (free) |
|---|---|---|---|
| **BTC.D** weekly (+ newest daily) | BTC market cap ÷ total crypto market cap | 2014-07 → | CoinMarketCap web API `global-metrics/quotes/historical` |
| **OTHERS.D** weekly (+ newest daily) | Market cap of **ranks 11–125 ÷ top 125**, stablecoins **included**, ranked by the vendor's rank (see note) | 2014-07 → | CMC `listings/historical?date=…&limit=500` |
| **OTHERS $** | Same ranks 11–125 in USD | 2014-07 → | same |
| **Breadth** weekly | Share of the top-50 alts that beat BTC over 13 weeks. Uses that week's listing (survivorship-free); stablecoins and wrapped/staked twins excluded; coins listed < 13 weeks ago skipped | 2014-10 → | same (listing 13 weeks earlier for prices) |
| **BTC on-chain** daily | Price, MVRV ratio (not MVRV-Z), issuance USD | 2012 → | Coin Metrics community API |
| **Retail: Coinbase** daily | USD turnover (base volume × close) of BTC-USD + ETH-USD | 2015-07 → | Coinbase Exchange public candles |
| **Retail: Upbit** weekly | KRW turnover summed over **all** KRW markets | 2017-10 → | Upbit public API |
| **Retail: memecoins** daily | 30-day revenue of DeFiLlama categories Launchpad + Telegram Bot + Trading App | 2019 → (scored from first $5M day, 2023-05) | DeFiLlama fees overview (per-protocol breakdown) |
| **Retail: App Store** daily snapshot | US App Store ranks (overall top-100 and Finance top-100) of crypto apps | from launch of your ledger | Apple RSS |
| Facts (not scored) | USDT+USDC supply; Coinbase web traffic rank; AI crypto questions | recent | Coin Metrics, Tranco, Anthropic Economic Index |
| **Volume** daily | Total market 24h volume (adjusted) | 2016 → | CMC global daily |

**Note on OTHERS.D:** use the vendor's *ranked* list. CMC appends unranked derivatives (stETH, WBTC, WETH…) with large caps after rank ~199. Sorting everything by market cap pulls them into the top 125 and gives ~12% instead of ~8%. TradingView's OTHERS.D includes them, which is why TradingView reads higher. Either definition is acceptable if documented, but the trend-line acceptance values in §9 are for the ranked (CMC) definition.

**Paid alternatives are welcome** (e.g. CoinGecko Pro, Kaiko, CryptoCompare/CCData, Glassnode or Coin Metrics Pro, Artemis). Requirements:
- weekly history across **both** the 2017/18 and 2021 altseasons for every index input;
- survivorship-free breadth;
- the same definitions as above.

### 4.2 Retail rows (what people DO, not what they look up)

Deliberately excluded, do not add them:
- Google Trends, Wikipedia: lookups moved to chatbots;
- Fear & Greed: mostly price;
- YouTube statistics: its API terms forbid storing and aggregating them.

Weekly sample of each row:
- **coinbase:** mean of the daily turnover over the 30 days before the stamp (≥ 20 days present);
- **upbit:** sum of the 4 weekly candles before the stamp (all 4 present);
- **memecoins:** the value on the day before the stamp, from the first day ≥ $5M on;
- **app store:** `app_score` of the best-ranked crypto app in the newest snapshot of the 7 days before the stamp:
  - overall #1 = 100, #10 = 90, #100 = 60;
  - Finance #10 = 50, #100 = 10;
  - outside both = 5;
  - log interpolation between anchors;
  - the apps list is in `cycle.py` `APPS`.

Robinhood publishes only monthly crypto volume (press releases) with no history across 2021, so it is not a scored row. Adding it as an unscored fact is fine.

### 4.3 Robustness requirements

- **Stale beats empty.** A failed refresh never overwrites stored good data with less or with partial data.

  Example we hit: if some Upbit markets fail, the week's sum reads low and overwrites a good value. The fix is to write nothing and warn.
- **Freshness per source:** store the newest data day and a stale flag.
  - Weekly sources are stale after 10 days, daily sources after 4 days.
  - The panel names stale sources.
- Never draw NaN or Infinity.
- **The history is expensive to rebuild.** It is ~630 weekly listings plus paced calls. Persist it durably, never only in an ephemeral cache.
- **A single missing week should not blank the index for 4 weeks** (the current reference does; see §10). Your call how, but document it.

---

## 5. The method (v2; exact arithmetic in `cycle.py`)

### 5.1 Rotation (0–100, absolute scales)

Each part is clamped to 0–100. Rotation = the mean of the parts present, at least 2 of 3.
- **BTC.D drawdown:** dd = 1 − mean4(BTC.D) / max of mean4(BTC.D) over the last 52 weeks (≥ 40 values). Score = 100 × dd / 0.50.
- **OTHERS.D rise:** rise = mean4(OTHERS.D) / min of mean4 over 52 weeks − 1. Score = 100 × ln(1 + rise) / ln 3.
- **Breadth:** b = 4-week mean of breadth %. Score = 100 × (b − 25) / 65.

Why absolute scales: percentiles scored a 3–12% BTC.D dip at 60–70 in the 2022–24 bear market.

### 5.2 BTC heat (0–100)

Heat = the mean of the trailing percentiles of MVRV ratio, Puell (issuance ÷ its 365-day mean), Mayer (price ÷ 200-day mean) and Pi Cycle (111-day mean ÷ 2 × 350-day mean). Needs at least 3 of the 4.
- Percentile = mid-rank over the previous 208 weeks, current week excluded, ≥ 104 values.

### 5.3 Retail (0–100) and euphoria

- **Row score** = 100 × clamp(1 + ln(x / M) / ln 20, 0, 1), where M = the row's max over its last 208 weekly samples, current included.
  - 100 = at its 4-year high; 0 = at a twentieth of it.
  - Log scale, because retail moves 10–30× between bear and mania.
  - The first 52 weeks of each row are warm-up (not scored).
  - Zero or missing values are skipped, never passed to ln.
  - The App Store row is already 0–100 and is used as is.
- **Retail** = the mean of the rows present (≥ 1).
  - History starts 2016-08.
  - It sits flat at 100 during manias. That is correct: every row is at its high.
- **Euphoria** = (retail + heat) / 2.

### 5.4 Index and phases

- **Index** = (2 × rotation + euphoria) / 3. **T = 75.**
- **Phases** (first match wins):

| Key | English label | Rule |
|---|---|---|
| `po_vrcholu` | **Past the top** | ≥ 2 of the previous 26 weeks at index ≥ T, and index ≤ their max − 15 |
| `prehrate` | **End is near** | index ≥ T and euphoria ≥ 70 |
| `bezi` | **Altseason is on** | rotation ≥ 60, or index ≥ T |
| `zacina` | **Alts are starting** | rotation ≥ 30 and (rotation +15 vs 13 weeks ago, or an OTHERS.D breakout event in the last 13 weeks) |
| `btc_sezona` | **Only BTC runs** | heat ≥ 50 and rotation < 30 |
| `zima` | **Alts not moving yet** | otherwise |

### 5.5 Trend lines (TradingView-style, week t sees only data ≤ t)

**OTHERS.D resistance:**
- **Anchor:** the highest weekly close of the last 312 weeks (6 years, so the 2022 top stays in view until 2028).
- **Bottom:** the lowest close after the anchor that is at least 4 weeks old.
- **Line:** the tightest line from the anchor over the confirmed ±4-week pivot highs between anchor and bottom.
- **Status** (first match):
  - `pruraz` (**trend broken**): two consecutive closes more than 3% beyond the line, with no close back inside since. A retest that holds keeps it.
  - `pruraz_nepotvrzeny` (**breaking the trend**): one close beyond, or only the newest daily point.
  - `zpet_pod` (**false breakout**): a break within 13 weeks, then a close back inside.
  - `downtrend` (**falling**).
  - `bez_trendu` (**no trend**): no line, because the week is itself the extreme, there is no bottom yet, or there is no pivot.

  The breakout event used by `zacina` is the week the weekly status turns `pruraz`.

**BTC.D support:** the mirror of the above, from the lowest close (2022-11-28) under the higher lows up to the top.

**BTC.D green line (display only):** a straight line from the 2018 altseason low (weekly BTC.D minimum around 2018-01, 32.8%) through the 2022 low (37.9%), extended to today. It shows the rising floor of BTC dominance.

### 5.6 Other tile verdicts

- **BTC.D word:** change of mean4(BTC.D) over 13 weeks: ≤ −1.5 pp falling, ≥ +1.5 pp rising, otherwise sideways.
- **Volume:** 7-day mean ÷ the median of the prior year: < 0.8 weak, < 1.5 normal, < 2.5 elevated, otherwise extreme.
- **Retail tempo:** retail now − 4 weeks ago: ≥ 25 rush, ≥ 8 gradually, ≤ −8 leaving, otherwise flat.

---

## 6. Charts (one chart component for all five details)

TradingView look (Adam: "tall and sharp"):
- **Height:** 0.46 × width, clamped to 260–460 px (460 at ~1100 px wide, 260 on a phone).
- **Y axis:**
  - dominance and volume charts fit the visible data with 5% padding (OTHERS.D does **not** start at 0);
  - the index and retail charts are 0–100 with a little headroom above 100;
  - 4–6 round ticks (0/5/10/15/20% or 0/20/…/100).
- **Main series:** a 2 px line over a gradient area (≈30% opacity at the top to 0).
- **Trend lines:** 2 px, from their anchor running into an empty ~8% future margin on the right, clipped to the plot. Their future end does not stretch the y axis.
- **Value tag** (TradingView-style pill) on the right edge of the plot with the newest value, and a dotted price line from the newest point.
- A faint log-scale **right axis** for a secondary dollar series.
- **X axis:** year labels from 2016, including future years in the margin; every other year on a phone.
- Crosshair tooltip with date and values.
- A legend under the chart.
- On a phone, hide minor point labels and keep only those that carry the story.

Per tile:

| Tile | Chart | Under the chart |
|---|---|---|
| Altseason cycle | Index (area, 0–100); OTHERS in $ on the log right axis; a dashed horizontal line at 75 labelled `top zone · 75`; the three past altseason ends marked with their values (`2017: 100`, `2018: 95`, `2021: 80` — label 2017 to the left so it does not collide with 2018) | Three plain-words rows (§7.3), each with a small score chip on the right |
| OTHERS | OTHERS.D (area, fitted axis); the red resistance line; hollow marks at the anchor (`top 2022`) and the touching pivot; a green mark labelled `break <Mon YYYY>` under the point where the break started; the newest daily point | — |
| BTC.D | BTC.D (area, fitted); the red support line (anchor labelled `low 2022 · 37.9%`); the break mark; the green 2018→2022 line with its value today under its end point | — |
| Retail | Retail index (area, 0–100); OTHERS in $ on the log right axis (**no BTC line**) | A header `Retail 55 waking up · pace flat`, then a table (§7.4) |
| Volume | 7-day average $bn (area, fitted, floor 0); BTC price on the log right axis; the 2019–2020 span shaded, labelled `exchanges inflated volume then (wash trading)` (short on a phone) | — |

The panel must also render cleanly on a phone (375 px), with no horizontal overflow.

---

## 7. English copy (use as written; tone: plain, short, no jargon)

### 7.1 Tiles, slider, notes

- Tiles: `ALTSEASON CYCLE`, `OTHERS`, `BTC.D`, `RETAIL`, `VOLUME`
- Toggle: `Expand ▾` / `Collapse ▴`
- Slider: `CALM` · `TOP ZONE · 75` · `WEEK OF <Mon D>`
- Words:
  - phases: `Alts not moving yet`, `Only BTC runs`, `Alts are starting`, `Altseason is on`, `End is near`, `Past the top`;
  - OTHERS: `trend broken`, `breaking the trend`, `false breakout`, `falling`, `no trend`;
  - BTC.D: `falling`, `rising`, `sideways`;
  - retail: `asleep`, `waking up`, `rushing in`;
  - volume: `weak`, `normal`, `elevated`, `extreme`;
  - tempo: `rush`, `gradually`, `leaving`, `flat`;
  - missing: `no history` or `data missing`.
- Notes:
  - `Stale data: <source> (<N>d), …`
  - `The panel data is from the previous run.`

### 7.2 Info popovers ("i")

- **Altseason cycle:** "**Altseason cycle** — how close an altseason's end is. 75 = where the 2018 and 2021 altseasons ended."
  - How it is calculated: "⅔ rotation into alts (falling BTC dominance, rising OTHERS, how many alts beat BTC) and ⅓ euphoria (retail and how overheated Bitcoin is). 'End is near' = the index at 75 or more and euphoria at 70 or more; 'Past the top' = the index 15 below its high of the last half-year."
- **OTHERS:** "**OTHERS.D** — small alts' share of the market. Breaking the line from the 2022 top = money moving into alts."
  - How it is calculated: "a TradingView-style line — from the highest weekly close of 6 years over the lower highs down to the bottom. A break = two weekly closes more than 3% above the line; each week sees only its own past."
  - Add one line if your OTHERS.D definition differs from TradingView's.
- **BTC.D:** "**BTC dominance** — Bitcoin's share of the market. When it falls, money flows into alts."
  - How it is calculated: "the red line runs from the 2022 low under the higher lows (as on TradingView); a break = two weekly closes more than 3% below it. The green line runs from the 2018 altseason low through the 2022 low to today: BTC dominance's rising floor."
- **Retail:** "**Retail** — how much people actually trade, against each row's own 4-year high. High = a top is usually near."
  - How it is calculated: "Coinbase (US), Upbit (Korea), memecoins on-chain and the top crypto app. A row reads 100 at its 4-year high and 0 at a twentieth of it (log scale); the index = the mean of the rows. Blue area = retail, red = OTHERS in dollars."
  - "Google, Wikipedia and Fear & Greed are not measured: lookups moved into chatbots, and Fear & Greed is mostly price."
- **Volume:** "**Volume** — the whole market's daily trading (7-day average) against its 1-year norm. Tops ran 2–4×, but so did crashes."
  - "2019–20 contains fake exchange volume. Alts' share ex stablecoins: up to 76% in May 2021."

### 7.3 Altseason cycle breakdown (three rows under the chart, this week's numbers)

1. **Is money moving into alts?** (chip = rotation), three short lines:
   - `BTC dominance −2% from its 1-year high (−30 to −50% in an altseason)`
   - `small alts +23% above their 1-year low (+100% or more in an altseason)`
   - `only 24% of alts beat BTC (80%+ in an altseason)`
2. **Is the market euphoric?** (chip = euphoria): `people trade at 55/100 of their high · Bitcoin overheated at 46/100`
3. **Altseason cycle** (chip = index): `⅔ money into alts + ⅓ euphoria. From 75 (with euphoria from 70): "End is near".`

### 7.4 Retail table

Columns: *(name)* | `today` | `vs the high` | `score`. On a phone each row takes two lines.

| Row | today | vs the high | score |
|---|---|---|---|
| `Coinbase (US)` | `$1.1bn/day` | bar + `35% of the 2024 high` | chip |
| `Upbit (Korea)` | `43tn KRW / month` | bar + `13% of the 2024 high` | chip |
| `Memecoins on-chain` | `$58.2M / month` | bar + `23% of the 2025 high` | chip |
| `Top crypto app` | `fomo #91` | `tops: Coinbase #1` | chip |
| `New stablecoins` | `+$16.2bn / 13 weeks` | `a fact, no score` | — |
| `Coinbase traffic` | `#1,010` | bar + `81% of the 2021 top` | — |
| `AI questions on crypto` | `0.50% of chats` | `Claude, Feb 2026` | — |

Score chip colours: < 35 calm, < 70 caution, ≥ 70 hot.

---

## 8. Backend contract (suggested)

One JSON document per refresh (the reference calls it the `cycle` block, documented field by field in ARCHITECTURE §13.8). It should carry:
- `version`, `as_of`, `generated`, `rules` (every threshold);
- `index`, `phase`, `rotation`, `euphoria`, `heat`;
- full weekly `series` from 2014-07 (index, rotation, euphoria, retail, heat, phase, btcd, othersd, breadth, others_usd, btc, the four heat metrics, breakout weeks, and the raw weekly retail samples);
- `components` per tile, with the verdict words decided on the backend and the line objects (anchor, touch, bottom, slope, status, since, back, line_now, dist_pct, latest_line);
- `events` P0/P1/P2/P2b with `index_at_events`;
- `freshness` per source, `anomalies`.

Keep it NaN-free.

Refresh: at least daily. The reference runs every 6 h; weekly values change once a week, daily points (newest OTHERS.D, BTC.D, volume) every day.

**Forward ledger:** append one line per closed week (week, index, phase, rotation, euphoria, retail, heat) to durable storage. It is the honest test of the method from now on.

---

## 9. Acceptance (reference numbers, real data, week of 2026-09-21)

**Historical events** (P0/P1/P2 = weekly BTC.D minimum in the stated windows):

| Event | Week | Index |
|---|---|---|
| P0 | 2017-06-19 | 99.7 |
| P1 | 2018-01-15 | 95.2 |
| P2 | 2021-05-17 | 79.7 |
| P2b | 2021-11 | 62.3 |

- The index is ≥ 75 in ~8.4% of evaluated weeks (from 2016-08), in exactly three episodes (2017-04, 2017-12, 2021-05). It stays < 75 through 2023–2026: max 46.1, today 23.4, phase `Alts not moving yet`.
- "End is near" first lit ~10 weeks before P0, 1 week before P1 and 2 weeks before P2, and never away from a top.

**Trend lines (ranked OTHERS.D definition):**
- OTHERS.D: line from **2022-01-03 (20.43%)** through the **2024-12-02** high; status `trend broken` since **2026-05-11**.
- BTC.D: line from **2022-11-28 (37.88%)** through the **2024-12-09** low; broken since **2025-08-25**.

**Retail (±5):**
- tops: 2017-12 100, 2018-01 97, 2021-05 99, 2024-12 93;
- bottoms: 2018-12 20, 2023-09 14;
- today ~55 (Coinbase ~64 = 35% of its Dec 2024 level).

**Engineering:**
- A second, independent implementation of every stored number, as in the reference `audit.py` §37. It must agree week by week, and deliberately wrong phases, lines or NaN must fail it.
- UI checked at 1200 px and 375 px:
  - chart heights measured in the DOM;
  - the value tag present;
  - no horizontal overflow;
  - no console errors.

If your data vendor differs, small deviations are expected. Explain any deviation larger than the tolerances above.

---

## 10. Known weak spots (from an independent review; improve freely)

1. **One missing week blanks the index for 4 weeks.** 4-week means require all 4 values; BTC heat requires the exact Sunday value. Suggested fix: 3 of 4 values, and the latest value within the prior 7 days.
2. **Data sources can break silently.** The reference uses unofficial or free endpoints (the CMC web API especially). Prefer robust vendors, alert your ops on failure, and show freshness on the panel.
3. **"Past the top" is late by design** (1–2 months after the top). In 2017 it fired between two alt tops. The panel is a map, not a sell signal, so keep the copy honest.
4. **Only two historical altseasons** exist. v2 was designed with both in view, so it fits them by construction. The forward ledger is the real test.
5. **The retail mix changes over time:** 2017 has only Coinbase, 2021 adds Upbit, and memecoins and App Store data are recent. Document how you handle it.

---

## 11. Deliverables

1. The panel live at cymetica.com/gem-screener, in English, in your design system, matching the screenshots.
2. The backend job with durable history, freshness, anomalies and the forward ledger.
3. A short review note: what you changed or improved and why, which data vendors you chose, and the acceptance results from §9.
