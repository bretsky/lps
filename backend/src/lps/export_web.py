"""
Web export: turn the latest career workbook into the static JSON bundle the
rankings site consumes.

Reads `player_ratings_career_<first>_<last>.xlsx` (the workbook `career.py`
writes) and emits the bundle under `frontend/public/data/current/`. The
previous `current/` (if any) is auto-moved to
`frontend/public/data/archive/<its_build_id>/` -- past snapshots stay
recoverable locally, but only `current/` is tracked in git. The current
build's own id + generated timestamp live in `current/meta.json`. Contents:

    index.json          -- slim ranking rows (the rated pool) for the board
    lanes/<lane>.json   -- same slim rows per position
    players/<slug>.json -- full detail per player (all columns, trajectory,
                          resume breakdown, splits, tier, radar percentiles)
    tiers.json          -- tier labels, colors, CLR cutoffs, memberships
    meta.json           -- build id, generated date, year range, weights
    glossary.json       -- column -> definition from export_excel._GLOSSARY

Design notes
------------
- We read the *workbook*, not the in-memory frames, so this script stays
  independent of career.py's runtime. career.py's `_career_layout` gives us
  the display->raw column map; anything Overview has that isn't in the layout
  is a dynamic tournament column (raw name == display header, per
  `.replace("_pts","")` round-tripping).
- Tier binning is HYBRID (locked design decision): hard caps for GOATs (top 5)
  and Legends (next 15) plus percentile bands below, all computed over the
  RATED POOL (games >= RATED_MIN_GAMES). The un-rated tail is written to
  disk as `players/*.json` too (so search from a shared link still works) but
  is filtered out of `index.json` / `lanes/*.json`.
- Radar percentiles are computed over the rated pool as well, both globally
  and per-lane, and stored on each player's detail JSON.
- Numbers rounded server-side (3 sig figs for scores, 3 dp for rates) to keep
  payload small.

Run:
    poetry run python -m lps.export_web
    poetry run python -m lps.export_web --workbook player_ratings_career_2011_2026.xlsx
    poetry run python -m lps.export_web --out ../frontend/public/data
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import logging
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

import numpy as np
import pandas as pd

from .career import _career_layout, YEARS_DEFAULT, CLRConfig
from .config import INFO_DIR, PROJECT_ROOT
from .contribution import ROLES
from .export_excel import _GLOSSARY
from .io_oracle import load_oracle_all
from .player_identity import label_map
from .season import _LANE_NAMES

HALL_OF_LEGENDS_CSV = INFO_DIR / "hall_of_legends.csv"
PLAYER_STATUS_CSV = INFO_DIR / "player_status.csv"

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
RATED_MIN_GAMES = 100  # inclusion floor for the public board (see plan §11.1)

# Tier ladder (top -> bottom).  Cutoffs are absolute CLR floors -- round
# numbers so the meaning of "Legend" (CLR >= 40) is stable across reruns
# rather than "top 20 today".  Membership counts drift as the data grows;
# the numbers don't.  Tune here.
_TIERS: list[dict] = [
    {"key": "goats", "label": "GOATs", "clr_min": 70.0, "color": "#f5c15b"},
    {"key": "legends", "label": "Legends", "clr_min": 50.0, "color": "#d97757"},
    {"key": "greats", "label": "Greats", "clr_min": 30.0, "color": "#a685e2"},
    {"key": "elite", "label": "Elite", "clr_min": 15.0, "color": "#6aa7e6"},
    {"key": "stars", "label": "Stars", "clr_min": 6.0, "color": "#5fbf94"},
    {"key": "contenders", "label": "Contenders", "clr_min": 0.0, "color": "#8a94a3"},
]

# 7 radar axes -- (label, source raw column, invert?).  Invert=True flips
# rank-style columns where lower is better before percentile-ing.
_RADAR_AXES: list[tuple[str, str, bool]] = [
    ("peak", "peak_lps", False),
    ("longevity", "total_score", False),
    ("consistency", "pace_value", False),
    ("resume", "resume_bonus", False),
    ("impact", "avg_contrib", False),  # per-game win-prob added; contrib_pg_w isn't on the career sheet
    ("clutch", "clutch_gap", False),
    ("dominance", "hn_global", True),
]

# Columns kept on the slim index row (fits ~30 KB gzipped for 1.2k rows).
# `positions` is a list [{lane, clr, share}] for multi-role players (Xiaohu, Perkz).
# The scalar `position` is the primary lane (first entry in `positions`); the
# board filters by any lane in `positions` so a mid/top hybrid appears in both.
_INDEX_FIELDS: list[str] = [
    "rank", "slug", "playername", "position", "positions",
    "current_team", "current_league", "current_year",
    "region_elo", "n_years", "first_year", "last_year", "games", "win_rate",
    "clr", "career_value", "pace_value", "peak_value", "resume_bonus",
    "total_score", "peak_lps", "tier",
    "hall_of_legends", "hol_year", "is_retired", "is_active",
]

# Round most floats to this many decimals when writing.
_ROUND_DECIMALS = 3


# ---------------------------------------------------------------------------
# Workbook -> DataFrames with raw column names
# ---------------------------------------------------------------------------
def _display_to_raw_map(all_tourn: list[str], years: tuple[int, ...], include_lane: bool) -> dict[str, str]:
    """Invert the `_career_layout` (raw, display, fmt, width) tuples into a
    display-header -> raw-column map."""
    lay = _career_layout(all_tourn, years, include_lane)
    return {display: raw for (raw, display, _fmt, _w) in lay}


def _load_workbook(path: Path) -> tuple[pd.DataFrame, dict[str, pd.DataFrame], tuple[int, ...], list[str], pd.DataFrame]:
    """Read Overview + per-lane sheets and rename display headers back to raw
    column names.  Returns (overview, per_lane, years, tourn_cols, about)."""
    xls = pd.ExcelFile(path)
    ov = pd.read_excel(xls, sheet_name="Overview")
    about = pd.read_excel(xls, sheet_name="About", header=None)

    # Discover years from Overview's per-year columns (headers are the ints/strs).
    year_cols = [c for c in ov.columns if isinstance(c, (int, np.integer)) or (isinstance(c, str) and c.isdigit())]
    years = tuple(sorted(int(c) for c in year_cols))
    # Discover tournament cols: those in Overview that aren't in the fixed
    # layout and aren't year cols.  Their raw name == display header.
    fixed_map = _display_to_raw_map([], years, include_lane=True)
    known_headers = set(fixed_map.keys()) | {str(y) for y in years} | {int(y) for y in years}
    tourn_cols = [c for c in ov.columns if c not in known_headers]

    # Full map with tournament cols identity-mapped and year cols → yYYYY.
    full_map = dict(fixed_map)
    for tc in tourn_cols:
        full_map[tc] = str(tc)
    for y in years:
        full_map[int(y)] = f"y{y}"
        full_map[str(y)] = f"y{y}"

    ov = ov.rename(columns=full_map)

    lanes: dict[str, pd.DataFrame] = {}
    fixed_map_lane = _display_to_raw_map([], years, include_lane=False)
    lane_full_map = dict(fixed_map_lane)
    for tc in tourn_cols:
        lane_full_map[tc] = str(tc)
    for y in years:
        lane_full_map[int(y)] = f"y{y}"
        lane_full_map[str(y)] = f"y{y}"
    for lane, sheet in _LANE_NAMES.items():
        if sheet in xls.sheet_names:
            df = pd.read_excel(xls, sheet_name=sheet).rename(columns=lane_full_map)
            df["position"] = lane
            lanes[lane] = df

    return ov, lanes, years, [str(t) for t in tourn_cols], about


# ---------------------------------------------------------------------------
# Slugs
# ---------------------------------------------------------------------------
_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _base_slug(name: str) -> str:
    s = _SLUG_RE.sub("-", str(name).lower()).strip("-")
    return s or "player"


def _assign_slugs(names: Iterable[str]) -> list[str]:
    """Deterministic per-name slug with collision suffixes (`-2`, `-3`, ...)
    assigned in first-seen order so subsequent runs are stable."""
    slugs: list[str] = []
    seen: dict[str, int] = {}
    for n in names:
        base = _base_slug(n)
        i = seen.get(base, 0) + 1
        seen[base] = i
        slugs.append(base if i == 1 else f"{base}-{i}")
    return slugs


# ---------------------------------------------------------------------------
# Tiers
# ---------------------------------------------------------------------------
def _assign_tiers(clr: pd.Series) -> tuple[pd.Series, list[dict]]:
    """Bin players into tiers by absolute CLR cutoffs (top-down).  Returns
    (tier_key per player, tier meta list with `clr_floor` cutoffs and
    `count`).  The cutoff is the tier's designed CLR floor -- reported as-is,
    not the observed min of members -- so the floor stays a round number even
    if a tier is empty in a given rerun."""
    tier = pd.Series(index=clr.index, dtype=object)
    for t in _TIERS:  # top -> bottom
        m = tier.isna() & (clr >= float(t["clr_min"]))
        tier.loc[m] = t["key"]

    tier_meta: list[dict] = []
    for t in _TIERS:
        members = tier[tier == t["key"]]
        tier_meta.append({
            "key": t["key"], "label": t["label"], "color": t["color"],
            "count": int(len(members)),
            "clr_floor": float(t["clr_min"]),
        })
    return tier, tier_meta


# ---------------------------------------------------------------------------
# Radar percentiles
# ---------------------------------------------------------------------------
def _radar_percentiles(frame: pd.DataFrame) -> dict[str, list[float]]:
    """For each axis, return a list of 0-100 percentile values in `frame` row
    order.  Inverted axes (rank-style) are negated before ranking."""
    out: dict[str, list[float]] = {}
    for label, col, invert in _RADAR_AXES:
        if col not in frame.columns:
            out[label] = [None] * len(frame)  # type: ignore[list-item]
            continue
        s = frame[col].astype(float)
        if invert:
            s = -s
        pct = s.rank(pct=True, method="average") * 100.0
        out[label] = [_round(v, 1) for v in pct.tolist()]
    return out


# ---------------------------------------------------------------------------
# JSON shaping helpers
# ---------------------------------------------------------------------------
def _round(x, decimals: int = _ROUND_DECIMALS):
    if x is None:
        return None
    try:
        if isinstance(x, (float, np.floating)):
            if np.isnan(x) or np.isinf(x):
                return None
            return round(float(x), decimals)
        if isinstance(x, (int, np.integer)):
            return int(x)
        return x
    except (TypeError, ValueError):
        return x


def _clean(v):
    """Convert numpy/pandas scalars to plain Python, NaN -> None.
    Bool is checked BEFORE int because bool is a subclass of int in Python (and
    numpy.bool_ predates numpy.integer's MRO), so a naive int branch turns
    True/False into 1/0 in JSON.
    Lists/dicts (e.g., the `positions` list) pass through untouched — `pd.isna`
    at the tail would raise on them."""
    if v is None:
        return None
    if isinstance(v, (list, dict)):
        return v
    if isinstance(v, (np.bool_, bool)):
        return bool(v)
    if isinstance(v, (float, np.floating)):
        if np.isnan(v) or np.isinf(v):
            return None
        return float(v)
    if isinstance(v, (int, np.integer)):
        return int(v)
    if isinstance(v, str):
        return v
    if pd.isna(v):
        return None
    return v


def _row_dict(row: pd.Series, cols: list[str]) -> dict:
    return {c: _clean(row[c]) if c in row else None for c in cols}


def _index_row(row: pd.Series) -> dict:
    d = _row_dict(row, _INDEX_FIELDS)
    for k in ("clr", "career_value", "pace_value", "peak_value", "resume_bonus",
              "total_score", "peak_lps", "win_rate"):
        d[k] = _round(d.get(k))
    return d


def _tournament_dict(row: pd.Series, tourn_cols: list[str]) -> dict:
    out: dict[str, float] = {}
    for tc in tourn_cols:
        if tc in row:
            v = _clean(row[tc])
            if v not in (None, 0, 0.0):
                out[tc] = _round(v)
    return out


def _trajectory(row: pd.Series, years: tuple[int, ...]) -> dict:
    out: dict[str, float] = {}
    for y in years:
        col = f"y{y}"
        if col in row:
            v = _clean(row[col])
            if v not in (None, 0, 0.0):
                out[str(y)] = _round(v)
    return out


def _splits(row: pd.Series) -> dict:
    """Pre-formatted 'T1 (245.3), ...' strings AND their structured
    counterparts. The strings are kept for backwards-compatible consumers; the
    structured lists (`teams`, `leagues`, `lanes`) are what the detail page
    should render — each entry is `{name, clr}` sorted highest-first."""
    out: dict = {}
    for k in ("teams_lps", "leagues_lps", "lanes_lps"):
        if k in row:
            v = _clean(row[k])
            if v:
                out[k] = v
                out[k.replace("_lps", "")] = _parse_split_string(v)
    return out


def _resume_breakdown(row: pd.Series) -> dict:
    """9-category (count, pts) breakdown that sums (Pt) to `resume_bonus`."""
    cats = [
        ("wlds_title", "rb_wlds_title_n", "rb_wlds_title_pts"),
        ("wlds_deep", "rb_wlds_deep_n", "rb_wlds_deep_pts"),
        ("msi", "rb_msi_n", "rb_msi_pts"),
        ("other_intl", "rb_othr_intl_n", "rb_othr_intl_pts"),
        ("dom_champ", "rb_dom_champ_n", "rb_dom_champ_pts"),
        ("dom_final", "rb_dom_final_n", "rb_dom_final_pts"),
        ("dom_cup", "rb_dom_cup_n", "rb_dom_cup_pts"),
        ("mvp", "rb_mvp_n", "rb_mvp_pts"),
        ("allpro", "rb_allpro_n", "rb_allpro_pts"),
    ]
    out: dict[str, dict] = {}
    for key, n_col, p_col in cats:
        n = _clean(row.get(n_col)) if n_col in row else None
        p = _clean(row.get(p_col)) if p_col in row else None
        if (n or 0) or (p or 0):
            out[key] = {"n": int(n or 0), "pts": _round(p)}
    return out


# The scalar columns we send on the full player detail JSON, grouped for the
# frontend's breakdown view.
_DETAIL_HEADLINE = ["rank", "slug", "playername", "position", "positions",
                    "current_team", "current_league", "current_year",
                    "region_elo", "n_years", "first_year", "last_year", "games",
                    "win_rate", "clr", "tier"]
_DETAIL_CLR = ["career_value", "pace_value", "peak_value", "resume_bonus",
               "intl_bonus", "title_bonus", "award_bonus"]
_DETAIL_CAREER_LPS = ["total_score", "lps_per_year", "peak_year", "peak_lps",
                      "peak_years", "peak_band_avg"]
_DETAIL_PHASE = ["reg_pts", "playoff_pts", "tourn_pts"]
_DETAIL_COMPONENT = ["base_pts", "contrib_pts", "wbonus_pts"]
_DETAIL_SOURCES = ["kills_pts", "deaths_pts", "assists_pts", "damage_pts", "fb_pts"]
_DETAIL_RATES = ["pts_per_game", "pts_per_game_w", "clutch_gap", "avg_contrib",
                 "avg_resid", "avg_p_model", "sched_strength"]
_DETAIL_HIGH_NOON = ["hn_lane_best", "hn_lane", "hn_lane_yrs",
                     "hn_global_best", "hn_global", "hn_global_yrs"]


def _detail_json(row: pd.Series, tourn_cols: list[str], years: tuple[int, ...],
                 radar_global: dict, radar_lane: dict, idx_in_global: int,
                 idx_in_lane: Optional[int]) -> dict:
    def _grp(cols):
        return {c: _round(_clean(row.get(c))) for c in cols if c in row}

    detail = {
        **_row_dict(row, _DETAIL_HEADLINE),
        "clr_components": _grp(_DETAIL_CLR),
        "career_lps": _grp(_DETAIL_CAREER_LPS),
        "phase": _grp(_DETAIL_PHASE),
        "components": _grp(_DETAIL_COMPONENT),
        "sources": _grp(_DETAIL_SOURCES),
        "rates": _grp(_DETAIL_RATES),
        "high_noon": _grp(_DETAIL_HIGH_NOON),
        "resume_breakdown": _resume_breakdown(row),
        "tournaments": _tournament_dict(row, tourn_cols),
        "trajectory": _trajectory(row, years),
        "splits": _splits(row),
        "radar": {
            "global": {axis: radar_global[axis][idx_in_global] for axis, *_ in _RADAR_AXES},
            "lane": ({axis: radar_lane[axis][idx_in_lane] for axis, *_ in _RADAR_AXES}
                     if idx_in_lane is not None and radar_lane else None),
        },
    }
    # Round scalars in the headline block.
    for k in ("clr", "win_rate"):
        detail[k] = _round(detail.get(k))
    return detail


# ---------------------------------------------------------------------------
# About sheet -> meta.json
# ---------------------------------------------------------------------------
def _about_to_meta(about: pd.DataFrame) -> dict:
    """Extract weights/era mults/etc. from the About sheet into a flat dict."""
    kv: dict = {}
    for _, r in about.iterrows():
        k = r[0]
        v = r[1] if len(r) > 1 else None
        if pd.isna(k) or not isinstance(k, str):
            continue
        key = k.strip().strip("*").strip()
        if key in ("Field", ""):  # skip the header row
            continue
        kv[key] = _clean(v)
    return kv


# ---------------------------------------------------------------------------
# Main build
# ---------------------------------------------------------------------------
@dataclass
class ExportConfig:
    workbook: Optional[Path] = None
    out_root: Optional[Path] = None
    build_id: Optional[str] = None
    rated_min_games: int = RATED_MIN_GAMES


# International events show up in Oracle's `league` column as their own tags;
# a player whose most-recent-year rows are only internationals (e.g., Ming 2022
# = only MSI + Worlds) would otherwise get `current_league = "MSI"`, which
# doesn't describe their domestic affiliation. Prefer domestic games when
# picking the "current" team/league; only fall back to internationals if a
# player has literally nothing else recorded.
_INTL_LEAGUES = {"MSI", "WLDs", "WCS", "Worlds", "FST", "EWC"}


def _current_team_league(playernames: Iterable[str]) -> pd.DataFrame:
    """For every name in `playernames`, return their MOST RECENT (year, team, league)
    from Oracle box-scores. Active players → current team/league. Retired players
    → their last team/league (still useful context in the UI).

    Joins by canonical player-identity label (via `player_identity.label_map`)
    so disambiguated workbook names like "Knight (LPL)" match the raw Oracle
    handle "Knight" through their shared `playerid`. Prefers domestic games
    when picking the latest year so players whose only most-recent games are
    international events don't end up labeled "MSI"/"Worlds".

    Returns [playername, current_team, current_league, current_year].
    """
    names = set(playernames)
    try:
        df = load_oracle_all()
    except FileNotFoundError:
        logger.warning("[web] no Oracle CSVs found -- current team/league will be null")
        return pd.DataFrame(columns=["playername", "current_team", "current_league", "current_year"])

    # Column names vary across Oracle schema years.
    name_col = next((c for c in ("playername", "player") if c in df.columns), None)
    team_col = next((c for c in ("teamname", "team") if c in df.columns), None)
    league_col = "league" if "league" in df.columns else None
    if not (name_col and team_col and league_col):
        logger.warning("[web] Oracle missing name/team/league cols -- current team/league null")
        return pd.DataFrame(columns=["playername", "current_team", "current_league", "current_year"])

    if "position" in df.columns:
        df = df[df["position"] != "team"]
    if "datacompleteness" in df.columns:
        df = df[df["datacompleteness"] == "complete"]

    cols = [name_col, team_col, league_col, "year"]
    if "playerid" in df.columns:
        cols.append("playerid")
    df = df[cols].rename(columns={name_col: "raw_name", team_col: "team", league_col: "league"})

    # Canonical label: workbook renames shared handles ("Knight (LPL)"); Oracle
    # stores raw ("Knight"). Bridge via playerid -> label; fall back to raw when
    # no playerid or no label registered (Leaguepedia-only players).
    lm = label_map()
    if "playerid" in df.columns:
        df["playername"] = df["playerid"].map(lm).fillna(df["raw_name"])
    else:
        df["playername"] = df["raw_name"]

    df = df[df["playername"].isin(names)]
    df = df.dropna(subset=["playername", "team"])
    if df.empty:
        return pd.DataFrame(columns=["playername", "current_team", "current_league", "current_year"])

    df["is_domestic"] = ~df["league"].isin(_INTL_LEAGUES)

    def _mode(s: pd.Series):
        m = s.mode()
        return m.iloc[0] if len(m) else None

    def _pick(g: pd.DataFrame) -> pd.Series:
        dom = g[g["is_domestic"]]
        src = dom if len(dom) else g
        yr = int(src["year"].max())
        src = src[src["year"] == yr]
        return pd.Series({
            "current_team": _mode(src["team"]),
            "current_league": _mode(src["league"]),
            "current_year": yr,
        })

    return (
        df.groupby("playername", group_keys=False)
        .apply(_pick, include_groups=False)
        .reset_index()
    )


# Matches "Name (12.3)" or "Name (78%)" — team/league/lane split entries.
_SPLIT_RE = re.compile(r"^\s*(?P<name>.+?)\s*\((?P<val>[\d.]+)%?\)\s*$")


def _parse_split_string(s) -> list[dict]:
    """Parse a career.py breakdown string ('T1 (245.3), DAMWON (30.1)' or
    'T1 (78%), DAMWON (10%)') back into structured entries. Returns
    [{name, clr}] sorted highest-first (order is preserved from the string,
    which career.py already sorts descending). Values in % strings are kept
    as-is under `clr` — the frontend can distinguish by tiers.json context or
    treat both as 'contribution weight' for display."""
    if not isinstance(s, str) or not s.strip():
        return []
    out: list[dict] = []
    for part in s.split(", "):
        m = _SPLIT_RE.match(part)
        if not m:
            continue
        try:
            v = float(m.group("val"))
        except ValueError:
            continue
        out.append({"name": m.group("name"), "clr": _round(v)})
    return out


def _load_hall_of_legends() -> pd.DataFrame:
    """Read info/hall_of_legends.csv (playername, year_inducted, order).
    Returns an empty frame if the file is missing so builds don't hard-fail."""
    if not HALL_OF_LEGENDS_CSV.exists():
        logger.warning("[web] no %s -- skipping HoL merge", HALL_OF_LEGENDS_CSV.name)
        return pd.DataFrame(columns=["playername", "hol_year", "hol_order"])
    df = pd.read_csv(HALL_OF_LEGENDS_CSV)
    df = df.rename(columns={"year_inducted": "hol_year", "order": "hol_order"})
    df["playername"] = df["playername"].astype(str)
    for c in ("hol_year", "hol_order"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df[["playername", "hol_year", "hol_order"]]


# Fallback set for CSVs written before the wikitext-scraped
# `is_retired_as_player` column existed. Once the column is present it's the
# authoritative signal and this set is unused.
_PLAYING_ROLES = {"Top", "Jungle", "Mid", "Bot", "Support", "Substitute"}


def _load_player_status(years: tuple[int, ...]) -> pd.DataFrame:
    """Read info/player_status.csv (playername, is_retired, is_retired_as_player,
    country, role) from fetch_player_status. Missing file = empty frame + warn.

    Folds Leaguepedia's "Retired as Player" state (scraped from page wikitext
    into the `is_retired_as_player` column by fetch_player_status) into
    `is_retired` so the badge shows correctly for players like Wolf who
    aren't Cargo-retired but have `|isretiredplayer=Yes` on their wiki page."""
    if not PLAYER_STATUS_CSV.exists():
        logger.warning(
            "[web] no %s -- Active/Retired badges will be blank. "
            "Run `python -m lps.fetch_player_status` to populate.",
            PLAYER_STATUS_CSV.name,
        )
        return pd.DataFrame(columns=["playername", "is_retired", "country", "role"])
    df = pd.read_csv(PLAYER_STATUS_CSV)
    if df["is_retired"].dtype == object:
        df["is_retired"] = df["is_retired"].astype(str).str.lower().isin(("true", "1", "yes"))
    df["playername"] = df["playername"].astype(str)

    if "is_retired_as_player" in df.columns:
        if df["is_retired_as_player"].dtype == object:
            df["is_retired_as_player"] = (
                df["is_retired_as_player"].astype(str).str.lower().isin(("true", "1", "yes"))
            )
        n_added = int((df["is_retired_as_player"] & ~df["is_retired"]).sum())
        df["is_retired"] = df["is_retired"] | df["is_retired_as_player"]
        if n_added:
            logger.info("[web] +%d retired-as-player (wikitext-scraped)", n_added)
    # Non-playing-role fallback ALWAYS runs (not just for older CSVs): Broxah
    # and similar players show `Role=Streamer` in Cargo but don't have the
    # `|isretiredplayer=Yes` wikitext flag set, so the scrape misses them.
    # Cargo's Role is the authoritative "what are they doing now" signal, so
    # a non-playing role is a strong indicator they're no longer a player.
    if "role" in df.columns:
        role = df["role"].astype(str).str.strip()
        has_role = role.notna() & (role != "") & (role.str.lower() != "nan")
        non_playing = has_role & ~role.isin(_PLAYING_ROLES)
        n_added = int((non_playing & ~df["is_retired"]).sum())
        df["is_retired"] = df["is_retired"] | non_playing
        if n_added:
            logger.info("[web] +%d retired (non-playing Cargo role)", n_added)
    return df


def _latest_career_workbook() -> Path:
    candidates = sorted(PROJECT_ROOT.glob("player_ratings_career_*.xlsx"))
    if not candidates:
        raise FileNotFoundError(
            "no player_ratings_career_*.xlsx found in backend/ -- "
            "run `python -m lps.career` first (or `python -m lps.update_all`)."
        )
    # Prefer the widest-year span, falling back to mtime.
    def _span(p: Path) -> tuple[int, int]:
        m = re.match(r"player_ratings_career_(\d{4})_(\d{4})", p.stem)
        return (int(m[2]) - int(m[1]) if m else 0, int(p.stat().st_mtime))
    return max(candidates, key=_span)


def build_web_bundle(cfg: ExportConfig) -> Path:
    wb = cfg.workbook or _latest_career_workbook()
    out_root = cfg.out_root or (PROJECT_ROOT.parent / "frontend" / "public" / "data")
    build_id = cfg.build_id or _dt.date.today().isoformat()
    # The site always serves current/. Any existing current/ is moved to
    # archive/<its_build_id>/ so past snapshots are recoverable locally; the
    # archive dir is gitignored (only current/ ships in the repo).
    out_dir = out_root / "current"
    if out_dir.exists():
        prev_meta = out_dir / "meta.json"
        prev_build = build_id
        try:
            prev_build = json.loads(prev_meta.read_text("utf-8")).get("build_id", build_id)
        except Exception:
            pass
        archive_dst = out_root / "archive" / prev_build
        if archive_dst.exists():
            shutil.rmtree(archive_dst)
        archive_dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(out_dir), str(archive_dst))
        logger.info("[web] archived previous build to %s", archive_dst)
    (out_dir / "players").mkdir(parents=True, exist_ok=True)
    (out_dir / "lanes").mkdir(parents=True, exist_ok=True)

    logger.info("[web] reading %s", wb.name)
    ov, lanes, years, tourn_cols, about = _load_workbook(wb)

    # Overview has no `position` column (it's cross-lane); derive each player's
    # full `positions` list from per-lane sheets and pick the highest-CLR lane as
    # the primary. Multi-role players (Xiaohu, Perkz) carry every lane they
    # played so the UI can show all of them and the lane pages can rank them
    # under every lane they qualify for.
    positions_by_name: dict[str, list[dict]] = {}
    for lane, df in lanes.items():
        if "playername" not in df.columns or "clr" not in df.columns:
            continue
        games_col = df["games"] if "games" in df.columns else pd.Series([0] * len(df))
        for name, clr, games in zip(df["playername"], df["clr"], games_col):
            if pd.isna(clr):
                continue
            positions_by_name.setdefault(name, []).append(
                {"lane": lane, "clr": float(clr), "games": int(games) if pd.notna(games) else 0}
            )
    for lst in positions_by_name.values():
        lst.sort(key=lambda p: p["clr"], reverse=True)
        total = sum(p["clr"] for p in lst) or 1.0
        for p in lst:
            p["share"] = round(100.0 * p["clr"] / total, 1)
            p["clr"] = _round(p["clr"])
    ov["positions"] = ov["playername"].map(positions_by_name).apply(
        lambda x: x if isinstance(x, list) else []
    )
    ov["position"] = ov["positions"].apply(lambda lst: lst[0]["lane"] if lst else None)

    # Slugs from Overview order (rank order).
    ov = ov.sort_values("rank" if "rank" in ov.columns else "clr", ascending=[True] if "rank" in ov.columns else [False]).reset_index(drop=True)
    ov["slug"] = _assign_slugs(ov["playername"].tolist())
    slug_by_name = dict(zip(ov["playername"], ov["slug"]))

    # Hall of Legends + Leaguepedia player status
    hol = _load_hall_of_legends()
    ov = ov.merge(hol, on="playername", how="left")
    ov["hall_of_legends"] = ov["hol_year"].notna() | ov["hol_order"].notna()
    ov["hol_year"] = ov["hol_year"].astype("Int64")

    status = _load_player_status(years)
    ov = ov.merge(status[["playername", "is_retired"]] if len(status) else status,
                  on="playername", how="left")
    # is_active: known-not-retired AND played in the newest season on record.
    # is_retired NaN -> unknown (blank badge, not "Active" nor "Retired").
    latest_year = int(years[-1])
    ov["is_active"] = pd.Series(
        [
            (r is False) and (ly == latest_year) if pd.notna(r) else pd.NA
            for r, ly in zip(ov["is_retired"], ov["last_year"])
        ],
        dtype=object,
    )
    # Current team/league from most-recent Oracle year (active → current, retired → last).
    ctl = _current_team_league(ov["playername"].tolist())
    ov = ov.merge(ctl, on="playername", how="left")
    if "current_year" in ov.columns:
        ov["current_year"] = ov["current_year"].astype("Int64")
    logger.info(
        "[web] current team/league: %d players mapped (of %d)",
        int(ov["current_team"].notna().sum()) if "current_team" in ov.columns else 0,
        len(ov),
    )

    # For players who aren't currently active (retired, on hiatus, coaching,
    # unknown), showing "last team in Oracle" is often just a coda team they
    # spent a partial split on. The team they earned the most CLR on -- the
    # first entry of the `teams_lps` split, which career.py already sorts by
    # CLR -- is the affiliation people associate with them. Same for league.
    def _top_split(s) -> Optional[str]:
        lst = _parse_split_string(s)
        return lst[0]["name"] if lst else None

    career_team = ov["teams_lps"].apply(_top_split) if "teams_lps" in ov.columns else None
    career_league = ov["leagues_lps"].apply(_top_split) if "leagues_lps" in ov.columns else None
    if career_team is not None:
        not_active = ov["is_active"] != True  # covers False AND pd.NA (unknown)
        ov["current_team"] = ov["current_team"].where(~not_active, career_team)
        ov["current_league"] = ov["current_league"].where(~not_active, career_league)
        # `current_year` describes the Oracle-latest year; for career-team
        # overrides it no longer matches the displayed team, so null it out
        # to avoid confusing "Team X (2019)"-style captions later.
        ov.loc[not_active, "current_year"] = pd.NA

    logger.info(
        "[web] HoL: %d matched; status: %d rows (retired=%s, active=%s, unknown=%s)",
        int(ov["hall_of_legends"].sum()),
        int((~ov["is_retired"].isna()).sum()),
        int((ov["is_retired"] == True).sum()),
        int((ov["is_active"] == True).sum()),
        int(ov["is_retired"].isna().sum()),
    )

    # Rated pool: games >= floor.
    rated = ov[ov["games"] >= cfg.rated_min_games].copy().reset_index(drop=True)
    logger.info("[web] rated pool: %d / %d players (games >= %d)",
                len(rated), len(ov), cfg.rated_min_games)

    # Tiers over the rated pool (rewrite ranks within the rated pool too).
    rated["rank"] = rated["clr"].rank(ascending=False, method="first").astype(int)
    rated = rated.sort_values("rank").reset_index(drop=True)
    tier_series, tier_meta = _assign_tiers(rated["clr"].reset_index(drop=True))
    rated["tier"] = tier_series.values

    # Radar percentiles over the rated pool (global + per-lane sub-pools).
    radar_global = _radar_percentiles(rated)
    slug_to_global_idx = {s: i for i, s in enumerate(rated["slug"])}

    radar_by_lane: dict[str, dict] = {}
    lane_slug_idx: dict[str, dict[str, int]] = {}
    for lane in ROLES:
        sub = rated[rated["position"] == lane].reset_index(drop=True)
        if len(sub):
            radar_by_lane[lane] = _radar_percentiles(sub)
            lane_slug_idx[lane] = {s: i for i, s in enumerate(sub["slug"])}

    # index.json  (rated only)
    index_rows = [_index_row(r) for _, r in rated.iterrows()]
    _write_json(out_dir / "index.json", index_rows)

    # lanes/<lane>.json  (built from per-lane workbook sheets — multi-role
    # players appear under every lane they hit the rated-games floor in, each
    # row ranked by that lane's own CLR. Enrichments (slug, HoL, status,
    # current team/league, positions list, global tier) are looked up from the
    # Overview-derived `ov` frame by playername.)
    enrich_cols = [
        "playername", "slug", "current_team", "current_league", "current_year",
        "hall_of_legends", "hol_year", "is_retired", "is_active", "positions",
    ]
    ov_enrich = ov[[c for c in enrich_cols if c in ov.columns]].copy()
    for lane in ROLES:
        lf = lanes.get(lane)
        if lf is None or not len(lf) or "playername" not in lf.columns:
            continue
        # Drop any overlapping enrichment cols from the lane sheet before merge
        # so ov_enrich's values win (lane sheets have their own `position`).
        drop_overlap = [c for c in enrich_cols if c != "playername" and c in lf.columns]
        lf = lf.drop(columns=drop_overlap).merge(ov_enrich, on="playername", how="left")
        # Rated pool per-lane: same games floor, but against per-lane games.
        lf = lf[lf["games"] >= cfg.rated_min_games].copy()
        if not len(lf):
            continue
        lf["rank"] = lf["clr"].rank(ascending=False, method="first").astype(int)
        lf = lf.sort_values("rank").reset_index(drop=True)
        # Tier bands re-assigned from THIS LANE's CLR distribution so a mid
        # main whose per-lane CLR is 50 lands in Legends on the mid page even
        # if his cross-lane total earns GOATs on the main board.
        lf_tier, _ = _assign_tiers(lf["clr"].reset_index(drop=True))
        lf["tier"] = lf_tier.values
        lf["position"] = lane  # this file IS the lane page; label with this lane
        _write_json(out_dir / "lanes" / f"{lane}.json", [_index_row(r) for _, r in lf.iterrows()])

    # players/<slug>.json  (every player, rated or not -- shared links still work)
    # Attach slug + rank + tier from the rated pool where present; unrated get
    # tier=null and their un-rated Overview rank.
    rated_by_slug = rated.set_index("slug")
    for _, row in ov.iterrows():
        slug = row["slug"]
        if slug in rated_by_slug.index:
            r_row = rated_by_slug.loc[slug].copy()
        else:
            r_row = row.copy()
            r_row["tier"] = None
        idx_global = slug_to_global_idx.get(slug, 0)
        lane = r_row.get("position")
        idx_lane = lane_slug_idx.get(lane, {}).get(slug) if isinstance(lane, str) else None
        lane_radar = radar_by_lane.get(lane, {}) if isinstance(lane, str) else {}
        detail = _detail_json(r_row, tourn_cols, years, radar_global, lane_radar,
                              idx_global if slug in slug_to_global_idx else 0,
                              idx_lane if slug in rated_by_slug.index else None)
        detail["rated"] = slug in rated_by_slug.index
        _write_json(out_dir / "players" / f"{slug}.json", detail)

    # tiers.json
    _write_json(out_dir / "tiers.json", {
        "tiers": tier_meta,
        "rated_min_games": cfg.rated_min_games,
        "rated_count": len(rated),
    })

    # meta.json
    meta = {
        "build_id": build_id,
        "generated": _dt.datetime.now().isoformat(timespec="seconds"),
        "years": [int(years[0]), int(years[-1])],
        "source_workbook": wb.name,
        "rated_min_games": cfg.rated_min_games,
        "beta": True,
        "counts": {
            "total": int(len(ov)),
            "rated": int(len(rated)),
            "by_lane": {lane: int((rated["position"] == lane).sum()) for lane in ROLES},
        },
        "about": _about_to_meta(about),
        "radar_axes": [{"key": a, "source": c, "inverted": inv} for a, c, inv in _RADAR_AXES],
    }
    _write_json(out_dir / "meta.json", meta)

    # glossary.json
    _write_json(out_dir / "glossary.json",
                {"entries": [{"term": k, "definition": v} for k, v in _GLOSSARY]})

    logger.info("[web] wrote bundle to %s", out_dir)
    return out_dir


def _write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(description="Build the LPS website JSON bundle.")
    ap.add_argument("--workbook", type=Path, default=None,
                    help="career workbook path (default: newest player_ratings_career_*.xlsx)")
    ap.add_argument("--out", type=Path, default=None,
                    help="output root (default: <repo>/frontend/public/data)")
    ap.add_argument("--build-id", type=str, default=None,
                    help="build id / subdirectory name (default: today's date)")
    ap.add_argument("--rated-min-games", type=int, default=RATED_MIN_GAMES,
                    help=f"rated-pool floor (default: {RATED_MIN_GAMES} games)")
    args = ap.parse_args()

    build_web_bundle(ExportConfig(
        workbook=args.workbook,
        out_root=args.out,
        build_id=args.build_id,
        rated_min_games=args.rated_min_games,
    ))


if __name__ == "__main__":
    main()
