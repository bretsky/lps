"""
Fetch per-player status from Leaguepedia (Players cargo table) so we can label
each player Active vs. Retired on the website.  Writes info/player_status.csv:

    playername,is_retired,country,role

Runs against a list of player names (default: the ones on the newest career
workbook so we only query the rated pool -- ~1.2k rows -- not every LoL pro
Leaguepedia has ever heard of).  Names are matched by Leaguepedia's `Players.ID`
column, which is the player's canonical handle; most Oracle names round-trip
cleanly but a handful will be missed and left as unknown.

Run:
    poetry run python -m lps.fetch_player_status
    poetry run python -m lps.fetch_player_status --workbook player_ratings_career_2011_2026.xlsx
"""

from __future__ import annotations

import argparse
import csv
import logging
import re
import time
from pathlib import Path

import pandas as pd

from .config import INFO_DIR
from .export_web import _latest_career_workbook
from .io_oracle import latest_oracle_year, load_oracle_year
from .lp_client import LPClient
from .player_identity import label_map

logger = logging.getLogger(__name__)

PLAYER_STATUS_CSV = INFO_DIR / "player_status.csv"

# Strip player_identity's disambiguation suffixes off a workbook label so we can
# query Leaguepedia by the raw handle (Cargo's Players.ID). Order matters:
# collision `#N` first, then trailing `(League)`. Applied at query time only —
# the disambiguated label is preserved as the row's playername in the output
# CSV so downstream merges (export_web) line up with the workbook.
_COLLISION_SUFFIX_RE = re.compile(r"\s*#\d+\s*$")
_LEAGUE_SUFFIX_RE = re.compile(r"\s*\([^)]+\)\s*$")


def _base_handle(name: str) -> str:
    n = _COLLISION_SUFFIX_RE.sub("", str(name))
    return _LEAGUE_SUFFIX_RE.sub("", n).strip()

# Cargo's URL length limit -- keep IN() batches modest.  Batches >100 have
# been observed to trip internal_api_error_MWException; adding Team + OverviewPage
# columns bloats each row too, so 25 stays comfortably under Fandom's per-request
# work limit.
_BATCH = 25
# Polite pacing between batches to avoid the Fandom API rate limit (60/min ish).
_PACE_SECONDS = 2.0


def _rated_playernames(workbook: Path, min_games: int = 100) -> list[str]:
    df = pd.read_excel(workbook, sheet_name="Overview")
    df = df[df["Games"] >= min_games]
    return df["Player"].astype(str).tolist()


def _career_teams_by_name(workbook: Path, min_games: int = 100) -> dict[str, set[str]]:
    """Parse the Overview sheet's 'Teams (by CLR)' column into
    {playername -> set of team names}. Used to disambiguate Cargo rows for
    handles shared across people (Wolf, Knight, ...) -- prefer the row whose
    Team matches one of this player's actual career teams."""
    df = pd.read_excel(workbook, sheet_name="Overview")
    df = df[df["Games"] >= min_games]
    team_col = next((c for c in df.columns if "Teams" in str(c)), None)
    if team_col is None:
        return {}
    entry_re = re.compile(r"^\s*(.+?)\s*\([\d.%]+\)\s*$")
    out: dict[str, set[str]] = {}
    for name, s in zip(df["Player"].astype(str), df[team_col].astype(str)):
        if not isinstance(s, str) or not s.strip() or s == "nan":
            continue
        teams: set[str] = set()
        for part in s.split(", "):
            m = entry_re.match(part)
            if m:
                teams.add(m.group(1).strip().lower())
        if teams:
            out[name] = teams
    return out


# Wolf's page has `|isretiredplayer=Yes`; the template accepts Yes/True/1/Y.
_RETIRED_AS_PLAYER_RE = re.compile(
    r"^\s*\|\s*isretiredplayer\s*=\s*(Yes|True|1|Y)\b",
    re.IGNORECASE | re.MULTILINE,
)


def _current_season_names(year: int) -> set[str]:
    """Playernames with any recorded games in a given Oracle year -- the set
    we skip the wikitext scrape for (they're definitionally still players)."""
    try:
        df = load_oracle_year(year)
    except FileNotFoundError:
        logger.warning("[status] no Oracle CSV for %d -- can't skip active names", year)
        return set()
    if "position" in df.columns:
        df = df[df["position"] != "team"]
    name_col = "playername" if "playername" in df.columns else "player"
    if name_col not in df.columns:
        return set()
    # Bridge raw Oracle names to the canonical labels used on Leaguepedia
    # (Knight -> Knight (LPL)); needed so the skip-set matches the query IDs.
    lm = label_map()
    if "playerid" in df.columns:
        canon = df["playerid"].map(lm).fillna(df[name_col])
    else:
        canon = df[name_col]
    return set(canon.dropna().astype(str))


