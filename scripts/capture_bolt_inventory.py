"""Fixed, one-shot private observation launcher. No live execution authority.

Use only a separately reviewed bridge operation with verified immutable source,
isolated Python (-I -S), outer deadline/output limits and confirmed cleanup.
No arguments, RPC, installation, authorization or trusted topology assertion.
"""
import hashlib
import json
from pathlib import Path
import re
import sys

_CODES=frozenset('capture.'+s for s in ('observed','inventory_unresolved','classification_unresolved',
    'status_unresolved','owner_changed','timeout','unavailable','malformed','bounds'))


def _capture_once():
    # -I -S excludes caller PYTHONPATH, user-site and site startup hooks. The
    # bridge must verify this root and manifest before launching; no root input.
    if not sys.flags.isolated or not sys.flags.no_site:raise ValueError
    if any(n=='regear' or n.startswith('regear.') for n in sys.modules):raise ValueError
    backend=Path(__file__).resolve().parents[1]/'backend'
    if backend.is_symlink() or not backend.is_dir():raise ValueError
    sys.path.insert(0,str(backend))
    from regear.adapters.steamos import bolt_inventory_capture, commands
    for module in (bolt_inventory_capture,commands):
        if not Path(module.__file__).resolve().is_relative_to(backend):raise ValueError
    runner=commands.BoltInventoryCaptureCommandRunner()
    return bolt_inventory_capture.capture_inventory(runner)


def _failure(code):
    return dict(schema_version=1,code=code,object_count=None,type_counts={},status_counts={},
                calls=0,bytes_read=0,advertised_path_sha256=None,path_digest_scope='advertised_only_not_binding')


def _public(report):
    def integer(n,upper):
        if type(n) is not int or not 0<=n<=upper:raise ValueError
        return n
    def counts(rows,allowed):
        if type(rows) is not tuple or len(rows)>len(allowed):raise ValueError
        result={}
        for row in rows:
            if type(row) is not tuple or len(row)!=2:raise ValueError
            key,count=row
            if type(key) is not str or key not in allowed or key in result:raise ValueError
            result[key]=integer(count,2)
            if count==0:raise ValueError
        if sum(result.values())>2:raise ValueError
        return result
    if type(report.code) is not str or report.code not in _CODES:raise ValueError
    result=_failure(report.code)
    if report.object_count is not None:result['object_count']=integer(report.object_count,64)
    result['calls']=integer(report.calls,8);result['bytes_read']=integer(report.bytes_read,65536)
    result['type_counts']=counts(report.type_counts,{'host','peripheral'})
    result['status_counts']=counts(report.status_counts,{'connected','auth-error','authorized','disconnected','unknown','connecting','authorizing'})
    path=report.sysfs_path
    if path is not None:
        if (report.code!='capture.observed' or type(path) is not str or len(path)>1024
                or not path.startswith('/sys/devices/') or any(not p or p in ('.','..')
                or not re.fullmatch(r'[A-Za-z0-9_:+.\-]+',p) for p in path.split('/')[1:])):raise ValueError
        result['advertised_path_sha256']=hashlib.sha256(path.encode('utf-8')).hexdigest()
    if report.code=='capture.observed' and (path is None or result['object_count']!=2
            or result['type_counts']!={'host':1,'peripheral':1}
            or sum(result['status_counts'].values())!=2
            or not set(result['status_counts'])<={'connected','auth-error','authorized'}):raise ValueError
    return result


def main(argv=None):
    args=sys.argv[1:] if argv is None else argv
    exit_code=1
    if args or not sys.flags.isolated or not sys.flags.no_site:
        result=_failure('capture.launcher_rejected');exit_code=2
    else:
        try:
            result=_public(_capture_once())
            exit_code=0 if result['code']=='capture.observed' else 1
        except (Exception,KeyboardInterrupt):
            result=_failure('capture.launcher_failed')
    raw=json.dumps(result,separators=(',',':'),sort_keys=True)
    if len(raw.encode('utf-8'))>4096:
        raw=json.dumps(_failure('capture.launcher_failed'));exit_code=1
    print(raw)
    return exit_code


if __name__=='__main__':raise SystemExit(main())
