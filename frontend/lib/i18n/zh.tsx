// Simplified Chinese UI text (see en.tsx for the shape). Terms follow LPL broadcast usage:
// 全球总决赛, 先锋赛, 上单 / 打野 / 中单 / ADC / 辅助, 最佳阵容, FMVP, 名人堂, 赛区. The site's own
// terms: Résumé = 荣誉, Career / Pace / Peak = 生涯 / 年均 / 巅峰, tier = 梯队. Chinese prose
// uses full-width punctuation.

import type { ReactNode } from "react";
import type { Messages } from "./en";

const ROLE_NAMES: Record<string, string> = { top: "上单", jng: "打野", mid: "中单", bot: "ADC", sup: "辅助" };

export const zh: Messages = {
  lang: { label: "语言" },
  notFound: { title: "页面未找到", body: "该页面不存在或已移动。" },
  nav: {
    rankings: "历史排行榜",
    rankingsShort: "排行榜",
    profile: "选手资料",
    playerCard: "选手卡",
    about: "关于",
    viewCard: "查看选手卡",
  },
  footer: {
    build: (build: string, rated: number, asOf: number | null, minGames: number) =>
      `版本 ${build} · ${asOf !== null ? `截至${asOf}赛季末，` : ""}参评选手 ${rated} 名（至少 ${minGames} 场）`,
    aboutLink: "关于CLR与术语表",
    byRole: "各位置历史排行榜",
    pastSeasons: "往届赛季",
    disclaimer: "本站未获Riot Games认可 · 数据和照片来自Oracle's Elixir与Leaguepedia · 联赛标志版权归各自所有者所有",
  },

  lanes: { top: "上单", jng: "打野", mid: "中单", bot: "ADC", sup: "辅助" },
  tiers: {
    goats: { label: "GOAT", one: "GOAT" },
    legends: { label: "传奇", one: "传奇" },
    greats: { label: "巨星", one: "巨星" },
    elite: { label: "精英", one: "精英" },
    stars: { label: "明星", one: "明星" },
    contenders: { label: "竞争者", one: "竞争者" },
  },
  parts: { career: "生涯", pace: "年均", peak: "巅峰", resume: "荣誉" },
  events: {
    worlds: "全球总决赛",
    msi: "MSI",
    first_stand: "先锋赛",
    ewc: "电竞世界杯",
    intl: "国际赛事",
    domestic: "联赛",
    cup: "杯赛",
  },
  places: { gold: "冠军", silver: "亚军", bronze: "四强" },
  edition: {
    hol: "名人堂",
    worlds: "世界冠军",
    tier: (one: string) => `${one}版`,
    word: "版",
    inducted: (y: number) => `${y}年入选`,
  },
  status: {
    hol: (y: number | null) => (y ? `名人堂成员（${y}年入选）` : "名人堂成员"),
    active: "现役——本赛季仍在参赛",
    activeShort: "现役",
    retired: "退役",
    inactive: "未活跃——休息、服兵役、转型教练或情况不明",
    inactiveShort: "未活跃",
  },
  marks: {
    honor: (year: number, what: string, place: string) => `${year} ${what} — ${place}`,
    eventChampion: (n: number, event: string) => `${n}次${event}冠军`,
    domesticChampion: (leagues: [string, number][], other: number, total: number) =>
      leagues.length
        ? [...leagues.map(([lg, n]) => `${n}次${lg}冠军`), ...(other > 0 ? [`${other}次其他联赛冠军`] : [])].join("、")
        : `${total}次联赛冠军`,
  },
  common: {
    games: (g: string) => `${g}场`,
    winRate: (wr: string) => `胜率 ${wr}`,
    kda: (k: string) => `KDA ${k}`,
    pts: (x: string) => `${x}分`,
  },

  frozen: (year: number, sep: ReactNode, back: ReactNode): ReactNode => (
    <>
      定格于{year}赛季末 {sep} 生涯、冠军和梯队只计入截至当时的成绩 {sep} {back}
    </>
  ),
  backToToday: "返回今日",
  hero: {
    kicker: "英雄联盟电竞",
    titleA: "历史",
    titleB: "排行榜",
    subtitle: "生涯传奇评分",
    asOf: (y: number) => `截至${y}赛季末`,
    viewCard: (rank: number, name: string) => `#${rank} ${name} — 查看选手卡`,
    roleB: ROLE_NAMES,
  },
  board: {
    allRoles: "全部位置",
    yearTitle: "查看过去某个赛季结束时的排名",
    yearAria: "按赛季查看排名",
    asOfToday: (y: number) => `截至今日（${y}）`,
    asOfEnd: (y: number) => `截至${y}赛季末`,
    search: "搜索选手或姓名…",
    allLeagues: "全部联赛",
    leagueAria: "联赛",
    sortAria: "排序方式",
    sortBy: (label: string) => `排序 · ${label}`,
    sort: { clr: "CLR", total_score: "生涯LPS", peak_lps: "巅峰LPS", resume_bonus: "荣誉", n_years: "生涯年限" },
    col: { player: "选手", role: "位置", career: "生涯", titles: "冠军", clr: "CLR", peak: "巅峰" },
    players: (n: number) => `${n} 名选手`,
    loadFailed: "无法加载更多选手",
    retry: "重试",
    loading: "正在加载选手…",
  },
  row: {
    isNew: "新",
    notRated: (y: number) => `${y}赛季末尚未参评`,
    rankSame: (prev: number, y: number) => `${y}赛季末排名 #${prev}（无变化）`,
    rankMove: (up: boolean, d: number, prev: number, y: number) =>
      `${up ? "上升" : "下降"}${d}位 · ${y}赛季末排名 #${prev}`,
    clrSame: (prev: string, y: number) => `${y}赛季末CLR ${prev}（无变化）`,
    clrMove: (prev: string, y: number, delta: string) => `${y}赛季末CLR ${prev}（${delta}）`,
    gamesWin: (g: string, wr: string) => `${g}场 · ${wr}`,
  },

  profile: {
    photo: (caption: string) => `照片 · ${caption}`,
    years: (first: number, last: number, n: number) =>
      first === last ? `${first} · ${n}年` : `${first}–${last} · ${n}年`,
    trophy: {
      worlds: "全球总决赛",
      msi: "MSI",
      first_stand: "先锋赛",
      ewc: "EWC",
      domestic: "联赛冠军",
      mvp: "MVP",
    },
    trophyTitle: (n: number, label: string) => `${label} ×${n}`,
    global: "总榜",
    nearby: "排名相近",
  },
  waterfall: {
    title: "CLR构成",
    tips: {
      career: "生涯总量——经样本收缩修正后的各赛季产出总和。",
      pace: "年均产出——按生涯长度调整后的产出。",
      peak: "巅峰赛季——奖励最高水平有多高。",
      resume: "奖杯——全球总决赛/MSI/联赛冠军 + MVP/最佳阵容。",
    },
    pctOfClr: (p: string) => `占CLR的${p}%`,
    resumeSplit: "荣誉构成：",
    intl: "国际赛",
    titles: "冠军",
    awards: "奖项",
  },
  resume: {
    title: "荣誉",
    summary: (pts: string, n: number) => `${pts}分 · ${n}项成就`,
    rows: { worlds: "全球总决赛", msi: "MSI", otherIntl: "其他国际", league: "联赛", awards: "奖项" },
    cats: {
      champion: "冠军",
      finalist: "亚军",
      out: "止步决赛前",
      cup: "杯赛",
      mvp: "MVP",
      allpro: "最佳阵容",
    },
    otherIntlEvents: "IEM / EWC / MSC / 先锋赛 / 洲际赛",
    hint: {
      champion: (event: string) => `${event}冠军`,
      finalist: (event: string) => `${event}亚军`,
      out: (event: string) => `${event}：止步决赛前（四强、八强或小组赛）`,
      domChampion: "联赛冠军",
      domFinalist: "联赛亚军",
      domCup: "国内杯赛 / 次级国内赛事冠军",
      mvp: "常规赛或季后赛MVP",
      allpro: "入选最佳阵容",
    },
    trophyCase: (n: number) => `荣誉陈列 · ${n}个冠军`,
    kind: {
      worlds: "全球总决赛",
      msi: "MSI",
      first_stand: "先锋赛",
      ewc: "EWC",
      intl: "国际",
      domestic: "联赛",
      cup: "杯赛",
    },
    chipPlace: { gold: "冠军", silver: "亚军", bronze: "四强" },
  },
  anatomy: {
    title: "生涯LPS剖析",
    total: "总计",
    peak: "巅峰",
    phase: { reg_pts: "常规赛", playoff_pts: "季后赛", tourn_pts: "国际赛" },
    comp: { base_pts: "基础分", contrib_pts: "贡献值", wbonus_pts: "胜利加成" },
    compHint: {
      base_pts: "仅凭在参评战队中担任该位置即可获得的价值。",
      contrib_pts: "超出预期的表现——模型捕捉到的信号。",
      wbonus_pts: "对模型未预料到的胜利的奖励（beta * (result - p_model)）。",
    },
    source: { kills_pts: "击杀", deaths_pts: "死亡", assists_pts: "助攻", damage_pts: "伤害" },
    byPhase: "按阶段",
    byPhaseSub: "常规赛 / 季后赛 / 国际赛事",
    byComponent: "按构成",
    byComponentSub: "基础分 / 贡献值 / 胜利加成",
    bySource: "按数据来源",
    bySourceSub: "击杀 / 死亡 / 助攻 / 伤害——合计即贡献值",
    byTournament: "按赛事",
  },
  season: {
    title: "逐赛季表现",
    summary: (peak: string, year: number | null, n: number) => `巅峰 ${peak}${year ? `（${year}）` : ""} · ${n}个赛季`,
    year: "年份",
    team: "战队",
    cup: {
      worlds: "全球总决赛",
      msi: "MSI",
      first_stand: "先锋赛",
      ewc: "电竞世界杯",
      intl: "其他国际赛事",
      domestic: "联赛",
      cup: "国内杯赛",
    },
    medal: { gold: "冠军", silver: "亚军", bronze: "四强" },
    chip: (event: string, medal: string, n: number) => `${event}${medal}${n > 1 ? ` ×${n}` : ""}`,
    mvpChip: (n: number) => `MVP奖项${n > 1 ? ` ×${n}` : ""}`,
    allproChip: (n: number) => `入选最佳阵容${n > 1 ? ` ×${n}` : ""}`,
    tip: {
      lps: (v: string) => `${v} LPS`,
      regular: (v: string) => `常规赛 ${v}`,
      playoffs: (v: string) => `季后赛 ${v}`,
      intl: (v: string) => `国际赛 ${v}`,
      global: (r: number) => `总榜 #${r}`,
      lane: (r: number) => `位置 #${r}`,
    },
    legend: {
      regular: "常规赛",
      playoffs: "季后赛",
      intl: "国际赛",
      peakYr: "巅峰赛季",
      negative: "负值",
      hnGlobal: "HN总榜排名",
      hnLane: "HN位置排名",
      lineTop: "（线条顶端 = 第1名）",
      cups: "奖杯 = 赛事：",
      tint: "颜色 = 名次：",
      mvp: "MVP奖项",
      allpro: "入选最佳阵容",
    },
  },
  splits: {
    title: "细分数据",
    teams: "战队",
    leagues: "联赛",
    lanes: "位置",
    rate: {
      lpsGame: { label: "场均LPS", hint: "加权场均LPS（按阶段和比赛重要性调整）。" },
      clutch: { label: "关键战差值", hint: "高重要性比赛中场均产出的差值。" },
      intangibles: { label: "隐性价值", hint: "平均残差——模型未涵盖的场均价值（avg_resid）。" },
      sos: { label: "赛程强度", hint: "赛程强度——所遇对手的平均水平。" },
      regionElo: { label: "赛区Elo", hint: "当前赛区强度（主要联赛的赛季平均Elo）。" },
      avgContrib: { label: "平均贡献值", hint: "高于基准的场均贡献（增加的胜率）。" },
      hnLane: { label: "HN排名（位置）", hint: "同位置内最佳赛季的High Noon排名。" },
      hnGlobal: { label: "HN排名（总榜）", hint: "与所有位置相比的最佳赛季High Noon排名。" },
    },
    bestN: (yrs: string) => `最佳N个赛季：${yrs}`,
  },
  champs: {
    title: "英雄池",
    summary: (n: number) => `使用过${n}个英雄 · 按获得的LPS排序`,
    careerKda: "生涯 K / D / A",
    careerKdaHint: (n: string) => `有数据统计的${n}场比赛合计。`,
    kdaHint: "（击杀 + 助攻）/ 死亡，生涯总计。",
    perGame: "场均",
    perGameHint: "场均击杀 / 死亡 / 助攻。",
    careerCs: "生涯补刀",
    careerCsHint: "小兵 + 野怪，仅计有补刀记录的比赛。",
    cspm: "分均补刀",
    col: { champion: "英雄", games: "场次", winPct: "胜率", kda: "K / D / A", lps: "获得LPS" },
  },

  card: {
    rank: "排名",
    clrSub: (rank: number) => `历史 #${rank}`,
    peak: "巅峰",
    winPct: "胜率 %",
    shelf: {
      worlds: "全球总决赛冠军",
      msi: "MSI冠军",
      first_stand: "先锋赛冠军",
      ewc: "电竞世界杯冠军",
      domestic: "联赛冠军",
      mvp: "MVP奖项",
    },
    shelfTitle: (n: number, what: string) => `${what} ×${n}`,
    noShelf: (first: number, last: number, seasons: number, games: string) =>
      `${first}–${last} · ${seasons}个赛季 · ${games}场`,
    percentile: "百分位概览",
    readout: {
      careerLps: "生涯LPS",
      seasons: "赛季",
      lpsGame: "场均LPS",
      bestLane: "位置最佳排名",
      bestGlobal: "总榜最佳排名",
      peakYears: "巅峰赛季数",
    },
    signature: "招牌英雄",
    champLine: (games: number, lps: string) => `${games}场 · ${lps}`,
    moreTitles: (n: number) => `另有${n}个冠军`,
    noTitles: "尚无冠军",
    saving: "正在保存…",
    save: (back: boolean) => `将${back ? "背面" : "正面"}保存为图片`,
    saveError: "无法生成图片——请重试",
    flip: (toBack: boolean) => (toBack ? "翻到卡片背面" : "翻到卡片正面"),
    clickToFlip: "点击卡片翻面",
  },
  radar: {
    axes: {
      peak: "巅峰",
      longevity: "持久",
      consistency: "稳定",
      resume: "荣誉",
      impact: "影响力",
      clutch: "关键战",
      dominance: "统治力",
    },
    all: "全部选手",
    vsLane: (lane: string) => `对比${lane}`,
  },

  about: {
    kicker: "运作方式",
    titleA: "关于",
    titleB: "CLR",
    intro: (hl: (s: string) => ReactNode): ReactNode => (
      <>
        {hl("生涯传奇评分")}（CLR）为每位选手的整个职业生涯排名。它的基础是LPS（联赛表现评分），衡量每位选手在每场比赛中，与处于同样局面的普通选手相比，使战队胜率变化了多少。各赛季单独计分，再汇总为CLR；CLR还会计入冠军、名次和奖项。
      </>
    ),
    weight: (part: string) => `${part}权重`,
    settings: (first: number, last: number, minGames: number, build: string, sep: ReactNode): ReactNode => (
      <>
        {first}–{last}赛季 {sep} 至少{minGames}场参评 {sep} 版本 {build}
      </>
    ),
    sectionsAria: "章节",
    resumePointsNav: "荣誉分值",
    linkTo: (label: string) => `链接到“${label}”`,
    sections: {
      clr: {
        title: "生涯传奇评分",
        blurb: "核心数值：每段职业生涯一个分数，综合总量、年均、巅峰和奖杯。",
      },
      resume: {
        title: "荣誉",
        blurb: "数据统计看不到的大舞台成绩：名次、冠军和奖项。每一项都有固定分值，列在下方的表格中。",
      },
      "resume-categories": {
        title: "荣誉类别",
        blurb: "资料页中荣誉划分的14个类别，每类显示选手获得的次数，以及扣除重复折扣后增加的CLR分值。",
      },
      lps: {
        title: "赛季得分（LPS）",
        blurb: "在汇总为CLR之前，每个赛季如何根据比赛本身计分。",
      },
      context: { title: "比赛背景", blurb: "描述一个赛季背后比赛情况的辅助数值。" },
      ranks: {
        title: "排名与同侪",
        blurb: "选手在所有选手中的位置，以及其价值的来源。",
      },
      other: { title: "其他", blurb: "术语表中的其余条目。" },
    },
    rs: {
      title: "荣誉如何计分",
      intro: (w: string) =>
        `每项成就都会为CLR增加固定的分数。下面所有数值都已包含荣誉的CLR权重（×${w}），因此正好等于首次获得该成就时为选手CLR增加的分数。`,
      intlTitle: "国际赛事与杯赛",
      intlBody: (perWeight: string, rounds: [string, string][]) =>
        `全球总决赛和MSI冠军的分值是设定好的。其他赛事的冠军分值为 ${perWeight} × 该赛事的赛事权重，这一权重与该赛事的比赛在LPS中所占的重要性权重相同（全球总决赛 = 1）。冠军以下的每一轮获得冠军分值的固定比例：${rounds
          .map(([label, pct]) => `${label} ${pct}%`)
          .join("、")}。战队阵容中的每位选手都获得全额分数。`,
      event: "赛事",
      weight: "权重",
      set: "设定",
      cupsRow: "国内杯赛（计入国内冠军）",
      domTitle: "国内联赛",
      domBody: (champion: string, finalist: string, year: number) =>
        `赛段季后赛冠军最高为${champion}分，决赛失利最高为${finalist}分，再乘以联赛强度：当年该联赛的Elo评分除以最强联赛的评分。${year}年的数值：`,
      league: "联赛",
      strength: "强度",
      titleCol: "冠军",
      runnerUp: "亚军",
      awardsTitle: "个人奖项",
      awardsBody: "国际赛事奖项为固定分值。联赛奖项（标*）与冠军一样乘以联赛强度，因此所示数值是其最高可能分值。",
      award: "奖项",
      points: "分值",
      repeatsTitle: "重复获得",
      repeatsBody: (pct: number, example: string, steps: string[], total: ReactNode, naive: string): ReactNode => (
        <>
          重复获得同一项成就，价值为前一次的{pct}%。按以下分组分别计算：同一赛事的同一轮次（每个全球总决赛冠军、每次MSI亚军）、所有联赛冠军合为一组、所有联赛亚军合为一组，以及每种奖项各为一组。选手价值最高的一次始终全额计算。例如，{example}相加为
          {steps.join(" + ")} = {total}，而不是{naive}。
        </>
      ),
    },
  },
};
