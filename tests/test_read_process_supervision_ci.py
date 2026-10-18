"""Run the reviewed generic Linux fixtures outside shared test discovery."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import selectors
import signal
import subprocess
import sys
import time
import unittest


ROOT = Path(__file__).resolve().parent / 'fixtures' / 'read_process_supervision'
HASHES = {
    'read_process_supervision.py': '7ae2ef035df71daaf3e710da868ddc0d2e15dc00a9d8458b006e6801bb8449a9',
    'test_read_process_supervision.py': '07d2af6df398c4b30ee7965269acce4fe030ccbf98e52b2e4cd7e09195e3bfcb',
    'README.md': '175067e8cc19e3916054c518340ea6514792726340a02400811ce5d49183d55e',
}


def capture_worker(command, directory, seconds):
    """Bound one fixed child; its enclosing supervisor owns escaped children."""
    output = bytearray()
    deadline = time.monotonic() + seconds
    process = subprocess.Popen(command, cwd=directory, stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               start_new_session=True, shell=False,
                               env={'PATH': '/usr/bin:/bin', 'LANG': 'C', 'LC_ALL': 'C'})
    try:
        os.set_blocking(process.stdout.fileno(), False)
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while selector.get_map():
                if time.monotonic() >= deadline:
                    raise TimeoutError('fixture worker timed out')
                for key, _ in selector.select(.05):
                    chunk = os.read(key.fileobj.fileno(), 1024)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    output.extend(chunk)
                    if len(output) > 16384:
                        raise ValueError('fixture output exceeded bound')
        while os.waitid(os.P_PID, process.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT) is None:
            if time.monotonic() >= deadline:
                raise TimeoutError('fixture worker did not exit')
            time.sleep(.01)
    finally:
        # Signal before reaping to keep process-group identity pinned.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=1)
        process.stdout.close()
    return {'returncode': process.returncode, 'output': output.decode('utf-8', errors='strict')}


def supervise_fixtures():
    # This dedicated interpreter, never shared discovery, adopts escaped children.
    spec = importlib.util.spec_from_file_location('generic_supervision', ROOT / 'read_process_supervision.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # Real failure cases qualify the enclosing boundary, separately from 21 fixtures.
    escaped = ('import os,time; r,w=os.pipe(); pid=os.fork(); '
               '\nif pid==0:\n os.close(r); os.setsid(); os.write(w,b"1"); '
               'os.close(w); time.sleep(10); os._exit(0)'
               '\nos.close(w); assert os.read(r,1)==b"1"; os.close(r); time.sleep(10)')
    cases = [(escaped, .4), ('print("x"*32768)', 2)]
    for source, seconds in cases:
        try:
            module.guard_call(lambda: capture_worker(
                [sys.executable, '-I', '-S', '-B', '-c', source], ROOT, seconds),
                total_seconds=3, cleanup_seconds=1)
        except module.GuardFailure:
            pass
        else:
            raise AssertionError('containment fault was not refused')
        if module.children():
            raise AssertionError('containment left adopted children')
    command = [sys.executable, '-I', '-S', '-B', '-m', 'unittest',
               'discover', '-s', '.', '-p', 'test_read_process_supervision.py', '-v']
    result = module.guard_call(lambda: capture_worker(command, ROOT, 10),
                               total_seconds=12, cleanup_seconds=1, cap=32768)
    result['containment_faults'] = 'timeout-escaped-descendant/output-overflow:clean'
    print(json.dumps(result))


@unittest.skipUnless(sys.platform == 'linux', 'dedicated nonroot Linux fixture gate')
class ReadProcessSupervisionCITests(unittest.TestCase):
    def test_exact_generic_packet_in_dedicated_interpreter(self):
        self.assertNotEqual(os.geteuid(), 0, 'fixture gate requires nonroot Linux')
        for name, digest in HASHES.items():
            self.assertEqual(hashlib.sha256((ROOT / name).read_bytes()).hexdigest(), digest)
        command = [sys.executable, '-I', '-S', '-B', str(Path(__file__).resolve()), '--fixture-supervisor']
        outer = capture_worker(command, ROOT, 20)
        self.assertEqual(outer['returncode'], 0, outer['output'])
        result = json.loads(outer['output'])
        self.assertEqual(result['containment_faults'], 'timeout-escaped-descendant/output-overflow:clean')
        text = result['output']
        print('Generic supervision: Python', platform.python_version(), 'kernel', platform.release())
        for name, digest in HASHES.items():
            print(name, digest)
        print(text, end='')
        self.assertEqual(result['returncode'], 0, text)
        self.assertRegex(text, r'Ran 21 tests in [0-9.]+s\s+OK\s*\Z')
        self.assertEqual(text.count(' ... ok\n'), 21, 'all 21 fixtures must pass without skips')


if __name__ == '__main__':
    if sys.argv[1:] == ['--fixture-supervisor']:
        supervise_fixtures()
    else:
        unittest.main()
