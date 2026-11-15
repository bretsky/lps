"""Master driver: pull the latest data and recompute all LPS scores + rankings.

One command to take the repo from "new data exists upstream" to "refreshed
workbooks on disk". Two modes:

  * INCREMENTAL (default) -- refresh only the *latest* year end-to-end and reuse
    everything already cached for prior years. Fast; this is the day-to-day run.
  * FULL (--full)         -- re-pull everything and recompute the entire
    2011->latest Elo chain and every per-year score from scratch. Slow but
    fully self-consistent. Use after a model/scoring change or a region edit.

What a normal (incremental) run does, in order:

  0. Oracle       -- pull any season CSV that changed on Oracle's Elixir's Drive
                     folder (incl. a brand-new season) into data/oracle/ via
                     lps.refresh_oracle. Older seasons OE corrected get their
                     feature caches busted too, so step 4 rebuilds them.
     Preflight    -- resolve the target year from the newest Oracle CSV; verify
                     that CSV and (unless --skip-fetch) Leaguepedia creds exist.
  1. Pull LP      -- force-refresh the *current year's* international match JSONs
                     (older cached years are left untouched) + re-fetch
                     achievements/awards (old CSVs are backed up first).
  2. Region guard -- diff the current year's match teams against
                     team_regions_<year>.csv. Any team without a region is
                     *appended* (blank) to that CSV -- existing rows are never
                     touched -- and the run HALTS so you can fill them in. Elo is
                     only correct once every international team has a region.
  3. Regional Elo -- recompute ending_elos_<year>.csv for the target year.
  4. Scores       -- bust the target year's feature cache, then rebuild all
                     workbooks (per-year + Career_LPS.xlsx) reusing prior years.
  5. Web bundle   -- new players' photos, then export_web -> frontend/public/data/current/.
  6. Deploy       -- only with --deploy: build the static site and upload it to
                     Cloudflare Pages (`npm run deploy` in frontend/).

Manual prerequisites this script does NOT do for you (by design):
  * Filling the `region` column for newly-seen teams (step 2 halts for this).
  * Seeding starting_elos_<year>.csv for a brand-new year (step 3 halts and
    tells you to run `--full`, which reseeds every boundary via rerun_elos.py).

Examples:
  poetry run python -m lps.update_all                 # incremental, latest year
  poetry run python -m lps.update_all --year 2024     # incremental, pin year
  poetry run python -m lps.update_all --skip-fetch    # recompute only, no network
  poetry run python -m lps.update_all --skip-oracle   # keep the local Oracle CSVs
  poetry run python -m lps.update_all --full          # full rebuild, all years
  poetry run python -m lps.update_all --dry-run       # print the plan, run nothing
  poetry run python -m lps.update_all --deploy        # ...and publish the site
"""

from __future__ import annotations

import argparse
import csv
import logging
import shutil
import subprocess
import sys
from pathlib import Path

from .config import INFO_DIR, LEAGUEPEDIA_DIR, LP_PASSWORD, LP_USERNAME, PROJECT_ROOT
from .extract_team_names import extract_team_names_by_year
from .io_oracle import _infer_year_from_name, list_oracle_files
from .refresh_oracle import RefreshError, refresh

logger = logging.getLogger("lps.update_all")

MATCHES_DIR = LEAGUEPEDIA_DIR / "matches"
CACHE_DIR = PROJECT_ROOT / "data" / "cache"
DEFAULT_START_YEAR = 2011


class HaltError(RuntimeError):
    """A prerequisite is missing that only a human can resolve. Stops the run cleanly."""


# --------------------------------------------------------------------------- #
# command runner
# --------------------------------------------------------------------------- #
def run(cmd: list[str], *, cwd: Path | None = None, dry_run: bool = False) -> None:
    """Run a subcommand, echoing it first. Raises CalledProcessError on failure."""
    printable = " ".join(cmd)
    logger.info("\n$ %s", printable)
    if dry_run:
        return
    subprocess.run(cmd, cwd=str(cwd or PROJECT_ROOT), check=True)


def _module_cmd(module: str, *args: str) -> list[str]:
    return [sys.executable, "-m", f"lps.{module}", *args]


