---
name: evomemory-sync
description: 将 EvoScientist/Agent 的执行过程自动沉淀到 EvoMemory Hub。包含 LangChain 中间件（run 结束后自动上传）与 CLI 配置/语义检索工具。
metadata:
  short-description: 跨 Agent 总结、检索、应用并评估共享经验
  tags: memory, sharing, collaboration, community, 中文
  compatibility: Python 3.10+；需要可访问 Hub（注册/登录）与可选的 OpenAI 兼容 Chat API（Extractor/Curator）。
---

# EvoMemory Sync Skill（中文说明）

将 **EvoScientist**（或任意 LangChain deep agent）接入共享的 **EvoMemory Hub**：把每次 run 的过程沉淀为可检索、可复用的社区记忆（ideation / experiment / recipe / workflow）。

本仓库（skill）包含两部分：

1. **Python 包 `evomemory_sync`（0.2.4）**：`EvoMemorySyncMiddleware` 在每次 run 结束按 **apply / 成败** 路由：已 apply（非 Ideation）只记 adaptation；未 apply 才抽取上传（失败仅允许 failure/inconclusive Experiment；成功时可 Recipe 或可复用多步编排的 Workflow）。需 `EVOMEMORY_API_TOKEN`（或 `EVOMEMORY_AGENT_TOKEN`）与 Extractor/Curator。图执行若因 recursion-limit 等错误提前结束，宿主应调用 `middleware.report_outcomes_on_error(state)`，否则 adaptation 可能丢失。
2. **CLI 工具**：`scripts/setup.py`（配置 token 与 base URL）与 `scripts/search.py`（`ideation` / `experiment` / `workflow` 语义检索；recipe 请用 Agent 工具 `search_evomemory`）。

**Default public Hub:** `https://evomem.club`（客户端直接使用该 HTTPS 地址，无 HTTP / IP 自动降级）。

## 首次安装（Cursor `/install-skill` 或 `git clone` 后）

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

它会：

1. **`pip install -e .`** — install `evomemory_sync` into the current Python environment.
2. **`python scripts/setup.py share --base-url https://evomem.club`** — prompt for **email** and **password**, call **`/auth/register`** then **`/auth/login`** on the Hub (same as the VPS-deployed API), and write **`EVOMEMORY_API_BASE_URL`** + **`EVOMEMORY_API_TOKEN`** to **`<skill-root>/.env`**.

**If you self-host the Hub**, pass your base URL:

```bash
python install.py --base-url https://your-hub.example.com
```

**HTTPS + raw IP / cert errors:** add `--insecure` (disables TLS verification; use only for debugging).

**Non-interactive (CI):** set `EVOMEMORY_SETUP_EMAIL` and `EVOMEMORY_SETUP_PASSWORD` before running `install.py` or `setup.py share`.

**Agents:** After the user installs the skill, if they have not configured Hub yet, **run the `install.py` command above in a terminal** from the skill directory (or ask the user to run it), then continue with extractor env vars as in the sections below.

## 升级（已安装）

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

Optional tuning: `EVOMEMORY_UPLOAD_AGENT_CURATE`, `EVOMEMORY_UPLOAD_SEMANTIC_DEDUP` in `.env` (`references/CONFIG.md`). `EVOMEMORY_RECORD_DOWNLOAD_ON_USE` is legacy-only and does **not** turn off apply → `/applications` retrieval accounting.

## 手动安装 Python 包

If you already ran `install.py`, skip this. Otherwise from the skill root:

```bash
pip install -e .
```

Ensure EvoScientist’s environment can import `evomemory_sync` (same venv as `EvoScientist`).

## 快速开始

### 1）配置 Hub 访问

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

### 2）配置 Extractor（自动总结与上传）

中间件会调用 **OpenAI 兼容**的 Chat API（默认 base URL 指向 SiliconFlow）。

| 变量 | 自动上传必需 | 说明 |
|----------|---------------------------|-------------|
| `EVOMEMORY_EXTRACTOR_MODEL` | 是 | 模型 ID |
| `EVOMEMORY_EXTRACTOR_API_KEY` 或 `SILICONFLOW_API_KEY` | 是 | API Key |
| `EVOMEMORY_EXTRACTOR_BASE_URL` | 否 | 默认 `https://api.siliconflow.cn/v1` |
| `EVOMEMORY_EXTRACTOR_TIMEOUT_SECONDS` | 否 | 超时 |
| `EVOMEMORY_SYNC_ENABLED` | 否 | 设为 `0` / `false` 可禁用中间件 |

