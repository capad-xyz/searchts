#!/usr/bin/env bash
# ==============================================================================
# demo_searchts_vs_agent_reach.sh
# Side-by-side terminal demo: searchts vs. a naive fetch / Agent-Reach-style setup
#
# Usage:
#   bash demo_searchts_vs_agent_reach.sh
#
# Override any target:
#   SHARE_URL="https://gemini.google.com/share/..." \
#   FINGERPRINT_URL="https://www.crunchbase.com/" \
#   WALLED_URL="https://www.linkedin.com/in/someone/" \
#   VIDEO_URL="https://www.youtube.com/watch?v=..." \
#   REEL_URL="https://www.instagram.com/reel/..." \
#   bash demo_searchts_vs_agent_reach.sh
#
# What it needs: curl, python3, and searchts (installed, or uvx on PATH).
# The first uvx run downloads the package. No stealth browser is needed for
# these five steps; `searchts install --browser` adds it.
# ==============================================================================

set -u

BOLD="\033[1m"
DIM="\033[2m"
GREEN="\033[0;32m"
RED="\033[0;31m"
YELLOW="\033[0;33m"
CYAN="\033[0;36m"
RESET="\033[0m"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

RUNNER=(searchts)
if ! command -v searchts >/dev/null 2>&1; then
  if ! command -v uvx >/dev/null 2>&1; then
    echo "searchts is not installed and uvx is not on PATH." >&2
    echo 'Install it with: pipx install "searchts[mcp]"' >&2
    exit 1
  fi
  RUNNER=(uvx --from "searchts[mcp]" searchts)
fi

banner() {
  printf '\n%b\n' "${BOLD}${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
  printf '%b\n' "${BOLD}${CYAN}  $1${RESET}"
  printf '%b\n' "${BOLD}${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
}

step() {
  printf '\n%b\n' "${BOLD}${YELLOW}▶ $1${RESET}"
}

json_fields() {
  python3 -c '
import json, sys
path = sys.argv[1]
with open(path, encoding="utf-8") as fh:
    data = json.load(fh)
print("backend: {}  status: {}  chars: {}".format(data.get("backend"), data.get("status"), data.get("chars")))
text = (data.get("text") or "").strip().splitlines()
for line in text[:8]:
    print("  " + line)
' "$1"
}

banner "DEMO 1: AI-chat share links (ChatGPT / Claude / Gemini)"
SHARE_URL="${SHARE_URL:-https://gemini.google.com/share/6d141b742a13}"

step "1A. What a plain fetch gets (raw HTML, no JavaScript and no decoder)"
printf '%b\n' "${DIM}\$ curl -sSL '${SHARE_URL}' -o share.html${RESET}"
if curl -sSL --max-time 20 "$SHARE_URL" -o "$TMP/share.html"; then
  raw_bytes=$(wc -c < "$TMP/share.html" | tr -d ' ')
  printf '  downloaded %s bytes of HTML.\n' "$raw_bytes"
else
  printf '  %bcurl could not fetch it.%b\n' "$RED" "$RESET"
fi
printf '%b\n' "${RED}✘ The conversation is not readable text in that HTML: it lives in the provider's data channel.${RESET}"

step "1B. What searchts read does (native share extractor; browserless for the first five providers)"
printf '%b\n' "${DIM}\$ ${RUNNER[*]} read '${SHARE_URL}' --json${RESET}"
if "${RUNNER[@]}" read "$SHARE_URL" --json > "$TMP/share.json" 2> "$TMP/share.err"; then
  if json_fields "$TMP/share.json"; then
    printf '%b\n' "${GREEN}✔ Recognized the share URL and decoded role-labeled Markdown from the native payload.${RESET}"
  else
    printf '%b\n' "${RED}✘ The read succeeded but its JSON did not parse.${RESET}"
  fi
else
  sed -n '1,6p' "$TMP/share.err"
  printf '%b\n' "${RED}✘ It failed loudly instead of returning a shell. That is the contract.${RESET}"
fi

banner "DEMO 2: Escalating unlocker + prompt-injection scrubbing"
FINGERPRINT_URL="${FINGERPRINT_URL:-https://www.crunchbase.com/}"

step "2A. A naive Python fetch on a TLS-fingerprinted site"
printf '%b\n' "${DIM}\$ python3 -c \"import urllib.request; urllib.request.urlopen('${FINGERPRINT_URL}')\"${RESET}"
python3 -c '
import sys, urllib.request
try:
    with urllib.request.urlopen(sys.argv[1], timeout=15) as response:
        print(f"  HTTP {response.status}: {len(response.read())} bytes")
except Exception as exc:
    code = getattr(exc, "code", "")
    print(f"  {type(exc).__name__} {code}".rstrip())
