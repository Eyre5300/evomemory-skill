import unittest

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


if __name__ == "__main__":
    unittest.main()

