import time

import numpy as np
import pandas as pd

n = 5_000_000
cv = pd.DataFrame({
    "unique_id": np.random.randint(0, 1000, n),
    "abs_err": np.random.randn(n),
    "sq_err": np.random.randn(n),
    "smape": np.random.randn(n),
})

def agg_pandas(cv):
    grouped = cv.groupby("unique_id")
    res = grouped.agg(mae=("abs_err", "mean"), mse=("sq_err", "mean"), smape=("smape", "mean"))
    return res

def agg_cat(cv):
    cv["unique_id"] = cv["unique_id"].astype("category", copy=False)
    grouped = cv.groupby("unique_id", observed=True)
    res = grouped.agg(mae=("abs_err", "mean"), mse=("sq_err", "mean"), smape=("smape", "mean"))
    return res

t0 = time.time()
agg_pandas(cv.copy())
print("Pandas groupby:", time.time() - t0)

t0 = time.time()
agg_cat(cv.copy())
print("Cat groupby:", time.time() - t0)
