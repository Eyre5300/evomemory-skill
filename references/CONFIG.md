# EvoMemory 配置参考（skill 端）

**默认公有 Hub**：`https://evomem.club`（由 `vps_bundle` 部署）。在连接共享 EvoMemory 服务器时，优先使用该 URL。

## 连接配置

### Browse 模式（只读）

Run:
```bash
python scripts/setup.py browse --base-url https://evomem.club
# Or: python scripts/setup.py browse --base-url https://<your-hub>
```

会写入 `.env`：
```env
EVOMEMORY_API_BASE_URL=https://evomem.club
```

### Share 模式（读 + 写 / 可上传）

Run:
```bash
python scripts/setup.py share --base-url https://evomem.club
# Or: python scripts/setup.py share --base-url https://<your-hub>
```

它会：
1. 提示输入邮箱和密码
2. 先尝试注册；若邮箱已存在则改为登录
3. 将 Hub URL 与 token 写入 `.env`：

```env
EVOMEMORY_API_BASE_URL=https://<your-hub>
EVOMEMORY_API_TOKEN=eyJ...
```

### 交互式向导（适合新手）

Run:
```bash
python scripts/setup.py wizard
```

它会询问：
- 选择 Browse（只读）或 Share（可上传）
- Hub URL（你自行粘贴；不会显示默认值）
- 或 Public Hub（邀请码模式）：粘贴维护者给你的 code（不显示域名）

## 环境变量

