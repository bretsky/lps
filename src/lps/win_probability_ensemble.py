"""
Model 2: Ensemble Win Probability Prediction

This module implements a two-stage ensemble approach:
1. Train 5 position-specific models (one per role) that predict win probability
   using only that position's features
2. Train a meta-model (GradientBoostingClassifier) that combines the 5 position
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
from sklearn.ensemble import GradientBoostingClassifier
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
    performance_metrics: Sequence[str] = (
        "kills_nonfb",  # Kills excluding firstblood
        "deaths_nonfb",  # Deaths excluding firstblood victim
        "assists_nonfb",  # Assists excluding firstblood assist
        "csdiffat15",
        "firstbloodkill",  # Binary: did this player get firstblood kill
        "firstbloodassist",  # Binary: did this player get firstblood assist
        "firstbloodvictim",  # Binary: did this player die to firstblood
    )

    # Position model parameters (LogisticRegression)
    position_C: float = 1.0
    position_max_iter: int = 1000
    position_solver: str = "lbfgs"

    # Meta-model parameters (GradientBoostingClassifier)
    meta_n_estimators: int = 100
    meta_max_depth: int = 3
    meta_learning_rate: float = 0.1

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

    # Decompose KDA to remove firstblood correlation
    logging.info("Decomposing KDA features...")
    if "kills" in df.columns and "firstbloodkill" in df.columns:
        df["kills_nonfb"] = df["kills"] - df["firstbloodkill"]
    if "assists" in df.columns and "firstbloodassist" in df.columns:
        df["assists_nonfb"] = df["assists"] - df["firstbloodassist"]
    if "deaths" in df.columns and "firstbloodvictim" in df.columns:
        df["deaths_nonfb"] = df["deaths"] - df["firstbloodvictim"]

    # Build team-level features
    logging.info("Building team-level features...")

    # We need to pivot so each game-team has all 5 positions as columns
    # Group by gameid + team (all players on same team have same result)
    pivot_features = list(cfg.performance_metrics)

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

    # Extract target variable
    y = team_df["result"]
    team_df = team_df.drop(columns=["gameid", "result"])

    # Split into train/test
    X_train, X_test, y_train, y_test = train_test_split(
        team_df, y, test_size=0.2, random_state=cfg.random_state, stratify=y
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
    logging.info("Stage 2: Training Meta-Model (Gradient Boosting)")
    logging.info("=" * 60)

    # Create meta-features: 5 position win rate predictions
    meta_X_train = pd.DataFrame(position_predictions_train)
    meta_X_test = pd.DataFrame(position_predictions_test)

    logging.info(f"Meta-features shape: Train={meta_X_train.shape} | Test={meta_X_test.shape}")
    logging.info(f"Meta-features: {list(meta_X_train.columns)}")

    # Train meta-model
    meta_model = GradientBoostingClassifier(
        n_estimators=cfg.meta_n_estimators,
        max_depth=cfg.meta_max_depth,
        learning_rate=cfg.meta_learning_rate,
        random_state=cfg.random_state,
        verbose=0,
    )
    meta_model.fit(meta_X_train, y_train)

    # Evaluate
    train_acc = accuracy_score(y_train, meta_model.predict(meta_X_train))
    test_acc = accuracy_score(y_test, meta_model.predict(meta_X_test))

    train_proba = meta_model.predict_proba(meta_X_train)[:, 1]
    test_proba = meta_model.predict_proba(meta_X_test)[:, 1]

    logging.info(f"\nMeta-model Accuracy: Train={train_acc:.3f} | Test={test_acc:.3f}")
    logging.info(f"Meta-model Avg prediction: Train={train_proba.mean():.2%} | Test={test_proba.mean():.2%}")

    # Show feature importances and correlations (combined view)
    correlations = meta_X_train.corrwith(y_train).fillna(0)

    feature_analysis = pd.DataFrame({
        'position': meta_X_train.columns,
        'importance': meta_model.feature_importances_,
        'correlation': [correlations[pos] for pos in meta_X_train.columns],
    })

    # Calculate directional importance (importance × sign of correlation)
    feature_analysis['directional_importance'] = (
        feature_analysis['importance'] * np.sign(feature_analysis['correlation'])
    )
    feature_analysis['abs_directional_importance'] = np.abs(feature_analysis['directional_importance'])

    # Sort by absolute directional importance
    feature_analysis = feature_analysis.sort_values('abs_directional_importance', ascending=False)

    logging.info(f"\nMeta-model position effects (magnitude & direction):")
    logging.info(f"  {'Position':<10} {'Importance':<12} {'Correlation':<14} {'Dir. Effect':<15} {'Interpretation':<20}")
    logging.info("  " + "-" * 85)

    for _, row in feature_analysis.iterrows():
        pos = row['position']
        importance = row['importance']
        correlation = row['correlation']
        dir_importance = row['directional_importance']

        # Determine direction symbol and interpretation
        if correlation > 0:
            direction = "↑"
            interpretation = "Higher → More wins"
        else:
            direction = "↓"
            interpretation = "Higher → Fewer wins"

        sign = "+" if dir_importance >= 0 else ""

        logging.info(
            f"  {pos.upper():<10} {importance:>7.3f}      {correlation:>+7.3f} {direction}      "
            f"{sign}{dir_importance:>+7.3f}        {interpretation}"
        )

    logging.info("\nInterpretation:")
    logging.info("  - Importance: How much the meta-model relies on this position (magnitude)")
    logging.info("  - Correlation: Direction of relationship between position prediction and winning")
    logging.info("  - Directional Effect: Importance × sign(Correlation) - combined magnitude & direction")
    logging.info("  - All positions should show ↑ (higher performance → more wins)")

    # Store feature importances for use in scenarios
    # Create a simplified version for backward compatibility
    feature_importances = pd.DataFrame({
        'position': feature_analysis['position'],
        'importance': feature_analysis['importance']
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

        # Get final prediction from meta-model
        meta_input = pd.DataFrame([position_probs])
        final_prob = meta_model.predict_proba(meta_input)[0, 1]

        logging.info(f"\n  Position-level predictions:")
        for pos in cfg.roles:
            logging.info(f"    {pos.upper():<8} {position_probs[pos]:.2%}")

        logging.info(f"\n  → Final win probability (from meta-model): {final_prob:.2%}")

        # Calculate net winrate change attributable to each position
        logging.info(f"\n  Net winrate change attributable to each position:")
        logging.info("  " + "-" * 80)

        baseline = 0.50
        total_change = final_prob - baseline

        # Calculate weighted contributions
        # Approximate contribution as (deviation from 50%) * importance, then normalize
        contributions = []
        raw_contributions = {}
        for pos in cfg.roles:
            importance = feature_importances[feature_importances['position'] == pos]['importance'].iloc[0]
            deviation = position_probs[pos] - baseline
            raw_contribution = deviation * importance
            raw_contributions[pos] = raw_contribution
            contributions.append((pos, position_probs[pos], deviation, importance, raw_contribution))

        # Normalize contributions to sum to total_change
        sum_raw_contributions = sum(raw_contributions.values())
        if abs(sum_raw_contributions) > 1e-10:
            normalization_factor = total_change / sum_raw_contributions
        else:
            normalization_factor = 0

        normalized_contributions = []
        for pos, pos_prob, deviation, importance, raw_contrib in contributions:
            normalized_contrib = raw_contrib * normalization_factor
            normalized_contributions.append((pos, pos_prob, deviation, importance, normalized_contrib))

        # Sort by absolute contribution
        normalized_contributions.sort(key=lambda x: abs(x[4]), reverse=True)

        logging.info(f"  {'Pos':<8} {'Pred WR':<10} {'Dev 50%':<12} {'Importance':<12} {'WR Contrib':<12} {'Impact':<10}")
        logging.info("  " + "-" * 80)

        cumulative = baseline
        for pos, pos_prob, deviation, importance, contrib in normalized_contributions:
            cumulative += contrib
            impact = "↑ Helps" if contrib > 0 else "↓ Hurts" if contrib < 0 else "= Neutral"
            logging.info(
                f"  {pos.upper():<8} {pos_prob:>6.2%}     {deviation*100:>+6.2f}pp     "
                f"{importance:>6.3f}       {contrib*100:>+6.2f}pp     {impact}"
            )

        logging.info("  " + "-" * 80)
        logging.info(f"  Baseline:                                             {baseline:.2%}")
        logging.info(f"  Total position contributions:                         {total_change*100:>+6.2f}pp")
        logging.info(f"  Final win probability:                                {final_prob:.2%}")
        logging.info(f"  ✓ Verification: {baseline:.2%} + {total_change*100:+.2f}pp = {final_prob:.2%}")

    # Scenario 1: Balanced game (all stats equal)
    # Sample firstblood features from a random match to ensure consistency
    random_match_idx = np.random.choice(len(X_train))
    firstblood_cols = [col for col in X_train.columns if 'firstblood' in col]

    balanced = {}
    for col in X_train.columns:
        col_name = '_'.join(col.split('_')[1:]) if '_' in col else col
        if col in firstblood_cols:
            # Use firstblood values from the same random match
            balanced[col] = X_train.iloc[random_match_idx][col]
        elif col_name in ['kills_nonfb', 'assists_nonfb', 'deaths_nonfb']:
            balanced[col] = round(feature_stats.loc['mean', col])
        elif 'diff' in col_name:
            balanced[col] = 0  # Equal CS/XP
        else:
            balanced[col] = round(feature_stats.loc['mean', col])

    print_scenario(balanced, "1. Balanced game (all positions average performance)")

    # Scenario 2: Dominating game (high stats across all lanes)
    dominating = balanced.copy()
    for col in X_train.columns:
        if 'kills_nonfb' in col or 'assists_nonfb' in col:
            dominating[col] = feature_stats.loc['75%', col]
        elif 'deaths_nonfb' in col:
            dominating[col] = feature_stats.loc['25%', col]
        elif 'diff' in col:
            dominating[col] = abs(feature_stats.loc['75%', col])
        elif 'firstbloodkill' in col:
            dominating[col] = 1  # Got firstblood kill
        elif 'firstbloodassist' in col:
            dominating[col] = 0
        elif 'firstbloodvictim' in col:
            dominating[col] = 0

    print_scenario(dominating, "2. Dominating performance (winning all lanes)")

    # Scenario 3: Losing game (poor stats across all lanes)
    losing = balanced.copy()
    for col in X_train.columns:
        if 'kills_nonfb' in col or 'assists_nonfb' in col:
            losing[col] = feature_stats.loc['25%', col]
        elif 'deaths_nonfb' in col:
            losing[col] = feature_stats.loc['75%', col]
        elif 'diff' in col:
            losing[col] = -abs(feature_stats.loc['75%', col])
        elif 'firstbloodkill' in col:
            losing[col] = 0
        elif 'firstbloodassist' in col:
            losing[col] = 0
        elif 'firstbloodvictim' in col:
            losing[col] = 1  # Died to firstblood

    print_scenario(losing, "3. Poor performance (losing all lanes)")

    # Scenario 4: Mixed game (some lanes winning, some losing)
    mixed = balanced.copy()
    positions_ahead = ['top', 'mid']
    positions_behind = ['jng', 'bot', 'sup']

    for col in X_train.columns:
        for pos in positions_ahead:
            if col.startswith(f'{pos}_'):
                if 'kills_nonfb' in col or 'assists_nonfb' in col:
                    mixed[col] = feature_stats.loc['75%', col]
                elif 'deaths_nonfb' in col:
                    mixed[col] = feature_stats.loc['25%', col]
                elif 'diff' in col:
                    mixed[col] = abs(feature_stats.loc['75%', col])
                elif 'firstbloodkill' in col:
                    mixed[col] = 1 if pos == 'top' else 0  # Top got firstblood

        for pos in positions_behind:
            if col.startswith(f'{pos}_'):
                if 'kills_nonfb' in col or 'assists_nonfb' in col:
                    mixed[col] = feature_stats.loc['25%', col]
                elif 'deaths_nonfb' in col:
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

        print_scenario(random_scenario, f"5.{i+1}. Random scenario #{i+1} (sampled from training data)")

    return {
        'position_models': position_models,
        'position_scalers': position_scalers,
        'meta_model': meta_model,
        'feature_stats': feature_stats,
        'cfg': cfg,
    }


if __name__ == "__main__":
    train_ensemble_model()
