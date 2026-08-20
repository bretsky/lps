"""
Leaguepedia ScoreboardPlayers ingestion for years/regions Oracle's Elixir doesn't cover.

Oracle box-score data starts 2014 and is Western-only until Korea (2015) and China (2016)
appear. To let career stats accumulate from the missing years, we pull per-player
scoreboards from Leaguepedia's Cargo `ScoreboardPlayers` table and adapt them into the same
schema the scoring pipeline consumes.

Pre-2015 the only reliably-populated stats are KDA + CS (damage-to-champions and, often,
gold are empty), so the downstream model is a REDUCED one (see lp_reduced.py): per-position
kills/deaths/assists/CS, no damage / first blood / @15 timeline.

Fetched data is cached to data/leaguepedia/scoreboards/<year>.parquet so we don't re-hit the
API. Run:  poetry run python -m lps.lp_ingest --years 2013-2015
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Optional

import pandas as pd

from .config import DATA_DIR
from .lp_client import LPClient

logger = logging.getLogger(__name__)

_SB_DIR = DATA_DIR / "leaguepedia" / "scoreboards"

# Leaguepedia Tournaments.League -> our Elo/Oracle league code (also the game_label).
LEAGUE_MAP = {
    "LoL The Champions": "OGN",
    "LoL Champions Korea": "LCK",
    "Tencent LoL Pro League": "LPL",
    "LoL Pro League": "LPL",
    "LoL Master Series": "LMS",
    "Europe League Championship Series": "EU LCS",
    "North America League Championship Series": "NA LCS",
    "World Championship": "WLDs",
    "Mid-Season Invitational": "MSI",
    "Garena Premier League": "GPL",
    "Circuit Brazilian League of Legends": "CBLOL",
    "Turkish Championship League": "TCL",
    "Vietnam Championship Series A": "VCS",
}
_ROLE_MAP = {"Top": "top", "Jungle": "jng", "Mid": "mid", "Bot": "bot", "Support": "sup"}

# Which leagues to pull per year (only the gaps Oracle lacks). 2014/2015 West is in Oracle.
GAP_SPECS: dict[int, list[str]] = {
    2013: ["LoL The Champions", "Tencent LoL Pro League",
           "Europe League Championship Series", "North America League Championship Series",
           "World Championship"],
    2014: ["LoL The Champions", "Tencent LoL Pro League", "World Championship"],  # East + Worlds
    2015: ["Tencent LoL Pro League"],                                              # China only
}

_FIELDS = ("SP.Link=playername, SP.Champion=champion, SP.Kills=kills, SP.Deaths=deaths, "
           "SP.Assists=assists, SP.CS=cs, SP.Gold=gold, SP.Team=teamname, SP.Role=role, "
           "SP.Side=side, SP.PlayerWin=win, SP.GameId=gameid, SP.DateTime_UTC=date, "
           "T.League=lp_league, T.Year=year")


def _fetch_league_year(lp: LPClient, league: str, year: int) -> pd.DataFrame:
    league_esc = league.replace("'", "\\'")
    rows = lp.query(
        tables="ScoreboardPlayers=SP, Tournaments=T",
        join_on="SP.OverviewPage=T.OverviewPage",
        fields=_FIELDS,
        where=f"T.League='{league_esc}' AND T.Year={year}",
    )
    return pd.DataFrame(rows)


def _fetch_gamelengths(lp: LPClient, league: str, year: int) -> pd.DataFrame:
    """Per-game length (minutes) from ScoreboardGames, joinable to players by GameId."""
    league_esc = league.replace("'", "\\'")
    rows = lp.query(
        tables="ScoreboardGames=SG, Tournaments=T",
        join_on="SG.OverviewPage=T.OverviewPage",
        fields="SG.GameId=gameid, SG.Gamelength_Number=gamelength",
        where=f"T.League='{league_esc}' AND T.Year={year}",
    )
    return pd.DataFrame(rows)


def _adapt(df: pd.DataFrame) -> pd.DataFrame:
    """Adapt raw ScoreboardPlayers rows into the pipeline's per-player-game schema."""
    if df.empty:
        return df
    out = pd.DataFrame()
    out["gameid"] = df["gameid"].astype(str)
    # ScoreboardPlayers Side is "1"/"2"; map to Blue/Red so opponent pairing (team_leagues)
    # matches the rest of the pipeline.
    out["side"] = df["side"].astype(str).map({"1": "Blue", "2": "Red"}).fillna(df["side"].astype(str))
    out["position"] = df["role"].map(_ROLE_MAP)
    # Leaguepedia disambiguates handles as "Uzi (Jian Zi-Hao)"; strip the parenthetical so
    # names match Oracle's short handles ("Uzi") for cross-source career merging.
    out["playername"] = df["playername"].astype(str).str.replace(r"\s*\(.*\)\s*$", "", regex=True)
    out["teamname"] = df["teamname"].astype(str)
    out["league"] = df["lp_league"].map(LEAGUE_MAP).fillna(df["lp_league"])
    for c in ("kills", "deaths", "assists", "cs"):
        out[c] = pd.to_numeric(df[c], errors="coerce")
    out["result"] = (df["win"].astype(str).str.lower() == "yes").astype(int)
    out["champion"] = df["champion"].astype(str)
    out["date"] = pd.to_datetime(df["date"], errors="coerce")
    out["year"] = pd.to_numeric(df["year"], errors="coerce").astype("Int64")
    out["datacompleteness"] = "complete"
    # Keep only real lanes with a parsed KDA/CS and both sides present.
    out = out[out["position"].notna()]
    out = out.dropna(subset=["kills", "deaths", "assists", "cs"])
    return out.reset_index(drop=True)


