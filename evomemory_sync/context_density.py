"""Computable ContextDensity for agent experiences (Pareto proposal section 3.2).

Experimental helper: not wired into the production extract/upload/search path.

ContextDensity(e) = 1 - H(context|e) / H(context)

All quantities are derived from measurable decision dimensions and optional
agent trajectories; no LLM subjective "how much do you still need to know".
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence


def log2_bits(n: float) -> float:
    """Entropy in bits for a uniform choice among n alternatives (n >= 1)."""
    n = max(1.0, float(n))
    return math.log2(n)


@dataclass
class DecisionDimension:
    """One independent decision axis needed to reproduce a successful fix."""

    name: str
    branches_before: int
    branches_after: int
    measurement: str = ""

    @property
    def h_before(self) -> float:
        return log2_bits(self.branches_before)

    @property
    def h_after(self) -> float:
        return log2_bits(self.branches_after)

    @property
    def eliminated_branches(self) -> int:
        return max(0, self.branches_before - self.branches_after)

    @property
    def bits_pruned(self) -> float:
        return max(0.0, self.h_before - self.h_after)


@dataclass
class TrajectoryStep:
    """One agent step with a measurable branching factor."""

    index: int
    action: str
    branches: int
    note: str = ""

    @property
    def h_bits(self) -> float:
        return log2_bits(self.branches)


@dataclass
class ExperienceConstraints:
    """Structured constraints extracted from experience text (rule-based)."""

    pinned_files: tuple[str, ...] = ()
    pinned_functions: tuple[str, ...] = ()
    pinned_symbols: tuple[str, ...] = ()
    negative_hypotheses: tuple[str, ...] = ()
    literal_parameters: tuple[str, ...] = ()


@dataclass
class ContextDensityResult:
    h_context_bits: float
    h_context_given_e_bits: float
    context_density: float
    dimensions: list[DecisionDimension] = field(default_factory=list)
    trajectory_steps: list[TrajectoryStep] = field(default_factory=list)
    constraints: ExperienceConstraints | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def bits_pruned_total(self) -> float:
        return max(0.0, self.h_context_bits - self.h_context_given_e_bits)

    @property
    def infeasible_fraction_pruned(self) -> float:
        """Combinatorial share of cross-product search space removed."""
        before = 1.0
        after = 1.0
        for d in self.dimensions:
            before *= max(1, d.branches_before)
            after *= max(1, d.branches_after)
        if before <= 0:
            return 0.0
        return 1.0 - (after / before)


_FILE_RE = re.compile(
    r"(?<![\w./-])([A-Za-z0-9_][\w./-]*\.(?:py|js|ts|java|go|rs|cpp|c|h))\b"
)
_FUNC_RE = re.compile(
    r"(?:\b(?:function|method|def|in)\s+[`'\"]?([A-Za-z_]\w*)[`'\"]?|"
    r"`([A-Za-z_]\w+)\(\)`|"
    r"\b([A-Za-z_]\w+)\s*\(\)|"
    r"的\s+(_[A-Za-z]\w+)|"  # Chinese prose: ".../file.py 的 _cstack 中"
    r"\b(_[A-Za-z]\w+)\b)",
    re.IGNORECASE,
)
_NEGATIVE_RE = re.compile(
    r"(?:not|instead of|rather than|而非|不是|不要|避免|don't)\s+"
    r"[`'\"]?([A-Za-z_][\w./-]{1,40})[`'\"]?",
    re.IGNORECASE,
)
_SYMBOL_RE = re.compile(r"`([A-Za-z_]\w+)`|(?:\b)([A-Z][A-Z0-9_]{2,})\b")
_LITERAL_RE = re.compile(
    r"(?:=\s*)([`'\"][^`'\"]+[`'\"]|right\b|\b1\b|[-+]?\d+(?:\.\d+)?|True|False|None)"
)


def extract_experience_constraints(
    problem: str = "",
    solution: str = "",
    *,
    extra_text: str = "",
) -> ExperienceConstraints:
    """Rule-based constraint extraction from recipe / experience prose."""
    text = "\n".join(p for p in (problem, solution, extra_text) if p).strip()
    files: list[str] = []
    seen: set[str] = set()
    for m in _FILE_RE.finditer(text):
        path = m.group(1).replace("\\", "/")
        if path in seen:
            continue
        seen.add(path)
        files.append(path)

    funcs: list[str] = []
    fseen: set[str] = set()
    for m in _FUNC_RE.finditer(text):
        name = next((g for g in m.groups() if g), None)
        if not name or name in fseen:
            continue
        if name.lower() in {"if", "in", "the", "and", "or", "not", "def", "method", "function"}:
            continue
        fseen.add(name)
        funcs.append(name)

    negatives: list[str] = []
    nseen: set[str] = set()
    for m in _NEGATIVE_RE.finditer(text):
        frag = m.group(1).strip()
        key = frag.lower()
        if key in nseen or len(frag) < 3:
            continue
        nseen.add(key)
        negatives.append(frag)

    symbols: list[str] = []
    sseen: set[str] = set()
    for m in _SYMBOL_RE.finditer(text):
        sym = m.group(1) or m.group(2)
        if sym and sym not in sseen:
            sseen.add(sym)
            symbols.append(sym)

    literals: list[str] = []
    lseen: set[str] = set()
    for m in _LITERAL_RE.finditer(text):
        lit = m.group(1)
        if lit not in lseen:
            lseen.add(lit)
            literals.append(lit)

    return ExperienceConstraints(
        pinned_files=tuple(files),
        pinned_functions=tuple(funcs),
        pinned_symbols=tuple(symbols),
        negative_hypotheses=tuple(negatives),
        literal_parameters=tuple(literals),
    )


def apply_constraints_to_branches(
    branches_before: int,
    *,
    pinned_count: int = 0,
    negative_elimination_ratio: float = 0.0,
    literal_pin_count: int = 0,
    literal_space_before: int = 1,
) -> int:
    """Shrink branch count after applying experience constraints."""
    n = max(1, int(branches_before))
    if pinned_count > 0:
        n = 1
    elif negative_elimination_ratio > 0:
        n = max(1, int(math.ceil(n * (1.0 - min(0.95, negative_elimination_ratio)))))
    if literal_pin_count > 0 and literal_space_before > 1:
        divisor = literal_space_before ** min(literal_pin_count, 3)
        n = max(1, int(math.ceil(n / divisor)))
    return max(1, min(n, branches_before))


def compute_context_density(
    dimensions: Sequence[DecisionDimension],
    *,
    trajectory_steps: Sequence[TrajectoryStep] | None = None,
    include_trajectory_in_denominator: bool = False,
) -> ContextDensityResult:
    """
    Compute ContextDensity from decision dimensions (and optional trajectory).

    By default H(context) uses only *task* dimensions (subsystems, file, function,
    edit site, …). Set include_trajectory_in_denominator=True to add per-step
    exploration entropy Σ log2(b_t) — useful when comparing against a concrete run.
    """
    dims = list(dimensions)
    steps = list(trajectory_steps or [])

    h_task_before = sum(d.h_before for d in dims)
    h_task_after = sum(d.h_after for d in dims)
    h_traj = sum(s.h_bits for s in steps)

    h_before = h_task_before + (h_traj if include_trajectory_in_denominator else 0.0)
    # Experience documents the task structure; trajectory choices are already
    # collapsed into dimension pins, so trajectory residual after e is 0.
    h_after = h_task_after

    if h_before <= 0:
        density = 1.0
    else:
        density = 1.0 - (h_after / h_before)
        density = max(0.0, min(1.0, density))

    return ContextDensityResult(
        h_context_bits=h_before,
        h_context_given_e_bits=h_after,
        context_density=density,
        dimensions=dims,
        trajectory_steps=steps,
        metadata={
            "h_task_before": h_task_before,
            "h_task_after": h_task_after,
            "h_trajectory": h_traj,
            "include_trajectory_in_denominator": include_trajectory_in_denominator,
        },
    )


def build_swebench_dimensions(
    *,
    repo_py_files: int,
    module_py_files: int,
    keyword_candidate_files: int,
    target_file_functions: int,
    edit_sites_in_function: int,
    subpackages: int,
    constraints: ExperienceConstraints,
    module_name: str = "",
) -> list[DecisionDimension]:
    """SWE-bench code-repair decision model (computable from repo + issue stats)."""
    c = constraints

    # D1: which subpackage / subsystem
    hyp_before = max(2, subpackages)
    hyp_after = apply_constraints_to_branches(
        hyp_before,
        pinned_count=1 if module_name and module_name.lower() in " ".join(c.pinned_files).lower() else 0,
        negative_elimination_ratio=0.5 * len(c.negative_hypotheses),
    )
    if any(module_name and module_name in f for f in c.pinned_files):
        hyp_after = 1

    # D2: which file in repo (or module)
    file_before = max(1, keyword_candidate_files or module_py_files or repo_py_files)
    file_after = apply_constraints_to_branches(
        file_before,
        pinned_count=len(c.pinned_files),
    )

    # D3: which function / region inside file
    func_before = max(1, target_file_functions)
    func_after = apply_constraints_to_branches(
        func_before,
        pinned_count=len(c.pinned_functions),
    )

    # D4: which statement / edit site (Lite: <=3 hunks, often 1 line)
    edit_before = max(1, edit_sites_in_function)
    edit_after = apply_constraints_to_branches(
        edit_before,
        pinned_count=len(c.literal_parameters),
        literal_pin_count=len(c.literal_parameters),
        literal_space_before=4,
    )
    if c.literal_parameters:
        edit_after = min(edit_after, 2)

    return [
        DecisionDimension(
            "subsystem",
            hyp_before,
            hyp_after,
            f"subpackages={subpackages}, module_hint={module_name!r}",
        ),
        DecisionDimension(
            "target_file",
            file_before,
            file_after,
            f"keyword_candidates={keyword_candidate_files}, module_files={module_py_files}, repo_files={repo_py_files}",
        ),
        DecisionDimension(
            "target_function",
            func_before,
            func_after,
            f"functions_in_target={target_file_functions}",
        ),
        DecisionDimension(
            "edit_site",
            edit_before,
            edit_after,
            f"plausible_sites={edit_sites_in_function}, literals_pinned={len(c.literal_parameters)}",
        ),
    ]


def build_swebench_trajectory(
    *,
    subpackages: int,
    keyword_hits: int,
    module_py_files: int,
    target_file_functions: int,
    test_commands: int = 1,
) -> list[TrajectoryStep]:
    """Typical successful SWE-agent path with measurable branch factors per step."""
    return [
        TrajectoryStep(
            1,
            "triage_subsystem",
            max(2, subpackages),
            "Which top-level area of the repo is implicated?",
        ),
        TrajectoryStep(
            2,
            "search_symbol",
            max(2, keyword_hits),
            "grep/semantic search: files mentioning the failing API",
        ),
        TrajectoryStep(
            3,
            "pick_file",
            max(1, min(keyword_hits, module_py_files)),
            "Open one file among keyword hits",
        ),
        TrajectoryStep(
            4,
            "pick_function",
            max(1, target_file_functions),
            "Locate failing logic inside file",
        ),
        TrajectoryStep(
            5,
            "author_patch",
            max(2, 3),
            "Edit type: wrong assignment / off-by-one / missing call / test-only",
        ),
        TrajectoryStep(
            6,
            "verify",
            max(1, test_commands),
            "Run FAIL_TO_PASS tests",
        ),
    ]


def summarize_result(result: ContextDensityResult) -> dict[str, Any]:
    """JSON-serializable summary for CLI / Hub metadata."""
    return {
        "context_density": round(result.context_density, 4),
        "h_context_bits": round(result.h_context_bits, 3),
        "h_context_given_e_bits": round(result.h_context_given_e_bits, 3),
        "bits_pruned": round(result.bits_pruned_total, 3),
        "infeasible_fraction_pruned": round(result.infeasible_fraction_pruned, 4),
        "dimensions": [
            {
                "name": d.name,
                "branches_before": d.branches_before,
                "branches_after": d.branches_after,
                "bits_before": round(d.h_before, 3),
                "bits_after": round(d.h_after, 3),
                "bits_pruned": round(d.bits_pruned, 3),
                "measurement": d.measurement,
            }
            for d in result.dimensions
        ],
        "trajectory": [
            {
                "step": s.index,
                "action": s.action,
                "branches": s.branches,
                "h_bits": round(s.h_bits, 3),
                "note": s.note,
            }
            for s in result.trajectory_steps
        ],
        "metadata": result.metadata,
    }
