"""
Season player ratings -- ties the whole pipeline together.

For every scorable team-game it computes, per player:

    score = baseline(opponent league) + lam * net_contribution + beta * (result - p_model)

then aggregates to a per-player season rating with EQUAL weighting of three phases --
regular season, playoffs, and an average international run (see build_player_ratings):
regular season and playoffs are rate-normalized (schedule-/format-length agnostic) while
international runs accumulate (a deep Worlds/MSI run counts for more).

Pieces joined:
  - contribution.py  -> per-player net win-probability contribution + p_model (Model 2)
  - team_leagues.py  -> each team's home league + opponent's home league (baseline input)
  - scoring.py       -> baseline (opponent league's strength) + weights

NOTE: contributions use Model 1's context-aware expected reference by default
(use_model1=False falls back to the global mean). First blood is not scored (Model 2 has no
team-level FB feature; see WinProbabilityConfig.team_firstblood). Baseline uses the OPPONENT
league's Elo (domestic: your own league).
"""

from __future__ import annotations

import json
import logging
import math
from datetime import date as _date, timedelta
from typing import Optional

import numpy as np
import pandas as pd

from .config import DATA_DIR
from .contribution import (
    LANE_STATS,
    ROLES,
    contributions_for_frame,
    explain_team_game,
    train_win_prob_bundle,
)
from .expected_stats import expected_reference_frame
from .io_oracle import load_oracle_years
from .player_identity import label_map as player_label_map
from .scoring import REFERENCE_ELO, ScoreWeights, load_league_elos, apply_scored_terms
from .team_leagues import build_team_game_table, resolve_home_leagues
from .win_probability import WinProbabilityConfig, build_team_features

# Cache for the weight-invariant per-match feature frame (trains the models). Scaling /
# weight changes reuse this instead of retraining. Bust it (force_recompute=True) when
# the models or features change.
# Reference level the per-player contribution is measured against (Model 1's conditional
# prediction). None = conditional MEAN ("vs an average player"); a low quantile (e.g. 0.2) =
# REPLACEMENT level, so nearly every performance is above it -> contribution is larger and
# accumulates (WAR-style: value above replacement).
_REPLACEMENT_QUANTILE: Optional[float] = 0.20

# Scale the per-player contribution is measured on (see contribution.contributions_for_frame):
#   "pp" = win-probability points (state-dependent; under-credits players on dominant teams).
#   "z"  = raw log-odds delta (teammate-/game-state-independent, a purer individual-skill
#          measure). Raw z runs ~20x larger than "pp", which would swamp the baseline/
#          win-bonus terms (both on a 0-1 probability scale) and break the tuned weights and
#          Excel formatting. _CONTRIB_Z_RESCALE multiplies z back onto a pp-comparable scale;
#          a LINEAR rescale preserves state-independence (the whole point of using z), it only
#          changes units. Default ~= mean(pp)/mean(z) so overall contribution magnitude (and
#          thus the baseline/contribution balance) matches the "pp" pipeline -- the switch
#          then only REDISTRIBUTES contribution across team strengths, without re-weighting
#          contribution vs baseline. Retune scoring weights for precision (this is approximate).
_CONTRIB_METRIC: str = "z"
_CONTRIB_Z_RESCALE: float = 0.05

_CACHE_DIR = DATA_DIR / "cache"
_INVARIANT_COLS = [
    "gameid",
    "game",
    "date",
    "side",
    "position",
    "playername",
    "teamname",
    "opp_teamname",
    "own_league",
    "opp_league",
    "is_international",
    "game_label",
    "phase",
    "result",
    "p_model",
    "net_contribution",
    "c_kills",
    "c_deaths",
    "c_assists",
    "c_damage",
    "baseline",
]
# Per-source components of net_contribution (they sum to it): kills/deaths/assists/damage
# from the lane.
_SOURCES = ["c_kills", "c_deaths", "c_assists", "c_damage"]

# --- Series credit for partial appearances / substitutes ----------------------------------
# A Bo3/Bo5 is ONE match but N games, and a player may play only some of them. Each
# (player, series) is credited fractionally:
#   - VOLUME (contribution, win-bonus, source terms): scaled by games_played / series_games,
#     so a sub who played 1 of 3 games accumulates 1/3 of the match's individual value.
#   - BASELINE (the "you beat competition of this quality" win reward): distributed by the
#     share of the series' WINNING games the player was present for.
# _BASELINE_SERIES_SHARE selects how the baseline is split:
#   - False (default, WINNER-TAKE-ALL): 0 if the team LOST the series; else wins_present /
#     wins_needed. Sums to 1.0 across the winning team's lane, so the total baseline per
#     series win is preserved. For a full-time starter this reduces EXACTLY to the old
#     series win-gate (wins_present == wins_needed => factor 1), so only subs are affected.
#   - True (GAME-SHARE): both teams earn wins_present / series_games, so a team that goes 2-3
#     in a Bo5 keeps 2/5 of the baseline and the winner 3/5 (total across both teams = 1.0).
_BASELINE_SERIES_SHARE: bool = False

# Cross-year per-lane contribution normalization ------------------------------------------
# Model 2 sees only KDA + damage (+ CS in the reduced model), which capture a carry's impact
# well but structurally UNDER-MEASURE a support's (vision, roams, engage/peel) and, to a lesser
# degree, a jungler's. Empirically that compresses the per-game net_contribution ~2-3x for
# sup/jng vs carries (bot per-game std ~16pp vs sup ~7pp) and the lanes have different-SHAPED
# distributions (support is more peaked). Because the baseline and win-bonus terms are IDENTICAL
# for all five players on a team, net_contribution is the only thing separating teammates, so
# the carry out-scores the support no matter who actually played better (this is why a bot
# laner's peak LPS could sit ~20pts above his own support's).
#
# We remove that measurement bias with QUANTILE NORMALIZATION pooled across ALL years: pool each
# lane's per-game leave-one-out contribution over every season, then remap each lane's empirical
# CDF onto a common REFERENCE distribution (all Oracle lanes/years pooled). The Nth-percentile
# game in any lane -- and over all time, the best-ever season in any lane -- then lands at the
# same value, so lanes are directly comparable. Crucially the remap is a SINGLE fixed function
# per lane (not per year), so real within-year cross-lane differences survive (a lane can be
# stronger than another in a given season); only the systematic all-time lane scale is equalized.
# The reduced-model (2013-2015) lanes are mapped onto the same Oracle reference, which also lines
# up their contribution scale with the modern years. The stat components are rescaled by the same
# per-game factor so they still sum to the normalized contribution.
_LANE_NORMALIZE: bool = True
_LANE_COMPONENTS = ("c_kills", "c_deaths", "c_assists", "c_damage")
_REMAP_KNOTS = 1001  # quantile grid resolution for the CDF tables
_REMAP_ORACLE_YEARS = tuple(
    range(2014, 2026)
)  # Oracle box-score years (define the reference)
_REMAP_LP_YEARS = (
    2013,
    2014,
    2015,
    2017,
    2018,
    2019,
)  # reduced (KDA+CS) LP years (gap fills + Rift Rivals)
# The earliest years are KDA-ONLY (no reliable CS), a different contribution distribution, so
# they get their own remap source and are pooled separately before mapping onto the Oracle ref.
_REMAP_LP_KDA_YEARS = (2011, 2012)
_REMAP_CACHE = _CACHE_DIR / "lane_remap.pkl"


