"""Linux-only transient read supervision. Own children only; no system setting.

Each slot has 2.5s of work plus at most .5s kill/reap confirmation inside 3s.
The complete collector has 44s of work plus at most 1s cleanup inside 45s.
No worker is accepted until its process group AND adopted children are gone.
"""
import base64
import ctypes
import json
import math
import os
import selectors
import subprocess
import signal
import time


class GuardFailure(Exception): pass


FRAME_MAGIC=b'RPS1'
FRAME_HEADER=8


def frame_result(value,cap):
    """One length-delimited result. Never use descendant-owned EOF as completion."""
    try:
        body=json.dumps({'ok':True,'value':value},separators=(',',':'),allow_nan=False).encode('utf-8')
    except (ValueError,TypeError,UnicodeError,RecursionError):
        body=b'{"ok":false,"error":"worker_failed"}'
    if len(body)>cap:body=b'{"ok":false,"error":"output_bound"}'
    if len(body)>cap:raise GuardFailure('output_bound')
    return FRAME_MAGIC+len(body).to_bytes(4,'big')+body


def frame_length(data,cap):
    if len(data)<FRAME_HEADER:return None
    if bytes(data[:4])!=FRAME_MAGIC:raise GuardFailure('result_frame_invalid')
    size=int.from_bytes(data[4:8],'big')
    if size==0 or size>cap:raise GuardFailure('output_bound')
    total=FRAME_HEADER+size
    if len(data)>total:raise GuardFailure('result_trailing')
    return total


def decode_result(data,cap):
    total=frame_length(data,cap)
    if total is None or len(data)!=total:raise GuardFailure('result_truncated')
    def pairs(items):
        result={}
        for key,value in items:
            if key in result:raise GuardFailure('result_malformed')
            result[key]=value
        return result
    def finite_float(text):
        value=float(text)
        if not math.isfinite(value):raise GuardFailure('result_malformed')
        return value
    try:
        text=bytes(data[FRAME_HEADER:]).decode('utf-8',errors='strict')
        depth=0;quoted=False;escaped=False
        for char in text:
            if quoted:
                if escaped:escaped=False
                elif char=='\\':escaped=True
                elif char=='"':quoted=False
            elif char=='"':quoted=True
            elif char in '[{':
                depth+=1
                if depth>32:raise GuardFailure('result_malformed')
            elif char in ']}':depth-=1
        decoder=json.JSONDecoder(object_pairs_hook=pairs,parse_float=finite_float,
            parse_constant=lambda _: (_ for _ in ()).throw(GuardFailure('result_malformed')))
        result,end=decoder.raw_decode(text)
        if end!=len(text):raise GuardFailure('result_trailing')
    except (ValueError,UnicodeError,RecursionError):raise GuardFailure('result_malformed') from None
    if type(result) is not dict or type(result.get('ok')) is not bool:raise GuardFailure('result_malformed')
    if result['ok']:
        if set(result)!={'ok','value'}:raise GuardFailure('result_malformed')
        return result['value']
    if set(result)!={'ok','error'} or result['error'] not in ('worker_failed','output_bound'):
        raise GuardFailure('result_malformed')
    raise GuardFailure(result['error'])


def drain_result_after_cleanup(read_fd,data,cap):
    """All own writers must be gone before EOF and no trailing bytes are accepted."""
    total=frame_length(data,cap)
    if total is None or len(data)!=total:raise GuardFailure('result_truncated')
    try:extra=os.read(read_fd,1)
    except BlockingIOError:raise GuardFailure('result_pipe_unconfirmed') from None
    if extra:raise GuardFailure('result_trailing')
    return decode_result(data,cap)


def set_subreaper():
    if os.name!='posix' or not hasattr(os,'fork') or not hasattr(os,'pidfd_open') or not hasattr(signal,'pidfd_send_signal'):
        raise GuardFailure('supervision_unavailable')
    libc=ctypes.CDLL(None,use_errno=True)
    if libc.prctl(36,1,0,0,0)!=0:raise GuardFailure('supervision_unavailable')


def children():
    with open('/proc/self/task/'+str(os.getpid())+'/children','rb') as f:raw=f.read(4097)
    if len(raw)>4096:raise GuardFailure('child_cleanup_unconfirmed')
    values=[int(x) for x in raw.split()]
    if len(values)>64 or any(x<=1 for x in values):raise GuardFailure('child_cleanup_unconfirmed')
    return values


