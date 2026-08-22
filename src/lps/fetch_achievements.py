"""
Fetch tournament placements + domestic titles from Leaguepedia -> info/achievements.csv.

This is the data layer for CLR resume bonuses (Phase 2). Leaguepedia's `TournamentResults`
Cargo table gives clean team-level placements -- (OverviewPage, Team, Place) -- for every event;
we pull:

  - INTERNATIONAL: every Worlds + MSI main-event placement (champion .. play-in), and
  - DOMESTIC: every split PLAYOFFS champion/finalist (Place 1/2 on a "* Playoffs" page).

Results are written to a committed, hand-editable CSV (info/achievements.csv) so the resume
scoring is reproducible without re-hitting the (flaky) API, and gaps/renames can be fixed by
hand -- exactly like info/team_regions_<year>.csv. Player credit is assigned later (see
achievements.py) by joining these team-level rows to our own per-player roster data.

Awards (regional MVP / All-Pro / Finals MVP) are NOT in Cargo; scaffold a template only.

Run:  poetry run python -m lps.fetch_achievements
"""

from __future__ import annotations

import argparse
import csv
import logging
import re
from typing import Optional

from .config import INFO_DIR
from .lp_client import LPClient

logger = logging.getLogger(__name__)

ACHIEVEMENTS_CSV = INFO_DIR / "achievements.csv"
AWARDS_CSV = INFO_DIR / "player_awards.csv"

# Our data range. Leaguepedia carries future/placeholder tournament pages (e.g. a 2027 MSI
# stub); bound to the seasons we actually score so the committed CSV stays clean.
MIN_YEAR, MAX_YEAR = 2011, 2025

# Leaguepedia League full-names whose split PLAYOFFS titles we credit (i.e. rated majors/regions;
# unrated years still score 0 via missing Elo downstream). Used only to bound the roster pull.
# (Kept here, not imported from achievements.py, to avoid a circular import.)
DOMESTIC_LEAGUES = [
    "LoL Champions Korea", "League of Legends Champions Korea", "LoL The Champions",
    "Tencent LoL Pro League", "LoL Pro League",
    "Europe League Championship Series", "League of Legends European Championship",
    "LoL EMEA Championship", "North America League Championship Series",
    "League of Legends Championship Series", "LoL Master Series", "Pacific Championship Series",
    "League of Legends Championship Pacific", "Vietnam Championship Series",
    "Circuit Brazilian League of Legends", "Liga Latinoamerica", "LoL Japan League",
    "Turkish Championship League", "League of Legends Championship of The Americas North",
    "League of Legends Championship of The Americas South",
]

# Season N -> calendar year, for the earliest Worlds pages ("Season 2 World Championship").
_SEASON_YEAR = {"1": 2011, "2": 2012, "3": 2013}


def _worlds_year(page: str) -> Optional[int]:
    """Parse the calendar year from a Worlds/MSI overview page name."""
    m = re.search(r"(20\d\d)", page)
    if m:
        return int(m.group(1))
    m = re.search(r"Season (\d+)", page)
    return _SEASON_YEAR.get(m.group(1)) if m else None


def _bucket(place: str, *, intl: bool) -> str:
    """Map a Place string ('1', '3-4', '5-8', ...) to a placement bucket."""
    p = str(place).strip()
    if p == "1":
        return "champion"
    if p == "2":
        return "finalist"
    if not intl:
        return "other"                                   # domestic: only title/finalist matter
    if p in ("3", "4", "3-4"):
        return "semifinalist"
    if p in ("5-6", "7-8", "5-8"):
        return "quarterfinalist"
    return "group"                                        # everything below top-8 at an intl event


def _split_of(name: str) -> str:
    """Best-effort split label from a domestic tournament name (Spring/Summer/Winter/...)."""
    for s in ("Spring", "Summer", "Winter", "Season Finals", "Regional Finals", "Proving Grounds"):
        if s.lower() in name.lower():
            return s
    return ""


