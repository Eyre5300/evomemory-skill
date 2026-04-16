"""Tests for evomemory_sync.middleware — context building and verify-vs-upload routing."""

import os
import sys
from unittest import mock

# Ensure the package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from evomemory_sync.middleware import _should_verify_instead_of_upload


class TestShouldVerifyInsteadOfUpload:
    """Logic: hub_refs + no errors -> verify; else -> upload."""

    def test_hub_refs_no_errors_should_verify(self):
        ctx = {
            "_hub_references": ["abc-123", "def-456"],
            "has_tool_error_flag": False,
        }
        should_verify, refs = _should_verify_instead_of_upload(ctx)
        assert should_verify is True
        assert refs == ["abc-123", "def-456"]

    def test_hub_refs_with_errors_should_upload(self):
        ctx = {
            "_hub_references": ["abc-123"],
            "has_tool_error_flag": True,
        }
        should_verify, refs = _should_verify_instead_of_upload(ctx)
        assert should_verify is False
        assert refs == ["abc-123"]

    def test_no_hub_refs_should_upload(self):
        ctx = {"has_tool_error_flag": False}
        should_verify, refs = _should_verify_instead_of_upload(ctx)
        assert should_verify is False
        assert refs == []

    def test_empty_hub_refs_should_upload(self):
        ctx = {"_hub_references": [], "has_tool_error_flag": False}
        should_verify, refs = _should_verify_instead_of_upload(ctx)
        assert should_verify is False
        assert refs == []

    def test_none_hub_refs_treated_as_empty(self):
        ctx = {"_hub_references": None, "has_tool_error_flag": False}
        should_verify, refs = _should_verify_instead_of_upload(ctx)
        assert should_verify is False
        assert refs == []
