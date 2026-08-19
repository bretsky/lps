"""
Model 1 as an expected-stats provider for the contribution attribution.

player_contribution.py already trains Model 1, but its trainer is built for reporting,
not for feeding expected values back into the win-prob decomposition. This module is the
thin wrapper that does exactly that: for each player-game it predicts the MEAN of the five
lane stats Model 2 consumes, given game context (champion, opponent champion, gold share,
game length, game totals).

These expected values become the reference in contribution.contributions_for_frame, so a
player's contribution is measured against "what an average player would do in THIS game
context" (e.g. a tank's low kills are expected, not a demerit) instead of a flat global
mean.

Reuses build_game_state_features() from player_contribution.py for the feature set, and
predicts IN-SAMPLE on the same games being scored (Model 1 is used as a conditional-mean
smoother, so in-sample prediction is acceptable; the features are champion + game
aggregates, which can't memorize an individual player's game).
"""

from __future__ import annotations

import logging
from typing import Optional, Sequence

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

from .contribution import LANE_STATS, ROLES
from .player_contribution import ExpectedPerformanceConfig, build_game_state_features

logging.basicConfig(level=logging.INFO, format="%(message)s")

# Game-state features used to predict each lane stat (subset of player_contribution's
# feature_map, restricted to the five stats Model 2 consumes).
FEATURE_MAP: dict[str, list[str]] = {
    "kills_nonfb": ["_gold_share", "_game_total_kills", "_gamelength_min", "champion"],
    "deaths_nonfb": ["_game_total_kills", "_gamelength_min", "champion"],
    "assists_nonfb": ["_gold_share", "_game_total_kills", "_gamelength_min", "champion"],
    "damagetochampions": ["_gold_share", "champion", "_gamelength_min", "_game_total_damagetochampions"],
}

_CATEGORICAL = ("champion", "oppchampion")


def _decompose_kda(df: pd.DataFrame) -> pd.DataFrame:
    """Add kills_nonfb / deaths_nonfb / assists_nonfb (first-blood-removed KDA)."""
    df = df.copy()
    # firstblood terms fillna(0): the LPL lacks firstbloodassist/victim, so treat a
    # missing flag as no adjustment (negligible +/-1 on one event per game).
    if "kills" in df.columns and "firstbloodkill" in df.columns:
        df["kills_nonfb"] = df["kills"] - df["firstbloodkill"].fillna(0)
    if "assists" in df.columns and "firstbloodassist" in df.columns:
        df["assists_nonfb"] = df["assists"] - df["firstbloodassist"].fillna(0)
    if "deaths" in df.columns and "firstbloodvictim" in df.columns:
        df["deaths_nonfb"] = df["deaths"] - df["firstbloodvictim"].fillna(0)
    return df


def compute_expected_stats(
    df: pd.DataFrame,
    roles: Sequence[str] = ROLES,
    max_iter: int = 150,
) -> pd.DataFrame:
    """
    Expected (mean) value of each lane stat per player-game, from Model 1.

    Args:
        df: raw Oracle rows (one year).
        roles: positions to model.
        max_iter: HistGradientBoostingRegressor boosting iterations.

    Returns:
        Long table: one row per (gameid, side, position) with columns
        exp_kills_nonfb, exp_deaths_nonfb, exp_assists_nonfb, exp_damagetochampions,
        exp_csdiffat15. Values are NaN where a position/stat had too little data.
    """
    df = _decompose_kda(df)

    cfg = ExpectedPerformanceConfig(roles=tuple(roles))
    feat_df, _ = build_game_state_features(df, cfg)

    out = feat_df[["gameid", "side", "position"]].copy()

    for stat in LANE_STATS:
        if stat not in feat_df.columns:
            logging.warning(f"[expected_stats] stat {stat!r} missing; skipping")
            out[f"exp_{stat}"] = np.nan
            continue

        expected = pd.Series(np.nan, index=feat_df.index, dtype=float)

        for position in roles:
            pos_df = feat_df[feat_df["position"] == position]
            feats = [f for f in FEATURE_MAP[stat] if f in pos_df.columns]
            if not feats:
                continue

            cat = [c for c in _CATEGORICAL if c in feats]
            X = pd.get_dummies(pos_df[feats], columns=cat, drop_first=False)
            y = pos_df[stat]

            valid = X.notna().all(axis=1) & y.notna()
            if valid.sum() < 50:
                continue

            # Mean-prediction model (squared-error loss). In-sample prediction: the exact
            # one-hot columns are reused, so no column alignment is needed.
            model = HistGradientBoostingRegressor(
                loss="squared_error",
                max_iter=max_iter,
                learning_rate=0.06,
                max_depth=8,
                min_samples_leaf=20,
                early_stopping=True,
                validation_fraction=0.1,
                random_state=42,
            )
            model.fit(X[valid], y[valid])
            expected.loc[pos_df.index[valid]] = model.predict(X[valid])

        out[f"exp_{stat}"] = expected
        logging.info(f"[expected_stats] {stat}: {out[f'exp_{stat}'].notna().sum():,} predictions")

    return out


def expected_reference_frame(
    df: pd.DataFrame,
    team_df: pd.DataFrame,
    roles: Sequence[str] = ROLES,
    max_iter: int = 150,
) -> pd.DataFrame:
    """
    Model 1 expected values reshaped to team-game rows, aligned to `team_df`.

    Produces one row per (gameid, side) with columns named like Model 2's features
    ({role}_{stat}), row-aligned to team_df, ready to pass as `expected_df` to
    contribution.contributions_for_frame.
    """
    exp_long = compute_expected_stats(df, roles=roles, max_iter=max_iter)

    piv = exp_long.pivot_table(
        index=["gameid", "side"],
        columns="position",
        values=[f"exp_{s}" for s in LANE_STATS],
    )
    # Flatten ("exp_kills_nonfb", "top") -> "top_kills_nonfb".
    piv.columns = [f"{pos}_{val.replace('exp_', '')}" for val, pos in piv.columns]
    piv = piv.reset_index()

    # Row-align to team_df (left merge keeps team_df order; missing -> NaN -> mean fallback).
    aligned = team_df[["gameid", "side"]].merge(piv, on=["gameid", "side"], how="left")
    return aligned.drop(columns=["gameid", "side"])
