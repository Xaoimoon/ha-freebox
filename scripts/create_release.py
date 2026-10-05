"""Creates a Forgejo release via the REST API. Called by the release
workflow (.forgejo/workflows/release.yml) after bump_version.py has tagged
a new version — not part of the Home Assistant integration itself.

Reads the release body from a file (see bump_version.py's release_notes.md)
and posts it to POST /api/v1/repos/{owner}/{repo}/releases using stdlib only
(no `requests` dependency needed for one API call).
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", required=True, help="e.g. https://brokk.xaoimoon.fr")
    parser.add_argument("--repo", required=True, help="e.g. xaoimoon/ha-freebox")
    parser.add_argument("--token", required=True)
    parser.add_argument("--tag", required=True, help="e.g. v0.2.0")
    parser.add_argument("--notes-file", type=Path, required=True)
    args = parser.parse_args()

    body = args.notes_file.read_text(encoding="utf-8") if args.notes_file.exists() else ""
    payload = json.dumps(
        {
            "tag_name": args.tag,
            "name": args.tag,
            "body": body,
            "draft": False,
            "prerelease": False,
        }
    ).encode("utf-8")

    request = urllib.request.Request(
        url=f"{args.server}/api/v1/repos/{args.repo}/releases",
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"token {args.token}",
        },
    )

    try:
        with urllib.request.urlopen(request) as response:
            print(f"Release created: HTTP {response.status}")
    except urllib.error.HTTPError as err:
        print(f"Failed to create release: HTTP {err.code} {err.reason}", file=sys.stderr)
        print(err.read().decode("utf-8", errors="replace"), file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
