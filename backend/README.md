# CLR backend

The Python half of [CLR](../README.md): data ingestion, the scoring models, regional Elo, and the
pipeline that writes the per-season and career workbooks and the website's JSON bundle.

Python 3.12+, managed with [Poetry](https://python-poetry.org/). Run every command from this
`backend/` folder; it's a src-layout package, so run modules with `python -m lps.<module>`.

## Setup

```bash
poetry install
cp .env.example .env
```

`.env` holds Leaguepedia credentials, which the pipeline needs to fetch international matches,
pre-2014 games, rosters, titles and photos:

```ini
LP_USERNAME=YourWikiUser@YourBotName
LP_PASSWORD=your_bot_password
```

To get them, sign in at [lol.fandom.com](https://lol.fandom.com/), open
`Special:BotPasswords`, and create a bot password with read access.

### Oracle's Elixir data

Game-level box scores from 2014 on come from [Oracle's Elixir](https://oracleselixir.com/), one
CSV per season in `data/oracle/` (the filename must contain the year, e.g.
`2025_LoL_esports_match_data_from_OraclesElixir.csv`). You can download them by hand from the site
and drop them in.

`lps.refresh_oracle` (run automatically by `update_all`) instead keeps them current through the
Google Drive API. It reuses an OAuth `token.json` with the Drive scope from a sibling project,
looked up at `../../python-sharp/token.json` or under `PSHARP_PATH`. Without one, download the CSVs
by hand and pass `--skip-oracle` to `update_all`.

## Updating scores and rankings

One command pulls the latest data and rebuilds everything:

```bash
poetry run python -m lps.update_all --dry-run   # print the plan, run nothing
poetry run python -m lps.update_all             # refresh the latest season, reuse cached earlier ones
poetry run python -m lps.update_all --full      # re-pull everything, recompute every season and the whole Elo chain
```

In order, it:

1. **Refreshes Oracle's Elixir CSVs** that changed upstream (and busts the caches of any older
   season Oracle's Elixir corrected).
2. **Preflight**: picks the target year from the newest Oracle CSV (`--year` overrides) and checks
   that the CSV and credentials are present.
3. **Pulls Leaguepedia**: re-fetches the current year's international matches and the
   achievements and awards tables (backing up the existing CSVs to `info/backup_auto/` first).
4. **Region guard**: any international team seen for the first time is appended to
   `info/team_regions_<year>.csv` with a blank region, and the run **stops** until you fill it in.
   Regional Elo is only right once every team has a region.
5. **Regional Elo**: recomputes `info/ending_elos_<year>.csv`.
6. **Scores**: rebuilds `player_ratings_<year>.xlsx` per season and
   `player_ratings_career_<first>_<last>.xlsx` (the career ranking and CLR) via `lps.career`.
7. **Photos**: picks Leaguepedia photos for new players.
8. **Web bundle**: writes the site's JSON to `../frontend/public/data/current/` via `lps.export_web`.
9. **Deploy**, only with `--deploy`: builds and uploads the site.

Useful flags: `--skip-fetch` (no network, recompute from cache), `--skip-oracle`,
`--skip-achievements`, `--skip-regions`, `--skip-elo`, `--skip-web`, `--year N`. Exit code `2` means
it halted on something only a person can do (such as filling in regions); `1` means a step failed.

### Adding a new season

The latest year is detected from the newest Oracle CSV, so a new season mostly rolls over on its
own. The first run of a new year `YYYY` needs two things by hand:

1. Run `update_all`. It downloads the new CSV, pulls the year's international matches, then halts
   at the region guard.
2. Fill in `region` for each new team in `info/team_regions_YYYY.csv`. Use `N/A` to exclude a team
   from Elo; a blank cell keeps halting the run.
3. Seed `info/starting_elos_YYYY.csv` from `info/ending_elos_<YYYY-1>.csv` (rename the
   `ending_elo` column to `starting_elo`, and merge or rename any regions that changed at the
   boundary). If you skip this, the prior year carries forward with a warning; `--full` reseeds
   every boundary through `rerun_elos.py`.
4. Run `update_all` again (`--skip-fetch` reuses the first run's pull).

## What lives where

| Path | Contents | In git? |
|---|---|---|
| `src/lps/` | The package (see the module map in [`../CLAUDE.md`](../CLAUDE.md)). | yes |
| `info/` | Hand-curated inputs and computed Elos: `team_regions_<year>.csv`, `starting_elos_<year>.csv`, `ending_elos_<year>.csv`, `player_id_aliases.csv` and `player_handle_bridge.csv` (identity fixes), achievements and awards, and an optional `player_image_overrides.csv` to pin or block a photo. | yes |
| `data/oracle/` | Oracle's Elixir CSVs. | no |
| `data/leaguepedia/` | Scraped Leaguepedia JSON (matches, player history, photos). | no |
| `data/cache/` | Per-season feature caches. Delete a season's files to force it to rebuild. | no |
| `player_ratings_*.xlsx` | Generated workbooks. | no |
| `analysis/` | One-off investigation scripts, not part of the pipeline. | yes |

## How the models fit together

Scoring is two-stage, retrained each season:

1. **Expected performance** (`expected_stats.py`, `player_contribution.py`): predicts the stat line
   an average player would produce in the same role and game state.
2. **Win probability** (`win_probability_ensemble.py`): five per-role models plus a meta-model
   predict a team's chance of winning from its players' actual stat lines.

A player's **contribution** in a game (`contribution.py`) is the change in predicted win
probability when their expected stat line is swapped for their real one. `season.py` turns contributions, win credit and
the regional Elo factor (`regional_elo.py`) into season LPS; `career.py` builds career value, pace,
peak and the résumé (`achievements.py`) into CLR. The site's
[About page](https://clr.brettselby.xyz/about) defines every number in plain language.

Regional Elo runs year by year over every international event Leaguepedia lists (Worlds, MSI,
First Stand, EWC, IEM, Rift Rivals, wildcard events and others; see
`fetch_international_matches.py`) with K = 64; a region with no seed starts at 1000. Each year's
ending Elos seed the next year's starting Elos.

## Development

```bash
poetry run pytest
poetry run black src/ && poetry run isort src/
poetry run mypy src/
```

[`../CLAUDE.md`](../CLAUDE.md) documents the module map, data layout and the non-obvious gotchas
(caches that bake in player identities, the year-rollover traps, and so on).
