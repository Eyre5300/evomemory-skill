"""Minimal multi-step tool-use agents (producer = Claude, consumer = local qwen).

Both share the tool registry in `tools.py` and the same loop contract, so a task
solved by the producer and retried by the consumer are directly comparable. The
returned `AgentResult.trace` is what the experience extractor consumes later.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import requests

from . import tools as toolkit
from .config import CONSUMER, PRODUCER

DEFAULT_SYSTEM = (
    "You are a careful multi-step problem solver. Use the provided tools when they help. "
    "Think step by step. When you are confident, give a final answer on its own line "
    "prefixed exactly with 'FINAL ANSWER:' followed by the answer only."
)


@dataclass
class AgentResult:
    answer: str
    steps: int
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    trace: list[dict[str, Any]] = field(default_factory=list)
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error and bool(self.answer)


def _final_answer(text: str) -> str:
    text = (text or "").strip()
    for line in reversed(text.splitlines()):
        if "FINAL ANSWER:" in line:
            return line.split("FINAL ANSWER:", 1)[1].strip()
    # models often skip the prefix and end with a LaTeX/code delimiter — take the
    # last line that actually contains a digit, else the last non-empty line.
    for line in reversed(text.splitlines()):
        if any(c.isdigit() for c in line):
            return line.strip()
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return lines[-1] if lines else ""


# --- consumer: OpenAI-compatible (Ollama / local qwen) --------------------


def run_consumer(task: str, *, system: str = DEFAULT_SYSTEM, extra_context: str = "",
                 seed: int | None = None, tools_openai: list[dict[str, Any]] | None = None,
                 execute_fn=None, max_steps: int | None = None, done_check=None) -> AgentResult:
    """Run the weak model via the OpenAI-compatible chat endpoint with tool calls.

    Pass a fixed `seed` for reproducibility (Ollama is non-deterministic by default,
    even at temperature 0). Vary the seed to measure success-rate variance.
    Pass `tools_openai` + `execute_fn` to swap the tool surface (e.g. code-repair
    tools); defaults to the calculator toolkit.
    """
    tools_spec = tools_openai if tools_openai is not None else toolkit.openai_tools()
    execfn = execute_fn if execute_fn is not None else toolkit.execute
    steps_budget = max_steps if max_steps is not None else CONSUMER.max_steps

    sys_text = system + (f"\n\n{extra_context}" if extra_context else "")
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": sys_text},
        {"role": "user", "content": task},
    ]
    url = CONSUMER.base_url.rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {CONSUMER.api_key}", "Content-Type": "application/json"}
    tool_calls_log: list[dict[str, Any]] = []
    read_only_streak = 0

    for step in range(steps_budget):
        payload = {
            "model": CONSUMER.model,
            "messages": messages,
            "tools": tools_spec,
            "temperature": CONSUMER.temperature,
        }
        if seed is not None:
            payload["seed"] = seed
        try:
            r = requests.post(url, json=payload, headers=headers, timeout=CONSUMER.timeout)
            r.raise_for_status()
            msg = r.json()["choices"][0]["message"]
        except Exception as e:
            return AgentResult(answer="", steps=step, tool_calls=tool_calls_log, trace=messages, error=f"consumer request failed: {e}")

        messages.append({k: v for k, v in msg.items() if k in ("role", "content", "tool_calls")})
        calls = msg.get("tool_calls") or []
        if not calls:
            # Persistence: if the task isn't actually solved yet and budget remains,
            # don't let the model stop early — nudge it to act and keep going.
            if done_check is not None and not done_check() and step < steps_budget - 1:
                messages.append({"role": "user", "content":
                    "The tests are NOT passing yet, so you are not done. Make the necessary "
                    "file edit and call run_tests. Do not stop until run_tests reports all tests pass."})
                continue
            return AgentResult(answer=_final_answer(msg.get("content") or ""), steps=step + 1,
                               tool_calls=tool_calls_log, trace=messages)
        acted = False
        for call in calls:
            fn = call.get("function", {})
            name = fn.get("name", "")
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except Exception:
                args = {}
            result = execfn(name, args)
            if name in ("edit_file", "run_tests"):
                acted = True
            tool_calls_log.append({"name": name, "args": args, "result": result})
            messages.append({"role": "tool", "tool_call_id": call.get("id", ""), "content": result})

        # Anti-thrash: if the model only explores (read-only tools) for too many steps
        # without acting, push it to apply the fix and test.
        read_only_streak = 0 if acted else read_only_streak + 1
        if done_check is not None and read_only_streak >= 6 and not done_check():
            messages.append({"role": "user", "content":
                "You have gathered enough information. Stop searching and APPLY the fix now: "
                "use edit_file with the exact change described in the guidance, then call run_tests."})
            read_only_streak = 0

    return AgentResult(answer="", steps=steps_budget, tool_calls=tool_calls_log, trace=messages,
                       error="consumer hit max_steps without a final answer")


# --- producer: Anthropic Claude (official SDK) ----------------------------


def run_producer(task: str, *, system: str = DEFAULT_SYSTEM) -> AgentResult:
    """Run the strong model (Claude) with a manual tool-use loop to produce experience."""
    if not PRODUCER.ready:
        return AgentResult(answer="", steps=0, error="ANTHROPIC_API_KEY not set (producer disabled)")
    try:
        import anthropic
    except Exception as e:
        return AgentResult(answer="", steps=0, error=f"anthropic SDK import failed: {e}")

    client = anthropic.Anthropic(api_key=PRODUCER.api_key)
    messages: list[dict[str, Any]] = [{"role": "user", "content": task}]
    tool_calls_log: list[dict[str, Any]] = []
    trace: list[dict[str, Any]] = [{"role": "user", "content": task}]

    def _create(msgs: list[dict[str, Any]]):
        kwargs: dict[str, Any] = dict(
            model=PRODUCER.model, max_tokens=PRODUCER.max_tokens,
            system=system, messages=msgs, tools=toolkit.anthropic_tools(),
        )
        # Newer-API niceties; strip if the installed SDK/model rejects them.
        try:
            return client.messages.create(
                thinking={"type": "adaptive"},
                output_config={"effort": PRODUCER.effort},
                **kwargs,
            )
        except TypeError:
            return client.messages.create(**kwargs)
        except Exception as e:
            if "thinking" in str(e) or "output_config" in str(e) or "effort" in str(e):
                return client.messages.create(**kwargs)
            raise

    for step in range(PRODUCER.max_steps):
        try:
            resp = _create(messages)
        except Exception as e:
            return AgentResult(answer="", steps=step, tool_calls=tool_calls_log, trace=trace, error=f"producer request failed: {e}")

        if resp.stop_reason == "refusal":
            return AgentResult(answer="", steps=step + 1, tool_calls=tool_calls_log, trace=trace, error="producer refused")

        messages.append({"role": "assistant", "content": resp.content})
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        if text:
            trace.append({"role": "assistant", "content": text})

        tool_uses = [b for b in resp.content if getattr(b, "type", "") == "tool_use"]
        if resp.stop_reason != "tool_use" or not tool_uses:
            return AgentResult(answer=_final_answer(text), steps=step + 1, tool_calls=tool_calls_log, trace=trace)

        results = []
        for tu in tool_uses:
            result = toolkit.execute(tu.name, dict(tu.input or {}))
            tool_calls_log.append({"name": tu.name, "args": dict(tu.input or {}), "result": result})
            trace.append({"role": "tool", "name": tu.name, "args": dict(tu.input or {}), "result": result})
            results.append({"type": "tool_result", "tool_use_id": tu.id, "content": result})
        messages.append({"role": "user", "content": results})

    return AgentResult(answer="", steps=PRODUCER.max_steps, tool_calls=tool_calls_log, trace=trace,
                       error="producer hit max_steps without a final answer")