def _pool_lane_loo() -> dict:
    """Pool RAW lane leave-one-out contributions (net_contribution) across all remap
    years, per (source, lane), and build quantile-knot tables that map each source-lane's CDF
    onto a common reference (all Oracle lanes/years pooled). Reads the cached weight-invariant
    frames (building them if missing) -- this is the only step that spans all years."""
    from . import lp_reduced

    q_grid = np.linspace(0.0, 1.0, _REMAP_KNOTS)
    per_lane: dict[tuple[str, str], list] = {}
    ref_vals: list = []

    def add(long: pd.DataFrame, source: str) -> None:
        if long.empty:
            return
        loo = long["net_contribution"].to_numpy(float)
        pos = long["position"].to_numpy()
        for lane in ROLES:
            v = loo[pos == lane]
            v = v[np.isfinite(v)]
            if len(v):
                per_lane.setdefault((source, lane), []).append(v)
                if source == "oracle":
                    ref_vals.append(v)

    for y in _REMAP_ORACLE_YEARS:
        try:
            add(_match_features(y, use_model1=True), "oracle")
        except Exception as e:
            logging.warning(f"[lane-norm] oracle {y} skipped ({type(e).__name__}: {e})")
    for y in _REMAP_LP_YEARS:
        try:
            add(lp_reduced._lp_features(y), "lp")
        except Exception as e:
            logging.warning(f"[lane-norm] lp {y} skipped ({type(e).__name__}: {e})")
    for y in _REMAP_LP_KDA_YEARS:
        try:
            add(lp_reduced._lp_features(y), "lp_kda")
        except Exception as e:
            logging.warning(f"[lane-norm] lp_kda {y} skipped ({type(e).__name__}: {e})")

    ref = np.concatenate(ref_vals) if ref_vals else np.array([0.0, 1.0])
    tables = {"q_grid": q_grid, "ref_q": np.quantile(ref, q_grid), "lane_q": {}}
    for key, arrs in per_lane.items():
        tables["lane_q"][key] = np.quantile(np.concatenate(arrs), q_grid)
    return tables


def build_lane_remap(force_recompute: bool = False) -> dict:
    """Build (and disk-cache) the cross-year per-lane quantile-remap tables. With
    force_recompute, first rebuild every remap year's weight-invariant frame (after a model
    change) so the pooled distributions are current; otherwise reuse whatever is cached.
    """
    from . import lp_reduced

    if force_recompute:
        total = (
            len(_REMAP_ORACLE_YEARS) + len(_REMAP_LP_YEARS) + len(_REMAP_LP_KDA_YEARS)
        )
        done = 0
        for y in _REMAP_ORACLE_YEARS:
            done += 1
            logging.info(
                f"[lane-norm] ({done}/{total}) rebuilding oracle {y} models ..."
            )
            try:
                _match_features(y, use_model1=True, force_recompute=True)
            except Exception as e:
                logging.warning(
                    f"[lane-norm] oracle {y} rebuild skipped ({type(e).__name__}: {e})"
                )
        for y in _REMAP_LP_YEARS + _REMAP_LP_KDA_YEARS:
            done += 1
            logging.info(f"[lane-norm] ({done}/{total}) rebuilding lp {y} models ...")
            try:
                lp_reduced._lp_features(y, force_recompute=True)
            except Exception as e:
                logging.warning(
                    f"[lane-norm] lp {y} rebuild skipped ({type(e).__name__}: {e})"
                )
        logging.info(
            f"[lane-norm] pooling {total} years into cross-year remap tables ..."
        )
    elif _REMAP_CACHE.exists():
        return pd.read_pickle(_REMAP_CACHE)

    tables = _pool_lane_loo()
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    pd.to_pickle(tables, _REMAP_CACHE)
    return tables


def _get_lane_remap() -> dict:
    """Load the cached remap tables, building them once (from the cached per-year frames) if
    they don't exist yet."""
    if _REMAP_CACHE.exists():
        return pd.read_pickle(_REMAP_CACHE)
    return build_lane_remap(force_recompute=False)


def apply_lane_remap(
    long: pd.DataFrame, source: str, tables: Optional[dict] = None
) -> pd.DataFrame:
    """Quantile-normalize each lane's per-game leave-one-out contribution onto the global
    reference distribution (so the Nth-percentile game is worth the same in every role). Stat
    components are rescaled to still sum to the normalized contribution. Mutates and returns `long`; no-op when _LANE_NORMALIZE is False.

    `source` selects which per-lane CDF to invert ('oracle' or 'lp')."""
    if not _LANE_NORMALIZE or long.empty:
        return long
    if tables is None:
        tables = _get_lane_remap()
    q_grid, ref_q = tables["q_grid"], tables["ref_q"]
    comp = [c for c in _LANE_COMPONENTS if c in long.columns]

    loo = long["net_contribution"].to_numpy(float)
    new_loo = loo.copy()
    pos = long["position"].to_numpy()
    for lane in ROLES:
        lane_q = tables["lane_q"].get((source, lane))
        if lane_q is None:
            continue
        m = pos == lane
        if not m.any():
            continue
        u = np.interp(loo[m], lane_q, q_grid)  # this lane's empirical CDF -> percentile
        new_loo[m] = np.interp(
            u, q_grid, ref_q
        )  # value at the same percentile in the reference

    if comp:
        C = long[comp].to_numpy(float)
        with np.errstate(divide="ignore", invalid="ignore"):
            ratio = np.where(np.abs(loo) > 1e-9, new_loo / loo, np.nan)
        newC = C * ratio[:, None]
        zero = ~np.isfinite(ratio)  # loo ~ 0: split evenly (shares undefined)
        if zero.any():
            newC[zero] = (new_loo[zero] / len(comp))[:, None]
        long[comp] = newC
    long["net_contribution"] = new_loo
    return long


# Tournament importance weights derived from average peak concurrent viewership over the
# last 3 years -- an objective proxy for how much each tournament matters. Keys are Oracle
# game_labels; update as new data arrives. FST (First Stand) debuted 2025 so has 2 years.
_TOURNAMENT_VIEWERSHIP = {
    "WLDs": [6752585, 6941610, 6402760],  # Worlds
    "MSI": [2315920, 3447582, 2829728],  # Mid-Season Invitational
    "EWC": [1477470, 1208123, 1123619],  # Esports World Cup
    "FST": [1106126, 1500730],  # First Stand (2025+; Oracle label to confirm)
    "MSC": [591496],  # Mid-Season Cup (2020; peak concurrent viewers)
    "LTA": [318462],  # LTA cross-conference championship (Americas, 2025)
    "AC": [238904], # Americas Cup
    "KeSPA": [173449, 110196, 66335],  # KeSPA Cup (domestic, KR)
    "KeSPA Cup": [173449, 110196, 66335],  # 2026 KeSPA Cup label, using same weights as previous years
    "DCup": [55751, 69654, 60238],  # Demacia Cup (domestic, CN)
}

# Small international / cross-region events without reliable viewership data: a flat 0.1
# weight on the same 0-1 scale (Worlds = 1.0). Kept SEPARATE from _TOURNAMENT_VIEWERSHIP so
# the viewership-derived numbers stay honest. (Minor DOMESTIC 2nd-tiers are dropped instead
# -- see EXCLUDED_LEAGUES.)
_MANUAL_TOURNAMENT_WEIGHTS = {
    "IEM": 0.1,  # Intel Extreme Masters (3rd-party intl, top teams, off-season)
    "ASI": 0.1,  # Asia Invitational (minor intl)
    "IWCI": 0.1,  # International Wildcard Invitational (wildcard qualifier)
    "Riot": 0.1,  # 2020 VCS x PCS cross-region event (MSI-cancelled COVID season)
    # Early-era (2011-2012) events, scored as "tournament" phase (no regional Elo pre-2013 in
    # the region-keyed era). No reliable viewership numbers exist, so these are hand-set on the
    # Worlds=1.0 scale and are prime CALIBRATION targets against the consensus all-time list.
    "OGN": 0.4,  # Champions Korea -- premier league of the dominant region (2012)
    "IPL": 0.15,  # IGN Pro League (IPL5 drew top intl fields; other IPLs smaller)
    "MLG": 0.1,  # MLG Pro Circuit (NA LAN)
    "DH": 0.1,  # DreamHack (EU LAN)
    "RR": 0.2,  # Rift Rivals (2017-2019 mid-season regional-rivalry exhibition, no damage data)
}