def cleanup(pid,deadline):
    # The leader is held unreaped until the first group signal, preventing PID reuse.
    try:os.killpg(pid,signal.SIGKILL)
    except ProcessLookupError:
        try:os.kill(pid,signal.SIGKILL)
        except ProcessLookupError:pass
    while time.monotonic()<deadline:
        # Signal only pidfd-bound, parent-qualified children of this supervisor.
        for child in children():
            try:fd=os.pidfd_open(child)
            except ProcessLookupError:continue
            try:
                with open('/proc/'+str(child)+'/status','rb') as f:raw=f.read(8193)
                if len(raw)>8192 or b'PPid:\t'+str(os.getpid()).encode()+b'\n' not in raw:
                    raise GuardFailure('child_cleanup_unconfirmed')
                signal.pidfd_send_signal(fd,signal.SIGKILL)
            except FileNotFoundError:pass
            finally:os.close(fd)
        while True:
            try:
                child,_=os.waitpid(-1,os.WNOHANG)
                if not child:break
            except ChildProcessError:break
        try:os.killpg(pid,0);group=True
        except ProcessLookupError:group=False
        if not group and not children():return
        time.sleep(.005)
    raise GuardFailure('child_cleanup_unconfirmed')


def guard_call(fn,total_seconds=3,cleanup_seconds=.5,cap=16384):
    """Fork with a parent watchdog; every post-fork path guarantees cleanup."""
    if type(cap) is not int or not 64<=cap<=262144:raise GuardFailure('output_bound')
    started=time.monotonic();hard=started+total_seconds;work=hard-cleanup_seconds
    set_subreaper()
    if children():raise GuardFailure('supervisor_not_dedicated')
    # Fail selector initialization before any worker exists.
    sel=selectors.DefaultSelector()
    read_fd=write_fd=None;pid=None;data=bytearray();failure=None;confirmed=False
    previous={};oldmask=None
    cancellation=(signal.SIGTERM,signal.SIGINT,signal.SIGHUP)
    def cancel(signum,frame):raise GuardFailure('interrupted')
    try:
        oldmask=signal.pthread_sigmask(signal.SIG_BLOCK,cancellation)
        for sig in cancellation:previous[sig]=signal.signal(sig,cancel)
        read_fd,write_fd=os.pipe2(os.O_CLOEXEC|os.O_NONBLOCK)
        pid=os.fork()
        if pid==0:
            try:
                os.close(read_fd);sel.close();os.setsid()
                signal.pthread_sigmask(signal.SIG_SETMASK,oldmask)
                raw=frame_result(fn(),cap)
            except BaseException:
                error=b'{"ok":false,"error":"worker_failed"}'
                raw=FRAME_MAGIC+len(error).to_bytes(4,'big')+error
            try:
                sent=0
                while sent<len(raw):
                    if time.monotonic()>=work:break
                    try:sent+=os.write(write_fd,raw[sent:sent+512])
                    except BlockingIOError:time.sleep(.001)
            except BaseException:pass
            finally:os._exit(0)
        os.close(write_fd);write_fd=None
        sel.register(read_fd,selectors.EVENT_READ)
        signal.pthread_sigmask(signal.SIG_SETMASK,oldmask)
        complete=False
        while not complete:
            remaining=work-time.monotonic()
            if remaining<=0:raise GuardFailure('call_timeout')
            for _,_ in sel.select(timeout=min(.02,remaining)):
                block=os.read(read_fd,min(512,cap+FRAME_HEADER+1-len(data)))
                if not block:raise GuardFailure('result_truncated')
                data.extend(block)
                total=frame_length(data,cap)
                complete=total is not None and len(data)==total
                if complete:break
    except BaseException as exc:failure=exc
    finally:
        # Mask repeated cancellation for finite teardown, then restore caller state.
        if oldmask is not None:signal.pthread_sigmask(signal.SIG_BLOCK,cancellation)
        try:
            try:sel.close()
            except BaseException:failure=GuardFailure('result_pipe_unconfirmed')
            for fd in (write_fd,):
                if fd is not None:
                    try:os.close(fd)
                    except OSError:pass
            if pid is not None and pid>0:
                try:
                    cleanup(pid,hard);confirmed=True
                except BaseException:failure=GuardFailure('child_cleanup_unconfirmed')
                if confirmed and failure is None:
                    # Keep the reader through teardown: inherited writers cannot
                    # delay completion, but bytes they emitted must not disappear.
                    try:value=drain_result_after_cleanup(read_fd,data,cap)
                    except GuardFailure as exc:failure=exc
                    except BaseException:failure=GuardFailure('result_malformed')
        finally:
            if read_fd is not None:
                try:os.close(read_fd)
                except OSError:pass
            for sig,handler in previous.items():signal.signal(sig,handler)
            if oldmask is not None:signal.pthread_sigmask(signal.SIG_SETMASK,oldmask)
    if pid is not None and not confirmed:raise GuardFailure('child_cleanup_unconfirmed')
    if failure:raise failure
    if time.monotonic()>hard:raise GuardFailure('call_timeout')
    return value


