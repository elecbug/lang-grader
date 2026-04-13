#!/usr/bin/env bash

# =========================
# Usage check
# =========================
if [ -z "$1" ]; then
    echo "Usage: ./all_merge.sh [root_folder]"
    exit 1
fi

ROOT="$1"

# Validate root path
if ! ROOT_ABS="$(cd "$ROOT" 2>/dev/null && pwd)"; then
    echo "Invalid path: $ROOT"
    exit 1
fi

# Path to merge script (assumed same directory as this script)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MERGE_SCRIPT="$SCRIPT_DIR/merge.sh"

# Check merge script existence
if [ ! -f "$MERGE_SCRIPT" ]; then
    echo "merge.sh not found in $SCRIPT_DIR"
    exit 1
fi

# =========================
# Traverse directories
# =========================
find "$ROOT_ABS" -type d | while IFS= read -r dir; do

    echo "Processing: $dir"

    # Execute merge script for each directory
    "$MERGE_SCRIPT" "$dir"

done

echo "All done."