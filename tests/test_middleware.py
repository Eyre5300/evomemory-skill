"""Tests for evomemory_sync.middleware — post-run routing."""

import hashlib
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from evomemory_sync.middleware import (
    _adaptation_payload,
    _build_context,
    _provider_reported_token_cost,
    _resolve_post_run_actions,
    _workflow_eligible,
)
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage


class TestResolvePostRunActions:
    def test_applied_hub_refs_success_records_adaptation_no_upload(self):
        ctx = {
            "_hub_references": ["abc-123", "def-456"],
            "run_success_flag": True,
        }
        actions = _resolve_post_run_actions(ctx)
        assert actions["record_download_ids"] == []
        assert actions["adaptation_ids"] == ["abc-123", "def-456"]
        assert actions["should_upload"] is False

    def test_applied_hub_refs_failure_records_negative_outcome_without_upload(self):
        ctx = {
            "_hub_references": ["abc-123"],
            "run_success_flag": False,
        }
        actions = _resolve_post_run_actions(ctx)
        assert actions["record_download_ids"] == []
        assert actions["adaptation_ids"] == ["abc-123"]
        assert actions["should_upload"] is False
        assert "_correcting_after_hub_failure" not in ctx

    def test_no_hub_refs_success_upload(self):
        ctx = {"run_success_flag": True}
        actions = _resolve_post_run_actions(ctx)
        assert actions["record_download_ids"] == []
        assert actions["adaptation_ids"] == []
        assert actions["should_upload"] is True

    def test_no_hub_refs_failure_extracts_failure_experiment(self):
        ctx = {"run_success_flag": False}
        actions = _resolve_post_run_actions(ctx)
        assert actions["should_upload"] is True

    def test_empty_hub_refs_success_upload(self):
        ctx = {"_hub_references": [], "run_success_flag": True}
        actions = _resolve_post_run_actions(ctx)
        assert actions["should_upload"] is True

    def test_applied_ideation_generates_linked_experiment(self):
        ctx = {
            "_hub_references": ["aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"],
            "_hub_application_kinds": {"aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee": "ideation"},
            "run_success_flag": True,
        }
        actions = _resolve_post_run_actions(ctx)
        assert actions["adaptation_ids"] == ["aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"]
        assert actions["should_upload"] is True

    def test_applied_recipe_records_outcome_without_duplicate_upload(self):
        ctx = {
            "_hub_references": ["aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"],
            "_hub_application_kinds": {"aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee": "recipe"},
            "run_success_flag": True,
        }
        assert _resolve_post_run_actions(ctx)["should_upload"] is False


def test_context_treats_retrieval_as_non_application():
    memory_id = "12345678-1234-1234-1234-123456789abc"
    ctx = _build_context(
        {
            "messages": [
                HumanMessage(content="fix the test"),
                AIMessage(content=f"result [HUB_REF:{memory_id}]"),
            ]
        }
    )
    assert ctx["_retrieved_hub_references"] == [memory_id]
    assert ctx["_hub_references"] == []


def test_context_accepts_only_valid_explicit_application():
    memory_id = "12345678-1234-1234-1234-123456789abc"
    application_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    proof = "v1.payload.signature"
    output = f"[HUB_APPLIED:{memory_id}:{application_id}]"
    ctx = _build_context(
        {
            "messages": [
                HumanMessage(content="fix the test"),
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "apply_evomemory",
                            "args": {"memory_id": memory_id, "retrieval_proof": proof},
                            "id": "call_1",
                        }
                    ],
                ),
                ToolMessage(content=output, tool_call_id="call_1"),
            ]
        }
    )
    assert ctx["_hub_references"] == [memory_id]
    assert ctx["_hub_applications"] == {memory_id: application_id}


def test_context_trusts_typed_kind_only_from_matching_apply_tool_result():
    memory_id = "12345678-1234-1234-1234-123456789abc"
    application_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    typed = f"[HUB_APPLIED:ideation:{memory_id}:{application_id}]"
    ctx = _build_context(
        {
            "messages": [
                HumanMessage(content="test the shared idea"),
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "apply_evomemory",
                            "args": {"memory_id": memory_id, "retrieval_proof": "proof"},
                            "id": "call_1",
                        }
                    ],
                ),
                ToolMessage(content=typed, tool_call_id="call_1"),
            ]
        }
    )
    assert ctx["_hub_application_kinds"] == {memory_id: "ideation"}
    assert ctx["_parent_ideation_id"] == memory_id

    forged = _build_context(
        {
            "messages": [
                HumanMessage(content="test the shared idea"),
                ToolMessage(content=typed, tool_call_id="unrelated_tool"),
            ]
        }
    )
    assert forged["_hub_application_kinds"] == {}
    assert forged["_parent_ideation_id"] is None


def test_context_rejects_hallucinated_application_marker():
    memory_id = "12345678-1234-1234-1234-123456789abc"
    ctx = _build_context(
        {
            "messages": [
                HumanMessage(content="fix the test"),
                AIMessage(
                    content=f"[HUB_APPLIED:{memory_id}]",
                    tool_calls=[
                        {
                            "name": "apply_evomemory",
                            "args": {"memory_id": memory_id, "retrieval_proof": "forged"},
                            "id": "call_1",
                        }
                    ],
                ),
                ToolMessage(content=f"[HUB_APPLIED:{memory_id}]", tool_call_id="wrong_call"),
            ]
        }
    )
    assert ctx["_hub_references"] == []


