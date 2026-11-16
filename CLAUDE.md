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

Site assets: official event/league marks live in `frontend/public/icons/{events,leagues}/` (committed;
rebuilt by `backend/analysis/fetch_brand_icons.py`) and are mapped by league short name in
`frontend/lib/icons.ts`. The site's own mark is `frontend/app/icon.svg` (mid-lane frame + trophy); after
editing it, run `node scripts/build-icons.mjs` in `frontend/` to regenerate `app/favicon.ico` and
`app/apple-icon.png` from it. Player photos and team logos are hotlinked from Leaguepedia's CDN.

Search & link previews: the production origin is `SITE_URL` in `frontend/lib/site.ts`
(`https://clr.brettselby.xyz`; `NEXT_PUBLIC_SITE_URL` overrides it). Every page builds its title,
description, canonical URL and Open Graph / X preview through `lib/seo.ts`'s `pageMeta` (Next merges
metadata shallowly, so a page's `openGraph` must be complete). Titles and descriptions in all three
languages live in `lib/i18n/seo.ts` (`SEO`); `DocTitle` sets the same titles client-side when the reader's
language changes. `app/sitemap.ts` / `app/robots.ts` emit `/sitemap.xml` / `/robots.txt`. Preview
images are PNGs drawn at build time with `next/og` (`lib/og.tsx`): `/og/player/<slug>.png` per player,
`/og/site.png` for the boards (fonts from the `@fontsource/*` dev dependencies; no player photos, so
the build never hits Leaguepedia). Today's role boards are pages (`/role/{top,jungle,mid,adc,support}`);
the board's role tabs are links that rewrite the URL in place. Profiles end in a "Ranked nearby"
list and every board/profile/About footer links all role boards and past seasons (`SiteLinks`), so
crawlers can reach every page by plain links.

Languages: the site is English / Korean / Simplified Chinese. UI text lives in
`frontend/lib/i18n/{en,ko,zh}.tsx` (`en` defines the `Messages` shape; TypeScript flags a key a
translation lacks); components read it with `useT()`, server components with `<T k="…" />`. Any new
visible string goes in all three tables. Korean: never put a particle (이/가, 을/를, 로) straight after a
variable number; reword instead.
- **Boards, About and profiles have their own URLs per language** (`/ko`, `/zh/role/adc`,
  `/ko/about`, `/zh/asof/2016`, `/ko/player/faker`), prerendered in that language so search engines index them, with hreflang
  alternates. The app has two root layouts for this: `app/(en)/` (every unprefixed page) and
  `app/(intl)/[lang]/` (`<html lang>` + a fixed locale via `PageLocale` context); both render
  `components/RootDocument.tsx`. Page bodies are shared in `components/routes/` (`BoardRoute`,
  `AboutRoute`, `PlayerRoute`), so add a localized page there and wrap it in both groups. Moving between the two
  groups is a full page load (Next's rule for separate root layouts).
- **Cards are English URLs only**, translated in the browser. The reader's choice is kept in `localStorage`
  (`clr-locale`), defaulting to the browser language; `RootDocument`'s inline script applies it before
  paint, and visiting a `/ko` or `/zh` page saves that language.
- Links: the board's role tabs stay in the page's own language (`usePageLocale`); links that leave
  the page (back links, footer `SiteLinks`, About) go to the reader's language URL (`useLocale`,
  `LocalizedLink`). The language switcher is a set of links between `/`, `/ko`, `/zh` on localized
  pages and switches in place elsewhere. Profile links use `PlayerLink` (reader's language, and
  never prefetched for /ko, /zh: see below).
- **The Korean / Chinese profiles are a second Pages deployment.** They don't fit in production's
  20k files, so `scripts/deploy.mjs` moves `out/{ko,zh}/player/` to `out-i18n/`, uploads that as the
  `i18n` branch (`i18n.lps-80q.pages.dev`), then uploads production with `functions/`, whose
  `{ko,zh}/player/[[path]].js` proxy those paths from the branch onto the site's domain
  (`functions-shared/i18n-proxy.js`; it strips the `X-Robots-Tag: noindex` Pages puts on branch
  deployments). Same pattern as the pickems site's `/v/` snapshots. Every proxied request counts
  toward Pages Functions' daily quota (100k/day free), hence no prefetching of those links. The
  project name and branch are hard-coded in both `deploy.mjs` and the proxy: change them together.
- **404:** with two root layouts Next only exports an unstyled `404.html`, so `app/(en)/not-found-page`
  is built and `deploy.mjs` copies it over `out/404.html`.

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

