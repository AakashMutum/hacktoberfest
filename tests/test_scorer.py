import numpy as np

from backend.generator import FEATURES


def test_auc_on_held_out_days(engine):
    held_out = engine.stream_df
    assert set(held_out["typology"].unique()) <= {0, 1, 2, 3, 4}
    assert engine.base_scorer.auc(held_out) > 0.95


def test_contributions_explain_probability(engine):
    x = engine.stream_X[0]
    prob, factors, latency = engine.base_scorer.score_one(x)
    direct = float(engine.base_scorer.booster.inplace_predict(x.reshape(1, -1))[0])
    assert abs(prob - direct) < 1e-4
    assert all(f["feature"] in FEATURES and f["contribution"] > 0 for f in factors)


def test_latency_under_10ms(engine):
    lat = [engine.base_scorer.score_one(engine.stream_X[i])[2] for i in range(300)]
    assert np.percentile(lat, 50) < 10


def test_smurfing_mostly_missed_then_adapted(engine):
    before = engine._detect(engine.pool_eval, engine.base_scorer)["rate"]
    assert before < 0.5
    result = engine.adapt()
    assert result["after"]["rate"] > before
    assert result["train_seconds"] < 10
    engine.reset()
