"""
Excel export of the season player ratings.

Runs the full LPS pipeline for a year and writes a formatted workbook:

    - one sheet PER LANE (TOP/JUNGLE/MID/BOT/SUPPORT), every player ranked with the full
      score breakdown (phase, score-component, contribution-source, per-tournament) plus
      per-game rate/quality stats,
    - an "Overview" sheet with every player across all lanes ranked together,
    - "About" (run parameters + tournament weights) and "Glossary" (column definitions).

Run:
    poetry run python -m lps.export_excel                 # 2024 -> player_ratings_2024.xlsx
    poetry run python -m lps.export_excel --year 2024 --out board.xlsx
    poetry run python -m lps.export_excel --min-games 20 --intl-weight 2.0

Everything downstream of _match_features is cached, so re-exporting with different weights
is fast (no retraining).
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
from .scoring import REFERENCE_ELO, ScoreWeights, expected_score, load_league_elos
from .season import (
    _DEMO_WEIGHTS,
    _LANE_NAMES,
    _viewership_weights,
    build_player_match_scores,
    build_player_ratings,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Column layout: (source_col, friendly_header, excel_number_format, width, group)
# `group` is only used to decide a light header fill so related columns read together.
# ---------------------------------------------------------------------------
_PCT = "0.0%"
_PTS = "0.00"
_INT = "0"
_SIGNED = "+0.000;-0.000;0.000"

# Point-accumulation columns that scale with schedule length -- these get schedule-normalized
# (multiplied by REF/N_ref). Counts and per-game ratios are deliberately excluded: rescaling
# total_score and total_weight together leaves the weighted per-game value unchanged.
_ACCUM_BASE_COLS = [
    "total_score", "base_pts", "contrib_pts", "wbonus_pts",
    "kills_pts", "deaths_pts", "assists_pts", "damage_pts", "fb_pts",
    "reg_pts", "playoff_pts", "tourn_pts", "total_weight",
]


def apply_schedule_norm(frame: pd.DataFrame, mult: float,
                        tourn_cols: list[str]) -> pd.DataFrame:
    """Rescale a year's point-accumulation columns by `mult` (= REF/N_ref) so a full season is
    worth the same regardless of schedule length. Returns a copy; counts and per-game ratios
    are untouched (scaling total_score and total_weight together leaves per-game values fixed)."""
    if abs(mult - 1.0) < 1e-12:
        return frame
    cols = [c for c in _ACCUM_BASE_COLS + list(tourn_cols) if c in frame.columns]
    frame = frame.copy()
    frame[cols] = frame[cols] * mult
    return frame

_COLUMNS: list[tuple[str, str, str, int, str]] = [
    ("rank",          "Rank",        _INT, 6,  "id"),
    ("playername",    "Player",      None, 16, "id"),
    ("team",          "Team",        None, 18, "id"),
    ("league",        "League",      None, 8,  "id"),
    ("region_elo",    "RegElo",      _INT, 8,  "id"),
    # volume
    ("games",         "Games",       _INT, 7,  "vol"),
    ("wins",          "Wins",        _INT, 6,  "vol"),
    ("win_rate",      "Win%",        _PCT, 7,  "vol"),
    ("reg_games",     "RegG",        _INT, 6,  "vol"),
    ("playoff_games", "PlfG",        _INT, 6,  "vol"),
    ("tourn_games",   "TrnG",        _INT, 6,  "vol"),
    ("n_tourneys",    "#Trn",        _INT, 6,  "vol"),
    # headline score
    ("total_score",   "LPS",         _PTS, 9,  "score"),
    ("pts_per_game",  "LPS/Gm",      _PTS, 9,  "score"),
    ("pts_per_game_w","LPS/Gm·wt",   _PTS, 10, "score"),
    ("clutch_gap",    "Clutch",      _SIGNED, 9, "score"),
    ("contrib_pg",    "Con/Gm",      _PTS, 9,  "score"),
    ("contrib_pg_w",  "Con/Gm·wt",   _PTS, 10, "score"),
    # by phase
    ("reg_pts",       "Regular",     _PTS, 9,  "phase"),
    ("playoff_pts",   "Playoffs",    _PTS, 9,  "phase"),
    ("tourn_pts",     "Tourneys",    _PTS, 9,  "phase"),
    # by score component
    ("base_pts",      "Baseline",    _PTS, 9,  "comp"),
    ("contrib_pts",   "Contribution",_PTS, 12, "comp"),
    ("wbonus_pts",    "WinBonus",    _PTS, 9,  "comp"),
    # contribution split by source (sum to Contribution)
    ("kills_pts",     "Kills",       _PTS, 8,  "src"),
    ("deaths_pts",    "Deaths",      _PTS, 8,  "src"),
    ("assists_pts",   "Assists",     _PTS, 8,  "src"),
    ("damage_pts",    "Damage",      _PTS, 8,  "src"),
    ("fb_pts",        "FirstBlood",  _PTS, 10, "src"),
    # per-tournament (filled dynamically from tournament_cols)
    # rate / quality stats
    ("avg_contrib",   "AvgContrib",  _SIGNED, 10, "rate"),
    ("avg_resid",     "Intangibles", _SIGNED, 12, "rate"),
    ("avg_p_model",   "AvgWinProb",  _PCT, 10, "rate"),
    ("sched_strength","SoS",         _PCT, 8,  "rate"),
    ("fb_rate",       "FB%",         _PCT, 7,  "rate"),
    ("best_game",     "BestGame",    _SIGNED, 10, "rate"),
    ("worst_game",    "WorstGame",   _SIGNED, 10, "rate"),
]

# Per-tournament columns get their own format/width; header comes from the label.
_TOURN_FMT, _TOURN_WIDTH = _PTS, 8

_GLOSSARY: list[tuple[str, str]] = [
    ("Rank", "Rank within the lane by CLR on the career workbook (by LPS on per-season sheets); "
             "Overview sheets rank across all lanes."),
    ("CLR", "Career Legend Rating (career workbook only): the holistic, PPS/JAWS-inspired "
            "primary ranking = w_career*CareerVal + w_pace*PaceVal + w_peak*PeakVal. Blends "
            "career bulk, per-year pace, and peak onto one comparable scale so longevity, rate, "
            "and dominance all count (resume bonuses for titles/awards are added later). See the "
            "About sheet for the weights and divisor."),
    ("CareerVal", "CLR bulk term = CareerLPS / D, where D is a typical career length (yrs). "
                  "Careers longer than D keep a proportional bulk edge; shorter ones scale down."),
    ("PaceVal", "CLR rate term = per-active-year LPS, empirical-Bayes shrunk toward the cohort "
                "mean by weighted games so brilliant short careers score well but tiny, noisy "
                "samples can't top the board. Length-neutral counterweight to CareerVal."),
    ("PeakVal", "CLR peak term = best-season peak. Default 'sustain' = the single best season "
                "(PeakLPS) PLUS a bonus for additional strong seasons (mean of seasons 2..N, "
                "zero-padded). A sharp one-year peak keeps its full single-season height (never "
                "diluted); a multi-year prime rises above it -- longer peaks rewarded, shorter "
                "ones relatively punished."),
    ("PeakTop3", "Mean of a player's 3 best schedule-normalized seasons (over active seasons "
                 "only) -- the sustained-excellence view of peak; PeakLPS is the single best."),
    ("LPS", "League Performance Score: total_score = Baseline + Contribution + WinBonus, "
            "accumulated across regular season, playoffs and tournaments (more games help). "
            "Schedule-length normalized (see About) so a full season is worth the same across "
            "years and these per-year totals sum to CareerLPS."),
    ("LPS/Gm", "Pure mean per-game score (contribution + win-bonus + win-gated baseline), "
               "every game weighted equally, before the accumulation weighting -- schedule-"
               "length invariant and consistent with CareerLPS (baseline counts only on "
               "series wins)."),
    ("LPS/Gm·wt", "WEIGHTED mean per-game score: total_score / total accumulation weight. "
               "Weights each game by its stakes (playoff/tournament games count more) but "
               "divides by the total weight, so it stays comparable across leagues. Above the "
               "pure mean => the player raised their game in higher-stakes matches."),
    ("Con/Gm", "Contribution component of LPS per game (pure mean, LPS scale) -- how much "
               "per-game value comes from win-prob contribution. Schedule-length invariant."),
    ("Con/Gm·wt", "Weighted contribution per game = contribution points / total accumulation "
               "weight (same match scaling as LPS/Gm.wt). Above Con/Gm => the player's "
               "contribution was stronger in higher-stakes games."),
    ("Clutch", "INDIVIDUAL clutch = LPS/Gm.wt - LPS/Gm. How much the player's OWN per-game "
               "value rose (or fell) in higher-stakes games. Positive = stepped up in "
               "playoffs/tournaments; negative = faded. (Distinct from Intangibles, which is "
               "team-level and identical for all 5 teammates.)"),
    ("Regular / Playoffs / Tourneys", "LPS earned in each phase. Regular & playoffs are "
        "length-normalized per region (a full run ~ one unit); tournaments are weighted by "
        "viewership and normalized so a full winning run = the tournament's weight."),
    ("Baseline", "Points for the strength of the OPPONENT's league (cross-league parity term)."),
    ("Contribution", "Win-probability the player added vs an expected player at their "
                     "position (leave-one-out on Model 2), summed over games. Quantile-"
                     "normalized PER LANE across ALL years (each lane's per-game distribution "
                     "remapped onto a common reference), so the Nth-percentile game -- and the "
                     "best-ever season -- is worth the same in every role. This removes the "
                     "box-score bias that under-measures supports/junglers (making cross-lane "
                     "and same-team comparisons fair) while preserving real within-year "
                     "differences between lanes."),
    ("WinBonus", "Credit for actually winning vs the model's expectation: beta*(result - p_model). "
                 "Positive = won games the model rated as losses (clutch); negative = choked."),
    ("Kills/Deaths/Assists/Damage/FirstBlood", "Contribution split by stat source -- these "
        "sum to Contribution. First blood is credited to the FB getter (+) / victim (-)."),
    ("AvgContrib", "Mean per-game net win-probability contribution (after per-lane "
                   "normalization; comparable across roles)."),
    ("Intangibles", "TEAM-level: mean per-game (result - p_model), i.e. how much the team wins "
                 "ABOVE what its box score (KDA/damage/first blood) predicts -- macro, "
                 "shotcalling, closing games, doing more with less. Identical for all 5 "
                 "teammates (not individual)."),
    ("AvgWinProb", "Mean model win probability for the player's team-games (team strength)."),
    ("SoS", "Strength of schedule: mean opponent-league baseline faced (higher = tougher)."),
    ("FB%", "Share of games the player got first blood or was the first-blood victim."),
    ("BestGame / WorstGame", "Player's single-game best / worst net contribution (win-prob)."),
    ("#Trn", "Distinct tournaments the player appeared in."),
    ("RegElo", "The player's home-region strength: that league's ending Elo for the year "
               "(see the Regions sheet). Higher = stronger region."),
    ("<Tournament>", "LPS earned at that specific tournament (WLDs=Worlds, MSI, EWC=Esports "
                     "World Cup, KeSPA/DCup=domestic cups). These sum to Tourneys."),
]


def build_export_frame(
    year: int,
    weights: ScoreWeights,
    min_games: int,
    intl_weight: float,
    force_recompute: bool = False,
    matches: Optional[pd.DataFrame] = None,
) -> tuple[pd.DataFrame, list[str], dict]:
    """
    Full per-player ratings enriched with per-game rate/quality stats.

    Returns (frame, tournament_cols, meta) where frame has one row per player (all lanes),
    tournament_cols is the ordered list of per-tournament point columns, and meta carries
    run parameters for the About sheet. force_recompute rebuilds that year's model cache.
    `matches` injects a pre-scored per-(player,match) frame (e.g. the reduced Leaguepedia
    model, lp_reduced) instead of building from Oracle.
    """
    if matches is None:
        matches = build_player_match_scores(year, weights=weights, force_recompute=force_recompute)
    ratings = build_player_ratings(
        year, weights=weights, matches=matches, min_games=min_games, intl_weight=intl_weight,
    )
    tourn_cols = ratings.attrs.get("tournament_cols", [])

    # Per-player rate/quality stats from the per-match frame.
    matches = matches.copy()
    matches["_resid"] = matches["result"] - matches["p_model"]
    # Win-gate the baseline in the per-game score (baseline only on SERIES wins), matching how
    # the accumulation awards it, so LPS/Gm is consistent with CareerLPS. Series = same day +
    # event + team pair; a series is won if the player's mean game result > 0.5.
    _day = pd.to_datetime(matches["date"]).dt.date.astype(str)
    _a, _b = matches["teamname"].astype(str), matches["opp_teamname"].astype(str)
    _pair = np.where(_a.values < _b.values, _a + "|" + _b, _b + "|" + _a)
    matches["_sid"] = _day + "@" + matches["game_label"].astype(str) + "@" + _pair
    _swon = (matches.groupby(["playername", "_sid"])["result"].transform("mean") > 0.5).astype(float)
    matches["_gscore"] = (matches["contribution_term"] + matches["win_bonus"]
                          + matches["baseline_term"] * _swon)
    g = matches.groupby("playername")
    extra = pd.DataFrame({
        "wins": g["result"].sum().astype(int),
        # LPS/Game is the mean per-game score with the baseline win-gated (as in CareerLPS),
        # BEFORE the accumulation weighting -- so it's schedule-length invariant (a long-
        # schedule league isn't penalized per game) yet consistent with the cumulative total.
        "pts_per_game": g["_gscore"].mean(),
        # Contribution per game, same treatment as LPS/Gm (on the LPS/point scale, i.e.
        # lam-weighted contribution_term) so you can read how much per-game value is
        # contribution. Pure mean here; weighted variant added after the join.
        "contrib_pg": g["contribution_term"].mean(),
        "avg_contrib": g["net_contribution"].mean(),
        "avg_resid": g["_resid"].mean(),
        "avg_p_model": g["p_model"].mean(),
        "sched_strength": g["baseline"].mean(),
        "best_game": g["net_contribution"].max(),
        "worst_game": g["net_contribution"].min(),
        "fb_rate": g["c_fb"].apply(lambda s: float((s != 0).mean())),
    })
    tourn_only = matches[matches["phase"] == "tournament"]
    extra["n_tourneys"] = tourn_only.groupby("playername")["game_label"].nunique()

    r = ratings.join(extra)
    r["n_tourneys"] = r["n_tourneys"].fillna(0).astype(int)
    # Weighted per-game average: total_score / total accumulation weight. Rewards players who
    # performed better in higher-stakes (higher-weight: playoff/tournament) games, but divides
    # by the total weight so it stays on the same comparable scale as the pure mean.
    r["pts_per_game_w"] = r["total_score"] / r["total_weight"].where(r["total_weight"] > 0, 1.0)
    # Individual "clutch": how much a player's own per-game value shifted UP in higher-stakes
    # (higher-weight: playoff/tournament) games. Positive = raised their game when it mattered.
    r["clutch_gap"] = r["pts_per_game_w"] - r["pts_per_game"]
    # Weighted contribution per game: contrib_pts / total accumulation weight (same match
    # scaling as LPS/Gm.wt, restricted to the contribution component).
    r["contrib_pg_w"] = r["contrib_pts"] / r["total_weight"].where(r["total_weight"] > 0, 1.0)
    # Home-region strength (the year's ending Elo for the player's league).
    elos = load_league_elos(year)
    r["region_elo"] = r["league"].map(elos)
    r = r.reset_index().rename(columns={"index": "playername"})
    if "playername" not in r.columns and "playername" not in r:
        r = r.rename(columns={r.columns[0]: "playername"})

    meta = {
        "year": year,
        "alpha": weights.alpha,
        "lam": weights.lam,
        "beta": weights.beta,
        "min_games": min_games,
        "intl_weight": intl_weight,
        "n_ref": ratings.attrs.get("n_ref", 0.0),
        "tournament_weights": ratings.attrs.get("tournament_weights", {}),
        "elos": elos,
    }
    return r, tourn_cols, meta


def _ordered_columns(tourn_cols: list[str]) -> list[tuple[str, str, Optional[str], int]]:
    """Full (col, header, fmt, width) layout, inserting per-tournament cols before rates."""
    out: list[tuple[str, str, Optional[str], int]] = []
    for col, hdr, fmt, width, group in _COLUMNS:
        if group == "rate" and tourn_cols and not any(o[0] == tourn_cols[0] for o in out):
            for tc in tourn_cols:
                out.append((tc, tc.replace("_pts", ""), _TOURN_FMT, _TOURN_WIDTH))
        out.append((col, hdr, fmt, width))
    # If there were no rate columns after which to insert (defensive), append at the end.
    if tourn_cols and not any(o[0] == tourn_cols[0] for o in out):
        for tc in tourn_cols:
            out.append((tc, tc.replace("_pts", ""), _TOURN_FMT, _TOURN_WIDTH))
    return out


def _write_sheet(writer, sheet_name: str, df: pd.DataFrame,
                 layout: list[tuple[str, str, Optional[str], int]]) -> None:
    """Write one dataframe to a sheet and apply header/format/freeze/filter styling."""
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    cols = [(c, h, f, w) for (c, h, f, w) in layout if c in df.columns]
    out = df[[c for c, _, _, _ in cols]].copy()
    out.columns = [h for _, h, _, _ in cols]
    out.to_excel(writer, sheet_name=sheet_name, index=False, startrow=0)

    ws = writer.sheets[sheet_name]
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill("solid", fgColor="305496")
    center = Alignment(horizontal="center", vertical="center")

    for j, (col, hdr, fmt, width) in enumerate(cols, start=1):
        letter = get_column_letter(j)
        cell = ws.cell(row=1, column=j)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = center
        ws.column_dimensions[letter].width = width
        if fmt is not None:
            for row in range(2, ws.max_row + 1):
                ws.cell(row=row, column=j).number_format = fmt

    ws.freeze_panes = "C2"  # keep header + Rank/Player visible while scrolling
    ws.auto_filter.ref = f"A1:{get_column_letter(len(cols))}{ws.max_row}"


def _write_about(writer, meta: dict) -> None:
    rows = [
        ("LPS player ratings", ""),
        ("Season", meta["year"]),
        ("Generated", _dt.date.today().isoformat()),
        ("", ""),
        ("Weights", ""),
        ("  alpha (baseline)", meta["alpha"]),
        ("  lambda (contribution)", meta["lam"]),
        ("  beta (win bonus)", meta["beta"]),
        ("  intl_weight (tournament phase)", meta["intl_weight"]),
        ("  min games", meta["min_games"]),
        ("  N_ref (per-phase reference MATCHES)", round(float(meta["n_ref"]), 1)),
        ("", ""),
        ("Schedule-length normalization", ""),
    ]
    _mult = float(meta.get("sched_mult", 1.0))
    _ref = meta.get("ref_nref")
    if _ref is not None and abs(_mult - 1.0) > 1e-9:
        rows += [
            ("  REF (cross-year mean N_ref)", round(float(_ref), 1)),
            ("  Scaling factor applied (REF/N_ref)", round(_mult, 4)),
            ("  Effect", "Every point-accumulation column (LPS, phase, component, per-"),
            ("", "tournament) is multiplied by this factor so a full season is worth the"),
            ("", "same regardless of schedule length -- per-year totals sum to CareerLPS."),
        ]
    else:
        rows += [
            ("  Scaling factor applied (REF/N_ref)", 1.0),
            ("  Note", "Single-year export -- NOT cross-year normalized. Run via"),
            ("", "lps.career to get per-season sheets whose totals sum to CareerLPS."),
        ]
    rows += [
        ("", ""),
        ("Tournament weights (sqrt avg viewership, Worlds=1)", ""),
    ]
    for k, v in sorted(meta["tournament_weights"].items(), key=lambda kv: -kv[1]):
        rows.append((f"  {k}", v))
    about = pd.DataFrame(rows, columns=["Field", "Value"])
    about.to_excel(writer, sheet_name="About", index=False)
    ws = writer.sheets["About"]
    ws.column_dimensions["A"].width = 46
    ws.column_dimensions["B"].width = 16
    from openpyxl.styles import Font
    for row in ws.iter_rows(min_row=1, max_row=ws.max_row, min_col=1, max_col=1):
        row[0].font = Font(bold=True)


def _write_regions(writer, meta: dict) -> None:
    """Regional strength: each league's ending Elo and its baseline (win rate vs 1000-Elo)."""
    elos = meta.get("elos", {})
    if not elos:
        return
    _peak = max(elos.values()) if elos else REFERENCE_ELO
    rows = [(lg, elo, expected_score(elo, _peak))
            for lg, elo in sorted(elos.items(), key=lambda kv: -kv[1])]
    reg = pd.DataFrame(rows, columns=["League", "Elo", "Baseline"])
    reg.to_excel(writer, sheet_name="Regions", index=False)
    ws = writer.sheets["Regions"]
    from openpyxl.styles import Alignment, Font, PatternFill
    ws.column_dimensions["A"].width = 10
    ws.column_dimensions["B"].width = 10
    ws.column_dimensions["C"].width = 12
    for j, hdr in enumerate(["League", "Elo", "Baseline"], start=1):
        c = ws.cell(row=1, column=j)
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="305496")
        c.alignment = Alignment(horizontal="center")
    for row in range(2, ws.max_row + 1):
        ws.cell(row=row, column=2).number_format = "0"
        ws.cell(row=row, column=3).number_format = "0.0%"
    ws.freeze_panes = "A2"


