import pandas as pd

for tag, path in [("2013 (unmerged)", "data/cache/lp_features_2013.pkl"),
                  ("2014 (merged)",   "data/cache/lp_features_2014_merged.pkl"),
                  ("2014 (unmerged)", "data/cache/lp_features_2014.pkl")]:
    df = pd.read_pickle(path)
    counts = df["phase"].value_counts().to_dict()
    print(f"{tag}: {counts}")
