from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

from .io_oracle import load_oracle_years

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)


@dataclass
class TeamRegressionConfig:
    """Config for team-level win-probability regression."""

    years: Iterable[int] = (2024,)  # Single year for testing
    # Roles as they appear in the "position" column
    roles: Sequence[str] = ("top", "jng", "mid", "bot", "sup")
    # Stats to ignore (substrings to match in column names)
    ignored_stats: Sequence[str] = ("goldspent", "opp_inhibitors", "inhibitors", "earned gpm", "earnedgold", "participantid", "totalgold")
    # Stats to convert to "above expected" based on game outcome and length
    above_expected_stats: Sequence[str] = ("kills", "deaths", "assists", "damagetotowers")
    game_length_bucket_minutes: int = 5  # Bucket size for game length grouping
    z_eps: float = 1e-9
    C: float = 1.0          # inverse regularization strength
    max_iter: int = 500     # logistic regression iterations


def _detect_schema(df: pd.DataFrame) -> Dict[str, str]:
    """
    Map to canonical names based on your exact column set.
    Raises if something important is missing.
    """
    cols = set(df.columns)

    required = {
        "gameid",
        "side",
        "position",
        "playername",
        "teamname",
        "result",
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
    }


def _normalize_result(series: pd.Series) -> pd.Series:
    """
    Ensure result is {0,1} integer.
    Your Oracle 'result' column is already numeric, but this is
    robust to e.g. '0'/'1' as strings.
    """
    s = pd.to_numeric(series, errors="coerce")
    if s.isna().any():
        raise ValueError(f"Non-numeric values found in result column: {series.unique()}")
    # Some Oracle dumps use 1 for win, 0 for loss already; just ensure int type.
    s = s.astype(int)
    # Optional sanity check: only 0/1 allowed
    bad = set(s.unique()) - {0, 1}
    if bad:
        raise ValueError(f"Unexpected result values (expected 0/1): {bad}")
    return s



