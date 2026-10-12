# Transcribe a video

Transcribe a video turns a video URL or a local audio file into text, preferring
captions that already exist and falling back to speech recognition only when
there are none. YouTube, TikTok, Instagram and Reddit video are supported.

## Sub-features

- `transcribe-captions` pulls an existing subtitle track with no key at all.
- `transcribe-file` writes the transcript to the path given by `-o`.
- `transcribe-local` accepts a local audio file rather than a URL.
- `transcribe-provider` chooses a recognition provider with `--provider`.
- `transcribe-no-subtitle` skips caption lookup with `--no-subtitles`.
- `transcribe-fallback` reaches for recognition only when no caption track
  exists.

## How to get to it (user POV)

- Run `searchts transcribe <url>` to print the transcript.
- Run `searchts transcribe <url> -o out.txt` to write it to a file.
- Run `searchts transcribe ./audio.m4a -o out.txt` for a local file.

## Driving it with searchts

Preconditions:

- `doctor --json` reports `youtube` and `tiktok` `ok` with an active backend.
  Without one, the drive is unreachable with that precondition recorded, not
  failed.
- No speech-recognition key is configured, so a passing drive proves the
  caption-first path.
- The video has a caption track. A video without one reaches the fallback and
  needs a key or a local model download, which is a different proof.

- **Caption pull.** Run `.venv/bin/python -m searchts transcribe https://www.youtube.com/watch?v=jNQXAC9IVRw -o artifacts/transcribe/meeting-day.txt > artifacts/transcribe/meeting-day.out 2> artifacts/transcribe/meeting-day.err`. Exit code `0`.
- **Payload.** Open `artifacts/transcribe/meeting-day.txt`. It is longer than 200 characters and contains sentences, not a URL and not an error string.
- **Streams.** Read `artifacts/transcribe/meeting-day.err`, which carries the progress tick, and `artifacts/transcribe/meeting-day.out`, which carries only the confirmation line naming the file written. A progress tick on stdout would be a regression of the rule that progress never lands there.
- **Local file.** Run `.venv/bin/python -m searchts transcribe artifacts/transcribe/meeting-day.txt -o artifacts/transcribe/local.txt`. Exit code `0` and `artifacts/transcribe/local.txt` is non-empty. A non-audio input proves only that the argument is accepted.
- **Proof.** Open `artifacts/transcribe/meeting-day.txt`. It holds recognisable spoken sentences about the video, which is what distinguishes a transcript from a status message.
- **Report an unreachable fallback.** If the caption track is absent, record the provider that was needed and the key that was missing rather than treating the failure as a transcript.

## Gotchas

- Auto-generated captions can be wrong or in the wrong language. That a
  transcript exists is the proof; its accuracy is not.
- Transcript text has no guaranteed line structure. Do not assert on line counts.
- The local recognition fallback downloads a model on first use and is slow. A
  drive that reaches it needs a generous timeout, and a timeout is not a passing
  proof.
- Never pipe a transcribe into `head`.
- Progress is written to stderr as it happens. A drive that only captures stdout
  will think the command hung.