import json

from evomemory_sync.usage_telemetry import record_llm_usage


def test_record_llm_usage_is_content_free(tmp_path, monkeypatch):
    target = tmp_path / "usage.jsonl"
    monkeypatch.setenv("EVOMEMORY_USAGE_LOG_FILE", str(target))
    monkeypatch.setenv("EVOMEMORY_AGENT_INSTANCE_ID", "agent-a")

    record_llm_usage(
        "extractor",
        "cheap-model",
        {
            "usage": {"prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15},
            "choices": [{"message": {"content": "private completion"}}],
        },
    )

    row = json.loads(target.read_text(encoding="utf-8"))
    assert row["stage"] == "extractor"
    assert row["input_tokens"] == 12
    assert row["output_tokens"] == 3
    assert row["total_tokens"] == 15
    assert row["agent_instance_id"] == "agent-a"
    assert "private completion" not in target.read_text(encoding="utf-8")


def test_record_llm_usage_accepts_responses_style_names(tmp_path, monkeypatch):
    target = tmp_path / "usage.jsonl"
    monkeypatch.setenv("EVOMEMORY_USAGE_LOG_FILE", str(target))

    record_llm_usage("curator", "m", {"usage": {"input_tokens": 7, "output_tokens": 2}})

    row = json.loads(target.read_text(encoding="utf-8"))
    assert row["total_tokens"] == 9