def _compute_above_expected(
    df: pd.DataFrame,
    stats: Sequence[str],
    pos_col: str,
    result_col: str,
    bucket_minutes: int = 5,  # Unused now, kept for backwards compatibility
) -> pd.DataFrame:
    """
    Convert raw stats to "above expected" based on position, result, game length, and team totals.

    For each stat:
    1. Computes player's percentage of team total
    2. Fits regression: player_pct ~ gamelength (per position/result)
    3. Computes expected_stat = expected_pct * team_total

    Returns dataframe with new "{stat}_above_expected" columns and original columns removed.
    """
    df = df.copy()

    # Find game length column
    gamelength_col = "gamelength"

    # Convert to minutes if needed
    df["_gamelength_min"] = df[gamelength_col] / 60.0

    # Find game and side columns for grouping
    game_col = "gameid"
    side_col = "side"

    def fit_best_model(X, y):
        """Try multiple models and return the best one with its predictions and formula."""
        X_mean = X.mean()
        y_mean = y.mean()

        models = []

        # 1. Linear: y = a + bx
        numerator = ((X - X_mean) * (y - y_mean)).sum()
        denominator = ((X - X_mean) ** 2).sum()
        if denominator > 0:
            slope = numerator / denominator
            intercept = y_mean - slope * X_mean
            y_pred = intercept + slope * X
            ss_total = ((y - y_mean) ** 2).sum()
            ss_residual = ((y - y_pred) ** 2).sum()
            r2 = 1 - (ss_residual / ss_total) if ss_total > 0 else 0
            formula = f"y = {intercept:.3f} + {slope:.4f}x"
            models.append(('linear', y_pred, r2, formula))

        # 2. Logarithmic: y = a + b*ln(x)
        if (X > 0).all():
            X_log = np.log(X)
            X_log_mean = X_log.mean()
            numerator = ((X_log - X_log_mean) * (y - y_mean)).sum()
            denominator = ((X_log - X_log_mean) ** 2).sum()
            if denominator > 0:
                b = numerator / denominator
                a = y_mean - b * X_log_mean
                y_pred = a + b * X_log
                ss_total = ((y - y_mean) ** 2).sum()
                ss_residual = ((y - y_pred) ** 2).sum()
                r2 = 1 - (ss_residual / ss_total) if ss_total > 0 else 0
                formula = f"y = {a:.3f} + {b:.4f}*ln(x)"
                models.append(('log', y_pred, r2, formula))

        # 3. Polynomial (quadratic): y = a + bx + cx²
        X_sq = X ** 2
        # Use normal equations for multiple regression
        n = len(X)
        sum_x = X.sum()
        sum_x2 = X_sq.sum()
        sum_x3 = (X ** 3).sum()
        sum_x4 = (X ** 4).sum()
        sum_y = y.sum()
        sum_xy = (X * y).sum()
        sum_x2y = (X_sq * y).sum()

        # Build matrix equation: [X'X]β = X'y
        try:
            A = np.array([
                [n, sum_x, sum_x2],
                [sum_x, sum_x2, sum_x3],
                [sum_x2, sum_x3, sum_x4]
            ])
            b_vec = np.array([sum_y, sum_xy, sum_x2y])
            coeffs = np.linalg.solve(A, b_vec)
            a, b, c = coeffs
            y_pred = a + b * X + c * X_sq
            ss_total = ((y - y_mean) ** 2).sum()
            ss_residual = ((y - y_pred) ** 2).sum()
            r2 = 1 - (ss_residual / ss_total) if ss_total > 0 else 0
            formula = f"y = {a:.3f} + {b:.4f}x + {c:.6f}x²"
            models.append(('poly', y_pred, r2, formula))
        except np.linalg.LinAlgError:
            pass  # Singular matrix, skip this model

        # 4. Exponential: y = a*e^(bx)
        # Convert to linear: ln(y) = ln(a) + bx
        if (y > 0).all():
            y_log = np.log(y)
            y_log_mean = y_log.mean()
            numerator = ((X - X_mean) * (y_log - y_log_mean)).sum()
            denominator = ((X - X_mean) ** 2).sum()
            if denominator > 0:
                b = numerator / denominator
                ln_a = y_log_mean - b * X_mean
                a = np.exp(ln_a)
                y_pred = a * np.exp(b * X)
                ss_total = ((y - y_mean) ** 2).sum()
                ss_residual = ((y - y_pred) ** 2).sum()
                r2 = 1 - (ss_residual / ss_total) if ss_total > 0 else 0
                formula = f"y = {a:.3f}*e^({b:.6f}x)"
                models.append(('exp', y_pred, r2, formula))

        # Return the best model by R²
        if models:
            best = max(models, key=lambda m: m[2])
            return best[0], best[1], best[2], best[3]
        else:
            return 'mean', np.full(len(X), y_mean), 0, f"y = {y_mean:.3f}"

    logging.info(f"Computing above-expected values for {len(stats)} stats using best-fit regression")
    logging.info(f"(Conditioning on team totals and game length)")

    # For each stat, compute expected values using regression
    for stat in stats:
        if stat not in df.columns:
            logging.warning(f"Stat '{stat}' not found in dataframe, skipping")
            continue

        # Compute game totals (both teams) for this stat
        game_total_col = f"_game_total_{stat}"
        df[game_total_col] = df.groupby(game_col)[stat].transform("sum")

        # Compute player's percentage of game total
        pct_col = f"_pct_{stat}"
        # Avoid division by zero
        df[pct_col] = np.where(
            df[game_total_col] > 0,
            df[stat] / df[game_total_col],
            0
        )

        logging.info(f"\n  Regression results for {stat} (modeling % of game total across both teams):")
        logging.info(f"    {'Position':<8} {'N':<10} {'Model':<8} {'R²':<8} {'Formula (y = player % of game total, x = game length)'}")
        logging.info(f"    {'-'*8} {'-'*10} {'-'*8} {'-'*8} {'-'*50}")

        # Store predictions for each group
        predictions = {}

        # For each position, fit the best regression model on percentages
        # (game totals capture overall game pace/style without penalizing for strong teammates)
        for pos, group in df.groupby(pos_col):
            X = group["_gamelength_min"].values
            y = group[pct_col].values
            n = len(X)

            # Need at least 3 points to fit models
            if n < 3:
                pct_pred = np.full(n, y.mean())
                # Convert back to absolute values
                stat_pred = pct_pred * group[game_total_col].values
                predictions[pos] = pd.Series(stat_pred, index=group.index)
                logging.info(f"    {pos:<8} {n:<10} {'mean':<8} {'N/A':<8} y = {y.mean():.3f}")
                continue

            # Fit best model on percentages
            model_type, pct_pred, r2, formula = fit_best_model(X, y)

            # Convert predictions back to absolute values using game totals
            stat_pred = pct_pred * group[game_total_col].values
            predictions[pos] = pd.Series(stat_pred, index=group.index)

            logging.info(f"    {pos:<8} {n:<10} {model_type:<8} {r2:<8.3f} {formula}")

        # Combine all predictions
        expected = pd.concat([pred for pred in predictions.values()])
        expected = expected.sort_index()

        # Create new column with above-expected value
        new_col = f"{stat}_above_expected"
        df[new_col] = df[stat] - expected

        # Drop original and temp columns
        df = df.drop(columns=[stat, game_total_col, pct_col])

        logging.info(f"  ✓ Created {new_col} (removed {stat})")

    # Clean up temporary columns
    df = df.drop(columns=["_gamelength_min"])

    return df


