# Fund picks tray (spec, v2: top on desktop, bottom dock on phones)

Today `#pickBar` sits in `.controls` **inside `.stickytop`** (`position:sticky; z-index:20`; app header ≤ 130px, ET-28990), so
unframed it already stays in view, and framed `#pickFloat` (fixed at `--gs-vt`, z-index 30) does it. The problem is weight, not
place. `PICKS` is capped at 30 in `togglePick` (a 31st click silently does nothing). Mockup: `fund-picks-bar-redesign.*`.

## Desktop (> 640px)
- **Place:** the tray replaces `#pickBar` in its slot (under the filters, left of the benchmark badge), so it rides the existing
  sticky block: no new offset, no new z-index. Hidden at 0 picks.
- **First pick (0 → 1):** add `.pt-enter` once: it drops in 8px (0.26s), then one 1.2s cyan glow fades to rest; remove the
  class on `animationend`. Nothing loops; the page's `prefers-reduced-motion` blanket turns both off.
- **No row is covered.** Unframed, rows scroll inside `.tablewrap`, sized `calc(100vh - 230px)` for the sticky block; subtract
  the tray: `calc(100vh - 230px - var(--pt-h,0px))`, `--pt-h` set on `:root` by a ResizeObserver (0 when hidden). Framed, pin
  the one tray (`.pt-pinned{position:fixed;top:var(--gs-vt,0px);left:0;right:0;z-index:30}`, slot keeps `min-height:var(--pt-h)`)
  on `syncPickFloat`'s test; rows pass under it like under the site header, and `focusin` on a row hidden under it scrolls that
  row clear. `#pickFloat` and its cloned markup go.
