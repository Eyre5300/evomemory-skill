import importlib.util
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_MOD_PATH = _REPO_ROOT / "evomemory_sync" / "extraction_fields.py"


def _load_extraction_fields():
    spec = importlib.util.spec_from_file_location(
        "evomemory_sync.extraction_fields_isolated",
        _MOD_PATH,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestExtractionFields(unittest.TestCase):
    def test_normalize_experiment_aliases(self) -> None:
        m = _load_extraction_fields()
        raw = {
            "memory_type": "experiment",
            "proposal_context": "pc",
            "data_strategy": "ds",
            "model_strategy": "ms",
            "environment_constraints": "ec",
        }
        out = m.normalize_llm_extraction(raw)
        self.assertEqual(out["task_description"], "pc")
        self.assertEqual(out["data_summary"], "ds")

    def test_normalize_failed_ideation_proposal_from_goal(self) -> None:
        m = _load_extraction_fields()
        raw = {
            "memory_type": "ideation",
            "status": "failed",
            "goal": "g",
        }
        out = m.normalize_llm_extraction(raw)
        self.assertEqual(out["proposal_summary"], "g")


if __name__ == "__main__":
    unittest.main()
