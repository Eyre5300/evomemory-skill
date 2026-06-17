"""Tests for computable ContextDensity."""

from evomemory_sync.context_density import (
    DecisionDimension,
    apply_constraints_to_branches,
    build_swebench_dimensions,
    compute_context_density,
    extract_experience_constraints,
)


def test_extract_constraints_finds_file_and_function():
    problem = "astropy modeling separability_matrix bug"
    solution = (
        "Edit astropy/modeling/separable.py in _cstack: set cright[...] = right, not 1."
    )
    c = extract_experience_constraints(problem, solution)
    assert "astropy/modeling/separable.py" in c.pinned_files
    assert "_cstack" in c.pinned_functions or "cstack" in [f.lower() for f in c.pinned_functions]


def test_context_density_increases_with_precision():
    vague = extract_experience_constraints("modeling bug", "fix separability code")
    precise = extract_experience_constraints(
        "modeling separability_matrix nested CompoundModels",
        "Patch astropy/modeling/separable.py _cstack: cright = right",
    )
    dims_vague = build_swebench_dimensions(
        repo_py_files=889,
        module_py_files=54,
        keyword_candidate_files=12,
        target_file_functions=8,
        edit_sites_in_function=23,
        subpackages=22,
        constraints=vague,
        module_name="modeling",
    )
    dims_precise = build_swebench_dimensions(
        repo_py_files=889,
        module_py_files=54,
        keyword_candidate_files=12,
        target_file_functions=8,
        edit_sites_in_function=23,
        subpackages=22,
        constraints=precise,
        module_name="modeling",
    )
    r_vague = compute_context_density(dims_vague)
    r_precise = compute_context_density(dims_precise)
    assert r_precise.context_density > r_vague.context_density
    assert r_precise.h_context_given_e_bits < r_vague.h_context_given_e_bits


def test_apply_constraints_pin_to_one():
    assert apply_constraints_to_branches(54, pinned_count=1) == 1


def test_zero_dimensions_density_one():
    r = compute_context_density([])
    assert r.context_density == 1.0
