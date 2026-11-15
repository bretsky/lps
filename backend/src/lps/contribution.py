"""
Per-player win-probability contribution.

Given a team-game, how much did each player's ACTUAL performance move the team's win
probability versus an EXPECTED player? This is the `net_contribution_i` term the scoring
formula needs (see scoring.py).

Mechanics. Model 2 (win_probability.py) is a logistic regression on standardized team
features with no intercept (w_j is the model's coefficient for feature j -- NOT the
scoring beta):

    z = sum_j  w_j * (x_j - mu_j) / sigma_j        p_model = sigmoid(z)

Each lane owns 4 features (kills_nonfb, deaths_nonfb, assists_nonfb, damagetochampions).
Any non-lane feature is a "team feature" (none by default: the old `teamfirstblood` flag is off,
see WinProbabilityConfig.team_firstblood). A player's contribution is the
leave-one-out (LOO) probability delta from swapping their stats to expected:

    delta_z_i        = sum_{j in lane(i)} w_j * (actual_j - expected_j) / sigma_j
    net_contribution = sigmoid(z) - sigmoid(z - delta_z_i)

i.e. "how much lower would the win prob be if this player had played at expected level".

The EXPECTED reference is pluggable (`expected` / `expected_df`):
  - None (default): the training global mean mu_j -- "vs an average player overall".
    Fast, needs only Model 2.
  - Model 1's conditional prediction (expected given champion / game state, from
    expected_stats.py) -- the more correct reference (a tank isn't penalized for low
    kills). Passed as a per-team-game `expected_df` to contributions_for_frame.

Team features (if any) are not a player's, so their LOO delta is returned as a separate
'team_fb' diagnostic term (all zeros when there are no team features). It is not credited
to any player.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

from .io_oracle import load_oracle_years
from .win_probability import WinProbabilityConfig, build_team_features

ROLES = ("top", "jng", "mid", "bot", "sup")
# csdiffat15 is intentionally excluded: the LPL has no @15 timeline data in Oracle's
# Elixir, and dropping it lets the LPL (all "partial" completeness) be scored on the
# stats it does have (KDA + damage).
LANE_STATS = ("kills_nonfb", "deaths_nonfb", "assists_nonfb", "damagetochampions")
_META_COLS = ("gameid", "side", "result")


def _sigmoid(z: float) -> float:
    return 1.0 / (1.0 + np.exp(-z))


@dataclass
class WinProbBundle:
    """Trained Model 2 plus everything needed to attribute per-player contributions."""

    model: LogisticRegression
    feature_cols: list[str]
    coef: dict[str, float]    # Model 2 logistic coefficient per feature (NOT scoring beta)
    mu: dict[str, float]      # scaler mean per feature
    sigma: dict[str, float]   # scaler scale (std) per feature
    lane_features: dict[str, list[str]]  # role -> its feature columns
    team_features: list[str]             # non-lane features (empty by default)

    def z(self, row: pd.Series, expected: Optional[dict[str, float]] = None) -> float:
        """Total log-odds for a team-game row (no intercept)."""
        exp = expected or self.mu
        return sum(
            self.coef[f] * (row[f] - exp.get(f, self.mu[f])) / self.sigma[f]
            for f in self.feature_cols
        )


def train_win_prob_bundle(cfg: Optional[WinProbabilityConfig] = None) -> WinProbBundle:
    """Train Model 2 and package it for contribution attribution."""
    if cfg is None:
        cfg = WinProbabilityConfig()

    df = load_oracle_years(cfg.years)
    team_df = build_team_features(df, cfg)

    feature_cols = [c for c in team_df.columns if c not in _META_COLS]
    X = team_df[feature_cols].astype(float)
    y = team_df["result"].astype(int)

    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    model = LogisticRegression(
        C=cfg.C, max_iter=cfg.max_iter, solver=cfg.solver,
        fit_intercept=False, random_state=cfg.random_state,
    )
    model.fit(X_scaled, y)

    coef = dict(zip(feature_cols, model.coef_[0]))
    mu = dict(zip(feature_cols, scaler.mean_))
    sigma = dict(zip(feature_cols, scaler.scale_))

    lane_features = {
        role: [f"{role}_{s}" for s in LANE_STATS if f"{role}_{s}" in feature_cols]
        for role in ROLES
    }
    lane_cols = {c for cols in lane_features.values() for c in cols}
    team_features = [c for c in feature_cols if c not in lane_cols]

    return WinProbBundle(
        model=model, feature_cols=feature_cols, coef=coef, mu=mu, sigma=sigma,
        lane_features=lane_features, team_features=team_features,
    )


def contributions_for_row(
    row: pd.Series,
    bundle: WinProbBundle,
    expected: Optional[dict[str, float]] = None,
    metric: str = "pp",
) -> dict[str, float]:
    """
    Per-player (and team-feature) net contributions for one team-game.

    Args:
        row: a team-game row (columns = bundle.feature_cols, as from build_team_features).
        bundle: trained Model 2 bundle.
        expected: optional {feature -> expected value}. Missing features fall back to the
            training mean. None => global-mean reference for every feature.
        metric: contribution scale (see contributions_for_frame). "pp" (default) =
            win-probability points sigmoid(z) - sigmoid(z - delta_z); "z" = the raw
            log-odds delta delta_z (teammate- and game-state-independent).

    Returns:
        {'p_model': ..., 'top': ..., 'jng': ..., ..., 'team_fb': ...} where each value is
        the chosen metric for that player's / the team's feature block.
    """
    exp = expected or {}
    z = bundle.z(row, expected=exp)
    p = _sigmoid(z)

    def loo(features: list[str]) -> float:
        dz = sum(
            bundle.coef[f] * (row[f] - exp.get(f, bundle.mu[f])) / bundle.sigma[f]
            for f in features
        )
        return dz if metric == "z" else p - _sigmoid(z - dz)

    out: dict[str, float] = {"p_model": p}
    for role in ROLES:
        out[role] = loo(bundle.lane_features[role])
    out["team_fb"] = loo(bundle.team_features)
    return out


def contributions_for_frame(
    team_df: pd.DataFrame,
    bundle: WinProbBundle,
    expected_df: Optional[pd.DataFrame] = None,
    metric: str = "pp",
) -> pd.DataFrame:
    """
    Vectorized per-LANE contributions (leave-one-out) for every team-game.

    A lane's contribution measures how much its actual stats beat the expected reference,
    on one of two scales (`metric`):
      - "pp" (default): WIN-PROBABILITY POINTS, sigmoid(z) - sigmoid(z - dz_lane) -- how
        much the team's win prob would drop if the lane played at expected level. Intuitive
        ("wins added") but STATE-DEPENDENT: the same dz is worth more near p=0.5 and is
        squashed near p=0/1, so it under-credits players on dominant (usually-winning) teams.
      - "z": the raw LOG-ODDS delta dz_lane itself. In this linear no-intercept model
        dz_lane = sum_j coef_j*(x_j - e_j)/sigma_j depends ONLY on the lane's own stats vs
        the reference -- teammate- and game-state-INDEPENDENT (a purer individual-skill
        measure). ~20x larger in magnitude than "pp", so downstream weights (scoring.lam)
        must be retuned when switching.

    Also emits, for pure interpretability, the per-feature log-odds deviations (dz_{feature})
    -- unchanged by `metric` -- so a lane's contribution can be split by source, and team_fb
    (the team-feature LOO on the same scale, zero without team features), as a diagnostic.

    Args:
        team_df: team-game rows (columns = bundle.feature_cols) from build_team_features.
        expected_df: optional per-row expected values, ROW-ALIGNED to team_df; missing/NaN
            cells fall back to the training mean. None => global-mean reference.
        metric: "pp" (win-prob points, default) or "z" (raw log-odds delta).

    Returns one row per team-game: gameid, side, result, p_model, one column per role
    (that lane's net_contribution on the chosen scale), team_fb, and dz_{feature} columns.
    """
    fc = bundle.feature_cols
    n = len(team_df)
    X = team_df[fc].astype(float).values
    mu = np.array([bundle.mu[f] for f in fc])
    sigma = np.array([bundle.sigma[f] for f in fc])
    coef = np.array([bundle.coef[f] for f in fc])

    # Expected matrix: default to the training mean, override per cell from expected_df.
    E = np.tile(mu, (n, 1)).astype(float)
    if expected_df is not None:
        for k, f in enumerate(fc):
            if f in expected_df.columns:
                col = expected_df[f].to_numpy(dtype=float)
                m = ~np.isnan(col)
                E[m, k] = col[m]

    Xs = (X - mu) / sigma
    Es = (E - mu) / sigma
    Dz = coef[None, :] * (Xs - Es)     # per-feature log-odds deviation from expected
    z = Xs @ coef
    p = _sigmoid(z)

    out = pd.DataFrame({
        "gameid": team_df["gameid"].values,
        "side": team_df["side"].values,
        "result": team_df["result"].astype(int).values,
        "p_model": p,
    })
    idx_of = {f: i for i, f in enumerate(fc)}
    for role in ROLES:
        idx = [idx_of[c] for c in bundle.lane_features[role]]
        dz_role = Dz[:, idx].sum(axis=1)
        # per-lane LOO on the chosen scale: raw log-odds delta ("z") or win-prob points ("pp")
        out[role] = dz_role if metric == "z" else p - _sigmoid(z - dz_role)
        for c, i in zip(bundle.lane_features[role], idx):
            out[f"dz_{c}"] = Dz[:, i]                          # per-feature share for the split
    idx_fb = [idx_of[c] for c in bundle.team_features]
    dz_fb = Dz[:, idx_fb].sum(axis=1)
    out["team_fb"] = dz_fb if metric == "z" else p - _sigmoid(z - dz_fb)   # diagnostic only
    return out


def explain_team_game(row: pd.Series, bundle: WinProbBundle) -> dict:
    """
    Decompose a team-game's Model 2 win-prob into per-feature / per-lane log-odds so you
    can see WHY p_model landed where it did.

    z = sum_j coef_j * (x_j - mu_j)/sigma_j (no intercept); p = sigmoid(z). Each feature's
    term is its push toward win (+) or loss (-). Returns per-lane sums, the team-feature
    terms, p, and z.
    """
    feat = {f: bundle.coef[f] * (row[f] - bundle.mu[f]) / bundle.sigma[f] for f in bundle.feature_cols}
    z = sum(feat.values())
    lane = {role: sum(feat[f] for f in bundle.lane_features[role]) for role in ROLES}
    team = {f: feat[f] for f in bundle.team_features}
    return {"p": _sigmoid(z), "z": z, "lane_logodds": lane, "team_logodds": team, "feat_logodds": feat}


def _demo(year: int = 2024) -> None:
    import logging

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    cfg = WinProbabilityConfig(years=(year,))
    bundle = train_win_prob_bundle(cfg)

    df = load_oracle_years(cfg.years)
    team_df = build_team_features(df, cfg).reset_index(drop=True)

    # Vectorized p_model for every team-game (global-mean reference).
    fc = bundle.feature_cols
    X = team_df[fc].astype(float).values
    mu = np.array([bundle.mu[f] for f in fc])
    sigma = np.array([bundle.sigma[f] for f in fc])
    coef = np.array([bundle.coef[f] for f in fc])
    p_all = pd.Series(_sigmoid(((X - mu) / sigma) @ coef), index=team_df.index)

    # Pick games ACROSS the win-prob spectrum -- contributions are meaningful near 0.5,
    # and vanish at the saturated extremes (an already-decided game can't be moved).
    picks = {
        "toss-up (p~0.50)": (p_all - 0.50).abs().idxmin(),
        "moderate favorite (p~0.70)": (p_all - 0.70).abs().idxmin(),
        "heavy favorite (p~0.90)": (p_all - 0.90).abs().idxmin(),
    }
    for label, idx in picks.items():
        row = team_df.loc[idx]
        c = contributions_for_row(row, bundle)
        lane_sum = sum(c[r] for r in ROLES) + c["team_fb"]
        logging.info(f"\n{label}  (gameid={row['gameid']}, side={row['side']}, result={int(row['result'])})")
        logging.info(f"  p_model = {c['p_model']:.3f}")
        logging.info("  net contribution vs an average player (probability points):")
        for role in ROLES:
            logging.info(f"    {role:<6} {c[role]*100:+6.2f}pp")
        logging.info(f"    {'team_fb':<6} {c['team_fb']*100:+6.2f}pp")
        logging.info(f"    {'sum':<6} {lane_sum*100:+6.2f}pp   (vs p_model-0.5 = {(c['p_model']-0.5)*100:+6.2f}pp)")


if __name__ == "__main__":
    _demo()
