"""
Tune ALL LPS / CLR parameters against the per-lane consensus GOAT lists.

Objective = mean per-lane Spearman correlation between our within-lane CLR and the consensus
weights in info/consensus_ratings.csv (5 lanes x ~25 players). Consensus is past/eye-test biased,
so the goal is "close enough", not a perfect fit -- see the caveats printed at the end.

Two-level coordinate descent, exploiting the pipeline's caching:
  - OUTER (expensive): the scoring weights -- alpha, lam, beta, the three region exponents, and
    intl_weight -- change per-match scores, so each candidate re-scores + re-aggregates every year
    (reuses the cached weight-invariant features + models; no retraining).
  - INNER (cheap): the CLR composite + resume-bonus params are pure post-aggregation transforms,
    so for each scoring config we fully optimize them on the aggregated frame in a fast loop.

Run:  poetry run python -m lps.tune_consensus              # default search
      poetry run python -m lps.tune_consensus --quick      # coarse, 1 pass (fast smoke test)
      poetry run python -m lps.tune_consensus --passes 3   # more thorough

Writes the best config to info/tuned_params.json (apply by hand to the dataclass defaults).
"""

from __future__ import annotations

import argparse
import csv
import json
import logging

import numpy as np
from scipy.stats import spearmanr

from .achievements import BonusConfig, score_bonuses
from .career import (
    CLRConfig,
    _add_bonuses,
    _add_clr,
    _aggregate,
    _apply_era_adjustment,
    _stack,
    run_year_frames,
)
from .config import INFO_DIR
from .export_excel import apply_schedule_norm
from .scoring import ScoreWeights
from .season import build_lane_remap

logger = logging.getLogger(__name__)

YEARS = tuple(range(2011, 2026))
MIN_GAMES = 3
LANES = ("top", "jng", "mid", "bot", "sup")


# --------------------------------------------------------------------------------------------
# Consensus
# --------------------------------------------------------------------------------------------
def _norm(s: str) -> str:
    return "".join(str(s).lower().split())


