"""Recovery policies: retry on the robot or ask a remote operator, and who gets the next operator.

Policies see only what the system logs: SKU id, detected failure type, attempts so far,
queue length, free operators, the station's priority weight, and outcomes of past
retries/interventions. They never see SKU difficulty or true retry odds.
"""

from __future__ import annotations

from .sim import CYCLE_S, HANDLE_MEAN, RETRY_EXTRA, TYPES


class FirstFailHuman:
    """Every detected failure goes to a person, first come first served."""
    name = "first-fail-human"

    def reset(self, robots, n_ops):
        pass

    def decide(self, sku, ftype, k, t, qlen, free_ops, w):
        return "human"

    def pick(self, queue, t, robots):
        return min(range(len(queue)), key=lambda i: queue[i].t_req)

    def observe_retry(self, *a):
        pass

    def observe_human(self, *a):
        pass


class FixedRetry(FirstFailHuman):
    """Retry N times on the robot, then a person, FIFO."""

    def __init__(self, n=3):
        self.n = n
        self.name = f"retry-{n}-then-human"

    def decide(self, sku, ftype, k, t, qlen, free_ops, w):
        return "retry" if k < self.n else "human"


class CostAware(FirstFailHuman):
    """Retry while the learned odds beat the expected cost of waiting for a person.

    p_hat(type, attempt, sku) = fleet rate for (type, attempt) x shrunk SKU factor.
    Retry iff  w * c_retry  <  p_hat * (w * E[wait + handle] + lam * E[handle]),
    i.e. one retry costs less robot time than the share of the human path it saves.
    The operator queue is served by priority weight x aging / expected handle time.
    """
    name = "cost-aware"

    def __init__(self, lam=1.0, max_tries=4, aging_s=120.0, prior_n=4.0):
        self.lam, self.max_tries, self.aging_s, self.prior_n = lam, max_tries, aging_s, prior_n

    def reset(self, robots, n_ops):
        self.n_ops = max(1, n_ops)
        self.tk = {}       # (type, k) -> [successes, trials]
        self.sku = {}      # sku -> [observed successes, expected successes]
        self.hsum = {t: [HANDLE_MEAN[t] * 2, 2.0] for t in TYPES}  # weak prior on handle time
        self.wait_ewma = {}  # station weight -> recent observed queue wait (priority makes FIFO math wrong)

    def _m(self, t, k):
        s, n = self.tk.get((t, min(k, 3)), (0.0, 0.0))
        prior = 0.5 * 0.6 ** k
        return (s + prior * self.prior_n) / (n + self.prior_n)

    def p_hat(self, sku, t, k):
        os_, es = self.sku.get(sku, (0.0, 0.0))
        f = (os_ + 2.0) / (es + 2.0)
        return min(0.98, self._m(t, k) * f)

    def handle(self, t):
        s, n = self.hsum[t]
        return s / n

    def decide(self, sku, ftype, k, t, qlen, free_ops, w):
        if ftype == "PSTOP" or k >= self.max_tries:
            self.last = "protective stop: always a person" if ftype == "PSTOP" else f"{k} tries used"
            return "human"
        h = self.handle(ftype)
        if free_ops > 0 and qlen == 0:
            wait = 0.0
        else:
            wait = max((qlen + 1) / self.n_ops * h, self.wait_ewma.get(w, 0.0))
        c = CYCLE_S + RETRY_EXTRA[ftype]
        p = self.p_hat(sku, ftype, k)
        self.last = f"p(retry works)={p:.2f}, expected wait {wait:.0f}s + handle {h:.0f}s"
        return "retry" if w * c < p * (w * (wait + h) + self.lam * h) else "human"

    def pick(self, queue, t, robots):
        def score(i):
            q = queue[i]
            return robots[q.robot]["w"] * (1 + (t - q.t_req) / self.aging_s) / self.handle(q.ftype)
        i = max(range(len(queue)), key=score)
        w = robots[queue[i].robot]["w"]
        self.wait_ewma[w] = 0.8 * self.wait_ewma.get(w, 0.0) + 0.2 * (t - queue[i].t_req)
        return i

    def observe_retry(self, sku, t, k, ok):
        m = self._m(t, k)
        s = self.tk.setdefault((t, min(k, 3)), [0.0, 0.0])
        s[0] += ok
        s[1] += 1
        o = self.sku.setdefault(sku, [0.0, 0.0])
        o[0] += ok
        o[1] += m

    def observe_human(self, t, dur):
        s = self.hsum[t]
        s[0] += dur
        s[1] += 1
