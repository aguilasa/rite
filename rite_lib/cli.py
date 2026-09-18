"""Command-line interface. Every subcommand prints text, or JSON with --json."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__, check as checkmod, config, ops, selection, views
from .gitutil import GitError
from .model import Project, RiteError, display

EXIT_OK, EXIT_FAIL, EXIT_USAGE, EXIT_NO_CONFIG = 0, 1, 2, 3


def _ids(values: list[str] | None) -> list[str]:
    out: list[str] = []
    for v in values or []:
        out += [x.strip() for x in v.split(",") if x.strip()]
    return out


def _emit(args, data, text: str) -> None:
    if args.json:
        print(json.dumps(data, indent=2, ensure_ascii=False, default=str))
    else:
        print(text)


def _pick_text(root: Path, label: str, pick: selection.Pick) -> str:
    if pick.item:
        return (f"{label}: {pick.item.id} — {pick.item.title}\n"
                f"  file: {display(root, pick.item.path)}\n  why: {pick.reason}")
    return f"{label}: none — {pick.reason}"


def _project(args) -> Project:
    root = Path(args.root).resolve() if args.root else None
    return Project(config.load(root) if root else config.load(start=Path.cwd()))


def _item(project: Project, args, item_id: str):
    cycle = project.resolve_cycle(args.cycle) if args.cycle else None
    return project.find_item(item_id, cycle)


# --- subcommands ---------------------------------------------------------------
def cmd_resolve_cycle(project: Project, args) -> int:
    c = project.resolve_cycle(args.name)
    data = {
        "cycle": c.name, "path": display(project.root, c.path), "prefix": c.prefix,
        "progress": display(project.root, c.progress_path), "fixes": display(project.root, c.fixes_path),
        "profile": display(project.root, c.profile_path), "profile_exists": c.profile_path.is_file(),
        "pitfalls": display(project.root, c.pitfalls_path), "pitfalls_exists": c.pitfalls_path.is_file(),
        "plan": c.meta.get("plan"), "archived": c.archived,
    }
    _emit(args, data, "\n".join(f"{k}: {v}" for k, v in data.items()))
    return EXIT_OK


def cmd_next(project: Project, args) -> int:
    cycle = project.resolve_cycle(args.cycle)
    fn = {"task": selection.next_task, "review": selection.next_review, "fix": selection.next_fix}[args.what]
    pick = fn(cycle)
    data = {"cycle": cycle.name, "kind": args.what, **pick.as_dict(project.root)}
    _emit(args, data, _pick_text(project.root, f"next {args.what} ({cycle.name})", pick))
    return EXIT_OK if pick.item else EXIT_FAIL


def cmd_new_task(project: Project, args) -> int:
    cycle = project.resolve_cycle(args.cycle)
    phase = int(args.phase) if str(args.phase).isdigit() else args.phase
    item = ops.new_task(project, cycle, title=args.title, type_=args.type, phase=phase,
                        depends_on=_ids(args.depends_on), source_of_truth=args.source_of_truth, slug=args.slug)
    data = {"id": item.id, "path": display(project.root, item.path)}
    _emit(args, data, f"created {item.id}: {data['path']}")
    return EXIT_OK


def cmd_new_fix(project: Project, args) -> int:
    cycle = project.resolve_cycle(args.cycle)
    item = ops.new_fix(project, cycle, origin=args.origin, title=args.title, severity=args.severity,
                       depends_on=_ids(args.depends_on), slug=args.slug)
    data = {"id": item.id, "path": display(project.root, item.path)}
    _emit(args, data, f"created {item.id}: {data['path']}")
    return EXIT_OK


def _result_text(verb: str, res: dict) -> str:
    lines = [f"{verb} {res['id']}"]
    for key in ("done_on", "done_commit", "reviewed_on", "status"):
        if res.get(key):
            lines.append(f"  {key}: {res[key]}")
    if res.get("commit"):
        lines.append(f"  committed {res['commit']}: {res['message']}")
    else:
        lines.append("  files written, not committed: " + ", ".join(res["files"]))
    return "\n".join(lines)


def cmd_close(project: Project, args) -> int:
    cycle, item = _item(project, args, args.id)
    res = ops.close(project, cycle, item, sha=args.sha, commit=not args.no_commit, force=args.force)
    _emit(args, res, _result_text("closed", res))
    return EXIT_OK


def cmd_mark(project: Project, args) -> int:
    cycle, item = _item(project, args, args.id)
    res = ops.mark(project, cycle, item, args.status, reason=args.reason or "", commit=args.commit)
    _emit(args, res, _result_text(f"marked {args.status}", res))
    return EXIT_OK


def cmd_mark_reviewed(project: Project, args) -> int:
    cycle, item = _item(project, args, args.id)
    res = ops.mark_reviewed(project, cycle, item, fixes=_ids(args.fixes), commit=not args.no_commit,
                            force=args.force)
    _emit(args, res, _result_text("reviewed", res))
    return EXIT_OK


def cmd_mark_stale(project: Project, args) -> int:
    cycle, item = _item(project, args, args.id)
    res = ops.mark_stale(project, cycle, item, reason=args.reason, commit=not args.no_commit)
    _emit(args, res, _result_text("stale", res))
    return EXIT_OK


def _target_cycles(project: Project, args) -> list:
    if getattr(args, "all", False) or (not args.cycle and len(project.live_cycles()) != 1
                                       and not project.cfg["paths"]["default_cycle"]):
        return project.live_cycles()
    return [project.resolve_cycle(args.cycle)]


def cmd_sync(project: Project, args) -> int:
    changed = []
    for c in _target_cycles(project, args):
        changed += views.sync(project, c)
    data = {"changed": [display(project.root, p) for p in changed]}
    _emit(args, data, "\n".join(f"synced {p}" for p in data["changed"]) or "views already in sync")
    return EXIT_OK


def cmd_check(project: Project, args) -> int:
    cycles = _target_cycles(project, args)
    findings = checkmod.run(project, cycles, quick=args.quick)
    errors = [f for f in findings if f.level == "error"]
    data = {"cycles": [c.name for c in cycles], "errors": len(errors),
            "warnings": len(findings) - len(errors), "findings": [f.__dict__ for f in findings]}
    tail = f"check: {len(errors)} error(s), {len(findings) - len(errors)} warning(s) in {len(cycles)} cycle(s)"
    _emit(args, data, "\n".join([*(str(f) for f in findings), tail]))
    return EXIT_FAIL if errors else EXIT_OK


def cmd_status(project: Project, args) -> int:
    cycles = _target_cycles(project, args)
    age = int(project.cfg["status"]["review_age_days"])
    out, texts = [], []
    for c in cycles:
        s = selection.summary(c, review_age_days=age)
        for key in ("next_task", "next_review", "next_fix"):
            s[key] = s[key].as_dict(project.root)
        out.append(s)
        t = s["tasks"]
        fx = s["open_fixes"]
        texts.append("\n".join([
            f"cycle {c.name} [{c.prefix or 'no prefix'}] — {display(project.root, c.path)}",
            f"  tasks: {t['done']} done, {t['in-progress']} in-progress, {t['pending']} pending, "
            f"{t['blocked']} blocked, {t['skipped']} skipped ({t['total']} total)",
            f"  review queue: {len(s['review_queue'])}"
            + (f" ({', '.join(s['review_queue'])})" if s["review_queue"] else "")
            + (f"; aged: {', '.join(s['review_aged'])}" if s["review_aged"] else ""),
            "  open fixes: " + ", ".join(f"{k} {v}" for k, v in fx.items()),
            f"  next task: {s['next_task']['id'] or '— ' + s['next_task']['reason']}",
            f"  next review: {s['next_review']['id'] or '—'}",
            f"  next fix: {s['next_fix']['id'] or '—'}",
            f"  suggested: /rite:{s['suggestion']['command']} — {s['suggestion']['reason']}",
        ]))
    if not cycles:
        texts.append(f"no live cycle under {display(project.root, project.cycles_root)} (run /rite:new-cycle)")
    _emit(args, {"cycles": out}, "\n\n".join(texts))
    return EXIT_OK


def cmd_guard(project: Project, args) -> int:
    from . import guard
    verdict = guard.classify(project.cfg, Path(args.path))
    _emit(args, verdict, verdict["message"] or "allowed")
    return EXIT_FAIL if verdict["blocked"] else EXIT_OK


# --- parser --------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--root", help="repository root (default: nearest folder with rite.toml)")
    common.add_argument("--json", action="store_true", help="machine-readable output")
    common.add_argument("--cycle", help="cycle name or folder (default: resolve-cycle rules)")

    p = argparse.ArgumentParser(prog="rite.py", description="Deterministic bookkeeping for the Rite workflow.")
    p.add_argument("--version", action="version", version=f"rite {__version__}")
    sub = p.add_subparsers(dest="command", required=True, metavar="COMMAND")

    s = sub.add_parser("resolve-cycle", parents=[common], help="print the cycle the rules select")
    s.add_argument("name", nargs="?")
    s.set_defaults(fn=cmd_resolve_cycle)

    s = sub.add_parser("next", parents=[common], help="select the next task, review or fix")
    s.add_argument("what", choices=["task", "review", "fix"])
    s.set_defaults(fn=cmd_next)

    s = sub.add_parser("new-task", parents=[common], help="create a task with an atomically allocated ID")
    s.add_argument("--title", required=True)
    s.add_argument("--type", required=True)
    s.add_argument("--phase", required=True)
    s.add_argument("--depends-on", action="append", help="IDs, comma-separated or repeated")
    s.add_argument("--source-of-truth", required=True, help="link to the plan section, e.g. /docs/plans/P.md#4.2")
    s.add_argument("--slug")
    s.set_defaults(fn=cmd_new_task)

    s = sub.add_parser("new-fix", parents=[common], help="create a fix with an atomically allocated ID")
    s.add_argument("--origin", required=True)
    s.add_argument("--title", required=True)
    s.add_argument("--severity", required=True, choices=list(config.SEVERITIES))
    s.add_argument("--depends-on", action="append")
    s.add_argument("--slug")
    s.set_defaults(fn=cmd_new_fix)

    s = sub.add_parser("close", parents=[common], help="record a finished item from its work commit")
    s.add_argument("id")
    s.add_argument("--sha", default="HEAD", help="the work commit (default HEAD)")
    s.add_argument("--no-commit", action="store_true")
    s.add_argument("--force", action="store_true")
    s.set_defaults(fn=cmd_close)

    s = sub.add_parser("mark", parents=[common], help="set pending/in-progress/blocked/skipped")
    s.add_argument("id")
    s.add_argument("status")
    s.add_argument("--reason")
    s.add_argument("--commit", action="store_true")
    s.set_defaults(fn=cmd_mark)

    s = sub.add_parser("mark-reviewed", parents=[common], help="record a review (and the fixes it opened)")
    s.add_argument("id")
    s.add_argument("--fixes", action="append", help="fix IDs opened by this review")
    s.add_argument("--no-commit", action="store_true")
    s.add_argument("--force", action="store_true")
    s.set_defaults(fn=cmd_mark_reviewed)

    s = sub.add_parser("mark-stale", parents=[common], help="close a fix whose symptom no longer reproduces")
    s.add_argument("id")
    s.add_argument("--reason", required=True)
    s.add_argument("--no-commit", action="store_true")
    s.set_defaults(fn=cmd_mark_stale)

    s = sub.add_parser("sync", parents=[common], help="regenerate progress/fixes tables from frontmatter")
    s.add_argument("--all", action="store_true")
    s.set_defaults(fn=cmd_sync)

    s = sub.add_parser("check", parents=[common], help="validate items, links, views and profile")
    s.add_argument("--all", action="store_true")
    s.add_argument("--quick", action="store_true", help="skip git, link and profile checks")
    s.set_defaults(fn=cmd_check)

    s = sub.add_parser("status", parents=[common], help="summarise cycles and suggest the next command")
    s.add_argument("--all", action="store_true")
    s.set_defaults(fn=cmd_status)

    s = sub.add_parser("guard", parents=[common], help="is this path read-only or generated?")
    s.add_argument("path")
    s.set_defaults(fn=cmd_guard)
    return p


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    try:
        project = _project(args)
        return args.fn(project, args)
    except config.NoConfig as exc:
        print(f"rite: {exc}", file=sys.stderr)
        return EXIT_NO_CONFIG
    except (config.ConfigError, RiteError, GitError, ValueError) as exc:
        print(f"rite: {exc}", file=sys.stderr)
        return EXIT_FAIL
