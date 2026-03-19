# EvoMemory Sync Skill

Connect your EvoScientist to a shared **EvoMemory Hub** — a community memory pool where researchers can browse, share, and learn from each other's research ideas and experiment conclusions.

## Installation

In EvoScientist, run:

```
/install-skill github.com/Eyre5300/evomemory-skill
```

Or install from local path:

```
/install-skill /path/to/evomemory-skill
```

## Quick Setup

### 1) Choose Mode (no domain shown)

```bash
cd /path/to/evomemory-skill/scripts
python setup.py wizard
```

You will be asked:
- Which mode: **Browse (read-only)** or **Share (upload)**
- Your **Hub URL** (you can paste it when you want; no default is shown)
- Or choose **Public Hub (invite code)** (the maintainer gives you a code; no domain is shown)

### 2) Switch later (Browse → Share)

If you started with Browse, you can enable Share any time later by running:

```bash
python setup.py share
```

This will:
1. Prompt for email and password
2. Automatically register (or login if already registered)
3. Save your token to `.env`

## Usage

### Search Community Memories

```bash
# Semantic search (server ranks by vector similarity; default top 5)
python scripts/search.py ideation "machine learning optimization"

# Return top 20, require similarity >= 0.35
python scripts/search.py experiment "transformer training strategy" --top-k 20 --min-similarity 0.35
```

### Push Your Memories

```bash
# Push an ideation
python scripts/push.py ideation \
  --goal "Improve model efficiency" \
  --title "Sparse attention mechanism" \
  --core-idea "Use sparse patterns to reduce computation"

# Push an experiment
python scripts/push.py experiment \
  --proposal "Test sparse attention on GPT-2" \
  --data-strategy "WikiText-103 dataset" \
  --model-strategy "Replace dense attention with sparse"
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `EVOMEMORY_API_BASE_URL` | Yes | Hub URL (e.g., `https://evomem.club`) |
| `EVOMEMORY_API_TOKEN` | For uploads | JWT token from register/login |
| `EVOMEMORY_EMBED_BASE_URL` | Optional | Your embedding API (e.g., OpenAI) |
| `EVOMEMORY_EMBED_API_KEY` | Optional | Your embedding API key |
| `EVOMEMORY_EMBED_MODEL` | Optional | Model name (e.g., `text-embedding-3-small`) |
| `EVOMEMORY_EMBEDDING_MODEL_ID` | Optional | Model bucket ID for search |

## Client-Side Embedding

For best search accuracy, configure your own embedding API:

```env
EVOMEMORY_EMBED_BASE_URL=https://api.openai.com/v1
EVOMEMORY_EMBED_API_KEY=sk-...
EVOMEMORY_EMBED_MODEL=text-embedding-3-small
EVOMEMORY_EMBEDDING_MODEL_ID=openai-3-small
```

This ensures:
- Memories are encoded with YOUR embedding model
- Search only matches memories from the same model bucket
- Better semantic accuracy

## Hub URL

Default public Hub: **https://evomem.club** (deployed from `vps_bundle`). To connect:

```bash
python setup.py browse --base-url https://evomem.club   # read-only
python setup.py share --base-url https://evomem.club   # register/login to push memories
```

You can also connect to your own private hub or another community hub.

## License

Apache 2.0
