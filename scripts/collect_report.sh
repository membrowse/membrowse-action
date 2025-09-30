#!/bin/bash

# collect_report.sh - Collects memory usage data and generates report for MemBrowse
# This script orchestrates the entire memory analysis process:
# 1. Calls memory_report.py to generate JSON report from ELF and linker scripts
# 2. Enriches with git metadata
# 3. Uploads to MemBrowse API

set -euo pipefail

# Script arguments
ELF_PATH="${1:-}"
LD_SCRIPTS="${2:-}"
TARGET_NAME="${3:-}"
API_KEY="${4:-}"
COMMIT_SHA="${5:-}"
BASE_SHA="${6:-}"
BRANCH_NAME="${7:-}"
REPO_NAME="${8:-}"
PR_NUMBER="${9:-}"
CURRENT_COMMIT_NUM="${10:-}"
TOTAL_COMMITS="${11:-}"

MEMBROWSE_API_URL="${MEMBROWSE_UPLOAD_URL:-}"

# Validate required arguments
if [[ -z "$ELF_PATH" ]]; then
    echo "Error: ELF file path is required"
    exit 1
fi

if [[ -z "$LD_SCRIPTS" ]]; then
    echo "Error: Linker script paths are required"
    exit 1
fi

if [[ -z "$TARGET_NAME" ]]; then
    echo "Error: Target name is required"
    exit 1
fi

if [[ ! -f "$ELF_PATH" ]]; then
    echo "Error: ELF file not found: $ELF_PATH"
    exit 1
fi

# Validate linker scripts exist
for ld_script in $LD_SCRIPTS; do
    if [[ ! -f "$ld_script" ]]; then
        echo "Error: Linker script not found: $ld_script"
        exit 1
    fi
done

if [[ -n "$CURRENT_COMMIT_NUM" && -n "$TOTAL_COMMITS" ]]; then
    echo "($COMMIT_SHA): Started MemBrowse Memory Report generation (commit $CURRENT_COMMIT_NUM of $TOTAL_COMMITS)"
else
    echo "($COMMIT_SHA): Started MemBrowse Memory Report generation"
fi
echo "Target: $TARGET_NAME"
echo "ELF file: $ELF_PATH"
echo "Linker scripts: $LD_SCRIPTS"

echo "($COMMIT_SHA): ELF analysis."

# Log membrowse version for debugging
echo "=== MEMBROWSE VERSION INFO ==="
python3 -c "import membrowse; print(f'Package location: {membrowse.__file__}'); import sys; sys.path.insert(0, '.'); from setup import setup; print('Version from setup.py check')" 2>/dev/null || true
pip show membrowse 2>/dev/null || echo "pip show failed"
echo "=============================="

# Parse memory regions from linker scripts
echo "($COMMIT_SHA): Parsing memory regions from linker scripts."
MEMORY_REGIONS_JSON=$(mktemp)

python3 -m membrowse.linker.cli $LD_SCRIPTS > "$MEMORY_REGIONS_JSON" || {
    echo "($COMMIT_SHA): Error: Failed to parse memory regions"
    exit 1
}

# Generate JSON report using Python script
echo "($COMMIT_SHA): Generating JSON memory report..."
REPORT_JSON=$(mktemp)

python3 -m membrowse.core.cli \
    --elf-path "$ELF_PATH" \
    --memory-regions "$MEMORY_REGIONS_JSON" \
    --output "$REPORT_JSON" || {
    echo "($COMMIT_SHA): Error: Failed to generate memory report"
    exit 1
}

echo "($COMMIT_SHA): JSON report generated successfully"

# Debug: Check usb_device mapping
echo "=== DEBUG: usb_device SYMBOL MAPPING ==="
grep -A5 '"name": "usb_device"' "$REPORT_JSON" | grep "source_file" || echo "usb_device not found in report"
echo "========================================="

if [[ -z "$COMMIT_SHA" ]]; then
    COMMIT_SHA=$(git rev-parse HEAD)
fi

if [[ -z "$BRANCH_NAME" ]]; then
    BRANCH_NAME=$(git rev-parse --abbrev-ref HEAD)
fi

if [[ -z "$REPO_NAME" ]]; then
    REPO_NAME=$(git config --get remote.origin.url | sed 's/.*\/\([^\/]*\)\.git/\1/' || echo "unknown")
fi

COMMIT_MESSAGE=$(git log -1 --pretty=format:"%s" "$COMMIT_SHA" 2>/dev/null || echo "Unknown commit message")
COMMIT_TIMESTAMP=$(git log -1 --pretty=format:"%cI" "$COMMIT_SHA" 2>/dev/null || echo "$(date -u +%Y-%m-%dT%H:%M:%SZ)")

if [[ -n "$CURRENT_COMMIT_NUM" && -n "$TOTAL_COMMITS" ]]; then
    echo "($COMMIT_SHA): Starting upload of report to Membrowse (commit $CURRENT_COMMIT_NUM of $TOTAL_COMMITS)..."
else
    echo "($COMMIT_SHA): Starting upload of report to Membrowse..."
fi

UPLOAD_ARGS=(
    "--base-report" "$REPORT_JSON"
    "--commit-sha" "$COMMIT_SHA"
    "--commit-message" "$COMMIT_MESSAGE"
    "--timestamp" "$COMMIT_TIMESTAMP"
    "--base-sha" "$BASE_SHA"
    "--branch-name" "$BRANCH_NAME"
    "--repository" "$REPO_NAME"
    "--target-name" "$TARGET_NAME"
)

if [[ -n "$PR_NUMBER" ]]; then
    UPLOAD_ARGS+=("--pr-number" "$PR_NUMBER")
fi

if [[ -n "$API_KEY" ]]; then
    UPLOAD_ARGS+=("--api-key" "$API_KEY")
    if [[ -n "$MEMBROWSE_API_URL" ]]; then
        UPLOAD_ARGS+=("--api-endpoint" "$MEMBROWSE_API_URL")
    fi
fi

python3 -m membrowse.api.client "${UPLOAD_ARGS[@]}" || {
    echo "($COMMIT_SHA): Error: Failed upload report"
    exit 1
}

if [[ -n "$CURRENT_COMMIT_NUM" && -n "$TOTAL_COMMITS" ]]; then
    echo "($COMMIT_SHA): Memory report uploaded successfully (commit $CURRENT_COMMIT_NUM of $TOTAL_COMMITS)"
else
    echo "($COMMIT_SHA): Memory report uploaded successfully"
fi
