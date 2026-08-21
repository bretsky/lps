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
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

from .contribution import ROLES
from .lp_ingest import load_year
from .scoring import REFERENCE_ELO, ScoreWeights, load_league_elos
from .season import (
    _CACHE_DIR, _INVARIANT_COLS, _REPLACEMENT_QUANTILE, _SOURCES, apply_lane_remap,
)
from .team_leagues import build_team_game_table, resolve_home_leagues

logger = logging.getLogger(__name__)

_RSTATS = ("kills", "deaths", "assists", "cs")  # reduced feature set
_KDA = ("kills", "deaths", "assists")           # KDA-only variant (earliest years, no CS)
# Contribution split slot per stat (CS rides the "c_damage" slot to match the Oracle schema).
_STAT_COL = {"kills": "c_kills", "deaths": "c_deaths", "assists": "c_assists", "cs": "c_damage"}
_ALL_STAT_COLS = ("c_kills", "c_deaths", "c_assists", "c_damage")

# Years whose reduced model is trained TOGETHER on their pooled data, so a year too small to fit
# alone (2011 = 28 games) borrows strength from its neighbour. Contributions are still emitted
# per-year (career.py breaks them out by season). Map: year -> tuple of pooled years.
MODEL_GROUPS: dict[int, tuple[int, ...]] = {2011: (2011, 2012), 2012: (2011, 2012)}

# Years scored KDA-only (CS is absent/unreliable: OGN 2012 is 100% CS-null, Worlds 2012 25%),
# so CS is dropped rather than imputed for the most important early league.
_KDA_ONLY_YEARS = frozenset({2011, 2012})


def _rstats_for(year: int) -> tuple[str, ...]:
    return _KDA if year in _KDA_ONLY_YEARS else _RSTATS


# Game-state features for the replacement-level quantile regression (mirrors the Oracle
# Model 1's FEATURE_MAP as closely as the reduced data allows: champion + game length +
# game total kills + CS share, which stands in for Oracle's gold share).
_LP_FEATURE_MAP: dict[str, list[str]] = {
    "kills":   ["cs_share", "game_total_kills", "gamelength", "champion"],
    "deaths":  ["game_total_kills", "gamelength", "champion"],
    "assists": ["cs_share", "game_total_kills", "gamelength", "champion"],
    "cs":      ["gamelength", "game_total_kills", "champion"],
}

# Leaguepedia leagues to score per year -- only the gaps Oracle lacks, so no double-count
# when both sources feed the career aggregation. None => use everything present that year.
GAP_LEAGUES: dict[int, Optional[list[str]]] = {
    2011: None,                    # pre-Oracle: score everything (Worlds only)
    2012: None,                    # pre-Oracle: score everything (Champions Korea + LANs)
    2013: None,                    # Oracle has no 2013 data: score all of it
    2014: ["OGN", "LPL"],          # Oracle covers NA/EU + Worlds; LP fills East domestic
    2015: ["LPL"],                 # Oracle covers all but LPL domestic
}


def _sigmoid(z):
    return 1.0 / (1.0 + np.exp(-z))


def _add_context(df: pd.DataFrame) -> pd.DataFrame:
    """Add the game-state context features the replacement regression consumes."""
    d = df.copy()
    d["game_total_kills"] = d.groupby("gameid")["kills"].transform("sum")
    team_cs = d.groupby(["gameid", "side"])["cs"].transform("sum")
    d["cs_share"] = d["cs"] / team_cs.where(team_cs > 0, np.nan)
    return d


def _replacement_reference(df: pd.DataFrame, q: float,
                           rstats: tuple[str, ...] = _RSTATS) -> pd.DataFrame:
    """Per (gameid, side, position) CHAMPION-CONDITIONAL replacement level for each reduced
    stat, via quantile regression (like the Oracle Model 1): predict the q-th quantile (1-q
    for deaths) of the stat from champion + game length + game total kills + CS share. Falls
    back to the per-position empirical quantile where a position/stat has too little data."""
    d = _add_context(df[df["position"].isin(ROLES)].copy())
    out = d[["gameid", "side", "position"]].copy()
    for stat in rstats:
        qeff = 1.0 - q if stat == "deaths" else q
        pred = pd.Series(np.nan, index=d.index, dtype=float)
        for pos in ROLES:
            pdf = d[d["position"] == pos]
            if pdf.empty:
                continue
            feats = [f for f in _LP_FEATURE_MAP[stat] if f in pdf.columns]
            cat = [c for c in ("champion",) if c in feats]
            X = pd.get_dummies(pdf[feats], columns=cat)
            y = pdf[stat]
            valid = X.notna().all(axis=1) & y.notna()
            fallback = y[y.notna()].quantile(qeff) if y.notna().any() else 0.0
            if valid.sum() < 50:
                pred.loc[pdf.index] = fallback
                continue
            mdl = HistGradientBoostingRegressor(
                loss="quantile", quantile=qeff, max_iter=150, learning_rate=0.06,
                max_depth=8, min_samples_leaf=20, early_stopping=True,
                validation_fraction=0.1, random_state=42)
            mdl.fit(X[valid], y[valid])
            pred.loc[pdf.index[valid]] = mdl.predict(X[valid])
            pred.loc[pdf.index[~valid]] = fallback     # rows with missing context
        out[stat] = pred.values
    return out


