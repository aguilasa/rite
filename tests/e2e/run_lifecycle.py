"""End-to-end lifecycle from zero with a real headless Claude Code (costs tokens; not in unittest).

    python tests/e2e/run_lifecycle.py [--model sonnet] [--keep] [--max-steps 14]

Starts from examples/python-minimal with only code and a plan (no rite.toml, no cycle), then:
  1. /rite:init --yes                  -> rite.toml + CLAUDE.md block, committed
  2. /rite:new-cycle ... --yes         -> cycle folder, views, profile, pitfalls
  3. /rite:plan-to-tasks ... --yes     -> tasks with anchors, a closing task, profile phase checks
  4. /rite:execute-batch textkit 2     -> first wave(s); then a defect is planted
  5. autopilot: run whatever `rite status` suggests (execute-batch / review / fix-all) until the
     cycle can close
  6. /rite:close-cycle textkit --yes   -> archived, links rewritten
  7. /rite:retro textkit --yes         -> retro.md
and asserts on git log, frontmatter and `rite check` after every step.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "examples" / "python-minimal"
RITE = [sys.executable, str(ROOT / "bin" / "rite.py")]


def sh(repo: Path, *cmd: str, check: bool = True, timeout: int | None = None) -> str:
    res = subprocess.run(cmd, cwd=repo, capture_output=True, text=True, encoding="utf-8", errors="replace",
                         stdin=subprocess.DEVNULL, timeout=timeout)
    if check and res.returncode:
        raise AssertionError(f"{' '.join(cmd)} -> {res.returncode}\n{res.stdout}\n{res.stderr}")
    return res.stdout


def rite(repo: Path, *args: str) -> tuple[int, str]:
    res = subprocess.run([*RITE, *args, "--root", str(repo)], capture_output=True, text=True, encoding="utf-8")
    return res.returncode, res.stdout + res.stderr


def rite_json(repo: Path, *args: str) -> dict:
    code, out = rite(repo, *args, "--json")
    return json.loads(out[: out.rfind("}") + 1]) if "{" in out else {"_error": out, "_code": code}


def claude(repo: Path, prompt: str, model: str, log: list[str]) -> str:
    print(f"\n$ claude -p {prompt!r}", flush=True)
    try:
        out = sh(repo, "claude", "-p", prompt, "--plugin-dir", str(ROOT), "--model", model,
                 "--dangerously-skip-permissions", check=False, timeout=45 * 60)
    except subprocess.TimeoutExpired:
        out = "TIMEOUT"
    print(out[-2500:], flush=True)
    log.append(f"## {prompt}\n\n{out}\n")
    return out


def subjects(repo: Path) -> list[str]:
    return sh(repo, "git", "log", "--format=%s").splitlines()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="sonnet")
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--max-steps", type=int, default=14)
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    tmp = Path(tempfile.mkdtemp(prefix="rite-life-"))
    repo = tmp / "textkit"
    shutil.copytree(EXAMPLE, repo, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "rite.toml", "rite"))
    for cmd in (["init", "-q"], ["config", "user.name", "Rite E2E"], ["config", "user.email", "e2e@example.invalid"],
                ["config", "core.autocrlf", "false"], ["add", "-A"], ["commit", "-q", "-m", "chore: textkit"]):
        sh(repo, "git", *cmd)
    print(f"repo: {repo}")
    transcript: list[str] = []
    ok = True

    def expect(cond: bool, what: str) -> bool:
        nonlocal ok
        print(("PASS " if cond else "FAIL ") + what, flush=True)
        ok &= bool(cond)
        return bool(cond)

    def check_green(when: str) -> None:
        code, out = rite(repo, "check", "--all")
        expect(code == 0, f"{when}: rite check green" + ("" if code == 0 else "\n" + out[-1500:]))

    def clean_tree(when: str) -> None:
        dirty = sh(repo, "git", "status", "--porcelain").strip()
        expect(not dirty, f"{when}: working tree clean" + (f"\n{dirty}" if dirty else ""))

    # 1. init
    claude(repo, "/rite:init --yes", args.model, transcript)
    if not expect((repo / "rite.toml").is_file(), "init: rite.toml written"):
        return finish(ok, tmp, repo, transcript, args.keep)
    code, _ = rite(repo, "status", "--all")
    expect(code == 0, "init: rite.toml loads")
    expect("<!-- rite:begin -->" in (repo / "CLAUDE.md").read_text(encoding="utf-8"), "init: CLAUDE.md block")
    expect(any("rite" in s and s.startswith("chore") for s in subjects(repo)[:2]), "init: committed")
    clean_tree("init")

    # 2. new cycle
    claude(repo, "/rite:new-cycle textkit --prefix TXT --plan docs/plans/PLAN-textkit.md --yes", args.model, transcript)
    info = rite_json(repo, "resolve-cycle", "textkit")
    expect(info.get("prefix") == "TXT", f"new-cycle: cycle resolves with prefix TXT ({info.get('prefix')})")
    expect(info.get("profile_exists") and info.get("pitfalls_exists"), "new-cycle: profile and pitfalls exist")
    clean_tree("new-cycle")

    # 3. plan to tasks
    claude(repo, "/rite:plan-to-tasks docs/plans/PLAN-textkit.md textkit --yes", args.model, transcript)
    status = rite_json(repo, "status", "--cycle", "textkit")
    total = status.get("cycles", [{}])[0].get("tasks", {}).get("total", 0)
    expect(total >= 2, f"plan-to-tasks: {total} tasks created")
    cyc = repo / info.get("path", "docs/rite/cycles/textkit")
    types = [re.search(r"(?m)^type: (\S+)", p.read_text(encoding="utf-8")).group(1)
             for p in sorted(cyc.glob("[0-9]*.md"))]
    expect("closing" in types, f"plan-to-tasks: a closing task exists ({types})")
    check_green("plan-to-tasks")
    clean_tree("plan-to-tasks")

    # 4. first batch, then plant a defect for the reviewers to find
    claude(repo, "/rite:execute-batch textkit 2", args.model, transcript)
    done = [p for p in cyc.glob("[0-9]*.md") if re.search(r"(?m)^status: done", p.read_text(encoding="utf-8"))]
    closes = [s for s in subjects(repo) if s.startswith("chore(rite): close")]
    expect(len(done) >= 1, f"execute-batch: {len(done)} task(s) done")
    expect(len(closes) == len(done), f"execute-batch: one close commit per done task ({len(closes)}/{len(done)})")
    check_green("execute-batch")
    clean_tree("execute-batch")
    mod = next((p for p in (repo / "textkit").rglob("*.py") if "def slugify" in p.read_text(encoding="utf-8")), None)
    if mod:
        text = mod.read_text(encoding="utf-8")
        mod.write_text(text.replace("def slugify(", "def _slugify_ok(", 1)
                       + "\n\ndef slugify(text):\n    return _slugify_ok(text).upper()\n", encoding="utf-8")
        sh(repo, "git", "add", "--", str(mod.relative_to(repo)))
        sh(repo, "git", "commit", "-q", "-m", "refactor: tweak slugify")
        print("planted defect in", mod.relative_to(repo))

    # 5. autopilot on the status suggestion
    seen: list[str] = []
    for _ in range(args.max_steps):
        s = rite_json(repo, "status", "--cycle", "textkit").get("cycles", [{}])[0]
        cmd = s.get("suggestion", {}).get("command")
        seen.append(cmd)
        if cmd == "close-cycle" or cmd is None:
            break
        prompt = {"execute": "/rite:execute-batch textkit 3", "review": "/rite:review textkit",
                  "fix": "/rite:fix-all textkit"}.get(cmd)
        blocked = re.search(r"/rite:execute (\S+) re-checks", s.get("suggestion", {}).get("reason", ""))
        if cmd == "execute" and blocked:
            prompt = f"/rite:execute textkit {blocked.group(1)}"
        if not prompt:
            expect(False, f"autopilot: unexpected suggestion {cmd}: {s.get('suggestion')}")
            break
        claude(repo, prompt, args.model, transcript)
        check_green(f"after {prompt}")
    print("autopilot:", " -> ".join(str(c) for c in seen))
    expect("review" in seen, "autopilot: reviews ran")
    expect("fix" in seen, "autopilot: the planted defect became a fix and fix-all ran")
    expect(seen and seen[-1] == "close-cycle", f"autopilot: cycle ready to close ({seen[-1] if seen else None})")
    out = sh(repo, sys.executable, "-c", "from textkit import slugify; print(slugify('Hello, World!'))", check=False)
    expect(out.strip() == "hello-world", f"planted defect repaired ({out.strip()!r})")

    # 6. close cycle
    claude(repo, "/rite:close-cycle textkit --yes", args.model, transcript)
    archived = rite_json(repo, "resolve-cycle", "textkit")
    expect(archived.get("archived") is True, f"close-cycle: archived at {archived.get('path')}")
    expect(any(s == "chore(rite): archive textkit" for s in subjects(repo)), "close-cycle: archive commit")
    check_green("close-cycle")

    # 7. retro
    claude(repo, "/rite:retro textkit --yes", args.model, transcript)
    retro = repo / archived.get("path", "") / "retro.md"
    expect(retro.is_file(), "retro: retro.md written")
    clean_tree("retro")

    # every done item has exactly one close commit
    all_items = rite_json(repo, "stats", "textkit")
    n_done = all_items.get("tasks", {}).get("done", 0) + all_items.get("fixes", {}).get("done", 0)
    n_close = len([s for s in subjects(repo) if s.startswith("chore(rite): close")])
    expect(n_done == n_close, f"one close commit per done item ({n_close}/{n_done})")
    return finish(ok, tmp, repo, transcript, args.keep)


def finish(ok: bool, tmp: Path, repo: Path, transcript: list[str], keep: bool) -> int:
    (tmp / "transcript.md").write_text("\n".join(transcript), encoding="utf-8")
    print("\nRESULT:", "PASS" if ok else "FAIL")
    print("git log:\n" + sh(repo, "git", "log", "--format=  %h %s"))
    if keep or not ok:
        print(f"kept: {tmp}")
    else:
        shutil.rmtree(tmp, ignore_errors=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