# --------------------------------------------------------------------------- #
# phase 0 -- Oracle's Elixir refresh + preflight
# --------------------------------------------------------------------------- #
def refresh_oracle_csvs(*, dry_run: bool) -> list[int]:
    """Sync data/oracle/ with OE's Drive folder; returns the years swapped in.

    A rejected download keeps the old file and only warns (the run goes on with
    what's on disk); Drive being unreachable halts, since the point of the run is
    the latest data -- pass --skip-oracle to rebuild from the local CSVs anyway."""
    logger.info("\n[oracle] checking Oracle's Elixir's Drive folder for new data")
    try:
        result = refresh(check=dry_run)
    except RefreshError as e:
        raise HaltError(
            f"Couldn't refresh Oracle's Elixir data: {e}. Fix that, or re-run with "
            "--skip-oracle to use the CSVs already in data/oracle/."
        ) from e
    if result.failed:
        logger.warning(
            "[oracle] %s not updated (see above); continuing with the local copies",
            ", ".join(map(str, result.failed)),
        )
    # On --dry-run, the seasons that *would* be pulled, so the plan shows their cache busts.
    return result.stale if dry_run else result.updated


def resolve_target_year(explicit: int | None) -> int:
    """Target year = explicit override, else the newest year with an Oracle CSV."""
    if explicit is not None:
        return explicit
    years = sorted(
        {y for p in list_oracle_files() if (y := _infer_year_from_name(p)) is not None}
    )
    if not years:
        raise HaltError(
            f"No Oracle's Elixir CSVs found in {list_oracle_files.__module__}'s ORACLE_DIR. "
            "Download the latest year's CSV from https://oracleselixir.com/ into data/oracle/ "
            "(filename must contain the year, e.g. '2025_LoL_esports_..._OraclesElixir.csv')."
        )
    return years[-1]


def check_oracle_year(year: int) -> None:
    if not any(str(year) in p.name for p in list_oracle_files()):
        raise HaltError(
            f"No Oracle CSV for {year} in data/oracle/. Download it from "
            "https://oracleselixir.com/ (filename must contain the year), then re-run."
        )


def check_credentials() -> None:
    if not LP_USERNAME or not LP_PASSWORD:
        raise HaltError(
            "Leaguepedia credentials missing. Set LP_USERNAME / LP_PASSWORD in .env, "
            "or re-run with --skip-fetch to recompute from already-cached data."
        )


# --------------------------------------------------------------------------- #
# phase 1 -- pull Leaguepedia
# --------------------------------------------------------------------------- #
def force_refresh_current_year_matches(year: int, *, dry_run: bool) -> None:
    """Delete this year's cached per-tournament match JSONs so the fetch re-pulls
    them (in-progress events otherwise stay frozen). Older years and the rebuilt
    `*_all.json` aggregates are left alone -- the fetch rewrites the aggregates."""
    if not MATCHES_DIR.exists():
        return
    stale = [
        p
        for p in MATCHES_DIR.glob(f"*{year}*.json")
        if not p.name.endswith("_all.json")
    ]
    if not stale:
        logger.info("[fetch] no cached %s match files to refresh", year)
        return
    logger.info("[fetch] clearing %d cached %s match file(s) to force refresh", len(stale), year)
    for p in stale:
        logger.info("        rm %s", p.name)
        if not dry_run:
            p.unlink()


def backup_achievement_csvs(*, dry_run: bool) -> None:
    """fetch_achievements overwrites the achievements/awards CSVs wholesale, which
    would clobber any hand-edited rows. Snapshot them first."""
    names = [
        "achievements.csv",
        "achievements_raw.csv",
        "player_awards.csv",
        "player_awards_raw.csv",
    ]
    existing = [INFO_DIR / n for n in names if (INFO_DIR / n).exists()]
    if not existing:
        return
    backup_dir = INFO_DIR / "backup_auto"
    logger.info("[fetch] backing up %d achievement CSV(s) -> %s", len(existing), backup_dir)
    if dry_run:
        return
    backup_dir.mkdir(parents=True, exist_ok=True)
    for p in existing:
        shutil.copy2(p, backup_dir / p.name)


def pull_leaguepedia(year: int, *, skip_achievements: bool, dry_run: bool) -> None:
    force_refresh_current_year_matches(year, dry_run=dry_run)
    run(_module_cmd("fetch_international_matches"), dry_run=dry_run)
    if not skip_achievements:
        backup_achievement_csvs(dry_run=dry_run)
        run(_module_cmd("fetch_achievements"), dry_run=dry_run)


