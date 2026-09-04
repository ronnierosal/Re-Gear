"""Bounded operator-started shutdown observation; never requests poweroff."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import threading

if __package__:
    from . import capture_shutdown_evidence as evidence
else:
    import capture_shutdown_evidence as evidence


LIVE_BODY = r'''
def follow_shutdown():
    argv = tuple("--lines=0" if arg == "--lines=2000" else arg
                 for arg in journal_argv("current", "shutdown")) + ("--follow",)
    process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               shell=False, env={"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"})
    deadline = time.monotonic() + LIVE_SECONDS
    retained = bytearray()
    pending = bytearray()
    total_bytes = 0
    status = "observed"
    previous = None
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ, "stdout")
            selector.register(process.stderr, selectors.EVENT_READ, "stderr")
            initial = empty_report("observed")
            print(json.dumps(initial), flush=True)
            while selector.get_map() and time.monotonic() < deadline:
                for key, _ in selector.select(min(1, max(0, deadline-time.monotonic()))):
                    chunk = os.read(key.fileobj.fileno(), 65536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    total_bytes += len(chunk)
                    if total_bytes > MAX_BYTES:
                        status = "size_limit"
                        break
                    if key.data == "stderr":
                        status = "journal_unavailable"
                        break
                    pending.extend(chunk)
                    while b"\n" in pending:
                        line, _, remainder = pending.partition(b"\n")
                        pending = bytearray(remainder)
                        retained.extend(line + b"\n")
                        report = classify_journal(bytes(retained))
                        if report["status"] == "size_limit":
                            status = "size_limit"
                            break
                        signature = (report["symptoms"], report["checkpoints"], report["shutdown_phases"])
                        if signature != previous:
                            print(json.dumps(report), flush=True)
                            previous = signature
                    if status != "observed":
                        break
                if status != "observed":
                    break
            final = classify_journal(bytes(retained)) if retained else empty_report("observed")
            if status != "observed":
                final["status"] = status
            if pending:
                final["status"] = "malformed_journal"
            if process.poll() not in (None, 0):
                final["status"] = "journal_unavailable"
            print(json.dumps(final), flush=True)
    finally:
        # This is only our journalctl child, never a session or driver client.
        if process.poll() is None:
            process.kill()
        process.wait(timeout=1)
        process.stdout.close()
        process.stderr.close()

follow_shutdown()
'''


def live_payload(seconds: int) -> str:
    if type(seconds) is not int or not 30 <= seconds <= 300:
        raise ValueError("live capture duration must be 30-300 seconds")
    source = evidence.remote_payload("current", "shutdown").rsplit("\nprint(", 1)[0]
    return source + f"\nLIVE_SECONDS = {seconds}\n" + LIVE_BODY


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True)
    parser.add_argument("--identity-file", type=Path, required=True)
    parser.add_argument("--seconds", type=int, default=180)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = live_payload(args.seconds)
    argv = evidence.build_ssh_argv(host=args.host, user="deck", port=22,
                                  timeout_seconds=10, identity_file=args.identity_file)
    count = 0
    with args.output.open("x", encoding="utf-8") as output:
        with subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL) as process:
            timer = threading.Timer(args.seconds + 25, process.kill)
            timer.start()
            try:
                process.stdin.write(payload.encode("utf-8"))
                process.stdin.close()
                while True:
                    line = process.stdout.readline(evidence.MAX_REPORT_BYTES + 1)
                    if not line:
                        break
                    if len(line) > evidence.MAX_REPORT_BYTES or count >= evidence.MAX_ROWS + 2:
                        raise ValueError("live report bound exceeded")
                    report = evidence.validate_report(line.decode("utf-8"), "current", "shutdown")
                    report["collector"]["selection"] = "bounded_follow"
                    output.write(json.dumps(report, sort_keys=True) + "\n")
                    output.flush()
                    count += 1
                    if count == 1:
                        print(f"Live shutdown capture ready for {args.seconds} seconds.", flush=True)
                process.wait(timeout=2)
            finally:
                timer.cancel()
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=2)
    print(f"Saved {count} redacted reports; SSH exit={process.returncode}. Physical poweroff remains unverified.")
    return 0 if count else 1


if __name__ == "__main__":
    raise SystemExit(main())
