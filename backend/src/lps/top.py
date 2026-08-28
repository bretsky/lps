from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence

import numpy as np
import pandas as pd

from .config import ORACLE_DIR
from .io_oracle import load_oracle_years


TOP_POS_LABELS = {"top", "Top", "TOP"}


@dataclass
class TopLaneConfig:
    """Hyperparameters for top-lane LPS v1."""

    min_games_season: int = 10
    replacement_quantile: float = 0.2  # bottom 20% = replacement
    career_exponent: float = 0.9  # concavity for career value
    z_eps: float = 1e-9


def _detect_cols(df: pd.DataFrame) -> dict:
    """Detect key column names (player, game, pos, league, year, split) with fallbacks."""
    cols = df.columns

    # Player identifier
    if "playername" in cols:
        player_col = "playername"
    elif "player" in cols:
        player_col = "player"
    else:
        raise KeyError("Could not find a player column (expected 'playername' or 'player').")

    # Game identifier
    if "gameid" in cols:
        game_col = "gameid"
    elif "game" in cols:
        game_col = "game"
    else:
        raise KeyError("Could not find a game id column (expected 'gameid' or 'game').")

    # Position
    if "position" in cols:
        pos_col = "position"
    elif "role" in cols:
        pos_col = "role"
    else:
        raise KeyError("Could not find a position column (expected 'position' or 'role').")

    # League
    if "league" in cols:
        league_col = "league"
    else:
        raise KeyError("Could not find a league column (expected 'league').")

    # Year
    if "year" in cols:
        year_col = "year"
    else:
        year_col = None

    # Split / season
    split_col = None
    for c in ("split", "season"):
        if c in cols:
            split_col = c
            break

    return {
        "player": player_col,
        "game": game_col,
        "pos": pos_col,
        "league": league_col,
        "year": year_col,
        "split": split_col,
    }


def _make_season_id(df: pd.DataFrame, year_col: Optional[str], split_col: Optional[str]) -> pd.Series:
    """Create a season_id string like '2022_Spring' or just '2022' as fallback."""
    if year_col is not None and split_col is not None:
        return df[year_col].astype(str) + "_" + df[split_col].astype(str)
    if year_col is not None:
        return df[year_col].astype(str)
    # Worst case: no year, no split; treat all as one season
    return pd.Series(["unknown"] * len(df), index=df.index)


def _filter_top_players(df: pd.DataFrame, cfg: TopLaneConfig) -> pd.DataFrame:
    """Filter Oracle dataset to only top-lane player rows with complete data."""
    cols = _detect_cols(df)
    pos_col = cols["pos"]

    out = df.copy()

    # Normalize position labels
    out[pos_col] = out[pos_col].astype(str)

    # Player rows only (Oracle team rows usually have position = 'team')
    mask_player = ~out[pos_col].str.lower().eq("team")
    out = out[mask_player]

    # Top lane only
    mask_top = out[pos_col].isin(TOP_POS_LABELS) | out[pos_col].str.lower().eq("top")
    out = out[mask_top]

    # Keep only complete games if the flag exists
    if "datacompleteness" in out.columns:
        out = out[out["datacompleteness"] == "complete"]

    # Season identifie
