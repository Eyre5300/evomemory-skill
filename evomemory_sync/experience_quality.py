"""Computable experience quality: P(e) and G(e) (Pareto proposal §3).

Two complementary, automatically computable scores for one experience ``e``:

    P(e) = P_empirical(e) * ContextDensity(e)          # precision / reliability
    G(e) = G_structural(e) * G_empirical(e)            # generalization / breadth

Design constraints (from the proposal):

* **P_empirical** — Bayesian-smoothed verification success rate. Never-verified
  experiences sit at the no-information prior 0.5 (no good/bad assumption).
* **ContextDensity** — already implemented in :mod:`evomemory_sync.context_density`
  as ``1 - H(context|e)/H(context)`` over measurable decision dimensions. This
  module *consumes* a context-density float; it does not recompute it (the
  benchmark-specific dimension builders live in ``context_density``).
* **G_structural** — from the *text* abstraction level only (count of concrete
  constraints: pinned files/functions/literals…). Fewer constraints → more
  general. Computable at upload time, no verification data needed.
* **G_empirical** — from real verification history across distinct task *kinds*.
  Cold start (zero verifications) is 1.0 so new experiences are not pre-penalized.

All functions are pure and dependency-free (only stdlib + the local
``context_density`` constraint helpers), so they are cheap to unit-test and carry
no API cost. Default constants are calibrated to reproduce the worked examples in
the proposal; they are intentionally exposed as parameters because the calibration
itself is a validation experiment (proposal §3, ablations).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .context_density import ExperienceConstraints, extract_experience_constraints

# --- P(e) -----------------------------------------------------------------


def p_empirical(
    successes: int,
    trials: int,
    *,
    prior_alpha: float = 0.5,
    prior_beta: float = 0.5,
) -> float:
    """Bayesian (Beta) posterior-mean success rate of an experience.

    ``(successes + alpha) / (trials + alpha + beta)``.

    The default Jeffreys prior (``alpha = beta = 0.5``) reproduces the proposal's
    examples: 8/10 verified → ``(8+0.5)/(10+1) ≈ 0.773`` and zero verifications →
    ``0.5/1 = 0.5`` (no-information prior, neither rewarded nor penalized).
    """
    if trials < 0 or successes < 0 or successes > trials:
        raise ValueError(f"need 0 <= successes <= trials, got {successes}/{trials}")
    return (successes + prior_alpha) / (trials + prior_alpha + prior_beta)


def aggregate_p(p_emp: float, context_density: float) -> float:
    """P(e) = P_empirical(e) * ContextDensity(e), clamped to [0, 1]."""
    return _clamp01(p_emp) * _clamp01(context_density)


# --- G(e) -----------------------------------------------------------------


@dataclass(frozen=True)
class StructuralWeights:
    """Per-constraint-type contribution to the 'how specific is this text' count.

    Hard pins (a concrete file / function / literal value) localize the
    experience to a single context, so they weigh most. Symbols and negative
    hypotheses ("check session, *not* routing") narrow scope but remain partly
    transferable advice, so they weigh less.
    """

    pinned_files: float = 1.0
    pinned_functions: float = 1.0
    literal_parameters: float = 1.0
    pinned_symbols: float = 0.5
    negative_hypotheses: float = 0.5


def weighted_constraint_count(
    constraints: ExperienceConstraints,
    weights: StructuralWeights = StructuralWeights(),
) -> float:
    """Weighted number of concrete constraints in an experience's text."""
    return (
        weights.pinned_files * len(constraints.pinned_files)
        + weights.pinned_functions * len(constraints.pinned_functions)
        + weights.literal_parameters * len(constraints.literal_parameters)
        + weights.pinned_symbols * len(constraints.pinned_symbols)
        + weights.negative_hypotheses * len(constraints.negative_hypotheses)
    )


def g_structural(
    constraint_count: float,
    *,
    half_saturation: float = 3.0,
) -> float:
    """Structural generalization from concrete-constraint count → [0, 1].

    ``1 / (1 + n / half_saturation)`` — monotonically decreasing in ``n``.

    With the default ``half_saturation = 3.0`` this reproduces the proposal's
    abstraction-level anchors:

    * L3 (no concrete constraints, ``n = 0``)           → ``1.0``
    * L2 (1-2 domain constraints, ``n ≈ 2``)            → ``≈ 0.60``
    * L1 (many file/function/literal pins, ``n ≈ 10``)  → ``≈ 0.23``
    """
    if constraint_count < 0:
        raise ValueError("constraint_count must be >= 0")
    if half_saturation <= 0:
        raise ValueError("half_saturation must be > 0")
    return 1.0 / (1.0 + constraint_count / half_saturation)


