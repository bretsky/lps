"""
Multi-year runner + cumulative "greatest of all time" workbook.

Runs the full LPS pipeline for a range of years (retraining models per year so meta changes
are captured), writes one workbook per year, then aggregates every year into a single career
workbook: LPS and all breakdowns summed across years per (player, lane), with years active,
per-year LPS trajectory, and peak year -- ranked by career LPS.

Run:
    poetry run python -m lps.career                       # 2014-2025, all workbooks
    poetry run python -m lps.career --years 2018-2025
    poetry run python -m lps.career --no-recompute        # reuse cached per-year models
    poetry run python -m lps.career --no-yearly           # only the career workbook

Cross-year note: each year's point totals are schedule-normalized (scaled by REF/N_ref, where
REF is the cross-year mean matches per player) so a full season is worth the same across eras;
the SAME normalized numbers are written to each per-year workbook, so per-year LPS totals SUM
to CareerLPS. Summing gives a career/longevity metric (more seasons + higher peaks both help).
Recent years offer more international events, so modern players have marginally more to
accumulate -- an intended "more opportunity" effect.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from .achievements import (
    BonusConfig,
    score_bonuses,
    RESUME_BREAKDOWN_COLS,
    _RB_PTS,
)
from .config import PROJECT_ROOT
from .contribution import ROLES
from .export_excel import (
    _INT,
    _PCT,
    _PTS,
    _SIGNED,
    _GLOSSARY,
    _ACCUM_BASE_COLS,
    _write_glossary,
    _write_sheet,
    build_export_frame,
)
from .io_oracle import available_oracle_years, latest_oracle_year, load_oracle_years
from .scoring import REFERENCE_ELO, ScoreWeights, load_league_elos, apply_scored_terms
from .season import _DEMO_WEIGHTS, _LANE_NAMES, _SOURCES, build_player_match_scores
from .team_leagues import resolve_home_leagues

logger = logging.getLogger(__name__)

YEARS_DEFAULT = tuple(
    range(2011, latest_oracle_year() + 1)
)  # 2011-2013 via reduced Leaguepedia model; 2014+ Oracle (upper bound = newest CSV)
# (2011+2012 share one pooled KDA-only model; see lp_reduced.MODEL_GROUPS)


@dataclass
class CLRConfig:
    """Career Legend Rating -- the holistic PPS/JAWS-inspired composite (see
    docs/holistic-lps-plan.md).  Phase 0 is Oracle/LP-only and blends three length-decoupled
    views of a career onto a common ~one-season scale so the weights are unit-free and can be
    calibrated directly against the consensus all-time list:

        CLR = w_career * CareerValue + w_pace * PaceValue + w_peak * PeakValue

    Resume bonuses (titles / awards / international finishes -- Phase 2) are added on top later.
    Defaults are provisional placeholders pending calibration; only `career_divisor`,
    `peak_top_n`, and the three-era framing are locked (per the plan doc)."""

    career_divisor: float = (
        7.5  # D: avg career length (yrs) of retired top-100-by-CareerLPS
    )
    # PEAK = "plateau" definition. A season counts as a PEAK YEAR if it is within `peak_band` of
    # the player's best season (>= (1-peak_band)*best). PeakVal = mean(peak years) + a length
    # bonus for each EXTRA peak year:
    #     PeakVal = avg(peak years) + peak_len_bonus * best_season * (k - 1)
    # A one-year peak (Marin) scores exactly its single great season; a wide plateau (Faker)
    # scores its plateau average plus a length reward. The length bonus offsets the fact that
    # averaging in a slightly-lower peak year would otherwise drag the mean down -- so a longer
    # peak is NEVER penalized as long as peak_len_bonus >= peak_band/2 (the worst-case average
    # drop from adding a year at the band edge). Both default safely above that floor.
    peak_band: float = 0.15  # within 15% of the best season counts as a peak year
    peak_len_bonus: float = (
        0.10  # per extra peak year, as a fraction of the best season (tuned)
    )
    pace_prior_games: float = (
        50.0  # empirical-Bayes shrinkage strength (weighted games)
    )
    # Tuned against the consensus surveys: career bulk is up-weighted (1.6) and rate/pace stays
    # comparatively low (0.8), with peak the 1.0 reference.
    w_career: float = 1.6
    w_pace: float = 0.8
    w_peak: float = 1.0
    # ERA ADJUSTMENT (discrete 3-era, per docs/holistic-lps-plan.md). Modern seasons offer more to
    # accumulate (more events, stronger-Elo leagues, richer box-score data) than early ones, so a
    # dominant early season scores lower in raw LPS than an equally dominant modern one -- which
    # under-credits the old-era greats the consensus rates highly. Each season's point totals are
    # multiplied by its era's entry here: (Era1 = <=2014 reduced-model era, Era2 = 2015-2017
    # graphics overhaul, Era3 = 2018+ Runes Reforged / modern). Ranking is scale-invariant, so Era3
    # is the 1.0 reference and >1 on the older eras lifts them. Tuned to the (combined) consensus
    # surveys: (1.6, 1.35, 1.0) -- the reduced-model early era gets the biggest lift.
    era_mults: tuple[float, float, float] = (1.6, 1.35, 1.0)


# Columns that ACCUMULATE across years (summed).
_SUM_COLS = [
    "games",
    "wins",
    "reg_games",
    "playoff_games",
    "tourn_games",
    "n_tourneys",
    "total_score",
    "base_pts",
    "contrib_pts",
    "wbonus_pts",
    "kills_pts",
    "deaths_pts",
    "assists_pts",
    "damage_pts",
    "fb_pts",
    "reg_pts",
    "playoff_pts",
    "tourn_pts",
    "total_weight",
]
# Counts don't scale with schedule length; every other summed column (the point accumulations)
# is proportional to that year's N_ref, so it gets schedule-normalized -- see
# export_excel._ACCUM_BASE_COLS, which is the point-column list actually rescaled per year.
_COUNT_COLS = [
    "games",
    "wins",
    "reg_games",
    "playoff_games",
    "tourn_games",
    "n_tourneys",
]
# Columns averaged across years weighted by that year's games.
_GW_COLS = [
    "pts_per_game",
    "contrib_pg",
    "avg_contrib",
    "avg_resid",
    "avg_p_model",
    "sched_strength",
    "fb_rate",
    "region_elo",
]


def run_year_frames(
    years: tuple[int, ...],
    weights: ScoreWeights,
    min_games: int,
    intl_weight: float,
    force_recompute: bool,
) -> tuple[list[dict], list[str]]:
    """Build one enriched frame per year. Where both sources exist (Oracle 2014+ and the
    reduced Leaguepedia model for gap years 2013-2015) their per-match frames are MERGED and
    home leagues re-resolved across the union, so e.g. an Eastern team whose only Oracle games
    are Worlds (home would wrongly resolve to 'WLDs') picks up its real domestic home from
    Leaguepedia and its Worlds games are credited. Returns a list of
    {year, source, frame, tc, meta, n_ref} records + the union of per-tournament columns.
    Per-year workbooks are written by the caller AFTER schedule normalization is applied.
    """
    from . import lp_reduced

    records: list[dict] = []
    all_tourn: list[str] = []
    failed: list[str] = []
    oracle_years = set(available_oracle_years())  # upper bound = newest CSV on disk
    for year in years:
        oracle_ok = year >= 2014 and year in oracle_years
        lp_ok = year in lp_reduced.GAP_LEAGUES
        # When both sources exist, resolve home leagues across their UNION so an Eastern team
        # whose only Oracle games are Worlds (home would be 'WLDs' -> games drop) inherits its
        # real domestic home from Leaguepedia and its international games are scored.
        home = _global_home_leagues(year) if (oracle_ok and lp_ok) else None
        srcs: list[tuple[str, pd.DataFrame]] = []
        try:
            if oracle_ok:
                logger.info(
                    f"[career] {year} [oracle]: building (force_recompute={force_recompute}) ..."
                )
                srcs.append(
                    (
                        "oracle",
                        build_player_match_scores(
                            year,
                            weights=weights,
                            force_recompute=force_recompute,
                            home_leagues=home,
                        ),
                    )
                )
            if lp_ok:
                logger.info(f"[career] {year} [lp]: building reduced model ...")
                srcs.append(
                    (
                        "lp",
                        lp_reduced.build_match_scores(
                            year,
                            weights=weights,
                            home_leagues=home,
                            force_recompute=force_recompute,
                        ),
                    )
                )
            if not srcs:
                continue
            combined = (
                srcs[0][1]
                if len(srcs) == 1
                else _combine_matches([f for _, f in srcs], year, weights)
            )
            frame, tc, meta = build_export_frame(
                year, weights, min_games, intl_weight, matches=combined
            )
        except Exception as e:  # a bad/incomplete year shouldn't kill the whole run
            logger.warning(f"[career] {year}: SKIPPED ({type(e).__name__}: {e})")
            failed.append(str(year))
            continue

        records.append(
            {
                "year": year,
                "source": "+".join(s for s, _ in srcs),
                "frame": frame,
                "tc": tc,
                "meta": meta,
                "n_ref": float(meta.get("n_ref", 0.0) or 0.0),
            }
        )
        for c in tc:
            if c not in all_tourn:
                all_tourn.append(c)
    if failed:
        logger.warning(f"[career] skipped: {failed}")
    return records, all_tourn


def _global_home_leagues(year: int) -> Optional[dict]:
    """Resolve each team's home league across BOTH Oracle and Leaguepedia raw data for a
    year, preferring rated leagues, then back-fill from the authoritative team->region map
    (info/team_regions_<year>.csv, the same mapping the Elos are built from). The back-fill
    fixes teams that appear only at an international event in our box-score data (e.g. Worlds
    wildcards KaBuM->CBLOL, Dark Passage->TCL, ahq/TPA->LNL) so their games baseline instead
    of dropping -- without needing to ingest those minor regions' domestic scoreboards.
    """
    from . import lp_ingest
    from .team_regions import load_team_regions

    parts = []
    try:
        o = load_oracle_years((year,))
        parts.append(o[o["position"] != "team"][["teamname", "league"]])
    except Exception:
        pass
    try:
        parts.append(lp_ingest.load_year(year)[["teamname", "league"]])
    except Exception:
        pass
    if not parts:
        return None
    rated = set(load_league_elos(year))
    both = pd.concat(parts, ignore_index=True).dropna(subset=["teamname", "league"])
    home = resolve_home_leagues(both, preferred=rated)
    # Back-fill unresolved/unrated homes from the team->region mapping (case-insensitive, since
    # e.g. team_regions has "Ahq eSports Club" but the box scores have "ahq eSports Club").
    tr = {t.lower(): r for t, r in load_team_regions(year).items()}
    for team in both["teamname"].unique():
        if home.get(team) not in rated:
            region = tr.get(str(team).lower())
            if region in rated:
                home[team] = region
    return home


def _combine_matches(
    frames: list[pd.DataFrame], year: int, weights: ScoreWeights
) -> pd.DataFrame:
    """Concatenate per-source match frames for a year and re-resolve home leagues + baseline
    across the union, so a team whose only games in one source were an international event
    (home would resolve to that event) inherits its real domestic home from the other source
    and keeps those international games. Sources cover disjoint leagues, so no game overlaps.
    """
    m = pd.concat(frames, ignore_index=True)
    elos = load_league_elos(year)
    rated = set(elos)
    # Home league = modal own_league among RATED DOMESTIC games (ignores WLDs/MSI etc.).
    dom = m[m["own_league"].isin(rated)]
    home = dom.groupby("teamname")["own_league"].agg(
        lambda s: s.mode().iat[0] if not s.mode().empty else None
    )
    m["own_league"] = m["teamname"].map(home).fillna(m["own_league"])
    m["opp_league"] = m["opp_teamname"].map(home).fillna(m["opp_league"])
    m["is_international"] = (
        m["own_league"].notna()
        & m["opp_league"].notna()
        & (m["own_league"] != m["opp_league"])
    )
    # Re-score across the union with the region-scaled formula (baseline re-derived from the
    # re-resolved opp_league), so contribution/win_bonus pick up the correct per-game region
    # factor too -- not just the baseline term. See scoring.apply_scored_terms.
    apply_scored_terms(m, weights, elos, source_cols=_SOURCES)
    return m.dropna(subset=["baseline"]).reset_index(drop=True)


def _stack(records: list[dict], all_tourn: list[str]) -> pd.DataFrame:
    """Concatenate all frames into one long frame (row = player-year-source), carrying the
    year and that frame's n_ref (for per-frame schedule normalization)."""
    parts = []
    for rec in records:
        d = rec["frame"].copy()
        if "playername" not in d.columns:  # index holds the player name
            d = d.reset_index().rename(columns={d.columns[0]: "playername"})
        d["year"] = rec["year"]
        d["_nref"] = rec["n_ref"]
        for c in all_tourn:  # ensure every tournament col exists
            if c not in d.columns:
                d[c] = 0.0
        parts.append(d)
    allyears = pd.concat(parts, ignore_index=True)
    allyears[all_tourn] = allyears[all_tourn].fillna(0.0)
    # Canonicalize player names case-insensitively (Leaguepedia "MaRin" vs Oracle "Marin",
    # etc.) so the same player merges across sources. Display = most common original spelling.
    key = allyears["playername"].astype(str).str.lower()
    canon = (
        allyears.assign(_k=key)
        .groupby("_k")["playername"]
        .agg(lambda s: s.mode().iat[0] if not s.mode().empty else s.iloc[0])
    )
    allyears["playername"] = key.map(canon)
    return allyears


