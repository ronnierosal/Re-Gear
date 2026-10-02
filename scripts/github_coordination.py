"""Cooperative GitHub task records; never hardware proof or an agent identity authority.

Only the serialized, default-branch agent-coordination workflow writes records.
All subprocess inputs are argument arrays or JSON stdin; issue text is never code.
"""
import argparse
import json
import os
import re
import subprocess
import urllib.parse
import sys
from pathlib import Path

BLOCK = re.compile(r"^```regear-task[ \t]*\r?\n(.*?)^```[ \t]*$", re.M | re.S)
SHA = re.compile(r"[0-9a-f]{40}")
ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}")
ACTIVE = {"claimed", "in-progress", "blocked", "pr-open", "software-validated",
          "review-requested", "changes-requested",
          "hardware-required", "hardware-validated", "ready-to-merge"}
# Record fields an exact-candidate result is bound to, and the evidence fields
# that must not survive a change of any of them.
CANDIDATE_BINDING = ("class", "hardware", "branch", "scope", "agent", "behavior", "procedure_approval",
                     "validation", "bug", "regression")
# Absent and the default are the same acceptance contract.
BINDING_DEFAULTS = {"bug": False}
EVIDENCE = ("software", "review", "review_request", "hardware_evidence")
# States that bind software evidence to one exact candidate head/base.
CANDIDATE = {"software-validated", "review-requested", "changes-requested",
             "hardware-required", "hardware-validated", "ready-to-merge"}
TERMINAL = {"merged", "closed", "cancelled"}
LABELS = (["agent-task"] + [f"task:{state}" for state in sorted(ACTIVE | TERMINAL | {"backlog"})]
          + [f"agent:{agent}" for agent in ("codex-cloud", "claude", "codex-local")]
          + [f"risk:{risk}" for risk in "ABCD"]
          + ["hardware:required", "hardware:not-required"])
FIELDS = {"schema", "owner", "agent", "branch", "status", "class", "hardware",
          "validation", "scope", "revision", "bug", "regression", "behavior",
          "software", "review", "hardware_evidence", "procedure_approval", "transfer",
          "review_request", "auto_merge", "integration"}
OPTIONAL = {"bug", "regression", "behavior", "software", "review", "hardware_evidence",
            "procedure_approval", "transfer", "review_request", "auto_merge", "integration"}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def load_record(text):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, f"duplicate JSON field: {key}")
            result[key] = value
        return result
    return json.loads(text, object_pairs_hook=unique)