def g_structural_from_text(
    problem: str = "",
    solution: str = "",
    *,
    extra_text: str = "",
    weights: StructuralWeights = StructuralWeights(),
    half_saturation: float = 3.0,
) -> float:
    """Convenience: rule-based constraint extraction → weighted count → G_structural."""
    constraints = extract_experience_constraints(problem, solution, extra_text=extra_text)
    n = weighted_constraint_count(constraints, weights)
    return g_structural(n, half_saturation=half_saturation)


def g_empirical(
    kind_successes: int,
    kind_trials: int,
    *,
    cold_start: float = 1.0,
    pseudo_miss: float = 1.0,
) -> float:
    """Empirical generalization: success breadth across distinct task *kinds*.

    Two tasks are the same "kind" when their embeddings exceed the caller's
    similarity threshold (the proposal uses cosine > 0.9); the caller groups
    verification outcomes by kind and passes the per-kind success / trial counts.

    * Zero verifications → ``cold_start`` (default 1.0, no pre-penalty).
    * Otherwise ``kind_successes / (kind_trials + pseudo_miss)`` — a conservative
      estimator that adds one pseudo-miss. Matches the proposal's example:
      verified on 3 kinds, succeeded on 2 → ``2 / (3 + 1) = 0.5``.
    """
    if kind_trials < 0 or kind_successes < 0 or kind_successes > kind_trials:
        raise ValueError(f"need 0 <= successes <= trials, got {kind_successes}/{kind_trials}")
    if kind_trials == 0:
        return _clamp01(cold_start)
    return kind_successes / (kind_trials + pseudo_miss)


def aggregate_g(g_struct: float, g_emp: float) -> float:
    """G(e) = G_structural(e) * G_empirical(e), clamped to [0, 1]."""
    return _clamp01(g_struct) * _clamp01(g_emp)


# --- Combined quality -----------------------------------------------------


@dataclass(frozen=True)
class Quality:
    """Full P/G breakdown for one experience.

    ``P`` and ``G`` are the headline coordinates used for retrieval-time filtering
    (§4.4) and Pareto analysis (§3.4, §5.5). The sub-scores are retained so
    ablations can drop a component (e.g. set ``g_structural`` only) and so the
    "pseudo-generalization" case (high ``g_structural`` but low ``g_empirical``)
    is inspectable.
    """

    p_empirical: float
    context_density: float
    p: float
    g_structural: float
    g_empirical: float
    g: float
    metadata: dict[str, Any] = field(default_factory=dict)

    def dominates(self, other: "Quality", *, strict: bool = True) -> bool:
        """Pareto dominance on the (P, G) plane.

        ``self`` dominates ``other`` when it is no worse on both axes and (when
        ``strict``) strictly better on at least one. Used to flag "dominated"
        experiences (§3.4) during offline analysis — never at serving time.
        """
        ge_both = self.p >= other.p and self.g >= other.g
        if not strict:
            return ge_both
        return ge_both and (self.p > other.p or self.g > other.g)

    def to_dict(self) -> dict[str, Any]:
        return {
            "P": round(self.p, 4),
            "G": round(self.g, 4),
            "p_empirical": round(self.p_empirical, 4),
            "context_density": round(self.context_density, 4),
            "g_structural": round(self.g_structural, 4),
            "g_empirical": round(self.g_empirical, 4),
            "metadata": self.metadata,
        }


def compute_quality(
    *,
    successes: int,
    trials: int,
    context_density: float,
    g_struct: float,
    kind_successes: int,
    kind_trials: int,
    prior_alpha: float = 0.5,
    prior_beta: float = 0.5,
    cold_start: float = 1.0,
    pseudo_miss: float = 1.0,
    metadata: dict[str, Any] | None = None,
) -> Quality:
    """Assemble a :class:`Quality` from raw verification + structural inputs.

    ``context_density`` and ``g_struct`` are passed in already-computed (the
    former from a benchmark-specific dimension builder in ``context_density``,
    the latter from :func:`g_structural_from_text`) so this function stays free of
    benchmark and text-parsing concerns.
    """
    p_emp = p_empirical(successes, trials, prior_alpha=prior_alpha, prior_beta=prior_beta)
    g_emp = g_empirical(kind_successes, kind_trials, cold_start=cold_start, pseudo_miss=pseudo_miss)
    return Quality(
        p_empirical=p_emp,
        context_density=_clamp01(context_density),
        p=aggregate_p(p_emp, context_density),
        g_structural=_clamp01(g_struct),
        g_empirical=g_emp,
        g=aggregate_g(g_struct, g_emp),
        metadata=dict(metadata or {}),
    )


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))
