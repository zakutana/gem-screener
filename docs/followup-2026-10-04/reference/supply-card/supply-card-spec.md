# Supply column tooltip + Supply card: shorter (spec)

Read from the live code: pressure 1–10 = 6 − ceil(yearly change of the sellable pile / 2.5%); 1–3 Flooding, 4–7 Balanced,
8–10 Squeezing; `sp.status` is `measured` (point), `range` or `unknown`; `sp.tone` colours the figure (unchanged). Nothing is
deleted: every sentence of today's card moves behind one labelled expand. Mockup: `supply-card-redesign.html` / `.png`.

## Tooltip (`saTip`): title + one line + one small line
- Title: `Supply pressure {p}/10 · {band}` (range: `{lo}–{hi}/10`), or `Supply pressure unknown`.
- Line: `Sellable tokens {grow|shrink|hold steady} {abs figure} a year` + ` (estimate)` when `status !== 'measured'`.
  A range that crosses zero reads `change −2.8% to +15.1% a year`. Unknown: `Not enough measured for a figure.`
- Small (`.pk`): `1 = most new supply` / `10 = shrinking fastest` (pressure ≤ 5 / ≥ 6) · `{n} parts not measured` when n > 0.

## Card (`supplyCard`): tiles unchanged, then
```html
<div class="sa-hero {tone}"><div class="sa-fig"><b>{saHero}</b>{status!=='measured' && status!=='unknown' ?
  <button class="sa-est tipme" type="button" {tipAttrs('Estimate: a range', n+' parts could not be measured. An unknown outflow counts as 0, an unknown inflow as the typical token’s.')}>estimate</button>}</div>
 <span class="sa-press {band|unknown}{ range}" {tipAttrs('Supply pressure '+p+' of 10', '1 = the sellable pile grows fastest, 10 = it shrinks fastest. 1–3 Flooding, 4–7 Balanced, 8–10 Squeezing.')}>
  <span class="pn">{p}<small>/10</small></span><span class="pb">{band}</span><span class="ps">1 = most new supply</span></span>
 <div class="sa-unit">sellable tokens a year</div></div>            <!-- unknown: "?" and "not enough measured for a figure" -->
<p class="sa-say">{sp.sentence}</p>
<div class="sa-viz"><div class="sa-pie">{saPie(sp,84) with class="s" data-k on each slice}<div class="sl-tip" role="tooltip" hidden></div></div>
 <ul class="sa-leg" aria-label="Tokens in play today"><li tabindex="0" data-k="free"><i></i>Free to sell<span class="v">33.5M</span></li>… +reserve</ul>
 <div class="sa-curve"><p class="sa-ctit">Sellable pile, next 24 months</p>{saCurve(sp)}</div></div>
<details class="sa-more"><summary>What we could not measure <span class="n">{unknown_names.length}</span>{disagree ? <span class="dis">sources disagree</span>}</summary>
 <dl><dt>Not measured</dt><dd>{chips}</dd><dt>Assumed</dt><dd>An unknown outflow counts as 0, an unknown inflow as the typical token’s. That is why the figure is a range.</dd>
 <dt>Sources</dt><dd>{supplyDisagreeWhy(e)}</dd><dt>Pressure</dt><dd>{formula}</dd><dt>Read</dt><dd>{dayOf(refreshed_at)} · Supply Analyzer by EventTrader</dd></dl></details>
<div class="sa-foot"><a href="{link}" target="_blank" rel="noopener">Open in Supply Analyzer ↗</a></div>
```
**Pie slices:** hover, focus or tap on a slice or its legend row highlights both (`.hl`, others dim) and shows `.sl-tip`:
name, `{amount} · {share}%`, one line: Free to sell "can be sold now"; Staked, free to unlock "staked, can be withdrawn";
Staked, locked "staked and locked"; Vesting "unlocks on a schedule"; Newly paid out "just paid out"; Bought back, kept "bought
back, held"; Bought back, burned "bought back, destroyed"; Reserve "not in circulation yet" (no share: it is outside the pie).
These one-liners are our reading of the slice names; Cymetica should confirm them.

