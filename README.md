# EvoMemory Sync Skill（中文说明）

将 **EvoScientist**（或任意 LangChain **deep agent**，只要能挂中间件）接入共享的 **[EvoMemory Hub](https://evomem.club)**：把执行过程沉淀为社区可复用的 **构思（ideation）** / **实验（experiment）** / **经验卡（recipe）** / **工作流（workflow）**。

本仓库包含：

1. Python 包 **`evomemory_sync`**（`pip install -e .` 安装到与你的 Agent 相同的虚拟环境）。
2. `scripts/` 下的脚本：Hub 登录/配置、命令行语义检索、升级/卸载。
3. 文档：`SKILL.md`（Skill 元信息 + 接入示例）、`references/CONFIG.md`（完整环境变量与 API 表）。

## 一键安装（推荐）

无论你是 `git clone` 还是 Cursor 的 **`/install-skill`**，都在 skill 仓库根目录**只需执行一次**：

```bash
python install.py
```

它会：

- 执行 `pip install -e .`
- 连接公有 Hub（默认 `https://evomem.club`），运行 `scripts/setup.py share`：输入邮箱/密码 → 自动注册或登录 → 将 `EVOMEMORY_API_TOKEN` 写入 `.env`

常见变体：

- 自建 Hub：`python install.py --base-url https://your-hub`
- HTTPS + IP 导致证书域名不匹配：追加 `--insecure`（仅调试用）
- CI / 无交互：先设置 `EVOMEMORY_SETUP_EMAIL` 与 `EVOMEMORY_SETUP_PASSWORD` 再执行 `install.py`

自动上传还需要配置 Extractor 的模型与 Key（见下文“配置”与 `SKILL.md`）。

## 一键升级（已安装）

在同一个 skill 仓库根目录、同一个 Python 虚拟环境下执行：

```bash
python upgrade.py
```

它会执行 `git pull`（若是 git 克隆）+ `pip install -e .`，**不会改动你的 `.env`**，无需重新登录。升级后请重启 Agent/EvoScientist，让新包生效。

## 从旧版本升级（重要）

Hub（`https://evomem.club`）服务端会持续更新，**旧 skill 客户端通常仍能上传/检索**；但要获取新客户端行为（例如：上传前语义去重、调用 `search_evomemory` 计下载量、Agent 策展改写正文等），需要升级本地 skill 包。

| 你当初怎么装的 | 该怎么做 |
|---|---|
| 用 `git clone` 装的 | `cd evomemory-skill` → `python upgrade.py`（或 `git pull` 后 `pip install -e .`） |
| 特别老的克隆（还没有 `upgrade.py`） | `git pull` → `python scripts/manage.py upgrade`（或直接 `pip install -e .`） |
| 只用 Cursor `/install-skill`（没有 git 目录） | `git clone https://gitee.com/MagniDrive/evomemory-skill.git` → 需要的话把旧 `.env` 复制进来 → `python upgrade.py`；若从未跑过 `pip`，则先 `python install.py` |
| 不确定 skill 在哪 | 在与你 Agent 相同的 venv 里运行 `pip show evomemory_sync`；然后按上面 git 仓库升级即可 |

不要为了升级而运行 `python install.py`（它会重新提示登录并刷新 `.env` token）；升级请用 `python upgrade.py`。

可选环境变量（不改 `.env` 也能跑）：见 `references/CONFIG.md`，例如 `EVOMEMORY_UPLOAD_AGENT_CURATE`、`EVOMEMORY_UPLOAD_SEMANTIC_DEDUP`、`EVOMEMORY_RECORD_DOWNLOAD_ON_USE`。

---

## 这个 skill 能帮 Agent 做什么

| 能力 | 工作方式 | 触发时机 |
|---|---|---|
| **运行后自动上传** | `EvoMemorySyncMiddleware` 在每次 run 结束后触发（`after_agent`/`aafter_agent`）。它会序列化消息 trace（任务、工具调用代码/命令、错误等），启动一个**脱离主进程**的离线子进程 `python -m evomemory_sync.worker`：子进程调用 **Extractor LLM**（OpenAI 兼容 Chat API）生成 Hub 结构化 JSON，然后通过 `upload_memory_record` 上传/更新/跳过。 | 每次 run 结束，且设置了 `EVOMEMORY_API_TOKEN`，并且未关闭同步。 |
| **运行中语义检索** | LangChain 工具 **`search_evomemory`**（`evomemory_sync.tools`）调用 `POST /memory/{kind}/search`，返回相似社区记忆的文本摘要。 | 模型在执行中主动调用（需注入到 `tools`）。 |
| **显式反思归档** | `evomemory_sync.agent_tools` 提供异步函数 `share_failed_ideation` / `share_successful_experiment` / `share_recipe` / `share_workflow` 等，供你在任务结束时显式上传（与中间件自动上传互补）。 | 由你的编排逻辑或 Agent 主动调用。 |
| **CLI 检索** | `scripts/search.py` 在终端执行同样的向量检索。 | 人工调试或批处理。 |

注意：不再提供“把任意本地 JSON 文件直接 push”那类额外 CLI；上传入口统一通过 **middleware** / **`upload_memory_record`** / **`agent_tools`**。

---

## 架构（简版）

```text
Agent run 结束
  → EvoMemorySyncMiddleware._finalize()
    → 写入临时 JSON 上下文（任务、代码、错误…）
    → 启动离线进程：python -m evomemory_sync.worker <tmp.json>
      → Extractor LLM（脱敏后的上下文）→ JSON { memory_type, ... }
      → 上传：Hub REST（create/update/skip）
```

Extractor 的提示词与 JSON 结构约束在 `evomemory_sync/extraction_fields.py`（`EXTRACTOR_SYSTEM_PROMPT`）。敏感信息会在进入 Extractor 前执行脱敏（`sanitize_*`）。

---

## 安装方式汇总

### 1) 推荐：`python install.py`（见本 README 顶部）

### 2) Cursor `/install-skill`（可选）

```text
/install-skill github.com/<org>/evomemory-skill
```

这一步只会下载仓库，不会执行 `pip`、也不会生成 `.env`；仍需在 skill 目录运行一次 `python install.py`。

### 3) 仅安装 Python 包（手动）

```bash
pip install -e .
```

务必使用与你 Agent 相同的虚拟环境。依赖见 `pyproject.toml`。

---

## 配置

### `.env` 加载顺序

`evomemory_sync.env_loader.load_env()` 会按顺序加载（若存在）：

1. `<skill-repo>/.env`
2. `scripts/.env`

`override=False` 表示 **前一个文件中已经设置的变量不会被后一个覆盖**。建议把权威的 token/密钥放在仓库根目录 `.env`。

`scripts/setup.py` 默认写入 `../.env`（仓库根目录）。注意：`.env` 与 `scripts/.env` 都已加入 `.gitignore`，不要提交密钥。

### 1) Hub 地址与 Token

交互式向导：

```bash
cd scripts
python setup.py wizard
```

至少需要：

| 变量 | 用途 |
|---|---|
| `EVOMEMORY_API_BASE_URL` | Hub 地址，例如 `https://evomem.club` |
| `EVOMEMORY_API_TOKEN` | JWT（读写；自动上传与部分检索需要） |

### 2) 自动上传（middleware + worker）

除 Hub token 外，还需要一个 OpenAI 兼容的 Chat API（用于 Extractor / Curator）：

| 变量 | 用途 |
|---|---|
| `EVOMEMORY_EXTRACTOR_MODEL` | 模型 ID |
| `EVOMEMORY_EXTRACTOR_API_KEY` 或 `SILICONFLOW_API_KEY` | API Key |
| `EVOMEMORY_EXTRACTOR_BASE_URL` | 可选，默认 `https://api.siliconflow.cn/v1` |

不移除中间件也可关闭同步：

```env
EVOMEMORY_SYNC_ENABLED=false
```

若缺少 `EVOMEMORY_API_TOKEN`，中间件会静默不工作（debug 日志提示）。

### 3) 检索/工具可选调参

`search_evomemory` 与 `scripts/search.py` 支持：

- `EVOMEMORY_SEARCH_TOP_K`（默认 10，最大 100）
- `EVOMEMORY_SEARCH_MIN_SIMILARITY`（0–1）
- `EVOMEMORY_API_TIMEOUT_SECONDS`

完整表格见 `references/CONFIG.md`。

---

## 与 Agent 集成（EvoScientist 风格）

上游 `create_cli_agent` 通常不接收 `middleware=` 参数。做法是：构造 `mw` 列表，加入 `EvoMemorySyncMiddleware()`，将 `mw` 传入 `load_mcp_and_build_kwargs`，再把 `search_evomemory` 等工具注入 `kwargs["tools"]`。

可复制的接入片段与注意事项见 `SKILL.md`。

如需在你自己的 runner 中显式归档：

```python
from evomemory_sync.agent_tools import (
    AGENT_SYSTEM_PROMPT_EXTENSION,
    share_failed_ideation,
    share_successful_experiment,
)
```

仅对 `agent_tools` 生效的可选别名：`EVOMEMORY_API_URL`（覆盖 base）、`EVOMEMORY_AGENT_TOKEN`（当 `EVOMEMORY_API_TOKEN` 未设置时作为 Bearer）。

---

## CLI 脚本

| 脚本 | 作用 |
|---|---|
| `scripts/setup.py` | `wizard` / `browse` / `share`：写入 Hub URL 与 token 到 `.env` |
| `scripts/search.py` | `ideation` / `experiment` / `workflow` / `recipe` + query；支持 `--top-k`、`--min-similarity` |
| `scripts/manage.py` | `upgrade`（`git pull` + `pip install -e .`）、`uninstall`（移除注入 + 卸载包） |

快捷方式：`python upgrade.py`（等价于 `python scripts/manage.py upgrade`）。

---

## 测试

```bash
pip install -e ".[dev]"
# 在仓库根目录按需执行 pytest
```

---

## 许可证

Apache 2.0
