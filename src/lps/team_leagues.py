"""
Resolve each team's home league and pair up opponents per game.

Two jobs, both needed by the scoring pipeline:

1. home league: a team's home league is simply the `league` it appears in most often
   in the Oracle data. Domestic seasons dwarf international events in game count (e.g.
   T1: 114 LCK games vs 27 Worlds / 25 MSI), so the mode is a robust home-league signal
   without having to enumerate which labels are international events.

2. opponent + domestic/international labelling: the two teams in a game are the two
   `side`s (Blue/Red) of the same gameid. A game is INTERNATIONAL exactly when the two
   teams' home leagues differ (this captures MSI/Worlds/EWC and correctly leaves Korean
   KeSPA Cup / Chinese Demacia Cup as domestic, since both teams share a home league).

The opponent's home league is what the scoring baseline uses (see scoring.league_baseline:
baseline = opponent league's strength).
"""

from __future__ import annotations

import logging
from typing import Optional

import pandas as pd

from .io_oracle import load_oracle_year

logging.basicConfig(level=logging.INFO, format="%(message)s")

_SIDE_OPPOSITE = {"Blue": "Red", "Red": "Blue"}


def resolve_home_leagues(df: pd.DataFrame) -> dict[str, str]:
    """
    Map each teamname to its home league = the league it plays in most often.

    Ties are broken by the highest game count (arbitrary among exact ties).
    """
    pair_counts = (
        df.dropna(subset=["teamname", "league"])
        .groupby(["teamname", "league"])
        .size()
        .reset_index(name="n")
    )
    # Most-played league per team.
    home = (
        pair_counts.sort_values("n", ascending=False)
        .drop_duplicates("teamname")
        .set_index("teamname")["league"]
    )
    return home.to_dict()


def build_team_game_table(
    df: pd.DataFrame,
    home_leagues: Optional[dict[str, str]] = None,
) -> pd.DataFrame:
    """
    One row per (gameid, side) with its opponent and home-league labelling.

    Columns:
        gameid, side, teamname, game_label (the raw Oracle `league` for that game),
        result, own_league, opp_teamname, opp_league, is_international

    - own_league / opp_league are HOME leagues (may be None if a team is unmapped).
    - is_international is True only when both home leagues are known and differ.
    """
    if home_leagues is None:
        home_leagues = resolve_home_leagues(df)

    # Collapse to one row per team-game. All rows within a (gameid, side) share
    # teamname / league / result / playoffs, so 'first' is safe.
    agg_kwargs = dict(
        teamname=("teamname", "first"),
        game_label=("league", "first"),
        result=("result", "first"),
    )
    if "playoffs" in df.columns:
        agg_kwargs["playoffs"] = ("playoffs", "first")
    tg = (
        df.dropna(subset=["gameid", "side", "teamname"])
        .groupby(["gameid", "side"], as_index=False)
        .agg(**agg_kwargs)
    )

    # Attach the opponent (the other side of the same gameid).
    opp = tg[["gameid", "side", "teamname"]].copy()
    opp["side"] = opp["side"].map(_SIDE_OPPOSITE)
    opp = opp.rename(columns={"teamname": "opp_teamname"})
    tg = tg.merge(opp, on=["gameid", "side"], how="left")

    # Home leagues for both sides.
    tg["own_league"] = tg["teamname"].map(home_leagues)
    tg["opp_league"] = tg["opp_teamname"].map(home_leagues)
    tg["is_international"] = (
        tg["own_league"].notna()
        & tg["opp_league"].notna()
        & (tg["own_league"] != tg["opp_league"])
    )

    return tg


def _demo(year: int = 2024) -> None:
    """Sanity-check home-league resolution and domestic/international labelling."""
    from .scoring import load_league_elos

    df = load_oracle_year(year)
    rated = set(load_league_elos(year))

    homes = resolve_home_leagues(df)
    rated_teams = {t: lg for t, lg in homes.items() if lg in rated}
    logging.info(
        f"{year}: {len(homes)} teams resolved, {len(rated_teams)} in a rated league "
        f"({', '.join(sorted(rated))})"
    )

    tg = build_team_game_table(df, homes)
    # Focus on team-games whose own league is rated (the ones we can score).
    scorable = tg[tg["own_league"].isin(rated)]
    dom = (~scorable["is_international"]).sum()
    intl = scorable["is_international"].sum()
    logging.info(f"Rated-team-games: {len(scorable):,}  ({dom:,} domestic, {intl:,} international)")

    # Sample a few international matchups to eyeball correctness.
    logging.info("\nSample international matchups (own -> opp home leagues):")
    sample = (
        tg[tg["is_international"]]
        [["game_label", "teamname", "own_league", "opp_teamname", "opp_league"]]
        .drop_duplicates("teamname")
        .head(12)
    )
    for _, r in sample.iterrows():
        logging.info(
            f"  [{r['game_label']:<5}] {r['teamname']:<18} ({r['own_league']}) "
            f"vs {r['opp_teamname']:<18} ({r['opp_league']})"
        )


if __name__ == "__main__":
    _demo()
