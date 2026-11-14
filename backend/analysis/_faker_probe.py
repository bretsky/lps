"""Investigate Faker 2018 LPS."""
from __future__ import annotations
import logging
logging.basicConfig(level=logging.WARNING)
from lps.io_oracle import load_oracle_year
import pandas as pd

def main() -> None:
    out = open("G:/tmp_faker_probe.txt", "w", encoding="utf-8")

    for yr in [2014, 2017, 2018]:
        ydf = load_oracle_year(yr)
        faker = ydf[(ydf["playername"].str.lower() == "faker") & (ydf["position"] != "team")]
        out.write(f"\n=== {yr} === ({len(faker)} games)\n")
        if "datacompleteness" in faker.columns:
            out.write(f"Completeness: {faker['datacompleteness'].value_counts().to_dict()}\n")
        if len(faker):
            cols = [c for c in ["date","league","teamname","result","kills","deaths","assists","damagetochampions","cspm","earned gpm"] if c in faker.columns]
            out.write(faker[cols].to_string() + "\n")
            out.write(f"\nMeans:\n{faker[['kills','deaths','assists']].mean().to_string()}\n")
            if "result" in faker.columns:
                out.write(f"Win rate: {faker['result'].mean():.3f}\n")

    out.close()
    print("Done, see G:/tmp_faker_probe.txt")

if __name__ == "__main__":
    main()