def _clean_player(link: str) -> str:
    """Leaguepedia player Link -> handle, stripping the '(disambiguation)' parenthetical so it
    matches our canonical handles (e.g. 'Bin (Chen Ze-Bin)' -> 'Bin')."""
    return re.sub(r"\s*\(.*\)\s*$", "", str(link)).strip()


def _rosters_intl(lp: LPClient) -> dict[tuple[int, str, str], set[str]]:
    """{(year, event, team) -> {players}} for Worlds + MSI, from ScoreboardPlayers (same team
    names as TournamentResults, so placements join by exact team). Two bulk queries."""
    out: dict[tuple[int, str, str], set[str]] = {}
    for evt, like in (("WLDs", "%World Championship%"), ("MSI", "%Mid-Season Invitational%")):
        rows = lp.query(
            tables="ScoreboardPlayers",
            fields="OverviewPage=page, Team=team, Link=player",
            where=f"OverviewPage LIKE '{like}'",
        )
        for r in rows:
            year = _worlds_year(r.get("page", ""))
            if year is None or not (MIN_YEAR <= year <= MAX_YEAR):
                continue
            key = (year, evt, (r.get("team") or "").strip())
            out.setdefault(key, set()).add(_clean_player(r.get("player", "")))
    return out


def _rosters_domestic(lp: LPClient) -> dict[tuple[str, str], set[str]]:
    """{(overview_page, team) -> {players}} for rated-league split playoffs, from ScoreboardPlayers
    (one bulk query per year to bound size). Placements join by exact (page, team)."""
    inlist = ", ".join("'" + n.replace("'", "\\'") + "'" for n in DOMESTIC_LEAGUES)
    out: dict[tuple[str, str], set[str]] = {}
    for year in range(MIN_YEAR, MAX_YEAR + 1):
        rows = lp.query(
            tables="ScoreboardPlayers=SP, Tournaments=T",
            join_on="SP.OverviewPage=T.OverviewPage",
            fields="SP.OverviewPage=page, SP.Team=team, SP.Link=player",
            where=f"T.Year={year} AND SP.OverviewPage LIKE '%Playoffs%' AND T.League IN ({inlist})",
        )
        for r in rows:
            key = ((r.get("page") or "").strip(), (r.get("team") or "").strip())
            out.setdefault(key, set()).add(_clean_player(r.get("player", "")))
    return out


def fetch(lp: Optional[LPClient] = None) -> list[dict]:
    """Query Leaguepedia for intl placements + domestic playoff podiums, each with its team's
    roster (from ScoreboardPlayers), and return achievement rows. Player credit is assigned by
    ROSTER (matching handles to our universe), not by team-name -- so org renames between
    Leaguepedia and Oracle don't matter."""
    lp = lp or LPClient()
    rows: list[dict] = []

    intl_rosters = _rosters_intl(lp)
    logger.info(f"[achievements] intl rosters: {len(intl_rosters)} (year,event,team) groups")

    # --- International: Worlds + MSI main-event placements (all places, all years) -------------
    for evt, like in (("WLDs", "%World Championship%"), ("MSI", "%Mid-Season Invitational%")):
        raw = lp.query(
            tables="TournamentResults",
            fields="OverviewPage=page, Team=team, Place=place",
            # main event only: skip Play-In / Main Event / Group sub-pages and regional qualifiers
            where=(f"OverviewPage LIKE '{like}' AND OverviewPage NOT LIKE '%/%' "
                   "AND OverviewPage NOT LIKE '%Qualifier%' AND OverviewPage NOT LIKE '%Regional%'"),
        )
        for r in raw:
            year = _worlds_year(r.get("page", ""))
            if year is None or not (MIN_YEAR <= year <= MAX_YEAR):
                continue
            team = (r.get("team") or "").strip()
            roster = intl_rosters.get((year, evt, team), set())
            rows.append({
                "year": year, "category": "intl", "event": evt, "league_full": "",
                "split": "", "team": team, "place": (r.get("place") or "").strip(),
                "bucket": _bucket(r.get("place", ""), intl=True),
                "players": ";".join(sorted(roster)), "page": r.get("page", ""),
            })
        logger.info(f"[achievements] {evt}: {sum(1 for x in rows if x['event'] == evt)} placements")

    # --- Domestic: split PLAYOFFS podium (Place 1/2) across all leagues/years -----------------
    dom_rosters = _rosters_domestic(lp)
    logger.info(f"[achievements] domestic rosters: {len(dom_rosters)} (page,team) groups")
    raw = lp.query(
        tables="TournamentResults=TR, Tournaments=T",
        join_on="TR.OverviewPage=T.OverviewPage",
        fields="T.Year=year, T.League=league, T.Name=name, TR.OverviewPage=page, "
               "TR.Team=team, TR.Place=place",
        where="TR.Place IN ('1','2') AND T.OverviewPage LIKE '%Playoffs%'",
    )
    for r in raw:
        try:
            year = int(r.get("year") or 0)
        except ValueError:
            year = 0
        if not (MIN_YEAR <= year <= MAX_YEAR):
            continue
        page, team = (r.get("page") or "").strip(), (r.get("team") or "").strip()
        roster = dom_rosters.get((page, team), set())
        rows.append({
            "year": year, "category": "domestic", "event": "", "league_full": r.get("league", ""),
            "split": _split_of(r.get("name", "")), "team": team,
            "place": (r.get("place") or "").strip(),
            "bucket": _bucket(r.get("place", ""), intl=False),
            "players": ";".join(sorted(roster)), "page": page,
        })
    logger.info(f"[achievements] domestic playoff podiums: "
                f"{sum(1 for x in rows if x['category'] == 'domestic')}")
    return rows


