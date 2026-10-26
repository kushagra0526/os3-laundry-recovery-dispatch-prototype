"""One held-out fleet at 6 robots per operator: what each policy does with the same failures."""
import math
from laundrysim.policy import CostAware, FirstFailHuman, FixedRetry
from laundrysim.scenarios import fleet, n_robots
from laundrysim.sim import run_shift

cfg = fleet(7001)
n = n_robots(cfg)
m = math.ceil(n / 6)
print(f"fleet: {n} robots at {len(cfg.sites)} sites, {m} remote operators, one 8 h shift\n")
for p in (FirstFailHuman(), FixedRetry(3), CostAware()):
    r = run_shift(cfg, p, m, keep_log=True)
    s = r.summary(n, m)
    print(f"{p.name:20} {s['items_per_robot_hour']:6.1f} items/robot-h  {s['interventions']:5d} interventions  "
          f"{s['auto_recoveries']:5d} self-recoveries  p95 wait {s['wait_p95_s']:4.0f}s")
    if p.name == "cost-aware":
        shown = {"RETRY": 0, "HUMAN": 0}
        print("\n  sample decisions (cost-aware):")
        for t, rb, e, d in r.log:
            if e in shown and shown[e] < 4 and t > 3600:
                shown[e] += 1
                print(f"   {int(t // 3600):02d}:{int(t % 3600 // 60):02d}  robot {rb:2d}  {e:5}  {d}")
        print(f"\n  labeled intervention episodes for retraining: {len(r.dataset)} (e.g. {r.dataset[0]})")