# Minor / secondary tiers (2nd divisions, academy & challenger leagues, regional feeders)
# that have no regional Elo. Previously these were mislabeled as 0-weight "tournaments",
# which (a) polluted games/win_rate/min_games and (b) buried the real gaps in the warning.
# We DROP them from scoring instead -- but ONLY in years where the label isn't a RATED top
# league (see build_player_ratings). That rated guard is what lets PCS/VCS/LJL/LCO appear
# here safely: they are top-tier (rated) in some years and secondary feeders in others
# (e.g. 2025, after the Pacific regions folded into LCP), and we only exclude the latter.
EXCLUDED_LEAGUES = {
    "NA CS",
    "EU CS",  # NA / EU Challenger Series
    "CK",  # Challengers Korea
    "LSPL",  # LoL Secondary Pro League (CN 2nd div)
    "OCS",  # Oceanic Challenger Series
    "LJLCS",  # LJL Challenger Series (JP 2nd div)
    "NACL",  # NA Challengers League
    "CD",
    "CDF",  # Circuito Desafiante (BR 2nd div) / minor cup
    "BRCC",
    "CISC",
    "TCS",  # minor / qualifier circuits
    "LHE",
    "LMF",
    "DDH",
    "SL (LATAM)",
    "ASCI",  # LATAM minor / secondary
    "EM",  # EMEA Masters (2nd-tier EU)
    "NEST",  # domestic minor multi-title event (CN)
    "Asia Master",  # regional invitational feeder
    "LRN",
    "LRS",  # LTA North/South regional feeders (below LTA N/S)
    "GPL",  # rest-of-SEA minor circuit 2016-2018 after Vietnam
    # (VCS) + Taiwan (LMS) split off; no intl slot, so
    # unrated -- rated guard keeps its rated 2013 season
    "TCL",  # Turkey: rated region 2013-2023, then demoted to an
    # EMEA ERL (no intl slot) in 2024+; rated guard keeps
    # its 2013-2023 seasons, drops the ERL-tier years
    "PCS",
    "VCS",
    "LJL",
    "LCO",  # top-tier in their years (rated guard keeps those)
    "PCL", # Pacific Challengers League
}

# Year-aware league-label aliases: Oracle sometimes labels the Worlds regional-qualifier
# gauntlet (Sept, top domestic teams) with the MODERN league name (LCS/LEC) or the LCK code
# before that name became the top-league label. Remap source -> target ONLY in years where
# the source isn't rated but the target is, so it fires for the 2015-2018 gauntlet games and
# never touches 2019+ (where LCS/LEC ARE the top leagues). Folds them into the parent major
# league instead of dropping them at weight 0.
_LEAGUE_ALIASES = {"LCS": "NA LCS", "LEC": "EU LCS", "LCK": "OGN"}

# (year, league) pairs whose Elo is CARRIED FORWARD from the last year the region had
# international anchoring matches (they stopped attending Worlds/MSI, so their Elo can't be
# recomputed -- see info/ending_elos_*.csv). Listed here so home-league resolution treats
# them as rated for the BASELINE but NOT as a home-preference: a team that also played a
# genuinely-anchored rated league that year keeps that as its home (e.g. 2024 DetonatioN
# FocusMe stays PCS, which it actually competed in), while pure-region teams (AXIZ, Burning
# Core) still fall back to their mode league and finally get a valid baseline.
_CARRYFORWARD_ELOS = {(2023, "LCO"), (2024, "LJL"), (2024, "LCO")}


def _viewership_weights(scale: str = "sqrt") -> dict:
    """
    Tournament weights from average viewership, normalized so the most-watched (Worlds) =
    1.0 (divide by max; nothing is forced to 0).

    scale compresses the ~2-orders-of-magnitude viewership spread so Worlds doesn't dwarf
    everything: 'sqrt' (default) is balanced (Worlds 1.0, MSI ~0.65, EWC/FST ~0.44, cups
    ~0.10); 'linear' none (cups ~0.01); 'log' over-compresses (cups ~0.70).
    """
    avg = {k: sum(v) / len(v) for k, v in _TOURNAMENT_VIEWERSHIP.items()}
    if scale == "linear":
        f = avg
    elif scale == "sqrt":
        f = {k: math.sqrt(v) for k, v in avg.items()}
    elif scale == "log":
        f = {k: math.log(v) for k, v in avg.items()}
    else:
        raise ValueError(f"unknown scale {scale!r}")
    top = max(f.values())
    weights = {k: round(x / top, 3) for k, x in f.items()}
    # Fold in hand-set weights for events without viewership data (already on the 0-1 scale).
    weights.update(_MANUAL_TOURNAMENT_WEIGHTS)
    return weights


def _remap_league_aliases(df: pd.DataFrame, rated: set[str]) -> pd.DataFrame:
    """Fold Worlds regional-qualifier gauntlet games (Oracle-labelled with the modern
    league name, e.g. 'LCS'/'LEC', or 'LCK' pre-rename) into their parent major league.
    Remap source -> target only where the source ISN'T rated this year but the target IS,
    so it fires for the 2015-2018 gauntlet and never touches years where LCS/LEC/LCK are
    themselves the rated top league."""
    active = {
        src: tgt
        for src, tgt in _LEAGUE_ALIASES.items()
        if tgt in rated and src not in rated
    }
    if not active or "league" not in df.columns:
        return df
    hits = df["league"].isin(active)
    if hits.any():
        df = df.copy()
        df.loc[hits, "league"] = df.loc[hits, "league"].map(active)
        logging.info(
            f"[leagues] remapped {int(hits.sum())} gauntlet game-rows "
            f"{ {k: active[k] for k in sorted(active)} }"
        )
    return df


def _player_lane_table(df: pd.DataFrame) -> pd.DataFrame:
    """One row per (gameid, side, position): player and team.

    `playername` is replaced by the disambiguated identity label (see player_identity) so
    that same-handle-different-person cases (e.g. the LPL/VCS/NA "Knight"s) stay separate
    downstream. Falls back to the raw handle when a row has no usable playerid.
    """
    cols = [
        "gameid",
        "side",
        "position",
        "playername",
        "playerid",
        "teamname",
    ]
    d = df[[c for c in cols if c in df.columns]].copy()
    d["position"] = (
        d["position"]
        .astype(str)
        .str.lower()
        .replace({"jungle": "jng", "adc": "bot", "support": "sup"})
    )
    d = d[d["position"].isin(ROLES)]
    agg = dict(playername=("playername", "first"), teamname=("teamname", "first"))
    if "playerid" in d.columns:
        agg["playerid"] = ("playerid", "first")
    out = d.groupby(["gameid", "side", "position"], as_index=False).agg(**agg)
    if "playerid" in out.columns:
        labels = out["playerid"].astype(str).str.strip().map(player_label_map())
        out["playername"] = labels.fillna(out["playername"])
        out = out.drop(columns=["playerid"])
    return out


