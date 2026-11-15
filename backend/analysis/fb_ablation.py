"""
First-blood ablation: how much do the career rankings move if first blood is removed from
the performance score?

First blood enters the score in exactly one place: season._match_features credits the team's
first-blood log-odds term (`team_fb`) to the FB killer (+) / victim (-) as `c_fb`, and adds it
to `net_contribution`. (The lane stats are already FB-free: kills_nonfb / deaths_nonfb /
assists_nonfb.) The cross-lane remap pools the LOO *excluding* c_fb, so zeroing c_fb after the
cache load is a clean ablation that needs no retraining.

Runs the full career aggregation twice from the existing caches (no network, no retraining,
nothing written to the repo): once as-is, once with c_fb zeroed. Then it compares ranks.

    poetry run python analysis/fb_ablation.py [--out DIR]

Caveat: Model 2 still has `teamfirstblood` as a feature, so the lane-stat coefficients stay
"conditional on FB". Retraining Model 2 without it (so lane stats absorb FB's correlation)
would be the stronger variant; this script measures dropping the per-player FB credit only.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from lps import career, season
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
    ap.add_argument("--out", type=Path, default=Path("data/fb_ablation"))
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    career.write_career_workbook = _capture_workbook
    career._write_yearly_breakdown = _capture_yearly
    career._write_asof_snapshots = lambda *a, **k: None

    base = _run(False, args.out)
    nofb = _run(True, args.out)

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
