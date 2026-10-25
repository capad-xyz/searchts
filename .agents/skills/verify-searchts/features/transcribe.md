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
- `transcribe-consent` requires approval before fetching a missing model and
  names the model, size, source, cache path and retry action for agents.
- `transcribe-receipt` reports the engine, model, device, language and whether
  it translated the audio.
- `transcribe-hint` biases local decoding with `--hint`; `--translate`
  opts into English output except with turbo.
- `transcribe-models` lists cached models and removes one with
  `--remove-model NAME --yes`.

## How to get to it (user POV)

- Run `searchts transcribe <url>` to print the transcript.
- Run `searchts transcribe <url> -o out.txt` to write it to a file.
- Run `searchts transcribe ./audio.m4a -o out.txt` for a local file.
- Run `searchts transcribe ./audio.m4a --provider local --model small --yes --json`
  for a consented local transcription.
- Run `searchts transcribe ./audio.m4a --model turbo --hint "Laurentius, Dark Souls"`
  to select a model and bias decoding toward names; add `--translate` for
  English output (except with turbo).
- Set `whisper_model` or `SEARCHTS_WHISPER_MODEL` to choose the local model by
  default, or use `--model` for one command.
- Run `searchts transcribe --list-models --json` to inspect model cache state.
- Run `searchts transcribe --remove-model small --yes --json` to remove a
  cached model after approval.
- Run `searchts transcribe --cleanup --dry-run` to report the faster-whisper
  removal impact, or add `--yes` after approval to remove unused packages and
  old faster-whisper model folders.
- Run `searchts transcribe <url> --provider local-fw` to force the temporary
  faster-whisper fallback while it remains installed.

## Driving it with searchts

Preconditions:

- `doctor --json` reports `youtube` and `tiktok` `ok` with an active backend.
  Without one, the drive is unreachable with that precondition recorded, not
  failed.
- The recorded real local drive uses the packaged CPU build and an isolated
  model cache. GPU acceleration is not available in the current PyPI wheels.
- The video has a caption track. A video without one reaches the fallback and
  needs a key or a local model download, which is a different proof.

- **Caption pull.** Run `.venv/bin/python -m searchts transcribe https://www.youtube.com/watch?v=jNQXAC9IVRw -o artifacts/transcribe/meeting-day.txt > artifacts/transcribe/meeting-day.out 2> artifacts/transcribe/meeting-day.err`. Exit code `0`.
- **Payload.** Open `artifacts/transcribe/meeting-day.txt`. It is longer than 200 characters and contains sentences, not a URL and not an error string.
- **Streams.** Read `artifacts/transcribe/meeting-day.err`, which carries the progress tick, and `artifacts/transcribe/meeting-day.out`, which carries only the confirmation line naming the file written. A progress tick on stdout would be a regression of the rule that progress never lands there.
- **Local file.** Run `.venv/bin/python -m searchts transcribe artifacts/transcribe/meeting-day.txt -o artifacts/transcribe/local.txt`. Exit code `0` and `artifacts/transcribe/local.txt` is non-empty. A non-audio input proves only that the argument is accepted.
- **Proof.** Open `artifacts/transcribe/meeting-day.txt`. It holds recognisable spoken sentences about the video, which is what distinguishes a transcript from a status message.
- **Report an unreachable fallback.** If the caption track is absent, record the provider that was needed and the key that was missing rather than treating the failure as a transcript.
- **Consent, no download.** Run
  `HOME=/tmp/searchts-439-smoke-home SEARCHTS_MODEL_DIR=/tmp/searchts-439-smoke-models .venv-439-py312/bin/python -m searchts transcribe .agents/skills/verify-searchts/artifacts/transcribe/smoke.wav --provider local --json`.
  It exits `1`, writes an `ok: false` JSON object with
  `consent_needed: true`, the 190 MB small model's pinned URL and cache path,
  and `approve_command`; stderr stays separate. Evidence is in
  `artifacts/transcribe/consent.*`.
- **Real engine.** The approval was `--yes` in
  `HOME=/tmp/searchts-439-smoke-home SEARCHTS_MODEL_DIR=/tmp/searchts-439-smoke-models .venv-439-py312/bin/python -m searchts transcribe .agents/skills/verify-searchts/artifacts/transcribe/smoke-clear.wav --provider local --model base --yes --json`.
  It exited `0` with engine `whisper.cpp`, model `base`, device `cpu`,
  and detected language `en`. The 5-second ffmpeg `flite` speech clip was
  transcribed inaccurately as “Oh, this is the speed track combination test.”;
  this drive proves the real inference path and receipt, not recognition
  quality. The default `small` model is selected for accuracy.
- **Model inventory and removal.** `list.stdout.json` reports all three
  models and marks only base cached. The recorded
  `--remove-model base --yes --json` drive exits `0` and removes the model
  plus any partial download from the isolated cache. See
  `artifacts/transcribe/list.*` and `remove.*`.

## Gotchas

- Auto-generated captions can be wrong or in the wrong language. That a
  transcript exists is the proof; its accuracy is not.
- Transcript text has no guaranteed line structure. Do not assert on line counts.
- A missing local model downloads only after a terminal yes or `--yes`. Agents
  must relay the structured consent response and wait for the user.
- Base is faster but less accurate on CPU. Use the small model by default;
  avoid claiming transcript quality from a successful exit alone.
- Never pipe a transcribe into `head`.
- Progress is written to stderr as it happens. A drive that only captures stdout
  will think the command hung.
