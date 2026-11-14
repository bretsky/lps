from __future__ import annotations
import logging
logging.basicConfig(level=logging.WARNING)
from lps.io_oracle import load_oracle_year

def main() -> None:
    df = load_oracle_year(2014)
    out = open("G:/tmp_2014.txt", "w", encoding="utf-8")
    player_df = df[df["position"] != "team"]
    out.write(f"Total rows: {len(df)}\n")
    out.write(f"Player rows: {len(player_df)}\n")
    if "league" in player_df.columns:
        out.write(f"Leagues: {player_df['league'].value_counts().to_dict()}\n")
    out.write(f"Players named faker: {player_df['playername'].str.lower().eq('faker').sum()}\n")
    # Find SKT players
    skt = player_df[player_df["teamname"].str.contains("SK Telecom|SKT", na=False)]
    out.write(f"SKT rows: {len(skt)}\n")
    out.write(f"SKT players: {skt['playername'].unique().tolist()}\n")
    if len(skt):
        out.write(skt[["date","league","playername","result"]].to_string() + "\n")
    out.close()
    print("done")

if __name__ == "__main__":
    main()
