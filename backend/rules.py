"""Baseline static rules engine, the kind of system Circuit Breaker is compared against."""
from __future__ import annotations

import time

RULES = [
    ("amount_over_50k", "Amount above ₹50,000", lambda t: t["amount"] > 50_000),
    ("new_payee_over_25k", "First-time payee and amount above ₹25,000", lambda t: t["new_payee"] == 1 and t["amount"] > 25_000),
    ("velocity_over_10", "More than 10 payments in an hour", lambda t: t["sender_txn_1h"] > 10),
]


def evaluate(txn: dict):
    """Returns (blocked, fired_rule_labels, latency_ms)."""
    t0 = time.perf_counter()
    fired = [label for _, label, fn in RULES if fn(txn)]
    return bool(fired), fired, (time.perf_counter() - t0) * 1000
