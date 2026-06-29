#!/usr/bin/env bash
# Staged Claude Code-style session for the searchts hero demo.
# Narration is illustrative; the searchts read is a REAL call.
url="https://stackoverflow.com/questions/11227809/why-is-processing-a-sorted-array-faster-than-an-unsorted-array"

R=$'\033[0m'; DIM=$'\033[2m'
CORAL=$'\033[38;5;173m'; GRY=$'\033[38;5;245m'; RED=$'\033[38;5;203m'; GRN=$'\033[38;5;114m'; WHT=$'\033[38;5;252m'

q="$1"; w=62
bar=$(printf '─%.0s' $(seq 1 $((w+2))))
printf -v line "%-*s" "$w" "> $q"
printf "%b\n" "${GRY}╭${bar}╮${R}"
printf "%b\n" "${GRY}│${R} ${WHT}${line}${R} ${GRY}│${R}"
printf "%b\n" "${GRY}╰${bar}╯${R}"
echo
sleep 1.3
printf "%b\n" "${CORAL}●${R} I'll pull the canonical Stack Overflow answer."
echo
sleep 1.2
printf "%b\n" "${CORAL}●${R} ${WHT}Fetch${R}${GRY}(stackoverflow.com/questions/11227809)${R}"
sleep 1.5
printf "%b\n" "  ${GRY}└${R} ${RED}Error: HTTP 403${R} ${GRY}- blocked by Cloudflare bot protection${R}"
echo
sleep 1.6
printf "%b\n" "${CORAL}●${R} That page is bot-walled. Routing through ${WHT}searchts${R} instead."
echo
sleep 1.1
printf "%b\n" "${CORAL}●${R} ${WHT}searchts read${R} ${GRY}https://stackoverflow.com/questions/11227809${R}"
{ timeout 15 searchts read "$url" 2>&1 | head -7; printf '%s\n' "... +118 lines"; } | sed "s/^/  ${GRY}│${R} /"
echo
sleep 1.9
printf "%b\n" "${CORAL}●${R} Here's the answer:"
echo
printf "%b\n" "  It's ${GRN}branch prediction${R}. The hot loop branches on whether each value"
printf "%b\n" "  is >= 128. On a ${WHT}sorted${R} array those branches come in long predictable"
printf "%b\n" "  runs, so the CPU's branch predictor is right almost every time and avoids"
printf "%b\n" "  pipeline flushes - about ${GRN}6x faster${R} than the unsorted case."
