"""Shared plumbing for the end-to-end runs: example manifests, temp repos, headless Claude.

Every example under ``examples/`` carries an ``e2e.json`` manifest describing what the runs need
(cycle, prefix, plan, gate, a read-only path to probe, and a declarative defect to plant). Keeping
those facts in the example is what lets the same run exercise any stack.
"""

from __future__ import annotations

import json
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
    if "candidates" not in defect:
        defect["candidates"] = [{k: defect[k] for k in ("find", "replace", "append") if k in defect}]
    return directory, manifest


def defect_edits(manifest: dict) -> list[dict]:
    return manifest["defect"]["candidates"]


# --- processes -----------------------------------------------------------------
def sh(cwd: Path, *cmd: str, check: bool = True, timeout: int | None = None) -> str:
    res = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                         stdin=subprocess.DEVNULL, timeout=timeout)
    if check and res.returncode:
        raise AssertionError(f"{' '.join(cmd)} -> {res.returncode}\n{res.stdout}\n{res.stderr}")
    return res.stdout


def shell(cwd: Path, command: str) -> str:
    """Run a manifest command string (it carries its own quoting) and return stdout+stderr."""
    res = subprocess.run(command, cwd=cwd, shell=True, capture_output=True, text=True, encoding="utf-8",
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


def claude(repo: Path, prompt: str, model: str, log: list[str] | None = None, timeout: int = 45 * 60) -> str:
    print(f"\n$ claude -p {prompt!r}", flush=True)
    try:
        out = sh(repo, "claude", "-p", prompt, "--plugin-dir", str(ROOT), "--model", model,
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
    defect = manifest["defect"]
    for path in sorted(repo.glob(defect["file_glob"])):
        text = path.read_text(encoding="utf-8")
        for edit in defect_edits(manifest):
            if edit.get("find") and edit["find"] in text:
                broken = text.replace(edit["find"], edit["replace"], 1) + edit.get("append", "")
                path.write_text(broken, encoding="utf-8", newline="\n")
                sh(repo, "git", "add", "--", str(path.relative_to(repo)).replace("\\", "/"))
                sh(repo, "git", "commit", "-q", "-m", defect.get("commit_subject", "refactor: tweak"))
                print(f"planted defect in {path.relative_to(repo)}", flush=True)
                return path
    return None


def symptom(repo: Path, manifest: dict) -> str:
    """Last line of the manifest's symptom command — the observable the defect changes."""
    out = shell(repo, manifest["defect"]["symptom_command"])
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
