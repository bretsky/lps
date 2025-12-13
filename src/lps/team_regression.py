from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

from .io_oracle import load_oracle_years


@dataclass
class TeamRegressionConfig:
    """Config for team-level win-probability regression."""

    years: Iterable[int] = range(2014, 2026)
    # Roles as they appear in the "position" column
    roles: Sequence[str] = ("top", "jng", "mid", "bot", "sup")
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



def _filter_player_rows(df: pd.DataFrame, pos_col: str) -> pd.DataFrame:
    """
    Drop aggregated 'team' rows etc.
    In Oracle data, team rows usually have position == 'team'.
    """
    out = df.copy()
    out[pos_col] = out[pos_col].astype(str)
    mask_player = ~out[pos_col].str.lower().eq("team")
    return out[mask_player]


def _get_numeric_stat_cols(df: pd.DataFrame, result_col: str) -> List[str]:
    """
    Use all numeric columns as candidate stats, except the label (result).
    Everything else (year, playoffs, kpm, towers, etc.) is fair game.
    Columns like year/split will end up with 0 Blue-Red diff and thus
    no learned impact.
    """
    numeric_cols = df.select_dtypes(include=["number"]).columns.tolist()
    if result_col in numeric_cols:
        numeric_cols.remove(result_col)
    return numeric_cols


def build_team_diff_matrix(
    df: pd.DataFrame,
    cfg: Optional[TeamRegressionConfig] = None,
) -> Tuple[pd.DataFrame, pd.Series, List[str]]:
    """
    Build X_diff and y for team-level logistic regression.

    One row per game:
        X_diff = (Blue team stats - Red team stats) over role-split features
        y      = 1 if Blue won, 0 if Blue lost
    """
    if cfg is None:
        cfg = TeamRegressionConfig()

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
        df = df[df["datacompleteness"] == "complete"]

    # Normalize result to 0/1
    df[result_col] = _normalize_result(df[result_col])

    # Standardize position values; keep only defined roles
    df[pos_col] = df[pos_col].astype(str).str.lower()
    df = df[df[pos_col].isin(cfg.roles)]

    # All numeric columns except the label
    stat_cols = _get_numeric_stat_cols(df, result_col)
    if not stat_cols:
        raise ValueError("No numeric stat columns found to use as features.")

    # Pivot: index = (gameid, side), columns = (stat, position), values = mean stat for that role
    pivot = df.pivot_table(
        index=[game_col, side_col],
        columns=pos_col,
        values=stat_cols,
        aggfunc="mean",
    )

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
    side_lower = pivot[side_col].astype(str).str.lower()
    blue = pivot[side_lower == "blue"].copy()
    red = pivot[side_lower == "red"].copy()

    # Ensure only games where both sides present
    blue = blue.set_index(game_col)
    red = red.set_index(game_col)

    common_games = blue.index.intersection(red.index)
    blue = blue.loc[common_games]
    red = red.loc[common_games]

    # Feature columns: all role_stat columns (e.g. 'top_csdiffat10', 'jng_damagetochampions', etc.)
    feature_cols = [c for c in blue.columns if any(c.startswith(f"{r}_") for r in cfg.roles)]
    feature_cols = sorted(set(feature_cols).intersection(red.columns))

    if not feature_cols:
        raise ValueError("No overlapping feature columns between blue and red after pivot.")

    X_blue = blue[feature_cols].astype(float)
    X_red = red[feature_cols].astype(float)

    # Feature difference: Blue - Red
    X_diff = X_blue - X_red

    # Target: Blue win?
    y = _normalize_result(blue["result_team"])

    # Drop rows with any NaNs in features
    mask_valid = X_diff.notna().all(axis=1)
    X_diff = X_diff[mask_valid]
    y = y[mask_valid]

    return X_diff, y, feature_cols


def zscore_features(
    X: pd.DataFrame,
    eps: float = 1e-9,
) -> Tuple[pd.DataFrame, pd.Series, pd.Series]:
    """
    Z-score features across all games: (X - mu) / sigma.
    """
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
    df = load_oracle_years(cfg.years)

    X_diff, y, feature_cols = build_team_diff_matrix(df, cfg)
    X_z, mu, sd = zscore_features(X_diff, eps=cfg.z_eps)

    # Fit logistic regression
    lr = LogisticRegression(
        penalty="l2",
        C=cfg.C,
        max_iter=cfg.max_iter,
        solver="lbfgs",
    )
    lr.fit(X_z, y.values.ravel())

    return TeamWinModel(
        model=lr,
        feature_names=feature_cols,
        mean_=mu,
        std_=sd,
    )


if __name__ == "__main__":
    cfg = TeamRegressionConfig()
    model = fit_team_win_model(cfg)
    coef_df = model.coef_frame()

    # Show top 30 features by absolute impact on win probability
    print(coef_df.head(30).to_string(index=False))
