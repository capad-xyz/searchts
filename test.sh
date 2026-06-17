#!/bin/bash
# searchts one-shot full test
# Usage: bash test.sh
# Run it on any machine with Python 3.10+

set -e

echo "============================================"
echo "    searchts full test"
echo "============================================"
echo ""

# -- 1. Prepare a clean environment --
echo "Creating test environment..."
TEST_DIR=$(mktemp -d)
python3 -m venv "$TEST_DIR/venv"
source "$TEST_DIR/venv/bin/activate"

# -- 2. Install --
echo "Installing from GitHub..."
pip install -q https://github.com/capad-xyz/searchts/archive/main.zip 2>&1 | tail -1
echo ""

# -- 3. Auto-configure --
echo "Running install..."
searchts install --env=auto 2>&1
echo ""

# -- 4. Diagnose --
echo "Running doctor..."
searchts doctor 2>&1
echo ""

# -- 5. Test one by one --
PASS=0
FAIL=0
SKIP=0

test_it() {
    local name="$1"
    shift
    echo -n "  $name ... "
    output=$(eval "$@" 2>&1) || true
    if echo "$output" | grep -q "http"; then
        echo "PASS"
        PASS=$((PASS+1))
    elif echo "$output" | grep -q "not installed\|not configured"; then
        echo "SKIP (missing dependency)"
        SKIP=$((SKIP+1))
    else
        echo "FAIL"
        echo "    $(echo "$output" | head -2)"
        FAIL=$((FAIL+1))
    fi
}

echo "Read tests"
test_it "Web" "searchts read 'https://example.com'"
test_it "GitHub" "searchts read 'https://github.com/capad-xyz/searchts'"
test_it "YouTube" "searchts read 'https://www.youtube.com/watch?v=dQw4w9WgXcQ'"
test_it "RSS" "searchts read 'https://hnrss.org/frontpage'"
test_it "Twitter" "searchts read 'https://x.com/elonmusk/status/1893797839927353448'"
test_it "Reddit" "searchts read 'https://www.reddit.com/r/LocalLLaMA/hot'"

echo ""
echo "Search tests"
test_it "Web search" "searchts search 'best AI agent framework' -n 2"
test_it "GitHub search" "searchts search-github 'yt-dlp' -n 2"
test_it "Twitter search" "searchts search-twitter 'AI agent' -n 2"
test_it "Reddit search" "searchts search-reddit 'machine learning' -n 2"
test_it "YouTube search" "searchts search-youtube 'AI tutorial' -n 2"

echo ""
echo "============================================"
echo "  PASS: $PASS   FAIL: $FAIL   SKIP: $SKIP"
echo "============================================"

# -- 6. Cleanup --
deactivate 2>/dev/null || true
rm -rf "$TEST_DIR"

if [ $FAIL -eq 0 ]; then
    echo ""
    echo "All tests passed!"
else
    echo ""
    echo "$FAIL test(s) failed, check the output above"
    exit 1
fi
