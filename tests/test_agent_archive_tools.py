import asyncio
from unittest import mock

from evomemory_sync.agent_tools import share_experiment, share_failed_ideation, share_ideation


def test_share_ideation_has_no_outcome_type():
    captured = {}

    def upload(payload):
        captured.update(payload)
        return {"status": "success"}

    with mock.patch("evomemory_sync.agent_tools.upload_memory_record", side_effect=upload):
        result = asyncio.run(
            share_ideation("goal long enough", "title", "core idea long enough", "rationale long enough", "requirements long enough", "validation plan long enough")
        )
    assert result["status"] == "success"
    assert captured["memory_type"] == "ideation"
    assert "status" not in captured and "type" not in captured


def test_share_experiment_preserves_failure_evidence():
    captured = {}

    def upload(payload):
        captured.update(payload)
        return {"status": "success"}

    with mock.patch("evomemory_sync.agent_tools.upload_memory_record", side_effect=upload):
        asyncio.run(
            share_experiment(
                "proposal context", "data strategy", "model strategy", "Python 3.14",
                "failure", "six assertions failed", "revise constraint extraction",
                metrics={"failed": 6}, failure_reason="numeric limit omitted",
                evidence_type="deterministic_test", parent_ideation_id="idea-id",
            )
        )
    assert captured["outcome"] == "failure"
    assert captured["parent_ideation_id"] == "idea-id"


def test_legacy_failed_ideation_becomes_failed_experiment():
    captured = {}

    def upload(payload):
        captured.update(payload)
        return {"status": "success"}

    with mock.patch("evomemory_sync.agent_tools.upload_memory_record", side_effect=upload):
        asyncio.run(share_failed_ideation("goal", "title", "concrete failure path", "error notes"))
    assert captured["memory_type"] == "experiment"
    assert captured["outcome"] == "failure"
