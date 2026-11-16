// English UI text. This table defines the shape (`Messages`) that ko.tsx and zh.tsx must
// match key for key, so TypeScript flags any string a translation is missing. Values are
// strings, or functions for text with numbers or markup in it (word order differs by
// language, so whole sentences live here rather than being glued together in components).
//
// Glossary definitions and résumé-table labels on /about are not here: the backend writes
// them, translated, into glossary.json (backend/src/lps/web_glossary_i18n.py).

import type { ReactNode } from "react";

const plural = (n: number, one: string, many: string) => (n === 1 ? one : many);

const ROLE_NAMES: Record<string, string> = { top: "Top Laners", jng: "Junglers", mid: "Mid Laners", bot: "ADCs", sup: "Supports" };

export const en = {
  lang: { label: "Language" },
  notFound: { title: "Page not found", body: "That page doesn't exist, or has moved." },
  nav: {
    rankings: "All-time rankings",
    rankingsShort: "Rankings",
    profile: "Profile",
    playerCard: "Player card",
    about: "About",
    viewCard: "View card",
  },
  footer: {
    build: (build: string, rated: number, asOf: number | null, minGames: number) =>
      `Build ${build} · ${rated} rated players${asOf !== null ? ` as of ${asOf}` : ""} (games ≥ ${minGames})`,
    aboutLink: "About CLR & glossary",
    byRole: "Greatest by role",
    pastSeasons: "Past seasons",
    disclaimer:
      "Not endorsed by Riot Games · Data and photos from Oracle's Elixir and Leaguepedia · League marks © their owners",
  },

  // Shared vocabulary
  lanes: { top: "Top", jng: "Jungle", mid: "Mid", bot: "Bot", sup: "Support" },
  tiers: {
    goats: { label: "GOATs", one: "GOAT" },
    legends: { label: "Legends", one: "Legend" },
    greats: { label: "Greats", one: "Great" },
    elite: { label: "Elite", one: "Elite" },
    stars: { label: "Stars", one: "Star" },
    contenders: { label: "Contenders", one: "Contender" },
  },
  /** The four CLR parts. */
  parts: { career: "Career", pace: "Pace", peak: "Peak", resume: "Résumé" },
  /** Event families (Honor kinds), as on marks and tooltips. */
  events: {
    worlds: "Worlds",
    msi: "MSI",
    first_stand: "First Stand",
    ewc: "Esports World Cup",
    intl: "International",
    domestic: "League",
    cup: "Cup",
  },
  /** Finishes by medal. */
  places: { gold: "Champion", silver: "Finalist", bronze: "Semifinalist" },
  edition: {
    hol: "Hall of Legends",
    worlds: "World Champion",
    tier: (one: string) => `${one} Edition`,
    word: "EDITION",
    inducted: (y: number) => `INDUCTED ${y}`,
  },
  status: {
    hol: (y: number | null) => `Hall of Legends inductee${y ? ` (${y})` : ""}`,
    active: "Active — competing this season",
    activeShort: "Active",
    retired: "Retired",
    inactive: "Inactive — hiatus, military, coaching, or unknown",
    inactiveShort: "Inactive",
  },
  marks: {
    honor: (year: number, what: string, place: string) => `${year} ${what} — ${place}`,
    eventChampion: (n: number, event: string) => `${n}× ${event} champion`,
    /** Domestic-title pill: titles per league, most first; `other` = titles with no known league. */
    domesticChampion: (leagues: [string, number][], other: number, total: number) =>
      leagues.length
        ? `${[...leagues.map(([lg, n]) => `${n}× ${lg}`), ...(other > 0 ? [`${other}× other league`] : [])].join(", ")} champion`
        : `${total}× domestic champion`,
  },
  common: {
    games: (g: string) => `${g} games`,
    winRate: (wr: string) => `${wr} win rate`,
    kda: (k: string) => `${k} KDA`,
    pts: (x: string) => `${x} pts`,
  },

  // Rankings board
  frozen: (year: number, sep: ReactNode, back: ReactNode): ReactNode => (
    <>
      Frozen at the end of {year} {sep} careers, titles and tiers count only what had happened by then {sep} {back}
    </>
  ),
  backToToday: "Back to today",
  hero: {
    kicker: "League of Legends Esports",
    titleA: "All-Time",
    titleB: "Rankings",
    subtitle: "Career Legend Rating",
    asOf: (y: number) => `as of ${y}`,
    viewCard: (rank: number, name: string) => `#${rank} ${name} — view card`,
    roleB: ROLE_NAMES,
  },
  board: {
    allRoles: "All Roles",
    yearTitle: "See the rankings as they stood at the end of a past season",
    yearAria: "Rankings as of season",
    asOfToday: (y: number) => `As of today (${y})`,
    asOfEnd: (y: number) => `As of end of ${y}`,
    search: "Search player or name…",
    allLeagues: "All leagues",
    leagueAria: "League",
    sortAria: "Sort by",
    sortBy: (label: string) => `Sort · ${label}`,
    sort: { clr: "CLR", total_score: "CareerLPS", peak_lps: "PeakLPS", resume_bonus: "Résumé", n_years: "Longevity" },
    col: { player: "Player", role: "Role", career: "Career", titles: "Titles", clr: "CLR", peak: "Peak" },
    players: (n: number) => `${n} ${plural(n, "player", "players")}`,
    loadFailed: "Couldn't load more players",
    retry: "Retry",
    loading: "Loading players…",
  },
  row: {
    isNew: "NEW",
    notRated: (y: number) => `Not yet rated at the end of ${y}`,
    rankSame: (prev: number, y: number) => `#${prev} at the end of ${y} (no change)`,
    rankMove: (up: boolean, d: number, prev: number, y: number) =>
      `${up ? "Up" : "Down"} ${d} · #${prev} at the end of ${y}`,
    clrSame: (prev: string, y: number) => `CLR ${prev} at the end of ${y} (no change)`,
    clrMove: (prev: string, y: number, delta: string) => `CLR ${prev} at the end of ${y} (${delta})`,
    gamesWin: (g: string, wr: string) => `${g} G · ${wr}`,
  },

  // Player profile
  profile: {
    photo: (caption: string) => `Photo · ${caption}`,
    years: (first: number, last: number, n: number) =>
      first === last ? `${first} · ${n}yr` : `${first}–${last} · ${n}yr`,
    trophy: {
      worlds: "Worlds",
      msi: "MSI",
      first_stand: "First Stand",
      ewc: "EWC",
      domestic: "League titles",
      mvp: "MVP",
    },
    trophyTitle: (n: number, label: string) => `${n}× ${label}`,
    global: "Global",
    nearby: "Ranked nearby",
  },
  waterfall: {
    title: "CLR Composition",
    tips: {
      career: "Career volume — total sample-shrunk production across seasons.",
      pace: "Per-year rate — production adjusted for career length.",
      peak: "Peak seasons — reward for how high the ceiling was.",
      resume: "Hardware — Worlds/MSI/domestic titles + MVP/All-Pro awards.",
    },
    pctOfClr: (p: string) => `${p}% of CLR`,
    resumeSplit: "Résumé split:",
    intl: "Intl",
    titles: "Titles",
    awards: "Awards",
  },
  resume: {
    title: "Résumé",
    summary: (pts: string, n: number) => `${pts} pts · ${n} achievements`,
    rows: { worlds: "Worlds", msi: "MSI", otherIntl: "Other Intl", league: "League", awards: "Awards" },
    cats: {
      champion: "Champion",
      finalist: "Finalist",
      out: "Out before final",
      cup: "Cup",
      mvp: "MVP",
      allpro: "All-Pro",
    },
    otherIntlEvents: "IEM / EWC / MSC / First Stand / Rift Rivals",
    hint: {
      champion: (event: string) => `${event} champion`,
      finalist: (event: string) => `${event} finalist (runner-up)`,
      out: (event: string) => `${event}: eliminated before the final (semifinal, quarterfinal or group stage)`,
      domChampion: "Domestic league title",
      domFinalist: "Runner-up in a domestic league",
      domCup: "Domestic cup / secondary domestic title",
      mvp: "Regular-season or playoff MVP",
      allpro: "All-Pro team selection",
    },
    trophyCase: (n: number) => `Trophy case · ${n} titles`,
    kind: {
      worlds: "Worlds",
      msi: "MSI",
      first_stand: "First Stand",
      ewc: "EWC",
      intl: "Intl",
      domestic: "League",
      cup: "Cup",
    },
    chipPlace: { gold: "Champion", silver: "Finalist", bronze: "Semis" },
  },
  anatomy: {
    title: "Career LPS Anatomy",
    total: "Total",
    peak: "Peak",
    phase: { reg_pts: "Regular", playoff_pts: "Playoffs", tourn_pts: "International" },
    comp: { base_pts: "Baseline", contrib_pts: "Contribution", wbonus_pts: "Win Bonus" },
    compHint: {
      base_pts: "Value earned by simply playing the position on a rated team.",
      contrib_pts: "Above-expected performance — the model's signal.",
      wbonus_pts: "Reward for winning games the model did not predict (beta * (result - p_model)).",
    },
    source: { kills_pts: "Kills", deaths_pts: "Deaths", assists_pts: "Assists", damage_pts: "Damage" },
    byPhase: "By phase",
    byPhaseSub: "Regular season / playoffs / international events",
    byComponent: "By component",
    byComponentSub: "Baseline / contribution / win bonus",
    bySource: "By stat source",
    bySourceSub: "Kills / Deaths / Assists / Damage — sums to Contribution",
    byTournament: "By tournament",
  },
  season: {
    title: "Season-by-Season",
    summary: (peak: string, year: number | null, n: number) =>
      `Peak ${peak}${year ? ` (${year})` : ""} · ${n} ${plural(n, "season", "seasons")}`,
    year: "Year",
    team: "Team",
    cup: {
      worlds: "Worlds",
      msi: "MSI",
      first_stand: "First Stand",
      ewc: "Esports World Cup",
      intl: "Other international",
      domestic: "Domestic league",
      cup: "Domestic cup",
    },
    medal: { gold: "champion", silver: "finalist", bronze: "semifinalist" },
    chip: (event: string, medal: string, n: number) => `${event} ${medal}${n > 1 ? ` ×${n}` : ""}`,
    mvpChip: (n: number) => `MVP award${n > 1 ? ` ×${n}` : ""}`,
    allproChip: (n: number) => `All-Pro selection${n > 1 ? ` ×${n}` : ""}`,
    tip: {
      lps: (v: string) => `${v} LPS`,
      regular: (v: string) => `Regular ${v}`,
      playoffs: (v: string) => `Playoffs ${v}`,
      intl: (v: string) => `Intl ${v}`,
      global: (r: number) => `Global #${r}`,
      lane: (r: number) => `Lane #${r}`,
    },
    legend: {
      regular: "regular season",
      playoffs: "playoffs",
      intl: "international",
      peakYr: "peak yr",
      negative: "negative",
      hnGlobal: "HN global rank",
      hnLane: "HN lane rank",
      lineTop: "(line top = rank #1)",
      cups: "Cup = tournament:",
      tint: "Tint = placement:",
      mvp: "MVP award",
      allpro: "All-Pro selection",
    },
  },
  splits: {
    title: "Splits & Context",
    teams: "Teams",
    leagues: "Leagues",
    lanes: "Lanes",
    rate: {
      lpsGame: { label: "LPS / Game", hint: "Weighted per-game LPS (phase & stakes adjusted)." },
      clutch: { label: "Clutch Gap", hint: "Difference in per-game production in higher-stakes games." },
      intangibles: { label: "Intangibles", hint: "Avg residual — unmodeled per-game value (avg_resid)." },
      sos: { label: "SoS", hint: "Schedule strength — avg opponent quality faced." },
      regionElo: { label: "Region Elo", hint: "Current region strength (season-avg Elo of primary league)." },
      avgContrib: { label: "Avg Contribution", hint: "Per-game contribution above baseline (win-prob added)." },
      hnLane: { label: "HN Rank (lane)", hint: "High Noon peer rank across best seasons within lane." },
      hnGlobal: { label: "HN Rank (global)", hint: "High Noon peer rank across best seasons vs all lanes." },
    },
    bestN: (yrs: string) => `Best-N seasons: ${yrs}`,
  },
  champs: {
    title: "Champion Pool",
    summary: (n: number) => `${n} ${plural(n, "champion", "champions")} played · ranked by LPS earned`,
    careerKda: "Career K / D / A",
    careerKdaHint: (n: string) => `Totals over ${n} games with box scores.`,
    kdaHint: "(Kills + Assists) / Deaths, career.",
    perGame: "Per game",
    perGameHint: "Average kills / deaths / assists per game.",
    careerCs: "Career CS",
    careerCsHint: "Minions + monsters, games with CS recorded.",
    cspm: "CS / min",
    col: { champion: "Champion", games: "Games", winPct: "Win%", kda: "K / D / A", lps: "LPS earned" },
  },

  // Player card
  card: {
    rank: "RANK",
    clrSub: (rank: number) => `#${rank} all-time`,
    peak: "PEAK",
    winPct: "WIN %",
    shelf: {
      worlds: "Worlds titles",
      msi: "MSI titles",
      first_stand: "First Stand titles",
      ewc: "Esports World Cup titles",
      domestic: "Domestic titles",
      mvp: "MVP awards",
    },
    shelfTitle: (n: number, what: string) => `${n} ${what}`,
    noShelf: (first: number, last: number, seasons: number, games: string) =>
      `${first}–${last} · ${seasons} ${plural(seasons, "season", "seasons")} · ${games} games`,
    percentile: "PERCENTILE PROFILE",
    readout: {
      careerLps: "Career LPS",
      seasons: "Seasons",
      lpsGame: "LPS / game",
      bestLane: "Best lane rk",
      bestGlobal: "Best global rk",
      peakYears: "Peak years",
    },
    signature: "SIGNATURE",
    champLine: (games: number, lps: string) => `${games}g · ${lps}`,
    moreTitles: (n: number) => `${n} more ${plural(n, "title", "titles")}`,
    noTitles: "No titles yet",
    saving: "Saving…",
    save: (back: boolean) => `Save ${back ? "back" : "front"} as image`,
    saveError: "Couldn’t render the image — try again",
    flip: (toBack: boolean): string => (toBack ? "Flip to card back" : "Flip to card front"),
    clickToFlip: "Click the card to flip",
  },
  radar: {
    axes: {
      peak: "Peak",
      longevity: "Longev.",
      consistency: "Consis.",
      resume: "Résumé",
      impact: "Impact",
      clutch: "Clutch",
      dominance: "Domin.",
    },
    all: "All players",
    vsLane: (lane: string) => `vs ${lane}`,
  },

  // About / glossary
  about: {
    kicker: "How it works",
    titleA: "About",
    titleB: "CLR",
    intro: (hl: (s: string) => ReactNode): ReactNode => (
      <>
        The {hl("Career Legend Rating")} (CLR) ranks every player&apos;s whole career. Its base is LPS (League
        Performance Score), which measures how much each player moved their team&apos;s chances of winning, game by
        game, against what an average player would have done in the same spot. Seasons are scored on their own, then
        rolled up into CLR, which also counts titles, placements and awards.
      </>
    ),
    weight: (part: string) => `${part} weight`,
    settings: (first: number, last: number, minGames: number, build: string, sep: ReactNode): ReactNode => (
      <>
        Seasons {first}–{last} {sep} rated at {minGames}+ games {sep} build {build}
      </>
    ),
    sectionsAria: "Sections",
    resumePointsNav: "Résumé points",
    linkTo: (label: string) => `Link to ${label}`,
    sections: {
      clr: {
        title: "Career Legend Rating",
        blurb: "The headline number: one score per career that counts bulk, pace, peak and hardware.",
      },
      resume: {
        title: "Résumé",
        blurb:
          "Big-stage results the box score can't see: placements, titles and awards. Every one has a fixed point value, listed in the tables below.",
      },
      "resume-categories": {
        title: "Résumé categories",
        blurb:
          "The 14 categories a profile splits the résumé into, each with how many the player earned and the CLR points they add after repeat discounts.",
      },
      lps: {
        title: "Season score (LPS)",
        blurb: "How each season is scored from the games themselves, before it rolls up into CLR.",
      },
      context: { title: "Game context", blurb: "Supporting numbers that describe the games behind a season." },
      ranks: {
        title: "Ranks & peers",
        blurb: "Where a player stands against the field, and where their value came from.",
      },
      other: { title: "Other", blurb: "Everything else in the glossary." },
    },
    rs: {
      title: "How the résumé is scored",
      intro: (w: string) =>
        `Every achievement adds a fixed number of points to CLR. All the values below already include the résumé's CLR weight (×${w}), so they are exactly what a first-time achievement adds to a player's CLR.`,
      intlTitle: "International events and cups",
      intlBody: (perWeight: string, rounds: [string, string][]) =>
        `Worlds and MSI titles have set values. Every other event's title is worth ${perWeight} × its tournament weight, the same importance weight its games carry in LPS (Worlds = 1). Each round below the title earns a fixed share of the title value: ${rounds
          .map(([label, pct]) => `${label.toLowerCase()} ${pct}%`)
          .join(", ")}. Every player on the team's roster gets the full amount.`,
      event: "Event",
      weight: "Weight",
      set: "set",
      cupsRow: "Domestic cups (counted under domestic titles)",
      domTitle: "Domestic leagues",
      domBody: (champion: string, finalist: string, year: number) =>
        `A split playoff title is worth up to ${champion} and a lost final up to ${finalist}, multiplied by the league's strength: its Elo rating divided by the strongest league's that year. The values for ${year}:`,
      league: "League",
      strength: "Strength",
      titleCol: "Title",
      runnerUp: "Runner-up",
      awardsTitle: "Individual awards",
      awardsBody:
        "International honors are flat. Domestic awards (marked *) are multiplied by league strength, like titles, so the value shown is the most they can be worth.",
      award: "Award",
      points: "Points",
      repeatsTitle: "Repeats",
      repeatsBody: (pct: number, example: string, steps: string[], total: ReactNode, naive: string): ReactNode => (
        <>
          Winning the same thing again is worth {pct}% of the time before: the same round of the same event (every
          Worlds title, every MSI runner-up finish), all domestic league titles together, all domestic runner-up
          finishes together, and each award type. A player&apos;s most valuable instance always counts in full. For
          example, {example.charAt(0).toLowerCase() + example.slice(1)} add {steps.join(" + ")} = {total}, not {naive}.
        </>
      ),
    },
  },
};

export type Messages = typeof en;
