"""
Pre-registered consistency check of the Altseason cyklus index.

    python cycle_backtest.py --selftest   synthetic checks only, no data
    python cycle_backtest.py              lock PREREG + PREREG_V2, evaluate on cycle_history.json

Adam's requirement (2026-09-26): the index must sit on the 2017/18 and 2021
altseason peaks. With two peaks there is no statistics to speak of, and the design
already knew both cycles — so this is called what it is, a consistency check, not
an out-of-sample test. What keeps it honest:

- PREREG below is hashed into backtest_cache/cycle_prereg.lock the first time the
  script runs, BEFORE any index value is computed on real data (the design was
  debugged on synthetic series only). A changed PREREG is refused and needs a new id.
- Peaks are dated by stated rules, not picked by eye.
- Four variants of two knobs that can mis-time a gate by a week (breadth gate on the
  raw weekly or its 4-week mean; T = 0.9 or 0.85 x the index at the 2018 peak) and the
  rule that picks one are fixed here; all four are reported.
- If no variant passes, the report says FAIL and nothing is tuned.

v1 failed (2026-09-26: the 2017/18 cycle's highest week was June 2017, not Jan 2018)
and stays locked and reported. PREREG_V2 (2026-09-27) is a new registration with its
own id and lock (backtest_cache/cycle_prereg_v2.lock), committed before any v2 code
computed an index. It was designed after v1 failed, with both cycles in view, so it
passes by construction; the honest test is the forward ledger (cycle_ledger.jsonl).

Writes cycle_backtest_summary.json (v1 at the top level as before, v2 under "v2";
the collector reads the v2 rules) and cycle_backtest_report.html (charts for Adam).
"""
import datetime
import hashlib
import io
import json
import math
import os
import sys

import cycle

LOCK = os.path.join("backtest_cache", "cycle_prereg.lock")
LOCK_V2 = os.path.join("backtest_cache", "cycle_prereg_v2.lock")

PREREG = {
    "id": "altseason-cycle-v1",
    "registered": "2026-09-26",
    "weeks": "Monday 00:00 UTC; inputs from 2014-07-07",
    "components": {
        "rotation": ["BTC.D drawdown: 1 - mean4(BTC.D) / max(mean4(BTC.D), 52 w), trailing percentile",
                     "OTHERS.D rise: mean4(OTHERS.D) / min(mean4(OTHERS.D), 52 w) - 1, trailing percentile",
                     "breadth: share of top-50 alts beating BTC over 13 w, 4-week mean, used raw"],
        "heat": ["mean of trailing percentiles of MVRV ratio, Puell (issuance / 365-d mean), "
                 "Mayer (price / 200-d mean), Pi Cycle (111-d mean / 2 x 350-d mean); >= 3 of 4 present"],
    },
    "percentile": "mid-rank over the previous 208 weeks, current excluded, min 104 values",
    "index": "I = (rotation + heat) / 2; rotation needs >= 2 of 3 parts; None if a pillar is missing",
    "phases": {
        "order": ["po_vrcholu", "prehrate", "bezi", "zacina", "btc_sezona", "zima"],
        "po_vrcholu": "two consecutive prehrate weeks within the last 26 w and I <= their max - 15",
        "prehrate": "I >= T and breadth_gate >= 75 and BTC.D dd52 >= 25",
        "bezi": "rotation >= 60 and (gate >= 75 or (gate >= 50 and dd52 >= 25))",
        "zacina": "rotation >= 40 and (rotation up >= 15 over 13 w or an OTHERS.D breakout within 13 w)",
        "btc_sezona": "heat >= 50 and rotation < 40",
        "zima": "otherwise",
    },
    "T": "round(t_factor x max I over [P1 - 8 w, P1 + 2 w]), clamped to [80, 90]",
    "events": {
        "P0": "min weekly BTC.D in 2017-01-01..2017-09-30 (reported)",
        "P1": "min weekly BTC.D in [2017-12-17 - 26 w, + 13 w] (required)",
        "P2": "min weekly BTC.D in [2021-04-14 - 26 w, + 13 w] (required)",
        "P2b": "max OTHERS USD in 2021-07-01..2021-12-31 (reported)",
    },
    "evaluation_start": "first week where every component has >= 104 weeks of scores (index not None)",
    "pass": [
        "a prehrate week in [P - 8 w, P + 2 w] for P1 and for P2",
        "cycle 1 (eval start..2019-12-31) highest I week in [P1 - 12 w, P1 + 4 w]; "
        "cycle 2 (2020-01-01..2022-12-31) highest I week in [P2 - 12 w, P2 + 4 w]",
        "share of evaluated weeks with I >= T at most 10 %",
        "at most 2 prehrate episodes outside [P - 16 w, P + 8 w] of every event, not counting an episode "
        "followed by an OTHERS USD drawdown >= 40 % within 8 weeks (a caught local top)",
    ],
    "variants": [{"breadth_gate": g, "t_factor": f} for g in ("mean4", "raw") for f in (0.9, 0.85)],
    "selection": "passes all -> fewest false episodes -> fewest weeks >= T -> (mean4, 0.9)",
    "reported_only": ["forward 13/26-week OTHERS USD return and vs BTC per phase, by episode",
                      "window sensitivity 104/156/260 weeks"],
    # a literal: this used to read cycle.DEFAULT_RULES at import, so a v2 edit of the
    # defaults would have changed v1's hash and its lock would have refused every run
    "trendline": {"trend_break": 0.03, "trend_fail": 0.03, "trend_min_weeks": 40,
                  "trend_max_weeks": 156, "trend_pivot": 4, "trend_touch_gap": 8},
}
V1_SHA256 = "2fb9e3884563f40bcddbab7660595eb4a8b91b2119d59f07c0d82aad449917c7"   # = the v1 lock

