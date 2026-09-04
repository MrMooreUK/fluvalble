"""Tests for curated GitHub release notes."""

import json
from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_current_version_has_curated_release_notes():
    manifest = json.loads((ROOT / "custom_components" / "fluvalble" / "manifest.json").read_text(encoding="utf-8"))
    version = manifest["version"]
    notes_path = ROOT / "docs" / "releases" / f"v{version}.md"

    assert notes_path.is_file()
    assert notes_path.read_text(encoding="utf-8").startswith(f"# Fluval BLE v{version}\n")


def test_release_workflow_publishes_curated_notes_not_changelog():
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")

    assert 'notes_path="docs/releases/v${{ steps.version.outputs.version }}.md"' in workflow
    assert "body_path: /tmp/release_notes.md" in workflow
    assert "Extract changelog for this release" not in workflow
    assert 'open("CHANGELOG.md")' not in workflow
