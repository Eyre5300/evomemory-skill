import importlib.util
import sys
import types
import unittest
from pathlib import Path

if "requests" not in sys.modules:
    sys.modules["requests"] = types.ModuleType("requests")
if "urllib3" not in sys.modules:
    urllib3_stub = types.ModuleType("urllib3")
    urllib3_stub.exceptions = types.SimpleNamespace(InsecureRequestWarning=Warning)
    urllib3_stub.disable_warnings = lambda *_args, **_kwargs: None
    sys.modules["urllib3"] = urllib3_stub

_SAN_PATH = Path(__file__).resolve().parent.parent / "evomemory_sync" / "sanitize.py"
_SPEC = importlib.util.spec_from_file_location("evomemory_sanitize_for_test", _SAN_PATH)
_MOD = importlib.util.module_from_spec(_SPEC)
assert _SPEC and _SPEC.loader
_SPEC.loader.exec_module(_MOD)
sanitize_text = _MOD.sanitize_text


class TestExtractorSanitization(unittest.TestCase):
    def test_redacts_common_secrets_and_identifiers(self) -> None:
        src = (
            "api_key=sk-abcdefghijklmnopqrstuvwxyz "
            "email=test.user@example.com "
            "path=C:\\Users\\Alice\\project\\secret.txt "
            "ip=192.168.1.10 "
            "mac=AA:BB:CC:DD:EE:FF"
        )
        out = sanitize_text(src)
        self.assertNotIn("sk-abcdefghijklmnopqrstuvwxyz", out)
        self.assertNotIn("test.user@example.com", out)
        self.assertNotIn("C:\\Users\\Alice\\project\\secret.txt", out)
        self.assertNotIn("192.168.1.10", out)
        self.assertNotIn("AA:BB:CC:DD:EE:FF", out)
        self.assertIn("[REDACTED]", out)

    def test_redacts_api_key_after_underscore(self) -> None:
        src = "foo_api api_key=supersecretvalue123456"
        out = sanitize_text(src)
        self.assertNotIn("supersecretvalue123456", out)
        self.assertIn("[REDACTED]", out)

    def test_redacts_sk_after_my_api_key_assignment(self) -> None:
        src = "my_api_key = sk-abcdefghijklmnopqrst"
        out = sanitize_text(src)
        self.assertNotIn("sk-abcdefghijklmnopqrst", out)
        self.assertIn("[REDACTED]", out)


if __name__ == "__main__":
    unittest.main()
