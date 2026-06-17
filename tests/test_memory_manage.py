"""Tests for memory_manage trash/delete."""

import os
import sys
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from evomemory_sync.memory_manage import trash_or_delete_memory

MID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
HEADERS = {"Authorization": "Bearer test"}


def test_first_delete_moves_to_trash():
    with mock.patch("evomemory_sync.memory_manage.get_own_memory_row") as get_row:
        get_row.return_value = {"id": MID, "visibility": "public"}
        with mock.patch("evomemory_sync.memory_manage.requests.patch") as patch:
            patch.return_value = mock.Mock(status_code=200, text="{}")
            out = trash_or_delete_memory("recipe", MID, headers=HEADERS)
    assert out["action"] == "moved_to_trash"
    patch.assert_called_once()


def test_second_delete_permanent():
    with mock.patch("evomemory_sync.memory_manage.get_own_memory_row") as get_row:
        get_row.return_value = {"id": MID, "visibility": "hidden"}
        with mock.patch("evomemory_sync.memory_manage.requests.delete") as delete:
            delete.return_value = mock.Mock(status_code=200, text="{}")
            out = trash_or_delete_memory("recipe", MID, headers=HEADERS)
    assert out["action"] == "permanently_deleted"
    delete.assert_called_once()
