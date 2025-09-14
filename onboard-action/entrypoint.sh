#!/bin/bash
set -e

# Onboard Action entrypoint for MemBrowse historical analysis
# This script processes the last N commits and generates memory reports for each

NUM_COMMITS="$1"
BUILD_SCRIPT="$2"
ELF_PATH="$3"
LD_PATHS="$4"
TARGET_NAME="$5"
API_KEY="$6"

# Get the directory of this script to find shared resources
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SHARED_DIR="$(dirname "$SCRIPT_DIR")/shared"

echo "Starting historical memory analysis for $TARGET_NAME"
echo "Processing last $NUM_COMMITS commits"
echo "Build script: $BUILD_SCRIPT"
echo "ELF file: $ELF_PATH"
echo "Linker scripts: $LD_PATHS"

# Get repository name
REPO_NAME="$GITHUB_REPOSITORY"
CURRENT_BRANCH="$GITHUB_REF_NAME"

# Save current state
ORIGINAL_HEAD=$(git rev-parse HEAD)

# Get the last N commits on the current branch (reversed to process oldest first)
echo "Getting commit history..."
COMMITS=$(git log --format="%H" -n "$NUM_COMMITS" "$CURRENT_BRANCH" --reverse)

# We'll pass LD_PATHS directly to collect_report.sh which handles the parsing

# Process each commit
COMMIT_COUNT=0
while IFS= read -r commit; do
    COMMIT_COUNT=$((COMMIT_COUNT + 1))
    echo ""
    echo "=== Processing commit $COMMIT_COUNT/$NUM_COMMITS: $commit ==="
    
    # Checkout the commit
    echo "$commit: Checking out commit..."
    git checkout "$commit" --quiet
    
    # Clean any previous build artifacts
    echo "Cleaning previous build artifacts..."
    git clean -fd || true
    
    # Build the firmware
    echo "$commit: Building firmware with: $BUILD_SCRIPT"
    if ! eval "$BUILD_SCRIPT"; then
        echo "$commit: Build failed, stopping workflow..."
        git checkout "$ORIGINAL_HEAD" --quiet
        exit 1
    fi
    
    # Check if ELF file was generated
    if [[ ! -f "$ELF_PATH" ]]; then
        echo "$commit: ELF file not found at $ELF_PATH, stopping workflow..."
        git checkout "$ORIGINAL_HEAD" --quiet
        exit 1
    fi
    
    # Get parent commit SHA for base comparison
    BASE_SHA=$(git rev-parse "$commit~1" 2>/dev/null || echo "")
    
    echo "$commit: Generating memory report for commit..."
    echo "$commit: Base commit: $BASE_SHA"

    # Run the modular memory collection script
    if ! bash "$SHARED_DIR/collect_report.sh" \
        "$ELF_PATH" \
        "$LD_PATHS" \
        "$TARGET_NAME" \
        "$API_KEY" \
        "$commit" \
        "$BASE_SHA" \
        "$CURRENT_BRANCH" \
        "$REPO_NAME"; then
        echo "$commit: Failed to generate or upload memory report, stopping workflow..."
        git checkout "$ORIGINAL_HEAD" --quiet
        exit 1
    fi
    echo "$commit: Memory report generated and uploaded successfully"

done <<< "$COMMITS"

# Restore original HEAD
echo ""
echo "Restoring original HEAD..."
git checkout "$ORIGINAL_HEAD" --quiet

echo ""
echo "Historical analysis completed!"
echo "Processed $COMMIT_COUNT commits"