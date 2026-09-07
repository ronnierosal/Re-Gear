"""Exact live kernel symbol lookup for experimental AMD DMA-buf attribution.

Pointer values remain ephemeral inside privileged evaluation; never serialize
this result into diagnostic reports or durable launch policy. Symbol presence
alone does not verify a receive program or certify a device/exporter.
"""
from dataclasses import dataclass, field
from pathlib import Path
from io import BytesIO
import re

MAX_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True)
class ReceiveSymbols:
    dma_buf_fops: int = field(repr=False)
    amdgpu_dmabuf_ops: int = field(repr=False)


def parse_receive_symbols(raw):
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_BYTES:
        raise ValueError('symbol inventory unavailable or oversized')
    wanted = {'dma_buf_fops': '', 'amdgpu_dmabuf_ops': '[amdgpu]'}
    found = {}
    # Validate every row, including irrelevant rows after both target symbols.
    for index, row in enumerate(BytesIO(raw)):
        if index >= 1_000_000 or len(row) > 4096:
            raise ValueError('symbol inventory bounds exceeded')
    # Two forward-only C-level searches avoid splitting the complete inventory.
    # Each candidate row is parsed once, including repeated substrings in a row;
    # at most MAX_BYTES input and one million rows are traversed, without a set
    # of offsets or candidate list. Exact third-field checks remain unchanged.
    names=(b'dma_buf_fops',b'amdgpu_dmabuf_ops')
    positions=[raw.find(name) for name in names]
    while any(position>=0 for position in positions):
        position=min(position for position in positions if position>=0)
        start=raw.rfind(b'\n',0,position)+1
        end=raw.find(b'\n',position)
        end=len(raw) if end<0 else end+1
        row=raw[start:end]
        for index,name in enumerate(names):
            if 0<=positions[index]<end:
                positions[index]=raw.find(name,end)
        fields = row.split()
        if len(fields) < 3 or fields[2] not in (b'dma_buf_fops', b'amdgpu_dmabuf_ops'):
            continue
        try:
            values = [part.decode('ascii') for part in fields]
        except UnicodeDecodeError as exc:
            raise ValueError('symbol inventory malformed') from exc
        name = values[2]
        if (name in found or len(values) != (4 if wanted[name] else 3)
                or (values[3] if len(values)==4 else '') != wanted[name]
                or values[1] not in ('d','D','r','R')
                or re.fullmatch(r'[0-9a-fA-F]{16}', values[0]) is None):
            raise ValueError('symbol identity ambiguous or malformed')
        address = int(values[0],16)
        if address < 0xffff800000000000 or address % 8:
            raise ValueError('symbol address hidden or unsupported')
        found[name] = address
    if set(found) != set(wanted) or len(set(found.values())) != 2:
        raise ValueError('required symbol identity unavailable')
    return ReceiveSymbols(**found)


def read_receive_symbols():
    with Path('/proc/kallsyms').open('rb') as source:
        raw = source.read(MAX_BYTES+1)
    return parse_receive_symbols(raw)