def load_consensus_sources() -> list[tuple[str, dict[str, dict[str, float]]]]:
    """Every info/consensus_ratings*.csv is one independent survey: (name, {group -> {player -> w}})
    where group is a lane (top/jng/mid/bot/sup) or 'overall' (a cross-lane ranking). Combining two
    surveys = averaging their Spearmans, so their different scales/rosters need no reconciliation.
    """
    out = []
    for path in sorted(INFO_DIR.glob("consensus_ratings*.csv")):
        src: dict[str, dict[str, float]] = {}
        with open(path, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                w = float(row["weight"])
                if w > 0:  # ignore the zero tail: only players actually ranked count
                    src.setdefault(row["lane"].strip(), {})[_norm(row["player"])] = w
        out.append((path.stem, src))
    return out


CONSENSUS_SOURCES = load_consensus_sources()


def _rho_one(clr_by: dict, weights: dict[str, float]) -> float:
    pairs = [(clr_by[n], w) for n, w in weights.items() if n in clr_by]
    return spearmanr(*zip(*pairs)).correlation if len(pairs) >= 3 else np.nan


def _mean_rho(career_all, career_lane) -> tuple[float, dict[str, float]]:
    """Objective = mean Spearman over EVERY (survey, group): each survey's five lanes (vs
    within-lane CLR) plus its 'overall' list, if any (vs cross-lane career CLR). All terms are
    weighted equally, so the two surveys count the same regardless of roster size."""
    lane_by = {
        lane: dict(
            zip(
                career_lane[career_lane["position"] == lane]["playername"].map(_norm),
                career_lane[career_lane["position"] == lane]["clr"],
            )
        )
        for lane in LANES
    }
    all_by = dict(zip(career_all["playername"].map(_norm), career_all["clr"]))
    per: dict[str, float] = {}
    for name, src in CONSENSUS_SOURCES:
        for group, weights in src.items():
            clr_by = all_by if group == "overall" else lane_by.get(group, {})
            per[f"{name}:{group}"] = _rho_one(clr_by, weights)
    rhos = [v for v in per.values() if v == v]
    return (float(np.mean(rhos)) if rhos else float("nan")), per


# --------------------------------------------------------------------------------------------
# Expensive pass: (re)score + aggregate everything for a scoring config
# --------------------------------------------------------------------------------------------
def build_aggregates(sw: ScoreWeights, intl_weight: float):
    """Run the full per-year pipeline for a scoring config and return the pieces the cheap CLR
    loop needs: the stacked (pre-era) per-(player,year) frame, tourney cols, years, roster.
    """
    records, all_tourn = run_year_frames(YEARS, sw, MIN_GAMES, intl_weight, False)
    got = tuple(sorted({r["year"] for r in records}))
    nrefs = [r["n_ref"] for r in records if r["n_ref"]]
    ref = float(np.mean(nrefs)) if nrefs else 1.0
    for rec in records:
        mult = ref / rec["n_ref"] if rec["n_ref"] else 1.0
        rec["frame"] = apply_schedule_norm(rec["frame"], mult, rec["tc"])
    allyears = _stack(records, all_tourn)
    roster = allyears[["playername", "year", "team", "league", "position"]].copy()
    return allyears, all_tourn, got, roster


# --------------------------------------------------------------------------------------------
# Cheap pass: CLR composite + resume bonuses on the aggregated frame
# --------------------------------------------------------------------------------------------
_BONUS_CACHE: dict = {}


def _bonus_long(roster, bcfg: BonusConfig):
    """score_bonuses depends only on the roster + bonus point structure (repeat_decay,
    champ_per_weight), NOT on scoring weights or CLR params -- so cache by those."""
    key = (bcfg.repeat_decay, bcfg.champ_per_weight)
    if key not in _BONUS_CACHE:
        _BONUS_CACHE[key] = score_bonuses(roster, bcfg)
    return _BONUS_CACHE[key]


def eval_clr(allyears, all_tourn, got, roster, clr_cfg: CLRConfig, bcfg: BonusConfig):
    ally = _apply_era_adjustment(allyears, all_tourn, clr_cfg.era_mults)
    ca = _add_clr(_aggregate(ally, ["playername"], all_tourn, got), got, clr_cfg)
    cl = _add_clr(
        _aggregate(ally, ["playername", "position"], all_tourn, got), got, clr_cfg
    )
    ca, cl = _add_bonuses(ca, cl, _bonus_long(roster, bcfg), bcfg.w_bonus)
    return _mean_rho(ca, cl)


# --------------------------------------------------------------------------------------------
# Search space
# --------------------------------------------------------------------------------------------
# INNER (cheap) params live on CLRConfig / BonusConfig. w_peak is pinned at 1.0 (ranking is
# scale-invariant, so only the ratios matter). era3 mult is pinned at 1.0 (modern reference).
INNER_SPACE = {
    ("clr", "w_career"): [0.6, 0.8, 1.0, 1.3, 1.6],
    ("clr", "w_pace"): [0.2, 0.4, 0.6, 0.8],
    ("clr", "pace_prior_games"): [25.0, 50.0, 100.0],
    ("clr", "peak_band"): [0.10, 0.15, 0.20, 0.25],
    ("clr", "peak_len_bonus"): [0.05, 0.10, 0.15],
    ("clr", "era1"): [1.0, 1.15, 1.25, 1.4, 1.6],
    ("clr", "era2"): [1.0, 1.1, 1.2, 1.35],
    ("bonus", "w_bonus"): [0.5, 0.75, 1.0, 1.25, 1.5],
    ("bonus", "repeat_decay"): [0.6, 0.7, 0.8, 0.9, 1.0],
    ("bonus", "champ_per_weight"): [3.5, 4.6, 5.5],
}
# OUTER (expensive) params live on ScoreWeights (+ intl_weight, carried alongside). region_exp is a
# single constant; w_playoff and intl_weight are the playoff/tourney phase multipliers (regular is
# the reference phase, pinned at 1.0 -- scaling all three equally is just a global CLR rescale).
OUTER_SPACE = {
    "alpha": [0.4, 0.6, 0.75, 1.0],
    "lam": [1.0, 1.5, 2.0, 2.5],
    "beta": [0.0, 0.25],
    "region_exp": [0.5, 1.0, 1.5, 2.0, 2.5, 3.0],
    "w_playoff": [0.5, 0.75, 1.0, 1.5, 2.0],
    "intl_weight": [1.0, 1.5, 2.0, 3.0],
}


def _mk_cfgs(inner: dict) -> tuple[CLRConfig, BonusConfig]:
    clr = CLRConfig(
        w_career=inner[("clr", "w_career")],
        w_pace=inner[("clr", "w_pace")],
        w_peak=1.0,
        pace_prior_games=inner[("clr", "pace_prior_games")],
        peak_band=inner[("clr", "peak_band")],
        peak_len_bonus=inner[("clr", "peak_len_bonus")],
        era_mults=(inner[("clr", "era1")], inner[("clr", "era2")], 1.0),
    )
    bcfg = BonusConfig(
        w_bonus=inner[("bonus", "w_bonus")],
        repeat_decay=inner[("bonus", "repeat_decay")],
        champ_per_weight=inner[("bonus", "champ_per_weight")],
    )
    return clr, bcfg


def optimize_inner(agg, init: dict, passes: int) -> tuple[dict, float]:
    """Coordinate descent over the cheap CLR/bonus params for a fixed aggregated frame."""

    def score(d):
        clr, bcfg = _mk_cfgs(d)
        return eval_clr(*agg, clr, bcfg)[0]

    best, best_s = dict(init), score(init)
    for _ in range(passes):
        improved = False
        for key, grid in INNER_SPACE.items():
            for v in grid:
                if v == best[key]:
                    continue
                cand = dict(best)
                cand[key] = v
                s = score(cand)
                if s > best_s + 1e-5:
                    best, best_s, improved = cand, s, True
        if not improved:
            break
    return best, best_s


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(
        description="Tune all params against the consensus lists."
    )
    ap.add_argument(
        "--quick", action="store_true", help="1 pass, skip alpha/lam/beta re-search"
    )
    ap.add_argument(
        "--passes", type=int, default=2, help="coordinate-descent passes (outer)"
    )
    args = ap.parse_args()

    logger.info("[tune] building cross-year lane-normalization tables (once) ...")
    build_lane_remap(force_recompute=False)

    # Starting point = current shipped defaults.
    sw0, iw0 = ScoreWeights(alpha=0.75, lam=2.0, beta=0.0), 2.0
    outer = {
        **{
            k: getattr(sw0, k)
            for k in ("alpha", "lam", "beta", "region_exp", "w_playoff")
        },
        "intl_weight": iw0,
    }
    inner_init = {
        ("clr", "w_career"): 1.0,
        ("clr", "w_pace"): 0.5,
        ("clr", "pace_prior_games"): 50.0,
        ("clr", "peak_band"): 0.15,
        ("clr", "peak_len_bonus"): 0.10,
        ("clr", "era1"): 1.25,
        ("clr", "era2"): 1.15,
        ("bonus", "w_bonus"): 1.0,
        ("bonus", "repeat_decay"): 0.8,
        ("bonus", "champ_per_weight"): 4.6,
    }
    inner_passes = 1 if args.quick else 2
    outer_space = dict(OUTER_SPACE)
    if args.quick:
        for k in ("alpha", "lam", "beta"):
            outer_space[k] = [
                outer[k]
            ]  # freeze the already-tuned score weights in quick mode

    agg_cache: dict = {}

    def outer_eval(o: dict):
        sw = ScoreWeights(
            alpha=o["alpha"],
            lam=o["lam"],
            beta=o["beta"],
            region_exp=o["region_exp"],
            w_regular=1.0,
            w_playoff=o["w_playoff"],
        )
        key = (
            o["alpha"],
            o["lam"],
            o["beta"],
            o["region_exp"],
            o["w_playoff"],
            o["intl_weight"],
        )
        if key not in agg_cache:
            agg_cache[key] = build_aggregates(sw, o["intl_weight"])
        best_inner, rho = optimize_inner(agg_cache[key], inner_init, inner_passes)
        return rho, best_inner

    best_o = dict(outer)
    best_rho, best_inner = outer_eval(best_o)
    logger.info(f"[tune] baseline mean rho = {best_rho:.4f}")

    passes = 1 if args.quick else args.passes
    for p in range(passes):
        improved = False
        for name, grid in outer_space.items():
            for v in grid:
                if v == best_o[name]:
                    continue
                cand = dict(best_o)
                cand[name] = v
                rho, inner = outer_eval(cand)
                logger.info(
                    f"[tune] pass {p} {name}={v}: rho={rho:.4f}"
                    + ("  * NEW BEST" if rho > best_rho + 1e-5 else "")
                )
                if rho > best_rho + 1e-5:
                    best_o, best_rho, best_inner, improved = cand, rho, inner, True
        if not improved:
            logger.info(f"[tune] pass {p}: no improvement, stopping.")
            break

    # Final report + per-lane detail at the winner.
    clr, bcfg = _mk_cfgs(best_inner)
    key = (
        best_o["alpha"],
        best_o["lam"],
        best_o["beta"],
        best_o["region_exp"],
        best_o["w_playoff"],
        best_o["intl_weight"],
    )
    rho, per = eval_clr(*agg_cache[key], clr, bcfg)

    best = {
        "mean_rho": round(rho, 4),
        "per_group_rho": {k: round(float(v), 3) for k, v in per.items()},
        "ScoreWeights": {
            k: best_o[k] for k in ("alpha", "lam", "beta", "region_exp", "w_playoff")
        },
        "w_regular": 1.0,
        "intl_weight": best_o["intl_weight"],
        "CLRConfig": {
            "w_career": clr.w_career,
            "w_pace": clr.w_pace,
            "w_peak": clr.w_peak,
            "pace_prior_games": clr.pace_prior_games,
            "peak_band": clr.peak_band,
            "peak_len_bonus": clr.peak_len_bonus,
            "era_mults": list(clr.era_mults),
        },
        "BonusConfig": {
            "w_bonus": bcfg.w_bonus,
            "repeat_decay": bcfg.repeat_decay,
            "champ_per_weight": bcfg.champ_per_weight,
        },
    }
    logger.info("\n" + "=" * 70 + "\n[tune] BEST CONFIG\n" + "=" * 70)
    logger.info(json.dumps(best, indent=2))
    out = INFO_DIR / "tuned_params.json"
    out.write_text(json.dumps(best, indent=2), encoding="utf-8")
    logger.info(f"\n[tune] wrote {out}")


if __name__ == "__main__":
    main()
