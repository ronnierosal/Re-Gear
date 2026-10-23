"""Injected fake-port contracts only; no transport or production implementation."""

from enum import StrEnum
from typing import Protocol

from ..domain.controller_target_session import Frame, Request


class Dispatch(StrEnum):
    SUBMITTED = "submitted"
    REFUSED = "refused_before_submission"


class TargetReader(Protocol):
    def read(self, deadline: float) -> Frame:
        """Fresh coherent verified frame; return before the injected deadline."""


class TargetWriter(Protocol):
    def set_targets(self, request: Request) -> Dispatch:
        """REFUSED guarantees no submission; exceptions/other results are uncertain.

        Honor request.deadline. SUBMITTED is not evidence of effective state.
        """
