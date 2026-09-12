"""Build an immutable operator-only legacy-record reconciliation zipapp."""
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    def git(*args):
        return subprocess.check_output(('git', *args), cwd=ROOT, text=True).strip()
    if git('status', '--porcelain', '--untracked-files=all'):
        raise ValueError('clean committed source required')
    revision = git('rev-parse', 'HEAD')
    output = ROOT / 'out' / ('Re-Gear-reset-record-' + revision[:12] + '.pyz')
    output.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(output, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
        for relative in git('ls-files', 'backend/regear').splitlines():
            path = ROOT / relative
            if path.suffix != '.py':
                continue
            if path.is_symlink() or not path.is_file():
                raise ValueError('source not regular')
            archive.writestr(path.relative_to(ROOT / 'backend').as_posix(), path.read_bytes())
        archive.writestr('__main__.py',
            'from regear.delivery.whole_dock_reset import main\nraise SystemExit(main())\n')
        archive.writestr('recovery-source.json', json.dumps({'revision': revision,
            'purpose': 'operator-attested physical reset reconciliation; no hardware writes'}))
    print(output)
    print(hashlib.sha256(output.read_bytes()).hexdigest())


if __name__ == '__main__':
    main()
