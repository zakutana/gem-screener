# Build request: Altseason Panel for cymetica.com/gem-screener

**For:** the lead agent of the Cymetica SDLC pipeline
**From:** Adam (product owner, Gem Screener)
**Scope:** rebuild ONE component, the Altseason panel with all its subsections, on Cymetica's infrastructure at https://cymetica.com/gem-screener.

> **HOW TO READ THIS SPEC — three levels of freedom:**
> 1. **Method, data, architecture: inspiration only.** This is our proposal, built by one developer on free data. Take it as a starting point and improve anything you judge better: formulas, thresholds, data sources, retail and AI signals (§4.4), robustness. You don't need to ask; just document what you changed and why (§11).
> 2. **Texts: may change, but stay ultra degen-friendly.** Reword freely, but keep the rules of §1: a tile is a name, a number and one plain word; no jargon and no paragraphs; explanations stay behind the "i" button in at most 20 plain words; every number is explained with this week's own numbers. §7 is our copy, a good default, not a contract.
> Separate from the Altseason panel: **Appendix B** asks you to improve how chains are valued on the Chains tab, **Appendix C** the Sectors tab's theme chart.
>
> 3. **Design: keep it the same.** The owner likes the current design a lot. Keep the layout and the look as in the reference: the five tiles in one row with the wider first tile, the always-visible slider with the top-zone tick, one tall TradingView-style chart per tile (fitted axis, gradient area, value pill on the right, trend lines running into the future margin, year labels, legend), the rows under the charts, and the phone layout. Only the colours and fonts come from your design system.

The look is defined by the reference code (`template.html`) and this spec; running it is optional, if you want to see the charts live (§0). All texts are in English (our copy is in §7).

