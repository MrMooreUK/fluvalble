## Release: dev → master

**Version:** <!-- e.g. 0.0.4 -->

## Pre-merge checklist
- [ ] All CI checks pass on `dev`
- [ ] `manifest.json` version matches the intended release version
- [ ] `CHANGELOG.md` has an entry for this version with today's date
- [ ] `docs/releases/vX.Y.Z.md` contains concise, user-facing release notes
- [ ] The rendered release notes were reviewed before tagging
- [ ] Manually tested on a real Fluval light (or all changes are non-functional)
- [ ] No debug/temporary code left in

## Post-merge steps
1. Tag main: `git tag vX.Y.Z && git push origin vX.Y.Z`
2. The release workflow will publish `docs/releases/vX.Y.Z.md` and attach the zip asset
3. HACS users will see the update within 24 hours

## What's included
<!-- Summarize the release and link to the rendered docs/releases/vX.Y.Z.md file. -->
