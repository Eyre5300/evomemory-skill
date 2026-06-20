"""Unit tests for experience_quality (P/G metrics, proposal §3)."""


import pytest

from evomemory_sync.context_density import extract_experience_constraints
from evomemory_sync.experience_quality import (
    Quality,
    aggregate_g,
    aggregate_p,
    compute_quality,
    g_empirical,
    g_structural,
    g_structural_from_text,
    p_empirical,
    weighted_constraint_count,
)


# --- P_empirical ----------------------------------------------------------


def test_p_empirical_matches_proposal_example():
    # Proposal: verified 10x, succeeded 8x -> P_emp ~= 0.78 (Jeffreys prior).
    assert p_empirical(8, 10) == pytest.approx(8.5 / 11, abs=1e-6)
    assert round(p_empirical(8, 10), 2) == 0.77


def test_p_empirical_no_information_prior_is_half():
    # Never verified -> 0.5, no good/bad assumption.
    assert p_empirical(0, 0) == 0.5


def test_p_empirical_monotonic_in_successes():
    assert p_empirical(2, 10) < p_empirical(5, 10) < p_empirical(9, 10)


def test_p_empirical_rejects_bad_counts():
    with pytest.raises(ValueError):
        p_empirical(5, 3)
    with pytest.raises(ValueError):
        p_empirical(-1, 3)


# --- G_structural ---------------------------------------------------------


def test_g_structural_abstraction_anchors():
    # L3 (no constraints) -> ~1.0, L2 (~2) -> ~0.6, L1 (~10) -> ~0.2.
    assert g_structural(0) == 1.0
    assert g_structural(2) == pytest.approx(0.6, abs=0.02)
    assert g_structural(10) < 0.3


def test_g_structural_strictly_decreasing():
    vals = [g_structural(n) for n in range(0, 12)]
    assert all(a > b for a, b in zip(vals, vals[1:]))


def test_g_structural_from_text_specific_vs_abstract():
    specific = g_structural_from_text(
        problem="修复登录跳转 bug",
        solution="改 middleware/session.py 的 expire() 函数，删除 auth_token cookie，把 retries 设为 3",
    )
    abstract = g_structural_from_text(
        problem="排查复杂系统 bug",
        solution="先定位数据流：状态从哪来、经过谁、到哪去，而非从表象倒推",
    )
    assert abstract == pytest.approx(1.0)
    assert specific < abstract
    # Specific text pins a file, a function, a snake_case symbol and a literal
    # (incl. the Chinese "设为 3" assignment), so it sits clearly below the L2
    # anchor — well under 0.6.
    assert specific < 0.55


def test_weighted_constraint_count_counts_pins():
    c = extract_experience_constraints(
        "", "改 middleware/session.py 的 expire()，retries = 3"
    )
    # at least one file + one function + one literal pinned
    assert len(c.pinned_files) >= 1
    assert weighted_constraint_count(c) >= 2.0


# --- G_empirical ----------------------------------------------------------


def test_g_empirical_cold_start_is_one():
    assert g_empirical(0, 0) == 1.0


def test_g_empirical_matches_proposal_example():
    # Verified on 3 kinds, succeeded on 2 -> 2/(3+1) = 0.5.
    assert g_empirical(2, 3) == pytest.approx(0.5, abs=1e-6)


def test_g_empirical_rejects_bad_counts():
    with pytest.raises(ValueError):
        g_empirical(4, 3)


# --- aggregation & clamping ----------------------------------------------


def test_aggregate_clamps_to_unit_interval():
    assert aggregate_p(1.5, 0.8) == pytest.approx(0.8)
    assert aggregate_g(-0.2, 0.9) == 0.0
    assert 0.0 <= aggregate_p(0.7, 0.6) <= 1.0


# --- combined Quality -----------------------------------------------------


def test_compute_quality_end_to_end():
    q = compute_quality(
        successes=8,
        trials=10,
        context_density=0.9,
        g_struct=0.6,
        kind_successes=2,
        kind_trials=3,
    )
    assert q.p == pytest.approx(p_empirical(8, 10) * 0.9, abs=1e-6)
    assert q.g == pytest.approx(0.6 * 0.5, abs=1e-6)
    d = q.to_dict()
    assert set(d) >= {"P", "G", "p_empirical", "g_structural", "g_empirical"}


def test_pseudo_generalization_is_penalized():
    # High structural generality but poor real-world transfer -> low G.
    pseudo = compute_quality(
        successes=5, trials=5, context_density=0.5,
        g_struct=1.0, kind_successes=0, kind_trials=5,
    )
    genuine = compute_quality(
        successes=5, trials=5, context_density=0.5,
        g_struct=0.6, kind_successes=4, kind_trials=4,
    )
    assert pseudo.g_structural > genuine.g_structural  # "looks" more general
    assert pseudo.g < genuine.g                        # but actually transfers worse


def test_quality_pareto_dominance():
    strong = Quality(0.9, 0.9, 0.81, 0.8, 0.9, 0.72)
    weak = Quality(0.5, 0.5, 0.25, 0.5, 0.5, 0.25)
    assert strong.dominates(weak)
    assert not weak.dominates(strong)
    # equal on both axes -> not strict domination
    assert not strong.dominates(strong)
    assert strong.dominates(strong, strict=False)
