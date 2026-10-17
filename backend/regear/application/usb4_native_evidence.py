"""Collect inert observations; no production consumer or authorization decision.

One owner/read/owner sequence. A completed collection is not a qualified API,
permission, grant, enrollment, GPU enumeration or lifecycle-readiness result.
Native API selection and any real reader require separate installed evidence.
"""
from dataclasses import dataclass, replace
import math
from typing import Callable

from ..ports.usb4_native_evidence import (
    AttachmentEvidence, Fact, NativeEvidenceReader, NativeSnapshot, ReadBudget, ReadLimits,
)


@dataclass(frozen=True)
class EvidenceReport:
    code: str
    snapshot: NativeSnapshot | None = None


class _InvalidClock(Exception):
    pass


def _number(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def _identity(value):
    return type(value) is str and 0 < len(value) <= 128 and value.isascii() and all(33 <= ord(c) < 127 for c in value)


def _generation(value):
    return type(value) is int and value >= 0


def _attachment(value):
    if type(value) is not AttachmentEvidence or not _identity(value.binding) or not _generation(value.generation):
        return False
    if type(value.fresh) is not bool:
        return False
    if any(x is not None and type(x) is not bool for x in (
            value.authorization_requested, value.authorized, value.enrolled, value.gpu_present)):
        return False
    return all(x is None or _identity(x) for x in (value.authorization_binding, value.enrollment_binding)) and all(
        x is None or _generation(x) for x in (value.authorization_generation, value.enrollment_generation))


def collect_native_evidence(reader: NativeEvidenceReader, *, clock: Callable[[], float],
                            cancelled: Callable[[], bool] = lambda: False,
                            limits: ReadLimits = ReadLimits()) -> EvidenceReport:
    """Read no more than three times. Budgets cannot enlarge the fixed ceilings.

Reader-raised exceptions are categorical, with no native identifiers or messages
returned. Cancellation/deadline checks bracket every call; blocking readers must
enforce the supplied deadline themselves. This is not an OS timeout mechanism.
"""
    fail = lambda code: EvidenceReport("evidence." + code)
    if (type(limits) is not ReadLimits or not _number(limits.seconds)
            or not 0 < limits.seconds <= 30 or not _number(limits.max_age)
            or not 0 <= limits.max_age <= 30
            or type(limits.max_bytes) is not int or not 0 < limits.max_bytes <= 65536
            or type(limits.max_objects) is not int or not 2 <= limits.max_objects <= 64):
        return fail("limits_invalid")
    try:
        start = clock()
        if not _number(start):
            return fail("clock_invalid")
        budget = ReadBudget(start + limits.seconds, limits.max_bytes, limits.max_objects)
        last = start

        def guard():
            nonlocal last
            cancellation = cancelled()
            if type(cancellation) is not bool or cancellation:
                raise InterruptedError
            now = clock()
            if not _number(now) or now < last:
                raise _InvalidClock
            last = now
            if now >= budget.deadline:
                raise TimeoutError

        guard()
        owner = reader.service_owner(budget)
        guard()
        if owner is None:
            return fail("service_unavailable")
        if not _identity(owner):
            return fail("owner_invalid")
        remaining = limits.max_bytes - 2 * len(owner)
        if remaining < 0:
            return fail("bounds")
        guard()
        snapshot = reader.observe(owner, ReadBudget(budget.deadline, remaining, limits.max_objects - 2))
        guard()
        if (type(snapshot) is not NativeSnapshot or not _number(snapshot.captured_at)
                or any(type(x) is not Fact for x in (snapshot.api, snapshot.plugin_context,
                       snapshot.static_permission, snapshot.enrollment_store, snapshot.attachment_state))
                or type(snapshot.bytes_read) is not int or snapshot.bytes_read < 0
                or type(snapshot.objects_read) is not int or snapshot.objects_read < 0
                or (snapshot.attachment is not None and not _attachment(snapshot.attachment))):
            return fail("malformed")
        if snapshot.objects_read + 2 > limits.max_objects or snapshot.bytes_read + 2 * len(owner) > limits.max_bytes:
            return fail("bounds")
        guard()
        after = reader.service_owner(budget)
        guard()
        if after != owner or type(after) is not str:
            return fail("owner_changed")
        if not 0 <= last - snapshot.captured_at <= limits.max_age:
            return fail("stale")
        attachment = snapshot.attachment
        if snapshot.attachment_state is not Fact.OBSERVED:
            return EvidenceReport("evidence.observed", replace(snapshot, attachment=None))
        if attachment is not None:
            authorized = attachment.authorized if (attachment.fresh
                and attachment.authorization_binding == attachment.binding
                and attachment.authorization_generation == attachment.generation) else None
            enrolled = attachment.enrolled if (attachment.fresh
                and attachment.enrollment_binding == attachment.binding
                and attachment.enrollment_generation == attachment.generation) else None
            snapshot = replace(snapshot, attachment=replace(attachment, authorized=authorized, enrolled=enrolled))
        return EvidenceReport("evidence.observed", snapshot)
    except InterruptedError:
        return fail("cancelled")
    except TimeoutError:
        return fail("timeout")
    except PermissionError:
        return fail("denied")
    except NotImplementedError:
        return fail("unsupported")
    except _InvalidClock:
        return fail("clock_invalid")
    except Exception:
        return fail("error")
