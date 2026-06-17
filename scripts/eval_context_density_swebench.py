#!/usr/bin/env python3
"""Evaluate computable ContextDensity on one SWE-bench Lite instance.

Data (hf-mirror):
  curl -L -o data/swebench_lite_test.parquet \\
    https://hf-mirror.com/datasets/SWE-bench/SWE-bench_Lite/resolve/main/data/test-00000-of-00001.parquet
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable

# Allow running without install
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from evomemory_sync.context_density import (  # noqa: E402
    build_swebench_dimensions,
    build_swebench_trajectory,
    compute_context_density,
    extract_experience_constraints,
    summarize_result,
)


def _count_py_files(root: Path) -> int:
    return sum(1 for p in root.rglob("*.py") if p.is_file())


def _keyword_file_hits(module_root: Path, keywords: Iterable[str]) -> list[str]:
    hits: list[str] = []
    kws = [k.lower() for k in keywords if k]
    for p in module_root.rglob("*.py"):
        try:
            text = p.read_text(encoding="utf-8", errors="ignore").lower()
        except OSError:
            continue
        if any(k in text for k in kws):
            hits.append(str(p.relative_to(module_root)).replace("\\", "/"))
    return hits


def _function_count(py_path: Path) -> int:
    text = py_path.read_text(encoding="utf-8", errors="ignore")
    return len(re.findall(r"^def (\w+)", text, re.MULTILINE))


def _nontrivial_lines_in_function(py_path: Path, func_name: str) -> int:
    text = py_path.read_text(encoding="utf-8", errors="ignore")
    m = re.search(rf"def {re.escape(func_name)}\([^)]*\):(.*?)(?=\ndef |\Z)", text, re.DOTALL)
    if not m:
        return 1
    lines = [
        ln
        for ln in m.group(1).splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]
    return max(1, len(lines))


def _issue_keywords(problem: str) -> list[str]:
    kws: list[str] = []
    for token in re.findall(r"[A-Za-z_][\w]{3,}", problem):
        if token.lower() in {"python", "model", "from", "true", "false", "array", "issue"}:
            continue
        kws.append(token)
    # prefer API-ish tokens
    ordered = sorted(set(kws), key=lambda x: ("_" in x, x[0].isupper(), len(x)), reverse=True)
    return ordered[:6]


def _experience_precise(instance_id: str, problem: str, patch: str) -> tuple[str, str]:
    file_match = re.search(r"diff --git a/(\S+)", patch or "")
    target_file = file_match.group(1) if file_match else "unknown.py"
    func = "_cstack" if "_cstack" in (patch or "") else "target_function"
    problem_para = (
        f"在 {instance_id.split('__')[0]} 仓库做 Python 代码调试："
        f"{problem.strip()[:280].replace(chr(10), ' ')}"
    )
    solution_para = (
        f"在 {target_file} 的 {func} 中修复赋值：将 "
        f"`cright[-right.shape[0]:, -right.shape[1]:] = 1` 改为 `= right`，"
        f"使嵌套 CompoundModel 保留真实 coord_matrix。"
        f"先用 issue 中的 separability_matrix 用例复现，grep separability 缩小范围，"
        f"再运行 FAIL_TO_PASS 测试确认。"
    )
    return problem_para, solution_para


def _experience_vague(problem: str) -> tuple[str, str]:
    return (
        "Python 科学计算库里的 modeling 问题。",
        "检查 separability 相关代码并修复矩阵计算 bug。",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="ContextDensity demo on SWE-bench Lite")
    parser.add_argument(
        "--instance-id",
        default="astropy__astropy-12907",
        help="SWE-bench Lite instance_id",
    )
    parser.add_argument(
        "--parquet",
        default=str(Path(__file__).resolve().parents[2] / "data" / "swebench_lite_test.parquet"),
    )
    parser.add_argument(
        "--repo-root",
        default=str(Path(__file__).resolve().parents[2] / "data" / "repos" / "astropy"),
        help="Local clone checked out at instance base_commit",
    )
    args = parser.parse_args()

    try:
        import pyarrow.parquet as pq
    except ImportError as exc:
        print("pip install pyarrow", file=sys.stderr)
        raise SystemExit(1) from exc

    table = pq.read_table(args.parquet)
    data = table.to_pydict()
    if args.instance_id not in data["instance_id"]:
        raise SystemExit(f"instance {args.instance_id!r} not in {args.parquet}")

    idx = data["instance_id"].index(args.instance_id)
    problem = data["problem_statement"][idx]
    patch = data["patch"][idx] or ""
    repo = data["repo"][idx]
    base_commit = data["base_commit"][idx]

    repo_root = Path(args.repo_root)
    astropy_pkg = repo_root / "astropy"
    if not astropy_pkg.is_dir():
        raise SystemExit(
            f"Missing repo at {repo_root}. Clone astropy and checkout {base_commit}."
        )

    module = "modeling"
    module_root = astropy_pkg / module
    keywords = _issue_keywords(problem)
    keyword_hits = _keyword_file_hits(module_root, keywords)

    patch_file = re.search(r"diff --git a/(\S+)", patch)
    target_rel = patch_file.group(1) if patch_file else ""
    target_path = repo_root / target_rel if target_rel else None

    repo_py = _count_py_files(astropy_pkg)
    module_py = _count_py_files(module_root)
    subpackages = len([d for d in astropy_pkg.iterdir() if d.is_dir() and not d.name.startswith(".")])

    func_count = _function_count(target_path) if target_path and target_path.is_file() else 8
    func_name = "_cstack" if "_cstack" in patch else "separability_matrix"
    edit_sites = (
        _nontrivial_lines_in_function(target_path, func_name)
        if target_path and target_path.is_file()
        else 20
    )

    trajectory = build_swebench_trajectory(
        subpackages=subpackages,
        keyword_hits=max(2, len(keyword_hits)),
        module_py_files=module_py,
        target_file_functions=func_count,
        test_commands=max(1, len(json.loads(data["FAIL_TO_PASS"][idx]))),
    )
    traj_bits = sum(s.h_bits for s in trajectory)

    results: dict[str, Any] = {
        "instance_id": args.instance_id,
        "repo": repo,
        "base_commit": base_commit,
        "measurable_envelope": {
            "repo_py_files": repo_py,
            "subpackage_count": subpackages,
            "modeling_py_files": module_py,
            "keyword_candidate_files": len(keyword_hits),
            "keyword_hits_sample": keyword_hits[:8],
            "issue_keywords": keywords,
            "gold_patch_file": target_rel,
            "target_function_count": func_count,
            "edit_sites_in_function": edit_sites,
            "agent_trajectory_steps": len(trajectory),
            "agent_trajectory_bits": round(traj_bits, 3),
        },
        "evaluations": {},
    }

    for label, (prob, sol) in {
        "no_experience": ("", ""),
        "vague_experience": _experience_vague(problem),
        "precise_experience": _experience_precise(args.instance_id, problem, patch),
    }.items():
        constraints = extract_experience_constraints(prob, sol)
        dims = build_swebench_dimensions(
            repo_py_files=repo_py,
            module_py_files=module_py,
            keyword_candidate_files=max(1, len(keyword_hits)),
            target_file_functions=func_count,
            edit_sites_in_function=edit_sites,
            subpackages=subpackages,
            constraints=constraints,
            module_name=module,
        )
        if label == "no_experience":
            for d in dims:
                d.branches_after = d.branches_before
        cd = compute_context_density(dims, trajectory_steps=trajectory)
        results["evaluations"][label] = {
            "problem": prob,
            "solution": sol,
            "constraints": {
                "pinned_files": constraints.pinned_files,
                "pinned_functions": constraints.pinned_functions,
                "literal_parameters": constraints.literal_parameters,
                "negative_hypotheses": constraints.negative_hypotheses,
            },
            **summarize_result(cd),
        }

    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
