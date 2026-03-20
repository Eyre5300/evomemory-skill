# EvoMemory Sync Skill

Shared **EvoMemory Hub** integration for EvoScientist-style workflows: **automatic post-run sync** via a LangChain `AgentMiddleware`, plus lightweight **CLI** setup and search.

## What’s in the box

| Part | Role |
|------|------|
| `evomemory_sync/` | Installable package: `EvoMemorySyncMiddleware`, LLM extractor, Hub uploader |
| `scripts/setup.py` | Configure `EVOMEMORY_API_BASE_URL` and optional JWT |
| `scripts/search.py` | Semantic search against the Hub |

## Installation

### As an EvoScientist skill (documentation + scripts)

```
/install-skill github.com/Eyre5300/evomemory-skill
```

### As a Python package (required for middleware)

From this repo root:

```bash
pip install -e .
```

Use the **same Python environment** as EvoScientist so `import evomemory_sync` works.

## Setup

```bash
cd scripts
python setup.py wizard
```

Browse-only or share (register/login). Credentials go to `.env`.

## Auto-upload middleware

Set at minimum:

```env
EVOMEMORY_API_BASE_URL=https://evomem.club
EVOMEMORY_API_TOKEN=eyJ...
EVOMEMORY_EXTRACTOR_MODEL=Qwen/Qwen2.5-7B-Instruct
EVOMEMORY_EXTRACTOR_API_KEY=sk-...
# Optional: OpenAI-compatible base (default is SiliconFlow)
# EVOMEMORY_EXTRACTOR_BASE_URL=https://api.siliconflow.cn/v1
```

Disable without uninstalling:

```env
EVOMEMORY_SYNC_ENABLED=false
```

### Wiring into EvoScientist

`create_cli_agent` does **not** take `middleware=`. Add `EvoMemorySyncMiddleware()` to the **`mw` list** before `load_mcp_and_build_kwargs(be, mw)`, same as built-in middleware. See **SKILL.md** for a full snippet.

## Search

```bash
python scripts/search.py ideation "machine learning optimization"
python scripts/search.py experiment "transformer training" --top-k 20 --min-similarity 0.35
```

## Environment variables

See `references/CONFIG.md` for Hub, embedding, search, extractor, and sync toggles.

## License

Apache 2.0
