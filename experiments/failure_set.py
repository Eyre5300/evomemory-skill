"""B2: failure-set two-phase protocol.

Phase 1 — run each task's baseline (no experience), N seeds per consumer, and
classify per consumer: solvable (baseline_pass > 0) vs failure-set (0/N).
Phase 2 (the arms) runs only on each consumer's failure-set, because the claim is
about tasks the weak model cannot solve alone. Conditioning per consumer keeps the
comparison clean (each model has its own failure-set).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class BaselineResult:
    consumer: str
    task: str
    seeds: list[int]
    passes: int
    steps: list[int]

    @property
    def in_failure_set(self) -> bool:
        return self.passes == 0


def run_baselines(
    consumers: list[Any],
    tasks: list[Any],
    seeds: list[int],
    run_one: Callable[[Any, Any, int], tuple[bool, int]],
) -> list[BaselineResult]:
    """Phase 1. ``run_one(consumer, task, seed) -> (passed, steps)``.

    Returns one BaselineResult per (consumer, task). ``run_one`` is injected so the
    same protocol drives Flask / SWE-bench / GAIA without this module importing any
    benchmark.
    """
    out: list[BaselineResult] = []
    for cons in consumers:
        cname = getattr(cons, "name", str(cons))
        for task in tasks:
            tid = getattr(task, "id", str(task))
            passes, steps = 0, []
            for s in seeds:
                ok, n = run_one(cons, task, s)
                passes += int(bool(ok))
                steps.append(int(n))
            out.append(BaselineResult(cname, tid, list(seeds), passes, steps))
    return out


def failure_set(results: list[BaselineResult]) -> dict[str, list[str]]:
    """Per-consumer list of task ids with 0/N baseline pass (the failure-set)."""
    fs: dict[str, list[str]] = {}
    for r in results:
        if r.in_failure_set:
            fs.setdefault(r.consumer, []).append(r.task)
    return fs


def solvable_set(results: list[BaselineResult]) -> dict[str, list[str]]:
    """Per-consumer list of task ids the model can already solve alone (skip these)."""
    sv: dict[str, list[str]] = {}
    for r in results:
        if not r.in_failure_set:
            sv.setdefault(r.consumer, []).append(r.task)
    return sv
