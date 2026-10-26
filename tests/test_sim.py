import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from laundrysim.policy import CostAware, FirstFailHuman, FixedRetry
from laundrysim.scenarios import fleet, n_robots
from laundrysim.sim import Config, run_shift

SMALL = Config(seed=7, sites=[(4, 1.0), (3, 3.0)], n_skus=120, hard_share=0.2)


class TestSim(unittest.TestCase):
    def test_deterministic(self):
        a = run_shift(SMALL, CostAware(), 2).summary(7, 2)
        b = run_shift(SMALL, CostAware(), 2).summary(7, 2)
        self.assertEqual(a, b)

    def test_accounting(self):
        r = run_shift(SMALL, FixedRetry(2), 2, keep_log=True)
        self.assertEqual(r.interventions, len(r.dataset))
        self.assertEqual(r.interventions, len(r.waits))
        self.assertGreaterEqual(r.blocked_s, 0)
        self.assertLessEqual(r.auto_recoveries, r.auto_attempts)

    def test_protective_stops_never_retried(self):
        r = run_shift(SMALL, FixedRetry(5), 7, keep_log=True)
        self.assertFalse([e for e in r.log if e[2] == "RETRY" and e[3].startswith("PSTOP")])
        self.assertTrue([e for e in r.log if e[2] == "HUMAN" and e[3].startswith("PSTOP")])

    def test_unlimited_operators_favour_humans_scarce_favour_retries(self):
        cfg = fleet(3)
        n = n_robots(cfg)
        full = {p.name: run_shift(cfg, p, n).good for p in (FirstFailHuman(), FixedRetry(3))}
        tight = {p.name: run_shift(cfg, p, max(1, n // 8)).good for p in (FirstFailHuman(), FixedRetry(3))}
        self.assertGreater(full["first-fail-human"], full["retry-3-then-human"])
        self.assertLess(tight["first-fail-human"], tight["retry-3-then-human"])


class TestCostAware(unittest.TestCase):
    def setUp(self):
        self.p = CostAware()
        self.p.reset([{"w": 1.0}], 2)

    def test_retries_more_when_queue_is_long(self):
        idle = self.p.decide(0, "DROP", 1, 0, 0, 2, 1.0)
        busy = self.p.decide(0, "DROP", 1, 0, 12, 0, 1.0)
        self.assertEqual((idle, busy), ("human", "retry"))

    def test_learns_hopeless_sku(self):
        for _ in range(30):
            self.p.observe_retry(5, "MISS", 0, True)    # MISS usually recovers
        for _ in range(8):
            self.p.observe_retry(9, "MISS", 0, False)   # but never on SKU 9
        self.assertEqual(self.p.decide(5, "MISS", 0, 0, 0, 2, 1.0), "retry")
        self.assertEqual(self.p.decide(9, "MISS", 0, 0, 0, 2, 1.0), "human")

    def test_never_retries_protective_stop(self):
        self.assertEqual(self.p.decide(0, "PSTOP", 0, 0, 50, 0, 1.0), "human")


if __name__ == "__main__":
    unittest.main()