def _write_glossary(writer) -> None:
    gl = pd.DataFrame(_GLOSSARY, columns=["Column", "Meaning"])
    gl.to_excel(writer, sheet_name="Glossary", index=False)
    ws = writer.sheets["Glossary"]
    ws.column_dimensions["A"].width = 34
    ws.column_dimensions["B"].width = 100
    from openpyxl.styles import Alignment, Font
    ws.cell(row=1, column=1).font = Font(bold=True)
    ws.cell(row=1, column=2).font = Font(bold=True)
    for row in range(2, ws.max_row + 1):
        ws.cell(row=row, column=1).font = Font(bold=True)
        ws.cell(row=row, column=2).alignment = Alignment(wrap_text=True, vertical="top")


def _overview_layout(layout: list[tuple[str, str, Optional[str], int]]) -> list[tuple]:
    """The compact Overview column subset (all lanes ranked together), with a Lane column."""
    overview_cols = ["rank", "playername", "team", "league", "region_elo", "position", "games",
                     "win_rate", "total_score", "pts_per_game", "pts_per_game_w", "clutch_gap",
                     "contrib_pg", "contrib_pg_w", "reg_pts", "playoff_pts", "tourn_pts",
                     "base_pts", "contrib_pts", "wbonus_pts"]
    ov = [(c, h, f, w) for (c, h, f, w) in layout if c in overview_cols
          or c.endswith("_pts")]  # include per-tournament cols
    return ([("rank", "Rank", _INT, 6), ("playername", "Player", None, 16),
             ("team", "Team", None, 18), ("league", "League", None, 8),
             ("position", "Lane", None, 8)]
            + [x for x in ov if x[0] not in ("rank", "playername", "team", "league", "position")])


