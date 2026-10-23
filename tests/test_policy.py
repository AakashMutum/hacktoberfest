import pytest

from backend import policy, rules


@pytest.mark.parametrize("prob,action", [
    (0.0, "allow"), (0.29, "allow"), (0.30, "nudge"), (0.59, "nudge"),
    (0.60, "hold"), (0.849, "hold"), (0.85, "block"), (1.0, "block"),
])
def test_decide(prob, action):
    assert policy.decide(prob) == action


def test_only_medium_and_high_risk_are_investigated():
    assert [a for a in ("allow", "nudge", "hold", "block") if policy.needs_investigation(a)] == ["hold", "block"]


@pytest.mark.parametrize("lang", policy.LANGS)
def test_copy_complete_in_every_language(lang):
    assert set(policy.COPY[lang]) == set(policy.COPY["en"])
    msg = policy.customer_message("hold", lang, 12345, "x@ybl")
    assert "12,345" in msg and "{" not in msg


def test_rules_engine():
    base = {"amount": 1000, "new_payee": 0, "sender_txn_1h": 1}
    assert not rules.evaluate(base)[0]
    assert rules.evaluate({**base, "amount": 60_000})[0]
    assert rules.evaluate({**base, "amount": 30_000, "new_payee": 1})[0]
    assert rules.evaluate({**base, "sender_txn_1h": 12})[0]


def test_tight_rules_engine():
    base = {"amount": 12_000, "new_payee": 1, "new_device": 0, "sender_txn_1h": 1, "hour": 14}
    assert not rules.evaluate(base, "tight")[0]
    assert rules.evaluate({**base, "hour": 2}, "tight")[0]
    assert rules.evaluate({**base, "new_device": 1}, "tight")[0]
    assert len(rules.describe("tight")) == 4
