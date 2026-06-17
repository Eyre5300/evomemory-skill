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
| `EVOMEMORY_RECORD_DOWNLOAD_ON_USE` | No | `true` | When `search_evomemory` returns results, POST `record-download` so web download counts increment |
| `EVOMEMORY_HUB_RESOLVE_CACHE_TTL_SECONDS` | No | `3600` | How long `resolve_working_hub_base_url_cached` keeps a probe result (long-running agents can pick up Hub URL changes without restart) |
| `EVOMEMORY_HUB_RESOLVE_CACHE_MAX_ENTRIES` | No | `32` | Max cached Hub origins (FIFO eviction) |
| `EVOMEMORY_SEARCH_TOP_K` | No | 10 | Default for `scripts/search.py` `--top-k` (1–100) |
| `EVOMEMORY_SEARCH_MIN_SIMILARITY` | No | 0 | Default for `scripts/search.py` `--min-similarity` (0–1) |
| `EVOMEMORY_SYNC_ENABLED` | No | `true` | Set `0`/`false` to disable `EvoMemorySyncMiddleware` |
| `EVOMEMORY_SYNC_SEND_RAW_CONTEXT` | No | `false` | If `true`, skip client-side redaction in middleware (unsafe; debugging only) |
| `EVOMEMORY_WORKER_LOG_FILE` | No | `$HOME/.evomemory/worker.log` (POSIX) or equivalent | Worker process log file; middleware redirects child **stdout/stderr** here by default |
| `EVOMEMORY_WORKER_LOG_LEVEL` | No | `INFO` | Log level for `evomemory_sync.worker` |
| `EVOMEMORY_EXTRACTOR_MODEL` | For auto-upload | - | Chat model id (OpenAI-compatible API) |
| `EVOMEMORY_EXTRACTOR_API_KEY` | For auto-upload | - | API key (or use `SILICONFLOW_API_KEY`) |
| `EVOMEMORY_EXTRACTOR_BASE_URL` | No | `https://api.siliconflow.cn/v1` | Chat Completions base URL |
| `EVOMEMORY_EXTRACTOR_TIMEOUT_SECONDS` | No | falls back to `EVOMEMORY_API_TIMEOUT_SECONDS` | Extractor HTTP timeout |

## Auto-upload middleware (`evomemory_sync`)

When `EvoMemorySyncMiddleware` is registered on the agent and `EVOMEMORY_API_TOKEN` is set, each completed run spawns an offline worker that calls an LLM to produce Hub-shaped JSON, then uploads via **`upload_memory_record`**. Upload path: **agent curator** (default) searches Hub for similar cards, an LLM chooses **create / update / skip** and rewrites the draft; if curator is off or fails, **rule-based semantic dedup** applies (`EVOMEMORY_UPLOAD_SEMANTIC_DEDUP`).

**Post-run routing:** cited Hub experience (`[HUB_REF:uuid]` in the trace) always triggers **`record-download`** (success or failure). **Verify** only when cited and the run **succeeded** (`run_success_flag`: no tool/code errors; self-check/ground-truth passed when applicable). Upload only when: cited + failed (correction, curator prefers update), or not cited + succeeded. Not cited + failed → no upload. The trace written for extraction is **redacted in the parent process** before the temp JSON file is created (unless `EVOMEMORY_SYNC_SEND_RAW_CONTEXT=true`). Worker logs and uncaptured tracebacks go to `EVOMEMORY_WORKER_LOG_FILE` (default under `~/.evomemory/`).

When an agent **uses** Hub memories via `search_evomemory`, the skill calls **`POST /memory/{kind}/{id}/record-download`** for each returned row so the website **download_count** stays in sync (web “下载” button uses the full `GET .../download` endpoint).

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
- **Agent tools** (`delete_evomemory`, `list_my_evomemory`, `restore_evomemory` in `evomemory_sync.tools`): first delete moves to trash (`hidden`); second delete permanently removes.
