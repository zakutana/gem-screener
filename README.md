# Gem Screener

Screener kryptoprojektů nad daty DeFiLlamy a CoinGecka: kolik projekt vydělává,
kolik stojí, jestli se dá koupit a co se s ním chystá. Česky.

**Web:** https://zakutana.github.io/gem-screener/ — obnovuje se sám každých 6 hodin.

## Jak se to obnovuje

GitHub Actions (`.github/workflows/update.yml`) každých 6 hodin:

1. spustí `collector.py` (DeFiLlama, CoinGecko, DexScreener, datasety DeFiLlamy),
2. pustí všechny tři audity — **když některý selže, nic se nezveřejní** a web
   zůstane na poslední dobré verzi,
3. sestaví stránku (`build_viewer.py`) a nasadí ji na GitHub Pages,
4. připíše výběr do `picks_ledger.jsonl` (záznam tipů — dopředný test).

Ručně: záložka **Actions → Aktualizace Gem Screeneru → Run workflow**.

## CoinGecko klíč (doporučeno)

Sdílené adresy GitHub Actions dostávají od CoinGecka častěji odmítnutí (HTTP 429).
Zdarma: založ si účet na coingecko.com → *Developer Dashboard* → *Demo API key*
a ulož ho v repu jako secret `COINGECKO_DEMO_KEY`
(*Settings → Secrets and variables → Actions → New repository secret*).
Bez klíče to funguje taky, jen s větším rizikem, že některý běh selže.

## Lokálně

`python app.py` (nebo `dist\GemScreener.exe` z `build_exe.bat`) — stejná stránka
s tlačítkem Aktualizovat data.

Audity: `python audit.py`, `python audit_sectors.py`, `node audit_static.js`.
Zpětný test: `python backtest.py` (kritéria zamčená v `backtest_cache/prereg.lock`).

Není to investiční doporučení.
