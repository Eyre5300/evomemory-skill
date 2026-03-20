---
name: evomemory-sync
description: Sync EvoScientist research memories to a shared EvoMemory Hub. Includes a LangChain AgentMiddleware for automatic post-run upload, plus CLI setup and vector search. Use when the user wants community memory sharing, Hub configuration, or semantic search over ideation/experiment memories.
tags: [memory, sharing, collaboration, community]
---

# EvoMemory Sync Skill

Connect **EvoScientist** (or any LangChain deep agent built the same way) to a shared **EvoMemory Hub** — a community pool for research ideation and experiment memories.

This repository is two things:

1. **Python package `evomemory_sync`** — `EvoMemorySyncMiddleware` runs **after each agent invocation**, uses an LLM to turn the message trace into structured JSON, then **POSTs silently** to the Hub (when `EVOMEMORY_API_TOKEN` and extractor settings are set).
2. **CLI helpers** — `scripts/setup.py` (token + base URL) and `scripts/search.py` (semantic search).

**Default public Hub:** `https://evomem.club` (deployed from `vps_bundle`).

## Install the package

From the skill root (so imports resolve):

```bash
pip install -e .
```

Ensure EvoScientist’s environment can import `evomemory_sync` (same venv as `EvoScientist`).

## Quick Start

### 1. Configure Hub access

```bash
cd scripts
python setup.py wizard
# Or: python setup.py browse --base-url https://evomem.club
#      python setup.py share --base-url https://evomem.club
```

Writes `.env` with `EVOMEMORY_API_BASE_URL` and optionally `EVOMEMORY_API_TOKEN`.

### 2. Configure the extractor (middleware)

The middleware calls an **OpenAI-compatible** chat API (default base URL targets SiliconFlow).

| Variable | Required for auto-upload | Description |
|----------|---------------------------|-------------|
| `EVOMEMORY_EXTRACTOR_MODEL` | Yes | Chat model id for summarization |
| `EVOMEMORY_EXTRACTOR_API_KEY` or `SILICONFLOW_API_KEY` | Yes | API key |
| `EVOMEMORY_EXTRACTOR_BASE_URL` | No | Default `https://api.siliconflow.cn/v1` |
| `EVOMEMORY_EXTRACTOR_TIMEOUT_SECONDS` | No | Overrides timeout for extractor calls |
| `EVOMEMORY_SYNC_ENABLED` | No | Set `0` / `false` to disable middleware |

### 3. CLI search (unchanged)

```bash
python scripts/search.py ideation "machine learning optimization"
python scripts/search.py experiment "transformer training" --top-k 20 --min-similarity 0.35
```

## Integration snippet (EvoScientist)

Upstream `create_cli_agent` **does not** accept a `middleware=` keyword. You inject the middleware **where the list `mw` is built**, then pass that list into `load_mcp_and_build_kwargs` (same pattern as `ToolErrorHandlerMiddleware` / `create_memory_middleware`).

Example (conceptual — adjust imports to your checkout):

```python
from deepagents import create_deep_agent
from EvoScientist.EvoScientist import load_mcp_and_build_kwargs
from EvoScientist.middleware import ToolErrorHandlerMiddleware, create_memory_middleware
from evomemory_sync import EvoMemorySyncMiddleware

# After you construct backends `be`, memory dir `_mem_dir`, and your chat model:
mw = [
    EvoMemorySyncMiddleware(),
    ToolErrorHandlerMiddleware(),
    create_memory_middleware(_mem_dir, extraction_model=your_chat_model),
]
# If you use AskUserMiddleware, insert it as EvoScientist does (often `mw.insert(0, ...)`).

kwargs = load_mcp_and_build_kwargs(be, mw)
agent = create_deep_agent(
    **kwargs,
    checkpointer=checkpointer,
    interrupt_on=_interrupt_on,
).with_config({"recursion_limit": 1000})
```

Load `.env` before starting the CLI (or rely on the middleware’s optional `python-dotenv` load on first run).

## How the middleware decides M_I vs M_E

On `after_agent` / `aafter_agent` it builds a context object from `state["messages"]`:

- First **HumanMessage** → task / proposal text.
- **AIMessage** `tool_calls` → code/commands (e.g. `execute` + `command`, or args named `code` / `command`).
- **ToolMessage** → `status == "error"` and error bodies feed **M_I** hints; successful experiment closure feeds **M_E** hints.

The LLM must output JSON only: either `memory_type: "ideation"` (failed or promising), `memory_type: "experiment"`, or `{ "skip": true }`. See `evomemory_sync/extractor.py` for the system prompt.

## Hub field reference

See `references/CONFIG.md` for env vars, embedding buckets, and REST endpoints.

## Commands (CLI)

| Command | Description |
|---------|-------------|
| `setup.py browse` | Read-only Hub URL → `.env` |
| `setup.py share` | Register/login → token in `.env` |
| `setup.py wizard` | Interactive wizard |
| `search.py ideation \| experiment <query>` | Vector / semantic search |

Manual `push.py` / `push_from_json.py` CLIs were removed; uploads go through the **middleware** or your own code calling `evomemory_sync.uploader.upload_memory_record`.
