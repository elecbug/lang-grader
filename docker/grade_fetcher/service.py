# -*- coding: utf-8 -*-
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Optional

from .github_client import GitHubClient
from .models import Config, RepoRef, Status
from .staging import (
    ensure_dir,
    record_failure,
    safe_write,
    write_json_merge,
)
from .url_parser import parse_repo_url


class FetchService:
    """
    New policy:
    - each student has "urls": [...]
    - download ONLY explicitly listed files
    - no repo scan
    - no tree traversal
    - no auto-pick main
    - no guessed .c/.h collection
    """

    def __init__(self, cfg: Config, gh: GitHubClient):
        self.cfg = cfg
        self.gh = gh

    # ----- internals -----

    def _resolve_ref(self, stu_id: str, r: RepoRef, limit_dt: Optional[datetime]) -> Optional[str]:
        branch = r.branch
        if branch is None:
            raise RuntimeError("Explicit file URL must include a branch")

        if limit_dt is not None:
            return self.gh.get_commit_before(r.owner, r.repo, branch, limit_dt)
        return self.gh.get_branch_head(r.owner, r.repo, branch)

    def _validate_explicit_file_ref(self, r: RepoRef) -> None:
        # repo root / tree / empty path 금지
        if not r.branch or not r.path:
            raise ValueError("Only explicit file URLs are allowed")

    def _stage_explicit_file(
        self,
        stu_id: str,
        submitted_url: str,
        r: RepoRef,
        sha: str,
    ) -> bool:
        student_root = os.path.join(self.cfg.suite_dir(), stu_id)
        ensure_dir(student_root)

        # 명시된 path가 실제로 파일인지 한 번 확인
        meta = self.gh.get_contents_meta(r.owner, r.repo, r.path, sha)
        if not meta or meta.get("type") != "file":
            record_failure(
                student_root,
                submitted_url,
                Status.REPRESENTATIVE_FETCH_FAILED,
                f"Explicit path is not a file: {r.path}",
            )
            return False

        try:
            data = self.gh.fetch_raw(r.owner, r.repo, sha, r.path)
        except Exception as e:
            record_failure(
                student_root,
                submitted_url,
                Status.REPRESENTATIVE_FETCH_FAILED,
                f"Failed to fetch explicit file '{r.path}'",
                str(e),
            )
            return False

        # 명시된 파일만 저장. 원래 경로 그대로 보존
        dst = os.path.join(student_root, r.path)
        safe_write(dst, data)

        write_json_merge(
            os.path.join(student_root, ".submission_meta.json"),
            {
                "last_submitted_url": submitted_url,
                "last_saved_path": r.path,
                "policy": "explicit_only",
            },
        )

        print(f"[{stu_id}] saved explicit file: {r.path}")
        return True

    # ----- public -----

    def run_for_map(self, map_data: dict | list) -> None:
        limit_dt: Optional[datetime] = None
        if self.cfg.respect_limit and isinstance(map_data, dict) and "limit" in map_data:
            limit_dt = datetime.fromisoformat(
                map_data["limit"].replace("Z", "+00:00")
            ).astimezone(timezone.utc)
            students = map_data.get("students", [])
        elif isinstance(map_data, list):
            students = map_data
        elif isinstance(map_data, dict) and "students" in map_data:
            students = map_data["students"]
        else:
            raise ValueError("Invalid map JSON format")

        ensure_dir(self.cfg.suite_dir())

        staged_students = 0
        staged_files = 0

        for it in students:
            stu = it.get("id")
            urls = it.get("urls")

            if not stu or not isinstance(urls, list) or not urls:
                continue

            student_root = os.path.join(self.cfg.suite_dir(), stu)
            ensure_dir(student_root)

            student_success = False

            for url in urls:
                try:
                    ref = parse_repo_url(url)
                    self._validate_explicit_file_ref(ref)
                    print(f"[{stu}] Parsed explicit file URL: {ref}")
                except Exception as e:
                    record_failure(
                        student_root,
                        str(url),
                        Status.URL_PARSE_FAILED,
                        "Only explicit GitHub file URLs are allowed",
                        str(e),
                    )
                    continue

                try:
                    sha = self._resolve_ref(stu, ref, limit_dt)
                except Exception as e:
                    record_failure(
                        student_root,
                        str(url),
                        Status.HEAD_LOOKUP_FAILED if ref.branch else Status.DEFAULT_BRANCH_FAILED,
                        "Could not resolve file ref",
                        str(e),
                    )
                    continue

                if limit_dt is not None and not sha:
                    record_failure(
                        student_root,
                        str(url),
                        Status.NO_COMMIT_BEFORE_LIMIT,
                        f"No commit on '{ref.branch}' <= {limit_dt.isoformat()}",
                    )
                    continue

                if limit_dt is not None:
                    print(f"[{stu}] Using commit {sha} (<= {limit_dt.isoformat()})")
                else:
                    print(f"[{stu}] Using branch HEAD {sha}")

                ok = self._stage_explicit_file(stu, str(url), ref, sha)
                if ok:
                    student_success = True
                    staged_files += 1

            if student_success:
                staged_students += 1

        print(
            f"Staged students: {staged_students}, "
            f"Files: {staged_files}, "
            f"Suite: {self.cfg.suite}, Root: {self.cfg.suite_dir()}"
        )