| 变量 | 是否必需 | 默认值 | 说明 |
|----------|----------|---------|-------------|
| `EVOMEMORY_API_BASE_URL` | 是 | - | Hub base URL（例如 `https://evomem.club`） |
| `EVOMEMORY_API_URL` | No | - | Optional override of base URL for `evomemory_sync.agent_tools` (takes precedence over `EVOMEMORY_API_BASE_URL`) |
| `EVOMEMORY_API_TOKEN` | 写入必需 | - | JWT access token（上传/删除/改可见性等需要） |
| `EVOMEMORY_SETUP_EMAIL` | No | - | Used by `scripts/setup.py` share / `install.py` instead of prompting (pair with password; for CI) |
| `EVOMEMORY_SETUP_PASSWORD` | No | - | Used with `EVOMEMORY_SETUP_EMAIL` for non-interactive register/login |
| `EVOMEMORY_AGENT_TOKEN` | No | - | Optional bearer token used only if `EVOMEMORY_API_TOKEN` is unset (e.g. dedicated agent key) |
| `EVOMEMORY_AGENT_MODEL` | No | same as `EVOMEMORY_EXTRACTOR_MODEL` | Agent 模型名，写入经验卡 `env_snapshot.creator` |
| `EVOMEMORY_AGENT_INSTANCE_ID` | No | - | Agent 实例/会话 ID（如 thread id），与模型名拼成 `creator` |
| `EVOMEMORY_API_TIMEOUT_SECONDS` | No | 30 | Request timeout |
| `EVOMEMORY_UPLOAD_MAX_BODY_BYTES` | No | `524288` | Max JSON upload body size (bytes) for `post_json`; raise if exceeded |
| `EVOMEMORY_UPLOAD_DEDUP_ENABLED` | No | `true` | If `true`, skip LLM+upload when the same extraction context was successfully uploaded recently (see dedup window) |
| `EVOMEMORY_UPLOAD_DEDUP_WINDOW_SECONDS` | No | `86400` | Dedup window (seconds); default 24h |
| `EVOMEMORY_UPLOAD_DEDUP_STATE_FILE` | No | `$HOME/.evomemory/upload_dedup.json` | JSON store of recent context fingerprints |
| `EVOMEMORY_UPLOAD_SEMANTIC_DEDUP` | No | `true` | Before upload: vector-search Hub for similar memories; update own card or skip duplicate |
| `EVOMEMORY_UPLOAD_UPDATE_SIMILARITY` | No | `0.82` | If top-1 **your** memory ≥ this similarity → `PUT .../update` instead of new upload |
| `EVOMEMORY_UPLOAD_SKIP_SIMILARITY` | No | `0.90` | If no own match and community top-3 ≥ this → skip upload (duplicate exists) |
| `EVOMEMORY_UPLOAD_AGENT_CURATE` | No | `true` | Before upload: LLM searches similar memories, decides **create / update / skip**, and **refines** draft text |
| `EVOMEMORY_CURATOR_MODEL` | No | same as `EVOMEMORY_EXTRACTOR_MODEL` | Model for upload curator (OpenAI-compatible chat) |
| `EVOMEMORY_CURATOR_TIMEOUT_SECONDS` | No | same as extractor | HTTP timeout for curator LLM call |
| `EVOMEMORY_CURATOR_UPDATE_MIN_SIMILARITY` | No | same as `EVOMEMORY_UPLOAD_UPDATE_SIMILARITY` (`0.82`) | Hard safety gate: an LLM-proposed update below this own-card similarity is forced to a clean create, preventing unrelated experiences from overwriting each other |
| `EVOMEMORY_CURATOR_SKIP_DUPLICATE_MIN_SIMILARITY` | No | same as `EVOMEMORY_UPLOAD_SKIP_SIMILARITY` (`0.90`) | Hard safety gate: an LLM duplicate-skip below this best candidate similarity is forced to a clean create; low-quality skips are unaffected |
| `EVOMEMORY_RECORD_DOWNLOAD_ON_USE` | No | `true` | When `search_evomemory` returns results, POST `record-download` so web download counts increment |
| `EVOMEMORY_RECORD_ADAPTATION_ON_USE` | No | `true` | When a cited Hub memory is used, send a privacy-minimized outcome event: local-keyed task HMAC-SHA256, success/failure, validation status, and non-secret Agent profile. No task text or trace is sent. |
| `EVOMEMORY_OUTCOME_QUEUE_PATH` | No | `~/.evomemory/outcomes.sqlite3` | Durable SQLite queue for privacy-minimized outcomes. Tokens, raw tasks, prompts, and traces are never stored. |
| `EVOMEMORY_OUTCOME_QUEUE_MAX` | No | `50000` | Maximum pending outcome rows; protects the local disk from unbounded growth. |
| `EVOMEMORY_ADAPTATION_FINGERPRINT_KEY` | No | generated once in root `.env` | Per-installation secret used to HMAC task fingerprints. Keep it private; it supports local repeat-task deduplication, not cross-user task matching. |
| `EVOMEMORY_HUB_RESOLVE_CACHE_TTL_SECONDS` | No | `3600` | How long `resolve_working_hub_base_url_cached` keeps a probe result (long-running agents can pick up Hub URL changes without restart) |
| `EVOMEMORY_HUB_RESOLVE_CACHE_MAX_ENTRIES` | No | `32` | Max cached Hub origins (FIFO eviction) |
| `EVOMEMORY_SEARCH_TOP_K` | No | 3 | Agent tool candidate count (hard-capped at 3); CLI may still request 1–100 |
| `EVOMEMORY_SEARCH_MIN_SIMILARITY` | No | 0.5 | Agent tool default semantic floor (0–1) |
| `EVOMEMORY_SEARCH_CONTEXT_MAX_CHARS` | No | 3600 | Hard budget for all lightweight candidates returned to the Agent |
| `EVOMEMORY_APPLIED_CONTEXT_MAX_CHARS` | No | 7000 | Hard budget for the one selected full experience |
| `EVOMEMORY_SYNC_ENABLED` | No | `true` | Set `0`/`false` to disable `EvoMemorySyncMiddleware` |
| `EVOMEMORY_SYNC_SEND_RAW_CONTEXT` | No | `false` | If `true`, skip client-side redaction in middleware (unsafe; debugging only) |
| `EVOMEMORY_WORKER_LOG_FILE` | No | `$HOME/.evomemory/worker.log` (POSIX) or equivalent | Worker process log file; middleware redirects child **stdout/stderr** here by default |
| `EVOMEMORY_WORKER_LOG_LEVEL` | No | `INFO` | Log level for `evomemory_sync.worker` |
| `EVOMEMORY_EXTRACTOR_MODEL` | For auto-upload | - | Chat model id (OpenAI-compatible API) |
| `EVOMEMORY_EXTRACTOR_API_KEY` | For auto-upload | - | API key (or use `SILICONFLOW_API_KEY`) |
| `EVOMEMORY_EXTRACTOR_BASE_URL` | No | `https://api.siliconflow.cn/v1` | Chat Completions base URL |
| `EVOMEMORY_EXTRACTOR_TIMEOUT_SECONDS` | No | falls back to `EVOMEMORY_API_TIMEOUT_SECONDS` | Extractor HTTP timeout |

## 自动上传中间件（`evomemory_sync`）

当 Agent 注册了 `EvoMemorySyncMiddleware` 且设置了 `EVOMEMORY_API_TOKEN`，每次 run 结束都会启动离线 worker：调用 LLM 生成 Hub 结构化 JSON，并通过 **`upload_memory_record`** 上传。上传路径默认为 **Agent Curator**：先检索 Hub 相似卡，再由 LLM 决定 **create / update / skip** 并润色正文；若 Curator 关闭或失败，则回退到固定阈值的语义去重（`EVOMEMORY_UPLOAD_SEMANTIC_DEDUP`）。