# v2, registered 2026-09-27 after v1's FAIL. Every threshold the index, the phases,
# the retail score and the trendline use is in "rules"; cycle.DEFAULT_RULES must
# equal them (main() and the selftest refuse a drift). The texts are the definition.
PREREG_V2 = {
    "id": "altseason-cycle-v2",
    "registered": "2026-09-27",
    "supersedes": "altseason-cycle-v1 (FAIL on 2026-09-26; stays locked and reported)",
    "honesty": "Designed after v1 failed, with both altseasons in view; the planning run of 2026-09-27 "
               "computed these formulas on the real history before this registration, so passing is by "
               "construction: a consistency check, not a test. The test is forward: cycle_ledger.jsonl.",
    "job": "an exit gauge that works week by week during an altseason: the index climbs towards the level "
           "of past altseason ends, the phase says prehrate (Blizi se konec), then po_vrcholu",
    "weeks": "Monday 00:00 UTC stamps, inputs from 2014-07-07; daily inputs are read on the day before "
             "the stamp; weekly inputs after clean_spikes (a week > 25 % off two neighbours that agree "
             "within 10 % is dropped)",
    "rotation": {
        "parts": ["BTC.D drawdown dd = 1 - mean4(BTC.D) / max of mean4(BTC.D) over the 52 weeks up to t "
                  "(>= 40 values); score = 100 x dd / 0.50",
                  "OTHERS.D rise = mean4(OTHERS.D) / min of mean4(OTHERS.D) over the 52 weeks up to t "
                  "(>= 40 values) - 1; score = 100 x ln(1 + rise) / ln 3",
                  "breadth b = 4-week mean of the share of the top-50 alts beating BTC over 13 weeks "
                  "(that week's CMC listing, stablecoins and wrapped twins out); score = 100 x (b - 25) / 65"],
        "combine": "each part clamped to 0-100; rotation = mean of the parts present, >= 2 of 3",
        "why": "absolute scales: v1's trailing percentile scored a 3-12 % BTC.D dip 60-70 in 2022-24, "
               "which held no altseason",
    },
    "heat": "BTC heat, unchanged from v1: mean of the trailing percentiles (mid-rank, previous 208 weeks, "
            "current excluded, >= 104 values) of MVRV ratio, Puell (issuance / 365-day mean), Mayer "
            "(price / 200-day mean), Pi Cycle (111-day mean / 2 x 350-day mean); >= 3 of 4 present",
    "retail": {
        "rows": {
            "coinbase": "Coinbase Exchange BTC-USD + ETH-USD daily USD turnover (base volume x close, UTC "
                        "days, today's partial day dropped); mean of the days present among the 30 days "
                        "before the stamp, >= 20 present",
            "upbit": "Upbit weekly KRW turnover summed over every KRW market; the sum of the 4 weekly "
                     "candles of the 4 weeks before the stamp, all 4 present",
            "degen": "DeFiLlama 30-day revenue of Launchpad + Telegram Bot + Trading App on the day before "
                     "the stamp; the row starts on the first day it is >= $5M",
            "apps": "app_score of the best-ranked scored crypto app (US App Store; overall #1 = 100, #10 = "
                    "90, #100 = 60; Finance #10 = 50, #100 = 10; outside both = 5) in the newest ledger "
                    "entry of the 7 days before the stamp; used as is: no log score, no warm-up",
        },
        "score": "row score = 100 x clamp(1 + ln(x / M) / ln 20, 0, 1), M = the max of the row's positive "
                 "weekly samples over the 208 weeks up to and including the stamp; x <= 0 or missing = no "
                 "score (never passed to ln); the first 52 weeks after a row's first positive sample are "
                 "warm-up (no score)",
        "index": "retail = mean of the row scores present at the stamp, >= 1 row",
        "facts": "new stablecoin dollars (USDT + USDC, 13-week change), Coinbase web traffic (Tranco), AI "
                 "questions: shown, never scored",
    },
    "euphoria": "(retail + heat) / 2; none if either is missing",
    "index": "I = (2 x rotation + euphoria) / 3; none if either is missing",
    "T": 75,
    "phases": {
        "order": ["po_vrcholu", "prehrate", "bezi", "zacina", "btc_sezona", "zima"],
        "po_vrcholu": "at least 2 of the 26 weeks before t at I >= T, and I <= their max - 15",
        "prehrate": "I >= T and euphoria >= 70",
        "bezi": "rotation >= 60, or I >= T",
        "zacina": "rotation >= 30 and (rotation - rotation 13 weeks earlier >= 15, or an OTHERS.D breakout "
                  "event in weeks t - 13 .. t)",
        "btc_sezona": "heat >= 50 and rotation < 30",
        "zima": "otherwise",
    },
    "trendline": {
        "input": "weekly closes; week t sees closes up to t only; down = OTHERS.D resistance (d = +1), up = "
                 "BTC.D support (d = -1); more extreme = larger d x close",
        "anchor": "the most extreme close of the 312 weeks up to t (ties: the earliest); the anchor at t "
                  "itself = no line",
        "opposite": "the least extreme close after the anchor and at least 4 weeks before t (ties: the "
                    "latest); none = no line",
        "pivots": "closes strictly between anchor and opposite that are the most extreme of +-4 weeks and "
                  "strictly more extreme than the 4 weeks before them",
        "line": "through the anchor with slope s = d x max over the pivots of d x (c_j - c_a) / (j - a): the "
                "tightest line over the lower highs (under the higher lows); no pivot, or a line value <= 0 "
                "at t = no line",
        "beyond": "d x close > d x line x (1 + d x 0.03); inside: d x close <= d x line; breaks only after "
                  "the opposite extreme; a break = 2 consecutive closes beyond",
        "status": ["bez_trendu: no line",
                   "pruraz: the latest break with no close back inside since",
                   "pruraz_nepotvrzeny: the close at t beyond (one close)",
                   "zpet_pod: a break within the last 13 weeks (t - break <= 13) with a close back inside since",
                   "pruraz_nepotvrzeny: for the newest status only, the newest daily point beyond the line "
                   "extended to its day",
                   "downtrend: otherwise"],
        "breakout_event": "a week whose weekly status (no daily point) is pruraz after a week that was not",
    },
    "events": {
        "P0": "min weekly BTC.D in 2017-01-01..2017-09-30",
        "P1": "min weekly BTC.D in [2017-12-17 - 26 w, + 13 w]",
        "P2": "min weekly BTC.D in [2021-04-14 - 26 w, + 13 w]",
        "P2b": "max OTHERS USD in 2021-07-01..2021-12-31 (reported)",
    },
    "evaluation_start": "the first week with an index",
    "pass": [
        "a prehrate week in [P - 8 w, P + 2 w] for each of P0, P1, P2",
        "cycle 1 (evaluation start..2019-12-31): the highest-index week (ties: the earliest) in "
        "[P0 - 12 w, P0 + 4 w] or [P1 - 12 w, P1 + 4 w]; cycle 2 (2020-01-01..2022-12-31): in "
        "[P2 - 12 w, P2 + 4 w]",
        "at most 10 % of the evaluated weeks at I >= T",
        "at most 2 prehrate episodes starting outside [P - 16 w, P + 8 w] of every event (P0, P1, P2, P2b)",
    ],
    "reported_only": [
        "lead time: for P0, P1, P2, P minus the first week of the earliest prehrate episode with a week in "
        "[P - 8 w, P + 2 w]",
        "13/26-week OTHERS USD return and vs BTC after the start of every phase episode (prehrate and "
        "po_vrcholu first)",
        "the highest index from 2023-01-01 to the newest week, and each calendar year's maximum",
        "v1's verdict beside it (FAIL, never re-tuned)",
    ],
    "forward_test": "cycle_ledger.jsonl: one line per closed week (week, index, phase, rotation, euphoria, "
                    "retail, heat), appended by the collector after the snapshot is written; CI commits it",
    "rules": {
        "T": 75, "window": 208, "min_window": 104,
        "rot_dd_full": 50, "rot_rise_full": 3, "rot_breadth_lo": 25, "rot_breadth_hi": 90, "rot_min_parts": 2,
        "rot_weight": 2, "euph_weight": 1,
        "retail_window": 208, "retail_warmup": 52, "retail_span": 20, "retail_min_rows": 1,
        "coinbase_days": 30, "coinbase_min_days": 20, "meme_start_usd": 5000000, "apps_max_age_days": 7,
        "prehrate_euphoria": 70, "bezi_rotation": 60,
        "zacina_rotation": 30, "zacina_rise": 15, "zacina_weeks": 13,
        "btc_sezona_heat": 50, "btc_sezona_rotation": 30,
        "po_vrcholu_drop": 15, "po_vrcholu_weeks": 26, "po_vrcholu_min": 2,
        "trend_window": 312, "trend_pivot": 4, "trend_break": 0.03, "trend_confirm": 2, "trend_back_weeks": 13,
    },
}


V2_SHA256 = "c03f3450e3edd61cbad1077438adbb2cb93ee36fdd392b4e04392804a52d6914"   # = the v2 lock
V3_SHA256 = "7f4261689b356bb0eae55d862e44b87a46420ee9f9a4cd35ec4418bb8f4fd1b8"   # = the v3 lock

# v3, registered 2026-09-28 — this time BEFORE any v3 number was computed on the real
# history (the cloud session that wrote it has no market data; it was debugged on
# synthetic series only). Why a v3 at all: three independent reviews (method,
# engineering, product) agreed that v2 fits the past but could miss the next
# altseason — see the "why" texts. v2 stays locked and reported.
PREREG_V3 = {
    "id": "altseason-cycle-v3",
    "registered": "2026-09-28",
    "supersedes": "altseason-cycle-v2 (PASS by construction; stays locked and reported)",
    "honesty": "Registered before any v3 value was computed on the real history: the rules below were written "
               "and debugged on synthetic series only. The designers still knew both past altseasons, so the "
               "historical pass criteria are a consistency check; the forward ledger (cycle_ledger.jsonl) is the "
               "test.",
    "job": "an informative map of the altseason cycle for degens: how far money has rotated into alts and how "
           "euphoric the market is; the phase says when an altseason is on, near its end (prehrate, Blizi se "
           "konec) and past its top (po_vrcholu) - also for an altseason weaker or longer than 2017 and 2021",
    "why": [
        "BTC.D's floor rises every cycle (2018 low 32.8 %, 2022 low 37.9 %): v2's fixed scale (a 50 % drawdown "
        "= full) scores a real rotation from 65 % to 45 % at 62, so a weaker altseason could stay under 75 and "
        "never show either exit phase",
        "v2's one-year windows: an altseason that runs flat for longer than a year drifts out of them and v2 "
        "read po_vrcholu with nothing turned",
        "v2's exit phases both needed I >= 75",
        "v2's 4-week means needed all four weeks: one lost weekly listing blanked the index for four weeks",
    ],
    "weeks": "Monday 00:00 UTC stamps, inputs from 2014-07-07; weekly inputs after clean_spikes (a week > 25 % off "
             "two neighbours that agree within 10 % is dropped; the newest week, with no right neighbour, is judged "
             "by the two weeks before it and held back)",
    "mean4": "the mean of the values present among the 4 weeks up to t, at least 3 (roll_min)",
    "rotation": {
        "parts": ["BTC.D path = (P - B) / max(P - F, 25) x 100, where B = mean4(BTC.D) at t, P = the highest "
                  "mean4(BTC.D) of the 52 weeks up to t (>= 40 present; ties: the earliest) and F = the lowest "
                  "mean4(BTC.D) of the weeks t-311..t-52 (>= 52 present; ties: the latest): the share of the way "
                  "from the 1-year high down to the previous cycle's low; score = the path clamped to 0-100",
                  "OTHERS.D rise = mean4(OTHERS.D) / the lowest mean4(OTHERS.D) of the 52 weeks up to t (>= 40 "
                  "present) - 1; score = 100 x ln(1 + rise) / ln 3",
                  "breadth b = mean4 of the share of the top-50 alts beating BTC over 13 weeks (that week's CMC "
                  "listing, stablecoins and wrapped twins out); score = 100 x (b - 25) / 65"],
        "combine": "each part clamped to 0-100; rotation = mean of the parts present, >= 2 of 3",
    },
    "heat": "BTC heat as in v2 (mean of the trailing percentiles, mid-rank, previous 208 weeks, current excluded, "
            ">= 104 values, of MVRV ratio, Puell, Mayer, Pi Cycle; >= 3 of 4), each metric read on the newest day "
            "with a price among the 7 days before the stamp",
    "retail": "as in v2 (rows coinbase, upbit, degen, apps; 4-year log score; >= 1 row), with two fixes: a "
              "Coinbase day counts only when both pairs have it (ETH-USD from its first day), and the memecoin "
              "row reads the newest value among the 7 days before the stamp",
    "euphoria": "(retail + heat) / 2; none if either is missing",
    "index": "I = (2 x rotation + euphoria) / 3; none if either is missing",
    "T": 75,
    "phases": {
        "order": ["po_vrcholu", "prehrate", "bezi", "zacina", "btc_sezona", "zima"],
        "po_vrcholu": "at least 4 of the 26 weeks before t in phase bezi or prehrate, I <= the highest index of "
                      "those 26 weeks - 15, and mean4(OTHERS USD) at t <= 0.75 x its highest mean4 of the weeks "
                      "t-26..t (alts really fell in dollars)",
        "prehrate": "euphoria >= 70 and (I >= T or rotation >= 60)",
        "bezi": "rotation >= 60, or I >= T",
        "zacina": "rotation >= 30 and (rotation - rotation 13 weeks earlier >= 15, or an OTHERS.D breakout event "
                  "in the 13 weeks t-12..t)",
        "btc_sezona": "heat >= 50 and rotation < 30",
        "zima": "otherwise",
    },
    "trendline": "unchanged from PREREG_V2 (312-week anchor, pivots +-4, 3 % beyond, 2 closes, 13 weeks back)",
    "events": "as PREREG_V2: P0, P1, P2 = min weekly BTC.D in their windows, P2b = max OTHERS USD in 2021-H2",
    "evaluation_start": "the first week with an index",
    "pass": [
        "a prehrate week in [P - 8 w, P + 2 w] for each of P0, P1, P2",
        "cycle 1 (evaluation start..2019-12-31): the highest-index week (ties: the earliest) in "
        "[P0 - 12 w, P0 + 4 w] or [P1 - 12 w, P1 + 4 w]; cycle 2 (2020-01-01..2022-12-31): in [P2 - 12 w, P2 + 4 w]",
        "at most 10 % of the evaluated weeks at I >= T",
        "at most 2 prehrate episodes starting outside [P - 16 w, P + 8 w] of every event (P0, P1, P2, P2b)",
        "no prehrate week and no week at I >= T from 2023-01-01 to 2026-06-30 (Bitcoin made new highs with no "
        "altseason: the failure v1 had)",
    ],
    "selftest": "on synthetic series (no data): a weaker altseason - BTC.D from 65 % to 45 % over a previous-cycle "
                "low of 38 %, OTHERS.D x 2, breadth about 69 %, high euphoria - must read prehrate during it (v2 "
                "reads only bezi there) and po_vrcholu after alts fall in dollars; the same altseason held flat "
                "for 70 weeks must not read po_vrcholu while it runs",
    "reported_only": [
        "lead time for P0, P1, P2 as in v2",
        "every po_vrcholu episode with its start",
        "13/26-week OTHERS USD return and vs BTC after the start of every phase episode",
        "the highest index from 2023-01-01, each calendar year's maximum, the index at P0, P1, P2, P2b",
        "v1 (FAIL) and v2 (PASS by construction) beside it, never re-tuned",
    ],
    "forward_test": "cycle_ledger.jsonl: one line per closed week (week, index, phase, rotation, euphoria, retail, "
                    "heat, version, stale sources, scored retail rows)",
    "rules": {
        "T": 75, "window": 208, "min_window": 104, "roll_min": 3,
        "rot_floor_window": 312, "rot_floor_gap": 52, "rot_floor_min": 52,
        "rot_span_min": 25, "rot_rise_full": 3, "rot_breadth_lo": 25, "rot_breadth_hi": 90, "rot_min_parts": 2,
        "rot_weight": 2, "euph_weight": 1, "heat_max_age_days": 7,
        "retail_window": 208, "retail_warmup": 52, "retail_span": 20, "retail_min_rows": 1,
        "coinbase_days": 30, "coinbase_min_days": 20, "meme_start_usd": 5000000, "meme_max_age_days": 7,
        "apps_max_age_days": 7,
        "prehrate_euphoria": 70, "bezi_rotation": 60,
        "zacina_rotation": 30, "zacina_rise": 15, "zacina_weeks": 13,
        "btc_sezona_heat": 50, "btc_sezona_rotation": 30,
        "po_vrcholu_drop": 15, "po_vrcholu_weeks": 26, "po_vrcholu_min": 4, "po_vrcholu_usd_drop": 25,
        "trend_window": 312, "trend_pivot": 4, "trend_break": 0.03, "trend_confirm": 2, "trend_back_weeks": 13,
    },
    "rejected_before_registration": [
        "anchoring the BTC.D high and the OTHERS.D low at the previous cycle's low instead of a rolling year "
        "(against the long-plateau problem): on the synthetic history it held 2022's bear market at a rotation of "
        "about 85 and read bezi for half a year, because BTC.D stayed far under 2019's high",
        "anchoring at the most recent 52-week high: a year on a plateau makes a new 52-week high out of noise, "
        "the same failure as v2",
    ],
    "known_limit": "an altseason that runs flat for longer than a year still drifts out of the one-year windows: "
                   "after about a year its rotation fades and the phase falls back (to zima in the selftest) while "
                   "alts still hold - never to po_vrcholu while they hold their dollar value. No altseason so far "
                   "ran flat for a year (2017: about 10 months, 2021: about 5)",
}
LOCK_V3 = os.path.join("backtest_cache", "cycle_prereg_v3.lock")