# Three-era framing (docs/holistic-lps-plan.md): Era 1 = start-2014 (reduced-model / thin-data
# era), Era 2 = 2015-2017 (graphics overhaul), Era 3 = 2018-present (Runes Reforged / modern LoL).
ERA_BOUNDS = (2014, 2017)  # era1: year <= 2014; era2: 2015-2017; era3: >= 2018
ERA_LABELS = ("<=2014", "2015-2017", "2018+")


def _era_index(year: int) -> int:
    return 0 if year <= ERA_BOUNDS[0] else (1 if year <= ERA_BOUNDS[1] else 2)


def _apply_era_adjustment(
    allyears: pd.DataFrame, tourn_cols: list[str], era_mults: tuple[float, float, float]
) -> pd.DataFrame:
    """Scale each season's point totals by its ERA's multiplier (3 flat eras -- see ERA_BOUNDS),
    lifting the thin-data / fewer-event early eras so their greats aren't under-credited vs modern
    ones. Era 3 (modern) is the 1.0 reference. All-1.0 = off (returns input unchanged). Applied at
    the stacked-frame level, per row's year, so the per-year workbooks (written earlier from the raw
    frames) are untouched."""
    if all(abs(m - 1.0) < 1e-12 for m in era_mults):
        return allyears
    cols = [c for c in _ACCUM_BASE_COLS + list(tourn_cols) if c in allyears.columns]
    m = allyears["year"].map(lambda y: era_mults[_era_index(int(y))]).to_numpy()
    ally = allyears.copy()
    ally[cols] = ally[cols].mul(m, axis=0)
    logger.info(
        "[career] era mults (%s) = %s",
        ", ".join(ERA_LABELS),
        ", ".join(f"{x:g}" for x in era_mults),
    )
    return ally


