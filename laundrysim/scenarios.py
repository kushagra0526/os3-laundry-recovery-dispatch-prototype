"""Fleet scenarios. DEV seeds are for tuning; HELDOUT seeds were committed before the first held-out run."""

import random

from .sim import Config

DEV = list(range(1, 13))
HELDOUT = list(range(7001, 7041))
ROBOTS_PER_OP = (8, 6, 4, 3)   # staffing levels tried for every fleet


def fleet(seed: int) -> Config:
    rng = random.Random(seed * 101)
    n_sites = rng.randint(3, 6)
    sites = []
    for i in range(n_sites):
        n = rng.randint(1, 3)
        express = 3.0 if i == 0 or rng.random() < 0.2 else 1.0   # same-day lanes block costlier
        sites.append((n, express))
    return Config(seed=seed, sites=sites, n_skus=rng.choice((20, 40, 80)),
                  hard_share=rng.uniform(0.10, 0.40))


def n_robots(cfg: Config) -> int:
    return sum(n for n, _ in cfg.sites)
