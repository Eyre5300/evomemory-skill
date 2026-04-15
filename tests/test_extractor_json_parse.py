import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_extractor_parse_fn():
    if "requests" not in sys.modules:
        sys.modules["requests"] = types.ModuleType("requests")
    if "urllib3" not in sys.modules:
        urllib3_stub = types.ModuleType("urllib3")
        urllib3_stub.exceptions = types.SimpleNamespace(InsecureRequestWarning=Warning)
        urllib3_stub.disable_warnings = lambda *_a, **_k: None
        sys.modules["urllib3"] = urllib3_stub

    pkg = types.ModuleType("evomemory_sync")
    pkg.__path__ = [str(_REPO_ROOT / "evomemory_sync")]
    sys.modules["evomemory_sync"] = pkg

    for mod_name, fname in (
        ("evomemory_sync.extraction_fields", "extraction_fields.py"),
        ("evomemory_sync.sanitize", "sanitize.py"),
    ):
        path = _REPO_ROOT / "evomemory_sync" / fname
        spec = importlib.util.spec_from_file_location(mod_name, path)
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = mod
        spec.loader.exec_module(mod)

    ext_path = _REPO_ROOT / "evomemory_sync" / "extractor.py"
    spec = importlib.util.spec_from_file_location("evomemory_sync.extractor", ext_path)
    assert spec and spec.loader
    ext = importlib.util.module_from_spec(spec)
    sys.modules["evomemory_sync.extractor"] = ext
    spec.loader.exec_module(ext)
    return ext._parse_json_object


_parse_json_object = _load_extractor_parse_fn()


class TestExtractorJsonParse(unittest.TestCase):
    def test_plain_object(self) -> None:
        self.assertEqual(_parse_json_object('{"a": 1}'), {"a": 1})

    def test_fenced_json(self) -> None:
        raw = '```json\n{"x": "y"}\n```'
        self.assertEqual(_parse_json_object(raw), {"x": "y"})

    def test_fence_with_inner_triple_backticks_in_string(self) -> None:
        inner = '{"note": "see ```code``` block"}'
        raw = f"```json\n{inner}\n```"
        self.assertEqual(_parse_json_object(raw), json.loads(inner))

    def test_brace_slice_fallback(self) -> None:
        raw = 'Preamble {"k": true} trailing'
        self.assertEqual(_parse_json_object(raw), {"k": True})


if __name__ == "__main__":
    unittest.main()