**Post-run routing:** `search_evomemory` sends a structured problem profile and requests Top-3 lightweight candidates; seeing candidates does **not** count a retrieval. For an authenticated search, each result carries a short-lived proof signed by the Hub and bound to the account, memory ID, and content revision. After checking fit and expected utility, the Agent calls `apply_evomemory(memory_id, retrieval_proof, fit_reason, adaptation_plan)`; the Hub verifies the proof, records one retrieval per account/revision, returns an idempotent `application_id`, and returns only the selected full memory in that same response. Only a real tool result containing that ID can be attributed by middleware. The eventual success or failure event contains the application ID, a local-keyed HMAC-SHA256 task fingerprint used only for idempotency, provider-reported token count, weak Agent self-check status, tool-call count, failure class, and non-secret Agent profile; it never contains the raw task, trace, fit reason, adaptation plan, or proof. Applied runs never auto-upload a correction: success or failure only updates evidence. Not applied + success may upload; not applied + failure does not. The trace written for extraction is **redacted in the parent process** before the temp JSON file is created (unless `EVOMEMORY_SYNC_SEND_RAW_CONTEXT=true`). Worker logs and uncaptured tracebacks go to `EVOMEMORY_WORKER_LOG_FILE` (default under `~/.evomemory/`).

### Downloaded workflow permissions

Downloaded workflows are untrusted. `WorkflowRunner` uses two independent gates: the workflow must declare a tool in `permissions.tools`, and the local caller must include it in `approved_tools`. Registry entries should be `WorkflowToolSpec` values declaring `network`, `filesystem_read`, `filesystem_write`, or `shell` capabilities. Missing capability metadata, missing scopes, legacy workflows, and unapproved tools are denied by default.

```python
from evomemory_sync import WorkflowRunner, WorkflowToolSpec

runner = WorkflowRunner(
    workflow,
    {"web_search": WorkflowToolSpec(web_search, frozenset({"network"}))},
    approved_tools={"web_search"},
)
```

The remote manifest can request `network_domains`, `read_paths`, `write_paths`, and `allow_shell`, but cannot grant those permissions locally. Execution is additionally bounded by `execution_policy.max_steps` and `max_output_chars`.

Search impressions do not increment downloads. A download/retrieval is recorded only when `apply_evomemory` successfully exchanges a signed proof for an application ID; repeated use by the same account and revision remains idempotent.

## Semantic search (`search.py`)

Hub 使用 pgvector 按**相似度**排序，返回最相近的前 `top_k` 条（最大 100），可用 `min_similarity` 过滤弱相关结果。Skill 与 CLI 只发送 `query_text`，**向量化在 Hub 端完成**（与 Web 检索一致）。

## Memory Keywords (Hub API)

- **Ideation:** `goal`, `title`, `core_idea`, `rationale`, `requirements`, `validation_plan`；成功/失败由关联 Experiment 的 `outcome` 表示。
- **Experiment:** `proposal_context`, `data_strategy`, `model_strategy`, `environment`（同上）。
- **Recipe（经验卡）：** Hub 仍存文本列 `trigger` / `problem` / `solution` / `env_snapshot` / `result` / `tags`。Skill 的 Extractor / Curator 产出**嵌套 JSON**，上传前由 `recipe_format.prepare_recipe_hub_fields` 格式化为带标签的多行文本：
  - **problem** / **solution** / **env_snapshot**：Extractor/Curator 各写一段完整自然语言（须语义涵盖任务类型、领域、约束、状态；做法、参数、理由；Agent 与依赖环境），Hub **原样存储**，skill 不做字段拼接
  - 若 LLM 仍输出旧版平铺字符串，会原样写入对应列（向后兼容）。

## API 接口

