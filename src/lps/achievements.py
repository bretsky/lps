"""
CLR resume bonuses (Phase 2): turn info/achievements.csv + info/player_awards.csv into per-player
IntlBonus / TitleBonus / AwardBonus.

Scoring:
  - IntlBonus  = flat points per (event x placement bucket) at Worlds/MSI (a global title is a
                 global title regardless of region), summed over a player's career.
  - TitleBonus = domestic split-playoff titles/finals, each scaled by that region's strength
                 (regionElo / strongest-region-Elo that year), so an LCK/LPL title outweighs a
                 weak-region one. Unrated leagues (no Elo) contribute 0.
  - AwardBonus = small hand-curated regional-MVP / All-Pro / Finals-MVP tiebreaker.

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
from .scoring import load_league_elos

logger = logging.getLogger(__name__)

# Leaguepedia League (full name) -> our rated league code. Only leagues that are ever rated need
# an entry; anything unmapped (or mapped to an unrated code in a given year) scores 0 via Elo.
# (Refined against the distinct-league list the fetcher logs.)
FULL2CODE: dict[str, str] = {
    # Korea
    "LoL Champions Korea": "LCK",
    "League of Legends Champions Korea": "LCK",
    "Champions Korea": "LCK",
    "LoL The Champions": "OGN",                          # 2013-2014 Korea
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
    # International: flat points per (event, bucket).
    intl_points: dict[tuple[str, str], float] = field(default_factory=lambda: {
        ("WLDs", "champion"): 6.0, ("WLDs", "finalist"): 3.0, ("WLDs", "semifinalist"): 1.5,
        ("WLDs", "quarterfinalist"): 0.75, ("WLDs", "group"): 0.25,
        ("MSI", "champion"): 3.0, ("MSI", "finalist"): 1.5, ("MSI", "semifinalist"): 0.75,
        ("MSI", "quarterfinalist"): 0.4, ("MSI", "group"): 0.1,
    })
    # Domestic split podium base points (each multiplied by regionElo/topElo that year).
    domestic_champion: float = 1.5
    domestic_finalist: float = 0.5
    # Awards (small tiebreaker).
    award_points: dict[str, float] = field(default_factory=lambda: {
        "worlds_finals_mvp": 2.0, "msi_finals_mvp": 1.0, "regional_mvp": 1.0,
        "all_pro_1": 0.75, "all_pro_2": 0.4, "all_pro_3": 0.2,
    })
    # Overall resume-bonus weight into CLR. Kept < 1 so the resume BOOSTS individual performance
    # rather than swamping it (raw bonus points for the most-decorated players rival the entire
    # base CLR); also, team achievements credit every player on a winning roster equally, so a
    # heavy weight would over-reward dynasty role-players. Prime calibration target.
    w_bonus: float = 0.35


_BONUS_COLS = ["intl_bonus", "title_bonus", "award_bonus"]


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
        logger.warning(f"[achievements] {ACHIEVEMENTS_CSV} missing -- run lps.fetch_achievements")
        return pd.DataFrame()
    return pd.read_csv(ACHIEVEMENTS_CSV)


def load_awards() -> pd.DataFrame:
    if not AWARDS_CSV.exists():
        return pd.DataFrame(columns=["year", "playername", "award"])
    return pd.read_csv(AWARDS_CSV)


def _empty_bonus() -> pd.DataFrame:
    return pd.DataFrame(columns=["playername", "position", "year", *_BONUS_COLS])


def score_bonuses(roster: pd.DataFrame, cfg: BonusConfig | None = None) -> pd.DataFrame:
    """Given our per-(player, year) roster [playername, year, position], return a long
    per-(playername, position, year) bonus frame with intl_bonus / title_bonus / award_bonus.

    Credit is by ROSTER: each achievement row carries the team's players (Leaguepedia handles);
    we credit every player who is in OUR universe that year (matched case-insensitively) and
    attribute it to the lane they played that year. No team-name matching -- org renames between
    Leaguepedia and Oracle are irrelevant. career.py aggregates to per-player / per-player-lane."""
    cfg = cfg or BonusConfig()
    ach = load_achievements()
    if ach.empty or roster.empty or "players" not in ach.columns:
        return _empty_bonus()

    # Our universe: (name_lower, year) -> (canonical name, lane) for the season the player played.
    r = roster[["playername", "year", "position"]].dropna(subset=["playername", "year"]).copy()
    r["year"] = r["year"].astype(int)
    r["_nlc"] = r["playername"].astype(str).str.lower()
    r = r.drop_duplicates(["_nlc", "year"]).set_index(["_nlc", "year"])
    pos, cname = r["position"], r["playername"]

    ach = ach.copy()
    ach["year"] = pd.to_numeric(ach["year"], errors="coerce")
    ach = ach[ach["year"].notna() & ach["players"].notna() & (ach["players"].astype(str) != "")]
    ach["year"] = ach["year"].astype(int)

    # Points per achievement row (before crediting players).
    scale = _region_scale(sorted(r.index.get_level_values(1).unique()))
    code = ach["league_full"].map(FULL2CODE)
    dom_base = ach["bucket"].map({"champion": cfg.domestic_champion,
                                  "finalist": cfg.domestic_finalist}).fillna(0.0)
    dom_scale = np.array([scale.get((y, c), 0.0) for y, c in zip(ach["year"], code)])
    intl_pts = np.array([cfg.intl_points.get((e, b), 0.0)
                         for e, b in zip(ach["event"], ach["bucket"])])
    ach["pts"] = np.where(ach["category"] == "intl", intl_pts, dom_base.to_numpy() * dom_scale)
    ach["kind"] = np.where(ach["category"] == "intl", "intl_bonus", "title_bonus")
    ach = ach[ach["pts"] > 0]

    # Explode rosters -> one row per (achievement, player), keep only players in our universe.
    ex = ach.assign(_nlc=ach["players"].astype(str).str.split(";")).explode("_nlc")
    ex["_nlc"] = ex["_nlc"].str.strip().str.lower()
    ex = ex[ex["_nlc"] != ""]
    ex = ex.join(pos.rename("position"), on=["_nlc", "year"], how="inner")
    ex = ex.join(cname.rename("cname"), on=["_nlc", "year"])
    parts = []
    if len(ex):
        g = (ex.groupby(["cname", "position", "year", "kind"])["pts"].sum()
             .unstack("kind", fill_value=0.0).reset_index()
             .rename(columns={"cname": "playername"}))
        parts.append(g)

    # Awards: matched by (name, year), attributed to that year's lane.
    aw = load_awards()
    if len(aw):
        aw = aw.copy()
        aw["year"] = pd.to_numeric(aw["year"], errors="coerce")
        aw = aw[aw["year"].notna()]
        aw["year"] = aw["year"].astype(int)
        aw["_nlc"] = aw["playername"].astype(str).str.lower()
        aw["award_bonus"] = aw["award"].map(cfg.award_points).fillna(0.0)
        aw = aw[aw["award_bonus"] > 0]
        aw = aw.join(pos.rename("position"), on=["_nlc", "year"], how="inner")
        aw = aw.join(cname.rename("cname"), on=["_nlc", "year"])
        if len(aw):
            ga = (aw.groupby(["cname", "position", "year"])["award_bonus"].sum().reset_index()
                  .rename(columns={"cname": "playername"}))
            parts.append(ga)

    if not parts:
        return _empty_bonus()
    out = parts[0]
    for p in parts[1:]:
        out = out.merge(p, on=["playername", "position", "year"], how="outer")
    for c in _BONUS_COLS:
        if c not in out.columns:
            out[c] = 0.0
    out[_BONUS_COLS] = out[_BONUS_COLS].fillna(0.0)
    return out[["playername", "position", "year", *_BONUS_COLS]]
