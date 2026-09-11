"""Deterministic checks for Re-Gear's pure domain boundary."""

from __future__ import annotations

import ast
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DOMAIN_ROOT = REPOSITORY_ROOT / "backend" / "regear" / "domain"
ADAPTER_ROOT = REPOSITORY_ROOT / "backend" / "regear" / "adapters"
FORBIDDEN_IMPORT_ROOTS = {
    "asyncio",
    "ctypes",
    "http",
    "os",
    "pathlib",
    "shutil",
    "socket",
    "subprocess",
    "urllib",
}
#: The one adapter permitted to write, mirroring how subprocess is confined to
#: commands.py. Device detachment requires a sysfs write, and concentrating it
#: in a single reviewed module keeps every other adapter read-only rather than
#: relaxing the ban globally. This module is additionally constrained below.
#:
#: Matched as an exact repository-relative path, not a file name: a module named
#: device_removal.py in any other adapter directory must not inherit the
#: exemption.
DEVICE_WRITER = Path("backend/regear/adapters/steamos/device_removal.py")
WHOLE_DOCK_WRITER = Path("backend/regear/adapters/steamos/whole_dock_writer.py")

#: The exact receiver expressions the device writer may call write_text on, and
#: how many such calls may exist. Pinning the expressions rather than string
#: literals is the difference between checking what the module mentions and
#: checking what it writes to; a relative path, a caller-supplied Path or an
#: extra call site all fail here.
APPROVED_WRITE_EXPRESSIONS = {
    "self._remove_node(address)",
    "PCI_RESCAN",
}
MAX_DEVICE_WRITES = 2

#: Writes that module may perform. Anything else stays forbidden even there.
DEVICE_WRITER_ALLOWED_CALLS = {"write_text"}

FORBIDDEN_WRITE_CALLS = {
    "write",
    "chmod",
    "mkdir",
    "rename",
    "replace",
    "rmdir",
    "symlink_to",
    "touch",
    "unlink",
    "write_bytes",
    "write_text",
}


def whole_dock_writer_failures() -> list[str]:
    """Keep removal and reauthorization limited to fixed device attributes."""
    path = REPOSITORY_ROOT / WHOLE_DOCK_WRITER
    if not path.exists():
        return []
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    failures = []
    writes = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == "write":
                writes.append(node)
                if (ast.unparse(node.func) != "os.write" or len(node.args) != 2
                        or ast.unparse(node.args[0]) != "attribute"
                        or ast.unparse(node.args[1]) != "b'1' if usb or reauthorize else b'0'"):
                    failures.append("whole-dock writer has an unapproved write")
            if ast.unparse(node.func) == "os.open" and len(node.args) >= 2:
                if "O_WRONLY" in ast.unparse(node.args[1]):
                    if (ast.unparse(node.args[0]) != "'remove' if usb else 'authorized'"
                            or not any(k.arg == "dir_fd" and ast.unparse(k.value) == "directory"
                                       for k in node.keywords)):
                        failures.append("whole-dock writer has an unapproved writable target")
    if len(writes) != 1:
        failures.append("whole-dock writer must have exactly one bounded write site")
    return failures


def imported_roots(node: ast.AST) -> tuple[str, ...]:
    if isinstance(node, ast.Import):
        return tuple(alias.name.split(".", 1)[0] for alias in node.names)
    if isinstance(node, ast.ImportFrom) and node.module:
        return (node.module.split(".", 1)[0],)
    return ()


def device_writer_failures() -> list[str]:
    """Constrain the one adapter permitted to write to device nodes.

    Permitting a write is not the same as permitting arbitrary writes. The
    device writer may only reach the two sysfs paths that detach and re-enumerate
    a PCI device, and every write target must be built from those constants, so
    a future edit cannot quietly widen it into a general filesystem writer.
    """
    path = REPOSITORY_ROOT / DEVICE_WRITER
    if not path.exists():
        return []
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    failures: list[str] = []
    writes = 0
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        if node.func.attr not in DEVICE_WRITER_ALLOWED_CALLS:
            continue
        writes += 1
        receiver = ast.unparse(node.func.value)
        if receiver not in APPROVED_WRITE_EXPRESSIONS:
            failures.append(
                f"{path.relative_to(REPOSITORY_ROOT)}:{node.lineno}: "
                f"device writer writes to unapproved destination {receiver!r}"
            )
    if writes > MAX_DEVICE_WRITES:
        failures.append(
            f"{path.relative_to(REPOSITORY_ROOT)}: device writer has {writes} write "
            f"call sites, more than the {MAX_DEVICE_WRITES} approved"
        )
    if "subprocess" in {root for node in ast.walk(tree) for root in imported_roots(node)}:
        failures.append(
            f"{path.relative_to(REPOSITORY_ROOT)}: the device writer must not spawn processes"
        )
    return failures


def main() -> int:
    failures: list[str] = []
    for path in sorted(DOMAIN_ROOT.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            for root in imported_roots(node):
                if root in FORBIDDEN_IMPORT_ROOTS:
                    failures.append(
                        f"{path.relative_to(REPOSITORY_ROOT)}:{node.lineno}: "
                        f"domain imports forbidden I/O module {root!r}"
                    )
    for path in sorted(ADAPTER_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                permitted = (
                    path.relative_to(REPOSITORY_ROOT) == DEVICE_WRITER
                    and node.func.attr in DEVICE_WRITER_ALLOWED_CALLS
                )
                permitted = permitted or (
                    path.relative_to(REPOSITORY_ROOT) == WHOLE_DOCK_WRITER
                    and ast.unparse(node.func) == "os.write"
                )
                if node.func.attr in FORBIDDEN_WRITE_CALLS and not permitted:
                    failures.append(
                        f"{path.relative_to(REPOSITORY_ROOT)}:{node.lineno}: "
                        f"adapter calls forbidden filesystem writer {node.func.attr!r}"
                    )
        if path.name != "commands.py" and "subprocess" in {
            root for node in ast.walk(tree) for root in imported_roots(node)
        }:
            failures.append(
                f"{path.relative_to(REPOSITORY_ROOT)}: subprocess access belongs only in commands.py"
            )
    command_source = (ADAPTER_ROOT / "steamos" / "commands.py").read_text(
        encoding="utf-8"
    )
    if "shell=True" in command_source.replace(" ", ""):
        failures.append("backend/regear/adapters/steamos/commands.py: shell execution is forbidden")
    failures.extend(device_writer_failures())
    failures.extend(whole_dock_writer_failures())
    if failures:
        print("Architecture check failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print(
        "Architecture check passed: domain is I/O-free and the adapter "
        "subprocess boundary is constrained."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
