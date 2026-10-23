TIMING = {"train_seconds", "total_seconds"}


def _run(engine):
    engine.reset()
    first = engine.attack()
    adapt = {k: v for k, v in engine.adapt().items() if k not in TIMING}
    second = engine.attack()
    engine.reset()
    return first, adapt, second


def test_red_team_is_reproducible(engine):
    assert _run(engine) == _run(engine)


def test_red_team_shows_miss_then_improvement(engine):
    first, adapt, second = _run(engine)
    assert first["cb_rate"] < 0.5
    assert adapt["after"]["rate"] > adapt["before"]["rate"]
    assert second["model_version"] == 2
    assert second["cb_rate"] > first["cb_rate"]
