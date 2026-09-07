"""Disposable independent direct-open and SCM_RIGHTS enforcement controls.

Receiver commands name no paths or PIDs. The only opens are fixed /dev/null
and /dev/zero constants; no player, GPU or inherited-resource coverage exists.
"""
import array
import errno
import json
import os
from pathlib import Path
import socket
import stat
import sys

if Path(__file__).name!='__main__.py':
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))

from scripts.probe_paired_journal_fixture import run_fixture as journal_fixture
from scripts.probe_filter_preparation_fixture import publish_preparation,recover_preparation
from scripts.probe_killed_filter_controller import _child_setup


def open_controls(*,open_fd=os.open,fstat=os.fstat,close_fd=os.close):
    results=[]
    for path,minor in (('/dev/null',3),('/dev/zero',5)):
        try:fd=open_fd(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC)
        except OSError as error:
            if error.errno!=errno.EPERM:raise
            results.append(False)
        else:
            try:
                info=fstat(fd)
                if not stat.S_ISCHR(info.st_mode) or info.st_rdev!=os.makedev(1,minor):
                    raise ValueError('dummy open identity mismatch')
                results.append(True)
            finally:close_fd(fd)
    return dict(null_opened=results[0],zero_opened=results[1])


def receive_command(sock,*,open_probe=open_controls,fstat=os.fstat,close_fd=os.close):
    data,ancillary,flags,_=sock.recvmsg(16,socket.CMSG_SPACE(array.array('i').itemsize))
    descriptors=[]
    try:
        malformed=False
        for level,kind,raw in ancillary:
            if level!=socket.SOL_SOCKET or kind!=socket.SCM_RIGHTS:
                malformed=True;continue
            values=array.array('i')
            complete=len(raw)-len(raw)%values.itemsize
            values.frombytes(raw[:complete]);descriptors.extend(values)
            if complete!=len(raw):malformed=True
        if malformed or flags&~socket.MSG_CTRUNC:raise ValueError('unexpected ancillary packet')
        if data==b'fd':
            if len(descriptors)>1:raise ValueError('too many descriptors')
            return dict(received=len(descriptors),truncated=bool(flags&socket.MSG_CTRUNC),
                        device=fstat(descriptors[0]).st_rdev if descriptors else None)
        if descriptors or flags:raise ValueError('control command carries descriptors')
        if data==b'open-controls':return open_probe()
        if data==b'stop':return None
        raise ValueError('unknown fixed receiver command')
    finally:
        errors=[]
        for fd in descriptors:
            try:close_fd(fd)
            except OSError as error:errors.append(error)
        if errors:raise errors[0]


def enforcement_receiver(sock,directory,parent):
    try:
        _child_setup(parent,{sock.fileno(),directory})
        fd=os.open('cgroup.procs',os.O_WRONLY|os.O_NOFOLLOW,dir_fd=directory)
        try:
            packet=str(os.getpid()).encode('ascii')
            if os.write(fd,packet)!=len(packet):raise ValueError('short membership write')
        finally:os.close(fd)
        os.close(directory)
        sock.settimeout(8)
        if sock.send(b'ready')!=5:raise ValueError('short readiness')
        for _ in range(16):
            result=receive_command(sock)
            if result is None:break
            packet=json.dumps(result,separators=(',',':')).encode('ascii')
            if len(packet)>256 or sock.send(packet)!=len(packet):raise ValueError('short result')
    except BaseException:os._exit(2)
    os._exit(0)


def probe_open_controls(sock,*,denied):
    if type(denied) is not bool:raise ValueError('explicit control expectation required')
    if sock.send(b'open-controls')!=13:raise ValueError('short control request')
    raw,ancillary,flags,_=sock.recvmsg(257)
    if not raw or len(raw)>256 or ancillary or flags:raise ValueError('invalid control response')
    def pairs(items):
        result={}
        for key,value in items:
            if key in result:raise ValueError('duplicate control field')
            result[key]=value
        return result
    result=json.loads(raw,object_pairs_hook=pairs)
    if (type(result) is not dict or set(result)!={'null_opened','zero_opened'}
            or any(type(value) is not bool for value in result.values())):
        raise ValueError('invalid direct control fields')
    return result==dict(null_opened=not denied,zero_opened=True)


def run_fixture(*,runner=journal_fixture):
    observations=[]
    def probe(sock,*,denied):
        matched=probe_open_controls(sock,denied=denied)
        observations.append((denied,matched))
        return matched
    report=runner(publisher=publish_preparation,recoverer=recover_preparation,
                  receiver_factory=enforcement_receiver,extra_probe=probe)
    successful=report.get('state')=='fixture_passed'
    exact=observations==[(False,True),(True,True),(True,True),(False,True)]
    if successful and not exact:report['state']='fixture_failed'
    report.update(direct_open_denial_verified=exact and successful,
        scm_rights_denial_verified=exact and successful,
        direct_open_restoration_verified=exact and successful,
        launch_authorized=False,disconnect_clearance=False)
    return report


def main():
    if sys.argv[1:]!=['--disposable-fixture']:raise SystemExit('Explicit --disposable-fixture required')
    report=run_fixture();print(json.dumps(report,sort_keys=True))
    return 0 if report['state']=='fixture_passed' else 1


if __name__=='__main__':raise SystemExit(main())