def _scrape_isretiredplayer(client: LPClient, page_names: list[str]) -> dict[str, bool]:
    """Fetch each page's wikitext and grep for `|isretiredplayer=Yes` in its
    Infobox Player call. The flag is only in the raw wikitext (not Cargo), so
    this is the authoritative source for the "Retired as Player" state that
    Leaguepedia's UI shows for players who moved to coaching/streaming.

    Returns {overview_page -> bool}. Pages that fail to fetch are omitted."""
    site = client.client.client  # underlying mwclient Site
    out: dict[str, bool] = {}
    for i, name in enumerate(page_names):
        try:
            txt = site.pages[name].text() or ""
        except Exception as e:
            logger.debug("[status] wikitext fetch failed for %s: %s", name, e)
            continue
        out[name] = bool(_RETIRED_AS_PLAYER_RE.search(txt))
        # Modest pacing so we don't rate-limit the API on ~200-300 pages.
        if (i + 1) % 25 == 0:
            logger.info("[status] scraped %d/%d pages", i + 1, len(page_names))
            time.sleep(1.0)
    return out


def _team_matches_career(cargo_team: str, career: set[str]) -> bool:
    """Match Cargo `Team` against the player's Oracle career teams. Exact
    (case-insensitive) first, then substring either direction so that
    organization rebrands (SK Telecom T1 → T1, Longzhu → KZ, ...) still line
    up. Requires the shorter side to be >=2 chars to avoid empty matches."""
    t = str(cargo_team).strip().lower()
    if not t:
        return False
    if t in career:
        return True
    return any(
        (len(t) >= 2 and t in c) or (len(c) >= 2 and c in t)
        for c in career
    )


def _attribute_to_names(
    df: pd.DataFrame,
    handle_by_name: dict[str, str],
    teams_by_name: dict[str, set[str]],
) -> pd.DataFrame:
    """Expand Cargo rows (keyed by base handle) into per-workbook-label rows.

    A single base handle like "Knight" may correspond to multiple disambiguated
    workbook labels ("Knight (LPL)", "Knight (VCS)", ...) AND Cargo itself may
    return multiple rows for that handle (six different Wolfs). For each label
    we pick the Cargo row whose `team` best matches that label's Oracle career
    teams; without a career-team match we fall back to the first row so
    unambiguous handles ("Faker", "Xiaohu") still resolve.

    Emits one row per label that has any Cargo hit, with `playername` set to
    the disambiguated label. Labels with no matching Cargo row are dropped —
    their badge stays blank, which is the correct default for unknown status."""
    # Case-insensitive group lookup: Cargo stores IDs with whatever casing the
    # player registered (`FIX`, `illusion`, `khaN`), but our workbook labels use
    # their own casing (`Fix`, `illuSioN`, `Khan`). Fandom's `IN (...)` match is
    # case-insensitive so the rows come back — we just have to key attribution
    # case-insensitively too or the exact-case lookup drops them.
    df = df.copy()
    df["_handle_lc"] = df["handle"].astype(str).str.lower()
    by_handle: dict[str, pd.DataFrame] = {h: g for h, g in df.groupby("_handle_lc", sort=False)}
    out_rows: list[pd.Series] = []
    n_team_disambig = 0
    missing: list[str] = []
    for name, handle in handle_by_name.items():
        g = by_handle.get(handle.lower())
        if g is None or not len(g):
            missing.append(name)
            continue
        picked = None
        if len(g) > 1:
            career = teams_by_name.get(name, set())
            if career:
                mask = g["team"].apply(lambda t: _team_matches_career(t, career))
                if mask.any():
                    picked = g[mask].iloc[0]
                    n_team_disambig += 1
        if picked is None:
            picked = g.iloc[0]
        row = picked.copy()
        row["playername"] = name
        out_rows.append(row)
    if n_team_disambig:
        logger.info(
            "[status] disambiguated %d colliding handles by career team match",
            n_team_disambig,
        )
    if missing:
        logger.info(
            "[status] %d labels had no Cargo hit (status unknown): %s",
            len(missing), ", ".join(sorted(missing)),
        )
    if not out_rows:
        return pd.DataFrame(columns=["playername", "is_retired", "country", "role", "team", "overview_page"])
    result = pd.DataFrame(out_rows).reset_index(drop=True)
    return result[["playername", "is_retired", "country", "role", "team", "overview_page"]]


