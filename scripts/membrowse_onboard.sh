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
MEMBROWSE_API_URL="$7"

# Find membrowse_collect_report.sh - check PATH first (for installed package), then relative path (for development)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COLLECT_REPORT_SCRIPT="$(command -v membrowse_collect_report.sh 2>/dev/null || echo "$SCRIPT_DIR/membrowse_collect_report.sh")"

if [[ ! -f "$COLLECT_REPORT_SCRIPT" ]]; then
    echo "Error: membrowse_collect_report.sh not found in PATH or at $SCRIPT_DIR/membrowse_collect_report.sh"
    exit 1
fi

# Progress tracking variables
SUCCESSFUL_UPLOADS=0
FAILED_UPLOADS=0
START_TIME=$(date +%s)

# Function to update GitHub Actions Job Summary with progress
update_progress_summary() {
    local current_commit=$1
    local total_commits=$2
    local commit_sha=$3
    local status=$4

    local current_time=$(date +%s)
    local elapsed_time=$((current_time - START_TIME))
    local elapsed_formatted=$(printf "%02d:%02d" $((elapsed_time / 60)) $((elapsed_time % 60)))

    # Initialize or update the summary
    cat >> "$GITHUB_STEP_SUMMARY" << EOF
# MemBrowse Historical Analysis Progress

**Target:** $TARGET_NAME
**Total Commits:** $total_commits
**Elapsed Time:** ${elapsed_formatted}

## Progress Overview
- 🔄 **Current:** $current_commit of $total_commits
- ✅ **Successful:** $SUCCESSFUL_UPLOADS
- ❌ **Failed:** $FAILED_UPLOADS

## Latest Commit
**Commit $current_commit:** \`${commit_sha:0:8}\` - $status

---
EOF
}

# Function to add commit result to summary
add_commit_result() {
    local commit_num=$1
    local commit_sha=$2
    local status=$3
    local build_status=$4
    local upload_status=$5

    local status_icon="🔄"
    case $status in
        "SUCCESS") status_icon="✅" ;;
        "FAILED") status_icon="❌" ;;
        "BUILDING") status_icon="🔨" ;;
        "UPLOADING") status_icon="📤" ;;
    esac

    echo "| $commit_num | \`${commit_sha:0:8}\` | $status_icon $status | $build_status | $upload_status |" >> "$GITHUB_STEP_SUMMARY"
}

# Function to create final summary
create_final_summary() {
    local total_processed=$1
    local current_time=$(date +%s)
    local total_time=$((current_time - START_TIME))
    local total_formatted=$(printf "%02d:%02d" $((total_time / 60)) $((total_time % 60)))

    cat >> "$GITHUB_STEP_SUMMARY" << EOF

## Final Results
- **Total Commits Processed:** $total_processed
- **Successful Uploads:** $SUCCESSFUL_UPLOADS
- **Failed Uploads:** $FAILED_UPLOADS
- **Total Time:** ${total_formatted}

EOF

    if [ $FAILED_UPLOADS -gt 0 ]; then
        echo "⚠️ **Some uploads failed. Check the logs for details.**" >> "$GITHUB_STEP_SUMMARY"
    else
        echo "🎉 **All commits processed successfully!**" >> "$GITHUB_STEP_SUMMARY"
    fi
}

echo "Starting historical memory analysis for $TARGET_NAME"
echo "Processing last $NUM_COMMITS commits"
echo "Build script: $BUILD_SCRIPT"
echo "ELF file: $ELF_PATH"
echo "Linker scripts: $LD_PATHS"

# Initialize GitHub Actions Summary
if [ -n "$GITHUB_STEP_SUMMARY" ]; then
    cat > "$GITHUB_STEP_SUMMARY" << EOF
# MemBrowse Historical Analysis

**Target:** $TARGET_NAME
**Total Commits:** $NUM_COMMITS
**Status:** Starting analysis...

| # | Commit | Status | Build | Upload |
|---|--------|--------|-------|--------|
EOF
fi

# Extract branch name from git, with fallback to environment variable
# Use symbolic-ref first, then search for branches pointing at HEAD (works in detached HEAD)
CURRENT_BRANCH=$(git symbolic-ref --short HEAD 2>/dev/null || \
                 git for-each-ref --points-at HEAD --format='%(refname:short)' refs/heads/ | head -n1 || \
                 echo "${GITHUB_REF_NAME:-unknown}")

# Save current state
ORIGINAL_HEAD=$(git rev-parse HEAD)

# Get the last N commits on the current branch (reversed to process oldest first)
echo "Getting commit history..."
COMMITS=$(git log --format="%H" -n "$NUM_COMMITS" --reverse)

# We'll pass LD_PATHS directly to collect_report.sh which handles the parsing

# Process each commit
COMMIT_COUNT=0
while IFS= read -r commit; do
    COMMIT_COUNT=$((COMMIT_COUNT + 1))
    echo ""
    echo "=== Processing commit $COMMIT_COUNT/$NUM_COMMITS: $commit ==="

    # Update progress summary for checkout
    [ -n "$GITHUB_STEP_SUMMARY" ] && add_commit_result "$COMMIT_COUNT" "$commit" "BUILDING" "Checking out..." "Pending"

    # Checkout the commit
    echo "$commit: Checking out commit..."
    git checkout "$commit" --quiet

    # Clean any previous build artifacts
    echo "Cleaning previous build artifacts..."
    git clean -fd || true

    # Update progress for build
    [ -n "$GITHUB_STEP_SUMMARY" ] && add_commit_result "$COMMIT_COUNT" "$commit" "BUILDING" "Building..." "Pending"

    # Build the firmware
    echo "$commit: Building firmware with: $BUILD_SCRIPT"
    # Execute build script using bash -c
    # NOTE: BUILD_SCRIPT comes from action input and is controlled by workflow owner
    # This is intentional - users need to specify their build commands
    if ! bash -c "$BUILD_SCRIPT"; then
        echo "$commit: Build failed, stopping workflow..."
        FAILED_UPLOADS=$((FAILED_UPLOADS + 1))
        [ -n "$GITHUB_STEP_SUMMARY" ] && add_commit_result "$COMMIT_COUNT" "$commit" "FAILED" "Build Failed" "Skipped"
        git checkout "$ORIGINAL_HEAD" --quiet
        exit 1
    fi

    # Check if ELF file was generated
    if [[ ! -f "$ELF_PATH" ]]; then
        echo "$commit: ELF file not found at $ELF_PATH, stopping workflow..."
        FAILED_UPLOADS=$((FAILED_UPLOADS + 1))
        [ -n "$GITHUB_STEP_SUMMARY" ] && add_commit_result "$COMMIT_COUNT" "$commit" "FAILED" "ELF Not Found" "Skipped"
        git checkout "$ORIGINAL_HEAD" --quiet
        exit 1
    fi

    # Get parent commit SHA for base comparison
    BASE_SHA=$(git rev-parse "$commit~1" 2>/dev/null || echo "")

    echo "$commit: Generating memory report for commit..."
    echo "$commit: Base commit: $BASE_SHA"

    # Update progress for upload
    [ -n "$GITHUB_STEP_SUMMARY" ] && add_commit_result "$COMMIT_COUNT" "$commit" "UPLOADING" "Complete" "Uploading..."

    # Run the modular memory collection script
    if ! "$COLLECT_REPORT_SCRIPT" \
        "$ELF_PATH" \
        "$LD_PATHS" \
        "$TARGET_NAME" \
        "$API_KEY" \
        "$commit" \
        "$BASE_SHA" \
        "$CURRENT_BRANCH" \
        "" \
        "$MEMBROWSE_API_URL" \
        "" \
        "$COMMIT_COUNT" \
        "$NUM_COMMITS"; then
        echo "$commit: Failed to generate or upload memory report, stopping workflow..."
        FAILED_UPLOADS=$((FAILED_UPLOADS + 1))
        [ -n "$GITHUB_STEP_SUMMARY" ] && add_commit_result "$COMMIT_COUNT" "$commit" "FAILED" "Complete" "Upload Failed"
        git checkout "$ORIGINAL_HEAD" --quiet
        exit 1
    fi
    echo "$commit: Memory report generated and uploaded successfully"

    # Update success count and progress
    SUCCESSFUL_UPLOADS=$((SUCCESSFUL_UPLOADS + 1))
    [ -n "$GITHUB_STEP_SUMMARY" ] && add_commit_result "$COMMIT_COUNT" "$commit" "SUCCESS" "Complete" "Complete"

done <<< "$COMMITS"

# Restore original HEAD
echo ""
echo "Restoring original HEAD..."
git checkout "$ORIGINAL_HEAD" --quiet

# Create final summary
[ -n "$GITHUB_STEP_SUMMARY" ] && create_final_summary "$COMMIT_COUNT"

echo ""
echo "Historical analysis completed!"
echo "Processed $COMMIT_COUNT commits"
echo "Successful uploads: $SUCCESSFUL_UPLOADS"
echo "Failed uploads: $FAILED_UPLOADS"
