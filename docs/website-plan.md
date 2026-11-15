# LPS Rankings Website — Build Plan

Status: **planning only** (no code yet). This document scopes everything needed — data
pipeline (backend), frontend, and the three signature features (**Tiers**, **Trading Cards**,
**Granular Score Breakdown**) — for a public site that displays the LPS all-time rankings.

Inspirations: [Adjusted Hockey PPS](https://adjustedhockey.com) (tiered all-time board,
"resume"-style pages) and Riot's *Hall of Legends* (cinematic, card-forward, League-native
art direction) — reinterpreted with our own LPS/CLR data and a League-esports skin.

---

## 1. Decisions locked in

| Decision | Choice | Why |
|---|---|---|
| Data delivery | **Static precomputed JSON** (Phase 1) | The whole dataset is small (see §3). No server/DB to run or pay for. Updates = re-run pipeline + redeploy. |
| Frontend | **Next.js (App Router) + React + TypeScript + Tailwind** | Best-in-class for static export *and* rich interactive cards; SSG for SEO/share previews; huge ecosystem for the SVG/canvas card rendering and charts we need. |
| Hosting | **Vercel or Cloudflare Pages** (static) | Free tier is plenty; global CDN; instant preview deploys; trivial custom domain. |
| Charts | **Recharts** (or visx if we outgrow it) | Declarative React charts for trajectory/breakdown; visx for the bespoke waterfall if needed. |
| Card sharing | **Server-generated OG images** via `@vercel/og` / Satori + a client "download PNG" via `html-to-image` | One code path renders both the on-page card and the shareable image. |

**The static-first bet (validated).** The generated `player_ratings_career_*.xlsx` Overview is
3,715 players × 102 columns ≈ **6.3 MB** raw JSON, **5.3 MB** as the xlsx. That is *tiny*:

- A **slim ranking index** (rank, name, CLR, tier, lane, team, region, a few headline stats —
  ~12 fields) is ≈ 400–600 KB raw, **~90 KB gzipped**. Loads instantly, filter/sort entirely
  client-side.
- **Per-player detail** (all 102 columns + per-year trajectory) split into one small JSON per
  player (~1–3 KB each), fetched on demand when a card/profile opens. 3,715 tiny files sit
  behind the CDN with no runtime cost.

So every feature we want is achievable statically and fast. See §9 for the precise threshold at
which we'd graduate to a cheap API — none of the launch features cross it.

---

## 2. What the data already gives us (no model work needed)

Everything below is **already produced** by `lps.career` in the career workbook. The website is a
presentation layer over these columns — no new metrics required for v1.

**Identity / context:** `playername`, primary `team`, `league`, `position` (lane), `region_elo`,
`first_year`/`last_year`, `n_years`, `games`, `win_rate`.

**Headline score & tier driver:** `clr` (Career Legend Rating — the primary ranking), plus its
weighted components that **sum to CLR**: `career_value`, `pace_value`, `peak_value`,
`resume_bonus`.

**Résumé (hardware):** `intl_bonus`, `title_bonus`, `award_bonus`, and the 9-category breakdown
with count + weighted points each: Worlds titles, Worlds deep runs, MSI, other intl, domestic
champ/final/cup, MVP, All-Pro (`rb_*_n` / `rb_*_pts`).

**Career shape:** `total_score` (CareerLPS), `lps_per_year`, `peak_year`, `peak_lps`,
`peak_years`, `peak_band_avg`, and the **per-year trajectory** `y2011…y2026` (one column per
season — this is the spark for the trajectory chart).

**Peer dominance (companion):** High Noon ranks `hn_lane_best`, `hn_lane`, `hn_global_best`,
`hn_global` (+ the years that compose them).

**Granular score sources (the breakdown engine):**
- By phase: `reg_pts`, `playoff_pts`, `tourn_pts`
- By component: `base_pts`, `contrib_pts`, `wbonus_pts`
- By stat source (sum to Contribution): `kills_pts`, `deaths_pts`, `assists_pts`, `damage_pts`
- Per tournament: dynamic `WLDs`, `MSI`, `EWC`, … columns
- Per-game rates: `pts_per_game`, `pts_per_game_w`, `clutch_gap`, `avg_contrib`, `avg_resid`
  (Intangibles), `avg_p_model`, `sched_strength`, `best_game`, `worst_game`

