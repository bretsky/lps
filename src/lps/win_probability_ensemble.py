"""
Model 2: Ensemble Win Probability Prediction

This module implements a two-stage ensemble approach:
1. Train 5 position-specific models (one per role) that predict win probability
   using only that position's features
2. Train a meta-model (LogisticRegression) that combines the 5 position
   predictions into a final win probability

This approach allows each position model to specialize in understanding how
performance in that role affects overall win probability.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional, Sequence

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler

from .config import ORACLE_DIR
from .io_oracle import load_oracle_years

logging.basicConfig(level=logging.INFO, format="%(message)s")


@dataclass
class EnsembleConfig:
    """Configuration for ensemble win probability model."""

    oracle_dir: Path = ORACLE_DIR
    years: Iterable[int] = (2024,)
    roles: Sequence[str] = ("top", "jng", "mid", "bot", "sup")

    # Performance metrics to use as features (per position)
    # Note: Firstblood is a team-level feature in meta-model, not position-level
    performance_metrics: Sequence[str] = (
        "kills",
        "deaths",
        "assists",
        "csdiffat15",
    )

    # Position model parameters (LogisticRegression)
    position_C: float = 1.0
    position_max_iter: int = 1000
    position_solver: str = "lbfgs"

    # Meta-model parameters (LogisticRegression)
    meta_C: float = 1.0
    meta_max_iter: int = 1000
    meta_solver: str = "lbfgs"
    meta_fit_intercept: bool = False  # Force 50% baseline (no intercept)

    random_state: int = 42


def preprocess_oracle_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Standardize column names for Oracle's Elixir data."""
    df = df.copy()

    # Common column renames
    renames = {
        "position": "position",
        "playername": "playername",
        "teamname": "teamname",
        "result": "result",
        "gamelength": "gamelength",
    }

    # Only rename columns that exist
    renames = {k: v for k, v in renames.items() if k in df.columns}
    if renames:
        df = df.rename(columns=renames)

    # Convert gamelength from seconds to minutes if needed
    if "gamelength" in df.columns:
        if df["gamelength"].median() > 100:  # Likely in seconds
            df["gamelength_min"] = df["gamelength"] / 60
        else:
            df["gamelength_min"] = df["gamelength"]

    # Ensure result is binary (1 = win, 0 = loss)
    if "result" in df.columns:
        df["result"] = df["result"].astype(int)

    return df


