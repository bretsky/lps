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
(use_model1=False falls back to the global mean). The team_fb term is not yet credited to
any player. Baseline uses the OPPONENT league's Elo (domestic: your own league).
"""

from __future__ import annotations

import logging
import math
from typing import Optional

import numpy as np
import pandas as pd

from .config import DATA_DIR
from .contribution import (
    LANE_STATS, ROLES, contributions_for_frame, explain_team_game, train_win_prob_bundle,
)
from .expected_stats import expected_reference_frame
from .io_oracle import load_oracle_years
from .scoring import REFERENCE_ELO, ScoreWeights, load_league_elos
from .team_leagues import build_team_game_table, resolve_home_leagues
from .win_probability import WinProbabilityConfig, build_team_features

# Cache for the weight-invariant per-match feature frame (trains the models). Scaling /
# weight changes reuse this instead of retraining. Bust it (force_recompute=True) when
# the models or features change.
_CACHE_DIR = DATA_DIR / "cache"
_INVARIANT_COLS = [
    "gameid", "game", "date", "side", "position", "playername", "teamname", "opp_teamname",
    "own_league", "opp_league", "is_international", "game_label", "phase", "result",
    "p_model", "net_contribution", "c_kills", "c_deaths", "c_assists", "c_damage",
    "c_fb", "baseline",
]
# Per-source components of net_contribution (they sum to it): kills/deaths/assists/damage
# from the lane, plus first blood (credited to the kill-getter / victim).
_SOURCES = ["c_kills", "c_deaths", "c_assists", "c_damage", "c_fb"]

# Tournament importance weights derived from average peak concurrent viewership over the
# last 3 years -- an objective proxy for how much each tournament matters. Keys are Oracle
# game_labels; update as new data arrives. FST (First Stand) debuted 2025 so has 2 years.
_TOURNAMENT_VIEWERSHIP = {
    "WLDs":  [6752585, 6941610, 6402760],   # Worlds
    "MSI":   [2315920, 3447582, 2829728],   # Mid-Season Invitational
    "EWC":   [1477470, 1208123, 1123619],   # Esports World Cup
    "FST":   [1106126, 1500730],            # First Stand (2025+; Oracle label to confirm)
    "KeSPA": [173449, 110196, 66335],       # KeSPA Cup (domestic, KR)
    "DCup":  [55751, 69654, 60238],         # Demacia Cup (domestic, CN)
}


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
    return {k: round(x / top, 3) for k, x in f.items()}


def _player_lane_table(df: pd.DataFrame) -> pd.DataFrame:
    """One row per (gameid, side, position): player, team, and first-blood roles."""
    cols = ["gameid", "side", "position", "playername", "teamname",
            "firstbloodkill", "firstbloodvictim"]
    d = df[[c for c in cols if c in df.columns]].copy()
    d["position"] = (
        d["position"].astype(str).str.lower()
        .replace({"jungle": "jng", "adc": "bot", "support": "sup"})
    )
    d = d[d["position"].isin(ROLES)]
    agg = dict(playername=("playername", "first"), teamname=("teamname", "first"))
    if "firstbloodkill" in d.columns:
        agg["firstbloodkill"] = ("firstbloodkill", "first")
    if "firstbloodvictim" in d.columns:
        agg["firstbloodvictim"] = ("firstbloodvictim", "first")
    return d.groupby(["gameid", "side", "position"], as_index=False).agg(**agg)


def _match_features(year: int, use_model1: bool = True, force_recompute: bool = False) -> pd.DataFrame:
    """
    Weight-INVARIANT per-(player, match) features: net_contribution, baseline, p_model,
    phase, league context. This is the expensive part (trains Model 1 + Model 2), so it's
    cached to disk; scaling/weight changes reuse it. Set force_recompute=True after any
    model/feature change.
    """
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = _CACHE_DIR / f"match_features_{year}_m1{int(use_model1)}.pkl"
    if path.exists() and not force_recompute:
        return pd.read_pickle(path)

    cfg = WinProbabilityConfig(years=(year,))
    df = load_oracle_years(cfg.years)

    # Model 2 + per-team-game contributions, referenced against Model 1 expected values.
    bundle = train_win_prob_bundle(cfg)
    team_df = build_team_features(df, cfg).reset_index(drop=True)
    expected_df = expected_reference_frame(df, team_df) if use_model1 else None
    contrib = contributions_for_frame(team_df, bundle, expected_df=expected_df)

    # Long form: one row per (team-game, lane). net_contribution is that lane's per-lane
    # LOO (unchanged). We SPLIT it across its four stats by each stat's log-odds share --
    # pure interpretability, so c_kills+c_deaths+c_assists+c_damage == net_contribution.
    frames = []
    for role in ROLES:
        sub = contrib[["gameid", "side", "result", "p_model", "team_fb"]].copy()
        sub["position"] = role
        net = contrib[role].to_numpy()
        sub["net_contribution"] = net
        Dz = np.stack([contrib[f"dz_{role}_{s}"].to_numpy() for s in LANE_STATS], axis=1)
        dz_sum = Dz.sum(axis=1)
        frac = np.where(np.abs(dz_sum)[:, None] > 1e-9, Dz / dz_sum[:, None], 0.25)
        split = net[:, None] * frac
        sub["c_kills"], sub["c_deaths"], sub["c_assists"], sub["c_damage"] = (
            split[:, 0], split[:, 1], split[:, 2], split[:, 3]
        )
        frames.append(sub)
    long = pd.concat(frames, ignore_index=True)

    # Attach player names, team, and first-blood roles.
    long = long.merge(_player_lane_table(df), on=["gameid", "side", "position"], how="left")

    # First blood, folded into net_contribution: the team's FB term is credited to the
    # player who got the first-blood kill (+) or was the victim (-). LPL lacks
    # firstbloodvictim, so its non-FB side's debit is left unattributed.
    fbk = long["firstbloodkill"].fillna(0).to_numpy() if "firstbloodkill" in long.columns else np.zeros(len(long))
    fbv = long["firstbloodvictim"].fillna(0).to_numpy() if "firstbloodvictim" in long.columns else np.zeros(len(long))
    long["c_fb"] = np.where((fbk == 1) | (fbv == 1), long["team_fb"].to_numpy(), 0.0)
    long["net_contribution"] = long["net_contribution"] + long["c_fb"]
    tg = build_team_game_table(df, resolve_home_leagues(df))
    tg_cols = ["gameid", "side", "opp_teamname", "own_league", "opp_league",
               "is_international", "game_label"]
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
        is_rated, np.where(po == 1, "playoff", "regular"), "tournament",
    )

    # Keep only scorable rows (baseline computable + player known).
    long = long.dropna(subset=["baseline", "playername"])
    inv = long[[c for c in _INVARIANT_COLS if c in long.columns]].reset_index(drop=True)
    inv.to_pickle(path)
    return inv


def build_player_match_scores(
    year: int,
    weights: Optional[ScoreWeights] = None,
    use_model1: bool = True,
    force_recompute: bool = False,
) -> pd.DataFrame:
    """
    One row per (player, match) with the full score decomposition. Applies the (cheap)
    weights on top of the cached weight-invariant features:

        score = alpha*baseline + lam*net_contribution + beta*(result - p_model)

    Columns add: baseline_term, contribution_term, win_bonus, score.
    """
    if weights is None:
        weights = ScoreWeights()

    m = _match_features(year, use_model1=use_model1, force_recompute=force_recompute).copy()
    m["baseline_term"] = weights.alpha * m["baseline"]
    m["contribution_term"] = weights.lam * m["net_contribution"]
    m["win_bonus"] = weights.beta * (m["result"] - m["p_model"])
    m["score"] = m["baseline_term"] + m["contribution_term"] + m["win_bonus"]
    # Per-source weighted terms (kills/deaths/assists/damage/fb sum to contribution_term).
    for s in _SOURCES:
        m[f"{s}_term"] = weights.lam * m[s]
    return m


def build_player_ratings(
    year: int,
    weights: Optional[ScoreWeights] = None,
    rated_only: bool = True,
    min_games: int = 15,
    use_model1: bool = True,
    regular_season_ref_games: Optional[float] = None,
    intl_weight: float = 2.0,
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
        matches = build_player_match_scores(year, weights, use_model1=use_model1,
                                            force_recompute=force_recompute)
    if rated_only:
        matches = matches[matches["own_league"].isin(rated)]

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

    def _to_series(phase_df: pd.DataFrame) -> pd.DataFrame:
        """One row per (player, series): the comps AVERAGED over the series' games."""
        if phase_df.empty:
            return pd.DataFrame(columns=["playername", "seriesid", "own_league", "game_label"] + comps)
        agg = {c: (c, "mean") for c in comps}
        agg.update(own_league=("own_league", "first"), game_label=("game_label", "first"),
                   teamname=("teamname", "first"))
        return phase_df.groupby(["playername", "seriesid"], as_index=False).agg(**agg)

    reg = _to_series(m[m["phase"] == "regular"])
    plf = _to_series(m[m["phase"] == "playoff"])
    tourn = _to_series(m[m["phase"] == "tournament"])
    tourn_games = m[m["phase"] == "tournament"]   # game-level, kept only for champion detection

    n_ref = (   # reference volume = mean regular-season MATCHES (series) per player
        regular_season_ref_games
        if regular_season_ref_games is not None
        else (reg.groupby("playername").size().mean() if len(reg) else 0.0)
    )

    # Tournament weights: default = viewership-based (Worlds=1.0). Overridable. Any
    # tournament label without a weight is warned and counted as 0.
    tw = _viewership_weights() if tournament_weights is None else dict(tournament_weights)
    unknown = sorted(set(tourn["game_label"].unique()) - set(tw))
    if unknown:
        logging.warning(f"[tournaments] no weight for {unknown}; counting them as 0 -- add viewership.")
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
        lbl: tourn_games.loc[(tourn_games["game_label"] == lbl) & (tourn_games["teamname"] == team),
                             "seriesid"].nunique()
        for lbl, team in champ.items()
    }
    player_matches = tourn.groupby(["playername", "game_label"])["seriesid"].transform("size")
    cap = tourn["game_label"].map(champ_matches)
    norm = cap.where(cap > 0, 1.0)  # per-tournament length normalizer (champion's match count)
    tourn["w_eff"] = tourn["w"] * np.minimum(1.0, cap / player_matches).fillna(1.0) / norm

    # Normalize to the deepest capped-weighted run so the champion gets a full weighted phase.
    weighted_run = tourn.groupby("playername")["w_eff"].sum()
    max_run = weighted_run.max() if len(weighted_run) else 1.0
    tourn_scale = (intl_weight * n_ref / max_run) if max_run else 0.0

    # Regular season and playoffs both ACCUMULATE (a one-match sub scores far less than a
    # full-run player), but each MATCH is weighted by N_ref / (deepest run in matches in that
    # league) so a FULL run ~ one phase unit in every region -- equalizing schedule/bracket
    # length across regions without removing the volume signal within one.
    def _accumulate(series_df: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
        d = series_df.copy()
        if d.empty:
            return pd.DataFrame(columns=comps), pd.Series(dtype=float)
        run = d.groupby(["own_league", "playername"]).size().groupby(level="own_league").max()
        d["w"] = n_ref / d["own_league"].map(run)
        comp_sums = d[comps].mul(d["w"], axis=0).groupby(d["playername"]).sum()
        weight_sums = d["w"].groupby(d["playername"]).sum()  # per-player total accumulation weight
        return comp_sums, weight_sums

    reg_c, reg_w = _accumulate(reg)
    plf_c, plf_w = _accumulate(plf)

    # Tournaments: accumulate per MATCH weighted by tournament importance (w_eff = weight x cap),
    # normalized to the deepest capped-weighted run.
    tourn_weighted = tourn[comps].mul(tourn["w_eff"], axis=0)
    tourn_c = tourn_weighted.groupby(tourn["playername"]).sum() * tourn_scale
    tourn_w = (tourn["w_eff"] * tourn_scale).groupby(tourn["playername"]).sum()

    # Per-player TOTAL accumulation weight = Σ weight_g over all games (the same weights that
    # built total_score = Σ score_g·weight_g). It's the denominator for a scale-comparable
    # WEIGHTED per-game average (total_score / total_weight): high-stakes games count more,
    # but dividing by the total weight keeps it comparable across leagues/schedules.
    total_weight = reg_w.add(plf_w, fill_value=0.0).add(tourn_w, fill_value=0.0)

    rename = {"baseline_term": "base_pts", "contribution_term": "contrib_pts", "win_bonus": "wbonus_pts"}
    rename.update({f"{s}_term": f"{s[2:]}_pts" for s in _SOURCES})  # c_kills_term -> kills_pts, c_fb_term -> fb_pts
    src = reg_c.add(plf_c, fill_value=0.0).add(tourn_c, fill_value=0.0).rename(columns=rename)
    src["total_score"] = src[["base_pts", "contrib_pts", "wbonus_pts"]].sum(axis=1)

    # Phase totals sum only the real score components (baseline/contrib/win_bonus) -- NOT
    # the source-decomposition terms (which decompose contribution) or the fb diagnostic.
    score_comps = ["baseline_term", "contribution_term", "win_bonus"]
    phase_tot = pd.DataFrame({
        "reg_pts": reg_c[score_comps].sum(axis=1),
        "playoff_pts": plf_c[score_comps].sum(axis=1),
        "tourn_pts": tourn_c[score_comps].sum(axis=1),
    })

    # Per-tournament breakdown: each tournament's contribution (they sum to tourn_pts).
    tourn = tourn.assign(_tsc=tourn[score_comps].sum(axis=1) * tourn["w_eff"])
    by_tourn = (
        tourn.groupby(["playername", "game_label"])["_tsc"].sum().unstack(fill_value=0.0) * tourn_scale
    )
    by_tourn.columns = [f"{c}_pts" for c in by_tourn.columns]
    tourn_cols = [f"{lbl}_pts" for lbl in sorted(tw, key=lambda k: -tw[k])
                  if f"{lbl}_pts" in by_tourn.columns]

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

    r = meta.join(src).join(phase_tot).join(by_tourn)
    r["total_weight"] = total_weight
    pts = (["base_pts", "contrib_pts", "wbonus_pts", "total_score", "reg_pts", "playoff_pts",
            "tourn_pts", "total_weight"] + [f"{s[2:]}_pts" for s in _SOURCES] + tourn_cols)
    r[pts] = r[pts].fillna(0.0)

    r = r[r["games"] >= min_games].sort_values("total_score", ascending=False)
    r.attrs["n_ref"] = n_ref
    r.attrs["tournament_weights"] = tw
    r.attrs["tournament_cols"] = tourn_cols
    r.attrs["intl_weight"] = intl_weight
    return r


_LANE_NAMES = {"top": "TOP", "jng": "JUNGLE", "mid": "MID", "bot": "BOT", "sup": "SUPPORT"}


def _print_outliers(matches: pd.DataFrame, n: int = 5) -> None:
    """Single-game outliers with the gameid shown so each can be verified."""
    import logging

    def show(sel: pd.DataFrame, col: str) -> None:
        metric = col.replace("contribution_term", "contrib").replace("win_bonus", "wbonus")
        for _, r in sel.iterrows():
            res = "W" if r["result"] == 1 else "L"
            date = str(r.get("date", ""))[:10]
            g = r.get("game", None)
            gtag = f"G{int(g)}" if pd.notna(g) else "--"
            matchup = f"{str(r['teamname'])[:16]} vs {str(r.get('opp_teamname', ''))[:16]}"
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
    logging.info("    Biggest upset wins (win_bonus -- won when model expected a loss):")
    show(wb.nlargest(n, "win_bonus"), "win_bonus")
    logging.info("    Biggest chokes (win_bonus -- lost when model expected a win):")
    show(wb.nsmallest(n, "win_bonus"), "win_bonus")


# Default demo weights: baseline down-weighted (alpha) so contribution/win-bonus matter more.
_DEMO_WEIGHTS = ScoreWeights(alpha=0.5, lam=3.0, beta=1.0)
_MAJOR = {"LCK", "LPL", "LEC", "LCS"}


def explain_upsets(year: int = 2024, n: int = 5, weights: Optional[ScoreWeights] = None) -> None:
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
    team_df = build_team_features(df, cfg).reset_index(drop=True).set_index(["gameid", "side"])

    m = build_player_match_scores(year, weights=weights)
    wb = m.drop_duplicates(subset=["gameid", "side"]).nlargest(n, "win_bonus")

    logging.info(f"\n=== Why the top {n} upsets had low p_model (winning team's OWN box score) ===")
    for _, r in wb.iterrows():
        row = team_df.loc[(r["gameid"], r["side"])]
        ex = explain_team_game(row, bundle)
        g = r.get("game", None)
        gtag = f"G{int(g)}" if pd.notna(g) else "--"
        logging.info(
            f"\n  {str(r.get('date', ''))[:10]}  {r['game_label']}  "
            f"{r['teamname']} vs {r['opp_teamname']}  {gtag}  -> WON at p={ex['p']:.3f} (z={ex['z']:+.2f})"
        )
        logging.info(f"    {'lane':<6} {'K':>3} {'D':>3} {'A':>3} {'dmg':>6}  {'log-odds':>8}")
        for role in ROLES:
            logging.info(
                f"    {role:<6} {row.get(f'{role}_kills_nonfb', 0):>3.0f} "
                f"{row.get(f'{role}_deaths_nonfb', 0):>3.0f} {row.get(f'{role}_assists_nonfb', 0):>3.0f} "
                f"{row.get(f'{role}_damagetochampions', 0):>6.0f}  {ex['lane_logodds'][role]:>+8.2f}"
            )
        fb = int(row.get("teamfirstblood", 0))
        logging.info(
            f"    firstblood: {'got' if fb == 1 else 'lost'}    team-feature log-odds "
            f"{sum(ex['team_logodds'].values()):+.2f}"
        )


def _demo(year: int = 2024, per_lane: int = 20) -> None:
    import logging

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    w = _DEMO_WEIGHTS
    matches = build_player_match_scores(year, weights=w)
    ratings = build_player_ratings(year, weights=w, matches=matches)
    n_ref = ratings.attrs.get("n_ref", 0)
    tw = ratings.attrs.get("tournament_weights", {})

    tw_str = ", ".join(f"{k}={v:.2f}" for k, v in sorted(tw.items(), key=lambda kv: -kv[1]))
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
        header = (f"  {'#':>2}  {'player':<13} {'team':<15} {'lg':<4} {'reg':>6} {'plf':>6}"
                  f"{tourn_hdr} {'total':>7} {'wr':>4}")
        logging.info(header)
        logging.info("  " + "-" * (len(header) - 2))
        for i, (name, r) in enumerate(sub.iterrows(), 1):
            tvals = "".join(f"{r[c]:>7.1f}" for c in tourn_cols)
            logging.info(
                f"  {i:>2}  {name:<13} {str(r['team'])[:14]:<15} {r['league']:<4} "
                f"{r['reg_pts']:>6.1f} {r['playoff_pts']:>6.1f}{tvals} "
                f"{r['total_score']:>7.2f} {r['win_rate']:>4.0%}"
            )

    # First blood (now folded into the score, part of contrib): impact + top beneficiaries.
    fbd = matches[matches["c_fb"] != 0]
    got = fbd.loc[fbd["c_fb"] > 0, "c_fb"]
    lost = fbd.loc[fbd["c_fb"] < 0, "c_fb"]
    logging.info("\n\n=== First blood (folded into contrib) ===")
    logging.info(
        f"  Win-prob impact per game: getting first blood {got.mean() * 100:+.2f}pp (killer), "
        f"being the victim {lost.mean() * 100:+.2f}pp."
    )
    logging.info("  Top 10 by cumulative first-blood points (fb_pts, part of contrib/total):")
    for name, r in ratings.sort_values("fb_pts", ascending=False).head(10).iterrows():
        logging.info(f"    {name:<13} {str(r['team'])[:16]:<16} {r['position']:<4} "
                     f"fb_pts={r['fb_pts']:+5.2f}   (total={r['total_score']:.1f})")

    logging.info("\n\n=== Single-game outliers: OVERALL (all scored games) ===")
    _print_outliers(matches)
    major_intl = matches[matches["own_league"].isin(_MAJOR) | (matches["phase"] == "tournament")]
    logging.info("\n=== Single-game outliers: MAJOR REGIONS (LCK/LPL/LEC/LCS) + INTERNATIONAL ===")
    _print_outliers(major_intl)


if __name__ == "__main__":
    _demo()
