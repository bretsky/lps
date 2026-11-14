"""
Fetch per-player, per-year team history from Leaguepedia and cache team logos.

Writes two files:
  data/leaguepedia/player_history.json  -- {player: {year: [team, ...]}}
  data/leaguepedia/team_logos.json      -- {team_name: logo_url | null}

Uses ScoreboardPlayers joined to Tournaments for historically-accurate team
names (e.g. "DragonX" for Keria in 2020, not the current "Kiwoom DRX").
Logo URLs are resolved via the Leaguepedia Cargo Teams table (filename) then
the MediaWiki imageinfo API (direct CDN URL); teams not found get null and
the frontend falls back to the text name.

Run:
    poetry run python -m lps.fetch_player_history
    poetry run python -m lps.fetch_player_history --players Faker Keria Caps
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

from .config import LEAGUEPEDIA_DIR, PROJECT_ROOT
from .lp_client import LPClient

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

PLAYER_HISTORY_JSON = LEAGUEPEDIA_DIR / "player_history.json"
TEAM_LOGOS_JSON     = LEAGUEPEDIA_DIR / "team_logos.json"

# Team name substrings that indicate all-star exhibitions with no stable logo page.
# Used only when looking up logos — history filtering uses TournamentLevel instead.
_SKIP_LOGO_PATTERNS = ("allstars", "all-stars", "all stars")

# Team names matching this pattern are national/regional representations, not org contracts.
# These are excluded from player history regardless of TournamentLevel (e.g. Asian Games 2018
# is classified as Primary but South Korea (National Team) is still not an org affiliation).
_NATIONAL_TEAM_RE = re.compile(r"national\s+team", re.IGNORECASE)

# Filename variants to try when the Teams cargo table has no entry for a team.
# Leaguepedia filenames follow the pattern: {name}logo {variant}.png
_LOGO_VARIANTS = ("profile", "square", "std")

# Batch size for IN() queries — Leaguepedia Cargo handles ~100 names fine.
_BATCH = 80

# MediaWiki imageinfo API supports up to 50 titles per request.
_IMG_BATCH = 50
_MW_API = "https://lol.fandom.com/api.php"
_MW_UA  = "LPS-bot/1.0 (league-performance-score)"


def _resolve_image_urls(filenames: list[str]) -> dict[str, str]:
    """Batch-resolve Leaguepedia wiki filenames to direct CDN URLs via imageinfo API.

    Returns {filename: cdn_url} for filenames that resolved successfully.
    """
    resolved: dict[str, str] = {}
    for i in range(0, len(filenames), _IMG_BATCH):
        batch = filenames[i : i + _IMG_BATCH]
        titles = "|".join(f"File:{fn}" for fn in batch)
        params = urllib.parse.urlencode({
            "action": "query",
            "titles": titles,
            "prop": "imageinfo",
            "iiprop": "url",
            "format": "json",
        })
        req = urllib.request.Request(
            f"{_MW_API}?{params}",
            headers={"User-Agent": _MW_UA},
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            for page in data.get("query", {}).get("pages", {}).values():
                title = page.get("title", "")          # "File:T1logo profile.png"
                if not title.startswith("File:"):
                    continue
                filename = title[len("File:"):]
                info = page.get("imageinfo", [])
                if info and info[0].get("url"):
                    resolved[filename] = info[0]["url"]
        except Exception as exc:
            logger.warning("[logos] imageinfo API error for batch %d: %s", i, exc)
        time.sleep(0.5)
    return resolved


def _escape(s: str) -> str:
    return s.replace("'", "\\'")


def fetch_player_history(
    player_names: list[str],
    lp: LPClient,
) -> dict[str, dict[str, list[str]]]:
    """Return {player: {year: [team, ...]}} from ScoreboardPlayers + Tournaments.

    Uses GROUP BY to collapse per-game rows to unique (player, team, year) tuples.
    Multiple teams per year (mid-season transfers) are preserved in order of first
    appearance.
    """
    out: dict[str, dict[str, list[str]]] = {}
    names = list(player_names)
    total = len(names)

    for i in range(0, total, _BATCH):
        batch = names[i : i + _BATCH]
        quoted = ", ".join(f'"{_escape(n)}"' for n in batch)
        logger.info(
            "[history] querying %d/%d players (batch %d–%d)",
            min(i + _BATCH, total), total, i + 1, i + len(batch),
        )
        rows = lp.query(
            tables="ScoreboardPlayers=SP, Tournaments=T",
            join_on="SP.OverviewPage=T.OverviewPage",
            fields="SP.Link=player, SP.Team=team, T.Year=year",
            where=f'SP.Link IN ({quoted}) AND T.TournamentLevel NOT IN ("Showmatch", "AllStar")',
            group_by="SP.Link, SP.Team, T.Year",
            order_by="T.Year, SP.Link",
        )
        for r in rows:
            player = (r.get("player") or "").strip()
            team   = (r.get("team")   or "").strip()
            year   = (r.get("year")   or "").strip()
            if not (player and team and year):
                continue
            if _NATIONAL_TEAM_RE.search(team):
                continue
            by_year = out.setdefault(player, {})
            teams_this_year = by_year.setdefault(year, [])
            if team not in teams_this_year:
                teams_this_year.append(team)
        time.sleep(1)

    logger.info("[history] fetched history for %d players", len(out))
    return out


def fetch_team_logos(
    team_names: set[str],
    lp: LPClient,
    existing: dict[str, str | None] | None = None,
) -> dict[str, str | None]:
    """Return {team_name: direct_cdn_logo_url | null}.

    Two-step: (1) Cargo Teams table gives the wiki filename per team name.
    (2) MediaWiki imageinfo API resolves each filename to the actual CDN URL.
    Teams not in the Teams table, or whose image can't be resolved, get null.
    Skips national/all-star pseudo-teams. Merges with `existing` for incremental runs.
    """
    logos: dict[str, str | None] = dict(existing or {})
    to_fetch = sorted(
        n for n in team_names
        if n not in logos
        and not any(pat in n.lower() for pat in _SKIP_LOGO_PATTERNS)
    )
    if not to_fetch:
        return logos

    logger.info("[logos] looking up %d team names in Cargo", len(to_fetch))
    # Step 1: team name → wiki filename
    name_to_filename: dict[str, str] = {}
    for i in range(0, len(to_fetch), _BATCH):
        batch = to_fetch[i : i + _BATCH]
        quoted = ", ".join(f'"{_escape(n)}"' for n in batch)
        rows = lp.query(
            tables="Teams",
            fields="Name=name, Image=image",
            where=f"Name IN ({quoted}) AND Image != \"\"",
        )
        for r in rows:
            if r.get("name") and r.get("image"):
                name_to_filename[r["name"]] = r["image"]
        time.sleep(1)

    logger.info("[logos] %d/%d teams have a wiki filename", len(name_to_filename), len(to_fetch))

    # Step 2: wiki filename → direct CDN URL via imageinfo API
    filenames = list(set(name_to_filename.values()))
    logger.info("[logos] resolving %d filenames via imageinfo API", len(filenames))
    filename_to_url = _resolve_image_urls(filenames)

    # Step 3: fallback for teams not in the Teams table — guess filename pattern
    # Leaguepedia uses "{name}logo {variant}.png" (no separator, space before variant).
    missing_names = [n for n in to_fetch if n not in name_to_filename or name_to_filename[n] not in filename_to_url]
    if missing_names:
        logger.info("[logos] trying filename fallback for %d teams not in Teams table", len(missing_names))
        guess_filenames: list[str] = []
        for name in missing_names:
            for variant in _LOGO_VARIANTS:
                guess_filenames.append(f"{name}logo {variant}.png")
        guessed_urls = _resolve_image_urls(guess_filenames)
        for name in missing_names:
            for variant in _LOGO_VARIANTS:
                fn = f"{name}logo {variant}.png"
                if fn in guessed_urls:
                    name_to_filename[name] = fn
                    filename_to_url[fn] = guessed_urls[fn]
                    break

    # Combine and mark nulls for teams with no entry
    for name in to_fetch:
        filename = name_to_filename.get(name)
        if filename and filename in filename_to_url:
            logos[name] = filename_to_url[filename]
        else:
            logos[name] = None

    found_count = sum(1 for v in logos.values() if v)
    logger.info("[logos] resolved %d/%d team logos", found_count, len(logos))
    return logos


def _all_player_names() -> list[str]:
    """Read player names from the latest career workbook (same source as export_web)."""
    from .career import _career_layout, YEARS_DEFAULT
    import openpyxl, glob

    pattern = str(PROJECT_ROOT / "player_ratings_career_*.xlsx")
    files = sorted(glob.glob(pattern))
    if not files:
        raise FileNotFoundError(f"No workbook found matching {pattern}")
    wb_path = files[-1]
    logger.info("[history] reading player names from %s", wb_path)
    wb = openpyxl.load_workbook(wb_path, read_only=True, data_only=True)
    ws = wb["Overview"]
    rows = list(ws.iter_rows(values_only=True))
    headers = [str(h).strip() if h is not None else "" for h in rows[0]]
    candidates = ("playername", "Playername", "Player", "player")
    name_idx = next(
        (headers.index(c) for c in candidates if c in headers), None
    )
    if name_idx is None:
        raise ValueError(f"No player name column found in Overview sheet. Headers: {headers[:10]}")
    names = [str(r[name_idx]).strip() for r in rows[1:] if r[name_idx]]
    wb.close()
    return names


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--players", nargs="+", metavar="NAME",
        help="Specific player names to fetch (default: all from workbook).",
    )
    args = parser.parse_args()

    lp = LPClient()

    # Load existing caches so incremental re-runs only add new data.
    history: dict[str, dict[str, list[str]]] = {}
    if PLAYER_HISTORY_JSON.exists():
        history = json.loads(PLAYER_HISTORY_JSON.read_text(encoding="utf-8"))
        logger.info("[history] loaded %d cached players", len(history))

    logos: dict[str, str | None] = {}
    if TEAM_LOGOS_JSON.exists():
        logos = json.loads(TEAM_LOGOS_JSON.read_text(encoding="utf-8"))
        logger.info("[logos] loaded %d cached team entries", len(logos))

    # Player names to fetch.
    if args.players:
        names = args.players
    else:
        names = _all_player_names()

    new_history = fetch_player_history(names, lp)
    # Merge: overwrite with fresh data for fetched players, keep others.
    history.update(new_history)

    # Collect all unique team names across updated history.
    all_teams: set[str] = set()
    for by_year in history.values():
        for teams in by_year.values():
            all_teams.update(teams)

    logos = fetch_team_logos(all_teams, lp, existing=logos)

    LEAGUEPEDIA_DIR.mkdir(parents=True, exist_ok=True)
    PLAYER_HISTORY_JSON.write_text(
        json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    TEAM_LOGOS_JSON.write_text(
        json.dumps(logos, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logger.info("[history] wrote %s", PLAYER_HISTORY_JSON)
    logger.info("[logos]   wrote %s", TEAM_LOGOS_JSON)


if __name__ == "__main__":
    main()
