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

from .achievements import BonusConfig, score_bonuses
from .config import PROJECT_ROOT
from .contribution import ROLES
from .export_excel import (
    _INT, _PCT, _PTS, _SIGNED, _GLOSSARY, _write_glossary, _write_sheet,
    build_export_frame,
)
from .io_oracle import load_oracle_years
from .scoring import REFERENCE_ELO, ScoreWeights, load_league_elos
from .season import _DEMO_WEIGHTS, _LANE_NAMES, build_player_match_scores
from .team_leagues import resolve_home_leagues

logger = logging.getLogger(__name__)

YEARS_DEFAULT = tuple(range(2011, 2026))  # 2011-2013 via reduced Leaguepedia model; 2014-2025 Oracle
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

    career_divisor: float = 7.5      # D: avg career length (yrs) of retired top-100-by-CareerLPS
    # PEAK = "plateau" definition. A season counts as a PEAK YEAR if it is within `peak_band` of
    # the player's best season (>= (1-peak_band)*best). PeakVal = mean(peak years) + a length
    # bonus for each EXTRA peak year:
    #     PeakVal = avg(peak years) + peak_len_bonus * best_season * (k - 1)
    # A one-year peak (Marin) scores exactly its single great season; a wide plateau (Faker)
    # scores its plateau average plus a length reward. The length bonus offsets the fact that
    # averaging in a slightly-lower peak year would otherwise drag the mean down -- so a longer
    # peak is NEVER penalized as long as peak_len_bonus >= peak_band/2 (the worst-case average
    # drop from adding a year at the band edge). Both default safely above that floor.
    peak_band: float = 0.15          # within 15% of the best season counts as a peak year
    peak_len_bonus: float = 0.10     # per extra peak year, as a fraction of the best season
    pace_prior_games: float = 50.0   # empirical-Bayes shrinkage strength (weighted games)
    w_career: float = 1.0
    w_pace: float = 1.0
    w_peak: float = 1.0

# Columns that ACCUMULATE across years (summed).
_SUM_COLS = [
    "games", "wins", "reg_games", "playoff_games", "tourn_games", "n_tourneys",
    "total_score", "base_pts", "contrib_pts", "wbonus_pts",
    "kills_pts", "deaths_pts", "assists_pts", "damage_pts", "fb_pts",
    "reg_pts", "playoff_pts", "tourn_pts", "total_weight",
]
# Counts don't scale with schedule length; every other summed column (the point accumulations)
# is proportional to that year's N_ref, so it gets schedule-normalized -- see
# export_excel._ACCUM_BASE_COLS, which is the point-column list actually rescaled per year.
_COUNT_COLS = ["games", "wins", "reg_games", "playoff_games", "tourn_games", "n_tourneys"]
# Columns averaged across years weighted by that year's games.
_GW_COLS = ["pts_per_game", "contrib_pg", "avg_contrib", "avg_resid", "avg_p_model",
            "sched_strength", "fb_rate", "region_elo"]


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
    Per-year workbooks are written by the caller AFTER schedule normalization is applied."""
    from . import lp_reduced

    records: list[dict] = []
    all_tourn: list[str] = []
    failed: list[str] = []
    for year in years:
        oracle_ok = 2014 <= year <= 2025
        lp_ok = year in lp_reduced.GAP_LEAGUES
        # When both sources exist, resolve home leagues across their UNION so an Eastern team
        # whose only Oracle games are Worlds (home would be 'WLDs' -> games drop) inherits its
        # real domestic home from Leaguepedia and its international games are scored.
        home = _global_home_leagues(year) if (oracle_ok and lp_ok) else None
        srcs: list[tuple[str, pd.DataFrame]] = []
        try:
            if oracle_ok:
                logger.info(f"[career] {year} [oracle]: building (force_recompute={force_recompute}) ...")
                srcs.append(("oracle", build_player_match_scores(
                    year, weights=weights, force_recompute=force_recompute, home_leagues=home)))
            if lp_ok:
                logger.info(f"[career] {year} [lp]: building reduced model ...")
                srcs.append(("lp", lp_reduced.build_match_scores(
                    year, weights=weights, home_leagues=home, force_recompute=force_recompute)))
            if not srcs:
                continue
            combined = srcs[0][1] if len(srcs) == 1 else _combine_matches(
                [f for _, f in srcs], year, weights)
            frame, tc, meta = build_export_frame(
                year, weights, min_games, intl_weight, matches=combined)
        except Exception as e:  # a bad/incomplete year shouldn't kill the whole run
            logger.warning(f"[career] {year}: SKIPPED ({type(e).__name__}: {e})")
            failed.append(str(year))
            continue

        records.append({"year": year, "source": "+".join(s for s, _ in srcs),
                        "frame": frame, "tc": tc, "meta": meta,
                        "n_ref": float(meta.get("n_ref", 0.0) or 0.0)})
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
    of dropping -- without needing to ingest those minor regions' domestic scoreboards."""
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


