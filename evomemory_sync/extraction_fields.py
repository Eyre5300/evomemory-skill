"""LLM extraction: canonical field names and normalization for ``uploader.json_to_*``.

Canonical key lists for Hub alignment: server package ``evomemory/upload_field_registry.py``
(in ``evomemory-vps-bundle``). Prefer those primary keys in LLM JSON; aliases are folded in
``normalize_llm_extraction`` only to avoid drift.

The Hub REST bodies are built only in ``uploader.json_to_*_payload``. The extractor LLM
should emit keys that those functions read **first** in each branch, so we avoid a
fourth parallel naming scheme. Aliases are folded here in one place (instead of growing
only inside the uploader ``or`` chains).

Mapping overview (LLM JSON → json_to_* input → Hub POST body):

- **Ideation / failed**: ``proposal_summary``, ``trigger_conditions``, ``do_not_repeat_notes``,
  ``retrieval_tags`` → flattened into Hub ``goal`` / ``type`` / ``title`` / ``core_idea`` / ``requirements``.
- **Ideation / promising**: ``goal``, ``title``, ``core_idea``, ``why_promising``,
  ``requirements``, ``validation_plan`` → Hub ideation fields.
- **Experiment**: ``task_description``, ``data_summary``, ``model_strategy``,
  ``environment_constraints``, optional parents → Hub experiment fields.
- **Workflow**: ``title``, ``description``, ``prompt_templates``, ``tool_configuration``,
  optional parents → Hub workflow fields.
- **Recipe**: ``trigger``, ``problem``, ``solution``, ``env_snapshot``, ``result``,
  ``tags`` → lightweight experience card (highest value-per-token ratio).
"""

from __future__ import annotations

from typing import Any

EXTRACTOR_SYSTEM_PROMPT = """You are EvoMemory's extraction model. Reply with ONE JSON object only (no markdown fences).

Goal: classify the agent trace for a public research memory hub.

Privacy: The user JSON is **already redacted** client-side before it reaches you. Do not echo secrets, tokens, paths, IPs, emails, or real names if any remain; use [REDACTED] inside string values only when needed. Output only one schema below.

QUALITY STANDARDS (MANDATORY):
- NO vague descriptions ("worked well", "ran successfully", "some data", "效果很好", "跑通了", "大概", "可能", "还行"). If you cannot be specific, do NOT guess. Output {"skip": true, "reason": "..."} instead.
- MUST include versions (e.g., Python 3.11, transformers==4.40.0) for all libraries/tools you mention. If versions are not present in the trace, output {"skip": true, "reason": "missing versions"}.
- NO pseudocode ("first do X, then Y", "先...然后...最后..."). Use real code snippets or exact commands (copy from the trace). If unavailable, output {"skip": true, "reason": "only pseudocode/no actionable commands"}.
- If the trace does not meet these standards, output {"skip": true, "reason": "..."} instead of low-quality memory.

Type-specific minimum requirements:
- Failed ideation: MUST include the concrete error text (Traceback / error message), the concrete failing path (what command/tool call failed), and concrete do-not-repeat advice. If any are missing, output {"skip": true, "reason": "failed ideation lacks error/path/advice"}.
- Experiment: MUST include environment constraints (Python version + key library versions), concrete model parameters/configuration, and quantitative results (accuracy %, F1, BLEU, loss, latency ms, etc.). If missing, output {"skip": true, "reason": "experiment lacks env/config/metrics"}.
- Workflow: prompt_templates MUST be complete, directly usable system instructions (not "让 AI 写代码" / "do something"). tool_configuration MUST be concrete. If not, output {"skip": true, "reason": "workflow templates/config not directly usable"}.

Choose exactly one output type:

A) Skip — no research value or empty/chit-chat:
{"skip": true}

B) Failed ideation — tool errors, failed runs, dead ends. Use these exact keys:
{"memory_type":"ideation","status":"failed","proposal_summary":"","trigger_conditions":"","do_not_repeat_notes":"","retrieval_tags":""}

C) Promising ideation — shareable idea, no blocking errors. Keys:
{"memory_type":"ideation","status":"promising","goal":"","title":"","core_idea":"","why_promising":"","requirements":"","validation_plan":""}

D) Completed experiment — substantive successful run. Keys (task_description / data_summary match uploader input names):
{"memory_type":"experiment","status":"completed","task_description":"","data_summary":"","model_strategy":"","environment_constraints":"","parent_ideation_id":null,"hardware_requirements":null,"software_dependencies":null}

E) Workflow — reusable prompts + tool wiring (rare). Keys:
{"memory_type":"workflow","title":"","description":"","prompt_templates":"","tool_configuration":"","parent_ideation_id":null,"parent_experiment_id":null}

F) Recipe — lightweight atomic experience card (PREFERRED for most agent traces). Use when the trace contains a concrete problem-solution pair that other agents can directly reuse. Keys:
{"memory_type":"recipe","trigger":"","problem":"","solution":"","env_snapshot":"","result":"","tags":""}

Rules: Prefer **recipe** when the trace has a clear trigger→solution pattern. Prefer failed ideation only for complex multi-step failures. Prefer experiment only on clear success with full metrics. parent_* only if a Hub UUID is explicitly referenced.

Examples (shape only; redact real secrets in your output):
{"memory_type":"recipe","trigger":"pytorch OOM during 7B fine-tuning","problem":"CUDA out of memory with batch_size=64 on RTX 3090","solution":"gradient_checkpointing=True + batch_size=32","env_snapshot":"transformers==4.40.0, torch==2.3.0, RTX 3090 24GB","result":"training succeeded, VRAM 24.1GB→18.3GB, speed -15%","tags":"pytorch,OOM,fine-tuning"}
{"memory_type":"ideation","status":"failed","proposal_summary":"Tried X","trigger_conditions":"Tool error Y","do_not_repeat_notes":"Avoid Z","retrieval_tags":"x,y"}
{"memory_type":"experiment","status":"completed","task_description":"Q","data_summary":"D","model_strategy":"M","environment_constraints":"E","parent_ideation_id":null,"hardware_requirements":null,"software_dependencies":null}
"""