def _team_features(df: pd.DataFrame,
                   rstats: tuple[str, ...] = _RSTATS) -> tuple[pd.DataFrame, list[str]]:
    """One row per (gameid, side): per-position KDA(+CS) features + result."""
    d = df[df["position"].isin(ROLES)].copy()
    wide = d.pivot_table(index=["gameid", "side"], columns="position",
                         values=list(rstats), aggfunc="first")
    wide.columns = [f"{pos}_{stat}" for (stat, pos) in wide.columns]
    feature_cols = [f"{pos}_{stat}" for pos in ROLES for stat in rstats]
    wide = wide.reindex(columns=feature_cols)
    res = d.groupby(["gameid", "side"])["result"].first()
    wide = wide.join(res).reset_index().dropna(subset=feature_cols)
    return wide, feature_cols


def _load_filtered(year: int) -> pd.DataFrame:
    """Load a year's ingested scoreboards, restricted to its GAP_LEAGUES (None => all)."""
    df = load_year(year)
    leagues = GAP_LEAGUES.get(year)
    if leagues is not None:
        df = df[df["league"].isin(leagues)].copy()
    return df


def _resolve_home(df: pd.DataFrame, year: int, home_leagues: Optional[dict]) -> dict:
    """Home league per team. A caller-supplied map wins; otherwise resolve from the data and
    BACK-FILL from the authoritative team->region map (info/team_regions_<year>.csv). The
    back-fill is essential for the earliest years, whose Elos are region-keyed and whose games
    are all international events (2011 is Worlds-only), so the event label yields no region."""
    if home_leagues is not None:
        return home_leagues
    from .team_regions import load_team_regions
    rated = set(load_league_elos(year))
    home = resolve_home_leagues(df, preferred=rated)
    tr = {str(t).lower(): r for t, r in load_team_regions(year).items()}
    for team in df["teamname"].dropna().unique():
        if home.get(team) not in rated:
            region = tr.get(str(team).lower())
            if region in rated:
                home[team] = region
    return home


def _contributions(train_df: pd.DataFrame, rstats: tuple[str, ...]) -> pd.DataFrame:
    """Fit the reduced Model 2 on train_df and return per-(gameid, side, position) leave-one-out
    net contribution + per-stat split. Identity and league labelling are added by the caller
    (per-year), so a pooled train_df (e.g. 2011+2012) can drive several years' outputs."""
    team_df, feature_cols = _team_features(train_df, rstats)

    # Model 2: no-intercept logistic on standardized team features.
    X = team_df[feature_cols].astype(float).values
    y = team_df["result"].astype(int).values
    scaler = StandardScaler()
    Xs = scaler.fit_transform(X)
    model = LogisticRegression(C=1.0, max_iter=1000, fit_intercept=False, random_state=42)
    model.fit(Xs, y)
    coef = model.coef_[0]
    mu, sigma = scaler.mean_, scaler.scale_

    # Reference each feature against a CHAMPION-CONDITIONAL REPLACEMENT level (per-(position,
    # champion) quantile; low for higher-is-better stats, high (1-q) for deaths) instead of the
    # mean, so nearly every performance is above it and contribution accumulates (WAR-style),
    # while a champion's role (e.g. a tank's low kills) isn't penalized. q=None -> mean.
    if _REPLACEMENT_QUANTILE is None:
        Es = np.zeros((len(team_df), len(feature_cols)))
    else:
        rep = _replacement_reference(train_df, _REPLACEMENT_QUANTILE, rstats)
        piv = rep.pivot_table(index=["gameid", "side"], columns="position", values=list(rstats))
        piv.columns = [f"{pos}_{stat}" for (stat, pos) in piv.columns]
        piv = piv.reindex(columns=feature_cols).reset_index()
        E = team_df[["gameid", "side"]].merge(piv, on=["gameid", "side"], how="left")[feature_cols]
        Es = np.nan_to_num((E.to_numpy(dtype=float) - mu[None, :]) / sigma[None, :], nan=0.0)
    # Per-feature log-odds deviation from replacement; per-lane leave-one-out contribution.
    Dz = coef[None, :] * (Xs - Es)
    z = Xs @ coef
    p = _sigmoid(z)
    idx_of = {f: i for i, f in enumerate(feature_cols)}

    long_parts = []
    for role in ROLES:
        rcols = [f"{role}_{s}" for s in rstats]
        idx = [idx_of[c] for c in rcols]
        dz_role = Dz[:, idx].sum(axis=1)
        net = p - _sigmoid(z - dz_role)
        frac = np.where(np.abs(dz_role)[:, None] > 1e-9,
                        Dz[:, idx] / dz_role[:, None], 1.0 / len(rstats))
        split = net[:, None] * frac
        sub = pd.DataFrame({
            "gameid": team_df["gameid"].values, "side": team_df["side"].values,
            "result": team_df["result"].astype(int).values, "p_model": p,
            "position": role, "net_contribution": net,
        })
        for j, stat in enumerate(rstats):     # CS (if present) rides in the c_damage slot
            sub[_STAT_COL[stat]] = split[:, j]
        for col in _ALL_STAT_COLS:            # slots absent from rstats (e.g. CS in KDA-only) = 0
            if col not in sub.columns:
                sub[col] = 0.0
        sub["c_fb"] = 0.0
        long_parts.append(sub)
    return pd.concat(long_parts, ignore_index=True)


