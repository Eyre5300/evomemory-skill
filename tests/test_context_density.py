"""Tests for computable ContextDensity."""

from evomemory_sync.context_density import (
    apply_constraints_to_branches,
    build_gaia_dimensions,
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


def test_extract_constraints_from_chinese_prose():
    # Regression: rule-based extraction must catch snake_case symbols and the
    # Chinese "设为 N" assignment form, not only English "= N".
    c = extract_experience_constraints(
        "修复登录跳转 bug",
        "改 middleware/session.py 的 expire() 函数，删除 auth_token cookie，把 retries 设为 3",
    )
    assert "middleware/session.py" in c.pinned_files
    assert "expire" in c.pinned_functions
    assert "auth_token" in c.pinned_symbols
    assert any("3" in lit for lit in c.literal_parameters)


def test_build_gaia_dimensions_more_pins_more_density():
    vague = extract_experience_constraints("研究类任务", "用工具查一下然后回答")
    precise = extract_experience_constraints(
        "GAIA 多步检索",
        "用 web_search 打开 source_table.csv，把 max_rows 设为 50，读取 total_count 列求和",
    )
    common = dict(available_tools=12, candidate_sources=8, operations_per_source=6, answer_formats=4)
    r_vague = compute_context_density(build_gaia_dimensions(constraints=vague, **common))
    r_precise = compute_context_density(build_gaia_dimensions(constraints=precise, **common))
    assert r_precise.context_density > r_vague.context_density


def test_apply_constraints_pin_to_one():
    assert apply_constraints_to_branches(54, pinned_count=1) == 1


def test_zero_dimensions_density_one():
    r = compute_context_density([])
    assert r.context_density == 1.0
