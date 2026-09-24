"""Evidence that a configuration file is the schema an adapter was written for.

A suffix is not a schema. `graphics.ini` parsing proving a file is key-value
text says nothing about whether its keys mean what an adapter thinks they mean,
and a game update can change that meaning without changing the file name. So a
schema carries a version key with an explicit list of versions the adapter was
written against, the addresses that must be present, and validators for the
*current* values -- not only for the values Re-Gear would like to write.

Anything that does not match exactly is UNKNOWN. Unknown is a support level, not
an error: it means Advisor, with the file untouched.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Mapping

from .graphics_config_format import ConfigDocument, split_address


class SchemaVerdict(StrEnum):
    MATCHED = "graphics_schema.matched"
    VERSION_ABSENT = "graphics_schema.version_absent"
    VERSION_UNSUPPORTED = "graphics_schema.version_unsupported"
    KEY_ABSENT = "graphics_schema.key_absent"
    CURRENT_VALUE_UNSUPPORTED = "graphics_schema.current_value_unsupported"


@dataclass(frozen=True, slots=True)
class SchemaAssessment:
    verdict: SchemaVerdict
    detail: str = ""
    observed_version: str | None = None
    signature: str = ""

    @property
    def matched(self) -> bool:
        return self.verdict is SchemaVerdict.MATCHED


def structural_signature(document: ConfigDocument) -> str:
    """A stable description of which addresses a document holds.

    Deliberately the *shape*, never the values: it identifies the schema a file
    presents, and recording it alongside a managed write is what later makes
    "the game changed its configuration layout" a visible event rather than a
    silent mismatch. Kept human-readable so it can be read in evidence.
    """
    return ";".join(sorted(document.values()))


@dataclass(frozen=True, slots=True)
class GameSchema:
    """One configuration layout an adapter has actually been written against."""

    schema_id: str
    version_address: str
    supported_versions: tuple[str, ...]
    required_addresses: tuple[str, ...]
    #: Address -> validator for the value currently in the file. A file holding
    #: a value this adapter cannot even describe is not one it may rewrite.
    current_value_validators: Mapping[str, "object"]

    def __post_init__(self) -> None:
        if not self.schema_id:
            raise ValueError("schema id is required")
        split_address(self.version_address)
        if not self.supported_versions:
            raise ValueError("a schema must name the versions it supports")
        for address in self.required_addresses:
            split_address(address)
        for address in self.current_value_validators:
            split_address(address)

    def assess(self, document: ConfigDocument) -> SchemaAssessment:
        """Decide whether this document is the schema, with a reason if not."""
        signature = structural_signature(document)
        values = document.values()
        observed = values.get(self.version_address)
        if observed is None:
            return SchemaAssessment(
                SchemaVerdict.VERSION_ABSENT,
                f"{self.version_address} is not present",
                None,
                signature,
            )
        if observed.strip() not in self.supported_versions:
            return SchemaAssessment(
                SchemaVerdict.VERSION_UNSUPPORTED,
                f"{self.version_address}={observed!r} is not one of "
                f"{', '.join(self.supported_versions)}",
                observed,
                signature,
            )
        for address in self.required_addresses:
            if address not in values:
                return SchemaAssessment(
                    SchemaVerdict.KEY_ABSENT, f"{address} is missing", observed, signature
                )
        for address, validator in self.current_value_validators.items():
            current = values.get(address)
            if current is None:
                return SchemaAssessment(
                    SchemaVerdict.KEY_ABSENT, f"{address} is missing", observed, signature
                )
            accepts = getattr(validator, "accepts", None)
            if accepts is None or not accepts(current):
                return SchemaAssessment(
                    SchemaVerdict.CURRENT_VALUE_UNSUPPORTED,
                    f"{address} currently holds {current!r}, which this adapter "
                    "does not recognise",
                    observed,
                    signature,
                )
        return SchemaAssessment(SchemaVerdict.MATCHED, "", observed, signature)
