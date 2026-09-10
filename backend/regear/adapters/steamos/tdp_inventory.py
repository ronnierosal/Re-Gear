"""One-shot ASUS power-limit settings inventory; no control authority or telemetry.

Values describe live firmware settings in watts, not measured power consumption.
Presence does not establish writability, hardware compatibility, or safe limits.
Reads are bounded but sequential: the result is not an atomic firmware snapshot.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


MAX_VALUE_BYTES = 64
_FIELDS = ("current_value", "min_value", "max_value", "default_value")
_ALIASES = (
    ("sustained", "ppt_pl1_spl"),
    ("slow", "ppt_pl2_sppt"),
    ("fast", "ppt_pl3_fppt"),
    ("fast", "ppt_fppt"),
)


@dataclass(frozen=True, slots=True)
class TdpField:
    status: str
    value: int | None = None

    def to_dict(self) -> dict[str, object]:
        return {"status": self.status, "value": self.value}


@dataclass(frozen=True, slots=True)
class TdpSource:
    source: str
    limit: str
    attribute: str
    status: str
    fields: tuple[TdpField, ...]
    ordering: str

    def to_dict(self) -> dict[str, object]:
        return {
            "source": self.source,
            "limit": self.limit,
            "attribute": self.attribute,
            "status": self.status,
            "fields": {name: field.to_dict() for name, field in zip(_FIELDS, self.fields)},
            "ordering": self.ordering,
        }


@dataclass(frozen=True, slots=True)
class TdpInventory:
    sources: tuple[TdpSource, ...]

    def to_dict(self) -> dict[str, object]:
        # Even equal values from two sources are ambiguous: no precedence is implied.
        return {
            "value_kind": "firmware_power_limit_setting",
            "unit": "watts",
            "sources": [source.to_dict() for source in self.sources],
            "limits": {
                limit: (
                    "ambiguous" if len(present) > 1 else
                    present[0].status if present else "absent"
                )
                for limit in ("sustained", "slow", "fast")
                for present in [[s for s in self.sources if s.limit == limit and s.status != "absent"]]
            },
        }


def _read_integer(path: Path) -> TdpField:
    try:
        with path.open("rb") as stream:
            raw = stream.read(MAX_VALUE_BYTES + 1)
    except FileNotFoundError:
        return TdpField("absent")
    except OSError:
        return TdpField("invalid")
    if len(raw) > MAX_VALUE_BYTES:
        return TdpField("invalid")
    token = raw.strip(b" \t\r\n")
    if not token or any(byte < 48 or byte > 57 for byte in token):
        return TdpField("invalid")
    return TdpField("observed", int(token))


def _ordering(fields: tuple[TdpField, ...]) -> str:
    current, minimum, maximum, default = (field.value for field in fields)
    if minimum is not None and maximum is not None and minimum > maximum:
        return "inconsistent"
    for value in (current, default):
        if value is not None and (
            (minimum is not None and value < minimum)
            or (maximum is not None and value > maximum)
        ):
            return "inconsistent"
    return "consistent" if minimum is not None and maximum is not None else "incomplete"


class AsusTdpInventory:
    """Inspect only fixed ASUS attribute locations under an injectable sysfs root."""

    def __init__(self, sys_root: Path = Path("/sys")) -> None:
        self._sys_root = Path(sys_root)

    def scan(self) -> TdpInventory:
        sources = []
        for source, root, aliases in (
            ("asus_firmware_attributes", self._sys_root / "class/firmware-attributes/asus-armoury/attributes", _ALIASES),
            ("asus_legacy_wmi", self._sys_root / "devices/platform/asus-nb-wmi", _ALIASES[:2] + _ALIASES[3:]),
        ):
            for limit, attribute in aliases:
                path = root / attribute
                if source == "asus_firmware_attributes":
                    fields = tuple(_read_integer(path / name) for name in _FIELDS)
                else:
                    fields = (_read_integer(path),) + (TdpField("absent"),) * 3
                try:
                    path.stat()
                    present = True
                    inaccessible = False
                except FileNotFoundError:
                    present = False
                    inaccessible = False
                except OSError:
                    present = True
                    inaccessible = True
                ordering = _ordering(fields)
                if inaccessible or any(field.status == "invalid" for field in fields) or ordering == "inconsistent":
                    status = "invalid"
                elif all(field.status == "observed" for field in fields[:3]):
                    status = "observed"
                elif present or any(field.status == "observed" for field in fields):
                    status = "incomplete"
                else:
                    status = "absent"
                sources.append(TdpSource(source, limit, attribute, status, fields, ordering))
        return TdpInventory(tuple(sources))