def _lp_features(year: int, home_leagues: Optional[dict] = None,
                 force_recompute: bool = False) -> pd.DataFrame:
    """Weight-INVARIANT per-(player, match) features for a Leaguepedia gap year (net
    contribution, sources, baseline, p_model, phase, league context). This is the expensive
    part (Model 2 + the quantile-regression replacement), so it's cached to disk like the
    Oracle _match_features; scaling/weight changes reuse it. A caller-supplied home_leagues
    map (the merge-year case) is cached under a distinct '_merged' key so it doesn't collide
    with the standalone map.

    Years in a MODEL_GROUPS entry (2011+2012) fit ONE model on their pooled data but each still
    returns only its own season's rows, so career.py keeps per-season contributions."""
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tag = "_merged" if home_leagues is not None else ""
    path = _CACHE_DIR / f"lp_features_{year}{tag}.pkl"   # RAW; normalization applied downstream
    if path.exists() and not force_recompute:
        return pd.read_pickle(path)

    rstats = _rstats_for(year)
    group = MODEL_GROUPS.get(year, (year,))
    # Pool the group's data for MODEL FITTING only; the output frame stays this-year-only.
    train_df = pd.concat([_load_filtered(y) for y in group], ignore_index=True)
    if train_df.empty:
        raise RuntimeError(f"no Leaguepedia rows for group {group} after GAP_LEAGUES filter")

    long_all = _contributions(train_df, rstats)

    # Restrict to THIS season's games (career.py aggregates + breaks out per year).
    df = _load_filtered(year)
    if df.empty:
        raise RuntimeError(f"no Leaguepedia rows for {year} after GAP_LEAGUES filter")
    year_games = set(df["gameid"].astype(str))
    long = long_all[long_all["gameid"].astype(str).isin(year_games)].copy()

    # Attach player identity from THIS year's data.
    ids = df[["gameid", "side", "position", "playername", "teamname"]].drop_duplicates(
        ["gameid", "side", "position"])
    long = long.merge(ids, on=["gameid", "side", "position"], how="left")

    # Opponent / league labelling + baseline (opponent-league Elo), like season._match_features.
    home = _resolve_home(df, year, home_leagues)
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
    inv = long[[c for c in _INVARIANT_COLS if c in long.columns]].reset_index(drop=True)
    inv.to_pickle(path)
    return inv


def build_match_scores(year: int, weights: Optional[ScoreWeights] = None,
                       home_leagues: Optional[dict] = None,
                       force_recompute: bool = False) -> pd.DataFrame:
    """Per-(player, match) scored frame for a Leaguepedia gap year, matching the schema of
    season.build_player_match_scores. Reads the cached weight-invariant features and applies
    the (cheap) weights. home_leagues overrides the per-team home-league map."""
    weights = weights or ScoreWeights()
    long = _lp_features(year, home_leagues=home_leagues, force_recompute=force_recompute).copy()
    # Cross-lane normalization onto the same global (Oracle) reference as the full model. The
    # KDA-only earliest years use their own pooled source distribution (see season._REMAP_*).
    long = apply_lane_remap(long, "lp_kda" if year in _KDA_ONLY_YEARS else "lp")
    long["baseline_term"] = weights.alpha * long["baseline"]
    long["contribution_term"] = weights.lam * long["net_contribution"]
    long["win_bonus"] = weights.beta * (long["result"] - long["p_model"])
    long["score"] = long["baseline_term"] + long["contribution_term"] + long["win_bonus"]
    for s in _SOURCES:
        long[f"{s}_term"] = weights.lam * long[s]
    return long.reset_index(drop=True)
