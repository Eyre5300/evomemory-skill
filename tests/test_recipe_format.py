"""Tests for recipe Hub field pass-through (LLM prose, no template stitching)."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from evomemory_sync.recipe_format import (
    format_env_snapshot_section,
    prepare_recipe_hub_fields,
    transferable_recipe_title,
)
from evomemory_sync.extraction_fields import normalize_llm_extraction
from evomemory_sync.uploader import json_to_recipe_payload


def test_prose_strings_pass_through_unchanged():
    problem = (
        "在 Python web 应用里做代码调试，只能用 execute，服务启动即 500，"
        "日志显示 ImportError 来自缺失的 flask 扩展。"
    )
    solution = (
        "安装 flask-cors==4.0.0 并在 app 上注册 CORS。这样选是因为 500 由 import 失败引起，"
        "先补齐依赖比改业务逻辑更直接。"
    )
    env = "由 gpt-4 + run-1 总结；依赖 Flask==3.0，通过 execute 安装，运行在 Linux 容器内。"
    data = {
        "memory_type": "recipe",
        "trigger": "Flask 500 on boot",
        "problem": problem,
        "solution": solution,
        "env_snapshot": env,
        "result": "ok",
        "tags": "flask",
    }
    fields = prepare_recipe_hub_fields(data)
    assert fields["problem"] == problem
    assert fields["solution"] == solution
    assert fields["env_snapshot"] == env
    assert "task_type:" not in fields["problem"]


def test_nested_dict_deprecated_not_stitched():
    data = {
        "memory_type": "recipe",
        "trigger": "t",
        "problem": {"task_type": "代码调试", "domain": "web", "constraints": "x", "state": "y"},
        "solution": {"method": "m", "parameters": "p", "rationale": "r"},
        "env_snapshot": {"creator": "a"},
        "result": "ok",
    }
    fields = prepare_recipe_hub_fields(data)
    assert fields["problem"] == ""
    assert fields["solution"] == ""
    assert fields["env_snapshot"] == ""


def test_normalize_clears_legacy_nested_sections():
    raw = {
        "memory_type": "recipe",
        "problem": {"task_type": "a"},
        "solution": "already prose",
        "env_snapshot": '{"creator":"x"}',
    }
    out = normalize_llm_extraction(raw)
    assert out["problem"] == ""
    assert out["solution"] == "already prose"
    assert out["env_snapshot"] == ""


def test_creator_fallback_only_when_env_missing():
    data = {
        "memory_type": "recipe",
        "trigger": "t",
        "problem": "p",
        "solution": "s",
        "env_snapshot": "",
        "_agent_metadata": {"model": "Qwen-72B", "instance_id": "thread-xyz"},
        "result": "ok",
    }
    env = format_env_snapshot_section(data)
    assert "Qwen-72B + thread-xyz" in env
    assert "本经验由" in env


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


def test_benchmark_only_trigger_falls_back_to_problem_semantics():
    result = json_to_recipe_payload(
        {
            "memory_type": "recipe",
            "trigger": "MBPP task_id=56",
            "problem": "Write a python function to check whether an integer is one less than twice its decimal reverse.",
            "solution": "Reverse the decimal digits and compare n + 1 with 2 * reversed_n.",
        }
    )
    assert result["trigger"] == "check whether an integer is one less than twice its decimal reverse"
    assert "MBPP" not in result["trigger"]
    assert "56" not in result["trigger"]


def test_semantic_part_survives_evaluation_marker_removal():
    title = transferable_recipe_title(
        "HumanEval problem 12: preserve stable order while removing duplicates",
        "Sequence deduplication problem.",
    )
    assert title == "preserve stable order while removing duplicates"


def test_chinese_case_number_is_not_a_recipe_title():
    title = transferable_recipe_title(
        "LiveCodeBench 第 477 题",
        "将混合大小写字符串统一转换为小写，同时保留数字和标点。",
    )
    assert title == "将混合大小写字符串统一转换为小写，同时保留数字和标点"
    assert "477" not in title


def test_normal_semantic_trigger_is_preserved():
    title = transferable_recipe_title(
        "Flask 500 on boot after extension upgrade",
        "A Flask service fails during startup.",
    )
    assert title == "Flask 500 on boot after extension upgrade"


def test_benchmark_prefix_and_command_style_become_capability_title():
    title = transferable_recipe_title(
        "MBPP task_id=59. Write a function to find the nth octagonal number.",
        "Compute an octagonal figurate number from its one-based index.",
    )
    assert title == "find the nth octagonal number"
