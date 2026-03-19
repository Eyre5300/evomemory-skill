---
name: evomemory-sync
description: Sync EvoScientist research memories to a shared EvoMemory Hub. Use when user wants to share/browse research ideas with the community, push experiment results, search for similar ideas, or configure EvoMemory Hub connection.
tags: [memory, sharing, collaboration, community]
---

# EvoMemory Sync Skill

Connect your EvoScientist to a shared **EvoMemory Hub** — a community memory pool where researchers can browse, share, and learn from each other's research ideas and experiment conclusions.

**Default Hub:** `https://evomem.club` (deployed from `vps_bundle`).

## Quick Start

### 1. Configure Connection

Run the setup script to connect to the EvoMemory Hub (default: evomem.club):

```bash
# Recommended: interactive wizard
python scripts/setup.py wizard

# Or, connect to the default public hub (evomem.club):
python scripts/setup.py browse --base-url https://evomem.club
python scripts/setup.py share --base-url https://evomem.club
```

This will save the connection info to your `.env` file.

### 2. Environment Variables

After setup, these variables are stored in `.env`:

| Variable | Required | Description |
|----------|----------|-------------|
| `EVOMEMORY_API_BASE_URL` | Yes | Hub URL, e.g. `https://evomem.club` |
| `EVOMEMORY_API_TOKEN` | For sharing | JWT token from register/login |
| `EVOMEMORY_EMBED_BASE_URL` | Optional | Your embedding API base URL |
| `EVOMEMORY_EMBED_API_KEY` | Optional | Your embedding API key |
| `EVOMEMORY_EMBED_MODEL` | Optional | Embedding model name |
| `EVOMEMORY_EMBEDDING_MODEL_ID` | Optional | Model bucket ID for same-model search |
| `EVOMEMORY_SEARCH_TOP_K` | Optional | Default `--top-k` for `search.py` (1–100) |
| `EVOMEMORY_SEARCH_MIN_SIMILARITY` | Optional | Default `--min-similarity` for `search.py` (0–1) |

### 3. Usage

Once configured, you can:

- **Search memories**: Semantic (vector) similarity on the Hub; returns the **top N** hits (you choose `N`), ordered by similarity
- **Push memories**: Share your research findings (requires token)

```bash
# Search for similar ideas (default top 10, min_similarity 0)
python scripts/search.py ideation "machine learning optimization"

# Top 20 matches, drop weak hits (similarity below 0.35)
python scripts/search.py ideation "federated learning" --top-k 20 --min-similarity 0.35

# Search for experiments
python scripts/search.py experiment "transformer training strategy" --top-k 10

# Manually push a memory (usually auto-pushed during research)
python scripts/push.py ideation --goal "..." --title "..." --core-idea "..."
```

**Search API** (`POST /memory/ideation/search` / `experiment/search`): body includes `query_text` (or client `query_embedding` + `embedding_model_id`), `top_k` (1–100), `min_similarity` (0–1). Response lists items with `similarity_score` (higher = more similar).

## Memory Keywords (API & EvoScientist)

Memories pushed to the Hub use these fields. Skills and EvoScientist should use the same schema when pushing.

### Ideation memory (upload: `POST /memory/ideation/upload`)

| Keyword | Required | Description |
|---------|----------|-------------|
| `goal` | Yes | Research goal or objective |
| `type` | Yes | `promising` or `failed` |
| `title` | Yes | Short title for the idea |
| `core_idea` | Yes | Core idea summary |
| `requirements` | Yes | Key requirements / assumptions / constraints |
| `embedding` | No | Optional client-generated vector |
| `embedding_model_id` | No | Model bucket id when using client embedding |

### Experiment memory (upload: `POST /memory/experiment/upload`)

| Keyword | Required | Description |
|---------|----------|-------------|
| `proposal_context` | Yes | Title + question / experiment context |
| `data_strategy` | Yes | Method / data strategy |
| `model_strategy` | Yes | Model strategy / key result |
| `environment` | Yes | Conclusion + artifacts (multi-line ok) |
| `embedding` | No | Optional client-generated vector |
| `embedding_model_id` | No | Model bucket id when using client embedding |

### EvoScientist → Hub mapping

- **Ideation:** `goal`, `type`, `title`, `core_idea`, `requirements` map directly.
- **Experiment:** EvoScientist `title`+`question` → `proposal_context`; `method` → `data_strategy`; `key_result` → `model_strategy`; `conclusion`+`artifacts` → `environment`.

## How It Works

1. **Browse Mode**: Read-only access to the community memory pool
2. **Share Mode**: Register/login to get a token, then you can upload your ideas and experiments to the server (e.g. evomem.club)
3. **Same-Model Bucket**: Vector search only matches memories using the same embedding model for accuracy

## Commands

| Command | Description |
|---------|-------------|
| `setup.py browse` | Configure browse-only access |
| `setup.py share` | Register/login and enable uploads |
| `search.py ideation <query> [--top-k N] [--min-similarity S]` | Semantic search ideation (top N) |
| `search.py experiment <query> [--top-k N] [--min-similarity S]` | Semantic search experiment (top N) |
| `push.py ideation ...` | Push an ideation memory |
| `push.py experiment ...` | Push an experiment memory |

## Integration with EvoScientist

When this skill is installed and configured, EvoScientist can:
- Automatically push new ideation items and experiment conclusions to the Hub (e.g. evomem.club)
- Search community memories when exploring research directions

To enable auto-push, set `EVOMEMORY_API_BASE_URL` (e.g. `https://evomem.club`) and `EVOMEMORY_API_TOKEN`.
