# Plan: A Holistic LPS ("Résumé Score"), inspired by PPS / JAWS

Status: **draft plan** (no code yet). Owner decisions locked so far:
- The holistic composite becomes the **new primary ranking**; `CareerLPS` is demoted to a
  component column (kept, not deleted).
- First build target: **plan only**; implementation phases below are sequenced for later.

### Locked parameters
- **Peak term** = a player's best-season peak. **Open sub-decision (see §6):** whether this is the
  **single max season**, the **mean of top-3** seasons, or a **blend** of both. Leaning toward
  including the single max (possibly the primary peak signal), because many great LoL careers were
  short with one very sharp peak (Marin the canonical example) — top-3 averaging dilutes exactly
  that profile. Whatever is chosen feeds `ResumeScore`.
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
ResumeScore = w_career · CareerValue
            + w_pace   · PaceValue
            + w_peak   · PeakValue
            + TitleBonus + IntlBonus + AwardShare      # capped, era/region-calibrated
```

All weights + caps live in a new `ResumeConfig` @dataclass (per repo convention). `CareerLPS`
stays as a component column; the workbook's default sort switches to `ResumeScore`.

- **CareerValue** = `CareerLPS / 7.5`.
- **PaceValue** = length-robust rate (`LPS/Gm·wt`) shrunk toward the mean via an empirical-Bayes
  prior on games, so small samples don't top the board.
- **PeakValue** = best-season peak. Candidate forms (decide by calibration, §6):
  - **single max** — the one best schedule-normalized season (rewards short, sharp peaks like Marin);
  - **top-3 mean** — JAWS-style, rewards sustained excellence over dilution of one-year spikes;
  - **blend** — e.g. `max(single, top-3 mean)` or a weighted combo, to reward both without
    letting a lone outlier season fully define a career.
- **High Noon** = rolling-3-yr best positional peer rank — **companion column**, not summed in.

## 5. Implementation phases (sequenced for later)

**Phase 0 — Composite (Oracle-only, no new data).**
Add CareerValue/PaceValue/PeakValue + `ResumeScore` columns in `career.py`/`export_excel.py`;
switch primary sort. Weights in `ResumeConfig`. Note methodology on the `About` sheet.

**Phase 1 — "High Noon" peer-rank trajectory (Oracle-only).**
For each (year, position) rank players by that season's normalized LPS; store best rolling-3-year
average rank. A groupby over data we already produce. Surfaces sustained #1-at-position dominance.

**Phase 2 — Résumé bonuses (Leaguepedia curation).**
Era/region-calibrated, PPS-style capped:
- **TitleBonus** — domestic split titles + international (Worlds/MSI) finishes, weighted by event
  tier and region Elo (reuse `regional_elo.py`).
- **AwardShare** — regional MVP / All-Pro / Finals MVP as shares; small, tiebreaker-only.
- Scrape via `lp_client.py` → curated CSVs in `info/` (e.g. `player_awards.csv`,
  `titles_<year>.csv`), hand-filled where Cargo is incomplete (same workflow as
  `team_regions_<year>.csv`).

**Phase 3 — Standard & tiers.**
Per-position `ResumeScore` threshold from the top historical cohort; label tiers
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
- **Peak form (single max vs top-3 vs blend).** Short LoL careers with one dominant season
  (e.g. Marin) argue for including the single max so sharp peaks aren't averaged away; sustained
  primes argue for top-3. Resolve empirically against the consensus list — try all three peak
  forms and keep whichever best reproduces the hand-ranked ordering (and consider exposing single
  max and top-3 as separate columns regardless of which feeds the score).

## 7. Sources
- Adjusted Hockey — HHOF Methodology / Career / Pace / Peak / Inspiration pages (adjustedhockey.com)
- Daily Faceoff — "A whole new way to determine Hall of Fame worthiness"
- Wikipedia — Win Shares; SABR — Bill James Hall of Fame Monitor; JAWS (baseball) background
