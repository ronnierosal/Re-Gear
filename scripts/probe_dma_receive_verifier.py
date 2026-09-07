"""Root-only load-verifier probe. No attachment or real-device isolation test.

Compiler targeting inputs are synthetic; only live BTF and symbol prerequisites
are inspected. Bytecode and verifier logs contain privileged pointers and must
never appear in reports. Program descriptors are closed before returning.
"""
import os
from pathlib import Path
import platform
import sys

if Path(__file__).name != "__main__.py":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from hdm.delivery.device_filter_btf import parse_dma_buf_receive_btf
from hdm.adapters.steamos.device_receive_symbols import ReceiveSymbols, read_receive_symbols
from hdm.delivery.dma_receive_program import compile_dma_receive
from hdm.delivery.device_receive_kernel import FileReceiveLink


def _read_btf():
    with open("/sys/kernel/btf/vmlinux", "rb") as source:
        return source.read(64 * 1024 * 1024 + 1)


def capture(*, read_btf=_read_btf, read_symbols=read_receive_symbols,
            parse_layout=parse_dma_buf_receive_btf, compile_program=compile_dma_receive,
            owner_factory=FileReceiveLink, effective_uid=None):
    report = dict(schema_version=1, verifier_accepted=False, enforcement_verified=False,
                  disconnect_clearance=False, synthetic_target_inputs=True)
    if platform.system() != "Linux" or platform.machine() != "x86_64":
        return dict(report, code="unsupported_platform")
    uid = os.geteuid() if effective_uid is None else effective_uid()
    if type(uid) is not int or uid != 0:
        return dict(report, code="root_required")
    phase = "layout"
    owner = None
    try:
        layout = parse_layout(read_btf(), pointer_size=8)
        phase = "symbols"
        symbols = read_symbols()
        if type(symbols) is not ReceiveSymbols:
            raise ValueError("typed symbols required")
        phase = "compile"
        # These values are deliberately not discovered device/cgroup targets.
        # The resulting program is never attached, so they affect no process.
        program = compile_program((1,), ((1, 3),), layout=layout,
            dma_buf_fops=symbols.dma_buf_fops, amdgpu_dmabuf_ops=symbols.amdgpu_dmabuf_ops,
            allowed_internal_primary_minor=0)
        phase = "verifier"
        owner = owner_factory()
        owner.verify_load(program, hook_btf_id=layout.receive.hook_btf_id)
        report.update(verifier_accepted=True, code="verifier_accepted")
    except Exception:
        # Never serialize exception text, bytecode, addresses, or verifier log.
        report["code"] = phase + "_unavailable"
    finally:
        if owner is not None:
            try:
                owner.close()
            except Exception:
                report.update(verifier_accepted=False, code="cleanup_unconfirmed")
    return report


def main():
    import json
    if sys.argv[1:]:
        raise SystemExit("No arguments accepted")
    result = capture()
    print(json.dumps(result, sort_keys=True))
    return 0 if result["verifier_accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
