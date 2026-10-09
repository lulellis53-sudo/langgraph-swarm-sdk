import time

import numpy as np
import pandas as pd


def generate_df(n):
    unique_ids = np.repeat(np.arange(n // 100), 100)
    ds = np.tile(pd.date_range("2020-01-01", periods=100), n // 100)
    y = np.random.randn(n)
    return pd.DataFrame({"unique_id": unique_ids, "ds": ds, "y": y})

df = generate_df(1_000_000)

def validate_old(df):
    if df["y"].isna().any():
        pass
    if df.duplicated(["unique_id", "ds"]).any():
        pass
    shortest = int(df.groupby("unique_id", observed=True).size().min())

def validate_new(df):
    if df["y"].hasnans:
        pass
    if df.duplicated(["unique_id", "ds"]).any():
        pass
    shortest = df["unique_id"].value_counts(sort=False).min()

t0 = time.time()
validate_old(df)
print("Old:", time.time() - t0)

t0 = time.time()
validate_new(df)
print("New:", time.time() - t0)