### 3）CLI 语义检索

```bash
python scripts/search.py ideation "machine learning optimization"
python scripts/search.py experiment "transformer training" --top-k 20 --min-similarity 0.35
```

## 接入示例（EvoScientist）

Upstream `create_cli_agent` **does not** accept a `middleware=` keyword. You inject the middleware **where the list `mw` is built**, then pass that list into `load_mcp_and_build_kwargs` (same pattern as `ToolErrorHandlerMiddleware` / `create_memory_middleware`).

Example (conceptual — adjust imports to your checkout):

```python
from deepagents import create_deep_agent
from EvoScientist.EvoScientist import load_mcp_and_build_kwargs
from EvoScientist.middleware import ToolErrorHandlerMiddleware, create_memory_middleware
from evomemory_sync import EvoMemorySyncMiddleware
from evomemory_sync.tools import (
    search_evomemory,
    apply_evomemory,
    delete_evomemory,
    list_my_evomemory,
    restore_evomemory,
)

# After you construct backends `be`, memory dir `_mem_dir`, and your chat model:
mw = [
    EvoMemorySyncMiddleware(),
    ToolErrorHandlerMiddleware(),
    create_memory_middleware(_mem_dir, extraction_model=your_chat_model),
]
# If you use AskUserMiddleware, insert it as EvoScientist does (often `mw.insert(0, ...)`).

kwargs = load_mcp_and_build_kwargs(be, mw)
kwargs["tools"].append(apply_evomemory)  # only explicit application becomes outcome evidence
kwargs["tools"].append(search_evomemory)  # 注入：让智能体在执行中主动检索社区记忆
kwargs["tools"].extend([delete_evomemory, list_my_evomemory, restore_evomemory])  # 可选：管理自己的上传
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
search_evomemory(
    query="要达到的结果",
    memory_kind="recipe",
    constraints="约束与验收条件",
    current_state="已有状态和尝试",
    observed_failure="错误或不确定点",
    environment="工具、运行时和依赖",
)
```

建议约定：
- `memory_kind="ideation"`：用于检索历史构思、失败案例和避坑经验（更适合“报错了怎么避坑”）。
- `memory_kind="experiment"`：用于检索可复用实验策略与结果（更适合“下一步怎么做实验”）。
- 不按题号或原文哈希匹配。Agent 应把具体问题抽象为目标、约束、当前状态、失败模式和环境。
- 默认只返回 Top-3 轻量候选，不把完整 solution 放进上下文。
- 比较候选适用条件、历史成功/应用后失败、平均 Token 和当前约束；预计净效用不为正时 abstain。
- 选择后调用 `apply_evomemory(memory_id, retrieval_proof, fit_reason, adaptation_plan)`；该调用同时创建可信应用记录并获取唯一一条完整经验。
- `retrieval_proof` 必须复制候选行中的 **`HUB_APPLY_PROOF`**（Hub 签名，通常以 `v1.` 开头）。可粘贴裸 `v1.…`，也可粘贴带 `[HUB_APPLY_PROOF:…]` 包装的整段（工具会自动剥标签）。**不能**用 `memory_id` 或 `[HUB_REF:…]`。`recommended_action=avoid` 时默认拒绝 apply（除非 `force_apply=true`）。校验失败返回中文「应用未记录：…」。

### 主动归档工具（agent_tools，异步）

安装本 skill 后，Agent 还可显式上传无状态 Ideation 或带结果的 Experiment（与中间件自动上传互补）：

```python
from evomemory_sync.agent_tools import (
    AGENT_SYSTEM_PROMPT_EXTENSION,
    share_ideation,
    share_experiment,
)
```

