import unittest
from pathlib import Path

from scripts.setup import env_path


class TestSetupEnvPath(unittest.TestCase):
    def test_default_env_path_points_repo_root(self) -> None:
        expected = (Path(__file__).resolve().parent.parent / ".env").resolve()
        self.assertEqual(env_path(None), expected)


if __name__ == "__main__":
    unittest.main()