def _match_features(
    year: int,
    use_model1: bool = True,
    force_recompute: bool = False,
    home_leagues: Optional[dict] = None,
) -> pd.DataFrame:
    """
    Weight-INVARIANT per-(player, match) features: net_contribution, baseline, p_model,
    phase, league context. This is the expensive part (trains Model 1 + Model 2), so it's
    cached to disk; scaling/weight changes reuse it. Set force_recompute=True after any
    model/feature change.

    home_leagues overrides the per-team home-league map (default: resolve from this year's
    Oracle data). Pass a map resolved across MULTIPLE sources (e.g. Oracle + Leaguepedia) so
    a team whose only Oracle games are an international event still gets its real domestic
    home -- otherwise its games baseline as NaN and drop. When provided, the result is cached
    under a distinct '_merged' key (the labelling is source-set-specific) so it doesn't
    collide with the default map but is still reused across runs.
    """
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tag = "_merged" if home_leagues is not None else ""
    # Cache holds RAW (un-normalized) contributions; cross-lane normalization is applied
    # downstream in build_player_match_scores from the global remap tables.
    met = f"_{_CONTRIB_METRIC}"  # bust the cache when the contribution scale changes
    path = _CACHE_DIR / f"match_features_{year}_m1{int(use_model1)}{met}{tag}.pkl"
    if path.exists() and not force_recompute:
        cached = pd.read_pickle(path)
        if "c_fb" not in cached.columns:
            return cached
        # Pre-removal cache: its net_contribution still carries the first-blood credit.
        logging.info(f"[features] {path.name} predates first-blood removal; rebuilding")

    cfg = WinProbabilityConfig(years=(year,))
    df = load_oracle_years(cfg.years)
    df = _remap_league_aliases(df, set(load_league_elos(year)))

    # Model 2 + per-team-game contributions, referenced against Model 1 expected values.
    bundle = train_win_prob_bundle(cfg)
    team_df = build_team_features(df, cfg).reset_index(drop=True)
    expected_df = (
        expected_reference_frame(df, team_df, quantile=_REPLACEMENT_QUANTILE)
        if use_model1
        else None
    )
    contrib = contributions_for_frame(
        team_df, bundle, expected_df=expected_df, metric=_CONTRIB_METRIC
    )
    if _CONTRIB_METRIC == "z" and _CONTRIB_Z_RESCALE != 1.0:
        # Linear rescale onto a pp-comparable scale (state-independence preserved). The dz_*
        # per-feature columns are left RAW -- they only feed the ratio-based source split
        # (frac = Dz/dz_sum), where any constant factor cancels; the lane totals carry the
        # rescaled scale that flows into net_contribution downstream.
        for role in ROLES:
            contrib[role] = contrib[role] * _CONTRIB_Z_RESCALE

    # Long form: one row per (team-game, lane). net_contribution is that lane's per-lane
    # LOO (unchanged). We SPLIT it across its four stats by each stat's log-odds share --
    # pure interpretability, so c_kills+c_deaths+c_assists+c_damage == net_contribution.
    frames = []
    for role in ROLES:
        sub = contrib[["gameid", "side", "result", "p_model"]].copy()
        sub["position"] = role
        net = contrib[role].to_numpy()
        sub["net_contribution"] = net
        Dz = np.stack(
            [contrib[f"dz_{role}_{s}"].to_numpy() for s in LANE_STATS], axis=1
        )
        dz_sum = Dz.sum(axis=1)
        frac = np.where(np.abs(dz_sum)[:, None] > 1e-9, Dz / dz_sum[:, None], 0.25)
        split = net[:, None] * frac
        sub["c_kills"], sub["c_deaths"], sub["c_assists"], sub["c_damage"] = (
            split[:, 0],
            split[:, 1],
            split[:, 2],
            split[:, 3],
        )
        frames.append(sub)
    long = pd.concat(frames, ignore_index=True)

    # Attach player names and team.
    long = long.merge(
        _player_lane_table(df), on=["gameid", "side", "position"], how="left"
    )

    # Resolve home leagues preferring RATED leagues, so teams that span an unrated + rated
    # league (e.g. Fukuoka SoftBank HAWKS: LJL + PCS) are scored on their rated + international
    # games instead of being dropped for having an unrated home league. A caller-supplied map
    # (resolved across Oracle + Leaguepedia) takes precedence for the gap years.
    if home_leagues is None:
        # Carry-forward leagues rate the baseline but don't claim home from a team's
        # genuinely-anchored rated league (see _CARRYFORWARD_ELOS).
        carry = {lg for (y, lg) in _CARRYFORWARD_ELOS if y == year}
        home_leagues = resolve_home_leagues(
            df, preferred=set(load_league_elos(year)) - carry
        )
    tg = build_team_game_table(df, home_leagues)
    tg_cols = [
        "gameid",
        "side",
        "opp_teamname",
        "own_league",
        "opp_league",
        "is_international",
        "game_label",
    ]
    if "playoffs" in tg.columns:
        tg_cols.append("playoffs")
    long = long.merge(tg[tg_cols], on=["gameid", "side"], how="left")

    # Match date + in-series game number (for looking games up, and Bo3/Bo5 context).
    if "date" in df.columns:
        long["date"] = long["gameid"].map(df.groupby("gameid")["date"].first())
    if "game" in df.columns:
        long["game"] = long["gameid"].map(df.groupby("gameid")["game"].first())

    # Baseline = opponent league's strength (expected win rate vs a 1000-Elo league).
    elos = load_league_elos(year)
    opp_elo = long["opp_league"].map(elos)
    long["baseline"] = 1.0 / (1.0 + 10 ** ((REFERENCE_ELO - opp_elo) / 400.0))

    # Phase classification:
    #   - rated league label -> 'regular' or 'playoff' by the playoffs flag.
    #   - any other label (Worlds/MSI/EWC/First Stand, KeSPA/Demacia cups, ...) is a
    #     'tournament'; each tournament is weighted by importance in build_player_ratings
    #     (domestic cups get a low weight rather than being treated as playoffs).
    rated = set(elos)
    if "playoffs" in long.columns:
        po = long["playoffs"].fillna(0).astype(int).to_numpy()
    else:
        po = np.zeros(len(long), dtype=int)
    is_rated = long["game_label"].isin(rated).to_numpy()
    long["phase"] = np.where(
        is_rated,
        np.where(po == 1, "playoff", "regular"),
        "tournament",
    )

    # Keep only scorable rows (baseline computable + player known).
    long = long.dropna(subset=["baseline", "playername"])
    inv = long[[c for c in _INVARIANT_COLS if c in long.columns]].reset_index(drop=True)
    inv.to_pickle(path)  # default or '_merged' path per the tag above
    return inv


def build_player_match_scores(
    year: int,
    weights: Optional[ScoreWeights] = None,
    use_model1: bool = True,
    force_recompute: bool = False,
    home_leagues: Optional[dict] = None,
) -> pd.DataFrame:
    """
    One row per (player, match) with the full score decomposition. Applies the (cheap)
    weights on top of the cached weight-invariant features:

        score = alpha*baseline + lam*net_contribution + beta*(result - p_model)

    Columns add: baseline_term, contribution_term, win_bonus, score.
    """
    if weights is None:
        weights = ScoreWeights()

    m = _match_features(
        year,
        use_model1=use_model1,
        force_recompute=force_recompute,
        home_leagues=home_leagues,
    ).copy()
    # Cross-lane normalization: quantile-remap each lane's contribution onto the global
    # (all-years) reference so lanes are directly comparable (see apply_lane_remap).
    m = apply_lane_remap(m, "oracle")
    # Apply the (cheap) region-scaled score formula on top of the cached features -- baseline is
    # recomputed vs the year's PEAK region and raised to the per-phase region exponent, so no
    # model retraining is needed when the weights/exponents change. See scoring.apply_scored_terms.
    apply_scored_terms(m, weights, load_league_elos(year), source_cols=_SOURCES)
    return m


_LP_STAGE_WEIGHT_CACHE: dict[int, dict] = {}


