#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Parse a pasted table-like text and build a JSON like:

{
  "limit": "2025-09-09T00:00:00Z",
  "students": [
    {
      "id": "5702952",
      "urls": [
        "https://github.com/...",
        "https://github.com/..."
      ]
    }
  ]
}

Key changes from the old version:
- keeps ALL extracted GitHub URLs per student
- supports blob/raw/tree/repo-root style GitHub links
- normalizes full-width URL text like "ＨＴＴＰＳ ://"
- handles inline comments after URLs
"""

import argparse
import json
import re
import sys
import unicodedata
from typing import List, Dict, Optional

# --- Regex helpers -----------------------------------------------------------

SCHEME_FIX_RE = re.compile(r'\b(https?)\s*:\s*//', re.IGNORECASE)

# GitHub URL matcher:
# - blob / raw / tree links
# - repo root links
# - stop before whitespace or obvious trailing delimiters
GITHUB_URL_RE = re.compile(
    r'(https?://(?:www\.)?github\.com/[^\s\]\">\'\u3000]+)',
    re.IGNORECASE
)

ID_RE = re.compile(r'\b\d{6,}\b')


# --- Core functions ----------------------------------------------------------

def normalize_text(s: str) -> str:
    """Normalize full-width ASCII etc. and collapse broken schemes."""
    s = unicodedata.normalize('NFKC', s)
    s = SCHEME_FIX_RE.sub(r'\1://', s)
    return s


def split_rows(raw: str) -> List[str]:
    return [ln.rstrip() for ln in raw.splitlines()]


def harvest_records(lines: List[str]) -> Dict[str, List[str]]:
    """
    Group contiguous lines by student ID, but only start a new record when the line
    looks like a real table row.

    Safer rules:
    1) Prefer TSV-like rows and read the ID from the "아이디" column (or 4th column fallback).
    2) Ignore IDs that appear only inside URLs / file names / comments.
    3) Non-row wrapped lines are appended to the current student's record.
    """
    buckets: Dict[str, List[str]] = {}
    current_id: Optional[str] = None

    header_idx: Optional[int] = None

    def normalize_cell(cell: str) -> str:
        return cell.strip().strip('"').strip("'")

    def find_id_in_tsv_row(ln: str) -> Optional[str]:
        nonlocal header_idx

        # Only trust tabular rows here
        if "\t" not in ln:
            return None

        cols = [normalize_cell(c) for c in ln.split("\t")]

        # Detect header row once
        lowered = [c.replace(" ", "") for c in cols]
        if "아이디" in lowered:
            header_idx = lowered.index("아이디")
            return None

        # Prefer header-derived column
        if header_idx is not None and header_idx < len(cols):
            m = ID_RE.fullmatch(cols[header_idx])
            if m:
                return m.group(0)

        # Fallback: many exports are
        # 연번 / 학과명 / 성명 / 아이디 / ...
        if len(cols) >= 4:
            m = ID_RE.fullmatch(cols[3])
            if m:
                return m.group(0)

        return None

    def find_id_in_plain_row(ln: str) -> Optional[str]:
        """
        Conservative fallback for non-TSV rows:
        only accept an ID if it appears near the beginning of a line that looks
        like a table row, not inside URLs or arbitrary text.
        """
        s = ln.strip()
        if not s:
            return None

        # Skip obvious URL/file-description lines
        lower = s.lower()
        if "github.com/" in lower or "raw.githubusercontent.com/" in lower:
            return None

        # Example accepted shapes:
        # "12 컴퓨터공학과 홍길동 5880642 제출 ..."
        # "12  컴퓨터공학과  홍길동  5880642"
        m = re.match(
            r'^\s*\d+\s+\S+(?:\s+\S+){0,3}\s+(?P<sid>\d{6,})\b',
            s
        )
        if m:
            return m.group("sid")

        return None

    for ln in lines:
        sid = find_id_in_tsv_row(ln)
        if sid is None:
            sid = find_id_in_plain_row(ln)

        if sid is not None:
            if current_id != sid:
                current_id = sid
                buckets.setdefault(current_id, [])
            buckets[current_id].append(ln)
            continue

        # Continuation / wrapped line: append only if we already entered a record
        if current_id is not None:
            buckets[current_id].append(ln)

    return buckets


def extract_submission_flag(record_text: str) -> Optional[bool]:
    if "미제출" in record_text:
        return False
    if "제출" in record_text:
        return True
    return None


def clean_url(url: str) -> str:
    """
    Clean trailing punctuation / inline comments around a URL.
    Preserve valid parentheses inside path names.
    """
    url = url.strip()

    # remove spaces around slashes if broken by paste
    url = re.sub(r'\s+/', '/', url)
    url = re.sub(r'/\s+', '/', url)

    # remove inline " // comment" only if it is separated by whitespace
    url = re.sub(r'\s+//.*$', '', url)

    # remove obvious trailing punctuation, but keep ')' for balanced paths
    while url and url[-1] in ';,\'"』」〉>…':
        url = url[:-1]

    # remove trailing ] or } if obviously unmatched
    while url.endswith(']'):
        if url.count('[') < url.count(']'):
            url = url[:-1]
        else:
            break

    while url.endswith('}'):
        if url.count('{') < url.count('}'):
            url = url[:-1]
        else:
            break

    # remove trailing ')' only when unmatched
    while url.endswith(')'):
        if url.count('(') < url.count(')'):
            url = url[:-1]
        else:
            break

    # same for full-width parenthesis
    while url.endswith('）'):
        if url.count('（') < url.count('）'):
            url = url[:-1]
        else:
            break

    return url


def extract_urls(record_text: str) -> List[str]:
    """
    Extract ALL GitHub URLs in a student block.
    """
    found = GITHUB_URL_RE.findall(record_text)

    cleaned: List[str] = []
    seen = set()

    for url in found:
        u = clean_url(url)
        if u and u not in seen:
            seen.add(u)
            cleaned.append(u)

    return cleaned


def build_map(
    text: str,
    limit: Optional[str],
    only_submitted: bool
) -> Dict:
    norm = normalize_text(text)
    lines = split_rows(norm)
    buckets = harvest_records(lines)

    students: List[Dict[str, object]] = []

    for sid, rec_lines in buckets.items():
        block = "\n".join(rec_lines)

        if only_submitted:
            flag = extract_submission_flag(block)
            if flag is False:
                continue

        urls = extract_urls(block)
        if not urls:
            continue

        students.append({
            "id": sid,
            "urls": urls
        })

    out = {"students": students}
    if limit:
        out["limit"] = limit
    return out


# --- CLI ---------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser(
        description="Build student_map.json from pasted table text."
    )
    p.add_argument("input", nargs="?", default="-",
                   help="Input text file (default: stdin).")
    p.add_argument("-o", "--out", default="student_map.json",
                   help="Output JSON path (default: student_map.json).")
    p.add_argument("--limit", default=None,
                   help="ISO8601 timestamp for grading cutoff, e.g., 2025-09-09T00:00:00Z")
    p.add_argument("--only-submitted", action="store_true",
                   help="Keep only rows that look like '제출'.")
    p.add_argument("--pretty", action="store_true",
                   help="Pretty-print JSON (indent=2).")

    args = p.parse_args()

    if args.input == "-":
        raw = sys.stdin.read()
    else:
        with open(args.input, "r", encoding="utf-8") as f:
            raw = f.read()

    student_map = build_map(
        text=raw,
        limit=args.limit,
        only_submitted=args.only_submitted,
    )

    with open(args.out, "w", encoding="utf-8") as f:
        if args.pretty:
            json.dump(student_map, f, ensure_ascii=False, indent=2)
        else:
            json.dump(student_map, f, ensure_ascii=False)

    print(f"Written: {args.out}  (students: {len(student_map.get('students', []))})")


if __name__ == "__main__":
    main()