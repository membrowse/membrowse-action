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

MEMBROWSE_API_URL="https://membrowse.uc.r.appspot.com/api/upload"

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

echo "Starting memory analysis for target: $TARGET_NAME"
echo "ELF file: $ELF_PATH"
echo "Linker scripts: $LD_SCRIPTS"

echo "Starting direct ELF analysis..."

# Get script directory for relative imports
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Parse memory regions from linker scripts
echo "Parsing memory regions from linker scripts..."
MEMORY_REGIONS_JSON=$(mktemp)

python3 "$SCRIPT_DIR/memory_regions.py" $LD_SCRIPTS > "$MEMORY_REGIONS_JSON" || {
    echo "Error: Failed to parse memory regions"
    exit 1
}

# Generate JSON report using Python script
echo "Generating JSON memory report..."
REPORT_JSON=$(mktemp)

python3 "$SCRIPT_DIR/memory_report.py" \
    --elf-path "$ELF_PATH" \
    --memory-regions "$MEMORY_REGIONS_JSON" \
    --output "$REPORT_JSON" || {
    echo "Error: Failed to generate memory report"
    exit 1
}

echo "JSON report generated successfully"

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

echo "Upload memory report to MemBrowse..."

UPLOAD_ARGS=(
    "--base-report" "$REPORT_JSON"
    "--commit-sha" "$COMMIT_SHA"
    "--commit-message" "$COMMIT_MESSAGE"
    "--timestamp" "$COMMIT_TIMESTAMP"
    "--base-sha" "$BASE_SHA"
    "--branch-name" "$BRANCH_NAME"
    "--repository" "$REPO_NAME"
    "--target-name" "$TARGET_NAME"
    "--print-report"
)

if [[ -n "$API_KEY" ]]; then
    UPLOAD_ARGS+=("--api-key" "$API_KEY")
    if [[ -n "$MEMBROWSE_API_URL" ]]; then
        UPLOAD_ARGS+=("--api-endpoint" "$MEMBROWSE_API_URL")
    fi
fi

python3 "$SCRIPT_DIR/upload.py" "${UPLOAD_ARGS[@]}" || {
    echo "Error: Failed upload report"
    exit 1
}

echo "Memory analysis completed successfully"
