# PLAN.md restore staging for #199

Full fixed PLAN is zlib+base64 in `*.b64` (concat in order, zlib decompress).
Local authoritative copy: `/tmp/plan199_fixed.md` on the agent box.

Parent: `create_or_update_file` PLAN.md with content=`$file:/tmp/plan199_fixed.md` (needs review-pipeline $file expansion), sha=`fb3a73aab92a089aa63f5a9cab85fc76802a247b`, then delete `.plan199-restore/` and size-test probe files.
