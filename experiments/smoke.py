"""Local smoke test: prove the consumer agent does multi-step tool use on local qwen.

Run from repo root (no API cost):
    python -m experiments.smoke
"""

from __future__ import annotations

from .agent import run_consumer
from .config import CONSUMER

TASK = "Compute (123 * 7 + 19) ** 2 minus 5000 using the calculator tool, then give the final number."


def main() -> int:
    print(f"consumer model = {CONSUMER.model} @ {CONSUMER.base_url}")
    res = run_consumer(TASK)
    print("error      :", res.error or "(none)")
    print("steps      :", res.steps)
    print("tool_calls :", res.tool_calls)
    print("answer     :", res.answer)
    # Expected: (123*7+19)**2 - 5000 = 880**2 - 5000 = 774400 - 5000 = 769400
    ok = res.ok and "769400" in res.answer.replace(",", "")
    print("SMOKE OK   :", ok)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
