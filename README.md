# LPS — League Performance Score

A League of Legends esports analytics system that quantifies each player's contribution to their
team's win probability (a WAR-like metric), plus an all-time career ranking (CLR) and a public
rankings website.

The repo is split into two projects:

| Folder | What it is |
|---|---|
| **`backend/`** | The Python analytics system — win-probability models, regional Elo, data ingestion, and the ratings/CLR pipeline that generates the `player_ratings_*.xlsx` workbooks. Managed with Poetry. See [`backend/README.md`](backend/README.md) and [`CLAUDE.md`](CLAUDE.md). |
| **`frontend/`** | The rankings website (tiers, trading cards, granular score breakdowns) that consumes a JSON bundle exported from the backend. See the build plan in [`docs/website-plan.md`](docs/website-plan.md). |

## Quick start (backend)

```bash
cd backend
poetry install
poetry run python -m lps.career        # build the career ranking workbook
```

## Publishing the site

The site is a fully static Next.js export hosted on **Cloudflare Pages** (no server). The
backend writes the data bundle to `frontend/public/data/current/`; `frontend/scripts/deploy.mjs`
builds every page from it into `frontend/out/` and uploads that with `wrangler`.

```bash
cd backend && poetry run python -m lps.update_all --deploy   # refresh data, then publish
cd frontend && npm run stage                                 # build out/ only, no upload
cd frontend && npm run deploy                                # build + upload the current bundle
```

One-time setup: `npx wrangler@4 login`, then
`npx wrangler@4 pages project create lps --production-branch main`, then add the custom domain
under the project's *Custom domains* tab in the Cloudflare dashboard. Deploys from `main` go to
production; from any other branch, to a `<branch>.lps.pages.dev` preview.

Limits to keep in mind: Pages allows 20,000 files per site on the free plan (100,000 paid) and
25 MiB per file. The script checks both before uploading. Today's build is about 8.7k files
(four per player: profile and card, each as HTML plus an RSC payload). The JSON bundle itself
isn't uploaded, since the site only reads it at build time, and past bundles are archived to
`frontend/data-archive/`, outside `public/`.

## Docs

- [`docs/website-plan.md`](docs/website-plan.md) — full website build plan (data pipeline, tiers, cards, breakdowns).
- [`docs/holistic-lps-plan.md`](docs/holistic-lps-plan.md) — the CLR (Career Legend Rating) design.
- [`CLAUDE.md`](CLAUDE.md) — how the backend fits together + non-obvious gotchas.