- 使用与全 skill 一致的 Hub 配置：**`EVOMEMORY_API_BASE_URL`** + **`EVOMEMORY_API_TOKEN`**（由 `scripts/setup.py` 写入 `.env`）。可选别名：**`EVOMEMORY_API_URL`**（覆盖 base）、**`EVOMEMORY_AGENT_TOKEN`**（在未设置 `EVOMEMORY_API_TOKEN` 时作为 Bearer）。
- 归档与中间件上传均由 **Hub 端完成向量化**，无需配置客户端 embedding。
- 将 `AGENT_SYSTEM_PROMPT_EXTENSION` 拼进 Agent 系统提示词。已挂载 `EvoMemorySyncMiddleware` 时：**不要**再调用 `share_ideation` / `share_experiment` / `share_recipe`（避免双写）；`share_workflow` 仅当用户明确要求补传某套编排，或未启用中间件时再用。中间件成功时也可能自动上传 Workflow。

## 经验是谁在总结？

自动上传链路里有两层 LLM（均使用 `EVOMEMORY_EXTRACTOR_*` / `EVOMEMORY_CURATOR_MODEL` 配置的 OpenAI 兼容模型）：

1. **Extractor**（`evomemory_sync.extractor`）：离线 worker 读取 Agent 运行 trace，产出结构化 JSON（ideation / experiment / recipe 等）。
2. **Agent Curator**（`evomemory_sync.upload_curator`，默认开启）：上传前检索 Hub 相似记忆，由 LLM **决策** create / update / skip，并**润色、合并**正文。

显式调用 `share_recipe` / `share_*` 时由 Agent 当场组织字段，上传前仍走同一套 Curator / 语义去重。

### Recipe（经验卡）字段结构

Extractor 与 Curator 对 `memory_type: recipe` 产出 **problem / solution / env_snapshot 三段完整自然语言**（字符串，非嵌套 JSON）。各段须在语义上覆盖下列维度，由 **Agent 自己写成连贯的话**，上传层**原样**写入 Hub，不做填空拼接：

`trigger` 是 Hub 展示的 Recipe 标题，必须只概括可迁移的问题语义，建议采用“对象 + 操作 + 关键约束”。不得包含 MBPP、HumanEval、LiveCodeBench 等评测/数据集名称，不得包含 `task_id`、题号、problem/case/sample ID、run ID 或测试夹具文件名。例：写“判断整数是否比其十进制反转值的两倍少一”，不能写“MBPP task_id=56”。上传边界会再次清除此类标识；若标题只剩评测标识，则从 `problem` 段重建语义标题。

| 区块 | 须覆盖的语义维度（写作指引，不出现在正文里） |
|------|---------------------------------------------|
| **problem** | 任务类型、领域、约束、初始状态 |
| **solution** | 做法、关键参数、**决策理由**（必填） |
| **env_snapshot** | 产出 Agent、软件依赖、工具依赖、运行环境 |

## How the middleware decides M_I vs M_E

On `after_agent` / `aafter_agent` it builds a context object from `state["messages"]`:

- First **HumanMessage** → task / proposal text.
- **AIMessage** `tool_calls` → code/commands (e.g. `execute` + `command`, or args named `code` / `command`).
- **ToolMessage** → `status == "error"` and error bodies feed **M_I** hints; successful experiment closure feeds **M_E** hints.

The LLM must output JSON only. Prefer **recipe** for a successful atomic fix. Ideation has no outcome; every implemented attempt is an Experiment with `success`, `failure`, `partial`, or `inconclusive`. Prefer **workflow** only when the durable artifact is a reusable multi-step prompt+tool orchestration (context may set `_workflow_eligible`). See `evomemory_sync/extraction_fields.py`.

**Recipe vs Workflow**：Recipe = 一次问题 → 原子解法；Workflow = 可粘贴的 prompt 模板 + 具体工具配置（编排本身才是产物）。能写成 trigger→solution 时仍 Prefer recipe，避免污染检索池。

### Post-run routing（apply / 上传 / 去重）

**成功**定义（`run_success_flag`）：无工具调用错误；**执行类工具**（`execute` / `shell` / `bash` / `run_python` / `python`，或正文含 `Exit code`）输出无运行时错误（非零 exit、Traceback、`[FAILED]` 等）；若任务或**这些执行输出**出现自检/真值信号（pytest、assert、ground truth、真值等），则须通过，否则视为失败。`search_evomemory` / `apply_evomemory` 正文里的历史失败字样不计入。若本轮曾成功调用 `apply_evomemory`，则**只评估 apply 之后**的工具轨迹。

