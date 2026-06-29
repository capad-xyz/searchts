# Demo recordings

The README GIFs are recorded with [vhs](https://github.com/charmbracelet/vhs).

- `demo1.tape` - the hero: a staged Claude Code session. The agent's built-in `Fetch` is blocked (HTTP 403, Cloudflare), so it routes through searchts (already installed), reads the page, and answers the user's question. Drives `claude1.sh`.
- `claude1.sh` - the staged agent narration used by `demo1.tape`; the narration is illustrative but the `searchts read` it runs is a real call.
- `demo2.tape` - the install, also a staged Claude Code session: the agent adds searchts as an MCP server (`searchts mcp install`) and a Claude Code skill (`searchts skill install`), then verifies it with a real read. Drives `claude2.sh`.
- `claude2.sh` - the staged agent narration for `demo2.tape`; the install commands and the page read it runs are real.
- `bg.png` - the gradient backdrop used as `MarginFill`.
- `Dockerfile` - layers Python + searchts (and JetBrainsMono Nerd Font, for the Claude Code `⏺`/`⎿` glyphs) onto the official vhs image, since vhs (ttyd) does not run natively on Windows and searchts needs Python in the recording shell.

The commands in the tapes run for real, so the output is genuine.

## Regenerate

```bash
docker build -t searchts-vhs .

# record to mp4 (so we can add the zoom pass)
docker run --rm -v "$PWD:/vhs" searchts-vhs demo1.tape
docker run --rm -v "$PWD:/vhs" searchts-vhs demo2.tape

# cinematic zoom + slight speed-up, then a palette-optimized GIF (demo1 is 1480x880)
ffmpeg -i demo1.mp4 -vf "zoompan=z='min(zoom+0.00014,1.08)':d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':fps=25:s=1480x880,format=yuv420p" -c:v libx264 demo1_zoom.mp4
ffmpeg -i demo1_zoom.mp4 -vf "setpts=PTS/1.3,fps=15,scale=1080:-1:flags=lanczos,palettegen=stats_mode=diff" palette1.png
ffmpeg -i demo1_zoom.mp4 -i palette1.png -lavfi "setpts=PTS/1.3,fps=15,scale=1080:-1:flags=lanczos[x];[x][1:p]paletteuse=dither=bayer:bayer_scale=3" demo1.gif
```

`demo2.gif` is produced the same way (a 1400x880 frame).
