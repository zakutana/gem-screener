# Hot sectors + Top Picks fund: redesign spec

Scope: `#startThemes` and `#startFund` on the Top Picks tab. Mockup: `hot-sectors-redesign.html` / `.png`.
Uses only the page's own tokens (`--surface*`, `--accent*`, `--good`, `--bad`, `--rule*`, `--focus`) and its fonts
(IBM Plex Sans / IBM Plex Mono / Archivo Black). Reuses `.stpill`, `.cardi`, `.c-good/.c-bad/.c-na`, the `#tip` tooltip,
`:focus-visible` and the existing `prefers-reduced-motion` blanket. No new data: every value is what `renderStart()` has today.

## Structure
`.st-h` "Hot sectors" is replaced by the panel title; `#startFund` moves inside the panel.
```html
<section class="hs" aria-labelledby="hs-h">
  <div class="hs-head"><h3 class="hs-title" id="hs-h">Hot sectors</h3><!-- cardInfo(...) --></div>
  <ul class="hs-grid">                       <!-- one <li> per theme in hotFirst -->
    <li class="hs-card cardtip st-{th.stage}" data-theme="{th.key}" {cardTipAttrs(name, ctip)}>
      <div class="hs-top">
        <h4 class="hs-name"><button class="hs-open" type="button">{themeName}</button></h4>
        <span class="tipme" tabindex="0" {tipAttrs(STAGE.name, stageWhy(th), STAGE.rule)}>{stagePill(th.stage)}</span>
        {cardInfo(themeName, ctip)}
      </div>
      <ul class="hs-sigs" aria-label="Signals">  <!-- one per th.tags; omit the <ul> when empty -->
        <li class="hs-sig {THEME_TAGS[t].cls} tipme" tabindex="0" {tipAttrs(label, THEME_TAG_SHORT[t])}>
          {TAG_ICO[t] at 14px, aria-hidden}{tagLabel(t)}</li>
      </ul>
      <div class="hs-fund">
        <span class="hs-fn">{f.name}</span>
        <span class="hs-ret"><span class="hs-num c-bad">−3.8%</span><span class="hs-since">since launch</span></span>
        <a class="hs-link" href="{f.url}" target="_blank" rel="noopener"
           aria-label="{f.name} fund page (opens in a new tab)">Fund <span class="ar" aria-hidden="true">→</span></a>
      </div>
    </li>
  </ul>
  <section class="hs-flag" aria-labelledby="tp-name">
    <span class="hs-gem" aria-hidden="true"><!-- gem SVG from the mockup, 24px --></span>
    <div><h4 class="hs-flag-name" id="tp-name">Gem Screener Top Picks <span class="mgr">(CyMetica-managed)</span></h4>
      <p class="hs-flag-sub">the Degen picks at equal weight · rebalanced weekly</p></div>
    <span class="hs-ret"><span class="hs-num c-bad">−0.9%</span><span class="hs-since">since launch</span></span>
    <a class="hs-cta" href="{f.url}" target="_blank" rel="noopener">Fund performance <span class="ar" aria-hidden="true">→</span></a>
  </section>
</section>
```
`fundRet()` splits in two: the number (`fmtPct(r,1)`, class from the same `r1` rounding rule) and the fixed word
"since launch". The flagship's name is split only for styling; its text is unchanged.

