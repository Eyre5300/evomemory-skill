"""Tests for evomemory_sync.middleware — post-run routing."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from evomemory_sync.middleware import _resolve_post_run_actions


class TestResolvePostRunActions:
    def test_hub_refs_success_verify_no_upload(self):
        ctx = {
            "_hub_references": ["abc-123", "def-456"],
            "has_tool_error_flag": False,
        }
        actions = _resolve_post_run_actions(ctx)
        assert actions["record_download_ids"] == ["abc-123", "def-456"]
        assert actions["verify_ids"] == ["abc-123", "def-456"]
        assert actions["should_upload"] is False

    def test_hub_refs_failure_record_download_upload_no_verify(self):
        ctx = {
            "_hub_references": ["abc-123"],
            "has_tool_error_flag": True,
        }
        actions = _resolve_post_run_actions(ctx)
        assert actions["record_download_ids"] == ["abc-123"]
        assert actions["verify_ids"] == []
        assert actions["should_upload"] is True
        assert ctx["_correcting_after_hub_failure"] is True

    def test_no_hub_refs_success_upload(self):
        ctx = {"has_tool_error_flag": False}
        actions = _resolve_post_run_actions(ctx)
        assert actions["record_download_ids"] == []
        assert actions["verify_ids"] == []
        assert actions["should_upload"] is True

    def test_no_hub_refs_failure_no_upload(self):
        ctx = {"has_tool_error_flag": True}
        actions = _resolve_post_run_actions(ctx)
        assert actions["should_upload"] is False

    def test_empty_hub_refs_success_upload(self):
        ctx = {"_hub_references": [], "has_tool_error_flag": False}
        actions = _resolve_post_run_actions(ctx)
        assert actions["should_upload"] is True