def _combine_matches(frames: list[pd.DataFrame], year: int,
                     weights: ScoreWeights) -> pd.DataFrame:
    """Concatenate per-source match frames for a year and re-resolve home leagues + baseline
    across the union, so a team whose only games in one source were an international event
    (home would resolve to that event) inherits its real domestic home from the other source
    and keeps those international games. Sources cover disjoint leagues, so no game overlaps."""
    m = pd.concat(frames, ignore_index=True)
    elos = load_league_elos(year)
    rated = set(elos)
    # Home league = modal own_league among RATED DOMESTIC games (ignores WLDs/MSI etc.).
    dom = m[m["own_league"].isin(rated)]
    home = (dom.groupby("teamname")["own_league"]
            .agg(lambda s: s.mode().iat[0] if not s.mode().empty else None))
    m["own_league"] = m["teamname"].map(home).fillna(m["own_league"])
    m["opp_league"] = m["opp_teamname"].map(home).fillna(m["opp_league"])
    m["is_international"] = (m["own_league"].notna() & m["opp_league"].notna()
                            & (m["own_league"] != m["opp_league"]))
    peak = max(elos.values()) if elos else REFERENCE_ELO   # baseline vs the year's peak region
    opp_elo = m["opp_league"].map(elos)
    m["baseline"] = 1.0 / (1.0 + 10 ** ((peak - opp_elo) / 400.0))
    m["baseline_term"] = weights.alpha * m["baseline"]
    m["score"] = m["baseline_term"] + m["contribution_term"] + m["win_bonus"]
    return m.dropna(subset=["baseline"]).reset_index(drop=True)


def _stack(records: list[dict], all_tourn: list[str]) -> pd.DataFrame:
    """Concatenate all frames into one long frame (row = player-year-source), carrying the
    year and that frame's n_ref (for per-frame schedule normalization)."""
    parts = []
    for rec in records:
        d = rec["frame"].copy()
        if "playername" not in d.columns:      # index holds the player name
            d = d.reset_index().rename(columns={d.columns[0]: "playername"})
        d["year"] = rec["year"]
        d["_nref"] = rec["n_ref"]
        for c in all_tourn:                       # ensure every tournament col exists
            if c not in d.columns:
                d[c] = 0.0
        parts.append(d)
    allyears = pd.concat(parts, ignore_index=True)
    allyears[all_tourn] = allyears[all_tourn].fillna(0.0)
    # Canonicalize player names case-insensitively (Leaguepedia "MaRin" vs Oracle "Marin",
    # etc.) so the same player merges across sources. Display = most common original spelling.
    key = allyears["playername"].astype(str).str.lower()
    canon = (allyears.assign(_k=key).groupby("_k")["playername"]
             .agg(lambda s: s.mode().iat[0] if not s.mode().empty else s.iloc[0]))
    allyears["playername"] = key.map(canon)
    return allyears


