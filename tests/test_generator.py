import numpy as np

from backend.generator import FEATURES, generate


def test_generator_is_deterministic_and_shaped():
    acc_a, main_a, pool_a = generate(seed=7, total=20_000)
    acc_b, main_b, pool_b = generate(seed=7, total=20_000)
    assert main_a[FEATURES].equals(main_b[FEATURES])
    assert 18_000 <= len(main_a) <= 21_000
    assert main_a["ts"].is_monotonic_increasing
    assert not main_a[FEATURES].isna().any().any()


def test_typologies_present_and_smurfing_held_out(engine):
    main, pool = engine.main, engine.pool
    assert set(main["typology"].unique()) == {0, 1, 2, 3, 4}
    assert set(pool["typology"].unique()) == {5}
    assert 0.01 < main["label"].mean() < 0.05


def test_fraud_signatures(engine):
    m = engine.main
    card = m[m["typology"] == 3]
    assert card["amount"].max() < 200
    ato = m[m["typology"] == 4]
    assert ato["new_device"].mean() == 1.0
    smurf = engine.pool
    assert smurf["amount"].between(9_000, 9_999).all()
    assert np.all(smurf["near_threshold"] == 1)
