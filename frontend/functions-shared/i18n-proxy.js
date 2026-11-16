// Serves /ko/player/<slug> and /zh/player/<slug> (and their .txt RSC payloads) on the site's own
// domain from the branch deployment that holds them, SHARD_HOST.
//
// Why: Cloudflare Pages caps a deployment at 20,000 files and the Korean and Chinese profiles
// (~8.5k files) don't fit beside the rest of the site. scripts/deploy.mjs builds everything once,
// moves those profiles to out-i18n/ and uploads them with `--branch i18n`; production keeps the
// rest, plus this function (functions/{ko,zh}/player/[[path]].js). Same build, so the profiles'
// /_next/static scripts and styles are production's own files: only the pages come through here.
//
// Every request that reaches a Pages Function counts toward its daily quota (100k/day on the free
// plan), so the site never prefetches these links (components/PlayerLink.tsx).

// <branch>.<project's pages.dev subdomain>: scripts/deploy.mjs uploads branch "i18n" of project "lps",
// whose subdomain is lps-80q.pages.dev (Cloudflare adds a suffix when a name is taken; see the
// "Deployment alias URL" wrangler prints).
const SHARD_HOST = "i18n.lps-80q.pages.dev";
const FILE = /^[a-z0-9-]{1,80}(\.txt)?$/; // a player slug, or its RSC payload

/** The site's own 404 page, with a 404 status. */
async function notFound(env, url) {
  const page = await env.ASSETS.fetch(new URL("/404", url));
  return new Response(page.body, { status: 404, headers: { "content-type": "text/html; charset=utf-8" } });
}

export async function proxyProfile({ request, params, env }) {
  const url = new URL(request.url);
  if (request.method !== "GET" && request.method !== "HEAD") return new Response("Method not allowed", { status: 405 });
  // On the shard itself (should it ever be deployed with this function) the file is local.
  if (url.hostname === SHARD_HOST) return env.ASSETS.fetch(request);

  const rest = params.path || [];
  if (rest.length !== 1 || !FILE.test(rest[0])) return notFound(env, url);

  const upstream = new URL(`https://${SHARD_HOST}${url.pathname}${url.search}`);
  // Forward only content-negotiation and cache headers: the shard host is public and needs nothing else.
  const headers = new Headers();
  for (const h of ["accept", "accept-language", "range", "if-none-match", "if-modified-since"]) {
    if (request.headers.has(h)) headers.set(h, request.headers.get(h));
  }
  const res = await fetch(upstream, { method: request.method, headers, redirect: "manual" });
  if (res.status === 404) return notFound(env, url);

  const out = new Headers(res.headers);
  // Pages marks every preview / branch deployment `X-Robots-Tag: noindex`. These pages are meant to
  // be indexed under the site's domain, so that header must not come along.
  out.delete("x-robots-tag");
  out.delete("set-cookie");
  // Shard redirects (e.g. faker.html -> faker) point at its own host: keep them on this domain.
  const loc = res.headers.get("location");
  if (loc) {
    const target = new URL(loc, upstream);
    if (target.host === upstream.host) out.set("location", `${target.pathname}${target.search}`);
  }
  return new Response(res.body, { status: res.status, statusText: res.statusText, headers: out });
}