**Career splits (already formatted for display):** `teams_lps`, `leagues_lps`, `lanes_lps` —
"T1 (245.3), DAMWON Gaming (30.1)" style, orderable as shares with `--breakdown-pct`.

**Glossary:** `export_excel._GLOSSARY` is a ready-made, curated column dictionary → ship it as the
site's tooltips/definitions so every stat is explainable inline.

> The site should treat **CLR** as the canonical rank and **CareerLPS/peak/résumé** as the story
> behind it — exactly the decomposition the workbook already exposes.

---

## 3. Backend = a new export step (Python, in-repo)

No server. Add one module, `backend/src/lps/export_web.py` (sibling to `export_excel.py`), that reads the
same in-memory career frames (or the workbook) and emits a **versioned static asset bundle** the
frontend consumes. Wire it into `update_all.py` so a data refresh regenerates the site data.

### 3.1 Outputs (written to `frontend/public/data/<build_id>/`)

| File | Shape | Purpose |
|---|---|---|
| `index.json` | array of slim rows (all 3,715) | The ranking board: rank, name, slug, tier, lane, team, league, region, clr, careerLPS, peakLPS, n_years, win_rate, a headshot/team key. |
| `players/<slug>.json` | one object per player | Full 102-col detail + `y*` trajectory + résumé breakdown + splits + `radar` (global & lane percentiles, §3.3), for the card & profile. |
| `lanes/<lane>.json` | slim rows per lane | Per-lane boards (Top/Jungle/Mid/Bot/Support), each already ranked. |
| `tiers.json` | tier cutoffs + membership counts | Drives the tier rail and badges (see §4). |
| `meta.json` | build id, generated date, year range, weights, era mults | About page + cache-busting. |
| `glossary.json` | from `_GLOSSARY` | Inline stat definitions / tooltips. |

- **Slugs** are stable, URL-safe player ids (canonical lowercased name from `career._stack`, with
  collision suffixes) — used for `/player/<slug>` routes and card share URLs.
- **`build_id`** (date or content hash) namespaces each deploy so the CDN caches immutably and a
  redeploy never serves stale JSON. `meta.json` at a stable path points to the current build.
- Numbers rounded server-side (2–3 sig figs) to shrink payloads and standardize display.

### 3.2 Tier assignment (computed here, not in the frontend)

Tiers are a **presentation binning of CLR**, assigned once in `export_web.py` so the rule is
single-sourced and stable. Proposed League-themed ladder (top → bottom):

| Tier | Theme | Rough intent |
|---|---|---|
| **GOATs** | the pantheon | top ~0.3% / hard cap ~5–10 players |
| **Legends** | Hall-of-Legends tier | next elite band |
| **Greats** | perennial stars | |
| **Elite** | multi-year standouts | |
| **Stars** | strong starters | |
| **Contenders** | rated regulars | the long tail |

Binning method (pick in review): **percentile bands** (simple, stable), **natural gaps** in the
CLR distribution (k-means/jenks — reads more "earned"), or **hybrid** (hard caps on GOATs/Legends,
percentiles below). Export both the tier label and the numeric cutoffs so the frontend can show
"X CLR from the next tier." Optionally per-lane tiers too (a Support GOAT ≠ globally top-10 CLR).

### 3.3 Percentile radar axes (computed here — powers the card back, §5)

The radar needs each aspect expressed as a **0–100 percentile** so the shape is comparable across
players. Computed once in `export_web.py` with `frame[col].rank(pct=True) * 100`, stored on each
player's JSON as a `radar` object — **both** `global` (vs all 3,715) and `lane` (vs same-position
players only), since the frontend lets the viewer toggle the reference pool. Proposed **7 axes**
(roughly independent, each already a column from §2):

| Axis | Source column | Reads as |
|---|---|---|
| **Peak** | `peak_lps` / `peak_value` | how high they got at their best |
| **Longevity** | `total_score` (CareerLPS) or `n_years` | career bulk / staying power |
| **Consistency** | `pace_value` | per-year production, sample-shrunk |
| **Résumé** | `resume_bonus` | titles / placements / awards (hardware) |
| **Impact** | `contrib_pg_w` (weighted contribution per game) | per-game win-prob added |
| **Clutch** | `clutch_gap` | stepped up in higher-stakes games |
| **Dominance** | `hn_global` / `hn_lane` (**inverted** — lower rank = better) | peer standing across best seasons |

