"""One-off driver: recompute the full regional-Elo chain 2011->2025 after the
2011-2012 team_regions edits (and the new 2012 TH region).

Nothing in the repo automates the year-to-year hand-off, and rebrand boundaries
involve renames, GPL-style consolidations, split-inheritances, and hand-picked
seeds. We reconstruct each boundary's predecessor link empirically from the
*current* (pre-recompute) files, then carry the *recomputed* value across the
same link.

Predecessor resolution for a region R in starting_elos_N, against ending_elos_{N-1}:
  1. NAME  : R exists by name in ending_{N-1}      -> continuation
  2. RENAME: unique (elo, count) match, count>0    -> renamed region
  3. INHERIT: unique elo match (elo != default)    -> split/rename that reset count
  4. BLEND : registered formula (GPL, LLA, ...)     -> recomputed from new endings
  5. FRESH : none of the above                      -> keep hand seed (flagged if
             the seed is non-default, i.e. an unresolved blend)

Count handling for a matched predecessor P:
  - if old_start_N[R].count == old_end_{N-1}[P].count  -> straight carry, use NEW count
  - else                                               -> hand-set count, keep R's count

Run modes:
  python rerun_elos.py --plan     # read-only; classify every boundary, no writes
  python rerun_elos.py --run      # execute the full recompute chain
"""

from __future__ import annotations

import csv
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

INFO = Path("info")
SNAP = INFO / "_rerun_snapshot"


def _discover_years() -> list[int]:
    """2011 through the newest year that has a starting_elos_<year>.csv seed."""
    seeded = sorted(
        int(p.stem.split("_")[-1])
        for p in INFO.glob("starting_elos_*.csv")
        if p.stem.split("_")[-1].isdigit()
    )
    return list(range(2011, (seeded[-1] if seeded else 2025) + 1))


YEARS = _discover_years()
DEFAULT_ELO = 1000.0

Rows = list[tuple[str, float, int]]
Dict = dict[str, tuple[float, int]]


# Registered consolidation seeds: (year, region) -> {constituent_in_{year-1}: team_weight}.
# Every historical blend is a team-count-weighted mean of the prior year's endings;
# each set of weights was reverse-engineered to reproduce the committed seed exactly.
BLENDS: dict[tuple[int, str], dict[str, int]] = {
    (2013, "GPL"): {"TW": 2, "VN": 2, "PH": 1, "SG": 1, "TH": 1},  # SEA -> GPL (incl new TH)
    (2019, "LLA"): {"LLN": 1, "CLS": 1},                            # LatAm merge
    (2019, "LST"): {"LGS": 2, "LCM": 1, "TPL": 2, "PGS": 2, "SLS": 1},  # SEA tour merge
    (2020, "PCS"): {"LMS": 3, "LST": 2},                            # LMS+LST -> PCS
    (2025, "LTA N"): {"LCS": 7, "LLA": 1},                          # Americas North
    (2025, "LTA S"): {"CBLOL": 3, "LLA": 1},                        # Americas South
    (2025, "LCP"): {"PCS": 5, "VCS": 3},                            # Asia-Pacific merge
}


def blend_value(weights: dict[str, int], end_prev: Dict) -> float:
    return sum(end_prev[r][0] * n for r, n in weights.items()) / sum(weights.values())


def read_elos(path: Path) -> Rows:
    rows: Rows = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            region = (row.get("region") or "").strip()
            if not region:
                continue
            elo = float(row.get("starting_elo") or row.get("ending_elo") or "")
            count = int((row.get("match_count") or "0").strip() or 0)
            rows.append((region, elo, count))
    return rows


def as_dict(rows: Rows) -> Dict:
    return {r: (e, c) for (r, e, c) in rows}


def write_starting(path: Path, rows: Rows) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["region", "starting_elo", "match_count"])
        for region, elo, count in rows:
            w.writerow([region, round(elo, 2), count])


def resolve_predecessor(region: str, e: float, c: int, old_end_prev: Rows) -> tuple[str | None, str]:
    """Return (predecessor_region | None, classification)."""
    end = as_dict(old_end_prev)
    if region in end:
        return region, "NAME"

    ck = Counter((round(x, 2), n) for (_, x, n) in old_end_prev if n > 0)
    for r, x, n in old_end_prev:
        if n > 0 and (round(x, 2), n) == (round(e, 2), c) and ck[(round(x, 2), n)] == 1:
            return r, "RENAME"

    ek = Counter(round(x, 2) for (_, x, _) in old_end_prev)
    if round(e, 2) != round(DEFAULT_ELO, 2):
        for r, x, _ in old_end_prev:
            if round(x, 2) == round(e, 2) and ek[round(x, 2)] == 1:
                return r, "INHERIT"
    return None, "FRESH"


