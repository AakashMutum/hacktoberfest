"""XGBoost risk scorer with per-transaction factor attributions via pred_contribs."""
from __future__ import annotations

import math
import time

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.metrics import roc_auc_score

from .generator import FEATURE_LABELS, FEATURES

PARAMS = {
    "objective": "binary:logistic",
    "eval_metric": "auc",
    "max_depth": 6,
    "eta": 0.12,
    "subsample": 0.9,
    "colsample_bytree": 0.9,
    "min_child_weight": 2,
    "tree_method": "hist",
    "nthread": 4,
}


class Scorer:
    def __init__(self, booster: xgb.Booster, version: int = 1, trained_on: int = 0, train_seconds: float = 0.0):
        self.booster = booster
        # Single-row scoring is fastest without a thread pool.
        self.booster.set_param({"nthread": 1})
        self.version = version
        self.trained_on = trained_on
        self.train_seconds = train_seconds

    @classmethod
    def train(cls, df: pd.DataFrame, rounds: int = 220, seed: int = 42, version: int = 1) -> "Scorer":
        t0 = time.perf_counter()
        params = dict(PARAMS, seed=seed)
        dtrain = xgb.DMatrix(df[FEATURES].to_numpy(dtype=np.float32), label=df["label"].to_numpy(), feature_names=FEATURES)
        booster = xgb.train(params, dtrain, num_boost_round=rounds)
        return cls(booster, version=version, trained_on=len(df), train_seconds=time.perf_counter() - t0)

    def predict(self, df: pd.DataFrame) -> np.ndarray:
        return self.booster.inplace_predict(df[FEATURES].to_numpy(dtype=np.float32))

    def auc(self, df: pd.DataFrame) -> float:
        return float(roc_auc_score(df["label"], self.predict(df)))

    def score_one(self, x: np.ndarray, top_k: int = 5):
        """Score a single feature vector. Returns (probability, factors, latency_ms)."""
        t0 = time.perf_counter()
        dm = xgb.DMatrix(x.reshape(1, -1).astype(np.float32), feature_names=FEATURES, nthread=1)
        contribs = self.booster.predict(dm, pred_contribs=True)[0]
        prob = 1.0 / (1.0 + math.exp(-float(contribs.sum())))
        latency = (time.perf_counter() - t0) * 1000
        order = np.argsort(-contribs[:-1])
        factors = []
        for i in order[:top_k]:
            c = float(contribs[i])
            if c <= 0:
                break
            factors.append({"feature": FEATURES[i], "label": FEATURE_LABELS[FEATURES[i]],
                            "value": float(x[i]), "contribution": round(c, 4)})
        return prob, factors, latency

    def save(self, path: str) -> None:
        self.booster.save_model(path)

    @classmethod
    def load(cls, path: str) -> "Scorer":
        b = xgb.Booster()
        b.load_model(path)
        return cls(b)
