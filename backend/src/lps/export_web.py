"""
Web export: turn the latest career workbook into the static JSON bundle the
rankings site consumes.

Reads `player_ratings_career_<first>_<last>.xlsx` (the workbook `career.py`
writes) and emits the bundle under `frontend/public/data/current/`. The
previous `current/` (if any) is auto-moved to
`frontend/data-archive/<its_build_id>/` -- past snapshots stay recoverable
locally, but only `current/` is tracked in git. The archive lives outside
`public/` on purpose: Next copies all of `public/` into the static export, and
the archive alone is tens of thousands of files (Cloudflare Pages caps a site
at 20,000). The current
build's own id + generated timestamp live in `current/meta.json`. Contents:

    index.json          -- slim ranking rows (the rated pool) for the board
    lanes/<lane>.json   -- same slim rows per position
    players/<slug>.json -- full detail per player (all columns, trajectory,
                          resume breakdown, splits, tier, radar percentiles)
    tiers.json          -- tier labels, colors, CLR cutoffs, memberships
    asof/<year>.json    -- the board frozen at the end of each past season (slim
                          rows; the site joins photos etc. from index.json)
    meta.json           -- build id, generated date, year range, weights, asof_years
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
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

import numpy as np
import pandas as pd

from .achievements import FULL2CODE, _ach_category, _MVP_AWARDS, load_achievements, load_awards
from .career import _career_layout, YEARS_DEFAULT, CLRConfig
from .config import INFO_DIR, PROJECT_ROOT
from .contribution import ROLES
from .export_excel import _GLOSSARY
from .io_oracle import load_oracle_all
from .player_identity import label_map, resolve_label
from .season import _LANE_NAMES

HALL_OF_LEGENDS_CSV = INFO_DIR / "hall_of_legends.csv"
PLAYER_STATUS_CSV = INFO_DIR / "player_status.csv"

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
# Inclusion floor for the public board: career games. ~One full season for a starter in any
# league (full-time rookies mostly log 35-75), so a rookie who starts a whole year is rated
# after it. Past-year boards keep it too, except while seasons were short (2011-12, when even
# the busiest 10% of players logged 12 / 39 games): there it's ASOF_SEASON_FRAC of the busiest
# season so far (90th-percentile games in one season), never below ASOF_MIN_GAMES_LOW.
RATED_MIN_GAMES = 30
ASOF_SEASON_FRAC = 0.5
ASOF_MIN_GAMES_LOW = 10
ASOF_MIN_BOARD = 20  # skip a past-year board with fewer rated players than this

# Tier ladder (top -> bottom).  Cutoffs are absolute CLR floors -- round
# numbers so the meaning of "Legend" (CLR >= 30) is stable across reruns
# rather than "top 20 today".  Membership counts drift as the data grows;
# the numbers don't.  Tune here.
_TIERS: list[dict] = [
    {"key": "goats", "label": "GOATs", "clr_min": 50.0, "color": "#f5c15b"},
    {"key": "legends", "label": "Legends", "clr_min": 30.0, "color": "#d97757"},
    {"key": "greats", "label": "Greats", "clr_min": 18.0, "color": "#a685e2"},
    {"key": "elite", "label": "Elite", "clr_min": 9.0, "color": "#6aa7e6"},
    {"key": "stars", "label": "Stars", "clr_min": 4.0, "color": "#5fbf94"},
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
    "photo", "photo_cx", "photo_ar", "photo_top", "photo_neck", "real_name", "titles",
    "rank_prev",  # rank on the previous season's board in the same view (null = unrated then)
    "clr_prev",   # CLR at the end of the previous season, same view (null = hadn't played yet)
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
    out = {display: raw for (raw, display, _fmt, _w) in lay}
    # Headers renamed since older workbooks were written (old header -> new header).
    for old, new in _LEGACY_HEADERS.items():
        if new in out:
            out.setdefault(old, out[new])
    return out


# The "...Semi" resume columns were renamed "...Elim" (they also hold quarterfinal and
# group-stage exits); map the old headers so workbooks built before the rename still load.
_LEGACY_HEADERS = {
    f"{pre}Semi{suf}": f"{pre}Elim{suf}"
    for pre in ("Wlds", "MSI", "Intl")
    for suf in ("#", "Pt")
}


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


def _load_yearly_breakdown() -> dict[str, dict[str, dict[str, float]]]:
    """Load the per-(player, year) component breakdown written by career.py."""
    path = PROJECT_ROOT / "player_yearly_breakdown.json"
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        return json.load(f)


TOP_CHAMPIONS = 10  # champions listed per profile (ranked by LPS earned on them)


def _load_champion_stats() -> dict[str, dict]:
    """Load the per-player champion splits + career box-score totals written by career.py."""
    path = PROJECT_ROOT / "player_champions.json"
    if not path.exists():
        logger.warning("[web] %s missing -- run lps.career; profiles get no champions", path.name)
        return {}
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _box_line(d: dict) -> dict:
    """Games/wins/LPS plus derived K/D/A, KDA ratio and CS/min (only where the data exists)."""
    out = {"games": d["games"], "wins": d["wins"], "lps": _round(d["lps"])}
    n = d.get("kda_games")
    if n:
        k, de, a = d["kills"], d["deaths"], d["assists"]
        out.update(
            kills=k, deaths=de, assists=a, kda_games=n,
            kda=_round((k + a) / max(de, 1)),
        )
    if d.get("cs_minutes"):
        out.update(cs=d["cs"], cspm=_round(d["cs"] / d["cs_minutes"]))
    return out


def _champion_block(stats: dict | None) -> tuple[list[dict], dict | None]:
    """(top champions by LPS, career box-score totals) for one player's detail JSON."""
    if not stats:
        return [], None
    champs = [
        {"champion": c["champion"], **_box_line(c)}
        for c in stats.get("champions", [])[:TOP_CHAMPIONS]
    ]
    totals = _box_line(stats["totals"]) if stats.get("totals") else None
    if totals is not None:
        totals["n_champions"] = len(stats.get("champions", []))
    return champs, totals


def _achievement_name_map(playernames: Iterable[str]) -> dict[str, str]:
    """{lowercase handle: workbook label} for matching achievements.csv `players`.

    Also registers bare-handle aliases for disambiguated names like "Knight (LPL)"
    so achievements CSV entries (which store plain handles) resolve correctly.
    Skips a bare handle that is already taken (non-disambiguated player with the
    same handle) or shared by several disambiguated names.
    """
    names_lc = {str(n).lower(): str(n) for n in playernames}
    _bare_count: dict[str, int] = {}
    for key in list(names_lc):
        if "(" in key:
            bare = re.sub(r"\s*\(.*\)\s*$", "", key).strip()
            _bare_count[bare] = _bare_count.get(bare, 0) + 1
    for key, canonical in list(names_lc.items()):
        if "(" in key:
            bare = re.sub(r"\s*\(.*\)\s*$", "", key).strip()
            if bare not in names_lc and _bare_count.get(bare, 0) == 1:
                names_lc[bare] = canonical
    return names_lc


def _resolve_achiever(
    handle: str,
    names_lc: dict[str, str],
    league_full: object = None,
    team: object = None,
    year: object = None,
) -> Optional[str]:
    """Leaguepedia handle on an achievement/award row -> workbook label (or None).

    Goes through the same identity bridge the résumé scoring uses
    (`player_identity.resolve_label`: handle + team + year, then handle + league), so a
    shared handle like "Knight" lands on "Knight (LPL)" vs "Knight (VCS)" by roster.
    Falls back to the plain / bare-handle name map.
    """
    h = str(handle or "").strip()
    if not h:
        return None
    region = FULL2CODE.get(str(league_full)) if league_full else None
    lab = resolve_label(h, region, team, year)
    if isinstance(lab, str) and lab.lower() in names_lc:
        return names_lc[lab.lower()]
    return names_lc.get(h.lower())


# achievements.csv `league_full` (or the page's leading token when that's blank) ->
# the short league key the frontend has an icon for (frontend/lib/icons.ts).
_LEAGUE_KEYS = {
    "lol champions korea": "LCK", "lck": "LCK",
    "lol the champions": "OGN", "ogn": "OGN", "champions": "OGN",
    "tencent lol pro league": "LPL", "lol pro league": "LPL", "lpl": "LPL",
    "lol emea championship": "LEC", "lec": "LEC",
    "europe league championship series": "EU LCS", "eu lcs": "EU LCS",
    "north america league championship series": "NA LCS", "na lcs": "NA LCS",
    "league of legends championship series": "LCS", "lcs": "LCS",
    "circuit brazilian league of legends": "CBLOL", "cblol": "CBLOL",
    "turkish championship league": "TCL", "tcl": "TCL",
    "lol japan league": "LJL", "ljl": "LJL",
    "vietnam championship series": "VCS", "vcs": "VCS",
    "pacific championship series": "PCS", "pcs": "PCS",
    "lol master series": "LMS", "lms": "LMS",
    "liga latinoamerica": "LLA", "lla": "LLA",
    "league of legends championship pacific": "LCP", "lcp": "LCP",
    "league of legends championship of the americas south": "LTA S",
    "league of legends championship of the americas north": "LTA N",
    "oceanic pro league": "OPL", "opl": "OPL",
    "league of legends circuit oceania": "LCO", "lco": "LCO",
}

