// Page titles and search-result descriptions in each language. The titles are also what
// DocTitle sets in the browser, so a page's tab title matches its prerendered <title>. Written
// for the words people search with ("롤 원딜 순위", "英雄联盟 历史最佳 中单"), not translated
// word for word. Korean: no particle straight after a variable number.

import type { Lane } from "../types";
import type { Locale } from "./config";

/** What a profile's title and description say, gathered once per page (components/routes/PlayerRoute). */
export interface PlayerFacts {
  name: string;               // handle ("Faker")
  native: string | null;      // Hangul / Chinese name on that site ("이상혁"), else null
  realName: string | null;    // romanized ("Lee Sang-hyeok")
  lane: Lane | null;
  team: string | null;
  league: string | null;
  active: boolean;
  span: string;               // "2013–2026"
  rank: number;
  laneRank: number | null;
  clr: string;                // "83.0"
  titles: { worlds?: number; msi?: number; first_stand?: number; ewc?: number; domestic?: number; league?: string };
  games: number;
  winPct: number | null;
  champs: string[];
}

export interface SeoText {
  home: string;
  role: (lane: Lane) => string;
  asof: (year: number) => string;
  about: string;
  card: (name: string) => string;
  homeDesc: (players: string, y0: number, y1: number, top: string) => string;
  roleDesc: (lane: Lane, players: string, y0: number, y1: number, top: string) => string;
  asofDesc: (year: number, top: string) => string;
  aboutDesc: string;
  player: (f: PlayerFacts) => string;
  playerDesc: (f: PlayerFacts) => string;
  /** "Faker, Canyon and Ruler" in this language. */
  list: (names: string[]) => string;
  /** og:locale */
  ogLocale: string;
}

const EN_ROLE_ONE: Record<Lane, string> = { top: "top laner", jng: "jungler", mid: "mid laner", bot: "ADC", sup: "support" };

/** "6× Worlds, 2× MSI, 10× LCK" in each language (counts first in English, after in Korean / Chinese). */
function titleList(t: PlayerFacts["titles"], names: Record<"worlds" | "msi" | "first_stand" | "ewc", string>,
  fmt: (n: number, what: string) => string, sep: string, domesticFallback: string): string {
  const parts: string[] = [];
  for (const k of ["worlds", "msi", "first_stand", "ewc"] as const) if (t[k]) parts.push(fmt(t[k]!, names[k]));
  if (t.domestic) parts.push(fmt(t.domestic, t.league ?? domesticFallback));
  return parts.join(sep);
}
const nameWith = (f: PlayerFacts, open: string, close: string) => (f.native ? `${f.name}${open}${f.native}${close}` : f.name);

const EN_ROLES: Record<Lane, string> = { top: "Top Laners", jng: "Junglers", mid: "Mid Laners", bot: "ADCs", sup: "Supports" };
const enRoleLower = (l: Lane) => (l === "bot" ? EN_ROLES[l] : EN_ROLES[l].toLowerCase());

// The role words Korean / Chinese fans search with.
const KO_ROLES: Record<Lane, string> = { top: "탑", jng: "정글", mid: "미드", bot: "원딜", sup: "서포터" };
const ZH_ROLES: Record<Lane, string> = { top: "上单", jng: "打野", mid: "中单", bot: "ADC", sup: "辅助" };

