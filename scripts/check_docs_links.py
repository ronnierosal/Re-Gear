"""Check local Markdown paths and docs/INDEX.md reachability without dependencies.

Scans repository-root Markdown and docs recursively (including archives). Checks
inline/reference links and images; ignores fenced/inline code and HTML comments.
Fragments and external URLs are deliberately not validated. This is a bounded
Markdown link checker, not a full CommonMark renderer or a network link crawler.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit


def visible_markdown(text: str) -> str:
    """Mask code/comments while preserving offsets for line-number diagnostics."""
    def mask(match: re.Match[str]) -> str:
        return re.sub(r"[^\n]", " ", match.group())

    text = re.sub(r"<!--[\s\S]*?-->", mask, text)
    lines = text.splitlines(keepends=True)
    fence = None
    for index, line in enumerate(lines):
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
        if fence:
            if marker and marker[1][0] == fence[0] and len(marker[1]) >= len(fence) and not marker[2].strip():
                fence = None
            lines[index] = re.sub(r"[^\n]", " ", line)
        elif marker:
            fence = marker[1]
            lines[index] = re.sub(r"[^\n]", " ", line)
    return re.sub(r"(?<!`)(`+)(?!`)[\s\S]*?(?<!`)\1(?!`)", mask, "".join(lines))


def destination(value: str) -> str:
    """Read a destination, excluding its optional Markdown title."""
    value = value.strip()
    if value.startswith("<"):
        end = value.find(">")
        return value[1:end] if end >= 0 else value[1:]
    return re.split(r"(?<!\\)\s", value, maxsplit=1)[0]


def links(text: str) -> list[tuple[int, str]]:
    """Return (line number, destination) pairs for visible links/images."""
    text = visible_markdown(text)
    result: list[tuple[int, str]] = []
    definitions: dict[str, str] = {}
    def key(label: str) -> str:
        return " ".join(label.split()).casefold()

    def definition(match: re.Match[str]) -> str:
        target = destination(match[2])
        definitions[key(match[1])] = target
        return re.sub(r"[^\n]", " ", match.group())

    text = re.sub(r"^ {0,3}\[([^]\n]+)\]:[ \t]*(.+)$", definition, text, flags=re.MULTILINE)
    # Keep backticks in an inline link label harmless: visible_markdown masks
    # them, but the surrounding [] and destination remain intact.
    pattern = re.compile(r"(?<!\\)\[([^]\n]*)\]")
    offset = 0
    while match := pattern.search(text, offset):
        end = match.end()
        target = None
        if text[end:end + 1] == "(":
            cursor, depth, angled = end + 1, 1, False
            while cursor < len(text):
                char = text[cursor]
                if char == "\\":
                    cursor += 2
                    continue
                if char == "<":
                    angled = True
                elif char == ">":
                    angled = False
                elif not angled and char == "(":
                    depth += 1
                elif not angled and char == ")":
                    depth -= 1
                    if depth == 0:
                        target = destination(text[end + 1:cursor])
                        end = cursor + 1
                        break
                cursor += 1
        elif text[end:end + 1] == "[":
            reference = pattern.match(text, end)
            if reference:
                target = definitions.get(key(reference[1] or match[1]))
                end = reference.end()
        else:
            target = definitions.get(key(match[1]))
        if target is not None:
            result.append((text.count("\n", 0, match.start()) + 1, target))
        offset = end
    return result


def resolve_local(root: Path, source: Path, target: str) -> tuple[Path | None, str | None]:
    target = re.sub(r"\\([!\"#$%&'()*+,\-./:;<=>?@\[\]\\^_`{|}~])", r"\1", target)
    try:
        parsed = urlsplit(target)
    except ValueError:
        return None, "malformed URL"
    if parsed.scheme or parsed.netloc or not parsed.path:
        return None, None
    path = unquote(parsed.path)
    candidate = Path(os.path.abspath(root / path.lstrip("/") if path.startswith("/") else source.parent / path))
    try:
        relative = candidate.relative_to(root)
    except ValueError:
        return None, "target escapes repository"
    current = root
    for component in relative.parts:
        if not current.is_dir():
            return None, "missing target"
        names = {entry.name for entry in current.iterdir()}
        if component not in names:
            folded = sorted(name for name in names if name.casefold() == component.casefold())
            return None, f"case mismatch (found {folded[0]!r})" if folded else "missing target"
        current /= component
    return current, None


def check(root: Path) -> tuple[list[str], int]:
    root = root.resolve()
    docs = root / "docs"
    files = sorted(set(root.glob("*.md")) | set(docs.rglob("*.md")))
    graph: dict[Path, set[Path]] = {}
    errors = []
    for source in files:
        graph[source] = set()
        try:
            text = source.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError as error:
            errors.append(f"{source.relative_to(root).as_posix()}: invalid UTF-8 at byte {error.start}")
            continue
        for line, target in links(text):
            resolved, error = resolve_local(root, source, target)
            if error:
                errors.append(f"{source.relative_to(root).as_posix()}:{line}: {error}: {target}")
            elif resolved is not None:
                if resolved.is_dir():
                    # Directory links are valid. Only their actual landing page
                    # grants navigation reachability, not every contained file.
                    for name in ("README.md", "INDEX.md"):
                        landing, _ = resolve_local(root, resolved / "_", name)
                        if landing is not None and landing.is_file():
                            graph[source].add(landing)
                elif resolved.suffix.lower() == ".md":
                    graph[source].add(resolved)
    index = docs / "INDEX.md"
    if index not in graph:
        errors.append("docs/INDEX.md: missing documentation navigation entry point")
    reached: set[Path] = set()
    pending = [index]
    while pending:
        page = pending.pop()
        if page not in reached:
            reached.add(page)
            pending.extend(graph.get(page, set()) - reached)
    for page in sorted(docs.glob("*.md")):
        if page not in reached:
            errors.append(f"{page.relative_to(root).as_posix()}: unreachable from docs/INDEX.md")
    return errors, len(files)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1], help="repository root (default: parent of scripts/)")
    args = parser.parse_args()
    errors, count = check(args.root)
    for error in errors:
        print(error)
    print(f"Checked {count} Markdown files; {len(errors)} errors (local paths and docs index reachability).")
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
