"""Read-only DMA layout/symbol and full audio-context prerequisites."""
import hashlib
import json
from pathlib import Path
import platform
import sys

if Path(__file__).name != '__main__.py':
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))

from hdm.delivery.device_filter_btf import parse_dma_buf_receive_btf
from hdm.adapters.steamos.device_receive_symbols import ReceiveSymbols, read_receive_symbols
from scripts.probe_audio_trial_context import capture as capture_audio


def _btf():
    with open('/sys/kernel/btf/vmlinux','rb') as source:
        return source.read(64*1024*1024+1)


def capture(*, read_btf=_btf, read_symbols=read_receive_symbols, audio=capture_audio):
    report=dict(schema_version=1,dma_layout_ready=False,dma_symbols_ready=False,
                dma_filter_verified=False,disconnect_clearance=False)
    if platform.system()!='Linux' or platform.machine()!='x86_64':
        report['code']='unsupported_platform'
        return report
    try:
        raw=read_btf()
        parse_dma_buf_receive_btf(raw,pointer_size=8)
        report['dma_layout_ready']=True
        report['btf_sha256']=hashlib.sha256(raw).hexdigest()
    except (OSError,ValueError):
        report['dma_layout_code']='layout_unavailable'
    try:
        # Intentionally discard ephemeral pointer values; no address in output.
        if type(read_symbols()) is not ReceiveSymbols:
            raise ValueError("symbol observation unavailable")
        report['dma_symbols_ready']=True
    except (OSError,ValueError) as error:
        report['dma_symbols_code']=('symbols_hidden_or_unsupported'
            if type(error) is ValueError and str(error)=='symbol address hidden or unsupported'
            else 'symbols_unavailable')
    report['audio']=audio()
    report['code']='prerequisites_observed' if (report['dma_layout_ready']
        and report['dma_symbols_ready'] and report['audio'].get('ready') is True) else 'prerequisites_incomplete'
    return report


def main():
    if sys.argv[1:]:raise SystemExit('No arguments accepted')
    report=capture()
    print(json.dumps(report,sort_keys=True))
    return 0 if report['code']=='prerequisites_observed' else 1


if __name__=='__main__':raise SystemExit(main())
