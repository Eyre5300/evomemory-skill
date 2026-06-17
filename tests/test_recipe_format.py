"""Tests for structured recipe formatting."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from evomemory_sync.recipe_format import (
    format_env_snapshot_section,
    prepare_recipe_hub_fields,
)
from evomemory_sync.uploader import json_to_recipe_payload


def test_structured_recipe_formats_prose_not_labels():
    data = {
        "memory_type": "recipe",
        "trigger": "OOM",
        "problem": {
            "task_type": "代码调试",
            "domain": "Python web应用",
            "constraints": "仅 execute",
            "state": "启动 500",
        },
        "solution": {
            "method": "减小 batch",
            "parameters": "batch_size=32",
            "rationale": "峰值显存过高，减半 batch 降低激活占用",
        },
        "env_snapshot": {
            "creator": "gpt-4 + run-1",
            "software_dependencies": "torch==2.3",
            "tool_dependencies": "execute",
            "environment": "CUDA 12",
        },
        "result": "ok",
        "tags": "gpu",
    }
    fields = prepare_recipe_hub_fields(data)
    assert "task_type:" not in fields["problem"]
    assert "domain:" not in fields["problem"]
    assert "代码调试" in fields["problem"]
    assert "Python web应用" in fields["problem"]
    assert "仅 execute" in fields["problem"]
    assert "启动 500" in fields["problem"]

    assert "method:" not in fields["solution"]
    assert "rationale:" not in fields["solution"]
    assert "减小 batch" in fields["solution"]
    assert "batch_size=32" in fields["solution"]
    assert "峰值显存过高" in fields["solution"]

    assert "creator:" not in fields["env_snapshot"]
    assert "software_dependencies:" not in fields["env_snapshot"]
    assert "gpt-4 + run-1" in fields["env_snapshot"]
    assert "torch==2.3" in fields["env_snapshot"]


def test_creator_fallback_from_agent_metadata():
    data = {
        "memory_type": "recipe",
        "trigger": "t",
        "problem": {"task_type": "a", "domain": "b", "constraints": "c", "state": "d"},
        "solution": {"method": "m", "parameters": "p", "rationale": "r"},
        "env_snapshot": {},
        "_agent_metadata": {"model": "Qwen-72B", "instance_id": "thread-xyz"},
        "result": "ok",
    }
    env = format_env_snapshot_section(data)
    assert "creator:" not in env
    assert "Qwen-72B + thread-xyz" in env


def test_legacy_free_text_still_works():
    data = {
        "memory_type": "recipe",
        "trigger": "When X",
        "problem": "plain problem text",
        "solution": "plain solution",
        "env_snapshot": "torch 2.3",
        "result": "done",
    }
    result = json_to_recipe_payload(data)
    assert result["problem"] == "plain problem text"
    assert result["solution"] == "plain solution"
