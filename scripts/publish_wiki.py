"""Render canonical Wiki sources into an empty staging directory; never pushes Git."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
from urllib.parse import quote, unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs/wiki"
REPO = "https://github.com/ronnierosal/Re-Gear/blob/main/"
RAW = "https://raw.githubusercontent.com/wiki/ronnierosal/Re-Gear/"


def render(output: Path) -> list[str]:
    config = json.loads((SOURCE / "publication.json").read_text(encoding="utf-8"))
    pages = {(SOURCE / path).resolve(): slug for path, slug in config["pages"].items()}
    aliases = config["aliases"]
    slugs = [*pages.values(), *aliases]
    if len(slugs) != len(set(slugs)) or any(not re.fullmatch(r"[A-Za-z0-9_-]+", s) for s in slugs):
        raise ValueError("Duplicate or invalid publication slug")
    for path in pages:
        if not path.is_relative_to(SOURCE) or not path.is_file():
            raise ValueError(f"Missing or outside canonical source: {path}")
    if output.exists() and any(output.iterdir()):
        raise ValueError("Output must be empty; inspect existing publication before synchronization")
    output.mkdir(parents=True, exist_ok=True)
    assets: dict[str, Path] = {}

    def rewrite(source: Path, text: str) -> str:
        def target(match: re.Match[str]) -> str:
            value = match[1]
            parsed = urlsplit(value)
            if parsed.scheme or parsed.netloc or not parsed.path:
                return match.group()
            path = (source.parent / unquote(parsed.path)).resolve()
            suffix = ("?" + parsed.query if parsed.query else "") + ("#" + parsed.fragment if parsed.fragment else "")
            if path in pages:
                dest = pages[path] + suffix
            elif path.is_file() and path.suffix.lower() in {".png", ".svg", ".jpg", ".jpeg", ".webp"}:
                if path.is_relative_to(SOURCE / "assets"):
                    asset = "assets/" + path.relative_to(SOURCE / "assets").as_posix()
                elif path.is_relative_to(ROOT / "assets"):
                    asset = "assets/" + path.relative_to(ROOT / "assets").as_posix()
                else:
                    raise ValueError(f"Unmapped asset: {path}")
                if asset in assets and assets[asset] != path:
                    raise ValueError(f"Asset collision: {asset}")
                assets[asset] = path
                dest = RAW + quote(asset, safe="/")
            elif path.is_relative_to(ROOT) and path.exists():
                dest = REPO + quote(path.relative_to(ROOT).as_posix(), safe="/") + suffix
            else:
                raise ValueError(f"Missing local target in {source}: {value}")
            return "](" + dest + ")"
        # Canonical sources use simple inline destinations. Fail the separate
        # docs gate on local path errors; do not guess a publication target.
        return re.sub(r"\]\(([^)\s]+)\)", target, text)

    for source, slug in pages.items():
        (output / (slug + ".md")).write_text(rewrite(source, source.read_text(encoding="utf-8-sig")), encoding="utf-8")
    for alias, destination in aliases.items():
        if destination not in pages.values():
            raise ValueError(f"Unknown alias destination: {destination}")
        (output / (alias + ".md")).write_text(f"# Page moved\n\nRead the [Player Guide]({destination}). This page keeps existing links working; the guide has one maintained home.\n", encoding="utf-8")
    for name, path in assets.items():
        destination = output / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
    sidebar = """# Re-Gear

- [Home](Home)
- [Player Guide](Player-Guide)
- [Getting Started](Getting-Started)
- [Tutorials](Tutorial-Cards)
- [Command Center](Command-Center)
- [eGPU and Docking](eGPU-and-Docking)
- [Performance](Performance-and-Power)
- [Controllers](Controllers)
- [Customization](Customize)
- [How-To](How-To)
- [Visual Guide](Player-Visual-Guide)
- [Troubleshooting](Troubleshooting)
- [Diagnostics and Privacy](Diagnostics-and-Privacy)

## Contributors

- [Technical Guide](Technical-Guide)
- [eGPU Lifecycle](eGPU-Lifecycle)
- [Architecture](Architecture)
- [Scripts and CI](Scripts-and-CI)
- [Current Evidence](Current-State)
"""
    (output / "_Sidebar.md").write_text(sidebar, encoding="utf-8")
    return sorted(p.relative_to(output).as_posix() for p in output.rglob("*") if p.is_file())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = Path(os.path.abspath(args.output))
    if output == ROOT or ROOT.is_relative_to(output) or output.is_relative_to(SOURCE):
        parser.error("Use a separate empty staging directory")
    files = render(output)
    print(f"Rendered {len(files)} files into {output}. No Git repository was modified or pushed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
