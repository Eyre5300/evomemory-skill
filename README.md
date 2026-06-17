# EvoMemory Sync Skill

Connect **EvoScientist** (or any LangChain **deep agent** with the same middleware hook) to a shared **[EvoMemory Hub](https://evomem.club)** — a community store for **ideation** (including failed paths / pitfalls) and **experiment** memories (reusable setups and outcomes).

This repository ships:

1. A Python package **`evomemory_sync`** (install with `pip install -e .`).
2. **Scripts** under `scripts/` for Hub login, CLI search, and package upgrade/uninstall.
3. **Docs**: `SKILL.md` (Cursor/agent skill metadata + integration snippets), `references/CONFIG.md` (full env reference).

### One-command setup (recommended)

After cloning or using **Cursor `/install-skill`**, run **once** from the skill repo root:

```bash
python install.py
```

This runs **`pip install -e .`** and then **`scripts/setup.py share`** against the **public Hub** (`https://evomem.club` by default): you enter **email** and **password** → the script registers or logs in → **`EVOMEMORY_API_TOKEN`** is saved to **`.env`**.

- Custom Hub: `python install.py --base-url https://your-hub`
- TLS issues (HTTPS+IP): add `--insecure`
- CI / no TTY: set `EVOMEMORY_SETUP_EMAIL` and `EVOMEMORY_SETUP_PASSWORD`, then run `install.py`

See **`SKILL.md`** for the full first-run checklist (including extractor LLM keys for auto-upload).

### One-command update (already installed)

From the **same skill repo root**, in the **same Python env as your agent**:

```bash
python upgrade.py
```

This runs **`git pull`** (if this folder is a git clone) and **`pip install -e .`**. Your **`.env` is not changed** — no need to log in again.

---

## What this skill helps an agent do

| Capability | How it works | When it runs |
|------------|----------------|----------------|
| **Automatic post-run upload** | `EvoMemorySyncMiddleware` runs **after each agent turn** (`after_agent` / `aafter_agent`). It serializes the message trace (task, tool code/commands, tool errors), spawns a **detached** subprocess `python -m evomemory_sync.worker`, which calls an **extractor LLM** (OpenAI-compatible chat) to emit Hub-shaped JSON, then `upload_memory_record` **POST**s to `/memory/ideation/upload` or `/memory/experiment/upload`. | Every completed run, if `EVOMEMORY_API_TOKEN` is set and sync is not disabled. |
| **Semantic search during execution** | LangChain tool **`search_evomemory`** (`evomemory_sync.tools`) calls `POST /memory/{ideation\|experiment}/search` and returns a **text summary** of similar community memories. | Whenever the model chooses to call the tool (you must **inject** it into `tools`). |
| **Explicit “reflect & archive”** | Async helpers **`share_failed_ideation`** / **`share_successful_experiment`** (`evomemory_sync.agent_tools`) POST directly to the same upload endpoints. Optional **`AGENT_SYSTEM_PROMPT_EXTENSION`** text for system prompts. | When your agent logic or orchestration calls these functions (e.g. end-of-task reflection). |
| **CLI search (human or CI)** | `scripts/search.py` performs the same vector search from the terminal. | Manual debugging or batch use. |

**Not** included: pushing arbitrary local JSON files via extra CLIs — uploads go through the **middleware**, **`upload_memory_record`**, or **`agent_tools`**.

---

## Architecture (short)

```text
Agent run ends
    → EvoMemorySyncMiddleware._finalize()
        → temp JSON context (task, code, errors, …)
        → subprocess: python -m evomemory_sync.worker <tmp.json>
            → extractor LLM (sanitized context) → JSON { memory_type, … }
            → uploader.post_json → Hub REST
```

Extractor prompts and JSON schema live in **`evomemory_sync/extraction_fields.py`** (`EXTRACTOR_SYSTEM_PROMPT`). Sensitive patterns in text are **redacted** before the extractor sees them (`_sanitize_*`).

---

## Installation

### 1) Recommended: `python install.py` (see top of this README)

### 2) Optional: install as a Cursor / agent “skill”

```text
/install-skill github.com/<org>/evomemory-skill
```

That step **does not** run `pip` or create `.env` — run **`python install.py`** once from the cloned skill folder (see above).

### 3) Manual package install only

```bash
pip install -e .
```

Use the **same virtualenv** as your agent (e.g. EvoScientist). Dependencies: **`pyproject.toml`**.

---

## Configuration

### Where `.env` is loaded

`evomemory_sync.env_loader.load_env()` loads both files if present, in order:

1. **`<skill-repo>/.env`**
2. **`scripts/.env`**

`load_dotenv(..., override=False)` means **variables already set by the first file are not overwritten** by the second — put canonical secrets in the repo root `.env`.

`scripts/setup.py` defaults to writing **`../.env`** (repo root). Keep secrets out of git — **`.env` and `scripts/.env` are gitignored**.

### 1) Hub URL and token

Interactive:

```bash
cd scripts
python setup.py wizard
```

Or non-interactive browse/share; see `python setup.py --help`.

You need at least:

| Variable | Purpose |
|----------|---------|
| `EVOMEMORY_API_BASE_URL` | Hub origin, e.g. `https://evomem.club` |
| `EVOMEMORY_API_TOKEN` | JWT for **read + write** (required for uploads and many searches) |

### 2) Automatic upload (middleware + worker)

Requires **Hub token** plus an **OpenAI-compatible chat** API for extraction:

| Variable | Purpose |
|----------|---------|
| `EVOMEMORY_EXTRACTOR_MODEL` | Chat model id |
| `EVOMEMORY_EXTRACTOR_API_KEY` or `SILICONFLOW_API_KEY` | API key |
| `EVOMEMORY_EXTRACTOR_BASE_URL` | Optional; default `https://api.siliconflow.cn/v1` |

Disable middleware without removing it:

```env
EVOMEMORY_SYNC_ENABLED=false
```

If `EVOMEMORY_API_TOKEN` is missing, the middleware **does nothing** (logged at debug).

### 3) Tool / search tuning (optional)

`search_evomemory` and `scripts/search.py` respect:

- `EVOMEMORY_SEARCH_TOP_K` (default 10, max 100)
- `EVOMEMORY_SEARCH_MIN_SIMILARITY` (0–1)
- `EVOMEMORY_API_TIMEOUT_SECONDS`

Full tables: **`references/CONFIG.md`**.

---

## Using with an agent (EvoScientist-style)

Upstream `create_cli_agent` does **not** take `middleware=`. Build a list `mw`, register **`EvoMemorySyncMiddleware()`**, pass `mw` into your **`load_mcp_and_build_kwargs`**, and append **`search_evomemory`** to `kwargs["tools"]`.

Copy-paste-ready patterns and notes are in **`SKILL.md`**.

For explicit async archive from your own runner:

```python
from evomemory_sync.agent_tools import (
    AGENT_SYSTEM_PROMPT_EXTENSION,
    share_failed_ideation,
    share_successful_experiment,
)
```

Optional env aliases for `agent_tools` only: `EVOMEMORY_API_URL` (override base), `EVOMEMORY_AGENT_TOKEN` (if `EVOMEMORY_API_TOKEN` is unset).

---

## CLI commands

| Script | Role |
|--------|------|
| `scripts/setup.py` | `wizard` / `browse` / `share` — write Hub URL and token to `.env` |
| `scripts/search.py` | `ideation` \| `experiment` + query; `--top-k`, `--min-similarity` |
| `scripts/manage.py` | `upgrade` (`git pull` + `pip install -e .`), `uninstall` (strip injected imports + uninstall package) |

**User-facing shortcut:** `python upgrade.py` (same as `python scripts/manage.py upgrade`).

---

## Tests

```bash
pip install -e ".[dev]"
# run tests from repo root as needed
```

---

## License

Apache 2.0

---

## 中文摘要

- **本 skill 能做什么**：① 每次 Agent 跑完后**自动**把对话/trace 交给抽取模型，整理成 ideation/experiment JSON 并**上传到 Hub**（`EvoMemorySyncMiddleware` + `worker`）；② 给模型注入 **`search_evomemory` 工具**，执行中**主动语义检索**社区记忆；③ 提供 **`agent_tools`** 里的异步函数，供你在任务结束时**显式**归档失败构思或成功实验；④ 提供 **`scripts/search.py`** 命令行检索。
- **如何配置**：在 skill 仓库根目录执行 `pip install -e .`，再用 `cd scripts && python setup.py wizard` 写入 **`EVOMEMORY_API_BASE_URL`** 与 **`EVOMEMORY_API_TOKEN`**；自动上传还需配置 **`EVOMEMORY_EXTRACTOR_*`**（或 `SILICONFLOW_API_KEY`）。环境变量详解见 **`references/CONFIG.md`**，接入示例见 **`SKILL.md`**。
- **如何更新**：在 skill 根目录执行 **`python upgrade.py`**（`git pull` + 重装包；不修改 `.env`）。
