"""Explicit development RPC read, separate from authorization/reconciliation.

Imports of the native reader/XML implementation are request-local: an optional
native module missing in Decky's Python cannot prevent plugin startup. No UI,
background poll, retained device identity, journal or permission request.
"""
import threading
import time
import os
import importlib
import types

_READ_LOCK=threading.Lock()
_CODES=frozenset('observed service_unavailable owner_invalid owner_changed limits_invalid clock_invalid malformed bounds stale cancelled timeout denied unsupported error'.split())
_IMPORTS = (
    ('collector', 'regear.application.usb4_native_evidence', ('collect_native_evidence',)),
    ('facts', 'regear.ports.usb4_native_evidence', ('Fact', 'ReadLimits')),
    ('command_runner', 'regear.adapters.steamos.commands', ('BoltNativeReadCommandRunner',)),
    ('transport', 'regear.adapters.steamos.bolt_native_read_transport', ('BoltNativeReadTransport',)),
    ('reader', 'regear.adapters.steamos.usb4_native_evidence', ('BoltNativeEvidenceReader',)),
)


def _import_failure(error):
    """Map names internally; no exception name, text, type or path is public."""
    name = error.name
    if type(name) is not str:
        return 'dependency_unavailable'
    if name in ('xml', 'xml.etree', 'xml.etree.ElementTree', 'xml.parsers',
                'xml.parsers.expat', 'pyexpat', '_elementtree'):
        return 'xml_runtime_unavailable'
    if name in ('selectors', 'select', 'fcntl', 'subprocess', '_posixsubprocess', '_winapi'):
        return 'process_runtime_unavailable'
    if name in tuple(module for _, module, _ in _IMPORTS):
        return 'module_unavailable'
    return 'dependency_unavailable'


def _import_preflight():
    """Fixed module/symbol reads only. Never instantiate or invoke a symbol."""
    rows = [dict(stage='facade', outcome='ready', failure='none')]
    imported = {}
    for stage, name, symbols in _IMPORTS:
        failure = 'none'
        try:
            module = importlib.import_module(name)
            if not isinstance(module, types.ModuleType):
                failure = 'module_unavailable'
            elif not all(symbol in vars(module) and callable(vars(module)[symbol]) for symbol in symbols):
                failure = 'symbol_unavailable'
            else:
                imported[stage] = {symbol: vars(module)[symbol] for symbol in symbols}
        except ImportError as error:
            failure = _import_failure(error)
        except Exception:
            failure = 'import_failed'
        rows.append(dict(stage=stage, outcome='ready' if failure == 'none' else 'failed', failure=failure))
    return rows, imported


def unavailable(code='usb4_diagnostic.unavailable'):
    return dict(schema_version=1,code=code,available=False,api='unknown',
        plugin_context='unknown',static_permission='unknown',enrollment_store='unknown',
        attachment_state='unknown',process_identity='unknown',hardware_write=False,mutation_allowed=False,safe_to_unplug=False)


def create_reader(clock, imported):
    runner = imported['command_runner']['BoltNativeReadCommandRunner']
    transport = imported['transport']['BoltNativeReadTransport']
    reader = imported['reader']['BoltNativeEvidenceReader']
    return reader(transport(runner(), clock=clock), clock=clock)


def read_usb4_native_diagnostic(*, collector=None, clock=time.monotonic):
    if not _READ_LOCK.acquire(blocking=False):
        return unavailable('usb4_diagnostic.busy')
    imports = []
    try:
        imports, imported = _import_preflight()
        if any(row['outcome'] != 'ready' for row in imports):
            return {**unavailable('usb4_diagnostic.reader_unavailable'), 'imports': imports}
        collect_native_evidence = imported['collector']['collect_native_evidence']
        Fact, ReadLimits = imported['facts']['Fact'], imported['facts']['ReadLimits']
        report=(collector or collect_native_evidence)(create_reader(clock, imported),clock=clock,
            limits=ReadLimits(seconds=3,max_age=2))
        code=report.code if report.code in {'evidence.'+c for c in _CODES} else 'evidence.error'
        result=unavailable(code)
        result.update(available=True,plugin_context='observed',imports=imports)
        uid=getattr(os,'geteuid',lambda:None)()
        if type(uid) is int and uid>=0:
            result['process_identity']='root' if uid==0 else 'nonroot'
        if report.snapshot is not None and code=='evidence.observed':
            for name in ('api','enrollment_store','attachment_state'):
                fact=getattr(report.snapshot,name,None)
                if type(fact) is Fact: result[name]=fact.value
        # Neither read success nor daemon ownership qualifies grant permission.
        return result
    except ImportError as error:
        return {**unavailable('usb4_diagnostic.reader_unavailable'), 'imports': imports + [dict(
            stage='execution', outcome='failed', failure=_import_failure(error))]}
    except Exception:
        return unavailable('evidence.error')
    finally:
        _READ_LOCK.release()
