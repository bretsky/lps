"""
Win Probability Model (Model 2)

Predicts win probability from per-lane player performance.

This is the second part of the player contribution system:
1. Model 1 (player_contribution.py): Predicts expected baseline performance
   - Outputs probabilities for binary metrics (firstblood, etc.)
   - Outputs quantile predictions for continuous metrics
2. Model 2 (this file): Predicts win probability from actual performance
   - Uses LogisticRegression to handle continuous probability inputs
3. Combine: Calculate contribution = (actual - expected) × ∂WinProb/∂stat
"""

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler

from .io_oracle import load_oracle_years

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)


@dataclass
class WinProbabilityConfig:
    """Config for win probability model (Model 2)."""

    years: Iterable[int] = (2024,)
    roles: Sequence[str] = ("top", "jng", "mid", "bot", "sup")

    # Performance metrics to use as features
    performance_metrics: Sequence[str] = (
        "kills",
        "deaths",
        "assists",
        "damagetotowers",
        "damagetochampions",
        "csdiffat15",
        "xpdiffat15",
        "firstbloodkill",
        "firstbloodassist",
        "firstbloodvictim",
    )

    # Model parameters (LogisticRegression)
    C: float = 1.0  # Inverse of regularization strength
    max_iter: int = 1000  # Maximum iterations for solver
    solver: str = "lbfgs"  # Optimization algorithm
    penalty: str = "l2"  # Regularization type
    test_size: float = 0.2
    random_state: int = 42


def _detect_schema(df: pd.DataFrame) -> Dict[str, str]:
    """Map to canonical column names."""
    cols = set(df.columns)

    required = {
        'game': ['gameid'],
        'pos': ['position'],
        'result': ['result'],
    }

    schema = {}
    for key, candidates in required.items():
        found = [c for c in candidates if c in cols]
        if not found:
            raise ValueError(f"Missing required column for '{key}': tried {candidates}")
        schema[key] = found[0]

    return schema


def _filter_player_rows(df: pd.DataFrame, pos_col: str) -> pd.DataFrame:
    """Filter to only player rows (exclude team rows)."""
    valid_positions = {"top", "jng", "jungle", "mid", "bot", "adc", "sup", "support"}
    return df[df[pos_col].astype(str).str.lower().isin(valid_positions)].copy()


def build_team_features(df: pd.DataFrame, cfg: Optional[WinProbabilityConfig] = None) -> pd.DataFrame:
    """
    Build team-level features from individual player performance.

    For each game, create features for each position:
    - top_kills, top_deaths, top_assists, ...
    - jng_kills, jng_deaths, jng_assists, ...
    - etc.

    Returns:
        DataFrame with one row per team (game + side), with columns for each position's stats
    """
    if cfg is None:
        cfg = WinProbabilityConfig()

    logging.info("Building team-level features from player data...")

    schema = _detect_schema(df)
    game_col = schema["game"]
    pos_col = schema["pos"]
    result_col = schema["result"]

    # Filter to complete games and player rows only
    if "datacompleteness" in df.columns:
        before = len(df)
        df = df[df["datacompleteness"] == "complete"]
        logging.info(f"Filtered to complete games: {len(df):,} rows (removed {before - len(df):,})")

    df = _filter_player_rows(df, pos_col)
    logging.info(f"Player rows: {len(df):,}")

    # Standardize position names
    df[pos_col] = df[pos_col].astype(str).str.lower()
    df[pos_col] = df[pos_col].replace({"jungle": "jng", "adc": "bot", "support": "sup"})

    # Filter to valid positions
    df = df[df[pos_col].isin(cfg.roles)]
    logging.info(f"After filtering to valid positions: {len(df):,}")

    # Ensure side column exists
    if "side" not in df.columns:
        raise ValueError("Missing 'side' column (Blue/Red team)")

    # Pivot: one row per game+side, columns for each position's stats
    logging.info("Pivoting player stats to team features...")

    # Build list of features to pivot
    pivot_features = []
    for metric in cfg.performance_metrics:
        if metric in df.columns:
            pivot_features.append(metric)
        else:
            logging.warning(f"Metric '{metric}' not found in data, skipping")

    if not pivot_features:
        raise ValueError("No performance metrics found in data")

    logging.info(f"Using {len(pivot_features)} metrics: {pivot_features}")

    # For each position, create columns for each metric
    team_data = []

    for (game_id, side), group in df.groupby([game_col, "side"]):
        row = {
            game_col: game_id,
            "side": side,
        }

        # Get result (1 = win, 0 = loss)
        result = group[result_col].iloc[0]
        row["result"] = 1 if result == 1 else 0

        # For each position, add its stats
        for position in cfg.roles:
            pos_players = group[group[pos_col] == position]

            if len(pos_players) == 0:
                # Missing player for this position (shouldn't happen often)
                for metric in pivot_features:
                    row[f"{position}_{metric}"] = np.nan
            elif len(pos_players) == 1:
                # Normal case: one player per position
                player = pos_players.iloc[0]
                for metric in pivot_features:
                    row[f"{position}_{metric}"] = player[metric]
            else:
                # Multiple players in same position (data issue)
                logging.warning(f"Multiple {position} players in game {game_id} side {side}, using first")
                player = pos_players.iloc[0]
                for metric in pivot_features:
                    row[f"{position}_{metric}"] = player[metric]

        team_data.append(row)

    team_df = pd.DataFrame(team_data)
    logging.info(f"Created team features: {len(team_df):,} teams, {len(team_df.columns)} columns")

    # Drop rows with missing data
    before = len(team_df)
    team_df = team_df.dropna()
    if len(team_df) < before:
        logging.warning(f"Dropped {before - len(team_df):,} teams with missing data")

    return team_df


