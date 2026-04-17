"""Offline worker for EvoMemory extraction + upload."""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

import hashlib

from .env_loader import load_env

from .extraction_fields import normalize_llm_extraction
from .extractor import _call_llm_to_extract_json
from .upload_dedup import fingerprint_context, mark_upload_succeeded, should_skip_duplicate
from .uploader import upload_memory_record

logger = logging.getLogger("evomemory_sync.worker")


def _default_worker_log_path() -> Path:
    custom = os.getenv("EVOMEMORY_WORKER_LOG_FILE", "").strip()
    if custom:
        return Path(custom).expanduser()
    return Path.home() / ".evomemory" / "worker.log"


def _setup_logging() -> None:
    level_name = os.getenv("EVOMEMORY_WORKER_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    log_path = _default_worker_log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        filename=str(log_path),
        filemode="a",
    )


def main() -> int:
    if len(sys.argv) != 2:
        return 2

    temp_file_path = Path(sys.argv[1]).expanduser().resolve()
    try:
        load_env()
        raw = temp_file_path.read_text(encoding="utf-8")
        ctx_hash = hashlib.sha256(raw.encode("utf-8", errors="ignore")).hexdigest()[:12]
        logger.info("offline worker start tmp=%s ctx_hash=%s", temp_file_path.name, ctx_hash)
        ctx = json.loads(raw)
        if not isinstance(ctx, dict):
            return 1

        fp = fingerprint_context(ctx)
        if should_skip_duplicate(fp):
            logger.info(
                "offline worker dedup_skip tmp=%s fp=%s… (same context uploaded recently)",
                temp_file_path.name,
                fp[:16],
            )
            return 0

        record = _call_llm_to_extract_json(ctx)
        if not record or not isinstance(record, dict):
            return 0
        record = normalize_llm_extraction(record)
        if record.get("skip") is True:
            logger.info("offline worker skip ctx_hash=%s", ctx_hash)
            return 0

        mem_type = str(record.get("memory_type") or record.get("memory_kind") or record.get("type") or "")
        logger.info("offline worker upload ctx_hash=%s memory_type=%s", ctx_hash, mem_type)
        # Retry up to 3 times for transient failures
        last_err = None
        for attempt in range(1, 4):
            try:
                upload_memory_record(record)
                mark_upload_succeeded(fp)
                logger.info("offline worker done ctx_hash=%s", ctx_hash)
                return 0
            except Exception as upload_err:
                last_err = upload_err
                if attempt < 3:
                    import time as _time
                    logger.warning("offline worker upload attempt %d failed: %s, retrying in %ds…", attempt, upload_err, attempt * 2)
                    _time.sleep(attempt * 2)
        logger.error("offline worker upload failed after 3 attempts: %s", last_err)
        return 1
    except Exception:
        logger.exception("offline worker failed")
        return 1
    finally:
        try:
            os.remove(str(temp_file_path))
        except Exception:
            pass


if __name__ == "__main__":
    _setup_logging()
    raise SystemExit(main())