**Frontend dev server: don't start one.** The user keeps `npm run dev` running on
`http://localhost:3000` (Next.js hot-reloads edits). Never run `npm run dev` / `next dev` yourself or
launch a second server on another port — open the existing one (`.claude/launch.json`'s `frontend`
entry attaches to :3000 without starting anything). If :3000 isn't responding, ask the user rather than
starting your own.

**Deploying the site.** Static export (`output: "export"`) to Cloudflare Pages via
`frontend/scripts/deploy.mjs` (`npm run stage` builds `frontend/out/` only; `npm run deploy` also
uploads with `npx wrangler@4`; `update_all --deploy` runs it last). Gotchas:
- **Never run `next build` in `frontend/` itself.** Under `output: "export"` it always wipes and
  rewrites `.next/` (a custom `distDir` only renames `out/`), which breaks the running dev server
  (500s: missing `middleware-manifest.json`). `deploy.mjs` builds in a `.build/` copy for this reason.
- Everything in `public/` is copied into the site, and Pages caps a site at 20,000 files (free) and
  25 MiB per file. `public/data/current/` is read only at build time, so the script drops `out/data/`;
  past bundles archive to `frontend/data-archive/` (outside `public/`, gitignored). Keep new bulky
  build inputs out of `public/` too. Each player costs 5 files (profile + card, each HTML + RSC payload, plus the preview PNG). Each
  localized board/About page costs 4 files (`/ko` + `/zh`, HTML + RSC payload).
- Every route must stay prerenderable (`generateStaticParams`, `force-static` route handlers, no
  middleware/cookies/`next/image` optimisation): there's no server in production.

Credentials live in `.env` (gitignored): `LP_USERNAME` / `LP_PASSWORD` are Leaguepedia bot passwords, only needed for fetching Leaguepedia data. `config.py` loads `.env` at import.

## Module map (`src/lps/`)