def train_win_probability_model(cfg: Optional[WinProbabilityConfig] = None) -> LogisticRegression:
    """
    Train Model 2: Win Probability from per-lane performance.

    Uses LogisticRegression to handle continuous probability inputs
    (e.g., firstblood probabilities from Model 1).

    Returns:
        Trained logistic regression model
    """
    if cfg is None:
        cfg = WinProbabilityConfig()

    logging.info("=" * 60)
    logging.info("Model 2: Win Probability from Performance")
    logging.info("=" * 60)

    # Load data
    logging.info(f"\nLoading data for years: {list(cfg.years)}")
    df = load_oracle_years(cfg.years)
    logging.info(f"Loaded {len(df):,} rows")

    # Build team features
    team_df = build_team_features(df, cfg)

    # Prepare features and target
    schema = _detect_schema(df)
    feature_cols = [col for col in team_df.columns if col not in [schema["game"], "side", "result"]]
    X = team_df[feature_cols]
    y = team_df["result"]

    logging.info(f"\nFeatures: {len(feature_cols)} columns")
    logging.info(f"Samples: {len(X):,} teams ({y.sum():,} wins, {(~y.astype(bool)).sum():,} losses)")

    # Train/test split
    X_train, X_test, y_train, y_test = train_test_split(
        X, y,
        test_size=cfg.test_size,
        random_state=cfg.random_state,
        stratify=y
    )

    logging.info(f"\nTrain: {len(X_train):,} | Test: {len(X_test):,}")

    # Scale features for better convergence
    logging.info("\nScaling features...")
    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_test_scaled = scaler.transform(X_test)

    # Convert back to DataFrame for easier handling
    X_train_scaled = pd.DataFrame(X_train_scaled, columns=X_train.columns, index=X_train.index)
    X_test_scaled = pd.DataFrame(X_test_scaled, columns=X_test.columns, index=X_test.index)

    logging.info(f"Feature scaling complete (mean=0, std=1)")

    # Train model
    logging.info("\nTraining Logistic Regression (no intercept - forced 50% baseline)...")
    model = LogisticRegression(
        C=cfg.C,
        max_iter=cfg.max_iter,
        solver=cfg.solver,
        penalty=cfg.penalty,
        random_state=cfg.random_state,
        fit_intercept=False,  # Force 50-50 baseline (no intercept)
        verbose=0,
    )

    t_start = time.perf_counter()
    model.fit(X_train_scaled, y_train)
    t_elapsed = time.perf_counter() - t_start

    logging.info(f"Training complete in {t_elapsed:.2f}s")

    # Evaluate
    train_acc = model.score(X_train_scaled, y_train)
    test_acc = model.score(X_test_scaled, y_test)

    # Calculate average predictions (should be close to 50% with fit_intercept=False)
    train_pred_proba = model.predict_proba(X_train_scaled)[:, 1]
    test_pred_proba = model.predict_proba(X_test_scaled)[:, 1]
    train_avg_pred = train_pred_proba.mean()
    test_avg_pred = test_pred_proba.mean()

    logging.info(f"\nAccuracy: Train={train_acc:.3f} | Test={test_acc:.3f}")
    logging.info(f"Avg prediction: Train={train_avg_pred:.2%} | Test={test_avg_pred:.2%} (should be ~50%)")

    # Show feature coefficients (importance for logistic regression)
    # Positive coefficients increase win probability, negative decrease it
    coefficients = pd.DataFrame({
        'feature': feature_cols,
        'coefficient': model.coef_[0],
        'abs_coefficient': np.abs(model.coef_[0])
    }).sort_values('abs_coefficient', ascending=False)

    logging.info(f"\nTop 20 features (by absolute coefficient):")
    for _, row in coefficients.head(20).iterrows():
        direction = "↑" if row['coefficient'] > 0 else "↓"
        logging.info(f"  {row['feature']:<30} coef={row['coefficient']:>7.3f} {direction}")

    # Test on a few samples
    logging.info(f"\nSample predictions (from test set):")
    sample_indices = np.random.choice(len(X_test_scaled), min(5, len(X_test_scaled)), replace=False)
    for idx in sample_indices:
        pred_proba = model.predict_proba(X_test_scaled.iloc[[idx]])[0, 1]
        actual = y_test.iloc[idx]
        logging.info(f"  Predicted win prob: {pred_proba:.2%} | Actual: {'Win' if actual == 1 else 'Loss'}")

    # Generate synthetic scenarios to verify model behavior
    logging.info(f"\nSynthetic scenario testing:")
    logging.info("=" * 60)

    # Get typical ranges from training data for scaling synthetic values
    feature_stats = X_train.describe()

    def print_scenario_details(scenario_dict, scenario_name, scaler, feature_cols, roles, model):
        """Print detailed breakdown of a scenario with raw and scaled values."""
        logging.info(f"\n{scenario_name}")
        logging.info("-" * 80)

        # Create DataFrame and scale
        scenario_df = pd.DataFrame([scenario_dict])[feature_cols]
        scenario_scaled = pd.DataFrame(
            scaler.transform(scenario_df),
            columns=scenario_df.columns
        )

        # Get coefficients for win probability contribution
        coefficients = model.coef_[0]

        # Calculate log-odds contributions
        log_odds_contributions = scenario_scaled.iloc[0] * coefficients

        # Calculate probabilities
        baseline_prob = 0.50
        total_log_odds = log_odds_contributions.sum()
        final_prob = 1 / (1 + np.exp(-total_log_odds))
        prob_change = final_prob - baseline_prob

        # Convert each feature's log-odds to probability contribution
        feature_prob_contributions = {}
        if abs(total_log_odds) > 1e-10:
            for col in feature_cols:
                feature_prob_contributions[col] = prob_change * (log_odds_contributions[col] / total_log_odds)
        else:
            for col in feature_cols:
                feature_prob_contributions[col] = 0

        # Print per-lane breakdown
        for pos in roles:
            logging.info(f"\n  {pos.upper()}:")
            pos_features = [col for col in feature_cols if col.startswith(f'{pos}_')]

            for col in pos_features:
                metric = col.replace(f'{pos}_', '')
                raw_val = scenario_dict[col]
                scaled_val = scenario_scaled[col].iloc[0]
                wr_delta = feature_prob_contributions[col] * 100  # Convert to percentage points
                sign = "+" if wr_delta >= 0 else ""
                logging.info(f"    {metric:<20} raw={raw_val:>8.2f}  scaled={scaled_val:>7.2f}  wr_delta={sign}{wr_delta:>6.2f}pp")

        return scenario_df, scenario_scaled

    def print_lane_contributions(scenario_scaled, model, feature_cols, roles):
        """Calculate and print each lane's contribution to win probability."""
        logging.info("\n  Lane contributions to win probability:")
        logging.info("  " + "-" * 70)

        # Get coefficients (no intercept since fit_intercept=False)
        coefficients = model.coef_[0]

        # Calculate log-odds contribution for each feature
        # log_odds = sum(coef_i * x_i)  (no intercept)
        log_odds_contributions = scenario_scaled.iloc[0] * coefficients

        # Group by lane (log-odds space)
        lane_log_odds = {}
        for pos in roles:
            pos_features = [col for col in feature_cols if col.startswith(f'{pos}_')]
            pos_contribution = sum(log_odds_contributions[col] for col in pos_features if col in log_odds_contributions.index)
            lane_log_odds[pos] = pos_contribution

        # Calculate probabilities
        baseline_prob = 0.50  # 50-50 baseline (model forced to this via fit_intercept=False)
        total_log_odds = log_odds_contributions.sum()  # No intercept
        final_prob = 1 / (1 + np.exp(-total_log_odds))

        # Convert log-odds contributions to probability contributions
        # We want contributions to sum to (final_prob - 50%)
        total_log_odds_from_lanes = sum(lane_log_odds.values())
        prob_change = final_prob - baseline_prob

        lane_prob_contributions = {}
        if abs(total_log_odds_from_lanes) > 1e-10:  # Avoid division by zero
            for pos, log_odds_contrib in lane_log_odds.items():
                # Scale contribution proportionally
                lane_prob_contributions[pos] = prob_change * (log_odds_contrib / total_log_odds_from_lanes)
        else:
            # All lanes neutral
            for pos in lane_log_odds.keys():
                lane_prob_contributions[pos] = 0

        # Sort lanes by probability contribution
        sorted_lanes = sorted(lane_prob_contributions.items(), key=lambda x: x[1], reverse=True)

        logging.info(f"  {'Lane':<8} {'Prob contrib':<15} {'Cumulative':<15} {'Impact':<10}")
        logging.info("  " + "-" * 70)

        cumulative_prob = baseline_prob
        for pos, prob_contrib in sorted_lanes:
            cumulative_prob += prob_contrib
            impact = "↑ Helps win" if prob_contrib > 0 else "↓ Hurts win" if prob_contrib < 0 else "= Neutral"
            logging.info(f"  {pos.upper():<8} {prob_contrib:>+7.2%} ({prob_contrib*100:>+6.2f}pp)  {cumulative_prob:>6.2%}         {impact}")

        logging.info("  " + "-" * 70)
        logging.info(f"  Baseline (forced 50-50):    {baseline_prob:>6.2%}")
        logging.info(f"  Lane contributions:         {prob_change:>+6.2%} ({prob_change*100:>+6.2f}pp)")
        logging.info(f"  Final win probability:      {final_prob:>6.2%}")
        logging.info(f"  ✓ Verification: {baseline_prob:.2%} + {prob_change:+.2%} = {final_prob:.2%}")

    # Scenario 1: Balanced game (all stats equal)
    balanced = {}
    got_fb = random.choice([True, False])
    fb_pos = random.choice(cfg.roles)
    for col in feature_cols:
        col_pos = col.split('_')[0]
        if 'kills' in col or 'assists' in col:
            balanced[col] = round(feature_stats.loc['mean', col])  # Rounded mean
        elif 'deaths' in col:
            balanced[col] = round(feature_stats.loc['mean', col])
        elif 'damage' in col:
            balanced[col] = round(feature_stats.loc['mean', col])
        elif 'diff' in col:
            balanced[col] = 0  # Equal CS/XP
        elif 'firstbloodkill' in col:
            balanced[col] = 1 if (got_fb and col_pos == fb_pos) else 0
        elif col == 'firstbloodassist':
            balanced[col] = 1 if (got_fb and col_pos != fb_pos and random.random() < 0.25) else 0
        elif col == 'firstbloodvictim':
            balanced[col] = 1 if ((not got_fb) and col_pos == fb_pos) else 0
        else:
            balanced[col] = round(feature_stats.loc['mean', col])

    balanced_df, balanced_scaled = print_scenario_details(
        balanced, "1. Balanced game (all lanes equal)", scaler, feature_cols, cfg.roles, model
    )
    balanced_prob = model.predict_proba(balanced_scaled)[0, 1]
    logging.info(f"\n   → Win probability: {balanced_prob:.2%}")
    print_lane_contributions(balanced_scaled, model, feature_cols, cfg.roles)

    # Scenario 2: Dominating game (high stats across all lanes)
    dominating = balanced.copy()
    for col in feature_cols:
        if 'kills' in col or 'assists' in col:
            dominating[col] = feature_stats.loc['75%', col]
        elif 'deaths' in col:
            dominating[col] = feature_stats.loc['25%', col]
        elif 'damage' in col:
            dominating[col] = feature_stats.loc['75%', col]
        elif 'diff' in col:
            dominating[col] = abs(feature_stats.loc['75%', col])  # Positive CS/XP lead

    dominating_df, dominating_scaled = print_scenario_details(
        dominating, "2. Dominating performance (winning all lanes)", scaler, feature_cols, cfg.roles, model
    )
    dominating_prob = model.predict_proba(dominating_scaled)[0, 1]
    logging.info(f"\n   → Win probability: {dominating_prob:.2%}")
    print_lane_contributions(dominating_scaled, model, feature_cols, cfg.roles)

    # Scenario 3: Losing game (poor stats across all lanes)
    losing = balanced.copy()
    for col in feature_cols:
        if 'kills' in col or 'assists' in col:
            losing[col] = feature_stats.loc['25%', col]
        elif 'deaths' in col:
            losing[col] = feature_stats.loc['75%', col]
        elif 'damage' in col:
            losing[col] = feature_stats.loc['25%', col]
        elif 'diff' in col:
            losing[col] = -abs(feature_stats.loc['75%', col])  # Negative CS/XP (behind)

    losing_df, losing_scaled = print_scenario_details(
        losing, "3. Poor performance (losing all lanes)", scaler, feature_cols, cfg.roles, model
    )
    losing_prob = model.predict_proba(losing_scaled)[0, 1]
    logging.info(f"\n   → Win probability: {losing_prob:.2%}")
    print_lane_contributions(losing_scaled, model, feature_cols, cfg.roles)

    # Scenario 4: Mixed game (some lanes winning, some losing)
    mixed = balanced.copy()
    positions_ahead = ['top', 'mid']  # These lanes are winning
    positions_behind = ['jng', 'bot', 'sup']  # These lanes are losing

    for col in feature_cols:
        # Check which position this column belongs to
        for pos in positions_ahead:
            if col.startswith(f'{pos}_'):
                if 'kills' in col or 'assists' in col:
                    mixed[col] = feature_stats.loc['75%', col]
                elif 'deaths' in col:
                    mixed[col] = feature_stats.loc['25%', col]
                elif 'diff' in col:
                    mixed[col] = abs(feature_stats.loc['75%', col])

        for pos in positions_behind:
            if col.startswith(f'{pos}_'):
                if 'kills' in col or 'assists' in col:
                    mixed[col] = feature_stats.loc['25%', col]
                elif 'deaths' in col:
                    mixed[col] = feature_stats.loc['75%', col]
                elif 'diff' in col:
                    mixed[col] = -abs(feature_stats.loc['75%', col])

    mixed_df, mixed_scaled = print_scenario_details(
        mixed, "4. Mixed performance (Top/Mid winning, Jungle/Bot/Support losing)", scaler, feature_cols, cfg.roles, model
    )
    mixed_prob = model.predict_proba(mixed_scaled)[0, 1]
    logging.info(f"\n   → Win probability: {mixed_prob:.2%}")
    print_lane_contributions(mixed_scaled, model, feature_cols, cfg.roles)

    # Generate random scenarios
    n_random = 3  # Reduced to 3 since we're showing full details now
    for i in range(n_random):
        random_scenario = {}

        # First, sample a random team from training data to get consistent firstblood features
        # (ensures only one person has firstblood, only one has firstbloodvictim, etc.)
        random_team_idx = np.random.choice(len(X_train))

        # Extract firstblood features from this team (maintaining consistency)
        firstblood_cols = [col for col in feature_cols if 'firstblood' in col]
        for col in firstblood_cols:
            random_scenario[col] = X_train.iloc[random_team_idx][col]

        # Sample other features independently
        non_firstblood_cols = [col for col in feature_cols if 'firstblood' not in col]
        for col in non_firstblood_cols:
            random_scenario[col] = X_train[col].sample(1, random_state=None).iloc[0]

        random_df, random_scaled = print_scenario_details(
            random_scenario, f"5.{i+1}. Random scenario #{i+1} (sampled from training data)", scaler, feature_cols, cfg.roles, model
        )
        random_prob = model.predict_proba(random_scaled)[0, 1]
        logging.info(f"\n   → Win probability: {random_prob:.2%}")
        print_lane_contributions(random_scaled, model, feature_cols, cfg.roles)

    # Verify expectations
    logging.info("\n" + "=" * 60)
    logging.info("Sanity checks:")
    if dominating_prob > balanced_prob > losing_prob:
        logging.info("✓ Win probability ordering is correct:")
        logging.info(f"  Dominating ({dominating_prob:.2%}) > Balanced ({balanced_prob:.2%}) > Losing ({losing_prob:.2%})")
    else:
        logging.warning("✗ Win probability ordering is INCORRECT!")
        logging.warning(f"  Expected: Dominating > Balanced > Losing")
        logging.warning(f"  Got: {dominating_prob:.2%}, {balanced_prob:.2%}, {losing_prob:.2%}")

    if 0.4 < balanced_prob < 0.6:
        logging.info(f"✓ Balanced scenario predicts near 50%: {balanced_prob:.2%}")
    else:
        logging.warning(f"✗ Balanced scenario should be near 50%, got: {balanced_prob:.2%}")

    if mixed_prob > losing_prob:
        logging.info(f"✓ Mixed scenario better than losing: {mixed_prob:.2%} > {losing_prob:.2%}")
    else:
        logging.warning(f"✗ Mixed scenario should be better than losing!")

    logging.info("\n" + "=" * 60)
    logging.info("Model 2 Complete - Win Probability Model Ready")
    logging.info("=" * 60)

    return model


if __name__ == "__main__":
    cfg = WinProbabilityConfig()
    model = train_win_probability_model(cfg)
