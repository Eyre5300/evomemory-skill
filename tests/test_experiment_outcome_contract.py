from evomemory_sync.uploader import json_to_experiment_payload, json_to_ideation_payload
from evomemory_sync.worker import _record_allowed_for_outcome


def test_ideation_payload_has_no_success_failure_type():
    payload = json_to_ideation_payload(
        {
            "memory_type": "ideation",
            "goal": "Transfer experience across paraphrased tasks",
            "title": "Semantic capability and constraint representation",
            "core_idea": "Extract the reusable task structure before retrieval.",
            "rationale": "Exact fingerprints only match repeated benchmark cases.",
            "requirements": "A semantic extractor and embedding model are required.",
            "validation_plan": "Measure Recall at 3 and downstream success rate.",
        }
    )
    assert "type" not in payload
    assert payload["rationale"].startswith("Exact")


def test_failed_attempt_maps_to_experiment_and_is_worker_eligible():
    record = {
        "memory_type": "experiment",
        "task_description": "Test a semantic retrieval representation",
        "data_summary": "Ten held-out tasks and paraphrases",
        "model_strategy": "Top three semantic retrieval",
        "environment_constraints": "Python 3.14 and deterministic tests",
        "outcome": "failure",
        "result_summary": "Six assertions failed",
        "failure_reason": "Numeric constraints were omitted",
        "conclusion": "Revise the representation before reuse",
        "evidence_type": "deterministic_test",
    }
    payload = json_to_experiment_payload(record)
    assert payload["outcome"] == "failure"
    assert _record_allowed_for_outcome({"run_success_flag": False}, record)