## CSS (new; the old `.sahero/.sapill/.sasay/.saunk/.salegend` go)
```css
.sa-hero{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:2px 14px;align-items:center;margin-top:16px}
.sa-fig{display:flex;align-items:center;gap:10px;flex-wrap:wrap} .sa-fig b{font:700 34px/1.05 "IBM Plex Mono",monospace;font-variant-numeric:tabular-nums}
.sa-hero.red .sa-fig b{color:var(--bad)} .sa-hero.green .sa-fig b{color:var(--good)} .sa-hero.grey .sa-fig b{color:var(--muted)} .sa-unit{font-size:14px;color:var(--ink-2)}
.sa-est{appearance:none;cursor:help;font:600 11px "IBM Plex Mono",monospace;color:var(--ink-2);background:none;border:1px dashed var(--muted);border-radius:99px;padding:2px 9px}
.sa-press{grid-row:1/span 2;grid-column:2;display:flex;flex-direction:column;align-items:center;min-width:108px;padding:8px 12px;border-radius:10px;border:1.5px solid var(--warn);background:var(--surface);cursor:help}
.sa-press .pn{font:700 26px/1 "IBM Plex Mono",monospace} .sa-press .pn small{font-size:13px;color:var(--muted)} .sa-press .pb{font:700 10.5px "IBM Plex Mono",monospace;letter-spacing:.1em;text-transform:uppercase} .sa-press .ps{font:500 10px "IBM Plex Mono",monospace;color:var(--muted)}
.sa-press.Flooding{border-color:var(--bad);color:var(--bad)} .sa-press.Balanced{color:var(--warn)} .sa-press.Squeezing{border-color:var(--good);color:var(--good)} .sa-press.unknown{border:1.5px dashed var(--muted);color:var(--muted)} .sa-press.range{border-style:dashed}
.sa-say{margin:10px 0 0;font-size:15px;color:var(--ink)}
.sa-viz{display:grid;grid-template-columns:auto minmax(0,1fr) minmax(0,1.1fr);gap:12px 16px;align-items:center;margin-top:14px;padding-top:12px;border-top:1px solid var(--rule-soft)}
.sa-pie{position:relative;width:84px;height:84px} .sa-pie .s{cursor:pointer;transition:opacity .12s,transform .12s;transform-origin:42px 42px} .sa-pie.has-hl .s:not(.hl){opacity:.35} .sa-pie .s.hl{transform:scale(1.06)}
.sa-leg{list-style:none;margin:0;padding:0;display:grid;gap:2px;font-size:13px;color:var(--ink-2)} .sa-leg li{display:flex;align-items:center;gap:7px;padding:3px 6px;border-radius:6px} .sa-leg li .v{margin-left:auto;padding-left:8px;font:600 12.5px "IBM Plex Mono",monospace;color:var(--ink)} .sa-leg li.hl{background:var(--accent-soft);color:var(--ink)}
.sl-tip{position:absolute;z-index:5;left:-4px;bottom:calc(100% + 8px);width:230px;background:var(--surface);border:1px solid rgba(0,150,255,.35);border-radius:10px;padding:8px 11px;box-shadow:0 10px 30px rgba(0,0,0,.55);font-size:13px;pointer-events:none}
.sa-more{margin-top:12px;border:1px solid var(--rule-soft);border-radius:8px;background:var(--surface)} .sa-more>summary{cursor:pointer;display:flex;align-items:center;gap:8px;padding:9px 12px;min-height:40px;font-weight:600;font-size:13px;color:var(--ink-2)}
.sa-more>summary .dis{margin-left:auto;font:600 10.5px "IBM Plex Mono",monospace;text-transform:uppercase;border:1px solid var(--muted);border-radius:4px;padding:2px 7px} .sa-more dl{margin:0;padding:2px 12px 12px;display:grid;grid-template-columns:auto 1fr;gap:7px 14px;font-size:13px}
@media (max-width:560px){ .sa-fig b{font-size:24px;white-space:nowrap} .sa-viz{grid-template-columns:auto minmax(0,1fr)} .sa-curve{grid-column:1/-1} .sa-press{min-width:88px} }
```
States: measured (no `estimate`, solid pressure border), range (`estimate` tag + dashed border when the pressure itself is a
range), unknown (grey "?", dashed badge, expand lists all six parts), sources disagree (grey tag on the expand row, detail
inside). Colours keep their meaning: the figure uses `sp.tone`, red stays red. Keyboard: `estimate`, the badge and legend rows
are tab stops with the page's `#tip`; `<details>` is native; the page's reduced-motion rule removes the slice transition.

## Build it Better request (5 lines)
Supply Analyzer on the Gem Screener: the Supply tooltip and the Supply card are too long to read; please make them numbers first.
Tooltip: title + one line ("Sellable tokens grow +52% to +67% a year (estimate)") + one small line ("1 = most new supply · 3 parts not measured").
Card: big figure with a small "estimate" tag, the pressure badge "1/10 Flooding · 1 = most new supply", the one sentence, pie + curve.
Everything else (not measured, assumptions, sources disagree, formula, date) goes behind one expand: "What we could not measure (3)".
Pie: hover/tap a slice or legend row to highlight both and show "Free to sell · 33.5M · 6% · can be sold now". Mockup and spec attached.
