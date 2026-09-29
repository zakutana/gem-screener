# Build request: the Sectors tab on cymetica.com/gem-screener

**For:** the lead agent of the Cymetica SDLC pipeline
**From:** Adam (product owner, Gem Screener)
**Part 3 of 4** of one request — part 1 (the Altseason panel) is [`docs/altseason-panel/SPEC.md`](../altseason-panel/SPEC.md); do all four.
**Scope:** only the **Sectors tab's themes** — the themes table and the bubble chart ("Right = moves harder than BTC. Up = beat BTC this quarter…"). Nothing else on the page changes. The Altseason card on this tab is part 1 (the Altseason panel spec).

> **English only.** Our reference code is Czech-first; ignore all Czech. **Method and data are your call** (paid data welcome). **Keep the design:** the bubble chart, the uncertainty whiskers and the degen tone.

## Why

Your current version uses our method, so it has our weak spots. An independent review scored it 6/10: careful statistics, but it answers a different question than it promises — "which themes run hardest if an altseason starts, and which already run".

**What we don't like:**
1. **The ranking uses the wrong factor.** Themes are sorted and tiered by beta to BTC — how hard a theme moves with BTC, up and down. That is riskiness, not altseason performance (an altseason is alts beating BTC), and it was measured in a year with no altseason. Yet the page calls beta "the direct answer". A closer measure already exists in the code (`gamma`: sensitivity to alts outrunning BTC) but only sits in a tooltip.
2. **"Bottom right = the most room" / "Waiting to run" is partly mechanical.** When BTC falls, a high-beta theme falls further and lands bottom right by construction, then reads as an opportunity. The tag text even says "barely moved against BTC" next to −35%. "Already leading" also mixes beta with real outperformance. The vertical axis and the tags should use performance vs BTC *beyond* what beta explains.
3. **Survivorship is only half handled.** The "basket as it stood a year ago" is picked only from today's CoinGecko top 30 per category, so coins that dropped out were never candidates. The info text claims otherwise.
4. **The L1/L2 fundament is stablecoins** (mostly USDT on Ethereum and Tron, plus Base without a token) — the same weakness as the chain valuation (separate request). L1/L2 can never earn "fundament rising".
5. **Coverage and purity:** exchange tokens (BNB, OKB, MNT) sit in L1/L2 and drag them down; themes such as ecosystem rotations (Solana, Base) or BTCfi are missing; 11 columns with β ±SE, ρ and tier are not readable in 5 seconds.

**Must stay:** a degen sees at a glance **what is hot right now** (which themes are running, beating BTC and the other alts this month/quarter) — that half of the question matters as much as the altseason outlook; just measure it honestly (not beta in disguise).

**Use your Belief Networks.** Your internal belief-network model that monitors crypto communities and chats (what people talk about, how belief and attention shift between narratives) is the best signal for which themes are hot — it is exactly what price data cannot see early. Suggestions: map its topics onto the themes; show attention (share of conversation and its change) next to price performance vs BTC, so a degen sees whether a theme is talked about *and* bought, or only one of them; store its history so it can be checked against what the themes did next.

**Suggestions from a community member (we agree with all five):**
1. **"Beaten down but turning" vs "still falling" (falling knife).** One column mixes *how far a theme fell* with *whether it is still falling*: Gaming −79% and still falling, Infrastructure −67% and turning up — same column, opposite trades. Show level and momentum as two columns and add a tag "beaten down but turning" (define it honestly, e.g. deep drawdown from the 1-year high and 1-month performance vs BTC turning positive).
2. **The opposite tag: "lagging and still falling".** A coin that lags in a hot theme and is down over 3 months is not a laggard with room to catch up, it is a broken coin — flag it.
3. **Who in a hot theme has not moved yet.** The data (per-coin 1M/3M vs BTC, basket weight) is already in your response, just not shown. Show it, next to tag 2 so a laggard and a broken coin are not confused.
4. **Links for every coin: CoinGecko and DEXTools.** Every coin in a theme gets a link to its **CoinGecko** page and a link to its **main trading pair on DEXTools** (the deepest DEX pair; if a coin has no DEX pair, CoinGecko only). Put both links **in the coin's detail view, right next to its existing website link**. Today coins carry only a CoinGecko `id` and no way to jump to the chart or the pair.
5. **No Czech in the data.** Drop reasons come through the API in Czech ("méně než 40 týdnů historie"). Use machine codes (`insufficient_history`, `stablecoin`, …) and translate them only in the UI.

**Keep:** the bubble chart and its design, the uncertainty whiskers ("overlapping whiskers = statistically the same" is honest and good), the degen tone, no composite score, tags as tags (not filters).

## Acceptance — check each point

1. The sort and the tier are **not** raw beta to BTC; they use a measure of how a theme does against BTC / the other alts, and the page no longer calls beta "the direct answer".
2. The chart's vertical axis and the tags "Already leading" / "Waiting to run" use performance vs BTC **beyond what beta explains**; no tag text contradicts its own number.
3. **Level and momentum** are two separate columns; tags **"beaten down but turning"** and **"lagging and still falling"** exist, each with its rule written down.
4. Inside a theme, every coin shows its **1M and 3M vs BTC**, so the laggards of a hot theme are visible.
5. Every coin has a **CoinGecko link** and a **DEXTools link to its main trading pair** (CoinGecko only when no DEX pair exists), shown **in the coin's detail view next to its website link**.
6. The API carries **machine codes, no Czech** (e.g. `insufficient_history`, `stablecoin`).
7. **What is hot right now** is visible at a glance, and the **Belief Networks** attention (share of conversation and its change) stands next to price performance, with its history stored.
8. Survivorship: the year-ago basket is **not** limited to today's top 30 per category — or the page says honestly that it is.
9. L1/L2 are not judged on stablecoins alone; exchange tokens (BNB, OKB, MNT…) no longer sit in L1/L2.
10. **Design unchanged:** bubble chart, whiskers, degen tone; no composite score; tags stay tags, not filters.
11. A short note: what you changed and why, the data you used, and the themes' order before and after.

Reference code (inspiration, not to copy): `themes.py` (`build_themes`, beta/tier, `rs1m`/`rs3m`, tags), `audit_sectors.py`, ARCHITECTURE.md §12–§13.7 — public repo `zakutana/gem-screener`, branch `altseason-cycle-2r6d3t`.
