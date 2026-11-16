// Korean UI text (see en.tsx for the shape). Terms follow LCK broadcast usage: 월즈, 원딜,
// 서포터, 올프로, 파이널 MVP, 명예의 전당. The site's own terms: Résumé = 업적,
// Career / Pace / Peak = 커리어 / 페이스 / 피크. Sentences avoid putting a particle straight
// after a variable number (이/가, 을/를 depend on how the number is read).

import type { ReactNode } from "react";
import type { Messages } from "./en";

export const ko: Messages = {
  meta: {
    home: "CLR · 역대 랭킹",
    asof: (y: number) => `CLR · ${y} 시즌 종료 기준 역대 랭킹`,
    about: "소개 · CLR",
    card: (name: string) => `${name} · CLR 카드`,
  },
  lang: { label: "언어" },
  nav: {
    rankings: "역대 랭킹",
    rankingsShort: "랭킹",
    profile: "프로필",
    playerCard: "선수 카드",
    about: "소개",
    viewCard: "카드 보기",
  },
  footer: {
    build: (build: string, rated: number, asOf: number | null, minGames: number) =>
      `빌드 ${build} · ${asOf !== null ? `${asOf} 시즌 종료 기준 ` : ""}평가 대상 선수 ${rated}명 (${minGames}경기 이상)`,
    aboutLink: "CLR 소개 및 용어 설명",
    disclaimer:
      "Riot Games의 공식 승인을 받지 않은 사이트입니다 · 데이터 및 사진 출처: Oracle's Elixir, Leaguepedia · 리그 로고의 권리는 각 소유자에게 있습니다",
  },

  lanes: { top: "탑", jng: "정글", mid: "미드", bot: "원딜", sup: "서포터" },
  tiers: {
    goats: { label: "GOAT", one: "GOAT" },
    legends: { label: "레전드", one: "레전드" },
    greats: { label: "거장", one: "거장" },
    elite: { label: "엘리트", one: "엘리트" },
    stars: { label: "스타", one: "스타" },
    contenders: { label: "컨텐더", one: "컨텐더" },
  },
  parts: { career: "커리어", pace: "페이스", peak: "피크", resume: "업적" },
  events: {
    worlds: "월즈",
    msi: "MSI",
    first_stand: "퍼스트 스탠드",
    ewc: "이스포츠 월드컵",
    intl: "국제 대회",
    domestic: "리그",
    cup: "컵 대회",
  },
  places: { gold: "우승", silver: "준우승", bronze: "4강" },
  edition: {
    hol: "명예의 전당",
    worlds: "월즈 우승자",
    tier: (one: string) => `${one} 에디션`,
    word: "에디션",
    inducted: (y: number) => `${y} 헌액`,
  },
  status: {
    hol: (y: number | null) => `명예의 전당 헌액자${y ? ` (${y})` : ""}`,
    active: "현역 — 이번 시즌 출전 중",
    activeShort: "현역",
    retired: "은퇴",
    inactive: "비활동 — 휴식, 군 복무, 코치 전향 또는 알 수 없음",
    inactiveShort: "비활동",
  },
  marks: {
    honor: (year: number, what: string, place: string) => `${year} ${what} — ${place}`,
    eventChampion: (n: number, event: string) => `${event} 우승 ${n}회`,
    domesticChampion: (leagues: [string, number][], other: number, total: number) =>
      leagues.length
        ? [...leagues.map(([lg, n]) => `${lg} 우승 ${n}회`), ...(other > 0 ? [`기타 리그 우승 ${other}회`] : [])].join(", ")
        : `리그 우승 ${total}회`,
  },
  common: {
    games: (g: string) => `${g}경기`,
    winRate: (wr: string) => `승률 ${wr}`,
    kda: (k: string) => `KDA ${k}`,
    pts: (x: string) => `${x}점`,
  },

  frozen: (year: number, sep: ReactNode, back: ReactNode): ReactNode => (
    <>
      {year} 시즌 종료 시점 기준 {sep} 커리어, 우승, 티어는 그때까지의 기록만 반영합니다 {sep} {back}
    </>
  ),
  backToToday: "현재로 돌아가기",
  hero: {
    kicker: "리그 오브 레전드 이스포츠",
    titleA: "역대",
    titleB: "랭킹",
    subtitle: "커리어 레전드 레이팅",
    asOf: (y: number) => `${y} 시즌 종료 기준`,
    viewCard: (rank: number, name: string) => `#${rank} ${name} — 카드 보기`,
  },
  board: {
    allRoles: "전체 포지션",
    yearTitle: "지난 시즌 종료 시점의 순위 보기",
    yearAria: "시즌 기준 순위",
    asOfToday: (y: number) => `현재 기준 (${y})`,
    asOfEnd: (y: number) => `${y} 시즌 종료 기준`,
    search: "선수 또는 이름 검색…",
    allLeagues: "전체 리그",
    leagueAria: "리그",
    sortAria: "정렬 기준",
    sortBy: (label: string) => `정렬 · ${label}`,
    sort: { clr: "CLR", total_score: "커리어 LPS", peak_lps: "피크 LPS", resume_bonus: "업적", n_years: "활동 기간" },
    col: { player: "선수", role: "포지션", career: "커리어", titles: "우승", clr: "CLR", peak: "피크" },
    players: (n: number) => `선수 ${n}명`,
    loadFailed: "선수를 더 불러오지 못했습니다",
    retry: "다시 시도",
    loading: "선수 불러오는 중…",
  },
  row: {
    isNew: "신규",
    notRated: (y: number) => `${y} 시즌 종료 시점에는 평가 대상이 아니었음`,
    rankSame: (prev: number, y: number) => `${y} 시즌 종료 시점 #${prev} (변동 없음)`,
    rankMove: (up: boolean, d: number, prev: number, y: number) =>
      `${d}계단 ${up ? "상승" : "하락"} · ${y} 시즌 종료 시점 #${prev}`,
    clrSame: (prev: string, y: number) => `${y} 시즌 종료 시점 CLR ${prev} (변동 없음)`,
    clrMove: (prev: string, y: number, delta: string) => `${y} 시즌 종료 시점 CLR ${prev} (${delta})`,
    gamesWin: (g: string, wr: string) => `${g}경기 · ${wr}`,
  },

  profile: {
    photo: (caption: string) => `사진 · ${caption}`,
    years: (first: number, last: number, n: number) =>
      first === last ? `${first} · ${n}년` : `${first}–${last} · ${n}년`,
    trophy: {
      worlds: "월즈",
      msi: "MSI",
      first_stand: "퍼스트 스탠드",
      ewc: "EWC",
      domestic: "리그 우승",
      mvp: "MVP",
    },
    trophyTitle: (n: number, label: string) => `${label} ${n}회`,
    global: "전체",
  },
  waterfall: {
    title: "CLR 구성",
    tips: {
      career: "커리어 볼륨 — 표본 보정을 거친 전 시즌 생산량 합계.",
      pace: "연간 비율 — 커리어 길이를 감안해 보정한 생산량.",
      peak: "피크 시즌 — 최고점이 얼마나 높았는지에 대한 보상.",
      resume: "트로피 — 월즈/MSI/리그 우승 + MVP/올프로 수상.",
    },
    pctOfClr: (p: string) => `CLR의 ${p}%`,
    resumeSplit: "업적 내역:",
    intl: "국제 대회",
    titles: "우승",
    awards: "수상",
  },
  resume: {
    title: "업적",
    summary: (pts: string, n: number) => `${pts}점 · 업적 ${n}개`,
    rows: { worlds: "월즈", msi: "MSI", otherIntl: "기타 국제", league: "리그", awards: "수상" },
    cats: {
      champion: "우승",
      finalist: "준우승",
      out: "결승 전 탈락",
      cup: "컵 대회",
      mvp: "MVP",
      allpro: "올프로",
    },
    otherIntlEvents: "IEM / EWC / MSC / 퍼스트 스탠드 / 리프트 라이벌즈",
    hint: {
      champion: (event: string) => `${event} 우승`,
      finalist: (event: string) => `${event} 준우승`,
      out: (event: string) => `${event}: 결승 전 탈락 (4강, 8강 또는 그룹 스테이지)`,
      domChampion: "리그 우승",
      domFinalist: "리그 준우승",
      domCup: "국내 컵 대회 / 부차적인 국내 타이틀",
      mvp: "정규 시즌 또는 플레이오프 MVP",
      allpro: "올프로 팀 선정",
    },
    trophyCase: (n: number) => `트로피 진열장 · 우승 ${n}회`,
    kind: {
      worlds: "월즈",
      msi: "MSI",
      first_stand: "퍼스트 스탠드",
      ewc: "EWC",
      intl: "국제",
      domestic: "리그",
      cup: "컵",
    },
    chipPlace: { gold: "우승", silver: "준우승", bronze: "4강" },
  },
  anatomy: {
    title: "커리어 LPS 분석",
    total: "합계",
    peak: "피크",
    phase: { reg_pts: "정규 시즌", playoff_pts: "플레이오프", tourn_pts: "국제 대회" },
    comp: { base_pts: "기본 점수", contrib_pts: "기여도", wbonus_pts: "승리 보너스" },
    compHint: {
      base_pts: "평가 대상 팀에서 그 포지션으로 뛰는 것만으로 얻는 가치.",
      contrib_pts: "기대 이상의 활약 — 모델이 포착한 신호.",
      wbonus_pts: "모델이 예측하지 못한 승리에 대한 보상 (beta * (result - p_model)).",
    },
    source: { kills_pts: "킬", deaths_pts: "데스", assists_pts: "어시스트", damage_pts: "피해량" },
    byPhase: "단계별",
    byPhaseSub: "정규 시즌 / 플레이오프 / 국제 대회",
    byComponent: "구성 요소별",
    byComponentSub: "기본 점수 / 기여도 / 승리 보너스",
    bySource: "스탯별",
    bySourceSub: "킬 / 데스 / 어시스트 / 피해량 — 합계가 기여도",
    byTournament: "대회별",
  },
  season: {
    title: "시즌별 기록",
    summary: (peak: string, year: number | null, n: number) => `피크 ${peak}${year ? ` (${year})` : ""} · ${n}시즌`,
    year: "연도",
    team: "팀",
    cup: {
      worlds: "월즈",
      msi: "MSI",
      first_stand: "퍼스트 스탠드",
      ewc: "이스포츠 월드컵",
      intl: "기타 국제 대회",
      domestic: "리그",
      cup: "국내 컵 대회",
    },
    medal: { gold: "우승", silver: "준우승", bronze: "4강" },
    chip: (event: string, medal: string, n: number) => `${event} ${medal}${n > 1 ? ` ×${n}` : ""}`,
    mvpChip: (n: number) => `MVP 수상${n > 1 ? ` ×${n}` : ""}`,
    allproChip: (n: number) => `올프로 선정${n > 1 ? ` ×${n}` : ""}`,
    tip: {
      lps: (v: string) => `${v} LPS`,
      regular: (v: string) => `정규 시즌 ${v}`,
      playoffs: (v: string) => `플레이오프 ${v}`,
      intl: (v: string) => `국제 대회 ${v}`,
      global: (r: number) => `전체 #${r}`,
      lane: (r: number) => `포지션 #${r}`,
    },
    legend: {
      regular: "정규 시즌",
      playoffs: "플레이오프",
      intl: "국제 대회",
      peakYr: "피크 시즌",
      negative: "마이너스",
      hnGlobal: "HN 전체 순위",
      hnLane: "HN 포지션 순위",
      lineTop: "(선 맨 위 = 1위)",
      cups: "트로피 = 대회:",
      tint: "색상 = 성적:",
      mvp: "MVP 수상",
      allpro: "올프로 선정",
    },
  },
  splits: {
    title: "세부 분석",
    teams: "팀",
    leagues: "리그",
    lanes: "포지션",
    rate: {
      lpsGame: { label: "경기당 LPS", hint: "가중 경기당 LPS (단계 및 경기 중요도 보정)." },
      clutch: { label: "클러치 격차", hint: "중요도가 높은 경기에서의 경기당 생산량 차이." },
      intangibles: { label: "무형 요소", hint: "평균 잔차 — 모델이 설명하지 못한 경기당 가치 (avg_resid)." },
      sos: { label: "일정 난이도", hint: "일정 강도 — 상대한 팀들의 평균 수준." },
      regionElo: { label: "지역 Elo", hint: "현재 지역 강도 (주 소속 리그의 시즌 평균 Elo)." },
      avgContrib: { label: "평균 기여도", hint: "기준 대비 경기당 기여도 (더해진 승리 확률)." },
      hnLane: { label: "HN 순위 (포지션)", hint: "포지션 내 최고 시즌들 기준의 High Noon 순위." },
      hnGlobal: { label: "HN 순위 (전체)", hint: "전 포지션 대비 최고 시즌들 기준의 High Noon 순위." },
    },
    bestN: (yrs: string) => `최고 N시즌: ${yrs}`,
  },
  champs: {
    title: "챔피언 폭",
    summary: (n: number) => `플레이한 챔피언 ${n}개 · 획득 LPS 순`,
    careerKda: "커리어 K / D / A",
    careerKdaHint: (n: string) => `기록지가 있는 ${n}경기 합계.`,
    kdaHint: "(킬 + 어시스트) / 데스, 커리어 전체.",
    perGame: "경기당",
    perGameHint: "경기당 평균 킬 / 데스 / 어시스트.",
    careerCs: "커리어 CS",
    careerCsHint: "미니언 + 몬스터, CS가 기록된 경기 기준.",
    cspm: "분당 CS",
    col: { champion: "챔피언", games: "경기", winPct: "승률", kda: "K / D / A", lps: "획득 LPS" },
  },

  card: {
    rank: "순위",
    clrSub: (rank: number) => `역대 #${rank}`,
    peak: "피크",
    winPct: "승률 %",
    shelf: {
      worlds: "월즈 우승",
      msi: "MSI 우승",
      first_stand: "퍼스트 스탠드 우승",
      ewc: "이스포츠 월드컵 우승",
      domestic: "리그 우승",
      mvp: "MVP 수상",
    },
    shelfTitle: (n: number, what: string) => `${what} ${n}회`,
    noShelf: (first: number, last: number, seasons: number, games: string) =>
      `${first}–${last} · ${seasons}시즌 · ${games}경기`,
    percentile: "백분위 프로필",
    readout: {
      careerLps: "커리어 LPS",
      seasons: "시즌",
      lpsGame: "경기당 LPS",
      bestLane: "포지션 최고 순위",
      bestGlobal: "전체 최고 순위",
      peakYears: "피크 시즌 수",
    },
    signature: "주력 챔피언",
    champLine: (games: number, lps: string) => `${games}경기 · ${lps}`,
    moreTitles: (n: number) => `우승 ${n}회 더`,
    noTitles: "아직 우승 없음",
    saving: "저장 중…",
    save: (back: boolean) => `${back ? "뒷면" : "앞면"}을 이미지로 저장`,
    saveError: "이미지를 만들지 못했습니다 — 다시 시도해 주세요",
    flip: (toBack: boolean) => (toBack ? "카드 뒷면 보기" : "카드 앞면 보기"),
    clickToFlip: "카드를 클릭하면 뒤집힙니다",
  },
  radar: {
    axes: {
      peak: "피크",
      longevity: "롱런",
      consistency: "꾸준함",
      resume: "업적",
      impact: "영향력",
      clutch: "클러치",
      dominance: "지배력",
    },
    all: "전체 선수",
    vsLane: (lane: string) => `vs ${lane}`,
  },

  about: {
    kicker: "작동 방식",
    titleA: "CLR",
    titleB: "소개",
    intro: (hl: (s: string) => ReactNode): ReactNode => (
      <>
        {hl("커리어 레전드 레이팅")}(CLR)은 모든 선수의 커리어 전체를 평가해 순위를 매깁니다. 그 바탕은
        LPS(리그 퍼포먼스 스코어)로, 각 선수가 같은 상황의 평균 선수와 비교해 팀의 승리 확률을 경기마다 얼마나
        움직였는지를 측정합니다. 시즌마다 따로 점수를 매긴 뒤 CLR로 합산하며, CLR에는 우승, 순위, 수상도
        반영됩니다.
      </>
    ),
    weight: (part: string) => `${part} 가중치`,
    settings: (first: number, last: number, minGames: number, build: string, sep: ReactNode): ReactNode => (
      <>
        {first}–{last} 시즌 {sep} {minGames}경기 이상 평가 {sep} 빌드 {build}
      </>
    ),
    sectionsAria: "섹션",
    resumePointsNav: "업적 점수",
    linkTo: (label: string) => `${label} 링크`,
    sections: {
      clr: {
        title: "커리어 레전드 레이팅",
        blurb: "대표 지표: 커리어마다 하나의 점수로 누적량, 페이스, 피크, 트로피를 모두 반영합니다.",
      },
      resume: {
        title: "업적",
        blurb:
          "기록지에는 드러나지 않는 큰 무대의 성과: 순위, 우승, 수상. 모두 정해진 점수가 있으며 아래 표에 나와 있습니다.",
      },
      "resume-categories": {
        title: "업적 카테고리",
        blurb:
          "프로필에서 업적을 나누는 14개 카테고리로, 각각 선수가 달성한 횟수와 반복 할인 후 더해지는 CLR 점수를 보여 줍니다.",
      },
      lps: {
        title: "시즌 점수 (LPS)",
        blurb: "CLR로 합산되기 전, 각 시즌을 경기 자체로부터 어떻게 채점하는지 설명합니다.",
      },
      context: { title: "경기 맥락", blurb: "시즌을 이루는 경기들을 설명하는 보조 수치입니다." },
      ranks: {
        title: "순위와 비교",
        blurb: "선수가 다른 선수들과 비교해 어디에 서 있는지, 그리고 가치가 어디서 나왔는지 보여 줍니다.",
      },
      other: { title: "기타", blurb: "용어 설명의 나머지 항목입니다." },
    },
    rs: {
      title: "업적 채점 방식",
      intro: (w: string) =>
        `모든 업적은 CLR에 정해진 점수를 더합니다. 아래의 모든 값에는 이미 업적의 CLR 가중치(×${w})가 반영되어 있으므로, 처음 달성한 업적이 선수의 CLR에 더하는 점수와 정확히 같습니다.`,
      intlTitle: "국제 대회 및 컵 대회",
      intlBody: (perWeight: string, rounds: [string, string][]) =>
        `월즈와 MSI 우승은 값이 정해져 있습니다. 그 밖의 대회 우승은 ${perWeight} × 대회 가중치의 가치가 있으며, 대회 가중치는 그 대회의 경기가 LPS에서 갖는 중요도 가중치와 같습니다(월즈 = 1). 우승 아래의 각 라운드는 우승 가치의 정해진 비율을 받습니다: ${rounds
          .map(([label, pct]) => `${label} ${pct}%`)
          .join(", ")}. 팀 로스터의 모든 선수가 그 점수를 전부 받습니다.`,
      event: "대회",
      weight: "가중치",
      set: "고정",
      cupsRow: "국내 컵 대회 (국내 타이틀로 집계)",
      domTitle: "국내 리그",
      domBody: (champion: string, finalist: string, year: number) =>
        `스플릿 플레이오프 우승은 최대 ${champion}, 결승 패배는 최대 ${finalist}의 가치가 있으며, 여기에 리그 강도를 곱합니다. 리그 강도는 그해 그 리그의 Elo 레이팅을 가장 강한 리그의 레이팅으로 나눈 값입니다. ${year}년 기준 값:`,
      league: "리그",
      strength: "강도",
      titleCol: "우승",
      runnerUp: "준우승",
      awardsTitle: "개인 수상",
      awardsBody:
        "국제 대회 수상은 고정 점수입니다. 리그 수상(* 표시)은 우승과 마찬가지로 리그 강도를 곱하므로, 표시된 값은 받을 수 있는 최대치입니다.",
      award: "수상",
      points: "점수",
      repeatsTitle: "반복 달성",
      repeatsBody: (pct: number, example: string, steps: string[], total: ReactNode, naive: string): ReactNode => (
        <>
          같은 것을 다시 이루면 직전 가치의 {pct}%가 됩니다. 같은 대회의 같은 라운드끼리(모든 월즈 우승, 모든 MSI
          준우승), 리그 우승은 전부 하나로, 리그 준우승도 전부 하나로, 수상은 종류별로 묶어 적용합니다. 선수에게 가장
          가치 있는 하나는 항상 전부 인정됩니다. 예를 들어 {example}의 합은 {steps.join(" + ")} = {total}이며, 단순히
          더한 {naive}보다 작습니다.
        </>
      ),
    },
  },
};
