"""Shared plumbing for the end-to-end runs: example manifests, temp repos, headless Claude.

Every example under ``examples/`` carries an ``e2e.json`` manifest describing what the runs need
(cycle, prefix, plan, gate, a read-only path to probe, and a declarative defect to plant). Keeping
those facts in the example is what lets the same run exercise any stack.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "examples"
RITE_PY = ROOT / "bin" / "rite.py"
REQUIRED = ("name", "cycle", "prefix", "plan", "gate", "read_only_probe", "defect")
DEFECT_REQUIRED = ("file_glob", "symptom_command", "good_output", "bad_output")


def load_manifest(example: str) -> tuple[Path, dict]:
    """Return (example directory, manifest). Raises on a malformed manifest."""
    directory = EXAMPLES / example
    manifest_path = directory / "e2e.json"
    if not manifest_path.is_file():
        raise SystemExit(f"{example}: no e2e.json (examples: {', '.join(sorted(p.name for p in EXAMPLES.iterdir()))})")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    missing = [k for k in REQUIRED if k not in manifest]
    if missing:
        raise SystemExit(f"{manifest_path}: missing {missing}")
    defect = manifest["defect"]
    missing = [k for k in DEFECT_REQUIRED if k not in defect]
    if missing:
        raise SystemExit(f"{manifest_path}: defect missing {missing}")
    for defect in [defect] + ([manifest["residue_defect"]] if "residue_defect" in manifest else []):
        if "candidates" not in defect:
            defect["candidates"] = [{k: defect[k] for k in ("find", "replace", "append") if k in defect}]
    return directory, manifest


def defect_edits(manifest: dict) -> list[dict]:
    return manifest["defect"]["candidates"]


def defect_list(manifest: dict) -> list[dict]:
    """The manifest's ``defects`` (several, for the cost experiment), else its single ``defect``."""
    defects = manifest.get("defects") or [manifest["defect"]]
    for defect in defects:
        if "candidates" not in defect:
            defect["candidates"] = [{k: defect[k] for k in ("find", "replace", "append") if k in defect}]
    return defects


# --- processes -----------------------------------------------------------------
def sh(cwd: Path, *cmd: str, check: bool = True, timeout: int | None = None) -> str:
    res = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                         stdin=subprocess.DEVNULL, timeout=timeout)
    if check and res.returncode:
        raise AssertionError(f"{' '.join(cmd)} -> {res.returncode}\n{res.stdout}\n{res.stderr}")
    return res.stdout


def shell(cwd: Path, command: str) -> str:
    """Run a manifest command string (it carries its own quoting) and return stdout+stderr — in bash,
    the shell rite runs gates and evidence in, so the harness sees what the rite sees."""
    from rite_lib.compose import find_bash
    bash = find_bash()
    run = ([*bash, command], False) if bash else (command, True)
    res = subprocess.run(run[0], cwd=cwd, shell=run[1], capture_output=True, text=True, encoding="utf-8",
                         errors="replace", stdin=subprocess.DEVNULL)
    return (res.stdout + res.stderr).strip()


def rite(repo: Path, *args: str) -> tuple[int, str]:
    res = subprocess.run([sys.executable, str(RITE_PY), *args, "--root", str(repo)],
                         capture_output=True, text=True, encoding="utf-8", errors="replace")
    return res.returncode, res.stdout + res.stderr


def rite_json(repo: Path, *args: str) -> dict:
    code, out = rite(repo, *args, "--json")
    start = out.find("{")
    if start < 0:
        return {"_error": out, "_code": code}
    data = json.loads(out[start: out.rfind("}") + 1])
    data["_code"] = code
    return data


def claude(repo: Path, prompt: str, model: str, log: list[str] | None = None, timeout: int = 45 * 60,
           plugin: Path = ROOT) -> str:
    print(f"\n$ claude -p {prompt!r}", flush=True)
    try:
        out = sh(repo, "claude", "-p", prompt, "--plugin-dir", str(plugin), "--model", model,
                 "--dangerously-skip-permissions", check=False, timeout=timeout)
    except subprocess.TimeoutExpired:
        out = "TIMEOUT"
    print(out[-2500:], flush=True)
    if log is not None:
        log.append(f"## {prompt}\n\n{out}\n")
    return out


def subjects(repo: Path, n: int | None = None) -> list[str]:
    args = ["git", "log", "--format=%s"] + ([f"-{n}"] if n else [])
    return sh(repo, *args).splitlines()


