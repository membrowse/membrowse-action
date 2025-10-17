#!/bin/bash
set -e

# PR Action entrypoint for MemBrowse memory analysis
# This script handles both pull request and push events

# Usage message
usage() {
    cat << EOF
Usage: membrowse_report.sh [OPTIONS] <elf_path> <ld_scripts> <target_name> [<api_key> <api_url>]

Generate memory usage report for embedded firmware

OPTIONS:
    --local     Generate report locally without uploading (prints JSON to stdout)
    --help      Show this help message

ARGUMENTS:
    elf_path       Path to ELF file
    ld_scripts     Space-separated linker script paths (quoted)
    target_name    Target identifier (e.g., my-project)
    api_key        MemBrowse API key (required without --local)
    api_url        MemBrowse API endpoint (required without --local)

EXAMPLES:
    # Local mode - print report to stdout
    membrowse_report.sh --local build/firmware.elf "linker.ld" my-target

    # Upload to MemBrowse
    membrowse_report.sh build/firmware.elf "linker.ld" my-target "\$API_KEY" "https://membrowse.appspot.com/api/upload"

EOF
    exit 0
}

# Parse flags
LOCAL_MODE=false
while [[ "$1" == --* ]]; do
    case "$1" in
        --help)
            usage
            ;;
        --local)
            LOCAL_MODE=true
            shift
            ;;
        *)
            echo "Unknown option: $1"
            usage
            ;;
    esac
done

# Parse positional arguments
ELF_PATH="$1"
LD_PATHS="$2"
TARGET_NAME="$3"

if [[ "$LOCAL_MODE" == "false" ]]; then
    API_KEY="$4"
    MEMBROWSE_API_URL="$5"

    if [[ -z "$API_KEY" || -z "$MEMBROWSE_API_URL" ]]; then
        echo "Error: API key and URL required without --local flag"
        usage
    fi
else
    API_KEY=""
    MEMBROWSE_API_URL=""
fi

# Find membrowse_collect_report.sh - check PATH first (for installed package), then relative path (for development)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COLLECT_REPORT_SCRIPT="$(command -v membrowse_collect_report.sh 2>/dev/null || echo "$SCRIPT_DIR/membrowse_collect_report.sh")"

if [[ ! -f "$COLLECT_REPORT_SCRIPT" ]]; then
    echo "Error: membrowse_collect_report.sh not found in PATH or at $SCRIPT_DIR/membrowse_collect_report.sh"
    exit 1
fi

echo "Starting memory analysis for $TARGET_NAME"
echo "ELF file: $ELF_PATH"
echo "Linker scripts: $LD_PATHS"

# Determine commit SHA and branch based on event type
if [[ "$GITHUB_EVENT_NAME" == "pull_request" ]]; then
    # For pull requests, use the head commit
    COMMIT_SHA="$GITHUB_SHA"
    BASE_SHA=$(jq -r '.pull_request.base.sha' "$GITHUB_EVENT_PATH")
    BRANCH_NAME=$(jq -r '.pull_request.head.ref' "$GITHUB_EVENT_PATH")
    PR_NUMBER=$(jq -r '.pull_request.number' "$GITHUB_EVENT_PATH")

    echo "Pull request event detected"
    echo "Head commit: $COMMIT_SHA"
    echo "Base commit: $BASE_SHA"
    echo "Branch: $BRANCH_NAME"
    echo "PR number: $PR_NUMBER"
elif [[ "$GITHUB_EVENT_NAME" == "push" ]]; then
    # For push events, use the pushed commit
    COMMIT_SHA="$GITHUB_SHA"
    # For push events, use the before commit as base
    BASE_SHA=$(jq -r '.before' "$GITHUB_EVENT_PATH")
    # Extract branch name from git, with fallback to environment variable
    # Use symbolic-ref first, then search for branches pointing at HEAD (works in detached HEAD)
    BRANCH_NAME=$(git symbolic-ref --short HEAD 2>/dev/null || \
                  git for-each-ref --points-at HEAD --format='%(refname:short)' refs/heads/ | head -n1 || \
                  echo "${GITHUB_REF_NAME:-unknown}")
    PR_NUMBER=""

    echo "Push event detected"
    echo "Commit: $COMMIT_SHA"
    echo "Base commit: $BASE_SHA"
    echo "Branch: $BRANCH_NAME"
else
    echo "Unsupported event type: $GITHUB_EVENT_NAME"
    exit 1
fi

# Run the modular memory collection script
echo "Running memory analysis with membrowse_collect_report.sh..."
"$COLLECT_REPORT_SCRIPT" \
    "$ELF_PATH" \
    "$LD_PATHS" \
    "$TARGET_NAME" \
    "$API_KEY" \
    "$COMMIT_SHA" \
    "$BASE_SHA" \
    "$BRANCH_NAME" \
    "" \
    "$MEMBROWSE_API_URL" \
    "$PR_NUMBER"

echo "Memory analysis completed successfully"