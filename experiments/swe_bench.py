"""Real SWE-bench Verified tasks, Docker-free.

For each task we: clone the repo from a local cache, checkout its base_commit,
apply the task's test_patch (which adds the failing tests), and grade by running
the FAIL_TO_PASS tests with pytest in a per-repo venv. The agent navigates the
real repository with the same tools as the Flask harness, so SweTask/SweEnv plug
straight into run_consumer / the experiment driver.

Layout on the server (EVOMEMORY_SWEBENCH_DIR, default ~/bty/swebench):
    subset_purepy.json     cached task list (repo/base_commit/test_patch/FAIL_TO_PASS/…)
    repos/<name>           a full git clone of each repo (checked out per task)
    venvs/<name>/bin/python a venv with that repo's deps + pytest
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

SWEBENCH_DIR = Path(os.environ.get("EVOMEMORY_SWEBENCH_DIR", os.path.expanduser("~/bty/swebench")))
REPOS_DIR = SWEBENCH_DIR / "repos"
VENVS_DIR = SWEBENCH_DIR / "venvs"

CODE_SYSTEM = (
    "You are a software engineer fixing a bug in a large real Python repository. "
    "Navigate with list_dir and search_code, read the relevant source, make a minimal "
    "edit with edit_file, and verify with run_tests. Work step by step; do not edit tests."
)


def _as_list(x) -> list[str]:
    if isinstance(x, list):
        return x
    try:
        return json.loads(x)
    except Exception:
        return [s for s in str(x).split() if s]


@dataclass(frozen=True)
class SweTask:
    id: str
    repo: str            # e.g. sympy/sympy
    base_commit: str
    problem_statement: str
    test_patch: str
    gold_patch: str
    fail_to_pass: tuple[str, ...]
    pass_to_pass: tuple[str, ...]

    @property
    def reponame(self) -> str:
        return self.repo.split("/")[-1]

    @property
    def issue(self) -> str:
        return self.problem_statement.strip()[:4000]

    @property
    def kind(self) -> str:
        return self.reponame


def load_tasks(path: str | None = None) -> list[SweTask]:
    p = Path(path or (SWEBENCH_DIR / "subset_purepy.json"))
    out = []
    for t in json.loads(p.read_text(encoding="utf-8")):
        out.append(SweTask(
            id=t["instance_id"], repo=t["repo"], base_commit=t["base_commit"],
            problem_statement=t["problem_statement"], test_patch=t["test_patch"],
            gold_patch=t.get("patch", ""),
            fail_to_pass=tuple(_as_list(t["FAIL_TO_PASS"])),
            pass_to_pass=tuple(_as_list(t.get("PASS_TO_PASS", []))),
        ))
    return out


class SweEnv:
    """A fresh checkout of one task's repo with the test_patch applied."""

    def __init__(self, task: SweTask):
        self.task = task
        self.venv_py = VENVS_DIR / task.reponame / "bin" / "python"
        self.root = self._make_workdir()

    def _make_workdir(self) -> Path:
        tmp = Path(tempfile.mkdtemp(prefix="swe_"))
        dst = tmp / self.task.reponame
        subprocess.run(["git", "clone", "-q", str(REPOS_DIR / self.task.reponame), str(dst)], check=True)
        subprocess.run(["git", "-C", str(dst), "checkout", "-q", self.task.base_commit], check=True)
        patch = dst / "_test.patch"
        patch.write_text(self.task.test_patch, encoding="utf-8")
        subprocess.run(["git", "-C", str(dst), "apply", "_test.patch"], cwd=str(dst))
        patch.unlink(missing_ok=True)
        return dst

    def cleanup(self) -> None:
        shutil.rmtree(self.root.parent, ignore_errors=True)

    def apply_gold(self) -> bool:
        """Apply the gold patch (for env validation). Returns True on clean apply."""
        p = self.root / "_gold.patch"
        p.write_text(self.task.gold_patch, encoding="utf-8")
        r = subprocess.run(["git", "-C", str(self.root), "apply", "_gold.patch"])
        p.unlink(missing_ok=True)
        return r.returncode == 0

    # --- agent tools (same surface as the Flask harness) ---
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
            if "__pycache__" in p.parts or "/.git" in str(p):
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

    def _pytest(self, tests: tuple[str, ...]) -> subprocess.CompletedProcess:
        return subprocess.run(
            [str(self.venv_py), "-m", "pytest", "-q", "-p", "no:cacheprovider", *tests],
            cwd=str(self.root), capture_output=True, text=True, timeout=600,
            env=dict(os.environ, PYTHONPATH=str(self.root)),
        )

    def run_tests(self) -> str:
        r = self._pytest(self.task.fail_to_pass)
        tail = (r.stdout or r.stderr).strip().splitlines()[-12:]
        return ("ALL TESTS PASSED\n" if r.returncode == 0 else "TESTS FAILED\n") + "\n".join(tail)

    def tests_pass(self) -> bool:
        return self._pytest(self.task.fail_to_pass).returncode == 0


def swe_tools_openai() -> list[dict[str, Any]]:
    def fn(name, desc, props=None, required=None):
        return {"type": "function", "function": {"name": name, "description": desc,
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
        fn("run_tests", "Run the task's tests and report pass/fail."),
    ]


def swe_executor(env: SweEnv) -> Callable[[str, dict[str, Any]], str]:
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
