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

Awards (regional MVP / All-Pro / Finals MVP) come from the `IndividualAchievements` Cargo table
(Display holds the award name, joined to Tournaments for year/league) -> info/player_awards.csv.
Hand-added rows tagged notes='manual' (e.g. Finals MVPs missing from the table) survive re-fetch.

Run:  poetry run python -m lps.fetch_achievements
      poetry run python -m lps.fetch_achievements --skip-placements   # refresh only awards
"""

from __future__ import annotations

import argparse
import csv
import logging
import re
from datetime import datetime
from typing import Optional

from .config import INFO_DIR
from .lp_client import LPClient

logger = logging.getLogger(__name__)

ACHIEVEMENTS_CSV = INFO_DIR / "achievements.csv"  # refined (intl + rated domestic)
ACHIEVEMENTS_RAW_CSV = INFO_DIR / "achievements_raw.csv"  # everything fetched
AWARDS_CSV = INFO_DIR / "player_awards.csv"  # refined (classified + rated)
AWARDS_RAW_CSV = INFO_DIR / "player_awards_raw.csv"  # everything, annotated

# Our data range. Leaguepedia carries future/placeholder tournament pages (e.g. a 2027 MSI
# stub); bound to the seasons we actually score so the committed CSV stays clean.
MIN_YEAR, MAX_YEAR = 2011, datetime.now().year

# Leaguepedia League full-names whose split PLAYOFFS titles we credit (i.e. rated majors/regions;
# unrated years still score 0 via missing Elo downstream). Used only to bound the roster pull.
# (Kept here, not imported from achievements.py, to avoid a circular import.)
DOMESTIC_LEAGUES = [
    "LoL Champions Korea",
    "League of Legends Champions Korea",
    "Champions Korea",
    "LoL The Champions",
    "Tencent LoL Pro League",
    "LoL Pro League",
    "Europe League Championship Series",
    "League of Legends European Championship",
    "LoL EMEA Championship",
    "League of Legends EMEA Championship",
    "North America League Championship Series",
    "League of Legends Championship Series",
    "LoL Master Series",
    "Pacific Championship Series",
    "League of Legends Championship Pacific",
    "Vietnam Championship Series",
    "Circuit Brazilian League of Legends",
    "Liga Latinoamerica",
    "LoL Japan League",
    "Turkish Championship League",
    "League of Legends Championship of The Americas North",
    "League of Legends Championship of The Americas South",
]
_RATED_DOMESTIC = set(DOMESTIC_LEAGUES)
# Awards from international events -- flat (not tied to a domestic league / Elo). Worlds/MSI have
# their own tiers; every other cross-region event shares the generic intl_* tokens.
_FLAT_AWARDS = {
    "worlds_finals_mvp",
    "msi_finals_mvp",
    "worlds_mvp",
    "msi_mvp",
    "worlds_all_pro",
    "msi_all_pro",
    "intl_finals_mvp",
    "intl_mvp",
    "intl_all_pro",
}

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
        return "other"  # domestic: only title/finalist matter
    if p in ("3", "4", "3-4"):
        return "semifinalist"
    if p in ("5-6", "7-8", "5-8"):
        return "quarterfinalist"
    return "group"  # everything below top-8 at an intl event


def _split_of(name: str) -> str:
    """Best-effort split label from a domestic tournament name (Spring/Summer/Winter/...)."""
    for s in (
        "Spring",
        "Summer",
        "Winter",
        "Season Finals",
        "Regional Finals",
        "Proving Grounds",
    ):
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
    for evt, like in (
        ("WLDs", "%World Championship%"),
        ("MSI", "%Mid-Season Invitational%"),
    ):
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


# Extra tournaments to credit, aligned with the LPS tournament universe (season._viewership_weights
# / _MANUAL_TOURNAMENT_WEIGHTS). Each maps its LPS label -> the Leaguepedia League(s) to pull, its
# category (cross-region 'intl' vs single-region 'domestic_cup'), and optional scoping (a page
# substring filter, or a year window for events whose league name is reused across eras). Worlds +
# MSI are handled separately above. 'Riot' (2020 VCS x PCS) is omitted -- no clean LP league + tiny.
TOURNAMENT_REGISTRY: dict[str, dict] = {
    "EWC": {"leagues": ["Esports World Cup"], "category": "intl"},
    "FST": {"leagues": ["First Stand"], "category": "intl"},
    "MSC": {"leagues": ["Mid-Season Cup 2020"], "category": "intl"},
    "LTA": {
        "leagues": ["League of Legends Championship of The Americas"],
        "category": "intl",
    },
    "RR": {
        "leagues": ["Rift Rivals 2017 LCK-LPL-LMS", "Rift Rivals 2017 NA-EU"],
        "category": "intl",
    },
    "ASI": {"leagues": ["League of Legends Asia Invitational"], "category": "intl"},
    "IWCI": {"leagues": ["International Wildcard Invitational"], "category": "intl"},
    "IEM": {
        "leagues": ["Intel Extreme Masters"],
        "category": "intl",
        "page_like": "world championship",
    },
    "IPL": {"leagues": ["IGN Pro League"], "category": "intl"},
    "MLG": {"leagues": ["MLG 2012 Fall"], "category": "intl"},
    "DH": {"leagues": ["DreamHack"], "category": "intl", "years": (2011, 2012)},
    "OGN": {
        "leagues": ["LoL The Champions"],
        "category": "intl",
        "years": (2012, 2012),
    },
    "KeSPA": {"leagues": ["KeSPA Cup"], "category": "domestic_cup"},
    "DCup": {"leagues": ["Demacia Cup"], "category": "domestic_cup"},
}
# Cross-region event leagues whose MVP / All-Pro count as flat intl awards. Excludes leagues that
# are ALSO rated domestic (e.g. "LoL The Champions" = 2012 intl but 2013+ domestic KR) so their
# domestic-era awards stay classified as regional, not intl.
_INTL_EVENT_LEAGUES = {
    lg.lower()
    for label, m in TOURNAMENT_REGISTRY.items()
    if m["category"] == "intl"
    for lg in m["leagues"]
    if lg not in _RATED_DOMESTIC
}
# Page substrings that mark a NON-final stage (qualifier/group/etc.) within a registry league --
# excluded so a team's best placement is its real bracket finish, not a group/qualifier "1st".
_STAGE_EXCLUDE = (
    "qualifier",
    "qualifying",
    "promotion",
    "relegation",
    "showmatch",
    "regular season",
    "group",
    "swiss",
    "tiebreaker",
    "points",
    "play-in",
    "play in",
    "kickoff",
    "spring season",
    "summer season",
    "winter season",
    "open",
    "campus",
)


def _place_low(place: str) -> int:
    """Leading integer of a Place string ('3-4' -> 3), for picking a team's best finish."""
    m = re.match(r"\s*(\d+)", str(place))
    return int(m.group(1)) if m else 999


