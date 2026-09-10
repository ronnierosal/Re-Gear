"""Pinned, no-follow user directories for privileged local delivery.

Linux publishes the open inode rather than looking up a temporary name again.
Publication never replaces an existing entry. Windows is a development test
fallback; deployed SteamOS requires descriptor operations and procfs.
"""
from __future__ import annotations

import os
import secrets
import stat
import subprocess
import sys
from pathlib import Path


class UserDirectory:
    def __init__(self, path: Path, uid: int | None = None, gid: int | None = None,
                 *, create_from: Path | None = None, create: bool = False,
                 final_mode: int = 0o700, set_owner=None):
        self.path = path
        self.fd = None
        self.uid, self.gid = uid, gid
        if final_mode not in {0o700, 0o750, 0o755}:
            raise ValueError('unsafe user directory mode')
        if not path.is_absolute() or '..' in path.parts:
            raise ValueError('unsafe user directory')
        if os.name == 'nt':
            current = Path(path.anchor)
            for part in path.parts[1:]:
                current /= part
                if create and create_from is not None and current.is_relative_to(create_from):
                    current.mkdir(mode=final_mode if current == path else 0o700, exist_ok=True)
                if current.is_symlink() or not current.is_dir():
                    raise ValueError('unsafe user directory')
            if set_owner:
                set_owner(path, uid, gid)
            return
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        descriptor = os.open(path.anchor, flags)
        current = Path(path.anchor)
        try:
            for part in path.parts[1:]:
                current /= part
                created = False
                try:
                    child = os.open(part, flags, dir_fd=descriptor)
                except FileNotFoundError:
                    if not create or create_from is None or not current.is_relative_to(create_from) or current == create_from:
                        raise
                    # mkdir returns no descriptor. Create as the destination user
                    # so a swapped entry never receives privileged chown/chmod.
                    try:
                        credentials = {}
                        if os.geteuid() == 0:
                            credentials = dict(user=uid, group=gid, extra_groups=())
                        elif (uid, gid) != (os.geteuid(), os.getegid()):
                            raise ValueError('cannot create as destination user')
                        subprocess.run(
                            [sys.executable, '-I', '-c',
                             'import os,sys; os.umask(0); os.mkdir(sys.argv[1], int(sys.argv[3]), dir_fd=int(sys.argv[2]))',
                             part, str(descriptor), str(final_mode if current == path else 0o700)],
                            pass_fds=(descriptor,), check=True, timeout=10,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            **credentials,
                        )
                    except subprocess.SubprocessError as error:
                        raise OSError('user directory creation failed') from error
                    created = True
                    child = os.open(part, flags, dir_fd=descriptor)
                os.close(descriptor)
                descriptor = child
                metadata = os.fstat(descriptor)
                if created:
                    if metadata.st_uid != uid:
                        raise ValueError('created directory owner changed')
                    if set_owner:
                        set_owner(descriptor, uid, gid)
                elif uid is not None and (current == create_from or
                        (create_from is not None and current.is_relative_to(create_from)) or current == path):
                    if metadata.st_uid != uid:
                        raise ValueError('user directory owner changed')
            metadata = os.fstat(descriptor)
            self.uid = metadata.st_uid if uid is None else uid
            self.gid = metadata.st_gid if gid is None else gid
            self.fd = descriptor
        except BaseException:
            os.close(descriptor)
            raise

    def __enter__(self):
        return self

    def __exit__(self, *args):
        if self.fd is not None:
            os.close(self.fd)

    def publish(self, name: str, data: bytes, mode: int):
        if Path(name).name != name:
            raise ValueError('unsafe delivery filename')
        if self.fd is None:
            with (self.path / name).open('xb') as target:
                target.write(data)
            return
        temporary = '.re-gear-' + secrets.token_hex(16) + '.tmp'
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                             os.O_NOFOLLOW, 0o600, dir_fd=self.fd)
        try:
            offset = 0
            while offset < len(data):
                written = os.write(descriptor, data[offset:])
                if written <= 0:
                    raise OSError('delivery write made no progress')
                offset += written
            os.fchmod(descriptor, mode)
            os.fchown(descriptor, self.uid, self.gid)
            os.fsync(descriptor)
            os.link(f'/proc/self/fd/{descriptor}', name,
                    dst_dir_fd=self.fd, follow_symlinks=True)
            os.fsync(self.fd)
        finally:
            os.close(descriptor)
            try:
                os.unlink(temporary, dir_fd=self.fd)
            except FileNotFoundError:
                pass

    def remove_matching(self, name: str, expected: bytes, limit: int):
        if self.fd is None:
            target = self.path / name
            if target.is_symlink() or target.read_bytes() != expected:
                raise ValueError('managed file changed')
            target.unlink()
            return
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                             dir_fd=self.fd)
        try:
            value = os.fstat(descriptor)
            if (not stat.S_ISREG(value.st_mode) or value.st_uid != self.uid
                    or value.st_mode & 0o022 or os.read(descriptor, limit + 1) != expected):
                raise ValueError('managed file changed')
            current = os.stat(name, dir_fd=self.fd, follow_symlinks=False)
            if (current.st_dev, current.st_ino) != (value.st_dev, value.st_ino):
                raise ValueError('managed file replaced')
            os.unlink(name, dir_fd=self.fd)
            os.fsync(self.fd)
        finally:
            os.close(descriptor)
