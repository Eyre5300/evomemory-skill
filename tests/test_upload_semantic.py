"""Tests for semantic upload dedup decision logic."""

import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from evomemory_sync.upload_semantic import (
    build_search_query,
    decide_upload_action,
)


def test_build_search_query_recipe():
    q = build_search_query(
        "recipe",
        {"trigger": "deploy", "problem": "crash", "solution": "increase memory"},
    )
    assert "deploy" in q
    assert "crash" in q


@patch("evomemory_sync.upload_semantic.fetch_current_user_id", return_value="user-1")
@patch("evomemory_sync.upload_semantic.search_similar")
def test_decide_update_own_top1(mock_search, _mock_me):
    mock_search.return_value = [
        {"id": "aaa", "author_user_id": "user-1", "similarity_score": 0.91},
        {"id": "bbb", "author_user_id": "user-2", "similarity_score": 0.88},
    ]
    action, mid, own, others = decide_upload_action(
        "recipe",
        {"trigger": "t", "problem": "p", "solution": "s"},
        {"Authorization": "Bearer x"},
    )
    assert action == "update"
    assert mid == "aaa"
    assert own is not None
    assert len(others) == 1


@patch("evomemory_sync.upload_semantic.fetch_current_user_id", return_value="user-1")
@patch("evomemory_sync.upload_semantic.search_similar")
def test_decide_skip_similar_community(mock_search, _mock_me):
    mock_search.return_value = [
        {"id": "bbb", "author_user_id": "user-2", "similarity_score": 0.95},
        {"id": "ccc", "author_user_id": "user-3", "similarity_score": 0.92},
    ]
    action, mid, _own, others = decide_upload_action(
        "recipe",
        {"trigger": "t", "problem": "p", "solution": "s"},
        {"Authorization": "Bearer x"},
    )
    assert action == "skip_duplicate"
    assert mid is None
    assert len(others) == 2


@patch("evomemory_sync.upload_semantic.fetch_current_user_id", return_value="user-1")
@patch("evomemory_sync.upload_semantic.search_similar")
def test_decide_upload_when_own_below_threshold(mock_search, _mock_me):
    mock_search.return_value = [
        {"id": "aaa", "author_user_id": "user-1", "similarity_score": 0.70},
    ]
    action, mid, _, _ = decide_upload_action(
        "recipe",
        {"trigger": "t", "problem": "p", "solution": "s"},
        {"Authorization": "Bearer x"},
    )
    assert action == "upload"
    assert mid is None
