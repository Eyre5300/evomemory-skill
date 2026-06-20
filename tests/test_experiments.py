"""Tests for the closed-loop MVP harness: grader robustness, tools, no answer leak."""

import json
from pathlib import Path

import pytest

from experiments.tasks import TASKS, Task, grade
from experiments import tools as toolkit

REPO = Path(__file__).resolve().parent.parent


# --- grader robustness (the flip claim depends entirely on this) ----------

LAST2 = next(t for t in TASKS if t.id == "last2_3pow2024")  # answer "81"


def test_grade_exact_and_boxed():
    assert grade(LAST2, "81")
    assert grade(LAST2, "\\boxed{81}")
    assert grade(LAST2, "...therefore the answer is 81")
    assert grade(LAST2, "The last two digits are 81.")


def test_grade_rejects_wrong_and_empty():
    assert not grade(LAST2, "63")          # the real baseline failure value
    assert not grade(LAST2, "01")
    assert not grade(LAST2, "")
    # must not false-positive on a number that merely contains the answer
    assert not grade(LAST2, "8100")
    assert not grade(LAST2, "the result is 811")


def test_grade_uses_final_number_not_substring():
    # earlier bug: substring match let "1" match anything containing a 1
    one = Task("x", "q", "1")
    assert not grade(one, "the value is 100")   # last number 100, not 1
    assert grade(one, "after reducing, it is 1")


def test_grade_negative_numbers():
    neg = next(t for t in TASKS if t.id == "sum_minus_odds")  # -4950
    assert grade(neg, "the difference is -4950")
    assert not grade(neg, "4950")


# --- tools ---------------------------------------------------------------


def test_calculate_correct():
    assert toolkit.calculate("(123 * 7 + 19) ** 2 - 5000") == "769400"
    assert toolkit.execute("calculate", {"expression": "2+2"}) == "4"


def test_calculate_rejects_unsafe():
    # no arbitrary eval: names / calls must not execute
    assert toolkit.calculate("__import__('os')").startswith("ERROR")


def test_tool_schemas_match_registry():
    assert {t["name"] for t in toolkit.anthropic_tools()} == set(toolkit.REGISTRY)
    assert {t["function"]["name"] for t in toolkit.openai_tools()} == set(toolkit.REGISTRY)


# --- no answer leak: experiences must teach method, not state the answer --


def test_code_task_is_buggy_and_fixable():
    # The code-repair task must start failing and pass after the intended one-line fix.
    from experiments.code_env import CodeEnv, code_executor, make_workdir

    env = CodeEnv(make_workdir())
    try:
        ex = code_executor(env)
        assert not env.tests_pass(), "pristine project should fail (it has the bug)"
        out = ex("edit_file", {"path": "store/pricing.py",
                               "old": "quantity >= BULK_THRESHOLD",
                               "new": "quantity > BULK_THRESHOLD"})
        assert out.startswith("OK"), out
        assert env.tests_pass(), "project should pass after the threshold fix"
    finally:
        env.cleanup()


def test_code_experience_does_not_leak_literal_fix():
    # The pruning experience should point to the file/nature, not hand over the diff.
    exp = (REPO / "experiments" / "code_experience.txt").read_text(encoding="utf-8")
    assert "pricing.py" in exp                      # prunes the search space
    assert ">= BULK_THRESHOLD" not in exp           # but does not state the buggy code
    assert "> BULK_THRESHOLD" not in exp            # nor the literal fix


def test_sidecar_cold_then_verified_p_rises():
    from evomemory_sync.quality_sidecar import QualitySidecar

    s = QualitySidecar()
    try:
        s.upsert_structural("e1", context_density=0.8, g_structural=0.5)
        cold = s.quality("e1")
        assert cold.p == pytest.approx(0.5 * 0.8, abs=1e-6)  # prior 0.5 x CD
        for _ in range(4):
            s.record_verification("e1", task_kind="k", success=True)
        assert s.quality("e1").p > cold.p  # passing verifications lift P
    finally:
        s.close()


def test_sidecar_p_separates_working_from_misleading():
    # M3 essence: two experiences with IDENTICAL structural scores; only empirical
    # verification (P_empirical) tells the working one from the misleading one.
    from evomemory_sync.quality_sidecar import QualitySidecar

    s = QualitySidecar()
    try:
        s.upsert_structural("good", context_density=0.8, g_structural=0.4)
        s.upsert_structural("bad", context_density=0.8, g_structural=0.4)
        for _ in range(3):
            s.record_verification("good", task_kind="k", success=True)
            s.record_verification("bad", task_kind="k", success=False)
        ranked = s.ranked("p")
        assert ranked[0][0] == "good"
        assert s.quality("good").p > s.quality("bad").p
        assert s.best(min_p=0.5)[0] == "good"
    finally:
        s.close()


def test_all_code_tasks_start_failing():
    # Every task in the suite must begin with a failing test (the bug is present).
    from experiments.code_env import CodeEnv, make_workdir
    from experiments.code_tasks import TASKS

    assert len(TASKS) >= 4
    for t in TASKS:
        env = CodeEnv(make_workdir(t.id))
        try:
            assert not env.tests_pass(), f"{t.id} should start failing (bug present)"
        finally:
            env.cleanup()


def test_abstraction_parse_json_robust():
    from evomemory_sync.abstraction import _parse_json

    assert _parse_json('{"l1":"a","l2":"b","l3":"c"}')["l2"] == "b"
    assert _parse_json("```json\n{\"l1\":\"x\"}\n```")["l1"] == "x"
    assert _parse_json('here is the result: {"l3":"y"} done')["l3"] == "y"


def test_experiences_do_not_leak_multichar_answers():
    exps = json.loads((REPO / "experiments" / "experiences.json").read_text(encoding="utf-8"))
    by_id = {t.id: t for t in TASKS}
    for tid, text in exps.items():
        ans = by_id[tid].answer.strip()
        # only meaningful for multi-character numeric answers (single digits can
        # legitimately appear inside a method, e.g. a cycle "7,9,3,1")
        if len(ans) >= 2 and any(c.isdigit() for c in ans):
            assert ans not in text, f"experience for {tid} leaks the answer {ans!r}"
