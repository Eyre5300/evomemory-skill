"""Offline worker for EvoMemory extraction + upload."""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass

from .extractor import _call_llm_to_extract_json
from .uploader import upload_memory_record

logger = logging.getLogger("evomemory_sync.worker")


def _setup_logging() -> None:
    level_name = os.getenv("EVOMEMORY_WORKER_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    log_file = os.getenv("EVOMEMORY_WORKER_LOG_FILE", "").strip()
    kwargs = {
        "level": level,
        "format": "%(asctime)s %(levelname)s %(name)s: %(message)s",
    }
    if log_file:
        kwargs["filename"] = log_file
        kwargs["filemode"] = "a"
    logging.basicConfig(**kwargs)


_setup_logging()


def main() -> int:
    if len(sys.argv) != 2:
        return 2

    temp_file_path = Path(sys.argv[1]).expanduser().resolve()
    try:
        raw = temp_file_path.read_text(encoding="utf-8")
        ctx = json.loads(raw)
        if not isinstance(ctx, dict):
            return 1

        record = _call_llm_to_extract_json(ctx)
        if not record or not isinstance(record, dict):
            return 0
        if record.get("skip") is True:
            return 0

        upload_memory_record(record)
        return 0
    except Exception:
        logger.exception("offline worker failed")
        return 1
    finally:
        try:
            os.remove(str(temp_file_path))
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())

