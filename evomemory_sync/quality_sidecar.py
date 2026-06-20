"""Client-side P/G quality sidecar (Pareto proposal §3, §4.4).

A local SQLite store, keyed by experience id, that holds each experience's
structural quality (ContextDensity, G_structural — computed once at upload) plus
its accumulating verification history (per-kind success/trial counts). The combined
P(e) and G(e) are derived on demand via :mod:`evomemory_sync.experience_quality`.

This is the "client sidecar" approach: P/G live here, not on the Hub, so retrieval
can rank/filter by quality without any server-side schema change.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from .experience_quality import Quality, compute_quality

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
    success   INTEGER NOT NULL
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

    def record_verification(self, eid: str, *, task_kind: str, success: bool) -> None:
        """Append one verification outcome (feeds P_empirical and G_empirical)."""
        self._con.execute(
            "INSERT INTO verifications(eid, task_kind, success) VALUES(?,?,?)",
            (eid, task_kind, int(bool(success))),
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

    def __iter__(self) -> Iterator[str]:
        return iter(self.eids())
