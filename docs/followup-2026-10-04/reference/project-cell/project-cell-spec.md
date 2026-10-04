# Apps table project cell: one badge, one circle (spec)
`nameCell(e)` on Apps keeps logo, name, symbol and at most ONE mark: the smiley `.hsb`, shown only when the `reaches_you` check
is `good` (the row needs that verdict from the collector, e.g. `e.holders_ok`; the page must not derive it from `holders_share`).
Every other mark leaves the cell (supply-sources (i), holder-share and risk icons); the Guardians in the detail carry them.
```html
<span class="hsb" tabindex="0" role="img" aria-label="Shares revenue with holders: 70% of revenue"><svg viewBox="0 0 24 24" aria-hidden="true">
 <circle class="face" cx="12" cy="12" r="10.2"/><circle class="eye" cx="8.8" cy="9.8" r="1.35"/><circle class="eye" cx="15.2" cy="9.8" r="1.35"/>
 <path d="M7.9 14.2c1 1.6 2.4 2.4 4.1 2.4s3.1-.8 4.1-2.4"/></svg></span>
```
```css
.hsb{display:inline-flex;margin-left:8px;color:var(--good);cursor:help;border-radius:50%} /* the face outline is the only circle */
.hsb svg{width:22px;height:22px;fill:none;stroke:currentColor;stroke-width:1.6;stroke-linecap:round;stroke-linejoin:round}
.hsb .face{fill:rgba(0,255,136,.10);transition:fill .12s} .hsb .eye{fill:currentColor;stroke:none}
.hsb:hover .face,.hsb:focus-visible .face{fill:rgba(0,255,136,.22)} .hsb:focus-visible{outline:2px solid var(--focus);outline-offset:2px}
```
Tooltip via the page's `#tip` (`tipAttrs`), one line: "Holders get {round(100·holders_share)}% of revenue". No ring, no glow; reduced motion: the page's rule.
**Build it Better (2 lines):** Apps table: remove every mark from the project cell except one green smiley, a single circle (the face is the ring), shown only when the Holders share check is green.
Hover or tap shows one line, "Holders get 70% of revenue"; the Guardians in the coin detail carry the rest; no new column. Mockup + spec attached.