# --- repositories ---------------------------------------------------------------
def make_repo(example: str, *, strip: tuple[str, ...] = ()) -> tuple[Path, Path, dict]:
    """Copy an example into a fresh temp git repo. Returns (tmp root, repo, manifest)."""
    directory, manifest = load_manifest(example)
    tmp = Path(tempfile.mkdtemp(prefix=f"rite-{example}-"))
    repo = tmp / manifest["name"]
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc", "node_modules", *strip)
    shutil.copytree(directory, repo, ignore=ignore)
    for cmd in (["init", "-q"], ["config", "user.name", "Rite E2E"],
                ["config", "user.email", "e2e@example.invalid"], ["config", "core.autocrlf", "false"],
                ["config", "commit.gpgsign", "false"], ["add", "-A"], ["commit", "-q", "-m", "chore: example"]):
        sh(repo, "git", *cmd)
    return tmp, repo, manifest


def plant_defect(repo: Path, manifest: dict) -> Path | None:
    """Apply the manifest's declarative defect and commit it. Returns the file, or None if it did not apply."""
    return apply_defect(repo, manifest["defect"])


def apply_defect(repo: Path, defect: dict) -> Path | None:
    """Apply one declarative defect and commit it. With ``after`` (a generator whose output follows
    the edited file) it runs that command and commits what it rewrote too. Returns the file, or None."""
    for path in sorted(repo.glob(defect["file_glob"])):
        text = path.read_text(encoding="utf-8")
        for edit in defect["candidates"]:
            if edit.get("find") and edit["find"] in text:
                broken = text.replace(edit["find"], edit["replace"], 1) + edit.get("append", "")
                path.write_text(broken, encoding="utf-8", newline="\n")
                sh(repo, "git", "add", "--", str(path.relative_to(repo)).replace("\\", "/"))
                if defect.get("after"):
                    shell(repo, defect["after"])
                    sh(repo, "git", "add", "-A")
                sh(repo, "git", "commit", "-q", "-m", defect.get("commit_subject", "refactor: tweak"))
                print(f"planted defect in {path.relative_to(repo)}", flush=True)
                return path
    return None


# --- seeding: the cost experiment starts from finished tasks and open fixes --------
def seed_done(repo: Path, manifest: dict, example: str) -> list[str]:
    """Apply the example's reference solution task by task: a work commit, then ``rite close``."""
    solution = manifest["solution"]
    source = EXAMPLES / example / solution["dir"]
    closed = []
    for item_id, task in solution["tasks"].items():
        for rel in task["files"]:
            target = repo / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((source / (rel + solution.get("suffix", ""))).read_bytes())
        if solution.get("after"):
            shell(repo, solution["after"])
        sh(repo, "git", "add", "-A")
        refs = rite_json(repo, "commit-refs", item_id)
        subject = refs["subject_template"].format(subject=task["subject"])
        sh(repo, "git", "commit", "-q", "-m", subject + "\n\n" + "\n".join(refs["trailers"]))
        code, out = rite(repo, "close", item_id)
        if code:
            raise AssertionError(f"rite close {item_id}: {out}")
        closed.append(item_id)
    return closed


def fill_fix(path: Path, defect: dict, seen: str) -> None:
    """Write what a reviewer would: the observable, its evidence as run, the files, the check."""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from rite_lib import frontmatter
    text = frontmatter.set_fields(path.read_text(encoding="utf-8"), {"files": defect["files"]})
    command, good = defect["symptom_command"], defect["good_output"]
    swaps = [
        ("<!-- What is wrong, stated as an observable fact. -->",
         f"{defect['title']}: `{command}` prints `{seen}`, expected `{good}`."),
        ("```text\n$\n```", f"```text\n$ {command}\n{seen}\n```"),
        ("## Files\n\n-\n", "## Files\n\n" + "".join(f"- `{f}`\n" for f in defect["files"])),
        ("<!-- Command(s) that turn red before the fix and green after it. -->",
         f"`{command}` prints `{good}`."),
    ]
    for old, new in swaps:
        if old not in text:
            raise AssertionError(f"{path.name}: the fix template changed, cannot fill {old!r}")
        text = text.replace(old, new, 1)
    path.write_text(text, encoding="utf-8", newline="\n")


