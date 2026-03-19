---
name: evomemory-sync
description: Sync EvoScientist research memories to a shared EvoMemory Hub. Use when user wants to share/browse research ideas with the community, push experiment results, search for similar ideas, or configure EvoMemory Hub connection.
tags: [memory, sharing, collaboration, community]
---

# EvoMemory Sync Skill

Connect your EvoScientist to a shared **EvoMemory Hub** — a community memory pool where researchers can browse, share, and learn from each other's research ideas and experiment conclusions.

## Quick Start

### 1. Configure Connection

Run the setup script to connect to an EvoMemory Hub:

```bash
# Recommended: interactive wizard (no default hub shown)
python scripts/setup.py wizard

# Or, non-interactive:
python scripts/setup.py browse --base-url https://<your-hub>
python scripts/setup.py share --base-url https://<your-hub>
```

This will save the connection info to your `.env` file.

### 2. Environment Variables

After setup, these variables are stored in `.env`:

| Variable | Required | Description |
|----------|----------|-------------|
| `EVOMEMORY_API_BASE_URL` | Yes | Hub URL, e.g. `https://your-hub-domain` |
| `EVOMEMORY_API_TOKEN` | For sharing | JWT token from register/login |
| `EVOMEMORY_EMBED_BASE_URL` | Optional | Your embedding API base URL |
| `EVOMEMORY_EMBED_API_KEY` | Optional | Your embedding API key |
| `EVOMEMORY_EMBED_MODEL` | Optional | Embedding model name |
| `EVOMEMORY_EMBEDDING_MODEL_ID` | Optional | Model bucket ID for same-model search |

### 3. Usage

Once configured, you can:

- **Search memories**: Find similar ideas/experiments from the community
- **Push memories**: Share your research findings (requires token)

```bash
# Search for similar ideas
python scripts/search.py ideation "machine learning optimization"

# Search for experiments
python scripts/search.py experiment "transformer training strategy"

# Manually push a memory (usually auto-pushed during research)
python scripts/push.py ideation --goal "..." --title "..." --core-idea "..."
```

## How It Works

1. **Browse Mode**: Read-only access to the community memory pool
2. **Share Mode**: Register/login to get a token, then you can upload your ideas and experiments
3. **Same-Model Bucket**: Vector search only matches memories using the same embedding model for accuracy

## Commands

| Command | Description |
|---------|-------------|
| `setup.py browse` | Configure browse-only access |
| `setup.py share` | Register/login and enable uploads |
| `search.py ideation <query>` | Search ideation memories |
| `search.py experiment <query>` | Search experiment memories |
| `push.py ideation ...` | Push an ideation memory |
| `push.py experiment ...` | Push an experiment memory |

## Integration with EvoScientist

When this skill is installed and configured, EvoScientist can:
- Automatically push new ideation items and experiment conclusions to the Hub
- Search community memories when exploring research directions

To enable auto-push, ensure `EVOMEMORY_API_BASE_URL` and `EVOMEMORY_API_TOKEN` are set.
