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
            {
                "memory_id": memory_id,
                "retrieval_proof": "v1.signed.proof",
                "fit_reason": "The runtime and failure mode match exactly.",
                "adaptation_plan": "Apply the validated step, then rerun the tests.",
            }
        )
    rejected = tools_module.apply_evomemory.invoke(
        {
            "memory_id": memory_id,
            "retrieval_proof": "",
            "fit_reason": "No proof is available.",
            "adaptation_plan": "Do not apply this candidate.",
        }
    )
    assert "recorded by the Hub" in accepted
    assert f"[HUB_APPLIED:{memory_id}:{app_id}]" in accepted
    assert "未记录" in rejected


def test_apply_evomemory_rejects_uuid_or_hub_ref_as_proof():
    memory_id = "12345678-1234-1234-1234-123456789abc"
    with mock.patch("evomemory_sync.agent_tools.headers_or_error", return_value=({"Authorization": "Bearer x"}, None)), mock.patch(
        "evomemory_sync.hub_usage.create_application_by_id"
    ) as create:
        as_uuid = tools_module.apply_evomemory.invoke(
            {
                "memory_id": memory_id,
                "retrieval_proof": memory_id,
                "fit_reason": "The runtime and failure mode match exactly.",
                "adaptation_plan": "Apply the validated step, then rerun the tests.",
            }
        )
        as_ref = tools_module.apply_evomemory.invoke(
            {
                "memory_id": memory_id,
                "retrieval_proof": f"[HUB_REF:{memory_id}]",
                "fit_reason": "The runtime and failure mode match exactly.",
                "adaptation_plan": "Apply the validated step, then rerun the tests.",
            }
        )
    assert "未记录" in as_uuid
    assert "未记录" in as_ref
    create.assert_not_called()


def test_apply_evomemory_surfaces_hub_http_error():
    memory_id = "12345678-1234-1234-1234-123456789abc"
    with mock.patch("evomemory_sync.agent_tools.headers_or_error", return_value=({"Authorization": "Bearer x"}, None)), mock.patch(
        "evomemory_sync.hub_usage.create_application_by_id",
        return_value={"error": "HTTP 400", "detail": "proof expired"},
    ):
        out = tools_module.apply_evomemory.invoke(
            {
                "memory_id": memory_id,
                "retrieval_proof": "v1.signed.proof",
                "fit_reason": "The runtime and failure mode match exactly.",
                "adaptation_plan": "Apply the validated step, then rerun the tests.",
            }
        )
    assert "未记录" in out
    assert "HTTP 400" in out
    assert "proof expired" in out


def test_apply_evomemory_uses_hub_idempotency_for_retries():
    memory_id = "12345678-1234-1234-1234-123456789abc"
    app_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    with mock.patch("evomemory_sync.agent_tools.headers_or_error", return_value=({"Authorization": "Bearer x"}, None)), mock.patch(
        "evomemory_sync.hub_usage.create_application_by_id",
        return_value={
            "application_id": app_id,
            "memory_kind": "recipe",
            "memory_content": {"solution": "selected full solution"},
        },
    ) as create:
        first = tools_module.apply_evomemory.invoke(
            {
                "memory_id": memory_id,
                "retrieval_proof": "v1.signed.proof",
                "fit_reason": "The constraints match the candidate trigger.",
                "adaptation_plan": "Adapt the solution and validate it locally.",
            }
        )
        replay = tools_module.apply_evomemory.invoke(
            {
                "memory_id": memory_id,
                "retrieval_proof": "v1.signed.proof",
                "fit_reason": "The constraints match the candidate trigger.",
                "adaptation_plan": "Adapt the solution and validate it locally.",
            }
        )
    assert "recorded by the Hub" in first and "recorded by the Hub" in replay
    assert "selected full solution" in first
    assert create.call_count == 2


class TestOptionalAuthHeaders:
    def test_with_token(self):
        with mock.patch("evomemory_sync.uploader.hub_bearer_token", return_value="test-token-123"):
            headers = tools_module._optional_auth_headers()
            assert headers["Authorization"] == "Bearer test-token-123"
            assert "User-Agent" in headers
            assert "Content-Type" in headers

    def test_without_token(self):
        with mock.patch("evomemory_sync.uploader.hub_bearer_token", return_value=""):
            headers = tools_module._optional_auth_headers()
            assert "Authorization" not in headers


def test_normalize_retrieval_proof_strips_wrapper():
    raw = "[HUB_APPLY_PROOF:v1.payload.signature]"
    assert tools_module._normalize_retrieval_proof(raw) == "v1.payload.signature"
    assert tools_module._normalize_retrieval_proof("v1.payload.signature") == "v1.payload.signature"


