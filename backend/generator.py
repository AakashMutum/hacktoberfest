"""Seeded synthetic UPI-style transaction generator.

Produces ~200k transactions over 30 days with four fraud typologies used for
training, plus a separate pool of a fifth typology ("smurfing") that never
appears in the main dataset and is used only for red-team attacks.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import networkx as nx

SEED = 42
DAY = 86_400
N_DAYS = 30
TOTAL_TXNS = 200_000

N_USERS = 12_000
N_MERCHANTS = 800
N_MULES = 420
N_SLEEPERS = 220

TYPOLOGY_NAMES = {
    0: "legit",
    1: "social_engineering",
    2: "mule_ring",
    3: "card_testing",
    4: "account_takeover",
    5: "smurfing",
}

FIRST = ["arun", "priya", "karthik", "divya", "rahul", "sneha", "vijay", "lakshmi", "suresh", "anitha",
         "rohit", "meena", "ganesh", "kavya", "manoj", "deepa", "sanjay", "pooja", "ravi", "nisha",
         "ajay", "swathi", "harish", "revathi", "imran", "fathima", "joseph", "mary", "aakash", "neha"]
LAST = ["kumar", "raman", "iyer", "sharma", "nair", "reddy", "singh", "pillai", "das", "menon",
        "patel", "rao", "khan", "joshi", "varma", "gupta", "babu", "shetty", "mishra", "verma"]
BANKS = ["okaxis", "oksbi", "ybl", "paytm", "ibl", "okhdfcbank", "okicici"]
SHOPS = ["kirana", "medicals", "fuels", "cafe", "electronics", "supermart", "tiffins", "textiles",
         "recharge", "bakery", "mobiles", "hardware", "sweets", "opticals", "stationery"]

# Account kinds
USER, MERCHANT, MULE, SLEEPER = 0, 1, 2, 3


def _make_accounts(rng: np.random.Generator) -> pd.DataFrame:
    n = N_USERS + N_MERCHANTS + N_MULES + N_SLEEPERS
    kind = np.concatenate([
        np.full(N_USERS, USER), np.full(N_MERCHANTS, MERCHANT),
        np.full(N_MULES, MULE), np.full(N_SLEEPERS, SLEEPER),
    ])
    age = np.empty(n)
    age[kind == USER] = np.clip(rng.lognormal(6.4, 0.9, N_USERS), 20, 4000)
    age[kind == MERCHANT] = np.clip(rng.lognormal(6.8, 0.6, N_MERCHANTS), 90, 4000)
    young = rng.random(N_USERS) < 0.10
    age[:N_USERS][young] = rng.uniform(5, 90, young.sum())
    age[kind == MULE] = np.where(rng.random(N_MULES) < 0.3, rng.uniform(90, 700, N_MULES), rng.uniform(3, 75, N_MULES))
    age[kind == SLEEPER] = rng.uniform(250, 2200, N_SLEEPERS)
    usual = np.clip(rng.lognormal(np.log(900), 0.8, n), 80, 40_000)
    hour_center = np.clip(rng.normal(14, 2.5, n), 8, 21)

    vpas = []
    used = set()
    for i in range(n):
        if kind[i] == MERCHANT:
            base = f"{SHOPS[rng.integers(len(SHOPS))]}.{LAST[rng.integers(len(LAST))]}"
        else:
            base = f"{FIRST[rng.integers(len(FIRST))]}.{LAST[rng.integers(len(LAST))]}"
        vpa = f"{base}{rng.integers(10, 999)}@{BANKS[rng.integers(len(BANKS))]}"
        while vpa in used:
            vpa = f"{base}{rng.integers(1000, 9999)}@{BANKS[rng.integers(len(BANKS))]}"
        used.add(vpa)
        vpas.append(vpa)
    return pd.DataFrame({
        "account": np.arange(n), "vpa": vpas, "kind": kind, "age_days": age.round(0),
        "usual_spend": usual.round(0), "hour_center": hour_center,
    })


def _hours(rng, center, sd, size):
    return np.mod(np.round(rng.normal(center, sd, size)), 24).astype(int)


def _night_hours(rng, size):
    return rng.choice([22, 23, 0, 1, 2, 3, 4], size=size)


def _known_device_age(age_days):
    return np.minimum(np.asarray(age_days) * 1440, 525_600)


def _row(ts, s, r, amount, new_payee, new_device, device_age, typ):
    return (int(ts), int(s), int(r), float(round(amount)), int(new_payee), int(new_device), float(device_age), int(typ))


def _fraud_rows(rng, acc, n_days_span, campaigns_scale=1.0):
    """Typologies 1-4."""
    rows = []
    users = np.arange(N_USERS)
    mules = np.arange(N_USERS + N_MERCHANTS, N_USERS + N_MERCHANTS + N_MULES)
    merchants = np.arange(N_USERS, N_USERS + N_MERCHANTS)
    age = acc["age_days"].to_numpy()

    def day_ts(hour):
        d = rng.integers(0, n_days_span)
        return d * DAY + hour * 3600 + rng.integers(0, 3600)

    # 1. Social engineering: large first-time-payee transfer at odd hours, mule forwards it on.
    for _ in range(int(650 * campaigns_scale)):
        v, m = rng.choice(users), rng.choice(mules)
        ts = day_ts(int(_night_hours(rng, 1)[0]) if rng.random() < 0.65 else int(rng.integers(9, 21)))
        amt = rng.uniform(18_000, 190_000)
        if rng.random() < 0.3:
            # Paid into an ordinary-looking, unwitting account that leaves no graph trail.
            rows.append(_row(ts, v, rng.choice(users), amt, 1, 0, _known_device_age(age[v]), 1))
            continue
        rows.append(_row(ts, v, m, amt, 1, 0, _known_device_age(age[v]), 1))
        nxt = rng.choice(mules)
        rows.append(_row(ts + rng.integers(120, 2400), m, nxt, amt * rng.uniform(0.85, 0.98), 1, 0,
                         _known_device_age(age[m]), 1))

    # 2. Mule rings: fan-in from many victims to a hub, then fan-out down a chain.
    for _ in range(int(55 * campaigns_scale)):
        hub = rng.choice(mules)
        t0 = rng.integers(0, n_days_span) * DAY + rng.integers(0, DAY)
        total = 0.0
        for v in rng.choice(users, rng.integers(10, 20), replace=False):
            amt = rng.uniform(4_000, 38_000)
            total += amt
            rows.append(_row(t0 + rng.integers(0, 6 * 3600), v, hub, amt, 1, 0, _known_device_age(age[v]), 2))
        layer, t = [hub], t0 + 6 * 3600
        for _depth in range(3):
            nxt_layer = []
            for src in layer:
                for dst in rng.choice(mules, 2, replace=False):
                    amt = total / (2 * len(layer)) * rng.uniform(0.9, 0.98)
                    rows.append(_row(t + rng.integers(0, 3600), src, dst, amt, 1, 0, _known_device_age(age[src]), 2))
                    nxt_layer.append(dst)
            layer, t = nxt_layer[:2], t + 3600

    # 3. Card / UPI testing: bursts of tiny payments to many merchants.
    for _ in range(int(150 * campaigns_scale)):
        v = rng.choice(users)
        t0 = day_ts(int(rng.choice([0, 1, 2, 3, 4, 5, 13, 23])))
        new_dev = rng.random() < 0.6
        dev_age = rng.uniform(1, 90) if new_dev else _known_device_age(age[v])
        for k in range(rng.integers(7, 14)):
            gap = rng.integers(10, 45) if rng.random() < 0.7 else rng.integers(200, 900)
            t0 += gap
            rows.append(_row(t0, v, rng.choice(merchants), rng.uniform(1, 199),
                             1, int(new_dev), dev_age, 3))

    # 4. Account takeover: new device then immediate large transfer(s).
    for _ in range(int(560 * campaigns_scale)):
        v = rng.choice(users)
        m = rng.choice(mules) if rng.random() < 0.7 else rng.choice(users)
        hour = int(_night_hours(rng, 1)[0]) if rng.random() < 0.5 else int(rng.integers(8, 22))
        ts = day_ts(hour)
        dev_age = rng.uniform(1, 25) if rng.random() < 0.8 else rng.uniform(30, 3000)
        for k in range(rng.integers(1, 3)):
            rows.append(_row(ts + k * rng.integers(60, 600), v, m, rng.uniform(12_000, 150_000), 1, 1,
                             dev_age + k * 5, 4))
    return rows


def _smurf_rows(rng, acc, n_campaigns, day_lo, day_hi):
    """Typology 5 (held out): structured sub-10k transfers through aged sleeper accounts."""
    rows, campaign_ids = [], []
    users = np.arange(N_USERS)
    sleepers = np.arange(N_USERS + N_MERCHANTS + N_MULES, N_USERS + N_MERCHANTS + N_MULES + N_SLEEPERS)
    age = acc["age_days"].to_numpy()
    for c in range(n_campaigns):
        t0 = rng.integers(day_lo, day_hi) * DAY + int(rng.uniform(9, 11)) * 3600
        layer1 = rng.choice(sleepers, 3, replace=False)
        senders = rng.choice(users, rng.integers(6, 10), replace=False)
        for i, s in enumerate(senders):
            dst = layer1[i % 3]
            for _ in range(rng.integers(1, 3)):
                rows.append(_row(t0 + rng.integers(0, 4 * 3600), s, dst, rng.uniform(9_000, 9_990),
                                 int(rng.random() < 0.3), 0, _known_device_age(age[s]), 5))
                campaign_ids.append(c)
        layer, t = list(layer1), t0 + 4 * 3600
        for _depth in range(2):
            nxt = rng.choice(sleepers, 2, replace=False)
            for src in layer:
                for _ in range(rng.integers(2, 4)):
                    rows.append(_row(t + rng.integers(0, 3 * 3600), src, rng.choice(nxt), rng.uniform(9_000, 9_990),
                                     int(rng.random() < 0.3), 0, _known_device_age(age[src]), 5))
                    campaign_ids.append(c)
            layer, t = list(nxt), t + 3 * 3600
    return rows, campaign_ids


def _legit_rows(rng, acc, n):
    users = N_USERS
    age = acc["age_days"].to_numpy()
    usual = acc["usual_spend"].to_numpy()
    hc = acc["hour_center"].to_numpy()
    contacts = rng.integers(0, users, (users, 6))
    favs = rng.integers(users, users + N_MERCHANTS, (users, 8))

    s = rng.integers(0, users, n)
    kind = rng.random(n)
    r = np.empty(n, dtype=int)
    new_payee = np.zeros(n, dtype=int)
    m_fav = kind < 0.55
    m_newm = (kind >= 0.55) & (kind < 0.70)
    m_contact = (kind >= 0.70) & (kind < 0.93)
    m_newp = kind >= 0.93
    r[m_fav] = favs[s[m_fav], rng.integers(0, 8, m_fav.sum())]
    r[m_newm] = rng.integers(users, users + N_MERCHANTS, m_newm.sum())
    r[m_contact] = contacts[s[m_contact], rng.integers(0, 6, m_contact.sum())]
    r[m_newp] = rng.integers(0, users, m_newp.sum())
    new_payee[m_newm | m_newp] = 1

    amount = np.clip(rng.lognormal(np.log(usual[s]), 0.75), 10, None)
    # Legitimate large transfers: rent deposits, fees, vehicle purchases, family support.
    big = rng.random(n) < 0.03
    amount[big] = rng.uniform(25_000, 180_000, big.sum())
    big_new = big & (rng.random(n) < 0.5)
    new_payee[big_new] = 1

    micro = m_fav & (rng.random(n) < 0.06)
    amount[micro] = rng.uniform(5, 60, micro.sum())

    hour = _hours(rng, hc[s], 3.2, n)
    night = rng.random(n) < 0.04
    hour[night] = _night_hours(rng, night.sum())
    ts = rng.integers(0, N_DAYS, n) * DAY + hour * 3600 + rng.integers(0, 3600, n)
    new_dev = (rng.random(n) < 0.025).astype(int)
    new_dev[big & (rng.random(n) < 0.06)] = 1
    fresh = rng.random(n) < 0.3
    dev_age = np.where(new_dev == 1, np.where(fresh, rng.uniform(1, 60, n), rng.uniform(60, 30_000, n)), _known_device_age(age[s]))
    rows = list(zip(ts.astype(int), s, r, amount.round(0), new_payee, new_dev, dev_age, np.zeros(n, dtype=int)))
    return rows + _collector_rows(rng, acc, contacts)


def _collector_rows(rng, acc, contacts):
    """Legitimate pass-through accounts: people who pool money from friends and pay it on."""
    rows = []
    age = acc["age_days"].to_numpy()
    collectors = rng.choice(N_USERS, 300, replace=False)
    for c in collectors:
        for _ in range(rng.integers(1, 4)):
            t0 = rng.integers(0, N_DAYS) * DAY + int(rng.integers(8, 23)) * 3600
            payers = rng.choice(N_USERS, rng.integers(4, 14), replace=False)
            share = rng.uniform(500, 9_000)
            for p in payers:
                rows.append(_row(t0 + rng.integers(0, 10 * 3600), p, c, share * rng.uniform(0.9, 1.1),
                                 int(rng.random() < 0.6), 0, _known_device_age(age[p]), 0))
            dst = rng.integers(0, N_USERS + N_MERCHANTS)
            rows.append(_row(t0 + 11 * 3600, c, dst, share * len(payers) * rng.uniform(0.9, 1.0),
                             int(rng.random() < 0.5), 0, _known_device_age(age[c]), 0))
    return rows


COLS = ["ts", "sender", "receiver", "amount", "new_payee", "new_device", "device_age_min", "typology"]

FEATURES = [
    "amount_log", "hour", "odd_hour", "sender_age_days", "amount_to_usual", "new_payee", "new_device",
    "device_age_min", "sender_txn_1h", "sender_txn_24h", "receiver_age_days", "receiver_is_merchant",
    "recv_fan_in", "recv_out_degree", "recv_passthrough", "sender_passthrough", "chain_depth", "near_threshold",
]

FEATURE_LABELS = {
    "amount_log": "Transfer amount",
    "hour": "Hour of day",
    "odd_hour": "Odd-hour activity",
    "sender_age_days": "Sender account age",
    "amount_to_usual": "Amount vs usual spend",
    "new_payee": "First-time payee",
    "new_device": "Unrecognised device",
    "device_age_min": "Device age",
    "sender_txn_1h": "Payments in last hour",
    "sender_txn_24h": "Payments in last 24h",
    "receiver_age_days": "Payee account age",
    "receiver_is_merchant": "Payee is a merchant",
    "recv_fan_in": "Payee fan-in (distinct senders)",
    "recv_out_degree": "Payee fan-out",
    "recv_passthrough": "Payee pass-through ratio",
    "sender_passthrough": "Sender pass-through ratio",
    "chain_depth": "Forwarding chain depth",
    "near_threshold": "Just-under-10k structuring",
}


def _velocity(df: pd.DataFrame, window: int) -> np.ndarray:
    order = np.lexsort((df["ts"].to_numpy(), df["sender"].to_numpy()))
    key = df["sender"].to_numpy()[order].astype(np.int64) * 10**8 + df["ts"].to_numpy()[order].astype(np.int64)
    pos = np.searchsorted(key, key - window, side="left")
    counts = np.arange(len(key)) - pos
    out = np.empty(len(key), dtype=float)
    out[order] = counts
    return out


def graph_stats(df: pd.DataFrame, acc: pd.DataFrame) -> pd.DataFrame:
    """Per-account graph features from a networkx DiGraph of the payment network."""
    g = nx.DiGraph()
    agg = df.groupby(["sender", "receiver"])["amount"].agg(["sum", "count"]).reset_index()
    g.add_weighted_edges_from(agg[["sender", "receiver", "sum"]].itertuples(index=False, name=None))
    n = len(acc)
    fan_in = np.zeros(n)
    out_deg = np.zeros(n)
    for node, d in g.in_degree():
        fan_in[node] = d
    for node, d in g.out_degree():
        out_deg[node] = d
    in_amt = np.bincount(df["receiver"], weights=df["amount"], minlength=n)
    out_amt = np.bincount(df["sender"], weights=df["amount"], minlength=n)
    passthrough = np.minimum(in_amt, out_amt) / np.maximum(np.maximum(in_amt, out_amt), 1.0)

    # Forwarding subgraph: only accounts that pass most of what they receive straight on.
    is_merchant = (acc["kind"].to_numpy() == MERCHANT)
    fwd_nodes = [i for i in range(n) if passthrough[i] >= 0.5 and not is_merchant[i] and g.has_node(i)]
    fwd = g.subgraph(fwd_nodes)
    depth = np.zeros(n)
    for _ in range(5):
        new = depth.copy()
        for u in fwd.nodes:
            succ = list(fwd.successors(u))
            if succ:
                new[u] = min(5, 1 + max(depth[v] for v in succ))
        depth = new
    return pd.DataFrame({"fan_in": fan_in, "out_degree": out_deg, "passthrough": passthrough, "chain_depth": depth})


def build_features(df: pd.DataFrame, acc: pd.DataFrame, gs: pd.DataFrame) -> pd.DataFrame:
    s, r = df["sender"].to_numpy(), df["receiver"].to_numpy()
    out = df.copy()
    out["hour"] = (df["ts"] % DAY) // 3600
    out["amount_log"] = np.log1p(df["amount"])
    out["odd_hour"] = out["hour"].isin([22, 23, 0, 1, 2, 3, 4]).astype(int)
    out["sender_age_days"] = acc["age_days"].to_numpy()[s]
    out["amount_to_usual"] = (df["amount"] / acc["usual_spend"].to_numpy()[s]).round(3)
    out["sender_txn_1h"] = _velocity(df, 3600)
    out["sender_txn_24h"] = _velocity(df, DAY)
    out["receiver_age_days"] = acc["age_days"].to_numpy()[r]
    out["receiver_is_merchant"] = (acc["kind"].to_numpy()[r] == MERCHANT).astype(int)
    out["recv_fan_in"] = gs["fan_in"].to_numpy()[r]
    out["recv_out_degree"] = gs["out_degree"].to_numpy()[r]
    out["recv_passthrough"] = gs["passthrough"].to_numpy()[r].round(3)
    out["sender_passthrough"] = gs["passthrough"].to_numpy()[s].round(3)
    out["chain_depth"] = gs["chain_depth"].to_numpy()[r]
    out["near_threshold"] = ((df["amount"] % 10_000) >= 9_000).astype(int)
    out["label"] = (df["typology"] > 0).astype(int)
    vpa = acc["vpa"].to_numpy()
    out["sender_vpa"] = vpa[s]
    out["receiver_vpa"] = vpa[r]
    return out


def generate(seed: int = SEED, total: int = TOTAL_TXNS):
    """Return (accounts, main_df, smurf_pool_df). smurf pool carries a `campaign` column."""
    rng = np.random.default_rng(seed)
    acc = _make_accounts(rng)
    fraud = _fraud_rows(rng, acc, N_DAYS, campaigns_scale=total / TOTAL_TXNS)
    legit = _legit_rows(rng, acc, total - len(fraud) - 6_000)
    smurf, campaigns = _smurf_rows(rng, acc, n_campaigns=80, day_lo=22, day_hi=N_DAYS)

    main = pd.DataFrame(fraud + legit, columns=COLS)
    pool = pd.DataFrame(smurf, columns=COLS)
    pool["campaign"] = campaigns
    main["campaign"] = -1
    both = pd.concat([main, pool], ignore_index=True)
    both["ts"] = both["ts"].clip(0, N_DAYS * DAY - 1)
    gs = graph_stats(both, acc)
    feats = build_features(both, acc, gs)
    is_pool = np.arange(len(feats)) >= len(main)
    main_f = feats[~is_pool].sort_values("ts", kind="stable").reset_index(drop=True)
    pool_f = feats[is_pool].sort_values("ts", kind="stable").reset_index(drop=True)
    main_f["txn_id"] = [f"T{i:06d}" for i in range(len(main_f))]
    pool_f["txn_id"] = [f"R{i:05d}" for i in range(len(pool_f))]
    return acc, main_f, pool_f
