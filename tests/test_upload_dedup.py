import functools
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_UPLOAD_DEDUP_PATH = _REPO_ROOT / "evomemory_sync" / "upload_dedup.py"


@functools.lru_cache(maxsize=1)
def _upload_dedup_mod():
    """Load upload_dedup without importing evomemory_sync package (avoids heavy deps in CI)."""
    spec = importlib.util.spec_from_file_location(
        "evomemory_sync.upload_dedup_isolated",
        _UPLOAD_DEDUP_PATH,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestUploadDedup(unittest.TestCase):
    def test_fingerprint_order_invariant(self) -> None:
        u = _upload_dedup_mod()
        fingerprint_context = u.fingerprint_context

        a = {"task": "x", "nested": {"y": 1}}
        b = {"nested": {"y": 1}, "task": "x"}
        self.assertEqual(fingerprint_context(a), fingerprint_context(b))

    def test_should_skip_after_mark(self) -> None:
        u = _upload_dedup_mod()

        with tempfile.TemporaryDirectory() as td:
            state = Path(td) / "dedup.json"
            old_state = os.environ.get("EVOMEMORY_UPLOAD_DEDUP_STATE_FILE")
            old_win = os.environ.get("EVOMEMORY_UPLOAD_DEDUP_WINDOW_SECONDS")
            old_en = os.environ.get("EVOMEMORY_UPLOAD_DEDUP_ENABLED")
            try:
                os.environ["EVOMEMORY_UPLOAD_DEDUP_STATE_FILE"] = str(state)
                os.environ["EVOMEMORY_UPLOAD_DEDUP_WINDOW_SECONDS"] = "3600"
                os.environ["EVOMEMORY_UPLOAD_DEDUP_ENABLED"] = "1"

                fp = "a" * 64
                self.assertFalse(u.should_skip_duplicate(fp))
                # Failed extract/upload must not occupy the slot.
                self.assertFalse(u.should_skip_duplicate(fp))
                u.mark_upload_succeeded(fp)
                self.assertTrue(u.should_skip_duplicate(fp))
            finally:
                if old_state is None:
                    os.environ.pop("EVOMEMORY_UPLOAD_DEDUP_STATE_FILE", None)
                else:
                    os.environ["EVOMEMORY_UPLOAD_DEDUP_STATE_FILE"] = old_state
                if old_win is None:
                    os.environ.pop("EVOMEMORY_UPLOAD_DEDUP_WINDOW_SECONDS", None)
                else:
                    os.environ["EVOMEMORY_UPLOAD_DEDUP_WINDOW_SECONDS"] = old_win
                if old_en is None:
                    os.environ.pop("EVOMEMORY_UPLOAD_DEDUP_ENABLED", None)
                else:
                    os.environ["EVOMEMORY_UPLOAD_DEDUP_ENABLED"] = old_en


if __name__ == "__main__":
    unittest.main()