def _aggregate(
    allyears: pd.DataFrame,
    keys: list[str],
    all_tourn: list[str],
    years: tuple[int, ...],
) -> pd.DataFrame:
    """Aggregate the stacked frame to career totals over `keys` (['playername'] or
    ['playername','position'])."""
    sum_cols = _SUM_COLS + all_tourn
    g = allyears.groupby(keys, sort=False)

    out = g[sum_cols].sum()

    # Games-weighted means (Σ x*games / Σ games).
    gsum = out["games"].replace(0, 1)
    wsum = allyears.assign(
        **{f"_w_{c}": allyears[c] * allyears["games"] for c in _GW_COLS}
    )
    gwmeans = wsum.groupby(keys, sort=False)[[f"_w_{c}" for c in _GW_COLS]].sum()
    for c in _GW_COLS:
        out[c] = gwmeans[f"_w_{c}"] / gsum

    out["best_game"] = g["best_game"].max()
    out["worst_game"] = g["worst_game"].min()

    # Re-derived rates.
    out["win_rate"] = out["wins"] / out["games"].replace(0, 1)
    tw = out["total_weight"].replace(0, 1)
    out["pts_per_game_w"] = out["total_score"] / tw
    out["contrib_pg_w"] = out["contrib_pts"] / tw
    out["clutch_gap"] = out["pts_per_game_w"] - out["pts_per_game"]

    # Years active + peak.
    yr = g["year"].agg(n_years="nunique", first_year="min", last_year="max")
    out = out.join(yr)
    peak = (
        allyears.sort_values("total_score")
        .drop_duplicates(keys, keep="last")
        .set_index(keys)[["year", "total_score"]]
        .rename(columns={"year": "peak_year", "total_score": "peak_lps"})
    )
    out = out.join(peak)
    out["lps_per_year"] = out["total_score"] / out["n_years"].replace(0, 1)

    # Primary team / league / position = the value from the season with the most games.
    prim_cols = [c for c in ["team", "league", "position"] if c not in keys]
    prim = (
        allyears.sort_values("games")
        .drop_duplicates(keys, keep="last")
        .set_index(keys)[prim_cols]
    )
    for c in prim_cols:
        out[c] = prim[c]

    # Per-year LPS trajectory (one column per year).
    pivot = allyears.pivot_table(
        index=keys, columns="year", values="total_score", aggfunc="sum", fill_value=0.0
    )
    pivot.columns = [f"y{int(c)}" for c in pivot.columns]
    out = out.join(pivot)
    for y in years:
        if f"y{y}" not in out.columns:
            out[f"y{y}"] = 0.0

    return out.reset_index()


def _breakdown_df(
    frame: pd.DataFrame,
    keys: list[str],
    col: str,
    out_name: str,
    value_col: str = "clr_year",
    as_pct: bool = False,
) -> pd.DataFrame:
    """For each group in `keys`, list the distinct values of `col` a player logged, ordered by the
    value earned with each (CLR by default), as one string: 'T1 (245.3), DAMWON Gaming (30.1)' --
    or, with as_pct, share of the player's total: 'T1 (78%), DAMWON Gaming (10%)'.
    Returns a frame [*keys, out_name] to merge onto a career aggregate."""
    g = (
        frame.groupby(keys + [col], sort=False, dropna=True)[value_col]
        .sum()
        .reset_index()
    )
    g = g[(g[col].astype(str) != "") & (g[value_col].abs() > 1e-9)]
    g = g.sort_values(value_col, ascending=False)  # highest first, preserved by groupby
    if as_pct:
        tot = g.groupby(keys, sort=False)[value_col].transform("sum")
        pct = 100.0 * g[value_col] / tot.where(tot != 0, 1.0)
        g["_s"] = [f"{v} ({p:.0f}%)" for v, p in zip(g[col].astype(str), pct)]
    else:
        g["_s"] = [f"{v} ({s:.1f})" for v, s in zip(g[col].astype(str), g[value_col])]
    return (
        g.groupby(keys, sort=False)["_s"]
        .agg(", ".join)
        .reset_index()
        .rename(columns={"_s": out_name})
    )


def _add_clr_year(
    allyears: pd.DataFrame,
    career_all: pd.DataFrame,
    bonus_long: pd.DataFrame,
    w_bonus: float,
) -> pd.DataFrame:
    """Return a copy of `allyears` with an additive per-row CLR contribution `clr_year`, so
    team/league/lane splits can be ordered by (and shown as a share of) CLR rather than raw LPS:
        clr_year = (CLR - w_bonus*resume_bonus) * (row LPS / career LPS)   # performance, ∝ LPS
                 + w_bonus * that (player, lane, year)'s résumé bonus       # credited where earned
    The performance part (career bulk + pace + peak) tracks LPS, so the split isn't distorted by
    lumpy peak/pace attribution; the résumé bonus lands on the exact seasons/teams/lanes that
    earned it, so championship stints rank up (the intended 'by CLR, not LPS' difference). Summed
    per player it equals CLR. Computed as a column (no self-merge) so dual-position seasons -- two
    rows for one (player, year) -- aren't cartesian-inflated."""
    ally = allyears.copy()
    if len(bonus_long):  # résumé bonus per (player, lane, year)
        yb = (
            bonus_long.assign(_yb=bonus_long[_BONUS_COLS].sum(axis=1))
            .groupby(["playername", "position", "year"], as_index=False)["_yb"]
            .sum()
        )
        ally = ally.merge(yb, on=["playername", "position", "year"], how="left")
    if "_yb" not in ally.columns:
        ally["_yb"] = 0.0
    ally["_yb"] = ally["_yb"].fillna(0.0)
    # Spread each (player, lane, year) bonus across its rows by LPS, so it sums to the group bonus
    # exactly even when a season spans duplicate rows or multiple teams (a mid-year trade).
    grp = ally.groupby(["playername", "position", "year"])["total_score"].transform(
        "sum"
    )
    row_bonus = ally["_yb"] * ally["total_score"] / grp.where(grp != 0, 1.0)
    pl = career_all.set_index("playername")
    perf = ally["playername"].map(pl["clr"]) - w_bonus * ally["playername"].map(
        pl["resume_bonus"]
    )
    career_lps = ally["playername"].map(pl["total_score"])
    share = ally["total_score"] / career_lps.where(career_lps != 0, 1.0)
    ally["clr_year"] = perf * share + w_bonus * row_bonus
    return ally.drop(columns="_yb")


