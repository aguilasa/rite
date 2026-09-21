"""End-to-end loop with a real headless Claude Code and the plugin loaded (costs tokens; not in unittest).

    python tests/e2e/run_loop.py [--example python-minimal] [--model sonnet] [--keep]

Copies an example (with its cycle already planned) to a temp git repo and asserts, on git log,
frontmatter and the CLI:
  1. /rite:execute closes one task with a work commit + a bookkeeping commit;
  2. after the manifest's defect is planted, /rite:review opens a fix and records the review in one commit;
  3. /rite:fix closes that fix and the symptom command prints the good output again;
  4. an attempt to write the manifest's read-only path is blocked by the hook.

Everything specific to the example comes from its e2e.json; this file names no project, path or tool.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from _example import (Expect, claude, finish, make_repo, plant_defect, rite_json, sh,  # noqa: E402
                      subjects, symptom)
from rite_lib import frontmatter  # noqa: E402


def fields(path: Path) -> dict:
    return frontmatter.parse(path.read_text(encoding="utf-8"))[0]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--example", default="python-minimal")
    ap.add_argument("--model", default="sonnet")
    ap.add_argument("--keep", action="store_true", help="keep the temp repo for inspection")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    tmp, repo, manifest = make_repo(args.example)
    cycle = manifest["cycle"]
    print(f"example: {args.example}\nrepo: {repo}")
    expect, transcript = Expect(), []

    # 1. execute one task
    picked = rite_json(repo, "next", "task", "--cycle", cycle)
    if not expect(picked.get("id"), f"a task is selectable ({picked.get('reason')})"):
        return finish(expect, tmp, repo, transcript, args.keep)
    task_path = repo / picked["path"]
    before_done = rite_json(repo, "status", "--cycle", cycle)["cycles"][0]["tasks"]["done"]

    claude(repo, f"/rite:execute {cycle}", args.model, transcript)
    task = fields(task_path)
    expect(task.get("status") == "done" and task.get("reviewed_on") == "pending",
           f"execute: {picked['id']} done, awaiting review")
    log = subjects(repo, 2)
    expect(log[0] == f"chore(rite): close {picked['id']}" and not log[1].startswith("chore(rite)"),
           f"execute: work commit then bookkeeping commit {log}")
    after = rite_json(repo, "status", "--cycle", cycle)["cycles"][0]["tasks"]
    expect(after["done"] == before_done + 1, f"execute: exactly one more task done ({after})")
    expect.clean_tree(repo, "execute")

    # 2. plant the defect, then review
    planted = plant_defect(repo, manifest)
    expect(planted is not None, "defect planted from the manifest")
    expect(symptom(repo, manifest) == manifest["defect"]["bad_output"],
           f"defect is observable ({symptom(repo, manifest)!r})")

    claude(repo, f"/rite:review {cycle}", args.model, transcript)
    status = rite_json(repo, "status", "--cycle", cycle)["cycles"][0]
    open_fixes = sum(status["open_fixes"].values())
    expect(open_fixes >= 1, f"review: opened a fix ({status['open_fixes']})")
    expect(str(fields(task_path).get("reviewed_on", "")).count("-") == 2, "review: reviewed_on is a date")
    expect(subjects(repo, 1)[0].startswith(f"chore(rite): review {picked['id']}"),
           f"review: one review commit {subjects(repo, 1)}")
    fix = rite_json(repo, "next", "fix", "--cycle", cycle)

    # 3. fix
    claude(repo, f"/rite:fix {cycle}", args.model, transcript)
    if fix.get("path"):
        expect(fields(repo / fix["path"]).get("status") in ("done", "stale"),
               f"fix: {fix['id']} closed ({fields(repo / fix['path']).get('status')})")
    expect(symptom(repo, manifest) == manifest["defect"]["good_output"],
           f"fix: symptom repaired ({symptom(repo, manifest)!r})")
    expect.check_green(repo, "fix")

    # 4. guard
    probe = repo / manifest["read_only_probe"]
    before = probe.read_bytes()
    claude(repo, f"Use the Write tool to replace the content of {manifest['read_only_probe']} with the "
                 "single word x. Do not use the shell. Report whether it worked.", args.model, transcript)
    expect(probe.read_bytes() == before, "guard: read-only path unchanged")

    sh(repo, "git", "status", "--porcelain")
    return finish(expect, tmp, repo, transcript, args.keep)


if __name__ == "__main__":
    sys.exit(main())
