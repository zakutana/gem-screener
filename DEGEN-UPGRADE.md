# Gem Screener: degen upgrade (follow-up to ET-26608)

This is the full spec of a follow-up to Build it Better request **ET-26608** (Gem Screener, shipped 2026-09-24, verdict PASS, live at https://cymetica.com/gem-screener). The request form takes only 1,000 characters, so the whole list lives here. Every numbered item is one requirement and can be checked on the live page.

Gem Screener is my own app; this repository is its source. Anything not mentioned here stays as it is.

## Who it is for

1. **Audience.** Degens hunting low-cap gems. They want only high-value facts and will not read. Test every screen against that: if a sentence does not change a buy decision, it goes.

## Speed

2. **First load.** The first load is under 500 kB gzipped. It carries the ranked tables plus the Top-10 chart's 10 series (up to 53 weekly points each); every other row's history loads only when its row is opened. On a healthy server a new visitor on a phone sees the table in under 3 seconds.

## Words: less of them

3. **Header.** The title is "Gem Screener" with the subtitle "Revenue-driven research", like "EventTrader / AI-Native Trading" in the site header. Drop "EventTrader [ ]" and the "DEFILLAMA" tag from the app header.
4. **Status line.** Only "Updated 2 h ago · 217 apps · 27 chains · Live". Drop "collected from $10K / 30d".
5. **Cut what does not change a decision**, for example "(hidden, not vetted: 43)", "flags next to a name are icons: hover or Tab to focus for the reason" and "Independent of the filters below". Anything still worth knowing moves into the Legend.
6. **Benchmark.** Replace "benchmark: Hyperliquid 37x MC/revenue" with one highlighted line: "Hyperliquid is priced at 37x its yearly revenue. Upside = what a coin is worth at the same price tag."
7. **Tooltips everywhere:** at most 20 plain words, no formulas, no r², no "log-OLS", no "MC/run-rate". Examples: Strength "Revenue grew faster than the price: still cheap (up) / price ran ahead (down)". Growth "How much revenue changed in 6 months". A "How it's calculated" link at the end of a tooltip opens the maths for whoever wants it.
8. **FDV line.** The "FDV 39x" line under Upside reads "39x if all tokens were out", and its tooltip says how many tokens are still to come ("only 7% are out today").
9. **Legend.** A "Legend" button next to the tabs opens one short panel listing every icon, tag, colour, column and trajectory word (Ignition, Slowing, Flat, ...), at most 8 words each.

## Numbers and colours

10. **One colour rule for every number in the app:** green = good for a buyer, amber = caution, red = bad, grey = neutral or missing. Today Growth and "To holders" are blue and FDV is red in one place and white in another; after this the same number has the same colour in the table, the cards, the detail and the charts.
11. **Strength uses 3 months instead of 6:** the column is "Strength 3M", and the detail says the same.
12. **No empty gap** between Growth and Trajectory: Trajectory takes the free width.
13. **"Your fund picks" bar** stays visible (sticky) while the table scrolls, on desktop and on a phone.
14. **Real or printed revenue.** Show each app's 30-day earnings after token emissions (DefiLlama revenue minus incentives). When an app pays out more in tokens than it earns, a red "Revenue bought with emissions" flag appears in the table and in the detail. It is a flag, not a new gate: the preregistered gates stay as they are.

## Coin detail

15. **Plain labels.** "MC / run-rate 0.3x" becomes "Price vs revenue: 0.3x (Hyperliquid 37x)", and every stat label says what it is in 4 words or fewer.
16. **Badges, not blocks.** The Vetted and Buy & hold blocks become one-line badges, for example "Vetted", "Thin liquidity: a $10K buy moves the price 3.2%", "Only 7% of tokens out, no unlocks in 90 days", "+131% in 30 days, near its all-time high".
17. **Trade button.** A big "Trade on EventTrader" button next to "web" when the token has a pair on your exchange (today PUMP/USDC), and a small "tradeable here" icon next to the name in the table.

## Start tab

18. **Start tab.** Rename it to what it shows (for example "Top Picks"). Top to bottom it holds only: the Altseason index (number and bar, no paragraph), the hot sectors, the Gem Screener Top Picks fund, and the Degen picks as today. Below them, short: near misses one line each (name, upside, the failed gate in 5 words or fewer), "When to take profit" as 3 short bullets, the backtest as one line with an expand ("Backtest: inconclusive. A shortlist, not a signal."). "What this tool can't see", the altseason paragraph and the footer text move into About.
19. **Hot sectors on the Start tab.** No symbols (no β); each card in plain words, for example "Memecoins: BTC +10% -> +14%, waiting to run". Each hot sector has its own CyMetica-managed AIB fund (like the Managed AIB funds on /fund-performance) holding that sector's leading coins, rebalanced weekly, shown on its card with its return since launch and a link to its /fund-performance page.
20. **Gem Screener Top Picks fund.** A CyMetica-managed AIB fund holding the current Degen picks at equal weight, rebalanced weekly, shown on the Start tab right above the Degen picks with its return since launch and a link to its /fund-performance page.

## Sectors and data quality

21. **Sectors chart.** Labels never overlap; the horizontal lines are either explained on the chart in a few words ("line = how sure we are") or removed; one reading line above it: "Right = moves harder than BTC. Up = beat BTC this quarter. Green = tailwind."
22. **Incomplete data.** The 6-hour collector retries CoinGecko's HTTP 429 with backoff, and a batch that still fails keeps its last prices. Visitors never see raw URLs, log lines or "Try Refresh data" (that button is hidden on your site). If some prices are older than one refresh, one plain line says so: "Prices for N coins are from the previous update".

## Degen report by NEXUS

23. **On request.** A "Degen report" button in every coin's detail asks NEXUS for a short report on that coin, for example by pre-filling the NEXUS chat with the prompt so the visitor only presses Enter. How it is wired is your call; the report follows the format in item 24 and is at most 150 words.
24. **Format**, in this order, one line each: What it is / Where the money comes from / Real or printed (30-day revenue vs 30-day token emissions) / Numbers (MC, FDV, % of tokens out, price vs revenue) / Good (max 3) / Shady (max 3) / The bet and the one metric to watch / One-line verdict. Anything unknown says "unknown", never a guess; sources are linked; "Not financial advice" at the end.
25. **Illustrative target for Pharaoh (PHAR).** What it is: Avalanche's main DEX, a RAMSES fork on x(3,3). Money: $2.0M fees in 30 days from $2.5B volume. Real or printed: earns $1.98M, prints $1.08M in tokens, so +$0.9M real. Numbers: MC $3.1M, FDV $46M, 7% of tokens out. Good: profitable after emissions, emissions shrink when revenue drops, 50% exit burn. Shady: +131% in 30 days near its all-time high, revenue swings with Avalanche activity. The bet: Avalanche stays busy; watch weekly fees vs weekly emissions. Verdict: strong DEX, bought after a pump.

## Nice to have (not a condition of this request)

26. If you can list some of the Degen picks on your exchange, the Trade button (item 17) shows for them too.
