"""Tests for upload curator validation (no LLM)."""

import importlib.util
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "evomemory_sync"


def _load_curator():
    """Load upload_curator without importing evomemory_sync package __init__."""
    for name in ("env_loader", "extraction_fields", "extractor", "hub_url", "uploader", "upload_semantic"):
        p = PKG / f"{name}.py"
        spec = importlib.util.spec_from_file_location(f"evomemory_sync.{name}", p)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[f"evomemory_sync.{name}"] = mod
        assert spec.loader
        spec.loader.exec_module(mod)
    p = PKG / "upload_curator.py"
    spec = importlib.util.spec_from_file_location("evomemory_sync.upload_curator", p)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["evomemory_sync.upload_curator"] = mod
    assert spec.loader
    spec.loader.exec_module(mod)
    return mod


_curator = _load_curator()
_validate_decision = _curator._validate_decision


def test_validate_skip():
    d = _validate_decision(
        {"action": "skip", "reason": "duplicate"},
        similar_ctx={"own_ids": []},
        draft={"memory_type": "recipe"},
    )
    assert d is not None
    assert d.action == "skip"


def test_validate_update_own_id():
    own_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    d = _validate_decision(
        {
            "action": "update",
            "update_memory_id": own_id,
            "reason": "refine",
            "refined": {
                "memory_type": "recipe",
                "trigger": "t",
                "problem": "p",
                "solution": "s",
            },
        },
        similar_ctx={"own_ids": [own_id], "similar_own_top1": {"id": own_id, "similarity": 0.95}},
        draft={"memory_type": "recipe", "trigger": "t", "problem": "p", "solution": "s"},
    )
    assert d is not None
    assert d.action == "update"
    assert d.update_memory_id == own_id


def test_validate_update_rejects_foreign_id_uses_own_fallback():
    own_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    foreign = "11111111-2222-3333-4444-555555555555"
    d = _validate_decision(
        {
            "action": "update",
            "update_memory_id": foreign,
            "reason": "refine",
            "refined": {
                "memory_type": "recipe",
                "trigger": "t",
                "problem": "p",
                "solution": "s",
            },
        },
        similar_ctx={"own_ids": [own_id], "similar_own_top1": {"id": own_id, "similarity": 0.95}},
        draft={"memory_type": "recipe"},
    )
    assert d is not None
    assert d.action == "update"
    assert d.update_memory_id == own_id


def test_validate_update_below_similarity_gate_forces_clean_create(monkeypatch):
    monkeypatch.setenv("EVOMEMORY_CURATOR_UPDATE_MIN_SIMILARITY", "0.82")
    own_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    draft = {
        "memory_type": "recipe",
        "trigger": "MBPP task 79",
        "problem": "check odd word length",
        "solution": "return len(word) % 2 == 1",
    }
    d = _validate_decision(
        {
            "action": "update",
            "update_memory_id": own_id,
            "reason": "merge unrelated cards",
            "refined": {
                "memory_type": "recipe",
                "trigger": "difference of squares plus word length",
                "problem": "polluted merged problem",
                "solution": "polluted merged solution",
            },
        },
        similar_ctx={
            "own_ids": [own_id],
            "similar_own_top1": {"id": own_id, "similarity": 0.63},
        },
        draft=draft,
    )
    assert d is not None
    assert d.action == "create"
    assert d.update_memory_id is None
    assert d.refined["problem"] == draft["problem"]
