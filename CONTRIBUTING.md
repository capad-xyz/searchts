# Contributing to searchts

Thank you for your interest in contributing to searchts! This document provides guidelines and instructions for contributing.

## Getting Started

1. Fork the repository on GitHub
2. Clone your fork locally
3. Create a new branch for your contribution
4. Make your changes
5. Run tests and linting
6. Submit a pull request

## Development Setup

```bash
# Clone your fork
git clone https://github.com/capad-xyz/searchts.git
cd searchts

# Install in development mode, against the tested dependency set CI uses
pip install -c constraints.txt -e ".[dev]"
```

## Code Style

We use the following tools to maintain code quality:

- **ruff**: Linting and import sorting
- **mypy**: Type checking
- **pytest**: Testing

CI gates on all three, so run them before submitting a PR:

```bash
ruff check searchts tests
mypy searchts
pytest -q
```

Note there is no `ruff format` step. The tree is deliberately not
ruff-format-clean, and running it would rewrite most files — which collides
with the rule below about unrelated reformatting. Match the style of the code
around your change instead.

## Adding New Channels

searchts uses a unified channel interface. To add a new platform:

1. Create a new file in `searchts/channels/`
2. Implement the channel contract (see existing channels for examples)
3. Add tests in `tests/test_channels.py`
4. Update `searchts/doctor.py` to include the new channel
5. Update documentation

## Pull Request Guidelines

- **Small, focused changes** are preferred over large refactors
- Include tests for new functionality
- Update documentation if needed
- Follow existing code style
- Reference any related issues

**Title your PR as a conventional commit** (`type(scope): message`). PRs are
squash-merged, so the title becomes the commit message on `main`, and release
tooling reads it: a `feat:` cuts a minor release and a `fix:` cuts a patch one,
while `ci:`, `docs:`, `test:`, `refactor:` and `chore:` ship silently with the
next release. Maintainers cut releases by merging the standing release PR, so
please do not bump version numbers in your PR.

## What we merge (and what we don't)

searchts has a deliberately narrow identity: a **keyless, free, open-source** web layer for AI
agents. That focus is the whole point, so we're intentionally selective about what we take on.

**We're glad to merge:**

- Working code that improves the core — `read` / `search` / `transcribe` / `grab`, the unlocker, or
  its reliability — with tests.
- Bug fixes, docs, and new cases for the unlocker benchmark.
- Small, focused changes in preference to large refactors.

### Writing fetch block phrases

Block phrases decide whether the unlocker escalates to another backend, so false positives silently
turn successful reads into slower retries. Prefer the narrowest stable text from the challenge page:
`checking if the site connection is secure` identifies a specific interstitial, while a bare
`blocked` can appear in legitimate articles and must not be used.

For every phrase added to `_BLOCK_PHRASES`, add both a positive fixture that matches the real
challenge and a negative near-miss that stays clean. Keep fixtures focused on the distinguishing
wording rather than copying an entire vendor page. When a backend fetches through a relay, report
the URL the user requested in results and diagnostics, not the relay's wire URL.

**We generally won't merge:**

- **Backends that only register a name.** A new integration has to actually *do* the thing (read,
  search, return content) — not just add a config key or a `doctor` entry for a service.
- **First-class dependencies on paid, keyed third-party APIs.** They cut against the keyless-first
  promise. A bring-your-own-key extra may be considered, but a paid service is never a default or a
  headline backend.
- **Changes tied to promotion.** We decide on technical merit alone — please don't offer (or expect)
  a shout-out, cross-post, or link exchange in return. No hard feelings; we just keep that separate.
- **Unrelated reformatting bundled into a feature PR.** One change per PR keeps review honest.

If you're unsure whether an idea fits, open an issue first — we'd rather help you shape it before you
write the code.

## Reporting Issues

When reporting bugs, please include:

- Python version
- Operating system
- Steps to reproduce
- Expected vs actual behavior
- Any error messages

## Questions?

Open an issue or a discussion on GitHub, or reach out at oss@capad.fyi.
