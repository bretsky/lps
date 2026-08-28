# LPS Website — Roadmap & Next Steps

A living execution tracker for the rankings website. Pairs with **`docs/website-plan.md`** (the
full design/architecture) — this doc is "where we are and what to do next." Update as we go.

_Last updated: 2026-08-28._

---

## Current status

- ✅ **Design plan** written & iterated — `docs/website-plan.md` (tiers, trading cards, granular
  breakdown, N-sided percentile radar on the card back, static-JSON architecture).
- ✅ **Key decisions locked** (see plan §11.1): static precomputed JSON; **Next.js + React + TS +
  Tailwind**; **public/indexed**; **launch as beta**; **rated-floor** inclusion; **real photos
  where licensed** (monogram fallback); **contribution phase-split (laning/teamplay) DROPPED** —
  by-stat-source split only (LPL has no `@15` timeline data on any free source; see plan §6.1).
- ✅ **Repo reorganized** into `backend/` + `frontend/` (commit `3332c1b`). Backend verified:
  imports, `PROJECT_ROOT`, data paths, `latest_oracle_year()=2026` all resolve from `backend/`.
- ⬜ **P0 (export step) — NOT STARTED. ← next.**

Data reality check (already measured): career workbook = **3,715 players × 102 columns ≈ 6.3 MB**
raw JSON. Slim index ≈ 90 KB gzipped. Static approach is validated.

---

## P0 — Export bundle (`backend/src/lps/export_web.py`) ← NEXT

Goal: one Python module that turns the career workbook into a versioned static JSON bundle the
frontend consumes. Read the existing `player_ratings_career_2011_2026.xlsx` (or build in-memory via
`career.build_and_write` internals) and emit into `frontend/public/data/<build_id>/`.

**Concrete tasks:**

1. **Header→key mapping.** The workbook sheets use friendly headers ("CLR", "CareerVal",
   "CareerLPS", "Teams (by CLR)", per-year "2011".."2026", tournament cols "WLDs"/"MSI"/…). Invert
   `career._career_layout` / `export_excel._COLUMNS` to map headers back to canonical keys, so the
   export stays in sync with the workbook. (Sheets: `Overview` + `Top/Jungle/Mid/Bot/Support`.)
2. **`index.json`** — slim rows for the board (all rated players): `rank, slug, player, tier, lane
   (position), team, league, region_elo, clr, career_lps (CareerLPS), peak_lps, n_years, win_rate,
   first_year, last_year, active, partial_latest_season`.
3. **`players/<slug>.json`** — full detail per player: CLR + weighted components
   (`career_value/pace_value/peak_value/resume_bonus`), résumé breakdown (9 `rb_*` categories: #
   and Pt), phase (`reg/playoff/tourn_pts`), component (`base/contrib/wbonus_pts`), **by-stat-source
   (`kills/deaths/assists/damage/fb_pts`)**, per-tournament cols, per-year trajectory
   (`y2011..y2026`), High Noon (`hn_*`), per-game rates (`pts_per_game`, `pts_per_game_w`,
   `clutch_gap`, `avg_contrib`, `avg_resid`, `avg_p_model`, `sched_strength`), splits
   (`teams_lps/leagues_lps/lanes_lps`), and the **`radar`** object (below).
4. **Percentile radar (`radar`)** — compute 0–100 percentiles via `rank(pct=True)*100` for the 7
   axes (plan §3.3): Peak (`peak_lps`), Longevity (`total_score`/CareerLPS), Consistency
   (`pace_value`), Résumé (`resume_bonus`), Impact (`contrib_pg_w`), Clutch (`clutch_gap`),
   Dominance (`hn_global`/`hn_lane`, **inverted**). Store **both** `global` (vs all) and `lane` (vs
   same position), plus the raw value behind each axis for tooltips.
5. **Tier binning (`tiers.json`)** — **hybrid**: hard caps on GOATs/Legends (e.g. ~top 5–10 / next
   band) + percentile bands below (Greats/Elite/Stars/Contenders). Compute once here; store label +
   numeric cutoffs per tier. Assign each player their `tier` in `index.json`. Decide global-only vs
   per-lane tiers by eyeballing the CLR distribution.
6. **Rated floor** — filter `index.json`/`players` to a career-games / min-CLR threshold (tune
   against the distribution). Keep raw data complete underneath. Log how many were trimmed.
7. **Slugs / identity** — build stable URL-safe slugs from canonical player name; **verify
   `playername` uniqueness against `player_identity.py`** and add collision suffixes before URLs go
   public.
8. **`meta.json`** — `build_id` (date/content hash), generated date, year range, weights, era
   mults, and **`beta: true`**. **`glossary.json`** — from `export_excel._GLOSSARY` (tooltips).
9. **Rounding** — 2–3 sig figs server-side to shrink payloads.
10. **Wire into `update_all.py`** — regenerate the bundle after a data refresh (optional for POC;
    can run `export_web` standalone first).
11. **Verify** — sample a few known players (e.g. Faker, a one-year peak like Marin) and sanity-
    check tiers, radar shape, and that component columns sum to CLR.

**POC shortcut:** for the first pass, `index.json` + a handful of `players/*.json` + `tiers.json` +
`meta.json` is enough to build the board and one card. Full per-player fan-out can follow.

---

## P1–P4 (see plan §10 for detail)

- **P1 — Board (Feature A):** scaffold Next.js in `frontend/`; tiered leaderboard over `index.json`;
  filters (lane/region/era/active), sort, fuzzy search; per-lane boards; virtualized list.
- **P2 — Profile (Feature C):** `/player/<slug>` drill-down — CLR waterfall → phase/component/**by-
  stat-source** → trajectory → splits; glossary tooltips everywhere.
- **P3 — Cards (Feature B):** one `PlayerCard` component (3 render targets: page, OG image, PNG);
  tier-rarity frames; **flip-to-back percentile radar** (global↔lane toggle); `/card/<slug>` +
  `@vercel/og`; PNG download; `/compare` overlay.
- **P4 — Polish:** art direction (foils/rarity), mobile/a11y, About/methodology, analytics, domain.

---

## Parallel / pre-launch (non-blocking for engineering)

- **Legal & attribution** (plan §12) — Riot fan-content disclaimer, Oracle's Elixir attribution,
  Leaguepedia CC-BY-SA, team-logo trademark caution, player-photo licensing. Gates go-live, not P0.
- **Assets** — team crests / region crests / lane icons; tier frames & foils; player photos where
  licensed (monogram fallback).
- **Hosting** — Vercel/Cloudflare account + domain name.

## Decide-during-build (safe defaults exist)

Tier final cutoffs & labels (+ per-lane tiers?); radar axis count 5–8 & card-back default
(global); compare breadth; update cadence & deploy trigger; analytics.

---

## Loose ends

- Empty `info/` shell at repo root wouldn't delete during the reorg (stray Windows file handle;
  git ignores empty dirs so it's harmless). Remove once the handle releases.
