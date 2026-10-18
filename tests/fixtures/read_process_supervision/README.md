# Generic process-supervision CI candidate

The two adjacent Python files are the exact production implementation and its
standalone device-free fixtures. No configured route, host, credentials, private
receipt, installed-plugin path or device commands are included or imported.

Run serially on a dedicated nonroot Linux Python 3.11+ executor:

    python3 -I -S -B -m unittest discover -s . -p test_read_process_supervision.py -v

Expected: nine passes, zero skips. Eight fixtures use real Linux fork/process
sessions, own-child subreaping and pidfds, a temporary FIFO, cancellation masks,
combined synthetic command-output overflow and cleanup after setup failure. The
ninth checks that a process group is signaled before its leader is reaped.
The escaped-descendant fixture confirms setsid completion before proceeding.

Requires /proc, libc.prctl(PR_SET_CHILD_SUBREAPER), fork, pipe2, pidfd_open,
pidfd_send_signal, pthread_sigmask, waitid(WNOWAIT), and a writable POSIX temporary
directory. No SSH, D-Bus, RPM, network, devices, sudo, installation or credentials
are needed. The test interpreter signals/reaps only its own synthetic children.
Run without unrelated child processes or parallel tests in that interpreter.

Keep these two files adjacent, in paths approved by the retained repository
owner. The fixture loads only the adjacent module and Python standard library.
The generic module is passed unchanged to the private route boundary as data;
there is no sanitized replacement implementation or stub. CI must record both
file hashes and the Python/kernel versions alongside its test result.

This folder is a publication candidate, not a publication instruction. Retained
source-owner privacy and repository ownership review is required before CI
integration. The separate private bridge and private tests are intentionally
excluded from this execution set.