export const SEO: Record<Locale, SeoText> = {
  en: {
    home: "Greatest League of Legends Players of All Time · CLR Rankings",
    role: (l) => `Greatest ${EN_ROLES[l]} of All Time · LoL Esports Rankings · CLR`,
    asof: (y) => `All-Time LoL Player Rankings as of ${y} · CLR`,
    about: "How CLR Works · LoL Esports Career Ratings Explained",
    card: (name) => `${name} · CLR Card`,
    homeDesc: (n, y0, y1, top) =>
      `The greatest League of Legends pro players of all time, ranked: ${n} players from ${y0} to ${y1} across ` +
      `the LCK, LPL, LEC, LCS and every major league, by Career Legend Rating (CLR), which combines ` +
      `game-by-game impact on winning with titles and awards. Top five: ${top}.`,
    roleDesc: (l, n, y0, y1, top) =>
      `The greatest League of Legends ${enRoleLower(l)} of all time, ranked: ${n} pros from ${y0} to ${y1} by ` +
      `Career Legend Rating (CLR), counting only their seasons in that role. Top five: ${top}.`,
    asofDesc: (y, top) =>
      `The all-time League of Legends player rankings as they stood at the end of the ${y} season: every ` +
      `career, title and tier counted only through ${y}.${top ? ` Top five then: ${top}.` : ""}`,
    aboutDesc:
      "How the Career Legend Rating (CLR) ranks League of Legends pros: a win-probability model scores every " +
      "player's contribution in every game (LPS), then CLR rolls up career value, pace, peak and résumé. " +
      "Every column and term on the site explained.",
    player: (f) => `${f.name} · #${f.rank} All-Time · LoL Career Stats & Titles | CLR`,
    playerDesc: (f) => {
      const who = f.realName ? `${f.name} (${f.realName})` : f.name;
      const team = f.team ? ` ${f.active ? "for" : "last with"} ${f.team}${f.league ? ` (${f.league})` : ""}` : "";
      const lane = f.laneRank && f.lane ? `, #${f.laneRank} among ${enRoleLower(f.lane)}` : "";
      const won = titleList(f.titles, { worlds: "Worlds", msi: "MSI", first_stand: "First Stand", ewc: "EWC" },
        (n, w) => `${n}× ${w}`, ", ", "domestic league");
      return [
        `${who}, League of Legends ${f.lane ? EN_ROLE_ONE[f.lane] : "player"}${team}, ${f.span}.`,
        `Ranked #${f.rank} all-time by Career Legend Rating (CLR ${f.clr})${lane}.`,
        won ? `Titles: ${won}.` : "",
        `${f.games.toLocaleString("en-US")} pro games${f.winPct != null ? `, ${f.winPct}% win rate` : ""}.`,
        f.champs.length ? `Best champions: ${f.champs.join(", ")}.` : "",
      ].filter(Boolean).join(" ");
    },
    list: (names) =>
      names.length <= 1 ? names.join("") : `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`,
    ogLocale: "en_US",
  },
  ko: {
    home: "역대 최고의 롤 프로게이머 순위 · 리그 오브 레전드 이스포츠 · CLR",
    role: (l) => `역대 최고의 롤 ${KO_ROLES[l]} 선수 순위 · CLR`,
    asof: (y) => `${y} 시즌 종료 기준 역대 롤 선수 순위 · CLR`,
    about: "CLR 소개 · 롤 이스포츠 커리어 평가 방식",
    card: (name) => `${name} · CLR 카드`,
    homeDesc: (n, y0, y1, top) =>
      `리그 오브 레전드(롤) 역대 최고의 프로게이머 순위. ${y0}–${y1} LCK·LPL·LEC·LCS 등 주요 리그 선수 ` +
      `${n}명을 경기별 승리 기여도와 우승·수상 경력을 합산한 커리어 레전드 레이팅(CLR)으로 평가합니다. ` +
      `상위 5명: ${top}.`,
    roleDesc: (l, n, y0, y1, top) =>
      `롤 역대 최고의 ${KO_ROLES[l]} 선수 순위. ${y0}–${y1} 프로 선수 ${n}명을 해당 포지션에서 뛴 시즌만으로 ` +
      `커리어 레전드 레이팅(CLR)을 매겨 평가합니다. 상위 5명: ${top}.`,
    asofDesc: (y, top) =>
      `${y} 시즌 종료 시점의 롤 역대 선수 순위. 그 시즌까지의 커리어, 우승, 티어만 반영합니다.` +
      (top ? ` 당시 상위 5명: ${top}.` : ""),
    aboutDesc:
      "커리어 레전드 레이팅(CLR)이 롤 프로 선수를 평가하는 방식. 승률 예측 모델로 모든 경기에서 선수의 기여도(LPS)를 " +
      "계산하고, 커리어 가치·페이스·전성기·경력을 합산합니다. 사이트의 모든 지표와 용어를 설명합니다.",
    player: (f) => `${nameWith(f, "(", ")")} · 역대 ${f.rank}위 · 롤 커리어 기록 | CLR`,
    playerDesc: (f) => {
      const role = f.lane ? KO_ROLES[f.lane] : "프로";
      const team = f.team ? `${f.active ? "" : "전 "}${f.team}${f.league ? `(${f.league})` : ""} 소속 ` : "";
      const won = titleList(f.titles, { worlds: "롤드컵", msi: "MSI", first_stand: "퍼스트 스탠드", ewc: "이스포츠 월드컵" },
        (n, w) => `${w} ${n}회`, ", ", "리그");
      return [
        `${nameWith(f, "(", ")")}: ${team}리그 오브 레전드 ${role} 선수, ${f.span}.`,
        `커리어 레전드 레이팅(CLR ${f.clr}) 역대 ${f.rank}위${f.laneRank && f.lane ? `, ${KO_ROLES[f.lane]} ${f.laneRank}위` : ""}.`,
        won ? `우승: ${won}.` : "",
        `프로 통산 ${f.games.toLocaleString("ko-KR")}경기${f.winPct != null ? `, 승률 ${f.winPct}%` : ""}.`,
        f.champs.length ? `대표 챔피언: ${f.champs.join(", ")}.` : "",
      ].filter(Boolean).join(" ");
    },
    list: (names) => names.join(", "),
    ogLocale: "ko_KR",
  },
  zh: {
    home: "英雄联盟历史最佳职业选手排行榜 · LOL电竞 · CLR",
    role: (l) => `英雄联盟历史最佳${ZH_ROLES[l]}选手排行榜 · CLR`,
    asof: (y) => `截至${y}赛季末的英雄联盟历史选手排行榜 · CLR`,
    about: "关于CLR · 英雄联盟电竞生涯评分说明",
    card: (name) => `${name} · CLR选手卡`,
    homeDesc: (n, y0, y1, top) =>
      `英雄联盟历史最佳职业选手排行榜：${y0}–${y1}年间LCK、LPL、LEC、LCS等主要赛区的${n}名选手，` +
      `按生涯传奇评分（CLR）排名，综合每场比赛对胜利的贡献与冠军、奖项。前五名：${top}。`,
    roleDesc: (l, n, y0, y1, top) =>
      `英雄联盟历史最佳${ZH_ROLES[l]}选手排行榜：${y0}–${y1}年间${n}名职业选手，仅计算其在该位置的赛季，` +
      `按生涯传奇评分（CLR）排名。前五名：${top}。`,
    asofDesc: (y, top) =>
      `截至${y}赛季末的英雄联盟历史选手排行榜：生涯、冠军与段位只计算到${y}年为止。` + (top ? `当时前五名：${top}。` : ""),
    aboutDesc:
      "生涯传奇评分（CLR）如何评价英雄联盟职业选手：胜率模型计算每位选手在每场比赛中的贡献（LPS），" +
      "再综合生涯价值、效率、巅峰与履历。网站上每个指标与术语的说明。",
    player: (f) => `${nameWith(f, "（", "）")} · 历史第${f.rank}名 · 英雄联盟生涯数据 | CLR`,
    playerDesc: (f) => {
      const role = f.lane ? ZH_ROLES[f.lane] : "职业";
      const team = f.team ? `，${f.active ? "效力于" : "曾效力于"}${f.team}${f.league ? `（${f.league}）` : ""}` : "";
      const won = titleList(f.titles, { worlds: "全球总决赛", msi: "MSI", first_stand: "先锋赛", ewc: "电竞世界杯" },
        (n, w) => `${w}${/[A-Za-z]$/.test(w) ? " " : ""}${n}次`, "、", "联赛");
      return [
        `${nameWith(f, "（", "）")}，英雄联盟${role}选手${team}，${f.span}。`,
        `生涯传奇评分（CLR ${f.clr}）历史第${f.rank}名${f.laneRank && f.lane ? `，${ZH_ROLES[f.lane]}第${f.laneRank}名` : ""}。`,
        won ? `冠军：${won}。` : "",
        `职业比赛${f.games}场${f.winPct != null ? `，胜率${f.winPct}%` : ""}。`,
        f.champs.length ? `代表英雄：${f.champs.join("、")}。` : "",
      ].join("");
    },
    list: (names) => names.join("、"),
    ogLocale: "zh_CN",
  },
};
