# Generic process-supervision CI correction v2

This candidate corrects the exact result-pipe failure at commit
b7141de903851ccbfdb55fb488098fd2631f0c30. Both profiles ran all nine fixtures:
eight passed and the escaped-descendant test timed out. The failed bytes and CI
evidence are preserved. No corrected Linux PASS is claimed in this packet.

The two adjacent Python files are the actual production implementation and its
standalone device-free fixtures. No route, host, key, credentials, private
receipt, installed-plugin path or device commands are included or imported.

The worker emits one RPS1 frame: a four-byte magic plus a four-byte bounded body
length and one strict JSON envelope. Parent-side framing completion allows
mandatory process-group/adopted-descendant cleanup to begin while an escaped
child still holds an inherited writer. The reader stays open through teardown;
acceptance then requires confirmed cleanup, EOF and no trailing bytes. Truncated,
oversized, malformed, duplicate-key, nonfinite (including numeric overflow),
extra-envelope and trailing results are rejected. A complete frame never bypasses
failed cleanup. The fixture's inherited descriptor is not hidden or closed as a
workaround. Original deadlines are unchanged.

Run serially on a dedicated nonroot Linux Python 3.11+ executor:

    python3 -I -S -B -m unittest discover -s . -p test_read_process_supervision.py -v

Expected: twenty-one passes, zero skips. All eight original Linux fixtures,
including the escaped-child handshake, remain AST-identical. Two additional
Linux cases inject adversarial frames through the real pipe and verify rejection
and reaping, including a truncated frame whose escaped child retains its writer.
Eleven portable tests cover framing, malformed/duplicate/nonfinite/oversized/
truncated/trailing data, post-cleanup EOF and mandatory teardown ordering, plus
the retained signal-before-leader-reap regression. Do not weaken the original
escaped-child test, extend its deadline, or select a passing subset. If a CI
discovery gate asserts the old fixture count, update the count to21 while keeping
all original methods and running the complete suite.

Requires /proc, libc.prctl(PR_SET_CHILD_SUBREAPER), fork, pipe2, pidfd_open,
pidfd_send_signal, pthread_sigmask, waitid(WNOWAIT), and a writable POSIX temporary
directory. No SSH, D-Bus, RPM, network, devices, sudo, installation or credentials
are needed. The interpreter signals/reaps only its own synthetic children. Run
without unrelated children or parallel tests in that interpreter.

Keep the module and fixture adjacent in owner-approved repository paths. The
fixture loads only the adjacent production module and Python standard library.
The private route consumes these same bytes at its configuration boundary; no
sanitized replacement or test-only implementation is substituted. CI must record
both file hashes and Python/kernel versions with the complete result.

This is a privacy-reviewable publication candidate, not a publication instruction.
The private bridge, private route tests and private evidence are excluded. Source
owner retains repository integration, CI publication and acceptance gates.