def fetch_year(year: int, leagues: Optional[list[str]] = None,
               lp: Optional[LPClient] = None) -> pd.DataFrame:
    """Fetch + adapt all gap leagues for a year (defaults to GAP_SPECS[year])."""
    leagues = leagues if leagues is not None else GAP_SPECS.get(year, [])
    lp = lp or LPClient()
    parts, lens = [], []
    for lg in leagues:
        raw = _fetch_league_year(lp, lg, year)
        adapted = _adapt(raw)
        logger.info(f"[lp_ingest] {year} {lg}: {len(raw)} rows -> {len(adapted)} adapted "
                    f"({adapted['gameid'].nunique() if len(adapted) else 0} games, "
                    f"{LEAGUE_MAP.get(lg, lg)})")
        if len(adapted):
            parts.append(adapted)
            lens.append(_fetch_gamelengths(lp, lg, year))
    if not parts:
        return pd.DataFrame()
    df = pd.concat(parts, ignore_index=True)
    # Attach game length (minutes) for the game-state context features (see lp_reduced).
    gl = pd.concat(lens, ignore_index=True).drop_duplicates("gameid")
    gl_map = dict(zip(gl["gameid"].astype(str), pd.to_numeric(gl["gamelength"], errors="coerce")))
    df["gamelength"] = df["gameid"].astype(str).map(gl_map)
    return df


def save_year(year: int, df: pd.DataFrame) -> Path:
    _SB_DIR.mkdir(parents=True, exist_ok=True)
    path = _SB_DIR / f"{year}.pkl"
    df.to_pickle(path)
    return path


def load_year(year: int) -> pd.DataFrame:
    path = _SB_DIR / f"{year}.pkl"
    if not path.exists():
        raise FileNotFoundError(f"no ingested Leaguepedia scoreboard for {year}: {path}")
    return pd.read_pickle(path)


def _parse_years(s: str) -> list[int]:
    if "-" in s:
        a, b = s.split("-"); return list(range(int(a), int(b) + 1))
    return [int(x) for x in s.split(",")]


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(description="Fetch + cache Leaguepedia scoreboards for gap years.")
    ap.add_argument("--years", type=str, default="2013-2015")
    args = ap.parse_args()

    lp = LPClient()
    for year in _parse_years(args.years):
        df = fetch_year(year, lp=lp)
        if len(df):
            path = save_year(year, df)
            logger.info(f"[lp_ingest] {year}: saved {len(df)} player-games -> {path}")
        else:
            logger.warning(f"[lp_ingest] {year}: no data fetched")


if __name__ == "__main__":
    main()
