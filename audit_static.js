/**
 * Static audit of the viewer's inline JS/CSS.
 *
 * Catches the class of bug that bit this project twice: regex surgery that
 * silently deletes a function, leaving valid JS that only fails at runtime.
 * `node --check` passes on such a file; only this does not.
 *
 * The identifier scan runs over code with comments AND string literals removed
 * by a real scanner. The old version regex-stripped them, which mispaired
 * quotes and reported Czech prose ("revenue", "adopce", "trendu") as undefined
 * functions — 20 false alarms that would hide one real one.
 *
 * Run: node audit_static.js
 */
const fs = require('fs');

const src = fs.readFileSync('template.html', 'utf8');
const scripts = [...src.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)].map(m => m[1]);
const js = scripts.filter(c => !c.includes('SNAPSHOT_JSON')).join('\n');
const css = (src.match(/<style>([\s\S]*?)<\/style>/) || [])[1] || '';
// ids can be declared inside script-generated markup too, so scan the whole file
// for id="..." rather than only the static body.
const htmlOnly = src.replace(/<script[\s\S]*?<\/script>/g, '').replace(/<style>[\s\S]*?<\/style>/g, '');

const problems = [];
const notes = [];

function head(t) { console.log('\n' + '='.repeat(74) + '\n' + t + '\n' + '='.repeat(74)); }

/**
 * Blank out comments and string/template/regex literals, preserving offsets so
 * line numbers stay meaningful. Returns code where only real syntax remains.
 */
