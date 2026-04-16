"""Tests for evomemory_sync.tools — search tools and auth headers."""

import os
import sys
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import evomemory_sync.tools as tools_module


class TestOptionalAuthHeaders:
    def test_with_token(self):
        with mock.patch.object(tools_module, "_env", return_value="test-token-123"):
            headers = tools_module._optional_auth_headers()
            assert headers["Authorization"] == "Bearer test-token-123"
            assert "User-Agent" in headers
            assert "Content-Type" in headers

    def test_without_token(self):
        with mock.patch.object(tools_module, "_env", return_value=""):
            headers = tools_module._optional_auth_headers()
            assert "Authorization" not in headers


class TestTruncatePreviewText:
    def test_short_text_unchanged(self):
        result = tools_module._truncate_preview_text("hello", max_chars=100)
        assert result == "hello"

    def test_long_text_truncated(self):
        result = tools_module._truncate_preview_text("A" * 200, max_chars=50)
        assert result.endswith("…")
        assert len(result) == 51  # max_chars + "…" ellipsis

    def test_newlines_replaced(self):
        result = tools_module._truncate_preview_text("line1\nline2", max_chars=100)
        assert "\n" not in result

    def test_max_chars_zero(self):
        result = tools_module._truncate_preview_text("hello", max_chars=0)
        assert result == ""


class TestDefaultTopK:
    def test_default_value(self):
        with mock.patch.object(tools_module, "_env", return_value="10"):
            assert tools_module._default_top_k() == 10

    def test_clamped_to_100(self):
        with mock.patch.object(tools_module, "_env", return_value="999"):
            assert tools_module._default_top_k() == 100

    def test_clamped_to_1(self):
        with mock.patch.object(tools_module, "_env", return_value="-5"):
            assert tools_module._default_top_k() == 1


class TestDefaultMinSimilarity:
    def test_default_value(self):
        with mock.patch.object(tools_module, "_env", return_value="0"):
            assert tools_module._default_min_similarity() == 0.0

    def test_clamped_to_1(self):
        with mock.patch.object(tools_module, "_env", return_value="5.0"):
            assert tools_module._default_min_similarity() == 1.0

    def test_clamped_to_0(self):
        with mock.patch.object(tools_module, "_env", return_value="-1.0"):
            assert tools_module._default_min_similarity() == 0.0
