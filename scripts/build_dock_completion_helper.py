"""Build an immutable, exact-attachment operator recovery zipapp from clean Git."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import zipfile

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binding',required=True)
    parser.add_argument('--generation',required=True)
    args=parser.parse_args()
    if any(not re.fullmatch('[0-9a-f]{64}',v) for v in (args.binding,args.generation)):
        raise ValueError('exact attachment fingerprints required')
    def git(*args):
        return subprocess.check_output(('git',*args),cwd=ROOT,text=True).strip()
    if git('status','--porcelain','--untracked-files=all'):
        raise ValueError('clean source required')
    revision=git('rev-parse','HEAD')
    output=ROOT/'out'/('Re-Gear-complete-trial-'+revision[:12]+'.pyz')
    entry=('from regear.delivery.whole_dock_completion import main\n'
           'raise SystemExit(main(expected_binding='+repr(args.binding)+
           ',expected_generation='+repr(args.generation)+'))\n')
    with zipfile.ZipFile(output,'x',compression=zipfile.ZIP_DEFLATED) as archive:
        for relative in git('ls-files','backend/regear').splitlines():
            path=ROOT/relative
            if path.suffix!='.py':continue
            if path.is_symlink() or not path.is_file():raise ValueError('source not regular')
            archive.writestr(path.relative_to(ROOT/'backend').as_posix(),path.read_bytes())
        archive.writestr('__main__.py',entry)
        archive.writestr('recovery-source.json',json.dumps({'revision':revision,
            'purpose':'complete verified-down record only; no hardware writes'}))
    print(output)
    print(hashlib.sha256(output.read_bytes()).hexdigest())


if __name__=='__main__':main()
