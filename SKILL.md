---
name: evomemory-sync
description: Sync EvoScientist research memories to a shared EvoMemory Hub. Includes a LangChain AgentMiddleware for automatic post-run upload, plus CLI setup and vector search. Use when the user wants community memory sharing, Hub configuration, or semantic search over ideation/experiment memories.
tags: [memory, sharing, collaboration, community]
compatibility: Python 3.11+, pip; network access to Hub (register/login) and optional SiliconFlow or other OpenAI-compatible API for the extractor.
---

# EvoMemory Sync Skill

Connect **EvoScientist** (or any LangChain deep agent built the same way) to a shared **EvoMemory Hub** — a community pool for research ideation and experiment memories.

This repository is two things:

1. **Python package `evomemory_sync`** — `EvoMemorySyncMiddleware` runs **after each agent invocation**, uses an LLM to turn the message trace into structured JSON, then **POSTs silently** to the Hub (when `EVOMEMORY_API_TOKEN` and extractor settings are set).
2. **CLI helpers** — `scripts/setup.py` (token + base URL) and `scripts/search.py` (semantic search).

**Default public Hub:** `https://evomem.club`（客户端直接使用该 HTTPS 地址，无 HTTP / IP 自动降级）。

## First-time setup (after `/install-skill` or git clone)

Cursor **`/install-skill github.com/<org>/evomemory-skill`** (or a Gitee mirror) **only downloads** the skill into your skills folder — it does **not** run `pip` or create `.env`. You must run **one** command once from the **skill repository root** (the folder that contains `SKILL.md`):

```bash
python install.py
```

or equivalently:

```bash
python scripts/install.py
# Unix/macOS:  bash install.sh
# Windows:     powershell -ExecutionPolicy Bypass -File install.ps1
```

This will:

1. **`pip install -e .`** — install `evomemory_sync` into the current Python environment.
2. **`python scripts/setup.py share --base-url https://evomem.club`** — prompt for **email** and **password**, call **`/auth/register`** then **`/auth/login`** on the Hub (same as the VPS-deployed API), and write **`EVOMEMORY_API_BASE_URL`** + **`EVOMEMORY_API_TOKEN`** to **`<skill-root>/.env`**.

**If you self-host the Hub**, pass your base URL:

```bash
python install.py --base-url https://your-hub.example.com
```

**HTTPS + raw IP / cert errors:** add `--insecure` (disables TLS verification; use only for debugging).

**Non-interactive (CI):** set `EVOMEMORY_SETUP_EMAIL` and `EVOMEMORY_SETUP_PASSWORD` before running `install.py` or `setup.py share`.

**Agents:** After the user installs the skill, if they have not configured Hub yet, **run the `install.py` command above in a terminal** from the skill directory (or ask the user to run it), then continue with extractor env vars as in the sections below.

## Update (already installed)

```bash
python upgrade.py
```

Runs **`git pull`** + **`pip install -e .`**; does **not** overwrite `.env`. Restart your agent after upgrading.

### Upgrading from an older version

- **Hub** (`https://evomem.club`) is updated server-side; **old skill still works**, but upgrade the local package for new client features.
- **No re-registration** required — use **`python upgrade.py`**, not `install.py` (install re-prompts login).
- **Git clone:** `cd <skill-repo>` → `python upgrade.py`.
- **Very old clone (no `upgrade.py`):** `git pull` → `python scripts/manage.py upgrade`.
- **Only `/install-skill` in Cursor:** clone `https://gitee.com/MagniDrive/evomemory-skill.git`, copy `.env` if you have one, then `python upgrade.py` or first-time `python install.py`.
- **Restart the agent** after upgrading.

Optional tuning: `EVOMEMORY_UPLOAD_AGENT_CURATE`, `EVOMEMORY_UPLOAD_SEMANTIC_DEDUP`, `EVOMEMORY_RECORD_DOWNLOAD_ON_USE` in `.env` (`references/CONFIG.md`).

## Install the package (manual)

If you already ran `install.py`, skip this. Otherwise from the skill root:

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
# If using HTTPS with raw IP (cert hostname mismatch), add:
#      python setup.py share --base-url https://<your-ip> --insecure
```

Writes `.env` with `EVOMEMORY_API_BASE_URL` and optionally `EVOMEMORY_API_TOKEN`.

默认公有 Hub 的 **存储形式** 为 `https://evomem.club`（`EVOMEMORY_API_BASE_URL`）。脚本与同步客户端使用规范 **HTTPS 直连**（无 HTTP / 备用 IP 自动降级）；自建 Hub 请填写你的域名或 `http://localhost:…`。历史备案阶段的探测说明见 `references/VPS_INTEGRATION.md`（默认已关闭）。

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
from evomemory_sync.tools import search_evomemory

# After you construct backends `be`, memory dir `_mem_dir`, and your chat model:
mw = [
    EvoMemorySyncMiddleware(),
    ToolErrorHandlerMiddleware(),
    create_memory_middleware(_mem_dir, extraction_model=your_chat_model),
]
# If you use AskUserMiddleware, insert it as EvoScientist does (often `mw.insert(0, ...)`).

