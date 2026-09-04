# Release notes

GitHub releases use the versioned Markdown files in this directory. Keep these
notes concise and user-facing; `CHANGELOG.md` remains the detailed development
record.

For every release:

1. Add `vX.Y.Z.md`, matching the version in
   `custom_components/fluvalble/manifest.json`.
2. Start the file with `# Fluval BLE vX.Y.Z`.
3. Summarize the most important features, fixes, entity changes, and upgrade
   instructions in fixture and Home Assistant terminology.
4. Link to the full tag comparison or technical reference instead of copying
   packet identifiers and implementation history into the release body.
5. Review the file rendered on GitHub before pushing the release tag.

The promotion and release workflows reject a version whose curated notes file
is missing or has the wrong heading.