def write_csv(rows: list[dict]) -> None:
    INFO_DIR.mkdir(parents=True, exist_ok=True)
    cols = ["year", "category", "event", "league_full", "split", "team", "place", "bucket",
            "players", "page"]
    rows = sorted(rows, key=lambda r: (r["category"], -r["year"], r["event"], r["league_full"],
                                       r["split"], r["place"]))
    with ACHIEVEMENTS_CSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    logger.info(f"[achievements] wrote {len(rows)} rows -> {ACHIEVEMENTS_CSV}")

    # distinct domestic leagues (helps build the league_full -> code map in achievements.py)
    doms = sorted({r["league_full"] for r in rows if r["category"] == "domestic"})
    logger.info(f"[achievements] distinct domestic leagues ({len(doms)}): {doms}")


def scaffold_awards() -> None:
    """Create a hand-fill template for awards (regional MVP / All-Pro / Finals MVP) if absent."""
    if AWARDS_CSV.exists():
        logger.info(f"[achievements] {AWARDS_CSV} exists -- leaving as is")
        return
    cols = ["year", "playername", "award", "league", "notes"]
    # Minimal, factually-correct starter rows (well-known Worlds Finals MVPs). Extend with
    # regional MVP / All-Pro / MSI Finals MVP by hand. award in: regional_mvp, worlds_finals_mvp,
    # msi_finals_mvp, all_pro_1, all_pro_2, all_pro_3.
    examples = [
        {"year": 2015, "playername": "MaRin", "award": "worlds_finals_mvp", "league": "LCK", "notes": ""},
        {"year": 2016, "playername": "Faker", "award": "worlds_finals_mvp", "league": "LCK", "notes": ""},
    ]
    with AWARDS_CSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(examples)
    logger.info(f"[achievements] scaffolded awards template -> {AWARDS_CSV} "
                "(award in: regional_mvp, worlds_finals_mvp, msi_finals_mvp, all_pro_1/2/3)")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(description="Fetch tournament placements + titles -> info CSV.")
    ap.add_argument("--awards-template", action="store_true", help="also scaffold player_awards.csv")
    args = ap.parse_args()

    rows = fetch()
    if rows:
        write_csv(rows)
    else:
        logger.warning("[achievements] no rows fetched (API error?)")
    if args.awards_template:
        scaffold_awards()


if __name__ == "__main__":
    main()