def _add_clr(
    career: pd.DataFrame, years: tuple[int, ...], cfg: CLRConfig
) -> pd.DataFrame:
    """Add the Career Legend Rating composite + its components to an aggregated career frame.

    CLR = w_career*CareerValue + w_pace*PaceValue + w_peak*PeakValue.  All three are on a
    ~one-season scale (so the weights are unit-free):
      - CareerValue = CareerLPS / D   -- total production per unit of a typical career length;
        careers longer than D keep a bulk advantage, shorter ones scale down (Pace counters).
      - PaceValue   = per-active-year production, empirical-Bayes shrunk toward the cohort mean
        by weighted games so brilliant short careers aren't buried yet tiny samples can't win.
      - PeakValue   = "plateau" peak: mean of the player's PEAK YEARS (seasons within `peak_band`
        of their best season) plus a length bonus per extra peak year. A one-year peak (Marin)
        scores its single great season exactly; a wide plateau (Faker) scores its plateau average
        plus a length reward. A longer peak is never penalized (see CLRConfig for the guarantee).
    Also exposes peak_years (count) and peak_band_avg (plateau mean) as standalone columns.
    """
    best = career["peak_lps"].to_numpy(dtype=float)  # absolute peak season (== PeakLPS)
    thr = best * (1.0 - cfg.peak_band)  # peak-year threshold, per player
    ycols = [f"y{y}" for y in years if f"y{y}" in career.columns]
    yv = career[ycols].to_numpy(dtype=float) if ycols else np.zeros((len(career), 0))
    k = np.ones(
        len(career)
    )  # number of peak years (>= 1: the best season always counts)
    band_avg = best.copy()  # mean of the peak years (defaults to the best season)
    for i, row in enumerate(yv):
        peak_yrs = row[row >= thr[i]]  # seasons within the band of the peak
        if peak_yrs.size:
            k[i] = peak_yrs.size
            band_avg[i] = peak_yrs.mean()
    career["peak_years"] = k.astype(int)
    career["peak_band_avg"] = band_avg
    career["peak_value"] = band_avg + cfg.peak_len_bonus * best * (k - 1.0)

    career["career_value"] = career["total_score"] / cfg.career_divisor

    raw_pace = career["total_score"] / career["n_years"].replace(0, 1)
    gw = career["total_weight"].to_numpy(dtype=float)
    prior = float(np.average(raw_pace, weights=career["games"].clip(lower=1)))
    conf = gw / (gw + cfg.pace_prior_games)
    career["pace_value"] = conf * raw_pace + (1.0 - conf) * prior

    career["clr"] = (
        cfg.w_career * career["career_value"]
        + cfg.w_pace * career["pace_value"]
        + cfg.w_peak * career["peak_value"]
    )
    return career


_BONUS_COLS = ["intl_bonus", "title_bonus", "award_bonus"]