def _filter_player_rows(df: pd.DataFrame, pos_col: str) -> pd.DataFrame:
    """
    Drop aggregated 'team' rows etc.
    In Oracle data, team rows usually have position == 'team'.
    """
    out = df.copy()
    out[pos_col] = out[pos_col].astype(str)
    mask_player = ~out[pos_col].str.lower().eq("team")
    filtered = out[mask_player]
    logging.info(f"Filtered to {len(filtered):,} player rows (from {len(df):,} total)")
    return filtered


def _get_numeric_stat_cols(
    df: pd.DataFrame,
    result_col: str,
    game_col: str,
    side_col: str,
    ignored_stats: Sequence[str] = (),
) -> List[str]:
    """
    Use all numeric columns as candidate stats, except the label (result),
    and drop columns that are constant within (gameid, side) for every team.

    That filters out team-level constants like teamkills, teamdeaths, gamelength, etc.
    """
    # All numeric columns
    numeric_cols = df.select_dtypes(include=["number"]).columns.tolist()
    if result_col in numeric_cols:
        numeric_cols.remove(result_col)

    logging.info(f"Found {len(numeric_cols)} numeric columns to evaluate")

    # Filter out ignored stats first
    if ignored_stats:
        filtered_cols = []
        ignored_count = 0
        for col in numeric_cols:
            col_lower = col.lower()
            if any(ignored in col_lower for ignored in ignored_stats):
                ignored_count += 1
                continue
            filtered_cols.append(col)
        numeric_cols = filtered_cols
        if ignored_count > 0:
            logging.info(f"Filtered out {ignored_count} ignored stat columns")

    useful_cols: List[str] = []

    # Group once to avoid re-grouping inside the loop
    grouped = df.groupby([game_col, side_col])

    for col in numeric_cols:
        # For each (game, side), how many distinct values does this col have across players?
        nunique_per_team = grouped[col].nunique(dropna=False)
        # If it's 1 for every team, it's constant within team (gamelen, teamkills, etc.)
        if nunique_per_team.max() <= 1:
            continue
        useful_cols.append(col)

    logging.info(f"Kept {len(useful_cols)} player-level stat columns (filtered {len(numeric_cols) - len(useful_cols)} team-level constants)")
    return useful_cols