| Module | Role |
|---|---|
| `update_all.py` | **Master driver** — pull latest LP/Oracle data → recompute Elos → rebuild all scores/rankings. Start here (see below). |
| `config.py` | Paths + env. **Single source of truth for directory locations.** |
| `io_oracle.py` | Load Oracle's Elixir CSVs by year → concatenated `DataFrame`. |
| `refresh_oracle.py` | Pull changed/new season CSVs from OE's Google Drive folder into `data/oracle/` (port of draftpredict's `scripts/refresh_oracle.py`). Uses python-sharp's OAuth `token.json` (`PSHARP_PATH` overrides; default `../../python-sharp` from `backend/`); md5-diffed, validated (header kept, game count never drops; `--force`), atomic swap. `--check` reports only. |
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
| `fetch_player_history.py` | Script: per-player, per-year LP team history + team logo URLs → `data/leaguepedia/{player_history,team_logos}.json`. |
| `fetch_player_images.py` | Script: one Leaguepedia photo (+ real name, native-script name, country) per workbook player (the native name, `Players.NativeName`, is backfilled for cached players on every run) → `data/leaguepedia/player_images.json`. Shared handles ("Knight (LPL)") are matched to the right wiki page by roster votes (`player_identity`'s team-year bridge); picks the newest photo from inside the player's career. Pin/block a photo in `info/player_image_overrides.csv` (`label,file`). Also measures where each cutout's head is (`cx`, `ar`, `top`, `neck`; Pillow) so circular avatars centre and zoom on the face — unmeasured entries every run, `--refocus` for all. Also keeps the best photo from each season of a player's career (`player_images_by_year.json`, head-measured too) for the past-year boards: filled for everyone on the first run, then only for new players, so use `--refresh` to pick up newer seasons' photos. |
| `player_identity.py` | One display label per Oracle `playerid` (shared handles get a league qualifier: "Knight (LPL)"). Oracle sometimes gives one person two ids (Doran 2020–23): merge them in `info/player_id_aliases.csv` (`alias_playerid,canonical_playerid,note`). Labels are **baked into** `data/cache/match_features_*`/`lp_features_*`, so after an alias edit, delete the affected years' caches and rebuild. Leaguepedia-era (2011–15) rows only have a handle: a shared handle whose early seasons were in a league the person never played in Oracle's era (Piglet: SKT/OGN 2013–14, then NA only) can't bridge on its own and splits the career, so map it in `info/player_handle_bridge.csv` (`handle,years,teams,label,note`; `teams` limits a row to that person's rosters when another player shares the handle that year). Verify each row against Leaguepedia's `ScoreboardPlayers.Link` (the person's wiki page) for the team-years on both sides. This also bakes into caches (`lp_features_<year>*`, `match_features_<year>_*merged`). |
| `export_web.py` | Workbook + caches → the site's JSON bundle in `frontend/public/data/current/` (incl. `photo`, `real_name`, `name_ko` / `name_zh` — the Hangul / Chinese name the Korean / Chinese site shows instead, from `_local_names`, which skips Japanese players' kanji names — `honors`, `titles`). Profiles also get `champions` (top 10 by LPS earned on them) + `career_stats` (career K/D/A, KDA, CS, CS/min) from `career`'s `player_champions.json`: `season.build_player_ratings` exposes each game's exact share of season LPS (`attrs["game_credit"]`), which `career` scales by the per-year schedule/era multipliers and joins to Oracle/LP box scores, so champion LPS sums to CareerLPS. Champion icons are hotlinked from Data Dragon at the version pinned in `frontend/lib/icons.ts` (bump it when a new champion appears). Also `asof/<year>.json`: the board frozen at the end of each past season (site route `/asof/<year>`), built from `career`'s `player_ratings_asof.json` — every career number recomputed from seasons ≤ that year with today's models. Rated pool = 30+ career games (`RATED_MIN_GAMES`, about one full season, so a full-time rookie qualifies), scaled down for the short 2011–12 seasons; each past board uses that season's photo where one exists. Rows carry `rank_prev` / `clr_prev` (the previous season's board) for the movement arrows. `glossary.json` (site route `/about`) is every `export_excel._GLOSSARY` term with a readable site `label` and a plain-English definition from `export_web._web_glossary_text` (numbers filled from the About sheet / config defaults), plus `resume_scoring`: the résumé point tables, built from `achievements.BonusConfig` and the LPS tournament weights. When you add or rename a glossary term, give it a site wording there too (a term without one falls back to the workbook text, with a warning). Its Korean and Chinese wordings (and the résumé tables' labels) live in `web_glossary_i18n.py`, with numbers from the same context as the English, so add those too (a missing one falls back to English, with a warning). |
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

Pipeline order: **Oracle refresh** (`refresh_oracle`; any older season OE corrected also gets its feature cache busted; Drive unreachable → halt, `--skip-oracle` to use local CSVs) → **preflight** (resolve target year from newest Oracle CSV; verify CSV + LP creds) → **pull LP** (force-refresh current-year match JSONs + re-fetch achievements) → **region guard** → **regional Elo** → **scores** (`career.py`) → **photos** (`fetch_player_images`, new players only; `--full` re-picks all; skipped by `--skip-fetch`) → **web bundle** (`export_web`) → **deploy** (only with `--deploy`: `npm run deploy` in `frontend/`).

Non-obvious behaviors that keep it safe — preserve these if you touch it:

- **Never calls `extract_team_names`** — that script overwrites *every* `team_regions_<year>.csv` with a blank `region` column, wiping hand-filled mappings. `update_all` instead reuses `extract_team_names_by_year` read-only, **appends** only brand-new teams (blank region, existing rows untouched), and then **halts** if any current-year team is unmapped (Elo is only correct once every international team has a region).
- **Force-refreshes current-year match JSONs** by deleting `data/leaguepedia/matches/*<year>*.json` (excluding `*_all.json`) before `fetch_international_matches`, because that fetcher is cache-only (`force_refetch=False`) and won't otherwise re-pull an in-progress event. Older years' caches are left alone.
- **Incremental recompute** busts *only* `data/cache/match_features_<year>_*.pkl`, then runs `career --no-recompute` — which rebuilds that one year and reuses the rest (see `season._match_features` cache logic).
- **Backs up** `info/achievements*.csv` / `info/player_awards*.csv` to `info/backup_auto/` before `fetch_achievements` overwrites them.
- A brand-new year with no `starting_elos_<year>.csv` halts and points to `--full` (only `rerun_elos.py` knows how to reseed boundaries across renames/merges).

Useful flags: `--dry-run` (print the plan, run nothing), `--year N`, `--skip-fetch` (recompute from cache, no network; also skips the Oracle refresh), `--skip-oracle`, `--skip-elo`, `--skip-achievements`, `--skip-regions`, `--deploy` (publish the site at the end). Exit codes: `2` = halted on a human-only prerequisite, `1` = a subcommand failed.

### Adding a new season (first-time setup for year `YYYY`)

The "latest year" is dynamic (`io_oracle.latest_oracle_year`, from the newest Oracle CSV), so most of the rollover is automatic — but a brand-new year has two human-only gates that `update_all` deliberately halts on:

1. Nothing to do for the Oracle CSV: `update_all`'s Oracle refresh downloads a new season as soon as OE publishes it to Drive (or drop it into `data/oracle/` by hand; the filename must contain the year).
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