def prereg_hash(p=None):
    return hashlib.sha256(json.dumps(PREREG if p is None else p, sort_keys=True).encode("utf-8")).hexdigest()


def prereg_lock(p=None, path=LOCK):
    """The first run writes the lock; every later run compares against it."""
    p = PREREG if p is None else p
    h = prereg_hash(p)
    if os.path.exists(path):
        lk = json.load(io.open(path, encoding="utf-8"))
        return lk, lk.get("sha256") == h
    os.makedirs(os.path.dirname(path), exist_ok=True)
    lk = {"id": p["id"], "sha256": h,
          "locked_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    with io.open(path, "w", encoding="utf-8") as f:
        json.dump(lk, f, indent=1)
    return lk, True


def file_sha(p):
    try:
        return hashlib.sha256(open(p, "rb").read()).hexdigest()
    except OSError:
        return None


# ================================================================== evaluation
def evaluate(weeks, s, ev, rules, eval_start, cycles):
    res = cycle.compute_index(weeks, s, rules)
    I, ph = res["index"], res["phase"]
    T = rules["T"]
    out = {"T": T}
    in_win = lambda i, P, lo, hi: P is not None and P - lo <= i <= P + hi
    # 1. prehrate around P1 and P2
    for P in ("P1", "P2"):
        p = ev.get(P)
        out["hit_" + P] = any(ph[i] == "prehrate" for i in range(len(weeks)) if in_win(i, p, 8, 2))
    # 2. cycle maxima
    for name, (lo, hi), P in (("c1", cycles[0], "P1"), ("c2", cycles[1], "P2")):
        idx = [i for i in range(len(weeks)) if lo <= weeks[i] <= hi and I[i] is not None]
        top = max(idx, key=lambda i: (I[i], -i)) if idx else None
        out["max_" + name] = top
        out["max_ok_" + name] = top is not None and in_win(top, ev.get(P), 12, 4)
    # 3. share of weeks >= T
    ev_idx = [i for i in range(len(weeks)) if weeks[i] >= eval_start and I[i] is not None]
    out["weeks_ge_T"] = sum(1 for i in ev_idx if I[i] >= T)
    out["share_ge_T"] = 100.0 * out["weeks_ge_T"] / max(1, len(ev_idx))
    # 4. false prehrate episodes
    eps = [e for e in cycle.phase_episodes(weeks, ph) if e[0] == "prehrate"]
    false, caught, near = [], [], []
    ou = s["others_usd"]
    for e in eps:
        a = e[1]
        if any(in_win(a, ev.get(P), 16, 8) for P in ("P0", "P1", "P2", "P2b")):
            near.append(e)
            continue
        base = ou[a]
        fut = [x for x in ou[a:a + 9] if x is not None]
        dd = (min(fut) / base - 1) * 100 if (base and fut) else None
        (caught if (dd is not None and dd <= -40) else false).append(e + [dd])
    out["episodes_near"] = [[weeks[e[1]], weeks[e[2]]] for e in near]
    out["episodes_caught"] = [[weeks[e[1]], weeks[e[2]], r1(e[3])] for e in caught]
    out["episodes_false"] = [[weeks[e[1]], weeks[e[2]], r1(e[3])] for e in false]
    out["pass"] = bool(out["hit_P1"] and out["hit_P2"] and out["max_ok_c1"] and out["max_ok_c2"]
                       and out["share_ge_T"] <= 10.0 and len(false) <= 2)
    out["_res"] = res
    return out


def r1(x):
    return None if x is None else round(x, 1)


def ts_utc(y, m, d):
    return int(datetime.datetime(y, m, d, tzinfo=datetime.timezone.utc).timestamp())


def evaluate_v2(weeks, s, rows, ev):
    """PREREG_V2: the four pass criteria and the reported-only numbers."""
    R = dict(cycle.V2_RULES)
    return _evaluate(weeks, cycle.compute_index_v2(weeks, s, rows, R), ev, R)


def evaluate_v3(weeks, s, rows, ev):
    """PREREG_V3: v2's four criteria plus a quiet 2023-01..2026-06 (Bitcoin's new
    highs with no altseason), and every po_vrcholu episode reported."""
    R = dict(cycle.V3_RULES)
    res = cycle.compute_index_v3(weeks, s, rows, R)
    out = _evaluate(weeks, res, ev, R)
    I, ph, T = res["index"], res["phase"], R["T"]
    lo, hi = ts_utc(2023, 1, 1), ts_utc(2026, 6, 30)
    quiet = [i for i in range(len(weeks)) if lo <= weeks[i] <= hi and I[i] is not None]
    loud = [i for i in quiet if I[i] >= T or ph[i] == "prehrate"]
    out["quiet_weeks"] = len(quiet)
    out["quiet_2023_2026"] = bool(quiet) and not loud
    out["loud_weeks_2023_2026"] = [weeks[i] for i in loud]
    out["pass"] = bool(out["pass"] and out["quiet_2023_2026"])
    out["po_vrcholu_episodes"] = [[weeks[a], weeks[b]] for p, a, b in cycle.phase_episodes(weeks, ph)
                                  if p == "po_vrcholu"]
    out["index_at_P2b"] = r1(I[ev["P2b"]]) if ev.get("P2b") is not None and I[ev["P2b"]] is not None else None
    return out


def _evaluate(weeks, res, ev, R):
    I, ph = res["index"], res["phase"]
    T = R["T"]
    n = len(weeks)
    in_win = lambda i, P, lo, hi: P is not None and P - lo <= i <= P + hi
    ev_idx = [i for i in range(n) if I[i] is not None]
    e0 = ev_idx[0] if ev_idx else None
    out = {"T": T, "eval_start": weeks[e0] if e0 is not None else None, "weeks_evaluated": len(ev_idx)}
    # 1. "Blíží se konec" around each altseason end
    for P in ("P0", "P1", "P2"):
        out["hit_" + P] = any(ph[i] == "prehrate" for i in range(n) if in_win(i, ev.get(P), 8, 2))
    # 2. each cycle's highest week near its tops (ties: the earliest)
    for name, lo, hi, Ps in (("c1", weeks[e0] if e0 is not None else 0, ts_utc(2019, 12, 31), ("P0", "P1")),
                             ("c2", ts_utc(2020, 1, 1), ts_utc(2022, 12, 31), ("P2",))):
        idx = [i for i in ev_idx if lo <= weeks[i] <= hi]
        top = max(idx, key=lambda i: (I[i], -i)) if idx else None
        out["max_" + name] = top
        out["max_ok_" + name] = top is not None and any(in_win(top, ev.get(P), 12, 4) for P in Ps)
    # 3. rare: at most 10 % of the weeks at I >= T
    out["weeks_ge_T"] = sum(1 for i in ev_idx if I[i] >= T)
    out["share_ge_T"] = 100.0 * out["weeks_ge_T"] / max(1, len(ev_idx))
    # 4. false alarms: prehrate episodes starting away from every event
    eps = [e for e in cycle.phase_episodes(weeks, ph) if e[0] == "prehrate"]
    near = [e for e in eps if any(in_win(e[1], ev.get(P), 16, 8) for P in ("P0", "P1", "P2", "P2b"))]
    false = [e for e in eps if e not in near]
    out["episodes_near"] = [[weeks[e[1]], weeks[e[2]]] for e in near]
    out["episodes_false"] = [[weeks[e[1]], weeks[e[2]]] for e in false]
    out["pass"] = bool(out["hit_P0"] and out["hit_P1"] and out["hit_P2"] and out["max_ok_c1"] and out["max_ok_c2"]
                       and out["share_ge_T"] <= 10.0 and len(false) <= 2)
    # reported only: how early the warning came, the recent years, each year's max
    lead = {}
    for P in ("P0", "P1", "P2"):
        p = ev.get(P)
        hit = [e for e in eps if any(in_win(i, p, 8, 2) for i in range(e[1], e[2] + 1))]
        lead[P] = (p - min(e[1] for e in hit)) if hit else None
    out["lead_weeks"] = lead
    recent = [i for i in ev_idx if weeks[i] >= ts_utc(2023, 1, 1)]
    top = max(recent, key=lambda i: (I[i], -i)) if recent else None
    out["max_since_2023"] = {"week": weeks[top], "index": r1(I[top])} if top is not None else None
    yearly = {}
    for i in ev_idx:
        y = str(datetime.datetime.fromtimestamp(weeks[i], datetime.timezone.utc).year)
        yearly[y] = max(yearly.get(y, -1.0), I[i])
    out["yearly_max"] = {y: r1(v) for y, v in sorted(yearly.items())}
    out["_res"] = res
    return out


def forward_by_phase(weeks, s, phase):
    """What alts did after each phase episode started: 13/26 weeks, OTHERS USD
    and OTHERS vs BTC. Episodes, not weeks — neighbouring weeks are one event."""
    ou, btc = s["others_usd"], s["btc"]
    out = {}
    for p, a, b in cycle.phase_episodes(weeks, phase):
        row = {"start": weeks[a], "end": weeks[b]}
        for h in (13, 26):
            j = a + h
            if j < len(weeks) and ou[a] and ou[j]:
                row["usd%d" % h] = round((ou[j] / ou[a] - 1) * 100, 1)
                if btc[a] and btc[j]:
                    row["vbtc%d" % h] = round(((ou[j] / ou[a]) / (btc[j] / btc[a]) - 1) * 100, 1)
        out.setdefault(p, []).append(row)
    return out


# ================================================================== selftest
def selftest():
    ok = True

    def check(cond, msg):
        nonlocal ok
        print(("  ok   " if cond else "  FAIL ") + msg)
        ok = ok and cond

    # v1 is locked and still reported: its registration and its rules must not move
    check(prereg_hash() == V1_SHA256, "v1 PREREG hash unchanged (%s…)" % prereg_hash()[:12])
    check(all(cycle.V1_RULES[k] == v for k, v in PREREG["trendline"].items()),
          "v1 trendline rules = the registered literals")
    check(prereg_hash(PREREG_V2) == V2_SHA256, "v2 PREREG hash = its lock (%s…)" % prereg_hash(PREREG_V2)[:12])
    # percentile: mid-rank, ties split
    check(cycle.pct_rank([1, 2, 3, 4], 3) == 62.5, "mid-rank percentile with a tie")
    tp = cycle.trailing_pct(list(range(300)), 208, 104)
    check(tp[103] is None and tp[104] == 100.0, "trailing percentile starts at 104 values, new high = 100")
    # a planted downtrend and breakout
    # anchor 12,0 at week 10, a lower high at week 30 sets the line (slope -0,035),
    # the line is at 9,9 on week 70; a close of 11,0 there is 11 % over it
    vals = [10.0] * 10 + [12.0] + [12.0 - 0.05 * k for k in range(1, 60)] + [11.0] * 5
    vals[30] = vals[30] + 0.3
    lines = cycle.trend_break(vals, "down")
    b = [L for L in lines if L["anchor"] == 10]
    check(bool(b) and b[0]["breakout"] == 70 and b[0]["touch"] == 30, "planted breakout found at its week")
    poke = [10.0] * 10 + [12.0] + [12.0 - 0.05 * k for k in range(1, 60)]
    poke[30] += 0.3
    line = poke[10] + max((poke[j] - poke[10]) / (j - 10) for j in range(11, 70)) * (70 - 10)
    poke.append(line * 1.02)
    check(not any(L["breakout"] == 70 for L in cycle.trend_break(poke, "down") if L["anchor"] == 10),
          "a 2 % poke is not a breakout")
    lu = cycle.trend_break([30 - v for v in vals], "up")
    check(any(L["anchor"] == 10 and L["breakout"] == 70 for L in lu), "mirror case (rising support) finds the breakdown")
    killed = [10.0] * 10 + [12.0] + [11.0] * 50 + [12.5] + [11.0] * 10
    check(not any(L["anchor"] == 10 for L in cycle.trend_break(killed, "down")), "an exceeded anchor is dropped")
    # the index on a synthetic cycle: flat, then a rotation + heat surge
    n = 400
    weeks = [cycle.START_WEEK + i * cycle.WEEK for i in range(n)]
    import random
    rnd = random.Random(7)
    bd = [70 + rnd.uniform(-1, 1) for _ in range(n)]
    od = [5 + rnd.uniform(-0.2, 0.2) for _ in range(n)]
    br = [30 + rnd.uniform(-5, 5) for _ in range(n)]
    heat = [1 + rnd.uniform(-0.1, 0.1) for _ in range(n)]
    for i in range(330, 345):                        # the planted altseason
        k = i - 329
        bd[i] = 70 - 3 * k
        od[i] = 5 + 0.8 * k
        br[i] = 95
        heat[i] = 1 + 0.3 * k
    s = {"btcd": bd, "othersd": od, "breadth": br, "others_usd": od, "btc": [1.0] * n,
         "mvrv": heat, "puell": heat, "mayer": heat, "pi": heat, "breakouts": [False] * n}
    res = cycle.compute_index(weeks, s, dict(cycle.DEFAULT_RULES, T=85))
    peak = max(range(n), key=lambda i: res["index"][i] or -1)
    check(330 <= peak <= 345, "synthetic peak lands in the planted altseason (week %d)" % peak)
    check("prehrate" in res["phase"][330:346], "the planted altseason reads prehrate")
    check("prehrate" not in res["phase"][:320], "no prehrate before it")
    check(res["phase"][200] in ("zima", "btc_sezona", "zacina", "bezi"), "a quiet week has a phase")
    # NaN must be refused before it reaches the page
    try:
        json.dumps({"x": float("nan")}, allow_nan=False)
        check(False, "NaN rejected")
    except ValueError:
        check(True, "NaN rejected by allow_nan=False")
    ok = selftest_v2(check) and ok
    ok = selftest_v3(check) and ok
    print("SELFTEST", "OK" if ok else "FAILED")
    return 0 if ok else 1


def selftest_v2(check):
    """v2 on synthetic series only (no data): the registration, the trendline, the
    four-year log score and the index."""
    ok = True

    def chk(cond, msg):
        nonlocal ok
        check(cond, msg)
        ok = ok and bool(cond)
    R2 = PREREG_V2["rules"]
    drift = sorted(k for k in R2 if cycle.V2_RULES.get(k) != R2[k])
    chk(not drift, "cycle.V2_RULES = PREREG_V2 rules%s" % (" (drift: %s)" % ", ".join(drift) if drift else ""))
    # --- the trendline: anchor 20 at week 10, one lower high 16 at week 50 (slope -0,1
    # a week), the bottom 8 at week 90, then two closes > 3 % over the line (105, 106)
    L0 = lambda i: 20 - 0.1 * (i - 10)
    c = [10.0] * 10 + [20.0] + [20 - 0.15 * (i - 10) for i in range(11, 91)]
    c[50] = 16.0
    c += [8 + 0.2 * (i - 90) for i in range(91, 105)] + [11.0, 11.2, L0(107) * 1.01, L0(108) * 0.98]
    c += [L0(i) * 0.97 for i in range(109, 121)] + [8.2, 7.8, 7.5, 7.6, 7.7, 7.8, 7.9, 8.0]
    tl = lambda t, **kw: cycle.trend_line(c, "down", t, **kw)
    L = tl(106)
    chk((L["anchor"], L["touch"], L["opp"], round(L["slope"], 6)) == (10, 50, 90, -0.1),
        "planted hull: anchor, the lower high it touches, the bottom, slope")
    chk([tl(t)["status"] for t in (104, 105, 106)] == ["downtrend", "pruraz_nepotvrzeny", "pruraz"],
        "one close over the line is unconfirmed, two are a break (from %s)" % L["break_first"])
    chk(tl(107)["status"] == "pruraz", "a retest that holds within 3 % keeps the break")
    chk(tl(108)["status"] == "zpet_pod" and tl(119)["status"] == "zpet_pod" and tl(120)["status"] == "downtrend",
        "back inside: false breakout for 13 weeks, then downtrend")
    L = tl(127)
    chk(L["touch"] == 106 and L["opp"] == 123 and L["status"] == "downtrend",
        "a new bottom after the failed break redraws the line over the false-break high")
    st, ev = cycle.trend_weekly(c, "down")
    chk([i for i, e in enumerate(ev) if e] == [106], "one breakout event, at the confirming week")
    chk(tl(104, latest=(104.5, 11.2))["status"] == "pruraz_nepotvrzeny", "the newest daily point over the line is unconfirmed")
    u = [12.0] * 10 + [10.0] + [10 + 0.08 * (i - 10) for i in range(11, 91)]
    u[50] = 12.0
    u += [16.4 - 0.3 * (i - 90) for i in range(91, 105)]
    chk([cycle.trend_line(u, "up", t)["status"] for t in (98, 99, 100)] == ["downtrend", "pruraz_nepotvrzeny", "pruraz"],
        "BTC.D mode: support from the low under the higher low, broken downwards")
    o = [10 + (i % 7) * 0.1 for i in range(330)]
    o[5] = 30.0
    chk(cycle.trend_line(o, "down", 316)["anchor"] == 5 and cycle.trend_line(o, "down", 317)["anchor"] != 5,
        "an anchor 311 weeks old is kept (6-year window), at 312 it drops out")
    chk(cycle.trend_line([float(i) for i in range(1, 30)], "down", 28)["status"] == "bez_trendu",
        "bez_trendu: the week is itself the 6-year extreme")
    chk(cycle.trend_line([30.0 - i * 0.5 for i in range(40)], "down", 39)["status"] == "bez_trendu",
        "bez_trendu: no pivot between the anchor and the bottom")
    chk(cycle.trend_line([10.0] * 40 + [20.0, 19.0, 18.0, 17.5], "down", 43)["status"] == "bez_trendu",
        "bez_trendu: no bottom 4 weeks old yet")
    # --- the four-year log score
    xs = [0.0] * 5 + [None] * 3 + [100.0] * 60 + [5.0, 100 / math.sqrt(20), 0.0, None, 100.0]
    sc = cycle.retail_scores({"coinbase": xs})["coinbase"]
    chk(all(v is None for v in sc[:60]) and sc[60] == 100.0, "52-week warm-up from the first positive sample, then 100 at the high")
    chk(abs(sc[68]) < 1e-9 and abs(sc[69] - 50) < 1e-9, "1/20 of the 4-year high = 0, 1/sqrt(20) = 50")
    chk(sc[70] is None and sc[71] is None and sc[72] == 100.0, "zero and missing samples are skipped, never passed to ln")
    xs = [100.0] * 60 + [1000.0] + [100.0] * 300
    sc = cycle.retail_scores({"upbit": xs})["upbit"]
    chk(abs(sc[267] - 100 * (1 - math.log(10) / math.log(20))) < 1e-9 and sc[268] == 100.0,
        "the max is over the last 208 weekly samples")
    chk(cycle.retail_scores({"apps": [None, 42.0]})["apps"] == [None, 42.0], "the App Store row is used as is")
    # --- the index on a synthetic cycle: quiet years, then a planted altseason
    import random
    n = 520
    weeks = [cycle.START_WEEK + i * cycle.WEEK for i in range(n)]
    rnd = random.Random(11)
    bd = [70 + rnd.uniform(-1, 1) for _ in range(n)]
    od = [5 + rnd.uniform(-0.2, 0.2) for _ in range(n)]
    br = [30 + rnd.uniform(-5, 5) for _ in range(n)]
    ht = [1 + rnd.uniform(-0.1, 0.1) for _ in range(n)]
    cb = [1e9 * (1 + rnd.uniform(-0.1, 0.1)) for _ in range(n)]
    for i in range(430, 446):
        k = i - 429
        bd[i], od[i], br[i], ht[i], cb[i] = 70 - 2.3 * k, 5 + 0.7 * k, 95, 1 + 0.3 * k, 1e9 * (1 + 0.8 * k)
    for i in range(446, n):
        bd[i], od[i], br[i] = 55 + rnd.uniform(-1, 1), 7 + rnd.uniform(-0.2, 0.2), 20 + rnd.uniform(-5, 5)
        ht[i], cb[i] = 1.2 + rnd.uniform(-0.1, 0.1), 2e9 * (1 + rnd.uniform(-0.1, 0.1))
    s = {"btcd": bd, "othersd": od, "breadth": br, "mvrv": ht, "puell": ht, "mayer": ht, "pi": ht}
    rows = {"coinbase": cb, "upbit": [None] * n, "degen": [None] * n, "apps": [None] * n}
    r = cycle.compute_index_v2(weeks, s, rows)
    I, ph = r["index"], r["phase"]
    peak = max(range(n), key=lambda i: I[i] if I[i] is not None else -1)
    chk(430 <= peak <= 446 and I[peak] >= 75, "v2 peak in the planted altseason (week %d, %.0f)" % (peak, I[peak]))
    chk("prehrate" in ph[430:447] and "prehrate" not in ph[:430], "prehrate on the planted top only")
    chk(all(p == "po_vrcholu" for p in ph[447:470]), "po_vrcholu after the top")
    chk(max(x for x in I[:425] if x is not None) < 75, "quiet years stay under T")
    chk(all(p is None or p in cycle.PHASES_V2 for p in ph), "every week has a known phase")
    return ok


def weak_altseason(hold, seed=5):
    """PREREG_V3's selftest scenario: a previous cycle's BTC.D low of 38 %, years at
    62–65 %, then a weaker altseason — BTC.D 65 -> 45 % in 20 weeks, OTHERS.D x 2,
    breadth ~69 %, retail and BTC heat up — held `hold` weeks, then alts fall (OTHERS
    in dollars -45 %) and BTC.D recovers."""
    import random
    rnd = random.Random(seed)
    n = 520 + hold + 80
    weeks = [cycle.START_WEEK + i * cycle.WEEK for i in range(n)]
    bd, od, br, ht, cb, ou = [], [], [], [], [], []
    for i in range(n):
        if i < 230:
            b = 62
        elif i < 250:
            b = 62 - (i - 230) * 1.2
        elif i < 280:
            b = 38 + (i - 250) * 0.8
        elif i < 500:
            b = 62 + min(3, (i - 280) * 0.05)
        elif i < 520:
            b = 65 - (i - 500)
        elif i < 520 + hold:
            b = 45
        else:
            b = min(58, 45 + (i - 520 - hold) * 1.0)
        bd.append(b + rnd.uniform(-0.5, 0.5))
        alt = 500 <= i < 520 + hold
        ramp = min(1, max(0, (i - 500) / 20))
        od.append((5 * (1 + ramp) if alt else (6 if i >= 500 else 5)) + rnd.uniform(-0.1, 0.1))
        br.append((69 if alt and i >= 506 else 30) + rnd.uniform(-2, 2))
        ht.append((1 + 0.4 * ramp if alt else (1.1 if i >= 500 else 1)) + rnd.uniform(-0.03, 0.03))
        cb.append((6e9 if 350 <= i < 360 else (3e9 if alt else 1e9)) * (1 + rnd.uniform(-0.05, 0.05)))
        ou.append((100 if alt else (55 if i >= 500 else 50)) * (1 + rnd.uniform(-0.03, 0.03)))
    s = {"btcd": bd, "othersd": od, "breadth": br, "mvrv": ht, "puell": ht, "mayer": ht, "pi": ht, "others_usd": ou}
    rows = {"coinbase": cb, "upbit": [None] * n, "degen": [None] * n, "apps": [None] * n}
    return weeks, s, rows


def selftest_v3(check):
    """v3 on synthetic series only: the registration, the BTC.D path to the old low,
    the weaker and the longer altseason, the data fixes."""
    ok = True

    def chk(cond, msg):
        nonlocal ok
        check(cond, msg)
        ok = ok and bool(cond)
    R3 = PREREG_V3["rules"]
    drift = sorted(k for k in R3 if cycle.V3_RULES.get(k) != R3[k])
    chk(not drift, "cycle.V3_RULES = PREREG_V3 rules%s" % (" (drift: %s)" % ", ".join(drift) if drift else ""))
    chk(prereg_hash(PREREG_V3) == V3_SHA256, "v3 PREREG hash = its lock (%s…)" % prereg_hash(PREREG_V3)[:12])
    chk(cycle.DEFAULT_RULES == cycle.V3_RULES, "the page runs v3")
    # --- one missing week does not blank a 4-week mean; two do
    m = cycle.roll_mean_min([1.0, 2.0, None, 4.0, 5.0, None, None, 8.0], 4, 3)
    chk(m[3] == 7 / 3 and m[4] == 11 / 3 and m[6] is None, "4-week mean from 3 of 4 weeks, none from 2")
    # --- the BTC.D path: 1-year high 65, previous cycle's low 38, now 45 = 74 % of the way
    n = 400
    bd = [60.0] * 100 + [38.0] * 10 + [60.0] * 180 + [65.0] * 30 + [65.0 - k for k in range(1, 21)] + [45.0] * 60
    flat = [5.0] * n
    ro = cycle.rotation_v3({"btcd": bd, "othersd": flat, "breadth": [50.0] * n}, cycle.V3_RULES)
    i = 343
    chk(abs(ro["path"][i] - 100 * 20 / 27) < 1e-9 and ro["floor"][i] == 38.0 and ro["peak_at"][i] == 293,
        "BTC.D path = (65 - 45) / (65 - 38) = %.1f %% (v2: dd %.0f %% scored %.0f)" % (ro["path"][i], 100 * 20 / 65, 100 * 20 / 65 / 0.5))
    lo = [60.0] * 300 + [50.0] * 60 + [45.0 - 0.1 * k for k in range(40)]
    ro = cycle.rotation_v3({"btcd": lo, "othersd": flat, "breadth": [50.0] * n}, cycle.V3_RULES)
    chk(abs(ro["path"][399] - 100 * (50 - ro["bd4"][399]) / 25) < 1e-9 and ro["floor"][399] == 50.0,
        "a span under 25 pp counts as 25 pp (the old low is the 1-year high itself)")
    # --- the weaker altseason: v3 says "Blíží se konec", v2 never does; "Po vrcholu" after alts fall
    weeks, s, rows = weak_altseason(15)
    r3 = cycle.compute_index_v3(weeks, s, rows)
    r2 = cycle.compute_index_v2(weeks, s, rows)
    chk("prehrate" in r3["phase"][505:536], "weaker altseason: v3 reads prehrate (max index %.0f, rotation %.0f)"
        % (max(r3["index"][505:536]), max(r3["rotation"][505:536])))
    chk("prehrate" not in r2["phase"][505:536], "… where v2 reads only bezi (max index %.0f)" % max(r2["index"][505:536]))
    chk("po_vrcholu" in r3["phase"][535:560], "po_vrcholu after alts fall")
    chk("po_vrcholu" not in r3["phase"][:535] and "prehrate" not in r3["phase"][:500], "nothing before it")
    # --- the same altseason flat for 70 weeks: no po_vrcholu while alts hold their dollars
    weeks, s, rows = weak_altseason(70)
    r3 = cycle.compute_index_v3(weeks, s, rows)
    chk("po_vrcholu" not in r3["phase"][500:590], "a 70-week plateau never reads po_vrcholu while it runs")
    # (after a year flat the one-year windows have drifted and the phase fell back
    # before alts fell, so no po_vrcholu follows — PREREG_V3 "known_limit")
    chk(all(p is None or p in cycle.PHASES_V2 for p in r3["phase"]), "every week has a known phase")
    # --- the newest week has no right neighbour: a spike there is held back
    ws = [cycle.START_WEEK + i * cycle.WEEK for i in range(6)]
    sp = {"othersd": [10.0, 10.1, 10.2, 10.0, 10.1, 5.0], "btcd": [50.0] * 6, "others_usd": [1.0] * 6,
          "breadth": [40.0] * 6}
    an = cycle.clean_spikes(ws, sp)
    chk(sp["othersd"][5] is None and sp["breadth"][5] is None and an and an[-1].get("held"),
        "a spike in the newest week is held back")
    sp = {"othersd": [10.0, 10.1, 13.0, 13.2, 13.1, 13.3], "btcd": [50.0] * 6, "others_usd": [1.0] * 6,
          "breadth": [40.0] * 6}
    chk(not cycle.clean_spikes(ws, sp), "a real 30 % move that holds is not a spike")
    # --- data fixes: a Coinbase day needs both pairs; the memecoin row reads the newest of 7 days
    d0 = cycle.COINBASE_PAIRS[1][1] + 100 * cycle.DAY
    w = cycle.monday(d0 + 40 * cycle.DAY)
    btc = {str(d0 + j * cycle.DAY): 100.0 for j in range(40)}
    eth = {str(d0 + j * cycle.DAY): 50.0 for j in range(40) if j not in (35, 36, 37)}
    H = {"cbx": {"BTC-USD": btc, "ETH-USD": eth}, "meme30": {str(w - 3 * cycle.DAY): 6e6}}
    rw, _ = cycle.retail_rows(H, [w], cycle.V3_RULES)
    chk(rw["coinbase"] == [150.0], "a day without ETH-USD is skipped, never counted as $0 (%s)" % rw["coinbase"])
    chk(rw["degen"] == [6e6], "the memecoin row reads the newest value of the 7 days before the stamp")
    rw, _ = cycle.retail_rows(H, [w], cycle.V2_RULES)
    chk(rw["degen"] == [None], "… v2 kept the exact day")
    return ok


# ================================================================== report
def svg_line(weeks, series_list, w=980, h=260, y_fmt=lambda v: "%.0f" % v, bands=None, shade=None,
             lines=None, marks=None, ymin=None, ymax=None):
    xs = [i for i in range(len(weeks))]
    allv = [v for ser, _ in series_list for v in ser if v is not None]
    lo = min(allv) if ymin is None else ymin
    hi = max(allv) if ymax is None else ymax
    pad = 40
    X = lambda i: pad + (w - pad - 10) * i / max(1, len(weeks) - 1)
    Y = lambda v: 10 + (h - 30) * (1 - (v - lo) / ((hi - lo) or 1))
    out = ['<svg width="%d" height="%d" style="background:#1b1816;border-radius:8px">' % (w, h)]
    for y0, y1, col in bands or []:
        out.append('<rect x="%d" y="%.1f" width="%d" height="%.1f" fill="%s" opacity=".12"/>'
                   % (pad, Y(y1), w - pad - 10, Y(y0) - Y(y1), col))
    for a, b, col in shade or []:
        out.append('<rect x="%.1f" y="10" width="%.1f" height="%d" fill="%s" opacity=".25"/>'
                   % (X(a), max(2, X(b) - X(a)), h - 30, col))
    for v in (lo, (lo + hi) / 2, hi):
        out.append('<text x="4" y="%.1f" fill="#8c8175" font-size="10">%s</text>' % (Y(v) + 3, y_fmt(v)))
    yr = None
    for i, t in enumerate(weeks):
        y = datetime.datetime.fromtimestamp(t, datetime.timezone.utc).year
        if y != yr:
            yr = y
            out.append('<text x="%.1f" y="%d" fill="#8c8175" font-size="10">%d</text>' % (X(i), h - 6, y))
    for ser, col in series_list:
        d = []
        for i, v in enumerate(ser):
            if v is None:
                continue
            d.append(("M" if not d or ser[i - 1] is None else "L") + "%.1f %.1f" % (X(i), Y(v)))
        out.append('<path d="%s" fill="none" stroke="%s" stroke-width="1.6"/>' % ("".join(d), col))
    for (i0, v0, i1, v1, col) in lines or []:
        out.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" stroke-dasharray="5 4" stroke-width="1.5"/>'
                   % (X(i0), Y(v0), X(i1), Y(v1), col))
    for (i, v, col, label) in marks or []:
        out.append('<circle cx="%.1f" cy="%.1f" r="4" fill="%s"/><text x="%.1f" y="%.1f" fill="%s" font-size="11">%s</text>'
                   % (X(i), Y(v), col, X(i) + 6, Y(v) - 6, col, label))
    out.append("</svg>")
    return "".join(out)