def build_team_matrix(
    df: pd.DataFrame,
    cfg: Optional[TeamRegressionConfig] = None,
) -> Tuple[pd.DataFrame, pd.Series, List[str]]:
    """
    Build X and y for team-level logistic regression.

    Two rows per game (one for each team):
        X = team stats over role-split features
        y = 1 if team won, 0 if team lost
    Includes a 'side' feature (1 for blue, 0 for red) to capture side advantage.
    """
    if cfg is None:
        cfg = TeamRegressionConfig()

    logging.info("Building team matrix...")
    logging.info(f"Input data: {len(df):,} rows, {len(df.columns)} columns")

    # Show leagues in dataset if available
    if "league" in df.columns:
        leagues = sorted(df["league"].unique())
        logging.info(f"Leagues in dataset ({len(leagues)}): {', '.join(leagues)}")

    schema = _detect_schema(df)
    player_col = schema["player"]
    game_col = schema["game"]
    team_col = schema["team"]
    side_col = schema["side"]
    pos_col = schema["pos"]
    result_col = schema["result"]

    # Only player rows (no 'team' aggregates)
    df = _filter_player_rows(df, pos_col)

    # If datacompleteness exists, keep only complete rows
    if "datacompleteness" in df.columns:
        before = len(df)
        df = df[df["datacompleteness"] == "complete"]
        logging.info(f"Filtered to complete data: {len(df):,} rows (removed {before - len(df):,})")

    # Normalize result to 0/1
    df[result_col] = _normalize_result(df[result_col])

    # Standardize position values; keep only defined roles
    df[pos_col] = df[pos_col].astype(str).str.lower()
    before = len(df)
    df = df[df[pos_col].isin(cfg.roles)]
    logging.info(f"Kept only defined roles {cfg.roles}: {len(df):,} rows (removed {before - len(df):,})")

    # Compute efficiency metrics
    logging.info("Computing efficiency metrics...")
    if "damagetochampions" in df.columns and "earnedgoldshare" in df.columns:
        # Avoid division by zero
        df["dmg_per_gold_share"] = np.where(
            df["earnedgoldshare"] > 0,
            df["damagetochampions"] / df["earnedgoldshare"],
            0
        )
        logging.info("  Created dmg_per_gold (damagetochampions / earnedgoldshare)")

    if "damagetotowers" in df.columns and "earnedgoldshare" in df.columns:
        df["tower_dmg_per_gold_share"] = np.where(
            df["earnedgoldshare"] > 0,
            df["damagetotowers"] / df["earnedgoldshare"],
            0
        )
        logging.info("  Created tower_dmg_per_gold (damagetotowers / earnedgoldshare)")

    # Compute above-expected values for player evaluation (saved separately, not used in model)
    if cfg.above_expected_stats:
        logging.info("\nComputing above-expected metrics for player evaluation...")
        df_player_eval = _compute_above_expected(
            df,  # This function already makes a copy internally
            cfg.above_expected_stats,
            pos_col,
            result_col,
            cfg.game_length_bucket_minutes,
        )
        # Save to CSV for later analysis
        output_path = "player_above_expected_metrics.csv"
        df_player_eval.to_csv(output_path, index=False)
        logging.info(f"Saved player evaluation metrics to {output_path}")

    # All numeric columns except the label (using raw stats for team model)
    stat_cols = _get_numeric_stat_cols(df, result_col, game_col, side_col, cfg.ignored_stats)
    if not stat_cols:
        raise ValueError("No numeric stat columns found to use as features.")

    # Pivot: index = (gameid, side), columns = (stat, position), values = mean stat for that role
    logging.info(f"Pivoting data by role for {len(stat_cols)} stats...")
    pivot = df.pivot_table(
        index=[game_col, side_col],
        columns=pos_col,
        values=stat_cols,
        aggfunc="mean",
    )
    logging.info(f"Pivot complete: {len(pivot)} team-games")

    # Flatten MultiIndex columns: (stat, role) -> f"{role}_{stat}"
    pivot.columns = [f"{role}_{stat}" for stat, role in pivot.columns.to_flat_index()]
    pivot = pivot.reset_index()

    # Add team result per (game, side)
    res = (
        df.groupby([game_col, side_col])[result_col]
        .first()
        .rename("result_team")
        .reset_index()
    )
    pivot = pivot.merge(res, on=[game_col, side_col], how="left")

    # Split blue/red teams
    logging.info("Splitting into blue/red teams...")
    side_lower = pivot[side_col].astype(str).str.lower()
    blue = pivot[side_lower == "blue"].copy()
    red = pivot[side_lower == "red"].copy()

    # Ensure only games where both sides present
    blue = blue.set_index(game_col)
    red = red.set_index(game_col)

    common_games = blue.index.intersection(red.index)
    blue = blue.loc[common_games]
    red = red.loc[common_games]
    logging.info(f"Found {len(common_games):,} complete games with both blue and red teams")

    # Feature columns: all role_stat columns (e.g. 'top_csdiffat10', 'jng_damagetochampions', etc.)
    feature_cols = [c for c in blue.columns if any(c.startswith(f"{r}_") for r in cfg.roles)]
    feature_cols = sorted(set(feature_cols).intersection(red.columns))

    if not feature_cols:
        raise ValueError("No overlapping feature columns between blue and red after pivot.")

    X_blue = blue[feature_cols].astype(float)
    X_red = red[feature_cols].astype(float)

    # Get targets for both teams
    y_blue = _normalize_result(blue["result_team"])
    y_red = _normalize_result(red["result_team"])

    # Add side feature (1 for blue, 0 for red)
    logging.info(f"Creating separate rows for each team with {len(feature_cols)} features...")
    X_blue['side_blue'] = 1
    X_red['side_blue'] = 0

    # Stack blue and red teams
    X = pd.concat([X_blue, X_red], axis=0, ignore_index=True)
    y = pd.concat([y_blue, y_red], axis=0, ignore_index=True)

    # Update feature list to include side
    feature_cols = feature_cols + ['side_blue']

    logging.info(f"Stacked dataset: {len(X):,} team-games (from {len(common_games):,} games)")

    # Handle missing values intelligently
    # 1. First, drop columns that are mostly NaN (>80% missing)
    nan_pct = X.isna().mean()
    cols_to_keep = nan_pct[nan_pct < 0.8].index.tolist()
    n_dropped_cols = len(feature_cols) - len(cols_to_keep)

    if n_dropped_cols > 0:
        logging.info(f"Dropping {n_dropped_cols} features with >80% missing values")
        X = X[cols_to_keep]
        feature_cols = cols_to_keep

    # 2. For remaining NaNs, fill with 0
    n_nans = X.isna().sum().sum()
    if n_nans > 0:
        logging.info(f"Filling {n_nans:,} remaining NaN values with 0")
        X = X.fillna(0.0)

    # 3. Drop any rows that still have NaNs (should be none now)
    before = len(X)
    mask_valid = X.notna().all(axis=1)
    X = X[mask_valid]
    y = y[mask_valid]

    logging.info(f"Final dataset: {len(X):,} team-games × {len(feature_cols)} features")
    if len(y) > 0:
        logging.info(f"Target distribution: {y.sum():,} wins ({100*y.mean():.1f}%), {len(y) - y.sum():,} losses")
    else:
        logging.error("No valid samples remaining after filtering!")

    return X, y, feature_cols