def build_team_features(cfg: Optional[EnsembleConfig] = None) -> pd.DataFrame:
    """
    Build team-level features from player-level Oracle data.

    For each game-team, creates features like:
    - top_kills_nonfb, top_deaths_nonfb, top_assists_nonfb, ...
    - jng_kills_nonfb, jng_deaths_nonfb, jng_assists_nonfb, ...
    - etc. for all 5 positions

    Returns:
        DataFrame with one row per team-game, columns for all position features,
        and a 'result' column (1=win, 0=loss)
    """
    if cfg is None:
        cfg = EnsembleConfig()

    logging.info("Loading Oracle data...")
    df = load_oracle_years(cfg.years)
    df = preprocess_oracle_columns(df)

    # Filter to valid positions and games with results
    df = df[df["position"].isin(cfg.roles)]
    df = df[df["result"].notna()]

    logging.info(f"Loaded {len(df):,} player-games")

    # Build team-level features
    logging.info("Building team-level features...")

    # We need to pivot so each game-team has all 5 positions as columns
    # Group by gameid + team (all players on same team have same result)
    pivot_features = list(cfg.performance_metrics)

    # Also include firstblood features temporarily (needed for team-level firstblood flag)
    firstblood_features = ["firstbloodkill", "firstbloodassist", "firstbloodvictim"]
    pivot_features.extend(firstblood_features)

    # Check which features exist
    pivot_features = [f for f in pivot_features if f in df.columns]

    team_data = []
    for gameid, game in df.groupby("gameid"):
        # Each game should have 10 players (5 blue, 5 red)
        if len(game) != 10:
            continue

        # Split into blue and red teams
        blue_team = game[game["side"] == "Blue"] if "side" in game.columns else game.iloc[:5]
        red_team = game[game["side"] == "Red"] if "side" in game.columns else game.iloc[5:]

        for team, team_players in [("blue", blue_team), ("red", red_team)]:
            # Get result (all players on team have same result)
            result = team_players["result"].iloc[0]

            row = {"gameid": gameid, "result": result}

            # Add features for each position
            for position in cfg.roles:
                pos_players = team_players[team_players["position"] == position]
                if len(pos_players) != 1:
                    # Skip if position not found or duplicated
                    break

                player = pos_players.iloc[0]
                for metric in pivot_features:
                    row[f"{position}_{metric}"] = player[metric]
            else:
                # Only add row if all 5 positions were found
                team_data.append(row)

    team_df = pd.DataFrame(team_data)
    logging.info(f"Created team features: {len(team_df):,} teams, {len(team_df.columns)} columns")

    # Create team-level firstblood feature
    # teamfirstblood = 1 if team got firstblood, 0 if enemy got firstblood
    logging.info("Creating team-level firstblood feature...")
    fb_kill_cols = [f"{pos}_firstbloodkill" for pos in cfg.roles]
    fb_assist_cols = [f"{pos}_firstbloodassist" for pos in cfg.roles]

    # Team got firstblood if any position got kill or assist
    team_df["teamfirstblood"] = (
        (team_df[fb_kill_cols].sum(axis=1) > 0) |
        (team_df[fb_assist_cols].sum(axis=1) > 0)
    ).astype(int)

    # Drop position-specific firstblood columns (no longer needed)
    logging.info("Dropping position-specific firstblood columns...")
    fb_cols_to_drop = []
    for pos in cfg.roles:
        fb_cols_to_drop.extend([f"{pos}_firstbloodkill", f"{pos}_firstbloodassist", f"{pos}_firstbloodvictim"])
    fb_cols_to_drop = [col for col in fb_cols_to_drop if col in team_df.columns]
    if fb_cols_to_drop:
        team_df = team_df.drop(columns=fb_cols_to_drop)
        logging.info(f"Dropped {len(fb_cols_to_drop)} position-specific firstblood columns")

    # Drop rows with missing data
    before = len(team_df)
    team_df = team_df.dropna()
    if len(team_df) < before:
        logging.warning(f"Dropped {before - len(team_df):,} teams with missing data")

    return team_df