def validate(record):
    require(isinstance(record, dict), "record must be an object")
    require(not set(record) - FIELDS, "unknown record fields")
    require(FIELDS - OPTIONAL <= set(record), "missing required fields")
    require(type(record["schema"]) is int and record["schema"] == 1, "schema must be 1")
    require(type(record["revision"]) is int and record["revision"] > 0, "invalid revision")
    require(record["agent"] in {"codex-cloud", "claude", "codex-local"}, "invalid agent")
    require(record["status"] in ACTIVE | {"backlog"} | TERMINAL, "invalid status")
    require(record["class"] in {"A", "B", "C", "D"}, "invalid class")
    require(record["hardware"] in {"required", "not-required"}, "invalid hardware requirement")
    require(nonempty(record["validation"]), "validation is required")
    owner = record["owner"]
    require(owner is None or (isinstance(owner, str) and ID.fullmatch(owner)), "invalid owner")
    require(owner is not None or record["status"] == "backlog", "claimed owner required")
    branch = record["branch"]
    require(isinstance(branch, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,199}", branch)
            and not any(x in branch for x in ("..", "//", "@{"))
            and not branch.endswith(("/", ".", ".lock")), "invalid branch")
    scope = record["scope"]
    require(isinstance(scope, list) and bool(scope), "scope must be nonempty")
    for path in scope:
        require(isinstance(path, str) and re.fullmatch(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*", path)
                and not any(part in {".", ".."} for part in path.split("/")), "invalid scope path")
    require(len({p.lower() for p in scope}) == len(scope), "duplicate scope")
    require(type(record.get("bug", False)) is bool, "bug must be boolean")
    if record.get("bug"):
        require(nonempty(record.get("regression")), "bug requires regression statement")
    if record["class"] in {"C", "D"}:
        require(record["hardware"] == "required", "C/D require hardware")
    require(type(record.get("auto_merge", True)) is bool, "auto_merge must be boolean")
    for name in ("review_request", "integration"):
        item = record.get(name, {})
        require(isinstance(item, dict), f"{name} must be an object")
        for key in ("head", "base", "sha"):
            require(key not in item or (isinstance(item[key], str) and SHA.fullmatch(item[key])),
                    f"invalid {name} {key}")
    if record["status"] in CANDIDATE:
        item = record.get("software", {})
        require(isinstance(item, dict) and isinstance(item.get("head"), str)
                and SHA.fullmatch(item["head"]) and isinstance(item.get("base"), str)
                and SHA.fullmatch(item["base"]), "software revisions required")
        evidence(record, "software", item["head"], item["base"])
        if record["status"] == "hardware-required":
            require(record["hardware"] == "required", "hardware queue requires hardware task")
        if record["status"] == "hardware-validated":
            hardware(record, item["head"], item["base"])
    return record


def parse(body):
    matches = list(BLOCK.finditer(body or ""))
    require(len(matches) == 1 and (body or "").count("```regear-task") == 1,
            "exactly one regear-task block required")
    return validate(load_record(matches[0].group(1)))


def replace(body, record):
    parse(body)
    return BLOCK.sub(lambda _: "```regear-task\n" + json.dumps(record, indent=2) + "\n```", body)


def overlap(left, right):
    return any(a.lower() == b.lower() or a.lower().startswith(b.lower() + "/")
               or b.lower().startswith(a.lower() + "/") for a in left for b in right)


def collision(record, others):
    if record["status"] not in ACTIVE:
        return
    for number, other in others:
        if other["status"] in ACTIVE:
            require(record["branch"] != other["branch"], f"branch already claimed by #{number}")
            require(not overlap(record["scope"], other["scope"]), f"scope overlaps #{number}")


def update(old, new, expected_revision, others):
    validate(old)
    validate(new)
    require(old["revision"] == expected_revision, "stale revision; reread task")
    require(new["revision"] == expected_revision + 1, "new revision must increment once")
    require(old["status"] not in TERMINAL, "terminal task cannot be reclaimed")
    if old["owner"] is None:
        require(new["owner"] is not None and new["status"] == "claimed", "initial claim must start work")
    elif old["owner"] != new["owner"]:
        offer = old.get("transfer", {})
        require(offer == {"from": old["owner"], "to": new["owner"], "accepted": False},
                "ownership change requires prior transfer offer")
        require(new.get("transfer") == dict(offer, accepted=True), "transfer acceptance required")
    elif old["agent"] != new["agent"]:
        raise ValueError("agent change requires ownership transfer")
    if old["owner"] is not None:
        # Evidence is bound to the classification, scope, branch and acceptance
        # contract (validation, bug/regression) it was gathered under. Changing
        # any of them must not carry that evidence into a weaker gate (e.g. a
        # class D candidate rewritten as class A).
        changed = [key for key in CANDIDATE_BINDING
                   if old.get(key, BINDING_DEFAULTS.get(key)) != new.get(key, BINDING_DEFAULTS.get(key))]
        if changed:
            require(new["status"] not in CANDIDATE and not any(name in new for name in EVIDENCE),
                    f"changing {', '.join(changed)} must drop candidate evidence and leave candidate states")
    collision(new, others)
    return new


def evidence(record, name, head, base):
    item = record.get(name, {})
    require(isinstance(item, dict) and item.get("result") == "PASS", f"{name} PASS required")
    require(item.get("head") == head and item.get("base") == base, f"stale {name} head/base")
    require(isinstance(item.get("url"), str) and item["url"].startswith("https://"), f"{name} evidence URL required")
    return item


def check(record, pr, others=()):
    validate(record)
    require(pr["head"]["repo"] is not None and pr["head"]["repo"]["full_name"] == pr["base"]["repo"]["full_name"],
            "task branch must be in this repository")
    require(record["branch"] == pr["head"]["ref"], "task/PR branch mismatch")
    require(record["owner"] and record["status"] == "ready-to-merge", "task must have owner and ready-to-merge status")
    require(not pr.get("draft"), "draft PR is not ready")
    collision(record, others)
    head, base = pr["head"]["sha"], pr["base"]["sha"]
    require(SHA.fullmatch(head) and SHA.fullmatch(base), "invalid PR revisions")
    evidence(record, "software", head, base)
    review = evidence(record, "review", head, base)
    require(nonempty(review.get("reviewer")) and review["reviewer"] != record["owner"], "independent reviewer required")
    if record["class"] == "B":
        require(nonempty(record.get("behavior")), "class B requires established behavior citation")
    if record["hardware"] == "required":
        hardware(record, head, base)
    if record["class"] == "D":
        require(isinstance(record.get("procedure_approval"), str) and record["procedure_approval"].startswith("https://"),
                "class D procedure approval link required")


def hardware(record, head, base):
    hw = evidence(record, "hardware_evidence", head, base)
    require(hw.get("agent") == "codex-local" and nonempty(hw.get("tester")), "local Codex hardware evidence required")
    require(hw.get("tested_commit") == head, "hardware tested commit differs")
    require(isinstance(hw.get("artifact"), str) and re.fullmatch(r"sha256:[0-9a-f]{64}", hw["artifact"]), "immutable hardware artifact required")


class GitHub:
    def __init__(self, repo):
        require(re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo), "invalid repository")
        self.repo = repo

    def api(self, path, method="GET", payload=None):
        args = ["gh", "api", f"repos/{self.repo}" + (f"/{path}" if path else ""), "--method", method]
        if payload is not None:
            args += ["--input", "-"]
        result = subprocess.run(args, input=json.dumps(payload) if payload is not None else None,
                                capture_output=True, text=True, encoding="utf-8", check=True)
        return json.loads(result.stdout) if result.stdout.strip() else None

    def pages(self, path):
        result = []
        for page in range(1, 1001):
            separator = "&" if "?" in path else "?"
            batch = self.api(f"{path}{separator}per_page=100&page={page}")
            result.extend(batch)
            if len(batch) < 100:
                return result
        raise ValueError("pagination limit exceeded")

    def tasks(self):
        result = []
        for issue in self.pages("issues?state=open"):
            if "pull_request" not in issue and any(label["name"] == "agent-task" for label in issue["labels"]):
                result.append((issue["number"], parse(issue["body"])))
        return result


