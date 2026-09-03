// Data loaders. The bundle lives under `frontend/public/data/current/`
// (overwritten on each `python -m lps.export_web` run). The build id +
// generated timestamp are in `current/meta.json`. Past snapshots are
// auto-archived to `frontend/public/data/archive/<build_id>/` locally but
// are gitignored -- only `current/` ships in the repo.

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

const CURRENT_DATA = path.join(process.cwd(), "public", "data", "current");

async function readJson<T>(rel: string): Promise<T> {
  const p = path.join(CURRENT_DATA, rel);
  const raw = await fs.readFile(p, "utf-8");
  return JSON.parse(raw) as T;
}

export async function loadIndex(): Promise<IndexRow[]> {
  return readJson<IndexRow[]>("index.json");
}

export async function loadTiers(): Promise<TiersJson> {
  return readJson<TiersJson>("tiers.json");
}

export async function loadMeta(): Promise<Meta> {
  return readJson<Meta>("meta.json");
}

export async function loadLane(lane: Lane): Promise<IndexRow[]> {
  return readJson<IndexRow[]>(`lanes/${lane}.json`);
}

export async function loadPlayer(slug: string): Promise<PlayerDetail> {
  return readJson<PlayerDetail>(`players/${slug}.json`);
}

export async function loadGlossary(): Promise<GlossaryJson> {
  return readJson<GlossaryJson>("glossary.json");
}
