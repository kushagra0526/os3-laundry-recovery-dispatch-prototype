# laundrysim: retry or call a remote operator, and what that costs against a $2.50/hour price

OS3 sells its robot's laundry shift to hotels "as low as $2.50/hour" and describes the workflow as six steps: move linens, load the washer, washer to dryer, unload the dryer, fold, shelve (https://os3robotics.com/deploy/). Whenever a step fails there are two decisions: retry on the robot, or ask a remote person now; and when several robots are waiting, who gets the next free operator. At a flat hourly price, the remote-operator time those decisions spend is cost. This prototype is a simulator for that, adapted from my earlier warehouse recovery-dispatch prototype (inloop-robotics folder), with every number invented but plausible.

## What it is
- `laundrysim/sim.py`: event-driven 8-hour shift. 3-6 hotels with 1-3 robots each, a long-tail mix of linen types (towels easy; fitted sheets and duvet covers hard), five failure types (no grasp, two items, drop, wrong fold or bin, protective stop) with detection rates, retry times, retry odds that fall with each try, and operator connect + handle times. Defects that slip through reach the shelf. Hidden difficulty and true odds are never shown to a policy.
- `laundrysim/policy.py`: first-fail-human, retry-1/2/3-then-human (FIFO), and a cost-aware dispatcher that learns retry odds per failure type, attempt and linen type, and weighs expected queue wait against operator time. Protective stops always go to a person.
- `evaluate.py`: every policy on every fleet at 8, 6, 4, 3 and 1 robots per operator, same random failures for every policy, scored as items folded per robot-hour as a % of the best fixed rule for that fleet and staffing in hindsight, plus remote-operator cost as a % of the $2.50 price at an assumed $10, $20 and $30 per operator-hour.
- `sensitivity.py`: what-if on the failure rate (added after the held-out run).

## Results: 40 held-out fleets (seeds 7001-7040, committed before the first held-out run; dev seeds 1-12)
| robots / operator | first-fail-human | retry-1 | retry-2 | retry-3 | cost-aware |
|---|---|---|---|---|---|
| 8 | 93.8% | 98.9% | 96.3% | 92.5% | **100.9%** (worst fleet 87.9%) |
| 6 | 98.4% | 98.3% | 93.7% | 89.7% | **100.7%** (worst 94.7%) |
| 4 | 100.0% | 95.4% | 90.0% | 86.4% | 100.2% (worst 98.6%) |
| 3 | 100.0% | 94.6% | 89.3% | 85.2% | 99.8% (worst 97.8%) |
| 1 | 100.0% | 94.0% | 88.6% | 84.4% | 99.3% (worst 96.2%) |

- The best fixed rule depends on staffing: at 8:1 retry-1 wins 23 of 40 fleets, first-fail-human 9, retry-2 8; at 6:1 first-fail-human 22, retry-1 17; at 4:1 and below first-fail-human wins 40/40.
- The cost-aware policy is never far from the best fixed rule, but the gain is small: +0.9 points at 8:1 (58.7 vs 54.8 items/robot-h for first-fail-human) and nothing at 4:1 and below, where a person is free anyway. On one fleet at 8:1 it still reached only 87.9% of the best fixed rule.
- With my invented failure rates the remote cost is large at the top of the table: about 50% of the price at 8:1 and an assumed $10/h, 100% at $20/h.

## The number that matters: how rarely must the robot ask for help?
Same 40 fleets, cost-aware policy, assumed $20/h operator, failure probabilities scaled down (`python sensitivity.py`, output in `out/sensitivity.txt`; the scaling was added after the held-out run):

| failure scale | interventions per robot-hour | remote cost, % of $2.50 at 8:1 | at 4:1 |
|---|---|---|---|
| 1.0 | 4.47 | 101% | 123% |
| 0.5 | 2.89 | 65% | 71% |
| 0.25 | 1.65 | 36% | 38% |
| 0.1 | 0.67 | 15% | 15% |
| 0.05 | 0.35 | 8% | 8% |

Within this simulator, remote help stays under about 15% of the hourly price only if the robot asks for a person less than about once per 1.5 robot-hours (0.67 per hour). The operator cost, handle times and failure rates are my assumptions, not OS3 numbers; the real figure for their robot is what the intervention log would give.

## Read this before believing the table
Simulated failures, simulated people, my own policy compared against rules I wrote. Nothing is known about OS3's robot, its failure rates, how it is supervised, or what the $2.50 includes. The washer/dryer queueing, folding quality and shelf defects are only represented as a blocked-robot weight and a defect count. No OS3 data, code or systems were used.

## Run it (3 commands)
```
pip install pytest
python -m pytest -q tests
python evaluate.py heldout
```
Standard library only. 7 tests.

Unofficial prototype by Kushagra Pratap Singh. Not affiliated with OS3.