def task_number(body):
    numbers = re.findall(r"^Task: #([1-9][0-9]*)[ \t]*$", body or "", re.M)
    require(len(numbers) == 1, "PR requires exactly one Task: #N line")
    return int(numbers[0])


def queue(github):
    tasks = github.tasks()  # Invalid managed records fail closed, never silently disappear.
    prs = github.pages("pulls?state=open")
    rows = []
    for number, record in tasks:
        row = {"issue": number, "record": record, "hardware_queue_ready": False}
        if record["status"] == "hardware-required":
            matches = []
            for pr in prs:
                try:
                    if task_number(pr.get("body")) == number:
                        matches.append(pr)
                except ValueError:
                    continue
            try:
                require(len(matches) == 1, "hardware queue requires exactly one open task PR")
                pr = matches[0]
                require(sum(p["head"]["sha"] == pr["head"]["sha"] for p in prs) == 1,
                        "multiple open PRs share this head; status context is ambiguous")
                require(pr["head"]["repo"] is not None and pr["head"]["repo"]["full_name"] == pr["base"]["repo"]["full_name"],
                        "task branch must be in this repository")
                require(not pr.get("draft"), "draft PR is not ready")
                require(pr["head"]["ref"] == record["branch"], "task/PR branch mismatch")
                collision(record, [(n, r) for n, r in tasks if n != number])
                evidence(record, "software", pr["head"]["sha"], pr["base"]["sha"])
                review = evidence(record, "review", pr["head"]["sha"], pr["base"]["sha"])
                require(nonempty(review.get("reviewer")) and review["reviewer"] != record["owner"], "independent reviewer required")
                if record["class"] == "D":
                    require(isinstance(record.get("procedure_approval"), str) and record["procedure_approval"].startswith("https://"),
                            "class D procedure approval link required before hardware")
                row["hardware_queue_ready"] = True
            except ValueError as exc:
                row["queue_blocker"] = str(exc)
        rows.append(row)
    return rows


