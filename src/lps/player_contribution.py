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
from sklearn.inspection import permutation_importance
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
        "damagetochampions",
        "csdiffat15",  # CS difference at 15 min
        "xpdiffat15",  # XP difference at 15 min
    )

    # Baseline player percentile (25th percentile = bottom 25%)
    # Note: Adjusted from 20% due to discrete nature of data (many ties at low values)
    baseline_percentile: float = 0.25

    # Model parameters (HistGradientBoostingRegressor)
    max_iter: int = 500  # More iterations for better convergence
    max_depth: int = 8   # Deeper trees for capturing distribution tails
    learning_rate: float = 0.03  # Lower learning rate for finer quantile control
    min_samples_leaf: int = 10   # Reduced to allow more flexibility at lower quantiles
    early_stopping: bool = True  # Stop when validation score stops improving (uses quantile loss)
    validation_fraction: float = 0.2  # Use 20% for validation


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
    - Opponent champion (categorical, matched by position)
    - Position (categorical)
    - Gold share (player's % of team gold)
    - Game length
    - Overall game kills (both teams)
    - Overall game tower damage (both teams)
    - Overall game damage to champions (both teams)
    - Position-specific features:
      - Supports: ADC's cs/xp diff at 15 (supports partially responsible for lane outcome)

    Note: Blind pick detection is disabled - matchup information is captured directly
    through oppchampion feature instead.

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

    # Total damage to champions in game
    if "damagetochampions" in df.columns:
        df["_game_total_damagetochampions"] = df.groupby(game_col)["damagetochampions"].transform("sum")

    # Player's gold share (% of team's gold)
    if "earnedgold" in df.columns:
        team_gold = df.groupby([game_col, "side"])["earnedgold"].transform("sum")
        df["_gold_share"] = np.where(team_gold > 0, df["earnedgold"] / team_gold, 0)
    else:
        logging.warning("No gold share data found, using uniform 0.2")
        df["_gold_share"] = 0.2

    # Add opponent champion (same game, same position, opposite side)
    logging.info("Matching lane opponents...")
    df["_side_opp"] = df["side"].map({"Blue": "Red", "Red": "Blue"})
    opponent_df = df[[game_col, pos_col, "_side_opp", champion_col]].rename(
        columns={champion_col: "oppchampion", "_side_opp": "side"}
    )
    df = df.merge(
        opponent_df,
        on=[game_col, pos_col, "side"],
        how="left"
    )
    df = df.drop(columns=["_side_opp"])

    # Check match rate
    opp_match_rate = df["oppchampion"].notna().mean()
    logging.info(f"Matched {opp_match_rate*100:.1f}% of players with lane opponents")

    # Add ADC's cs/xp diff for supports (supports partially responsible for ADC performance)
    logging.info("Matching supports with their ADCs...")
    if "csdiffat15" in df.columns and "xpdiffat15" in df.columns:
        # Create ADC dataframe (bot laners with their stats)
        adc_df = df[df[pos_col] == "bot"][[game_col, "side", "csdiffat15", "xpdiffat15"]].rename(
            columns={"csdiffat15": "adc_csdiffat15", "xpdiffat15": "adc_xpdiffat15"}
        )

        # Merge ADC stats onto support rows
        df = df.merge(adc_df, on=[game_col, "side"], how="left")

        # Check match rate for supports
        support_mask = df[pos_col] == "sup"
        if support_mask.sum() > 0:
            adc_match_rate = df.loc[support_mask, "adc_csdiffat15"].notna().mean()
            logging.info(f"Matched {adc_match_rate*100:.1f}% of supports with their ADCs")
    else:
        logging.warning("csdiffat15 or xpdiffat15 not found, cannot add ADC stats for supports")
        df["adc_csdiffat15"] = np.nan
        df["adc_xpdiffat15"] = np.nan

    # Blind pick detection - DISABLED (using oppchampion directly instead)
    # Determine blind pick status from draft order using team rows
    # logging.info("Determining blind pick status from draft order...")

    # Initialize blind pick column (keep for compatibility, but not used as feature)
    df["_blind_pick"] = 0  # Default to not blind pick

    # Initialize _pick_order column (not used as feature anymore)
    df["_pick_order"] = -1

    # # Standard draft order (Blue=1, Red=2):
    # # Blue pick1 (overall 1), Red pick1 (2), Red pick2 (3), Blue pick2 (4),
    # # Blue pick3 (5), Red pick3 (6), Red pick4 (7), Blue pick4 (8),
    # # Blue pick5 (9), Red pick5 (10)
    # # Map (side, team_pick_num) -> overall_pick_order
    # draft_order_map = {
    #     ("Blue", 1): 1, ("Red", 1): 2, ("Red", 2): 3, ("Blue", 2): 4,
    #     ("Blue", 3): 5, ("Red", 3): 6, ("Red", 4): 7, ("Blue", 4): 8,
    #     ("Blue", 5): 9, ("Red", 5): 10,
    # }

    # # Check if we have pick columns and team rows
    # pick_cols = [f"pick{i}" for i in range(1, 6)]
    # has_pick_cols = all(col in df_with_teams.columns for col in pick_cols)

    if False:  # Disabled blind pick detection
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

            t_start2 = time.perf_counter() 
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
            logging.info(f"  Total time: {time.perf_counter()  - t_start2:.2f}s")
        else:
            logging.info("  No team rows found in data")
            df["_pick_order"] = -1  # Initialize if no team rows
    else:
        logging.info("  Pick order columns not found, blind pick status unavailable")
        df["_pick_order"] = -1  # Initialize if no pick columns

    # Identify feature columns
    feature_cols = [
        champion_col,
        "oppchampion",
        pos_col,
        "_gamelength_min",
        "_gold_share",
        # "_blind_pick",  # Disabled - using oppchampion directly instead
        "_game_total_kills",
        "_game_total_tower_dmg",
        "_game_total_damagetochampions",
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

    # Map from metric to the list of valid features for that metric
    feature_map = {
        "kills": ["_gold_share", "_game_total_kills", "_gamelength_min", "champion"],
        "deaths": ["_game_total_kills", "_gamelength_min", "champion"],
        "assists": ["_gold_share", "_game_total_kills", "_gamelength_min", "champion"],
        "damagetotowers": ["_gold_share", "_gamelength_min", "champion", "_game_total_tower_dmg"],
        "csdiffat15": ["champion", "oppchampion"],
        "xpdiffat15": ["champion", "oppchampion"],
        "damagetochampions": ["_gold_share", "champion", "_gamelength_min", "_game_total_damagetochampions"],
        # "adc_csdiffat15": ["champion", "oppchampion"],  # Support-specific: ADC's CS diff
        # "adc_xpdiffat15": ["champion", "oppchampion"],  # Support-specific: ADC's XP diff
    }

    # Metrics where LOWER is better (predict high quantile for baseline/bad players)
    reverse_metrics = {"deaths"}  # Bad players have MORE deaths

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

        # Get position-specific metrics (supports also predict ADC cs/xp diff)
        position_metrics = list(cfg.output_metrics)
        # if position == "sup":
        #     position_metrics.extend(["adc_csdiffat15", "adc_xpdiffat15"])

        for metric in position_metrics:
            # TODO: customize input features based on metrics
            # e.g. don't use tower damage as input for kills, don't use _gold_share for cs diff/xp diff
            # make support use ADC's cs/xp diff in addition / in replacement to their own, since they are partially responsible for it
            if metric not in pos_df.columns:
                logging.warning(f"Metric '{metric}' not found for {position}, skipping")
                continue

            logging.info(f"\n  Training {position} → {metric}")

            # Prepare data (exclude position from features since we're training per-position)
            feature_cols_no_pos = [col for col in feature_cols if col != pos_col]

            # Get feature subset based on metric (some metrics don't use all features)
            metric_features = feature_map.get(metric, feature_cols_no_pos)
            actual_features = [col for col in metric_features if col in pos_df.columns]

            # One-hot encode categorical features (champion and oppchampion)
            categorical_cols = [col for col in ["champion", "oppchampion"] if col in actual_features]
            X = pd.get_dummies(pos_df[actual_features], columns=categorical_cols, drop_first=False)
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

            # Determine target quantile (invert for metrics where lower is better)
            if metric in reverse_metrics:
                target_quantile = 1.0 - cfg.baseline_percentile  # e.g., 0.75 for deaths
                quantile_label = f"{target_quantile*100:.0f}th %ile (bad players have MORE {metric})"
            else:
                target_quantile = cfg.baseline_percentile  # e.g., 0.25
                quantile_label = f"{target_quantile*100:.0f}th %ile (bad players have LESS {metric})"

            # Diagnostic: Show actual data distribution
            y_quantiles = y.quantile([0.1, 0.2, 0.3, 0.5, 0.7, 0.9])
            logging.info(f"    Target distribution: 10%={y_quantiles[0.1]:.2f} 20%={y_quantiles[0.2]:.2f} 50%={y_quantiles[0.5]:.2f} 90%={y_quantiles[0.9]:.2f}")

            # Naive baseline: just predict the target quantile for everyone
            naive_baseline = y.quantile(target_quantile)
            logging.info(f"    Naive baseline (constant {quantile_label}): {naive_baseline:.2f}")

            # Train histogram-based gradient boosting with quantile loss
            # This predicts the target percentile (baseline player) performance
            model = HistGradientBoostingRegressor(
                loss='quantile',
                quantile=target_quantile,
                max_iter=cfg.max_iter,
                max_depth=cfg.max_depth,
                learning_rate=cfg.learning_rate,
                min_samples_leaf=cfg.min_samples_leaf,
                early_stopping=cfg.early_stopping,
                validation_fraction=cfg.validation_fraction,
                random_state=42,
                verbose=0,  # Suppress iteration output
            )

            model.fit(X, y)

            # Log actual iterations used (may be less than max_iter due to early stopping)
            if hasattr(model, 'n_iter_'):
                logging.info(f"    Converged after {model.n_iter_} iterations (max: {cfg.max_iter})")

            # Evaluate model performance
            # Note: R² is misleading for quantile regression (optimized for quantile loss, not MSE)
            train_score = model.score(X, y)
            y_pred = model.predict(X)

            # Check what percentile our predictions fall at (should be ~20th)
            actual_percentile = (y_pred[:, None] >= y.values[None, :]).mean(axis=1).mean() * 100

            # Compare to naive baseline
            naive_percentile = (naive_baseline >= y.values).mean() * 100

            # Mean Absolute Error (more interpretable than R² for quantile regression)
            mae = np.abs(y - y_pred).mean()
            mae_naive = np.abs(y - naive_baseline).mean()

            logging.info(f"    R² (MSE-based): {train_score:.3f} [NOTE: Negative is OK for quantile regression]")
            logging.info(f"    Model predictions at: {actual_percentile:.1f}th %ile (target: {target_quantile*100:.0f}th) | MAE: {mae:.2f}")
            logging.info(f"    Naive baseline at:    {naive_percentile:.1f}th %ile (target: {target_quantile*100:.0f}th) | MAE: {mae_naive:.2f}")

            # Show if model is better or worse than naive
            if abs(actual_percentile - target_quantile*100) < abs(naive_percentile - target_quantile*100):
                logging.info(f"    ✓ Model is closer to target than naive baseline")
            else:
                logging.warning(f"    ✗ Naive baseline is closer to target than model!")

            # Synthetic sample test: create random match conditions and show prediction
            logging.info(f"    Synthetic sample test:")
            synthetic_sample = {}
            for col in X.columns:
                # For one-hot encoded champion/oppchampion features, we'll set them all to 0
                # then randomly pick one to set to 1
                if col.startswith('champion_') or col.startswith('oppchampion_'):
                    synthetic_sample[col] = 0
                else:
                    # For numeric features, randomly sample from actual values
                    synthetic_sample[col] = X[col].sample(1, random_state=None).iloc[0]

            # Randomly select one champion and one oppchampion (if present)
            champion_cols = [c for c in X.columns if c.startswith('champion_')]
            if champion_cols:
                selected_champ = np.random.choice(champion_cols)
                synthetic_sample[selected_champ] = 1
                champ_name = selected_champ.replace('champion_', '')
            else:
                champ_name = "N/A"

            oppchampion_cols = [c for c in X.columns if c.startswith('oppchampion_')]
            if oppchampion_cols:
                selected_opp = np.random.choice(oppchampion_cols)
                synthetic_sample[selected_opp] = 1
                opp_name = selected_opp.replace('oppchampion_', '')
            else:
                opp_name = "N/A"

            # Create dataframe with correct column order
            synthetic_df = pd.DataFrame([synthetic_sample])[X.columns]
            synthetic_pred = model.predict(synthetic_df)[0]

            # Show the synthetic sample conditions and prediction
            conditions = []
            if champ_name != "N/A":
                conditions.append(f"{champ_name}")
            if opp_name != "N/A":
                conditions.append(f"vs {opp_name}")
            for col in ['_gold_share', '_gamelength_min', '_game_total_kills', '_game_total_tower_dmg', '_game_total_damagetochampions']:
                if col in synthetic_sample:
                    conditions.append(f"{col.replace('_', '')}={synthetic_sample[col]:.2f}")

            logging.info(f"      Conditions: {' | '.join(conditions)}")
            logging.info(f"      Predicted {metric} for baseline player: {synthetic_pred:.2f}")

            # Store model with (position, metric) key
            models[(position, metric)] = model

            # Calculate permutation importance (HistGradientBoostingRegressor doesn't have feature_importances_)
            # Use subset of data for speed (permutation importance is expensive)
            n_samples_perm = min(5000, len(X))
            if n_samples_perm < len(X):
                # Random sample for permutation importance
                perm_idx = np.random.choice(len(X), size=n_samples_perm, replace=False)
                X_perm = X.iloc[perm_idx]
                y_perm = y.iloc[perm_idx]
            else:
                X_perm = X
                y_perm = y

            logging.info(f"    Computing permutation importance on {n_samples_perm:,} samples...")
            perm_result = permutation_importance(
                model, X_perm, y_perm,
                n_repeats=5,
                random_state=42,
                n_jobs=-1  # Use all CPUs
            )

            # Build feature importance dataframe
            feature_importance = pd.DataFrame({
                'feature': X.columns,
                'importance': perm_result.importances_mean
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
