"""B3: unified experience provider — vector recall + P/G re-rank + control arms.

One provider serves every arm A0..A9 over the *same* scaffold, so arms differ only
in *what experience is injected*:

    A0 none      A1 irrelevant   A2 misleading
    A3 good L1   A4 good L2      A5 good L3
    A8 Ours = vector recall (relevance) → P/G re-rank (usefulness) → best
    A9 oracle = the known-good L1

The contribution wedge is A8: recall gives *relevant* candidates (what CoPS / Agent
KB stop at); P/G re-rank then picks the *useful* one. Relevance ≠ usefulness.
"""

from __future__ import annotations

from dataclasses import dataclass

from evomemory_sync import encoder
from evomemory_sync.quality_sidecar import QualitySidecar

from .exp_quality import add_experience

ARMS = ["A0", "A1", "A2", "A3", "A4", "A5", "A8", "A9"]
ARM_LABEL = {
    "A0": "none", "A1": "irrelevant", "A2": "misleading",
    "A3": "good-L1", "A4": "good-L2", "A5": "good-L3",
    "A8": "Ours(recall+P/G)", "A9": "oracle",
}


@dataclass(frozen=True)
class Experience:
    id: str
    text: str        # the guidance injected into the consumer
    context: str     # short situation text, used for embedding ψ(e) and recall
    task_id: str     # which task this experience targets
    kind: str        # task kind
    level: str       # L1 / L2 / L3 / -
    label: str       # good / misleading / irrelevant


class ExperienceProvider:
    def __init__(self, library: list[Experience], sidecar: QualitySidecar):
        self.library = library
        self.sidecar = sidecar

    # --- retrieval primitives -------------------------------------------
    def recall(self, query: str, top_n: int = 5) -> list[tuple[Experience, float]]:
        """Vector recall: rank the whole library by sim(query, e.context), top-N."""
        sims = encoder.sim_to(query, [e.context for e in self.library])
        ranked = sorted(zip(self.library, sims), key=lambda kv: -kv[1])
        return ranked[:top_n]

    def rerank(self, candidates: list[Experience]) -> list[tuple[Experience, dict]]:
        """P/G re-rank: score each candidate by (P, G) from the sidecar, P first."""
        scored = [(e, self.sidecar.quality_v2(e.id)) for e in candidates]
        scored.sort(key=lambda eq: (eq[1]["P"], eq[1]["G"]), reverse=True)
        return scored

    # --- arm selection ---------------------------------------------------
    def _good(self, task_id: str, level: str) -> Experience | None:
        for e in self.library:
            if e.task_id == task_id and e.label == "good" and e.level == level:
                return e
        return None

    def select(self, task, arm: str, *, top_n: int = 5) -> tuple[str | None, dict]:
        """Return (experience_text_or_None, meta) for the given task and arm."""
        tid = getattr(task, "id", str(task))
        query = getattr(task, "issue", tid)
        meta: dict = {"arm": arm, "label": ARM_LABEL.get(arm, arm)}

        if arm == "A0":
            return None, meta
        if arm == "A1":  # irrelevant: a library item from a different task, vector-far
            far = sorted(
                (e for e in self.library if e.task_id != tid),
                key=lambda e: encoder.sim_to(query, [e.context])[0],
            )
            e = far[0] if far else None
            meta["chosen"] = e.id if e else None
            return (e.text if e else None), meta
        if arm == "A2":  # misleading: wrong-pointer experience for this task
            e = next((x for x in self.library if x.task_id == tid and x.label == "misleading"), None)
            meta["chosen"] = e.id if e else None
            return (e.text if e else None), meta
        if arm in ("A3", "A4", "A5"):
            e = self._good(tid, {"A3": "L1", "A4": "L2", "A5": "L3"}[arm])
            meta["chosen"] = e.id if e else None
            return (e.text if e else None), meta
        if arm == "A9":  # oracle = known good L1
            e = self._good(tid, "L1")
            meta["chosen"] = e.id if e else None
            return (e.text if e else None), meta
        if arm == "A8":  # Ours: recall (relevance) → P/G re-rank (usefulness)
            recalled = [e for e, _ in self.recall(query, top_n=top_n)]
            if not recalled:
                return None, meta
            scored = self.rerank(recalled)
            e, q = scored[0]
            meta.update(chosen=e.id, P=round(q["P"], 3), G=round(q["G"], 3),
                        recalled=[x.id for x in recalled])
            return e.text, meta
        raise ValueError(f"unknown arm {arm!r}")


# --- Flask pilot library (good L1/L2/L3 + misleading per task) -------------

_MISLEADING = {
    "flask_blueprint_empty":
        "The bug is in src/flask/app.py, inside Flask.__init__. Add there:\n"
        "        if not import_name:\n            raise ValueError(\"name required\")\n"
        "Edit app.py and run_tests.",
    "flask_blueprint_dot":
        "The bug is in src/flask/cli.py, in the command name handling. Add a check that "
        "rejects names containing '.' there, then run_tests.",
    "flask_open_resource_mode":
        "The bug is in src/flask/helpers.py, in send_file. Add a mode check that rejects "
        "write modes there, then run_tests.",
}
_GOOD_L2 = {
    "validation":
        "For a constructor-validation bug, add the missing guard at the TOP of the class "
        "__init__, next to the existing argument checks, raising the same error type (ValueError).",
    "io-guard":
        "For an I/O-mode guard, validate the mode argument just before the resource is opened, "
        "raising ValueError for disallowed modes.",
}
_GOOD_L3 = {
    "validation":
        "Validate inputs at the boundary where an object is created; fail fast with a clear "
        "error rather than allowing an invalid object to exist.",
    "io-guard":
        "Constrain side-effecting operations at their entry point; reject unsafe arguments "
        "before performing the effect.",
}


def build_flask_library(sidecar: QualitySidecar | None = None) -> tuple[list[Experience], QualitySidecar]:
    """Pilot library for the Flask tasks, with the sidecar seeded so P separates
    good (verified success) from misleading (verified failure)."""
    from .swe_flask import FLASK_TASKS

    sc = sidecar or QualitySidecar()
    lib: list[Experience] = []

    def add(e: Experience, *, successes: int, trials: int, sim: float) -> None:
        lib.append(e)
        add_experience(sc, e.id, text=e.text)
        for i in range(trials):
            sc.record_verification(e.id, task_kind=e.kind, success=(i < successes), sim=sim)

    for t in FLASK_TASKS:
        add(Experience(f"good_L1::{t.id}", t.experience, t.issue, t.id, t.kind, "L1", "good"),
            successes=3, trials=3, sim=1.0)
        add(Experience(f"misleading::{t.id}", _MISLEADING[t.id], t.issue, t.id, t.kind, "L1", "misleading"),
            successes=0, trials=2, sim=0.9)
        if t.kind in _GOOD_L2:
            add(Experience(f"good_L2::{t.id}", _GOOD_L2[t.kind], t.issue, t.id, t.kind, "L2", "good"),
                successes=1, trials=1, sim=0.8)
            add(Experience(f"good_L3::{t.id}", _GOOD_L3[t.kind], t.issue, t.id, t.kind, "L3", "good"),
                successes=0, trials=0, sim=1.0)
    return lib, sc