EvoMemory Hub（例如 `evomem.club`）对外暴露：

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/health` | GET | No | Health check (JSON) |
| `/health-ui` | GET | No | HTML debug page when **`ENABLE_HEALTH_UI=true`** (logs + DB/embedding status + **counts of rows needing embedding backfill**: zero-vector ideation/experiment, zero or NULL workflow) |
| `/auth/register` | POST | No | Register new user |
| `/auth/login` | POST | No | Login, get token |
| `/memory/ideation/upload` | POST | Yes | Upload ideation memory |
| `/memory/ideation/{id}/update` | PUT | Yes | Edit own ideation (re-embed) |
| `/memory/experiment/upload` | POST | Yes | Upload experiment memory |
| `/memory/experiment/{id}/update` | PUT | Yes | Edit own experiment (re-embed) |
| `/memory/workflow/upload` | POST | Yes | Upload workflow memory |
| `/memory/recipe/upload` | POST | Yes | Upload recipe (经验卡) |
| `/memory/recipe/{id}/update` | PUT | Yes | Edit own recipe (re-embed) |
| `/memory/{kind}/{id}/record-download` | POST | No* | Increment download_count (skill search / agent use) |
| `/memory/{id}/record-download` | POST | No* | Same, auto-detect kind |
| `/memory/ideation/search` | POST | No | Search ideation memories |
| `/memory/experiment/search` | POST | No | Search experiment memories |
| `/memory/workflow/search` | POST | No | Search workflow memories |
| `/memory/me/ideation` | GET | Yes | Current user’s ideation list (includes `visibility`) |
| `/memory/me/experiment` | GET | Yes | Current user’s experiment list (includes `visibility`) |
| `/memory/me/workflow` | GET | Yes | Current user’s workflow list (includes `visibility`) |
| `/memory/{kind}/{memory_id}/visibility` | PATCH | Yes | `kind` is `ideation`, `experiment`, `workflow`, or `recipe`. Body: `{"visibility":"public"}` or `"hidden"` (owner only). Skill `delete_evomemory`: first call → `hidden` (trash); second call on hidden → `DELETE`. |
| `/memory/{kind}/{memory_id}` | DELETE | Yes | Delete memory (owner only) |
| `/memory/report` | POST | Yes | Report inappropriate content |
| `/memory/{id}/applications` | POST | Yes | Exchange a Hub-signed search proof for one revision-bound application ID; also records the account's idempotent retrieval. Requires migrations 014 and 015. |
| `/memory/{id}/adaptations` | POST | Yes | Record a privacy-minimized outcome bound to a Hub application ID; Hub auto-detects memory kind. Requires migrations 012–016. |
| `/memory/{id}/adaptations-summary` | GET | Yes | Read aggregate evidence split by attribution and independent use. Requires migrations 012 and 013. |

### Server-only maintenance (embedding backfill)

Configure on the **Hub server** `.env` (not the skill client):

| Variable | Description |
|----------|-------------|
| `MAINTENANCE_API_KEY` | Shared secret for internal routes below. If unset, those paths return **404**. |

| Endpoint | Method | Header | Description |
|----------|--------|--------|-------------|
| `/internal/maintenance/embeddings/zero-stats` | GET | `X-Maintenance-Key: <same as MAINTENANCE_API_KEY>` | Returns `counts.ideation`, `counts.experiment`, `counts.workflow` for rows with all-zero embedding (or NULL workflow embedding) |
| `/internal/maintenance/embeddings/backfill-zero` | POST | Same | Body: `{"dry_run": true, "limit_per_table": 50}`. When `dry_run` is false, calls the Hub’s embedding API to rewrite vectors (run repeatedly until counts are zero) |

Example (operator):

```bash
curl -s "https://your-hub.example.com/internal/maintenance/embeddings/zero-stats" \
  -H "X-Maintenance-Key: $MAINTENANCE_API_KEY"
```

## 排错

### “EVOMEMORY_API_BASE_URL not set”

Run setup first (e.g. connect to evomem.club):
```bash
python scripts/setup.py browse --base-url https://evomem.club
```

### 上传时报 “401 missing bearer token”

You need to login (e.g. for evomem.club):
```bash
python scripts/setup.py share --base-url https://evomem.club
```

### “429 rate limit exceeded”

The hub limits requests per user. Wait a moment and retry.

### Search returns no results

- Hub 可能尚无与查询语义相近的公开记忆；可换关键词或降低 `min_similarity`。
- 若 Hub 曾更换嵌入模型，旧数据需运维侧 backfill（见下文 maintenance）。

### Workflow search errors or empty similarity (server-side)

- Old rows may have **all-zero** embeddings or **NULL** workflow vectors. The Hub operator should set **`MAINTENANCE_API_KEY`**, check **`/internal/maintenance/embeddings/zero-stats`**, then run **`backfill-zero`** (see table above). **`/health-ui`** (when enabled) shows the same candidate counts.

### Cannot delete or hide a card from the CLI

- Use **`Authorization: Bearer`** with your JWT. Endpoints: **`PATCH .../visibility`** and **`DELETE /memory/{kind}/{id}`** — see the API table.
- **Agent tools** (`delete_evomemory`, `list_my_evomemory`, `restore_evomemory` in `evomemory_sync.tools`): first delete moves to trash (`hidden`); second delete permanently removes.
