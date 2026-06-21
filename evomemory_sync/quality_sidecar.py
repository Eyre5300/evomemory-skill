"""Client-side P/G quality sidecar (Pareto proposal §3, §4.4).

A local SQLite store, keyed by experience id, that holds each experience's
structural quality (ContextDensity, G_structural — computed once at upload) plus
its accumulating verification history (per-kind success/trial counts). The combined
P(e) and G(e) are derived on demand via :mod:`evomemory_sync.experience_quality`.

This is the "client sidecar" approach: P/G live here, not on the Hub, so retrieval
can rank/filter by quality without any server-side schema change.

v2 (paper metrics, deterministic / LLM-free) is available alongside v1:
``quality_v2`` derives P from the similarity-weighted Beta posterior over each
verification's (sim, outcome) and G from the MDL description-length penalty on the
experience text. ``record_verification`` accepts a per-verification ``sim`` weight
(default 1.0). v1 (``quality``) is kept for backward-compat and ablations.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from .experience_quality import (
    ComplexityWeights,
    Quality,
    compute_quality,
    generalization_mdl,
    p_weighted,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS experiences (
    eid             TEXT PRIMARY KEY,
    context_density REAL NOT NULL DEFAULT 0.5,
    g_structural    REAL NOT NULL DEFAULT 0.5,
    text            TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS verifications (
    eid       TEXT NOT NULL,
    task_kind TEXT NOT NULL,
    success   INTEGER NOT NULL,
    sim       REAL NOT NULL DEFAULT 1.0
);
"""