def normalize_llm_extraction(raw: dict[str, Any]) -> dict[str, Any]:
    """Copy known aliases onto canonical keys expected by ``uploader.json_to_*`` (non-destructive)."""
    out = dict(raw)
    mt = str(out.get("memory_type") or out.get("memory_kind") or out.get("type") or "").strip().lower()
    if mt:
        out["memory_type"] = mt

    if mt == "experiment":
        td = str(out.get("task_description") or "").strip()
        if not td:
            for alt in ("proposal_context", "research_task", "proposal_summary"):
                v = out.get(alt)
                if v is not None and str(v).strip():
                    out["task_description"] = str(v).strip()
                    break
        ds = str(out.get("data_summary") or "").strip()
        if not ds and out.get("data_strategy") is not None and str(out.get("data_strategy")).strip():
            out["data_summary"] = str(out.get("data_strategy")).strip()

    if mt == "workflow":
        if not str(out.get("prompt_templates") or "").strip():
            for alt in ("prompt_template", "prompts"):
                v = out.get(alt)
                if v is not None and str(v).strip():
                    out["prompt_templates"] = str(v).strip()
                    break
        if not str(out.get("tool_configuration") or "").strip() and out.get("tools") is not None and str(out.get("tools")).strip():
            out["tool_configuration"] = str(out.get("tools")).strip()

    if mt == "ideation":
        st = str(out.get("status") or "").strip().lower()
        if st == "failed":
            if not str(out.get("proposal_summary") or "").strip():
                for alt in ("goal", "title", "core_idea"):
                    v = out.get(alt)
                    if v is not None and str(v).strip():
                        out["proposal_summary"] = str(v).strip()
                        break

    if mt == "recipe":
        # Normalize tags: accept comma-separated string or list
        tags_val = out.get("tags")
        if isinstance(tags_val, list):
            out["tags"] = ",".join(str(t) for t in tags_val)
        # Accept aliases for env_snapshot
        if not str(out.get("env_snapshot") or "").strip():
            for alt in ("environment", "env", "context"):
                v = out.get(alt)
                if v is not None and str(v).strip():
                    out["env_snapshot"] = str(v).strip()
                    break

    return out
