# Demo recordings

The README GIFs are recorded with [vhs](https://github.com/charmbracelet/vhs).

- `demo1.tape` - the hero: read a Cloudflare-walled page as clean Markdown, plus a keyless search.
- `demo2.tape` - a staged Claude Code agent loop: the agent's built-in fetch is blocked (HTTP 403), it installs the `/searchts` skill on demand, retries through it, and answers. Drives `claude.sh`.
- `claude.sh` - the staged agent narration used by `demo2.tape`; the narration is illustrative but the `searchts skill install` and page read it runs are real.
- `bg.png` - the gradient backdrop used as `MarginFill`.
- `Dockerfile` - layers Python + searchts onto the official vhs image, since vhs (ttyd) does not run natively on Windows and searchts needs Python in the recording shell.

The commands in the tapes run for real, so the output is genuine.

## Regenerate

```bash
docker build -t searchts-vhs .

# record to mp4 (so we can add the zoom pass)
docker run --rm -v "$PWD:/vhs" searchts-vhs demo1.tape
docker run --rm -v "$PWD:/vhs" searchts-vhs demo2.tape

# cinematic zoom + slight speed-up, then a palette-optimized GIF
ffmpeg -i demo1.mp4 -vf "zoompan=z='min(zoom+0.00013,1.08)':d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':fps=25:s=1400x760,format=yuv420p" -c:v libx264 demo1_zoom.mp4
ffmpeg -i demo1_zoom.mp4 -vf "setpts=PTS/1.25,fps=15,scale=1040:-1:flags=lanczos,palettegen=stats_mode=diff" palette1.png
ffmpeg -i demo1_zoom.mp4 -i palette1.png -lavfi "setpts=PTS/1.25,fps=15,scale=1040:-1:flags=lanczos[x];[x][1:p]paletteuse=dither=bayer:bayer_scale=3" demo1.gif
```

`demo2.gif` is produced the same way (the tape uses a 1400x800 frame and a 1.4x speed-up).
