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

import pandas as pd

from .config import PROJECT_ROOT
from .contribution import ROLES
from .scoring import ScoreWeights
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

_COLUMNS: list[tuple[str, str, str, int, str]] = [
    ("rank",          "Rank",        _INT, 6,  "id"),
    ("playername",    "Player",      None, 16, "id"),
    ("team",          "Team",        None, 18, "id"),
    ("league",        "League",      None, 8,  "id"),
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
    ("pts_per_game",  "LPS/Game",    _PTS, 9,  "score"),
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
    ("avg_resid",     "AvgClutch",   _SIGNED, 10, "rate"),
    ("avg_p_model",   "AvgWinProb",  _PCT, 10, "rate"),
    ("sched_strength","SoS",         _PCT, 8,  "rate"),
    ("fb_rate",       "FB%",         _PCT, 7,  "rate"),
    ("best_game",     "BestGame",    _SIGNED, 10, "rate"),
    ("worst_game",    "WorstGame",   _SIGNED, 10, "rate"),
]

# Per-tournament columns get their own format/width; header comes from the label.
_TOURN_FMT, _TOURN_WIDTH = _PTS, 8

_GLOSSARY: list[tuple[str, str]] = [
    ("Rank", "Rank within the lane by LPS (Overview sheet: rank across all lanes)."),
    ("LPS", "League Performance Score: total_score = Baseline + Contribution + WinBonus, "
            "accumulated across regular season, playoffs and tournaments (more games help)."),
    ("LPS/Game", "LPS divided by games played -- per-game efficiency (a full-run star and a "
                 "one-series sub can be compared here)."),
    ("Regular / Playoffs / Tourneys", "LPS earned in each phase. Regular & playoffs are "
        "length-normalized per region (a full run ~ one unit); tournaments are weighted by "
        "viewership and normalized so a full winning run = the tournament's weight."),
    ("Baseline", "Points for the strength of the OPPONENT's league (cross-league parity term)."),
    ("Contribution", "Win-probability the player added vs an expected player at their "
                     "position (leave-one-out on Model 2), summed over games."),
    ("WinBonus", "Credit for actually winning vs the model's expectation: beta*(result - p_model). "
                 "Positive = won games the model rated as losses (clutch); negative = choked."),
    ("Kills/Deaths/Assists/Damage/FirstBlood", "Contribution split by stat source -- these "
        "sum to Contribution. First blood is credited to the FB getter (+) / victim (-)."),
    ("AvgContrib", "Mean per-game net win-probability contribution (raw, not scaled)."),
    ("AvgClutch", "Mean per-game (result - p_model): over/under-performance vs the model."),
    ("AvgWinProb", "Mean model win probability for the player's team-games (team strength)."),
    ("SoS", "Strength of schedule: mean opponent-league baseline faced (higher = tougher)."),
    ("FB%", "Share of games the player got first blood or was the first-blood victim."),
    ("BestGame / WorstGame", "Player's single-game best / worst net contribution (win-prob)."),
    ("#Trn", "Distinct tournaments the player appeared in."),
    ("<Tournament>", "LPS earned at that specific tournament (WLDs=Worlds, MSI, EWC=Esports "
                     "World Cup, KeSPA/DCup=domestic cups). These sum to Tourneys."),
]


def build_export_frame(
    year: int,
    weights: ScoreWeights,
    min_games: int,
    intl_weight: float,
) -> tuple[pd.DataFrame, list[str], dict]:
    """
    Full per-player ratings enriched with per-game rate/quality stats.

    Returns (frame, tournament_cols, meta) where frame has one row per player (all lanes),
    tournament_cols is the ordered list of per-tournament point columns, and meta carries
    run parameters for the About sheet.
    """
    matches = build_player_match_scores(year, weights=weights)
    ratings = build_player_ratings(
        year, weights=weights, matches=matches, min_games=min_games, intl_weight=intl_weight,
    )
    tourn_cols = ratings.attrs.get("tournament_cols", [])

    # Per-player rate/quality stats from the per-match frame.
    matches = matches.copy()
    matches["_resid"] = matches["result"] - matches["p_model"]
    g = matches.groupby("playername")
    extra = pd.DataFrame({
        "wins": g["result"].sum().astype(int),
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
    r["pts_per_game"] = r["total_score"] / r["games"].where(r["games"] > 0, 1)
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
    }
    return r, tourn_cols, meta


def _ordered_columns(tourn_cols: list[str]) -> list[tuple[str, str, Optional[str], int]]:
    """Full (col, header, fmt, width) layout, inserting per-tournament cols before rates."""
    out: list[tuple[str, str, Optional[str], int]] = []
    for col, hdr, fmt, width, group in _COLUMNS:
        if group == "rate" and not any(o[0] == tourn_cols[0] for o in out) and tourn_cols:
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
        ("  N_ref (per-phase reference games)", round(float(meta["n_ref"]), 1)),
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
    layout = _ordered_columns(tourn_cols)

    # Overview: everyone across all lanes, ranked together (a compact column subset).
    overview_cols = ["rank", "playername", "team", "league", "position", "games", "win_rate",
                     "total_score", "pts_per_game", "reg_pts", "playoff_pts", "tourn_pts",
                     "base_pts", "contrib_pts", "wbonus_pts"] + tourn_cols
    overview_layout = [(c, h, f, w) for (c, h, f, w) in layout if c in overview_cols]
    # add position header explicitly (not in _COLUMNS layout)
    overview_layout = ([("rank", "Rank", _INT, 6), ("playername", "Player", None, 16),
                        ("team", "Team", None, 18), ("league", "League", None, 8),
                        ("position", "Lane", None, 8)]
                       + [x for x in overview_layout if x[0] not in
                          ("rank", "playername", "team", "league", "position")])

    with pd.ExcelWriter(out, engine="openpyxl") as writer:
        _write_about(writer, meta)

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
