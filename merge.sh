#!/usr/bin/env bash

# =========================
# Usage check
# =========================
if [ -z "$1" ]; then
    echo "Usage: ./merge.sh [target_folder]"
    exit 1
fi

TARGET="$1"
OUTPUT="merged_output.txt"

# Convert to absolute path and validate
if ! ROOT="$(cd "$TARGET" 2>/dev/null && pwd)"; then
    echo "Invalid path: $TARGET"
    exit 1
fi

# Move to target directory
cd "$ROOT" || exit 1

# Remove existing output file
if [ -f "$OUTPUT" ]; then
    rm -f "$OUTPUT"
fi

# =========================
# Traverse files
# =========================
find . -type f \( -name "*.c" -o -name "*.h" -o -name "*.md" \) | sort | while IFS= read -r file; do
    rel="${file#./}"

    echo "# $rel" >> "$OUTPUT"
    echo >> "$OUTPUT"
    cat "$file" >> "$OUTPUT"
    echo >> "$OUTPUT"
    echo >> "$OUTPUT"
done

echo "Done. Output: $ROOT/$OUTPUT"