def _rosters_by_page(
    lp: LPClient, leagues: list[str]
) -> dict[tuple[str, str], set[str]]:
    """{(overview_page, team) -> {players}} for any set of leagues, from ScoreboardPlayers."""
    inlist = ", ".join("'" + n.replace("'", "\\'") + "'" for n in leagues)
    out: dict[tuple[str, str], set[str]] = {}
    rows = lp.query(
        tables="ScoreboardPlayers=SP, Tournaments=T",
        join_on="SP.OverviewPage=T.OverviewPage",
        fields="SP.OverviewPage=page, SP.Team=team, SP.Link=player",
        where=f"T.League IN ({inlist}) AND T.Year>={MIN_YEAR} AND T.Year<={MAX_YEAR}",
    )
    for r in rows:
        key = ((r.get("page") or "").strip(), (r.get("team") or "").strip())
        out.setdefault(key, set()).add(_clean_player(r.get("player", "")))
    return out


def _fetch_registry_placements(lp: LPClient) -> list[dict]:
    """Pull placements for every TOURNAMENT_REGISTRY event (the LPS tournament universe beyond
    Worlds/MSI). For each (event, year, team) keep the team's BEST finish across the event's
    non-stage pages, bucket it, and attach the roster of that page. Tags each row with the LPS
    label as `event` and 'intl' / 'domestic_cup' as `category`."""
    league2meta = {
        lg: (label, m)
        for label, m in TOURNAMENT_REGISTRY.items()
        for lg in m["leagues"]
    }
    all_leagues = list(league2meta)
    rosters = _rosters_by_page(lp, all_leagues)
    inlist = ", ".join("'" + n.replace("'", "\\'") + "'" for n in all_leagues)
    raw = lp.query(
        tables="TournamentResults=TR, Tournaments=T",
        join_on="TR.OverviewPage=T.OverviewPage",
        fields="T.Year=year, T.League=league, T.Name=name, TR.OverviewPage=page, "
        "TR.Team=team, TR.Place=place",
        where=f"T.League IN ({inlist})",
    )
    best: dict[tuple[str, int, str], dict] = {}
    for r in raw:
        meta = league2meta.get((r.get("league") or "").strip())
        if not meta:
            continue
        label, m = meta
        try:
            year = int(r.get("year") or 0)
        except ValueError:
            continue
        if not (MIN_YEAR <= year <= MAX_YEAR):
            continue
        yrs = m.get("years")
        if yrs and not (yrs[0] <= year <= yrs[1]):
            continue
        page = (r.get("page") or "").strip()
        pl = page.lower()
        if m.get("page_like") and m["page_like"] not in pl:
            continue
        if any(x in pl for x in _STAGE_EXCLUDE):
            continue
        low = _place_low(r.get("place", ""))
        if low >= 999:
            continue
        team = (r.get("team") or "").strip()
        key = (label, year, team)
        if key not in best or low < best[key]["low"]:
            best[key] = {
                "low": low,
                "place": (r.get("place") or "").strip(),
                "page": page,
                "category": m["category"],
            }
    rows = []
    for (label, year, team), b in best.items():
        roster = rosters.get((b["page"], team), set())
        rows.append(
            {
                "year": year,
                "category": b["category"],
                "event": label,
                "league_full": "",
                "split": "",
                "team": team,
                "place": b["place"],
                "bucket": _bucket(b["place"], intl=True),
                "players": ";".join(sorted(roster)),
                "page": b["page"],
            }
        )
    from collections import Counter

    logger.info(
        f"[achievements] registry placements: {dict(Counter(r['event'] for r in rows))}"
    )
    return rows