## CSS
```css
.hs{background:var(--surface);border:1.5px solid rgba(0,207,255,.45);border-radius:12px;padding:14px 16px 16px;
  box-shadow:0 0 0 1px rgba(0,0,0,.35),0 6px 22px rgba(0,0,0,.28);margin-bottom:26px}
.hs-head{display:flex;align-items:center;margin:0 0 12px} .hs-title{margin:0;font:700 12px "IBM Plex Sans",sans-serif;letter-spacing:.15em;text-transform:uppercase;color:var(--ink)}
.hs-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:10px;margin:0;padding:0;list-style:none}
.hs-card{--st:var(--good);position:relative;display:flex;flex-direction:column;gap:10px;min-width:0;cursor:pointer;
  background:var(--surface-2);border:1px solid var(--rule-soft);border-radius:9px;padding:12px 12px 12px 14px;transition:border-color .12s}
.hs-card::before{content:"";position:absolute;left:-1px;top:12px;bottom:12px;width:3px;border-radius:0 3px 3px 0;background:var(--st);opacity:.75}
.hs-card:hover,.hs-card:focus-within{border-color:var(--accent)}
.hs-card.st-emerging{--st:var(--accent)} .hs-card.st-fading{--st:var(--warn)} .hs-card.st-falling{--st:var(--bad)}
.hs-top{display:flex;align-items:center;gap:8px;min-width:0} .hs-name{margin:0;flex:none}
.hs-open{appearance:none;background:none;border:0;padding:0;cursor:pointer;color:var(--text-heading);
  font:400 22px/1 "Archivo Black","IBM Plex Sans",sans-serif;letter-spacing:.01em}
.hs-open:focus-visible{outline-offset:4px} .hs-top .cardi{margin-left:auto;width:20px;height:20px;font-size:10.5px}
.hs-sigs{display:flex;flex-wrap:wrap;gap:6px;margin:0;padding:0;list-style:none}
.hs-sig{display:inline-flex;align-items:center;gap:5px;height:24px;padding:0 9px 0 6px;border-radius:6px;cursor:help;
  font:600 11.5px "IBM Plex Sans",sans-serif;color:var(--ink);background:var(--rule-soft);border:1px solid var(--rule-soft)}
.hs-sig.good svg{color:var(--good)} .hs-sig.warn svg{color:var(--warn)} .hs-sig.bad svg{color:var(--bad)} .hs-sig.info svg{color:var(--accent)}
.hs-sig:hover,.hs-sig:focus-visible{border-color:var(--accent)}
.hs-fund{display:grid;grid-template-columns:1fr auto;grid-template-areas:"fn link" "ret link";align-items:end;column-gap:10px;
  margin-top:auto;background:var(--surface-sunk);border:1px solid var(--rule-soft);border-radius:8px;padding:9px 10px 10px 12px}
.hs-fund.none{grid-template-columns:1fr;grid-template-areas:"ret"} .hs-fund .hs-ret,.hs-fund .hs-na{grid-area:ret}
.hs-fn{grid-area:fn;font:500 11px "IBM Plex Mono",monospace;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.hs-ret{display:flex;align-items:baseline;gap:8px;white-space:nowrap} .hs-flag .hs-ret{gap:10px}
.hs-num{font:700 1.6rem/1.15 "IBM Plex Mono",monospace;font-variant-numeric:tabular-nums;letter-spacing:-.02em}
.hs-since{font:500 11.5px "IBM Plex Mono",monospace;color:var(--ink-2)} .hs-na{font:500 12px "IBM Plex Mono",monospace;color:var(--muted)}
.hs-link{grid-area:link;align-self:center;display:inline-flex;align-items:center;gap:6px;height:34px;padding:0 12px;
  border:1px solid rgba(0,207,255,.45);border-radius:8px;color:var(--accent);text-decoration:none;font:700 12.5px "IBM Plex Sans",sans-serif}
.hs-link:hover{background:var(--accent-soft);border-color:var(--accent)} .hs-link .ar,.hs-cta .ar{display:inline-block;transition:transform .15s}
.hs-link:hover .ar,.hs-cta:hover .ar{transform:translateX(3px)}
.hs-flag{display:grid;grid-template-columns:auto minmax(0,1fr) auto auto;align-items:center;gap:6px 22px;margin-top:12px;
  padding:16px 18px;border-radius:10px;border:1.5px solid var(--accent);
  background:linear-gradient(100deg,rgba(0,207,255,.13),rgba(0,207,255,.03) 55%),var(--surface-sunk)}
.hs-gem{width:44px;height:44px;border-radius:10px;display:grid;place-items:center;color:var(--accent);
  background:var(--accent-soft);border:1px solid rgba(0,207,255,.35)}
.hs-flag-name{margin:0;font:700 17px/1.25 "IBM Plex Sans",sans-serif;color:var(--text-heading)}
.hs-flag-name .mgr{font-weight:500;color:var(--ink-2)} .hs-flag .hs-num{font-size:2.1rem}
.hs-flag-sub{margin:3px 0 0;font:500 12px "IBM Plex Mono",monospace;color:var(--muted)}
.hs-cta{display:inline-flex;align-items:center;gap:8px;height:42px;padding:0 18px;border-radius:9px;white-space:nowrap;
  background:var(--accent);color:#04121c;text-decoration:none;font:700 14px "IBM Plex Sans",sans-serif}
.hs-cta:hover{background:var(--accent-ink)} .hs-cta:focus-visible{outline-color:var(--text-heading);outline-offset:3px}
@media (max-width:640px){
  .hs{padding:12px 12px 14px} .hs-grid{grid-template-columns:1fr;gap:8px} .hs-card{gap:8px;padding:11px 11px 11px 13px}
  .hs-open{font-size:20px} .hs-num{font-size:1.45rem}
  .hs-flag{grid-template-columns:auto minmax(0,1fr);gap:10px 12px;padding:14px} .hs-gem{width:38px;height:38px}
  .hs-flag-name{font-size:15.5px} .hs-flag .hs-ret{grid-column:1/-1} .hs-flag .hs-num{font-size:1.9rem}
  .hs-cta{grid-column:1/-1;justify-content:center;height:44px}
}
```

