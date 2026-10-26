"""Event-driven shift simulator: laundry robots folding linens, failing, retrying, waiting for remote operators.

Adapted from my warehouse recovery-dispatch prototype; the failure types are now folding failures.

All numbers are invented but plausible. Ground truth (SKU difficulty, true retry success)
is hidden from the policies; they only see what a real system would log.
"""

from __future__ import annotations

import heapq
import math
import random
from dataclasses import dataclass, field

TYPES = ("MISS", "DOUBLE", "DROP", "WRONG", "PSTOP")
# MISS = no grasp / corner not found, DOUBLE = two items, DROP, WRONG = wrong fold or bin, PSTOP = protective stop
# share of failures by type, detection rate, extra retry seconds, true base retry success
MIX = {"MISS": 0.55, "DOUBLE": 0.12, "DROP": 0.15, "WRONG": 0.08, "PSTOP": 0.10}
DETECT = {"MISS": 0.99, "DOUBLE": 0.80, "DROP": 0.97, "WRONG": 0.85, "PSTOP": 1.0}
RETRY_EXTRA = {"MISS": 12.0, "DOUBLE": 30.0, "DROP": 60.0, "WRONG": 40.0, "PSTOP": 0.0}
RETRY_BASE = {"MISS": 0.80, "DOUBLE": 0.75, "DROP": 0.50, "WRONG": 0.60, "PSTOP": 0.0}
HANDLE_MEAN = {"MISS": 60.0, "DOUBLE": 70.0, "DROP": 120.0, "WRONG": 80.0, "PSTOP": 150.0}
CONNECT_S = 15.0          # operator session connect + scene read
HUMAN_OK = 0.97
CYCLE_S = 45.0            # ~80 folded items/h when nothing fails
RETRY_DECAY = 0.6         # each further auto attempt on the same pick is less likely to work
SHIFT_S = 8 * 3600.0
MISSHIP_COST = 2.0        # $ per defective item that reaches the shelf (re-wash / refold), invented


@dataclass
class Sku:
    d: float              # hidden difficulty 0..1
    fail_p: float         # hidden per-attempt failure prob on a fresh pick
    mix: dict             # hidden failure-type mix for this SKU


@dataclass
class Config:
    seed: int
    sites: list           # [(n_robots, express_weight)]
    n_skus: int = 300
    hard_share: float = 0.15   # share of SKUs that are hard (deformable, shiny, tiny)
    fail_scale: float = 1.0    # multiplies every per-attempt failure probability (what-if only)


def true_retry_p(t: str, sku: Sku, k: int) -> float:
    return RETRY_BASE[t] * (1 - sku.d) ** 1.5 * RETRY_DECAY ** k


def make_skus(cfg: Config, rng: random.Random) -> list:
    out = []
    for _ in range(cfg.n_skus):
        hard = rng.random() < cfg.hard_share
        d = rng.betavariate(5, 3) if hard else rng.betavariate(1.2, 8)
        fail_p = min(1.0, (0.02 + 0.30 * d) * cfg.fail_scale)
        w = {t: MIX[t] * math.exp(rng.gauss(0, 0.4)) for t in TYPES}
        if hard:
            w["DROP"] *= 2.0
            w["DOUBLE"] *= 1.5
        s = sum(w.values())
        out.append(Sku(d, fail_p, {t: v / s for t, v in w.items()}))
    return out


@dataclass(order=True)
class Req:
    t_req: float
    robot: int = field(compare=False)
    ftype: str = field(compare=False)


@dataclass
class Result:
    good: int = 0
    misship: int = 0
    interventions: int = 0
    auto_recoveries: int = 0
    auto_attempts: int = 0
    blocked_s: float = 0.0
    express_blocked_s: float = 0.0
    op_busy_s: float = 0.0
    waits: list = field(default_factory=list)
    log: list = field(default_factory=list)   # (t, robot, event, detail) for the demo
    dataset: list = field(default_factory=list)  # one labeled episode per intervention

    def summary(self, n_robots: int, n_ops: int) -> dict:
        w = sorted(self.waits)
        p95 = w[int(0.95 * (len(w) - 1))] if w else 0.0
        return {
            "items_per_robot_hour": self.good / (n_robots * SHIFT_S / 3600),
            "misships": self.misship,
            "interventions": self.interventions,
            "auto_recoveries": self.auto_recoveries,
            "auto_attempts": self.auto_attempts,
            "blocked_robot_h": self.blocked_s / 3600,
            "express_blocked_h": self.express_blocked_s / 3600,
            "wait_p95_s": p95,
            "op_util": self.op_busy_s / (n_ops * SHIFT_S) if n_ops else 0.0,
        }


