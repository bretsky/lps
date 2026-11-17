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

/** Search results show about 160 characters of a description (Bing flags longer ones as an error).
 *  Hangul / CJK count double, being about twice as wide on the results page. */
const DESC_MAX = 160;
const descWidth = (s: string) =>
  [...s].reduce((w, c) => w + (/[ᄀ-ᇿ⺀-鿿가-힯豈-﫿＀-￯]/.test(c) ? 2 : 1), 0);

/** Joins a description's sentences in order, leaving out any after the first that would take it
 *  past DESC_MAX, so list them most important first. */
function fit(sep: string, parts: (string | false | 0 | null | undefined)[]): string {
  let out = "";
  for (const p of parts) {
    if (!p) continue;
    const next = out ? out + sep + p : p;
    if (!out || descWidth(next) <= DESC_MAX) out = next;
  }
  return out;
}

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
    homeDesc: (n, y0, y1, top) => fit(" ", [
      `The greatest League of Legends pros of all time: ${n} players, ${y0}–${y1}, ranked by Career Legend Rating.`,
      `Top five: ${top}.`,
    ]),
    roleDesc: (l, n, y0, y1, top) => fit(" ", [
      `The greatest League of Legends ${enRoleLower(l)} of all time: ${n} pros, ${y0}–${y1}.`,
      `Top five: ${top}.`,
      "Ranked only on their seasons in the role.",
    ]),
    asofDesc: (y, top) => fit(" ", [
      `All-time League of Legends rankings at the end of ${y}.`,
      top && `Top five then: ${top}.`,
      "Careers counted only through that season.",
    ]),
    aboutDesc:
      "How Career Legend Rating (CLR) ranks League of Legends pros: each player's impact on winning in every game, " +
      "plus titles and awards.",
    player: (f) => `${f.name} · #${f.rank} All-Time · LoL Career Stats & Titles | CLR`,
    playerDesc: (f) => {
      const who = f.realName ? `${f.name} (${f.realName})` : f.name;
      const team = f.team ? ` ${f.active ? "for" : "last with"} ${f.team}` : "";
      const won = titleList(f.titles, { worlds: "Worlds", msi: "MSI", first_stand: "First Stand", ewc: "EWC" },
        (n, w) => `${n}× ${w}`, ", ", "domestic league");
      return fit(" ", [
        `${who}, LoL ${f.lane ? EN_ROLE_ONE[f.lane] : "pro"}${team}, ${f.span}. #${f.rank} all-time (CLR ${f.clr}).`,
        won && `Titles: ${won}.`,
        f.laneRank && f.lane && `#${f.laneRank} among ${enRoleLower(f.lane)}.`,
        `${f.games.toLocaleString("en-US")} pro games${f.winPct != null ? `, ${f.winPct}% wins` : ""}.`,
        f.champs.length > 0 && `Best on ${f.champs.join(", ")}.`,
      ]);
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
    homeDesc: (n, y0, y1, top) => fit(" ", [
      `롤 역대 최고의 프로게이머 순위: ${y0}–${y1} 선수 ${n}명.`,
      `상위 5명: ${top}.`,
      "승리 기여도와 우승 경력으로 평가합니다.",
    ]),
    roleDesc: (l, n, y0, y1, top) => fit(" ", [
      `롤 역대 최고의 ${KO_ROLES[l]} 순위: ${y0}–${y1} 선수 ${n}명.`,
      `상위 5명: ${top}.`,
      "해당 포지션 시즌만 반영합니다.",
    ]),
    asofDesc: (y, top) => fit(" ", [
      `${y} 시즌 종료 시점의 롤 역대 선수 순위.`,
      top && `당시 상위 5명: ${top}.`,
      "그 시즌까지의 기록만 반영합니다.",
    ]),
    aboutDesc: "커리어 레전드 레이팅(CLR)이 롤 프로 선수를 평가하는 방식: 경기별 승리 기여도와 우승·수상 경력.",
    player: (f) => `${nameWith(f, "(", ")")} · 역대 ${f.rank}위 · 롤 커리어 기록 | CLR`,
    playerDesc: (f) => {
      const role = f.lane ? KO_ROLES[f.lane] : "프로";
      const team = f.team ? `${f.active ? "" : "전 "}${f.team} ` : "";
      const won = titleList(f.titles, { worlds: "롤드컵", msi: "MSI", first_stand: "퍼스트 스탠드", ewc: "이스포츠 월드컵" },
        (n, w) => `${w} ${n}회`, ", ", "리그");
      return fit(" ", [
        `${nameWith(f, "(", ")")}: ${team}${role}, ${f.span}. 역대 ${f.rank}위(CLR ${f.clr}).`,
        won && `우승: ${won}.`,
        f.laneRank && f.lane && `${KO_ROLES[f.lane]} ${f.laneRank}위.`,
        `통산 ${f.games.toLocaleString("ko-KR")}경기${f.winPct != null ? `, 승률 ${f.winPct}%` : ""}.`,
        f.champs.length > 0 && `대표 챔피언: ${f.champs.join(", ")}.`,
      ]);
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
    homeDesc: (n, y0, y1, top) => fit("", [
      `英雄联盟历史最佳职业选手排行榜：${y0}–${y1}年${n}名选手。`,
      `前五名：${top}。`,
      "综合胜利贡献与冠军履历。",
    ]),
    roleDesc: (l, n, y0, y1, top) => fit("", [
      `英雄联盟历史最佳${ZH_ROLES[l]}排行榜：${y0}–${y1}年${n}名选手。`,
      `前五名：${top}。`,
      "只计该位置的赛季。",
    ]),
    asofDesc: (y, top) => fit("", [
      `截至${y}赛季末的英雄联盟历史选手排行榜。`,
      top && `当时前五名：${top}。`,
      `只计算到${y}年为止。`,
    ]),
    aboutDesc: "生涯传奇评分（CLR）如何评价英雄联盟职业选手：每场比赛的胜利贡献，加上冠军与奖项。",
    player: (f) => `${nameWith(f, "（", "）")} · 历史第${f.rank}名 · 英雄联盟生涯数据 | CLR`,
    playerDesc: (f) => {
      const role = f.lane ? ZH_ROLES[f.lane] : "职业";
      const team = f.team ? `，${f.active ? "" : "曾效力"}${f.team}` : "";
      const won = titleList(f.titles, { worlds: "全球总决赛", msi: "MSI", first_stand: "先锋赛", ewc: "电竞世界杯" },
        (n, w) => `${w}${/[A-Za-z]$/.test(w) ? " " : ""}${n}次`, "、", "联赛");
      return fit("", [
        `${nameWith(f, "（", "）")}，英雄联盟${role}${team}，${f.span}。历史第${f.rank}名（CLR ${f.clr}）。`,
        won && `冠军：${won}。`,
        f.laneRank && f.lane && `${ZH_ROLES[f.lane]}第${f.laneRank}名。`,
        `职业比赛${f.games}场${f.winPct != null ? `，胜率${f.winPct}%` : ""}。`,
        f.champs.length > 0 && `代表英雄：${f.champs.join("、")}。`,
      ]);
    },
    list: (names) => names.join("、"),
    ogLocale: "zh_CN",
  },
};
