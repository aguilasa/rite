"""Command-line interface. Every subcommand prints text, or JSON with --json."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__, check as checkmod, config, ops, selection, views
from .gitutil import GitError
from .model import Project, RiteError, display, make_link

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


def cmd_commit_new(project: Project, args) -> int:
    cycle, item = _item(project, args, args.id)
    res = ops.commit_new(project, cycle, item)
    _emit(args, res, _result_text("opened", res))
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


def cmd_batch_plan(project: Project, args) -> int:
    from . import batch
    cycle = project.resolve_cycle(args.cycle)
    tokens = _ids(args.targets)
    if tokens == ["all"]:
        if args.kind != "fix":
            raise RiteError("'all' is only for fixes; a task batch takes a number (default 2)")
        tokens = [str(max(len(selection.open_fixes(cycle)), 1))]
    count = int(tokens[0]) if len(tokens) == 1 and tokens[0].isdigit() else None
    ids = [] if count is not None else tokens
    if count is not None and count < 1:
        raise RiteError("batch size must be >= 1")
    items = batch.select(cycle, args.kind, count, ids)
    if not items:
        raise RiteError(f"no selectable {args.kind} in cycle {cycle.name} (see: rite.py next {args.kind})")
    data = batch.plan(project, cycle, items)
    _emit(args, data, batch.render_text(data))
    return EXIT_OK


def cmd_new_cycle(project: Project, args) -> int:
    from . import lifecycle
    res = lifecycle.new_cycle(project, args.name, args.prefix, plan=args.plan, commit=args.commit)
    lines = [f"created cycle {res['cycle']} [{res['prefix']}] at {res['path']}"]
    lines += [f"  {p}" for p in res["created"]]
    if res["commit"]:
        lines.append(f"  committed {res['commit']}")
    text = "\n".join(lines)
    _emit(args, res, text)
    return EXIT_OK


def cmd_archive(project: Project, args) -> int:
    from . import lifecycle
    cycle = project.resolve_cycle(args.name)
    res = lifecycle.archive(project, cycle, commit=not args.no_commit, dry_run=args.dry_run)
    if res["blockers"]:
        lines = [f"cycle {res['cycle']} cannot close:"] + [f"  - {b}" for b in res["blockers"]]
    elif args.dry_run:
        lines = [f"cycle {res['cycle']} can close: {res['from']} -> {res['to']}"]
    else:
        lines = [f"archived {res['cycle']}: {res['from']} -> {res['to']}"]
        if res["rewritten"]:
            lines.append(f"  links rewritten in: {', '.join(res['rewritten'])}")
        if res["commit"]:
            lines.append(f"  committed {res['commit']}")
    text = "\n".join(lines)
    _emit(args, res, text)
    return EXIT_FAIL if res["blockers"] else EXIT_OK


def cmd_anchors(project: Project, args) -> int:
    from . import markdown
    path = Path(args.file)
    path = path if path.is_absolute() else project.root / path
    if not path.is_file():
        raise RiteError(f"{args.file} not found")
    # relative links are written from an item file, i.e. from the cycle folder
    base = project.resolve_cycle(args.cycle).path / "item.md" \
        if project.cfg.link_style == "relative" else project.root / "item.md"
    link = make_link(project.root, base, path, project.cfg.link_style)
    rows = []
    for level, title, slug, number in markdown.heading_anchors(path.read_text(encoding="utf-8")):
        anchor = number or slug
        rows.append({"level": level, "title": title, "anchor": anchor, "slug": slug,
                     "source_of_truth": f"{link}#{anchor}"})
    _emit(args, {"file": display(project.root, path), "headings": rows},
          "\n".join(f"{'  ' * (r['level'] - 1)}{r['title']}  ->  {r['source_of_truth']}" for r in rows))
    return EXIT_OK


def cmd_stats(project: Project, args) -> int:
    from . import stats
    cycle = project.resolve_cycle(args.name)
    data = stats.cycle_stats(project, cycle)
    _emit(args, data, stats.render_text(data))
    return EXIT_OK


def cmd_relink(project: Project, args) -> int:
    from . import lifecycle
    cycles = _target_cycles(project, args)
    changes = lifecycle.relink(project, cycles, write=args.write)
    total = sum(c["links"] for c in changes)
    lines = [f"  {c['file']}: {c['links']} link(s)" for c in changes]
    head = f"{'rewrote' if args.write else 'would rewrite'} {total} link(s) in {len(changes)} file(s) " \
           f"to {project.cfg.link_style}"
    _emit(args, {"style": project.cfg.link_style, "changes": changes, "written": args.write},
          "\n".join([head, *lines] + ([] if args.write else ["dry run: pass --write"])))
    return EXIT_OK


def cmd_migrate(args) -> int:
    from . import migrate
    if args.source != "we2002":
        raise RiteError(f"unknown source {args.source!r}; supported: we2002")
    root = Path(args.root).resolve() if args.root else Path.cwd()
    report = migrate.migrate_we2002(root, write=args.write)
    r = report.as_dict()
    lines = [f"{'migrated' if args.write else 'would migrate'} {r['items']} items in {len(r['cycles'])} cycles:"]
    lines += [f"  {c}" for c in r["cycles"]]
    lines.append(f"files {'changed' if args.write else 'to change'}: {len(r['changed'])}")
    if r["approximated_commits"]:
        lines.append(f"done_commit approximated by the last commit touching the item file "
                     f"({len(r['approximated_commits'])}): " + ", ".join(r["approximated_commits"]))
    if r["unresolved_commits"]:
        lines.append(f"done items without a findable work commit ({len(r['unresolved_commits'])}): "
                     + ", ".join(r["unresolved_commits"]))
    lines += [f"warning: {w}" for w in r["warnings"]]
    if r["actions"]:
        lines.append(f"action required ({len(r['actions'])}):")
        lines += [f"  {a['item']} ({a['file']}): {a['action']}" for a in r["actions"]]
    if not args.write:
        lines.append("dry run: nothing written (pass --write, on a branch)")
    _emit(args, r, "\n".join(lines))
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

    s = sub.add_parser("commit-new", parents=[common], help="commit a new, filled-in item with the views")
    s.add_argument("id")
    s.set_defaults(fn=cmd_commit_new)

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

    s = sub.add_parser("batch-plan", parents=[common], help="inventory, conflict matrix and waves for a batch")
    s.add_argument("targets", nargs="*", help="a count (default 2), item IDs, or 'all' (fixes only)")
    s.add_argument("--kind", choices=["task", "fix"], default="task")
    s.set_defaults(fn=cmd_batch_plan)

    s = sub.add_parser("new-cycle", parents=[common], help="create a cycle folder, views, profile and pitfalls")
    s.add_argument("name")
    s.add_argument("--prefix", required=True)
    s.add_argument("--plan", help="plan file (repo-relative)")
    s.add_argument("--commit", action="store_true")
    s.set_defaults(fn=cmd_new_cycle)

    s = sub.add_parser("archive", parents=[common], help="check a cycle can close; move it to archive_dir")
    s.add_argument("name")
    s.add_argument("--dry-run", action="store_true", help="only report blockers")
    s.add_argument("--no-commit", action="store_true")
    s.set_defaults(fn=cmd_archive)

    s = sub.add_parser("anchors", parents=[common], help="list a document's headings as source_of_truth links")
    s.add_argument("file")
    s.set_defaults(fn=cmd_anchors)

    s = sub.add_parser("stats", parents=[common], help="numbers for a retro: tasks, fixes, review latency")
    s.add_argument("name")
    s.set_defaults(fn=cmd_stats)

    s = sub.add_parser("relink", parents=[common], help="rewrite links in cycle files to [paths].link_style")
    s.add_argument("--all", action="store_true")
    s.add_argument("--write", action="store_true", help="write changes (default: dry run)")
    s.set_defaults(fn=cmd_relink)

    s = sub.add_parser("migrate", parents=[common], help="adopt a legacy backlog in place (run on a branch)")
    s.add_argument("--from", dest="source", required=True, help="legacy format: we2002")
    s.add_argument("--write", action="store_true", help="write changes (default: dry run)")
    s.set_defaults(fn=cmd_migrate, needs_project=False)

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
        if getattr(args, "needs_project", True) is False:
            return args.fn(args)
        project = _project(args)
        return args.fn(project, args)
    except config.NoConfig as exc:
        print(f"rite: {exc}", file=sys.stderr)
        return EXIT_NO_CONFIG
    except (config.ConfigError, RiteError, GitError, ValueError) as exc:
        print(f"rite: {exc}", file=sys.stderr)
        return EXIT_FAIL
