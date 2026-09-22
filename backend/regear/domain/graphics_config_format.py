"""The one text-configuration adapter for milestone 1, and its registry.

Parsing and rendering are pure, so "Re-Gear preserved every setting it does not
manage" is a property of a round trip over a string rather than something only
observable on disk. The renderer is deliberately not a formatter: it reproduces
every line it did not change exactly as it read it, including comments, blank
lines, duplicate keys, section order, spacing around ``=`` and the file's line
endings. A document nobody edited renders back byte-identical.

The adapter understands one shape: ``key=value`` lines, optionally inside
``[Section]`` headers, which is what the Unreal/Unity-style ``.ini`` and
``.cfg`` files this milestone targets use. Anything it cannot read is reported
as unreadable; it never guesses, because a guess here rewrites a player's file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Mapping, Sequence


#: A managed key is addressed as ``Section/key``; the empty section is the
#: preamble above the first header, addressed as ``/key``.
KEY_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,64}$")
SECTION_RE = re.compile(r"^[A-Za-z0-9_.\- ]{0,96}$")
SECTION_LINE_RE = re.compile(r"^\s*\[(?P<name>[^\]\r\n]*)\]\s*$")
ENTRY_LINE_RE = re.compile(
    r"^(?P<lead>\s*)(?P<key>[A-Za-z0-9_.\-]{1,64})(?P<pre>\s*)=(?P<post>\s*)"
    r"(?P<value>[^\r\n]*?)(?P<trail>\s*)$"
)
COMMENT_LINE_RE = re.compile(r"^\s*(?:[;#].*)?$")

MAX_LINES = 20_000


class DocumentProblem(StrEnum):
    """Why a document could not be taken as managed."""

    UNREADABLE_LINE = "graphics_config.unreadable_line"
    TOO_LARGE = "graphics_config.too_large"
    NOT_TEXT = "graphics_config.not_text"


class ConfigFormatError(ValueError):
    """Raised by the parser; callers turn this into Advisor support."""

    def __init__(self, problem: DocumentProblem, detail: str) -> None:
        super().__init__(f"{problem.value}: {detail}")
        self.problem = problem
        self.detail = detail


def address(section: str, key: str) -> str:
    """Build the ``Section/key`` address used by profiles."""
    if not SECTION_RE.fullmatch(section):
        raise ValueError("configuration section name is invalid")
    if not KEY_RE.fullmatch(key):
        raise ValueError("configuration key name is invalid")
    return f"{section}/{key}"


def split_address(value: str) -> tuple[str, str]:
    section, separator, key = value.partition("/")
    if not separator or not KEY_RE.fullmatch(key) or not SECTION_RE.fullmatch(section):
        raise ValueError("configuration key address is invalid")
    return section, key


@dataclass(frozen=True, slots=True)
class _Line:
    """One source line, kept verbatim unless it is an entry we rewrite."""

    raw: str
    ending: str
    section: str
    key: str | None = None
    value: str | None = None
    lead: str = ""
    pre: str = ""
    post: str = ""
    trail: str = ""

    def rendered(self, value: str | None = None) -> str:
        if self.key is None or value is None or value == self.value:
            return self.raw + self.ending
        return (
            f"{self.lead}{self.key}{self.pre}={self.post}{value}{self.trail}"
            + self.ending
        )


@dataclass(frozen=True, slots=True)
class ConfigDocument:
    """A parsed text configuration that can render itself back unchanged."""

    lines: tuple[_Line, ...]
    overrides: Mapping[str, str] = field(default_factory=dict)

    def values(self) -> dict[str, str]:
        """Current value of every entry, last occurrence winning."""
        found: dict[str, str] = {}
        for line in self.lines:
            if line.key is None:
                continue
            found[address(line.section, line.key)] = line.value or ""
        found.update(self.overrides)
        return found

    def get(self, key_address: str) -> str | None:
        return self.values().get(key_address)

    def has(self, key_address: str) -> bool:
        return key_address in self.values()

    def with_values(self, changes: Mapping[str, str]) -> "ConfigDocument":
        """Return a document with those addresses set.

        Only addresses already present are settable. Adding a key a game never
        wrote is a change to the game's schema, not to the player's setting, so
        it is refused here and reported as Advisor support upstream.
        """
        present = self.values()
        for key_address, value in changes.items():
            if key_address not in present:
                raise KeyError(key_address)
            if "\n" in value or "\r" in value:
                raise ValueError("configuration value must be a single line")
        merged = dict(self.overrides)
        merged.update(changes)
        return ConfigDocument(self.lines, merged)

    def render(self) -> str:
        """Render the document, rewriting only overridden last occurrences."""
        remaining = dict(self.overrides)
        # The last occurrence of a duplicated key is the one the game reads, so
        # it is the one we rewrite; earlier duplicates stay untouched.
        rewrite_at: dict[int, str] = {}
        for index in range(len(self.lines) - 1, -1, -1):
            line = self.lines[index]
            if line.key is None:
                continue
            key_address = address(line.section, line.key)
            if key_address in remaining:
                rewrite_at[index] = remaining.pop(key_address)
        if remaining:
            raise KeyError(next(iter(remaining)))
        return "".join(
            line.rendered(rewrite_at.get(index))
            for index, line in enumerate(self.lines)
        )


def parse_document(text: str) -> ConfigDocument:
    """Parse text into a document, refusing anything not fully understood."""
    if "\x00" in text:
        raise ConfigFormatError(DocumentProblem.NOT_TEXT, "document contains a NUL byte")
    raw_lines = text.splitlines(keepends=True)
    if len(raw_lines) > MAX_LINES:
        raise ConfigFormatError(
            DocumentProblem.TOO_LARGE, f"document has {len(raw_lines)} lines"
        )
    parsed: list[_Line] = []
    section = ""
    for number, raw in enumerate(raw_lines, start=1):
        body = raw
        ending = ""
        for candidate in ("\r\n", "\n", "\r"):
            if body.endswith(candidate):
                body, ending = body[: -len(candidate)], candidate
                break
        header = SECTION_LINE_RE.match(body)
        if header is not None:
            name = header.group("name")
            if not SECTION_RE.fullmatch(name):
                raise ConfigFormatError(
                    DocumentProblem.UNREADABLE_LINE, f"line {number}: section name"
                )
            section = name
            parsed.append(_Line(raw=body, ending=ending, section=section))
            continue
        entry = ENTRY_LINE_RE.match(body)
        if entry is not None:
            parsed.append(
                _Line(
                    raw=body,
                    ending=ending,
                    section=section,
                    key=entry.group("key"),
                    value=entry.group("value"),
                    lead=entry.group("lead"),
                    pre=entry.group("pre"),
                    post=entry.group("post"),
                    trail=entry.group("trail"),
                )
            )
            continue
        if COMMENT_LINE_RE.match(body):
            parsed.append(_Line(raw=body, ending=ending, section=section))
            continue
        raise ConfigFormatError(
            DocumentProblem.UNREADABLE_LINE, f"line {number}: not a key, section or comment"
        )
    return ConfigDocument(tuple(parsed))


@dataclass(frozen=True, slots=True)
class ConfigFormatAdapter:
    """A named, versioned way to read and write one configuration shape."""

    name: str
    suffixes: tuple[str, ...]

    def reads(self, filename: str) -> bool:
        lowered = filename.lower()
        return any(lowered.endswith(suffix) for suffix in self.suffixes)

    def parse(self, text: str) -> ConfigDocument:
        return parse_document(text)

    def render(self, document: ConfigDocument) -> str:
        return document.render()


KEY_VALUE_ADAPTER = ConfigFormatAdapter(
    name="key-value-text", suffixes=(".ini", ".cfg", ".conf")
)

#: One adapter this milestone. The registry exists so the second one is an
#: addition rather than a rewrite of the service.
ADAPTERS: tuple[ConfigFormatAdapter, ...] = (KEY_VALUE_ADAPTER,)


def adapter_for(filename: str) -> ConfigFormatAdapter | None:
    """The adapter that claims this filename, or ``None`` for Advisor support."""
    for adapter in ADAPTERS:
        if adapter.reads(filename):
            return adapter
    return None


def unmanaged_remainder(
    document: ConfigDocument, managed: Sequence[str]
) -> dict[str, str]:
    """Every value the profile does not manage, for before/after comparison."""
    owned = set(managed)
    return {
        key_address: value
        for key_address, value in document.values().items()
        if key_address not in owned
    }
