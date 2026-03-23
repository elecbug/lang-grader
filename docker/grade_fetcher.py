# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import os
import logging

from grade_fetcher.github_client import GitHubClient
from grade_fetcher.models import Config
from grade_fetcher.service import FetchService


def build_argparser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Fetch ONLY explicitly listed GitHub files per student."
    )
    ap.add_argument("--map", required=True, help="Path to student map JSON ({limit, students}).")
    ap.add_argument("--suite", required=True, help="Suite name (staged under data/<suite>/).")
    ap.add_argument("--data-root", default="data", help="Root data directory (default: data).")
    ap.add_argument("--respect-limit", action="store_true", help="Respect 'limit' field in map JSON (ISO 8601).")
    ap.add_argument("--log-level", default="WARNING", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return ap


def main() -> None:
    ap = build_argparser()
    args = ap.parse_args()

    logging.basicConfig(level=getattr(logging, args.log_level), format="%(asctime)s [%(levelname)s] %(message)s")

    cfg = Config(
        map_path=args.map,
        suite=args.suite,
        data_root=args.data_root,
        respect_limit=args.respect_limit,
        github_token=(os.environ.get("GITHUB_TOKEN") or "").strip() or None,
    )

    gh = GitHubClient(cfg.github_token)
    svc = FetchService(cfg, gh)

    with open(cfg.map_path, "r", encoding="utf-8") as f:
        map_data = json.load(f)

    svc.run_for_map(map_data)


if __name__ == "__main__":
    main()