def zscore_features(
    X: pd.DataFrame,
    eps: float = 1e-9,
) -> Tuple[pd.DataFrame, pd.Series, pd.Series]:
    """
    Z-score features across all games: (X - mu) / sigma.
    """
    logging.info("Standardizing features (z-score normalization)...")
    mu = X.mean(axis=0)
    sd = X.std(axis=0, ddof=0)

    sd_safe = sd.copy()
    sd_safe[(sd_safe < eps) | sd_safe.isna()] = 1.0

    X_z = (X - mu) / sd_safe

    return X_z, mu, sd_safe


@dataclass
class TeamWinModel:
    model: LogisticRegression
    feature_names: List[str]
    mean_: pd.Series
    std_: pd.Series

    def coef_frame(self) -> pd.DataFrame:
        """Return coefficients as a sorted DataFrame."""
        coefs = self.model.coef_[0]
        df = pd.DataFrame(
            {
                "feature": self.feature_names,
                "coef": coefs,
                "abs_coef": np.abs(coefs),
            }
        ).sort_values("abs_coef", ascending=False)
        return df


def fit_team_win_model(cfg: Optional[TeamRegressionConfig] = None) -> TeamWinModel:
    """
    Load Oracle data, build Blue-Red diff matrix, and fit logistic regression.
    """
    if cfg is None:
        cfg = TeamRegressionConfig()

    # Load all years specified
    logging.info(f"Loading Oracle data for years: {list(cfg.years)}")
    df = load_oracle_years(cfg.years)
    logging.info(f"Loaded {len(df):,} total rows from {len(list(cfg.years))} years")

    X, y, feature_cols = build_team_matrix(df, cfg)
    X_z, mu, sd = zscore_features(X, eps=cfg.z_eps)

    # Convert to numpy arrays for sklearn
    X_train = X_z.values
    y_train = y.values.ravel()

    # Validate data before fitting
    logging.info(f"Data validation: X shape={X_train.shape}, y shape={y_train.shape}")
    if np.isnan(X_train).any():
        logging.warning(f"Found {np.isnan(X_train).sum()} NaN values in X_train")
    if np.isinf(X_train).any():
        logging.warning(f"Found {np.isinf(X_train).sum()} infinite values in X_train")
    if np.isnan(y_train).any():
        logging.warning(f"Found {np.isnan(y_train).sum()} NaN values in y_train")

    # Fit logistic regression
    logging.info(f"Fitting logistic regression (C={cfg.C}, max_iter={cfg.max_iter})...")
    lr = LogisticRegression(
        penalty="l2",
        C=cfg.C,
        max_iter=cfg.max_iter,
        solver="lbfgs",
    )
    lr.fit(X_train, y_train)

    train_acc = lr.score(X_train, y_train)
    logging.info(f"Model fitted successfully! Training accuracy: {100*train_acc:.2f}%")

    return TeamWinModel(
        model=lr,
        feature_names=feature_cols,
        mean_=mu,
        std_=sd,
    )


if __name__ == "__main__":
    logging.info("=" * 60)
    logging.info("Team Win Probability Regression")
    logging.info("=" * 60)

    cfg = TeamRegressionConfig()
    model = fit_team_win_model(cfg)
    coef_df = model.coef_frame()

    # Show overall top 30 features
    logging.info("\n" + "=" * 60)
    logging.info("Top 30 Features Overall by Absolute Coefficient")
    logging.info("=" * 60)
    print("\n" + coef_df.head(30).to_string(index=False))

    # TODO: convert metrics to efficiency (e.g. Dmg per gold, etc.) to mitigate the effect of just being on the winning team
    # compute "expected" numbers (e.g. expected dmg, towers, gold, etc.), given a win/loss of certain length, how much would an average player in that role have done

    # Show top 100 features for each role
    for role in cfg.roles:
        role_features = coef_df[coef_df['feature'].str.startswith(f"{role}_")]
        if len(role_features) > 0:
            print("\n" + "=" * 60)
            print(f"Top 100 Features for {role.upper()}")
            print("=" * 60)
            print(role_features.head(100).to_string(index=False))
        else:
            print(f"\nNo features found for role: {role}")