def _lp_stage_weights(year: int) -> dict:
    """Load Leaguepedia match JSONs and build a lookup:
        (date_str "YYYY-MM-DD", frozenset({team_lower, team_lower})) -> stage_weight
    Only caches QF/SF/Finals entries (default weight 1.0 is implicit).
    Stage weights: Finals=3.0, Semifinals=2.0, Quarterfinals=1.5, else 1.0.
    """
    if year in _LP_STAGE_WEIGHT_CACHE:
        return _LP_STAGE_WEIGHT_CACHE[year]

    def _stage_w(match_id: str) -> float:
        mid = match_id.lower()
        if "quarterfinal" in mid:
            return 1.5
        if "semifinal" in mid:
            return 2.0
        if "final" in mid:  # grand final only (semi/quarter already caught above)
            return 3.0
        return 1.0

    table: dict = {}
    match_dir = DATA_DIR / "leaguepedia" / "matches"
    for path in sorted(match_dir.glob("*.json")):
        if path.stem.endswith("_all"):
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, list):
            continue
        for match in data:
            if str(match.get("Year", "")) != str(year):
                continue
            w = _stage_w(match.get("MatchId", ""))
            if w == 1.0:
                continue  # only cache above-default weights
            t1 = (match.get("Team1") or "").strip().lower()
            t2 = (match.get("Team2") or "").strip().lower()
            if not t1 or not t2:
                continue
            teams = frozenset([t1, t2])
            dt_str = (match.get("DateTime UTC") or "")[:10]
            if len(dt_str) == 10:
                table[(dt_str, teams)] = max(table.get((dt_str, teams), 0.0), w)

    _LP_STAGE_WEIGHT_CACHE[year] = table
    return table


def _annotate_stage_weights(matches: pd.DataFrame, year: int) -> pd.DataFrame:
    """Add a `stage_weight` column to the match frame (1.0 default; higher for QF/SF/Finals
    in international tournaments). Uses Leaguepedia match data joined by date + team pair,
    with ±1-day tolerance for multi-day BO5 series."""
    table = _lp_stage_weights(year)
    if not table:
        matches = matches.copy()
        matches["stage_weight"] = 1.0
        return matches

    intl_mask = matches["is_international"].fillna(False)
    if not intl_mask.any():
        matches = matches.copy()
        matches["stage_weight"] = 1.0
        return matches

    matches = matches.copy()
    matches["stage_weight"] = 1.0

    dates = pd.to_datetime(matches["date"]).dt.date
    t1 = matches["teamname"].str.strip().str.lower()
    t2 = matches["opp_teamname"].str.strip().str.lower()

    intl_idx = matches.index[intl_mask]
    for idx in intl_idx:
        teams = frozenset([t1[idx], t2[idx]])
        d = dates[idx]
        for delta in (0, -1, 1):
            key = (str(d + timedelta(days=delta)), teams)
            if key in table:
                matches.at[idx, "stage_weight"] = table[key]
                break

    return matches


