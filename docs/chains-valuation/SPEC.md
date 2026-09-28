# Build request: chain valuation on the Chains tab of cymetica.com/gem-screener

**For:** the lead agent of the Cymetica SDLC pipeline
**From:** Adam (product owner, Gem Screener)
**Scope:** only **how chains are valued** on the Chains tab (the price tag, the benchmark, the upside and the sort). Nothing else on the page changes.

> **English only.** Our reference code is Czech-first; ignore all Czech. **Method and data are your call** (paid data welcome: fees, DEX volume, users…). **Keep the Chains tab design** and the degen tone.

## Why

**Apps (we like it):** "Hyperliquid is priced at 35× its yearly revenue. Upside = what a coin is worth at the same price tag." A real price tag (market cap ÷ yearly revenue) against the market's leader.

**Chains (we don't like it):** "The median chain is priced at 2× its stablecoins. Upside = what a chain is worth at the same price tag."
- **Stablecoins are not income or usage.** Market cap ÷ stablecoins on the chain measures parked money. A chain full of settlement stablecoins (e.g. Tron's USDT) reads "cheap" while little happens on it.
- **The benchmark is the median chain, not a leader.** Half of the chains always show upside just by being below the median.
- **Activity is left out of the price tag.** DEX volume only feeds the growth/adoption index, and chain fees are only a tooltip check. Neither affects upside or the sort.
- Market cap ÷ TVL was rejected on purpose: TVL is partly the chain's own token, so it moves with the price.

## Acceptance — check each point

1. Chains show the **same one-line price tag as Apps**: "<leader> is priced at N× its yearly <measure>. Upside = what a chain is worth at the same price tag."
2. The benchmark is a **named leader chain**, not the median.
3. **Stablecoins alone are not the price tag.** The measure includes activity (e.g. yearly fees and/or DEX volume), is written down, and guards against wash-traded or incentivised volume.
4. That activity **enters the upside and the sort**, not only a tooltip.
5. Market cap ÷ TVL is not used.
6. **Chains tab design unchanged**, degen-friendly.
7. A short note: what you changed and why, the data you used, and the top 10 chains by upside before and after.

Reference code (inspiration, not to copy): `collector.py` (`compute_metrics`, `apply_valuation`, `adoption_index`), ARCHITECTURE.md §9.3 and §9.7 — public repo `zakutana/gem-screener`, branch `altseason-cycle-2r6d3t`.
