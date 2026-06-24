"""Demonstrate the full experience pipeline on ONE task, end to end:
   agent workflow (trace)  ->  producer raw experience  ->  auto L1/L2/L3  ->  P/G.
Run on tate:  python -u -m experiments.demo_pipeline
"""
from __future__ import annotations

from evomemory_sync.abstraction import generate_levels
from evomemory_sync.experience_quality import generalization_mdl, p_weighted

from .agent import run_consumer
from .models import get as get_consumer
from .swe_flask import (
    CODE_SYSTEM, TASKS_BY_ID, FlaskEnv, flask_executor, flask_tools_openai, make_flask_workdir,
)

H = "A peer agent that fixed a similar bug shared this guidance. Use it:"
task = TASKS_BY_ID["flask_blueprint_empty"]

print("=" * 70)
print("TASK:", task.id)
print("ISSUE:", task.issue[:160], "...")
print("=" * 70)

# ---------- 1. AGENT WORKFLOW: run the weak agent WITH the good experience ----------
env = FlaskEnv(make_flask_workdir(task), task.check)
consumer = get_consumer("qwen3-8b")
res = run_consumer(task.issue, system=CODE_SYSTEM, extra_context=f"{H}\n{task.experience}", seed=1,
                   tools_openai=flask_tools_openai(), execute_fn=flask_executor(env),
                   max_steps=20, done_check=env.tests_pass, consumer=consumer)
passed = env.tests_pass()
print("\n[1] AGENT WORKFLOW (the weak model's tool-call trace):")
for i, tc in enumerate(res.tool_calls, 1):
    a = tc.get("args", {})
    arg = a.get("path") or a.get("pattern") or (a.get("old", "")[:40].replace("\n", "\\n")) or ""
    print(f"   step {i:2d}: {tc['name']:11s} {arg!r:42s} -> {tc['result'][:46].replace(chr(10),' ')}")
print(f"   RESULT: {'PASS' if passed else 'FAIL'}  ({len(res.tool_calls)} tool calls)")
env.cleanup()

# ---------- 2. PRODUCER writes the RAW experience (from having solved it) ----------
raw = ("Bug: flask.Blueprint('') with an empty name was accepted without complaint. "
       "Fix: in src/flask/blueprints.py, in Blueprint.__init__, right before the line "
       "`self.name = name`, add `if not name: raise ValueError(\"'name' must not be empty.\")`. "
       "Verified: Blueprint('') now raises ValueError and Blueprint('good') still works.")
print("\n[2] PRODUCER RAW EXPERIENCE (written after solving):")
print("  ", raw)

# ---------- 3. AUTO-GENERATE L1/L2/L3 (abstraction.py, a local model) ----------
levels = generate_levels(raw)
print("\n[3] AUTO-GENERATED ABSTRACTION LEVELS (abstraction.py):")
for k in ("l1", "l2", "l3"):
    print(f"   {k.upper()}: {levels[k]}")

# ---------- 4. P/G for each level ----------
print("\n[4] P/G OF EACH LEVEL:")
for k in ("l1", "l2", "l3"):
    g = generalization_mdl(solution=levels[k])
    print(f"   {k.upper()}: G={g['G']:.3f}  (L={g['L']:.1f}; N_cond={g['N_cond']} N_ent={g['N_ent']} N_depth={g['N_depth']})")

print("\n[4b] P (precision) — depends on WHERE it was verified:")
own = p_weighted([1.0], [1])
print(f"   only its OWN task (1 success):     P={own['P']:.3f}   <- 越测越逼近满分 = 答案泄露信号")
cross = p_weighted([1.0, 0.45, 0.45, 0.40], [1, 1, 0, 1])
print(f"   cross-task track record:           P={cross['P']:.3f}   <- 诚实分(在别的任务上也证明过,<1)")
print("\nDONE.")
