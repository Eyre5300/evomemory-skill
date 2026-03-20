"""Offline worker for EvoMemory extraction + upload."""

from __future__ import annotations

import json
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
        return 1
    finally:
        try:
            os.remove(str(temp_file_path))
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())