def check_pr(github, pr, tasks, open_prs=None):
    number = task_number(pr.get("body"))
    open_prs = open_prs if open_prs is not None else github.pages("pulls?state=open")
    require(sum(p["head"]["sha"] == pr["head"]["sha"] for p in open_prs) == 1,
            "multiple open PRs share this head; status context is ambiguous")
    siblings = []
    for other in open_prs:
        try:
            if task_number(other.get("body")) == number:
                siblings.append(other["number"])
        except ValueError:
            continue
    require(siblings == [pr["number"]], "task requires exactly one open PR")
    issue = github.api(f"issues/{number}")
    require("pull_request" not in issue and issue["state"] == "open", "task must be an open issue")
    require(any(label["name"] == "agent-task" for label in issue["labels"]), "task must be opted in by a repository writer")
    record = parse(issue["body"])
    check(record, pr, [(n, r) for n, r in tasks if n != number])
    files = github.pages(f"pulls/{pr['number']}/files")
    require(len(files) == pr["changed_files"], "incomplete PR file inventory")
    for file in files:
        for path in [file["filename"]] + ([file["previous_filename"]] if "previous_filename" in file else []):
            require(any(path == scope or path.startswith(scope + "/") for scope in record["scope"]),
                    f"PR path outside claimed scope: {path}")
    latest = github.api(f"issues/{number}")
    require(latest["state"] == "open" and latest["body"] == issue["body"], "task changed while checking")


def publish(github, pr, tasks, open_prs=None):
    state, detail = "success", "Recorded gates pass; evidence truth and CI require independent verification"
    try:
        check_pr(github, pr, tasks, open_prs)
    except (ValueError, KeyError, TypeError) as exc:
        state, detail = "failure", str(exc)
    github.api(f"statuses/{pr['head']['sha']}", "POST", {
        "state": state, "context": "coordination/pr", "description": detail[:140],
        "target_url": pr["html_url"],
    })
    return state, detail


def refresh(github):
    prs = github.pages("pulls?state=open")
    for pr in prs:
        github.api(f"statuses/{pr['head']['sha']}", "POST", {"state": "pending", "context": "coordination/pr",
                   "description": "Refreshing current task and revision evidence"})
    try:
        tasks = github.tasks()
    except (ValueError, KeyError, TypeError) as exc:
        for pr in prs:
            github.api(f"statuses/{pr['head']['sha']}", "POST", {"state": "failure", "context": "coordination/pr",
                       "description": ("Invalid task inventory: " + str(exc))[:140]})
        raise
    for summary in prs:
        publish(github, github.api(f"pulls/{summary['number']}"), tasks, prs)


def trusted(github, event):
    require(os.environ.get("GITHUB_ACTIONS") == "true", "mutation requires trusted workflow")
    default = github.api("")["default_branch"]
    require(os.environ.get("GITHUB_REF") == f"refs/heads/{default}", "dispatch must run on default branch")
    actor = os.environ.get("GITHUB_ACTOR", "")
    require(re.fullmatch(r"[A-Za-z0-9-]+(?:\[bot\])?", actor), "invalid actor")
    permission = github.api(f"collaborators/{actor}/permission")["permission"]
    require(permission in {"admin", "maintain", "write"}, "repository write permission required")



MIRROR_NAMESPACES = ("task:", "agent:", "risk:", "hardware:")