PH_COL = {"zima": "#8c8175", "btc_sezona": "#5c82c4", "zacina": "#3fa37e", "bezi": "#b98a34",
          "prehrate": "#d97158", "po_vrcholu": "#a8432f"}


REPORT_HEAD = """<!doctype html><meta charset="utf-8"><title>Altseason cyklus — backtest</title>
<style>body{background:#131110;color:#f3eee5;font:14px 'IBM Plex Sans',system-ui;max-width:1040px;margin:24px auto;padding:0 16px}
td,th{padding:4px 10px;border-bottom:1px solid #2c2723;text-align:left}h1,h2,h3{font-weight:600}.v{font-size:22px;font-weight:700}
.note{color:#c9bfb2;border-left:3px solid #b98a34;padding:4px 12px}svg{max-width:100%;height:auto}</style>
<h1>Altseason cyklus — pre-registrovaný backtest</h1>
"""


def report_html(summary, weeks, s, chosen, all_res, v2=None, v3=None, s3=None):
    """v3 first (the page runs it), then v2 (PASS by construction), then v1 as it
    was locked and failed."""
    return REPORT_HEAD + (report_v2_html(summary, weeks, s3, v3, "v3", PREREG_V3) if v3 else "") + \
        (report_v2_html(summary, weeks, s, v2) if v2 else "") + \
        "<h2>v1 — zamčená 2026-09-26, beze změny</h2>" + report_v1_html(summary, weeks, s, chosen, all_res)