# League renames folded together in the index-row title tally (old key -> current key).
_TALLY_LEAGUE = {"OGN": "LCK"}

_INTL_EVENT_KIND = {"WLDs": "worlds", "MSI": "msi", "FST": "first_stand", "EWC": "ewc"}


def _honors(playernames: Iterable[str]) -> dict[str, list[dict]]:
    """Every podium finish (champion / finalist / semifinalist) per player, newest first.

    [{year, kind, medal, league?, event?, page}] where kind is worlds | msi |
    first_stand | ewc | intl | domestic | cup; `league` is a short key (LCK, LPL, ...) for
    domestic rows and `event` the raw event code (IEM, MSC, KeSPA, ...) for other intl
    and cup rows. Powers the card's trophy shelf and the profile trophy case.
    """
    names_lc = _achievement_name_map(playernames)
    medal_of = {"champion": "gold", "finalist": "silver", "semifinalist": "bronze"}
    kind_rank = {"worlds": 0, "msi": 1, "first_stand": 2, "ewc": 3, "intl": 4, "domestic": 5, "cup": 6}
    medal_rank = {"gold": 0, "silver": 1, "bronze": 2}
    out: dict[str, list[dict]] = {}
    ach = load_achievements()
    if ach.empty or "players" not in ach.columns:
        return out
    ach = ach.copy()
    ach["year"] = pd.to_numeric(ach["year"], errors="coerce")
    ach = ach[ach["year"].notna() & ach["players"].notna()]
    for _, row in ach.iterrows():
        medal = medal_of.get(str(row.get("bucket") or ""))
        cat, ev = str(row.get("category") or ""), str(row.get("event") or "")
        if medal is None or cat not in ("intl", "domestic", "domestic_cup"):
            continue
        page = str(row.get("page") or "")
        h: dict = {"year": int(row["year"]), "medal": medal, "page": page or None}
        if cat == "intl":
            h["kind"] = _INTL_EVENT_KIND.get(ev, "intl")
            if h["kind"] == "intl":
                h["event"] = ev or None
        else:
            h["kind"] = "domestic" if cat == "domestic" else "cup"
            lf = str(row.get("league_full") or "").strip().lower()
            lead = re.split(r"[/ ]", page, maxsplit=1)[0].lower() if page else ""
            h["league"] = _LEAGUE_KEYS.get(lf) or _LEAGUE_KEYS.get(lead)
            if cat == "domestic_cup":
                h["event"] = ev or None
        for p in str(row.get("players") or "").split(";"):
            canonical = _resolve_achiever(p, names_lc, row.get("league_full"), row.get("team"), int(row["year"]))
            if canonical:
                out.setdefault(canonical, []).append(dict(h))
    for lst in out.values():
        lst.sort(key=lambda x: (-x["year"], kind_rank[x["kind"]], medal_rank[x["medal"]]))
    return out


def _title_tally(honors: list[dict]) -> dict | None:
    """{worlds, msi, first_stand, ewc, domestic, league, leagues} champion counts for the
    index row. `leagues` is domestic titles per league, most first ({"LCK": 3, "LPL": 1};
    titles whose league is unknown count only toward `domestic`); `league` is its top key
    (the pill's mark). Ties go to the more recent league. Predecessor names in
    `_TALLY_LEAGUE` count as their successor (OGN titles are LCK titles here; the
    per-year honors keep the historical name). None when no titles."""
    gold = [h for h in honors if h["medal"] == "gold"]
    if not gold:
        return None
    out: dict = {k: sum(h["kind"] == k for h in gold) for k in ("worlds", "msi", "first_stand", "ewc", "domestic")}
    # honors are newest first and most_common keeps first-seen order on ties.
    leagues = Counter(
        _TALLY_LEAGUE.get(h["league"], h["league"]) for h in gold if h["kind"] == "domestic" and h.get("league")
    ).most_common()
    out["leagues"] = dict(leagues) or None
    out["league"] = leagues[0][0] if leagues else None
    return {k: v for k, v in out.items() if v}


def _year_achievements(
    playernames: Iterable[str],
) -> dict[str, dict[str, dict]]:
    """Per-(playername, year) achievement badges for the trajectory chart.

    Two axes: **tournament family** (cup silhouette) × **placement** (medal
    tint). Tournament families:
      - worlds   : Worlds (intl / event=WLDs)
      - msi      : MSI (intl / event=MSI)
      - first_stand : First Stand (intl / event=FST)
      - ewc      : Esports World Cup (intl / event=EWC)
      - intl     : every other international event (IEM, MSC, Rift Rivals…)
      - domestic : LCK/LPL/LCS/LEC etc. split playoffs
      - cup      : domestic cups (KeSPA, Demacia, …)

    Placement medal comes from the achievement's `bucket`:
      - champion       → gold
      - finalist       → silver
      - semifinalist   → bronze
      - group/quarterfinalist → skipped (not a "notable" achievement)

    Awards are kept flat (no placement axis):
      - mvp      : any MVP-family award (worlds/msi/finals/regional MVP)
      - allpro   : any All-Pro selection

    Only non-zero entries are stored. Example shape:

        { "2016": {
            "worlds":   {"gold": 1},
            "msi":      {"gold": 1},
            "intl":     {"gold": 1},              # e.g. IEM 2016
            "domestic": {"gold": 1},              # LCK spring
            "cup":      {"gold": 1},              # KeSPA
            "mvp": 2,
            "allpro": 1,
          }, ... }

    Player names are matched case-insensitively against the semicolon-separated
    `players` list in achievements.csv (same rule as `achievements.score_bonuses`).
    """
    names_lc = _achievement_name_map(playernames)
    out: dict[str, dict[str, dict]] = {}

    def _bump_medal(canonical: Optional[str], year: int, family: str, medal: str) -> None:
        if canonical is None:
            return
        by_year = out.setdefault(canonical, {}).setdefault(str(year), {})
        fam = by_year.setdefault(family, {})
        fam[medal] = fam.get(medal, 0) + 1

    def _bump_award(canonical: Optional[str], year: int, kind: str) -> None:
        if canonical is None:
            return
        by_year = out.setdefault(canonical, {}).setdefault(str(year), {})
        by_year[kind] = by_year.get(kind, 0) + 1

    _BUCKET_TO_MEDAL = {
        "champion": "gold",
        "finalist": "silver",
        "semifinalist": "bronze",
    }

    def _family(category: str, event: str) -> Optional[str]:
        if category == "intl":
            return _INTL_EVENT_KIND.get(event, "intl")
        if category == "domestic":
            return "domestic"
        if category == "domestic_cup":
            return "cup"
        return None

    ach = load_achievements()
    if not ach.empty and "players" in ach.columns:
        ach = ach.copy()
        ach["year"] = pd.to_numeric(ach["year"], errors="coerce")
        ach = ach[ach["year"].notna() & ach["players"].notna()]
        ach["year"] = ach["year"].astype(int)
        for _, row in ach.iterrows():
            medal = _BUCKET_TO_MEDAL.get(str(row.get("bucket") or ""))
            if medal is None:
                continue  # group / quarterfinalist / unknown — skip
            fam = _family(str(row.get("category") or ""), str(row.get("event") or ""))
            if fam is None:
                continue
            year = int(row["year"])
            for p in str(row.get("players") or "").split(";"):
                who = _resolve_achiever(p, names_lc, row.get("league_full"), row.get("team"), year)
                _bump_medal(who, year, fam, medal)

    aw = load_awards()
    if not aw.empty and "playername" in aw.columns and "award" in aw.columns:
        aw = aw.copy()
        aw["year"] = pd.to_numeric(aw["year"], errors="coerce")
        aw = aw[aw["year"].notna() & aw["playername"].notna()]
        aw["year"] = aw["year"].astype(int)
        for _, row in aw.iterrows():
            kind = "mvp" if str(row.get("award") or "") in _MVP_AWARDS else "allpro"
            who = _resolve_achiever(row["playername"], names_lc, row.get("league_full"))
            _bump_award(who, int(row["year"]), kind)

    return out


