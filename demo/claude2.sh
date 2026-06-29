#!/usr/bin/env bash
# Staged Claude Code-style session for the searchts install demo.
# Narration is illustrative; the install commands and the page read are REAL.
url="https://stackoverflow.com/questions/11227809/why-is-processing-a-sorted-array-faster-than-an-unsorted-array"
shown="https://stackoverflow.com/questions/11227809"

R=$'\033[0m'; DIM=$'\033[2m'
CORAL=$'\033[38;5;173m'; GRY=$'\033[38;5;245m'; GRN=$'\033[38;5;114m'; WHT=$'\033[38;5;252m'

q="$1"; w=62
bar=$(printf '─%.0s' $(seq 1 $((w+2))))
printf -v line "%-*s" "$w" "> $q"
printf "%b\n" "${GRY}╭${bar}╮${R}"
printf "%b\n" "${GRY}│${R} ${WHT}${line}${R} ${GRY}│${R}"
printf "%b\n" "${GRY}╰${bar}╯${R}"
echo
sleep 1.2
printf "%b\n" "${CORAL}●${R} Adding searchts - I'll set up both ways."
echo
sleep 1.1
printf "%b\n" "${CORAL}●${R} As an MCP server:"
printf "%b\n" "  ${GRY}└${R} ${WHT}searchts mcp install${R}"
searchts mcp install 2>&1 | head -2 | sed "s/^/  ${GRY}│${R} /"
echo
sleep 1.4
printf "%b\n" "${CORAL}●${R} Or as a Claude Code skill:"
printf "%b\n" "  ${GRY}└${R} ${WHT}searchts skill install${R}"
searchts skill install 2>&1 | sed "s/^/  ${GRY}│${R} /"
echo
sleep 1.5
printf "%b\n" "${CORAL}●${R} Set. Quick check on a page that blocks normal bots:"
printf "%b\n" "  ${GRY}└${R} ${WHT}searchts read${R} ${GRY}${shown}${R}"
timeout 15 searchts read "$url" 2>&1 | head -6 | sed "s/^/  ${GRY}│${R} /"
echo
sleep 1.6
printf "%b\n" "${CORAL}●${R} Working - I can read bot-walled pages now."
