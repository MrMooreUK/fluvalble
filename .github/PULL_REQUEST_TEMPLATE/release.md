## Release: dev → master

**Version:** <!-- e.g. 0.0.4 -->

## Pre-merge checklist
- [ ] All CI checks pass on `dev`
- [ ] `manifest.json` version matches the intended release version
- [ ] `CHANGELOG.md` has an entry for this version with today's date
- [ ] Manually tested on a real Fluval light (or all changes are non-functional)
- [ ] No debug/temporary code left in

## Post-merge steps
1. Tag master: `git tag v0.0.X && git push origin v0.0.X`
2. The release workflow will automatically create a GitHub Release with the zip asset
3. HACS users will see the update within 24 hours

## What's included
<!-- Paste the relevant CHANGELOG section here for quick review -->