def _year_rankings(
    lanes: dict[str, pd.DataFrame], years: tuple[int, ...]
) -> dict[str, dict[str, dict[str, int]]]:
    """Per-(player, year) HN-style peer ranks — mirrors `career._high_noon`
    exactly, but keeps *every* participating year rather than only aggregating
    the best N.

    Each year's per-lane per-year `total_score` (the workbook's `yYYYY` col on
    the lane sheets) is ranked in two ways: globally across all lanes, and
    within lane. For players who split roles inside a year we keep the *best*
    (lowest) rank across their lane rows — same choice HN makes. Returns:

        { playername: { "2013": {"global": 5, "lane": 1}, ... } }

    Only years the player actually participated in appear. Zero-LPS rows are
    dropped (they aren't 'seasons' for HN purposes).
    """
    stacked: list[pd.DataFrame] = []
    for lane, df in lanes.items():
        if "playername" not in df.columns:
            continue
        for y in years:
            col = f"y{y}"
            if col not in df.columns:
                continue
            sub = df[["playername", col]].rename(columns={col: "lps"})
            sub = sub[sub["lps"].notna() & (sub["lps"] != 0)]
            if not len(sub):
                continue
            sub = sub.assign(lane=lane, year=int(y))
            stacked.append(sub[["playername", "lane", "year", "lps"]])
    if not stacked:
        return {}
    allrows = pd.concat(stacked, ignore_index=True)
    allrows["rank_global"] = (
        allrows.groupby("year")["lps"].rank(ascending=False, method="min").astype(int)
    )
    allrows["rank_lane"] = (
        allrows.groupby(["year", "lane"])["lps"]
        .rank(ascending=False, method="min")
        .astype(int)
    )
    agg = (
        allrows.groupby(["playername", "year"], as_index=False)
        .agg(rank_global=("rank_global", "min"), rank_lane=("rank_lane", "min"))
    )
    out: dict[str, dict[str, dict[str, int]]] = {}
    for name, sub in agg.groupby("playername", sort=False):
        yr_map: dict[str, dict[str, int]] = {}
        for _, r in sub.iterrows():
            yr_map[str(int(r["year"]))] = {
                "global": int(r["rank_global"]),
                "lane": int(r["rank_lane"]),
            }
        out[str(name)] = yr_map
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
    """14-category (count, pts) breakdown that sums (pts) to `resume_bonus`."""
    cats = [
        ("wlds_title",      "rb_wlds_title_n",         "rb_wlds_title_pts"),
        ("wlds_final",      "rb_wlds_final_n",         "rb_wlds_final_pts"),
        ("wlds_semi",       "rb_wlds_semi_n",          "rb_wlds_semi_pts"),
        ("msi_title",       "rb_msi_title_n",          "rb_msi_title_pts"),
        ("msi_final",       "rb_msi_final_n",          "rb_msi_final_pts"),
        ("msi_semi",        "rb_msi_semi_n",           "rb_msi_semi_pts"),
        ("othr_intl_champ", "rb_othr_intl_champ_n",   "rb_othr_intl_champ_pts"),
        ("othr_intl_final", "rb_othr_intl_final_n",   "rb_othr_intl_final_pts"),
        ("othr_intl_semi",  "rb_othr_intl_semi_n",    "rb_othr_intl_semi_pts"),
        ("dom_champ",       "rb_dom_champ_n",          "rb_dom_champ_pts"),
        ("dom_final",       "rb_dom_final_n",          "rb_dom_final_pts"),
        ("dom_cup",         "rb_dom_cup_n",            "rb_dom_cup_pts"),
        ("mvp",             "rb_mvp_n",                "rb_mvp_pts"),
        ("allpro",          "rb_allpro_n",             "rb_allpro_pts"),
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
                    "photo", "photo_caption", "real_name", "country",
                    "current_team", "current_league", "current_year",
                    "region_elo", "n_years", "first_year", "last_year", "games",
                    "win_rate", "clr", "tier",
                    "hall_of_legends", "hol_year", "is_retired", "is_active"]
_DETAIL_CLR = ["career_value", "pace_value", "peak_value", "resume_bonus",
               "intl_bonus", "title_bonus", "award_bonus"]
_DETAIL_CAREER_LPS = ["total_score", "lps_per_year", "peak_year", "peak_lps",
                      "peak_years", "peak_band_avg"]
_DETAIL_PHASE = ["reg_pts", "playoff_pts", "tourn_pts"]
_DETAIL_COMPONENT = ["base_pts", "contrib_pts", "wbonus_pts"]
_DETAIL_SOURCES = ["kills_pts", "deaths_pts", "assists_pts", "damage_pts"]
_DETAIL_RATES = ["pts_per_game", "pts_per_game_w", "clutch_gap", "avg_contrib",
                 "avg_resid", "avg_p_model", "sched_strength"]
_DETAIL_HIGH_NOON = ["hn_lane_best", "hn_lane", "hn_lane_yrs",
                     "hn_global_best", "hn_global", "hn_global_yrs"]


def _detail_json(row: pd.Series, tourn_cols: list[str], years: tuple[int, ...],
                 radar_global: dict, radar_lane: dict, idx_in_global: int,
                 idx_in_lane: Optional[int],
                 hn_year_ranks: dict[str, dict[str, int]],
                 year_achievements: dict[str, dict],
                 year_teams: dict[str, list[dict[str, str]]],
                 yearly_breakdown: dict[str, dict[str, float]] | None = None,
                 honors: list[dict] | None = None) -> dict:
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
        "hn_year_ranks": hn_year_ranks,
        "year_achievements": year_achievements,
        "year_teams": year_teams,
        "honors": honors or [],
        "resume_breakdown": _resume_breakdown(row),
        "tournaments": _tournament_dict(row, tourn_cols),
        "trajectory": _trajectory(row, years),
        "trajectory_breakdown": yearly_breakdown or {},
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
# Glossary -> glossary.json (the site's /about page)
# ---------------------------------------------------------------------------
# export_excel._GLOSSARY is written for the workbook (column codes, CLI flags, file paths). The
# site gets its own version written for a reader with no background in the project: each
# workbook term (kept as the key, since the site derives each entry's anchor from it, e.g.
# /about#clr) maps to a readable label and a plain-English definition. The numbers quoted come
# from the run's About sheet where it records them (weights, decay, scoring knobs) and from the
# config defaults otherwise, so the page quotes the values that built the board. Terms missing
# here go out with the workbook wording (and a warning).

# Résumé events in display order: (event code in achievements.csv, site name).
_RESUME_EVENTS: list[tuple[str, str]] = [
    ("WLDs", "World Championship"),
    ("MSI", "Mid-Season Invitational"),
    ("FST", "First Stand"),
    ("EWC", "Esports World Cup"),
    ("OGN", "OGN Champions (2012)"),
    ("MSC", "Mid-Season Cup (2020)"),
    ("LTA", "LTA Championship"),
    ("RR", "Rift Rivals"),
    ("IPL", "IGN Pro League"),
    ("IEM", "Intel Extreme Masters"),
    ("ASI", "Asia Invitational"),
    ("IWCI", "International Wildcard Invitational"),
    ("MLG", "MLG Pro Circuit"),
    ("DH", "DreamHack"),
    ("KeSPA", "KeSPA Cup (Korea)"),
    ("DCup", "Demacia Cup (China)"),
]
_RESUME_CUPS = {"KeSPA", "DCup"}
_RESUME_ROUNDS: list[tuple[str, str]] = [
    ("champion", "Champion"),
    ("finalist", "Runner-up"),
    ("semifinalist", "Semifinal"),
    ("quarterfinalist", "Quarterfinal"),
    ("group", "Group stage"),
]
_AWARD_LABELS: list[tuple[str, str]] = [
    ("worlds_finals_mvp", "Worlds Finals MVP"),
    ("worlds_mvp", "Worlds tournament MVP"),
    # No worlds_all_pro row: Riot names no Worlds All-Pro team and Leaguepedia has none on
    # record, so the scored token never fires. Keep it off the site's points table.
    ("msi_finals_mvp", "MSI Finals MVP"),
    ("msi_mvp", "MSI tournament MVP"),
    ("msi_all_pro", "MSI All-Pro team"),
    ("intl_finals_mvp", "Finals MVP, other international event"),
    ("intl_mvp", "Tournament MVP, other international event"),
    ("intl_all_pro", "All-Pro team, other international event"),
    ("regional_mvp", "Domestic season MVP"),
    ("domestic_finals_mvp", "Domestic Finals MVP"),
    ("all_pro_1", "Domestic All-Pro 1st team"),
    ("all_pro_2", "Domestic All-Pro 2nd team"),
    ("all_pro_3", "Domestic All-Pro 3rd team"),
]