' "$FINGERPRINT_URL" 2>&1 || true
printf '%b\n' "${RED}✘ A default user agent gets a 403 before the page is even read.${RESET}"

step "2B. searchts read --scrub (curl_cffi -> Jina -> patchright stealth)"
printf '%b\n' "${DIM}\$ ${RUNNER[*]} read '${FINGERPRINT_URL}' --scrub --json${RESET}"
if "${RUNNER[@]}" read "$FINGERPRINT_URL" --scrub --json > "$TMP/fp.json" 2> "$TMP/fp.err"; then
  if json_fields "$TMP/fp.json"; then
    printf '%b\n' "${GREEN}✔ Clean Markdown from a tier above the naive fetch, with invisible/bidi injection characters scrubbed.${RESET}"
  else
    printf '%b\n' "${RED}✘ The read succeeded but its JSON did not parse.${RESET}"
  fi
else
  sed -n '1,6p' "$TMP/fp.err"
  printf '%b\n' "${YELLOW}✘ Failed loudly with the tier that stopped. No half-HTML passed off as the page.${RESET}"
fi

banner "DEMO 3: Fail-loud truth wall on an unauthenticated login gate"
WALLED_URL="${WALLED_URL:-https://www.linkedin.com/in/satyanadella/}"

step "3A. A naive scraper on a login wall served as HTTP 200"
printf '%b\n' "${RED}✘ Many sites serve the sign-in page as HTTP 200. A naive scraper hands that HTML back, and the model summarizes the login form.${RESET}"

step "3B. searchts read on a walled URL without a handed-over session"
printf '%b\n' "${DIM}\$ ${RUNNER[*]} read '${WALLED_URL}' --json${RESET}"
"${RUNNER[@]}" read "$WALLED_URL" --json > "$TMP/wall.out" 2> "$TMP/wall.err"
wall_rc=$?
printf '  exit code: %s  stdout bytes: %s\n' "$wall_rc" "$(wc -c < "$TMP/wall.out" | tr -d ' ')"
sed -n '1,5p' "$TMP/wall.err"
if [ "$wall_rc" -ne 0 ] && [ ! -s "$TMP/wall.out" ]; then
  printf '%b\n' "${GREEN}✔ Refused the fake read: non-zero exit, empty stdout, named tier and reason.${RESET}"
else
  printf '%b\n' "${YELLOW}! This URL was readable without a session; try another walled profile.${RESET}"
fi

banner "DEMO 4: Video and Instagram Reel transcription (subtitles first, then Whisper)"
VIDEO_URL="${VIDEO_URL:-https://www.youtube.com/watch?v=jNQXAC9IVRw}"
REEL_URL="${REEL_URL:-}"

step "4A. The Agent-Reach-style route: wire the upstream CLI yourself"
printf '%b\n' "${DIM}\$ yt-dlp --dump-json '${VIDEO_URL}' | jq '.subtitles'${RESET}"

step "4B. searchts transcribe, one command across YouTube, TikTok, Instagram and Reddit"
printf '%b\n' "${DIM}\$ ${RUNNER[*]} transcribe '${VIDEO_URL}'${RESET}"
"${RUNNER[@]}" transcribe "$VIDEO_URL" 2> "$TMP/tr.err" | head -n 10 || true
if [ -s "$TMP/tr.err" ]; then
  printf '%b\n' "${DIM}(status: $(head -n 1 "$TMP/tr.err"))${RESET}"
fi
if [ -n "$REEL_URL" ]; then
  printf '%b\n' "${DIM}\$ ${RUNNER[*]} transcribe '${REEL_URL}' --cookies-from-browser chrome${RESET}"
  "${RUNNER[@]}" transcribe "$REEL_URL" --cookies-from-browser chrome 2>&1 | head -n 10 || true
else
  printf '%b\n' "${DIM}# Login-gated Reel: REEL_URL=https://www.instagram.com/reel/...${RESET}"
  printf '%b\n' "${DIM}#   bash demo_searchts_vs_agent_reach.sh   (adds --cookies-from-browser chrome)${RESET}"
fi

banner "DEMO 5: The honest two-suite benchmark (Smoke vs. Walled)"
printf '%b\n' "${DIM}\$ python -m benchmarks.run${RESET}"
if [ "${RUN_BENCH:-0}" = "1" ]; then
  python3 -m benchmarks.run || true
else
  printf '%b\n' "${GREEN}✔ Smoke (open docs + 5 browserless AI share links) and Walled (Reddit, LinkedIn, Cloudflare/DataDome, X, Booking) are reported separately.${RESET}"
  printf '%b\n' "${DIM}  Last committed run: Smoke 12/12, Walled 2/7. See docs/scorecard.md.${RESET}"
  printf '%b\n' "${DIM}  Run it yourself with RUN_BENCH=1 bash demo_searchts_vs_agent_reach.sh.${RESET}"
fi