def _yn(b):
    return "ano" if b else "NE"


def report_v2_html(summary, weeks, s, v2, ver="v2", prereg=None):
    """One registered version (v2 or v3): the index, the criteria, both lines."""
    prereg = prereg or PREREG_V2
    S2 = summary[ver]
    res = v2["_res"]
    I = res["index"]
    evi = {k: v for k, v in summary["events_idx"].items() if v is not None}
    first = next((i for i, t in enumerate(weeks) if t >= cycle.DISPLAY_FROM), 0)
    W = weeks[first:]
    cut = lambda a: a[first:]
    marks = [(i - first, I[i], "#d97158", "%s %s" % (k, r1(I[i]))) for k, i in evi.items()
             if k in ("P0", "P1", "P2") and i >= first and I[i] is not None]
    idx_svg = svg_line(W, [(cut(res["rotation"]), "#5c82c4"), (cut(res["euphoria"]), "#b98a34"), (cut(I), "#f3eee5")],
                       bands=[(v2["T"], 100, "#d97158")], marks=marks, ymin=0, ymax=100, h=360)

    def line_svg(vals, mode, col):
        n = len(vals)
        L = cycle.trend_line(vals, mode, n - 1)
        a0 = first
        lines, mk = [], []
        if L["anchor"] is not None:
            v0 = vals[L["anchor"]]
            lines.append((L["anchor"] - a0, v0, n - 1 - a0, L["line_t"], col))
            mk.append((L["touch"] - a0, vals[L["touch"]], "#8fb0e6", "dotek %s" % cycle.iso(weeks[L["touch"]])))
            if L["break_first"] is not None:
                mk.append((L["break_first"] - a0, vals[L["break_first"]], "#3fa37e",
                           "průlom %s" % cycle.iso(weeks[L["break_first"]])))
        svg = svg_line(weeks[a0:], [(vals[a0:], "#8fb0e6")], y_fmt=lambda v: "%.1f %%" % v, lines=lines, marks=mk, h=360)
        txt = ("kotva %s (%.2f %%), dotek %s, dno %s — %s; linie dnes %.2f %%, poslední týden %.2f %%"
               % (cycle.iso(weeks[L["anchor"]]), vals[L["anchor"]], cycle.iso(weeks[L["touch"]]), cycle.iso(weeks[L["opp"]]),
                  L["status"], L["line_t"], vals[n - 1] or 0)) if L["anchor"] is not None else L["status"]
        return svg, txt
    od_svg, od_txt = line_svg(s["othersd"], "down", "#d97158")
    bd_svg, bd_txt = line_svg(s["btcd"], "up", "#3fa37e")
    crit = [
        ("„Blíží se konec“ v [P − 8, P + 2] týdnů u P0 / P1 / P2",
         "%s / %s / %s" % (_yn(S2["hit_P0"]), _yn(S2["hit_P1"]), _yn(S2["hit_P2"]))),
        ("maximum cyklu 1 u P0 nebo P1 · cyklu 2 u P2",
         "%s (%s) · %s (%s)" % (_yn(S2["max_ok_c1"]), S2["max_c1"] and cycle.iso(S2["max_c1"]),
                                _yn(S2["max_ok_c2"]), S2["max_c2"] and cycle.iso(S2["max_c2"]))),
        ("týdnů s indexem ≥ T (nejvýš 10 %)", "%d z %d (%.1f %%)" % (S2["weeks_ge_T"], S2["weeks_evaluated"], S2["share_ge_T"])),
        ("epizody „Blíží se konec“ mimo vrcholy (nejvýš 2)",
         "%d %s" % (len(S2["episodes_false"]), ", ".join("%s–%s" % (cycle.iso(a), cycle.iso(b)) for a, b in S2["episodes_false"]))),
    ]
    if "quiet_2023_2026" in S2:
        crit.append(("2023-01 až 2026-06 bez „Blíží se konec“ a bez indexu ≥ T (BTC na maximech, altseason žádná)",
                     "%s %s" % (_yn(S2["quiet_2023_2026"]), ", ".join(cycle.iso(w) for w in S2["loud_weeks_2023_2026"][:8]))))
        crit.append(("epizody „Po vrcholu“ (jen pro informaci)",
                     ", ".join("%s–%s" % (cycle.iso(a), cycle.iso(b)) for a, b in S2["po_vrcholu_episodes"]) or "—"))
    fwd = []
    for p in ("prehrate", "po_vrcholu"):
        for e in (S2["forward_by_phase"].get(p) or []):
            fwd.append("<tr><td style='color:%s'>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
                PH_COL.get(p, "#ccc"), p, cycle.iso(e["start"]), e.get("usd13"), e.get("vbtc13"), e.get("usd26")))
    lead = " · ".join("%s %s" % (k, "—" if v is None else "%d t" % v) for k, v in S2["lead_weeks"].items())
    m23 = S2["max_since_2023"]
    note = ("v3 byla zaregistrována 2026-09-28 dřív, než se jediné její číslo spočítalo na skutečné historii "
            "(ladila se jen na syntetických řadách). Autoři ale obě minulé altseasony znali, takže historická kritéria "
            "jsou kontrola konzistence; test je dopředný: <code>cycle_ledger.jsonl</code>." if ver == "v3" else
            "v2 byla navržena až po selhání v1, s oběma altseasony před očima, a plánovací běh 2026-09-27 spočítal "
            "tyto vzorce na skutečné historii ještě před registrací. Projde tedy z konstrukce: je to kontrola "
            "konzistence, ne test. Test je dopředný: <code>cycle_ledger.jsonl</code>, řádek za každý uzavřený týden.")
    tpl = """<h2>""" + ver + """ — %s (zaregistrováno %s)</h2>
<p class="v">Verdikt """ + ver + """: %s · T = %s</p>
<p>PREREG sha256 %s… · zamčeno %s · %s</p>
<p class="note">""" + note + """</p>
<h3>Index 2016 → dnes</h3><p>bílá = index, modrá = rotace do altů, zlatá = euforie (retail + BTC cyklus);
pruh = T (konec altseasonu); body = P0, P1, P2</p>%s
<table><tr><th>kritérium</th><th>výsledek</th></tr>%s</table>
<p>Náskok varování (od prvního týdne „Blíží se konec“ k vrcholu): %s</p>
<p>Maximum od 2023: %s · roční maxima: %s</p>
<h3>OTHERS.D — linie od vrcholu (týden vidí jen data do sebe)</h3>%s<p>%s</p>
<h3>BTC.D — support ode dna</h3>%s<p>%s</p>
<h3>Co alty udělaly po „Blíží se konec“ a „Po vrcholu“ (13 t v USD · 13 t proti BTC · 26 t v USD)</h3><table>%s</table>
"""
    return tpl % (S2["prereg_id"], prereg["registered"], S2["verdict"], v2["T"], S2["prereg_sha256"][:12], S2["locked_utc"],
       "PREREG beze změny" if S2["prereg_ok"] else "PREREG ZMĚNĚN", idx_svg,
       "".join("<tr><td>%s</td><td>%s</td></tr>" % r for r in crit), lead,
       ("%s (%s)" % (m23["index"], cycle.iso(m23["week"]))) if m23 else "—",
       ", ".join("%s: %s" % kv for kv in S2["yearly_max"].items()), od_svg, od_txt, bd_svg, bd_txt, "".join(fwd))


