# searchts.capad.fyi

Static landing page for searchts, deployed to Cloudflare Pages by
[`.github/workflows/site.yml`](../.github/workflows/site.yml) on every push to
`main` that touches `site/**`. No build step — the directory is deployed as-is.

## One-time setup

1. **Create the Pages project** (once, from a machine with wrangler auth):

   ```bash
   npx wrangler pages project create searchts --production-branch=main
   ```

2. **Add repo secrets** (GitHub → Settings → Secrets and variables → Actions):
   - `CLOUDFLARE_API_TOKEN` — token with the *Cloudflare Pages: Edit* permission
   - `CLOUDFLARE_ACCOUNT_ID` — from the Cloudflare dashboard sidebar

3. **Attach the custom domain**: Cloudflare dashboard → Workers & Pages →
   `searchts` → Custom domains → add `searchts.capad.fyi`. Since capad.fyi is
   already on Cloudflare, the CNAME record is created automatically.

## Local preview

```bash
python -m http.server -d site 8080
```
