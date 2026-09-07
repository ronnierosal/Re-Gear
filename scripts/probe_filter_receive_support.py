"""Fixed read-only BPF-LSM receive-filter prerequisites, never hook validation.

No subprocess, BPF load, privileged escalation, or filesystem mutation.
References: https://docs.kernel.org/bpf/prog_lsm.html and Linux UAPI btf.h.
Even available prerequisites cannot establish external DMA-buf attribution.
"""
import gzip
import io
import json
import os
import re
import struct
import sys
import zlib

CONFIG_LIMIT = 2 * 1024 * 1024
COMPRESSED_LIMIT = 512 * 1024
OPTIONS = ("CONFIG_BPF_LSM", "CONFIG_DEBUG_INFO_BTF", "CONFIG_BPF_SYSCALL")


def read_bounded(path, limit):
    with open(path, "rb") as source:
        raw = source.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("read exceeds bound")
    return raw


def parse_config(raw, *, compressed=False):
    if type(raw) is not bytes or len(raw) > (COMPRESSED_LIMIT if compressed else CONFIG_LIMIT):
        raise ValueError("invalid config size")
    if compressed:
        with gzip.GzipFile(fileobj=io.BytesIO(raw)) as source:
            raw = source.read(CONFIG_LIMIT + 1)
        if len(raw) > CONFIG_LIMIT:
            raise ValueError("expanded config exceeds bound")
    text = raw.decode("ascii")
    result = dict.fromkeys(OPTIONS, "unknown")
    seen = set()
    for line in text.splitlines():
        for option in OPTIONS:
            if line.startswith(option + "=") or line == "# " + option + " is not set":
                if option in seen:
                    raise ValueError("duplicate config option")
                seen.add(option)
                value = line.partition("=")[2] if "=" in line else "n"
                result[option] = {"y": "enabled", "n": "disabled", "m": "module"}.get(value, "unknown")
    return result


def parse_lsm(raw):
    if type(raw) is not bytes or not raw or len(raw) > 4096:
        raise ValueError("invalid LSM list")
    names = raw.decode("ascii").strip().split(",")
    if (any(re.fullmatch(r"[A-Za-z0-9_-]{1,64}", name) is None for name in names)
            or len(names) != len(set(names))):
        raise ValueError("malformed LSM list")
    return "active" if "bpf" in names else "inactive"


def parse_btf_header(raw):
    # struct btf_header: magic/version/flags/hdr_len/type_off/type_len/str_off/str_len.
    # Read only the header: existence is not proof the kernel can load our hook.
    if type(raw) is not bytes or len(raw) != 24:
        raise ValueError("BTF header unavailable")
    order = "<" if raw[:2] == b"\x9f\xeb" else ">" if raw[:2] == b"\xeb\x9f" else None
    if order is None:
        raise ValueError("invalid BTF magic")
    magic, version, flags, header, types, type_size, strings, string_size = struct.unpack(order + "HBBIIIII", raw)
    if version != 1 or flags != 0 or header < 24 or header > 4096 or not type_size or not string_size:
        raise ValueError("invalid BTF header")
    if types + type_size > 2**32 - 1 or strings + string_size > 2**32 - 1:
        raise ValueError("invalid BTF section bounds")
    return "header_present"


def read_btf_header(path):
    with open(path, "rb") as source:
        return source.read(24)


def run_probe(*, reader=read_bounded, btf_reader=read_btf_header, release=None):
    report = dict(preflight="unknown", kernel_hook_fixture_verified=False,
                  dma_buf_attribution="unresolved", disconnect_clearance=False,
                  config=dict.fromkeys(OPTIONS, "unknown"), config_source="unavailable",
                  active_bpf_lsm="unknown", btf="unknown")
    if sys.platform != "linux":
        report["reason"] = "linux_required"
        return report
    if release is None:
        release = os.uname().release
    paths = [("/proc/config.gz", True, "proc")]
    if type(release) is str and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,127}", release):
        paths.append(("/boot/config-" + release, False, "boot"))
    for path, compressed, label in paths:
        try:
            raw = reader(path, COMPRESSED_LIMIT if compressed else CONFIG_LIMIT)
            report["config"] = parse_config(raw, compressed=compressed)
            report["config_source"] = label
            break
        except (OSError, ValueError, EOFError, zlib.error):
            pass
    try:
        report["active_bpf_lsm"] = parse_lsm(reader("/sys/kernel/security/lsm", 4096))
    except (OSError, ValueError):
        pass
    try:
        report["btf"] = parse_btf_header(btf_reader("/sys/kernel/btf/vmlinux"))
    except (OSError, ValueError):
        pass
    checks = tuple(report["config"].values())
    if (all(value == "enabled" for value in checks)
            and report["active_bpf_lsm"] == "active" and report["btf"] == "header_present"):
        report["preflight"] = "prerequisites_observed"
    elif "disabled" in checks or "module" in checks or report["active_bpf_lsm"] == "inactive":
        report["preflight"] = "prerequisite_unavailable"
    return report


if __name__ == "__main__":
    if sys.argv[1:]:
        raise SystemExit("No arguments accepted")
    print(json.dumps(run_probe(), sort_keys=True))
