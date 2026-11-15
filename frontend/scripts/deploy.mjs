// Build the rankings site as static files and deploy it to Cloudflare Pages.
//   npm run stage     # build out/ only (preview: npx wrangler@4 pages dev out)
//   npm run deploy    # build out/ and upload it
// Env: PAGES_PROJECT (default lps), PAGES_FILE_LIMIT (default 20000, the free plan's per-site cap;
// paid plans allow 100000).
//
// Wrangler deploys to production when the current git branch is the project's production branch
// (main) and to a preview alias (<branch>.<project>.pages.dev) otherwise.
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
const limit = Number(process.env.PAGES_FILE_LIMIT || 20000);
const MAX_FILE = 25 * 1024 * 1024;

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
const SKIP = new Set(["node_modules", ".next", ".build", "out", "data-archive", "scripts", "tsconfig.tsbuildinfo"]);
const work = path.join(root, ".build");
rmSync(work, { recursive: true, force: true });
mkdirSync(work);
for (const e of readdirSync(root)) {
  if (!SKIP.has(e) && !e.endsWith(".stackdump")) cpSync(path.join(root, e), path.join(work, e), { recursive: true });
}
const nextBin = path.join(root, "node_modules", "next", "dist", "bin", "next");
run(process.execPath, [nextBin, "build"], { cwd: work, shell: false });

const out = path.join(root, "out");
rmSync(out, { recursive: true, force: true });
renameSync(path.join(work, "out"), out);
rmSync(work, { recursive: true, force: true });
rmSync(path.join(out, "data"), { recursive: true, force: true });

let files = 0;
let bytes = 0;
const big = [];
const walk = (dir) => {
  for (const e of readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) walk(p);
    else {
      const size = statSync(p).size;
      files += 1;
      bytes += size;
      if (size > MAX_FILE) big.push(path.relative(out, p));
    }
  }
};
walk(out);
const buildId = JSON.parse(readFileSync(meta, "utf-8")).build_id;
console.log(`\nout/: ${files} files, ${(bytes / 1024 / 1024).toFixed(0)} MB (data build ${buildId})`);
if (files > limit) fail(`over Cloudflare Pages' ${limit}-file limit (PAGES_FILE_LIMIT=100000 on a paid plan)`);
if (big.length) fail(`over Pages' 25 MiB per-file limit:\n  ${big.join("\n  ")}`);

if (stageOnly) {
  console.log(`staged in ${out}`);
  process.exit(0);
}
run("npx", ["wrangler@4", "pages", "deploy", "out", "--project-name", project, "--commit-dirty=true"]);