class GuardedNative:
    def __init__(self,native_type):
        self.native_type=native_type;self.budget=native_type().budget

    def invoke(self,slot,kind,arg):
        # Count and reserve in the parent before a worker can touch its selector.
        self.budget.begin(slot);before=self.budget.bytes
        def action():
            n=self.native_type();n.budget=self.budget
            n.budget.calls-=1
            try:
                raw=n.invoke(slot,kind,arg)
                return {'raw':base64.b64encode(raw).decode(),'bytes':n.budget.bytes-before,'error':None}
            except Exception as exc:
                return {'raw':'','bytes':n.budget.bytes-before,'error':getattr(exc,'code','read_unavailable')}
        try:
            result=guard_call(action)
        except GuardFailure:
            # If a worker cannot reply, bill its complete possible byte allowance.
            self.budget.approximate=True
            self.budget.account(9216)
            raise
        self.budget.account(result['bytes'])
        if result['error']:
            # Native exception class is injected by the fixed caller.
            raise self.native_type.stop_type(result['error'])
        return base64.b64decode(result['raw'],validate=True)




class ReadFailure(Exception):
    def __init__(self,code):self.code=code


def check_deadline(deadline):
    if time.monotonic()>=deadline:raise ReadFailure('call_timeout')


def bounded_command(argv,deadline,account,cap=8192):
    argv=tuple(argv)
    proc=None;sel=selectors.DefaultSelector();out=bytearray();err=bytearray();seen=0
    try:
        proc=subprocess.Popen(argv,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                              shell=False,start_new_session=True,
                              env={'PATH':'/usr/bin:/bin','LANG':'C','LC_ALL':'C'})
        for pipe in (proc.stdout,proc.stderr):
            os.set_blocking(pipe.fileno(),False);sel.register(pipe,selectors.EVENT_READ)
        while sel.get_map():
            check_deadline(deadline)
            for key,_ in sel.select(timeout=min(.03,max(0,deadline-time.monotonic()))):
                try:data=os.read(key.fileobj.fileno(),512)
                except BlockingIOError:continue
                if not data:sel.unregister(key.fileobj);continue
                seen+=len(data);account(len(data))
                if seen>cap:raise ReadFailure('output_bound')
                (out if key.fileobj is proc.stdout else err).extend(data)
        check_deadline(deadline)
        # Observe completion without reaping. The unreaped leader pins its PID /
        # process-group identity until the group's final signal in finally.
        while True:
            check_deadline(deadline)
            info=os.waitid(os.P_PID,proc.pid,os.WEXITED|os.WNOHANG|os.WNOWAIT)
            if info is not None:break
            time.sleep(.005)
        rc=info.si_status if info.si_code==os.CLD_EXITED else -1
        if rc:raise ReadFailure('read_unavailable')
        return bytes(out)
    finally:
        sel.close()
        if proc is not None:
            # Only the child process group created by THIS read invocation.
            try:os.killpg(proc.pid,signal.SIGKILL)
            except ProcessLookupError:pass
            try:proc.wait(timeout=.25)
            except subprocess.TimeoutExpired:raise ReadFailure('child_cleanup_unconfirmed') from None
            for pipe in (proc.stdout,proc.stderr):pipe.close()