def _aggregate(allyears: pd.DataFrame, keys: list[str], all_tourn: list[str],
               years: tuple[int, ...]) -> pd.DataFrame:
    """Aggregate the stacked frame to career totals over `keys` (['playername'] or
    ['playername','position'])."""
    sum_cols = _SUM_COLS + all_tourn
    g = allyears.groupby(keys, sort=False)

    out = g[sum_cols].sum()

    # Games-weighted means (Σ x*games / Σ games).
    gsum = out["games"].replace(0, 1)
    wsum = allyears.assign(**{f"_w_{c}": allyears[c] * allyears["games"] for c in _GW_COLS})
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
    peak = (allyears.sort_values("total_score").drop_duplicates(keys, keep="last")
            .set_index(keys)[["year", "total_score"]]
            .rename(columns={"year": "peak_year", "total_score": "peak_lps"}))
    out = out.join(peak)
    out["lps_per_year"] = out["total_score"] / out["n_years"].replace(0, 1)

    # Primary team / league / position = the value from the season with the most games.
    prim_cols = [c for c in ["team", "league", "position"] if c not in keys]
    prim = (allyears.sort_values("games").drop_duplicates(keys, keep="last")
            .set_index(keys)[prim_cols])
    for c in prim_cols:
        out[c] = prim[c]

    # Per-year LPS trajectory (one column per year).
    pivot = (allyears.pivot_table(index=keys, columns="year", values="total_score",
                                  aggfunc="sum", fill_value=0.0))
    pivot.columns = [f"y{int(c)}" for c in pivot.columns]
    out = out.join(pivot)
    for y in years:
        if f"y{y}" not in out.columns:
            out[f"y{y}"] = 0.0

    return out.reset_index()


def _add_clr(career: pd.DataFrame, years: tuple[int, ...], cfg: CLRConfig) -> pd.DataFrame:
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
    Also exposes peak_years (count) and peak_band_avg (plateau mean) as standalone columns."""
    best = career["peak_lps"].to_numpy(dtype=float)       # absolute peak season (== PeakLPS)
    thr = best * (1.0 - cfg.peak_band)                     # peak-year threshold, per player
    ycols = [f"y{y}" for y in years if f"y{y}" in career.columns]
    yv = career[ycols].to_numpy(dtype=float) if ycols else np.zeros((len(career), 0))
    k = np.ones(len(career))           # number of peak years (>= 1: the best season always counts)
    band_avg = best.copy()             # mean of the peak years (defaults to the best season)
    for i, row in enumerate(yv):
        peak_yrs = row[row >= thr[i]]                      # seasons within the band of the peak
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

    career["clr"] = (cfg.w_career * career["career_value"]
                     + cfg.w_pace * career["pace_value"]
                     + cfg.w_peak * career["peak_value"])
    return career


_BONUS_COLS = ["intl_bonus", "title_bonus", "award_bonus"]


def _add_bonuses(career_all: pd.DataFrame, career_lane: pd.DataFrame,
                 allyears: pd.DataFrame, cfg: BonusConfig) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Score resume bonuses from the per-(player,year) roster and fold them into CLR. Adds
    intl_bonus/title_bonus/award_bonus + resume_bonus columns and updates `clr` by
    cfg.w_bonus * resume_bonus. Bonuses are aggregated to per-player (Overview) and
    per-player-lane (lane sheets); a title credits the lane the player played that year."""
    roster = allyears[["playername", "year", "team", "league", "position"]].copy()
    bonus_long = score_bonuses(roster, cfg)
    b_all = (bonus_long.groupby("playername")[_BONUS_COLS].sum().reset_index()
             if len(bonus_long) else pd.DataFrame(columns=["playername", *_BONUS_COLS]))
    b_lane = (bonus_long.groupby(["playername", "position"])[_BONUS_COLS].sum().reset_index()
              if len(bonus_long) else
              pd.DataFrame(columns=["playername", "position", *_BONUS_COLS]))
    career_all = career_all.merge(b_all, on="playername", how="left")
    career_lane = career_lane.merge(b_lane, on=["playername", "position"], how="left")
    out = []
    for frame in (career_all, career_lane):
        for c in _BONUS_COLS:
            if c not in frame.columns:
                frame[c] = 0.0
        frame[_BONUS_COLS] = frame[_BONUS_COLS].fillna(0.0)
        frame["resume_bonus"] = frame[_BONUS_COLS].sum(axis=1)
        frame["clr"] = frame["clr"] + cfg.w_bonus * frame["resume_bonus"]
        out.append(frame)
    return out[0], out[1]


