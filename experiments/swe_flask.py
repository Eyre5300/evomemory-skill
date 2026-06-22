"""Multi-task SWE-bench-style suite on a real large repo (Flask).

Several distinct bugs in the actual Flask source tree (hundreds of files). Each task
reverts the repo to a BASE state (its bug present) by removing a guard, and is graded
by a behavioral check run in a pinned Flask-2.3-era venv (no Docker, no brittle old
pytest). The agent navigates with list_dir / search_code / read_file / edit_file /
run_tests — a genuinely large exploration space.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

# Paths are env-configurable so the same harness runs on the Windows dev box and the
# Linux GPU cluster (tate). Defaults are the local Windows dev paths.
_SRC = Path(os.environ.get(
    "EVOMEMORY_FLASK_SRC", os.path.expanduser("~/skill经验/swebench_eval/flask_src")))
_VENV_PY = Path(os.environ.get(
    "EVOMEMORY_FLASK_VENV_PY", os.path.expanduser("~/skill经验/flask_venv/Scripts/python.exe")))

CODE_SYSTEM = (
    "You are a software engineer fixing a bug in a large real Python repository (Flask). "
    "Navigate with list_dir and search_code, read the relevant source, make a minimal edit, "
    "and verify with run_tests. Work step by step."
)


@dataclass(frozen=True)
class FlaskTask:
    id: str
    kind: str
    file: str          # repo-relative path containing the bug
    bug_block: str     # exact text removed to create the buggy BASE state
    check: str         # python snippet -> prints 'ALL TESTS PASSED' or 'TESTS FAILED...'
    issue: str         # task prompt for the agent
    experience: str    # producer's L1 experience (anchor + exact insertion)


_CHK_EMPTY = (
    "import flask\nfrom flask import Blueprint\nok=True\n"
    "try:\n Blueprint('', 'x'); ok=False\nexcept ValueError: pass\nexcept Exception: ok=False\n"
    "try:\n Blueprint('good', 'x')\nexcept Exception: ok=False\n"
    "print('ALL TESTS PASSED' if ok else 'TESTS FAILED: Blueprint(\"\") must raise ValueError')\n"
)
_CHK_DOT = (
    "import flask\nfrom flask import Blueprint\nok=True\n"
    "try:\n Blueprint('a.b', 'x'); ok=False\nexcept ValueError: pass\nexcept Exception: ok=False\n"
    "try:\n Blueprint('good', 'x')\nexcept Exception: ok=False\n"
    "print('ALL TESTS PASSED' if ok else 'TESTS FAILED: Blueprint(\"a.b\") must raise ValueError')\n"
)
_CHK_OPENRES = (
    "import flask\napp=flask.Flask('x')\nok=True\n"
    "try:\n app.open_resource('anything', 'w'); ok=False\nexcept ValueError: pass\nexcept Exception: ok=False\n"
    "print('ALL TESTS PASSED' if ok else 'TESTS FAILED: open_resource write mode must raise ValueError')\n"
)

FLASK_TASKS: list[FlaskTask] = [
    FlaskTask(
        "flask_blueprint_empty", "validation", "src/flask/blueprints.py",
        '        if not name:\n            raise ValueError("\'name\' must not be empty.")\n',
        _CHK_EMPTY,
        "flask.Blueprint can be constructed with an empty name without complaint, which is wrong; "
        "it should raise ValueError on an empty name. Explore the repo, find the right source file, "
        "and add the validation so flask.Blueprint(\"\", __name__) raises ValueError. Use run_tests.",
        "The bug is in src/flask/blueprints.py, inside Blueprint.__init__. Find this existing line:\n"
        "        self.name = name\n"
        "Immediately BEFORE it, insert:\n"
        "        if not name:\n"
        "            raise ValueError(\"'name' must not be empty.\")\n"
        "Use edit_file with old = the existing line and new = the inserted lines followed by that "
        "existing line. Do not edit tests. Then run_tests.",
    ),
    FlaskTask(
        "flask_blueprint_dot", "validation", "src/flask/blueprints.py",
        '        if "." in name:\n            raise ValueError("\'name\' may not contain a dot \'.\' character.")\n',
        _CHK_DOT,
        "flask.Blueprint accepts a name containing a '.' character without complaint; it should raise "
        "ValueError for a dotted name. Find the right source file and add the validation so "
        "flask.Blueprint(\"a.b\", __name__) raises ValueError. Use run_tests.",
        "The bug is in src/flask/blueprints.py, inside Blueprint.__init__. Find this existing line:\n"
        "        self.name = name\n"
        "Immediately BEFORE it, insert:\n"
        "        if \".\" in name:\n"
        "            raise ValueError(\"'name' may not contain a dot '.' character.\")\n"
        "Use edit_file with old = the existing line and new = the inserted lines followed by that "
        "existing line. Do not edit tests. Then run_tests.",
    ),
    FlaskTask(
        "flask_open_resource_mode", "io-guard", "src/flask/scaffold.py",
        '        if mode not in {"r", "rt", "rb"}:\n            raise ValueError("Resources can only be opened for reading.")\n',
        _CHK_OPENRES,
        "Flask's open_resource() method accepts any file mode, but resources should only be opened for "
        "reading; opening with a write mode should raise ValueError. Find the right source file and add "
        "the mode validation. Use run_tests.",
        "The bug is in src/flask/scaffold.py, in the open_resource method. Find this existing line:\n"
        "        return open(os.path.join(self.root_path, resource), mode)\n"
        "Immediately BEFORE it, insert:\n"
        "        if mode not in {\"r\", \"rt\", \"rb\"}:\n"
        "            raise ValueError(\"Resources can only be opened for reading.\")\n"
        "Use edit_file with old = the existing return line and new = the inserted lines followed by that "
        "existing return line. Do not edit tests. Then run_tests.",
    ),
]

TASKS_BY_ID = {t.id: t for t in FLASK_TASKS}


def make_flask_workdir(task: FlaskTask) -> Path:
    """Fresh copy of Flask reverted to this task's BASE state (its bug present)."""
    tmp = Path(tempfile.mkdtemp(prefix="swe_flask_"))
    dst = tmp / "flask_src"
    shutil.copytree(_SRC, dst, ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"))
    f = dst / task.file
    t = f.read_text(encoding="utf-8")
    if task.bug_block in t:
        f.write_text(t.replace(task.bug_block, "", 1), encoding="utf-8")
    return dst


class FlaskEnv:
    def __init__(self, root: Path, check: str):
        self.root = Path(root)
        self.check = check

    def cleanup(self) -> None:
        shutil.rmtree(self.root.parent, ignore_errors=True)

    def list_dir(self, path: str = "") -> str:
        base = self.root / path
        if not base.is_dir():
            return f"ERROR: not a directory: {path or '.'}"
        items = [p.name + ("/" if p.is_dir() else "") for p in sorted(base.iterdir())
                 if p.name not in ("__pycache__", ".git")]
        return "\n".join(items) or "(empty)"

    def read_file(self, path: str) -> str:
        f = self.root / path
        if not f.is_file():
            return f"ERROR: no such file: {path}"
        t = f.read_text(encoding="utf-8", errors="ignore")
        return t[:7000] + ("\n...[truncated]" if len(t) > 7000 else "")

    def search_code(self, pattern: str) -> str:
        try:
            rx = re.compile(pattern)
        except re.error as e:
            return f"ERROR: bad regex: {e}"
        hits = []
        for p in self.root.rglob("*.py"):
            if "__pycache__" in p.parts:
                continue
            try:
                for i, line in enumerate(p.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                    if rx.search(line):
                        rel = str(p.relative_to(self.root)).replace("\\", "/")
                        hits.append(f"{rel}:{i}: {line.strip()[:120]}")
                        if len(hits) >= 40:
                            return "\n".join(hits) + "\n...[more matches truncated]"
            except Exception:
                pass
        return "\n".join(hits) or "(no matches)"

    def edit_file(self, path: str, old: str, new: str) -> str:
        f = self.root / path
        if not f.is_file():
            return f"ERROR: no such file: {path}"
        text = f.read_text(encoding="utf-8")
        c = text.count(old)
        if c == 0:
            return "ERROR: old string not found (copy it exactly from read_file)"
        if c > 1:
            return f"ERROR: old string not unique ({c} matches); add surrounding context"
        f.write_text(text.replace(old, new), encoding="utf-8")
        return "OK: edit applied"

    def _run(self) -> subprocess.CompletedProcess:
        return subprocess.run(
            [str(_VENV_PY), "-c", self.check], cwd=str(self.root),
            capture_output=True, text=True, timeout=90,
            env=dict(os.environ, PYTHONPATH=str(self.root / "src")),
        )

    def run_tests(self) -> str:
        r = self._run()
        return r.stdout.strip() or ("ERROR: " + r.stderr.strip()[-200:])

    def tests_pass(self) -> bool:
        return "ALL TESTS PASSED" in self._run().stdout


def flask_tools_openai() -> list[dict[str, Any]]:
    def fn(name, desc, props=None, required=None):
        return {"type": "function", "function": {
            "name": name, "description": desc,
            "parameters": {"type": "object", "properties": props or {}, "required": required or []}}}
    return [
        fn("list_dir", "List the entries of one directory (relative path; '' for repo root).",
           {"path": {"type": "string"}}),
        fn("search_code", "Search all .py files for a regex; returns matching file:line:text.",
           {"pattern": {"type": "string"}}, ["pattern"]),
        fn("read_file", "Read a source file by repo-relative path.", {"path": {"type": "string"}}, ["path"]),
        fn("edit_file", "Replace an exact unique substring in a file (copy `old` verbatim from read_file).",
           {"path": {"type": "string"}, "old": {"type": "string"}, "new": {"type": "string"}},
           ["path", "old", "new"]),
        fn("run_tests", "Run the behavioral check and report pass/fail."),
    ]


def flask_executor(env: FlaskEnv) -> Callable[[str, dict[str, Any]], str]:
    def execute(name: str, args: dict[str, Any]) -> str:
        a = args or {}
        if name == "list_dir":
            return env.list_dir(a.get("path", ""))
        if name == "search_code":
            return env.search_code(a.get("pattern", ""))
        if name == "read_file":
            return env.read_file(a.get("path", ""))
        if name == "edit_file":
            return env.edit_file(a.get("path", ""), a.get("old", ""), a.get("new", ""))
        if name == "run_tests":
            return env.run_tests()
        return f"ERROR: unknown tool {name!r}"
    return execute
