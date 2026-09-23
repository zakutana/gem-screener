# Gem Screener

> **English:** a crypto screener over DeFiLlama and CoinGecko data — how much a
> project earns, what it costs relative to that, whether its token can really be
> bought, and which market narrative it rides. The UI is Czech with an English
> switch (`#en`). **The full architecture and specification:
> [ARCHITECTURE.md](ARCHITECTURE.md). Rules for coding agents:
> [AGENTS.md](AGENTS.md).** MIT licensed. Not investment advice.

Screener kryptoprojektů nad daty DeFiLlamy a CoinGecka: kolik projekt vydělává,
kolik stojí, jestli se jeho token dá opravdu koupit, na jakém tržním narativu jede
a co se s ním chystá. Česky, s přepínačem do angličtiny.

## Co v tom je

- **Start (pro degena)** — appky, které projdou všemi 7 branami (byznys, prověření,
  cena, test 30×, růst, likvidita, téma s větrem), s pravidly „Kdy prodat“ a
  výsledkem předem zaregistrovaného zpětného testu nad nimi.
- **Apps a Chains** — seřazené podle Potenciálu (násobek vůči Hyperliquidu, u chainů
  vůči mediánu chainů), s důvěrou jako filtrem a štítky, nikdy jako pořadím. Každý
  řádek má téma a v tooltipu odkud.
- **Sektory** — 12 témat (AI, Memecoiny, DEX a perpy, RWA, Privacy, Prediction
  markets, DePIN, Gaming, DeFi úvěry a staking, L1, L2, Infrastruktura): jak moc
  zesilují BTC (beta s nejistotou), co už běží a jak roste jejich fundament.

## Spuštění

```
pip install -r requirements.txt
python collector.py        # sběr dat -> snapshot.json (3–6 min)
python app.py              # lokální stránka s tlačítkem Aktualizovat data
python build_viewer.py     # statická stránka gem_screener.html (anglicky, Apps)
```

Windows: `build_exe.bat` → `dist\GemScreener.exe` (stejná stránka, data vedle exe).

## Audity

`python audit.py`, `python audit_sectors.py`, `node audit_static.js` — přepočítají
každé číslo druhou implementací; když některý skončí chybou, nic se nezveřejní.
Zpětný test: `python backtest.py` (kritéria zamčená v `backtest_cache/prereg.lock`,
verdikt zatím NEPRŮKAZNÉ).

## Web (GitHub Pages)

`.github/workflows/update.yml` každých 6 hodin spustí collector, všechny tři audity,
sestaví stránku, nasadí ji na GitHub Pages a připíše výběr do `picks_ledger.jsonl`
(dopředný test tipů). Poběží, až bude repo veřejné:

1. repo veřejné, *Settings → Pages → Source: GitHub Actions*,
2. doporučeno: secret `COINGECKO_DEMO_KEY` (zdarma: coingecko.com → *Developer
   Dashboard* → *Demo API key*; *Settings → Secrets and variables → Actions*) —
   sdílené adresy GitHub Actions dostávají od CoinGecka častěji odmítnutí (429),
3. první push na `main` (nebo *Actions → Aktualizace Gem Screeneru → Run workflow*).

Adresa pak bude https://zakutana.github.io/gem-screener/.

## Licence

MIT — viz [LICENSE](LICENSE). Není to investiční doporučení.