def test_apply_evomemory_accepts_wrapped_proof():
    memory_id = "12345678-1234-1234-1234-123456789abc"
    app_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    with mock.patch("evomemory_sync.agent_tools.headers_or_error", return_value=({"Authorization": "Bearer x"}, None)), mock.patch(
        "evomemory_sync.hub_usage.create_application_by_id",
        return_value={"application_id": app_id, "memory_kind": "recipe"},
    ) as create:
        out = tools_module.apply_evomemory.invoke(
            {
                "memory_id": memory_id,
                "retrieval_proof": "[HUB_APPLY_PROOF:v1.signed.proof]",
                "fit_reason": "The runtime and failure mode match exactly.",
                "adaptation_plan": "Apply the validated step, then rerun the tests.",
            }
        )
    assert "recorded by the Hub" in out
    assert create.call_args.args[1] == "v1.signed.proof"


def test_apply_evomemory_refuses_avoid_without_force():
    memory_id = "12345678-1234-1234-1234-123456789abc"
    tools_module._LAST_CANDIDATE_META[memory_id] = {"recommended_action": "avoid"}
    with mock.patch("evomemory_sync.hub_usage.create_application_by_id") as create:
        out = tools_module.apply_evomemory.invoke(
            {
                "memory_id": memory_id,
                "retrieval_proof": "v1.signed.proof",
                "fit_reason": "The runtime and failure mode match exactly.",
                "adaptation_plan": "Apply the validated step, then rerun the tests.",
            }
        )
    assert "avoid" in out
    create.assert_not_called()
    tools_module._LAST_CANDIDATE_META.pop(memory_id, None)


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
        with mock.patch.object(tools_module, "_env", return_value="3"):
            assert tools_module._default_top_k() == 3

    def test_clamped_to_100(self):
        with mock.patch.object(tools_module, "_env", return_value="999"):
            assert tools_module._default_top_k() == 3

    def test_clamped_to_1(self):
        with mock.patch.object(tools_module, "_env", return_value="-5"):
            assert tools_module._default_top_k() == 1


class TestDefaultMinSimilarity:
    def test_default_value(self):
        with mock.patch.object(tools_module, "_env", return_value="0.5"):
            assert tools_module._default_min_similarity() == 0.5

    def test_clamped_to_1(self):
        with mock.patch.object(tools_module, "_env", return_value="5.0"):
            assert tools_module._default_min_similarity() == 1.0

    def test_clamped_to_0(self):
        with mock.patch.object(tools_module, "_env", return_value="-1.0"):
            assert tools_module._default_min_similarity() == 0.0


def test_problem_profile_summarizes_transferable_structure():
    profile = tools_module._problem_profile(
        "repair a failing parser",
        "must preserve public API",
        "tokenizer already passes",
        "nested quotes still fail",
        "Python 3.10",
    )
    assert "Objective: repair a failing parser" in profile
    assert "Constraints and acceptance: must preserve public API" in profile
    assert "Observed failure or uncertainty: nested quotes still fail" in profile


def test_recipe_candidates_are_compact_and_show_utility_not_solution():
    rendered = tools_module._format_results(
        "recipe",
        [
            {
                "id": "12345678-1234-1234-1234-123456789abc",
                "trigger": "parser fails on nested quotes",
                "problem_summary": "quoted delimiters are consumed too early",
                "solution": "THIS FULL SOLUTION MUST NOT APPEAR",
                "recommended_action": "inspect",
                "recommendation_reason": "check runtime constraints",
                "utility_score": 0.71,
                "evidence": {
                    "explicit_success_count": 2,
                    "failure_after_application_count": 1,
                    "avg_application_token_cost": 500,
                },
                "estimated_full_text_tokens": 900,
            }
        ],
        max_items=3,
    )
    assert "THIS FULL SOLUTION MUST NOT APPEAR" not in rendered
    assert "成功 2 / 应用后失败 1 / 平均 Token 500" in rendered
    assert "效用 0.710" in rendered


def test_search_sends_structured_profile_and_requests_top3_summaries():
    class Response:
        status_code = 200

        def json(self):
            return {"results": []}

    with mock.patch.object(tools_module, "get_base_url", return_value="https://hub.example"), mock.patch.object(
        tools_module.requests, "post", return_value=Response()
    ) as post:
        tools_module.search_evomemory.invoke(
            {
                "query": "repair parser",
                "memory_kind": "recipe",
                "constraints": "preserve API",
                "current_state": "basic cases pass",
                "observed_failure": "nested quote case fails",
                "environment": "Python 3.10",
            }
        )
    payload = post.call_args.kwargs["json"]
    assert payload["top_k"] == 3
    assert payload["response_mode"] == "summary"
    assert "Objective: repair parser" in payload["query_text"]
    assert "Constraints and acceptance: preserve API" in payload["query_text"]
