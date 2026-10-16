"""Explicit development RPC read, separate from authorization/reconciliation.

Imports of the native reader/XML implementation are request-local: an optional
native module missing in Decky's Python cannot prevent plugin startup. No UI,
background poll, retained device identity, journal or permission request.
"""
import threading
import time
import os

_READ_LOCK=threading.Lock()
_CODES=frozenset('observed service_unavailable owner_invalid owner_changed limits_invalid clock_invalid malformed bounds stale cancelled timeout denied unsupported error'.split())


def unavailable(code='usb4_diagnostic.unavailable'):
    return dict(schema_version=1,code=code,available=False,api='unknown',
        plugin_context='unknown',static_permission='unknown',enrollment_store='unknown',
        attachment_state='unknown',process_identity='unknown',hardware_write=False,mutation_allowed=False,safe_to_unplug=False)


def create_reader(clock):
    from ..adapters.steamos.commands import BoltNativeReadCommandRunner
    from ..adapters.steamos.bolt_native_read_transport import BoltNativeReadTransport
    from ..adapters.steamos.usb4_native_evidence import BoltNativeEvidenceReader
    return BoltNativeEvidenceReader(BoltNativeReadTransport(BoltNativeReadCommandRunner(),clock=clock),clock=clock)


def read_usb4_native_diagnostic(*, collector=None, clock=time.monotonic):
    if not _READ_LOCK.acquire(blocking=False):
        return unavailable('usb4_diagnostic.busy')
    try:
        from ..application.usb4_native_evidence import collect_native_evidence
        from ..ports.usb4_native_evidence import Fact, ReadLimits
        report=(collector or collect_native_evidence)(create_reader(clock),clock=clock,
            limits=ReadLimits(seconds=3,max_age=2))
        code=report.code if report.code in {'evidence.'+c for c in _CODES} else 'evidence.error'
        result=unavailable(code)
        result.update(available=True,plugin_context='observed')
        uid=getattr(os,'geteuid',lambda:None)()
        if type(uid) is int and uid>=0:
            result['process_identity']='root' if uid==0 else 'nonroot'
        if report.snapshot is not None and code=='evidence.observed':
            for name in ('api','enrollment_store','attachment_state'):
                fact=getattr(report.snapshot,name,None)
                if type(fact) is Fact: result[name]=fact.value
        # Neither read success nor daemon ownership qualifies grant permission.
        return result
    except ImportError:
        return unavailable('usb4_diagnostic.reader_unavailable')
    except Exception:
        return unavailable('evidence.error')
    finally:
        _READ_LOCK.release()