Notes: axes are a **design choice** finalizable in review (5–8 works; a radar reads best at 6–8).
Percentile (not raw value) is deliberate — it makes every axis unit-free and the polygon instantly
legible ("elite Peak, average Résumé"). `Clutch`/`Impact` can go negative in raw terms, but the
percentile mapping handles that automatically. We store the underlying raw value alongside each
percentile for the axis tooltip.

### 3.4 Assets (art direction)

- **Team logos & region crests:** map `team`/`league` → static SVG/PNG assets (a curated
  `frontend/public/assets/teams/*`). A `team_assets.json` keyed by the names Oracle/LP use.
- **Player photos:** optional; Leaguepedia has portraits but licensing must be checked before
  redistributing. v1 can ship a generated silhouette/monogram per player and layer in photos later
  where we have rights.
- **Tier/rank frames, foils, holo textures:** design assets for the card rarity system (§5).

---

## 4. Feature A — Tiers (the ranking board)

The landing experience: a **tier-stratified all-time leaderboard**.

- **Tier rail / bands:** the board is grouped into GOATs → Contenders bands (§3.2), each with its
  own color, crest, and a short definition. Adjusted-Hockey-style "shelves," but League-skinned.
- **Row = compact player line:** rank, name, team crest, lane icon, region, CLR, and a mini
  CLR-component bar (Career/Pace/Peak/Résumé stacked) so you read *why* they rank where they do at
  a glance. Hover → quick stats popover.
- **Controls (all client-side over `index.json`):** filter by lane / region / era / active-vs-
  retired; sort by CLR (default), CareerLPS, PeakLPS, résumé, longevity; text search with
  fuzzy-match on name.
- **Views:** Global board + per-lane boards (from `lanes/*.json`), toggle between them.
- **Tier badges** appear everywhere the player does (board, card, profile) for a consistent
  identity.

Performance: one ~90 KB gzipped fetch, then pure in-memory filter/sort — instant even at 3,715
rows (virtualized list for smooth scroll).

---

## 5. Feature B — Trading Cards (the signature shareable)

A **classic collectible-card** rendering of a player, designed to be screenshotted/shared.

**Card anatomy:**
- **Frame & rarity** driven by tier: GOATs = holo/foil legendary frame; down to a clean common
  frame for Contenders. Rank number and tier crest embossed.
- **Hero zone:** player photo/monogram, name, team crest, lane icon, region crest, active years.
- **Headline stat block:** big **CLR** with tier badge; secondary CareerLPS, PeakLPS, Peak year,
  win%, #years — the "stat line" on the card face.
- **Résumé ribbons:** Worlds/MSI/domestic title icons with counts (from `rb_*_n`) — the "hardware"
  strip, like championship pips.
- **CLR mini-decomposition:** a small stacked bar (Career / Pace / Peak / Résumé) so the card
  carries the *why*, not just the number.
- **Back of card (flip → the radar):** the card flips on a **3D `rotateY` animation** (CSS
  `transform-style: preserve-3d`, `backface-visibility: hidden` on each face) to reveal an
  **N-sided percentile radar/spider chart** (§5.1) as the hero of the back, with a condensed
  granular-breakdown summary (§6), High Noon peer rank, and career splits below it.

### 5.1 The percentile radar (card back)

A **7-axis radar** (Peak / Longevity / Consistency / Résumé / Impact / Clutch / Dominance — see
§3.3) plotting the player's **percentile (0–100) on each axis**, so the *shape* tells the story at
a glance: a spiky polygon = a specialist (e.g. huge Peak, thin Longevity — a Marin), a fat balanced
polygon = an all-time all-rounder (a Faker).

- **Reference toggle:** `vs all players` (global percentiles) ↔ `vs same lane` (lane percentiles) —
  both precomputed (§3.3); flipping the toggle just swaps which `radar.*` object feeds the chart.
- **Compare overlay:** on `/compare`, two players' polygons overlay on one radar (semi-transparent
  fills) — the cleanest possible "who's better at what."
- **Rendering:** Recharts `<RadarChart>` for the interactive card; for the OG/PNG share image the
  same axes render via an SVG polygon path (Satori-compatible) so the shared card back matches
  exactly. Axis labels carry glossary tooltips + the raw value behind the percentile.
