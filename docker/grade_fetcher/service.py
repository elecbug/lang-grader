# -*- coding: utf-8 -*-
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Optional

from .github_client import GitHubClient
from .models import Config, RepoRef, Status
from .staging import ensure_dir, record_failure, safe_write, write_json_merge
from .url_parser import parse_repo_url


class FetchService:
    """
    Policy:
    - blob/raw file URL  -> fetch only that file
    - tree directory URL -> fetch every file under that directory
    - repo root URL      -> forbidden
    - no guessed files outside explicitly submitted paths
    """

    def __init__(self, cfg: Config, gh: GitHubClient):
        self.cfg = cfg
        self.gh = gh

    def _resolve_ref(self, stu_id: str, r: RepoRef, limit_dt: Optional[datetime]) -> Optional[str]:
        branch = r.branch

        # root URL이면 default branch 가져오기
        if branch is None:
            branch = self.gh.get_default_branch(r.owner, r.repo)

        if limit_dt is not None:
            return self.gh.get_commit_before(r.owner, r.repo, branch, limit_dt)
        return self.gh.get_branch_head(r.owner, r.repo, branch)

    def _validate_ref(self, r: RepoRef) -> None:
        # # repo root 금지
        # if r.branch is None:
        #     raise ValueError("Repository root URL is not allowed")
        return

    def _stage_explicit_path(
        self,
        stu_id: str,
        submitted_url: str,
        r: RepoRef,
        sha: str,
    ) -> int:
        """
        Returns number of saved files.

        Policy:
        - file URL      -> save only that file
        - directory URL -> save every file under that directory
        - repo root URL -> save every file in the repository
        """
        student_root = os.path.join(self.cfg.suite_dir(), stu_id)
        ensure_dir(student_root)

        # [수정됨] 덮어쓰기 방지를 위해 저장소 소유자(owner)와 이름(repo)으로 폴더를 분리합니다.
        repo_base_dir = os.path.join(student_root, r.owner, r.repo)
        ensure_dir(repo_base_dir)

        saved_count = 0

        # 0) repo root: copy whole repository
        if not r.path:
            try:
                tree = self.gh.list_tree(r.owner, r.repo, sha)
            except Exception as e:
                # [수정됨] 에러 로그도 분리된 폴더에 저장합니다.
                record_failure(
                    repo_base_dir,
                    submitted_url,
                    Status.TREE_LIST_FAILED,
                    "Failed to enumerate full repository tree",
                    str(e),
                )
                return 0

            targets: list[str] = []
            for ent in tree:
                if ent.get("type") != "blob":
                    continue
                p = ent.get("path", "")
                if p:
                    targets.append(p)

            if not targets:
                record_failure(
                    repo_base_dir,
                    submitted_url,
                    Status.NO_SOURCES_FOUND,
                    "No files found in repository",
                )
                return 0

            for p in targets:
                try:
                    data = self.gh.fetch_raw(r.owner, r.repo, sha, p)
                    # [수정됨] student_root 대신 repo_base_dir를 베이스로 사용합니다.
                    dst = os.path.join(repo_base_dir, p)
                    safe_write(dst, data)
                    saved_count += 1
                except Exception as e:
                    print(f"[{stu_id}] fetch failed for {p}: {e}")

            write_json_merge(
                os.path.join(repo_base_dir, ".submission_meta.json"),
                {
                    "submitted_url": submitted_url,
                    "submitted_kind": "repo_root",
                    "saved_count": saved_count,
                    "policy": "explicit_file_dir_or_repo",
                },
            )
            print(f"[{stu_id}] saved full repository ({saved_count} files)")
            return saved_count

        # 1) explicit file / directory
        meta = self.gh.get_contents_meta(r.owner, r.repo, r.path, sha)
        if not meta:
            record_failure(
                repo_base_dir,
                submitted_url,
                Status.REPRESENTATIVE_FETCH_FAILED,
                f"Path not found at ref: {r.path}",
            )
            return 0

        # 1-a) explicit file
        if meta["type"] == "file":
            try:
                data = self.gh.fetch_raw(r.owner, r.repo, sha, r.path)
                # [수정됨] 개별 파일 다운로드 시에도 폴더 구조를 유지합니다.
                dst = os.path.join(repo_base_dir, r.path)
                safe_write(dst, data)
                saved_count = 1

                write_json_merge(
                    os.path.join(repo_base_dir, ".submission_meta.json"),
                    {
                        "submitted_url": submitted_url,
                        "submitted_kind": "file",
                        "submitted_path": r.path,
                        "saved_count": saved_count,
                        "policy": "explicit_file_dir_or_repo",
                    },
                )
                print(f"[{stu_id}] saved explicit file: {r.path}")
                return saved_count
            except Exception as e:
                record_failure(
                    repo_base_dir,
                    submitted_url,
                    Status.REPRESENTATIVE_FETCH_FAILED,
                    f"Failed to fetch file: {r.path}",
                    str(e),
                )
                return 0

        # 1-b) explicit directory
        if meta["type"] == "dir":
            dir_prefix = r.path.strip("/")

            try:
                tree = self.gh.list_tree(r.owner, r.repo, sha)
            except Exception as e:
                record_failure(
                    repo_base_dir,
                    submitted_url,
                    Status.TREE_LIST_FAILED,
                    f"Failed to enumerate tree for directory: {dir_prefix}",
                    str(e),
                )
                return 0

            targets: list[str] = []
            for ent in tree:
                if ent.get("type") != "blob":
                    continue
                p = ent.get("path", "")
                if p == dir_prefix or p.startswith(dir_prefix + "/"):
                    targets.append(p)

            if not targets:
                record_failure(
                    repo_base_dir,
                    submitted_url,
                    Status.NO_SOURCES_FOUND,
                    f"No files found under directory: {dir_prefix}",
                )
                return 0

            for p in targets:
                try:
                    data = self.gh.fetch_raw(r.owner, r.repo, sha, p)
                    # [수정됨] 디렉터리 내 파일들도 동일하게 처리합니다.
                    dst = os.path.join(repo_base_dir, p)
                    safe_write(dst, data)
                    saved_count += 1
                except Exception as e:
                    print(f"[{stu_id}] fetch failed for {p}: {e}")

            write_json_merge(
                os.path.join(repo_base_dir, ".submission_meta.json"),
                {
                    "submitted_url": submitted_url,
                    "submitted_kind": "dir",
                    "submitted_path": dir_prefix,
                    "saved_count": saved_count,
                    "policy": "explicit_file_dir_or_repo",
                },
            )
            print(f"[{stu_id}] saved explicit directory: {dir_prefix} ({saved_count} files)")
            return saved_count

        record_failure(
            repo_base_dir,
            submitted_url,
            Status.REPRESENTATIVE_FETCH_FAILED,
            f"Unsupported path type: {meta.get('type')}",
        )
        return 0

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

            student_ok = False

            for url in urls:
                try:
                    ref = parse_repo_url(url)
                    self._validate_ref(ref)
                    print(f"[{stu}] Parsed repo URL: {ref}")
                except Exception as e:
                    record_failure(
                        student_root,
                        str(url),
                        Status.URL_PARSE_FAILED,
                        "Unrecognized or unsupported GitHub URL",
                        str(e),
                    )
                    continue
                
                # [수정됨] run_for_map 레벨에서도 실패 기록이 겹치지 않게 분기된 폴더를 준비합니다.
                repo_base_dir = os.path.join(student_root, ref.owner, ref.repo)
                ensure_dir(repo_base_dir)

                try:
                    sha = self._resolve_ref(stu, ref, limit_dt)
                except Exception as e:
                    record_failure(
                        repo_base_dir,
                        str(url),
                        Status.HEAD_LOOKUP_FAILED,
                        "Could not resolve branch HEAD",
                        str(e),
                    )
                    continue

                if limit_dt is not None and not sha:
                    record_failure(
                        repo_base_dir,
                        str(url),
                        Status.NO_COMMIT_BEFORE_LIMIT,
                        f"No commit on '{ref.branch}' <= {limit_dt.isoformat()}",
                    )
                    continue

                if limit_dt is not None:
                    print(f"[{stu}] Using commit {sha} (<= {limit_dt.isoformat()})")
                else:
                    print(f"[{stu}] Using branch HEAD {sha}")

                count = self._stage_explicit_path(stu, str(url), ref, sha)
                if count > 0:
                    student_ok = True
                    staged_files += count

            if student_ok:
                staged_students += 1

        print(
            f"Staged students: {staged_students}, "
            f"Files: {staged_files}, "
            f"Suite: {self.cfg.suite}, Root: {self.cfg.suite_dir()}"
        )