import pandas as pd, json

# Check yearly breakdown json (from career.py's _write_yearly_breakdown)
breakdown = json.load(open("player_yearly_breakdown.json"))
faker_bd = breakdown.get("Faker", breakdown.get("faker", {}))
print("Faker yearly breakdown (2013-2016):")
for yr in sorted(faker_bd.keys()):
    if int(yr) <= 2016:
        print(f"  {yr}: {faker_bd[yr]}")

# Check per-year workbook for 2013 to see Faker's playoff_pts there
try:
    df13 = pd.read_excel("player_ratings_2013.xlsx", sheet_name="MID")
    faker13 = df13[df13.iloc[:,1].astype(str).str.lower() == 'faker']
    cols = [c for c in df13.columns if any(k in str(c).lower() for k in ['playoff','regular','regular','tourn'])]
    print("\n2013 per-year workbook MID cols:", cols)
    if not faker13.empty:
        print("Faker 2013:", faker13[cols].to_string())
except Exception as e:
    print(f"Error reading 2013 xlsx: {e}")
