"""
Reduced (KDA + CS) scoring model for Leaguepedia-sourced years.

Pre-2015 Oracle box scores don't exist for the East (and not at all pre-2014), so for those
gap years we score from Leaguepedia's ScoreboardPlayers (lp_ingest.py), which reliably has
only kills/deaths/assists/CS. This module is the reduced analogue of the Oracle pipeline
(win_probability + contribution + season._match_features), producing the SAME per-(player,
match) frame that season.build_player_ratings / export_excel.build_export_frame consume --
so the aggregation and workbook code run unchanged.

Differences from the full model:
  - features are per-position kills/deaths/assists/CS (no damage, no first blood, no @15);
  - expected reference is the global mean (no Model 1 conditional expectation);
  - CS occupies the "c_damage" source slot and c_fb is 0 (so the schema matches);
  - no reg/playoff flag in the source, so domestic games are all "regular".

Only the leagues Oracle DOESN'T cover that year are scored here (see GAP_LEAGUES), so nothing
is double-counted when both feed the career aggregation.
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

from .contribution import ROLES
from .lp_ingest import load_year
from .scoring import REFERENCE_ELO, ScoreWeights, load_league_elos
from .season import _REPLACEMENT_QUANTILE, _SOURCES
from .team_leagues import build_team_game_table, resolve_home_leagues

logger = logging.getLogger(__name__)

_RSTATS = ("kills", "deaths", "assists", "cs")  # reduced feature set

# Leaguepedia leagues to score per year -- only the gaps Oracle lacks, so no double-count
# when both sources feed the career aggregation. None => use everything present that year.
GAP_LEAGUES: dict[int, Optional[list[str]]] = {
    2013: None,                    # Oracle has no 2013 data: score all of it
    2014: ["OGN", "LPL"],          # Oracle covers NA/EU + Worlds; LP fills East domestic
    2015: ["LPL"],                 # Oracle covers all but LPL domestic
}


def _sigmoid(z):
    return 1.0 / (1.0 + np.exp(-z))


def _team_features(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """One row per (gameid, side): per-position KDA+CS features + result."""
    d = df[df["position"].isin(ROLES)].copy()
    wide = d.pivot_table(index=["gameid", "side"], columns="position",
                         values=list(_RSTATS), aggfunc="first")
    wide.columns = [f"{pos}_{stat}" for (stat, pos) in wide.columns]
    feature_cols = [f"{pos}_{stat}" for pos in ROLES for stat in _RSTATS]
    wide = wide.reindex(columns=feature_cols)
    res = d.groupby(["gameid", "side"])["result"].first()
    wide = wide.join(res).reset_index().dropna(subset=feature_cols)
    return wide, feature_cols


def build_match_scores(year: int, weights: Optional[ScoreWeights] = None,
                       home_leagues: Optional[dict] = None) -> pd.DataFrame:
    """Per-(player, match) scored frame for a Leaguepedia gap year, matching the schema of
    season.build_player_match_scores (so build_player_ratings can consume it). home_leagues
    overrides the per-team home-league map (default: resolve from this year's LP data)."""
    weights = weights or ScoreWeights()
    df = load_year(year)
    leagues = GAP_LEAGUES.get(year)
    if leagues is not None:
        df = df[df["league"].isin(leagues)].copy()
    if df.empty:
        raise RuntimeError(f"no Leaguepedia rows for {year} after GAP_LEAGUES filter")

    team_df, feature_cols = _team_features(df)

    # Model 2: no-intercept logistic on standardized team features.
    X = team_df[feature_cols].astype(float).values
    y = team_df["result"].astype(int).values
    scaler = StandardScaler()
    Xs = scaler.fit_transform(X)
    model = LogisticRegression(C=1.0, max_iter=1000, fit_intercept=False, random_state=42)
    model.fit(Xs, y)
    coef = model.coef_[0]
    mu, sigma = scaler.mean_, scaler.scale_

    # Reference each feature against a REPLACEMENT level (a global per-position-stat quantile;
    # low for higher-is-better stats, high (1-q) for deaths) instead of the mean, so nearly
    # every performance is above it and contribution accumulates (WAR-style). q=None -> mean.
    if _REPLACEMENT_QUANTILE is None:
        Es = np.zeros(len(feature_cols))
    else:
        q = _REPLACEMENT_QUANTILE
        r = np.array([np.quantile(X[:, i], 1 - q if feature_cols[i].endswith("_deaths") else q)
                      for i in range(len(feature_cols))])
        Es = (r - mu) / sigma                # replacement level in standardized space
    # Per-feature log-odds deviation from replacement; per-lane leave-one-out contribution.
    Dz = coef[None, :] * (Xs - Es[None, :])
    z = Xs @ coef
    p = _sigmoid(z)
    idx_of = {f: i for i, f in enumerate(feature_cols)}

    long_parts = []
    for role in ROLES:
        rcols = [f"{role}_{s}" for s in _RSTATS]
        idx = [idx_of[c] for c in rcols]
        dz_role = Dz[:, idx].sum(axis=1)
        net = p - _sigmoid(z - dz_role)
        dz_sum = dz_role
        frac = np.where(np.abs(dz_sum)[:, None] > 1e-9, Dz[:, idx] / dz_sum[:, None], 0.25)
        split = net[:, None] * frac
        sub = pd.DataFrame({
            "gameid": team_df["gameid"].values, "side": team_df["side"].values,
            "result": team_df["result"].astype(int).values, "p_model": p,
            "position": role, "net_contribution": net,
            "c_kills": split[:, 0], "c_deaths": split[:, 1],
            "c_assists": split[:, 2], "c_damage": split[:, 3],  # CS in the damage slot
        })
        sub["c_fb"] = 0.0
        long_parts.append(sub)
    long = pd.concat(long_parts, ignore_index=True)

    # Attach player identity.
    ids = df[["gameid", "side", "position", "playername", "teamname"]].drop_duplicates(
        ["gameid", "side", "position"])
    long = long.merge(ids, on=["gameid", "side", "position"], how="left")

    # Opponent / league labelling + baseline (opponent-league Elo), like season._match_features.
    home = home_leagues if home_leagues is not None else resolve_home_leagues(
        df, preferred=set(load_league_elos(year)))
    tg = build_team_game_table(df, home)
    tg_cols = ["gameid", "side", "opp_teamname", "own_league", "opp_league",
               "is_international", "game_label"]
    long = long.merge(tg[tg_cols], on=["gameid", "side"], how="left")
    long["date"] = long["gameid"].map(df.groupby("gameid")["date"].first())
    long["game"] = np.nan  # in-series game number unknown from ScoreboardPlayers

    elos = load_league_elos(year)
    peak = max(elos.values()) if elos else REFERENCE_ELO   # baseline vs the year's peak region
    opp_elo = long["opp_league"].map(elos)
    long["baseline"] = 1.0 / (1.0 + 10 ** ((peak - opp_elo) / 400.0))

    # Phase: rated domestic label -> regular (no playoff flag in source); else tournament.
    rated = set(elos)
    long["phase"] = np.where(long["game_label"].isin(rated), "regular", "tournament")
    long = long.dropna(subset=["baseline", "playername"])

    # Apply weights (same arithmetic as build_player_match_scores).
    long["baseline_term"] = weights.alpha * long["baseline"]
    long["contribution_term"] = weights.lam * long["net_contribution"]
    long["win_bonus"] = weights.beta * (long["result"] - long["p_model"])
    long["score"] = long["baseline_term"] + long["contribution_term"] + long["win_bonus"]
    for s in _SOURCES:
        long[f"{s}_term"] = weights.lam * long[s]
    return long.reset_index(drop=True)
