import json
import sqlite3
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from evomemory_sync import outcome_queue
from evomemory_sync import hub_usage


MEMORY_ID = "12345678-1234-1234-1234-123456789abc"
APPLICATION_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


def _payload(**updates):
    value = {
        "task_fingerprint": "a" * 64,
        "attribution": "explicit_application",
        "application_id": APPLICATION_ID,
        "outcome": "success",
        "validation_status": "passed",
        "evidence_type": "agent_self_check",
        "validation_reason": "local test",
        "agent_profile": {"model": "test"},
        "tool_calls": 1,
        "failure_type": None,
    }
    value.update(updates)
    return value


@pytest.fixture(autouse=True)
def isolated_queue(tmp_path, monkeypatch):
    monkeypatch.setenv("EVOMEMORY_OUTCOME_QUEUE_PATH", str(tmp_path / "outcomes.sqlite3"))


def test_queue_persists_only_approved_privacy_minimized_fields():
    assert outcome_queue.enqueue_outcome(MEMORY_ID, _payload()) is True
    with sqlite3.connect(outcome_queue.queue_path()) as conn:
        encoded = conn.execute("SELECT payload_json FROM pending_outcomes").fetchone()[0]
    stored = json.loads(encoded)
    assert stored["application_id"] == APPLICATION_ID
    assert "task_description" not in stored
    with pytest.raises(ValueError, match="non-approved"):
        outcome_queue.enqueue_outcome(MEMORY_ID, _payload(task_description="private task"))


def test_successful_delivery_removes_row_and_retry_uses_backoff():
    outcome_queue.enqueue_outcome(MEMORY_ID, _payload())
    retry = outcome_queue.flush_pending_outcomes(
        {"Authorization": "Bearer test"}, sender=lambda *_args: "retry", now=1000
    )
    assert retry == {"sent": 0, "retry": 1, "discard": 0}
    assert outcome_queue.outcome_queue_counts()["pending"] == 1
    not_due = outcome_queue.flush_pending_outcomes({}, sender=lambda *_args: "sent", now=1001)
    assert not_due["sent"] == 0
    sent = outcome_queue.flush_pending_outcomes({}, sender=lambda *_args: "sent", now=1002)
    assert sent["sent"] == 1
    assert outcome_queue.outcome_queue_counts()["pending"] == 0


def test_permanent_rejection_is_retained_as_dead_letter():
    outcome_queue.enqueue_outcome(MEMORY_ID, _payload())
    stats = outcome_queue.flush_pending_outcomes({}, sender=lambda *_args: "discard", now=1000)
    assert stats["discard"] == 1
    assert outcome_queue.outcome_queue_counts() == {"pending": 0, "dead": 1}


def test_same_application_updates_one_idempotent_queue_row():
    outcome_queue.enqueue_outcome(MEMORY_ID, _payload(outcome="failure"))
    outcome_queue.enqueue_outcome(MEMORY_ID, _payload(outcome="success"))
    with sqlite3.connect(outcome_queue.queue_path()) as conn:
        rows = conn.execute("SELECT payload_json FROM pending_outcomes").fetchall()
    assert len(rows) == 1
    assert json.loads(rows[0][0])["outcome"] == "success"


@pytest.mark.parametrize(
    ("status_code", "expected"),
    [(200, "sent"), (401, "retry"), (429, "retry"), (503, "retry"), (400, "discard"), (409, "discard")],
)
def test_hub_delivery_classifies_retryable_and_permanent_responses(status_code, expected):
    with patch.object(hub_usage, "adaptation_tracking_enabled", return_value=True), patch.object(
        hub_usage.requests, "post", return_value=SimpleNamespace(status_code=status_code)
    ):
        assert hub_usage.record_adaptation_by_id(MEMORY_ID, _payload(), {}) == expected


def test_hub_delivery_retries_transport_errors():
    with patch.object(hub_usage, "adaptation_tracking_enabled", return_value=True), patch.object(
        hub_usage.requests, "post", side_effect=OSError("offline")
    ):
        assert hub_usage.record_adaptation_by_id(MEMORY_ID, _payload(), {}) == "retry"
