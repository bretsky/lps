# CLAUDE.md

Guidance for working in this repo. Read alongside `README.md` (user-facing setup) — this file focuses on how the code actually fits together and the non-obvious gotchas.

## What this is

**LPS (League Performance Score)** — a League of Legends esports analytics system that quantifies how much each player contributes to their team's win probability (a WAR-like metric). It has three loosely-coupled subsystems:

1. **Player contribution / win-probability models** — trained on Oracle's Elixir match data.
2. **Regional Elo estimation** — derived from international tournament results scraped from Leaguepedia.
3. **Data ingestion** — loaders for Oracle CSVs and a Leaguepedia (Cargo) API client.

Python 3.12+, managed with **Poetry**, src-layout package under `src/lps/`.

## Environment & commands

```bash
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