def fetch_player_status(names: list[str], active_names: set[str] | None = None,
                       teams_by_name: dict[str, set[str]] | None = None) -> pd.DataFrame:
    """Query Leaguepedia's Players table for a list of player IDs.  Returns a
    frame (playername, is_retired, is_retired_as_player, country, role);
    players not found are dropped.

    `active_names` is the set of names known to be currently competing (from
    the latest Oracle season). For those we skip the wikitext scrape entirely
    -- they're clearly still players. For the rest of the not-Cargo-retired
    pool we fetch the page wikitext and parse `|isretiredplayer=Yes` from the
    infobox, which is the only source for the "Retired as Player" state."""
    client = LPClient()
    if client.client is None:
        raise RuntimeError(
            "Leaguepedia client failed to init -- check LP_USERNAME/LP_PASSWORD in .env"
        )

    # Map every requested (possibly disambiguated) workbook label to its base
    # Leaguepedia handle. Cargo's Players.ID is the raw handle -- querying
    # "Knight (LPL)" returns nothing, so we query "Knight" and re-attribute the
    # returned rows below. Multiple labels can share a base handle (Knight (LPL),
    # Knight (VCS), Knight (NA LCS)); teams_by_name disambiguates them per label.
    handle_by_name: dict[str, str] = {n: _base_handle(n) for n in names}
    base_handles = sorted({h for h in handle_by_name.values() if h})
    n_disambig = sum(1 for n, h in handle_by_name.items() if n != h)
    if n_disambig:
        logger.info(
            "[status] %d workbook labels have disambiguation suffixes -- querying by base handle",
            n_disambig,
        )

    rows: list[dict] = []
    n_batches = (len(base_handles) + _BATCH - 1) // _BATCH
    for bi, i in enumerate(range(0, len(base_handles), _BATCH)):
        batch = base_handles[i:i + _BATCH]
        # Cargo strings need double-quote escaping.
        in_list = ",".join('"' + n.replace('"', '\\"') + '"' for n in batch)
        logger.info("[status] batch %d/%d (%d names)", bi + 1, n_batches, len(batch))
        res = client.query(
            tables="Players",
            fields="ID, IsRetired, Country, Role, Team, OverviewPage",
            where=f"ID IN ({in_list})",
        )
        rows.extend(res)
        if bi < n_batches - 1:
            time.sleep(_PACE_SECONDS)

    if not rows:
        raise RuntimeError("Leaguepedia returned no rows -- query likely malformed")

    df = pd.DataFrame(rows)
    # Cargo returns strings; coerce IsRetired -> bool.
    df["is_retired"] = df["IsRetired"].astype(str).str.strip().isin(("1", "true", "True", "Yes"))
    df = df.rename(columns={
        "ID": "handle", "Country": "country", "Role": "role",
        "Team": "team", "OverviewPage": "overview_page",
    })
    df = df[["handle", "is_retired", "country", "role", "team", "overview_page"]]

    # Redirect fallback: some handles are stored in Cargo under a different
    # `Players.ID` than the wiki page name — Koro1's page is `Korol` (lowercase
    # L, not digit 1), WeiXiao's is `Wx`, Reginald's ID is `ReginaId` (I not L).
    # The `PlayerRedirects` table maps every known alias/spelling
    # (`AllName`) to the canonical `OverviewPage`, and Players rows join on
    # OverviewPage. So: look up redirects for the unmatched handles, then query
    # Players by OverviewPage, then relabel the returned handle to the original
    # requested casing so `_attribute_to_names` (case-insensitive lookup below)
    # finds them.
    exact_hits = {h.lower() for h in df["handle"].astype(str)}
    unmatched = [h for h in base_handles if h.lower() not in exact_hits]
    if unmatched:
        logger.info("[status] redirect fallback for %d unmatched handles", len(unmatched))
        redir_map: dict[str, str] = {}  # requested handle -> OverviewPage
        for i in range(0, len(unmatched), _BATCH):
            batch = unmatched[i:i + _BATCH]
            in_list = ",".join('"' + n.replace('"', '\\"') + '"' for n in batch)
            res = client.query(
                tables="PlayerRedirects",
                fields="AllName, OverviewPage",
                where=f"AllName IN ({in_list})",
            )
            by_lower = {n.lower(): n for n in batch}
            for r in res:
                requested = by_lower.get(str(r.get("AllName", "")).lower())
                op = r.get("OverviewPage")
                if requested and op and requested not in redir_map:
                    redir_map[requested] = str(op)
            if i + _BATCH < len(unmatched):
                time.sleep(_PACE_SECONDS)
        if redir_map:
            page_to_handle: dict[str, str] = {}
            for h, op in redir_map.items():
                page_to_handle.setdefault(op.lower(), h)
            pages = list({op for op in redir_map.values()})
            fb_rows: list[dict] = []
            for i in range(0, len(pages), _BATCH):
                batch = pages[i:i + _BATCH]
                in_list = ",".join('"' + n.replace('"', '\\"') + '"' for n in batch)
                res = client.query(
                    tables="Players",
                    fields="ID, IsRetired, Country, Role, Team, OverviewPage",
                    where=f"OverviewPage IN ({in_list})",
                )
                for r in res:
                    op = str(r.get("OverviewPage", ""))
                    requested = page_to_handle.get(op.lower())
                    if requested is None:
                        continue
                    r = dict(r)
                    r["ID"] = requested
                    fb_rows.append(r)
                if i + _BATCH < len(pages):
                    time.sleep(_PACE_SECONDS)
            if fb_rows:
                fb = pd.DataFrame(fb_rows)
                fb["is_retired"] = fb["IsRetired"].astype(str).str.strip().isin(("1", "true", "True", "Yes"))
                fb = fb.rename(columns={
                    "ID": "handle", "Country": "country", "Role": "role",
                    "Team": "team", "OverviewPage": "overview_page",
                })
                fb = fb[["handle", "is_retired", "country", "role", "team", "overview_page"]]
                logger.info(
                    "[status] redirect fallback recovered %d handles (%d rows)",
                    fb["handle"].nunique(), len(fb),
                )
                df = pd.concat([df, fb], ignore_index=True)

    # Re-attribute Cargo rows (keyed by base handle) back to each disambiguated
    # workbook label. When multiple labels share a base handle, career-team
    # match picks the right Cargo row per label. Labels with no Cargo match are
    # dropped (status stays unknown).
    df = _attribute_to_names(df, handle_by_name, teams_by_name or {})
    if df.empty:
        raise RuntimeError("Leaguepedia returned no rows -- query likely malformed")

    # Gray zone: not-retired per Cargo AND not competing in the current season.
    # Everyone else: skip the wikitext scrape.
    active = active_names or set()
    gray = df[~df["is_retired"] & ~df["playername"].isin(active)]
    pages = gray["overview_page"].dropna().unique().tolist()
    logger.info(
        "[status] wikitext scrape: %d gray-zone pages (of %d total; %d Cargo-retired, %d active)",
        len(pages), len(df),
        int(df["is_retired"].sum()),
        int(df["playername"].isin(active).sum()),
    )

    rap_by_page = _scrape_isretiredplayer(client, pages) if pages else {}
    df["is_retired_as_player"] = df["overview_page"].map(rap_by_page).fillna(False).astype(bool)
    n_rap = int((df["is_retired_as_player"] & ~df["is_retired"]).sum())
    logger.info("[status] found %d retired-as-player (in addition to %d fully retired)",
                n_rap, int(df["is_retired"].sum()))
    return df


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(description="Fetch player status from Leaguepedia.")
    ap.add_argument("--workbook", type=Path, default=None,
                    help="career workbook to derive the name list from (default: newest)")
    ap.add_argument("--min-games", type=int, default=100,
                    help="rated-floor threshold used to pick the query set")
    ap.add_argument("--out", type=Path, default=PLAYER_STATUS_CSV,
                    help=f"output CSV (default: {PLAYER_STATUS_CSV})")
    args = ap.parse_args()

    wb = args.workbook or _latest_career_workbook()
    names = _rated_playernames(wb, args.min_games)
    teams_by_name = _career_teams_by_name(wb, args.min_games)
    active = _current_season_names(latest_oracle_year())
    logger.info(
        "[status] querying Leaguepedia for %d rated players (skipping wikitext scrape for %d currently-active)",
        len(names), len(active & set(names)),
    )
    df = fetch_player_status(names, active_names=active, teams_by_name=teams_by_name)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.out, index=False, quoting=csv.QUOTE_MINIMAL)
    logger.info(
        "[status] wrote %s  (%d rows; %d retired, %d retired-as-player)",
        args.out, len(df),
        int(df["is_retired"].sum()),
        int(df.get("is_retired_as_player", pd.Series(dtype=bool)).sum()),
    )


if __name__ == "__main__":
    main()