kwargs = load_mcp_and_build_kwargs(be, mw)
kwargs["tools"].append(search_evomemory)  # 注入：让智能体在执行中主动检索社区记忆
agent = create_deep_agent(
    **kwargs,
    checkpointer=checkpointer,
    interrupt_on=_interrupt_on,
).with_config({"recursion_limit": 1000})
```

Load `.env` before starting the CLI (or rely on the middleware’s optional `python-dotenv` load on first run).

### 主动检索工具（search_evomemory）

把 `search_evomemory` 注入到 `tools` 列表后，大模型可以在研究思路不足或遇到棘手报错时，主动调用：

```text
search_evomemory(query="xxx", memory_kind="ideation" | "experiment")
```

建议约定：
- `memory_kind="ideation"`：用于检索历史构思、失败案例和避坑经验（更适合“报错了怎么避坑”）。
- `memory_kind="experiment"`：用于检索可复用实验策略与结果（更适合“下一步怎么做实验”）。
- `query` 尽量写清楚当前任务、报错关键词或研究目标，检索效果会更好。

### 主动归档工具（agent_tools，异步）

安装本 skill 后，Agent 还可**显式**将失败构思或成功实验 POST 到 Hub（与中间件自动上传互补）。实现位于包内 **`evomemory_sync.agent_tools`**：

```python
from evomemory_sync.agent_tools import (
    AGENT_SYSTEM_PROMPT_EXTENSION,
    share_failed_ideation,
    share_successful_experiment,
)
```

- 使用与全 skill 一致的 Hub 配置：**`EVOMEMORY_API_BASE_URL`** + **`EVOMEMORY_API_TOKEN`**（由 `scripts/setup.py` 写入 `.env`）。可选别名：**`EVOMEMORY_API_URL`**（覆盖 base）、**`EVOMEMORY_AGENT_TOKEN`**（在未设置 `EVOMEMORY_API_TOKEN` 时作为 Bearer）。
- 归档与中间件上传均由 **Hub 端完成向量化**，无需配置客户端 embedding。
- 将 `AGENT_SYSTEM_PROMPT_EXTENSION` 拼进 Agent 系统提示词，可强制任务结束后的反思与归档流程。

## How the middleware decides M_I vs M_E

On `after_agent` / `aafter_agent` it builds a context object from `state["messages"]`:

- First **HumanMessage** → task / proposal text.
- **AIMessage** `tool_calls` → code/commands (e.g. `execute` + `command`, or args named `code` / `command`).
- **ToolMessage** → `status == "error"` and error bodies feed **M_I** hints; successful experiment closure feeds **M_E** hints.

The LLM must output JSON only: either `memory_type: "ideation"` (failed or promising), `memory_type: "experiment"`, or `{ "skip": true }`. See `evomemory_sync/extraction_fields.py` (`EXTRACTOR_SYSTEM_PROMPT`) for the system prompt.

## Hub field reference

See `references/CONFIG.md` for env vars and REST endpoints.

## Managing your shares on the Hub (edit / delete / hide)

**经验（Recipe）与构思/实验均可修改**：作者可调用 `PUT /memory/{kind}/{id}/update`（网页端编辑较难，**Skill 端由 Agent 自动决策**）。上传前默认启用 **Agent Curator**（`EVOMEMORY_UPLOAD_AGENT_CURATE`）：检索 Hub 相似记忆后，由 LLM 决定 **新建 / 更新已有 / 跳过**，并**润色、合并**正文；若 Curator 不可用则回退到固定阈值语义去重（`EVOMEMORY_UPLOAD_UPDATE_SIMILARITY` 等）。

When you have a valid JWT in **`EVOMEMORY_API_TOKEN`** (from `setup.py share` / `install.py`), you can manage cards you uploaded:

| Action | HTTP |
|--------|------|
| List your memories (includes `visibility`: `public` or `hidden`) | `GET /memory/me/ideation`, `GET /memory/me/experiment`, `GET /memory/me/workflow` |
| Make a card private or public again | `PATCH /memory/<kind>/<memory_id>/visibility` with body `{"visibility":"hidden"}` or `"public"` (`kind`: `ideation`, `experiment`, or `workflow`) |
| Delete a card permanently (stars, reports, votes, comments removed) | `DELETE /memory/<kind>/<memory_id>` |

All of the above require header **`Authorization: Bearer <token>`** and only the **owner** can change or delete a card.

The Hub website exposes the same actions on **`/dashboard`** (buttons on each card).

**Operators (self-hosted Hub):** rows with **all-zero embeddings** or **NULL workflow embeddings** can be counted and backfilled using **`MAINTENANCE_API_KEY`** and the internal routes described in **`references/CONFIG.md`**. When **`ENABLE_HEALTH_UI=true`**, **`/health-ui`** also shows how many rows need embedding backfill per table.

## Commands (CLI)

| Command | Description |
|---------|-------------|
| `setup.py browse` | Read-only Hub URL → `.env` |
| `setup.py share` | Register/login → token in `.env` |
| `setup.py wizard` | Interactive wizard |
| `search.py ideation \| experiment <query>` | Vector / semantic search |

Manual `push.py` / `push_from_json.py` CLIs were removed; uploads go through the **middleware** or your own code calling `evomemory_sync.uploader.upload_memory_record`.
