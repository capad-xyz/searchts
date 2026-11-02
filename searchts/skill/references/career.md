# Jobs & recruiting

LinkedIn.

## Primary: read the public URL

For a LinkedIn profile, company page, or job posting, read the public URL
directly:

```bash
searchts read "https://www.linkedin.com/in/username"
searchts read "https://www.linkedin.com/jobs/view/123456"
```

`searchts read` runs the escalating unlocker, so it gets through most bot-walls
keylessly. To find people, companies, or jobs, use `searchts search` and read
the URLs it returns.

When LinkedIn shows a login wall:

```bash
searchts login check linkedin.com
searchts login check linkedin.com --url https://www.linkedin.com/feed/
searchts login signin https://www.linkedin.com
searchts login keep https://www.linkedin.com --cookies-from-browser firefox --yes
```

Never copy a browser login without the user's yes. `login check` proves no login
wall, not which account is signed in.

## Optional: LinkedIn scraper (MCP)

`searchts read` already reads profiles, companies, posts and people search
natively with a kept login. The `linkedin-scraper-mcp` bridge is an optional
fallback for the feed and for write/inbox tools; it is not part of the
first-pass install.

```bash
searchts install --only linkedin
mcporter call 'linkedin-scraper.get_person_profile(linkedin_url: "https://linkedin.com/in/username")'
mcporter call 'linkedin-scraper.search_jobs(keyword: "software engineer", limit: 10)'
```

> Needs a valid logged-in session. If it is unavailable, just
> `searchts read` the public URL.
