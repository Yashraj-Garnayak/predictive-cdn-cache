"""Popularity forecaster."""
from __future__ import annotations
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from .features import FEATURES, build_features, training_set


class PopularityModel:
    def __init__(self, random_state: int = 0):
        self.model = HistGradientBoostingRegressor(max_iter=200, random_state=random_state)
        self.fitted = False

    def fit(self, counts: pd.DataFrame, hours: range) -> "PopularityModel":
        X, y = training_set(counts, hours)
        self.model.fit(X[FEATURES], y)
        self.fitted = True
        return self

    def predict(self, counts: pd.DataFrame, hour: int) -> pd.Series:
        """Predicted request count at `hour` for every candidate video (see build_features)."""
        if not self.fitted:
            raise RuntimeError("model not fitted")
        f = build_features(counts, hour)
        if f.empty:
            return pd.Series(dtype=float)
        return pd.Series(self.model.predict(f[FEATURES]), index=f.index)

    def top_k(self, counts: pd.DataFrame, hour: int, k: int) -> list[int]:
        return [int(v) for v in self.predict(counts, hour).nlargest(k).index]