@dataclass
class QualitySidecar:
    path: str = ":memory:"

    def __post_init__(self):
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._con = sqlite3.connect(self.path)
        self._con.executescript(_SCHEMA)
        # Migrate pre-v2 DBs that lack the per-verification ``sim`` column.
        cols = {r[1] for r in self._con.execute("PRAGMA table_info(verifications)").fetchall()}
        if "sim" not in cols:
            self._con.execute("ALTER TABLE verifications ADD COLUMN sim REAL NOT NULL DEFAULT 1.0")
        self._con.commit()

    def close(self) -> None:
        self._con.close()

    # --- writes ----------------------------------------------------------

    def upsert_structural(self, eid: str, *, context_density: float, g_structural: float,
                          text: str = "") -> None:
        """Record the upload-time structural scores for an experience."""
        self._con.execute(
            "INSERT INTO experiences(eid, context_density, g_structural, text) VALUES(?,?,?,?) "
            "ON CONFLICT(eid) DO UPDATE SET context_density=excluded.context_density, "
            "g_structural=excluded.g_structural, text=excluded.text",
            (eid, float(context_density), float(g_structural), text),
        )
        self._con.commit()

    def record_verification(self, eid: str, *, task_kind: str, success: bool,
                            sim: float = 1.0) -> None:
        """Append one verification outcome.

        Feeds v1 (per-kind success/trial) and v2 (the similarity-weighted Beta
        posterior). ``sim`` is the verification task's similarity to the
        experience context (default 1.0 → counts as a full trial, so v2 P reduces
        to the plain Beta posterior when sims are not supplied).
        """
        self._con.execute(
            "INSERT INTO verifications(eid, task_kind, success, sim) VALUES(?,?,?,?)",
            (eid, task_kind, int(bool(success)), float(sim)),
        )
        self._con.commit()

    # --- reads -----------------------------------------------------------

    def _counts(self, eid: str) -> tuple[int, int, int, int]:
        rows = self._con.execute(
            "SELECT task_kind, success FROM verifications WHERE eid=?", (eid,)
        ).fetchall()
        trials = len(rows)
        successes = sum(s for _, s in rows)
        kinds: dict[str, int] = {}
        for kind, s in rows:
            kinds[kind] = max(kinds.get(kind, 0), s)
        kind_trials = len(kinds)
        kind_successes = sum(kinds.values())
        return successes, trials, kind_successes, kind_trials

    def quality(self, eid: str) -> Quality:
        row = self._con.execute(
            "SELECT context_density, g_structural FROM experiences WHERE eid=?", (eid,)
        ).fetchone()
        cd, gs = (row if row else (0.5, 0.5))
        successes, trials, k_succ, k_trials = self._counts(eid)
        return compute_quality(
            successes=successes, trials=trials, context_density=cd, g_struct=gs,
            kind_successes=k_succ, kind_trials=k_trials,
            metadata={"eid": eid, "trials": trials, "successes": successes,
                      "kind_trials": k_trials, "kind_successes": k_succ},
        )

    def eids(self) -> list[str]:
        return [r[0] for r in self._con.execute("SELECT eid FROM experiences ORDER BY eid").fetchall()]

    def ranked(self, by: str = "p") -> list[tuple[str, Quality]]:
        """All experiences with their Quality, sorted by P (default) or G, descending."""
        items = [(eid, self.quality(eid)) for eid in self.eids()]
        key = (lambda kv: kv[1].g) if by == "g" else (lambda kv: kv[1].p)
        return sorted(items, key=key, reverse=True)

    def best(self, *, min_p: float = 0.0, min_g: float = 0.0) -> tuple[str, Quality] | None:
        """Retrieval-time selection: highest-P experience meeting the P/G thresholds."""
        for eid, q in self.ranked(by="p"):
            if q.p >= min_p and q.g >= min_g:
                return eid, q
        return None

    # --- v2 reads (paper metrics: similarity-weighted P, MDL G) -----------

    def _pairs(self, eid: str) -> tuple[list[float], list[int]]:
        rows = self._con.execute(
            "SELECT sim, success FROM verifications WHERE eid=?", (eid,)
        ).fetchall()
        sims = [float(s) for s, _ in rows]
        outcomes = [int(y) for _, y in rows]
        return sims, outcomes

    def quality_v2(self, eid: str, *, lam: float = 0.1,
                   weights: ComplexityWeights = ComplexityWeights()) -> dict:
        """v2 P/G for one experience (deterministic, LLM-free).

        P = similarity-weighted Beta posterior over its (sim, outcome) log.
        G = exp(-lam * L) with L = w1*N_cond + w2*N_ent + w3*N_depth on its text.
        """
        row = self._con.execute(
            "SELECT text FROM experiences WHERE eid=?", (eid,)
        ).fetchone()
        text = row[0] if row and row[0] else ""
        sims, outcomes = self._pairs(eid)
        p = p_weighted(sims, outcomes)
        g = generalization_mdl(solution=text, lam=lam, weights=weights)
        return {
            "eid": eid,
            "P": p["P"], "a_P": p["a_P"], "b_P": p["b_P"],
            "G": g["G"], "L": g["L"],
            "N_cond": g["N_cond"], "N_ent": g["N_ent"], "N_depth": g["N_depth"],
            "trials": len(outcomes),
        }

    def ranked_v2(self, by: str = "p", *, lam: float = 0.1,
                  weights: ComplexityWeights = ComplexityWeights()) -> list[dict]:
        """All experiences with their v2 quality, sorted by P (default) or G, desc."""
        items = [self.quality_v2(eid, lam=lam, weights=weights) for eid in self.eids()]
        key = (lambda q: q["G"]) if by == "g" else (lambda q: q["P"])
        return sorted(items, key=key, reverse=True)

    def best_v2(self, *, min_p: float = 0.0, min_g: float = 0.0, lam: float = 0.1,
                weights: ComplexityWeights = ComplexityWeights()) -> dict | None:
        """v2 retrieval-time selection: highest-P experience meeting P/G thresholds."""
        for q in self.ranked_v2(by="p", lam=lam, weights=weights):
            if q["P"] >= min_p and q["G"] >= min_g:
                return q
        return None

    def __iter__(self) -> Iterator[str]:
        return iter(self.eids())