> **WHAT TO REPLACE on cymetica.com/gem-screener — on TWO tabs, with ONE module.** The existing "Altseason Index" card appears in two versions today:
> - **Top Picks tab:** a compact strip — `68%`, "Altseason index · In between", a bar from *BTC SEASON* to *ALTSEASON*. Screenshot: `current-top-picks-tab.webp`.
> - **Sectors tab:** a wider card — `68%`, "Altseason index · In between (3 months ago 22%)", "Share of the top-50 altcoins that beat BTC over ~90 days…", the same bar, a "last 40 weeks" sparkline and BTC 1M / 3M. Screenshot: `current-sectors-tab.webp`.
>
> **Replace both with the same new Altseason panel described here** — one component, identical on both tabs (same tiles, slider, charts, texts), each in the place of the old card. Not a compact variant on one tab and a full one on the other. The reference does exactly this: the one panel renders on its Start tab and above its Sectors tab.
>
> **SCOPE — READ FIRST.** Build or replace **only the Altseason panel** (the card with the five tiles *Altseason cycle · OTHERS.D · BTC.D · Retail · Volume*, its slider, its detail charts and info popovers). **Do not change anything else** on cymetica.com/gem-screener — no other sections, tables, tabs, filters, navigation or styles. The reference repository contains the whole Gem Screener; everything outside the files and sections named in §0 (the apps/chains screener, themes, the reference's own sector tables, degen view, backtest.py, liquidity, unlocks, etc.) is **out of scope — ignore it.** On your site the only change is the Altseason card on the Top Picks and Sectors tabs; everything else on those tabs stays.
>
> **The repository is a REFERENCE, not code to copy.** Use it mainly for the intended look, then for how we compute everything; you may run it to compare. Then build the panel natively in your own stack, with your own data pipeline, components and design system. Do not copy the repository, its files or its single-file HTML template into your product.
>
> **English only — ignore all Czech.** The reference is Czech-first: Czech UI text, Czech data keys (`zima`, `prehrate`, `pruraz`, `spi`…), Czech comments, commit messages and log lines. None of it goes into your build. Every user-visible string is English (§7 has the copy); name your own keys and code in English too (the Czech keys map to the English labels in §5.4, §7.1).
>
> **Data sources are your choice.** Pull the data from wherever you judge best — your existing feeds, paid APIs, your own indexers. The sources the reference uses (free CMC web API, Coin Metrics community, Upbit, Coinbase candles, DeFiLlama, Apple RSS) are only examples of what works; §4 lists what the data must satisfy, not where it must come from.
>
> **Architecture is your choice.** The reference is a *local desktop app*: a Python script (`collector.py`) fetches everything and writes one `snapshot.json`, which is embedded into a single static HTML file; `app.py` serves it on localhost (or as a Windows exe), and CI publishes the static page. There is no real server, database or API. You will change it on your side as you see fit; one natural client–server mapping, only as a suggestion:
> - **Backend worker (scheduled, e.g. every 6 h):** fetch, validate, compute the whole `cycle` result (§5) and append the weekly ledger. All computation happens here, never in the browser and never per request.
> - **Storage:** the long weekly/daily history, the latest computed result, the forward ledger and per-source freshness — in your database or object store, durable (not an ephemeral cache).
> - **API:** one read endpoint returning the latest computed result (the JSON contract of §8), cacheable; optionally a history endpoint.
> - **Frontend component:** fetches that JSON and only draws (tiles, slider, charts, popovers). It never decides a verdict or recomputes a number.
> - The reference's local-only parts (`app.py`, the exe build, the Refresh/Quit buttons, embedding JSON into HTML, the Czech/English switch) are not needed — the panel is English only.

---

## 0. How to use this spec

- **A reference implementation exists.** It is public on GitHub: `zakutana/gem-screener`, branch `altseason-cycle-2r6d3t`. Read these files:
  - `cycle.py`: data, index, phases, trend lines, retail;
  - `cycle_backtest.py`: the locked rules `PREREG_V3` (v3, the one the panel runs) and the historical validation;
  - `audit.py` §37: an independent second implementation used as an acceptance test;
  - `template.html`: search for "Altseason panel (cycle.py)" through `function cycleChart`;
  - `ARCHITECTURE.md` §13.8 and §17.1: the written specification.

  **To see the reference UI running** (the look to match), from the repo root on that branch: `pip install -r requirements.txt`, `python tools/cycle_seed.py` (one-time history build, ~40 min, resumable), `python collector.py` (3–6 min), then `python app.py` and open the Start tab (switch to EN top-right, expand the panel, click each tile). `python build_viewer.py --lang en --view start` writes a static `gem_screener.html` instead.
  Where this document and the code disagree, **this document states intent and the code states exact arithmetic.** Ask if they conflict.
- **You own engineering choices:** stack, data vendors (paid APIs are welcome), storage, scheduling and caching. §4 says what the data must satisfy, not where it must come from.
- **You have a free hand to review, change and improve** the method, data, architecture, robustness and wording (see the three levels at the top). The one thing to keep: the design — the panel must look like the reference (in your colours, in English) and stay ultra degen-friendly. Recommendation, not a rule: if you change the index or phase rules, write the new rules down before computing them on history and compare against §9, so the result is not tuned to the two known altseasons.
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

## 2. Layout (see the reference)

A card containing, top to bottom:

1. **Five tiles in one row** (first tile wider), plus an **Expand ▾ / Collapse ▴** button on the right. Each tile is a button; clicking it opens that tile's detail, clicking it again collapses the panel.

   | Tile | Big number | Word under it |
   |---|---|---|
   | **Altseason cycle** | index, e.g. `23/100` | phase name (§5.4) |
   | **OTHERS.D** | OTHERS.D today, e.g. `8.04%` | status of the OTHERS.D trend line (§5.5) |
   | **BTC.D** | BTC dominance today, e.g. `58.5%` | `support broken` when its support line (§5.5) is broken, otherwise the 13-week direction: falling / rising / sideways |
   | **Retail** | retail index, e.g. `55/100` | asleep (<35) / waking up / rushing in (≥70) |
   | **Volume** | 7-day average market volume — what it includes is your call (the reference: spot on all exchanges incl. DEXs), e.g. `$105bn` | weak / normal / elevated / extreme (against its 1-year norm; no multiplier on the tile — degens don't read it) |

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

The panel appears on two tabs (Top Picks and Sectors). If both instances are in the DOM at once, no id may collide (gradient ids included); opening a tile on one may, but need not, open it on the other.

---

## 3. Time base

- **Weekly axis:** Monday 00:00 UTC stamps from 2014-07-07.
  - A stamp's daily inputs are read on the day before it (Sunday); BTC heat and the memecoin row take the newest value among the 7 days before it, so one late day does not blank the week.
  - The "current" week is the newest Monday whose data is complete. In practice, week W becomes available on Tuesday.
- Charts start in **2016** (`display_from` = 2016-01-04); earlier data exists only to warm up windows.
- **Every computation at week t uses only data up to t.** No look-ahead, including the trend lines.
- **Spike cleaner:** a weekly value more than 25% away from two neighbours that agree within 10% is bad vendor data and is dropped. Example: 2020-11-30, OTHERS.D 5.95% between 10.75 and 10.83. Dropping it removes:
  - that week's OTHERS.D, OTHERS $ and breadth;
  - the breadth 13 weeks later.

  The newest week has no right neighbour: judge it by the two weeks before it and hold it back until the next week exists. Dropped points are listed in an `anomalies` field.
- **4-week means** (`mean4`) average the weeks present, **at least 3 of the 4**, so one lost week never blanks the index.

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
| **Retail: Coinbase** daily | USD turnover (base volume × close) of BTC-USD + ETH-USD; a day counts only when both pairs have it (ETH from 2016-05) | 2015-07 → | Coinbase Exchange public candles |
| **Retail: Upbit** weekly | KRW turnover summed over **all** KRW markets | 2017-10 → | Upbit public API |
| **Retail: memecoins** daily | 30-day revenue of DeFiLlama categories Launchpad + Telegram Bot + Trading App | 2019 → (scored from first $5M day, 2023-05) | DeFiLlama fees overview (per-protocol breakdown) |
| **Retail: App Store** daily snapshot | US App Store ranks (overall top-100 and Finance top-100) of crypto apps | from launch of your ledger | Apple RSS |
| Facts (not scored) | USDT+USDC supply; Coinbase web traffic rank; AI crypto questions | recent | Coin Metrics, Tranco, Anthropic Economic Index |
| **Volume** daily | Total market 24h spot volume (adjusted). The reference uses CMC's aggregate volume: by CMC's methodology the sum of spot trading on every exchange it tracks, DEXs included, derivatives excluded. **What goes into the volume is your call:** count whatever you judge right — CEX spot, DEX spot, perps (CEX and perp DEXs like Hyperliquid)… Measure each part on its own so nothing is counted twice, then **add them into one number and draw one line** (see §6). DEXs are a large share of degen trading today | 2016 → | CMC global daily |

**Note on OTHERS.D:** use the vendor's *ranked* list. CMC appends unranked derivatives (stETH, WBTC, WETH…) with large caps after rank ~199. Sorting everything by market cap pulls them into the top 125 and gives ~12% instead of ~8%. TradingView's OTHERS.D includes them, which is why TradingView reads higher. Either definition is acceptable if documented, but the trend-line acceptance values in §9 are for the ranked (CMC) definition.

**Paid alternatives are welcome** (e.g. CoinGecko Pro, Kaiko, CryptoCompare/CCData, Glassnode or Coin Metrics Pro, Artemis). Requirements:
- weekly history across **both** the 2017/18 and 2021 altseasons for every index input;
- survivorship-free breadth;
- the same definitions as above, or your own, documented.

### 4.2 Retail rows (what people DO, not what they look up)

Deliberately excluded by the reference (and why; see §4.4 before you bring any back):
- Google Trends, Wikipedia: lookups moved to chatbots;
- Fear & Greed: mostly price;
- YouTube statistics: its API terms forbid storing and aggregating them.

Weekly sample of each row:
- **coinbase:** mean of the daily turnover over the 30 days before the stamp (≥ 20 days present);
- **upbit:** sum of the 4 weekly candles before the stamp (all 4 present);
- **memecoins:** the newest value among the 7 days before the stamp, from the first day ≥ $5M on;
- **app store:** `app_score` of the best-ranked crypto app in the newest snapshot of the 7 days before the stamp:
  - overall #1 = 100, #10 = 90, #100 = 60;
  - Finance #10 = 50, #100 = 10;
  - outside both = 5;
  - log interpolation between anchors;
  - the apps list is in `cycle.py` `APPS`.

Robinhood publishes only monthly crypto volume (press releases) with no history across 2021, so it is not a scored row. Adding it as an unscored fact is fine.

### 4.3 Robustness requirements

- **Stale beats empty.** A failed refresh never overwrites stored good data with less or with partial data.

  Examples we hit: if some Upbit markets fail, the week's sum reads low and overwrites a good value; if the App Store chart does not come back, "no crypto app in the top 100" scores 5 and drags retail down. The fix is to write nothing and warn.
- **Freshness per source:** store the newest data day and a stale flag.
  - Weekly sources (and the App Store snapshot) are stale after 10 days, daily sources after 4 days.
  - The panel names stale sources.
- Never draw NaN or Infinity.
- **The history is expensive to rebuild.** It is ~630 weekly listings plus paced calls. Persist it durably, never only in an ephemeral cache.
- **The forward ledger** (§8) records, per week, which sources were stale and which retail rows were scored.

---

### 4.4 Retail and AI: where you can do better than the reference

The reference is built on free, public data by a single developer. Retail and AI interest are its weakest measured parts. You are an AI-native company with your own infrastructure and paid data, so **treat this section as an open brief, not a spec**. Rethink it freely, keeping the principles at the end.

**Known gaps in the reference:**
- **Retail moves between venues.** Coinbase's share of retail shrinks over time, and each row is scored against its own 4-year high, so a venue losing share reads low. Offshore exchanges (Binance, Bybit, OKX…) and perp DEXs (Hyperliquid and similar), where many degens trade now, are not measured.
- **The App Store row watches a hand-picked list of 10 apps.** A new hit app outside the list (the way pump.fun or fomo appeared) is missed. Robinhood, Cash App, Kalshi and Polymarket are tracked but unscored. Ranks, not downloads.
- **AI interest is not in the index.** Google Trends was dropped because crypto questions moved to chatbots, but there is no public dataset of how often people ask AI assistants about crypto with history back to 2021. The reference only shows two unscored facts: Anthropic's Economic Index (crypto share of Claude conversations, published every 2–4 months) and Cloudflare Radar (AI assistants fetching crypto sites on a user's behalf; needs a free token).
- **No social layer:** X, Telegram, Discord, TikTok and YouTube activity is not measured. The YouTube API terms forbid storing and aggregating its statistics, which is why the reference removed it.

**Ideas, your call:**
- Market-wide spot and perp volume by venue, including offshore and DEX (e.g. Kaiko, CCData, Coinalyze, Artemis, DeFiLlama), with retail-sized trade share where a vendor provides it.
- App downloads and ranks for *every* finance or crypto app, with new ones detected automatically (e.g. Sensor Tower, Appfigures, data.ai), instead of a fixed list.
- AI interest from sources you have access to: aggregate query-topic data, AI-assistant referral traffic to crypto sites (e.g. Similarweb), Cloudflare Radar. As an AI-native company you may have better signals of your own.
- Social mindshare, e.g. Kaito, LunarCrush or Santiment, if the licence allows storing history.
- Your own community / belief-network data on what crypto communities talk about — probably the best social signal you can get.

**Principles to keep:**
1. Measure what people **do** (trade, download, deploy money), not what they merely look up.
2. Score each row against its own history (the reference uses a 4-year log scale), so a series that grows structurally does not read as a permanent mania.
3. A scored row needs enough history to be judged. It should cover the 2021 altseason, or at least a full year of warm-up before it counts. Anything newer can be shown as an unscored fact.
4. If you change what the index scores, **write the new rules down before computing them on history** (as the reference did for v3), then compare against §9.

## 5. The method (v3; exact arithmetic in `cycle.py` `compute_index_v3`, locked rules in `cycle_backtest.py` `PREREG_V3`)

v3 (2026-09-28) replaced v2 after three independent reviews: v2 fitted the two past altseasons but could miss the next one (BTC.D's floor rises every cycle, and both exit phases needed the index at 75). v3 was locked before it was computed on real data.

### 5.1 Rotation (0–100, absolute scales)

Each part is clamped to 0–100. Rotation = the mean of the parts present, at least 2 of 3.
- **BTC.D path:** how much of the way from its 1-year high down to the previous cycle's low BTC.D has covered.
  - P = the highest mean4(BTC.D) of the last 52 weeks (≥ 40 values); F = the lowest mean4(BTC.D) of the weeks t−311..t−52 (≥ 52 values: the last cycle's low, not this year's); B = mean4(BTC.D) now.
  - Path = 100 × (P − B) / max(P − F, 25). 100 = at or under the old low. The 25 pp minimum span stops a dip just above an old low (2022, when stablecoins pushed BTC.D down in a bear market) from reading as a full rotation.
  - Why: BTC.D's floor rises every cycle (32.8% in 2018, 37.9% in 2022). v2's fixed scale (a 50% drawdown = full) scored a real rotation from 65% to 45% at 62; the path scores it 74.
- **OTHERS.D rise:** rise = mean4(OTHERS.D) / min of mean4 over 52 weeks − 1. Score = 100 × ln(1 + rise) / ln 3.
- **Breadth:** b = mean4 of breadth %. Score = 100 × (b − 25) / 65.

Why absolute scales: percentiles scored a 3–12% BTC.D dip at 60–70 in the 2022–24 bear market.

Rejected before registration: anchoring P at the previous cycle's low instead of a rolling year (to survive an altseason that runs flat for over a year) held the 2022 bear market at a rotation of ~85.

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
| `po_vrcholu` | **Past the top** | ≥ 4 of the previous 26 weeks in *Altseason is on* or *End is near*, index ≤ the max of those 26 weeks − 15, **and** OTHERS in $ (mean4) ≥ 25% below its high of the weeks t−26..t (alts really fell) |
| `prehrate` | **End is near** | euphoria ≥ 70 and (index ≥ T **or** rotation ≥ 60) — also fires in an altseason weaker than 2021 that never reaches 75 |
| `bezi` | **Altseason is on** | rotation ≥ 60, or index ≥ T |
| `zacina` | **Alts are starting** | rotation ≥ 30 and (rotation +15 vs 13 weeks ago, or an OTHERS.D breakout event in the 13 weeks t−12..t) |
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
  - `downtrend` (**below the line**).
  - `bez_trendu` (**no trend**): no line, because the week is itself the extreme, there is no bottom yet, or there is no pivot.

  The breakout event used by `zacina` is the week the weekly status turns `pruraz`.

**BTC.D support:** the mirror of the above, from the lowest close (2022-11-28) under the higher lows up to the top.

**BTC.D green line (display only):** a straight line from the 2018 altseason low (weekly BTC.D minimum around 2018-01, 32.8%) through the 2022 low (37.9%), extended to today. It shows the rising floor of BTC dominance.

### 5.6 Other tile verdicts

- **BTC.D word:** `support broken` when the BTC.D support line (§5.5) is broken; otherwise the change of mean4(BTC.D) over 13 weeks: ≤ −1.5 pp falling, ≥ +1.5 pp rising, otherwise sideways.
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
| Altseason cycle | Index (area, 0–100); OTHERS in $ on the log right axis; a dashed horizontal line at 75 labelled `top zone · 75`; the three past altseason ends marked with their values (label 2017 to the left so it does not collide with 2018) | The exit sentence, then three plain-words rows (§7.3), each with a small score chip on the right |
| OTHERS.D | OTHERS.D (area, fitted axis); the red resistance line; hollow marks at the anchor (`top 2022`) and the touching pivot; a green mark labelled `break <Mon YYYY>` under the point where the break started; today's value only in the value tag (no separate dot) | — |
| BTC.D | BTC.D (area, fitted); the red support line (anchor labelled `low 2022 · 37.9%`); the break mark; the green 2018→2022 line with its value today under its end point | — |
| Retail | Retail index (area, 0–100); OTHERS in $ on the log right axis (**no BTC line**) | A header `Retail 55 waking up · pace flat`, then a table (§7.4) |
| Volume | **One chart with one line** (area, like the other charts): the 7-day average total $bn from whatever sources you chose, summed into a single series — no split into parts, no stacked layers (fitted, floor 0). The legend says what is in the number; OTHERS in $ on the log right axis (no BTC line — the panel is about alts); the 2019–2020 span shaded, labelled `exchanges inflated volume then (wash trading)` (short on a phone) | — |

The panel must also render cleanly on a phone (375 px), with no horizontal overflow.

---

## 7. English copy (our default wording: reword freely if it stays ultra degen-friendly — plain, short, no jargon)

### 7.1 Tiles, slider, notes

- Tiles: `ALTSEASON CYCLE`, `OTHERS.D`, `BTC.D`, `RETAIL`, `VOLUME`
- Toggle: `Expand ▾` / `Collapse ▴`
- Slider: `CALM` · `TOP ZONE · 75` · `WEEK OF <Mon D>`
- Words:
  - phases: `Alts not moving yet`, `Only BTC runs`, `Alts are starting`, `Altseason is on`, `End is near`, `Past the top`;
  - OTHERS.D: `trend broken`, `breaking the trend`, `false breakout`, `below the line`, `no trend`;
  - BTC.D: `support broken`, `falling`, `rising`, `sideways`;
  - retail: `asleep`, `waking up`, `rushing in`;
  - volume: `weak`, `normal`, `elevated`, `extreme`;
  - tempo: `rush`, `gradually`, `leaving`, `flat`;
  - missing: `no history` or `data missing`.
- Notes:
  - `Stale data: <source> (<N>d), …`
  - `The panel data is from the previous run.`

### 7.2 Info popovers ("i")

- **Altseason cycle:** "**Altseason cycle** — how far money has rotated into alts and how euphoric the market is. Every past altseason top went above 75."
  - How it is calculated: "⅔ rotation into alts (how much of the way from its 1-year high to the last cycle's low BTC dominance has covered, how much small alts rose from their 1-year low, how many alts beat BTC) and ⅓ euphoria (retail and Bitcoin heat). 'End is near' = euphoria at 70 or more with the index at 75 or more or rotation at 60 or more; 'Past the top' = after an altseason the index 15 below its half-year high and alts down 25% in dollars."
  - "Rules locked on 28 Sep 2026, before they were computed on the real history. The two past altseasons were known to the authors, so the real test is every week from now on."
- **OTHERS.D:** "**OTHERS.D** — small alts' share of the market. Breaking the line from the 2022 top = money moving into alts."
  - How it is calculated: "a TradingView-style line — from the highest weekly close of 6 years over the lower highs down to the bottom. A break = two weekly closes more than 3% above the line; each week sees only its own past."
  - Add one line if your OTHERS.D definition differs from TradingView's.
- **BTC.D:** "**BTC dominance** — Bitcoin's share of the market. When it falls, money flows into alts."
  - How it is calculated: "the red line runs from the 2022 low under the higher lows (as on TradingView); a break = two weekly closes more than 3% below it. The green line runs from the 2018 altseason low through the 2022 low to today: BTC dominance's rising floor."
- **Retail:** "**Retail** — how much people actually trade, against each row's own 4-year high. High = where past tops happened."
  - How it is calculated: "Coinbase (US), Upbit (Korea), memecoins on-chain and the top crypto app. A row reads 100 at its 4-year high and 0 at a twentieth of it (log scale); the index = the mean of the rows. The area = retail, the line = OTHERS in dollars."
  - "Google, Wikipedia and Fear & Greed are not measured: lookups moved into chatbots, and Fear & Greed is mostly price."
- **Volume:** "**Volume** — daily spot trading on all exchanges including DEXs (no futures; 7-day average) against its 1-year norm. Tops ran 2–4×, but so did crashes."
  - "2019–20 contains fake exchange volume. Alts' share ex stablecoins: up to 76% in May 2021."
  - This describes the reference's number; if your volume includes more (e.g. perps), say so here and in the legend.

### 7.3 Altseason cycle: the exit sentence and the breakdown

Directly under the cycle chart, one line, always shown (a subtle callout, not a warning):

> **Around the end:** when “End is near” is on, sell in pieces and don't wait for the exact top. When “Past the top” shows, get out with the rest.

Why pieces: in 2017 "End is near" stayed on for 11 months while alts went ~10×; after it lit in April 2021 alts fell 43% in 3 months.

Then three rows under it (this week's numbers):

Each number stands next to the same number at the 2018 and 2021 altseason ends (`rotation_at_events`, computed on the backend — never a hand-written range):

1. **Is money moving into alts?** (chip = rotation), three short lines:
   - `BTC dominance has covered 5% of the way from its 1-year high 60.0% to the last cycle's low 37.9% (2018: 100%, 2021: 78%)` (the path shown clamped to 0–100)
   - `small alts +23% above their 1-year low (2018: +251%, 2021: +215%)`
   - `24% of the top 50 alts beat BTC over 13 weeks (2018: 89%, 2021: 90%)`
2. **Is the market euphoric?** (chip = euphoria): `retail 55/100 · Bitcoin heat 46/100`
3. **Altseason cycle** (chip = index): `⅔ money into alts + ⅓ euphoria. "End is near" = euphoria 70+ with the index at 75+ or money into alts at 60+.`

(The numbers above are illustrative only; the real ones come from `rotation_at_events` and this week's components of your own run.)

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
- `events` P0/P1/P2/P2b with `index_at_events`, and `rotation_at_events` (the BTC.D path, the OTHERS.D rise and the 4-week breadth at P1 and P2, for §7.3);
- the rotation's parts for this week: BTC.D `path` (pct, score, peak and its week, floor and its week), OTHERS.D `rise_pct` and the week of its low;
- `freshness` per source, `anomalies`.

Keep it NaN-free.

Refresh: at least daily. The reference runs every 6 h; weekly values change once a week, daily points (newest OTHERS.D, BTC.D, volume) every day.

**Forward ledger:** append one line per closed week (week, index, phase, rotation, euphoria, retail, heat, version, the stale sources, the scored retail rows) to durable storage; while a week is still the newest, a later run with fewer stale sources may replace its line. It is the honest test of the method from now on.

---

## 9. Acceptance (reference numbers, real data)

Reference run of 2026-09-28 (the v3 rules were locked before it). The trend lines are the same as in v2; retail differs only by the data fixes (5 weeks of 2016 Coinbase data after the BTC/ETH pair fix).

**Historical events** (P0/P1/P2 = weekly BTC.D minimum in the stated windows):

| Event | Week | Index v3 |
|---|---|---|
| P0 | 2017-06-19 | 99.7 |
| P1 | 2018-01-15 | 95.2 |
| P2 | 2021-05-17 | 79.4 |
| P2b | 2021-11 | 62.1 |

- **Pre-registered verdict: FAIL, by 2 weeks.** 4 of the 5 checks pass: "End is near" within [−8, +2] weeks of P0, P1 and P2; each cycle's highest week near its tops; 1 "End is near" episode away from the tops (2016-09-05..09-12, limit 2); **no "End is near" and no index ≥ 75 from 2023-01 to 2026-06**. The fifth fails: 54 of 529 weeks (10.2%) at ≥ 75, the limit was 10% (52 weeks). The owner chose to run v3 anyway and keep the FAIL on record; nothing was tuned.
- "End is near" episodes: 2017-04-03..2018-03-05 (continuous — see §10), 2021-04-19..06-14, 2021-11-15. "Past the top": 2018-03-26..08-27, 2021-07-05..08-16, 2022-02-14..05-30 (none between the two 2017 waves, where v2 wrongly had one).
- Max since 2023: 46.5; yearly max 2024 46.5, 2025 46.5; today (week of 2026-09-21) 23.5, `Alts not moving yet`.
- For comparison, v2 on the same data: P0 99.7, P1 95.2, P2 79.7, P2b 62.3; ≥ 75 in 8.4% of weeks (PASS); "Past the top" Aug–Oct 2017 between the two alt waves.

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

## 10. Known weak spots (from three independent reviews; improve freely)

1. **An altseason that runs flat for more than a year** drifts out of the one-year windows: after about a year the rotation fades and the phase falls back while alts still hold. v3 at least never says "Past the top" while alts hold their dollar value. No altseason so far ran flat for a year (2017 ≈ 10 months, 2021 ≈ 5). A fix that does not also mark the 2022 bear market as an altseason is welcome.
2. **Data sources can break silently.** The reference uses unofficial or free endpoints (the CMC web API especially). Prefer robust vendors, alert your ops on failure, and show freshness on the panel.
3. **"Past the top" is late by design** (1–2 months after the top). The panel is a map, not a sell signal, so keep the copy honest.
4. **Only two historical altseasons** exist. The designers knew both, so the historical checks are consistency, not proof. The forward ledger is the real test.
5. **The retail mix changes over time:** 2017 has only Coinbase, 2021 adds Upbit, and memecoins and App Store data are recent. Document how you handle it. Retail and AI coverage is the biggest room for improvement: see §4.4.
6. **"End is near" is on for long in a long, strong altseason:** in 2017–18 it stayed on for 11 months (April 2017 to March 2018), because rotation stayed ≥ 60 with high euphoria through both waves. A degen could read it as "sell" too early. It is also why v3 missed its 10% rule by 2 weeks. Improving this without tuning to 2017 is welcome — register the rule before computing it on history.
7. **Weaker next altseason:** v3's BTC.D path and its "End is near" rule (euphoria ≥ 70 and rotation ≥ 60, even under 75) exist for this case; they were tested on synthetic series only.

## 11. Deliverables

1. The panel live at cymetica.com/gem-screener on **both the Top Picks and the Sectors tab** (the same module in both places), in English, in your design system, matching the reference.
2. The backend job with durable history, freshness, anomalies and the forward ledger.
3. A short review note: what you changed or improved and why, which data vendors you chose, and the acceptance results from §9.
4. Separately: the improved chain valuation (Appendix B) and the improved Sectors tab (Appendix C).

---

## Appendix B — separate task: make the chain valuation as good as the apps one

This is **not** part of the Altseason panel. It concerns the **Chains** tab.

**Apps (we like it):** "Hyperliquid is priced at 35× its yearly revenue. Upside = what a coin is worth at the same price tag." A real price tag (market cap ÷ yearly revenue) against the market's leader.

**Chains (we don't like it):** "The median chain is priced at 2× its stablecoins. Upside = what a chain is worth at the same price tag." What is wrong with it:
- **Stablecoins are not income or usage.** Market cap ÷ stablecoins on the chain measures parked money. A chain full of settlement stablecoins (e.g. Tron's USDT) reads "cheap" while little happens on it.
- **The benchmark is the median chain, not a leader.** Half of the chains always show upside just by being below the median, so the number means less than on apps.
- **Activity is left out of the price tag.** DEX volume only feeds the growth/adoption index, and chain fees are only a tooltip check. Neither affects upside or the sort.
- Market cap ÷ TVL was rejected on purpose: TVL is partly the chain's own token, so it moves with the price.

**Your task:** tune it so it is top — the same quality and the same one-line clarity as apps. Choose the price tag, the benchmark and the data yourself (fees, DEX volume, users, paid sources…). Keep the Chains tab design, keep it degen-friendly, and write down what you changed and why.

Reference code: `collector.py` (`compute_metrics`, `apply_valuation`, `adoption_index`), ARCHITECTURE.md §9.3 and §9.7.

---

## Appendix C — separate task: make the Sectors tab answer its own question

This is **not** part of the Altseason panel. It concerns the **Sectors** tab: the themes table and the bubble chart ("Right = moves harder than BTC. Up = beat BTC this quarter…"). Your current version uses our method, so it has our weak spots. An independent review scored it 6/10: careful statistics, but it answers a different question than it promises ("which themes get hottest if an altseason starts").

**What we don't like:**
1. **The ranking uses the wrong factor.** Themes are sorted and tiered by beta to BTC — how hard a theme moves with BTC, up and down. That is riskiness, not altseason performance (an altseason is alts beating BTC), and it was measured in a year with no altseason. Yet the page calls beta "the direct answer". A closer measure already exists in the code (`gamma`: sensitivity to alts outrunning BTC) but only sits in a tooltip.
2. **"Bottom right = the most room" / "Waiting to run" is partly mechanical.** When BTC falls, a high-beta theme falls further and lands bottom right by construction, then reads as an opportunity. The tag text even says "barely moved against BTC" next to −35%. "Already leading" also mixes beta with real outperformance. The vertical axis and the tags should use performance vs BTC *beyond* what beta explains.
3. **Survivorship is only half handled.** The "basket as it stood a year ago" is picked only from today's CoinGecko top 30 per category, so coins that dropped out were never candidates. The info text claims otherwise.
4. **The L1/L2 fundament is stablecoins** (mostly USDT on Ethereum and Tron, plus Base without a token) — the same weakness as Appendix B. L1/L2 can never earn "fundament rising".
5. **Coverage and purity:** exchange tokens (BNB, OKB, MNT) sit in L1/L2 and drag them down; themes such as ecosystem rotations (Solana, Base) or BTCfi are missing; 11 columns with β ±SE, ρ and tier are not readable in 5 seconds.

**Must stay:** a degen sees at a glance **what is hot right now** (which themes are running, beating BTC and the other alts this month/quarter) — that half of the question matters as much as the altseason outlook; just measure it honestly (not beta in disguise).

**Use your own community signal.** If your internal belief network already monitors crypto communities and chats (what people talk about, how belief and attention shift between narratives), use it to judge which themes are hot — it is exactly what price data cannot see early. Suggestions: map its topics onto the themes; show attention (share of conversation and its change) next to price performance vs BTC, so a degen sees whether a theme is talked about *and* bought, or only one of them; store its history so it can be checked against what the themes did next. The same signal may also fill the "AI / social interest" gap in the Altseason panel's retail (§4.4).

**Suggestions from a community member (we agree with all five):**
1. **"Beaten down but turning" vs "still falling" (falling knife).** One column mixes *how far a theme fell* with *whether it is still falling*: Gaming −79% and still falling, Infrastructure −67% and turning up — same column, opposite trades. Show level and momentum as two columns and add a tag "beaten down but turning" (define it honestly, e.g. deep drawdown from the 1-year high and 1-month performance vs BTC turning positive).
2. **The opposite tag: "lagging and still falling".** A coin that lags in a hot theme and is down over 3 months is not a laggard with room to catch up, it is a broken coin — flag it.
3. **Who in a hot theme has not moved yet.** The data (per-coin 1M/3M vs BTC, basket weight) is already in your response, just not shown. Show it, next to tag 2 so a laggard and a broken coin are not confused.
4. **Network and contract address for every coin** — the single most valuable field. Coins carry only a CoinGecko `id`, so they cannot be joined with on-chain data (your FOMO radar works with addresses).
5. **No Czech in the data.** Drop reasons come through the API in Czech ("méně než 40 týdnů historie"). Use machine codes (`insufficient_history`, `stablecoin`, …) and translate them only in the UI.

**Keep:** the bubble chart and its design, the uncertainty whiskers ("overlapping whiskers = statistically the same" is honest and good), the degen tone, no composite score, tags as tags (not filters).

**Your task:** tune it so it is top and really answers "which themes run hardest in an altseason, and which already run". Method, factors, themes and data are your call. Keep the design, and write down what you changed and why.

Reference code: `themes.py` (`build_themes`, beta/tier, `rs1m`/`rs3m`, tags), `audit_sectors.py`, ARCHITECTURE.md §12–§13.7.
