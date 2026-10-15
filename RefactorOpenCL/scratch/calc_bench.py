import time

import numpy as np
import pandas as pd

n = 5_000_000
cv = pd.DataFrame({
    "unique_id": np.random.randint(0, 1000, n),
    "y": np.random.randn(n),
    "lgbm": np.random.randn(n),
})

def calc_pandas(cv):
    err = (cv["y"] - cv["lgbm"]).abs()
    cv = cv.assign(
        abs_err=err,
        sq_err=err**2,
        smape=2 * err / (cv["y"].abs() + cv["lgbm"].abs()).clip(lower=1e-9),
    )
    return cv

def calc_numpy(cv):
    y = cv["y"].to_numpy()
    lgbm = cv["lgbm"].to_numpy()
    err = np.abs(y - lgbm)
    
    denom = np.abs(y) + np.abs(lgbm)
    np.clip(denom, 1e-9, None, out=denom)
    
    cv["abs_err"] = err
    cv["sq_err"] = err ** 2
    cv["smape"] = (2.0 * err) / denom
    return cv

t0 = time.time()
calc_pandas(cv.copy())
print("Pandas:", time.time() - t0)

t0 = time.time()
calc_numpy(cv.copy())
print("Numpy:", time.time() - t0)

