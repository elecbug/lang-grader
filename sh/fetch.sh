#!/usr/bin/env bash
set -euo pipefail

# ============================================================
# Usage examples:
#   ./run.sh hw-test
#   ./run.sh data/hw-test
#   GITHUB_TOKEN=ghp_xxx ./run.sh hw-test
# ============================================================

IMAGE_NAME=$(cat $(pwd)/sh/name/IMAGE_NAME)

ROOT_DIR="$(pwd)"
WORK_DIR="${ROOT_DIR}/docker"

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <suite-folder or data/suite-folder>"
  exit 1
fi

ARG_SUITE="$1"

# Normalize suite
CLEAN_SUITE="${ARG_SUITE#data/}"
CLEAN_SUITE="${CLEAN_SUITE#./}"
SUITE_NAME="$(basename "$CLEAN_SUITE")"
SUITE_DIR="${ROOT_DIR}/${CLEAN_SUITE}"

TESTS_NAME=$(cat $(pwd)/sh/name/TESTS_NAME)
STUDENT_MAP_NAME=$(cat $(pwd)/sh/name/STUDENT_MAP_NAME)

TESTS_PATH="${SUITE_DIR}/${TESTS_NAME}"
MAP_JSON="${SUITE_DIR}/${STUDENT_MAP_NAME}"

# Checks
[[ -d "${SUITE_DIR}" ]] || { echo "Suite directory not found: ${SUITE_DIR}"; exit 1; }
[[ -f "${MAP_JSON}"  ]] || { echo "Mapping JSON not found: ${MAP_JSON}"; exit 1; }
sudo docker image inspect "${IMAGE_NAME}" >/dev/null 2>&1 || { echo "Build image first: ./build.sh"; exit 1; }

# 1) Fetch & stage (dir-scope; preserve subdirs; respect limit)
echo "========================================"
echo "Fetching sources using ${MAP_JSON} into ${SUITE_NAME}"
python3 "${WORK_DIR}/grade_fetcher.py" \
  --map "${MAP_JSON}" \
  --suite "raw" \
  --data-root "${SUITE_DIR}" \
  --respect-limit || { echo "Fetch step failed."; exit 1; }