def fetch(lp: Optional[LPClient] = None) -> list[dict]:
    """Query Leaguepedia for intl placements + domestic playoff podiums, each with its team's
    roster (from ScoreboardPlayers), and return achievement rows. Player credit is assigned by
    ROSTER (matching handles to our universe), not by team-name -- so org renames between
    Leaguepedia and Oracle don't matter."""
    lp = lp or LPClient()
    rows: list[dict] = []

    intl_rosters = _rosters_intl(lp)
    logger.info(
        f"[achievements] intl rosters: {len(intl_rosters)} (year,event,team) groups"
    )

    # --- International: Worlds + MSI main-event placements (all places, all years) -------------
    for evt, like in (
        ("WLDs", "%World Championship%"),
        ("MSI", "%Mid-Season Invitational%"),
    ):
        raw = lp.query(
            tables="TournamentResults",
            fields="OverviewPage=page, Team=team, Place=place",
            # main event only: skip Play-In / Main Event / Group sub-pages and regional qualifiers
            where=(
                f"OverviewPage LIKE '{like}' AND OverviewPage NOT LIKE '%/%' "
                "AND OverviewPage NOT LIKE '%Qualifier%' AND OverviewPage NOT LIKE '%Regional%'"
            ),
        )
        for r in raw:
            year = _worlds_year(r.get("page", ""))
            if year is None or not (MIN_YEAR <= year <= MAX_YEAR):
                continue
            team = (r.get("team") or "").strip()
            roster = intl_rosters.get((year, evt, team), set())
            rows.append(
                {
                    "year": year,
                    "category": "intl",
                    "event": evt,
                    "league_full": "",
                    "split": "",
                    "team": team,
                    "place": (r.get("place") or "").strip(),
                    "bucket": _bucket(r.get("place", ""), intl=True),
                    "players": ";".join(sorted(roster)),
                    "page": r.get("page", ""),
                }
            )
        logger.info(
            f"[achievements] {evt}: {sum(1 for x in rows if x['event'] == evt)} placements"
        )

    # --- Domestic: split PLAYOFFS podium (Place 1/2) across all leagues/years -----------------
    dom_rosters = _rosters_domestic(lp)
    logger.info(
        f"[achievements] domestic rosters: {len(dom_rosters)} (page,team) groups"
    )
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
        rows.append(
            {
                "year": year,
                "category": "domestic",
                "event": "",
                "league_full": r.get("league", ""),
                "split": _split_of(r.get("name", "")),
                "team": team,
                "place": (r.get("place") or "").strip(),
                "bucket": _bucket(r.get("place", ""), intl=False),
                "players": ";".join(sorted(roster)),
                "page": page,
            }
        )
    logger.info(
        f"[achievements] domestic playoff podiums: "
        f"{sum(1 for x in rows if x['category'] == 'domestic')}"
    )

    # Extra LPS tournaments (EWC/First Stand/MSC/LTA/Rift Rivals/KeSPA/Demacia/... -- everything
    # LPS scores beyond Worlds/MSI), aligning the resume's event coverage with the on-rift scoring.
    rows += _fetch_registry_placements(lp)
    return rows


