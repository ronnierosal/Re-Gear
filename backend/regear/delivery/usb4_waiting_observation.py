"""Volatile presentation-only USB4 notice projection, without authorization."""
import asyncio
import secrets
from ..adapters.steamos.usb4_attachment_observer import Usb4AttachmentObserver, Usb4AttachmentObservation

class Usb4WaitingObservation:
    def __init__(self, observer=None):
        self._observer = observer if observer is not None else Usb4AttachmentObserver()
        self._identity = None
        self._key = None
        self._lock = asyncio.Lock()

    def observe(self):
        try:
            result = self._observer.observe()
        except Exception:
            result = None
        state = result.state if type(result) is Usb4AttachmentObservation else 'unknown'
        if state not in ('none', 'unauthorized', 'authorized', 'unknown', 'ambiguous'):
            state = 'unknown'
        key = None
        if state in ('none', 'authorized'):
            self._identity = self._key = None
        elif state == 'unauthorized':
            if type(result.identity) is not tuple or not result.identity:
                state = 'unknown'
            else:
                if result.identity != self._identity:
                    try:
                        next_key = 'uw-' + secrets.token_hex(16)
                    except Exception:
                        return {'schema_version': 1, 'state': 'unknown', 'notice_key': None}
                    self._identity = result.identity
                    self._key = next_key
                key = self._key
        return {'schema_version': 1, 'state': state, 'notice_key': key}

    async def enrich_snapshot(self, snapshot):
        async with self._lock:
            worker = asyncio.create_task(asyncio.to_thread(self.observe))
            try:
                wire = await asyncio.shield(worker)
            except asyncio.CancelledError:
                # Finish the bounded passive read before releasing serialization.
                # Cancellation still propagates; its stale snapshot is never published.
                while not worker.done():
                    try:
                        await asyncio.shield(worker)
                    except asyncio.CancelledError:
                        continue
                raise
            return {**snapshot, 'usb4_waiting': wire}
