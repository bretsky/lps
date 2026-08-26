"""
Cross-league player scoring.

Combines three pieces into a per-player, per-match "points" score:

    score_i = b_i + lambda * net_contribution_i + beta * (result - p_model)
              |_____|   |__________________|         |__________________|
              league     individual play             beating expectations
              baseline

- b_i (league baseline): the OPPONENT league's strength, i.e. its expected win rate
  against a theoretical 1000-Elo league, expected_score(R_opponent, 1000). It reflects
  the quality of competition faced. Domestically the opponent is your own league, so it
  reduces to expected_score(R_own, 1000); internationally it uses the opponent's league.
  This is the cross-league parity anchor. With Model 1's "expected" reference set to the
  MEAN, a league-average player has net_contribution ~= 0 and therefore earns exactly b_i.

- net_contribution_i: how much this player's actual performance moved their team's
  win probability relative to an expected (mean) player, in win-probability units.
  Produced by the win-probability pipeline (Model 1 + Model 2). Plugged in here as
  an input; see the module TODO for the wiring.

- beta * (result - p_model): a zero-mean "win bonus" that rewards winning games the
  performance model did NOT predict (result=1/0, p_model = Model 2 team win prob).
  If the model is calibrated, E[result - p_model] = 0, so this does not inflate
  season averages -- it only rewards beating expectations.

Scope (current): only leagues that have an Elo in info/ending_elos_<year>.csv are
scored (the ~8 that play internationally). Minor/academy leagues have no baseline
and are skipped. International events (MSI/Worlds/EWC) need each team's home league
resolved and are deferred.
"""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

import numpy as np

from .config import INFO_DIR

logging.basicConfig(level=logging.INFO, format="%(message)s")


# Reference Elo for the "theoretical average league" the baseline is measured against.
REFERENCE_ELO = 1000.0


@dataclass
class ScoreWeights:
    """Tunable weights for the per-match scoring formula:

        score = baseline**region_exp_<phase> * (alpha + lam*contribution + beta*winbonus)

    where baseline = winrate(opponent league vs the year's peak region). The baseline acts as a
    REGION SCALING FACTOR on the whole per-game value (raised to a per-phase exponent), so a
    weak-region season is worth less; a higher exponent punishes weaker regions harder (fixes
    over-valuing non-eastern domestic play). alpha is now a FLAT base credit (win-gated downstream
    via base_frac), NOT a multiplier on baseline. exp=0 removes region scaling entirely; exp=1 =
    plain winrate; exp>1 = steeper."""

    alpha: float = 1.0  # flat base credit per (winning) game, before the region factor
    lam: float = 1.0  # weight on individual net contribution
    beta: float = 0.25  # weight on the win bonus (result - p_model)
    # Region factor: baseline (winrate vs the year's peak region) ^ region_exp scales the whole
    # per-game value. A SINGLE constant exponent for all phases; higher => weaker regions punished
    # harder (exp=0 removes region scaling, exp=1 = plain winrate). Consensus tuning preferred 2.0
    # (plain winrate over-values lesser/non-eastern regions); set to 1.5 to soften that penalty.
    region_exp: float = 1.5
    # Per-PHASE point multipliers (like the era multipliers): each phase's accumulated points are
    # scaled by its multiplier. Regular season is the reference (w_regular, usually 1.0); playoffs by
    # w_playoff. The TOURNAMENT phase is scaled by build_player_ratings' existing `intl_weight`.
    w_regular: float = 1.0
    w_playoff: float = 1.0


def expected_score(elo_a: float, elo_b: float) -> float:
    """
    Probability that a team/league of rating elo_a beats one of rating elo_b.

    Standard 400-point logistic Elo curve (same formula as regional_elo.py).
    """
    return 1.0 / (1.0 + 10 ** ((elo_b - elo_a) / 400.0))


def peak_elo(elos: dict[str, float]) -> float:
    """The strongest region's Elo that year -- the reference the baseline is measured against
    (so each era's best region anchors at 0.5, rewarding it equally despite Elo inflation).
    """
    return max(elos.values()) if elos else REFERENCE_ELO


