// Mirrors the JSON schema written by backend/src/lps/export_web.py.
// Keep in sync with _INDEX_FIELDS, _DETAIL_*, _TIERS, _RADAR_AXES there.

export type Lane = "top" | "jng" | "mid" | "bot" | "sup";

export type TierKey =
  | "goats"
  | "legends"
  | "greats"
  | "elite"
  | "stars"
  | "contenders";

export interface LanePosition {
  lane: Lane;
  clr: number;
  games: number;
  share: number; // 0-100, share of the player's cross-lane CLR earned in this lane
}

export interface IndexRow {
  rank: number;
  slug: string;
  playername: string;
  position: Lane | null;                 // primary lane (highest CLR)
  positions: LanePosition[];             // every lane played, sorted CLR desc
  current_team: string | null;           // most-recent Oracle season affiliation
  current_league: string | null;
  current_year: number | null;
  region_elo: number | null;
  n_years: number;
  first_year: number;
  last_year: number;
  games: number;
  win_rate: number | null;
  clr: number;
  career_value: number | null;
  pace_value: number | null;
  peak_value: number | null;
  resume_bonus: number | null;
  total_score: number | null;
  peak_lps: number | null;
  tier: TierKey;
  hall_of_legends: boolean;
  hol_year: number | null;
  is_retired: boolean | null;
  is_active: boolean | null;
}

export interface TierMeta {
  key: TierKey;
  label: string;
  color: string;
  count: number;
  clr_floor: number | null;
}

export interface TiersJson {
  tiers: TierMeta[];
  rated_min_games: number;
  rated_count: number;
}

export interface Meta {
  build_id: string;
  generated: string;
  years: [number, number];
  source_workbook: string;
  rated_min_games: number;
  beta: boolean;
  counts: {
    total: number;
    rated: number;
    by_lane: Record<Lane, number>;
  };
  about: Record<string, string | number | null>;
  radar_axes: { key: string; source: string; inverted: boolean }[];
}

export type RadarAxes = "peak" | "longevity" | "consistency" | "resume" | "impact" | "clutch" | "dominance";

export type TournamentFamily =
  | "worlds"
  | "msi"
  | "intl"
  | "domestic"
  | "cup";

export type Medal = "gold" | "silver" | "bronze";

export type YearAchievements = Partial<Record<TournamentFamily, Partial<Record<Medal, number>>>> & {
  mvp?: number;
  allpro?: number;
};

export interface PlayerDetail {
  rank: number;
  slug: string;
  playername: string;
  position: Lane | null;
  positions: LanePosition[];
  current_team: string | null;
  current_league: string | null;
  current_year: number | null;
  region_elo: number | null;
  n_years: number;
  first_year: number;
  last_year: number;
  games: number;
  win_rate: number | null;
  clr: number;
  tier: TierKey | null;
  rated: boolean;
  hall_of_legends: boolean;
  hol_year: number | null;
  is_retired: boolean | null;
  is_active: boolean | null;
  clr_components: Partial<{
    career_value: number;
    pace_value: number;
    peak_value: number;
    resume_bonus: number;
    intl_bonus: number;
    title_bonus: number;
    award_bonus: number;
  }>;
  career_lps: Partial<{
    total_score: number;
    lps_per_year: number;
    peak_year: number;
    peak_lps: number;
    peak_years: number;
    peak_band_avg: number;
  }>;
  phase: Partial<Record<"reg_pts" | "playoff_pts" | "tourn_pts", number>>;
  components: Partial<Record<"base_pts" | "contrib_pts" | "wbonus_pts", number>>;
  sources: Partial<
    Record<"kills_pts" | "deaths_pts" | "assists_pts" | "damage_pts" | "fb_pts", number>
  >;
  rates: Partial<{
    pts_per_game: number;
    pts_per_game_w: number;
    clutch_gap: number;
    avg_contrib: number;
    avg_resid: number;
    avg_p_model: number;
    sched_strength: number;
  }>;
  high_noon: Partial<{
    hn_lane_best: number;
    hn_lane: number;
    hn_lane_yrs: string;
    hn_global_best: number;
    hn_global: number;
    hn_global_yrs: string;
  }>;
  hn_year_ranks: Record<string, { global: number; lane: number }>;
  year_achievements: Record<string, YearAchievements>;
  year_teams: Record<string, { name: string; logo?: string }[]>;
  resume_breakdown: Partial<Record<string, { n: number; pts: number }>>;
  tournaments: Record<string, number>;
  trajectory: Record<string, number>;
  trajectory_breakdown: Record<string, {
    kills_pts?: number; deaths_pts?: number; assists_pts?: number;
    damage_pts?: number; fb_pts?: number;
    reg_pts?: number; playoff_pts?: number; tourn_pts?: number;
  }>;
  splits: Partial<{
    teams_lps: string;
    leagues_lps: string;
    lanes_lps: string;
    teams: { name: string; clr: number }[];
    leagues: { name: string; clr: number }[];
    lanes: { name: string; clr: number }[];
  }>;
  radar: {
    global: Record<RadarAxes, number | null>;
    lane: Record<RadarAxes, number | null> | null;
  };
}

export interface GlossaryJson {
  entries: { term: string; definition: string }[];
}