def build_player_ratings(
    year: int,
    weights: Optional[ScoreWeights] = None,
    rated_only: bool = True,
    min_games: int = 15,
    use_model1: bool = True,
    regular_season_ref_games: Optional[float] = None,
    intl_weight: float = 1.0,
    tournament_weights: Optional[dict] = None,
    matches: Optional[pd.DataFrame] = None,
    force_recompute: bool = False,
) -> pd.DataFrame:
    """
    Aggregate per-match scores across three phases: regular season, playoffs, and
    tournaments (Worlds/MSI/EWC/First Stand + domestic cups).

        regular_pts  = sum(regular scores) * N_ref / max_regular_run[league]  (accumulates)
        playoff_pts  = sum(playoff scores) * N_ref / max_playoff_run[league]  (accumulates)
        tourn_pts    = sum(score * w_tournament) * tourn_weight * (N_ref / max_weighted_run)
        total_score  = regular_pts + playoff_pts + tourn_pts

    Regular season and playoffs both accumulate but are normalized by the deepest run IN
    EACH LEAGUE, so a full season/run ~ one phase unit everywhere while a one-game sub
    scores far less; this equalizes schedule/bracket length across regions without erasing
    volume within a region. Tournaments ACCUMULATE, but each tournament game is scaled by
    its importance w_tournament (objective default: distinct regions in the field / max, so
    Worlds=1.0, MSI~0.9, EWC~0.4, domestic cups ~0.1-0.2), and the phase is normalized to
    the deepest WEIGHTED run so the champion gets tourn ~= reg.

    Args:
        min_games: drop players with fewer total scored matches (small-sample noise).
        use_model1: use Model 1's context-aware expected reference (vs global mean).
        regular_season_ref_games: N_ref (common per-phase scale). Default None => mean
            regular-season games per player.
        intl_weight: overall multiplier on the tournament phase.
        tournament_weights: optional {label: weight} override; default derives weights from
            each tournament's field breadth (distinct regions / max).
        matches: optional precomputed build_player_match_scores() frame (avoids recompute).
        force_recompute: rebuild the cached match-feature frame (after a model change).

    N_ref, tournament_weights, and intl_weight are stored on the result's `.attrs`.
    """
    rated = set(load_league_elos(year))
    if matches is None:
        matches = build_player_match_scores(
            year, weights, use_model1=use_model1, force_recompute=force_recompute
        )
    if rated_only:
        matches = matches[matches["own_league"].isin(rated)]

    # Drop non-scoring minor/secondary tiers (2nd divisions, academy/feeder leagues) so they
    # don't pad games/win_rate/min_games or get mislabeled as 0-weight tournaments -- but only
    # where the label isn't a RATED top league this year (PCS/VCS/LJL/LCO are top-tier in some
    # years, feeders in others; the rated guard keeps the years they count).
    excl = EXCLUDED_LEAGUES - rated
    if excl:
        drop = matches["game_label"].isin(excl)
        if drop.any():
            logging.info(
                f"[leagues] {year}: dropped {int(drop.sum())} games from non-rated "
                f"minor tiers {sorted(matches.loc[drop, 'game_label'].unique())}"
            )
            matches = matches[~drop]

    # Annotate each international game with a stage weight (Finals=3×, SF=2×, QF=1.5×, else 1×)
    # sourced from Leaguepedia match JSON, joined by (date ±1d, team pair).
    matches = _annotate_stage_weights(matches, year)

    def _mode(s: pd.Series):
        m = s.mode()
        return m.iat[0] if not m.empty else None

    source_terms = [f"{s}_term" for s in _SOURCES]
    comps = ["baseline_term", "contribution_term", "win_bonus"] + source_terms

    # SERIES (match) unit. A Bo3/Bo5 is ONE match, not N games. We collapse each series to the
    # MEAN of its games and make the accumulation unit the MATCH -- so a series won 2-0 is
    # never worth less than 2-1 (same per-game average => same score; a dominant sweep, with
    # no lost game dragging the mean, scores HIGHER). Volume ("more = better") now counts
    # matches/series (deeper runs, more tournaments), not games. A series is identified by
    # day + event label + unordered team pair (both teams share the id).
    m = matches.copy()
    _day = pd.to_datetime(m["date"]).dt.date.astype(str)
    _a, _b = m["teamname"].astype(str), m["opp_teamname"].astype(str)
    _pair = np.where(_a.values < _b.values, _a + "|" + _b, _b + "|" + _a)
    m["seriesid"] = _day + "@" + m["game_label"].astype(str) + "@" + _pair

    # Per-(player, series) fractional credit for partial appearances. Series totals (games,
    # wins) must come from the FULL game set -- a sub's own rows cover only the games they
    # played -- so aggregate every player's rows per (series, team) first, then per player.
    _team = (
        m.drop_duplicates(["seriesid", "teamname", "gameid"])
        .groupby(["seriesid", "teamname"])
        .agg(team_games=("gameid", "nunique"), team_wins=("result", "sum"))
        .reset_index()
    )
    _team["team_won"] = _team["team_wins"] > (_team["team_games"] - _team["team_wins"])
    _play = (
        m.drop_duplicates(["playername", "seriesid", "teamname", "gameid"])
        .groupby(["playername", "seriesid", "teamname"])
        .agg(games_played=("gameid", "nunique"), wins_present=("result", "sum"))
        .reset_index()
        .merge(_team, on=["seriesid", "teamname"], how="left")
    )
    _tg = _play["team_games"].replace(0, np.nan)
    _play["part_frac"] = (_play["games_played"] / _tg).fillna(1.0)  # fractional VOLUME
    if _BASELINE_SERIES_SHARE:  # GAME-SHARE: both teams, by games won
        _play["base_frac"] = (_play["wins_present"] / _tg).fillna(0.0)
    else:  # WINNER-TAKE-ALL: winners, by wins present
        _need = _play["team_wins"].where(_play["team_won"]).replace(0, np.nan)
        _play["base_frac"] = np.where(
            _play["team_won"], (_play["wins_present"] / _need).fillna(0.0), 0.0
        )
    _credit = _play[["playername", "seriesid", "part_frac", "base_frac"]]
    _vol_cols = [
        c for c in comps if c != "baseline_term"
    ]  # scaled by participation fraction

    def _to_series(phase_df: pd.DataFrame) -> pd.DataFrame:
        """One row per (player, series): comps AVERAGED over the games the player played, then
        credited fractionally for partial appearances -- VOLUME (contribution/win-bonus/source)
        by games played, and the league BASELINE by the share of the series' winning games the
        player was present for (see _BASELINE_SERIES_SHARE). This preserves the total points per
        series while distributing them to who actually played; a full-time starter is unchanged.
        The per-region match normalization (below) keeps regions with more matches from being
        overweighted."""
        cols = [
            "playername",
            "seriesid",
            "own_league",
            "game_label",
            "teamname",
            "part_frac",
            "base_frac",
        ]
        if phase_df.empty:
            return pd.DataFrame(columns=cols + comps)
        agg = {c: (c, "mean") for c in comps}
        agg.update(
            own_league=("own_league", "first"),
            game_label=("game_label", "first"),
            teamname=("teamname", "first"),
        )
        d = phase_df.groupby(["playername", "seriesid"], as_index=False).agg(**agg)
        d = d.merge(_credit, on=["playername", "seriesid"], how="left")
        d["part_frac"] = d["part_frac"].fillna(1.0)
        d["base_frac"] = d["base_frac"].fillna(0.0)
        d["baseline_term"] = d["baseline_term"] * d["base_frac"]  # win-fraction credit
        d[_vol_cols] = d[_vol_cols].mul(d["part_frac"], axis=0)  # fractional volume
        return d

    reg = _to_series(m[m["phase"] == "regular"])
    plf = _to_series(m[m["phase"] == "playoff"])
    tourn = _to_series(m[m["phase"] == "tournament"])
    tourn_games = m[
        m["phase"] == "tournament"
    ]  # game-level, kept only for champion detection

    # Reference volume = mean regular-season MATCHES (series) per player. The earliest years
    # (2011-2012) are 100% tournament (no domestic league in the data), so reg is empty; fall
    # back to mean matches/player over the tournament phase, else tourn_scale would be 0 and
    # zero out every score. (n_ref cancels against the schedule-norm ref/n_ref multiplier
    # downstream, so its exact value only needs to be positive and on the right scale.)
    if regular_season_ref_games is not None:
        n_ref = regular_season_ref_games
    elif len(reg):
        n_ref = reg.groupby("playername").size().mean()
    elif len(tourn):
        n_ref = tourn.groupby("playername").size().mean()
    else:
        n_ref = 0.0

    # Tournament weights: default = viewership-based (Worlds=1.0). Overridable. Any
    # tournament label without a weight is warned and counted as 0.
    tw = (
        _viewership_weights()
        if tournament_weights is None
        else dict(tournament_weights)
    )
    unknown = sorted(set(tourn["game_label"].unique()) - set(tw))
    if unknown:
        logging.warning(
            f"[tournaments] no weight for {unknown}; counting them as 0 -- add viewership."
        )
    tourn["w"] = tourn["game_label"].map(tw).fillna(0.0)

    # Tournament CAP + LENGTH NORMALIZATION, in MATCHES: each player's accumulation is capped
    # at min(their matches, the CHAMPION team's matches) in that tournament, so a long
    # lower-bracket grind can't out-accumulate the efficient champion. Champion = winner of the
    # tournament's last game; champ_matches is that team's SERIES count (full-run length). We
    # DIVIDE by champ_matches so a full champion run = the tournament weight w regardless of how
    # many matches the bracket has (decompounds Worlds's game-count advantage). Per match the
    # effective weight is  w * min(1, champ_matches/player_matches) / champ_matches.
    _t = tourn_games.sort_values(["date", "gameid"])
    champ = _t[_t["result"] == 1].groupby("game_label")["teamname"].last().to_dict()
    champ_matches = {
        lbl: tourn_games.loc[
            (tourn_games["game_label"] == lbl) & (tourn_games["teamname"] == team),
            "seriesid",
        ].nunique()
        for lbl, team in champ.items()
    }
    player_matches = tourn.groupby(["playername", "game_label"])["seriesid"].transform(
        "size"
    )
    cap = tourn["game_label"].map(champ_matches)
    norm = cap.where(
        cap > 0, 1.0
    )  # per-tournament length normalizer (champion's match count)
    tourn["w_eff"] = (
        tourn["w"] * np.minimum(1.0, cap / player_matches).fillna(1.0) / norm
    )

    # Normalize to the deepest capped-weighted run so the champion gets a full weighted phase.
    weighted_run = tourn.groupby("playername")["w_eff"].sum()
    max_run = weighted_run.max() if len(weighted_run) else 1.0
    tourn_scale = (intl_weight * n_ref / max_run) if max_run else 0.0

    # Regular season and playoffs both ACCUMULATE (a one-match sub scores far less than a
    # full-run player), but each MATCH is weighted by N_ref / (deepest run in matches in that
    # league) so a FULL run ~ one phase unit in every region -- equalizing schedule/bracket
    # length across regions without removing the volume signal within one.
    def _accumulate(
        series_df: pd.DataFrame,
    ) -> tuple[pd.DataFrame, pd.Series, pd.DataFrame]:
        d = series_df.copy()
        if d.empty:
            return (
                pd.DataFrame(columns=comps),
                pd.Series(dtype=float),
                pd.DataFrame(columns=["playername", "seriesid", "w"]),
            )
        run = (
            d.groupby(["own_league", "playername"])
            .size()
            .groupby(level="own_league")
            .max()
        )
        d["w"] = n_ref / d["own_league"].map(run)
        # Comps already carry the fractional credit (baseline x base_frac, volume x part_frac),
        # so they're summed at full match weight w; the accumulation WEIGHT (the per-game-average
        # denominator) counts EFFECTIVE matches -- w scaled by participation.
        comp_sums = d[comps].mul(d["w"], axis=0).groupby(d["playername"]).sum()
        weight_sums = (d["w"] * d["part_frac"]).groupby(d["playername"]).sum()
        return comp_sums, weight_sums, d[["playername", "seriesid", "w"]]

    reg_c, reg_w, reg_sw = _accumulate(reg)
    plf_c, plf_w, plf_sw = _accumulate(plf)
    # Per-phase point multipliers (regular = reference; tournaments are scaled by intl_weight in
    # tourn_scale below). Scale BOTH the points and the accumulation weight so the weighted per-game
    # average within a phase is unchanged -- only the phase's share of the career total moves.
    reg_c = reg_c * weights.w_regular
    reg_w = reg_w * weights.w_regular
    plf_c = plf_c * weights.w_playoff
    plf_w = plf_w * weights.w_playoff

    # Tournaments: accumulate per MATCH weighted by tournament importance (w_eff = weight x cap),
    # normalized to the deepest capped-weighted run.
    tourn_weighted = tourn[comps].mul(tourn["w_eff"], axis=0)
    tourn_c = tourn_weighted.groupby(tourn["playername"]).sum() * tourn_scale
    tourn_w = (
        (tourn["w_eff"] * tourn["part_frac"] * tourn_scale)
        .groupby(tourn["playername"])
        .sum()
    )

    # Per-player TOTAL accumulation weight = Σ weight_g over all games (the same weights that
    # built total_score = Σ score_g·weight_g). It's the denominator for a scale-comparable
    # WEIGHTED per-game average (total_score / total_weight): high-stakes games count more,
    # but dividing by the total weight keeps it comparable across leagues/schedules.
    total_weight = reg_w.add(plf_w, fill_value=0.0).add(tourn_w, fill_value=0.0)

    rename = {
        "baseline_term": "base_pts",
        "contribution_term": "contrib_pts",
        "win_bonus": "wbonus_pts",
    }
    rename.update(
        {f"{s}_term": f"{s[2:]}_pts" for s in _SOURCES}
    )  # c_kills_term -> kills_pts, ...
    src = (
        reg_c.add(plf_c, fill_value=0.0)
        .add(tourn_c, fill_value=0.0)
        .rename(columns=rename)
    )
    src["total_score"] = src[["base_pts", "contrib_pts", "wbonus_pts"]].sum(axis=1)

    # Per-GAME credit: each game's exact share of total_score, so LPS can be split by anything
    # game-level (champion played, ...). A series' points are its games' MEAN comps x the
    # fractional credit x the series weight, so a game carries 1/n of that (n = the player's games
    # in the series): baseline x base_frac + volume x part_frac, x series weight / n. Summed per
    # player this reproduces total_score (before career's per-year schedule/era scalars).
    sw = pd.concat(
        [
            reg_sw.assign(w=reg_sw["w"] * weights.w_regular, phase="regular"),
            plf_sw.assign(w=plf_sw["w"] * weights.w_playoff, phase="playoff"),
            tourn[["playername", "seriesid"]].assign(
                w=tourn["w_eff"] * tourn_scale, phase="tournament"
            ),
        ],
        ignore_index=True,
    )
    gcols = ["playername", "seriesid", "phase", "gameid", "result"]
    gcols += [c for c in ("side", "position") if c in m.columns]
    gm = m[gcols + ["baseline_term", "contribution_term", "win_bonus"]].merge(
        sw, on=["playername", "seriesid", "phase"]
    )
    gm = gm.merge(
        _credit.drop_duplicates(["playername", "seriesid"]),
        on=["playername", "seriesid"],
        how="left",
    )
    n_in_series = gm.groupby(["playername", "seriesid", "phase"])["gameid"].transform(
        "size"
    )
    gm["credit"] = (
        gm["w"].astype(float)
        * (
            gm["baseline_term"].fillna(0.0) * gm["base_frac"].fillna(0.0)
            + (gm["contribution_term"].fillna(0.0) + gm["win_bonus"].fillna(0.0))
            * gm["part_frac"].fillna(1.0)
        )
        / n_in_series
    )
    game_credit = gm[[c for c in gcols if c != "seriesid"] + ["credit"]]
    _chk = game_credit.groupby("playername")["credit"].sum()
    _gap = (_chk - src["total_score"].reindex(_chk.index).fillna(0.0)).abs().max()
    if np.isfinite(_gap) and _gap > 1e-6:
        logging.warning(f"[ratings] {year}: per-game credit off total_score by {_gap:.2e}")

    # Phase totals sum only the real score components (baseline/contrib/win_bonus) -- NOT
    # the source-decomposition terms (which decompose contribution).
    score_comps = ["baseline_term", "contribution_term", "win_bonus"]
    phase_tot = pd.DataFrame(
        {
            "reg_pts": reg_c[score_comps].sum(axis=1),
            "playoff_pts": plf_c[score_comps].sum(axis=1),
            "tourn_pts": tourn_c[score_comps].sum(axis=1),
        }
    )

    # Per-tournament breakdown: each tournament's contribution (they sum to tourn_pts).
    tourn = tourn.assign(_tsc=tourn[score_comps].sum(axis=1) * tourn["w_eff"])
    by_tourn = (
        tourn.groupby(["playername", "game_label"])["_tsc"]
        .sum()
        .unstack(fill_value=0.0)
        * tourn_scale
    )
    by_tourn.columns = [f"{c}_pts" for c in by_tourn.columns]
    tourn_cols = [
        f"{lbl}_pts"
        for lbl in sorted(tw, key=lambda k: -tw[k])
        if f"{lbl}_pts" in by_tourn.columns
    ]

    meta = matches.groupby("playername").agg(
        team=("teamname", _mode),
        league=("own_league", _mode),
        position=("position", _mode),
        games=("score", "size"),
        win_rate=("result", "mean"),
        reg_games=("phase", lambda s: int((s == "regular").sum())),
        playoff_games=("phase", lambda s: int((s == "playoff").sum())),
        tourn_games=("phase", lambda s: int((s == "tournament").sum())),
    )

    # Per-phase contribution averages — raw net_contribution (phase-weight-agnostic).
    # reg: plain mean. playoff: plain mean. intl (tournament): stage-weighted mean so
    # Finals/SF/QF games count more than group-stage games.
    reg_contrib_pg = (
        matches[matches["phase"] == "regular"]
        .groupby("playername")["net_contribution"]
        .mean()
        .rename("reg_contrib_pg")
    )
    playoff_contrib_pg = (
        matches[matches["phase"] == "playoff"]
        .groupby("playername")["net_contribution"]
        .mean()
        .rename("playoff_contrib_pg")
    )
    _intl = matches[matches["phase"] == "tournament"]
    if "stage_weight" in _intl.columns and _intl["stage_weight"].gt(0).any():
        intl_contrib_pg = (
            _intl.groupby("playername")
            .apply(
                lambda g: float(
                    np.average(g["net_contribution"], weights=g["stage_weight"])
                )
                if g["stage_weight"].sum() > 0
                else float(g["net_contribution"].mean())
            )
            .rename("intl_contrib_pg")
        )
    else:
        intl_contrib_pg = (
            _intl.groupby("playername")["net_contribution"]
            .mean()
            .rename("intl_contrib_pg")
        )

    r = (
        meta.join(src)
        .join(phase_tot)
        .join(by_tourn)
        .join(reg_contrib_pg)
        .join(playoff_contrib_pg)
        .join(intl_contrib_pg)
    )
    r["total_weight"] = total_weight
    pts = (
        [
            "base_pts",
            "contrib_pts",
            "wbonus_pts",
            "total_score",
            "reg_pts",
            "playoff_pts",
            "tourn_pts",
            "total_weight",
        ]
        + [f"{s[2:]}_pts" for s in _SOURCES]
        + tourn_cols
    )
    # Cast to float BEFORE fillna: all-tournament years (2011-2012) leave the empty regular/
    # playoff accumulators as object dtype, which would make fillna silently downcast (a pandas
    # FutureWarning). Coercing first keeps fillna on numeric columns.
    r[pts] = r[pts].astype("float64").fillna(0.0)

    r = r[r["games"] >= min_games].sort_values("total_score", ascending=False)
    r.attrs["n_ref"] = n_ref
    r.attrs["tournament_weights"] = tw
    r.attrs["tournament_cols"] = tourn_cols
    r.attrs["intl_weight"] = intl_weight
    r.attrs["game_credit"] = game_credit  # per-(player, game) LPS share, see above
    return r


