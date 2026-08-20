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

Cross-year note: each year's LPS is normalized to that year's own N_ref (matches) and Elos,
so an LPS point is roughly comparable across years; summing gives a career/longevity metric
(more seasons + higher peaks both help). Recent years offer more international events, so
modern players have marginally more to accumulate -- an intended "more opportunity" effect.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import logging
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

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

YEARS_DEFAULT = tuple(range(2013, 2026))  # 2013 via reduced Leaguepedia model; 2014-2025 Oracle

# Columns that ACCUMULATE across years (summed).
_SUM_COLS = [
    "games", "wins", "reg_games", "playoff_games", "tourn_games", "n_tourneys",
    "total_score", "base_pts", "contrib_pts", "wbonus_pts",
    "kills_pts", "deaths_pts", "assists_pts", "damage_pts", "fb_pts",
    "reg_pts", "playoff_pts", "tourn_pts", "total_weight",
]
# Counts don't scale with schedule length; every other summed column (the point
# accumulations) is proportional to that year's N_ref, so it gets schedule-normalized.
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
    write_yearly: bool,
) -> tuple[list[dict], list[str]]:
    """Build (and optionally write) one enriched frame per year. Where both sources exist
    (Oracle 2014+ and the reduced Leaguepedia model for gap years 2013-2015) their per-match
    frames are MERGED and home leagues re-resolved across the union, so e.g. an Eastern team
    whose only Oracle games are Worlds (home would wrongly resolve to 'WLDs') picks up its
    real domestic home from Leaguepedia and its Worlds games are credited. Returns a list of
    {year, source, frame, n_ref} records + the union of per-tournament columns."""
    from .export_excel import write_workbook
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
                    year, weights=weights, home_leagues=home)))
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
                        "frame": frame, "n_ref": float(meta.get("n_ref", 0.0) or 0.0)})
        for c in tc:
            if c not in all_tourn:
                all_tourn.append(c)
        if write_yearly:
            out = PROJECT_ROOT / f"player_ratings_{year}.xlsx"
            write_workbook(out, frame, tc, meta)
            logger.info(f"[career] {year} [{records[-1]['source']}]: wrote {out.name}  "
                        f"({len(frame)} players)")
    if failed:
        logger.warning(f"[career] skipped: {failed}")
    return records, all_tourn


def _global_home_leagues(year: int) -> Optional[dict]:
    """Resolve each team's home league across BOTH Oracle and Leaguepedia raw data for a
    year, preferring rated leagues. Lets a team seen only at an international event in one
    source pick up its real domestic home from the other."""
    from . import lp_ingest
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
    both = pd.concat(parts, ignore_index=True).dropna(subset=["teamname", "league"])
    return resolve_home_leagues(both, preferred=set(load_league_elos(year)))


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
    opp_elo = m["opp_league"].map(elos)
    m["baseline"] = 1.0 / (1.0 + 10 ** ((REFERENCE_ELO - opp_elo) / 400.0))
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
        ("total_score", "CareerLPS", _PTS, 11),
        ("lps_per_year", "LPS/Yr", _PTS, 8),
        ("peak_year", "PeakYr", _INT, 7),
        ("peak_lps", "PeakLPS", _PTS, 9),
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
    lay_all = _career_layout(all_tourn, years, include_lane=True)   # Overview shows Lane too
    lay_lane = _career_layout(all_tourn, years, include_lane=False)
    with pd.ExcelWriter(out, engine="openpyxl") as writer:
        _write_about(writer, meta)

        ov = career_all.sort_values("total_score", ascending=False).copy()
        ov.insert(0, "rank", range(1, len(ov) + 1))
        _write_sheet(writer, "Overview", ov, lay_all)

        for lane in ROLES:
            sub = career_lane[career_lane["position"] == lane].sort_values(
                "total_score", ascending=False).copy()
            sub.insert(0, "rank", range(1, len(sub) + 1))
            _write_sheet(writer, _LANE_NAMES[lane], sub, lay_lane)

        _write_glossary(writer)
    return out


def build_and_write(
    years: tuple[int, ...] = YEARS_DEFAULT,
    weights: Optional[ScoreWeights] = None,
    min_games: int = 15,
    intl_weight: float = 2.0,
    force_recompute: bool = True,
    write_yearly: bool = True,
    out: Optional[Path] = None,
) -> Path:
    weights = weights or _DEMO_WEIGHTS
    out = Path(out) if out is not None else PROJECT_ROOT / f"player_ratings_career_{years[0]}_{years[-1]}.xlsx"

    records, all_tourn = run_year_frames(
        years, weights, min_games, intl_weight, force_recompute, write_yearly)
    if not records:
        raise RuntimeError("no years produced ratings; nothing to aggregate")
    got = tuple(sorted({r["year"] for r in records}))     # years that actually succeeded
    allyears = _stack(records, all_tourn)

    # SCHEDULE-LENGTH NORMALIZATION: point accumulations scale with each frame's N_ref
    # (matches/player), which varies ~1.5x. Rescale every frame's point columns by REF/N_ref
    # so a full season is worth the same regardless of schedule length, while keeping the
    # Elo/baseline signal (stronger modern leagues still score higher per game). Applied
    # per-frame so Oracle and reduced-Leaguepedia frames are each normalized to their own
    # schedule.
    nrefs = [r["n_ref"] for r in records if r["n_ref"]]
    ref_nref = float(np.mean(nrefs)) if nrefs else 1.0
    mult = np.where(allyears["_nref"].values > 0, ref_nref / allyears["_nref"].values, 1.0)
    accum = [c for c in _SUM_COLS if c not in _COUNT_COLS] + all_tourn
    allyears[accum] = allyears[accum].mul(mult, axis=0)

    career_all = _aggregate(allyears, ["playername"], all_tourn, got)
    career_lane = _aggregate(allyears, ["playername", "position"], all_tourn, got)

    meta = {"years": got, "alpha": weights.alpha, "lam": weights.lam, "beta": weights.beta,
            "intl_weight": intl_weight, "min_games": min_games, "ref_nref": ref_nref}
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
    ap.add_argument("--years", type=str, default="2013-2025")
    ap.add_argument("--min-games", type=int, default=15)
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
