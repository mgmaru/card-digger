#!/usr/bin/env python3
"""Check relative links, heading anchors and code fences in the Markdown files.

Every document cross-references the others, so a renamed heading silently breaks
navigation. This runs in CI and needs no network access.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SEARCH_PATHS = ("README.md", "docs", "poc", "src")
LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
HEADING = re.compile(r"^(#{1,6})\s+(.+)$")
EXTERNAL = ("http://", "https://", "mailto:")


def slug(heading: str) -> str:
    """Approximate GitHub's heading anchor."""
    lowered = heading.strip().lower()
    stripped = re.sub(r"[^\w\s\-぀-ヿ一-鿿]", "", lowered)
    return stripped.replace(" ", "-")


def headings(text: str) -> list[str]:
    found: list[str] = []
    inside_fence = False
    for line in text.splitlines():
        if line.startswith("```"):
            inside_fence = not inside_fence
            continue
        if inside_fence:
            continue
        match = HEADING.match(line)
        if match:
            found.append(match.group(2))
    return found


def markdown_files() -> list[Path]:
    files: list[Path] = []
    for entry in SEARCH_PATHS:
        target = REPO_ROOT / entry
        if target.is_file() and target.suffix == ".md":
            files.append(target)
        elif target.is_dir():
            files.extend(sorted(target.rglob("*.md")))
    return sorted(set(files))


def main() -> int:
    files = markdown_files()
    anchors = {
        path.resolve(): {slug(h) for h in headings(path.read_text(encoding="utf-8"))}
        for path in files
    }

    problems: list[str] = []
    for path in files:
        text = path.read_text(encoding="utf-8")
        relative = path.relative_to(REPO_ROOT)

        if text.count("```") % 2:
            problems.append(f"{relative}: unbalanced code fence")

        for match in LINK.finditer(text):
            link = match.group(1)
            if link.startswith(EXTERNAL):
                continue
            file_part, _, fragment = link.partition("#")
            target = (path.parent / file_part).resolve() if file_part else path.resolve()

            if not target.exists():
                problems.append(f"{relative}: missing file -> {link}")
                continue
            if fragment and target.suffix == ".md":
                if fragment not in anchors.get(target, set()):
                    problems.append(f"{relative}: missing anchor -> {link}")

    print(f"checked {len(files)} markdown files")
    for problem in problems:
        print(f"NG {problem}")
    if problems:
        print(f"{len(problems)} problem(s) found")
        return 1
    print("all relative links, anchors and code fences are valid")
    return 0


if __name__ == "__main__":
    sys.exit(main())