def _add_bonuses(
    career_all: pd.DataFrame,
    career_lane: pd.DataFrame,
    bonus_long: pd.DataFrame,
    w_bonus: float,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Fold the (precomputed) per-(player,position,year) resume bonuses into CLR. Adds
    intl_bonus/title_bonus/award_bonus + resume_bonus columns and updates `clr` by
    w_bonus * resume_bonus. Bonuses are aggregated to per-player (Overview) and
    per-player-lane (lane sheets); a title credits the lane the player played that year.
    """
    agg_cols = (
        _BONUS_COLS + RESUME_BREAKDOWN_COLS
    )  # headline bonuses + per-category counts/pts
    b_all = (
        bonus_long.groupby("playername")[agg_cols].sum().reset_index()
        if len(bonus_long)
        else pd.DataFrame(columns=["playername", *agg_cols])
    )
    b_lane = (
        bonus_long.groupby(["playername", "position"])[agg_cols].sum().reset_index()
        if len(bonus_long)
        else pd.DataFrame(columns=["playername", "position", *agg_cols])
    )
    career_all = career_all.merge(b_all, on="playername", how="left")
    career_lane = career_lane.merge(b_lane, on=["playername", "position"], how="left")
    out = []
    for frame in (career_all, career_lane):
        for c in agg_cols:
            if c not in frame.columns:
                frame[c] = 0.0
        frame[agg_cols] = frame[agg_cols].fillna(0.0)
        frame["resume_bonus"] = frame[_BONUS_COLS].sum(axis=1)
        frame["clr"] = frame["clr"] + w_bonus * frame["resume_bonus"]
        out.append(frame)
    return out[0], out[1]


def _scale_clr_components(
    frame: pd.DataFrame, cfg: CLRConfig, w_bonus: float
) -> pd.DataFrame:
    """Rewrite the CLR component columns IN PLACE to their WEIGHTED contribution, so the
    displayed parts add straight up to CLR:
        CLR = w_career*CareerVal + w_pace*PaceVal + w_peak*PeakVal + w_bonus*Resume
    Each Resume sub-bonus (Intl/Titles/Awards) is shown post-w_bonus too, so it still sums to
    the (now weighted) Resume column. With the default unit weights this is a no-op; once the
    weights are calibrated away from 1.0 the columns stay reconcilable against CLR by eye.
    MUST run after everything that consumes the raw components (_add_clr_year reads the raw
    resume_bonus + clr), i.e. as the last step before writing."""
    scale = {
        "career_value": cfg.w_career,
        "pace_value": cfg.w_pace,
        "peak_value": cfg.w_peak,
        "resume_bonus": w_bonus,
        "intl_bonus": w_bonus,
        "title_bonus": w_bonus,
        "award_bonus": w_bonus,
    }
    scale.update(
        {c: w_bonus for c in _RB_PTS}
    )  # per-category points weighted too; counts not
    for col, w in scale.items():
        if col in frame.columns:
            frame[col] = frame[col] * w
    return frame


_HIGH_NOON_YEARS = (
    3  # High Noon averages a player's N best-ranked seasons (companion metric)
)


def _high_noon(
    allyears: pd.DataFrame, n_years: int = _HIGH_NOON_YEARS
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Compute 'High Noon' peer-rank companion columns from the stacked per-(player,year) frame.

    Each season, rated players are ranked by that year's schedule-normalized LPS (rank 1 = best),
    both GLOBALLY (all lanes together) and WITHIN LANE. For each player we record:
      - the BEST single-season rank (their highest peer standing ever), and
      - HN3 = the average peer rank over their N best-ranked seasons (default 3), plus the years
        that make it up -- i.e. how dominant they were across their strongest seasons.
    Best seasons are taken WHEREVER they fall (not a consecutive window), matching how PeakVal is
    defined, so a gap year never breaks the metric. Lower is better. COMPANION only -- NOT summed
    into CLR (peak already lives in the score). Returns (by_player, by_player_position) frames.
    """
    df = allyears[["playername", "position", "year", "total_score"]].copy()
    df = df[df["total_score"].notna() & df["year"].notna()]
    df["year"] = df["year"].astype(int)
    df["rank_global"] = df.groupby("year")["total_score"].rank(
        ascending=False, method="min"
    )
    df["rank_lane"] = df.groupby(["year", "position"])["total_score"].rank(
        ascending=False, method="min"
    )

    def _stats(year_rank: dict) -> tuple[float, float, str]:
        by_rank = sorted(
            year_rank.items(), key=lambda kv: kv[1]
        )  # best (lowest) rank first
        best = float(by_rank[0][1])
        top = by_rank[:n_years]
        hn = sum(r for _, r in top) / len(top)
        yrs = ",".join(
            str(y) for y in sorted(y for y, _ in top)
        )  # the High Noon seasons
        return best, hn, yrs

    def _rows(keys: list[str]) -> pd.DataFrame:
        out = []
        for key, sub in df.groupby(keys, sort=False):
            gb, g3, gyr = _stats(dict(zip(sub["year"], sub["rank_global"])))
            lb, l3, lyr = _stats(dict(zip(sub["year"], sub["rank_lane"])))
            rec = dict(zip(keys, key if isinstance(key, tuple) else (key,)))
            rec.update(
                hn_lane_best=lb,
                hn_lane=l3,
                hn_lane_yrs=lyr,
                hn_global_best=gb,
                hn_global=g3,
                hn_global_yrs=gyr,
            )
            out.append(rec)
        return pd.DataFrame(out)

    return _rows(["playername"]), _rows(["playername", "position"])


def _career_layout(
    all_tourn: list[str], years: tuple[int, ...], include_lane: bool
) -> list[tuple]:
    """(col, header, fmt, width) layout for a career sheet."""
    lay: list[tuple] = [
        ("rank", "Rank", _INT, 6),
        ("playername", "Player", None, 16),
        # Full career breakdown: every team / league (and, on Overview, every lane) a player
        # logged, ordered by the CLR earned with each -- "T1 (245.3), DAMWON Gaming (30.1)"
        # (or shares like "T1 (78%), ..." when built with breakdown_pct).
        ("teams_lps", "Teams (by CLR)", None, 38),
        ("leagues_lps", "Leagues (by CLR)", None, 24),
    ]
    if include_lane:
        lay.append(("lanes_lps", "Lanes (by CLR)", None, 20))
    lay += [
        ("n_years", "#Yrs", _INT, 6),
        ("first_year", "First", _INT, 7),
        ("last_year", "Last", _INT, 7),
        ("games", "Games", _INT, 7),
        ("win_rate", "Win%", _PCT, 7),
        ("clr", "CLR", _PTS, 9),
        ("career_value", "CareerVal", _PTS, 9),
        ("pace_value", "PaceVal", _PTS, 8),
        ("peak_value", "PeakVal", _PTS, 8),
        ("resume_bonus", "Resume", _PTS, 8),
        ("intl_bonus", "Intl", _PTS, 7),
        ("title_bonus", "Titles", _PTS, 7),
        ("award_bonus", "Awards", _PTS, 7),
        # Resume breakdown: a count (#) + weighted points (Pt) per category; the Pt columns sum to
        # Resume. Intl = WldsChmp+WldsFin+WldsSemi+MSIChmp+MSIFin+MSISemi+IntlChmp+IntlFin+IntlSemi;
        # Titles = DomChmp+DomFin+DomCup; Awards = MVP+AllPro.
        # Intl = Worlds/MSI/Other split by placement tier; OthIntl = EWC/First Stand/MSC/LTA/
        # Rift Rivals/ASI/...; DomCup = KeSPA + Demacia cups.
        ("rb_wlds_title_n", "WldsChmp#", _INT, 9),
        ("rb_wlds_title_pts", "WldsChmpPt", _PTS, 10),
        ("rb_wlds_final_n", "WldsFin#", _INT, 9),
        ("rb_wlds_final_pts", "WldsFinPt", _PTS, 9),
        ("rb_wlds_semi_n", "WldsSemi#", _INT, 9),
        ("rb_wlds_semi_pts", "WldsSemiPt", _PTS, 9),
        ("rb_msi_title_n", "MSIChmp#", _INT, 8),
        ("rb_msi_title_pts", "MSIChmpPt", _PTS, 9),
        ("rb_msi_final_n", "MSIFin#", _INT, 8),
        ("rb_msi_final_pts", "MSIFinPt", _PTS, 9),
        ("rb_msi_semi_n", "MSISemi#", _INT, 8),
        ("rb_msi_semi_pts", "MSISemiPt", _PTS, 9),
        ("rb_othr_intl_champ_n", "IntlChmp#", _INT, 9),
        ("rb_othr_intl_champ_pts", "IntlChmpPt", _PTS, 10),
        ("rb_othr_intl_final_n", "IntlFin#", _INT, 8),
        ("rb_othr_intl_final_pts", "IntlFinPt", _PTS, 9),
        ("rb_othr_intl_semi_n", "IntlSemi#", _INT, 8),
        ("rb_othr_intl_semi_pts", "IntlSemiPt", _PTS, 9),
        ("rb_dom_champ_n", "DomChmp#", _INT, 9),
        ("rb_dom_champ_pts", "DomChmpPt", _PTS, 10),
        ("rb_dom_final_n", "DomFin#", _INT, 8),
        ("rb_dom_final_pts", "DomFinPt", _PTS, 9),
        ("rb_dom_cup_n", "DomCup#", _INT, 8),
        ("rb_dom_cup_pts", "DomCupPt", _PTS, 9),
        ("rb_mvp_n", "MVP#", _INT, 7),
        ("rb_mvp_pts", "MVPPt", _PTS, 8),
        ("rb_allpro_n", "AllPro#", _INT, 8),
        ("rb_allpro_pts", "AllProPt", _PTS, 9),
        ("total_score", "CareerLPS", _PTS, 11),
        ("lps_per_year", "LPS/Yr", _PTS, 8),
        ("peak_year", "PeakYr", _INT, 7),
        ("peak_lps", "PeakLPS", _PTS, 9),
        ("peak_years", "PeakYrs", _INT, 8),
        ("peak_band_avg", "PeakAvg", _PTS, 9),
        ("hn_lane_best", "BestRkLane", _INT, 10),
        ("hn_lane", "HN3Lane", _PTS, 8),
        ("hn_lane_yrs", "HN3LaneYrs", None, 14),
        ("hn_global_best", "BestRkGlob", _INT, 10),
        ("hn_global", "HN3Glob", _PTS, 8),
        ("hn_global_yrs", "HN3GlobYrs", None, 14),
        ("pts_per_game", "LPS/Gm", _PTS, 8),
        ("pts_per_game_w", "LPS/Gm·wt", _PTS, 10),
        ("reg_pts", "Regular", _PTS, 9),
        ("playoff_pts", "Playoffs", _PTS, 9),
        ("tourn_pts", "Tourneys", _PTS, 9),
        ("base_pts", "Baseline", _PTS, 9),
        ("contrib_pts", "Contribution", _PTS, 12),
        ("wbonus_pts", "WinBonus", _PTS, 9),
        ("kills_pts", "Kills", _PTS, 8),
        ("deaths_pts", "Deaths", _PTS, 8),
        ("assists_pts", "Assists", _PTS, 8),
        ("damage_pts", "Damage", _PTS, 8),
        ("fb_pts", "FirstBlood", _PTS, 10),
    ]
    lay += [(c, c.replace("_pts", ""), _PTS, 8) for c in all_tourn]
    lay += [
        ("avg_contrib", "AvgContrib", _SIGNED, 10),
        ("avg_resid", "Intangibles", _SIGNED, 12),
        ("avg_p_model", "AvgWinProb", _PCT, 10),
        ("sched_strength", "SoS", _PCT, 8),
        ("region_elo", "RegElo", _INT, 8),
        ("clutch_gap", "Clutch", _SIGNED, 9),
    ]
    lay += [(f"y{y}", str(y), _PTS, 7) for y in years]  # per-year LPS trajectory
    return lay


def _write_about(writer, meta: dict) -> None:
    rows = [
        ("LPS career (cumulative) ratings", ""),
        ("Years", f"{meta['years'][0]}-{meta['years'][-1]}"),
        ("Generated", _dt.date.today().isoformat()),
        ("", ""),
        ("Weights", ""),
        ("  alpha (baseline)", meta["alpha"]),
        ("  lambda (contribution)", meta["lam"]),
        ("  beta (win bonus)", meta["beta"]),
        ("  region_exp (region scaling)", meta.get("region_exp")),
        ("  w_regular (regular-season mult)", meta.get("w_regular")),
        ("  w_playoff (playoff mult)", meta.get("w_playoff")),
        ("  intl_weight", meta["intl_weight"]),
        ("  min games / year", meta["min_games"]),
        ("", ""),
        (
            "Method",
            "Each year is scored independently (models retrained per year for meta",
        ),
        (
            "",
            "changes), then LPS and every breakdown are SUMMED across years per player.",
        ),
        (
            "",
            "CareerLPS rewards both peak and longevity. Per-year columns (yYYYY) show the",
        ),
        ("", "trajectory; PeakYr/PeakLPS mark the best single season."),
        ("", ""),
        (
            "Schedule normalization",
            f"Point totals rescaled per year by REF/N_ref "
            f"(REF={meta.get('ref_nref', 0):.1f} matches) so schedule length doesn't bias the",
        ),
        ("", "career sum across eras; the Elo/baseline strength signal is kept."),
        ("", ""),
        (
            "Era adjustment (3 eras)",
            "Era1 (<=2014) / Era2 (2015-2017) / Era3 (2018+) point totals x "
            f"{tuple(round(m, 3) for m in meta.get('era_mults', (1.0, 1.0, 1.0)))},",
        ),
        (
            "",
            "lifting the thin-data/fewer-event early eras so old-era greats aren't under-credited "
            "vs modern ones (Era3 = 1.0 reference). All 1.0 = off.",
        ),
    ]
    cfg = meta.get("clr")
    if cfg is not None:
        rows += [
            ("", ""),
            ("CLR (Career Legend Rating) -- PRIMARY RANKING", ""),
            (
                "",
                "Holistic PPS/JAWS-style composite (see docs/holistic-lps-plan.md). Blends",
            ),
            (
                "",
                "three length-decoupled views of a career onto a common one-season scale:",
            ),
            ("  CLR", "w_career*CareerVal + w_pace*PaceVal + w_peak*PeakVal"),
            (
                "  CareerVal",
                f"CareerLPS / D  (bulk; D = typical career length = {cfg.career_divisor})",
            ),
            (
                "  PaceVal",
                f"per-active-year LPS, empirical-Bayes shrunk toward the cohort mean "
                f"(prior = {cfg.pace_prior_games:g} weighted games) -- rate reward, length-neutral",
            ),
            (
                "  PeakVal",
                f"mean(peak years) + {cfg.peak_len_bonus:g}*PeakLPS*(PeakYrs-1); a "
                f"season is a peak year if >= {1 - cfg.peak_band:g}*PeakLPS (within "
                f"{cfg.peak_band:.0%} of the best). Longer peaks never penalized.",
            ),
            (
                "  + Resume",
                "w_bonus * (Intl + Titles + Awards) -- see Resume bonuses below",
            ),
            (
                "  Weights (w_career, w_pace, w_peak, w_bonus)",
                f"{cfg.w_career:g}, {cfg.w_pace:g}, {cfg.w_peak:g}, "
                f"{meta.get('w_bonus', 1.0):.4g}  (provisional -- pending calibration)",
            ),
            ("", "CareerLPS is kept as a component column; sheets now sort by CLR."),
            (
                "",
                "The CareerVal/PaceVal/PeakVal/Resume columns are shown as their WEIGHTED",
            ),
            (
                "",
                "contributions (component * its weight), so they add straight up to CLR.",
            ),
            ("", ""),
            ("Resume bonuses (Intl / Titles / Awards)", ""),
            (
                "  Intl",
                "Worlds/MSI placement points (champion..play-in), flat by event+round.",
            ),
            (
                "  Titles",
                "Domestic split-playoff titles/finals, each scaled by that region's Elo",
            ),
            ("", "strength (an LCK/LPL title outweighs a weak-region one)."),
            (
                "  Awards",
                "Regional MVP / All-Pro / Finals MVP (auto-pulled from Leaguepedia to",
            ),
            (
                "",
                "info/player_awards.csv); domestic awards region-scaled, global Finals MVP flat.",
            ),
            (
                "",
                "Credited to the lane the player played that year. Source: info/achievements.csv.",
            ),
            ("", ""),
            ("Resume diminishing returns", ""),
            (
                "  repeat_decay",
                f"{meta.get('repeat_decay', 1.0):g}  -- winning the SAME kind of thing "
                "(Worlds/MSI at a given round; domestic champ/finalist; a given award) repeatedly is",
            ),
            (
                "",
                "scaled per player: best instance full, k-th worth repeat_decay^(k-1). 1.0 = off.",
            ),
            (
                "",
                f"Decay shrank résumé to {meta.get('resume_shrink', 1.0):.1%} of undecayed; the "
                f"per-category Pt columns are already decayed. w_bonus is a flat {meta.get('w_bonus', 0):g}.",
            ),
            ("", ""),
            ("High Noon (peer rank) -- COMPANION, not in CLR", ""),
            (
                "",
                "Each season, rated players are ranked by that year's LPS (1 = best), globally",
            ),
            (
                "",
                "and within lane. BestRkLane/BestRkGlob = best single-season rank; HN3Lane/",
            ),
            (
                "",
                "HN3Glob = average rank over the player's 3 best-ranked seasons (listed in the",
            ),
            (
                "",
                "HN3*Yrs columns), taken wherever they fall (not a consecutive window, matching",
            ),
            ("", "PeakVal). Lower is better. Shown alongside CLR, not summed in."),
        ]
    about = pd.DataFrame(rows, columns=["Field", "Value"])
    about.to_excel(writer, sheet_name="About", index=False)
    ws = writer.sheets["About"]
    ws.column_dimensions["A"].width = 40
    ws.column_dimensions["B"].width = 66
    from openpyxl.styles import Font

    for row in ws.iter_rows(min_row=1, max_row=ws.max_row, min_col=1, max_col=1):
        row[0].font = Font(bold=True)


def write_career_workbook(
    out: Path,
    career_all: pd.DataFrame,
    career_lane: pd.DataFrame,
    all_tourn: list[str],
    years: tuple[int, ...],
    meta: dict,
) -> Path:
    lay_all = _career_layout(
        all_tourn, years, include_lane=True
    )  # Overview shows Lane too
    lay_lane = _career_layout(all_tourn, years, include_lane=False)
    with pd.ExcelWriter(out, engine="openpyxl") as writer:
        _write_about(writer, meta)

        ov = career_all.sort_values("clr", ascending=False).copy()
        ov.insert(0, "rank", range(1, len(ov) + 1))
        _write_sheet(writer, "Overview", ov, lay_all)

        for lane in ROLES:
            sub = (
                career_lane[career_lane["position"] == lane]
                .sort_values("clr", ascending=False)
                .copy()
            )
            sub.insert(0, "rank", range(1, len(sub) + 1))
            _write_sheet(writer, _LANE_NAMES[lane], sub, lay_lane)

        _write_glossary(writer)
    return out


def build_and_write(
    years: tuple[int, ...] = YEARS_DEFAULT,
    weights: Optional[ScoreWeights] = None,
    min_games: int = 3,
    intl_weight: float = 2.0,
    force_recompute: bool = True,
    write_yearly: bool = True,
    out: Optional[Path] = None,
    clr_cfg: Optional[CLRConfig] = None,
    bonus_cfg: Optional[BonusConfig] = None,
    breakdown_pct: bool = False,
) -> Path:
    weights = weights or _DEMO_WEIGHTS
    clr_cfg = clr_cfg or CLRConfig()
    bonus_cfg = bonus_cfg or BonusConfig()
    out = (
        Path(out)
        if out is not None
        else PROJECT_ROOT / f"player_ratings_career_{years[0]}_{years[-1]}.xlsx"
    )

    # Build the cross-year lane-normalization tables ONCE, up front, from ALL years pooled
    # (independent of the --years subset being written) so every per-year frame is remapped
    # against the same global reference. Must precede the year loop: it force-rebuilds each
    # year's raw contributions when force_recompute, so the pooled distributions are current.
    from .season import build_lane_remap

    logger.info("[career] building cross-year lane-normalization tables ...")
    build_lane_remap(force_recompute=force_recompute)

    # Per-year frames reuse the raw caches the prebuild just refreshed (gap-year '_merged'
    # variants build on demand), so the loop itself doesn't need to force a rebuild.
    records, all_tourn = run_year_frames(years, weights, min_games, intl_weight, False)
    if not records:
        raise RuntimeError("no years produced ratings; nothing to aggregate")
    got = tuple(sorted({r["year"] for r in records}))  # years that actually succeeded

    # SCHEDULE-LENGTH NORMALIZATION: point accumulations scale with each frame's N_ref
    # (matches/player), which varies ~1.5x. Rescale every year's point columns by REF/N_ref so
    # a full season is worth the same regardless of schedule length, while keeping the Elo/
    # baseline signal (stronger modern leagues still score higher per game). Applied to each
    # year's FRAME up front so the per-year workbooks and the career sum share the exact same
    # normalized numbers -- per-year LPS totals therefore sum to CareerLPS.
    from .export_excel import apply_schedule_norm, write_workbook

    nrefs = [r["n_ref"] for r in records if r["n_ref"]]
    ref_nref = float(np.mean(nrefs)) if nrefs else 1.0
    for rec in records:
        rec["mult"] = ref_nref / rec["n_ref"] if rec["n_ref"] else 1.0
        rec["frame"] = apply_schedule_norm(rec["frame"], rec["mult"], rec["tc"])

    if write_yearly:
        for rec in records:
            ymeta = dict(rec["meta"])
            ymeta["ref_nref"] = ref_nref
            ymeta["sched_mult"] = rec["mult"]
            out_y = PROJECT_ROOT / f"player_ratings_{rec['year']}.xlsx"
            write_workbook(out_y, rec["frame"], rec["tc"], ymeta)
            logger.info(
                f"[career] {rec['year']} [{rec['source']}]: wrote {out_y.name}  "
                f"({len(rec['frame'])} players, x{rec['mult']:.3f})"
            )

    allyears = _stack(records, all_tourn)  # frames already schedule-normalized
    # Era adjustment: normalize each season toward its era's best (cross-era comparability). Applied
    # here (post-stack) so the per-year workbooks written above keep their raw schedule-normed values.
    allyears = _apply_era_adjustment(allyears, all_tourn, clr_cfg.era_mults)
    career_all = _add_clr(
        _aggregate(allyears, ["playername"], all_tourn, got), got, clr_cfg
    )
    career_lane = _add_clr(
        _aggregate(allyears, ["playername", "position"], all_tourn, got), got, clr_cfg
    )

    # High Noon peer-rank companion columns (global + per-lane); NOT summed into CLR.
    hn_all, hn_lane = _high_noon(allyears)
    career_all = career_all.merge(hn_all, on="playername", how="left")
    career_lane = career_lane.merge(hn_lane, on=["playername", "position"], how="left")

    # Resume bonuses (Phase 2): Worlds/MSI placements + domestic titles + awards -> folded into
    # CLR (IntlBonus + TitleBonus + AwardBonus, weighted by w_bonus), attributed to the lane the
    # player played that year. See achievements.py / info/achievements.csv. Diminishing returns
    # (repeat_decay) shrink repeated like achievements before crediting; w_bonus is a flat weight.
    roster = allyears[["playername", "year", "team", "league", "position"]].copy()
    bonus_long = score_bonuses(roster, bonus_cfg)
    resume_shrink = float(bonus_long.attrs.get("resume_shrink", 1.0))
    w_bonus = bonus_cfg.w_bonus
    logger.info(
        f"[career] resume decay={bonus_cfg.repeat_decay:g}: survived {resume_shrink:.1%} "
        f"of undecayed points; w_bonus={w_bonus:g}"
    )
    career_all, career_lane = _add_bonuses(career_all, career_lane, bonus_long, w_bonus)

    # Career breakdowns: every team / league / lane a player logged, ordered by the CLR earned with
    # each (additive per-year decomposition, so multi-team/region/lane careers -- Xiaohu, Perkz --
    # are fully visible). Overview lists all lanes; per-lane sheets list teams/leagues within that
    # lane. `breakdown_pct` renders shares ("T1 (78%), ...") instead of absolute CLR, for the site.
    # NOTE: same-year team changes are attributed to the season's primary team (see _stack); the
    # per-team split isn't trade-accurate yet (career totals are).
    ally_clr = _add_clr_year(allyears, career_all, bonus_long, w_bonus)
    for col, name in (
        ("team", "teams_lps"),
        ("league", "leagues_lps"),
        ("position", "lanes_lps"),
    ):
        career_all = career_all.merge(
            _breakdown_df(ally_clr, ["playername"], col, name, as_pct=breakdown_pct),
            on="playername",
            how="left",
        )
    for col, name in (("team", "teams_lps"), ("league", "leagues_lps")):
        career_lane = career_lane.merge(
            _breakdown_df(
                ally_clr, ["playername", "position"], col, name, as_pct=breakdown_pct
            ),
            on=["playername", "position"],
            how="left",
        )

    # Show the CLR component columns as their WEIGHTED contributions (last step: _add_clr_year
    # above consumes the raw resume_bonus), so CareerVal+PaceVal+PeakVal+Resume sums to CLR.
    career_all = _scale_clr_components(career_all, clr_cfg, w_bonus)
    career_lane = _scale_clr_components(career_lane, clr_cfg, w_bonus)

    meta = {
        "years": got,
        "alpha": weights.alpha,
        "lam": weights.lam,
        "beta": weights.beta,
        "region_exp": weights.region_exp,
        "w_regular": weights.w_regular,
        "w_playoff": weights.w_playoff,
        "intl_weight": intl_weight,
        "min_games": min_games,
        "ref_nref": ref_nref,
        "clr": clr_cfg,
        "w_bonus": w_bonus,
        "repeat_decay": bonus_cfg.repeat_decay,
        "resume_shrink": resume_shrink,
        "era_mults": clr_cfg.era_mults,
    }
    write_career_workbook(out, career_all, career_lane, all_tourn, got, meta)
    logger.info(
        f"[career] wrote {out.name}  ({len(career_all)} players, {len(got)} years)"
    )
    _write_yearly_breakdown(allyears, out.parent)
    return out


def _write_yearly_breakdown(allyears: pd.DataFrame, out_dir: Path) -> None:
    """Write per-(player, year) component breakdown used by the web trajectory chart."""
    import json as _json

    comp_cols = [
        "kills_pts", "deaths_pts", "assists_pts", "damage_pts", "fb_pts",
        "reg_pts", "playoff_pts", "tourn_pts",
    ]
    avail = [c for c in comp_cols if c in allyears.columns]
    if not avail:
        return
    grp = allyears.groupby(["playername", "year"])[avail].sum()
    out: dict[str, dict[str, dict[str, float]]] = {}
    for (player, year), row in grp.iterrows():
        yr = str(int(year))
        d = {k: round(float(row[k]), 3) for k in avail if abs(float(row[k])) > 0.001}
        if d:
            out.setdefault(str(player), {})[yr] = d
    path = out_dir / "player_yearly_breakdown.json"
    path.write_text(
        _json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )
    logger.info(f"[career] wrote per-year breakdown -> {path.name}")


def _parse_years(s: str) -> tuple[int, ...]:
    if "-" in s:
        a, b = s.split("-")
        return tuple(range(int(a), int(b) + 1))
    return tuple(int(x) for x in s.split(","))


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(
        description="Build per-year + cumulative career LPS workbooks."
    )
    ap.add_argument("--years", type=str, default=f"2011-{latest_oracle_year()}")
    ap.add_argument("--min-games", type=int, default=3)
    ap.add_argument("--intl-weight", type=float, default=2.0)
    ap.add_argument("--alpha", type=float, default=_DEMO_WEIGHTS.alpha)
    ap.add_argument("--lam", type=float, default=_DEMO_WEIGHTS.lam)
    ap.add_argument("--beta", type=float, default=_DEMO_WEIGHTS.beta)
    ap.add_argument("--region-exp", type=float, default=_DEMO_WEIGHTS.region_exp)
    ap.add_argument(
        "--no-recompute", action="store_true", help="reuse cached per-year models"
    )
    ap.add_argument("--no-yearly", action="store_true", help="skip per-year workbooks")
    ap.add_argument(
        "--breakdown-pct",
        action="store_true",
        help="render team/league/lane splits as CLR shares (e.g. 'T1 (78%)')",
    )
    ap.add_argument(
        "--repeat-decay",
        type=float,
        default=BonusConfig.repeat_decay,
        help="diminishing returns for repeated like achievements (1.0 = off)",
    )
    ap.add_argument(
        "--w-bonus",
        type=float,
        default=BonusConfig.w_bonus,
        help="resume-bonus weight into CLR",
    )
    ap.add_argument(
        "--era-mults",
        type=str,
        default=None,
        help="era multipliers 'e1,e2,e3' (<=2014, 2015-2017, 2018+); default uses CLRConfig",
    )
    args = ap.parse_args()

    weights = ScoreWeights(
        alpha=args.alpha, lam=args.lam, beta=args.beta, region_exp=args.region_exp
    )
    bonus_cfg = BonusConfig(repeat_decay=args.repeat_decay, w_bonus=args.w_bonus)
    clr_cfg = CLRConfig()
    if args.era_mults:
        e = tuple(float(x) for x in args.era_mults.split(","))
        assert len(e) == 3, "--era-mults needs 3 comma-separated values"
        clr_cfg = CLRConfig(era_mults=e)
    build_and_write(
        years=_parse_years(args.years),
        weights=weights,
        min_games=args.min_games,
        intl_weight=args.intl_weight,
        force_recompute=not args.no_recompute,
        write_yearly=not args.no_yearly,
        breakdown_pct=args.breakdown_pct,
        bonus_cfg=bonus_cfg,
        clr_cfg=clr_cfg,
    )


if __name__ == "__main__":
    main()
