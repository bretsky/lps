// Build the rankings site as static files and deploy it to Cloudflare Pages.
//   npm run stage     # build out/ only (preview: npx wrangler@4 pages dev out)
//   npm run deploy    # build out/ and upload it
// Env: PAGES_PROJECT (default lps), PAGES_FILE_LIMIT (default 20000, the free plan's per-site cap;
// paid plans allow 100000).
//
// Wrangler deploys to production when the current git branch is the project's production branch
// (main) and to a preview alias (<branch>.<project>.pages.dev) otherwise.
//
// Two uploads, because one Pages deployment holds at most 20k files: the Korean and Chinese
// profiles (out/{ko,zh}/player/) move to out-i18n/ and go up first as the `i18n` branch
// deployment (i18n.lps-80q.pages.dev); then the rest goes to production, with functions/,
// whose {ko,zh}/player routes proxy those profiles onto the site's domain
// (functions-shared/i18n-proxy.js, which names the project and branch too). Both come from
// one build, so the profiles' /_next/static files are production's.
//
// The build reads public/data/current/ (written by `python -m lps.export_web`). The site never
// fetches those JSON files at runtime, so out/data/ is dropped before upload.
//
// The build runs in a copy of the app (.build/), because under output "export" `next build` always
// wipes and rewrites .next/ (distDir can't move it), which would break a running `npm run dev`.
// The copy resolves packages from frontend/node_modules by walking up.
// Node rather than bash: on Windows `bash` on PATH is often WSL's, not Git Bash.
import { spawnSync } from "node:child_process";
import { cpSync, existsSync, mkdirSync, readFileSync, readdirSync, renameSync, rmSync, statSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const stageOnly = process.argv.includes("--stage");
const project = process.env.PAGES_PROJECT || "lps";
const SHARD_BRANCH = "i18n"; // functions-shared/i18n-proxy.js names its host (SHARD_HOST)
const limit = Number(process.env.PAGES_FILE_LIMIT || 20000);
const MAX_FILE = 25 * 1024 * 1024;
// Windows: deleting a ~15k-file tree can hit ENOTEMPTY/EBUSY while an indexer or antivirus holds
// a file for a moment; rmSync retries those when asked to.
const RM = { recursive: true, force: true, maxRetries: 10, retryDelay: 300 };

const fail = (msg) => {
  console.error(msg);
  process.exit(1);
};
const run = (cmd, args, { cwd = root, shell = process.platform === "win32" } = {}) => {
  console.log(`\n$ ${cmd} ${args.join(" ")}`);
  const r = spawnSync(cmd, args, { cwd, stdio: "inherit", shell });
  if (r.error) fail(String(r.error));
  if (r.status !== 0) process.exit(r.status ?? 1);
};

const meta = path.join(root, "public", "data", "current", "meta.json");
if (!existsSync(meta)) fail("no public/data/current/ bundle -- run `python -m lps.export_web` first");
if (existsSync(path.join(root, "public", "data", "archive")))
  fail("public/data/archive/ would be copied into the site: move it to frontend/data-archive/");

// Copy everything the build reads; local build state, caches and the archive stay behind.
const SKIP = new Set([
  "node_modules", ".next", ".build", "out", "out-i18n", "data-archive", "scripts", "functions", "functions-shared",
  "tsconfig.tsbuildinfo",
]);
const work = path.join(root, ".build");
rmSync(work, RM);
mkdirSync(work);
for (const e of readdirSync(root)) {
  if (!SKIP.has(e) && !e.endsWith(".stackdump")) cpSync(path.join(root, e), path.join(work, e), { recursive: true });
}
const nextBin = path.join(root, "node_modules", "next", "dist", "bin", "next");
run(process.execPath, [nextBin, "build"], { cwd: work, shell: false });

const out = path.join(root, "out");
rmSync(out, RM);
renameSync(path.join(work, "out"), out);
rmSync(work, RM);
rmSync(path.join(out, "data"), RM);

// The styled 404 (app/(en)/not-found-page): Next can't export one with two root layouts.
cpSync(path.join(out, "not-found-page.html"), path.join(out, "404.html"));
for (const f of ["not-found-page.html", "not-found-page.txt"]) rmSync(path.join(out, f), RM);

// Korean / Chinese profiles -> out-i18n/ (see the header).
const shard = path.join(root, "out-i18n");
rmSync(shard, RM);
for (const l of ["ko", "zh"]) {
  const from = path.join(out, l, "player");
  if (!existsSync(from)) fail(`no ${path.relative(root, from)}: the build didn't make the ${l} profiles`);
  mkdirSync(path.join(shard, l), { recursive: true });
  renameSync(from, path.join(shard, l, "player"));
}
cpSync(path.join(out, "404.html"), path.join(shard, "404.html"));

const buildId = JSON.parse(readFileSync(meta, "utf-8")).build_id;
for (const dir of [out, shard]) {
  let files = 0;
  let bytes = 0;
  const big = [];
  const walk = (d) => {
    for (const e of readdirSync(d, { withFileTypes: true })) {
      const p = path.join(d, e.name);
      if (e.isDirectory()) walk(p);
      else {
        const size = statSync(p).size;
        files += 1;
        bytes += size;
        if (size > MAX_FILE) big.push(path.relative(dir, p));
      }
    }
  };
  walk(dir);
  const name = path.basename(dir);
  console.log("");
  console.log(`${name}/: ${files} files, ${(bytes / 1024 / 1024).toFixed(0)} MB (data build ${buildId})`);
  if (files > limit) fail(`${name}/ is over Cloudflare Pages' ${limit}-file limit (PAGES_FILE_LIMIT=100000 on a paid plan)`);
  if (big.length) fail(["over Pages' 25 MiB per-file limit:", ...big].join("\n  "));
}

if (stageOnly) {
  console.log(`staged in ${out} and ${shard}`);
  process.exit(0);
}
// The profiles first, so production's proxy never points at a branch that lacks them. Run from
// inside out-i18n/ so wrangler doesn't pick up functions/ (the shard serves plain files).
run("npx", ["wrangler@4", "pages", "deploy", ".", "--project-name", project, "--branch", SHARD_BRANCH, "--commit-dirty=true"], {
  cwd: shard,
});
run("npx", ["wrangler@4", "pages", "deploy", "out", "--project-name", project, "--commit-dirty=true"]);