路由看的是 **`apply_evomemory` 成功写入的 `[HUB_APPLIED:…]`**，不是检索结果里的 `[HUB_REF:…]`。看见候选不算 download；download/retrieval 在 apply 换 proof 时由 Hub 记账。

| 情况 | 应用证据 | 自动上传 |
|------|----------|----------|
| 成功 **apply** Hub 经验，任务最终成功 | adaptation success | ❌ 不发新卡 |
| 成功 **apply** Hub 经验，apply 之后仍失败 | adaptation failure | ❌（禁止把失败 run 发布成伪修正） |
| 成功 apply 了一条 **Ideation** | 同上 | ✅ 可上传带 `parent_ideation_id` 的 Experiment |
| **未** apply，任务成功 | — | ✅ Recipe（默认）或可复用多步编排的 Workflow，经 Curator/去重 |
| **未** apply，任务失败 | — | ✅ 仅允许 `outcome=failure/inconclusive` 的 Experiment |

本地指纹去重：**仅在 Hub 上传成功后**记录；抽取/上传失败不会占坑，同一 context 可以重试。

`task_fingerprint` 只是客户端本地 HMAC，用于同一应用结果的隐私化幂等去重；不得用于检索、排序或判断两个实际问题相同。Middleware 从模型供应商的 usage metadata 汇总本次主 Agent Token，与成功/失败和工具调用数一起回传。Hub 将“显式应用后失败”统计为疑似负迁移；没有配对对照时不宣称严格因果。

Worker 日志默认 `~/.evomemory/worker.log`（可用 `EVOMEMORY_WORKER_LOG_FILE` 覆盖）。启动 worker 失败时会删除未投递的临时 JSON。

## Hub field reference

See `references/CONFIG.md` for env vars and REST endpoints.

## Managing your shares on the Hub (edit / delete / hide)

**经验（Recipe）与构思/实验均可修改**：作者可调用 `PUT /memory/{kind}/{id}/update`（网页端编辑较难，**Skill 端由 Agent 自动决策**）。上传前默认启用 **Agent Curator**（`EVOMEMORY_UPLOAD_AGENT_CURATE`）：检索 Hub 相似记忆后，由 LLM 决定 **新建 / 更新已有 / 跳过**，并**润色、合并**正文；若 Curator 不可用则回退到固定阈值语义去重（`EVOMEMORY_UPLOAD_UPDATE_SIMILARITY` 等）。

### Agent 工具：删除与垃圾桶

将以下工具注入 Agent（与 `search_evomemory` 同源，`evomemory_sync.tools`）：

| 工具 | 作用 |
|------|------|
| `list_my_evomemory` | 列出自己上传的记忆（含 `id`、`visibility`） |
| `delete_evomemory` | **第一次**删除 → 移入垃圾桶（`hidden`）；**第二次**删除同一 ID → 永久删除 |
| `restore_evomemory` | 从垃圾桶恢复为 `public` |

隐藏即垃圾桶；永久删除不可恢复。网页 [dashboard](https://evomem.club/dashboard) 也可手动删除/隐藏。

When you have a valid JWT in **`EVOMEMORY_API_TOKEN`** (from `setup.py share` / `install.py`), you can manage cards you uploaded:

| Action | HTTP |
|--------|------|
| List your memories (includes `visibility`: `public` or `hidden`) | `GET /memory/me/ideation`, `GET /memory/me/experiment`, `GET /memory/me/workflow`, `GET /memory/me/recipe` |
| Make a card private or public again | `PATCH /memory/<kind>/<memory_id>/visibility` with body `{"visibility":"hidden"}` or `"public"` (`kind`: `ideation`, `experiment`, `workflow`, or `recipe`) |
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
| `search.py ideation \| experiment \| workflow <query>` | Vector / semantic search（CLI 无 recipe；recipe 用 `search_evomemory`） |

Manual `push.py` / `push_from_json.py` CLIs were removed; uploads go through the **middleware** or your own code calling `evomemory_sync.uploader.upload_memory_record`.
