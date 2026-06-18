# Developer tools

GitHub.

## Primary: read the public URL

For a repo, file, issue, or PR, read the public URL directly:

```bash
searchts read "https://github.com/owner/repo"
searchts read "https://github.com/owner/repo/issues/123"
```

To find repos or code, use `searchts search "<query>"` and read the URLs it
returns. `searchts read` runs the escalating unlocker and returns clean
markdown.

## Optional: GitHub CLI (gh)

If `gh` is installed and authenticated, it is a convenient enhancement for
structured GitHub work (it is not required — `searchts read` covers reading).
Run `searchts doctor` to see whether it is present.

```bash
# Search
gh search repos "query" --sort stars --limit 10
gh search code "query" --language python

# Repos / issues / PRs
gh repo view owner/repo
gh issue list -R owner/repo --state open
gh pr view 123 -R owner/repo

# Actions / CI
gh run list --repo owner/repo --limit 10
gh run view <run-id> --repo owner/repo --log-failed

# API / JSON
gh api repos/owner/repo
gh issue list --repo owner/repo --json number,title --jq '.[] | "\(.number): \(.title)"'
```
