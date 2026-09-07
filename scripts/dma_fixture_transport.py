"""Strict disposable DMA fixture IPC. No GPU opens or parent fork ownership."""
import array
import ctypes
import json
import math
import os
import signal
import socket


def _sequence(value):
    if type(value) is not int or not 1 <= value <= 16:
        raise ValueError('invalid fixture sequence')


def _json(raw):
    if type(raw) is not bytes or not 0 < len(raw) <= 512:
        raise ValueError('invalid packet length')
    def pairs(items):
        result = {}
        for key,value in items:
            if key in result: raise ValueError('duplicate packet key')
            result[key] = value
        return result
    value = json.loads(raw.decode('ascii'), object_pairs_hook=pairs,
                       parse_constant=lambda _: (_ for _ in ()).throw(ValueError('invalid number')))
    if type(value) is not dict: raise ValueError('object packet required')
    return value


def receive_one(sock, sequence=None):
    """Return descriptor identity; every delivered descriptor is closed."""
    if sequence is not None: _sequence(sequence)
    sock.settimeout(5)
    raw, ancillary, flags, _ = sock.recvmsg(513, socket.CMSG_SPACE(64 * array.array('i').itemsize),
                                           socket.MSG_CMSG_CLOEXEC)
    flags &= ~socket.MSG_CMSG_CLOEXEC
    descriptors = []
    malformed = False
    try:
        for level,kind,data in ancillary:
            if level != socket.SOL_SOCKET or kind != socket.SCM_RIGHTS:
                malformed = True
                continue
            values = array.array('i')
            size = values.itemsize
            values.frombytes(data[:len(data)//size*size])
            descriptors.extend(values)
            malformed |= len(data) % size != 0
        if raw == b'stop' and not ancillary and not flags: return None
        packet = _json(raw)
        _sequence(packet.get('sequence'))
        if sequence is None: sequence = packet['sequence']
        if (malformed or flags & ~socket.MSG_CTRUNC or set(packet) != {'sequence'}
                or type(packet['sequence']) is not int or packet['sequence'] != sequence
                or len(descriptors) > 1):
            raise ValueError('invalid descriptor packet')
        truncated = bool(flags & socket.MSG_CTRUNC)
        if truncated and descriptors:
            raise ValueError('partial descriptor delivery')
        identity = os.fstat(descriptors[0]) if descriptors else None
        return dict(sequence=sequence, received=len(descriptors), truncated=truncated,
                    identity=[identity.st_dev,identity.st_ino] if identity else None)
    finally:
        errors = []
        for fd in descriptors:
            try: os.close(fd)
            except OSError as exc: errors.append(exc)
        if errors: raise OSError('received descriptor cleanup failed') from errors[0]


def send_descriptor(sock, fd, sequence):
    _sequence(sequence)
    if type(fd) is not int or fd < 0: raise ValueError('invalid send descriptor')
    sock.settimeout(5)
    packet = json.dumps(dict(sequence=sequence), separators=(',', ':')).encode('ascii')
    if sock.sendmsg([packet], [(socket.SOL_SOCKET,socket.SCM_RIGHTS,array.array('i',[fd]))]) != len(packet):
        raise ValueError('short descriptor packet')


def exchange(sock, fd, sequence):
    send_descriptor(sock,fd,sequence)
    # Responses must never carry descriptors; receive/close any unexpected FDs.
    raw, ancillary, flags, _ = sock.recvmsg(513, socket.CMSG_SPACE(64*array.array('i').itemsize),
                                           socket.MSG_CMSG_CLOEXEC)
    flags &= ~socket.MSG_CMSG_CLOEXEC
    received = []
    try:
        for level,kind,data in ancillary:
            if level == socket.SOL_SOCKET and kind == socket.SCM_RIGHTS:
                values=array.array('i'); values.frombytes(data[:len(data)//values.itemsize*values.itemsize])
                received.extend(values)
        if ancillary or flags: raise ValueError('unexpected response ancillary or truncation')
        result = _json(raw)
        if (set(result) != {'sequence','received','truncated','identity'}
                or type(result['sequence']) is not int or result['sequence'] != sequence
                or type(result['received']) is not int or result['received'] not in (0,1)
                or type(result['truncated']) is not bool):
            raise ValueError('invalid fixture response')
        if result['received']:
            identity=result['identity']
            if (result['truncated'] or type(identity) is not list or len(identity)!=2
                    or any(type(v) is not int or not 0 < v < 2**64 for v in identity)):
                raise ValueError('invalid descriptor identity')
        elif result['identity'] is not None or not result['truncated']:
            raise ValueError('invalid rejected delivery')
        return result
    finally:
        errors=[]
        for item in received:
            try:os.close(item)
            except OSError as exc:errors.append(exc)
        if errors:raise OSError('response descriptor cleanup failed') from errors[0]


def _inventory():
    # Listdir closes its own enumeration FD before these fstat checks.
    names = os.listdir('/proc/self/fd')
    if len(names) > 4096 or any(not name.isdecimal() for name in names):
        raise ValueError('unbounded descriptor inventory')
    result = set()
    for name in names:
        fd = int(name)
        try: os.fstat(fd)
        except OSError as exc:
            if exc.errno == 9: continue  # Closed enumeration FD only in this single-threaded child.
            raise
        result.add(fd)
    return result


def receiver(sock, directory, parent, *, idle_timeout=5):
    """Fork-child entry; exits without returning. Parent owns fork and cleanup."""
    try:
        if (type(idle_timeout) not in (int,float) or not math.isfinite(idle_timeout)
                or not 0<idle_timeout<=60):
            raise ValueError('bounded receiver idle timeout required')
        if type(parent) is not int or parent <= 0:
            raise ValueError('invalid receiver lifecycle')
        libc = ctypes.CDLL(None,use_errno=True)
        if libc.prctl(1,signal.SIGKILL,0,0,0) != 0 or os.getppid() != parent:
            raise ValueError('parent lifetime unavailable')
        keep = {sock.fileno(), directory}
        for fd in _inventory() - keep: os.close(fd)
        member = os.open('cgroup.procs',os.O_WRONLY|os.O_NOFOLLOW,dir_fd=directory)
        try:
            packet = str(os.getpid()).encode('ascii')
            if os.write(member,packet) != len(packet): raise OSError('short membership write')
        finally: os.close(member)
        os.close(directory)
        if _inventory() != {sock.fileno()}: raise ValueError('inherited descriptors remain')
        sock.settimeout(5)
        if sock.send(b'ready') != 5: raise OSError('short readiness packet')
        for sequence in range(1,17):
            sock.settimeout(idle_timeout)
            # SOCK_SEQPACKET readiness leaves the full packet for receive_one.
            # MSG_PEEK without an ancillary buffer installs no received FDs.
            if not sock.recv(1,socket.MSG_PEEK):raise ValueError('receiver peer closed')
            result=receive_one(sock,sequence)
            if result is None: break
            payload = json.dumps(result,separators=(',',':')).encode('ascii')
            if sock.send(payload) != len(payload): raise OSError('short response')
        sock.close()
    except BaseException:
        os._exit(2)
    os._exit(0)
