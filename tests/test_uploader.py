"""Tests for evomemory_sync.uploader — payload conversion functions."""

import os
import sys
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from evomemory_sync.uploader import (
    json_to_ideation_payload,
    json_to_experiment_payload,
    json_to_recipe_payload,
)


class TestJsonToIdeationPayload:
    def test_success_ideation_minimal(self):
        data = {
            "memory_type": "ideation",
            "goal": "Test goal",
            "title": "Test title",
            "core_idea": "Test idea",
        }
        result = json_to_ideation_payload(data)
        assert result["goal"] == "Test goal"
        assert result["title"] == "Test title"
        assert result["core_idea"] == "Test idea"
        assert "type" not in result

    def test_ideation_keeps_rationale_and_validation_plan_separate(self):
        data = {
            "memory_type": "ideation",
            "goal": "Explore semantic retrieval",
            "title": "Semantic retrieval hypothesis",
            "core_idea": "Represent task capability and constraints",
            "rationale": "Exact fingerprints do not transfer",
            "requirements": "An embedding model is required",
            "validation_plan": "Measure Recall at 3",
        }
        result = json_to_ideation_payload(data)
        assert "type" not in result
        assert result["rationale"] == "Exact fingerprints do not transfer"
        assert result["validation_plan"] == "Measure Recall at 3"

    def test_wrong_type_raises(self):
        data = {"memory_type": "experiment"}
        try:
            json_to_ideation_payload(data)
            assert False, "Should have raised ValueError"
        except ValueError:
            pass

    def test_title_preserved(self):
        # Note: non-failed ideation does NOT truncate title (only failed ones do first_line[:200])
        data = {
            "memory_type": "ideation",
            "goal": "Test",
            "title": "A" * 500,
            "core_idea": "Test",
        }
        result = json_to_ideation_payload(data)
        assert len(result["title"]) == 500


class TestJsonToExperimentPayload:
    def test_outcome_alias_failed_and_failure_reason_filled(self):
        data = {
            "memory_type": "experiment",
            "task_description": "try fix",
            "data_summary": "n/a",
            "model_strategy": "edit",
            "environment_constraints": "py310",
            "outcome": "failed",
            "result_summary": "AssertionError on edge case",
            "conclusion": "reject approach",
        }
        result = json_to_experiment_payload(data)
        assert result["outcome"] == "failure"
        assert result["failure_reason"] == "AssertionError on edge case"
    def test_success_experiment(self):
        data = {
            "memory_type": "experiment",
            "task_description": "Task desc",
            "data_summary": "Data info",
            "model_summary": "Model info",
            "environment_constraints": "Constraints",
            "outcome": "failure",
            "result_summary": "The deterministic test failed",
            "failure_reason": "Assertion mismatch",
            "conclusion": "Reject this configuration",
            "metrics": {"passed": 0},
        }
        result = json_to_experiment_payload(data)
        assert result["proposal_context"] == "Task desc"
        assert result["data_strategy"] == "Data info"
        assert result["model_strategy"] == "Model info"
        assert result["environment"] == "Constraints"
        assert result["outcome"] == "failure"
        assert result["metrics"] == {"passed": 0}

    def test_parent_ids_preserved(self):
        data = {
            "memory_type": "experiment",
            "experiment_title": "Exp",
            "experiment_summary": "Sum",
            "hypothesis": "H",
            "method": "M",
            "parent_ideation_id": "ide-123",
        }
        result = json_to_experiment_payload(data)
        assert result["parent_ideation_id"] == "ide-123"

    def test_wrong_type_raises(self):
        try:
            json_to_experiment_payload({"memory_type": "ideation"})
            assert False, "Should have raised ValueError"
        except ValueError:
            pass


class TestJsonToRecipePayload:
    def test_success_recipe(self):
        data = {
            "memory_type": "recipe",
            "trigger": "When deploying",
            "problem": "Container crashes",
            "solution": "Increase memory limit",
        }
        result = json_to_recipe_payload(data)
        assert result["trigger"] == "When deploying"
        assert result["problem"] == "Container crashes"
        assert result["solution"] == "Increase memory limit"

    def test_defaults_for_missing(self):
        data = {"memory_type": "recipe"}
        result = json_to_recipe_payload(data)
        assert result["trigger"] == "可复用的问题解决经验"
        assert result["problem"] == "(unknown problem)"
        assert result["solution"] == "(unknown solution)"

    def test_wrong_type_raises(self):
        try:
            json_to_recipe_payload({"memory_type": "experiment"})
            assert False, "Should have raised ValueError"
        except ValueError:
            pass

    def test_internal_hub_references_never_enter_rest_payload(self):
        result = json_to_recipe_payload(
            {
                "memory_type": "recipe",
                "trigger": "A concrete trigger long enough",
                "problem": "A concrete problem description long enough",
                "solution": "A concrete validated solution long enough",
                "env_snapshot": "Python 3.10 on Linux with no extra dependencies",
                "_hub_references": ["aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"],
            }
        )
        assert "_hub_references" not in result
