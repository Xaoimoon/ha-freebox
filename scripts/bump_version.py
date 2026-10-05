"""Computes the next SemVer version from Conventional Commits and bumps
custom_components/freebox_os/manifest.json accordingly.

Not part of the Home Assistant integration itself — run by the release
workflow (.forgejo/workflows/release.yml) on every push to main. Can also be
run manually to preview the next version:

    python scripts/bump_version.py --dry-run

Bump rules (Conventional Commits, since the last "vX.Y.Z" tag):
  - a "BREAKING CHANGE:" footer, or "!" right before the ":" in the header
    (e.g. "feat!: ...") -> major
  - "feat: ..." -> minor
  - "fix: ..." or "perf: ..." -> patch
  - anything else (docs, chore, refactor, test, ci, build, style, revert)
    does not trigger a release on its own

The highest bump level found across all commits since the last tag wins. If
none of the commits are release-worthy, no version bump happens.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = REPO_ROOT / "custom_components" / "freebox_os" / "manifest.json"

TAG_PATTERN = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
HEADER_PATTERN = re.compile(r"^(?P<type>\w+)(\([^)]*\))?(?P<breaking>!)?:\s")
BUMP_ORDER = {"patch": 0, "minor": 1, "major": 2}

# Unlikely to appear in a real commit message; used to split `git log`
# records that may contain multi-line subjects/bodies. Deliberately not
# \x1c-\x1f: Python's str.strip() treats those as whitespace and silently
# swallows them, corrupting the split.
RECORD_SEP = "\x02"
FIELD_SEP = "\x01"


def run(*args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def get_last_tag() -> str | None:
    output = run("tag", "--list", "v[0-9]*.[0-9]*.[0-9]*", "--sort=-v:refname")
    tags = [line for line in output.splitlines() if TAG_PATTERN.match(line)]
    return tags[0] if tags else None


def get_commits_since(tag: str | None) -> list[tuple[str, str]]:
    """Return (subject, body) pairs for every commit since `tag` (or all
    history if there is no previous tag)."""
    range_arg = f"{tag}..HEAD" if tag else "HEAD"
    output = run(
        "log",
        range_arg,
        f"--format={FIELD_SEP}%s{FIELD_SEP}%b{RECORD_SEP}",
    )
    commits = []
    for record in output.split(RECORD_SEP):
        record = record.strip()
        if not record:
            continue
        _, subject, body = record.split(FIELD_SEP)
        commits.append((subject.strip(), body.strip()))
    return commits


def classify_bump(commits: list[tuple[str, str]]) -> str | None:
    highest: str | None = None
    for subject, body in commits:
        match = HEADER_PATTERN.match(subject)
        if not match:
            continue
        level: str | None
        if match.group("breaking") or "BREAKING CHANGE:" in body or "BREAKING-CHANGE:" in body:
            level = "major"
        elif match.group("type") == "feat":
            level = "minor"
        elif match.group("type") in ("fix", "perf"):
            level = "patch"
        else:
            level = None
        if level and (highest is None or BUMP_ORDER[level] > BUMP_ORDER[highest]):
            highest = level
    return highest


def bump_semver(tag: str | None, level: str) -> str:
    if tag:
        major, minor, patch = (int(part) for part in TAG_PATTERN.match(tag).groups())
    else:
        major, minor, patch = 0, 0, 0
    if level == "major":
        major, minor, patch = major + 1, 0, 0
    elif level == "minor":
        minor, patch = minor + 1, 0
    else:
        patch += 1
    return f"{major}.{minor}.{patch}"


def update_manifest(new_version: str) -> None:
    text = MANIFEST_PATH.read_text(encoding="utf-8")
    updated, count = re.subn(
        r'"version":\s*"\d+\.\d+\.\d+"',
        f'"version": "{new_version}"',
        text,
    )
    if count != 1:
        raise RuntimeError(
            f'Expected exactly one "version" field in {MANIFEST_PATH}, found {count}'
        )
    MANIFEST_PATH.write_text(updated, encoding="utf-8")


def build_release_notes(commits: list[tuple[str, str]]) -> str:
    lines = [subject for subject, _ in commits if HEADER_PATTERN.match(subject)]
    return "\n".join(f"- {line}" for line in lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="Print the result without writing anything"
    )
    parser.add_argument(
        "--github-output",
        help="Path to append GitHub/Forgejo Actions-style step outputs to",
    )
    args = parser.parse_args()

    last_tag = get_last_tag()
    commits = get_commits_since(last_tag)
    bump = classify_bump(commits)

    if bump is None:
        print("No release-worthy commits since", last_tag or "the beginning of history")
        if args.github_output:
            with open(args.github_output, "a", encoding="utf-8") as fh:
                fh.write("should_release=false\n")
        return 0

    new_version = bump_semver(last_tag, bump)
    notes = build_release_notes(commits)

    print(f"Bump: {bump} ({last_tag or 'v0.0.0'} -> v{new_version})")
    print(notes)

    if not args.dry_run:
        update_manifest(new_version)

    if args.github_output:
        with open(args.github_output, "a", encoding="utf-8") as fh:
            fh.write("should_release=true\n")
            fh.write(f"version={new_version}\n")
            fh.write(f"tag=v{new_version}\n")

    notes_path = REPO_ROOT / "release_notes.md"
    if not args.dry_run:
        notes_path.write_text(notes + "\n", encoding="utf-8")

    return 0


if __name__ == "__main__":
    sys.exit(main())
