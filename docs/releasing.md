# How a version is chosen

searchts is at 0.17.0 in `.release-please-manifest.json`. The number a user installs is semver. release-please reads squash-merge titles on `main`, keeps one release PR, and tags `vX.Y.Z` when that PR merges. The tag is what publishes to PyPI.

A feature PR does not edit a version file. The title is the version decision.

## What the title bumps

release-please takes the highest bump in the commits since the last tag.

| Title | Bump | From 0.17.0 |
| --- | --- | --- |
| `feat(scope):` | minor | 0.18.0 |
| `fix(scope):`, `perf(scope):`, `revert(scope):` | patch | 0.17.1 |
| `feat!:` or `fix!:`, or a `BREAKING CHANGE:` footer | minor, while the manifest is 0.x | 0.18.0 |
| `docs:`, `ci:`, `build:`, `refactor:`, `test:`, `style:`, `chore:` | none | stays 0.17.0 |

`!` after the type marks a break. A footer works too:

```text
BREAKING CHANGE: read --json no longer returns a bare string.
```

While the manifest is below 1.0.0, that break bumps the minor. `.release-please-config.json` sets `bump-minor-pre-major`, so a `!` cannot mint 1.0.0. 1.0.0 is its own decision. It means the read text, the CLI stdout a caller parses, and the MCP tool schemas are stable enough that a break is a major. A new progress UI is a minor. Putting hrefs back on a fallback that already promised links is a patch.

A `RELEASE AS: x.y.z` footer forces the number. Maintainers use it when the title rules would lie. Feature PRs leave it out.

## When to merge the release PR

Feature PRs land on `main` first. Each one updates the same release PR. The version on that PR is the highest bump in the pile.

Merge the release PR when that version is the one a user should install.

- A fix for a bug already on PyPI ships as its own patch when the feature work is still open. Restoring hrefs on the one-line fallback is that kind of fix. People on 0.17.0 should not wait on an unrelated UI change.
- A new progress UI, clickable links, and the command layout are a `feat` and a minor.
- If that fix is still unreleased when the feature merges, they share one minor. The changelog lists the fix under Fixed and the UI under Added. Do not cut 0.17.1 and 0.18.0 in the same sitting for commits that are already both on `main`.
- Do not merge the release PR between two commits of the same change.
- A postplan, a doc, or a test-only PR does not get a release.

There is one release PR. Do not open a second one.

## Files a feature PR leaves alone

release-please writes these when the release PR merges:

- `pyproject.toml` (`version`)
- `searchts/__init__.py` (`__version__`, marker `x-release-please-version`)
- `server.json` (`version` and `packages[0].version`)
- `.release-please-manifest.json`
- `CHANGELOG.md`

## Who merges

The author babysits the feature PR (CI, review, conflicts). A maintainer merges it once that is done, then merges the release PR under the rules above. Authors do not merge the release PR.

The release PR runs the Ubuntu, Windows, and macOS test jobs. Merge it when those are green. The push to main runs them again, plus the other Python versions. A green Ubuntu job is not enough. The 0.17.0 release PR was green and the Windows file-URI tests failed on main.
