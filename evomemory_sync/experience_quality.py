"""Computable experience quality: P(e) and G(e) (Pareto proposal §3).

Two complementary, automatically computable scores for one experience ``e``.

**v2 (paper version, fusion of the MDL/Occam idea)** — the headline metrics:

    P(e) = similarity-weighted Beta posterior mean   # precision / reliability
    G(e) = exp(-lambda * L(E))                        # generalization (MDL penalty)
    L(E) = w1*N_cond + w2*N_ent + w3*N_depth          # description-length cost

Both are deterministic and LLM-free:

* **P(e)** (:func:`p_weighted`) — each verification i contributes weight ``s_i``
  (its embedding similarity to the experience context) instead of a full count.
  ``y_i`` is the objective pass/fail of a unit test, never an LLM judgement. With
  all ``s_i = 1`` it reduces to the plain Beta posterior :func:`p_empirical`.
* **G(e)** (:func:`generalization_mdl`) — the more an experience pins itself to
  concrete instances (``N_ent``) and stacks situational predicates (``N_cond``,
  ``N_depth``), the longer its minimal description and the worse it generalizes.
  All three counts come from regex / bracket-scan over the text — no model call.

**v1 (legacy, kept for backward-compat and ablations)**:

    P(e) = P_empirical(e) * ContextDensity(e)
    G(e) = G_structural(e) * G_empirical(e)

All functions are pure and dependency-free (only stdlib + the local
``context_density`` constraint helpers), so they are cheap to unit-test and carry
no API cost. Default constants are calibrated to reproduce the worked examples in
the proposal; they are intentionally exposed as parameters because the calibration
itself is a validation experiment (proposal §3, ablations).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Sequence

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
    # Negative hypotheses ("check X, not Y") are transferable advice, not a concrete
    # constraint (model/file/parameter name), so they do NOT count toward textual
    # specificity. They still feed ContextDensity's search pruning. (M6 finding:
    # counting them made abstract principles look specific, e.g. "rather than …".)
    negative_hypotheses: float = 0.0


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


# ==========================================================================
# v2 (paper version): deterministic, LLM-free P(e) and G(e)
# ==========================================================================
#
# P(e) — similarity-weighted Beta posterior (relevance-weighted reliability).
# G(e) — description-length penalty G = exp(-lambda * L(E)) with
#        L(E) = w1*N_cond + w2*N_ent + w3*N_depth, every term counted by
#        regex / bracket-scan over the experience text (no LLM, fully reproducible).


def p_weighted(
    sims: Sequence[float],
    outcomes: Sequence[int],
    *,
    prior_alpha: float = 0.5,
    prior_beta: float = 0.5,
) -> dict[str, float]:
    """Similarity-weighted Beta posterior mean of success (paper P(e)).

    Each verification ``i`` contributes weight ``s_i`` (its similarity to the
    experience's context) rather than a full count::

        a_P = alpha + Σ s_i · y_i ,   b_P = beta + Σ s_i · (1 - y_i)
        P   = a_P / (a_P + b_P)

    ``y_i`` is the objective pass/fail of a test (0/1), never an LLM score. With
    all ``s_i = 1`` this reduces exactly to :func:`p_empirical`. Returns the
    posterior parameters and the mean (the Beta(a_P, b_P) also yields a CI).
    """
    if len(sims) != len(outcomes):
        raise ValueError("sims and outcomes must have equal length")
    a = float(prior_alpha)
    b = float(prior_beta)
    for s, y in zip(sims, outcomes):
        if y not in (0, 1):
            raise ValueError(f"outcomes must be 0/1, got {y!r}")
        s = _clamp01(s)
        a += s * y
        b += s * (1 - y)
    return {"a_P": a, "b_P": b, "P": a / (a + b)}


# --- G(e) v2: description-length (MDL / Occam) penalty ---------------------

# Condition / branch markers: English & Chinese conditionals, comparison
# operators, and explicit logical operators. Non-capturing groups so
# ``findall`` returns full matches and ``len`` is the count.
_COND_RE = re.compile(
    r"\b(?:if|when|whenever|unless|elif|case|switch)\b"   # English conditionals
    r"|如果|若|当|除非|否则|每当|只要"                      # Chinese conditionals
    r"|>=|<=|==|!=|<|>"                                    # comparison operators
    r"|&&|\|\|",                                           # explicit logical ops
    re.IGNORECASE,
)
# Sequential action-chain markers (each adds one step of logical depth).
_CHAIN_RE = re.compile(
    r"\b(?:then|next|afterwards?|finally)\b|然后|接着|之后|最后",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ComplexityWeights:
    """Per-term weights for the description-length cost L(E) (Gemini defaults)."""

    conditions: float = 1.0     # w1 · N_cond
    entities: float = 0.5       # w2 · N_ent
    depth: float = 1.0          # w3 · N_depth


def count_conditions(text: str) -> int:
    """N_cond — deterministic count of condition / branch markers (no LLM)."""
    return len(_COND_RE.findall(text))


def count_nesting_depth(text: str) -> int:
    """N_depth — 1 + max bracket nesting + action-chain steps (deterministic).

    A flat single-action instruction scores 1; nested brackets and chained
    ``then``/``然后`` actions add depth. Pure stack-scan, no parsing model.
    """
    depth = max_depth = 0
    for ch in text:
        if ch in "([{":
            depth += 1
            max_depth = max(max_depth, depth)
        elif ch in ")]}":
            depth = max(0, depth - 1)
    chain_steps = len(_CHAIN_RE.findall(text))
    return 1 + max_depth + chain_steps


def count_entities(constraints: ExperienceConstraints) -> int:
    """N_ent — bound concrete entities (files + functions + symbols + literals).

    Reuses the existing rule-based extractor; negative hypotheses are excluded
    (they are transferable advice, not a binding to one instance — M6 finding).
    """
    return (
        len(constraints.pinned_files)
        + len(constraints.pinned_functions)
        + len(constraints.pinned_symbols)
        + len(constraints.literal_parameters)
    )


def description_length(
    problem: str = "",
    solution: str = "",
    *,
    extra_text: str = "",
    weights: ComplexityWeights = ComplexityWeights(),
) -> dict[str, float]:
    """L(E) = w1*N_cond + w2*N_ent + w3*N_depth from experience text (deterministic)."""
    text = "\n".join(p for p in (problem, solution, extra_text) if p)
    constraints = extract_experience_constraints(problem, solution, extra_text=extra_text)
    n_cond = count_conditions(text)
    n_ent = count_entities(constraints)
    n_depth = count_nesting_depth(text)
    L = weights.conditions * n_cond + weights.entities * n_ent + weights.depth * n_depth
    return {"N_cond": n_cond, "N_ent": n_ent, "N_depth": n_depth, "L": float(L)}


def g_mdl(description_length_L: float, *, lam: float = 0.1) -> float:
    """G(e) = exp(-lambda · L(E)) ∈ (0, 1]. Lower description length → higher G."""
    if description_length_L < 0:
        raise ValueError("description length must be >= 0")
    if lam < 0:
        raise ValueError("lam must be >= 0")
    return math.exp(-lam * float(description_length_L))


def generalization_mdl(
    problem: str = "",
    solution: str = "",
    *,
    extra_text: str = "",
    lam: float = 0.1,
    weights: ComplexityWeights = ComplexityWeights(),
) -> dict[str, float]:
    """End-to-end deterministic G from experience text: counts → L(E) → G."""
    parts = description_length(problem, solution, extra_text=extra_text, weights=weights)
    parts["G"] = g_mdl(parts["L"], lam=lam)
    return parts
