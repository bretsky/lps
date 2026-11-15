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
  photo?: string | null;                 // Leaguepedia CDN thumbnail (fetch_player_images)
  photo_cx?: number | null;              // head centre, 0..1 of photo width (null = centre)
  photo_ar?: number | null;              // photo width / height
  photo_top?: number | null;             // top of the hair, 0..1 of photo height
  photo_neck?: number | null;            // neck, 0..1 of photo height (avatar zoom)
  titles?: TitleTally | null;            // champion counts for the trophy pills
  real_name?: string | null;             // Leaguepedia Players.Name
  rank_prev?: number | null;             // rank on the previous season's board, same view (null = unrated then)
  clr_prev?: number | null;              // CLR at the end of the previous season, same view (null = no seasons yet)
}

export interface TitleTally {
  worlds?: number;
  msi?: number;
  first_stand?: number;
  ewc?: number;
  domestic?: number;
  league?: string;                       // league with the most domestic titles (the pill's mark)
  leagues?: Record<string, number>;      // domestic titles per league, most first; unknown-league titles only in `domestic`
}

export type HonorKind = "worlds" | "msi" | "first_stand" | "ewc" | "intl" | "domestic" | "cup";

export interface Honor {
  year: number;
  kind: HonorKind;
  medal: "gold" | "silver" | "bronze";
  league?: string | null;                // short key for domestic / cup rows (LCK, LPL, ...)
  event?: string | null;                 // raw event code for other intl / cup rows (EWC, KeSPA, ...)
  page?: string | null;                  // Leaguepedia page
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
  prev_year?: number | null;             // season `rank_prev` on today's rows refers to
}

// asof/<year>.json -- the board frozen at the end of a past season. Rows carry only the
// fields that change with the snapshot; the loader joins the rest from the current index.
export type AsOfRow = Partial<IndexRow> & Pick<IndexRow, "slug" | "rank" | "clr" | "tier">;

export interface AsOfJson {
  year: number;
  prev_year: number | null;              // board `rank_prev` refers to (null = first board)
  rated_count: number;
  rated_min_games: number;               // this board's games floor (lower while seasons were short)
  tiers: TierMeta[];
  all: AsOfRow[];
  lanes: Partial<Record<Lane, AsOfRow[]>>;
}

export interface Meta {
  asof_years?: number[];                 // seasons with a frozen past-year board
  build_id: string;
  generated: string;
  years: [number, number];
  source_workbook: string;
  rated_min_games: number;
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
  | "first_stand"
  | "ewc"
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
  photo?: string | null;                 // Leaguepedia CDN thumbnail
  photo_caption?: string | null;         // "Team · Year" the photo was taken
  real_name?: string | null;             // Leaguepedia Players.Name
  country?: string | null;
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
    Record<"kills_pts" | "deaths_pts" | "assists_pts" | "damage_pts", number>
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
  honors?: Honor[];
  resume_breakdown: Partial<Record<string, { n: number; pts: number }>>;
  tournaments: Record<string, number>;
  trajectory: Record<string, number>;
  trajectory_breakdown: Record<string, {
    kills_pts?: number; deaths_pts?: number; assists_pts?: number;
    damage_pts?: number;
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
  champions?: ChampionLine[];            // top champions by LPS earned on them (export_web.TOP_CHAMPIONS)
  career_stats?: CareerStats | null;     // career box-score totals over the LPS-scored games
}

/** Box-score line over a set of games. K/D/A + KDA only where box scores exist
 *  (kda_games of them); CS + CS/min only where CS and game length were recorded. */
export interface BoxLine {
  games: number;
  wins: number;
  lps: number;                           // LPS earned in these games (sums to CareerLPS over all champions)
  kda_games?: number;
  kills?: number;
  deaths?: number;
  assists?: number;
  kda?: number;                          // (K + A) / max(D, 1)
  cs?: number;
  cspm?: number;
}

export interface ChampionLine extends BoxLine {
  champion: string;                      // display name as in Oracle / Leaguepedia ("Kai'Sa")
}

export interface CareerStats extends BoxLine {
  n_champions: number;
}

export interface ResumeRound {
  key: "champion" | "finalist" | "semifinalist" | "quarterfinalist" | "group";
  label: string;
  /** Share of the champion's points this round earns (champion = 1). */
  share: number;
}

/** The résumé point tables (backend export_web._resume_scoring); every value is in CLR points. */
export interface ResumeScoring {
  /** The résumé's CLR weight, already applied to every point value here. */
  weight: number;
  /** Each repeat of the same achievement is worth this × the one before. */
  repeat_decay: number;
  rounds: ResumeRound[];
  champ_per_weight: number;
  events: {
    code: string;
    name: string;
    kind: "intl" | "cup";
    tournament_weight: number;
    /** Worlds / MSI: title value set directly rather than from the tournament weight. */
    anchored: boolean;
    points: Record<ResumeRound["key"], number>;
  }[];
  domestic: {
    year: number;
    champion: number;
    finalist: number;
    leagues: { league: string; strength: number; champion: number; finalist: number }[];
  };
  awards: { key: string; label: string; points: number; scaled: boolean }[];
  example: { label: string; steps: number[]; total: number };
}

export interface GlossaryJson {
  /** term = the workbook column code (stable anchor id); label = the readable name. */
  entries: { term: string; label?: string; definition: string }[];
  resume_scoring?: ResumeScoring;
}
