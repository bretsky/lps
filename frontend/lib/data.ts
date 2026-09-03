// Data loaders.  In dev + static build, files live under
// `frontend/public/data/<build_id>/*.json`.  The root `/data/meta.json`
// points at the current build id so the versioned bundle can be
// cache-immutable.

import type {
  GlossaryJson,
  IndexRow,
  Lane,
  Meta,
  PlayerDetail,
  TiersJson,
} from "./types";
import { promises as fs } from "fs";
import path from "path";

const PUBLIC_DATA = path.join(process.cwd(), "public", "data");

async function readJson<T>(rel: string): Promise<T> {
  const p = path.join(PUBLIC_DATA, rel);
  const raw = await fs.readFile(p, "utf-8");
  return JSON.parse(raw) as T;
}

async function currentBuildId(): Promise<string> {
  // Prefer the pointer file; fall back to the newest directory.
  try {
    const pointer = await readJson<{ build_id: string }>("meta.json");
    return pointer.build_id;
  } catch {
    const entries = await fs.readdir(PUBLIC_DATA, { withFileTypes: true });
    const dirs = entries
      .filter((e) => e.isDirectory())
      .map((e) => e.name)
      .sort();
    if (!dirs.length) {
      throw new Error(
        "no bundle found under frontend/public/data/. Run `python -m lps.export_web` first."
      );
    }
    return dirs[dirs.length - 1];
  }
}

export async function loadIndex(): Promise<IndexRow[]> {
  const build = await currentBuildId();
  return readJson<IndexRow[]>(`${build}/index.json`);
}

export async function loadTiers(): Promise<TiersJson> {
  const build = await currentBuildId();
  return readJson<TiersJson>(`${build}/tiers.json`);
}

export async function loadMeta(): Promise<Meta> {
  const build = await currentBuildId();
  return readJson<Meta>(`${build}/meta.json`);
}

export async function loadLane(lane: Lane): Promise<IndexRow[]> {
  const build = await currentBuildId();
  return readJson<IndexRow[]>(`${build}/lanes/${lane}.json`);
}

export async function loadPlayer(slug: string): Promise<PlayerDetail> {
  const build = await currentBuildId();
  return readJson<PlayerDetail>(`${build}/players/${slug}.json`);
}

export async function loadGlossary(): Promise<GlossaryJson> {
  const build = await currentBuildId();
  return readJson<GlossaryJson>(`${build}/glossary.json`);
}
