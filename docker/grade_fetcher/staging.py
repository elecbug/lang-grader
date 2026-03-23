# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import logging
import os
from typing import Iterable, List, Optional

from .models import Status
from .url_parser import MAIN_RE


# -------- Filesystem helpers --------

def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def safe_write(path: str, data: bytes) -> None:
    ensure_dir(os.path.dirname(path))
    with open(path, "wb") as f:
        f.write(data)


def write_json_merge(path: str, patch: dict) -> None:
    """Merge/append JSON (best effort)."""
    ensure_dir(os.path.dirname(path))
    try:
        current = {}
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                current = json.load(f)
        current.update(patch)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(current, f, ensure_ascii=False, indent=2)
    except Exception:
        # Do not break pipeline on meta write failure
        logging.exception("meta write failed (non-fatal)")


def record_failure(student_root: str, submitted_url: str, status: Status, reason: str, detail: Optional[str] = None) -> None:
    payload = {
        "submitted_url": submitted_url,
        "status": status.value,
        "failure_reason": reason,
    }
    if detail:
        payload["detail"] = str(detail)[:500]
    write_json_merge(os.path.join(student_root, ".submission_meta.json"), payload)
    print(f"[{os.path.basename(student_root)}] ERROR {status.value}: {reason}")  # Preserve legacy console style