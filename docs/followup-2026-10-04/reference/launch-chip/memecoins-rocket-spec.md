> **Note (2026-10-04):** item [11] of `../../SPEC.md` wins where this differs: the chip is YELLOW (alternative B in the mock, a deliberate palette exception for this one chip), not cyan.

# Memecoins row: launch chip (spec)

What it is today (live code): `launchIcon(th)` renders an 18px green `a.caticon.nmicon.lpad` only for `th.key === 'memes'`,
linking to `https://cymetica.com/launchpad` in a new tab, `aria-label="Launch your own memecoin"`. That label is the only copy
the code has, so the chip says exactly that. Mockup: `memecoins-rocket-redesign.html` / `.png`.

**Colour: cyan (`--accent`).** Green and red are verdicts on the data on this page, and this row sits in Falling. Cyan is the
colour of every link and button here, so the chip reads as "action", not as "memecoins look good". Yellow (alternative B in the
mock) is outside the platform palette: the page itself says "EventTrader's palette has no amber, orange or yellow".

## HTML
In `themeNameCell(th)`, drop `launchIcon(th)` from `.nmrow` and append `launchCta(th)` as the last child of `.namecell`
(after `.txt`). Keep the class `lpad`: the row's click handler already skips `a.lpad`, so the row panel does not open.
```js
function launchCta(th){
  if (!th || th.key !== LAUNCHPAD_THEME) return '';
  return '<a class="lp-cta lpad" href="' + LAUNCHPAD_URL + '" target="_blank" rel="noopener" ' +
    'aria-label="Launch your own memecoin (opens in a new tab)">' +
    '<span class="lp-disc" aria-hidden="true">' + ICO_LAUNCH.replace(/width="15" height="15"/, 'width="20" height="20"') + '</span>' +
    '<span>Launch<span class="lp-long"> your own memecoin</span></span><span class="lp-ext" aria-hidden="true">↗</span></a>';
}
```
(Mock draws the same rocket path with stroke-width 1.7 instead of 1.3 so it holds at 20px.)

## CSS
```css
.lp-cta{display:inline-flex;align-items:center;gap:8px;flex:none;height:34px;padding:0 12px 0 3px;margin-left:14px;
  border-radius:99px;border:1px solid rgba(0,207,255,.55);text-decoration:none;white-space:nowrap;
  background:linear-gradient(90deg,rgba(0,207,255,.22),rgba(0,207,255,.06));color:var(--accent-ink);
  font:700 13px "IBM Plex Sans",sans-serif;transition:transform .15s,box-shadow .15s,border-color .15s}
.lp-disc{width:28px;height:28px;border-radius:50%;display:grid;place-items:center;flex:none;
  background:var(--accent);color:#04121c;box-shadow:0 0 14px rgba(0,207,255,.45)}
.lp-ext{opacity:.75;font-size:12px}
.lp-cta:hover{transform:translateY(-1px);border-color:var(--accent);box-shadow:0 0 0 1px var(--accent),0 8px 22px -8px rgba(0,207,255,.7)}
.lp-cta:focus-visible{outline:2px solid var(--text-heading);outline-offset:3px}
@media (max-width:560px){ .lp-cta{height:32px;margin-left:10px;font-size:12.5px} .lp-disc{width:26px;height:26px} .lp-long{display:none} }
@media (prefers-reduced-motion:reduce){ .lp-cta:hover{transform:none} }
```

## Behaviour
- Size: 34px tall (row height unchanged, the name cell is already ~40px), rocket glyph 20px on a 28px solid disc: the largest,
  brightest thing in the row, against an 18px icon today. No looping animation; the glow is static, hover lifts 1px.
- Phone (≤560px): the table keeps scrolling sideways as today (`min-width:820px`); the chip shortens to "Launch ↗" so the
  name column does not grow. The accessible name keeps the full phrase and contains the visible text (WCAG 2.5.3).
- Keyboard: a plain link, so it is in the tab order; focus shows a white ring (cyan on cyan would vanish).
- Other places that call `launchIcon` (theme panel `#pTags`, Hot sectors cards) keep the small icon unless asked.