def _is_relevant_placement(r: dict) -> bool:
    """A placement worth scoring: any international result (Worlds/MSI + registry cross-region
    events), any domestic cup (KeSPA/Demacia), or a domestic split podium in a rated major/region
    (minor/amateur-league split titles are dropped from the refined CSV)."""
    return r["category"] in ("intl", "domestic_cup") or (
        r["category"] == "domestic" and r["league_full"] in _RATED_DOMESTIC
    )


def write_csv(rows: list[dict]) -> None:
    """Write both the RAW placements (everything fetched) and the REFINED subset used for scoring
    (intl + rated-domestic only), mirroring the awards raw/refined pair."""
    INFO_DIR.mkdir(parents=True, exist_ok=True)
    cols = [
        "year",
        "category",
        "event",
        "league_full",
        "split",
        "team",
        "place",
        "bucket",
        "players",
        "page",
    ]
    rows = sorted(
        rows,
        key=lambda r: (
            r["category"],
            -r["year"],
            r["event"],
            r["league_full"],
            r["split"],
            r["place"],
        ),
    )

    def _dump(path, data, fieldnames):
        with path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            w.writerows(data)

    # Raw: everything, with a drop_reason column (blank = kept in the refined set).
    raw_rows = [
        {
            **r,
            "drop_reason": "" if _is_relevant_placement(r) else "minor/unrated league",
        }
        for r in rows
    ]
    _dump(ACHIEVEMENTS_RAW_CSV, raw_rows, cols + ["drop_reason"])
    refined = [r for r in rows if _is_relevant_placement(r)]
    _dump(ACHIEVEMENTS_CSV, refined, cols)
    logger.info(
        f"[achievements] wrote {len(rows)} raw -> {ACHIEVEMENTS_RAW_CSV.name}; "
        f"{len(refined)} refined (intl + rated domestic) -> {ACHIEVEMENTS_CSV.name}"
    )
    doms = sorted({r["league_full"] for r in rows if r["category"] == "domestic"})
    logger.info(f"[achievements] distinct domestic leagues in raw ({len(doms)})")


