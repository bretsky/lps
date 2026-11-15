"""
First-blood ablation: how much do the career rankings move if first blood is removed from
the performance score?

First blood enters the score in exactly one place: season._match_features credits the team's
first-blood log-odds term (`team_fb`) to the FB killer (+) / victim (-) as `c_fb`, and adds it
to `net_contribution`. (The lane stats are already FB-free: kills_nonfb / deaths_nonfb /
assists_nonfb.) The cross-lane remap pools the LOO *excluding* c_fb, so zeroing c_fb after the
cache load is a clean ablation that needs no retraining.

Two variants (`--variant`):

  credit  (default, minutes) -- run the full career aggregation twice from the existing caches
          (no retraining): once as-is, once with c_fb zeroed. Model 2 still has
          `teamfirstblood` as a feature, so the lane-stat coefficients stay "conditional on FB".
  retrain (~1.5 h) -- retrain Model 2 WITHOUT `teamfirstblood` every Oracle year, so the lane
          stats absorb whatever FB was explaining, and rebuild the cross-lane remap from those
          frames. Compared against a baseline rebuilt the same way (fresh remap) from a COPY of
          the real caches, so stale-remap effects don't leak into the diff. Everything lives
          under --out; data/cache is only read.

    poetry run python analysis/fb_ablation.py [--variant credit|retrain] [--out DIR]
"""

from __future__ import annotations

import argparse
import logging
import shutil
import time
from pathlib import Path

import pandas as pd

from lps import career, contribution, season
from lps.io_oracle import latest_oracle_year

_orig_match_features = season._match_features
_captured: dict = {}


def _no_fb_match_features(*a, **kw):
    m = _orig_match_features(*a, **kw).copy()
    if "c_fb" in m.columns:
        m["net_contribution"] = m["net_contribution"] - m["c_fb"]
        m["c_fb"] = 0.0
    return m


def _capture_workbook(out, career_all, career_lane, all_tourn, years, meta):
    _captured["all"] = career_all.copy()
    _captured["lane"] = career_lane.copy()
    return out


def _capture_yearly(allyears, out_dir):
    _captured["years"] = allyears.copy()


def _run(no_fb: bool, out_dir: Path) -> dict:
    _captured.clear()
    season._match_features = _no_fb_match_features if no_fb else _orig_match_features
    try:
        career.build_and_write(
            years=tuple(range(2011, latest_oracle_year() + 1)),
            force_recompute=False,
            write_yearly=False,
            out=out_dir / f"career_{'nofb' if no_fb else 'base'}.xlsx",
        )
    finally:
        season._match_features = _orig_match_features
    return dict(_captured)


_orig_btf_season = season.build_team_features
_orig_btf_contrib = contribution.build_team_features


def _btf_no_fb(*a, **kw):
    return _orig_btf_season(*a, **kw).drop(columns=["teamfirstblood"], errors="ignore")


def _run_retrain(no_fb: bool, cache_dir: Path, out_dir: Path) -> dict:
    """Full career build with season's caches (match features + lane remap) redirected to
    cache_dir; with no_fb, Model 2 is trained/applied without the teamfirstblood feature."""
    _captured.clear()
    saved = (season._CACHE_DIR, season._REMAP_CACHE)
    season._CACHE_DIR, season._REMAP_CACHE = cache_dir, cache_dir / "lane_remap.pkl"
    if no_fb:
        season.build_team_features = _btf_no_fb
        contribution.build_team_features = _btf_no_fb
    try:
        career.build_and_write(
            years=tuple(range(2011, latest_oracle_year() + 1)),
            force_recompute=False,
            write_yearly=False,
            out=out_dir / f"career_{'nofb' if no_fb else 'base'}.xlsx",
        )
    finally:
        season._CACHE_DIR, season._REMAP_CACHE = saved
        season.build_team_features = _orig_btf_season
        contribution.build_team_features = _orig_btf_contrib
    return dict(_captured)