def train_ensemble_model(cfg: Optional[EnsembleConfig] = None):
    """
    Train the ensemble win probability model.

    Stage 1: Train 5 position-specific models
    Stage 2: Train meta-model to combine position predictions
    """
    if cfg is None:
        cfg = EnsembleConfig()

    logging.info("=" * 60)
    logging.info("Ensemble Win Probability Model")
    logging.info("=" * 60)

    # Build team features
    team_df = build_team_features(cfg)

    # Extract target variable and teamfirstblood
    y = team_df["result"]
    teamfirstblood = team_df["teamfirstblood"]
    team_df = team_df.drop(columns=["gameid", "result", "teamfirstblood"])

    # Split into train/test
    X_train, X_test, y_train, y_test, teamfb_train, teamfb_test = train_test_split(
        team_df, y, teamfirstblood, test_size=0.2, random_state=cfg.random_state, stratify=y
    )

    logging.info(f"\nTrain size: {len(X_train):,} | Test size: {len(X_test):,}")

    # ========================================================================
    # Stage 1: Train position-specific models
    # ========================================================================
    logging.info("\n" + "=" * 60)
    logging.info("Stage 1: Training Position-Specific Models")
    logging.info("=" * 60)

    position_models = {}
    position_scalers = {}
    position_predictions_train = {}
    position_predictions_test = {}

    for pos in cfg.roles:
        logging.info(f"\n--- Training {pos.upper()} model ---")

        # Get features for this position
        pos_features = [col for col in X_train.columns if col.startswith(f"{pos}_")]
        logging.info(f"Features: {len(pos_features)} ({', '.join(pos_features)})")

        # Extract position data
        X_train_pos = X_train[pos_features]
        X_test_pos = X_test[pos_features]

        # Scale features
        scaler = StandardScaler()
        X_train_pos_scaled = scaler.fit_transform(X_train_pos)
        X_test_pos_scaled = scaler.transform(X_test_pos)

        # Train position model (LogisticRegression)
        model = LogisticRegression(
            C=cfg.position_C,
            max_iter=cfg.position_max_iter,
            solver=cfg.position_solver,
            random_state=cfg.random_state,
            fit_intercept=True,  # Each position can have its own baseline
            verbose=0,
        )
        model.fit(X_train_pos_scaled, y_train)

        # Evaluate
        train_acc = accuracy_score(y_train, model.predict(X_train_pos_scaled))
        test_acc = accuracy_score(y_test, model.predict(X_test_pos_scaled))

        # Get win probability predictions
        train_proba = model.predict_proba(X_train_pos_scaled)[:, 1]
        test_proba = model.predict_proba(X_test_pos_scaled)[:, 1]

        logging.info(f"Accuracy: Train={train_acc:.3f} | Test={test_acc:.3f}")
        logging.info(f"Avg predicted win rate: Train={train_proba.mean():.2%} | Test={test_proba.mean():.2%}")

        # Show feature coefficients (importance for logistic regression)
        coefficients_df = pd.DataFrame({
            'feature': pos_features,
            'coefficient': model.coef_[0],
            'abs_coefficient': np.abs(model.coef_[0])
        }).sort_values('abs_coefficient', ascending=False)

        logging.info(f"\nFeature coefficients (sorted by absolute value):")
        for _, row in coefficients_df.iterrows():
            direction = "↑" if row['coefficient'] > 0 else "↓"
            metric = row['feature'].replace(f"{pos}_", "")
            logging.info(f"  {metric:<20} coef={row['coefficient']:>7.3f} {direction}")

        # Show correlations with target
        X_train_pos_df = pd.DataFrame(X_train_pos_scaled, columns=pos_features)
        correlations = X_train_pos_df.corrwith(pd.Series(y_train.values)).fillna(0)
        correlations_df = pd.DataFrame({
            'feature': correlations.index,
            'correlation': correlations.values,
            'abs_correlation': np.abs(correlations.values)
        }).sort_values('abs_correlation', ascending=False)

        logging.info(f"\nFeature correlations with win (on scaled features):")
        for _, row in correlations_df.iterrows():
            direction = "↑" if row['correlation'] > 0 else "↓"
            metric = row['feature'].replace(f"{pos}_", "")
            logging.info(f"  {metric:<20} corr={row['correlation']:>7.3f} {direction}")

        # Store model and predictions
        position_models[pos] = model
        position_scalers[pos] = scaler
        position_predictions_train[pos] = train_proba
        position_predictions_test[pos] = test_proba

    # ========================================================================
    # Stage 2: Train meta-model
    # ========================================================================
    logging.info("\n" + "=" * 60)
    logging.info("Stage 2: Training Meta-Model (Logistic Regression)")
    logging.info("=" * 60)

    # Create meta-features: 5 position win rate predictions + team firstblood
    meta_X_train = pd.DataFrame(position_predictions_train)
    meta_X_test = pd.DataFrame(position_predictions_test)

    # Add team-level firstblood feature
    meta_X_train['teamfirstblood'] = teamfb_train.values
    meta_X_test['teamfirstblood'] = teamfb_test.values

    logging.info(f"Meta-features shape: Train={meta_X_train.shape} | Test={meta_X_test.shape}")
    logging.info(f"Meta-features: {list(meta_X_train.columns)}")

    # Scale meta-features
    meta_scaler = StandardScaler()
    meta_X_train_scaled = meta_scaler.fit_transform(meta_X_train)
    meta_X_test_scaled = meta_scaler.transform(meta_X_test)

    # Show scaling info
    logging.info(f"\nMeta-feature scaling (StandardScaler):")
    for i, pos in enumerate(meta_X_train.columns):
        mean = meta_scaler.mean_[i]
        std = meta_scaler.scale_[i]
        logging.info(f"  {pos.upper():<8} mean={mean:.4f}  std={std:.4f}")

    # Train LogisticRegression meta-model
    meta_model = LogisticRegression(
        C=cfg.meta_C,
        max_iter=cfg.meta_max_iter,
        solver=cfg.meta_solver,
        fit_intercept=cfg.meta_fit_intercept,
        random_state=cfg.random_state,
        verbose=0,
    )
    meta_model.fit(meta_X_train_scaled, y_train)

    # Evaluate LogisticRegression meta-model
    train_acc = accuracy_score(y_train, meta_model.predict(meta_X_train_scaled))
    test_acc = accuracy_score(y_test, meta_model.predict(meta_X_test_scaled))

    train_proba = meta_model.predict_proba(meta_X_train_scaled)[:, 1]
    test_proba = meta_model.predict_proba(meta_X_test_scaled)[:, 1]

    logging.info(f"\nLogisticRegression meta-model:")
    logging.info(f"  Accuracy: Train={train_acc:.3f} | Test={test_acc:.3f}")
    logging.info(f"  Avg prediction: Train={train_proba.mean():.2%} | Test={test_proba.mean():.2%} (should be ~50%)")

    # Create simple average baseline meta-model for comparison
    def average_meta_model(position_probs):
        """Simple baseline: just average the 5 position predictions (ignore teamfirstblood)."""
        # Only average the position predictions, not teamfirstblood
        pos_only = {k: v for k, v in position_probs.items() if k in cfg.roles}
        return np.mean(list(pos_only.values()))

    # Evaluate average meta-model (only average position predictions, not teamfirstblood)
    position_cols = [col for col in meta_X_train.columns if col in cfg.roles]
    train_avg_proba = meta_X_train[position_cols].mean(axis=1).values
    test_avg_proba = meta_X_test[position_cols].mean(axis=1).values

    train_avg_pred = (train_avg_proba > 0.5).astype(int)
    test_avg_pred = (test_avg_proba > 0.5).astype(int)

    train_avg_acc = accuracy_score(y_train, train_avg_pred)
    test_avg_acc = accuracy_score(y_test, test_avg_pred)

    logging.info(f"\nSimple Average meta-model (baseline):")
    logging.info(f"  Accuracy: Train={train_avg_acc:.3f} | Test={test_avg_acc:.3f}")
    logging.info(f"  Avg prediction: Train={train_avg_proba.mean():.2%} | Test={test_avg_proba.mean():.2%}")

    # Show coefficients (direct interpretability with LogisticRegression!)
    coefficients_df = pd.DataFrame({
        'feature': meta_X_train.columns,
        'coefficient': meta_model.coef_[0],
        'abs_coefficient': np.abs(meta_model.coef_[0])
    }).sort_values('abs_coefficient', ascending=False)

    logging.info(f"\nLogisticRegression coefficients (on scaled features):")
    logging.info(f"  {'Feature':<15} {'Coefficient':<14} {'Interpretation':<30}")
    logging.info("  " + "-" * 65)

    for _, row in coefficients_df.iterrows():
        feat = row['feature']
        coef = row['coefficient']

        # Determine direction and interpretation
        if feat == 'teamfirstblood':
            if coef > 0:
                direction = "↑"
                interpretation = "Team FB → More wins"
            else:
                direction = "↓"
                interpretation = "Team FB → Fewer wins (unexpected!)"
        else:
            if coef > 0:
                direction = "↑"
                interpretation = "Higher → More wins"
            else:
                direction = "↓"
                interpretation = "Higher → Fewer wins (unexpected!)"

        logging.info(f"  {feat.upper():<15} {coef:>+7.3f} {direction}      {interpretation}")

    # Show correlations for comparison
    correlations = meta_X_train.corrwith(y_train).fillna(0)
    correlations_df = pd.DataFrame({
        'feature': correlations.index,
        'correlation': correlations.values,
    }).sort_values('correlation', ascending=False)

    logging.info(f"\nMeta-feature correlations with win (for comparison):")
    for _, row in correlations_df.iterrows():
        direction = "↑" if row['correlation'] > 0 else "↓"
        logging.info(f"  {row['feature'].upper():<15} {row['correlation']:>+7.3f} {direction}")

    logging.info("\nInterpretation:")
    logging.info("  - Coefficients are on scaled features (standardized)")
    logging.info("  - No intercept (forced 50% baseline)")
    logging.info("  - Positive coefficient: Higher value → Higher overall win rate")
    logging.info("  - Larger coefficient = feature matters more in final prediction")
    logging.info("  - All features should have positive coefficients")
    logging.info("  - If all coefficients are similar, LogisticRegression is learning to average")

    # Store coefficients as "importance" for use in scenarios (now it's the actual coefficient!)
    feature_importances = pd.DataFrame({
        'feature': coefficients_df['feature'],
        'importance': np.abs(coefficients_df['coefficient']),  # Use absolute value for weighting
        'coefficient': coefficients_df['coefficient']  # Keep raw coefficient for direction
    })

    # ========================================================================
    # Test scenarios
    # ========================================================================
    logging.info("\n" + "=" * 60)
    logging.info("Scenario Testing")
    logging.info("=" * 60)

    # Get typical ranges from training data
    feature_stats = X_train.describe()

    def print_position_details(pos, scenario_dict, position_models, position_scalers, feature_stats):
        """Print detailed feature breakdown for a position."""
        pos_features = [col for col in scenario_dict.keys() if col.startswith(f"{pos}_")]

        # Get position data
        pos_data = {col: scenario_dict[col] for col in pos_features}
        pos_df = pd.DataFrame([pos_data])
        pos_scaled = position_scalers[pos].transform(pos_df)
        pos_scaled_df = pd.DataFrame(pos_scaled, columns=pos_df.columns)

        # Get prediction
        pos_prob = position_models[pos].predict_proba(pos_scaled)[0, 1]

        # Get coefficients for contribution calculation
        coefficients = position_models[pos].coef_[0]
        intercept = position_models[pos].intercept_[0]

        # Calculate log-odds contributions
        log_odds_contributions = pos_scaled_df.iloc[0] * coefficients
        total_log_odds = log_odds_contributions.sum() + intercept

        # Calculate baseline (intercept only)
        baseline_prob = 1 / (1 + np.exp(-intercept))
        prob_change = pos_prob - baseline_prob

        # Feature contributions to probability
        feature_prob_contributions = {}
        if abs(total_log_odds - intercept) > 1e-10:
            for col in pos_features:
                feature_prob_contributions[col] = prob_change * (
                    log_odds_contributions[col] / (total_log_odds - intercept)
                )
        else:
            for col in pos_features:
                feature_prob_contributions[col] = 0

        logging.info(f"\n  {pos.upper()}: (predicted win rate: {pos_prob:.2%})")
        for col in pos_features:
            metric = col.replace(f'{pos}_', '')
            raw_val = scenario_dict[col]
            scaled_val = pos_scaled_df[col].iloc[0]
            wr_delta = feature_prob_contributions[col] * 100
            sign = "+" if wr_delta >= 0 else ""

            # Special formatting for binary features
            if metric in ['firstbloodkill', 'firstbloodassist', 'firstbloodvictim']:
                logging.info(f"    {metric:<20} raw={raw_val:>8.0f}  scaled={scaled_val:>7.2f}  wr_delta={sign}{wr_delta:>6.2f}pp")
            else:
                logging.info(f"    {metric:<20} raw={raw_val:>8.2f}  scaled={scaled_val:>7.2f}  wr_delta={sign}{wr_delta:>6.2f}pp")

        return pos_prob

    def print_scenario(scenario_dict, scenario_name):
        """Print full scenario with all positions and final prediction."""
        logging.info(f"\n{scenario_name}")
        logging.info("-" * 80)

        # Get predictions from all position models
        position_probs = {}
        for pos in cfg.roles:
            pos_prob = print_position_details(pos, scenario_dict, position_models, position_scalers, feature_stats)
            position_probs[pos] = pos_prob

        # Extract teamfirstblood from scenario
        teamfirstblood = scenario_dict.get('teamfirstblood', 0)

        # Get predictions from both meta-models
        meta_input = pd.DataFrame([position_probs])
        meta_input['teamfirstblood'] = teamfirstblood
        meta_input_scaled = meta_scaler.transform(meta_input)

        # LogisticRegression prediction
        lr_prob = meta_model.predict_proba(meta_input_scaled)[0, 1]

        # Simple average prediction
        avg_prob = average_meta_model(position_probs)

        logging.info(f"\n  Meta-model inputs:")
        logging.info(f"    {'Feature':<12} {'Unscaled':<15} {'Scaled':<12}")
        logging.info(f"    {'-'*12} {'-'*15} {'-'*12}")
        for i, pos in enumerate(cfg.roles):
            unscaled_val = position_probs[pos]
            scaled_val = meta_input_scaled[0, i]
            logging.info(f"    {pos.upper():<12} {unscaled_val:>7.4f} ({unscaled_val:>5.1%})  {scaled_val:>+7.3f}")
        # Add teamfirstblood
        fb_unscaled = teamfirstblood
        fb_scaled = meta_input_scaled[0, -1]  # Last feature
        fb_text = "Team got FB" if fb_unscaled == 1 else "Enemy got FB"
        logging.info(f"    {'teamfb':<12} {fb_unscaled:>7.0f} ({fb_text:<7})  {fb_scaled:>+7.3f}")

        logging.info(f"\n  Final win probability (meta-model comparison):")
        logging.info(f"    Simple Average:         {avg_prob:.2%}")
        logging.info(f"    LogisticRegression:     {lr_prob:.2%}")
        logging.info(f"    Difference:             {(lr_prob - avg_prob)*100:+.2f}pp")

        # Use LogisticRegression for detailed breakdown
        final_prob = lr_prob

        # Calculate net winrate change attributable to each feature (positions + teamfirstblood)
        logging.info(f"\n  Net winrate change attributable to each feature:")
        logging.info("  " + "-" * 85)

        baseline = 0.50
        total_change = final_prob - baseline

        # Calculate weighted contributions
        # Approximate contribution as (deviation from neutral) * importance, then normalize
        contributions = []
        raw_contributions = {}

        # Position contributions
        for pos in cfg.roles:
            importance = feature_importances[feature_importances['feature'] == pos]['importance'].iloc[0]
            deviation = position_probs[pos] - baseline
            raw_contribution = deviation * importance
            raw_contributions[pos] = raw_contribution
            contributions.append((pos, position_probs[pos], deviation, importance, raw_contribution, 'position'))

        # Teamfirstblood contribution
        fb_importance = feature_importances[feature_importances['feature'] == 'teamfirstblood']['importance'].iloc[0]
        fb_baseline = 0.5  # Neutral = 50% chance of getting firstblood
        fb_deviation = teamfirstblood - fb_baseline
        fb_raw_contribution = fb_deviation * fb_importance
        raw_contributions['teamfirstblood'] = fb_raw_contribution
        contributions.append(('teamfirstblood', teamfirstblood, fb_deviation, fb_importance, fb_raw_contribution, 'team'))

        # Normalize contributions to sum to total_change
        sum_raw_contributions = sum(raw_contributions.values())
        if abs(sum_raw_contributions) > 1e-10:
            normalization_factor = total_change / sum_raw_contributions
        else:
            normalization_factor = 0

        normalized_contributions = []
        for feat, value, deviation, importance, raw_contrib, feat_type in contributions:
            normalized_contrib = raw_contrib * normalization_factor
            normalized_contributions.append((feat, value, deviation, importance, normalized_contrib, feat_type))

        # Sort by absolute contribution
        normalized_contributions.sort(key=lambda x: abs(x[4]), reverse=True)

        logging.info(f"  {'Feature':<12} {'Value':<12} {'Dev Neut':<12} {'Importance':<12} {'WR Contrib':<12} {'Impact':<10}")
        logging.info("  " + "-" * 85)

        cumulative = baseline
        for feat, value, deviation, importance, contrib, feat_type in normalized_contributions:
            cumulative += contrib
            impact = "↑ Helps" if contrib > 0 else "↓ Hurts" if contrib < 0 else "= Neutral"

            if feat_type == 'position':
                value_str = f"{value:>6.2%}"
            else:  # teamfirstblood
                value_str = "Got FB" if value == 1 else "Lost FB"

            logging.info(
                f"  {feat.upper():<12} {value_str:<12} {deviation*100:>+6.2f}pp     "
                f"{importance:>6.3f}       {contrib*100:>+6.2f}pp     {impact}"
            )

        logging.info("  " + "-" * 85)
        logging.info(f"  Baseline:                                                     {baseline:.2%}")
        logging.info(f"  Total contributions:                                          {total_change*100:>+6.2f}pp")
        logging.info(f"  Final win probability:                                        {final_prob:.2%}")
        logging.info(f"  ✓ Verification: {baseline:.2%} + {total_change*100:+.2f}pp = {final_prob:.2%}")

    # Scenario 1: Balanced game (all stats equal)
    balanced = {}
    for col in X_train.columns:
        col_name = '_'.join(col.split('_')[1:]) if '_' in col else col
        if col_name in ['kills', 'assists', 'deaths']:
            balanced[col] = round(feature_stats.loc['mean', col])
        elif 'diff' in col_name:
            balanced[col] = 0  # Equal CS/XP
        else:
            balanced[col] = round(feature_stats.loc['mean', col])

    # Add team-level firstblood (sample from training data)
    balanced['teamfirstblood'] = int(teamfb_train.sample(1).iloc[0])

    print_scenario(balanced, "1. Balanced game (all positions average performance)")

    # Scenario 2: Dominating game (high stats across all lanes)
    dominating = balanced.copy()
    for col in X_train.columns:
        if 'kills' in col or 'assists' in col:
            dominating[col] = feature_stats.loc['75%', col]
        elif 'deaths' in col:
            dominating[col] = feature_stats.loc['25%', col]
        elif 'diff' in col:
            dominating[col] = abs(feature_stats.loc['75%', col])

    dominating['teamfirstblood'] = 1  # Team got firstblood

    print_scenario(dominating, "2. Dominating performance (winning all lanes)")

    # Scenario 3: Losing game (poor stats across all lanes)
    losing = balanced.copy()
    for col in X_train.columns:
        if 'kills' in col or 'assists' in col:
            losing[col] = feature_stats.loc['25%', col]
        elif 'deaths' in col:
            losing[col] = feature_stats.loc['75%', col]
        elif 'diff' in col:
            losing[col] = -abs(feature_stats.loc['75%', col])

    losing['teamfirstblood'] = 0  # Enemy got firstblood

    print_scenario(losing, "3. Poor performance (losing all lanes)")

    # Scenario 4: Mixed game (some lanes winning, some losing)
    mixed = balanced.copy()
    positions_ahead = ['top', 'mid']
    positions_behind = ['jng', 'bot', 'sup']

    for col in X_train.columns:
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

    print_scenario(mixed, "4. Mixed performance (Top/Mid winning, Jungle/Bot/Support losing)")

    # Random scenarios
    n_random = 3
    for i in range(n_random):
        random_scenario = {}
        for col in X_train.columns:
            random_scenario[col] = X_train[col].sample(1, random_state=None).iloc[0]

        # Sample teamfirstblood independently
        random_scenario['teamfirstblood'] = int(teamfb_train.sample(1).iloc[0])

        print_scenario(random_scenario, f"5.{i+1}. Random scenario #{i+1} (sampled from training data)")

    return {
        'position_models': position_models,
        'position_scalers': position_scalers,
        'meta_model': meta_model,
        'meta_scaler': meta_scaler,
        'average_meta_model': average_meta_model,
        'feature_stats': feature_stats,
        'cfg': cfg,
    }


if __name__ == "__main__":
    train_ensemble_model()
