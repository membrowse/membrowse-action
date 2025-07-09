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
    echo "Checking out commit $commit..."
    git checkout "$commit" --quiet
    
    # Clean any previous build artifacts
    echo "Cleaning previous build artifacts..."
    git clean -fd || true
    
    # Build the firmware
    echo "Building firmware with: $BUILD_SCRIPT"
    if ! eval "$BUILD_SCRIPT"; then
        echo "Build failed for commit $commit, skipping..."
        continue
    fi
    
    # Check if ELF file was generated
    if [[ ! -f "$ELF_PATH" ]]; then
        echo "ELF file not found at $ELF_PATH for commit $commit, skipping..."
        continue
    fi
    
    # Get commit timestamp and message for better reporting
    COMMIT_DATE=$(git show -s --format=%ci "$commit")
    COMMIT_MSG=$(git show -s --format=%s "$commit")
    
    echo "Generating memory report for commit $commit..."
    echo "Commit date: $COMMIT_DATE"
    echo "Commit message: $COMMIT_MSG"
    
    # Run the modular memory collection script
    if bash "$SHARED_DIR/collect_report.sh" \
        "$ELF_PATH" \
        "$LD_PATHS" \
        "$TARGET_NAME" \
        "$API_KEY" \
        "$commit" \
        "" \
        "$CURRENT_BRANCH" \
        "$REPO_NAME"; then
        echo "Memory report generated successfully for commit $commit"
    else
        echo "Failed to generate memory report for commit $commit"
    fi
    
    # Small delay to avoid overwhelming the API
    sleep 1
    
done <<< "$COMMITS"

# Restore original HEAD
echo ""
echo "Restoring original HEAD..."
git checkout "$ORIGINAL_HEAD" --quiet

echo ""
echo "Historical analysis completed!"
echo "Processed $COMMIT_COUNT commits"