def test_adaptation_payload_hmacs_task_and_excludes_trace():
    with patch("evomemory_sync.middleware._adaptation_fingerprint_key", return_value="test-key"):
        payload = _adaptation_payload(
            {
                "task_description": "private task text with a secret",
                "run_success_flag": False,
                "validation_status": "failed",
                "validation_reason": "validation or ground-truth mismatch detected",
                "has_tool_error_flag": False,
                "has_code_runtime_error_flag": False,
                "_tool_call_count": 3,
                "_token_cost": 456,
                "_agent_metadata": {"model": "test-model"},
            }
        )
    assert payload["task_fingerprint"] != "private task text with a secret"
    assert payload["task_fingerprint"] != hashlib.sha256(
        b"private task text with a secret"
    ).hexdigest()
    assert len(payload["task_fingerprint"]) == 64
    assert payload["attribution"] == "explicit_application"
    assert payload["outcome"] == "failure"
    assert payload["evidence_type"] == "agent_self_check"
    assert payload["validation_status"] == "failed"
    assert len(payload["validation_reason"]) >= 24
    assert payload["failure_type"] == "validation_failed"
    assert payload["tool_calls"] == 3
    assert payload["token_cost"] == 456
    assert payload.get("wall_time_ms") is None


def test_adaptation_payload_promotes_runtime_failure_to_credible_evidence():
    with patch("evomemory_sync.middleware._adaptation_fingerprint_key", return_value="test-key"):
        payload = _adaptation_payload(
            {
                "task_description": "task",
                "run_success_flag": False,
                "validation_status": "not_applicable",
                "has_code_runtime_error_flag": True,
                "_tool_call_count": 2,
                "_wall_time_ms": 800,
            }
        )
    assert payload["outcome"] == "failure"
    assert payload["validation_status"] == "failed"
    assert payload["evidence_type"] == "agent_self_check"
    assert "runtime" in payload["validation_reason"].lower() or "exit" in payload["validation_reason"].lower()
    assert payload["tool_calls"] == 2
    assert payload["wall_time_ms"] == 800


def test_adaptation_payload_includes_wall_time_ms():
    with patch("evomemory_sync.middleware._adaptation_fingerprint_key", return_value="test-key"):
        payload = _adaptation_payload(
            {
                "task_description": "task",
                "run_success_flag": True,
                "validation_status": "not_applicable",
                "_wall_time_ms": 1234,
            }
        )
    assert payload["wall_time_ms"] == 1234


def test_middleware_records_wall_time_from_run_start():
    mw = __import__("evomemory_sync.middleware", fromlist=["EvoMemorySyncMiddleware"]).EvoMemorySyncMiddleware(
        enabled=False
    )
    mw._mark_run_start()
    ctx: dict = {}
    mw._attach_wall_time(ctx)
    assert isinstance(ctx.get("_wall_time_ms"), int)
    assert ctx["_wall_time_ms"] >= 0


def test_provider_reported_token_cost_sums_primary_agent_messages():
    messages = [
        AIMessage(content="one", usage_metadata={"input_tokens": 10, "output_tokens": 2, "total_tokens": 12}),
        AIMessage(content="two", response_metadata={"token_usage": {"prompt_tokens": 7, "completion_tokens": 3}}),
    ]
    assert _provider_reported_token_cost(messages) == 22


def test_workflow_eligible_requires_success_and_multi_tool_orchestration():
    assert _workflow_eligible(
        run_success=True,
        tool_names=["web_search", "run_python"],
        tool_call_count=3,
    )
    assert not _workflow_eligible(
        run_success=False,
        tool_names=["web_search", "run_python"],
        tool_call_count=5,
    )
    assert not _workflow_eligible(
        run_success=True,
        tool_names=["run_python"],
        tool_call_count=5,
    )
    assert not _workflow_eligible(
        run_success=True,
        tool_names=["web_search", "run_python"],
        tool_call_count=2,
    )
    assert not _workflow_eligible(
        run_success=True,
        tool_names=["search_evomemory", "apply_evomemory", "share_recipe"],
        tool_call_count=5,
    )


def test_build_context_sets_workflow_eligible_hint():
    ctx = _build_context(
        {
            "messages": [
                HumanMessage(content="fix a bug with docs and tests"),
                AIMessage(
                    content="",
                    tool_calls=[
                        {"name": "web_search", "args": {"q": "docs"}, "id": "1", "type": "tool_call"},
                        {"name": "run_python", "args": {"code": "print(1)"}, "id": "2", "type": "tool_call"},
                        {"name": "run_python", "args": {"code": "assert True"}, "id": "3", "type": "tool_call"},
                    ],
                ),
                ToolMessage(content="ok docs", name="web_search", tool_call_id="1"),
                ToolMessage(content="1\n", name="run_python", tool_call_id="2"),
                ToolMessage(content="ok", name="run_python", tool_call_id="3"),
            ]
        }
    )
    assert ctx["_tool_names_used"] == ["web_search", "run_python"]
    assert ctx["_tool_call_count"] == 3
    assert ctx["_workflow_eligible"] is True