- **A11y / reduced-motion:** the flip respects `prefers-reduced-motion` (cross-fade instead of 3D
  spin); the radar degrades to a labeled percentile table.

**Sharing:**
- Each card has a permalink `/card/<slug>` that renders server-side with an **OG image** (`@vercel/og`/Satori)
  so Twitter/Discord/Reddit unfurl a beautiful preview.
- "Download PNG" button uses the *same* React card component rasterized client-side
  (`html-to-image`) → identical art, no server round-trip.
- Optional "compare" mode: two cards side-by-side with a diff of key stats.

**Implementation note:** build the card as **one composable React component** parameterized by the
player JSON + tier theme tokens, rendered three ways (interactive page, OG image, PNG export) to
guarantee visual parity. Design in SVG/CSS (not canvas) so it scales crisply and Satori can render
it for OG.

---

## 6. Feature C — Granular Score Breakdown (the analytics centerpiece)

The `/player/<slug>` profile is where LPS earns credibility — a **drill-down from one number
(CLR) all the way to stat sources**, using the columns in §2. Progressive disclosure, top-down:

**Level 0 — CLR headline** with tier badge and rank (global + within-lane).

**Level 1 — CLR composition** (waterfall / stacked bar): `career_value + pace_value + peak_value +
resume_bonus = clr`. Each segment clickable to drill in. This is the "how is this score built"
view the request asks for.

**Level 2 — Résumé detail:** the 9 catgories (`rb_*`) as an icon grid with counts and weighted
points; Intl / Titles / Awards subtotals. Hover = which events/years (future: link to the source
achievements).

**Level 3 — CareerLPS anatomy:**
- **By phase:** Regular / Playoffs / Tourneys donut (`reg_pts`/`playoff_pts`/`tourn_pts`).
- **By component:** Baseline / Contribution / WinBonus.
- **By stat source:** Kills/Deaths/Assists/Damage bar (these *sum to Contribution*) —
  the most granular layer, showing *where on the rift* the value came from.
- **By tournament:** per-event bars (WLDs/MSI/EWC/…).

**Level 4 — Trajectory & peak:** a season-by-season line/area chart from `y2011…y2026`, with the
peak season(s) highlighted (`peak_year`, `peak_years` band) and the High Noon best-rank markers.

**Level 5 — Splits & context:** teams/leagues/lanes bars from `teams_lps`/`leagues_lps`/
`lanes_lps`; per-game rates (LPS/Gm, Clutch, Intangibles, SoS); region Elo context.

Every stat label carries a **tooltip sourced from the glossary** (`glossary.json`) so nothing is
unexplained. A "methodology" page links out to `docs/holistic-lps-plan.md` in plain language.

### 6.1 Contribution "phase" decomposition (laning / teamplay) — investigated, DROPPED

We evaluated adding a semantic **Laning vs Teamplay** split to the contribution breakdown (and a
corresponding radar axis). **Decision: do not build it.** Keep the uniformly-available **by-stat-
source** split (Kills / Deaths / Assists / Damage) as the most granular layer.

**Two reasons, both hard blockers:**

1. **Model consistency (the reconciliation invariant).** Everything the site displays must be a
   *partition of the number that drives the rank* — the by-source split already sums exactly to
   Contribution, just as `CareerVal+PaceVal+PeakVal+Resume` sums to CLR. A laning/teamplay split
   would require either (a) a **second, separately-trained model** on different features — which
   would disagree with the CLR-driving model game-to-game and produce the contradiction "strong
   breakdown, weak CLR (or vice-versa)"; or (b) **adding timeline features into the CLR model
   itself** — a scoring change that moves CLR and must be validated for signal gain and era-
   fairness first. Neither is a website task, and (a) is explicitly disallowed.

