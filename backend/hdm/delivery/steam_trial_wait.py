"""Bounded observation window for a separate Steam launch claim, not success."""
from __future__ import annotations

import re
import time


def wait_for_steam_trial(store, operation_id, *, clock=time.monotonic,
                         wait=time.sleep):
    """Never create authority; caller must cancel in finally after this window.

    The Steam marker is shared with cancellation, so its presence proves only
    that the claim is closed. It does not prove launch, GPU selection or release.
    """
    record = store.read()
    if record is None or record['operation_id'] != operation_id:
        return
    try:
        consumed = store._read_small_file(store._consumed)
        receipt = store._read_small_file(store._receipt).split('\n')
    except FileNotFoundError:
        return
    if (consumed != operation_id or len(receipt) != 2
            or receipt[0] != operation_id
            or re.fullmatch(r'[0-9a-f]{32}', receipt[1]) is None):
        return
    # The durable expiry is in the same boot-bound monotonic clock domain
    # used when arming the trial, never calendar time.
    deadline = min(clock() + 10.0, record['expires_at'])
    for _ in range(100):
        remaining = deadline - clock()
        if remaining <= 0:
            return
        try:
            claimed = store._read_small_file(store._steam_consumed)
        except FileNotFoundError:
            claimed = None
        # Exclusive creation wins the claim before its bytes are written.
        # An empty regular marker can be that writer in progress; observe it
        # only within the same bounded window, never grant replacement authority.
        if claimed not in (None, ''):
            if claimed != operation_id:
                raise ValueError('Steam trial claim identity mismatch')
            return
        wait(min(0.1, remaining))
