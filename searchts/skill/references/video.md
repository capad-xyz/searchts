# Video transcription

Subtitles-first transcripts for YouTube, TikTok, Instagram, and Reddit videos.

## Transcribe a video (`searchts transcribe`)

```bash
# Subtitles-first: returns the video's existing captions when present
# (no API key, no audio download, no model), else falls back to Whisper.
searchts transcribe "https://www.youtube.com/watch?v=VIDEO_ID"
searchts transcribe ./local_audio.mp3 -o /tmp/transcript.txt

# Force audio transcription, skipping any existing captions:
searchts transcribe "https://www.youtube.com/watch?v=VIDEO_ID" --no-subtitles
```

**Use case**: the primary way to get a transcript. `searchts transcribe` tries
existing captions first (pulled via yt-dlp), so a captioned URL (most YouTube
videos, many TikToks) transcribes with NO key and NO local model. Works for
YouTube, TikTok, Instagram, and Reddit videos.

> Only a video without usable subtitles (or `--no-subtitles`) needs a Whisper
> backend: configure a key first with `searchts configure groq-key gsk_xxx`
> (free, console.groq.com) or `searchts configure openai-key sk-xxx` (auto mode
> falls back from groq to openai), or `pip install "searchts[local-transcribe]"`
> for keyless local transcription.

## Reading the page instead

To read a video's description, title, or comments as text (rather than a
transcript), use `searchts read <url>` on the public URL.

## Choosing a tool

| Use case | Recommended tool |
|-----|---------|
| Video transcript / captions | `searchts transcribe <url>` |
| Video page text (title, description) | `searchts read <url>` |
