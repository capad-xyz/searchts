# Demo recording

The hero GIF in the project README is recorded with [vhs](https://github.com/charmbracelet/vhs).

- `demo.tape` - the vhs script (commands, theme, timing, the gradient backdrop).
- `bg.png` - the gradient backdrop used as `MarginFill`.
- `Dockerfile` - layers Python + searchts onto the official vhs image, since vhs (ttyd) does not run natively on Windows and searchts needs Python in the recording shell.

## Regenerate

```bash
docker build -t searchts-vhs .
docker run --rm -v "$PWD:/vhs" searchts-vhs demo.tape
```

This produces `demo.gif`. The tape runs `searchts read` and `searchts search` for real, so the output is genuine.