_LANE_NAMES = {
    "top": "TOP",
    "jng": "JUNGLE",
    "mid": "MID",
    "bot": "BOT",
    "sup": "SUPPORT",
}


def _print_outliers(matches: pd.DataFrame, n: int = 5) -> None:
    """Single-game outliers with the gameid shown so each can be verified."""
    import logging

    def show(sel: pd.DataFrame, col: str) -> None:
        metric = col.replace("contribution_term", "contrib").replace(
            "win_bonus", "wbonus"
        )
        for _, r in sel.iterrows():
            res = "W" if r["result"] == 1 else "L"
            date = str(r.get("date", ""))[:10]
            g = r.get("game", None)
            gtag = f"G{int(g)}" if pd.notna(g) else "--"
            matchup = (
                f"{str(r['teamname'])[:16]} vs {str(r.get('opp_teamname', ''))[:16]}"
            )
            logging.info(
                f"      {date}  {str(r['game_label']):<5} {matchup:<38} {gtag:<3} "
                f"{r['position']:<4} {r['playername']:<12} {res} p={r['p_model']:.2f}  "
                f"{metric}={r[col]:+.3f}"
            )

    logging.info("    Largest single-game contribution (net win-prob added):")
    show(matches.nlargest(n, "contribution_term"), "contribution_term")
    logging.info("    Worst single-game contribution (net win-prob lost):")
    show(matches.nsmallest(n, "contribution_term"), "contribution_term")
    # win_bonus is team-level (same for all 5), so dedupe to one row per team-game.
    wb = matches.drop_duplicates(subset=["gameid", "side"])
    logging.info(
        "    Biggest upset wins (win_bonus -- won when model expected a loss):"
    )
    show(wb.nlargest(n, "win_bonus"), "win_bonus")
    logging.info("    Biggest chokes (win_bonus -- lost when model expected a win):")
    show(wb.nsmallest(n, "win_bonus"), "win_bonus")