def record_mirrors(record):
    return [f"task:{record['status']}", f"agent:{record['agent']}",
            f"risk:{record['class']}", f"hardware:{record['hardware']}"]


def label_delta(current, wanted):
    """Labels to add and mirror labels to remove. Never a whole-set
    replacement, so a label added concurrently (e.g. merge-hold) survives."""
    add = [label for label in wanted if label not in current]
    remove = [label for label in current if label.startswith(MIRROR_NAMESPACES) and label not in wanted]
    return add, remove


def sync_labels(github, number, wanted):
    current = [x["name"] for x in github.api(f"issues/{number}")["labels"]]
    add, remove = label_delta(current, wanted)
    if add:
        github.api(f"issues/{number}/labels", "POST", {"labels": add})
    for label in remove:
        github.api(f"issues/{number}/labels/{urllib.parse.quote(label, safe='')}", "DELETE")
    return add, remove


def mirror_labels(github, number, record):
    # Only the mirror namespaces change; unrelated labels survive.
    sync_labels(github, number, ["agent-task"] + record_mirrors(record))

def apply_event(github, event):
    trusted(github, event)
    inputs = event["inputs"]
    number, revision = int(inputs["issue"]), int(inputs["expected_revision"])
    require(number > 0 and revision >= 0, "invalid issue/revision")
    issue = github.api(f"issues/{number}")
    require("pull_request" not in issue and issue["state"] == "open", "open task issue required")
    proposed = load_record(inputs["record_json"])
    if revision == 0:
        require("```regear-task" not in (issue["body"] or ""), "record already exists")
        new = validate(proposed)
        require(new["revision"] == 1 and new["owner"] is None and new["status"] == "backlog",
                "new record must start unclaimed at revision 1")
        body = (issue["body"] or "") + "\n\n```regear-task\n" + json.dumps(new, indent=2) + "\n```"
    else:
        old = parse(issue["body"])
        new = update(old, proposed, revision, [(n, r) for n, r in github.tasks() if n != number])
        body = replace(issue["body"], new)
    try:
        write_body(github, number, issue["body"], body, new)
    finally:
        refresh(github)  # GITHUB_TOKEN writes do not generate another workflow run.
    print(json.dumps({"issue": number, "record": new}))


def write_body(github, number, observed, body, new):
    """Guarded write of one issue body, then read back and mirror labels.

    `observed` is the body the caller derived `new` from; a different current
    body refuses the write. GitHub offers no conditional PATCH, so this is not
    atomic by itself: it is safe because every record writer (dispatch workflow
    and reconciler) runs in the one `github-task-record-writer` concurrency
    group. A human edit between the check and the PATCH is still possible and
    is the documented cooperative-guard limit."""
    # Direct edits are outside the cooperative writer protocol. Detect observed drift.
    require(github.api(f"issues/{number}")["body"] == observed, "issue changed during update")
    github.api(f"issues/{number}", "PATCH", {"body": body})
    require(parse(github.api(f"issues/{number}")["body"]) == new, "update readback mismatch")
    mirror_labels(github, number, new)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["queue", "check-pr", "apply-event", "gate-event"])
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY"))
    parser.add_argument("--pr", type=int)
    args = parser.parse_args()
    require(bool(args.repo), "--repo OWNER/REPO required")
    github = GitHub(args.repo)
    if args.command == "queue":
        print(json.dumps(queue(github), indent=2))
    elif args.command == "check-pr":
        require(args.pr is not None and args.pr > 0, "--pr required")
        check_pr(github, github.api(f"pulls/{args.pr}"), github.tasks())
        print("Recorded gates pass; independently verify evidence and required CI.")
    else:
        event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
        if args.command == "apply-event":
            apply_event(github, event)
        else:
            require(os.environ.get("GITHUB_ACTIONS") == "true", "status publishing requires trusted workflow")
            refresh(github)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, TypeError, subprocess.CalledProcessError) as error:
        print(f"coordination: {error}", file=sys.stderr)
        sys.exit(1)
