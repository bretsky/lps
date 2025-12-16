"""
Player Contribution Model

Goal: Calculate how much each player increased/decreased their team's win probability.

Method:
1. Model 1 (Expected Performance): Predict what an average/marginal (bottom 20%) player
   would do given the game state
2. Model 2 (Win Probability): Predict win probability from team stats
3. Calculate contribution: How does (actual - expected) performance change win probability
4. Allocate win shares proportionally based on contributions

This file implements Model 1: Expected Performance Model
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from tqdm import tqdm

from .io_oracle import load_oracle_years

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)


@dataclass
class ExpectedPerformanceConfig:
    """Config for expected performance model (Model 1)."""

    years: Iterable[int] = (2024,)
    roles: Sequence[str] = ("top", "jng", "mid", "bot", "sup")

    # Performance metrics to predict
    output_metrics: Sequence[str] = (
        "kills",
        "deaths",
        "assists",
        "damagetotowers",
        "csdiffat15",  # CS difference at 15 min
        "xpdiffat15",  # XP difference at 15 min
    )

    # Baseline player percentile (20th percentile = bottom 20%)
    baseline_percentile: float = 0.20

    # Model parameters (HistGradientBoostingRegressor)
    max_iter: int = 100  # Equivalent to n_estimators
    max_depth: int = 5
    learning_rate: float = 0.1


def _detect_schema(df: pd.DataFrame) -> Dict[str, str]:
    """Map to canonical column names."""
    cols = set(df.columns)

    required = {
        "gameid",
        "side",
        "position",
        "playername",
        "teamname",
        "result",
        "champion",
    }
    missing = required - cols
    if missing:
        raise KeyError(f"Missing required columns: {missing}")

    return {
        "player": "playername",
        "game": "gameid",
        "team": "teamname",
        "side": "side",
        "pos": "position",
        "result": "result",
        "champion": "champion",
    }


def _filter_player_rows(df: pd.DataFrame, pos_col: str) -> pd.DataFrame:
    """Keep only individual player rows, not team aggregates."""
    out = df.copy()
    out[pos_col] = out[pos_col].astype(str)
    mask_player = ~out[pos_col].str.lower().eq("team")
    filtered = out[mask_player]
    logging.info(f"Filtered to {len(filtered):,} player rows (from {len(df):,} total)")
    return filtered


def build_game_state_features(
    df: pd.DataFrame,
    cfg: Optional[ExpectedPerformanceConfig] = None,
) -> Tuple[pd.DataFrame, List[str]]:
    """
    Build game state features for predicting expected player performance.

    Features include:
    - Champion (categorical)
    - Position (categorical)
    - Gold share (player's % of team gold)
    - Game length
    - Blind pick status (TODO: need draft order data)
    - Overall game kills (both teams)
    - Overall game tower damage (both teams)
    - Position-specific features

    Returns:
        Tuple of (feature dataframe, feature column names)
    """
    if cfg is None:
        cfg = ExpectedPerformanceConfig()

    logging.info("Building game state features...")
    logging.info(f"Input data: {len(df):,} rows, {len(df.columns)} columns")

    # Filter for complete games only
    if "datacompleteness" in df.columns:
        before = len(df)
        df = df[df["datacompleteness"] == "complete"]
        logging.info(f"Filtered to complete games: {len(df):,} rows (removed {before - len(df):,})")
    else:
        logging.warning("No 'datacompleteness' column found, cannot filter incomplete games")

    schema = _detect_schema(df)
    game_col = schema["game"]
    pos_col = schema["pos"]
    result_col = schema["result"]
    champion_col = schema["champion"]

    # Keep a copy with team rows for draft information
    df_with_teams = df.copy()

    # Filter to player rows only for feature building
    df = _filter_player_rows(df, pos_col)

    # Standardize position
    df[pos_col] = df[pos_col].astype(str).str.lower()
    df = df[df[pos_col].isin(cfg.roles)]

    # Find game length column
    if "gamelength" in df.columns:
        df["_gamelength_min"] = df["gamelength"] / 60.0
    else:
        raise ValueError("Game length column not found")

    # Compute game totals (both teams)
    logging.info("Computing game-level aggregates...")

    # Total kills in game
    if "kills" in df.columns:
        df["_game_total_kills"] = df.groupby(game_col)["kills"].transform("sum")

    # Total tower damage in game
    if "damagetotowers" in df.columns:
        df["_game_total_tower_dmg"] = df.groupby(game_col)["damagetotowers"].transform("sum")

    # Player's gold share (% of team's gold)
    if "earnedgold" in df.columns:
        team_gold = df.groupby([game_col, "side"])["earnedgold"].transform("sum")
        df["_gold_share"] = np.where(team_gold > 0, df["earnedgold"] / team_gold, 0)
    elif "earnedgoldshare" in df.columns:
        df["_gold_share"] = df["earnedgoldshare"]
    else:
        logging.warning("No gold share data found, using uniform 0.2")
        df["_gold_share"] = 0.2

    # Determine blind pick status from draft order using team rows
    logging.info("Determining blind pick status from draft order...")

    # Initialize blind pick column now (pick_order will be added during merge)
    df["_blind_pick"] = 0  # Default to not blind pick

    # Standard draft order (Blue=1, Red=2):
    # Blue pick1 (overall 1), Red pick1 (2), Red pick2 (3), Blue pick2 (4),
    # Blue pick3 (5), Red pick3 (6), Red pick4 (7), Blue pick4 (8),
    # Blue pick5 (9), Red pick5 (10)
    # Map (side, team_pick_num) -> overall_pick_order
    draft_order_map = {
        ("Blue", 1): 1, ("Red", 1): 2, ("Red", 2): 3, ("Blue", 2): 4,
        ("Blue", 3): 5, ("Red", 3): 6, ("Red", 4): 7, ("Blue", 4): 8,
        ("Blue", 5): 9, ("Red", 5): 10,
    }

    # Check if we have pick columns and team rows
    pick_cols = [f"pick{i}" for i in range(1, 6)]
    has_pick_cols = all(col in df_with_teams.columns for col in pick_cols)

    if has_pick_cols:
        # Get team rows (position == "team")
        team_rows = df_with_teams[df_with_teams["position"] == "team"]
        logging.info(f"  Found {len(team_rows):,} team rows")

        if len(team_rows) > 0:
            logging.info(f"  Found {len(team_rows):,} team rows with draft information")

            # First pass: build pick order mappings (much faster than repeated masking)
            logging.info("  Building pick order mappings...")
            t_start = time.perf_counter()

            mappings = []
            for _, team_row in tqdm(team_rows.iterrows(), total=len(team_rows), desc="Processing draft orders"):
                game_id = team_row[game_col]
                side = team_row["side"]

                # Extract pick order for each champion
                for pick_num in range(1, 6):
                    pick_col = f"pick{pick_num}"
                    if pd.notna(team_row[pick_col]):
                        champion = team_row[pick_col]
                        overall_order = draft_order_map.get((side, pick_num), -1)

                        mappings.append({
                            game_col: game_id,
                            "side": side,
                            champion_col: champion,
                            "_pick_order": overall_order
                        })

            t_build = time.perf_counter()
            logging.info(f"  Built {len(mappings):,} mappings in {t_build - t_start:.2f}s")

            if len(mappings) > 0:
                # Create mapping dataframe and merge (vectorized operation, much faster)
                logging.info("  Merging pick orders...")
                mapping_df = pd.DataFrame(mappings)

                # Debug: Show sample data to understand mismatch
                logging.info(f"  Sample mapping champions: {mapping_df[champion_col].unique()[:5].tolist()}")
                logging.info(f"  Sample player champions: {df[champion_col].unique()[:5].tolist()}")
                logging.info(f"  Unique champions in mappings: {len(mapping_df[champion_col].unique())}")
                logging.info(f"  Unique champions in players: {len(df[champion_col].unique())}")
                logging.info(f"  Sample mapping pick orders: {mapping_df['_pick_order'].unique()[:10].tolist()}")

                # Merge to add pick order column
                df_before_merge = len(df)
                df = df.merge(
                    mapping_df,
                    on=[game_col, "side", champion_col],
                    how="left",
                    suffixes=('', '_new'),
                    indicator=True
                )
                matches = (df['_merge'] == 'both').sum()
                logging.info(f"  Merge matched {matches:,} / {df_before_merge:,} rows")
                df = df.drop(columns=['_merge'])

                # Check if _pick_order column exists after merge
                if "_pick_order" in df.columns:
                    # Debug: Check what values we got from the merge
                    non_nan_count = df["_pick_order"].notna().sum()
                    unique_values = df["_pick_order"].dropna().unique()
                    logging.info(f"  After merge: {non_nan_count:,} non-NaN values, unique values: {sorted(unique_values)[:10]}")

                    # Fill NaN with -1 for games without draft data
                    df["_pick_order"] = df["_pick_order"].fillna(-1).astype(int)
                else:
                    logging.warning("  Merge didn't create _pick_order column, setting all to -1")
                    df["_pick_order"] = -1
            else:
                logging.warning("  No mappings created, setting all pick orders to -1")
                df["_pick_order"] = -1

            t_merge = time.perf_counter()
            logging.info(f"  Merged pick orders in {t_merge - t_build:.2f}s")

            # Verify column exists before accessing
            if "_pick_order" in df.columns:
                logging.info(f"  Rows without pick order: {(df['_pick_order'] == -1).sum():,}")
            else:
                logging.error(f"  ERROR: _pick_order column not in dataframe after merge!")
                logging.error(f"  Available columns: {df.columns.tolist()}")

            logging.info(f"  Total time: {t_merge - t_start:.2f}s")

            # Second pass: determine blind picks by comparing lane opponents
            for game_id in df[game_col].unique():
                game_data = df[df[game_col] == game_id]

                # For each position, check who picked first
                for position in game_data[pos_col].unique():
                    pos_data = game_data[game_data[pos_col] == position]

                    # Get blue and red side picks for this position
                    blue_data = pos_data[pos_data["side"] == "Blue"]
                    red_data = pos_data[pos_data["side"] == "Red"]

                    if len(blue_data) > 0 and len(red_data) > 0:
                        blue_pick_order = blue_data["_pick_order"].iloc[0]
                        red_pick_order = red_data["_pick_order"].iloc[0]

                        # Whoever picked first (lower number) is blind pick
                        if blue_pick_order != -1 and red_pick_order != -1:
                            if blue_pick_order < red_pick_order:
                                df.loc[blue_data.index, "_blind_pick"] = 1
                            elif red_pick_order < blue_pick_order:
                                df.loc[red_data.index, "_blind_pick"] = 1

            blind_pick_count = df["_blind_pick"].sum()
            logging.info(f"  Identified {blind_pick_count:,} blind pick instances")
        else:
            logging.info("  No team rows found in data")
            df["_pick_order"] = -1  # Initialize if no team rows
    else:
        logging.info("  Pick order columns not found, blind pick status unavailable")
        df["_pick_order"] = -1  # Initialize if no pick columns

    # Identify feature columns
    feature_cols = [
        champion_col,
        pos_col,
        "_gamelength_min",
        "_gold_share",
        "_blind_pick",
        "_game_total_kills",
        "_game_total_tower_dmg",
    ]

    # Add position-specific features
    # TODO: Add support-specific features (ADC's cs diff contribution)

    logging.info(f"Created {len(feature_cols)} game state features")

    # Final check: ensure critical columns exist
    required_cols = ["_blind_pick", "_pick_order"]
    for col in required_cols:
        if col not in df.columns:
            logging.error(f"ERROR: Required column '{col}' missing from dataframe!")
            logging.error(f"Available columns: {df.columns.tolist()[:20]}...")  # Show first 20
            df[col] = -1 if col == "_pick_order" else 0  # Add with default value

    return df, feature_cols


def train_expected_performance_model(
    cfg: Optional[ExpectedPerformanceConfig] = None,
) -> Dict[Tuple[str, str], HistGradientBoostingRegressor]:
    """
    Train Model 1: Expected Performance Model

    For each position and performance metric:
    - Train a separate model to predict expected value given game state
    - Separate models per position avoid champion×position interaction issues
      (e.g., Poppy-top vs Poppy-support have very different expected stats)

    Returns:
        Dictionary mapping (position, metric) to trained model
    """
    if cfg is None:
        cfg = ExpectedPerformanceConfig()

    logging.info("=" * 60)
    logging.info("Model 1: Expected Performance (Baseline Player)")
    logging.info("=" * 60)
    logging.info(f"Baseline: {cfg.baseline_percentile*100:.0f}th percentile player")
    logging.info(f"Training separate models for {len(cfg.roles)} positions")

    # Load data
    logging.info(f"\nLoading data for years: {list(cfg.years)}")
    df = load_oracle_years(cfg.years)
    logging.info(f"Loaded {len(df):,} rows")

    # Build features
    df, feature_cols = build_game_state_features(df, cfg)

    # Get position column name
    pos_col = "position"

    # Train separate models for each position and metric
    models = {}

    for position in cfg.roles:
        print()
        logging.info("=" * 60)
        logging.info(f"Position: {position.upper()}")
        logging.info("=" * 60)

        # Filter to this position
        pos_df = df[df[pos_col] == position].copy()
        logging.info(f"Training samples for {position}: {len(pos_df):,}")

        if len(pos_df) < 100:
            logging.warning(f"Insufficient data for {position}, skipping")
            continue

        for metric in cfg.output_metrics:
            if metric not in pos_df.columns:
                logging.warning(f"Metric '{metric}' not found for {position}, skipping")
                continue

            logging.info(f"\n  Training {position} → {metric}")

            # Prepare data (exclude position from features since we're training per-position)
            feature_cols_no_pos = [col for col in feature_cols if col != pos_col]

            # One-hot encode champion
            X = pd.get_dummies(pos_df[feature_cols_no_pos], columns=["champion"], drop_first=False)
            y = pos_df[metric]

            # Remove rows with missing values
            mask_valid = X.notna().all(axis=1) & y.notna()
            X = X[mask_valid]
            y = y[mask_valid]

            if len(X) < 50:
                logging.warning(f"    Insufficient valid samples ({len(X)}), skipping")
                continue

            logging.info(f"    Valid samples: {len(X):,}")
            logging.info(f"    Features: {len(X.columns)}")

            # Train histogram-based gradient boosting with quantile loss
            # This predicts the 20th percentile (baseline player) performance
            model = HistGradientBoostingRegressor(
                loss='quantile',
                quantile=cfg.baseline_percentile,
                max_iter=cfg.max_iter,
                max_depth=cfg.max_depth,
                learning_rate=cfg.learning_rate,
                random_state=42,
            )

            model.fit(X, y)

            # Calculate training R²
            train_score = model.score(X, y)
            logging.info(f"    Training R²: {train_score:.3f}")

            # Store model with (position, metric) key
            models[(position, metric)] = model

            # Show top features with correlation direction
            feature_importance = pd.DataFrame({
                'feature': X.columns,
                'importance': model.feature_importances_
            })

            # Calculate correlation with target for direction
            correlations = X.corrwith(y)
            feature_importance['correlation'] = feature_importance['feature'].map(correlations)
            feature_importance['direction'] = feature_importance['correlation'].apply(
                lambda x: '+' if x > 0 else '-' if x < 0 else '0'
            )
            feature_importance = feature_importance.sort_values('importance', ascending=False)

            logging.info(f"    Top 10 features (direction: + positive, - negative):")
            for _, row in feature_importance.head(10).iterrows():
                logging.info(f"      {row['direction']} {row['feature']:<28} importance={row['importance']:.3f} corr={row['correlation']:.3f}")

    logging.info("\n" + "=" * 60)
    logging.info(f"✓ Trained {len(models)} models ({len(cfg.roles)} positions × {len(cfg.output_metrics)} metrics)")
    return models


if __name__ == "__main__":
    cfg = ExpectedPerformanceConfig()
    models = train_expected_performance_model(cfg)

    logging.info("\n" + "=" * 60)
    logging.info("Model 1 Complete - Expected Performance Models Ready")
    logging.info("=" * 60)
    logging.info("Next steps:")
    logging.info("1. Build Model 2: Win Probability from team stats")
    logging.info("2. Calculate player contributions: (actual - expected) × ∂WinProb")
    logging.info("3. Allocate win shares proportionally")