_HIGH_NOON_YEARS = 3   # High Noon averages a player's N best-ranked seasons (companion metric)


def _high_noon(allyears: pd.DataFrame,
               n_years: int = _HIGH_NOON_YEARS) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Compute 'High Noon' peer-rank companion columns from the stacked per-(player,year) frame.

    Each season, rated players are ranked by that year's schedule-normalized LPS (rank 1 = best),
    both GLOBALLY (all lanes together) and WITHIN LANE. For each player we record:
      - the BEST single-season rank (their highest peer standing ever), and
      - HN3 = the average peer rank over their N best-ranked seasons (default 3), plus the years
        that make it up -- i.e. how dominant they were across their strongest seasons.
    Best seasons are taken WHEREVER they fall (not a consecutive window), matching how PeakVal is
    defined, so a gap year never breaks the metric. Lower is better. COMPANION only -- NOT summed
    into CLR (peak already lives in the score). Returns (by_player, by_player_position) frames."""
    df = allyears[["playername", "position", "year", "total_score"]].copy()
    df = df[df["total_score"].notna() & df["year"].notna()]
    df["year"] = df["year"].astype(int)
    df["rank_global"] = df.groupby("year")["total_score"].rank(ascending=False, method="min")
    df["rank_lane"] = (df.groupby(["year", "position"])["total_score"]
                       .rank(ascending=False, method="min"))

    def _stats(year_rank: dict) -> tuple[float, float, str]:
        by_rank = sorted(year_rank.items(), key=lambda kv: kv[1])   # best (lowest) rank first
        best = float(by_rank[0][1])
        top = by_rank[:n_years]
        hn = sum(r for _, r in top) / len(top)
        yrs = ",".join(str(y) for y in sorted(y for y, _ in top))   # the High Noon seasons
        return best, hn, yrs

    def _rows(keys: list[str]) -> pd.DataFrame:
        out = []
        for key, sub in df.groupby(keys, sort=False):
            gb, g3, gyr = _stats(dict(zip(sub["year"], sub["rank_global"])))
            lb, l3, lyr = _stats(dict(zip(sub["year"], sub["rank_lane"])))
            rec = dict(zip(keys, key if isinstance(key, tuple) else (key,)))
            rec.update(hn_lane_best=lb, hn_lane=l3, hn_lane_yrs=lyr,
                       hn_global_best=gb, hn_global=g3, hn_global_yrs=gyr)
            out.append(rec)
        return pd.DataFrame(out)

    return _rows(["playername"]), _rows(["playername", "position"])


def _career_layout(all_tourn: list[str], years: tuple[int, ...],
                    include_lane: bool) -> list[tuple]:
    """(col, header, fmt, width) layout for a career sheet."""
    lay: list[tuple] = [
        ("rank", "Rank", _INT, 6),
        ("playername", "Player", None, 16),
        ("team", "Team", None, 18),
        ("league", "League", None, 8),
    ]
    if include_lane:
        lay.append(("position", "Lane", None, 8))
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
        ("  intl_weight", meta["intl_weight"]),
        ("  min games / year", meta["min_games"]),
        ("", ""),
        ("Method", "Each year is scored independently (models retrained per year for meta"),
        ("", "changes), then LPS and every breakdown are SUMMED across years per player."),
        ("", "CareerLPS rewards both peak and longevity. Per-year columns (yYYYY) show the"),
        ("", "trajectory; PeakYr/PeakLPS mark the best single season."),
        ("", ""),
        ("Schedule normalization", f"Point totals rescaled per year by REF/N_ref "
         f"(REF={meta.get('ref_nref', 0):.1f} matches) so schedule length doesn't bias the"),
        ("", "career sum across eras; the Elo/baseline strength signal is kept."),
    ]
    cfg = meta.get("clr")
    if cfg is not None:
        rows += [
            ("", ""),
            ("CLR (Career Legend Rating) -- PRIMARY RANKING", ""),
            ("", "Holistic PPS/JAWS-style composite (see docs/holistic-lps-plan.md). Blends"),
            ("", "three length-decoupled views of a career onto a common one-season scale:"),
            ("  CLR", "w_career*CareerVal + w_pace*PaceVal + w_peak*PeakVal"),
            ("  CareerVal", f"CareerLPS / D  (bulk; D = typical career length = {cfg.career_divisor})"),
            ("  PaceVal", f"per-active-year LPS, empirical-Bayes shrunk toward the cohort mean "
             f"(prior = {cfg.pace_prior_games:g} weighted games) -- rate reward, length-neutral"),
            ("  PeakVal", f"mean(peak years) + {cfg.peak_len_bonus:g}*PeakLPS*(PeakYrs-1); a "
             f"season is a peak year if >= {1 - cfg.peak_band:g}*PeakLPS (within "
             f"{cfg.peak_band:.0%} of the best). Longer peaks never penalized."),
            ("  + Resume", "w_bonus * (Intl + Titles + Awards) -- see Resume bonuses below"),
            ("  Weights (w_career, w_pace, w_peak, w_bonus)",
             f"{cfg.w_career:g}, {cfg.w_pace:g}, {cfg.w_peak:g}, "
             f"{meta.get('w_bonus', 1.0):g}  (provisional -- pending calibration)"),
            ("", "CareerLPS is kept as a component column; sheets now sort by CLR."),
            ("", ""),
            ("Resume bonuses (Intl / Titles / Awards)", ""),
            ("  Intl", "Worlds/MSI placement points (champion..play-in), flat by event+round."),
            ("  Titles", "Domestic split-playoff titles/finals, each scaled by that region's Elo"),
            ("", "strength (an LCK/LPL title outweighs a weak-region one)."),
            ("  Awards", "Hand-curated regional MVP / All-Pro / Finals MVP (info/player_awards.csv)."),
            ("", "Credited to the lane the player played that year. Source: info/achievements.csv."),
            ("", ""),
            ("High Noon (peer rank) -- COMPANION, not in CLR", ""),
            ("", "Each season, rated players are ranked by that year's LPS (1 = best), globally"),
            ("", "and within lane. BestRkLane/BestRkGlob = best single-season rank; HN3Lane/"),
            ("", "HN3Glob = average rank over the player's 3 best-ranked seasons (listed in the"),
            ("", "HN3*Yrs columns), taken wherever they fall (not a consecutive window, matching"),
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


def write_career_workbook(out: Path, career_all: pd.DataFrame,
                          career_lane: pd.DataFrame, all_tourn: list[str],
                          years: tuple[int, ...], meta: dict) -> Path:
    lay_all = _career_layout(all_tourn, years, include_lane=True)     # Overview shows Lane too
    lay_lane = _career_layout(all_tourn, years, include_lane=False)
    with pd.ExcelWriter(out, engine="openpyxl") as writer:
        _write_about(writer, meta)

        ov = career_all.sort_values("clr", ascending=False).copy()
        ov.insert(0, "rank", range(1, len(ov) + 1))
        _write_sheet(writer, "Overview", ov, lay_all)

        for lane in ROLES:
            sub = career_lane[career_lane["position"] == lane].sort_values(
                "clr", ascending=False).copy()
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
) -> Path:
    weights = weights or _DEMO_WEIGHTS
    clr_cfg = clr_cfg or CLRConfig()
    bonus_cfg = bonus_cfg or BonusConfig()
    out = Path(out) if out is not None else PROJECT_ROOT / f"player_ratings_career_{years[0]}_{years[-1]}.xlsx"

    # Build the cross-year lane-normalization tables ONCE, up front, from ALL years pooled
    # (independent of the --years subset being written) so every per-year frame is remapped
    # against the same global reference. Must precede the year loop: it force-rebuilds each
    # year's raw contributions when force_recompute, so the pooled distributions are current.
    from .season import build_lane_remap
    logger.info("[career] building cross-year lane-normalization tables ...")
    build_lane_remap(force_recompute=force_recompute)

    # Per-year frames reuse the raw caches the prebuild just refreshed (gap-year '_merged'
    # variants build on demand), so the loop itself doesn't need to force a rebuild.
    records, all_tourn = run_year_frames(
        years, weights, min_games, intl_weight, False)
    if not records:
        raise RuntimeError("no years produced ratings; nothing to aggregate")
    got = tuple(sorted({r["year"] for r in records}))     # years that actually succeeded

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
            logger.info(f"[career] {rec['year']} [{rec['source']}]: wrote {out_y.name}  "
                        f"({len(rec['frame'])} players, x{rec['mult']:.3f})")

    allyears = _stack(records, all_tourn)   # frames already schedule-normalized
    career_all = _add_clr(_aggregate(allyears, ["playername"], all_tourn, got), got, clr_cfg)
    career_lane = _add_clr(
        _aggregate(allyears, ["playername", "position"], all_tourn, got), got, clr_cfg)

    # High Noon peer-rank companion columns (global + per-lane); NOT summed into CLR.
    hn_all, hn_lane = _high_noon(allyears)
    career_all = career_all.merge(hn_all, on="playername", how="left")
    career_lane = career_lane.merge(hn_lane, on=["playername", "position"], how="left")

    # Resume bonuses (Phase 2): Worlds/MSI placements + domestic titles + awards -> folded into
    # CLR (IntlBonus + TitleBonus + AwardBonus, weighted by bonus_cfg.w_bonus), attributed to the
    # lane the player played that year. See achievements.py / info/achievements.csv.
    career_all, career_lane = _add_bonuses(career_all, career_lane, allyears, bonus_cfg)

    meta = {"years": got, "alpha": weights.alpha, "lam": weights.lam, "beta": weights.beta,
            "intl_weight": intl_weight, "min_games": min_games, "ref_nref": ref_nref,
            "clr": clr_cfg, "w_bonus": bonus_cfg.w_bonus}
    write_career_workbook(out, career_all, career_lane, all_tourn, got, meta)
    logger.info(f"[career] wrote {out.name}  ({len(career_all)} players, {len(got)} years)")
    return out


def _parse_years(s: str) -> tuple[int, ...]:
    if "-" in s:
        a, b = s.split("-"); return tuple(range(int(a), int(b) + 1))
    return tuple(int(x) for x in s.split(","))


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(description="Build per-year + cumulative career LPS workbooks.")
    ap.add_argument("--years", type=str, default="2011-2025")
    ap.add_argument("--min-games", type=int, default=3)
    ap.add_argument("--intl-weight", type=float, default=2.0)
    ap.add_argument("--alpha", type=float, default=_DEMO_WEIGHTS.alpha)
    ap.add_argument("--lam", type=float, default=_DEMO_WEIGHTS.lam)
    ap.add_argument("--beta", type=float, default=_DEMO_WEIGHTS.beta)
    ap.add_argument("--no-recompute", action="store_true", help="reuse cached per-year models")
    ap.add_argument("--no-yearly", action="store_true", help="skip per-year workbooks")
    args = ap.parse_args()

    weights = ScoreWeights(alpha=args.alpha, lam=args.lam, beta=args.beta)
    build_and_write(
        years=_parse_years(args.years), weights=weights, min_games=args.min_games,
        intl_weight=args.intl_weight, force_recompute=not args.no_recompute,
        write_yearly=not args.no_yearly,
    )


if __name__ == "__main__":
    main()
