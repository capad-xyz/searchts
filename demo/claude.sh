#!/usr/bin/env bash
# A staged Claude Code-style agent loop for the searchts demo.
# The narration is illustrative; the searchts install and page read are REAL.
url="https://stackoverflow.com/questions/11227809/why-is-processing-a-sorted-array-faster-than-an-unsorted-array"

DIM=$'\033[2m'; RST=$'\033[0m'
GRN=$'\033[38;5;114m'; RED=$'\033[38;5;203m'; BLU=$'\033[38;5;117m'; MAG=$'\033[38;5;212m'; GRY=$'\033[38;5;245m'

printf "%b\n" "${MAG}>${RST} $1"
sleep 1.1
printf "%b\n" "${BLU}*${RST} Looking up that Stack Overflow answer..."
sleep 1.1
printf "%b\n" "  ${DIM}fetching the page with the built-in web tool${RST}"
sleep 1.3
printf "%b\n" "${RED}x${RST} Blocked: ${RED}HTTP 403${RST} ${GRY}- the page is behind a Cloudflare bot wall.${RST}"
sleep 1.5
printf "%b\n" "${BLU}*${RST} My built-in fetch can't get through. Installing a tool that can: ${MAG}searchts${RST}"
sleep 1.0
printf "%b\n" "  ${GRY}\$ searchts skill install${RST}"
searchts skill install 2>&1 | sed "s/^/  /"
sleep 1.3
printf "%b\n" "${BLU}*${RST} Retrying through ${MAG}/searchts${RST}..."
sleep 0.8
printf "%b\n" "  ${GRY}\$ searchts read \$url${RST}"
timeout 15 searchts read "$url" 2>&1 | head -8 | sed "s/^/  /"
sleep 1.6
printf "%b\n" "${GRN}+${RST} Done. It's ${GRN}branch prediction${RST}: sorting the data makes the CPU's"
printf "%b\n" "  branch predictor almost always right, so the loop runs ~6x faster."
