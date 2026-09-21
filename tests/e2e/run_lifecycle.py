"""End-to-end lifecycle from zero with a real headless Claude Code (costs tokens; not in unittest).

    python tests/e2e/run_lifecycle.py [--example python-minimal] [--model sonnet] [--keep] [--max-steps 14]

Starts from an example stripped of its rite.toml and cycle (only code, tests and a plan), then:
  1. /rite:init --yes                  -> rite.toml + CLAUDE.md block, committed
  2. /rite:new-cycle ... --yes         -> cycle folder, views, profile, pitfalls
  3. /rite:plan-to-tasks ... --yes     -> tasks with anchors, a closing task, profile phase checks
  4. /rite:execute-batch <cycle> 2     -> first wave(s); then the manifest's defect is planted
  5. autopilot: run whatever `rite status` suggests (execute-batch / execute / review / fix-all)
     until the cycle can close
  6. /rite:close-cycle <cycle> --yes   -> archived, links rewritten
  7. /rite:retro <cycle> --yes         -> retro.md
and asserts on git log, frontmatter and `rite check` after every step.

Everything specific to the example comes from its e2e.json; this file names no project, path or tool.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from _example import (Expect, claude, finish, make_repo, plant_defect, rite_json,  # noqa: E402
                      subjects, symptom)

# the example ships a planned cycle; the lifecycle run creates its own from scratch
STRIP = ("rite.toml", "rite")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--example", default="python-minimal")
    ap.add_argument("--model", default="sonnet")
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--max-steps", type=int, default=14)
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    tmp, repo, manifest = make_repo(args.example, strip=STRIP)
    cycle, prefix, plan = manifest["cycle"], manifest["prefix"], manifest["plan"]
    print(f"example: {args.example}\nrepo: {repo}")
    expect, transcript = Expect(), []

    # 1. init
    claude(repo, "/rite:init --yes", args.model, transcript)
    if not expect((repo / "rite.toml").is_file(), "init: rite.toml written"):
        return finish(expect, tmp, repo, transcript, args.keep)
    expect(rite_json(repo, "status", "--all").get("_code") == 0, "init: rite.toml loads")
    expect("<!-- rite:begin -->" in (repo / "CLAUDE.md").read_text(encoding="utf-8"), "init: CLAUDE.md block")
    expect(any("rite" in s and s.startswith("chore") for s in subjects(repo, 2)), "init: committed")
    expect.clean_tree(repo, "init")

    # 2. new cycle
    claude(repo, f"/rite:new-cycle {cycle} --prefix {prefix} --plan {plan} --yes", args.model, transcript)
    info = rite_json(repo, "resolve-cycle", cycle)
    expect(info.get("prefix") == prefix, f"new-cycle: cycle resolves with prefix {prefix} ({info.get('prefix')})")
    expect(info.get("profile_exists") and info.get("pitfalls_exists"), "new-cycle: profile and pitfalls exist")
    expect.clean_tree(repo, "new-cycle")

    # 3. plan to tasks
    claude(repo, f"/rite:plan-to-tasks {plan} {cycle} --yes", args.model, transcript)
    total = rite_json(repo, "status", "--cycle", cycle)["cycles"][0]["tasks"]["total"]
    expect(total >= 2, f"plan-to-tasks: {total} tasks created")
    cyc_dir = repo / info["path"]
    types = [m.group(1) for p in sorted(cyc_dir.rglob("*.md"))
             if (m := re.search(r"(?m)^type: (\S+)", p.read_text(encoding="utf-8")))]
    expect("closing" in types, f"plan-to-tasks: a closing task exists ({types})")
    expect.check_green(repo, "plan-to-tasks")
    expect.clean_tree(repo, "plan-to-tasks")

    # 4. first batch, then plant the defect for the reviewers to find
    claude(repo, f"/rite:execute-batch {cycle} 2", args.model, transcript)
    done = rite_json(repo, "status", "--cycle", cycle)["cycles"][0]["tasks"]["done"]
    closes = [s for s in subjects(repo) if s.startswith("chore(rite): close")]
    expect(done >= 1, f"execute-batch: {done} task(s) done")
    expect(len(closes) == done, f"execute-batch: one close commit per done task ({len(closes)}/{done})")
    expect.check_green(repo, "execute-batch")
    expect.clean_tree(repo, "execute-batch")
    expect(plant_defect(repo, manifest) is not None, "defect planted from the manifest")

    # 5. autopilot on the status suggestion
    seen: list[str] = []
    for _ in range(args.max_steps):
        summary = rite_json(repo, "status", "--cycle", cycle)["cycles"][0]
        suggestion = summary.get("suggestion", {})
        cmd = suggestion.get("command")
        seen.append(cmd)
        if cmd == "close-cycle" or cmd is None:
            break
        prompt = {"execute": f"/rite:execute-batch {cycle} 3", "review": f"/rite:review {cycle}",
                  "fix": f"/rite:fix-all {cycle}"}.get(cmd)
        blocked = re.search(r"/rite:execute (\S+) re-checks", suggestion.get("reason", ""))
        if cmd == "execute" and blocked:
            prompt = f"/rite:execute {cycle} {blocked.group(1)}"
        if not prompt:
            expect(False, f"autopilot: unexpected suggestion {suggestion}")
            break
        claude(repo, prompt, args.model, transcript)
        expect.check_green(repo, f"after {prompt}")
    print("autopilot:", " -> ".join(str(c) for c in seen))
    expect("review" in seen, "autopilot: reviews ran")
    expect("fix" in seen, "autopilot: the planted defect became a fix and fix-all ran")
    expect(seen and seen[-1] == "close-cycle", f"autopilot: cycle ready to close ({seen[-1] if seen else None})")
    expect(symptom(repo, manifest) == manifest["defect"]["good_output"],
           f"planted defect repaired ({symptom(repo, manifest)!r})")

    # 6. close cycle
    claude(repo, f"/rite:close-cycle {cycle} --yes", args.model, transcript)
    archived = rite_json(repo, "resolve-cycle", cycle)
    expect(archived.get("archived") is True, f"close-cycle: archived at {archived.get('path')}")
    expect(f"chore(rite): archive {cycle}" in subjects(repo), "close-cycle: archive commit")
    expect.check_green(repo, "close-cycle")

    # 7. retro
    claude(repo, f"/rite:retro {cycle} --yes", args.model, transcript)
    expect((repo / archived.get("path", "") / "retro.md").is_file(), "retro: retro.md written")
    expect.clean_tree(repo, "retro")

    stats = rite_json(repo, "stats", cycle)
    n_done = stats.get("tasks", {}).get("done", 0) + stats.get("fixes", {}).get("done", 0)
    n_close = len([s for s in subjects(repo) if s.startswith("chore(rite): close")])
    expect(n_done == n_close, f"one close commit per done item ({n_close}/{n_done})")
    return finish(expect, tmp, repo, transcript, args.keep)


if __name__ == "__main__":
    sys.exit(main())
