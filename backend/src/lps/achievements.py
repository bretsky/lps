"""
CLR resume bonuses (Phase 2): turn info/achievements.csv + info/player_awards.csv into per-player
IntlBonus / TitleBonus / AwardBonus.

Scoring (event coverage aligned with the LPS tournament universe -- season._viewership_weights):
  - IntlBonus  = flat points per (event x placement bucket) at every CROSS-REGION event LPS
                 scores (Worlds, MSI, EWC, First Stand, MSC, LTA, Rift Rivals, ASI, IWCI, IEM,
                 IPL, MLG, DreamHack, OGN 2012). Champion points are DERIVED from the event's LPS
                 weight (Worlds/MSI anchored), so a title's resume value tracks its on-rift weight.
  - TitleBonus = domestic split-playoff titles/finals (region-Elo scaled) PLUS domestic cups
                 (KeSPA / Demacia, weight-derived flat), summed over a player's career.
  - AwardBonus = small individual-award tiebreaker (regional MVP / All-Pro / Finals MVP at any
                 event), auto-pulled from Leaguepedia's IndividualAchievements table; domestic
                 awards are region-Elo scaled, the global/intl-event Finals MVPs are flat.

Credit is assigned by joining the team-level achievement rows to OUR roster (per player-year:
team + home league + lane), so only players in our scored universe are credited, and a title is
attributed to the lane the player actually played that year. Team names are matched on a
normalized key (lowercase, alphanumerics only).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .fetch_achievements import ACHIEVEMENTS_CSV, AWARDS_CSV
from .player_identity import resolve_label
from .scoring import load_league_elos
from .season import _viewership_weights

logger = logging.getLogger(__name__)

# Leaguepedia League (full name) -> our rated league code. Only leagues that are ever rated need
# an entry; anything unmapped (or mapped to an unrated code in a given year) scores 0 via Elo.
# (Refined against the distinct-league list the fetcher logs.)
FULL2CODE: dict[str, str] = {
    # Korea
    "LoL Champions Korea": "LCK",
    "League of Legends Champions Korea": "LCK",
    "Champions Korea": "LCK",
    "LoL The Champions": "OGN",  # 2013-2014 Korea
    # China
    "Tencent LoL Pro League": "LPL",
    "LoL Pro League": "LPL",
    # Europe (EU LCS 2013-2018 -> LEC 2019+)
    "Europe League Championship Series": "EU LCS",
    "League of Legends European Championship": "LEC",
    "LoL EMEA Championship": "LEC",
    "League of Legends EMEA Championship": "LEC",
    # North America (NA LCS 2013-2018 -> LCS 2019+)
    "North America League Championship Series": "NA LCS",
    "League of Legends Championship Series": "LCS",
    # Other rated majors / regions (unrated years score 0 via missing Elo)
    "LoL Master Series": "LMS",
    "Pacific Championship Series": "PCS",
    "League of Legends Championship Pacific": "LCP",
    "Vietnam Championship Series": "VCS",
    "Circuit Brazilian League of Legends": "CBLOL",
    "Liga Latinoamerica": "LLA",
    "LoL Japan League": "LJL",
    "Turkish Championship League": "TCL",
    "League of Legends Championship of The Americas North": "LTA N",
    "League of Legends Championship of The Americas South": "LTA S",
}


@dataclass
class BonusConfig:
    """Resume-bonus weights (provisional -- pending calibration against the consensus list)."""

    # TOURNAMENTS (cross-region + domestic cups): champion points are DERIVED from the LPS
    # tournament weight (season._viewership_weights, Worlds=1.0) so the resume's event coverage +
    # importance stays locked to the on-rift scoring. champion_pts(label) = anchor if the event has
    # one, else champ_per_weight * LPS_weight[label]; then scaled down the bracket by intl_bucket.
    # Anchors keep Worlds/MSI at their tuned prestige premium; champ_per_weight=4.6 puts EWC/First
    # Stand ~2.0 (below MSI), MSC ~1.4, KeSPA ~0.6, Demacia ~0.4 -- matching their LPS weights.
    intl_champion_anchors: dict[str, float] = field(
        default_factory=lambda: {"WLDs": 6.0, "MSI": 3.0}
    )
    champ_per_weight: float = 3.5  # tuned to the consensus surveys
    intl_bucket: dict[str, float] = field(
        default_factory=lambda: {
            "champion": 1.0,
            "finalist": 0.5,
            "semifinalist": 0.25,
            "quarterfinalist": 0.125,
            "group": 0.04,
        }
    )
    # Domestic SPLIT podium base points (each multiplied by regionElo/topElo that year). Cups
    # (KeSPA/Demacia) instead use the weight-derived tournament points above (flat, category-tagged).
    domestic_champion: float = 1.5
    domestic_finalist: float = 0.5
    # Awards (small tiebreaker; auto-pulled from Leaguepedia IndividualAchievements). Domestic
    # awards are region-Elo scaled like titles; the intl Finals MVPs are flat (see FLAT_AWARDS).
    award_points: dict[str, float] = field(
        default_factory=lambda: {
            # International (flat): finals MVP, tournament MVP, and All-Pro at Worlds / MSI.
            "worlds_finals_mvp": 2.0,
            "msi_finals_mvp": 1.0,
            "worlds_mvp": 2.0,
            "msi_mvp": 1.0,
            "worlds_all_pro": 1.0,
            "msi_all_pro": 0.5,
            # Other intl events (EWC/First Stand/... ) -- flat, a tier below MSI honors.
            "intl_finals_mvp": 0.75,
            "intl_mvp": 0.75,
            "intl_all_pro": 0.4,
            # Domestic (region-Elo scaled): finals/season MVP + All-Pro tiers.
            "domestic_finals_mvp": 0.5,
            "regional_mvp": 1.0,
            "all_pro_1": 0.6,
            "all_pro_2": 0.35,
            "all_pro_3": 0.15,
        }
    )
    # Family weight on ALL individual awards: multiplies award_bonus (the MVP/All-Pro family) before
    # w_bonus, so awards can be scaled up/down RELATIVE to team titles/placements without editing
    # each token. The award analogue of champ_per_weight (tournaments). 1.0 = award_points as-is.
    award_weight: float = 0.75
    # Overall resume-bonus weight into CLR. Kept < 1 so the resume BOOSTS individual performance
    # rather than swamping it (raw bonus points for the most-decorated players rival the entire
    # base CLR); also, team achievements credit every player on a winning roster equally, so a
    # heavy weight would over-reward dynasty role-players. Prime calibration target. Tuned to the
    # per-lane consensus GOAT lists: the résumé tracks consensus strongly, so 1.0 (balanced) --
    # titles/placements matter, but on-rift value (CareerVal+PaceVal+PeakVal) still leads CLR.
    w_bonus: float = 0.5
    # DIMINISHING RETURNS on winning the SAME kind of thing repeatedly. Within each player, like
    # achievements are grouped (intl by event+bucket, domestic by bucket, awards by token), ordered
    # by value (best kept whole), and the k-th (1-indexed) is scaled by repeat_decay**(k-1). So a
    # 6-time Worlds winner's titles are worth 1 + d + d^2 + ... rather than 6x. 1.0 = OFF (every
    # win full). Rewards breadth of résumé over farming one dynasty. Tuned to the consensus
    # surveys: 0.6 (a moderate taper -- repeats still count, just noticeably less each time).
    repeat_decay: float = 0.8


_BONUS_COLS = ["intl_bonus", "title_bonus", "award_bonus"]
# Awards scored flat (global-stage individual honors); all others region-Elo scaled.
FLAT_AWARDS = {
    "worlds_finals_mvp",
    "msi_finals_mvp",
    "worlds_mvp",
    "msi_mvp",
    "worlds_all_pro",
    "msi_all_pro",
    "intl_finals_mvp",
    "intl_mvp",
    "intl_all_pro",
}

# Resume BREAKDOWN categories: a partition of every scored resume achievement into 14 buckets so a
# per-player count + summed points can be shown for each, and the points reconcile exactly to the
# three headline bonuses (intl/title/award) and thus to Resume. Order is display order.
#   Worlds and MSI each split by placement (title/finals/semis); other intl similarly;
#   dom_champ/dom_final = domestic splits; dom_cup = KeSPA/Demacia; mvp/allpro = award families.
_RB_CATS = [
    "wlds_title",       # Worlds champion
    "wlds_final",       # Worlds finalist
    "wlds_semi",        # Worlds semifinalist or quarterfinalist
    "msi_title",        # MSI champion
    "msi_final",        # MSI finalist
    "msi_semi",         # MSI semifinalist
    "othr_intl_champ",  # Other intl champion (IEM, EWC, MSC, Rift Rivals…)
    "othr_intl_final",  # Other intl finalist
    "othr_intl_semi",   # Other intl semifinalist or quarterfinalist
    "dom_champ",
    "dom_final",
    "dom_cup",
    "mvp",
    "allpro",
]
_RB_N = [f"rb_{c}_n" for c in _RB_CATS]  # per-category achievement COUNTS
_RB_PTS = [f"rb_{c}_pts" for c in _RB_CATS]  # per-category summed POINTS
RESUME_BREAKDOWN_COLS = _RB_N + _RB_PTS
# The three headline bonuses, each as the sum of its member categories' points (reconciliation).
_RB_TO_BONUS = {
    "intl_bonus": [
        "rb_wlds_title_pts",
        "rb_wlds_final_pts",
        "rb_wlds_semi_pts",
        "rb_msi_title_pts",
        "rb_msi_final_pts",
        "rb_msi_semi_pts",
        "rb_othr_intl_champ_pts",
        "rb_othr_intl_final_pts",
        "rb_othr_intl_semi_pts",
    ],
    "title_bonus": ["rb_dom_champ_pts", "rb_dom_final_pts", "rb_dom_cup_pts"],
    "award_bonus": ["rb_mvp_pts", "rb_allpro_pts"],
}
# Award tokens that count as an "MVP-type" honor; every other scored award is an All-Pro-type.
_MVP_AWARDS = {
    "worlds_finals_mvp",
    "msi_finals_mvp",
    "worlds_mvp",
    "msi_mvp",
    "intl_finals_mvp",
    "intl_mvp",
    "domestic_finals_mvp",
    "regional_mvp",
}


def _ach_category(category: str, event: str, bucket: str) -> str:
    """Map a scored achievement row to one of the 14 resume-breakdown buckets."""
    if category == "domestic_cup":
        return "dom_cup"
    if category == "intl":
        if event == "WLDs":
            if bucket == "champion":
                return "wlds_title"
            if bucket == "finalist":
                return "wlds_final"
            return "wlds_semi"  # semifinalist, quarterfinalist
        if event == "MSI":
            if bucket == "champion":
                return "msi_title"
            if bucket == "finalist":
                return "msi_final"
            return "msi_semi"  # semifinalist
        # Other international events (EWC, First Stand, MSC, LTA, Rift Rivals, ASI, …)
        if bucket == "champion":
            return "othr_intl_champ"
        if bucket == "finalist":
            return "othr_intl_final"
        return "othr_intl_semi"  # semifinalist, quarterfinalist
    return "dom_champ" if bucket == "champion" else "dom_final"


def _apply_repeat_decay(df: pd.DataFrame, decay: float) -> pd.DataFrame:
    """Diminishing returns for repeated like achievements. `df` is one row per credited
    (achievement, player) with `pts`, a player key `cname`, and a decay-group key `_dkey`.
    Within each (cname, _dkey) the rows are ordered by pts DESC (so the player's best instance
    keeps full value) and the k-th (0-indexed rank) is scaled by decay**rank. Returns `df` with
    `pts` decayed; a no-op when decay >= 1."""
    if decay >= 1.0 or df.empty:
        return df
    df = df.sort_values("pts", ascending=False, kind="stable")
    rank = df.groupby(["cname", "_dkey"]).cumcount()
    return df.assign(pts=df["pts"] * (decay**rank))


def _pivot_cats(ex: pd.DataFrame) -> pd.DataFrame:
    """Exploded (row-per-credited-player) frame with a `cat` + `pts` -> wide per-category count
    and points, keyed by (playername, position, year). `ex` must have a `cname` player column.
    """
    keys = ["cname", "position", "year"]
    cnt = ex.groupby(keys + ["cat"]).size().unstack("cat", fill_value=0)
    cnt.columns = [f"rb_{c}_n" for c in cnt.columns]
    pts = ex.groupby(keys + ["cat"])["pts"].sum().unstack("cat", fill_value=0.0)
    pts.columns = [f"rb_{c}_pts" for c in pts.columns]
    return (
        cnt.join(pts, how="outer").reset_index().rename(columns={"cname": "playername"})
    )


def _region_scale(years: list[int]) -> dict[tuple[int, str], float]:
    """(year, code) -> regionElo / strongest-region-Elo that year (0 if unrated)."""
    out: dict[tuple[int, str], float] = {}
    for y in years:
        elos = load_league_elos(y)
        if not elos:
            continue
        top = max(elos.values())
        for code, elo in elos.items():
            out[(y, code)] = elo / top if top else 0.0
    return out


def load_achievements() -> pd.DataFrame:
    if not ACHIEVEMENTS_CSV.exists():
        logger.warning(
            f"[achievements] {ACHIEVEMENTS_CSV} missing -- run lps.fetch_achievements"
        )
        return pd.DataFrame()
    return pd.read_csv(ACHIEVEMENTS_CSV)


def load_awards() -> pd.DataFrame:
    if not AWARDS_CSV.exists():
        return pd.DataFrame(columns=["year", "playername", "award"])
    return pd.read_csv(AWARDS_CSV)


def _empty_bonus() -> pd.DataFrame:
    return pd.DataFrame(
        columns=["playername", "position", "year", *_BONUS_COLS, *RESUME_BREAKDOWN_COLS]
    )


def score_bonuses(roster: pd.DataFrame, cfg: BonusConfig | None = None) -> pd.DataFrame:
    """Given our per-(player, year) roster [playername, year, position], return a long
    per-(playername, position, year) bonus frame with intl_bonus / title_bonus / award_bonus.

    Credit is by ROSTER: each achievement row carries the team's players (Leaguepedia handles);
    we credit every player who is in OUR universe that year (matched case-insensitively) and
    attribute it to the lane they played that year. No team-name matching -- org renames between
    Leaguepedia and Oracle are irrelevant. career.py aggregates to per-player / per-player-lane.
    """
    cfg = cfg or BonusConfig()
    ach = load_achievements()
    if ach.empty or roster.empty or "players" not in ach.columns:
        return _empty_bonus()

    # Our universe: (name_lower, year) -> (canonical name, lane) for the season the player played.
    r = (
        roster[["playername", "year", "position"]]
        .dropna(subset=["playername", "year"])
        .copy()
    )
    r["year"] = r["year"].astype(int)
    r["_nlc"] = r["playername"].astype(str).str.lower()
    r = r.drop_duplicates(["_nlc", "year"]).set_index(["_nlc", "year"])
    pos, cname = r["position"], r["playername"]

    ach = ach.copy()
    ach["year"] = pd.to_numeric(ach["year"], errors="coerce")
    ach = ach[
        ach["year"].notna()
        & ach["players"].notna()
        & (ach["players"].astype(str) != "")
    ]
    ach["year"] = ach["year"].astype(int)

    # Points per achievement row (before crediting players) + its breakdown category.
    scale = _region_scale(sorted(r.index.get_level_values(1).unique()))
    code = ach["league_full"].map(FULL2CODE)
    # Domestic SPLIT titles: base podium points x region-Elo strength that year.
    dom_base = (
        ach["bucket"]
        .map({"champion": cfg.domestic_champion, "finalist": cfg.domestic_finalist})
        .fillna(0.0)
    )
    dom_scale = np.array([scale.get((y, c), 0.0) for y, c in zip(ach["year"], code)])
    dom_pts = dom_base.to_numpy() * dom_scale
    # TOURNAMENTS (intl cross-region + domestic cups): champion points from the LPS tournament
    # weight (anchored for Worlds/MSI), scaled down the bracket by the bucket ladder.
    tw = _viewership_weights()

    def _champ(label: str) -> float:
        return cfg.intl_champion_anchors.get(
            label, cfg.champ_per_weight * tw.get(label, 0.0)
        )

    tour_pts = np.array(
        [
            _champ(e) * cfg.intl_bucket.get(b, 0.0)
            for e, b in zip(ach["event"], ach["bucket"])
        ]
    )
    is_split = (
        ach["category"].to_numpy() == "domestic"
    )  # intl + domestic_cup use tour_pts
    ach["pts"] = np.where(is_split, dom_pts, tour_pts)
    ach["cat"] = [
        _ach_category(cat, e, b)
        for cat, e, b in zip(ach["category"], ach["event"], ach["bucket"])
    ]
    ach = ach[ach["pts"] > 0]

    # Explode rosters -> one row per (achievement, player), keep only players in our universe.
    # Bridge each Leaguepedia handle to its canonical identity label using the achievement's
    # region, so a title lands on the right same-handle player (e.g. the LPL vs VCS "Knight").
    ex = ach.assign(_hraw=ach["players"].astype(str).str.split(";")).explode("_hraw")
    ex["_hraw"] = ex["_hraw"].str.strip()
    ex = ex[ex["_hraw"] != ""]
    _ex_reg = ex["league_full"].map(FULL2CODE)
    _ex_team = ex["team"] if "team" in ex.columns else pd.Series([None] * len(ex), index=ex.index)
    ex["_nlc"] = [
        resolve_label(h, r, t, y)
        for h, r, t, y in zip(ex["_hraw"], _ex_reg, _ex_team, ex["year"])
    ]
    ex["_nlc"] = ex["_nlc"].astype(str).str.lower()
    ex = ex.join(pos.rename("position"), on=["_nlc", "year"], how="inner")
    ex = ex.join(cname.rename("cname"), on=["_nlc", "year"])
    parts = []
    raw_pts = dec_pts = (
        0.0  # undecayed vs decayed résumé totals (for the w_bonus recompense)
    )
    if len(ex):
        # Decay group: repeated same tournament at the SAME round (intl + cups by event+bucket), or
        # repeated domestic split champ/finalist (by bucket).
        is_tour = ex["category"].isin(["intl", "domestic_cup"]).to_numpy()
        ex["_dkey"] = np.where(
            is_tour,
            "t:" + ex["event"].astype(str) + ":" + ex["bucket"].astype(str),
            "d:" + ex["bucket"].astype(str),
        )
        raw_pts += ex["pts"].sum()
        ex = _apply_repeat_decay(ex, cfg.repeat_decay)
        dec_pts += ex["pts"].sum()
        parts.append(_pivot_cats(ex))

    # Awards: matched by (name, year), attributed to that year's lane. Intl Finals MVPs are flat;
    # domestic awards (season/finals MVP, All-Pro) are region-Elo scaled like titles.
    aw = load_awards()
    if len(aw):
        aw = aw.copy()
        aw["year"] = pd.to_numeric(aw["year"], errors="coerce")
        aw = aw[aw["year"].notna()]
        aw["year"] = aw["year"].astype(int)
        base = aw["award"].map(cfg.award_points).fillna(0.0).to_numpy()
        code = (
            aw["league_full"].map(FULL2CODE)
            if "league_full" in aw.columns
            else pd.Series([None] * len(aw), index=aw.index)
        )
        # Bridge each award's Leaguepedia handle to its canonical identity label (by region).
        aw["_nlc"] = [resolve_label(h, r) for h, r in zip(aw["playername"], code)]
        aw["_nlc"] = aw["_nlc"].astype(str).str.lower()
        sc = np.array(
            [
                1.0 if a in FLAT_AWARDS else scale.get((y, c), 0.0)
                for a, y, c in zip(aw["award"], aw["year"], code)
            ]
        )
        aw["pts"] = (
            base * sc * cfg.award_weight
        )  # family weight on all individual awards
        aw["cat"] = np.where(aw["award"].isin(_MVP_AWARDS), "mvp", "allpro")
        aw = aw[aw["pts"] > 0]
        aw = aw.join(pos.rename("position"), on=["_nlc", "year"], how="inner")
        aw = aw.join(cname.rename("cname"), on=["_nlc", "year"])
        if len(aw):
            aw["_dkey"] = "a:" + aw["award"].astype(str)  # repeated same award token
            raw_pts += aw["pts"].sum()
            aw = _apply_repeat_decay(aw, cfg.repeat_decay)
            dec_pts += aw["pts"].sum()
            parts.append(_pivot_cats(aw))

    if not parts:
        return _empty_bonus()
    out = parts[0]
    for p in parts[1:]:  # achievement + award cats are disjoint
        out = out.merge(p, on=["playername", "position", "year"], how="outer")
    for c in RESUME_BREAKDOWN_COLS:
        if c not in out.columns:
            out[c] = 0.0
    out[RESUME_BREAKDOWN_COLS] = out[RESUME_BREAKDOWN_COLS].fillna(0.0)
    # Headline bonuses = sum of member categories' points (so the breakdown reconciles to Resume).
    for bonus, cols in _RB_TO_BONUS.items():
        out[bonus] = out[cols].sum(axis=1)
    out = out[["playername", "position", "year", *_BONUS_COLS, *RESUME_BREAKDOWN_COLS]]
    # Fraction of undecayed résumé points that survived the diminishing-returns decay (1.0 if off);
    # career.py reads this to recompense w_bonus for the shrinkage. Stored on .attrs.
    out.attrs["resume_shrink"] = (dec_pts / raw_pts) if raw_pts > 0 else 1.0
    return out
