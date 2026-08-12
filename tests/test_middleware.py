"""Tests for evomemory_sync.middleware — post-run routing."""

import hashlib
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from evomemory_sync.middleware import _adaptation_payload, _resolve_post_run_actions


class TestResolvePostRunActions:
    def test_hub_refs_success_records_adaptation_no_upload(self):
        ctx = {
            "_hub_references": ["abc-123", "def-456"],
            "run_success_flag": True,
        }
        actions = _resolve_post_run_actions(ctx)
        assert actions["record_download_ids"] == ["abc-123", "def-456"]
        assert actions["adaptation_ids"] == ["abc-123", "def-456"]
        assert actions["should_upload"] is False

    def test_hub_refs_failure_record_download_upload_no_verify(self):
        ctx = {
            "_hub_references": ["abc-123"],
            "run_success_flag": False,
        }
        actions = _resolve_post_run_actions(ctx)
        assert actions["record_download_ids"] == ["abc-123"]
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
    assert payload["outcome"] == "failure"
    assert payload["failure_type"] == "validation_failed"
    assert payload["tool_calls"] == 3
