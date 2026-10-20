# Video transcription

Subtitles-first transcripts for YouTube, TikTok, Instagram, Reddit, and X videos.

## Transcribe a video (`searchts transcribe`)

```bash
# Subtitles-first: returns the video's existing captions when present
# (no API key, no audio download, no model), else falls back to Whisper.
searchts transcribe "https://www.youtube.com/watch?v=VIDEO_ID"
searchts transcribe ./local_audio.mp3 -o /tmp/transcript.txt

# Force audio transcription, skipping any existing captions:
searchts transcribe "https://www.youtube.com/watch?v=VIDEO_ID" --no-subtitles
```

**Use case**: the audio, when `searchts read` says a player page has no
captions, or when the source is a local file. `searchts transcribe` tries
existing captions first (pulled via yt-dlp), so a captioned URL (most YouTube
videos, many TikToks) transcribes with NO key and NO local model. Works for
YouTube, TikTok, Instagram, Reddit, and X videos. A watch URL, a TikTok video,
an Instagram reel, a `v.redd.it` file, or an X post that has a video is a
player page: `searchts read` returns its captions, or fails and names this
command. An X post with no video is still a read of the page.

> Only a video without usable subtitles (or `--no-subtitles`) needs a Whisper
> backend: configure a key first with `searchts configure groq-key gsk_xxx`
> (free, console.groq.com) or `searchts configure openai-key sk-xxx` (auto mode
> falls back from groq to openai), or `pip install "searchts[local-transcribe]"`
> for keyless local transcription.

## Reading the page

`searchts read <url>` on a player page returns the captions, or fails and
names `searchts transcribe` for the audio. A channel, a feed, a Reddit
thread, an X profile, or an X post with no video is not a player page; read
those as pages.

## Choosing a tool

| Use case | Recommended tool |
|-----|---------|
| Captions on a player page | `searchts read <url>` |
| Audio, when that read found no captions, or a local file | `searchts transcribe <url>` or MCP `transcribe` |
| A channel, a feed, or a thread that is not one video | `searchts read <url>` |
