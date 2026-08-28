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

## Docs

- [`docs/website-plan.md`](docs/website-plan.md) — full website build plan (data pipeline, tiers, cards, breakdowns).
- [`docs/holistic-lps-plan.md`](docs/holistic-lps-plan.md) — the CLR (Career Legend Rating) design.
- [`CLAUDE.md`](CLAUDE.md) — how the backend fits together + non-obvious gotchas.
