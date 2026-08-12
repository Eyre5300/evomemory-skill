import unittest
from tempfile import TemporaryDirectory

import importlib.util
from pathlib import Path

_ENV_LOADER_PATH = Path(__file__).resolve().parent.parent / "evomemory_sync" / "env_loader.py"
_SPEC = importlib.util.spec_from_file_location("evomemory_sync_env_loader_for_test", _ENV_LOADER_PATH)
_MOD = importlib.util.module_from_spec(_SPEC)
assert _SPEC and _SPEC.loader
_SPEC.loader.exec_module(_MOD)
candidate_env_paths = _MOD.candidate_env_paths
repo_root = _MOD.repo_root


class TestEnvLoader(unittest.TestCase):
    def test_candidate_paths(self) -> None:
        root = repo_root()
        paths = candidate_env_paths()
        self.assertEqual(paths[0], root / ".env")
        self.assertEqual(paths[1], root / "scripts" / ".env")

    def test_adaptation_key_is_created_once_and_reused(self) -> None:
        original_root = _MOD.repo_root
        old_key = _MOD.os.environ.pop("EVOMEMORY_ADAPTATION_FINGERPRINT_KEY", None)
        try:
            with TemporaryDirectory() as temp:
                root = Path(temp)
                _MOD.repo_root = lambda: root
                first = _MOD.adaptation_fingerprint_key()
                _MOD.os.environ.pop("EVOMEMORY_ADAPTATION_FINGERPRINT_KEY", None)
                second = _MOD.adaptation_fingerprint_key()
                self.assertEqual(first, second)
                self.assertIn("EVOMEMORY_ADAPTATION_FINGERPRINT_KEY=", (root / ".env").read_text())
        finally:
            _MOD.repo_root = original_root
            if old_key is None:
                _MOD.os.environ.pop("EVOMEMORY_ADAPTATION_FINGERPRINT_KEY", None)
            else:
                _MOD.os.environ["EVOMEMORY_ADAPTATION_FINGERPRINT_KEY"] = old_key


if __name__ == "__main__":
    unittest.main()

