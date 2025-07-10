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

# Generate JSON report using Python script
echo "Generating JSON memory report..."
REPORT_JSON=$(mktemp)

python3 "$SCRIPT_DIR/memory_report.py" \
    --elf-path "$ELF_PATH" \
    --ld-scripts $LD_SCRIPTS \
    --output "$REPORT_JSON" || {
    echo "Error: Failed to generate memory report"
    exit 1
}

echo "JSON report generated successfully"

# Enrich with git metadata
echo "Enriching report with git metadata..."
FINAL_REPORT=$(mktemp)

# Get git information if not provided
if [[ -z "$COMMIT_SHA" ]]; then
    COMMIT_SHA=$(git rev-parse HEAD)
fi

if [[ -z "$BRANCH_NAME" ]]; then
    BRANCH_NAME=$(git rev-parse --abbrev-ref HEAD)
fi

if [[ -z "$REPO_NAME" ]]; then
    REPO_NAME=$(git config --get remote.origin.url | sed 's/.*\/\([^\/]*\)\.git/\1/' || echo "unknown")
fi

# Create enriched report with metadata
python3 -c "
import json
import sys
from datetime import datetime

# Read the base report
with open('$REPORT_JSON', 'r') as f:
    report = json.load(f)

# Add metadata
metadata = {
    'commit_sha': '$COMMIT_SHA',
    'base_sha': '$BASE_SHA',
    'branch_name': '$BRANCH_NAME',
    'repository': '$REPO_NAME',
    'target_name': '$TARGET_NAME',
    'timestamp': datetime.utcnow().isoformat() + 'Z',
    'analysis_version': '1.0.0'
}

# Merge metadata into report
enriched_report = {
    'metadata': metadata,
    'memory_analysis': report
}

# Write enriched report
with open('$FINAL_REPORT', 'w') as f:
    json.dump(enriched_report, f, indent=2)
"

echo "Report enriched with metadata"

# Upload to MemBrowse API if API key is provided
if [[ -n "$API_KEY" ]]; then
    echo "Uploading report to MemBrowse..."
    
    # TODO: Replace with actual MemBrowse API endpoint
    API_ENDPOINT="${MEMBROWSE_API_URL:-https://api.membrowse.com/v1/reports}"
    
    # Upload the report
    curl -X POST "$API_ENDPOINT" \
        -H "Authorization: Bearer $API_KEY" \
        -H "Content-Type: application/json" \
        -d @"$FINAL_REPORT" \
        --fail --show-error || {
        echo "Error: Failed to upload report to MemBrowse"
        exit 1
    }
    
    echo "Report uploaded successfully to MemBrowse"
else
    echo "No API key provided, skipping upload"
fi

# Output the final report for debugging
echo "Final report:"
cat "$FINAL_REPORT"

# Clean up final report
rm -f "$FINAL_REPORT"

echo "Memory analysis completed successfully"