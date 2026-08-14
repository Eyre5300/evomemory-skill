"""Tests for evomemory_sync.middleware — post-run routing."""

import hashlib
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from evomemory_sync.middleware import (
    _adaptation_payload,
    _build_context,
    _resolve_post_run_actions,
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

    def test_applied_hub_refs_failure_uploads_correction(self):
        ctx = {
            "_hub_references": ["abc-123"],
            "run_success_flag": False,
        }
        actions = _resolve_post_run_actions(ctx)
        assert actions["record_download_ids"] == []
        assert actions["adaptation_ids"] == ["abc-123"]
        assert actions["should_upload"] is True
        assert ctx["_correcting_after_hub_failure"] is True

    def test_no_hub_refs_success_upload(self):
        ctx = {"run_success_flag": True}
        actions = _resolve_post_run_actions(ctx)
        assert actions["record_download_ids"] == []
        assert actions["adaptation_ids"] == []
        assert actions["should_upload"] is True

    def test_no_hub_refs_failure_no_upload(self):
        ctx = {"run_success_flag": False}
        actions = _resolve_post_run_actions(ctx)
        assert actions["should_upload"] is False

    def test_empty_hub_refs_success_upload(self):
        ctx = {"_hub_references": [], "run_success_flag": True}
        actions = _resolve_post_run_actions(ctx)
        assert actions["should_upload"] is True


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
    assert payload["failure_type"] == "validation_failed"
    assert payload["tool_calls"] == 3