def report_v1_html(summary, weeks, s, chosen, all_res):
    res = chosen["_res"]
    I = res["index"]
    ev = summary["events"]
    evi = {k: v for k, v in summary["events_idx"].items() if v is not None}
    shade = [(max(0, i - 8), min(len(weeks) - 1, i + 2), "#d97158") for k, i in evi.items() if k in ("P1", "P2")]
    shade += [(i, i, "#b98a34") for k, i in evi.items() if k in ("P0", "P2b")]
    first = next((i for i, t in enumerate(weeks) if t >= cycle.DISPLAY_FROM), 0)
    W = weeks[first:]
    cut = lambda a: a[first:]
    sh = [(a - first, b - first, c) for a, b, c in shade if b >= first]
    idx_svg = svg_line(W, [(cut(res["rotation"]), "#5c82c4"), (cut(res["heat"]), "#b98a34"), (cut(I), "#f3eee5")],
                       bands=[(chosen["T"], 100, "#d97158")], shade=sh, ymin=0, ymax=100)
    od = s["othersd"]
    n = len(weeks)
    lines = cycle.trend_break(od, "down")
    picked = cycle.pick_lines(lines, n)
    a0 = max(0, min([L["anchor"] for L in picked] or [n - 156]) - 26)
    W2 = weeks[a0:]
    ln = []
    mk = []
    for L in picked:
        i1 = n - 1
        v0 = od[L["anchor"]]
        v1 = v0 + L["slope"] * (i1 - L["anchor"])
        ln.append((L["anchor"] - a0, v0, i1 - a0, v1, "#d97158"))
        mk.append((L["touch"] - a0, od[L["touch"]], "#8fb0e6", "dotek"))
        if L["breakout"] is not None:
            mk.append((L["breakout"] - a0, od[L["breakout"]], "#3fa37e", "průlom %s" % cycle.iso(weeks[L["breakout"]])))
    od_svg = svg_line(W2, [(od[a0:], "#8fb0e6")], y_fmt=lambda v: "%.1f %%" % v, lines=ln, marks=mk)
    bd_svg = svg_line(W, [(cut(s["btcd"]), "#b98a34")], y_fmt=lambda v: "%.0f %%" % v)
    rows = []
    for k, v in summary["variants"].items():
        rows.append("<tr><td>%s</td><td>%s</td><td>%.0f</td><td>%s</td><td>%s</td><td>%s/%s</td><td>%.1f %%</td><td>%d</td></tr>" % (
            k, "PASS" if v["pass"] else "fail", v["T"], v["hit_P1"], v["hit_P2"], v["max_ok_c1"], v["max_ok_c2"],
            v["share_ge_T"], len(v["episodes_false"])))
    fwd = []
    for p, eps in summary["forward_by_phase"].items():
        for e in eps[-6:]:
            fwd.append("<tr><td style='color:%s'>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
                PH_COL.get(p, "#ccc"), p, cycle.iso(e["start"]), e.get("usd13"), e.get("vbtc13"), e.get("usd26")))
    evrows = "".join("<tr><td>%s</td><td>%s</td><td>%s</td></tr>" % (
        k, cycle.iso(v) if v else "—", r1(I[summary["events_idx"][k]]) if summary["events_idx"].get(k) is not None else "—")
        for k, v in ev.items())
    lines_txt = "".join("<li>kotva %s (%.2f %%), dotek %s, %s%s — linie dnes %.2f %%, poslední týden %+.1f %%</li>" % (
        cycle.iso(weeks[L["anchor"]]), od[L["anchor"]], cycle.iso(weeks[L["touch"]]),
        L["status"], (" " + cycle.iso(weeks[L["breakout"]])) if L["breakout"] is not None else "",
        L["line_now"], L["dist_pct"] or 0) for L in picked)
    return """<p class="v">Verdikt v1: %s · vybraná varianta %s (T = %.0f)</p>
<p>PREREG %s · sha256 %s… · zamčeno %s · %s</p>
<h3>Index v1 2016 → dnes</h3><p>bílá = index, modrá = rotace do altů, zlatá = BTC cyklus; červeně okna vrcholů 2018 a 2021, zlatě P0/P2b; pruh = práh T</p>%s
<table><tr><th>událost</th><th>týden</th><th>index</th></tr>%s</table>
<h3>Varianty</h3><table><tr><th>varianta</th><th>výsledek</th><th>T</th><th>P1</th><th>P2</th><th>max cyklů</th><th>týdnů ≥ T</th><th>falešné epizody</th></tr>%s</table>
<p>Falešné epizody vybrané varianty: %s · zachycené lokální vrcholy: %s</p>
<h3>OTHERS.D — linie v1 (trend_break)</h3>%s<ul>%s</ul><p>poslední den: %s</p>
<h3>BTC dominance</h3>%s
<h3>Co alty udělaly po začátku fáze v1 (13 t v USD · 13 t proti BTC · 26 t v USD)</h3><table>%s</table>
<h3>Citlivost na okno percentilu</h3><pre>%s</pre>
""" % (summary["verdict"], summary["chosen"], chosen["T"], summary["prereg_id"], summary["prereg_sha256"][:12],
       summary["locked_utc"], "PREREG beze změny" if summary["prereg_ok"] else "PREREG ZMĚNĚN",
       idx_svg, evrows, "".join(rows), summary["variants"][summary["chosen"]]["episodes_false"],
       summary["variants"][summary["chosen"]]["episodes_caught"], od_svg, lines_txt,
       json.dumps(summary.get("latest")), bd_svg, "".join(fwd), json.dumps(summary["sensitivity"], indent=1))


