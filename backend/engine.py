"""Stream engine: replays held-out transactions through the scorer and the rules engine,
tracks metrics for both, runs investigations and red-team experiments."""
from __future__ import annotations

import asyncio
import json
import os
import pickle
import time
from collections import deque

import numpy as np
import pandas as pd

from . import investigator, policy, rules
from .generator import DAY, FEATURES, TYPOLOGY_NAMES, generate
from .scorer import Scorer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
MODEL_DIR = os.path.join(ROOT, "models")
TRAIN_DAYS = 21
TICK_S = 0.25
BASE_PER_TICK = 2
ATTACK_SIZE = 60
PRE_INVESTIGATE = 8
CACHE_PATH = os.path.join(DATA_DIR, "investigation_cache.json")


def load_dataset(seed: int):
    os.makedirs(DATA_DIR, exist_ok=True)
    path = os.path.join(DATA_DIR, f"dataset_seed{seed}.pkl")
    if os.path.exists(path):
        with open(path, "rb") as f:
            return pickle.load(f)
    data = generate(seed)
    with open(path, "wb") as f:
        pickle.dump(data, f)
    return data


def sim_clock(ts: float) -> str:
    day = int(ts // DAY) + 1
    secs = int(ts % DAY)
    return f"Day {day:02d} · {secs // 3600:02d}:{(secs % 3600) // 60:02d}"


class SystemStats:
    def __init__(self):
        self.seen = 0
        self.fraud_seen = 0
        self.fraud_caught = 0
        self.fraud_amount = 0.0
        self.rupees_saved = 0.0
        self.legit_blocked = 0
        self.legit_held = 0
        self.legit_nudged = 0
        self.latencies = deque(maxlen=5000)

    def snapshot(self):
        lat = np.array(self.latencies) if self.latencies else np.array([0.0])
        return {
            "seen": self.seen, "fraud_seen": self.fraud_seen, "fraud_caught": self.fraud_caught,
            "fraud_amount": round(self.fraud_amount), "rupees_saved": round(self.rupees_saved),
            "legit_blocked": self.legit_blocked, "legit_held": self.legit_held, "legit_nudged": self.legit_nudged,
            "p50_ms": round(float(np.percentile(lat, 50)), 3), "p95_ms": round(float(np.percentile(lat, 95)), 3),
        }


class Engine:
    def __init__(self, seed: int = 42):
        self.seed = seed
        self.acc, self.main, self.pool = load_dataset(seed)
        self.vpa_to_acc = dict(zip(self.acc["vpa"], self.acc["account"]))
        self.all = pd.concat([self.main, self.pool], ignore_index=True)
        self.by_sender = self.all.groupby("sender").indices
        self.by_receiver = self.all.groupby("receiver").indices
        self._graph_cache()

        self.train_df = self.main[self.main["ts"] < TRAIN_DAYS * DAY].reset_index(drop=True)
        self.stream_df = self.main[self.main["ts"] >= TRAIN_DAYS * DAY].reset_index(drop=True)
        self.stream_X = self.stream_df[FEATURES].to_numpy(dtype=np.float32)
        self.stream_rows = self.stream_df.to_dict("records")

        camp = self.pool["campaign"].to_numpy()
        self.pool_train = self.pool[camp % 2 == 0].reset_index(drop=True)
        self.pool_eval = self.pool[camp % 2 == 1].reset_index(drop=True)

        os.makedirs(MODEL_DIR, exist_ok=True)
        model_path = os.path.join(MODEL_DIR, f"scorer_seed{seed}.json")
        if os.path.exists(model_path):
            self.base_scorer = Scorer.load(model_path)
            self.base_scorer.trained_on = len(self.train_df)
        else:
            self.base_scorer = Scorer.train(self.train_df, seed=seed)
            self.base_scorer.save(model_path)
        self.base_auc = self.base_scorer.auc(self.stream_df)
        self.subscribers: set[asyncio.Queue] = set()
        self.lang = "en"
        self.llm_status = {"provider": None, "model": None, "mode": None, "state": "loading", "last_latency_ms": None, "error": None}
        self.inv_queue: asyncio.Queue | None = None
        self.pending: dict[tuple[str, str], float] = {}
        self.pre_records: dict[str, dict] = {}
        self.cache = self._load_cache()
        self.safe_mode = False
        self.reset()

    # ---------- state ----------
    def reset(self):
        self.scorer = self.base_scorer
        self.cursor = 0
        self.running = True
        self.speed = 1
        self.cb = SystemStats()
        self.rules = SystemStats()
        self.tight = SystemStats()
        self.records: dict[str, dict] = {}
        self.order: deque = deque(maxlen=4000)
        self.injected: deque = deque()
        self.attack_cursor = 0
        self.attack_seq = 0
        self.attacks: list[dict] = []
        self.adapt_result = None
        self.investigations: dict[tuple[str, str], dict] = {}
        self.clock_ts = float(self.stream_rows[0]["ts"])

    # ---------- scoring ----------
    def _score(self, row: dict, x: np.ndarray, injected: bool = False, attack_id: int | None = None) -> dict:
        t0 = time.perf_counter()
        prob, factors, _ = self.scorer.score_one(x)
        action = policy.decide(prob)
        cb_ms = (time.perf_counter() - t0) * 1000
        r_blocked, r_fired, r_ms = rules.evaluate(row, "simple")
        t_blocked, t_fired, t_ms = rules.evaluate(row, "tight")
        return {
            "txn_id": row["txn_id"], "ts": float(row["ts"]), "clock": sim_clock(row["ts"]),
            "sender_vpa": row["sender_vpa"], "receiver_vpa": row["receiver_vpa"],
            "amount": float(row["amount"]), "hour": int(row["hour"]),
            "new_payee": int(row["new_payee"]), "new_device": int(row["new_device"]),
            "risk": round(prob, 4), "action": action, "band": policy.risk_band(action), "factors": factors,
            "rules_blocked": r_blocked, "rules_fired": r_fired,
            "tight_blocked": t_blocked, "tight_fired": t_fired,
            "cb_ms": round(cb_ms, 3), "rules_ms": round(r_ms, 4), "tight_ms": round(t_ms, 4),
            "is_fraud": bool(row["label"]), "typology": TYPOLOGY_NAMES[int(row["typology"])],
            "injected": injected, "attack_id": attack_id, "model_version": self.scorer.version,
        }

    def _account(self, rec: dict):
        for stats, flagged, blocked, ms in (
            (self.cb, rec["action"] in ("hold", "block"), rec["action"] == "block", rec["cb_ms"]),
            (self.rules, rec["rules_blocked"], rec["rules_blocked"], rec["rules_ms"]),
            (self.tight, rec["tight_blocked"], rec["tight_blocked"], rec["tight_ms"]),
        ):
            stats.seen += 1
            stats.latencies.append(ms)
            if rec["is_fraud"]:
                stats.fraud_seen += 1
                stats.fraud_amount += rec["amount"]
                if flagged:
                    stats.fraud_caught += 1
                    stats.rupees_saved += rec["amount"]
            elif blocked:
                stats.legit_blocked += 1
        if not rec["is_fraud"]:
            if rec["action"] == "hold":
                self.cb.legit_held += 1
            elif rec["action"] == "nudge":
                self.cb.legit_nudged += 1

    def next_batch(self) -> list[dict]:
        out = []
        n = BASE_PER_TICK * self.speed
        while len(out) < n:
            if self.injected:
                rec = self.injected.popleft()
                rec["ts"] = self.clock_ts
                rec["clock"] = sim_clock(self.clock_ts)
            else:
                if self.cursor >= len(self.stream_rows):
                    self.running = False
                    break
                row = self.stream_rows[self.cursor]
                rec = self._score(row, self.stream_X[self.cursor])
                self.cursor += 1
                self.clock_ts = rec["ts"]
            self._account(rec)
            self.records[rec["txn_id"]] = rec
            if len(self.order) == self.order.maxlen:
                self.records.pop(self.order[0], None)
            self.order.append(rec["txn_id"])
            if policy.needs_investigation(rec["action"]):
                self._auto(rec["txn_id"])
            out.append(rec)
        return out

    def metrics(self) -> dict:
        return {
            "circuit_breaker": self.cb.snapshot(), "rules_engine": self.rules.snapshot(), "rules_tight": self.tight.snapshot(),
            "stream": {"cursor": self.cursor, "total": len(self.stream_rows), "running": self.running,
                       "speed": self.speed, "clock": sim_clock(self.clock_ts), "pending_injected": len(self.injected)},
            "model": self.model_info(),
        }

    def model_info(self) -> dict:
        return {"version": self.scorer.version, "trained_on": self.scorer.trained_on,
                "base_auc_typologies_1_4": round(self.base_auc, 4), "features": len(FEATURES)}

    # ---------- investigator tools ----------
    def tool_account_history(self, vpa: str) -> dict:
        a = self.vpa_to_acc.get(vpa)
        if a is None:
            return {"error": "unknown vpa"}
        prof = self.acc.iloc[a]
        idx = self.by_sender.get(a, [])
        sent = self.all.iloc[idx]
        sent = sent[sent["ts"] <= self.clock_ts + DAY].sort_values("ts").tail(5)
        return {
            "vpa": vpa, "account_age_days": int(prof["age_days"]), "usual_spend_inr": float(prof["usual_spend"]),
            "is_merchant": bool(prof["kind"] == 1), "payments_sent_total": int(len(idx)),
            "recent_payments": [{"to": r.receiver_vpa, "amount_inr": float(r.amount), "hour": int(r.hour),
                                 "new_payee": bool(r.new_payee), "new_device": bool(r.new_device)}
                                for r in sent.itertuples()],
        }

    def tool_graph_neighbours(self, vpa: str) -> dict:
        a = self.vpa_to_acc.get(vpa)
        if a is None:
            return {"error": "unknown vpa"}
        g = self.gstats
        def summarise(idx, col):
            if len(idx) == 0:
                return []
            sub = self.all.iloc[idx].groupby(col)["amount"].agg(["sum", "count"]).sort_values("sum", ascending=False).head(5)
            return [{"vpa": self.acc["vpa"].iat[n], "total_inr": round(float(s.sum)), "payments": int(s.count),
                     "account_age_days": int(self.acc["age_days"].iat[n]), "pass_through": round(float(g["passthrough"][n]), 2)}
                    for n, s in zip(sub.index, sub.itertuples())]
        return {
            "vpa": vpa, "distinct_senders": int(g["fan_in"][a]), "distinct_payees": int(g["out_degree"][a]),
            "pass_through": round(float(g["passthrough"][a]), 2), "forwarding_chain_depth": int(g["chain_depth"][a]),
            "senders": summarise(self.by_receiver.get(a, []), "sender"),
            "payees": summarise(self.by_sender.get(a, []), "receiver"),
        }

    def tool_risk_factors(self, txn_id: str) -> dict:
        rec = self.records.get(txn_id) or self.pre_records.get(txn_id)
        if rec is None:
            return {"error": "unknown transaction"}
        return {"txn_id": txn_id, "risk": rec["risk"], "proposed_action": rec["action"], "factors": rec["factors"],
                "rules_engine_fired": rec["rules_fired"]}

    def tools(self):
        return {"get_account_history": self.tool_account_history,
                "get_graph_neighbours": self.tool_graph_neighbours,
                "get_risk_factors": self.tool_risk_factors}

    # ---------- investigations ----------
    def _load_cache(self) -> dict:
        try:
            with open(CACHE_PATH, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def _save_cache(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(self.cache, f, ensure_ascii=False)

    def _cached(self, txn_id: str, lang: str) -> dict | None:
        key = (txn_id, lang)
        if key in self.investigations:
            return self.investigations[key]
        provider = self.llm_status.get("provider")
        if provider:
            hit = self.cache.get(f"{txn_id}|{lang}|{provider}")
            if hit:
                self.investigations[key] = hit
                return hit
        return None

    def _replay(self, txn_id: str, lang: str) -> dict | None:
        """Any cached real model output for this payment, from whichever provider recorded it."""
        prefix = f"{txn_id}|{lang}|"
        for key, result in self.cache.items():
            if key.startswith(prefix):
                return investigator.replayed(result)
        return None

    def cached_count(self) -> int:
        return len(self.cache)

    def request_investigation(self, txn_id: str, lang: str) -> dict | None:
        """Returns a finished result or a pending status. Never waits on the model."""
        if txn_id not in self.records:
            return None
        if self.safe_mode:
            result = self._replay(txn_id, lang) or investigator.fallback(self.records[txn_id], lang, "demo safe mode: no cached model output")
            self.records[txn_id].setdefault("investigations", {})[lang] = result
            return {"status": "done", "result": result}
        hit = self._cached(txn_id, lang)
        if hit:
            self.records[txn_id].setdefault("investigations", {})[lang] = hit
            return {"status": "done", "result": hit}
        key = (txn_id, lang)
        if key not in self.pending:
            self.pending[key] = time.time()
            self.inv_queue.put_nowait(key)
        return {"status": "pending", "since": self.pending[key]}

    def _auto(self, txn_id: str):
        if self.safe_mode:
            hit = self._replay(txn_id, self.lang)
            if hit:
                self.records[txn_id].setdefault("investigations", {})[self.lang] = hit
            return
        if self.inv_queue is None:
            return
        hit = self._cached(txn_id, self.lang)
        if hit:
            self.records[txn_id].setdefault("investigations", {})[self.lang] = hit
            return
        if self.inv_queue.qsize() == 0 and not self.pending:
            self.request_investigation(txn_id, self.lang)

    async def _investigate_now(self, rec: dict, lang: str) -> dict:
        result = await investigator.investigate(rec, lang, self.tools())
        if result["source"] == "model":
            self.llm_status.update(provider=result["provider"], model=result["model"], mode=result["mode"],
                                   state="ready", last_latency_ms=result["latency_ms"], error=None)
            self.cache[f"{rec['txn_id']}|{lang}|{result['provider']}"] = result
            self._save_cache()
        elif result["error"] == "no model provider reachable":
            self.llm_status.update(provider=None, model=None, mode=None, state="offline")
        return result

    async def worker(self):
        """Single background worker: concurrency 1 so a local CPU model is never oversubscribed."""
        self.inv_queue = asyncio.Queue()
        self.llm_status.update(await investigator.warm_up())
        await self.broadcast({"type": "llm_status", "status": self.llm_status})
        asyncio.create_task(self.pre_investigate())
        while True:
            txn_id, lang = await self.inv_queue.get()
            rec = self.records.get(txn_id)
            if rec is not None:
                result = await self._investigate_now(rec, lang)
                self.investigations[(txn_id, lang)] = result
                rec.setdefault("investigations", {})[lang] = result
                await self.broadcast({"type": "investigation", "txn_id": txn_id, "lang": lang, "result": result,
                                      "status": self.llm_status})
            self.pending.pop((txn_id, lang), None)

    async def pre_investigate(self):
        """Investigate the first flagged payments of the seeded stream ahead of time, cached on disk."""
        if not self.llm_status.get("provider") or self.llm_status["state"] != "ready":
            return
        provider = self.llm_status["provider"]
        p = self.base_scorer.predict(self.stream_df.iloc[:5000])
        idx = [i for i in range(len(p)) if p[i] >= policy.THRESHOLDS["hold"]][:PRE_INVESTIGATE]
        for i in idx:
            row = self.stream_rows[i]
            if f"{row['txn_id']}|en|{provider}" in self.cache:
                continue
            rec = self._score(row, self.stream_X[i])
            self.pre_records[rec["txn_id"]] = rec
            while not self.inv_queue.empty() or self.pending:
                await asyncio.sleep(1)
            await self._investigate_now(rec, "en")

    # ---------- graph ----------
    def _graph_cache(self):
        from .generator import graph_stats
        gs = graph_stats(self.all, self.acc)
        self.gstats = {c: gs[c].to_numpy() for c in gs.columns}

    def ego_graph(self, txn_id: str) -> dict | None:
        rec = self.records.get(txn_id)
        if rec is None:
            return None
        center = self.vpa_to_acc[rec["receiver_vpa"]]
        payer = self.vpa_to_acc[rec["sender_vpa"]]
        nodes: dict[int, dict] = {}
        edges: dict[tuple[int, int], dict] = {}
        g = self.gstats

        def add_node(n, depth):
            if n not in nodes:
                kind = int(self.acc["kind"].iat[n])
                nodes[n] = {"id": int(n), "vpa": self.acc["vpa"].iat[n], "depth": depth,
                            "merchant": kind == 1, "pass_through": round(float(g["passthrough"][n]), 2),
                            "fan_in": int(g["fan_in"][n]), "age_days": int(self.acc["age_days"].iat[n]),
                            "suspect": bool(kind != 1 and g["passthrough"][n] >= 0.5),
                            "role": "payer" if n == payer else ("payee" if n == center else "")}

        def add_edges(idx, limit):
            sub = self.all.iloc[idx].groupby(["sender", "receiver"])["amount"].agg(["sum", "count"])
            sub = sub.sort_values("sum", ascending=False).head(limit)
            for (s, r), v in sub.iterrows():
                edges[(int(s), int(r))] = {"source": int(s), "target": int(r), "amount": round(float(v["sum"])), "count": int(v["count"])}
            return [(int(s), int(r)) for s, r in sub.index]

        add_node(center, 0)
        add_node(payer, 1)
        for s, r in add_edges(self.by_receiver.get(center, []), 14):
            add_node(s, 1)
        frontier = [center]
        for depth in (1, 2, 3):
            nxt = []
            for n in frontier:
                if nodes[n]["merchant"]:
                    continue
                for s, r in add_edges(self.by_sender.get(n, []), 4):
                    add_node(r, depth)
                    nxt.append(r)
            frontier = [n for n in nxt if nodes[n]["suspect"]][:6]
        edges[(payer, center)] = edges.get((payer, center), {"source": int(payer), "target": int(center),
                                                             "amount": round(rec["amount"]), "count": 1})
        ring = [n["id"] for n in nodes.values() if n["suspect"]]
        return {"txn_id": txn_id, "center": int(center), "payer": int(payer), "nodes": list(nodes.values()),
                "edges": list(edges.values()), "suspect_count": len(ring)}

    # ---------- red team ----------
    def _detect(self, df: pd.DataFrame, scorer: Scorer) -> dict:
        p = scorer.predict(df)
        flagged = p >= policy.THRESHOLDS["hold"]
        recs = df.to_dict("records")
        rule_hits = sum(rules.evaluate(r, "simple")[0] for r in recs)
        tight_hits = sum(rules.evaluate(r, "tight")[0] for r in recs)
        n = max(len(df), 1)
        return {"n": int(len(df)), "detected": int(flagged.sum()), "rate": round(float(flagged.mean()), 4),
                "rules_detected": int(rule_hits), "rules_rate": round(rule_hits / n, 4),
                "tight_detected": int(tight_hits), "tight_rate": round(tight_hits / n, 4)}

    def attack(self) -> dict:
        n = len(self.pool_eval)
        idx = [(self.attack_cursor + i) % n for i in range(ATTACK_SIZE)]
        self.attack_cursor = (self.attack_cursor + ATTACK_SIZE) % n
        self.attack_seq += 1
        rows = self.pool_eval.iloc[idx].to_dict("records")
        X = self.pool_eval.iloc[idx][FEATURES].to_numpy(dtype=np.float32)
        recs = []
        for row, x in zip(rows, X):
            row = dict(row, txn_id=f"{row['txn_id']}-{self.attack_seq}")
            recs.append(self._score(row, x, injected=True, attack_id=self.attack_seq))
        self.injected.extend(recs)
        cb_hit = sum(r["action"] in ("hold", "block") for r in recs)
        rules_hit = sum(r["rules_blocked"] for r in recs)
        tight_hit = sum(r["tight_blocked"] for r in recs)
        result = {"attack_id": self.attack_seq, "seed": self.seed, "typology": "smurfing", "injected": len(recs),
                  "amount": round(sum(r["amount"] for r in recs)), "model_version": self.scorer.version,
                  "cb_detected": cb_hit, "cb_rate": round(cb_hit / len(recs), 4),
                  "rules_detected": int(rules_hit), "rules_rate": round(rules_hit / len(recs), 4),
                  "tight_detected": int(tight_hit), "tight_rate": round(tight_hit / len(recs), 4),
                  "nudged": sum(r["action"] == "nudge" for r in recs)}
        self.attacks.append(result)
        return result

    def adapt(self) -> dict:
        t0 = time.perf_counter()
        before = self._detect(self.pool_eval, self.scorer)
        rng = np.random.default_rng(self.seed)
        legit = self.train_df[self.train_df["label"] == 0]
        legit = legit.iloc[rng.choice(len(legit), 40_000, replace=False)]
        fraud = self.train_df[self.train_df["label"] == 1]
        train = pd.concat([legit, fraud, self.pool_train], ignore_index=True)
        new = Scorer.train(train, rounds=160, seed=self.seed, version=self.scorer.version + 1)
        after = self._detect(self.pool_eval, new)
        auc_before = self.scorer.auc(self.stream_df)
        auc_after = new.auc(self.stream_df)
        self.scorer = new
        self.adapt_result = {
            "before": before, "after": after, "labelled_attack_rows": int(len(self.pool_train)),
            "train_rows": int(len(train)), "train_seconds": round(new.train_seconds, 2),
            "total_seconds": round(time.perf_counter() - t0, 2),
            "auc_typologies_1_4_before": round(auc_before, 4), "auc_typologies_1_4_after": round(auc_after, 4),
            "model_version": new.version, "seed": self.seed,
            "eval_note": "Evaluated on held-out smurfing campaigns not used for retraining.",
        }
        return self.adapt_result

    # ---------- loop ----------
    async def broadcast(self, msg: dict):
        for q in list(self.subscribers):
            if q.qsize() > 50:
                continue
            q.put_nowait(msg)

    async def run(self):
        while True:
            await asyncio.sleep(TICK_S)
            if not self.running or not self.subscribers:
                continue
            batch = self.next_batch()
            await self.broadcast({"type": "batch", "txns": batch, "metrics": self.metrics()})
