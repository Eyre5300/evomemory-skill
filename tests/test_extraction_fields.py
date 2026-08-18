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

    def test_normalize_ideation_rationale_alias(self) -> None:
        m = _load_extraction_fields()
        raw = {
            "memory_type": "ideation",
            "goal": "g",
            "why_promising": "because",
        }
        out = m.normalize_llm_extraction(raw)
        self.assertEqual(out["rationale"], "because")

    def test_normalize_legacy_experiment_status(self) -> None:
        m = _load_extraction_fields()
        out = m.normalize_llm_extraction({"memory_type": "experiment", "status": "failed"})
        self.assertEqual(out["outcome"], "failure")

    def test_extractor_prompt_does_not_skip_only_for_missing_versions(self) -> None:
        m = _load_extraction_fields()
        prompt = m.EXTRACTOR_SYSTEM_PROMPT
        self.assertIn("do NOT skip solely for missing versions", prompt)
        self.assertIn("rather than skipping", prompt)


if __name__ == "__main__":
    unittest.main()
