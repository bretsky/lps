from lps.io_oracle import load_oracle_years

df = load_oracle_years(range(2014, 2026))
print(df.shape)
print(df.columns)
print(df["position"].value_counts().head())