# ================================================================== main
def main():
    lk, same = prereg_lock()          # FIRST: before any index value exists
    if not same:
        print("PREREG se změnil proti zámku %s — v1 je zamčená, změna potřebuje nové id" % LOCK)
        return 2
    lk2, same2 = prereg_lock(PREREG_V2, LOCK_V2)
    if not same2:
        print("PREREG_V2 se změnil proti zámku %s — v2 je zamčená, změna potřebuje nové id" % LOCK_V2)
        return 2
    drift = sorted(k for k in PREREG_V2["rules"] if cycle.V2_RULES.get(k) != PREREG_V2["rules"][k])
    if drift:
        print("cycle.V2_RULES se liší od PREREG_V2 (%s) — kód už nepočítá zaregistrovanou v2" % ", ".join(drift))
        return 2
    lk3, same3 = prereg_lock(PREREG_V3, LOCK_V3)
    if not same3 or lk3.get("sha256") != V3_SHA256:
        print("PREREG_V3 se změnil proti zámku %s — v3 je zamčená, změna potřebuje nové id" % LOCK_V3)
        return 2
    drift = sorted(k for k in PREREG_V3["rules"] if cycle.V3_RULES.get(k) != PREREG_V3["rules"][k])
    if drift:
        print("cycle.V3_RULES se liší od PREREG_V3 (%s) — kód už nepočítá zaregistrovanou v3" % ", ".join(drift))
        return 2
    H, _ = cycle.load_history(os.getcwd())
    if not H:
        print("cycle_history.json chybí — nejdřív python tools/cycle_seed.py")
        return 2
    # v2's retail starts with Coinbase (2015-07): without it the evaluation would begin
    # at Upbit's first scored week (2018-10), after P0 and P1, and v2 would fail on a gap
    first_cb = min((int(k) for k in ((H.get("cbx") or {}).get("BTC-USD") or {})), default=None)
    if first_cb is None or first_cb > cycle.COINBASE_PAIRS[0][1] + 30 * cycle.DAY:
        print("historie nemá denní data Coinbase od 2015-07 — nejdřív python tools/cycle_seed.py coinbase")
        return 2
    import time
    now = int(time.time())
    weeks = cycle.week_axis(now)
    s = cycle.series_from_history(H, weeks)
    s["breakouts"] = cycle.v1_breakouts(s["othersd"])
    evi = cycle.find_events(weeks, s)
    base = dict(cycle.V1_RULES)
    probe = cycle.compute_index(weeks, s, base)
    I = probe["index"]
    eval_i = next((i for i, v in enumerate(I) if v is not None), None)
    eval_start = weeks[eval_i] if eval_i is not None else weeks[-1]
    p1 = evi.get("P1")
    p1max = max((I[i] for i in range(max(0, p1 - 8), min(len(weeks), p1 + 3)) if I[i] is not None),
                default=None) if p1 is not None else None
    cyc = [(eval_start, int(datetime.datetime(2019, 12, 31, tzinfo=datetime.timezone.utc).timestamp())),
           (int(datetime.datetime(2020, 1, 1, tzinfo=datetime.timezone.utc).timestamp()),
            int(datetime.datetime(2022, 12, 31, tzinfo=datetime.timezone.utc).timestamp()))]
    variants = {}
    for v in PREREG["variants"]:
        T = min(90.0, max(80.0, round(v["t_factor"] * p1max))) if p1max is not None else 85.0
        rules = dict(base, breadth_gate=v["breadth_gate"], t_factor=v["t_factor"], T=T)
        name = "%s/%s" % (v["breadth_gate"], v["t_factor"])
        variants[name] = evaluate(weeks, s, evi, rules, eval_start, cyc)
        variants[name]["rules"] = rules
    passing = [k for k, v in variants.items() if v["pass"]]
    order = lambda k: (len(variants[k]["episodes_false"]), variants[k]["weeks_ge_T"], k != "mean4/0.9")
    chosen = min(passing, key=order) if passing else "mean4/0.9"
    ch = variants[chosen]
    sens = {}
    for win in (104, 156, 260):
        r = cycle.compute_index(weeks, s, dict(ch["rules"], window=win, min_window=min(104, win)))
        sens[str(win)] = {k: r1(r["index"][i]) for k, i in evi.items() if i is not None}
    summary = {
        "prereg_id": PREREG["id"], "prereg_sha256": lk["sha256"], "locked_utc": lk["locked_utc"],
        "prereg_ok": same, "cycle_py_sha256": file_sha("cycle.py"),
        "generated_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "verdict": "PASS" if passing else "FAIL", "chosen": chosen,
        "rules": {k: ch["rules"][k] for k in ("breadth_gate", "t_factor", "T")},
        "events": {k: (weeks[i] if i is not None else None) for k, i in evi.items()},
        "events_idx": evi, "eval_start": eval_start, "p1_max": r1(p1max),
        "index_at": {k: r1(I[i]) for k, i in evi.items() if i is not None},
        "variants": {k: {kk: vv for kk, vv in v.items() if kk not in ("_res", "rules")} for k, v in variants.items()},
        "forward_by_phase": forward_by_phase(weeks, s, ch["_res"]["phase"]),
        "sensitivity": sens,
        "latest": {"week": weeks[-1], "index": r1(ch["_res"]["index"][-1]), "phase": ch["_res"]["phase"][-1]},
    }
    for k in ("max_c1", "max_c2"):
        for v in summary["variants"].values():
            v[k] = weeks[v[k]] if isinstance(v[k], int) else None
    # v2 on the same weekly series and events; the collector reads summary["v2"]
    rows, _ = cycle.retail_rows(H, weeks)
    v2 = evaluate_v2(weeks, s, rows, evi)
    r2 = v2["_res"]
    S2 = {"prereg_id": PREREG_V2["id"], "prereg_sha256": lk2["sha256"], "locked_utc": lk2["locked_utc"],
          "prereg_ok": same2, "verdict": "PASS" if v2["pass"] else "FAIL", "rules": {"T": v2["T"]},
          "note": PREREG_V2["honesty"]}
    S2.update({k: v for k, v in v2.items() if k not in ("_res", "T", "pass")})
    for k in ("max_c1", "max_c2"):
        S2[k] = weeks[S2[k]] if isinstance(S2[k], int) else None
    S2["index_at"] = {k: r1(r2["index"][i]) for k, i in evi.items() if i is not None}
    S2["forward_by_phase"] = forward_by_phase(weeks, s, r2["phase"])
    S2["latest"] = {"week": weeks[-1], "index": r1(r2["index"][-1]), "phase": r2["phase"][-1]}
    summary["v2"] = S2
    # v3, the one the page runs: its own series (heat read on the newest of 7 days),
    # the same events
    s3 = cycle.series_from_history(H, weeks, cycle.V3_RULES)
    rows3, _ = cycle.retail_rows(H, weeks, cycle.V3_RULES)
    v3 = evaluate_v3(weeks, s3, rows3, evi)
    r3 = v3["_res"]
    S3 = {"prereg_id": PREREG_V3["id"], "prereg_sha256": lk3["sha256"], "locked_utc": lk3["locked_utc"],
          "prereg_ok": same3, "verdict": "PASS" if v3["pass"] else "FAIL", "rules": {"T": v3["T"]},
          "note": PREREG_V3["honesty"]}
    S3.update({k: v for k, v in v3.items() if k not in ("_res", "T", "pass")})
    for k in ("max_c1", "max_c2"):
        S3[k] = weeks[S3[k]] if isinstance(S3[k], int) else None
    S3["index_at"] = {k: r1(r3["index"][i]) for k, i in evi.items() if i is not None}
    S3["forward_by_phase"] = forward_by_phase(weeks, s3, r3["phase"])
    S3["latest"] = {"week": weeks[-1], "index": r1(r3["index"][-1]), "phase": r3["phase"][-1]}
    summary["v3"] = S3
    with io.open("cycle_backtest_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1, allow_nan=False)
    with io.open("cycle_backtest_report.html", "w", encoding="utf-8") as f:
        f.write(report_html(summary, weeks, s, ch, variants, v2, v3, s3))
    print("v1: verdikt %s · varianta %s · T %.0f · index P1 %s P2 %s · dnes %s (%s)" % (
        summary["verdict"], chosen, ch["T"], summary["index_at"].get("P1"), summary["index_at"].get("P2"),
        summary["latest"]["index"], summary["latest"]["phase"]))
    print("v2: verdikt %s · T %s · index P0 %s P1 %s P2 %s · týdnů ≥ T %.1f %% · náskok %s · max od 2023 %s · dnes %s (%s)" % (
        S2["verdict"], v2["T"], S2["index_at"].get("P0"), S2["index_at"].get("P1"), S2["index_at"].get("P2"),
        S2["share_ge_T"], S2["lead_weeks"], (S2["max_since_2023"] or {}).get("index"), S2["latest"]["index"],
        S2["latest"]["phase"]))
    print("v3: verdikt %s · T %s · index P0 %s P1 %s P2 %s P2b %s · týdnů ≥ T %.1f %% · 2023–26 klid %s · náskok %s · "
          "max od 2023 %s · dnes %s (%s)" % (
              S3["verdict"], v3["T"], S3["index_at"].get("P0"), S3["index_at"].get("P1"), S3["index_at"].get("P2"),
              S3["index_at"].get("P2b"), S3["share_ge_T"], _yn(S3["quiet_2023_2026"]), S3["lead_weeks"],
              (S3["max_since_2023"] or {}).get("index"), S3["latest"]["index"], S3["latest"]["phase"]))
    return 0


if __name__ == "__main__":
    sys.exit(selftest() if "--selftest" in sys.argv else main())