# --------------------------------------------------------------------------- #
# phase 2 -- region guard (non-destructive)
# --------------------------------------------------------------------------- #
def _read_team_regions_raw(path: Path) -> list[tuple[str, str]]:
    """Return [(team_name, region), ...] preserving order; [] if the file is absent."""
    if not path.exists():
        return []
    rows: list[tuple[str, str]] = []
    with open(path, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rows.append(
                ((row.get("team_name") or "").strip(), (row.get("region") or "").strip())
            )
    return rows


def sync_and_check_regions(year: int, *, dry_run: bool) -> None:
    """Append newly-seen teams (blank region) to team_regions_<year>.csv without
    touching existing rows, then halt if any team for `year` lacks a region."""
    teams_by_year = extract_team_names_by_year(MATCHES_DIR)
    match_teams = teams_by_year.get(year, set())
    if not match_teams:
        logger.info("[regions] no international match teams found for %s -- nothing to check", year)
        return

    path = INFO_DIR / f"team_regions_{year}.csv"
    existing = _read_team_regions_raw(path)
    existing_names = {name for name, _ in existing}
    mapped_names = {name for name, region in existing if region}

    new_teams = sorted(match_teams - existing_names)
    unmapped = sorted(t for t in match_teams if t not in mapped_names)

    # Non-destructive append of any brand-new teams (blank region) so the human has
    # a ready-to-fill row. Existing rows -- filled or not -- are preserved verbatim.
    if new_teams:
        logger.info("[regions] adding %d new team(s) to %s (blank region)", len(new_teams), path.name)
        if not dry_run:
            file_exists = path.exists()
            with open(path, "a", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                if not file_exists:
                    w.writerow(["team_name", "region"])
                for name in new_teams:
                    w.writerow([name, ""])

    if unmapped:
        listing = "\n".join(f"    - {t}" for t in unmapped)
        raise HaltError(
            f"{len(unmapped)} international team(s) for {year} have no region assigned.\n"
            f"  Fill the `region` column in: {path}\n"
            f"  (new teams were appended with a blank region for you)\n"
            f"  Regional Elo is only correct once every team is mapped. Teams:\n{listing}"
        )
    logger.info("[regions] all %d %s international teams are mapped", len(match_teams), year)


# --------------------------------------------------------------------------- #
# phase 3 -- regional Elo
# --------------------------------------------------------------------------- #
def _carry_elos(src: Path, dst: Path, dst_value_col: str) -> None:
    """Copy an Elo table across, renaming the value column (starting_elo<->ending_elo)
    and preserving region + match_count. Used to seed a new year with no region changes."""
    with open(src, "r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    with open(dst, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["region", dst_value_col, "match_count"])
        for r in rows:
            region = (r.get("region") or "").strip()
            if not region:
                continue
            val = (r.get("starting_elo") or r.get("ending_elo") or "").strip()
            count = (r.get("match_count") or "0").strip()
            w.writerow([region, val, count])


def recompute_elo_incremental(year: int, *, dry_run: bool) -> None:
    starting = INFO_DIR / f"starting_elos_{year}.csv"
    prev_ending = INFO_DIR / f"ending_elos_{year - 1}.csv"

    # Seed this year's starting Elos if absent. A straight carry-forward is only correct
    # when NO region merges/renames happened at this boundary; flag that assumption loudly.
    if not starting.exists():
        if not prev_ending.exists():
            raise HaltError(
                f"Neither {starting.name} nor {prev_ending.name} exists -- can't seed {year}'s "
                f"Elos. Create {starting.name} by hand, or run `--full` (rerun_elos.py reseeds "
                f"every boundary, incl. renames/merges)."
            )
        logger.warning(
            "[elo] %s: no %s -- seeding starting Elos by carry-forward from %s. If %s introduced "
            "region merges/renames (e.g. a LTA/LCP-style consolidation), seed by hand or run "
            "`--full` instead.",
            year, starting.name, prev_ending.name, year,
        )
        if not dry_run:
            _carry_elos(prev_ending, starting, "starting_elo")

    run(_module_cmd("regional_elo", "--year", str(year)), dry_run=dry_run)

    # regional_elo exits 0 even when it bails (no team_regions_<year>.csv / no international
    # matches yet), so verify its output. For a new season with no international games, fall
    # back to carrying the starting Elos forward so domestic scoring still has league baselines.
    ending = INFO_DIR / f"ending_elos_{year}.csv"
    if dry_run:
        return
    if not ending.exists():
        if not starting.exists():
            raise HaltError(
                f"regional_elo produced no {ending.name} and no {starting.name} exists to carry "
                f"forward. Check team_regions_{year}.csv / the Elo step above."
            )
        logger.warning(
            "[elo] %s: regional_elo produced no update (no international matches or "
            "team_regions_%s.csv yet) -- carrying starting Elos forward as %s so domestic "
            "scoring has league baselines. Re-run once %s international results are mapped.",
            year, year, ending.name, year,
        )
        _carry_elos(starting, ending, "ending_elo")


def recompute_elo_full(*, dry_run: bool) -> None:
    # rerun_elos.py is a repo-root driver that snapshots, reseeds every boundary
    # (renames/blends), and chains regional_elo across 2011->latest.
    run([sys.executable, "rerun_elos.py", "--run"], dry_run=dry_run)


# --------------------------------------------------------------------------- #
# phase 4 -- scores + rankings
# --------------------------------------------------------------------------- #
def bust_year_cache(year: int, *, dry_run: bool) -> None:
    """Delete only the target year's weight-invariant feature cache so career's
    --no-recompute rebuilds *just* that year and reuses every other year."""
    if not CACHE_DIR.exists():
        return
    stale = list(CACHE_DIR.glob(f"match_features_{year}_*.pkl"))
    if not stale:
        return
    logger.info("[scores] busting %d cached feature file(s) for %s", len(stale), year)
    for p in stale:
        logger.info("        rm %s", p.name)
        if not dry_run:
            p.unlink()


def recompute_scores(
    start_year: int,
    year: int,
    *,
    full: bool,
    weight_args: list[str],
    dry_run: bool,
    also_bust: list[int] | None = None,
) -> None:
    years_arg = f"{start_year}-{year}"
    if full:
        # force_recompute defaults True -> rebuilds every year + the lane remap.
        run(_module_cmd("career", "--years", years_arg, *weight_args), dry_run=dry_run)
    else:
        # The target year, plus any older season whose Oracle CSV OE just corrected.
        for y in sorted({year, *(y for y in (also_bust or []) if start_year <= y < year)}):
            bust_year_cache(y, dry_run=dry_run)
        run(
            _module_cmd("career", "--years", years_arg, "--no-recompute", *weight_args),
            dry_run=dry_run,
        )


# --------------------------------------------------------------------------- #
# orchestration
# --------------------------------------------------------------------------- #
def build_weight_args(args: argparse.Namespace) -> list[str]:
    """Pass through only the scoring knobs the user explicitly set; otherwise let
    career.py's finalized defaults stand."""
    out: list[str] = []
    for flag, val in (
        ("--min-games", args.min_games),
        ("--intl-weight", args.intl_weight),
        ("--alpha", args.alpha),
        ("--lam", args.lam),
        ("--beta", args.beta),
    ):
        if val is not None:
            out += [flag, str(val)]
    return out


def orchestrate(args: argparse.Namespace) -> int:
    weight_args = build_weight_args(args)

    # -- phase 0: newest Oracle data, then preflight (a brand-new season pulled
    # here becomes the target year)
    if args.skip_fetch or args.skip_oracle:
        logger.info("\n[oracle] skipped (%s)", "--skip-fetch" if args.skip_fetch else "--skip-oracle")
        oracle_updated: list[int] = []
    else:
        oracle_updated = refresh_oracle_csvs(dry_run=args.dry_run)
    year = resolve_target_year(args.year)
    mode = "FULL rebuild" if args.full else "INCREMENTAL update"
    logger.info("=" * 70)
    logger.info("LPS master update -- %s -- target year %s", mode, year)
    logger.info("=" * 70)
    check_oracle_year(year)
    if not args.skip_fetch:
        check_credentials()

    # -- phase 1: pull latest data
    if args.skip_fetch:
        logger.info("\n[fetch] skipped (--skip-fetch)")
    else:
        pull_leaguepedia(year, skip_achievements=args.skip_achievements, dry_run=args.dry_run)

    # -- phase 2: region guard (halts on unmapped teams)
    if args.skip_regions:
        logger.info("\n[regions] skipped (--skip-regions)")
    else:
        sync_and_check_regions(year, dry_run=args.dry_run)

    # -- phase 3: regional Elo
    if args.skip_elo:
        logger.info("\n[elo] skipped (--skip-elo)")
    elif args.full:
        recompute_elo_full(dry_run=args.dry_run)
    else:
        recompute_elo_incremental(year, dry_run=args.dry_run)

    # -- phase 4: scores + rankings
    recompute_scores(
        args.start_year,
        year,
        full=args.full,
        weight_args=weight_args,
        dry_run=args.dry_run,
        also_bust=oracle_updated,
    )

    # -- phase 5: website JSON bundle (turns the fresh career workbook into
    # frontend/public/data/current/*.json for the rankings site)
    if args.skip_web:
        logger.info("\n[web] skipped (--skip-web)")
    else:
        # Leaguepedia player photos for the cards: new players only on incremental
        # runs (cached picks are kept); --full re-picks every photo.
        if not args.skip_fetch:
            photo_args = ("--refresh",) if args.full else ()
            run(_module_cmd("fetch_player_images", *photo_args), dry_run=args.dry_run)
        run(_module_cmd("export_web"), dry_run=args.dry_run)

    # -- phase 6: publish (opt-in). frontend/scripts/deploy.mjs builds the static
    # export and uploads it with wrangler; it refuses if over Pages' file limits.
    if args.deploy:
        npm = shutil.which("npm")
        if npm is None and not args.dry_run:
            raise HaltError("--deploy needs npm on PATH (Node.js) to build and upload the site")
        run([npm or "npm", "run", "deploy"], cwd=PROJECT_ROOT.parent / "frontend", dry_run=args.dry_run)

    logger.info("\n%s", "=" * 70)
    logger.info("Done. Outputs:")
    logger.info(
        "  * player_ratings_career_%s_%s.xlsx (career rankings + CLR)",
        args.start_year,
        year,
    )
    logger.info("  * player_ratings_<year>.xlsx       (per-year workbooks)")
    if not args.skip_elo:
        logger.info("  * info/ending_elos_%s.csv     (refreshed regional Elos)", year)
    if not args.skip_web:
        logger.info("  * frontend/public/data/current/  (website JSON bundle)")
    if args.deploy:
        logger.info("  * Cloudflare Pages deploy           (frontend/out/)")
    logger.info("=" * 70)
    return 0


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(
        description="Pull latest Leaguepedia/Oracle data and recompute LPS scores + rankings.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument(
        "--full",
        action="store_true",
        help="full rebuild: re-pull everything, recompute the whole Elo chain and all years",
    )
    ap.add_argument(
        "--year", type=int, default=None, help="target year (default: newest Oracle CSV)"
    )
    ap.add_argument(
        "--start-year", type=int, default=DEFAULT_START_YEAR, help="first year in the career range"
    )
    ap.add_argument("--skip-fetch", action="store_true", help="no network; recompute from cache")
    ap.add_argument(
        "--skip-oracle", action="store_true", help="don't pull new Oracle's Elixir CSVs"
    )
    ap.add_argument("--skip-achievements", action="store_true", help="don't re-fetch achievements")
    ap.add_argument("--skip-regions", action="store_true", help="skip the unmapped-team guard")
    ap.add_argument("--skip-elo", action="store_true", help="don't recompute regional Elo")
    ap.add_argument("--skip-web", action="store_true", help="don't rebuild the website JSON bundle")
    ap.add_argument(
        "--deploy", action="store_true", help="finally build + upload the site to Cloudflare Pages"
    )
    ap.add_argument("--dry-run", action="store_true", help="print the plan; run nothing")
    # Scoring knobs -- default None so career.py's finalized defaults win unless set.
    ap.add_argument("--min-games", type=int, default=None)
    ap.add_argument("--intl-weight", type=float, default=None)
    ap.add_argument("--alpha", type=float, default=None)
    ap.add_argument("--lam", type=float, default=None)
    ap.add_argument("--beta", type=float, default=None)
    args = ap.parse_args()

    try:
        return orchestrate(args)
    except HaltError as e:
        logger.error("\nHALTED: %s", e)
        return 2
    except subprocess.CalledProcessError as e:
        logger.error("\nStep failed (exit %s): %s", e.returncode, " ".join(e.cmd))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
