# EvoMemory Configuration Reference

**Default public Hub:** `https://evomem.club` (deployed from `vps_bundle`). Use this URL when connecting to the shared EvoMemory server.

## Connection Setup

### Browse Mode (Read-only)

Run:
```bash
python scripts/setup.py browse --base-url https://evomem.club
# Or: python scripts/setup.py browse --base-url https://<your-hub>
```

This saves to `.env`:
```env
EVOMEMORY_API_BASE_URL=https://evomem.club
```

### Share Mode (Read + Write)

Run:
```bash
python scripts/setup.py share --base-url https://evomem.club
# Or: python scripts/setup.py share --base-url https://<your-hub>
```

This will:
1. Prompt for email and password
2. Try to register; if email exists, login instead
3. Save both URL and token to `.env`:

```env
EVOMEMORY_API_BASE_URL=https://<your-hub>
EVOMEMORY_API_TOKEN=eyJ...
```

### Interactive Wizard (Beginner-friendly)

Run:
```bash
python scripts/setup.py wizard
```

This will ask:
- Browse (read-only) or Share (upload)
- Hub URL (you paste it yourself; no default is shown)
- Or Public Hub (invite code): you paste a code given by the maintainer (no domain is shown)

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `EVOMEMORY_API_BASE_URL` | Yes | - | EvoMemory Hub base URL (e.g. `https://evomem.club`) |
| `EVOMEMORY_API_URL` | No | - | Optional override of base URL for `evomemory_sync.agent_tools` (takes precedence over `EVOMEMORY_API_BASE_URL`) |
| `EVOMEMORY_API_TOKEN` | For write | - | JWT access token |
| `EVOMEMORY_SETUP_EMAIL` | No | - | Used by `scripts/setup.py` share / `install.py` instead of prompting (pair with password; for CI) |
| `EVOMEMORY_SETUP_PASSWORD` | No | - | Used with `EVOMEMORY_SETUP_EMAIL` for non-interactive register/login |
| `EVOMEMORY_AGENT_TOKEN` | No | - | Optional bearer token used only if `EVOMEMORY_API_TOKEN` is unset (e.g. dedicated agent key) |
| `EVOMEMORY_API_TIMEOUT_SECONDS` | No | 30 | Request timeout |
| `EVOMEMORY_SEARCH_TOP_K` | No | 10 | Default for `scripts/search.py` `--top-k` (1–100) |
| `EVOMEMORY_SEARCH_MIN_SIMILARITY` | No | 0 | Default for `scripts/search.py` `--min-similarity` (0–1) |
| `EVOMEMORY_SYNC_ENABLED` | No | `true` | Set `0`/`false` to disable `EvoMemorySyncMiddleware` |
| `EVOMEMORY_EXTRACTOR_MODEL` | For auto-upload | - | Chat model id (OpenAI-compatible API) |
| `EVOMEMORY_EXTRACTOR_API_KEY` | For auto-upload | - | API key (or use `SILICONFLOW_API_KEY`) |
| `EVOMEMORY_EXTRACTOR_BASE_URL` | No | `https://api.siliconflow.cn/v1` | Chat Completions base URL |
| `EVOMEMORY_EXTRACTOR_TIMEOUT_SECONDS` | No | falls back to `EVOMEMORY_API_TIMEOUT_SECONDS` | Extractor HTTP timeout |

## Auto-upload middleware (`evomemory_sync`)

When `EvoMemorySyncMiddleware` is registered on the agent and `EVOMEMORY_API_TOKEN` is set, each completed run triggers an LLM call to produce Hub-shaped JSON, then `POST` to `/memory/ideation/upload` or `/memory/experiment/upload`. No local JSON files are written.

## Semantic search (`search.py`)

Hub 使用 pgvector 按**相似度**排序，返回最相近的前 `top_k` 条（最大 100），可用 `min_similarity` 过滤弱相关结果。Skill 与 CLI 只发送 `query_text`，**向量化在 Hub 端完成**（与 Web 检索一致）。

## Memory Keywords (Hub API)

- **Ideation:** `goal`, `type` (promising/failed), `title`, `core_idea`, `requirements`（Hub 可接受可选 `embedding` / `embedding_model_id`，skill 不再发送）。
- **Experiment:** `proposal_context`, `data_strategy`, `model_strategy`, `environment`（同上）。

## API Endpoints

The EvoMemory Hub (e.g. evomem.club) exposes:

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/health` | GET | No | Health check (JSON) |
| `/health-ui` | GET | No | HTML debug page when **`ENABLE_HEALTH_UI=true`** (logs + DB/embedding status + **counts of rows needing embedding backfill**: zero-vector ideation/experiment, zero or NULL workflow) |
| `/auth/register` | POST | No | Register new user |
| `/auth/login` | POST | No | Login, get token |
| `/memory/ideation/upload` | POST | Yes | Upload ideation memory |
| `/memory/experiment/upload` | POST | Yes | Upload experiment memory |
| `/memory/workflow/upload` | POST | Yes | Upload workflow memory |
| `/memory/ideation/search` | POST | No | Search ideation memories |
| `/memory/experiment/search` | POST | No | Search experiment memories |
| `/memory/workflow/search` | POST | No | Search workflow memories |
| `/memory/me/ideation` | GET | Yes | Current user’s ideation list (includes `visibility`) |
| `/memory/me/experiment` | GET | Yes | Current user’s experiment list (includes `visibility`) |
| `/memory/me/workflow` | GET | Yes | Current user’s workflow list (includes `visibility`) |
| `/memory/{kind}/{memory_id}/visibility` | PATCH | Yes | `kind` is `ideation`, `experiment`, or `workflow`. Body: `{"visibility":"public"}` or `"hidden"` (owner only) |
| `/memory/{kind}/{memory_id}` | DELETE | Yes | Delete memory (owner only) |
| `/memory/report` | POST | Yes | Report inappropriate content |

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

## Troubleshooting

### "EVOMEMORY_API_BASE_URL not set"

Run setup first (e.g. connect to evomem.club):
```bash
python scripts/setup.py browse --base-url https://evomem.club
```

### "401 missing bearer token" on upload

You need to login (e.g. for evomem.club):
```bash
python scripts/setup.py share --base-url https://evomem.club
```

### "429 rate limit exceeded"

The hub limits requests per user. Wait a moment and retry.

### Search returns no results

- Hub 可能尚无与查询语义相近的公开记忆；可换关键词或降低 `min_similarity`。
- 若 Hub 曾更换嵌入模型，旧数据需运维侧 backfill（见下文 maintenance）。

### Workflow search errors or empty similarity (server-side)

- Old rows may have **all-zero** embeddings or **NULL** workflow vectors. The Hub operator should set **`MAINTENANCE_API_KEY`**, check **`/internal/maintenance/embeddings/zero-stats`**, then run **`backfill-zero`** (see table above). **`/health-ui`** (when enabled) shows the same candidate counts.

### Cannot delete or hide a card from the CLI

- Use **`Authorization: Bearer`** with your JWT. Endpoints: **`PATCH .../visibility`** and **`DELETE /memory/{kind}/{id}`** — see the API table.
