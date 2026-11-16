# Deploying the site

The site is a fully static Next.js export (`output: "export"`) with no server, hosted on
**Cloudflare Pages**. `frontend/scripts/deploy.mjs` builds every page from the data bundle in
`frontend/public/data/current/` and uploads the result with `wrangler`.

## Commands

```bash
cd backend && poetry run python -m lps.update_all --deploy   # refresh data, then publish
cd frontend && npm run stage                                 # build out/ and out-i18n/ only, no upload
cd frontend && npm run deploy                                # build and upload the current bundle
```

To preview a staged build locally: `npx wrangler@4 pages dev out` from `frontend/`.

Wrangler deploys to production when the current git branch is `main` (the project's production
branch), and to a preview alias (`<branch>.lps-80q.pages.dev`) from any other branch.

Environment variables read by the script:

| Variable | Default | Meaning |
|---|---|---|
| `PAGES_PROJECT` | `lps` | Cloudflare Pages project name. |
| `PAGES_FILE_LIMIT` | `20000` | Per-deployment file cap the script checks against (100000 on a paid plan). |
| `NEXT_PUBLIC_SITE_URL` | `https://clr.brettselby.xyz` | Production origin used for canonical URLs, the sitemap and preview images (`frontend/lib/site.ts`). |

## First-time setup

1. `npx wrangler@4 login`
2. `npx wrangler@4 pages project create lps --production-branch main`
3. Add the custom domain under the project's *Custom domains* tab in the Cloudflare dashboard.

Cloudflare gives the project a `pages.dev` subdomain, adding a suffix when the name is taken (this
project's is `lps-80q.pages.dev`; wrangler prints it as the "Deployment alias URL"). That subdomain
is hard-coded in `frontend/functions-shared/i18n-proxy.js` (`SHARD_HOST`), so update it there if the
project is ever recreated or renamed, along with `PAGES_PROJECT` / the default in `deploy.mjs`.

The `i18n` branch deployment needs no setup of its own: the first `npm run deploy` creates it.

## What the script does

1. Checks that `public/data/current/` exists (written by `python -m lps.export_web`).
2. Builds in a copy of the app (`frontend/.build/`). Under `output: "export"`, `next build` always
   wipes and rewrites `.next/`, which would break a running `npm run dev`, so **never run
   `next build` in `frontend/` itself**.
3. Drops `out/data/`: the JSON bundle is only read at build time, so it isn't uploaded.
4. Copies the styled 404 page (`app/(en)/not-found-page`) over `out/404.html`. With two root
   layouts, Next only exports an unstyled one.
5. Moves the Korean and Chinese profiles (`out/{ko,zh}/player/`) to `out-i18n/`.
6. Checks both folders against the file-count limit and Pages' 25 MiB per-file limit.
7. Uploads `out-i18n/` as the `i18n` branch deployment (`i18n.lps-80q.pages.dev`) first, so the
   proxy below never points at a branch that lacks the profiles.
8. Uploads `out/` to production along with `frontend/functions/`.

## Why two deployments

A Pages deployment holds at most 20,000 files on the free plan, and the Korean and Chinese profiles
(about 8.5k files) don't fit beside the rest of the site. Production's
`functions/{ko,zh}/player/[[path]].js` proxy those paths from the `i18n` branch onto the site's own
domain (`functions-shared/i18n-proxy.js`), stripping the `X-Robots-Tag: noindex` header Pages adds
to branch deployments. Both uploads come from one build, so the profiles' `/_next/static` files are
production's own.

Every request that reaches a Pages Function counts toward the free plan's quota of 100k requests a
day, so the site never prefetches `/ko` or `/zh` profile links (`components/PlayerLink.tsx`).

`functions/` also serves the Naver Search Advisor verification file.

## File budget

Pages caps a site at 20,000 files (free) and 25 MiB per file, and everything in `public/` is copied
into the site, so keep bulky build-time inputs out of `public/`. Past data bundles are archived to
`frontend/data-archive/`, outside `public/`. Roughly:

- each player costs 5 files: profile and card (each HTML plus an RSC payload) and a preview PNG;
- each localized board or About page costs 4 files (`/ko` and `/zh`, HTML plus RSC payload);
- each board (today's and every past season) costs 6 CSV downloads (`/csv/<board>/<role>.csv`).

Every route must stay prerenderable (`generateStaticParams`, `force-static` route handlers, no
middleware, cookies or `next/image` optimisation), because production has no server.
