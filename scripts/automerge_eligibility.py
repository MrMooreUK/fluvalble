#!/usr/bin/env python3
"""Fail closed: allowlisted author + no dangerous new code + BLE packet path gate."""

from __future__ import annotations

import os
import re
import subprocess
import sys

ALLOWLIST = {
    "MrMooreUK",
    "dependabot[bot]",
    "github-actions[bot]",
}

DANGEROUS = re.compile(
    r"(?:"
    r"\bsubprocess\b|"
    r"\bos\.system\b|"
    r"\bos\.popen\b|"
    r"\bos\.spawn|"
    r"\beval\s*\(|"
    r"\bexec\s*\(|"
    r"\b__import__\s*\(|"
    r"\bimportlib\b|"
    r"\bsocket\s*\.|"
    r"\baiohttp\b|"
    r"\brequests\s*\.|"
    r"\burllib\b|"
    r"\bhttp\.client\b|"
    r"\basyncio\.create_subprocess|"
    r"shell\s*=\s*True|"
    r"\bpty\b|"
    r"\bctypes\b"
    r")"
)

BLE_PATHS = (
    "custom_components/fluvalble/core/discovery.py",
    "custom_components/fluvalble/core/protocol.py",
    "custom_components/fluvalble/core/client.py",
)

TYPE_OR_COMMENT = re.compile(
    r"^\s*(?:#|from\s+typing\s+import|import\s+typing|from\s+__future__\s+import|pass\s*$)"
)

UUID_OR_PACKET = re.compile(
    r"(?:"
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}|"
    r"\bUUID\b|"
    r"_packet\b|"
    r"build_.*packet|"
    r"encode_|"
    r"decode_|"
    r"FACEBD|facebd|"
    r"\bGATT\b|"
    r"characteristic"
    r")",
    re.I,
)


def main() -> int:
    author = os.environ.get("AUTHOR", "")
    base = os.environ["BASE"]
    head = os.environ["HEAD"]

    if author not in ALLOWLIST:
        print(
            f"::error::Automerge blocked: author '{author}' is not on the allowlist "
            f"({', '.join(sorted(ALLOWLIST))}). Manual Dev review required."
        )
        return 1

    diff = subprocess.check_output(
        ["git", "diff", "--unified=0", f"{base}...{head}"], text=True
    )
    added_by_file: dict[str, list[str]] = {}
    current = None
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            current = line[6:]
            added_by_file.setdefault(current, [])
            continue
        if current is None:
            continue
        if line.startswith("+") and not line.startswith("+++"):
            added_by_file[current].append(line[1:])

    failures: list[str] = []

    for path, lines in added_by_file.items():
        if not path.endswith(".py"):
            continue
        for text in lines:
            if DANGEROUS.search(text):
                failures.append(
                    f"{path}: dangerous pattern in new line: {text.strip()[:120]}"
                )

    for path in BLE_PATHS:
        lines = added_by_file.get(path, [])
        substantive = [
            t
            for t in lines
            if t.strip() and not TYPE_OR_COMMENT.match(t)
        ]
        if not substantive:
            continue
        # Fail closed on any substantive change to BLE packet paths.
        failures.append(
            f"{path}: substantive change requires Dev+Bob review "
            f"({len(substantive)} new non-type line(s)); no auto-merge."
        )

    if failures:
        for item in failures:
            print(f"::error::{item}")
        print("::error::Automerge eligibility failed. Fix or request manual @Dev review.")
        return 1

    print(f"Automerge eligibility OK for allowlisted author {author}")
    # silence unused lint for UUID helper kept for future tightening
    _ = UUID_OR_PACKET
    return 0


if __name__ == "__main__":
    sys.exit(main())