- **30 picks:** `.pt-full`: ring full in `--warn` (the page's caution blue), "30 is the limit: remove one to add another",
  every unticked `.pickbtn` gets `disabled` + `title="30 picks is the limit"`; below 30 they come back.

**Phone (≤ 640px):** bottom dock (CSS at the end), `main{padding-bottom:var(--pt-h)}` so the last rows scroll above it.

## HTML (`renderPickBar()` renders `.pt-inner` only; the section and its live region are created once)
```html
<section id="pickTray" class="picktray" aria-label="Your fund picks" hidden><div class="pt-inner">
 <div class="pt-ring" aria-hidden="true"><svg viewBox="0 0 46 46"><circle class="trk" cx="23" cy="23" r="19" fill="none" stroke-width="4"/>
  <circle class="val" cx="23" cy="23" r="19" fill="none" stroke-width="4" stroke-linecap="round" stroke-dasharray="{119.38*n/30} 119.38"/></svg><b>{n}</b></div>
 <div class="pt-id"><p class="pt-title">Your fund picks<span class="of">{n} of 30</span></p><p class="pt-sub"><span class="pt-what">Opens the Fund
  Launcher with these preloaded · you set the weights there</span><span class="pt-limit">30 is the limit: remove one to add another</span></p></div>
 <ul class="pt-chips"><li><button class="pt-chip" type="button" data-sym="{S}" aria-label="Remove {S}">{logoImg(e.logo_data, e.name, 20)}{S}<span class="x" aria-hidden="true">×</span></button></li>…</ul>
 <button class="pt-clear" type="button">Clear</button>
 <a class="pt-launch" href="{launchUrl()}">Launch a fund with these <span class="n" aria-hidden="true">{n}</span> →</a>
</div><p class="sr-only" aria-live="polite"><!-- set textContent: "{S} added. {n} of 30 picks." --></p></section>
```

## CSS (desktop; tokens are the page's)
```css
.picktray{flex-basis:100%;position:relative;border:1.5px solid rgba(0,207,255,.55);border-radius:10px;
  background:linear-gradient(100deg,rgba(0,207,255,.10),rgba(0,207,255,.02) 60%),var(--surface);box-shadow:0 0 0 1px rgba(0,0,0,.35),0 0 18px rgba(0,207,255,.10)}
.picktray[hidden]{display:none} .picktray.pt-enter{animation:pt-drop .26s ease-out 1,pt-glow 1.2s ease-out .26s 1}
@keyframes pt-drop{from{translate:0 -8px;opacity:0}}
@keyframes pt-glow{25%{border-color:var(--accent);box-shadow:0 0 0 4px rgba(0,207,255,.30),0 0 34px rgba(0,207,255,.55)} 60%{border-color:var(--accent);box-shadow:0 0 0 2px rgba(0,207,255,.18),0 0 22px rgba(0,207,255,.30)}}
.pt-inner{padding:9px 10px 9px 12px;display:grid;align-items:center;gap:8px 16px;grid-template-columns:auto auto minmax(0,1fr) auto auto;grid-template-areas:"ring id chips clear launch"}
.pt-ring{grid-area:ring;position:relative} .pt-ring svg{display:block;width:42px;height:42px;transform:rotate(-90deg)} .pt-ring .trk{stroke:var(--rule)} .pt-ring .val{stroke:var(--gem)}
.pt-ring b{position:absolute;inset:0;display:grid;place-items:center;font:700 15px "IBM Plex Mono",monospace;color:var(--text-heading)}
.pt-id{grid-area:id;min-width:0} .pt-title{margin:0;font:700 15px "IBM Plex Sans",sans-serif;color:var(--text-heading);white-space:nowrap} .pt-limit{display:none;color:var(--ink)}
.pt-title .of{font:600 12.5px "IBM Plex Mono",monospace;color:var(--gem);margin-left:6px} .pt-sub{margin:1px 0 0;font-size:12px;color:var(--ink-2);white-space:nowrap}
.pt-chips{grid-area:chips;display:flex;gap:6px;margin:0;padding:2px 0;list-style:none;overflow-x:auto;scrollbar-width:thin;min-width:0;mask-image:linear-gradient(90deg,#000 calc(100% - 28px),transparent)}
.pt-chip{display:inline-flex;align-items:center;gap:6px;height:32px;padding:0 9px 0 5px;border-radius:99px;flex:none;cursor:pointer;border:1px solid rgba(0,150,255,.35);background:rgba(0,207,255,.07);color:var(--ink);font:700 12.5px "IBM Plex Mono",monospace}
.pt-chip .x{color:var(--muted);font-size:14px} .pt-chip:hover{border-color:var(--accent)}
.pt-clear{grid-area:clear;appearance:none;border:0;background:none;color:var(--ink-2);font:600 13px "IBM Plex Sans",sans-serif;height:44px;padding:0 6px;cursor:pointer;text-decoration:underline;text-underline-offset:3px}
.pt-launch{grid-area:launch;display:inline-flex;align-items:center;gap:10px;height:44px;padding:0 18px 0 20px;border-radius:10px;background:var(--accent);color:#04121c;text-decoration:none;font:700 15px "IBM Plex Sans",sans-serif;white-space:nowrap;box-shadow:0 6px 20px -8px rgba(0,207,255,.8)}
.pt-launch:hover{background:var(--accent-ink)} .pt-launch:focus-visible{outline:2px solid var(--text-heading);outline-offset:3px}
.pt-launch .n{min-width:24px;height:24px;padding:0 6px;border-radius:99px;background:#04121c;color:var(--accent);display:inline-grid;place-items:center;font:700 12.5px "IBM Plex Mono",monospace}
.pt-full .pt-ring .val{stroke:var(--warn)} .pt-full .pt-title .of{color:var(--warn)} .pt-full .pt-limit{display:inline} .pt-full .pt-what{display:none} .pickbtn:disabled{opacity:.35;cursor:not-allowed}
@media (max-width:640px){ .picktray{position:fixed;left:0;right:0;z-index:30;top:calc(var(--gs-vt,0px) + var(--gs-vh,100dvh));transform:translateY(-100%);border:0;border-top:1.5px solid rgba(0,207,255,.55);border-radius:0;padding-bottom:env(safe-area-inset-bottom,0px);background:linear-gradient(180deg,rgba(0,207,255,.07),transparent 70%),var(--surface-2);box-shadow:0 -14px 34px -12px rgba(0,0,0,.85)}
  @keyframes pt-drop{from{translate:0 22px;opacity:0}} .pt-inner{grid-template-columns:auto minmax(0,1fr);grid-template-areas:"ring chips" "clear launch";gap:8px 10px;padding:10px 12px 12px}
  .pt-id,.pt-title{display:none} .pt-full .pt-id{display:block} .pt-full .pt-inner{grid-template-areas:"ring chips" "id id" "clear launch"} .pt-ring svg{width:40px;height:40px} .pt-launch{justify-content:center;height:46px} }
```
Accessibility: labelled region; chips are "Remove {S}" buttons; 44px+ targets; the live region announces each change without moving focus; the count is written, not only drawn.