# Default weights, tuned to best match a fan consensus of 2024's best players across all five
# lanes (grid search over alpha/lambda/beta/intl_weight; mean Spearman ~0.79, Pearson ~0.76):
#   - beta=0: the win-bonus (rewarding wins the model rated as upsets) adds team-level noise
#     that fans don't weight -- zeroing it improved every combo.
#   - alpha=0.75, lam=2: baseline vs contribution ratio in the broad optimum (fit is flat over
#     ratios ~0.5-2 once beta=0); alpha lowered to 0.75 to weight contribution a bit more.
#     intl_weight=2 (the build_player_ratings default) was optimal.
_DEMO_WEIGHTS = ScoreWeights(alpha=0.75, lam=1.0, beta=0.25)
_MAJOR = {"LCK", "LPL", "LEC", "LCS"}


def explain_upsets(
    year: int = 2024, n: int = 5, weights: Optional[ScoreWeights] = None
) -> None:
    """
    For the top-n upset wins, decompose the winning team's Model 2 win-prob so you can see
    which lanes/stats made the model rate them a near-certain loss -- and sanity-check that
    the upset is real, not a data artifact.
    """
    import logging

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    weights = weights or _DEMO_WEIGHTS

    cfg = WinProbabilityConfig(years=(year,))
    df = load_oracle_years(cfg.years)
    bundle = train_win_prob_bundle(cfg)
    team_df = (
        build_team_features(df, cfg)
        .reset_index(drop=True)
        .set_index(["gameid", "side"])
    )

    m = build_player_match_scores(year, weights=weights)
    wb = m.drop_duplicates(subset=["gameid", "side"]).nlargest(n, "win_bonus")

    logging.info(
        f"\n=== Why the top {n} upsets had low p_model (winning team's OWN box score) ==="
    )
    for _, r in wb.iterrows():
        row = team_df.loc[(r["gameid"], r["side"])]
        ex = explain_team_game(row, bundle)
        g = r.get("game", None)
        gtag = f"G{int(g)}" if pd.notna(g) else "--"
        logging.info(
            f"\n  {str(r.get('date', ''))[:10]}  {r['game_label']}  "
            f"{r['teamname']} vs {r['opp_teamname']}  {gtag}  -> WON at p={ex['p']:.3f} (z={ex['z']:+.2f})"
        )
        logging.info(
            f"    {'lane':<6} {'K':>3} {'D':>3} {'A':>3} {'dmg':>6}  {'log-odds':>8}"
        )
        for role in ROLES:
            logging.info(
                f"    {role:<6} {row.get(f'{role}_kills_nonfb', 0):>3.0f} "
                f"{row.get(f'{role}_deaths_nonfb', 0):>3.0f} {row.get(f'{role}_assists_nonfb', 0):>3.0f} "
                f"{row.get(f'{role}_damagetochampions', 0):>6.0f}  {ex['lane_logodds'][role]:>+8.2f}"
            )


def _demo(year: int = 2024, per_lane: int = 20) -> None:
    import logging

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    w = _DEMO_WEIGHTS
    matches = build_player_match_scores(year, weights=w)
    ratings = build_player_ratings(year, weights=w, matches=matches)
    n_ref = ratings.attrs.get("n_ref", 0)
    tw = ratings.attrs.get("tournament_weights", {})

    tw_str = ", ".join(
        f"{k}={v:.2f}" for k, v in sorted(tw.items(), key=lambda kv: -kv[1])
    )
    logging.info(
        f"\n{year} player ratings  (alpha={w.alpha}, lam={w.lam}, beta={w.beta}, min 15 games)\n"
        f"Phases: regular & playoffs accumulate by MATCH (Bo3/Bo5 averaged to one unit; a "
        f"2-0 counts the same as a 2-1 at equal per-game avg), normalized so a full run per "
        f"league ~ 1 unit (N_ref={n_ref:.0f} matches); subs score less.\n"
        f"Tournament weights (sqrt-scaled avg viewership, Worlds=1): {tw_str}.\n"
        f"Score broken down by phase: reg + plf + (each tournament) = total."
    )

    tourn_cols = ratings.attrs.get("tournament_cols", [])
    tourn_hdr = "".join(f"{c.replace('_pts', ''):>7}" for c in tourn_cols)
    for lane in ROLES:
        sub = ratings[ratings["position"] == lane].head(per_lane)
        logging.info(f"\n=== {_LANE_NAMES[lane]} (top {per_lane}) ===")
        header = (
            f"  {'#':>2}  {'player':<13} {'team':<15} {'lg':<4} {'reg':>6} {'plf':>6}"
            f"{tourn_hdr} {'total':>7} {'wr':>4}"
        )
        logging.info(header)
        logging.info("  " + "-" * (len(header) - 2))
        for i, (name, r) in enumerate(sub.iterrows(), 1):
            tvals = "".join(f"{r[c]:>7.1f}" for c in tourn_cols)
            logging.info(
                f"  {i:>2}  {name:<13} {str(r['team'])[:14]:<15} {r['league']:<4} "
                f"{r['reg_pts']:>6.1f} {r['playoff_pts']:>6.1f}{tvals} "
                f"{r['total_score']:>7.2f} {r['win_rate']:>4.0%}"
            )

    logging.info("\n\n=== Single-game outliers: OVERALL (all scored games) ===")
    _print_outliers(matches)
    major_intl = matches[
        matches["own_league"].isin(_MAJOR) | (matches["phase"] == "tournament")
    ]
    logging.info(
        "\n=== Single-game outliers: MAJOR REGIONS (LCK/LPL/LEC/LCS) + INTERNATIONAL ==="
    )
    _print_outliers(major_intl)


if __name__ == "__main__":
    _demo()