def _about_nums(about: dict, key: str) -> list[float]:
    """Every number in an About-sheet value, ignoring a trailing '(note)' ('1.3, 0.8  (x)')."""
    raw = about.get(key)
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return [float(raw)]
    text = str(raw or "").split("(")[0]
    return [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", text)]


def _about_num(about: dict, key: str, default: float, idx: int = 0) -> float:
    nums = _about_nums(about, key)
    return nums[idx] if len(nums) > idx else float(default)


def _glossary_params(about: dict) -> dict:
    """The scoring settings the glossary quotes: the run's About sheet, else config defaults."""
    from .achievements import BonusConfig
    from .scoring import ScoreWeights

    clr, bonus, sw = CLRConfig(), BonusConfig(), ScoreWeights()
    wkey = "Weights (w_career, w_pace, w_peak, w_bonus)"
    p = {
        "w_career": _about_num(about, wkey, clr.w_career, 0),
        "w_pace": _about_num(about, wkey, clr.w_pace, 1),
        "w_peak": _about_num(about, wkey, clr.w_peak, 2),
        "w_bonus": _about_num(about, wkey, bonus.w_bonus, 3),
        "decay": _about_num(about, "repeat_decay", bonus.repeat_decay),
        "alpha": _about_num(about, "alpha (baseline)", sw.alpha),
        "beta": _about_num(about, "beta (win bonus)", sw.beta),
        "region_exp": _about_num(about, "region_exp (region scaling)", sw.region_exp),
        "w_playoff": _about_num(about, "w_playoff (playoff mult)", sw.w_playoff),
        "intl_weight": _about_num(about, "intl_weight", 2.0),
        "divisor": clr.career_divisor,
        "pace_prior": clr.pace_prior_games,
        "peak_bonus": clr.peak_len_bonus,
        "era": tuple(clr.era_mults),
    }
    m = re.search(r"x\s*\(([^)]*)\)", str(about.get("Era adjustment (3 eras)", "")))
    if m:
        era = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", m.group(1))]
        if len(era) == 3:
            p["era"] = tuple(era)
    return p


def _fmt(x: float, nd: int = 3) -> str:
    """Compact number for prose: 3.0 -> '3', 0.375 -> '0.375', 0.1 -> '0.1'."""
    return f"{round(x, nd):g}"


def _resume_scoring(p: dict, year: int) -> dict:
    """The résumé point tables shown on /about, in CLR points (already x w_bonus).

    Mirrors achievements.score_bonuses: tournament champion = anchor (Worlds/MSI) else
    champ_per_weight x the event's LPS tournament weight, scaled down the bracket by
    intl_bucket; domestic split titles = base x (league Elo / top Elo); awards = base x
    award_weight (x league strength for domestic awards)."""
    from .achievements import FLAT_AWARDS, BonusConfig
    from .scoring import load_league_elos
    from .season import _viewership_weights

    cfg, wb = BonusConfig(), p["w_bonus"]
    tw = _viewership_weights()
    events = []
    for code, name in _RESUME_EVENTS:
        anchored = code in cfg.intl_champion_anchors
        champ = cfg.intl_champion_anchors.get(code, cfg.champ_per_weight * tw.get(code, 0.0))
        events.append(
            {
                "code": code,
                "name": name,
                "kind": "cup" if code in _RESUME_CUPS else "intl",
                "tournament_weight": round(float(tw.get(code, 0.0)), 3),
                "anchored": anchored,
                "points": {
                    r: round(champ * cfg.intl_bucket.get(r, 0.0) * wb, 3) for r, _ in _RESUME_ROUNDS
                },
            }
        )

    elos = load_league_elos(year) or {}
    top = max(elos.values()) if elos else 0.0
    leagues = [
        {
            "league": lg,
            "strength": round(e / top, 3),
            "champion": round(cfg.domestic_champion * wb * e / top, 3),
            "finalist": round(cfg.domestic_finalist * wb * e / top, 3),
        }
        for lg, e in sorted(elos.items(), key=lambda kv: -kv[1])
        if top
    ]

    awards = [
        {
            "key": k,
            "label": lbl,
            "points": round(cfg.award_points.get(k, 0.0) * cfg.award_weight * wb, 3),
            "scaled": k not in FLAT_AWARDS,
        }
        for k, lbl in _AWARD_LABELS
    ]

    d = p["decay"]
    wlds = cfg.intl_champion_anchors.get("WLDs", 6.0) * wb
    steps = [round(wlds * d**i, 3) for i in range(6)]
    return {
        "weight": wb,
        "repeat_decay": d,
        "rounds": [
            {"key": r, "label": lbl, "share": cfg.intl_bucket.get(r, 0.0)} for r, lbl in _RESUME_ROUNDS
        ],
        "champ_per_weight": cfg.champ_per_weight,
        "events": events,
        "domestic": {
            "year": int(year),
            "champion": round(cfg.domestic_champion * wb, 3),
            "finalist": round(cfg.domestic_finalist * wb, 3),
            "leagues": leagues,
        },
        "awards": awards,
        "example": {"label": "Six Worlds titles", "steps": steps, "total": round(sum(steps), 3)},
    }


def _web_glossary_text(p: dict, rs: dict) -> dict[str, tuple[str, str]]:
    """term -> (site label, plain-English definition). See the block comment above."""
    f = _fmt
    wc, wp, wk, wb, d = p["w_career"], p["w_pace"], p["w_peak"], p["w_bonus"], p["decay"]
    e1, e2, e3 = p["era"]
    pb = p["peak_bonus"]
    ev = {e["code"]: e for e in rs["events"]}

    def pts(code: str, rnd: str) -> str:
        return f(ev[code]["points"][rnd], 3)

    others = [e for e in rs["events"] if e["kind"] == "intl" and not e["anchored"]]
    o_lo = min(e["points"]["champion"] for e in others)
    o_hi = max(e["points"]["champion"] for e in others)
    aw = {a["key"]: a["points"] for a in rs["awards"]}
    dom = rs["domestic"]
    yr = dom["year"]
    lg = dom["leagues"][:4]
    dom_eg = ", ".join(f"{x['league']} {f(x['champion'], 2)}" for x in lg)
    steps = rs["example"]["steps"]
    step_txt = ", ".join(f(s) for s in steps[:4])

    # Region factor examples for the latest year (strongest league, then a few others).
    rexp = p["region_exp"]
    rf = []
    if lg:
        top_strength = 0.5 ** rexp
        rf.append(f"facing the strongest league gives {f(top_strength, 2)}")
        from .scoring import load_league_elos

        elos = load_league_elos(yr) or {}
        peak = max(elos.values()) if elos else 0.0
        for x in dom["leagues"][2:4]:
            e = elos.get(x["league"])
            if e is None:
                continue
            base = 1.0 / (1.0 + 10 ** ((peak - e) / 400.0))
            rf.append(f"facing the {x['league']} gives {f(base ** rexp, 2)}")
    rf_txt = f" (in {yr}, " + ", ".join(rf) + ")" if rf else ""

    return {
        "Rank": (
            "Rank",
            "A player's place on the all-time board, ordered by Career Legend Rating (CLR). The "
            "overall board ranks every lane together; each lane tab ranks players only against "
            "others in that position. The arrows show how far a player has moved since the board "
            "as it stood at the end of the previous season.",
        ),
        "Teams / Leagues / Lanes (by CLR)": (
            "Where the value came from",
            "The teams, leagues and lanes a player's CLR was earned with, largest first (for "
            "example T1 245.3, DAMWON Gaming 30.1). The performance part of CLR (everything "
            "except the résumé) is shared out across the player's seasons in proportion to each "
            "season's LPS, and each season's résumé points go to the season that earned them. "
            "Each season is then credited to the team, league and lane the player played that "
            "year, so the pieces add up exactly to the player's CLR. A player who changed teams "
            "mid-season has that whole season credited to their main team for the year.",
        ),
        "CLR": (
            "Career Legend Rating (CLR)",
            f"The headline number the all-time board is ranked by. It adds up four weighted "
            f"parts: CLR = {f(wc)} × Career value + {f(wp)} × Pace value + {f(wk)} × Peak value + "
            f"{f(wb)} × Résumé. The first three are built from LPS, the season performance score "
            f"described below, and each is on the scale of roughly one season of LPS, so the "
            f"weights compare directly. Career value rewards longevity, pace value rewards how "
            f"much a player produced per season, peak value rewards how high their best seasons "
            f"were, and the résumé rewards trophies, deep international runs and awards. The "
            f"idea is borrowed from JAWS, baseball's Hall of Fame yardstick, which blends career "
            f"totals with peak. Profiles show each part already multiplied by its weight, so the "
            f"four numbers add straight up to CLR.",
        ),
        "CareerVal": (
            "Career value",
            f"Total career production, scaled to a typical career. Career LPS (every season's "
            f"LPS added together) is divided by {f(p['divisor'])}, the average career length in "
            f"years of the top 100 retired players. Longer careers keep a proportional edge; "
            f"shorter ones score less. Before the seasons are added up, each is multiplied by an "
            f"era factor, because early seasons had fewer events to earn points in: ×{f(e1, 3)} "
            f"for 2014 and earlier, ×{f(e2, 3)} for 2015–2017 and ×{f(e3, 3)} from 2018 on. Shown "
            f"multiplied by its CLR weight ({f(wc)}).",
        ),
        "PaceVal": (
            "Pace value",
            f"How much a player produced per season: career LPS divided by the number of "
            f"seasons played. Short careers are noisy, so this is blended with the average "
            f"player's figure, trusting the player's own number more the more they have played "
            f"(their share is games ÷ (games + {f(p['pace_prior'])}), counting games adjusted for "
            f"schedule length and stakes). A brilliant short career still scores well, but a "
            f"handful of lucky games can't top the board. It balances career value, which "
            f"rewards length. Shown multiplied by its CLR weight ({f(wp)}).",
        ),
        "PeakVal": (
            "Peak value",
            f"How high a player's best stretch of seasons was. Sort the player's seasons from "
            f"best to worst by LPS (era-adjusted, as in career value). For each number of "
            f"seasons k, take the average of the best k and add a length bonus of {f(pb)} × (the "
            f"k-th best season) × (k − 1); peak value is the largest of these. A one-season peak "
            f"scores exactly that season, while k equally good seasons of S score S × (1 + "
            f"{f(pb)} × (k − 1)): three seasons of 10 score {f(10 * (1 + pb * 2))}. A weaker "
            f"season only joins the peak if it is close to the others (about three-quarters of "
            f"the best or better). Improving any season can never lower peak value. Shown "
            f"multiplied by its CLR weight ({f(wk)}).",
        ),
        "PeakYrs": (
            "Peak years",
            "How many seasons make up the player's peak: the k that gives the highest peak "
            "value. Always at least 1, since the best season always counts.",
        ),
        "PeakAvg": (
            "Peak average",
            "The average LPS of the player's peak seasons, before the length bonus. Peak value "
            "is this plus the bonus for each extra peak season.",
        ),
        "Resume": (
            "Résumé",
            f"Points for trophies, deep international runs and individual awards: big-stage "
            f"results that a box score can't see. It isn't a model; every achievement has a "
            f"fixed point value, listed in full in the tables below. A Worlds title is worth "
            f"{pts('WLDs', 'champion')} CLR, an MSI title {pts('MSI', 'champion')}, a domestic "
            f"league title up to {f(dom['champion'])}, and a domestic season MVP up to "
            f"{f(aw['regional_mvp'])}. Team results are credited in full to every player on the "
            f"roster (not split between them), and each lands in the season and lane the player "
            f"played that year. Winning the same thing again is worth less each time: the best "
            f"one counts in full and each repeat is worth {f(d)}× the one before, so six Worlds "
            f"titles add {step_txt}, … = {f(rs['example']['total'])} rather than "
            f"{f(6 * steps[0])}. Résumé points are not adjusted for era or schedule. The values "
            f"above are after the résumé's CLR weight ({f(wb)}); profiles show the résumé the "
            f"same way, so career + pace + peak + résumé = CLR.",
        ),
        "Intl": (
            "International results",
            f"Points for how far a player's team went at events between regions: Worlds, MSI, "
            f"First Stand, the Esports World Cup, the Mid-Season Cup, the LTA Championship, Rift "
            f"Rivals, IEM, IPL, MLG, DreamHack, the Asia Invitational, the International Wildcard "
            f"Invitational and the 2012 OGN Champions. A Worlds title is worth "
            f"{pts('WLDs', 'champion')} CLR and an MSI title {pts('MSI', 'champion')}. Every "
            f"other event's title is worth {f(rs['champ_per_weight'] * wb, 3)} × its tournament "
            f"weight, the same importance weight LPS gives that event's games (based on its "
            f"viewership next to Worlds, or set by hand for old or small events), which puts "
            f"them between {f(o_lo)} and {f(o_hi)}. Lower finishes earn a fixed share of the "
            f"title value: runner-up ½, semifinal ¼, quarterfinal ⅛, group stage 4%. So Worlds "
            f"pays {pts('WLDs', 'finalist')} for a lost final, {pts('WLDs', 'semifinalist')} "
            f"for a semifinal, {pts('WLDs', 'quarterfinalist')} for a quarterfinal and "
            f"{pts('WLDs', 'group')} for a group-stage exit.",
        ),
        "Titles": (
            "Domestic titles and cups",
            f"Points for domestic league playoffs and cups. Winning a split's playoffs is worth "
            f"{f(dom['champion'])} CLR and losing the final {f(dom['finalist'])}, each multiplied "
            f"by the league's strength that year: its regional Elo rating divided by the "
            f"strongest league's. In {yr} a title is worth {dom_eg}. A league with no rating that "
            f"year (one that sent no team to international events) scores 0. The KeSPA Cup "
            f"(Korea) and Demacia Cup (China) are scored like international events, by their "
            f"tournament weight: a KeSPA Cup win is worth {pts('KeSPA', 'champion')}.",
        ),
        "Awards": (
            "Individual awards",
            f"Points for MVP awards and All-Pro selections, pulled from Leaguepedia. Honors at "
            f"Worlds, MSI and other international events are flat; domestic ones are multiplied "
            f"by league strength, like titles. A Worlds Finals MVP or tournament MVP is worth "
            f"{f(aw['worlds_finals_mvp'])} CLR, a domestic season MVP up to "
            f"{f(aw['regional_mvp'])} and a domestic All-Pro 1st-team pick up to "
            f"{f(aw['all_pro_1'])}. Awards are deliberately small next to team results; they "
            f"mostly separate teammates who shared the same trophies.",
        ),
        "Resume breakdown (# / Pt columns)": (
            "Résumé breakdown",
            "Profiles split the résumé into 14 categories, each showing how many the player "
            "earned and the CLR points they're worth after repeats are discounted. The "
            "categories add up exactly to the résumé: Worlds (title, runner-up, semifinal or "
            "earlier), MSI (the same three), other international events (the same three), "
            "domestic league titles, domestic runner-ups, domestic cups, MVP awards and All-Pro "
            "selections. Only achievements worth points are counted, so a title in a league "
            "with no rating that year doesn't appear. Two entries in one category can be worth "
            "different amounts, because of league strength and the repeat discount.",
        ),
        "WldsChmp# / WldsChmpPt": (
            "Worlds titles",
            f"World Championships won. The first is worth {pts('WLDs', 'champion')}; each "
            f"further title is worth {f(d)}× the one before ({step_txt}, …).",
        ),
        "WldsFin# / WldsFinPt": (
            "Worlds runner-up",
            f"Worlds finals lost: {pts('WLDs', 'finalist')} for the first, discounted for repeats.",
        ),
        "WldsElim# / WldsElimPt": (
            "Worlds, out before the final",
            f"Every Worlds that ended before the final: semifinals ({pts('WLDs', 'semifinalist')}), quarterfinals "
            f"({pts('WLDs', 'quarterfinalist')}) and group-stage exits "
            f"({pts('WLDs', 'group')}). Each round is discounted for repeats on its own.",
        ),
        "MSIChmp# / MSIChmpPt": (
            "MSI titles",
            f"Mid-Season Invitationals won: {pts('MSI', 'champion')} for the first, discounted "
            f"for repeats.",
        ),
        "MSIFin# / MSIFinPt": (
            "MSI runner-up",
            f"MSI finals lost: {pts('MSI', 'finalist')} for the first, discounted for repeats.",
        ),
        "MSIElim# / MSIElimPt": (
            "MSI, out before the final",
            f"Every MSI that ended before the final: semifinals ({pts('MSI', 'semifinalist')}), quarterfinals "
            f"({pts('MSI', 'quarterfinalist')}) and group-stage exits "
            f"({pts('MSI', 'group')}).",
        ),
        "IntlChmp# / IntlChmpPt": (
            "Other international titles",
            f"Titles at every other event between regions (First Stand, the Esports World Cup, "
            f"Rift Rivals, IEM and the rest), worth {f(o_lo)} to {f(o_hi)} depending on the "
            f"event's weight (see the table above).",
        ),
        "IntlFin# / IntlFinPt": (
            "Other international runner-up",
            "Finals lost at those events: half the event's title value.",
        ),
        "IntlElim# / IntlElimPt": (
            "Other international, out before the final",
            "Runs at those events that ended before the final, in the semifinal, quarterfinal or group stage: ¼, ⅛ and 4% of "
            "the event's title value.",
        ),
        "DomChmp# / DomChmpPt": (
            "Domestic league titles",
            f"Domestic split-playoff wins, up to {f(dom['champion'])} each, scaled by league "
            f"strength. All of a player's league titles share one repeat discount, whichever "
            f"league they came from.",
        ),
        "DomFin# / DomFinPt": (
            "Domestic runner-up",
            f"Domestic playoff finals lost, up to {f(dom['finalist'])} each, scaled by league "
            f"strength and discounted for repeats.",
        ),
        "DomCup# / DomCupPt": (
            "Domestic cups",
            f"KeSPA Cup and Demacia Cup finishes at every round, scored by the cup's tournament "
            f"weight (a KeSPA Cup win is {pts('KeSPA', 'champion')}, a Demacia Cup win "
            f"{pts('DCup', 'champion')}).",
        ),
        "MVP# / MVPPt": (
            "MVP awards",
            "Domestic season MVP and Finals MVP, plus Finals MVP and tournament MVP at Worlds, "
            "MSI and other international events.",
        ),
        "AllPro# / AllProPt": (
            "All-Pro selections",
            "Domestic All-Pro 1st, 2nd and 3rd teams, plus the All-Pro teams at Worlds, MSI and "
            "other international events.",
        ),
        "LPS": (
            "League Performance Score (LPS)",
            f"A player's score for one season, built game by game. Every game earns three "
            f"things: a win credit of {f(p['alpha'])} if the team won the series; the player's "
            f"contribution, meaning how much their play moved the team's chance of winning "
            f"compared with an average player in the same spot; and a win bonus for beating the "
            f"odds. That total is multiplied by a region factor for the strength of the "
            f"opposition, so the same performance is worth more against stronger leagues. The "
            f"games of a best-of series are averaged into one match score. Matches are then "
            f"added up across the season: a full regular season is worth the same in every "
            f"league however long its schedule, a full playoff run is worth {f(p['w_playoff'])}× "
            f"that, and international events count by importance (Worlds 1, MSI "
            f"{f(ev['MSI']['tournament_weight'])}, and so on). Last, each season is rescaled to a "
            f"common schedule length, so seasons from different years are worth the same and "
            f"add up to career LPS. Playing more, going deeper and winning bigger events all "
            f"raise LPS.",
        ),
        "LPS/Gm": (
            "LPS per game",
            "The average score per game (win credit + contribution + win bonus, times the "
            "region factor), with every game counted equally. Unlike season LPS it doesn't grow "
            "with more games, so it measures quality rather than volume.",
        ),
        "LPS/Gm·wt": (
            "LPS per game, stakes-weighted",
            "The average score per game, with each game weighted the way season LPS weights it, "
            "so playoff and international games count for more. Higher than plain LPS per game "
            "means the player raised their level when more was on the line.",
        ),
        "Con/Gm": (
            "Contribution per game",
            "Just the contribution part of the per-game score (including the region factor), "
            "with every game counted equally.",
        ),
        "Con/Gm·wt": (
            "Contribution per game, stakes-weighted",
            "Contribution per game, weighted the same way as stakes-weighted LPS per game. "
            "Higher than plain contribution per game means the player contributed more in "
            "bigger games.",
        ),
        "Baseline": (
            "Win credit (baseline)",
            f"The flat part of each game's score: {f(p['alpha'])} points times the region "
            f"factor, paid only when the player's team wins the series. The region factor is "
            f"the chance the opponent's league would beat that year's strongest league (from "
            f"regional Elo ratings), raised to the power {f(rexp)}{rf_txt}. The factor "
            f"multiplies the whole game score, not just this part, which is how LPS rewards "
            f"competing against strong opposition.",
        ),
        "Contribution": (
            "Contribution",
            "The heart of LPS: how much the player's own play moved their team's chance of "
            "winning. Two models are trained on pro games every season. The first predicts the "
            "stat line (kills, deaths, assists, damage) an average player would "
            "produce in the same position and game situation. The second predicts a team's "
            "chance of winning from what its players actually produced. A player's contribution "
            "in a game is how much the predicted win chance changes when their expected stat "
            "line is swapped for their real one. Box scores under-credit supports and junglers, "
            "so each lane's per-game contributions are then mapped onto one shared scale across "
            "all years: a 90th-percentile game is worth the same in every role.",
        ),
        "WinBonus": (
            "Win bonus",
            f"Credit for winning when the stats said you shouldn't: {f(p['beta'])} × (result − "
            f"predicted chance of winning), where result is 1 for a win and 0 for a loss, times "
            f"the region factor. Winning a game the model gave a 30% chance adds "
            f"{f(p['beta'] * 0.7, 3)} before the region factor; losing one it gave 80% takes "
            f"away {f(p['beta'] * 0.8, 3)}.",
        ),
        "Kills/Deaths/Assists/Damage": (
            "Contribution by stat",
            "Contribution split by the stat that produced it; the four add up to contribution.",
        ),
        "AvgContrib": (
            "Average contribution",
            "Contribution per game on the shared cross-lane scale, before the region factor and "
            "season weighting. Comparable across roles.",
        ),
        "Intangibles": (
            "Intangibles",
            "A team number, not a player one: how much more the team won than its box scores "
            "predicted, per game (result − predicted chance of winning). It picks up what stats "
            "miss, like macro play, shotcalling and closing out games. It's identical for all "
            "five teammates, so it says nothing about any one player.",
        ),
        "Clutch": (
            "Clutch",
            "Contribution per game in high-stakes matches minus contribution per game in the "
            "regular season. High stakes means domestic playoffs and international events; "
            "international games count double, with extra weight by round (final 3×, semifinal "
            "2×, quarterfinal 1.5×, group stage 1×). Small samples are pulled toward the typical "
            "player, as if everyone had 20 extra average games, so a handful of games can't "
            "dominate. Positive means the player raised their game in big moments; negative "
            "means they faded. Unlike intangibles, this is the player's own number.",
        ),
        "Regular / Playoffs / Tourneys": (
            "Regular season, playoffs, tournaments",
            f"Season LPS split by phase. A full regular season is worth the same in every league; "
            f"a full playoff run is worth {f(p['w_playoff'])}× that. International events and "
            f"domestic cups are weighted by importance (Worlds 1, MSI "
            f"{f(ev['MSI']['tournament_weight'])}, First Stand {f(ev['FST']['tournament_weight'])}, "
            f"KeSPA Cup {f(ev['KeSPA']['tournament_weight'])}), a champion's full run is worth the "
            f"event's weight however many matches the bracket has, and the year's deepest "
            f"international run is worth {f(p['intl_weight'])}× a full regular season. The three "
            f"phases add up to LPS.",
        ),
        "AvgWinProb": (
            "Average win probability",
            "The model's average predicted chance of winning for the player's team across their "
            "games: a measure of how strong their team was.",
        ),
        "SoS": (
            "Strength of schedule",
            "How strong the opponents' leagues were on average, as the chance each would beat "
            "that year's strongest league (0.5 = the strongest league itself). Higher means "
            "tougher opposition.",
        ),
        "BestGame / WorstGame": (
            "Best and worst game",
            "The player's highest and lowest single-game contribution, in win probability.",
        ),
        "#Trn": (
            "Tournaments played",
            "How many different international events and domestic cups the player appeared in.",
        ),
        "RegElo": (
            "Region Elo",
            "The strength of the player's home league that season: its year-end Elo rating, "
            "computed from each region's results against other regions at international "
            "events. Higher means a stronger region.",
        ),
        "<Tournament>": (
            "LPS by tournament",
            "LPS earned at one specific event (WLDs = Worlds, MSI = Mid-Season Invitational, EWC "
            "= Esports World Cup, FST = First Stand, KeSPA and DCup = the Korean and Chinese "
            "domestic cups). Together they add up to the tournaments phase.",
        ),
        "BestRkLane / BestRkGlob": (
            "Best season rank",
            "The player's best single-season finish: each year, rated players are ranked by "
            "that season's LPS (1 = best that year), within their lane and across everyone. A "
            "companion number, not part of CLR. Lower is better.",
        ),
        "HN3Lane / HN3Glob": (
            "High Noon (3-season rank)",
            "The average of the player's three best season ranks, wherever in the career they "
            "fall (not necessarily back to back), within their lane and across everyone. About "
            "1.0 means a clear #1 three times over. Lower is better; a companion number, not "
            "part of CLR.",
        ),
        "HN3LaneYrs / HN3GlobYrs": (
            "High Noon seasons",
            "The three seasons behind the High Noon rank, within the lane and across everyone.",
        ),
    }


def web_glossary(about: Optional[dict] = None, year: Optional[int] = None) -> dict:
    """glossary.json: every workbook glossary term with its site label and wording, plus the
    résumé point tables (`resume_scoring`). `about` is the parsed About sheet (meta['about'])
    and `year` the latest season (for the league-strength examples)."""
    p = _glossary_params(about or {})
    rs = _resume_scoring(p, int(year if year is not None else YEARS_DEFAULT[-1]))
    text = _web_glossary_text(p, rs)
    terms = [k for k, _ in _GLOSSARY]
    stale = sorted(set(text) - set(terms))
    if stale:
        logger.warning("glossary: site wordings for terms no longer in _GLOSSARY: %s", stale)
    missing = [k for k in terms if k not in text]
    if missing:
        logger.warning("glossary: no site wording for %s; using the workbook text", missing)
    return {
        "entries": [
            {
                "term": k,
                "label": text.get(k, (k, v))[0],
                "definition": text.get(k, (k, v))[1],
            }
            for k, v in _GLOSSARY
        ],
        "resume_scoring": rs,
    }


# ---------------------------------------------------------------------------
# Main build
# ---------------------------------------------------------------------------
@dataclass
class ExportConfig:
    workbook: Optional[Path] = None
    out_root: Optional[Path] = None
    archive_root: Optional[Path] = None  # default: <repo>/frontend/data-archive
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


def _year_teams(
    playernames: Iterable[str],
) -> dict[str, dict[str, list[dict[str, str]]]]:
    """Per-(playername, year) team list from the Leaguepedia player-history cache.

    Returns {playername: {year_str: [{name, logo?}, ...]}} using historically-
    accurate team names (e.g. "DragonX" for Keria in 2020, not "Kiwoom DRX").
    Falls back silently to {} if the cache files haven't been generated yet —
    run `python -m lps.fetch_player_history` to populate them.
    """
    from .fetch_player_history import PLAYER_HISTORY_JSON, TEAM_LOGOS_JSON

    names = set(playernames)

    history: dict[str, dict[str, list[str]]] = {}
    if PLAYER_HISTORY_JSON.exists():
        import json as _json
        history = _json.loads(PLAYER_HISTORY_JSON.read_text(encoding="utf-8"))

    logos: dict[str, str | None] = {}
    if TEAM_LOGOS_JSON.exists():
        import json as _json
        logos = _json.loads(TEAM_LOGOS_JSON.read_text(encoding="utf-8"))

    if not history:
        logger.warning(
            "[web] player_history.json not found — run fetch_player_history to populate year_teams"
        )
        return {}

    out: dict[str, dict[str, list[dict[str, str]]]] = {}
    for player in names:
        by_year = history.get(player)
        if not by_year:
            continue
        out[player] = {
            year: [
                {"name": team, **( {"logo": logos[team]} if logos.get(team) else {} )}
                for team in teams
            ]
            for year, teams in by_year.items()
        }
    return out


def _player_photos(playernames: Iterable[str]) -> dict[str, dict[str, str | float | None]]:
    """{playername: {url, photo_caption, photo_cx/ar/top/neck, real_name, country}} from the
    Leaguepedia photo cache (`photo_*` = head position and aspect, for avatar crops).

    Empty (and the frontend falls back to a monogram) until
    `python -m lps.fetch_player_images` has populated it.
    """
    from .fetch_player_images import PLAYER_IMAGES_JSON, clean_text

    if not PLAYER_IMAGES_JSON.exists():
        logger.warning("[web] player_images.json not found -- run fetch_player_images for photos")
        return {}
    import json as _json

    cache = _json.loads(PLAYER_IMAGES_JSON.read_text(encoding="utf-8"))
    out: dict[str, dict[str, str | float | None]] = {}
    for name in set(playernames):
        e = cache.get(name)
        if not e or not e.get("url"):
            continue
        bits = [b for b in (e.get("team"), str(e["year"]) if e.get("year") else None) if b]
        out[name] = {"url": e["url"], "photo_caption": " · ".join(bits) or None,
                     "photo_cx": e.get("cx"), "photo_ar": e.get("ar"),
                     "photo_top": e.get("top"), "photo_neck": e.get("neck"),
                     "real_name": clean_text(e.get("real_name")) or None,
                     "country": clean_text(e.get("country")) or None}
    return out


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
    archive_root = cfg.archive_root or (PROJECT_ROOT.parent / "frontend" / "data-archive")
    # The site always reads current/. Any existing current/ is moved to
    # <archive_root>/<its_build_id>/ so past snapshots are recoverable locally;
    # the archive is gitignored and kept out of public/ (see module docstring).
    out_dir = out_root / "current"
    if out_dir.exists():
        prev_meta = out_dir / "meta.json"
        prev_build = build_id
        try:
            prev_build = json.loads(prev_meta.read_text("utf-8")).get("build_id", build_id)
        except Exception:
            pass
        archive_dst = archive_root / prev_build
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

    # Podium finishes (official event / league marks on the site) + an index-sized
    # title tally for the rankings table's trophy pills.
    honors_by_name = _honors(ov["playername"].tolist())
    logger.info("[web] honors: %d players with a podium finish", len(honors_by_name))
    ov["titles"] = ov["playername"].map(lambda n: _title_tally(honors_by_name.get(n, [])))

    # Leaguepedia photo per player (CDN thumbnail URL + "Team · Year" caption).
    photos = _player_photos(ov["playername"].tolist())
    ov["photo"] = ov["playername"].map(lambda n: (photos.get(n) or {}).get("url"))
    for col in ("photo_caption", "photo_cx", "photo_ar", "photo_top", "photo_neck",
                "real_name", "country"):
        ov[col] = ov["playername"].map(lambda n, c=col: (photos.get(n) or {}).get(c))
    logger.info("[web] player photos: %d / %d players", int(ov["photo"].notna().sum()), len(ov))

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

    # asof/<year>.json -- past-year boards (career numbers through that season). Written
    # before today's files so every live view can carry its rank on last season's board.
    asof_ranks = _write_asof(out_dir, ov, honors_by_name, cfg.rated_min_games, set(rated["slug"]))
    prev_ranks = asof_ranks.get(latest_year - 1)
    rated["rank_prev"], rated["clr_prev"] = _prev_ranks(rated, prev_ranks, "all")

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
        "hall_of_legends", "hol_year", "is_retired", "is_active", "positions", "photo",
        "photo_cx", "photo_ar", "photo_top", "photo_neck", "real_name", "titles",
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
        lf["rank_prev"], lf["clr_prev"] = _prev_ranks(lf, prev_ranks, lane)
        _write_json(out_dir / "lanes" / f"{lane}.json", [_index_row(r) for _, r in lf.iterrows()])

    # Per-(player, year) HN ranks — used by the trajectory chart to label each
    # season with its global/lane peer rank. Computed once over all lane sheets.
    hn_year_ranks_by_name = _year_rankings(lanes, years)
    logger.info(
        "[web] per-year HN ranks: %d players with ≥1 ranked season",
        len(hn_year_ranks_by_name),
    )
    year_achievements_by_name = _year_achievements(ov["playername"].tolist())
    logger.info(
        "[web] per-year achievements: %d players with ≥1 credited achievement",
        len(year_achievements_by_name),
    )
    year_teams_by_name = _year_teams(ov["playername"].tolist())
    logger.info(
        "[web] per-year teams: %d players mapped",
        len(year_teams_by_name),
    )
    yearly_breakdown_all = _load_yearly_breakdown()
    logger.info(
        "[web] per-year component breakdown: %d players loaded",
        len(yearly_breakdown_all),
    )
    champion_stats_all = _load_champion_stats()
    logger.info("[web] champion splits: %d players loaded", len(champion_stats_all))

    # players/<slug>.json  (every player, rated or not -- shared links still work)
    # Attach slug + rank + tier from the rated pool where present; unrated get
    # tier=null and their un-rated Overview rank.
    rated_by_slug = rated.set_index("slug")
    for _, row in ov.iterrows():
        slug = row["slug"]
        if slug in rated_by_slug.index:
            # set_index moved "slug" into the index; put it back so the detail JSON keeps it.
            r_row = rated_by_slug.loc[slug].copy()
            r_row["slug"] = slug
        else:
            r_row = row.copy()
            r_row["tier"] = None
        idx_global = slug_to_global_idx.get(slug, 0)
        lane = r_row.get("position")
        idx_lane = lane_slug_idx.get(lane, {}).get(slug) if isinstance(lane, str) else None
        lane_radar = radar_by_lane.get(lane, {}) if isinstance(lane, str) else {}
        detail = _detail_json(r_row, tourn_cols, years, radar_global, lane_radar,
                              idx_global if slug in slug_to_global_idx else 0,
                              idx_lane if slug in rated_by_slug.index else None,
                              hn_year_ranks_by_name.get(row["playername"], {}),
                              year_achievements_by_name.get(row["playername"], {}),
                              year_teams_by_name.get(row["playername"], {}),
                              yearly_breakdown_all.get(row["playername"], {}),
                              honors_by_name.get(row["playername"], []))
        detail["rated"] = slug in rated_by_slug.index
        detail["champions"], detail["career_stats"] = _champion_block(
            champion_stats_all.get(row["playername"])
        )
        _write_json(out_dir / "players" / f"{slug}.json", detail)

    # tiers.json
    _write_json(out_dir / "tiers.json", {
        "tiers": tier_meta,
        "rated_min_games": cfg.rated_min_games,
        "rated_count": len(rated),
        "prev_year": latest_year - 1 if prev_ranks else None,
    })

    # meta.json
    meta = {
        "asof_years": sorted(asof_ranks),
        "build_id": build_id,
        "generated": _dt.datetime.now().isoformat(timespec="seconds"),
        "years": [int(years[0]), int(years[-1])],
        "source_workbook": wb.name,
        "rated_min_games": cfg.rated_min_games,
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
    _write_json(out_dir / "glossary.json", web_glossary(meta["about"], int(years[-1])))

    logger.info("[web] wrote bundle to %s", out_dir)
    return out_dir


# Fields an as-of board row carries; everything else on an index row (photo, real name, HoL
# year, ...) doesn't change with the snapshot, so the site joins it from the current index by slug.
_ASOF_FIELDS: list[str] = [
    "rank", "slug", "position", "positions",
    "current_team", "current_league", "current_year",
    "region_elo", "n_years", "first_year", "last_year", "games", "win_rate",
    "clr", "career_value", "pace_value", "peak_value", "resume_bonus",
    "total_score", "peak_lps", "tier", "hall_of_legends", "is_retired", "is_active", "titles",
    "rank_prev", "clr_prev",
]
# Identity fields an as-of row carries itself when the player isn't on today's board (a
# 2013 regular who never reached today's games floor) -- the site has nothing to join.
_ASOF_IDENTITY_FIELDS: list[str] = [
    "playername", "photo", "photo_cx", "photo_ar", "photo_top", "photo_neck", "real_name",
    "hol_year",
]
# Photo fields an as-of row overrides when that season has its own photo (a 2013 board shows
# 2013 Faker, not 2026 Faker); see fetch_player_images.PHOTOS_BY_YEAR_JSON.
_ASOF_PHOTO_FIELDS: list[str] = ["photo", "photo_cx", "photo_ar", "photo_top", "photo_neck"]


def _photos_by_year() -> dict[str, dict[str, dict]]:
    from .fetch_player_images import PHOTOS_BY_YEAR_JSON

    if not PHOTOS_BY_YEAR_JSON.exists():
        logger.warning("[web] %s missing -- past-year boards use today's photos "
                       "(run lps.fetch_player_images)", PHOTOS_BY_YEAR_JSON.name)
        return {}
    return json.loads(PHOTOS_BY_YEAR_JSON.read_text("utf-8"))


def _era_photo(by_year: dict[str, dict], year: int) -> Optional[dict]:
    """The player's newest photo from `year` or before; failing that the earliest one after.
    Only transparent cutouts count (head measured: `cx` set) -- older Leaguepedia photos are
    often rectangular JPGs, which would paste a box over the hero stage and the avatars."""
    yrs = sorted(int(y) for y, e in by_year.items() if e.get("cx") is not None)
    if not yrs:
        return None
    before = [y for y in yrs if y <= year]
    return by_year[str(before[-1] if before else yrs[0])]


def _write_asof(out_dir: Path, ov: pd.DataFrame, honors_by_name: dict[str, list[dict]],
                rated_min_games: int, today_slugs: set[str]) -> dict[int, dict]:
    """Per-season "rankings as of the end of Y" boards -> `asof/<Y>.json`
    ({year, rated_count, tiers, all, lanes: {lane: rows}}), from career.py's
    `player_ratings_asof.json`. Ranks and tiers follow the same rules as the live board,
    applied to the career-through-Y numbers; the rated pool's games floor scales down for
    short early seasons (ASOF_SEASON_FRAC), so rows for players not on today's board carry
    their own identity fields (_ASOF_IDENTITY_FIELDS). Titles and Hall of Legends only
    count what had happened by Y. Status is read in hindsight: active = played in Y,
    retired = never played again, otherwise between teams (hiatus). Each row's `rank_prev` is
    its rank on the previous season's board in the same view (all roles / one lane), null if
    it wasn't rated then; the file's `prev_year` is null when there is no such board.
    Each row also carries `clr_prev`, its CLR at the end of the previous season (null if it
    hadn't played yet). Returns {year: {"rank" | "clr": {view: {slug: value}}}} for every
    board written ("all" + each lane), so the live board can diff against the last one."""
    src = PROJECT_ROOT / "player_ratings_asof.json"
    asof_dir = out_dir / "asof"
    if not src.exists():
        logger.warning("[web] no %s -- skipping past-year boards (run lps.career)", src.name)
        return {}
    snaps = json.loads(src.read_text("utf-8"))
    base = ov.set_index("playername")
    photos = _photos_by_year()
    ranks: dict[int, dict] = {}  # {year: {"rank" | "clr": {view: {slug: value}}}}

    def _shape(df: pd.DataFrame, year: int) -> pd.DataFrame:
        df = df[df["playername"].isin(base.index)].copy()
        b = base.loc[df["playername"]]
        df["slug"] = b["slug"].to_numpy()
        for c in _ASOF_IDENTITY_FIELDS[1:]:
            df[c] = b[c].to_numpy() if c in b.columns else None
        era = [_era_photo(photos.get(n, {}), year) for n in df["playername"]]
        df["_era_photo"] = [bool(e and e.get("url") and e["url"] != p) for e, p in zip(era, df["photo"])]
        for c, k in zip(_ASOF_PHOTO_FIELDS, ("url", "cx", "ar", "top", "neck")):
            df[c] = [e.get(k) if f else v for e, f, v in zip(era, df["_era_photo"], df[c])]
        df["current_team"] = df["team"]
        df["current_league"] = df["league"]
        active = df["last_year"] == year
        df["current_year"] = pd.Series(np.where(active, year, None), index=df.index, dtype=object)
        df["is_active"] = active
        df["is_retired"] = ~active & (b["last_year"].to_numpy() <= year)
        hol_y = b["hol_year"].astype(float).to_numpy()  # NaN = induction year unknown
        df["hall_of_legends"] = b["hall_of_legends"].to_numpy(dtype=bool) & ~(hol_y > year)
        return df

    prev_games: dict[str, float] = {}
    busiest = 0.0  # max over seasons so far of the 90th-percentile games in one season

    def _floor(all_rows: pd.DataFrame) -> int:
        nonlocal busiest, prev_games
        g = dict(zip(all_rows["playername"], all_rows["games"].astype(float)))
        season = pd.Series({n: v - prev_games.get(n, 0.0) for n, v in g.items()})
        season = season[season > 0]
        if len(season):
            busiest = max(busiest, float(season.quantile(0.9)))
        prev_games = g
        return int(min(rated_min_games, max(ASOF_MIN_GAMES_LOW, round(ASOF_SEASON_FRAC * busiest))))

    def _rank(df: pd.DataFrame, min_games: int) -> pd.DataFrame:
        df = df[df["games"] >= min_games].copy()
        df["rank"] = df["clr"].rank(ascending=False, method="first").astype(int)
        df = df.sort_values("rank").reset_index(drop=True)
        df["tier"] = _assign_tiers(df["clr"])[0].values
        return df

    def _row(r: pd.Series) -> dict:
        d = _row_dict(r, _ASOF_FIELDS)
        if r["slug"] not in today_slugs:
            d.update(_row_dict(r, _ASOF_IDENTITY_FIELDS))
        elif r["_era_photo"]:
            d.update(_row_dict(r, _ASOF_PHOTO_FIELDS))
        for k in ("clr", "career_value", "pace_value", "peak_value", "resume_bonus",
                  "total_score", "peak_lps", "win_rate", "region_elo"):
            d[k] = _round(d.get(k))
        return d

    for ys, snap in sorted(snaps.items()):
        year = int(ys)
        lanes_df = _shape(pd.DataFrame(snap["lanes"]), year)
        positions: dict[str, list[dict]] = {}
        for name, lane, clr, games in zip(lanes_df["playername"], lanes_df["position"],
                                          lanes_df["clr"], lanes_df["games"]):
            if pd.notna(clr) and lane in ROLES:
                positions.setdefault(name, []).append(
                    {"lane": lane, "clr": float(clr), "games": int(games or 0)})
        for lst in positions.values():
            lst.sort(key=lambda p: p["clr"], reverse=True)
            total = sum(p["clr"] for p in lst) or 1.0
            for p in lst:
                p["share"] = round(100.0 * p["clr"] / total, 1)
                p["clr"] = _round(p["clr"])

        def _titles(name: str) -> dict | None:
            return _title_tally([h for h in honors_by_name.get(name, []) if h["year"] <= year])

        all_df = _shape(pd.DataFrame(snap["all"]), year)
        all_df["positions"] = all_df["playername"].map(lambda n: positions.get(n, []))
        all_df["position"] = all_df["positions"].map(lambda p: p[0]["lane"] if p else None)
        all_df["titles"] = all_df["playername"].map(_titles)
        min_games = _floor(pd.DataFrame(snap["all"]))
        rated = _rank(all_df, min_games)
        if len(rated) < ASOF_MIN_BOARD:
            continue
        prev = ranks.get(year - 1)
        # Ranks from the rated board; CLR from everyone (so a newly rated player still shows growth).
        ranks[year] = {"rank": {"all": dict(zip(rated["slug"], rated["rank"].astype(int)))},
                       "clr": {"all": dict(zip(all_df["slug"], all_df["clr"].astype(float)))}}
        rated["rank_prev"], rated["clr_prev"] = _prev_ranks(rated, prev, "all")

        lane_rows: dict[str, list[dict]] = {}
        for lane in ROLES:
            lf = lanes_df[lanes_df["position"] == lane].copy()
            lf["positions"] = lf["playername"].map(lambda n: positions.get(n, []))
            lf["titles"] = lf["playername"].map(_titles)
            ranks[year]["clr"][lane] = dict(zip(lf["slug"], lf["clr"].astype(float)))
            lf = _rank(lf, min_games)
            ranks[year]["rank"][lane] = dict(zip(lf["slug"], lf["rank"].astype(int)))
            lf["rank_prev"], lf["clr_prev"] = _prev_ranks(lf, prev, lane)
            lane_rows[lane] = [_row(r) for _, r in lf.iterrows()]

        _, tier_meta = _assign_tiers(rated["clr"])
        _write_json(asof_dir / f"{year}.json", {
            "year": year,
            "prev_year": year - 1 if prev else None,
            "rated_count": int(len(rated)),
            "rated_min_games": min_games,
            "tiers": tier_meta,
            "all": [_row(r) for _, r in rated.iterrows()],
            "lanes": lane_rows,
        })
    logger.info("[web] past-year boards: %s", ", ".join(map(str, ranks)) or "none")
    return ranks


def _prev_ranks(df: pd.DataFrame, prev: Optional[dict], view: str) -> tuple[pd.Series, pd.Series]:
    """(rank, CLR) of each row on the previous board's `view`: rank None = unrated then, CLR
    None = no seasons yet (both None when there's no previous board). Object dtype so the
    ranks stay ints in the JSON (a float column would write `9.0`)."""
    rk = ((prev or {}).get("rank") or {}).get(view, {})
    cl = ((prev or {}).get("clr") or {}).get(view, {})
    rank = pd.Series([rk.get(s) for s in df["slug"]], index=df.index, dtype=object)
    clr = pd.Series([_round(cl[s]) if s in cl else None for s in df["slug"]], index=df.index, dtype=object)
    return rank, clr


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
    ap.add_argument("--archive", type=Path, default=None,
                    help="where the previous current/ is archived (default: <repo>/frontend/data-archive)")
    ap.add_argument("--build-id", type=str, default=None,
                    help="build id / subdirectory name (default: today's date)")
    ap.add_argument("--rated-min-games", type=int, default=RATED_MIN_GAMES,
                    help=f"rated-pool floor (default: {RATED_MIN_GAMES} games)")
    args = ap.parse_args()

    build_web_bundle(ExportConfig(
        workbook=args.workbook,
        out_root=args.out,
        archive_root=args.archive,
        build_id=args.build_id,
        rated_min_games=args.rated_min_games,
    ))


if __name__ == "__main__":
    main()
