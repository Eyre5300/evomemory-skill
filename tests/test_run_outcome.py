"""Tests for run outcome assessment."""

import os
import sys

from langchain_core.messages import HumanMessage, ToolMessage

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from evomemory_sync.run_outcome import assess_run_outcome


def test_success_no_errors_no_validation():
    msgs = [
        HumanMessage(content="train model"),
        ToolMessage(content="[OK]\nTraining complete", tool_call_id="1", name="execute"),
    ]
    out = assess_run_outcome(msgs, task="train model")
    assert out["run_success_flag"] is True
    assert out["validation_status"] == "not_applicable"


def test_fail_tool_error_status():
    msgs = [
        HumanMessage(content="run"),
        ToolMessage(content="[TOOL ERROR] boom", tool_call_id="1", name="execute", status="error"),
    ]
    out = assess_run_outcome(msgs, task="run")
    assert out["run_success_flag"] is False
    assert out["has_tool_error_flag"] is True


def test_fail_nonzero_exit_code():
    msgs = [
        HumanMessage(content="run script"),
        ToolMessage(content="stderr...\n\nExit code: 1", tool_call_id="1", name="execute"),
    ]
    out = assess_run_outcome(msgs, task="run script")
    assert out["run_success_flag"] is False
    assert out["has_code_runtime_error_flag"] is True


def test_fail_pytest_with_ground_truth_hint():
    msgs = [
        HumanMessage(content="compare output with ground truth using pytest"),
        ToolMessage(
            content="FAILED tests/test_main.py::test_x - AssertionError\n1 failed",
            tool_call_id="1",
            name="execute",
        ),
    ]
    out = assess_run_outcome(msgs, task="compare output with ground truth using pytest")
    assert out["validation_status"] == "failed"
    assert out["run_success_flag"] is False


def test_pass_pytest_self_check():
    msgs = [
        HumanMessage(content="run pytest self-check"),
        ToolMessage(content="3 passed\nExit code: 0", tool_call_id="1", name="execute"),
    ]
    out = assess_run_outcome(msgs, task="run pytest self-check")
    assert out["validation_status"] == "passed"
    assert out["run_success_flag"] is True


def test_search_failed_text_without_execute_does_not_mark_run_failed():
    """Search bodies mentioning FAILED must not count as execution."""
    msgs = [
        HumanMessage(content="look up similar experience"),
        ToolMessage(
            content="Candidate mentioned FAILED tests and Exit code: 1 in an old run.",
            tool_call_id="search-1",
            name="search_evomemory",
            status="success",
        ),
    ]
    out = assess_run_outcome(msgs, task="look up similar experience")
    assert out["has_code_runtime_error_flag"] is False
    assert out["validation_status"] == "not_applicable"
    assert out["run_success_flag"] is True
    assert out["outcome_scope"] == "full_run"


def test_search_memory_failure_text_does_not_poison_successful_execution():
    msgs = [
        HumanMessage(content="search experience, then validate with hidden tests"),
        ToolMessage(
            content=(
                "Found recipe: an old attempt said FAILED and Exit code: 1. "
                "This is retrieved memory text, not the current execution."
            ),
            tool_call_id="search-1",
            name="search_evomemory",
            status="success",
        ),
        ToolMessage(
            content=(
                "EvoMemory application recorded by the Hub. "
                "[HUB_APPLIED:recipe:aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa:bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb]"
            ),
            tool_call_id="apply-1",
            name="apply_evomemory",
            status="success",
        ),
        ToolMessage(
            content="[OK] all tests passed. Exit code: 0",
            tool_call_id="run-1",
            name="run_python",
            status="success",
        ),
    ]
    out = assess_run_outcome(msgs, task="search experience, then validate with hidden tests")
    assert out["has_code_runtime_error_flag"] is False
    assert out["validation_status"] == "passed"
    assert out["run_success_flag"] is True
    assert out["outcome_scope"] == "post_apply"


def test_rejected_apply_without_hub_applied_does_not_switch_scope():
    """Avoid / invalid apply must not create an empty post-apply success window."""
    msgs = [
        HumanMessage(content="fix with asserts"),
        ToolMessage(
            content="[FAILED] AssertionError\nExit code: 1",
            tool_call_id="run-1",
            name="run_python",
            status="success",
        ),
        ToolMessage(
            content="应用未记录：该候选 recommended_action=avoid，请 abstain。",
            tool_call_id="apply-1",
            name="apply_evomemory",
            status="success",
        ),
    ]
    out = assess_run_outcome(msgs, task="fix with asserts")
    assert out["outcome_scope"] == "full_run"
    assert out["run_success_flag"] is False


def test_trusted_apply_without_post_apply_execution_is_not_success():
    msgs = [
        HumanMessage(content="use hub recipe"),
        ToolMessage(
            content=(
                "EvoMemory application recorded by the Hub. "
                "[HUB_APPLIED:aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa:bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb]"
            ),
            tool_call_id="apply-1",
            name="apply_evomemory",
            status="success",
        ),
    ]
    out = assess_run_outcome(msgs, task="use hub recipe")
    assert out["outcome_scope"] == "post_apply"
    assert out["run_success_flag"] is False
    assert out["validation_status"] == "failed"
    assert "no execution" in out["validation_reason"]


def test_pre_apply_failure_does_not_poison_post_apply_success():
    """Defer flow: independent fail → apply → pass must count as application success."""
    msgs = [
        HumanMessage(content="fix add_string with hidden asserts"),
        ToolMessage(
            content="[FAILED] AssertionError\nExit code: 1",
            tool_call_id="run-1",
            name="run_python",
            status="success",
        ),
        ToolMessage(
            content="candidates…",
            tool_call_id="search-1",
            name="search_evomemory",
            status="success",
        ),
        ToolMessage(
            content="EvoMemory application recorded by the Hub. [HUB_APPLIED:recipe:aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa:bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb]",
            tool_call_id="apply-1",
            name="apply_evomemory",
            status="success",
        ),
        ToolMessage(
            content="[OK] all tests passed\nExit code: 0",
            tool_call_id="run-2",
            name="run_python",
            status="success",
        ),
    ]
    out = assess_run_outcome(msgs, task="fix add_string with hidden asserts")
    assert out["outcome_scope"] == "post_apply"
    assert out["has_tool_error_flag"] is False
    assert out["has_code_runtime_error_flag"] is False
    assert out["validation_status"] == "passed"
    assert out["run_success_flag"] is True


def test_post_apply_failure_still_counts_as_failure():
    msgs = [
        HumanMessage(content="fix with asserts"),
        ToolMessage(
            content="[FAILED] Exit code: 1",
            tool_call_id="run-1",
            name="run_python",
            status="success",
        ),
        ToolMessage(
            content=(
                "EvoMemory application recorded by the Hub. "
                "[HUB_APPLIED:recipe:aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa:bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb]"
            ),
            tool_call_id="apply-1",
            name="apply_evomemory",
            status="success",
        ),
        ToolMessage(
            content="[FAILED] AssertionError\nExit code: 1",
            tool_call_id="run-2",
            name="run_python",
            status="success",
        ),
    ]
    out = assess_run_outcome(msgs, task="fix with asserts")
    assert out["outcome_scope"] == "post_apply"
    assert out["run_success_flag"] is False
    assert out["has_code_runtime_error_flag"] is True or out["validation_status"] == "failed"