def run_shift(cfg: Config, policy, n_ops: int, keep_log: bool = False) -> Result:
    """One shift for one fleet. `policy` sees only logged signals (see policy.py)."""
    rng = random.Random(cfg.seed)
    skus = make_skus(cfg, rng)
    sku_w = [1.0 / (i + 1) ** 0.8 for i in range(len(skus))]  # long-tail demand
    robots = []
    for site, (n, wexp) in enumerate(cfg.sites):
        robots += [{"site": site, "w": wexp} for _ in range(n)]
    # Hidden-state rng for outcomes, separate stream per decision kind so policies see
    # the same picks/failures (common random numbers).
    pick_rng = random.Random(cfg.seed * 7 + 1)
    out_rng = random.Random(cfg.seed * 7 + 2)
    hum_rng = random.Random(cfg.seed * 7 + 3)

    res = Result()
    ev: list = []
    seq = 0

    def push(t, kind, r, **kw):
        nonlocal seq
        seq += 1
        heapq.heappush(ev, (t, seq, kind, r, kw))

    state = [None] * len(robots)  # per robot: dict(sku, k, ftype, blocked_since)
    queue: list = []
    free_ops = n_ops
    policy.reset(robots, n_ops)

    def log(t, r, e, d=""):
        if keep_log:
            res.log.append((round(t, 1), r, e, d))

    def start_pick(t, r):
        if t >= SHIFT_S:
            return
        si = pick_rng.choices(range(len(skus)), sku_w)[0]
        state[r] = {"sku": si, "k": 0, "ftype": None, "blocked_since": None}
        push(t + CYCLE_S * pick_rng.uniform(0.85, 1.15), "attempt", r, fresh=True)

    def done_good(t, r):
        res.good += 1
        start_pick(t, r)

    def handle_failure(t, r, ftype):
        st = state[r]
        sku = skus[st["sku"]]
        st["ftype"] = ftype
        choice = policy.decide(st["sku"], ftype, st["k"], t, len(queue), free_ops, robots[r]["w"])
        if choice == "retry" and ftype != "PSTOP":  # protective stops always need a person
            res.auto_attempts += 1
            dur = CYCLE_S + RETRY_EXTRA[ftype]
            ok = out_rng.random() < true_retry_p(ftype, sku, st["k"])
            push(t + dur, "retry_done", r, ok=ok)
            log(t, r, "RETRY", f"{ftype} sku{st['sku']} try {st['k'] + 1}; {getattr(policy, 'last', '')}")
        else:
            st["blocked_since"] = t
            req = Req(t, r, ftype)
            queue.append(req)
            log(t, r, "HUMAN", f"{ftype} sku{st['sku']} after {st['k']} tries; {getattr(policy, 'last', '')}")
            dispatch(t)

    def dispatch(t):
        nonlocal free_ops
        while free_ops > 0 and queue:
            i = policy.pick(queue, t, robots)
            req = queue.pop(i)
            free_ops -= 1
            wait = t - req.t_req
            res.waits.append(wait)
            mean = HANDLE_MEAN[req.ftype]
            dur = CONNECT_S + mean * math.exp(hum_rng.gauss(-0.08, 0.4))
            ok = hum_rng.random() < HUMAN_OK
            res.interventions += 1
            st = state[req.robot]
            res.dataset.append({"sku": st["sku"], "type": req.ftype, "auto_tries": st["k"],
                                "wait_s": round(wait, 1), "handle_s": round(dur, 1)})
            push(t + dur, "human_done", req.robot, ok=ok, dur=dur)

    for r in range(len(robots)):
        start_pick(pick_rng.uniform(0, CYCLE_S), r)

    while ev:
        t, _, kind, r, kw = heapq.heappop(ev)
        if t > SHIFT_S + 3600:
            break
        st = state[r]
        if kind == "attempt":
            sku = skus[st["sku"]]
            if out_rng.random() >= sku.fail_p:
                if t <= SHIFT_S:
                    done_good(t, r)
                continue
            ftype = out_rng.choices(TYPES, [sku.mix[x] for x in TYPES])[0]
            if out_rng.random() > DETECT[ftype]:
                # missed by the checks: a double/wrong/short item goes into the order
                res.misship += 1
                log(t, r, "MISSHIP", ftype)
                start_pick(t, r)
                continue
            handle_failure(t, r, ftype)
        elif kind == "retry_done":
            policy.observe_retry(st["sku"], st["ftype"], st["k"], kw["ok"])
            if kw["ok"]:
                res.auto_recoveries += 1
                if t <= SHIFT_S:
                    done_good(t, r)
            else:
                st["k"] += 1
                handle_failure(t, r, st["ftype"])
        elif kind == "human_done":
            blocked = t - st["blocked_since"]
            res.blocked_s += blocked
            if robots[r]["w"] > 1:
                res.express_blocked_s += blocked
            res.op_busy_s += kw["dur"]
            free_ops += 1
            policy.observe_human(st["ftype"], kw["dur"])
            if kw["ok"]:
                if t <= SHIFT_S:
                    done_good(t, r)
            else:
                st["blocked_since"] = t
                queue.append(Req(t, r, st["ftype"]))
            dispatch(t)
    return res
