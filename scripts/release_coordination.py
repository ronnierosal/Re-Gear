"""Shared local Git refs coordinate ready changes and immutable release versions."""
import argparse
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ZERO = "0" * 40

def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()

def required():
    return git("for-each-ref", "--format=%(objectname) %(refname)", "refs/regear/ready/").splitlines()

def check():
    for line in required():
        commit, ref = line.split()
        if subprocess.run(["git", "merge-base", "--is-ancestor", commit, "HEAD"], cwd=ROOT).returncode:
            raise SystemExit(f"Missing completed work: {ref} ({commit}). Integrate and test before building.")

def reserve(version):
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
        raise SystemExit("Player releases require a plain X.Y.Z version; no chat suffixes.")
    check()
    head = git("rev-parse", "HEAD")
    ref = "refs/regear/versions/" + version
    # Creation is atomic across every worktree; a used version is never recycled.
    result = subprocess.run(["git", "update-ref", ref, head, ZERO], cwd=ROOT, capture_output=True)
    if result.returncode:
        raise SystemExit(f"Version {version} is already reserved. Choose the next unused version.")

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["status", "ready", "check"])
    parser.add_argument("name", nargs="?")
    args = parser.parse_args()
    if args.action == "ready":
        if not args.name or not re.fullmatch(r"[a-z0-9-]+", args.name):
            parser.error("ready requires a lowercase workstream name")
        if git("status", "--porcelain"):
            raise SystemExit("Commit and verify work before registering it as ready.")
        ref = "refs/regear/ready/" + args.name
        old = subprocess.run(["git", "rev-parse", "--verify", ref], cwd=ROOT, capture_output=True, text=True)
        previous = old.stdout.strip() if old.returncode == 0 else ZERO
        if previous != ZERO:
            subprocess.run(["git", "merge-base", "--is-ancestor", previous, "HEAD"], cwd=ROOT, check=True)
        subprocess.run(["git", "update-ref", ref, git("rev-parse", "HEAD"), previous], cwd=ROOT, check=True)
    elif args.action == "check":
        check()
    else:
        print(git("for-each-ref", "--format=%(refname) %(objectname)", "refs/regear/"))

if __name__ == "__main__":
    main()
