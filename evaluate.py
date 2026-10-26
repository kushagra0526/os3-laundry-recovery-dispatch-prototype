"""Run every policy on every fleet at every staffing level; write out/<split>.json.

usage: python evaluate.py dev|heldout
"""

import json
import math
import sys
from multiprocessing import Pool
from pathlib import Path

from laundrysim.policy import CostAware, FirstFailHuman, FixedRetry
from laundrysim.scenarios import DEV, HELDOUT, ROBOTS_PER_OP, fleet, n_robots
from laundrysim.sim import MISSHIP_COST, run_shift

PRICE = 2.50          # OS3 site: hospitality "as low as $2.50/hour"
OP_COST = (10, 20, 30)  # assumed fully loaded remote-operator cost, $/hour (my assumption)
FIXED = lambda: [FirstFailHuman(), FixedRetry(1), FixedRetry(2), FixedRetry(3)]
POLICIES = lambda: FIXED() + [CostAware()]


def one(seed):
    cfg = fleet(seed)
    n = n_robots(cfg)
    rows = []
    for rpo in ROBOTS_PER_OP + (None,):          # None = one operator per robot (no queue)
        m = n if rpo is None else max(1, math.ceil(n / rpo))
        for p in POLICIES():
            s = run_shift(cfg, p, m).summary(n, m)
            rows.append({"seed": seed, "robots": n, "ops": m, "rpo": rpo or 1, "policy": p.name, **s})
    return rows


def aggregate(rows):
    names = [p.name for p in POLICIES()]
    fixed = [p.name for p in FIXED()]
    out = {}
    for rpo in sorted({r["rpo"] for r in rows}, reverse=True):
        rs = [r for r in rows if r["rpo"] == rpo]
        seeds = sorted({r["seed"] for r in rs})
        by = {(r["seed"], r["policy"]): r for r in rs}
        lvl = {}
        for nm in names:
            pr = [by[(s, nm)]["items_per_robot_hour"] for s in seeds]
            best_fixed = [max(by[(s, f)]["items_per_robot_hour"] for f in fixed) for s in seeds]
            lvl[nm] = {
                "items_per_robot_hour": sum(pr) / len(pr),
                "pct_of_best_fixed_in_hindsight": 100 * sum(p / b for p, b in zip(pr, best_fixed)) / len(pr),
                "worst_pct_of_best_fixed": 100 * min(p / b for p, b in zip(pr, best_fixed)),
                "express_blocked_h": sum(by[(s, nm)]["express_blocked_h"] for s in seeds) / len(seeds),
                "interventions": sum(by[(s, nm)]["interventions"] for s in seeds) / len(seeds),
                "defect_cost": MISSHIP_COST * sum(by[(s, nm)]["misships"] for s in seeds) / len(seeds),
                "wait_p95_s": sum(by[(s, nm)]["wait_p95_s"] for s in seeds) / len(seeds),
            }
            for x in OP_COST:   # remote-operator cost per robot-hour as % of the $2.50/h price
                lvl[nm][f"remote_pct_of_price_at_{x}_per_h"] = 100 * sum(
                    by[(s, nm)]["op_util"] * by[(s, nm)]["ops"] / by[(s, nm)]["robots"] * x / PRICE for s in seeds) / len(seeds)
        out[f"{rpo} robots/op"] = lvl
    # which fixed rule is best at each level, per fleet: shows no single rule wins everywhere
    winners = {}
    for rpo in sorted({r["rpo"] for r in rows}, reverse=True):
        rs = [r for r in rows if r["rpo"] == rpo and r["policy"] in fixed]
        seeds = sorted({r["seed"] for r in rs})
        cnt = {f: 0 for f in fixed}
        for s in seeds:
            cnt[max((r for r in rs if r["seed"] == s), key=lambda r: r["items_per_robot_hour"])["policy"]] += 1
        winners[f"{rpo} robots/op"] = cnt
    return {"levels": out, "best_fixed_rule_count": winners, "n_fleets": len({r["seed"] for r in rows})}


if __name__ == "__main__":
    split = sys.argv[1] if len(sys.argv) > 1 else "dev"
    seeds = {"dev": DEV, "heldout": HELDOUT}[split]
    with Pool() as pool:
        rows = [r for rs in pool.map(one, seeds) for r in rs]
    agg = aggregate(rows)
    Path("out").mkdir(exist_ok=True)
    Path(f"out/{split}.json").write_text(json.dumps({"summary": agg, "rows": rows}, indent=1))
    for lvl, d in agg["levels"].items():
        print(f"\n{lvl}")
        for nm, v in d.items():
            print(f"  {nm:20} {v['items_per_robot_hour']:6.1f} items/robot-h  {v['pct_of_best_fixed_in_hindsight']:5.1f}% of best fixed "
                  f"(worst {v['worst_pct_of_best_fixed']:5.1f}%)  express blocked {v['express_blocked_h']:5.1f} h  "
                  f"interventions {v['interventions']:6.0f}  p95 wait {v['wait_p95_s']:5.0f}s  "
                  f"remote cost % of $2.50 at $10/20/30 per h: {v['remote_pct_of_price_at_10_per_h']:.0f}/{v['remote_pct_of_price_at_20_per_h']:.0f}/{v['remote_pct_of_price_at_30_per_h']:.0f}")
    print("\nbest fixed rule per fleet:", json.dumps(agg["best_fixed_rule_count"]))