function stripLiterals(code) {
  const out = Array.from(code);
  const blank = (from, to) => { for (let i = from; i < to && i < out.length; i++) if (out[i] !== '\n') out[i] = ' '; };
  let i = 0;
  let prevSignificant = '';
  while (i < code.length) {
    const c = code[i], d = code[i + 1];
    if (c === '/' && d === '/') { let j = code.indexOf('\n', i); if (j < 0) j = code.length; blank(i, j); i = j; continue; }
    if (c === '/' && d === '*') { let j = code.indexOf('*/', i + 2); j = j < 0 ? code.length : j + 2; blank(i, j); i = j; continue; }
    if (c === '"' || c === "'" || c === '`') {
      let j = i + 1;
      while (j < code.length) { if (code[j] === '\\') { j += 2; continue; } if (code[j] === c) break; j++; }
      blank(i, Math.min(j + 1, code.length)); i = j + 1; prevSignificant = 'x'; continue;
    }
    // a "/" is a regex only where a value cannot already have ended
    if (c === '/' && /[(,=:[!&|?{};+\-*%~^]/.test(prevSignificant)) {
      let j = i + 1, inClass = false;
      while (j < code.length) {
        if (code[j] === '\\') { j += 2; continue; }
        if (code[j] === '[') inClass = true;
        else if (code[j] === ']') inClass = false;
        else if (code[j] === '/' && !inClass) break;
        else if (code[j] === '\n') break;
        j++;
      }
      if (code[j] === '/') { while (/[a-z]/.test(code[j + 1] || '')) j++; blank(i, j + 1); i = j + 1; prevSignificant = 'x'; continue; }
    }
    if (!/\s/.test(c)) prevSignificant = c;
    i++;
  }
  return out.join('');
}

const code = stripLiterals(js);
const countIn = (hay, needle) => hay.split(needle).length - 1;

// ---------------------------------------------------------------- 1. functions
head('1. FUNKCE — definice vs volani');
const defs = [...code.matchAll(/function\s+([A-Za-z_$][\w$]*)/g)].map(m => m[1]);
const dupes = [...new Set(defs.filter((n, i) => defs.indexOf(n) !== i))];
if (dupes.length) problems.push('Duplicitni definice funkci (pozdejsi tise prepise drivejsi): ' + dupes.join(', '));
console.log('  definovano:', defs.length, '| duplicit:', dupes.length);

// "used" means called OR passed as a value (list.filter(passesFilter))
const used = new Set([...code.matchAll(/(?:^|[^.\w$])([A-Za-z_$][\w$]*)/g)].map(m => m[1]));
const usedCount = (n) => (code.match(new RegExp('(?:^|[^.\\w$])' + n + '(?![\\w$])', 'g')) || []).length;
const unused = defs.filter(n => usedCount(n) <= 1);
console.log('  nikdy nepouzite:', unused.length ? unused.join(', ') : 'zadne');
if (unused.length) notes.push('Mrtvy kod — nepouzite funkce: ' + unused.join(', '));

const localFns = [...new Set([...code.matchAll(/var\s+([A-Za-z_$][\w$]*)\s*=\s*function/g)].map(m => m[1]))];
const allVars = [...new Set([...code.matchAll(/\bvar\s+([A-Za-z_$][\w$]*)/g)].map(m => m[1]))];
const params = [...new Set([...code.matchAll(/function[^(]*\(([^)]*)\)/g)]
  .flatMap(m => m[1].split(',').map(s => s.trim())).filter(Boolean))];
const BUILTINS = new Set(`if for while switch catch return typeof function new do else delete void in instanceof
  parseFloat parseInt isNaN isFinite setTimeout clearTimeout setInterval clearInterval requestAnimationFrame
  encodeURIComponent decodeURIComponent getComputedStyle fetch alert confirm matchMedia
  String Number Boolean Array Object Math JSON Date Set Map Promise RegExp Error
  document window console location navigator history localStorage MutationObserver Intl`.split(/\s+/));
const called = [...new Set([...code.matchAll(/(?:^|[^.\w$])([a-z_$][\w$]*)\s*\(/g)].map(m => m[1]))];
const undef = called.filter(n => !defs.includes(n) && !localFns.includes(n) && !allVars.includes(n)
  && !params.includes(n) && !BUILTINS.has(n));
console.log('  volane ale nikde nedefinovane:', undef.length ? undef.join(', ') : 'zadne');
if (undef.length) problems.push('Volane nedefinovane identifikatory: ' + undef.join(', '));

// A function handed over WITHOUT parentheses is not a call, so the scan above
// never sees it — `el.addEventListener('mouseleave', hideTip)` with no hideTip
// defined passed this audit, and in strict mode it throws the moment that line
// runs, taking the whole chart down with it.
const passed = [...new Set([
  ...[...code.matchAll(/addEventListener\(\s*['"]?[\w ]*['"]?\s*,\s*([A-Za-z_$][\w$]*)\s*[,)]/g)].map(m => m[1]),
  ...[...code.matchAll(/\.(?:forEach|map|filter|sort|some|every|find|reduce)\(\s*([A-Za-z_$][\w$]*)\s*[,)]/g)].map(m => m[1]),
  ...[...code.matchAll(/(?:setTimeout|setInterval|requestAnimationFrame)\(\s*([A-Za-z_$][\w$]*)\s*[,)]/g)].map(m => m[1]),
])];
const undefPassed = passed.filter(n => !defs.includes(n) && !localFns.includes(n) && !allVars.includes(n)
  && !params.includes(n) && !BUILTINS.has(n) && !['function', 'true', 'false', 'null'].includes(n));
console.log('  predane jako callback ale nedefinovane:', undefPassed.length ? undefPassed.join(', ') : 'zadne');
if (undefPassed.length) problems.push('Callbacky bez definice (spadne pri registraci): ' + undefPassed.join(', '));

// ---------------------------------------------------------------- 2. DOM ids
head('2. DOM — getElementById vs skutecne id');
const wanted = [...new Set([...js.matchAll(/getElementById\(['"]([\w-]+)['"]\)/g)].map(m => m[1]))];
// an id may live in static markup OR in a template string inside the JS
const present = new Set([...src.matchAll(/\bid="([\w-]+)"/g)].map(m => m[1]));
const missingIds = wanted.filter(id => !present.has(id));
console.log('  id hledanych v JS:', wanted.length, '| chybejicich:', missingIds.length);
if (missingIds.length) problems.push('JS hleda neexistujici id: ' + missingIds.join(', '));

// ids assembled at runtime ('view-' + v, 'heroChart' + View) never appear whole
const builtFromPrefix = (name) => [...js.matchAll(/['"]([\w-]{2,})['"]\s*\+/g)]
  .some(m => name.startsWith(m[1]) && name !== m[1]);
const staticIds = new Set([...htmlOnly.matchAll(/\bid="([\w-]+)"/g)].map(m => m[1]));
const orphanIds = [...staticIds].filter(id => !wanted.includes(id) && !js.includes(`'${id}'`)
  && !new RegExp(`[#.]${id}\\b`).test(css) && !builtFromPrefix(id) && !js.includes(id));
console.log('  id v HTML nikde nepouzita:', orphanIds.length ? orphanIds.join(', ') : 'zadne');
if (orphanIds.length) notes.push('Nepouzita id v markupu: ' + orphanIds.join(', '));

// ---------------------------------------------------------------- 3. state
head('3. STATE — klice a jejich cteni');
const stateBlock = (code.match(/var state\s*=\s*\{([\s\S]*?)\n\};/) || [])[1] || '';
const stateKeys = [...stateBlock.matchAll(/^\s*(\w+)\s*:/gm)].map(m => m[1]);
const deadState = stateKeys.filter(k => countIn(code, 'state.' + k) <= 1);
console.log('  klicu:', stateKeys.join(', ') || '(zadny state blok)');
console.log('  nikde nectenych:', deadState.length ? deadState.join(', ') : 'zadne');
if (deadState.length) notes.push('Nepouzite state klice: ' + deadState.join(', '));

// v11 goal: the UI has no time-window switching left. Reported, not enforced,
// until the rewrite lands — then it should read 0.
const windowRefs = countIn(code, 'state.window') + countIn(code, 'WLABEL')
  + countIn(code, 'state.panelWindow');
console.log('  zbyvajici odkazy na casove okno (cil v11 = 0):', windowRefs);

// ---------------------------------------------------------------- 4. columns vs sorting
head('4. SLOUPCE — kazdy klic musi mit vetev v sortValue');
// from the RAW js: the keys we are looking for are string literals, and
// stripLiterals would have blanked every one of them.
// Each column set is paired with ITS sort function — Sektory sorts through
// themeSortValue, Apps/Chains through sortValue — and every sortable key must
// have a branch in the right one, or clicking that header silently does nothing.
const fnBody = (name) => (js.match(new RegExp('function ' + name + '\\([\\s\\S]*?\\n\\}')) || [''])[0];
const COL_SETS = { COLS_APPS: 'sortValue', COLS_CHAINS: 'sortValue', COLS_THEMES: 'themeSortValue' };
let totalCols = 0, totalSortable = 0;
const unsortable = [];
for (const [setName, sortName] of Object.entries(COL_SETS)) {
  const block = (js.match(new RegExp('var ' + setName + '\\s*=\\s*\\[([\\s\\S]*?)\\n\\];')) || [])[1];
  if (!block) continue;
  const lines = block.split('\n').filter(l => /\{\s*key\s*:\s*['"]\w+['"]/.test(l));
  const body = fnBody(sortName);
  if (!body) { problems.push(setName + ': razeni ' + sortName + '() v kodu neexistuje'); continue; }
  totalCols += lines.length;
  for (const l of lines) {
    if (/sortable\s*:\s*false/.test(l)) continue;
    totalSortable++;
    const k = /key\s*:\s*['"](\w+)['"]/.exec(l)[1];
    if (!new RegExp(`['"]${k}['"]`).test(body)) unsortable.push(setName + '.' + k + ' -> ' + sortName);
  }
}
console.log('  sloupcu:', totalCols, '| razenych:', totalSortable, '| bez vetve v razeni:', unsortable.length);
if (unsortable.length) problems.push('Sloupce bez razeni (klik nic neudela): ' + unsortable.join(', '));

// ---------------------------------------------------------------- 5. info popovers
head('5. NAPOVEDY — data-info vs INFO_TEXT');
// Keys reach data-info three ways: static HTML, column defs (`info: 'x'`), and the
// 4th argument of statCell(). Only the first used to be checked, so a typo in a
// panel key would have thrown on click and never shown up here.
function statCellKeys(code) {
  const keys = [];
  let i = 0;
  while ((i = code.indexOf('statCell(', i)) >= 0) {
    if (/[\w$.]/.test(code[i - 1] || '')) { i += 9; continue; }  // not `function statCell(` / obj.statCell
    let j = i + 9, depth = 1, q = null, start = j;
    const args = [];
    for (; j < code.length && depth; j++) {
      const c = code[j];
      if (q) { if (c === '\\') j++; else if (c === q) q = null; continue; }
      if (c === "'" || c === '"') q = c;
      else if (c === '(' || c === '[' || c === '{') depth++;
      else if (c === ')' || c === ']' || c === '}') { if (--depth === 0) args.push(code.slice(start, j)); }
      else if (c === ',' && depth === 1) { args.push(code.slice(start, j)); start = j + 1; }
    }
    const last = (args[3] || '').trim().match(/^'(\w+)'$/);
    if (last) keys.push(last[1]);
    i = j;
  }
  return keys;
}
const fnDef = /function statCell\(k, v, cls, info\)/.test(js);
const infoUsed = [...new Set([
  ...[...src.matchAll(/data-info="(\w+)"/g)].map(m => m[1]),
  ...[...js.matchAll(/\binfo:\s*'(\w+)'/g)].map(m => m[1]),
  ...(fnDef ? statCellKeys(js) : []),
])];
if (!fnDef) notes.push('statCell zmenil signaturu — klice z panelu se nekontroluji');
const infoBlock = (js.match(/var INFO_TEXT\s*=\s*\{[\s\S]*?\n\};/) || [''])[0];
const infoMissing = infoUsed.filter(k => !new RegExp(`\\b${k}\\s*:`).test(infoBlock));
console.log('  data-info klicu:', infoUsed.length, '| chybejicich v INFO_TEXT:', infoMissing.length);
if (infoMissing.length) problems.push('data-info bez textu v INFO_TEXT: ' + infoMissing.join(', '));

// ---------------------------------------------------------------- 6. served-only fetch
head('6. FETCH — jen pod GEM_SERVED');
const guard = code.indexOf('GEM_SERVED');
const fetches = [...code.matchAll(/(?:^|[^.\w$])fetch\s*\(/g)].map(m => m.index);
const strayFetch = guard < 0 ? fetches : fetches.filter(i => i < guard);
console.log('  fetch volani:', fetches.length, '| mimo GEM_SERVED blok:', strayFetch.length);
if (strayFetch.length) {
  problems.push(strayFetch.length + 'x fetch() mimo GEM_SERVED — staticky artifact by hlasil chybu v konzoli');
}

// ---------------------------------------------------------------- 7. CSS
head('7. CSS — tridy definovane vs pouzite');
// classes built at runtime from a prefix + value: 't'+tier, 'p-'+slug, 'q-'+q
const DYNAMIC_PREFIXES = ['t', 'p-', 'q-'];
const cssClasses = [...new Set([...css.matchAll(/\.([a-zA-Z][\w-]*)/g)].map(m => m[1]))];
const usedInHtml = new Set([...src.matchAll(/class="([^"]*)"/g)].flatMap(m => m[1].split(/\s+/)));
// the prefix is usually the tail of a longer literal: '<span class="catchip t' + tier
const concatTails = [...js.matchAll(/['"]([^'"\n]*)['"]\s*\+/g)].map(m => m[1]);
const dynamic = (c) => DYNAMIC_PREFIXES.some(p =>
  c.startsWith(p) && c !== p && concatTails.some(s => s.endsWith(p)));
// last resort is loose containment: most classes are emitted inside a longer
// string ('<span class="sharebadge big">'), and a note nobody trusts is worse
// than a note that occasionally misses a truly dead class.
const deadCss = cssClasses.filter(c => !usedInHtml.has(c) && !dynamic(c) && !js.includes(c));
console.log('  trid v CSS:', cssClasses.length, '| nikde nepouzitych:', deadCss.length);
if (deadCss.length) { console.log('   ', deadCss.join(', ')); notes.push('Mrtve CSS tridy: ' + deadCss.join(', ')); }

// ---------------------------------------------------------------- 8. theme tokens
head('8. TEMA — kazdy token musi existovat ve vsech trech blocich');
const blocks = {
  light: (css.match(/^:root\{([\s\S]*?)\n\}/m) || [])[1] || '',
  media: (css.match(/@media \(prefers-color-scheme: dark\)\{[\s\S]*?:root:not\(\[data-theme="light"\]\)\{([\s\S]*?)\n  \}/) || [])[1] || '',
  attr: (css.match(/:root\[data-theme="dark"\]\{([\s\S]*?)\n\}/) || [])[1] || '',
};
const tokensOf = (b) => new Set([...b.matchAll(/(--[\w-]+)\s*:/g)].map(m => m[1]));
const t = Object.fromEntries(Object.entries(blocks).map(([k, v]) => [k, tokensOf(v)]));
console.log('  tokenu light:', t.light.size, '| media-dark:', t.media.size, '| attr-dark:', t.attr.size);
['media', 'attr'].forEach(k => {
  const miss = [...t.light].filter(x => !t[k].has(x));
  if (miss.length) problems.push('Tokeny chybi v bloku ' + k + ' (zustanou svetle v tmavem tematu): ' + miss.join(', '));
});
const extra = [...t.media].filter(x => !t.light.has(x));
if (extra.length) problems.push('Tokeny jen v dark bloku (ve svetlem tematu nedefinovane): ' + extra.join(', '));

// var() inside a comment is not a usage — strip CSS comments first
const cssCode = css.replace(/\/\*[\s\S]*?\*\//g, '');
const usedVars = new Set([...cssCode.matchAll(/var\((--[\w-]+)/g)].map(m => m[1]));
const jsVars = new Set([...code.matchAll(/css\((?:'|")(--[\w-]+)/g)].map(m => m[1]));
const allDefined = new Set([...t.light, ...t.media, ...t.attr]);
const undefVars = [...new Set([...usedVars, ...jsVars])].filter(v => !allDefined.has(v) && !cssCode.includes(v + ':'));
console.log('  var() bez definice:', undefVars.length ? undefVars.join(', ') : 'zadne');
if (undefVars.length) problems.push('Pouzite ale nedefinovane CSS promenne: ' + undefVars.join(', '));

// ---------------------------------------------------------------- 9. hidden attribute
// Any class with its own display rule outranks the browser's [hidden]{display:none},
// so `hidden` silently stops hiding. That is how Refresh/Ukončit stayed visible
// (and dead) on the static artifact — .refreshbtn sets inline-flex.
head('9. HIDDEN — atribut hidden musi opravdu skryvat');
const hiddenAttrs = (htmlOnly.match(/<[a-z][^>]*\shidden(?=[\s>=\/])/gi) || []).length;
const hiddenSets = (code.match(/\.hidden\s*=(?!=)/g) || []).length;
const globalHidden = /\[hidden\]\s*\{\s*display\s*:\s*none\s*!important/.test(cssCode);
console.log('  hidden v HTML:', hiddenAttrs, '| prirazeni .hidden v JS:', hiddenSets, '| globalni [hidden] pravidlo:', globalHidden ? 'ano' : 'NE');
if ((hiddenAttrs || hiddenSets) && !globalHidden)
  problems.push('Stranka pouziva hidden, ale chybi [hidden]{display:none !important} — trida s vlastnim display ho prebije');

// ---------------------------------------------------------------- 10. views and switch
// Start is a fourth view: it must be in the nav, in setView's list and have its
// section, or clicking the tab leaves the old view showing. The switch moved from
// a boolean to three modes; a leftover onlyReliable would be a dead branch.
head('10. POHLEDY A PREPINAC — Start, tri polohy duvery');
const navViews = [...htmlOnly.matchAll(/data-view="(\w+)"/g)].map(m => m[1]);
const setViewList = ((js.match(/\[('start'[^\]]*)\]\.forEach/) || [])[1] || '').match(/'(\w+)'/g) || [];
const listed = setViewList.map(s => s.replace(/'/g, ''));
const sections = [...htmlOnly.matchAll(/id="view-(\w+)"/g)].map(m => m[1]);
for (const v of navViews) {
  if (!listed.includes(v)) problems.push('Zalozka ' + v + ' chybi v seznamu setView — klik by nic neprepnul');
  if (!sections.includes(v)) problems.push('Zalozka ' + v + ' nema sekci view-' + v);
}
if (/state\.onlyReliable/.test(code)) problems.push('Zbytek state.onlyReliable — prepinac uz ma tri polohy (trustMode)');
const modes = [...htmlOnly.matchAll(/data-mode="(\w+)"/g)].map(m => m[1]);
const pf = fnBody('passesFilter');
const unhandled = modes.filter(m => m !== 'all' && !pf.includes("'" + m + "'"));
if (unhandled.length) problems.push('Poloha prepinace bez vetve v passesFilter: ' + unhandled.join(', '));
console.log('  zalozky:', navViews.join(', '), '| setView:', listed.join(', '), '| polohy prepinace:', modes.join(', '));

// ---------------------------------------------------------------- verdict
head('VERDIKT');
if (problems.length) { console.log('CHYBY (' + problems.length + '):'); problems.forEach(p => console.log('  X ' + p)); }
else console.log('zadne tvrde chyby');
if (notes.length) { console.log('\nPOZNAMKY (' + notes.length + '):'); notes.forEach(n => console.log('  ! ' + n)); }
process.exit(problems.length ? 1 : 0);