def _classify_award(display: str, league_full: str, name: str) -> Optional[str]:
    """Map a Leaguepedia IndividualAchievements.Display string to one of our award categories,
    or None to skip (coach/rookie/role-stat/fan-voted/etc.). Finals MVP, tournament MVP and
    All-Pro are all credited at the two international events, tagged with the event tier.
    """
    d = re.sub(r"\s+", " ", re.sub(r"[-]", " ", str(display).lower())).strip()
    # Detect the two international events by the LEAGUE field, not name substrings -- a domestic
    # split literally called "... Mid Season ..." (e.g. LCP) must NOT be read as MSI.
    lf = str(league_full).strip().lower()
    is_worlds = lf == "world championship"
    is_msi = lf == "mid-season invitational"
    is_intl_event = (
        lf in _INTL_EVENT_LEAGUES
    )  # EWC / First Stand / MSC / LTA / ... (flat)
    skip = any(
        x in d for x in ("fan", "expert", "nirvana", "kda", "best ", "round", "phase")
    )
    # A (non-finals) MVP: the spelled-out forms plus any "... mvp ..." string.
    is_mvp = (
        d
        in (
            "most valuable player",
            "regular season mvp",
            "player of the split",
            "season mvp",
        )
        or "mvp" in d
    )
    is_allpro = "all pro" in d or d in ("first team", "second team", "third team")
    # Finals / playoffs MVP (event-tiered).
    if "mvp" in d and ("final" in d or "playoff" in d):
        if is_worlds:
            return "worlds_finals_mvp"
        if is_msi:
            return "msi_finals_mvp"
        if is_intl_event:
            return "intl_finals_mvp"
        return "domestic_finals_mvp"
    if is_worlds or is_msi or is_intl_event:
        # Also credit the (non-finals) tournament MVP and All-Pro team at any intl event.
        if is_mvp and not skip:
            return "worlds_mvp" if is_worlds else "msi_mvp" if is_msi else "intl_mvp"
        if is_allpro and not skip:
            return (
                "worlds_all_pro"
                if is_worlds
                else "msi_all_pro" if is_msi else "intl_all_pro"
            )
        return None
    # Season MVP.
    if is_mvp and not skip:
        return "regional_mvp"
    # All-Pro teams -- official selections only (skip fan-/expert-voted alternates & role stats).
    if skip:
        return None
    if "all pro" in d or d in ("first team", "second team", "third team"):
        if "1st" in d or "first" in d:
            return "all_pro_1"
        if "2nd" in d or "second" in d:
            return "all_pro_2"
        if "3rd" in d or "third" in d:
            return "all_pro_3"
        return "all_pro_1"  # unranked "All-Pro Team" -> 1st team
    return None


def _refine_awards(raw: list[dict]) -> list[dict]:
    """From the raw IndividualAchievements dump, keep the scorable awards: recognized category,
    within our year range, and either a global Finals MVP or an award in a rated domestic league
    (minor/amateur-league honors are dropped, mirroring the placements refine)."""
    out = []
    for r in raw:
        cat = r.get("classified_as") or ""
        if not cat:
            continue
        try:
            year = int(r.get("year") or 0)
        except ValueError:
            continue
        if not (MIN_YEAR <= year <= MAX_YEAR):
            continue
        if cat not in _FLAT_AWARDS and r.get("league", "") not in _RATED_DOMESTIC:
            continue
        out.append(
            {
                "year": year,
                "playername": r.get("player", ""),
                "award": cat,
                "league_full": r.get("league", ""),
                "split": _split_of(r.get("name", "")),
                "notes": (r.get("display") or "").strip(),
            }
        )
    return out


def fetch_awards_raw(lp: Optional[LPClient] = None) -> list[dict]:
    """Pull EVERY IndividualAchievements row (all Display values, leagues, years -- no filtering),
    annotated with how each would be classified, for manual inspection of what's kept vs dropped.
    """
    lp = lp or LPClient()
    raw = lp.query(
        tables="IndividualAchievements=IA, Tournaments=T",
        join_on="IA.OverviewPage=T.OverviewPage",
        fields="IA.Player=player, IA.Link=link, IA.Display=display, IA.Description=description, "
        "IA.Place=place, T.Year=year, T.League=league, T.Name=name, IA.OverviewPage=page",
    )
    out = []
    for r in raw:
        out.append(
            {
                "year": r.get("year", ""),
                "league": r.get("league", ""),
                "name": r.get("name", ""),
                "player": _clean_player(r.get("player", "") or r.get("link", "")),
                "display": (r.get("display") or "").strip(),
                "description": (r.get("description") or "").strip(),
                "place": r.get("place", ""),
                "classified_as": _classify_award(
                    r.get("display", ""), r.get("league", ""), r.get("name", "")
                )
                or "",
                "page": r.get("page", ""),
            }
        )
    return out


