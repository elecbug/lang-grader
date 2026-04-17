# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import logging
import os
from typing import Optional

from .models import Status
from .url_parser import MAIN_RE


# -------- Filesystem helpers --------

TEXT_EXTENSIONS = {
    ".txt", ".md", ".csv", ".json", ".jsonl", ".xml", ".yaml", ".yml",
    ".html", ".htm", ".css", ".js", ".ts", ".jsx", ".tsx",
    ".py", ".java", ".c", ".cc", ".cpp", ".cxx", ".h", ".hpp",
    ".cs", ".go", ".rs", ".php", ".rb", ".kt", ".swift",
    ".sql", ".sh", ".bash", ".zsh", ".ps1",
    ".ini", ".cfg", ".conf", ".toml",
}

BINARY_SIGNATURES = (
    b"\x89PNG\r\n\x1a\n",
    b"\xff\xd8\xff",
    b"GIF87a",
    b"GIF89a",
    b"%PDF-",
    b"PK\x03\x04",
)


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def _looks_binary(data: bytes) -> bool:
    """Heuristic check for binary content."""
    if not data:
        return False

    for sig in BINARY_SIGNATURES:
        if data.startswith(sig):
            return True

    # Null byte is a strong binary indicator
    if b"\x00" in data:
        return True

    # Count suspicious control bytes
    sample = data[:4096]
    bad = 0
    for b in sample:
        if b < 9 or (13 < b < 32):
            bad += 1

    return (bad / max(1, len(sample))) > 0.05


def _is_probably_text_path(path: str) -> bool:
    """Check by file extension whether this is likely a text source."""
    _, ext = os.path.splitext(path.lower())
    return ext in TEXT_EXTENSIONS


def _decode_text_best_effort(data: bytes) -> Optional[str]:
    """
    Try common encodings and return decoded text if successful.
    Prefer UTF-8, then common Korean legacy encodings.
    """
    candidates = (
        "utf-8",
        "utf-8-sig",
        "cp949",
        "euc-kr",
        "latin-1",   # Last-resort salvage for unknown legacy single-byte text
    )

    for enc in candidates:
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue

    return None


def safe_write(path: str, data: bytes) -> None:
    """
    Save file safely.

    Policy:
    - If file looks binary: keep original bytes
    - If file looks like text: try decoding and normalize to UTF-8
    - If decoding fails: keep original bytes
    """
    ensure_dir(os.path.dirname(path))

    should_try_text = _is_probably_text_path(path) and not _looks_binary(data)

    if should_try_text:
        text = _decode_text_best_effort(data)
        if text is not None:
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(text)
            return

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