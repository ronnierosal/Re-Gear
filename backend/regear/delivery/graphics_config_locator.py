"""Read-only discovery of one game's graphics configuration.

Everything here is rooted at a Steam root the caller supplies explicitly. There
is no default, and no fallback to ``~/.steam``: during this milestone the only
roots passed in are test fixtures, and a locator that could find the player's
real library by accident is one bad default away from editing it.

Discovery answers "where would this game's configuration be", never "apply
something to it". It performs no writes and follows no symlink out of the root.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from ..domain.graphics_config_format import adapter_for
from ..domain.models import OperatingMode


STEAM_APP_ID_RE = re.compile(r"^[1-9][0-9]{0,9}$")
LIBRARY_FOLDERS = "steamapps/libraryfolders.vdf"
MAX_VDF_BYTES = 512 * 1024
MAX_LIBRARIES = 16
#: Windows games under Proton keep their configuration in the prefix's fake
#: drive; this is the ``My Documents`` path inside a default Proton prefix.
PREFIX_DOCUMENTS = "pfx/drive_c/users/steamuser/Documents"


class Runtime(StrEnum):
    PROTON = "proton"
    NATIVE = "native"


class LocationProblem(StrEnum):
    NO_LIBRARY = "graphics_locator.no_library"
    NOT_INSTALLED = "graphics_locator.not_installed"
    MANIFEST_CONTRADICTS = "graphics_locator.manifest_contradicts"
    AMBIGUOUS_INSTALL = "graphics_locator.ambiguous_install"
    NO_PREFIX = "graphics_locator.no_prefix"
    CONFIG_ABSENT = "graphics_locator.config_absent"
    ESCAPES_ROOT = "graphics_locator.escapes_root"
    NO_ADAPTER = "graphics_locator.no_adapter"


@dataclass(frozen=True, slots=True)
class ConfigLocation:
    """A located, readable configuration file and how it was reached."""

    steam_app_id: str
    runtime: Runtime
    library_root: Path
    install_dir: Path
    config_path: Path
    adapter_name: str

    @property
    def identity(self) -> str:
        """Stable identity for backups and provenance: this exact file.

        AppID, runtime and basename are not enough. One game can hold several
        files of the same name in different directories, and the same AppID can
        be installed in two libraries; sharing an identity between them would
        let one target's backup be restored over another's. The canonical
        target path is therefore part of the identity, digested so the result
        stays a safe filename.
        """
        target = hashlib.sha256(str(self.config_path).encode("utf-8")).hexdigest()[:32]
        return f"{self.steam_app_id}.{self.runtime.value}.{target}"


@dataclass(frozen=True, slots=True)
class LocationOutcome:
    location: ConfigLocation | None
    problem: LocationProblem | None
    detail: str = ""

    @property
    def located(self) -> bool:
        return self.location is not None


def _quoted_pairs(text: str) -> list[tuple[str, str]]:
    """Every ``"a"  "b"`` pair in a VDF-ish document, in order.

    A deliberately small reader: this milestone needs library paths and a
    handful of manifest fields, not a VDF object model. Nested structure is
    ignored rather than half-understood.
    """
    return [
        (match.group(1), match.group(2))
        for match in re.finditer(r'"([^"\r\n]{1,128})"\s+"([^"\r\n]{0,4096})"', text)
    ]


class GraphicsConfigLocator:
    """Find a game's configuration beneath one explicitly supplied Steam root."""

    def __init__(self, steam_root: Path) -> None:
        if not steam_root.is_absolute():
            raise ValueError("steam root must be absolute")
        self._root = steam_root

    @property
    def steam_root(self) -> Path:
        return self._root

    def library_roots(self) -> tuple[Path, ...]:
        """Every library directory, the root's own first."""
        roots: list[Path] = []
        own = self._root / "steamapps"
        if own.is_dir():
            roots.append(self._root)
        manifest = self._root / LIBRARY_FOLDERS
        text = self._read_small(manifest, MAX_VDF_BYTES)
        if text is not None:
            for key, value in _quoted_pairs(text):
                if key != "path":
                    continue
                candidate = Path(value)
                if not candidate.is_absolute() or not (candidate / "steamapps").is_dir():
                    continue
                if candidate not in roots:
                    roots.append(candidate)
                if len(roots) >= MAX_LIBRARIES:
                    break
        return tuple(roots)

    def install_directory(self, steam_app_id: str) -> tuple[Path, Path] | None:
        """``(library_root, install_dir)`` for an installed AppID.

        Kept for callers that only need the path. `locate` uses
        `resolve_install` instead, which distinguishes "not installed" from
        "the manifest disagrees with itself" and from "two libraries claim it".
        """
        install, problem = self.resolve_install(steam_app_id)
        return install if problem is None else None

    def resolve_install(
        self, steam_app_id: str
    ) -> tuple[tuple[Path, Path] | None, LocationProblem | None]:
        """Find the one library that installs this AppID, or say why not.

        A manifest is trusted only when its own contents agree with its name: a
        file called `appmanifest_620.acf` that declares `"appid" "999999"` is
        contradictory evidence, and picking either number would be a guess
        about which one the player's Steam believes. Two libraries holding
        manifests for the same AppID is ambiguity for the same reason.
        """
        self._require_app_id(steam_app_id)
        matches: list[tuple[Path, Path]] = []
        for library in self.library_roots():
            manifest = library / "steamapps" / f"appmanifest_{steam_app_id}.acf"
            text = self._read_small(manifest, MAX_VDF_BYTES)
            if text is None:
                continue
            fields = dict(_quoted_pairs(text))
            declared = fields.get("appid", "").strip()
            if declared != steam_app_id:
                return (None, LocationProblem.MANIFEST_CONTRADICTS)
            name = fields.get("installdir", "")
            if not name or "/" in name or "\\" in name or name in ("..", "."):
                return (None, LocationProblem.MANIFEST_CONTRADICTS)
            install = library / "steamapps" / "common" / name
            if install.is_dir():
                matches.append((library, install))
        if not matches:
            return (None, LocationProblem.NOT_INSTALLED)
        if len(matches) > 1:
            return (None, LocationProblem.AMBIGUOUS_INSTALL)
        return (matches[0], None)

    def compat_prefix(self, steam_app_id: str, library: Path) -> Path | None:
        """The Proton prefix directory for an AppID, if one exists."""
        self._require_app_id(steam_app_id)
        prefix = library / "steamapps" / "compatdata" / steam_app_id
        return prefix if (prefix / "pfx").is_dir() else None

    def locate(
        self,
        steam_app_id: str,
        config_filename: str,
        mode: OperatingMode,
        relative_dir: str,
    ) -> LocationOutcome:
        """Locate one game's configuration file.

        ``relative_dir`` is the game's own configuration directory, relative to
        the Proton prefix's Documents directory or, for a native game, to the
        install directory. The mode is carried for evidence only: which file
        holds a game's settings does not depend on where the player is sitting.
        """
        self._require_app_id(steam_app_id)
        if adapter_for(config_filename) is None:
            return LocationOutcome(None, LocationProblem.NO_ADAPTER, config_filename)
        found, problem = self.resolve_install(steam_app_id)
        if found is None:
            assert problem is not None
            return LocationOutcome(None, problem, steam_app_id)
        library, install = found
        prefix = self.compat_prefix(steam_app_id, library)
        if prefix is not None:
            runtime = Runtime.PROTON
            base = prefix / PREFIX_DOCUMENTS
        else:
            runtime = Runtime.NATIVE
            base = install
        candidate = base / relative_dir / config_filename
        containment = library if runtime is Runtime.NATIVE else prefix
        assert containment is not None
        if not self._contained(candidate, containment):
            return LocationOutcome(None, LocationProblem.ESCAPES_ROOT, str(candidate))
        if not candidate.is_file() or candidate.is_symlink():
            return LocationOutcome(None, LocationProblem.CONFIG_ABSENT, str(candidate))
        adapter = adapter_for(candidate.name)
        assert adapter is not None
        return LocationOutcome(
            ConfigLocation(
                steam_app_id=steam_app_id,
                runtime=runtime,
                library_root=library,
                install_dir=install,
                config_path=candidate,
                adapter_name=adapter.name,
            ),
            None,
        )

    @staticmethod
    def _contained(candidate: Path, root: Path) -> bool:
        """Whether a path stays inside a root once ``..`` is resolved away.

        Compared without touching the filesystem, so a not-yet-existing path is
        judged the same way an existing one is.
        """
        try:
            resolved = Path.resolve(candidate, strict=False)
            base = Path.resolve(root, strict=False)
        except OSError:
            return False
        return resolved == base or base in resolved.parents

    @staticmethod
    def _read_small(path: Path, limit: int) -> str | None:
        try:
            if path.is_symlink() or not path.is_file():
                return None
            if path.stat().st_size > limit:
                return None
            return path.read_text(encoding="utf-8", errors="strict")
        except (OSError, UnicodeDecodeError):
            return None

    @staticmethod
    def _require_app_id(steam_app_id: str) -> None:
        if not STEAM_APP_ID_RE.fullmatch(steam_app_id):
            raise ValueError("Steam AppID is invalid")
