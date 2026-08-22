# Plan: CLR (Career Legend Rating), a Holistic LPS inspired by PPS / JAWS

**Name locked: Career Legend Rating (CLR).** Career (whole-career), Legend (LoL's identity +
Riot's "Hall of Legends"), Rating (a quantitative composite). Three-word / three-letter, PPS
cadence, no collision with LPS or any LoL league acronym.

Status: **Phase 0 implemented** (see below). Owner decisions locked so far:
- The holistic composite (**CLR**) is the **new primary ranking**; `CareerLPS` is demoted to a
  component column (kept, not deleted). The career workbook now sorts by CLR.
- Remaining phases (High Noon, résumé bonuses, tiers, calibration) are sequenced below.

### Locked parameters
- **Peak term** = a player's best-season peak. **Open sub-decision (see §6):** whether this is the
  **single max season**, the **mean of top-3** seasons, or a **blend** of both. Leaning toward
  including the single max (possibly the primary peak signal), because many great LoL careers were
  short with one very sharp peak (Marin the canonical example) — top-3 averaging dilutes exactly
  that profile. Whatever is chosen feeds `CLR`.
- **High Noon** (rolling-3-yr positional peer rank) = **companion column, NOT summed** into the
  score (avoids double-counting peak). May be promoted to a small dominance bonus later if
  results warrant.
- **Career divisor D = 7.5** (avg career length of retired top-100-by-CareerLPS players). Long
  careers (e.g. Faker, ~2×) intentionally earn a proportionally larger career term; Pace and
  Peak are length-neutral counterweights so bulk alone can't win.
- **Top-N peak = 3** (LoL careers, and peaks, are short) — *provisional*; see the peak
  sub-decision above about also/instead using the single max season.
- **Eras (three):** Era 1 = start–2014 · Era 2 = 2015–2017 (League graphics overhaul) ·
  Era 3 = 2018–present (Runes Reforged = "modern" LoL). NB: Era 1 is almost entirely
  reduced-model / Leaguepedia data (Oracle box scores start 2014, East is LP-filled through 2015).
- **No hard caps on bonuses initially.** Revisit only if results look off.
- **Calibration ground truth:** owner's hand-made per-lane consensus "greatest of all time" list.
  Fit `w_career / w_pace / w_peak` (and later bonus scales) to best reproduce its ordering.

---

## 1. Motivation

Today's LPS ranks *career* value well and exposes *peak* as a separate column, but there is
**no single number** that blends longevity, peak dominance, efficiency, and résumé (titles,
international finishes, awards). We want a holistic metric in the spirit of hockey's
**Pidutti Point Share (PPS)** and baseball's **JAWS**.

## 2. What PPS is (the template)

PPS (Paul Pidutti, adjustedhockey.com) is a *Hall-of-Fame worthiness* score that collapses a
whole career into one era- and position-normalized number, then compares it to a positional
standard.

```
PPS = Career + Pace + Peak  +  (Playoff/Cup bonus + International bonus + Award shares)
```

- **Career Value** — career era-adjusted Point Shares ÷ 15 (divisor = HOF-length midpoint;
  20 undervalued long careers, 10 overvalued them).
- **Pace Value** — production per unit time; rewards rate so brilliant short careers aren't buried.
- **Peak Value** — best years / dominance; paired with **"High Noon"** = rolling 3-year
  positional rank ("where did they stand among peers each season").
- **Playoff/Cup bonus** — era-calibrated, capped (max 40 pts eras 1–2, 30 pts eras 3–5).
- **International bonus** — play on the biggest stage.
- **Award shares** — systematically derived from voting; deliberately small, a *tiebreaker*.

Everything is era-classified (5 eras ≈ 25 seasons) and league-strength adjusted, then scored
against a positional HOF standard (e.g. modern forward = 235 PPS) with tiers
(inner-circle / qualified / borderline / Hall of Very Good / not a candidate).

### Lineage
- **Bill James — Win Shares**: attribute team wins to individuals (≈ our Model 2 → contribution).
- **Bill James — Hall of Fame Monitor**: score a résumé against a "typical HOFer" standard.
- **Jay Jaffe — JAWS**: combine **career** + **peak** into one number — the exact move we're missing.
- **Hockey-Reference — Point Shares / adjusted stats**: era-neutralized common currency
  (≈ our schedule + cross-year quantile normalization).

## 3. Mapping PPS → LPS (what exists vs. what's missing)

| PPS factor | LPS today | Status |
|---|---|---|
| Career Value | `CareerLPS` (schedule-normalized yearly LPS, era-adj via Elo baseline) | ✅ Have |
| Pace Value | `LPS/Yr`, `LPS/Gm`, `LPS/Gm·wt` | ⚠️ Pieces, not integrated |
| Peak Value | `PeakLPS` / `PeakYr` (single best season, isolated column) | ⚠️ Have, no top-N, no peer-rank |
| Playoff/Cup bonus | `Playoffs`/`Tourneys` phase pts, `Clutch`, per-tournament cols | ⚠️ No title/championship bonus |
| International bonus | Elo baseline + viewership tournament weighting | ⚠️ Implicit only |
| Award shares | — | ❌ Missing |
| High Noon (peer rank) | — | ❌ Missing |
| Standard / tiers | — | ❌ Missing |

**Data reality:** Career/Pace/Peak come from Oracle (already in-pipeline). **Titles, MVP/All-Pro
awards, and international finishes are NOT in Oracle** — they live in Leaguepedia, which we can
reach via `lp_client.py` (see `fetch_international_matches.py` for the pattern). Bonuses are a
scrape + hand-curation task, exactly like PPS treats awards as a small verifiable layer.

## 4. Proposed metric

One composite per player, the new primary ranking:

```
CLR = w_career · CareerValue
    + w_pace   · PaceValue
    + w_peak   · PeakValue
    + TitleBonus + IntlBonus + AwardShare      # capped, era/region-calibrated (Phase 2+)
```

All weights + caps live in the `CLRConfig` @dataclass (per repo convention). `CareerLPS`
stays as a component column; the workbook's default sort switches to `CLR`. Phase 0 ships the
first three terms; the bonus terms are added in Phase 2.

- **CareerValue** = `CareerLPS / 7.5`.
- **PaceValue** = length-robust rate (`LPS/Gm·wt`) shrunk toward the mean via an empirical-Bayes
  prior on games, so small samples don't top the board.
- **PeakValue** = "plateau" peak (see §5 for the exact formula): the mean of a player's **peak
  years** (seasons within `peak_band` of their best) plus a length bonus per extra peak year. A
  one-year great (Marin) scores his single best season exactly; a wide plateau (Faker) scores its
  plateau average plus a length reward — and a longer peak is never penalized.
- **High Noon** = peer rank among that season's players (global + per-lane); HN3 = average over a
  player's 3 best-ranked seasons (non-consecutive) — **companion columns**, not summed in.

## 5. Implementation phases (sequenced for later)

**Phase 0 — Composite (Oracle/LP-only, no new data). ✅ DONE.**
Implemented in `career.py`: `CLRConfig` @dataclass (`career_divisor=7.5`, `peak_band=0.15`,
`peak_len_bonus=0.10`, `pace_prior_games=50`, `w_*=1.0`), `_add_clr()` adds `clr` + component
columns (`career_value`, `pace_value`, `peak_value`, `peak_years`, `peak_band_avg`); Overview +
lane sheets sort by CLR; methodology documented on the `About` sheet and glossary. All three
components sit on a ~one-season scale so the weights are unit-free.
- **CareerValue** = `CareerLPS / 7.5`.
- **PaceValue** = per-active-year LPS, empirical-Bayes shrunk toward the cohort mean by weighted
  games (prior strength `pace_prior_games`).
- **PeakValue** = `mean(peak years) + peak_len_bonus · best · (PeakYrs − 1)`, where a **peak
  year** is a season `≥ (1 − peak_band) · best`. Mean-of-plateau captures peak *height*; the
  length bonus rewards peak *width*. **Never-penalized guarantee:** adding a qualifying peak year
  changes PeakVal by `≥ best·(peak_len_bonus − peak_band/2)`, so as long as
  `peak_len_bonus ≥ peak_band/2` (0.10 ≥ 0.075 by default) a longer peak can never lower the
  score. `peak_years` (plateau width) and `peak_band_avg` (plateau height) are exposed as columns.
  *Known trade-off:* the hard `(1−band)` cutoff is a knife-edge (a season at 84.9% vs 85.1% of the
  peak flips in/out) — a soft, distance-weighted band is the fallback if that proves too brittle.
- **First-run sanity (defaults, uncalibrated):** top of board is a clean consensus ordering
  (Faker ≫ Canyon, Ruler, Knight, Keria, ShowMaker, Chovy …). Peak correctly isolates sharp
  peaks (Marin PeakVal ≈ 34.7, elite despite a 5-yr career). Known distortions are all
  weight/prior artifacts for **calibration** to fix: short high-volume careers (e.g. 3-yr Peyz)
  and one-split wonders (e.g. Wh1t3zZ, 1 yr) rank higher than longevity warrants at `w_*`=1.
  These motivate raising `w_career` and/or the pace prior, and are the reason Phase 0 ships with
  *provisional* weights pending the calibration step.

**Phase 1 — "High Noon" peer-rank trajectory. ✅ DONE.**
`_high_noon()` in `career.py`: each season, rank rated players by that year's schedule-normalized
LPS (1 = best), both **globally** (all lanes) and **within lane**. Per player it stores the best
single-season rank (`BestRkLane`/`BestRkGlob`) and **HN3** = the average rank over their 3
best-ranked seasons (`HN3Lane`/`HN3Glob`), with the constituent years listed (`HN3LaneYrs`/
`HN3GlobYrs`). Best seasons are taken **wherever they fall, not a consecutive window** — matching
how PeakVal uses a player's best seasons, so a gap year never breaks the metric. Companion columns
only (NOT summed into CLR — peak already lives in the score); lower is better.

**Phase 2 — Résumé bonuses (Leaguepedia curation).**
Era/region-calibrated, PPS-style capped:
- **TitleBonus** — domestic split titles + international (Worlds/MSI) finishes, weighted by event
  tier and region Elo (reuse `regional_elo.py`).
- **AwardShare** — regional MVP / All-Pro / Finals MVP as shares; small, tiebreaker-only.
- Scrape via `lp_client.py` → curated CSVs in `info/` (e.g. `player_awards.csv`,
  `titles_<year>.csv`), hand-filled where Cargo is incomplete (same workflow as
  `team_regions_<year>.csv`).

**Phase 3 — Standard & tiers.**
Per-position `CLR` threshold from the top historical cohort; label tiers
(inner-circle / qualified / borderline / …) so the number has meaning, like PPS's 235.

**Cross-cutting — Calibration.**
Set `w_*` and bonus caps by fitting to a small hand-ranked "ground truth" list of consensus
all-time players (how PPS/JAWS were tuned), via a dedicated calibration script — not by guessing.

## 6. Open questions / spikes
- **2011–2012 backfill (spike).** Data currently starts 2013 (`lp_ingest.GAP_SPECS`) because that
  is the earliest year with usable reduced-model (KDA+CS) Leaguepedia data; Oracle starts 2014.
  Extending to 2011–12 is possible but risky: no standard regional leagues yet (OGN 2012;
  LPL/EU/NA LCS 2013 → no clean region→Elo map, no regular/playoff split), sparse
  `ScoreboardPlayers` coverage, and tiny noisy samples for the Era-1 quantile reference. Action:
  1-hr spike querying `ScoreboardPlayers` for 2011/2012 to measure row counts + KDA/CS null
  rates; extend `GAP_SPECS` only if coverage is adequate (Worlds S1/S2 + OGN 2012).
- Bonuses are uncapped to start (locked); revisit only if title/award terms distort results.
- Whether to later promote **High Noon** from companion column to a small dominance bonus.
- **Peak "plateau" params (`peak_band`, `peak_len_bonus`).** Resolved for Phase 0 to the plateau
  form (mean of peak years + length bonus). Still to resolve empirically against the consensus
  list: the band width (default 15%), the length bonus (default 0.10, floored at `band/2`), and
  whether the hard cutoff should become a soft distance-weighted band to kill the knife-edge.
- **`w_peak` (term balance).** PeakVal's base is ~one elite season, so it's structurally larger
  than CareerVal/PaceVal; `w_peak` (currently 1.0) is the lever to rebalance the three terms and
  is a prime calibration target.

## 7. Sources
- Adjusted Hockey — HHOF Methodology / Career / Pace / Peak / Inspiration pages (adjustedhockey.com)
- Daily Faceoff — "A whole new way to determine Hall of Fame worthiness"
- Wikipedia — Win Shares; SABR — Bill James Hall of Fame Monitor; JAWS (baseball) background