def seed_fixes(repo: Path, manifest: dict, defects: list[dict]) -> list[str]:
    """Open one fix per planted defect, as a review would, and record the reviews that opened them."""
    opened: dict[str, list[str]] = {item_id: [] for item_id in manifest["solution"]["tasks"]}
    for defect in defects:
        seen = symptom_of(repo, defect)
        if seen != defect["bad_output"]:
            raise AssertionError(f"{defect['title']}: symptom prints {seen!r}, not {defect['bad_output']!r}")
        new = rite_json(repo, "new-fix", "--origin", defect["origin"], "--title", defect["title"],
                        "--severity", defect["severity"])
        if new.get("_code"):
            raise AssertionError(f"rite new-fix: {new}")
        fill_fix(repo / new["path"].lstrip("/"), defect, seen)
        opened[defect["origin"]].append(new["id"])
    for item_id, fixes in opened.items():
        args = ["mark-reviewed", item_id] + (["--fixes", ",".join(fixes)] if fixes else [])
        code, out = rite(repo, *args)
        if code:
            raise AssertionError(f"rite {' '.join(args)}: {out}")
    return [f for fixes in opened.values() for f in fixes]


def seed_fix(repo: Path, defect: dict, origin: str, planted: Path) -> str:
    """Open and commit one fix for a defect planted in ``planted``, as a review would. Returns its ID."""
    seen = symptom_of(repo, defect)
    if seen != defect["bad_output"]:
        raise AssertionError(f"{defect['title']}: symptom prints {seen!r}, not {defect['bad_output']!r}")
    new = rite_json(repo, "new-fix", "--origin", origin, "--title", defect["title"],
                    "--severity", defect["severity"])
    if new.get("_code"):
        raise AssertionError(f"rite new-fix: {new}")
    files = [str(planted.relative_to(repo)).replace("\\", "/")]
    fill_fix(repo / new["path"].lstrip("/"), {**defect, "files": files}, seen)
    code, out = rite(repo, "commit-new", new["id"])
    if code:
        raise AssertionError(f"rite commit-new {new['id']}: {out}")
    return new["id"]


def open_fixes(repo: Path, cycle: str) -> int:
    status = rite_json(repo, "status", "--cycle", cycle)
    return sum(status["cycles"][0]["open_fixes"].values())


def transcripts_for(repo: Path) -> Path:
    """Where Claude Code keeps the transcripts of the sessions run in ``repo``."""
    return Path.home() / ".claude" / "projects" / re.sub(r"[^A-Za-z0-9]", "-", str(repo.resolve()))


def invocations(repo: Path, command: str) -> list:
    """The invocations of ``command`` in the transcripts of the sessions run in ``repo``."""
    tools = str(ROOT / "tools")
    if tools not in sys.path:
        sys.path.insert(0, tools)
    import token_report
    return [i for i in token_report.collect(transcripts_for(repo), None) if i.command == command]


def agents_of(invocation, kind: str) -> int:
    """How many subagents of type ``kind`` an invocation started."""
    return sum(1 for run in invocation.agents if run.agent_type == kind)


def symptom(repo: Path, manifest: dict) -> str:
    """Last line of the manifest's symptom command — the observable the defect changes."""
    return symptom_of(repo, manifest["defect"])


def symptom_of(repo: Path, defect: dict) -> str:
    out = shell(repo, defect["symptom_command"])
    return out.splitlines()[-1].strip() if out else ""


class Expect:
    """Collects PASS/FAIL lines so a run reports everything it checked."""

    def __init__(self) -> None:
        self.ok = True

    def __call__(self, cond: object, what: str) -> bool:
        passed = bool(cond)
        print(("PASS " if passed else "FAIL ") + what, flush=True)
        self.ok &= passed
        return passed

    def check_green(self, repo: Path, when: str) -> None:
        code, out = rite(repo, "check", "--all")
        self(code == 0, f"{when}: rite check green" + ("" if code == 0 else "\n" + out[-1500:]))

    def clean_tree(self, repo: Path, when: str) -> None:
        dirty = sh(repo, "git", "status", "--porcelain").strip()
        self(not dirty, f"{when}: working tree clean" + (f"\n{dirty}" if dirty else ""))


def finish(expect: Expect, tmp: Path, repo: Path, transcript: list[str], keep: bool) -> int:
    (tmp / "transcript.md").write_text("\n".join(transcript), encoding="utf-8")
    print("\nRESULT:", "PASS" if expect.ok else "FAIL")
    print("git log:\n" + sh(repo, "git", "log", "--format=  %h %s"))
    if keep or not expect.ok:
        print(f"kept: {tmp}")
    else:
        shutil.rmtree(tmp, ignore_errors=True)
    return 0 if expect.ok else 1
