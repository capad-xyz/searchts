# Video / podcasts

Subtitles and transcripts for YouTube.

## YouTube (yt-dlp)

### Get video metadata

```bash
yt-dlp --dump-json "URL"
```

### Download subtitles

```bash
# Download subtitles (without downloading the video)
yt-dlp --write-sub --write-auto-sub --sub-lang "zh-Hans,zh,en" --skip-download -o "/tmp/%(id)s" "URL"

# Then read the .vtt file
cat /tmp/VIDEO_ID.*.vtt
```

### Get comments

```bash
# Extract comments (best-effort, completeness not guaranteed)
yt-dlp --write-comments --skip-download --write-info-json \
  --extractor-args "youtube:max_comments=20" \
  -o "/tmp/%(id)s" "URL"
# Comments are in the comments field of the .info.json
```

### Search videos

```bash
yt-dlp --dump-json "ytsearch5:query"
```

> **Subtitle note**: manually uploaded subtitles extract reliably; auto-generated subtitles may have line-to-line duplication and need post-processing.
> **Comment note**: `--write-comments` is based on web scraping (not the YouTube Data API), so some comments may be missing.

### No-subtitle fallback: Whisper audio transcription

```bash
# Fallback when a video has no subtitles: download the audio and transcribe with Whisper (a free Groq key is enough)
searchts transcribe "https://www.youtube.com/watch?v=VIDEO_ID"
searchts transcribe ./local_audio.mp3 -o /tmp/transcript.txt
```

> Configure a key first: `searchts configure groq-key gsk_xxx` (free, console.groq.com)
> or `searchts configure openai-key sk-xxx`. The default auto mode falls back from groq to openai on failure.

## Choosing a tool

| Use case | Recommended tool |
|-----|---------|
| YouTube subtitles | yt-dlp |
| Audio/video without subtitles | searchts transcribe |
