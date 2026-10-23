"""Baseline static rules engines that Circuit Breaker is compared against.

simple: the classic amount thresholds most legacy systems start with.
tight:  a fairer, more targeted rule set built from the same signals a fraud team would hand-tune.
"""
from __future__ import annotations

import time

NIGHT = {22, 23, 0, 1, 2, 3, 4}

RULESETS = {
    "simple": [
        ("Amount above ₹50,000", lambda t: t["amount"] > 50_000),
        ("First-time payee and amount above ₹25,000", lambda t: t["new_payee"] == 1 and t["amount"] > 25_000),
        ("More than 10 payments in an hour", lambda t: t["sender_txn_1h"] > 10),
    ],
    "tight": [
        ("First-time payee, amount above ₹10,000, between 22:00 and 04:59", lambda t: t["new_payee"] == 1 and t["amount"] > 10_000 and t["hour"] in NIGHT),
        ("New device and amount above ₹10,000", lambda t: t["new_device"] == 1 and t["amount"] > 10_000),
        ("More than 6 payments in an hour", lambda t: t["sender_txn_1h"] > 6),
        ("Amount above ₹1,50,000", lambda t: t["amount"] > 150_000),
    ],
}


def describe(name: str) -> list[str]:
    return [label for label, _ in RULESETS[name]]


def evaluate(txn: dict, ruleset: str = "simple"):
    """Returns (blocked, fired_rule_labels, latency_ms)."""
    t0 = time.perf_counter()
    fired = [label for label, fn in RULESETS[ruleset] if fn(txn)]
    return bool(fired), fired, (time.perf_counter() - t0) * 1000
