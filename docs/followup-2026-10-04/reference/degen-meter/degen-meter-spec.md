> **Note (2026-10-04):** item [5] of `../../SPEC.md` wins where this differs: the card meter has NO band word above it (no "Spicy" label); ignore `.dm-band` below.

# Degen meter: card and table (spec)

**What it encodes (live `degenMeter()`, ET-28378 A.1/A.3/A.9):** the engine's risk level `row.dlevel.level`, 1 to 10, higher
is riskier (legend copy). Segments 1..level are filled; level+1..`high` are dashed (how far the level can still move once the
missing checks are in); the rest are empty. Every segment carries the zone of its position: 1–3 green, 4–6 caution blue,
7–10 red; the number takes the zone of the level. Bands: Blue chip / Spicy / Casino (`d.band`). It already fills left to right.

**What reads as odd, and the fix.** Nothing says which end is safe, so a green-first fill reads like a score where more is
better; the number sits alone on the left with no "/10"; empty segments are all one grey, so the green-blue-red scale is
invisible until filled. Fix, without changing what is measured: the empty segments keep a faint tint of their zone (the whole
axis is always visible), the value sits at the end of the fill as `4/10`, and on the card the meter goes full width with its
name, the band word and the page's own end labels "Blue chip" / "Casino" (from the detail panel). Mockup: `degen-meter-redesign.*`.

## JS
`degenMeter(e, big)`: put `.dnum` after `.dsegs`, text `level + '<small>/10</small>'` (none: `–<small>/10</small>`). Segments already carry `off zg|zw|zb`; `.lvl` hides `.dnum`.
For the card, `.dc-risk` gets `degenMeterCard(e)` instead of `degenMeter(e)`:
```js
function degenMeterCard(e){
  var d = degenLevelOf(e), lo = d && (typeof d.low === 'number' ? d.low : d.level), hi = d && (typeof d.high === 'number' ? d.high : d.level);
  var tip = '1 to 10, higher is riskier.' + (d && hi > lo ? ' Range ' + lo + '–' + hi +
    ': the dashed segments are how far the level can still move once the missing checks are in.' : '');
  return '<div class="dm"><span class="dm-k">Degen meter' + cardInfo(d ? 'Degen meter ' + d.level + ' of 10' : 'Degen meter', d ? tip :
    'The level has not been computed for this coin yet. It comes with the next update.') + '</span>' +
    '<span class="dm-band">' + esc(d ? (BAND_NAME[d.band] || '') : 'Not available') + '</span>' + degenMeter(e) +
    '<span class="dm-ends" aria-hidden="true"><span>Blue chip</span><span>Casino</span></span></div>';
}
```
The meter stays a picture (`role="img"`, its existing aria-label "Degen meter 4 of 10, range 3 to 5", no tab stop, A.9); the
tooltip lives on the `(i)` beside its name, the page's usual `cardInfo` (hover, focus, tap).

## CSS (replace the matching `.dmeter` rules, below the `i.dash` rule so a dashed segment keeps its zone tint; add `.dm*`)
```css
.dmeter .dsegs i{width:7px;height:14px;border-width:1px}
.dmeter .dsegs i.zg{background:rgba(0,255,136,.13)} .dmeter .dsegs i.zw{background:rgba(59,130,246,.2)} .dmeter .dsegs i.zb{background:rgba(255,68,68,.15)}
.dmeter .dsegs i.on.zg{background:var(--good)} .dmeter .dsegs i.on.zw{background:var(--warn)} .dmeter .dsegs i.on.zb{background:var(--bad)}
.dmeter .dnum{font-size:14px;color:var(--ink);text-align:left} .dmeter .dnum small{font-size:10.5px;font-weight:500;color:var(--muted)}
.dmeter.d-good .dnum{color:var(--good)} .dmeter.d-warn .dnum{color:var(--warn)} .dmeter.d-bad .dnum{color:var(--bad)}
.dm{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:5px 12px;align-items:center;padding-top:10px;border-top:1px solid var(--rule-soft)}
.dm-k{display:flex;align-items:center;gap:6px;font:600 10.5px "IBM Plex Mono",monospace;letter-spacing:.1em;text-transform:uppercase;color:var(--muted)}
.dm-k .cardi{text-transform:none;letter-spacing:0;margin-left:0} .dm-band{justify-self:end;font-weight:700;font-size:12.5px;color:var(--ink-2)}
.dm .dmeter{grid-column:1/-1;display:grid;grid-template-columns:minmax(0,1fr) auto;gap:12px}
.dm .dmeter .dsegs{display:flex;gap:3px} .dm .dmeter .dsegs i{flex:1 1 0;width:auto;height:16px;border-radius:3px} .dm .dmeter .dsegs i.dash{border-width:1.5px}
.dm .dmeter .dnum{font-size:22px;line-height:1} .dm .dmeter .dnum small{font-size:13px}
.dm-ends{grid-column:1/-1;display:flex;justify-content:space-between;margin-right:56px;font:500 10.5px "IBM Plex Mono",monospace;color:var(--muted)}
.dm-ends span:first-child::before{content:"← "} .dm-ends span:last-child::after{content:" →"} .dc-risk{flex-wrap:wrap} .dc-risk .dm{flex:1 1 100%}
```
Table: the compact form is the same `degenMeter(e)` with the rules above (≈130px wide, unchanged column). Phone: the card
meter is fluid (segments share the width); the table scrolls sideways as today. Colour is never alone: the value is written,
the band is a word, the ends are labelled, and dashed segments are a pattern, not a hue.
