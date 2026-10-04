> **Note (2026-10-04):** item [7] of `../../SPEC.md` wins where this differs: Security is one guardian whose state is the worse of audit and past hacks.

# Guardians: the coin detail "Checks" block, six guardians (spec)

Coin detail only; no table changes. Each guardian is its **name and its icon ring(s)**, nothing else; every number and every
explanation is in the card that opens on hover, focus or tap (the page's own `.ckcard`). The look is the page's: `.ckc` rings,
`CHECK_ICON` glyphs. Mockup: `guardians-redesign.html` / `.png`.

Data: `row.dlevel.checks[]` (`id, verdict, code, text, context, source, as_of`) from `/api/v1/gem-screener/coins/{symbol}`.
The page decides no verdict.

## The six
| Name | Glyph (existing) | Fed by | State |
|---|---|---|---|
| Rug power | key `rug_power` | `rug_power` | its verdict |
| Holders paid | funnel `reaches_you` | `reaches_you` | its verdict (red under 5%, the check's rule) |
| Thin liquidity | drop `slippage` | `slippage` | its verdict |
| Price run | flame `price_run` | `price_run` | its verdict |
| Security | shield `audit` + history `track_record` | both | two rings, each its own verdict |
| Team | `team` | `team` | its verdict |

Not shown as guardians: `new_tokens`, `real_yield` (the Supply section covers dilution), `trend`, `strength_3m` (their own
table columns), `hidden_supply`, `insider_flow`, `whales`. They stay in the data and in the Degen meter. No group of future
guardians. The summary counts only the six (Security counts once, by its worse known ring).

## States: ring colour + a 15px mark on the ring (never colour alone)
good ✓ green · caution ! blue (`--warn`) · bad × red · not_checked ? dashed ring and dashed mark (a guardian whose data does
not exist for this coin, e.g. Rug power or Team "not scanned") · not_applicable – grey. No data never shows green: a
not_checked verdict stays dashed even if `value` holds something. No "safe" anywhere.

## HTML
```html
<section class="xcard gcard" aria-label="Guardians">
 <div class="gh">{checkIcon('audit')}<span class="t">Guardians</span></div>
 <div class="gsum"><span class="r">2 red</span> · <span class="c">1 caution</span> · <span class="g">2 clear</span> · <span class="n">1 not checked</span></div>
 <ul class="glist">
  <li class="grow ckt" tabindex="0" data-ck="reaches_you" aria-label="Holders paid: red. 0.0% of revenue to holders">
   <span class="ckc v-bad">{checkIcon('reaches_you')}<i class="mk" aria-hidden="true">×</i></span><span class="gn">Holders paid</span></li> …
 </ul>
</section>
```
Card (existing `.ckcard` via `.ckt`): icon, name, state pill, `c.text` (the key figure), one `c.context` line, `source · day`.

## CSS (new; `.ckc`, `.ckcard` reused)
```css
.gh{display:flex;align-items:center;gap:8px} .gh svg{width:15px;height:15px;fill:none;stroke:var(--accent);stroke-width:1.4;stroke-linecap:round;stroke-linejoin:round}
.gh .t{font:700 12px "IBM Plex Sans",sans-serif;letter-spacing:.15em;text-transform:uppercase;color:var(--ink)}
.gsum{margin:8px 0 6px;font:600 13px "IBM Plex Mono",monospace;color:var(--ink-2)}
.gsum .r{color:var(--bad)} .gsum .c{color:var(--warn)} .gsum .g{color:var(--good)} .gsum .n{color:var(--muted)}
.glist{list-style:none;margin:4px 0 0;padding:0;display:grid;grid-template-columns:1fr 1fr;gap:2px 10px}
.grow{position:relative;display:flex;gap:12px;align-items:center;padding:8px 6px;border-radius:8px;cursor:help}
.grow:hover,.grow:focus-visible{background:rgba(0,207,255,.06)} .gi{display:flex;gap:6px}
.gn{font-size:14px;font-weight:700;color:var(--ink)} .grow.v-not_checked .gn{color:var(--ink-2)}
.ckc{position:relative} .ckc .mk{position:absolute;right:-4px;top:-4px;width:15px;height:15px;border-radius:50%;display:grid;place-items:center;
  font:700 9.5px/1 "IBM Plex Mono",monospace;font-style:normal;color:var(--paper);box-shadow:0 0 0 2px var(--surface-2)}
.ckc.v-good .mk{background:var(--good)} .ckc.v-caution .mk{background:var(--warn)} .ckc.v-bad .mk{background:var(--bad)}
.ckc.v-not_checked .mk{background:var(--surface-2);color:var(--muted);border:1px dashed var(--muted)} .ckc.v-not_applicable .mk{background:#4a5a70}
```
Phone (390px): the same two-column grid fits (names are 1–2 words); no media query needed.

## Build it Better request (6 lines)
Gem Screener coin detail: replace the "Checks" block with a minimal Guardians block, using the page's own check icons and rings.
Six guardians, each shown only as its name and its ring: Rug power, Holders paid, Thin liquidity, Price run, Security, Team.
Every number and explanation moves into the existing hover/tap card; the block itself carries one line: "2 red · 1 caution · 2 clear".
States: ✓ green clear, ! blue caution, × red, ? dashed not checked (no data for this coin), – does not apply; a mark on each ring.
No data never shows green; dilution stays in the Supply section; no change to any table; no placeholder guardians.
Mockup + spec attached.