2. **Data coverage — the gap is UPSTREAM and unfixable on free data.** The laning phase needs
   Oracle's `@10/@15` timeline block (`golddiff/xpdiff/csdiffat10/15`, `kills/deaths/assistsat15`).
   That entire block is **missing for the LPL** (China) — and it is *not* an Oracle quirk:
   - **gol.gg**, an independent scraper, shows the identical hole — `GD@15 / CSD@15 / XPD@15`
     render as `-` for CN players while every other region is populated.
   - **Root cause:** LPL games run on **Tencent-operated Chinese tournament realms** that aren't
     exposed through the Riot spectator/live-client feed that Oracle *and* gol.gg both scrape. No
     spectator timeline → no `@`-time stats at all.
   - **Riot Match-V5 timeline API** doesn't help (LPL pro games aren't on the public-API realms).
   - The **only** source that carries LPL timeline is the **official licensed feed (Bayes Esports
     / GRID "LoL Data Portal")** — sourced from Riot directly, not scraped — which is B2B, access-
     gated, **paid**, and a heavy integration.

   Because even the "display-only, totals-preserved" re-partition depends on the same missing
   `@15` counts, a laning breakdown would be **structurally blind to the single largest region**
   on any free data — unacceptable for a site whose premise is fair *all-time, cross-region*
   comparison.

**Consequence for the plan:** the radar (§3.3) keeps its 7 uniformly-available axes (no Laning
axis); the breakdown (§6, Level 3) keeps the by-stat-source bars. If a laning decomposition ever
becomes a priority, it is gated behind **licensing the Bayes/GRID feed** (see §9 tripwires) and a
separate scoring-model validation — not a free-data feature.

_Evidence (checked Aug 2026): Oracle FAQ/downloads; gol.gg LPL player stats (CN `@15` = `-`);
Riot×Bayes LoL Data Portal announcements; GRID data portal; Tencent-realm hosting._

---

## 7. Site map & routes

```
/                     Tiered all-time board (Feature A) + hero
/lane/<lane>          Per-lane board
/player/<slug>        Full profile w/ granular breakdown (Feature C)
/card/<slug>          Standalone shareable card (Feature B) + OG image
/compare?a=..&b=..    Two-player / two-card comparison
/tiers                Tier definitions & methodology-lite
/about                Methodology, weights, era adjustments, data sources, changelog
```

All pages **statically generated** at build time from the JSON bundle (`generateStaticParams`
over the slug list), so every route is a CDN document — no runtime compute.

---

## 8. Frontend architecture

```
frontend/
  app/                 # Next.js App Router routes (above)
  components/
    board/             # TierBand, PlayerRow, Filters, SearchBox, VirtualList
    card/              # PlayerCard (one component, 3 render targets), CardFlip, RarityFrame, ResumeRibbon, PercentileRadar
    breakdown/         # ClrWaterfall, PhaseDonut, SourceBars, TrajectoryChart, ResumeGrid
    common/            # TierBadge, LaneIcon, TeamCrest, StatTooltip (glossary-backed)
  lib/
    data.ts            # typed loaders for index/player/tiers/meta JSON
    tiers.ts           # tier theme tokens (colors, frames, crests)
    format.ts          # number/percent formatting, slug helpers
    types.ts           # generated TS types mirroring the export schema
  public/
    data/<build_id>/   # the export bundle (§3)
    assets/            # team crests, region crests, tier frames, foils, icons
```

- **Typed contract:** generate `types.ts` from the Python export schema (or hand-maintain a shared
  schema) so the frontend and `export_web.py` never drift. A tiny schema-check in CI guards it.
- **Design system:** Tailwind + a small set of theme tokens per tier (color, frame, glow). League-
  flavored: dark cinematic base, gold/hextech accents, per-region color coding.
- **State:** URL-driven filters/sort (shareable board states); TanStack Query or plain fetch+cache
  for the on-demand player JSON.
- **Perf:** virtualize the board list; lazy-load player JSON on row/card open; prefetch on hover;
  images as optimized static assets.
- **A11y & mobile:** cards and breakdown charts must degrade to readable tables; keyboard-navigable
  board; respects reduced-motion for foils/animations.

---

## 9. When to graduate to a live API (the tripwires)

Stay static until one of these is actually needed — then the cheapest step is a read-only API over
**SQLite/Postgres** (FastAPI) or even just Cloudflare D1 / a serverless function, keeping the same
JSON contract:

