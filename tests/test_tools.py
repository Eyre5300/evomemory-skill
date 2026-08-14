"""Tests for evomemory_sync.tools — search tools and auth headers."""

import os
import sys
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import evomemory_sync.tools as tools_module


def test_apply_evomemory_requires_a_search_capability():
    memory_id = "12345678-1234-1234-1234-123456789abc"
    app_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    with mock.patch("evomemory_sync.agent_tools.headers_or_error", return_value=({"Authorization": "Bearer x"}, None)), mock.patch(
        "evomemory_sync.hub_usage.create_application_by_id",
        return_value={"application_id": app_id},
    ):
        accepted = tools_module.apply_evomemory.invoke(
            {"memory_id": memory_id, "retrieval_proof": "v1.signed.proof"}
        )
    rejected = tools_module.apply_evomemory.invoke({"memory_id": memory_id, "retrieval_proof": ""})
    assert "recorded by the Hub" in accepted
    assert f"[HUB_APPLIED:{memory_id}:{app_id}]" in accepted
    assert "not recorded" in rejected


def test_apply_evomemory_uses_hub_idempotency_for_retries():
    memory_id = "12345678-1234-1234-1234-123456789abc"
    app_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    with mock.patch("evomemory_sync.agent_tools.headers_or_error", return_value=({"Authorization": "Bearer x"}, None)), mock.patch(
        "evomemory_sync.hub_usage.create_application_by_id",
        return_value={"application_id": app_id},
    ) as create:
        first = tools_module.apply_evomemory.invoke(
            {"memory_id": memory_id, "retrieval_proof": "v1.signed.proof"}
        )
        replay = tools_module.apply_evomemory.invoke(
            {"memory_id": memory_id, "retrieval_proof": "v1.signed.proof"}
        )
    assert "recorded by the Hub" in first and "recorded by the Hub" in replay
    assert create.call_count == 2


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


def test_malformed_search_row_is_not_issued_an_application_receipt():
    rendered = tools_module._format_results("workflow", [{"id": "not-a-uuid"}], max_items=1)
    assert "[HUB_REF:not-a-uuid]" in rendered
    assert "HUB_APPLY_PROOF" not in rendered


def test_search_renders_only_hub_signed_application_proof():
    rendered = tools_module._format_results(
        "workflow",
        [{"id": "12345678-1234-1234-1234-123456789abc", "hub_retrieval_proof": "v1.payload.signature"}],
        max_items=1,
    )
    assert "[HUB_APPLY_PROOF:v1.payload.signature]" in rendered


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
