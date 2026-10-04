# Sectors rotation chart: stage tint (spec)

Live: `renderThemeScatter()` draws the plot frame as `rect fill:none stroke:--rule`, so the plot is the panel's flat `--surface`.
Change: four quadrant rects, each filled with a radial gradient from its outer corner in its stage colour (`stageColor(st)`: Emerging
`--accent`, Hot `--good`, Fading `--warn`, Falling `--bad`, the colours the corner labels already wear), fading to 0 before the median
lines. Inserted right after `<defs>`, before the frame, the median lines, tails, bubbles and labels, so all of those stay on top,
unchanged. Colour meaning is unchanged: each corner is tinted with the stage the page already names there. Recommended: **A, 6%**.
```js
var x0 = X(0), y0 = Y(0), x1 = W - pR, y1 = H - pB, TINT = 0.06;           // B: 0.10
[['emerging', pL, pT, 0, 0], ['hot', x1, pT, 1, 0], ['falling', pL, y1, 0, 1], ['fading', x1, y1, 1, 1]].forEach(function(q){
  var g = svgEl('radialGradient', {id: 'stg-' + q[0], gradientUnits: 'userSpaceOnUse', cx: q[1], cy: q[2],
    r: Math.hypot(x0 - pL, y0 - pT) * 0.95});
  [[0, 1], [0.55, 0.35], [1, 0]].forEach(function(s){
    g.appendChild(svgEl('stop', {offset: s[0], 'stop-color': stageColor(q[0]), 'stop-opacity': TINT * s[1]})); });
  defs.appendChild(g);
  svg.appendChild(svgEl('rect', {'class': 'stagebg', x: q[3] ? x0 : pL, y: q[4] ? y0 : pT,
    width: q[3] ? x1 - x0 : x0 - pL, height: q[4] ? y1 - y0 : y0 - pT, fill: 'url(#stg-' + q[0] + ')', 'pointer-events': 'none'}));
});
```
```css
.scatter.cycle .stagebg{pointer-events:none}   /* clicks still reach bubbles; no animation, so reduced motion is unaffected */
```
Notes: the gradient ids must be unique if the chart is drawn twice on a page (prefix with the host id). On a phone (`narrow`) the
same code applies; the quadrants are smaller, so 6% stays the right strength. Contrast of labels and ticks is unchanged.

## Build it Better request (2 lines)
Sectors tab rotation chart: tint each quadrant very softly in its stage colour (Emerging cyan, Hot green, Fading blue, Falling red),
a radial fade from its corner at about 6% opacity, under everything else, so the four stages read at a glance. Mockup + snippet attached.
