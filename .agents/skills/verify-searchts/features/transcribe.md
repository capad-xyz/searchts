# Transcribe a video

`searchts transcribe <url>` prefers captions that already exist, then falls back
to hosted Whisper (Groq / OpenAI, keyed) or keyless-local faster-whisper. YouTube,
TikTok, Instagram and Reddit video are the supported surfaces.

## Sub-features

- `transcribe-captions` pulls an existing subtitle track with no key at all.
- `transcribe-output` writes the transcript to a file with `-o`, and prints it
  otherwise.
- `transcribe-local-file` accepts a local audio file, not just a URL.
- `transcribe-fallback` reaches for Whisper only when there is no caption track.

## How to get to it (user POV)

- `searchts transcribe https://www.youtube.com/watch?v=<id>`
- `searchts transcribe <url> -o out.txt`
- `searchts transcribe ./audio.m4a -o out.txt`

## Driving it

Preconditions: `doctor --json` reports `youtube` and `tiktok` `ok` with
`yt-dlp` as the active backend. If it does not, the drive is `verified-unreachable`
with that prerequisite recorded, not a failure.

- **Caption pull.** `.venv/bin/python -m searchts transcribe https://www.youtube.com/watch?v=jNQXAC9IVRw -o artifacts/transcribe/meeting-day.txt 2> artifacts/transcribe/meeting-day.err`. Exit `0`.
- **Proof.** `artifacts/transcribe/meeting-day.txt` exists, is longer than 200
  characters, and holds sentences rather than a URL or an error string.
- **Progress is on stderr, the result line on stdout.** `artifacts/transcribe/meeting-day.err` contains `fetching subtitles…`; stdout holds only `[ok] Transcript written to …`. A *tick* on stdout is a P4.6 regression; the confirmation line is the command's answer and belongs there.
- **No key needed.** With no Whisper key configured this drive still succeeds,
  because captions existed. That is the point of captions-first: prove it on a
  video that has them.

## Gotchas

- Some videos have auto-generated captions that are poor or in the wrong
  language. A transcript that exists is the proof; its quality is not.
- Transcript text has no line structure guarantee. Do not assert on line counts.
- `faster-whisper` fallback downloads a model on first use and is slow. A drive
  that reaches it needs a generous timeout, and a timeout is not a passing proof.
- Never pipe `transcribe` into `head`; same broken-pipe trap as `read`.
## Proven here

Driven 2026-10-12 against `searchts v0.14.0`:
`transcribe https://www.youtube.com/watch?v=jNQXAC9IVRw -o …` → exit `0`,
218 characters of real caption text on disk, `fetching subtitles…` on stderr and
only the `[ok] Transcript written to …` line on stdout. No Whisper key
configured.