## States
- **Stage** (`st-hot` / `st-emerging` / `st-fading` / `st-falling`) colours only the 3px edge and the pill. **Return** colours only
  the number, by the existing rule: rounded > 0 `c-good`, < 0 `c-bad`, 0.0 `c-na`. The two never borrow each other's colour:
  a Hot sector whose fund is down shows a green edge and a red `−3.8%`, and the number stays the largest thing on the card.
- **Negative**: U+2212 minus (as `fmtPct` prints), red, same size as a positive. No hiding, no muting, no reordering by return.
- **Neutral / no return yet**: `.hs-ret` holds only `<span class="hs-since c-na">new, no return yet</span>`; the Fund link stays.
- **No fund**: `<div class="hs-fund none"><span class="hs-na tipme" …>No fund yet: under two of its coins are buyable on-chain</span></div>`.
- **Loading**: `.hs-na` "Fund: loading…"; flagship keeps its frame with "loading…". No sparklines: there is no fund series here.

## Responsive
Desktop: three cards in one row (auto-fit, min 260px), flagship one row: gem · name/sub · number · button.
≤ 640px: cards stack (no horizontal scroll, so no fund is hidden off-screen); flagship becomes gem + name, then the number,
then a full-width 44px button. Gutter is the existing `--gutter`. The mockup uses `@container` only to show both widths on one page.

## Accessibility
- The live `.thcard` is `role="button"` wrapping a link and focusable icons (nested interactive). Now the card is an `<li>`;
  the sector name is the `<button>` that opens the sector panel (bind `openThemePanel` to `.hs-open`; a click elsewhere
  on the card may still open it, but skip clicks inside `a, .tipme, .cardi`). Tab order: name → stage → (i) → signals → Fund.
- Signals now carry visible words (`tagLabel(t)`): "Already leading", "Beaten down but turning". Their tooltips are
  `THEME_TAG_SHORT[t]`, e.g. "Half or more under its 1-year high, and beating BTC this month." Icon `aria-hidden`.
- Hot pill tooltip: `STAGE.hot.long` ("Ahead of the median sector over 3 months and over the last month.") plus `stageWhy(th)`.
- Every tooltip opens on hover, keyboard focus and tap (existing `#tip` behaviour). Colour is never the only cue: stage has
  its glyph and word, return has its sign.
- Targets: Fund 34px high, flagship button 42/44px. Contrast: `--ink-2` on `--surface-sunk` and `#04121c` on `--accent` pass AA.
- Motion: only the 3px arrow nudge and border-colour fades, already removed by the page's `prefers-reduced-motion` rule.