def _award_drop_reason(r: dict) -> str:
    """Why a raw award row is (or isn't) in the refined set. Blank = kept."""
    cat = r.get("classified_as") or ""
    if not cat:
        return "unrecognized award"
    try:
        year = int(r.get("year") or 0)
    except ValueError:
        return "bad year"
    if not (MIN_YEAR <= year <= MAX_YEAR):
        return "out of range"
    if cat not in _FLAT_AWARDS and r.get("league", "") not in _RATED_DOMESTIC:
        return "minor/unrated league"
    return ""


def write_raw_awards_csv(rows: list[dict]) -> None:
    INFO_DIR.mkdir(parents=True, exist_ok=True)
    cols = [
        "year",
        "league",
        "name",
        "player",
        "display",
        "description",
        "place",
        "classified_as",
        "drop_reason",
        "page",
    ]
    rows = [{**r, "drop_reason": _award_drop_reason(r)} for r in rows]
    rows = sorted(
        rows, key=lambda r: (str(r["year"]), str(r["league"]), str(r["display"]))
    )
    with AWARDS_RAW_CSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    kept = sum(1 for r in rows if not r["drop_reason"])
    logger.info(
        f"[achievements] wrote {len(rows)} RAW awards ({kept} kept, {len(rows)-kept} "
        f"dropped) -> {AWARDS_RAW_CSV}"
    )


def _existing_manual_awards() -> list[dict]:
    """Rows in the current player_awards.csv whose notes start with 'manual' -- hand-added awards
    that a re-fetch must NOT clobber. 'manual' = official but missing from Leaguepedia's table;
    'manual*' = unofficial / fan-consensus (e.g. pre-2015 Worlds "Finals MVP")."""
    if not AWARDS_CSV.exists():
        return []
    import csv as _csv

    with AWARDS_CSV.open(newline="", encoding="utf-8") as f:
        return [
            r
            for r in _csv.DictReader(f)
            if (r.get("notes") or "").strip().lower().startswith("manual")
        ]


def write_awards_csv(rows: list[dict]) -> None:
    INFO_DIR.mkdir(parents=True, exist_ok=True)
    cols = ["year", "playername", "award", "league_full", "split", "notes"]
    rows = rows + [
        {c: (m.get(c) or "") for c in cols} for m in _existing_manual_awards()
    ]
    # de-dupe synonymous rows (e.g. "MVP" + "Player of the Split" for the same player/split).
    seen, uniq = set(), []
    for r in sorted(rows, key=lambda r: (-int(r["year"]), r["playername"], r["award"])):
        k = (
            str(r["year"]),
            r["playername"].lower(),
            r["league_full"],
            r["split"],
            r["award"],
        )
        if k in seen:
            continue
        seen.add(k)
        uniq.append(r)
    with AWARDS_CSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(uniq)
    from collections import Counter

    logger.info(
        f"[achievements] wrote {len(uniq)} awards -> {AWARDS_CSV}  "
        f"{dict(Counter(r['award'] for r in uniq))}"
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(
        description="Fetch tournament placements + titles + awards."
    )
    ap.add_argument(
        "--skip-placements", action="store_true", help="only refresh player_awards.csv"
    )
    ap.add_argument(
        "--skip-awards", action="store_true", help="only refresh achievements.csv"
    )
    ap.add_argument(
        "--raw-awards",
        action="store_true",
        help="dump EVERY IndividualAchievements row (unfiltered) for inspection, then exit",
    )
    args = ap.parse_args()

    lp = LPClient()
    if args.raw_awards:
        raw = fetch_awards_raw(lp)
        if raw:
            write_raw_awards_csv(raw)
        else:
            logger.warning("[achievements] no raw awards fetched (API error?)")
        return
    if not args.skip_placements:
        rows = fetch(lp)
        if rows:
            write_csv(rows)  # writes raw + refined
        else:
            logger.warning("[achievements] no placement rows fetched (API error?)")
    if not args.skip_awards:
        raw = fetch_awards_raw(lp)
        if raw:
            write_raw_awards_csv(raw)  # everything, annotated
            write_awards_csv(_refine_awards(raw))  # refined subset used for scoring
        else:
            logger.warning("[achievements] no awards fetched (API error?)")


if __name__ == "__main__":
    main()
