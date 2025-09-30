#!/bin/bash
set -e

# PR Action entrypoint for MemBrowse memory analysis
# This script handles both pull request and push events

ELF_PATH="$1"
LD_PATHS="$2"
TARGET_NAME="$3"
API_KEY="$4"

# Get the directory of this script to find scripts
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPTS_DIR="$(dirname "$SCRIPT_DIR")/scripts"

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
    BRANCH_NAME="$GITHUB_REF_NAME"
    PR_NUMBER=""
    
    echo "Push event detected"
    echo "Commit: $COMMIT_SHA"
    echo "Base commit: $BASE_SHA"
    echo "Branch: $BRANCH_NAME"
else
    echo "Unsupported event type: $GITHUB_EVENT_NAME"
    exit 1
fi

# Get repository name
REPO_NAME="$GITHUB_REPOSITORY"

# Run the modular memory collection script
echo "Running memory analysis with collect_report.sh..."
bash "$SCRIPTS_DIR/collect_report.sh" \
    "$ELF_PATH" \
    "$LD_PATHS" \
    "$TARGET_NAME" \
    "$API_KEY" \
    "$COMMIT_SHA" \
    "$BASE_SHA" \
    "$BRANCH_NAME" \
    "$REPO_NAME" \
    "$PR_NUMBER"

echo "Memory analysis completed successfully"