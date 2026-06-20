"""A local code-repair environment (mini SWE-bench) for the closed-loop MVP.

Gives the agent a genuinely multi-step task with a real exploration space: a small
multi-file project with one failing test. Tools: list_files, read_file, edit_file,
run_tests. Each run gets a fresh copy of the pristine project so edits don't leak
across runs. Grading = do the tests pass (checked independently of the agent's
self-report).
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

PROJECTS = Path(__file__).resolve().parent / "projects"

TASK_PROMPT = (
    "A unit test in this Python project is failing. Use the tools to explore the "
    "project, find the single bug, and fix it so that ALL tests pass. Do NOT modify "
    "any test file. Call run_tests to confirm. When all tests pass, reply with "
    "'FINAL ANSWER: fixed'."
)

CODE_SYSTEM = (
    "You are a software engineer fixing a bug in a small Python project. Work step by "
    "step using the tools. Read the failing test first to understand expected behavior, "
    "then locate the responsible source file and make a minimal edit. Verify with run_tests."
)


def make_workdir(task_id: str = "cart") -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="codeenv_"))
    dst = tmp / task_id
    shutil.copytree(PROJECTS / task_id, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    return dst


class CodeEnv:
    def __init__(self, root: Path):
        self.root = Path(root)

    def cleanup(self) -> None:
        shutil.rmtree(self.root.parent, ignore_errors=True)

    def list_files(self) -> str:
        out = []
        for p in sorted(self.root.rglob("*")):
            if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc":
                out.append(str(p.relative_to(self.root)).replace("\\", "/"))
        return "\n".join(out) or "(empty)"

    def read_file(self, path: str) -> str:
        f = self.root / path
        if not f.is_file():
            return f"ERROR: no such file: {path}"
        text = f.read_text(encoding="utf-8", errors="ignore")
        return text[:6000] + ("\n...[truncated]" if len(text) > 6000 else "")

    def edit_file(self, path: str, old: str, new: str) -> str:
        f = self.root / path
        if not f.is_file():
            return f"ERROR: no such file: {path}"
        text = f.read_text(encoding="utf-8")
        n = text.count(old)
        if n == 0:
            return "ERROR: old string not found (copy it exactly from read_file)"
        if n > 1:
            return f"ERROR: old string is not unique ({n} matches); add surrounding context"
        f.write_text(text.replace(old, new), encoding="utf-8")
        return "OK: edit applied"

    def _pytest(self) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-m", "pytest", "-q"], cwd=str(self.root),
            capture_output=True, text=True, timeout=120,
        )

    def run_tests(self) -> str:
        r = self._pytest()
        status = "ALL TESTS PASSED" if r.returncode == 0 else "TESTS FAILED"
        return f"{status}\n{(r.stdout or '')[-1500:]}"

    def tests_pass(self) -> bool:
        return self._pytest().returncode == 0


def code_tools_openai() -> list[dict[str, Any]]:
    def fn(name, desc, props=None, required=None):
        return {"type": "function", "function": {
            "name": name, "description": desc,
            "parameters": {"type": "object", "properties": props or {}, "required": required or []},
        }}
    return [
        fn("list_files", "List all files in the project (relative paths)."),
        fn("read_file", "Read a source file by its project-relative path.",
           {"path": {"type": "string"}}, ["path"]),
        fn("edit_file", "Replace an exact, unique substring in a file with new text. "
           "Copy `old` verbatim from read_file output, with enough context to be unique.",
           {"path": {"type": "string"}, "old": {"type": "string"}, "new": {"type": "string"}},
           ["path", "old", "new"]),
        fn("run_tests", "Run the project's test suite and report pass/fail."),
    ]


def code_executor(env: CodeEnv) -> Callable[[str, dict[str, Any]], str]:
    def execute(name: str, args: dict[str, Any]) -> str:
        a = args or {}
        if name == "list_files":
            return env.list_files()
        if name == "read_file":
            return env.read_file(a.get("path", ""))
        if name == "edit_file":
            return env.edit_file(a.get("path", ""), a.get("old", ""), a.get("new", ""))
        if name == "run_tests":
            return env.run_tests()
        return f"ERROR: unknown tool {name!r}"
    return execute