- **Full-text / advanced search** across all players+seasons that's too big to ship client-side
  (we're nowhere near — index is ~90 KB gzipped).
- **User accounts / voting / comments** (community "eye-test" overlays on the model).
- **Live/frequent data** (in-season weekly updates) where redeploy-per-update is too coarse.
- **Arbitrary cross-player queries / leaderboards** the precomputed bundles don't cover.
- **Per-match drill-down** using the ~75 MB `player_above_expected_metrics.csv` — too big to ship;
  if we want game-by-game detail on the profile, that's the first thing to put behind an API.
- **Laning/teamplay contribution split** — deferred (§6.1). Requires *both* a licensed timeline
  feed (Bayes/GRID, to cover LPL) **and** a validated contribution-model change; not a static-data
  feature.

None of Features A/B/C need this for launch. The migration is additive: same routes, loaders swap
`fetch('/data/...json')` → `fetch('/api/...')`.

---

## 10. Build phases (suggested)

1. **P0 — Export bundle:** `export_web.py` writes `index.json` + `players/*.json` + `tiers.json` +
   `meta.json` + `glossary.json`; tier binning decided; wired into `update_all.py`. *(Backend only;
   verifiable with a schema check + sample.)*
2. **P1 — Board (Feature A):** Next.js scaffold, tiered leaderboard, filters/search, per-lane
   boards. Ships a usable site.
3. **P2 — Profile (Feature C):** CLR waterfall → phase/component/source → trajectory → splits, all
   glossary-tooltipped.
4. **P3 — Cards (Feature B):** the card component, `/card/<slug>`, OG images, PNG download, compare.
5. **P4 — Polish:** art direction pass (foils/rarity), mobile/a11y, About/methodology, analytics,
   custom domain.

---

## 11. Decisions & remaining questions

### 11.1 Decisions locked (Aug 2026)

- **Audience: PUBLIC, indexed.** Triggers a legal/attribution bar before launch — see §12.
- **Model status: LAUNCH AS BETA.** Ship on current (provisional) CLR weights with a visible
  "provisional — rankings may change" framing. `meta.json` carries a `beta: true` flag; the site
  shows a persistent beta banner + a note on the About/methodology page. Weight calibration
  continues in parallel and reruns the export.
- **Inclusion: RATED FLOOR.** The public board filters to a career games / min-CLR threshold
  (exact value TBD in P0 by eyeballing the distribution) to trim the noisy tiny-sample tail. The
  full pool stays in the underlying data; `index.json` ships only rated players. (A future
  "explore all" toggle is easy to add later.)
- **Card art: REAL PHOTOS WHERE LICENSED.** Source player portraits pending a licensing check
  (§12); **monogram/silhouette is the fallback** per player where we don't have rights, so the
  card system must not hard-depend on a photo existing.
- **Contribution phase split: DROPPED** (§6.1) — by-stat-source split only.

### 11.2 Still open (decidable during build; safe defaults noted)

- **Tier cutoffs & labels:** method = hybrid (hard caps on GOATs/Legends + percentile bands
  below); final numeric cutoffs and whether to add **per-lane tiers** — tune in P0 against the CLR
  distribution. Labels: bespoke (GOATs/Legends/Greats/…) unless we prefer lore names.
- **Radar axes:** the 7 proposed (§3.3) as default; confirm count (5–8) & exact columns. Card back
  defaults to **global** percentiles with a lane toggle.
- **Player identity / slugs:** verify `playername` uniqueness against `player_identity.py` and add
  collision suffixes before URLs go public (P0).
- **Scope of card back / breadth of compare; update cadence & deploy trigger; analytics.**
- **Hosting account + domain name.**

---

## 12. Pre-launch legal & attribution checklist (public, indexed)

Because the site is public, these must be resolved before launch (none block P0/P1 engineering,
but they gate going live):

- **Riot fan-content compliance:** LoL, champion/player names, and any Riot IP are used under
  Riot's "Legal Jibber Jabber" fan-content policy — include the standard "not endorsed by Riot
  Games" disclaimer; no implication of official status; non-infringing use of marks.
- **Oracle's Elixir attribution:** the ratings derive from Oracle's Elixir data — display the
  required attribution/credit per their terms wherever data is shown (footer + About).
- **Leaguepedia (achievements/awards/portraits):** content is CC-BY-SA — attribute and preserve
  license terms for anything sourced from Leaguepedia (résumé data, and photos if used).
- **Team logos:** trademarked. Confirm acceptable fan-use or substitute neutral region/lane
  crests where a team's mark can't be used.
- **Player photos/likeness:** the "real photos where licensed" decision needs an explicit
  per-source rights check; ship monogram fallback everywhere a photo isn't cleared.
