"""Probe Leaguepedia for pre-2015 OGN/Champions page structures."""
from __future__ import annotations
import logging
logging.basicConfig(level=logging.WARNING)
from lps.lp_client import LPClient

def main() -> None:
    lp = LPClient()
    out = open("G:/tmp_ogn_probe.txt", "w", encoding="utf-8")

    # 1. All Tournaments rows for LoL The Champions (OGN) -- see what Years and page names exist
    out.write("=== Tournaments: LoL The Champions ===\n")
    rows = lp.query(
        tables="Tournaments",
        fields="Year=year, Name=name, OverviewPage=page, League=league",
        where="League='LoL The Champions'",
        order_by="Year ASC, Name ASC",
    )
    for r in rows:
        out.write(f"  {r.get('year')} | {r.get('league')} | {r.get('name')} | {r.get('page')}\n")
    out.write(f"  Total: {len(rows)} rows\n\n")

    # 2. TournamentResults for those pages (to see what place/team data exists)
    out.write("=== TournamentResults: LoL The Champions ===\n")
    rows2 = lp.query(
        tables="TournamentResults=TR, Tournaments=T",
        join_on="TR.OverviewPage=T.OverviewPage",
        fields="T.Year=year, T.Name=name, TR.OverviewPage=page, TR.Team=team, TR.Place=place",
        where="T.League='LoL The Champions'",
        order_by="T.Year ASC",
    )
    for r in rows2:
        out.write(f"  {r.get('year')} | {r.get('name')} | {r.get('place')} | {r.get('team')} | {r.get('page')}\n")
    out.write(f"  Total: {len(rows2)} rows\n\n")

    # 3. Also check "LoL Champions Korea" early years
    out.write("=== Tournaments: LoL Champions Korea (early years) ===\n")
    rows3 = lp.query(
        tables="Tournaments",
        fields="Year=year, Name=name, OverviewPage=page, League=league",
        where="League='LoL Champions Korea' AND Year<=2016",
        order_by="Year ASC, Name ASC",
    )
    for r in rows3:
        out.write(f"  {r.get('year')} | {r.get('league')} | {r.get('name')} | {r.get('page')}\n")
    out.write(f"  Total: {len(rows3)} rows\n")

    out.close()
    print("Done -> G:/tmp_ogn_probe.txt")

if __name__ == "__main__":
    main()
