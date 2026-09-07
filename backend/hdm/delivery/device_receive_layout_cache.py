"""Instance-local single-entry DMA BTF parse cache, without observation authority.

Each call requires freshly collected bytes; the caller owns collection and
freshness checks. Only their SHA256, explicit ABI, and frozen parsed layout are
retained. No BTF bytes, kernel addresses, symbol evidence or timestamps persist.
"""
from dataclasses import dataclass
import hashlib

from .device_filter_btf import DmaBufReceiveLayout, parse_dma_buf_receive_btf

MAX_BTF_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True)
class CachedDmaLayout:
    btf_sha256: str
    pointer_size: int
    layout: DmaBufReceiveLayout


class DmaReceiveLayoutCache:
    """One caller-owned cache; no globals, I/O, or thread-sharing guarantee."""
    def __init__(self):
        self._entry = None

    def parse(self, raw, *, pointer_size):
        if type(raw) is not bytes or not 0 < len(raw) <= MAX_BTF_BYTES:
            raise ValueError('bounded fresh BTF bytes required')
        if type(pointer_size) is not int or pointer_size != 8:
            raise ValueError('supported explicit DMA pointer ABI required')
        digest = hashlib.sha256(raw).hexdigest()
        current = self._entry
        if current is not None and (current.btf_sha256,current.pointer_size)==(digest,pointer_size):
            return current
        layout = parse_dma_buf_receive_btf(raw,pointer_size=pointer_size)
        if type(layout) is not DmaBufReceiveLayout:
            raise ValueError('validated frozen DMA layout required')
        entry = CachedDmaLayout(digest,pointer_size,layout)
        self._entry = entry
        return entry