def load_league_elos(year: int, info_dir: Optional[Path] = None) -> dict[str, float]:
    """
    Load ending Elos for a year as {league: elo}.

    Reads info/ending_elos_<year>.csv (region,ending_elo,match_count). The "region"
    column holds league codes (LCK, LPL, ...), so keys are league codes.

    Returns an empty dict (and logs) if the file is missing.
    """
    if info_dir is None:
        info_dir = INFO_DIR

    csv_file = info_dir / f"ending_elos_{year}.csv"
    if not csv_file.exists():
        logging.error(f"Ending Elos file not found: {csv_file}")
        return {}

    elos: dict[str, float] = {}
    with open(csv_file, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            league = (row.get("region") or "").strip()
            elo_str = (row.get("ending_elo") or "").strip()
            if not league or not elo_str:
                continue
            try:
                elos[league] = float(elo_str)
            except ValueError:
                logging.warning(f"Invalid Elo for {league!r}: {elo_str!r}")
    return elos


def league_baseline(
    league: str,
    year: int,
    elos: Optional[dict[str, float]] = None,
    opponent_league: Optional[str] = None,
) -> Optional[float]:
    """
    Baseline points for a match = the OPPONENT league's strength, i.e. that league's
    expected win rate against the year's PEAK (strongest) region:

        baseline = expected_score(R_opponent, R_peak)

    Measuring against the peak region (rather than a fixed 1000) anchors each era's best
    region at 0.5, so players are rewarded for competing in the best region of their era
    even when absolute Elos are lower/higher across eras.

    The baseline reflects the QUALITY OF COMPETITION faced, not your own league: facing
    a strong league yields a high baseline, a weak league a low one -- which is what
    gives cross-league parity (dominating a weak league earns little; competing against
    a strong one earns a lot).

    - Domestic (opponent_league=None): your opponent is your own league, so this reduces
      to expected_score(R_own, 1000) -- the domestic case is unchanged.
    - International (opponent_league given): uses the opponent's home-league Elo.

    `league` is the player's own league and is used only as the opponent for domestic
    matches. Returns None if the opponent league has no Elo for that year.
    """
    if elos is None:
        elos = load_league_elos(year)

    # Baseline is set exclusively by the opponent's league (domestic: your own league).
    opp = opponent_league if opponent_league is not None else league
    opp_elo = elos.get(opp)
    if opp_elo is None:
        return None
    return expected_score(opp_elo, peak_elo(elos))


def apply_scored_terms(
    m, weights: "ScoreWeights", elos: dict, source_cols: Sequence[str] = ()
):
    """Compute the per-match score component columns IN PLACE on a DataFrame `m`, applying the
    region-scaled formula on top of the cached weight-invariant features (cheap; no retraining):

        baseline = winrate(opp league vs the year's PEAK region)
        factor   = baseline ** region_exp                 # region scaling (single constant exp)
        score    = factor * (alpha + lam*net_contribution + beta*(result - p_model))

    Sets: baseline, baseline_term (= factor*alpha), contribution_term, win_bonus, <s>_term for
    each source col, and score. The alpha 'baseline' credit is win-gated DOWNSTREAM in
    build_player_ratings (base_frac, winner-take-all), so here it is the full per-game credit.
    Requires columns: opp_league, phase, net_contribution, result, p_model (+ each source col).
    """
    peak = max(elos.values()) if elos else REFERENCE_ELO
    baseline = 1.0 / (1.0 + 10 ** ((peak - m["opp_league"].map(elos)) / 400.0))
    factor = np.power(baseline, weights.region_exp)  # region scaling (single exponent)
    m["baseline"] = baseline
    m["baseline_term"] = factor * weights.alpha  # flat base credit, region-scaled
    m["contribution_term"] = factor * weights.lam * m["net_contribution"]
    m["win_bonus"] = factor * weights.beta * (m["result"] - m["p_model"])
    for s in source_cols:
        m[f"{s}_term"] = factor * weights.lam * m[s]
    m["score"] = m["baseline_term"] + m["contribution_term"] + m["win_bonus"]
    return m


def score_player_match(
    *,
    league: str,
    year: int,
    net_contribution: float,
    result: int,
    p_model: float,
    opponent_league: Optional[str] = None,
    weights: Optional[ScoreWeights] = None,
    elos: Optional[dict[str, float]] = None,
) -> Optional[dict[str, float]]:
    """
    Score one player in one match.

    Args:
        league: The player's (home) league code, must match an Elo key for the year.
        year: Season year (selects the ending_elos_<year>.csv Elos).
        net_contribution: Player's win-probability contribution vs an expected player
            (win-prob units, e.g. -0.05). Comes from the win-probability pipeline.
        result: 1 if the player's team won the match, 0 if it lost.
        p_model: Model 2's predicted win probability for the player's team.
        opponent_league: For international matches, the opponent's home league code.
            The baseline is always expected_score(R_opponent, 1000) -- the opponent
            league's strength. Leave None for domestic matches (opponent = own league).
        weights: lambda / beta weights (defaults: lam=1.0, beta=0.25).
        elos: Optional preloaded {league: elo} to avoid re-reading the CSV per call.

    Returns:
        A dict with the baseline, the two adjustment terms, and the total -- or None
        if the league (or given opponent league) is out of scope (no baseline available).
    """
    if weights is None:
        weights = ScoreWeights()

    baseline = league_baseline(league, year, elos=elos, opponent_league=opponent_league)
    if baseline is None:
        return None

    # Region factor = baseline^exp.
    factor = baseline**weights.region_exp
    baseline_term = factor * weights.alpha
    contribution_term = factor * weights.lam * net_contribution
    win_bonus = factor * weights.beta * (result - p_model)
    total = baseline_term + contribution_term + win_bonus

    return {
        "baseline": baseline,
        "baseline_term": baseline_term,
        "contribution_term": contribution_term,
        "win_bonus": win_bonus,
        "total": total,
    }


def _demo(year: int = 2024) -> None:
    """Print each in-scope league's baseline, plus a worked scoring example."""
    elos = load_league_elos(year)
    if not elos:
        logging.info(f"No Elos found for {year}; nothing to show.")
        return

    peak = peak_elo(elos)
    logging.info(
        f"League baselines for {year} (expected win rate vs the peak region, Elo {int(peak)}):"
    )
    logging.info(f"  {'League':<8} {'Elo':<10} {'Baseline':<10}")
    logging.info("  " + "-" * 30)
    for league, elo in sorted(elos.items(), key=lambda kv: kv[1], reverse=True):
        b = expected_score(elo, peak)
        logging.info(f"  {league:<8} {elo:<10.1f} {b:<10.3f}")

    # Worked example: your -0.05 contribution in a 0.75-ish league, won a game the
    # model gave 60%.
    logging.info(
        "\nWorked example (LCS player, net_contribution=-0.05, won a p_model=0.60 game):"
    )
    result = score_player_match(
        league="LCS",
        year=year,
        net_contribution=-0.05,
        result=1,
        p_model=0.60,
        elos=elos,
    )
    if result is None:
        logging.info("  LCS has no baseline this year.")
    else:
        logging.info(
            f"  baseline={result['baseline']:.3f}  "
            f"+ contribution={result['contribution_term']:+.3f}  "
            f"+ win_bonus={result['win_bonus']:+.3f}  "
            f"= total={result['total']:.3f}"
        )

    # International: baseline = the OPPONENT league's strength (quality of competition).
    logging.info("\nInternational baselines (= opponent league's strength vs 1000):")
    for own, opp in [("LCK", "LLA"), ("LLA", "LCK"), ("LCK", "LPL"), ("LLA", "CBLOL")]:
        b = league_baseline(own, year, elos=elos, opponent_league=opp)
        logging.info(f"  own={own:<6} vs {opp:<6} baseline = {b:.3f}")


if __name__ == "__main__":
    _demo()
