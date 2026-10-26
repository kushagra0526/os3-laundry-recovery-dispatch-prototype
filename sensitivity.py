"""What-if added after the held-out run: scale every failure probability down and see how much remote help costs.

Same 40 held-out fleets, cost-aware policy, remote cost as % of the $2.50/h price at an assumed $20/h operator.
"""
import dataclasses
import math

from laundrysim.policy import CostAware
from laundrysim.scenarios import HELDOUT, fleet, n_robots
from laundrysim.sim import SHIFT_S, run_shift

PRICE, OP = 2.50, 20.0
print("fail scale | interventions per robot-h | remote cost % of price at 8:1 | at 4:1 | items/robot-h at 8:1")
for scale in (1.0, 0.5, 0.25, 0.1, 0.05):
    row = []
    for rpo in (8, 4):
        pct, iph, ipr = [], [], []
        for seed in HELDOUT:
            cfg = dataclasses.replace(fleet(seed), fail_scale=scale)
            n = n_robots(cfg)
            m = max(1, math.ceil(n / rpo))
            s = run_shift(cfg, CostAware(), m).summary(n, m)
            pct.append(100 * s["op_util"] * m / n * OP / PRICE)
            iph.append(s["interventions"] / (n * SHIFT_S / 3600))
            ipr.append(s["items_per_robot_hour"])
        row.append((sum(pct) / len(pct), sum(iph) / len(iph), sum(ipr) / len(ipr)))
    print(f"{scale:9} | {row[0][1]:.2f} interventions/robot-h | remote {row[0][0]:.0f}% | {row[1][0]:.0f}% | {row[0][2]:.1f}")
