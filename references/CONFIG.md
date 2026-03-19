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
| `EVOMEMORY_API_TOKEN` | For write | - | JWT access token |
| `EVOMEMORY_API_TIMEOUT_SECONDS` | No | 30 | Request timeout |
| `EVOMEMORY_EMBED_BASE_URL` | No | - | Embedding API base URL |
| `EVOMEMORY_EMBED_API_KEY` | No | - | Embedding API key |
| `EVOMEMORY_EMBED_MODEL` | No | - | Embedding model name |
| `EVOMEMORY_EMBEDDING_MODEL_ID` | No | Same as model | Model bucket identifier |
| `EVOMEMORY_SEARCH_TOP_K` | No | 10 | Default for `scripts/search.py` `--top-k` (1–100) |
| `EVOMEMORY_SEARCH_MIN_SIMILARITY` | No | 0 | Default for `scripts/search.py` `--min-similarity` (0–1) |

## Semantic search (`search.py`)

Hub 使用 pgvector 按**相似度**排序，返回最相近的前 `top_k` 条（最大 100），可用 `min_similarity` 过滤弱相关结果。未配置客户端 embedding 时由服务端对 `query_text` 做向量化；配置了 `EVOMEMORY_EMBED_*` 时由客户端生成 `query_embedding` 并需指定 `embedding_model_id`（与上传时同桶）。

## Client-Side Embedding

### Why?

Different embedding models produce incompatible vectors. To ensure accurate similarity search, EvoMemory uses "same-model buckets":

- When you push, your `embedding_model_id` is stored with the memory
- When you search, only memories with matching `embedding_model_id` are compared

### Configuration Examples

**OpenAI:**
```env
EVOMEMORY_EMBED_BASE_URL=https://api.openai.com/v1
EVOMEMORY_EMBED_API_KEY=sk-...
EVOMEMORY_EMBED_MODEL=text-embedding-3-small
EVOMEMORY_EMBEDDING_MODEL_ID=openai-3-small
```

**Zhipu (智谱):**
```env
EVOMEMORY_EMBED_BASE_URL=https://open.bigmodel.cn/api/paas/v4
EVOMEMORY_EMBED_API_KEY=your-api-key
EVOMEMORY_EMBED_MODEL=embedding-2
EVOMEMORY_EMBEDDING_MODEL_ID=zhipu-embedding-2
```

**DeepSeek:**
```env
EVOMEMORY_EMBED_BASE_URL=https://api.deepseek.com/v1
EVOMEMORY_EMBED_API_KEY=sk-...
EVOMEMORY_EMBED_MODEL=deepseek-embedding
EVOMEMORY_EMBEDDING_MODEL_ID=deepseek-embed
```

**Local/Self-hosted (vLLM, ollama, etc.):**
```env
EVOMEMORY_EMBED_BASE_URL=http://localhost:8080/v1
EVOMEMORY_EMBED_API_KEY=dummy
EVOMEMORY_EMBED_MODEL=bge-large-zh
EVOMEMORY_EMBEDDING_MODEL_ID=bge-large-zh-local
```

## Memory Keywords (Hub API)

- **Ideation:** `goal`, `type` (promising/failed), `title`, `core_idea`, `requirements`; optional `embedding`, `embedding_model_id`.
- **Experiment:** `proposal_context`, `data_strategy`, `model_strategy`, `environment`; optional `embedding`, `embedding_model_id`.

## API Endpoints

The EvoMemory Hub (e.g. evomem.club) exposes:

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/health` | GET | No | Health check |
| `/auth/register` | POST | No | Register new user |
| `/auth/login` | POST | No | Login, get token |
| `/memory/ideation/upload` | POST | Yes | Upload ideation memory |
| `/memory/experiment/upload` | POST | Yes | Upload experiment memory |
| `/memory/ideation/search` | POST | No | Search ideation memories |
| `/memory/experiment/search` | POST | No | Search experiment memories |
| `/memory/report` | POST | Yes | Report inappropriate content |

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

- Check if `embedding_model_id` matches existing memories
- Try without client-side embedding (server will use its own)
- The hub might be empty for your model bucket
