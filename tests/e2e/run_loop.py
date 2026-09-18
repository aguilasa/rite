"""End-to-end loop with a real headless Claude Code and the plugin loaded (costs tokens; not in unittest).

    python tests/e2e/run_loop.py [--model sonnet] [--keep]

Copies examples/python-minimal to a temp git repo and asserts, on git log and frontmatter:
  1. /rite:execute closes TXT-TASK-01 with a work commit + a bookkeeping commit;
  2. after a planted defect, /rite:review opens a fix and records the review in one commit;
  3. /rite:fix closes that fix and the gates are green again;
  4. an attempt to write a read-only path is blocked by the hook.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from rite_lib import frontmatter  # noqa: E402

EXAMPLE = ROOT / "examples" / "python-minimal"
CYCLE = Path("docs/rite/cycles/textkit")


def sh(repo: Path, *cmd: str, check: bool = True) -> str:
    res = subprocess.run(cmd, cwd=repo, capture_output=True, text=True, encoding="utf-8", errors="replace",
                         stdin=subprocess.DEVNULL)
    if check and res.returncode:
        raise AssertionError(f"{' '.join(cmd)} -> {res.returncode}\n{res.stdout}\n{res.stderr}")
    return res.stdout


def claude(repo: Path, prompt: str, model: str) -> str:
    print(f"\n$ claude -p {prompt!r}", flush=True)
    out = sh(repo, "claude", "-p", prompt, "--plugin-dir", str(ROOT), "--model", model,
             "--dangerously-skip-permissions", check=False)
    print(out[-3000:], flush=True)
    return out


def fields(repo: Path, rel: str) -> dict:
    return frontmatter.parse((repo / CYCLE / rel).read_text(encoding="utf-8"))[0]


def subjects(repo: Path, n: int) -> list[str]:
    return sh(repo, "git", "log", f"-{n}", "--format=%s").splitlines()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="sonnet")
    ap.add_argument("--keep", action="store_true", help="keep the temp repo for inspection")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    tmp = Path(tempfile.mkdtemp(prefix="rite-e2e-"))
    repo = tmp / "textkit"
    shutil.copytree(EXAMPLE, repo, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for cmd in (["init", "-q"], ["config", "user.name", "Rite E2E"], ["config", "user.email", "e2e@example.invalid"],
                ["config", "core.autocrlf", "false"], ["add", "-A"], ["commit", "-q", "-m", "chore: example"]):
        sh(repo, "git", *cmd)
    print(f"repo: {repo}")
    ok = True

    def expect(cond: bool, what: str) -> None:
        nonlocal ok
        print(("PASS " if cond else "FAIL ") + what, flush=True)
        ok &= cond

    # 1. execute
    claude(repo, "/rite:execute textkit", args.model)
    t1 = fields(repo, "01-slugify.md")
    expect(t1.get("status") == "done" and t1.get("reviewed_on") == "pending", "execute: TXT-TASK-01 done, awaiting review")
    log = subjects(repo, 2)
    expect(log[0] == "chore(rite): close TXT-TASK-01" and not log[1].startswith("chore(rite)"),
           f"execute: work commit then bookkeeping commit {log}")
    expect(fields(repo, "02-word-count.md").get("status") == "pending", "execute: only one task done")

    # 2. plant a defect, then review
    init = repo / "textkit" / "__init__.py"
    mod = next((p for p in (repo / "textkit").glob("*.py") if "def slugify" in p.read_text(encoding="utf-8")), init)
    text = mod.read_text(encoding="utf-8")
    planted = text.replace("def slugify(", "def _slugify_ok(", 1) + \
        "\n\ndef slugify(text):\n    return _slugify_ok(text).upper()  # planted defect\n"
    mod.write_text(planted, encoding="utf-8")
    sh(repo, "git", "add", "--", str(mod.relative_to(repo)))
    sh(repo, "git", "commit", "-q", "-m", "refactor: tweak slugify")
    claude(repo, "/rite:review textkit", args.model)
    t1 = fields(repo, "01-slugify.md")
    fixes = sorted((repo / CYCLE).glob("FIX-TXT-*.md"))
    expect(bool(fixes), f"review: opened a fix ({[f.name for f in fixes]})")
    expect(str(t1.get("reviewed_on", "")).count("-") == 2, "review: reviewed_on is a date")
    expect(subjects(repo, 1)[0].startswith("chore(rite): review TXT-TASK-01"), f"review: one review commit {subjects(repo, 1)}")

    # 3. fix
    claude(repo, "/rite:fix textkit", args.model)
    if fixes:
        fx = frontmatter.parse(fixes[0].read_text(encoding="utf-8"))[0]
        expect(fx.get("status") == "done", f"fix: {fixes[0].stem} done")
    out = sh(repo, sys.executable, "-c", "from textkit import slugify; print(slugify('Hello, World!'))", check=False)
    expect(out.strip() == "hello-world", f"fix: slugify restored ({out.strip()!r})")
    check = subprocess.run([sys.executable, str(ROOT / "bin" / "rite.py"), "check", "--root", str(repo)],
                           capture_output=True, text=True)
    expect(check.returncode == 0, f"rite check green\n{check.stdout}")

    # 4. guard
    golden = repo / "data" / "golden" / "words.txt"
    before = golden.read_bytes()
    claude(repo, "Use the Write tool to replace the content of data/golden/words.txt with the single word x. "
                 "Do not use the shell. Report whether it worked.", args.model)
    expect(golden.read_bytes() == before, "guard: read-only golden file unchanged")

    print("\nRESULT:", "PASS" if ok else "FAIL")
    if args.keep or not ok:
        print(f"kept: {repo}")
    else:
        shutil.rmtree(tmp, ignore_errors=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