def write_workbook(out: Path, frame: pd.DataFrame, tourn_cols: list[str],
                   meta: dict) -> Path:
    """Write the formatted workbook from a pre-built enriched frame (no recompute)."""
    layout = _ordered_columns(tourn_cols)
    overview_layout = _overview_layout(layout)
    with pd.ExcelWriter(out, engine="openpyxl") as writer:
        _write_about(writer, meta)
        _write_regions(writer, meta)

        ov = frame.sort_values("total_score", ascending=False).copy()
        ov.insert(0, "rank", range(1, len(ov) + 1))
        _write_sheet(writer, "Overview", ov, overview_layout)

        for lane in ROLES:
            sub = frame[frame["position"] == lane].sort_values(
                "total_score", ascending=False).copy()
            sub.insert(0, "rank", range(1, len(sub) + 1))
            _write_sheet(writer, _LANE_NAMES[lane], sub, layout)

        _write_glossary(writer)
    return out


def export_excel(
    year: int = 2024,
    out: Optional[Path] = None,
    weights: Optional[ScoreWeights] = None,
    min_games: int = 15,
    intl_weight: float = 2.0,
) -> Path:
    """Build ratings and write the formatted workbook. Returns the output path."""
    weights = weights or _DEMO_WEIGHTS
    out = Path(out) if out is not None else PROJECT_ROOT / f"player_ratings_{year}.xlsx"
    frame, tourn_cols, meta = build_export_frame(year, weights, min_games, intl_weight)
    return write_workbook(out, frame, tourn_cols, meta)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(description="Export LPS season ratings to Excel.")
    ap.add_argument("--year", type=int, default=2024)
    ap.add_argument("--out", type=str, default=None)
    ap.add_argument("--min-games", type=int, default=15)
    ap.add_argument("--intl-weight", type=float, default=2.0)
    ap.add_argument("--alpha", type=float, default=_DEMO_WEIGHTS.alpha)
    ap.add_argument("--lam", type=float, default=_DEMO_WEIGHTS.lam)
    ap.add_argument("--beta", type=float, default=_DEMO_WEIGHTS.beta)
    args = ap.parse_args()

    weights = ScoreWeights(alpha=args.alpha, lam=args.lam, beta=args.beta)
    path = export_excel(
        year=args.year, out=args.out, weights=weights,
        min_games=args.min_games, intl_weight=args.intl_weight,
    )
    logger.info(f"Wrote {path}")


if __name__ == "__main__":
    main()
