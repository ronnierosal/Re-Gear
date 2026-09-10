"""Internal parent-death guard for the exact systemd sleep inhibitor."""

from __future__ import annotations

import ctypes
import os
import signal
import sys
from pathlib import Path


PR_SET_PDEATHSIG = 1
SYSTEMD_INHIBIT = "/usr/bin/systemd-inhibit"
PYTHON = "/usr/bin/python"
INHIBITOR_WHO = "Handheld Dock Mode"
INHIBITOR_WHY = "The attached eGPU is known to wake this handheld immediately from sleep"


def _arm_parent_death_signal(expected_parent: int) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(PR_SET_PDEATHSIG, signal.SIGTERM) != 0:
        raise OSError(ctypes.get_errno(), "Could not arm parent-death signal")
    if os.getppid() != expected_parent:
        raise RuntimeError("Parent exited before the guard was armed")


def _guard(expected_parent: int) -> None:
    _arm_parent_death_signal(expected_parent)
    helper = str(Path(__file__).resolve())
    current_pid = os.getpid()
    argv = (
        SYSTEMD_INHIBIT,
        "--what=sleep",
        f"--who={INHIBITOR_WHO}",
        f"--why={INHIBITOR_WHY}",
        "--mode=block",
        PYTHON,
        helper,
        "--hold",
        str(current_pid),
    )
    os.execv(SYSTEMD_INHIBIT, argv)


def _hold(expected_parent: int) -> None:
    _arm_parent_death_signal(expected_parent)
    while True:
        signal.pause()


def main() -> int:
    if len(sys.argv) != 3 or sys.argv[1] not in ("--guard", "--hold"):
        return 2
    try:
        expected_parent = int(sys.argv[2])
        if expected_parent <= 1:
            return 2
        if sys.argv[1] == "--guard":
            _guard(expected_parent)
        else:
            _hold(expected_parent)
    except (OSError, RuntimeError, ValueError) as error:
        print(f"Re-Gear inhibitor guard failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