def _rank(df: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    d = df[keys + ["clr"]].copy()
    d["rank"] = d["clr"].rank(ascending=False, method="min").astype(int)
    return d


def _compare(base: pd.DataFrame, nofb: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    b, n = _rank(base, keys), _rank(nofb, keys)
    c = b.merge(n, on=keys, suffixes=("_base", "_nofb"))
    c["d_rank"] = c["rank_base"] - c["rank_nofb"]  # + = moved UP without FB
    c["d_clr"] = c["clr_nofb"] - c["clr_base"]
    return c.sort_values("rank_base")


def _summary(c: pd.DataFrame, label: str) -> list[str]:
    from scipy.stats import kendalltau, spearmanr

    lines = [f"== {label} ({len(c)} rows) =="]
    for n in (10, 25, 50, 100, 250):
        top = c[c["rank_base"] <= n]
        overlap = int((c.loc[c["rank_base"] <= n, "rank_nofb"] <= n).sum())
        lines.append(
            f"  top {n:>3}: overlap {overlap}/{n}, mean |d_rank| {top['d_rank'].abs().mean():.2f}, "
            f"max |d_rank| {top['d_rank'].abs().max()}"
        )
    t100 = c[c["rank_base"] <= 100]
    lines.append(
        f"  spearman(all)={spearmanr(c['clr_base'], c['clr_nofb'])[0]:.5f}  "
        f"kendall(top100)={kendalltau(t100['rank_base'], t100['rank_nofb'])[0]:.4f}"
    )
    lines.append(
        f"  mean |d_clr| / mean |clr| (top 100) = "
        f"{t100['d_clr'].abs().mean() / t100['clr_base'].abs().mean():.4f}"
    )
    return lines


def main() -> None:
    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", choices=("credit", "retrain"), default="credit")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()
    if args.out is None:
        args.out = Path("data/fb_ablation") / ("" if args.variant == "credit" else "retrain")
    args.out.mkdir(parents=True, exist_ok=True)

    career.write_career_workbook = _capture_workbook
    career._write_yearly_breakdown = _capture_yearly
    career._write_asof_snapshots = lambda *a, **k: None

    if args.variant == "credit":
        base = _run(False, args.out)
        nofb = _run(True, args.out)
    else:
        logging.getLogger().setLevel(logging.INFO)
        base_cache, nofb_cache = args.out / "cache_base", args.out / "cache_nofb"
        base_cache.mkdir(exist_ok=True)
        nofb_cache.mkdir(exist_ok=True)
        for p in season._CACHE_DIR.glob("match_features_*.pkl"):  # read-only copy
            if not (base_cache / p.name).exists():
                shutil.copy2(p, base_cache / p.name)
        t0 = time.time()
        base = _run_retrain(False, base_cache, args.out)
        pd.to_pickle(base, args.out / "frames_base.pkl")
        print(f"[fb_ablation] baseline done in {(time.time() - t0) / 60:.1f} min", flush=True)
        t0 = time.time()
        nofb = _run_retrain(True, nofb_cache, args.out)
        pd.to_pickle(nofb, args.out / "frames_nofb.pkl")
        print(f"[fb_ablation] no-FB retrain done in {(time.time() - t0) / 60:.1f} min", flush=True)

    lines: list[str] = []
    overall = _compare(base["all"], nofb["all"], ["playername"])
    lines += _summary(overall, "overall career board")
    overall.to_csv(args.out / "overall.csv", index=False)
    for lane in season.ROLES:
        lc = _compare(
            base["lane"][base["lane"]["position"] == lane],
            nofb["lane"][nofb["lane"]["position"] == lane],
            ["playername", "position"],
        )
        lines += _summary(lc, f"lane {lane}")
        lc.to_csv(args.out / f"lane_{lane}.csv", index=False)

    cols = ["playername", "rank_base", "rank_nofb", "d_rank", "clr_base", "clr_nofb", "d_clr"]
    lines.append("\n== overall top 30 ==")
    lines.append(overall.head(30)[cols].to_string(index=False))
    top100 = overall[overall["rank_base"] <= 100]
    lines.append("\n== biggest movers in base top 100 ==")
    lines.append(
        top100.reindex(top100["d_rank"].abs().sort_values(ascending=False).index)
        .head(15)[cols]
        .to_string(index=False)
    )

    # Who gains/loses FB credit? Per-lane mean FB credit per game (from the base season frames).
    y = base.get("years")
    if y is not None and "fb_pts" in y.columns:
        lines.append("\n== season-level fb_pts by lane (base) ==")
        lines.append(
            y.groupby("position")["fb_pts"].describe()[["mean", "std", "min", "max"]].to_string()
        )

    text = "\n".join(lines)
    (args.out / "summary.txt").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
