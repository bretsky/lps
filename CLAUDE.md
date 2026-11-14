# CLAUDE.md

Guidance for working in this repo. Read alongside `README.md` (user-facing setup) — this file focuses on how the code actually fits together and the non-obvious gotchas.

## What this is

**LPS (League Performance Score)** — a League of Legends esports analytics system that quantifies how much each player contributes to their team's win probability (a WAR-like metric). It has three loosely-coupled subsystems:

1. **Player contribution / win-probability models** — trained on Oracle's Elixir match data.
2. **Regional Elo estimation** — derived from international tournament results scraped from Leaguepedia.
3. **Data ingestion** — loaders for Oracle CSVs and a Leaguepedia (Cargo) API client.

Python 3.12+, managed with **Poetry**, src-layout package under `backend/src/lps/`.

## Repo layout

The repo is split into `backend/` (this Python system) and `frontend/` (the rankings website, see
`docs/website-plan.md`). **All backend commands run from `backend/`** and all paths below
(`src/lps/`, `data/`, `info/`, generated `player_ratings_*.xlsx`) are relative to `backend/`.
`config.PROJECT_ROOT` resolves to `backend/`. `README.md`/`CLAUDE.md`/`docs/` stay at the repo root.

One-off investigation/debug scripts go in **`backend/analysis/`**, not `src/lps/` or the
`backend/` root. They're kept for reference and aren't part of the pipeline (see its README).

## Environment & commands

```bash
cd backend                                  # all backend commands run from here
poetry install                              # install deps + dev tools
poetry run python -m lps.<module>           # run any module's main()
poetry run pytest                           # tests (pytest configured, few/none exist yet)
poetry run black src/ && poetry run isort src/   # format
poetry run mypy src/                        # type-check
```

Most modules are runnable scripts with a `main()` and `if __name__ == "__main__"`. Prefer `python -m lps.<module>` over invoking files directly (src-layout + relative imports require package context).

Credentials live in `.env` (gitignored): `LP_USERNAME` / `LP_PASSWORD` are Leaguepedia bot passwords, only needed for fetching Leaguepedia data. `config.py` loads `.env` at import.

## Module map (`src/lps/`)

| Module | Role |
|---|---|
| `update_all.py` | **Master driver** — pull latest LP/Oracle data → recompute Elos → rebuild all scores/rankings. Start here (see below). |
| `config.py` | Paths + env. **Single source of truth for directory locations.** |
| `io_oracle.py` | Load Oracle's Elixir CSVs by year → concatenated `DataFrame`. |
| `lp_client.py` | `LPClient` — Leaguepedia Cargo query wrapper with exponential backoff. |
| `fetch_international_matches.py` | Script: pull MSI/Worlds/etc. matches → `data/leaguepedia/matches/*.json`. |
| `extract_team_names.py` | Script: derive unique team names from matches → `team_regions_<year>.csv` stubs to fill in. |
| `team_regions.py` | Load/validate the (manually filled) team→region mappings per year. |
| `team_regions.py` / `team_regression.py` | Note the two similar names: `team_regions` = region mapping; `team_regression` = a regression model over team stats. |
| `regional_elo.py` | Script: compute per-region Elo year-by-year from international match outcomes. |
| `player_contribution.py` | "Model 1" — expected (baseline) player performance given game state. |
| `win_probability.py` | "Model 2" — win prob from actual per-lane performance (single-model). |
| `win_probability_ensemble.py` | Ensemble variant: 5 position models + a meta-model. This is the primary/current win-prob model. |
| `top.py` | Standalone top-lane LPS v1 experiment (career value, replacement-level). |
| `main.py` / `top.py` | Scratch/experiment entry points — not the "real" pipeline. |

## Data layout & the important gotcha

- **Oracle's Elixir CSVs** → `data/oracle/` (one per year, `<year>_..._OraclesElixir.csv`). Loaded via `io_oracle`.
- **Leaguepedia match JSON** → `data/leaguepedia/matches/`.
- **Region mappings, starting/ending Elos** → the top-level **`info/`** directory (`INFO_DIR = PROJECT_ROOT / "info"` in `config.py`).

⚠️ **The README says region/Elo files live in `data/leaguepedia/info/`, but the code reads them from the top-level `info/` dir.** Trust `config.py` (`INFO_DIR`), not the README, for where these files actually go. Files: `team_regions_<year>.csv`, `starting_elos_<year>.csv`, `ending_elos_<year>.csv`.

- `data/` is entirely **gitignored** — the large CSVs and scraped JSON are not in version control. `info/` IS committed (region mappings + computed Elos are the valuable hand-curated artifacts).
- `player_above_expected_metrics.csv` at the repo root is a large (~75 MB) generated output, not source.

## Elo workflow (year-by-year, the recommended path)

The Elo pipeline chains year to year — each year's `ending_elos` seed the next year's `starting_elos`:

1. `fetch_international_matches` → match JSON.
2. `extract_team_names` → `info/team_regions_<year>.csv` stubs; **fill in the `region` column by hand**.
3. `team_regions` → validate completion.
4. Create `info/starting_elos_<year>.csv`, then `python -m lps.regional_elo --year <year>` → writes `ending_elos_<year>.csv`.

Elo config lives as module constants in `regional_elo.py` (`DEFAULT_ELO=1000`, `K_FACTOR=64`). Teams with region `N/A` are excluded.

## Master update (`update_all.py`) — the one command to run

`python -m lps.update_all` orchestrates the whole "new data upstream → refreshed workbooks on disk" flow via subprocess (same driver pattern as `rerun_elos.py`). Two modes:

- **Incremental (default)** — refresh only the *latest* year end-to-end, reuse everything cached for prior years. The day-to-day run.
- **Full (`--full`)** — re-pull everything, recompute the entire `2011→latest` Elo chain (via `rerun_elos.py --run`) and every per-year score. Use after a model/scoring change or region edits.

Pipeline order: **preflight** (resolve target year from newest Oracle CSV; verify CSV + LP creds) → **pull LP** (force-refresh current-year match JSONs + re-fetch achievements) → **region guard** → **regional Elo** → **scores** (`career.py`).

Non-obvious behaviors that keep it safe — preserve these if you touch it:

- **Never calls `extract_team_names`** — that script overwrites *every* `team_regions_<year>.csv` with a blank `region` column, wiping hand-filled mappings. `update_all` instead reuses `extract_team_names_by_year` read-only, **appends** only brand-new teams (blank region, existing rows untouched), and then **halts** if any current-year team is unmapped (Elo is only correct once every international team has a region).
- **Force-refreshes current-year match JSONs** by deleting `data/leaguepedia/matches/*<year>*.json` (excluding `*_all.json`) before `fetch_international_matches`, because that fetcher is cache-only (`force_refetch=False`) and won't otherwise re-pull an in-progress event. Older years' caches are left alone.
- **Incremental recompute** busts *only* `data/cache/match_features_<year>_*.pkl`, then runs `career --no-recompute` — which rebuilds that one year and reuses the rest (see `season._match_features` cache logic).
- **Backs up** `info/achievements*.csv` / `info/player_awards*.csv` to `info/backup_auto/` before `fetch_achievements` overwrites them.
- A brand-new year with no `starting_elos_<year>.csv` halts and points to `--full` (only `rerun_elos.py` knows how to reseed boundaries across renames/merges).

Useful flags: `--dry-run` (print the plan, run nothing), `--year N`, `--skip-fetch` (recompute from cache, no network), `--skip-elo`, `--skip-achievements`, `--skip-regions`. Exit codes: `2` = halted on a human-only prerequisite, `1` = a subcommand failed.

### Adding a new season (first-time setup for year `YYYY`)

The "latest year" is dynamic (`io_oracle.latest_oracle_year`, from the newest Oracle CSV), so most of the rollover is automatic — but a brand-new year has two human-only gates that `update_all` deliberately halts on:

1. Drop the `YYYY` Oracle CSV into `data/oracle/` (filename must contain the year).
2. `update_all` → **halts at the region guard**; fill `region` in `info/team_regions_YYYY.csv` (use `N/A` to exclude a team — a *blank* keeps halting).
3. Seed `info/starting_elos_YYYY.csv` from `ending_elos_<YYYY-1>.csv` (rename `ending_elo`→`starting_elo`; apply any region merges/renames at this boundary). Skipping it makes `update_all` carry the prior year forward with a warning; `--full` reseeds every boundary via `rerun_elos.py`.
4. Re-run `update_all` (`--skip-fetch` to reuse the first run's pull).

Watch for the annual "current year = 2025"-style caps if you add cross-year logic — they've bitten before (`career.oracle_ok`, `rerun_elos.YEARS`, `fetch_*` year bounds all now derive from data/`datetime` instead of a literal).

## Conventions

- **Config via `@dataclass`**: models take a typed config dataclass (e.g. `EnsembleConfig`, `ExpectedPerformanceConfig`, `TopLaneConfig`) with hyperparameters as fields and sensible defaults. Add tunables there rather than as loose function args.
- `from __future__ import annotations` at the top of every module; type hints throughout.
- Column-name resilience: Oracle schemas vary across years, so loaders/models detect column names with fallbacks (see `top._detect_cols`). Preserve this defensiveness when touching data-loading code.
- `logging.basicConfig(...)` is set up per-module; use `logging`, not bare `print`, for status output (some older code still prints).
- Positions/roles are consistently `("top", "jng", "mid", "bot", "sup")`; Oracle team-level rows have `position == "team"` and must be filtered out for player-level analysis. Filter to `datacompleteness == "complete"` where present.

## When making changes

- Paths: always import from `config.py`; don't hardcode `data/` or `info/`.
- New model? Follow the two-stage framing already documented in the module docstrings (expected performance → win prob → contribution = (actual − expected) × ∂WinProb/∂stat).
- Keep `README.md` and this file in sync when directory conventions or workflows change — they've already drifted once (the `info/` path).
