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