def plan_boundary(n: int, snap: Path) -> list[str]:
    """Classify every region in starting_N against ending_{N-1} (read-only)."""
    old_start = read_elos(snap / f"starting_elos_{n}.csv")
    old_end_prev = read_elos(snap / f"ending_elos_{n - 1}.csv")
    unresolved: list[str] = []
    lines = [f"\n=== {n - 1} -> {n} ==="]
    for region, e, c in old_start:
        if (n, region) in BLENDS:
            lines.append(f"  BLEND    {region:<8} (registered formula)")
            continue
        p, kind = resolve_predecessor(region, e, c, old_end_prev)
        if kind == "FRESH":
            if round(e, 2) == round(DEFAULT_ELO, 2):
                lines.append(f"  FRESH    {region:<8} default {e:.2f}")
            else:
                lines.append(f"  UNRESOLVED {region:<8} seed {e:.2f}  <-- needs a formula")
                unresolved.append(f"{n}:{region}={e:.2f}")
        else:
            lines.append(f"  {kind:<8} {region:<8} <- {p}")
    if unresolved:
        lines.append(f"  ** unresolved blends: {unresolved}")
    print("\n".join(lines))
    return unresolved


def rebuild_starting(n: int, snap: Path) -> None:
    old_start = read_elos(snap / f"starting_elos_{n}.csv")
    old_end_prev = read_elos(snap / f"ending_elos_{n - 1}.csv")
    new_end_prev = as_dict(read_elos(INFO / f"ending_elos_{n - 1}.csv"))
    old_end_dict = as_dict(old_end_prev)

    new_rows: Rows = []
    log: list[str] = []
    for region, e, c in old_start:
        if (n, region) in BLENDS:
            new_rows.append((region, blend_value(BLENDS[(n, region)], new_end_prev), c))
            log.append(f"BLEND {region}={new_rows[-1][1]:.2f}")
            continue
        p, kind = resolve_predecessor(region, e, c, old_end_prev)
        if p is not None and p in new_end_prev:
            new_elo, new_cnt_src = new_end_prev[p]
            count = new_cnt_src if c == old_end_dict[p][1] else c
            new_rows.append((region, new_elo, count))
            log.append(f"{kind[:4]} {region}<-{p}")
        else:
            new_rows.append((region, e, c))  # fresh / unresolved -> keep
            log.append(f"KEEP {region}={e:.2f}")
    write_starting(INFO / f"starting_elos_{n}.csv", new_rows)
    print(f"  starting_elos_{n}: " + " | ".join(log))


def run_year(year: int) -> None:
    print(f"\n{'#'*70}\n# regional_elo --year {year}\n{'#'*70}", flush=True)
    subprocess.run([sys.executable, "-m", "lps.regional_elo", "--year", str(year)], check=True)


def snapshot() -> None:
    if SNAP.exists():
        shutil.rmtree(SNAP)
    SNAP.mkdir(parents=True)
    for pat in ("starting_elos_*.csv", "ending_elos_*.csv"):
        for p in INFO.glob(pat):
            if p.parent == INFO:
                shutil.copy2(p, SNAP / p.name)
    print(f"Snapshotted {len(list(SNAP.glob('*.csv')))} files -> {SNAP}")


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "--plan"
    snapshot()

    if mode == "--plan":
        all_unresolved: list[str] = []
        for n in YEARS[1:]:
            all_unresolved += plan_boundary(n, SNAP)
        print("\n" + "=" * 60)
        if all_unresolved:
            print("UNRESOLVED BLENDS (need a formula or will be kept fixed):")
            for u in all_unresolved:
                print("  -", u)
        else:
            print("No unresolved blends -- every boundary is handled.")
        return

    if mode == "--run":
        run_year(2011)
        for n in YEARS[1:]:
            rebuild_starting(n, SNAP)
            run_year(n)
        print("\nDone. Pre-recompute snapshot kept in", SNAP)
        return

    print(f"Unknown mode {mode!r}; use --plan or --run")


if __name__ == "__main__":
    main()
