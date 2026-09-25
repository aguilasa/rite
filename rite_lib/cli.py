"""Command-line interface. Every subcommand prints text, or JSON with --json."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__, check as checkmod, compose, config, ops, selection, views
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
    if not pick.item:
        return f"{label}: none — {pick.reason}"
    text = (f"{label}: {pick.item.id} — {pick.item.title}\n"
            f"  file: {display(root, pick.item.path)}\n  why: {pick.reason}")
    return text + (f"\n  blocked: {selection.until(pick.unblocked_by)}" if pick.unblocked_by else "")


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
        "plan": c.meta.get("plan"), "archived": c.archived, "ticket": c.ticket, "local": c.local,
        "commit": ops.commit_refs(project, c), "workspace": project.workspace,
        "repos": project.repos() if project.workspace else [],
    }
    _emit(args, data, "\n".join(f"{k}: {v}" for k, v in data.items()))
    return EXIT_OK


def cmd_commit_refs(project: Project, args) -> int:
    cycle, item = _item(project, args, args.id)
    data = {"id": item.id, "cycle": cycle.name, **ops.commit_refs(project, cycle, item)}
    lines = [f"repo: {data['repo']}"] if data["repo"] else []
    lines += [f"subject: {data['subject_template']}"] + [f"trailer: {t}" for t in data["trailers"]]
    if data["local"]:
        lines.append(f"local cycle {cycle.name}: no Refs to the item; never stage its documents")
    _emit(args, data, "\n".join(lines))
    return EXIT_OK


def cmd_begin(project: Project, args) -> int:
    data = compose.begin(project, kind=args.kind, cycle_name=args.cycle, item_id=args.id,
                         claim=not args.no_claim)
    item = data.get("item")
    if not item:
        _emit(args, data, f"no {args.kind} selectable in {data['cycle']}: {data['reason']}")
        return EXIT_FAIL
    lines = [f"{item['id']} — {item['title']} ({data['cycle']}; {data['reason']})",
             f"  file: {item['path']}" + (f"  repo: {item['repo']}" if item["repo"] else ""),
             f"  source_of_truth: {item['source_of_truth']}",
             f"  profile: {data['paths']['profile']}   pitfalls: {data['paths']['pitfalls']}",
             f"  commit: {data['commit']['subject_template']}"
             + ("".join(f" | {x}" for x in data["commit"]["trailers"])),
             f"  next: {data['next_step']}"]
    _emit(args, data, "\n".join(lines))
    return EXIT_OK


def cmd_context(project: Project, args) -> int:
    data = compose.context(project, item_id=args.id, cycle_name=args.cycle)
    _emit(args, data, compose.render_context(data))
    return EXIT_OK


def cmd_gates(project: Project, args) -> int:
    data = compose.gates(project, cycle_name=args.cycle, item_id=args.id, tail=args.tail)
    lines = [f"gates in {data['where']} ({data['count']}):"]
    for g in data["gates"]:
        lines.append(f"  {'pass' if g['passed'] else 'FAIL'}  {g['command']}")
        if g["output"].strip():
            lines += [f"    {line}" for line in g["output"].splitlines()[-args.tail:]]
    _emit(args, data, "\n".join(lines) if data["count"] else "no gate declared")
    return EXIT_OK if data["passed"] else EXIT_FAIL


def cmd_reproduce(project: Project, args) -> int:
    data = compose.reproduce(project, fix_id=args.id, cycle_name=args.cycle, all_open=args.all,
                             tail=args.tail, scratch=args.scratch)
    lines = []
    for fix in data["fixes"]:
        if fix["runnable"]:
            flag = ""
        elif fix["why"] == "no_section":
            near = "".join(f'; near: "{h}"' for h in fix.get("near", []))
            flag = (" (no section: looked for " + ", ".join(f'"{t}"' for t in fix["looked_for"])
                    + f" in {fix['path']}{near}; runnable false)")
        elif fix["blocked"]:
            unblock = fix["unblock"]
            flag = (f" (blocked; unblocked by `{fix['unblocked_by']}` -> exit {unblock['exit_code']})"
                    if unblock else " (blocked, with no unblocked_by: nothing re-checks it)")
        elif fix["why"] == "unterminated":
            flag = " (a heredoc is never closed, so nothing ran: runnable false)"
        else:
            flag = " (its section has no command: runnable false)"
        flag += f" (over {data['limit_kb']} KB: hand it to an agent)" if fix["over_limit"] else ""
        lines.append(f"{fix['id']}{flag}")
        if fix["blocked"] and fix["unblock"]:
            lines += [f"    {line}" for line in fix["unblock"]["output"].splitlines()]
        for run in fix["commands"]:
            lines.append(f"  $ {run['command']}  -> exit {run['exit_code']}")
            lines += [f"    {line}" for line in run["output"].splitlines()]
        if fix["recorded"]:
            lines.append("  recorded:")
            lines += [f"    {line}" for line in fix["recorded"]]
    _emit(args, data, "\n".join(lines) or "no open fix")
    return EXIT_OK if data["count"] else EXIT_FAIL


def cmd_sweep(project: Project, args) -> int:
    data = compose.sweep(project, terms=_ids(args.terms), cycle_name=args.cycle, item_id=args.id)
    lines = []
    for term, found in data["results"].items():
        lines.append(f"{term}: {len(found['hits'])} hit(s)" + (" (capped)" if found["capped"] else ""))
        lines += [f"  {h['file']}:{h['line']}: {h['text']}" for h in found["hits"]]
    _emit(args, data, "\n".join(lines) or "no mention found")
    return EXIT_OK


def cmd_finish(project: Project, args) -> int:
    data = compose.finish(project, item_id=args.id, cycle_name=args.cycle, sha=args.sha,
                          commit=not args.no_commit, no_repo=args.no_repo, reason=args.reason)
    closed = data["closed"]
    lines = [_result_text("closed", closed)]
    lines.append("  check: " + ("clean" if not data["check"]["errors"]
                                else f"{len(data['check']['errors'])} error(s)"))
    lines += [f"    {e}" for e in data["check"]["errors"]]
    nxt = data["next"]
    lines.append(f"  next {nxt['kind']}: {nxt['id'] or '— ' + nxt['reason']}")
    _emit(args, data, "\n".join(lines))
    return EXIT_FAIL if data["check"]["errors"] else EXIT_OK


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
                        depends_on=_ids(args.depends_on), source_of_truth=args.source_of_truth, slug=args.slug,
                        repo=args.repo)
    data = {"id": item.id, "path": display(project.root, item.path)}
    _emit(args, data, f"created {item.id}: {data['path']}")
    return EXIT_OK


def cmd_new_fix(project: Project, args) -> int:
    cycle = project.resolve_cycle(args.cycle)
    item = ops.new_fix(project, cycle, origin=args.origin, title=args.title, severity=args.severity,
                       depends_on=_ids(args.depends_on), slug=args.slug, repo=args.repo)
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
    elif res.get("local"):
        lines.append("  local cycle, files written (no bookkeeping commit): " + ", ".join(res["files"]))
    else:
        lines.append("  files written, not committed: " + ", ".join(res["files"]))
    return "\n".join(lines)


def cmd_close(project: Project, args) -> int:
    cycle, item = _item(project, args, args.id)
    res = ops.close(project, cycle, item, sha=args.sha, commit=not args.no_commit, force=args.force,
                    no_repo=args.no_repo, reason=args.reason)
    _emit(args, res, _result_text("closed", res))
    return EXIT_OK


def cmd_rebind(project: Project, args) -> int:
    cycle, item = _item(project, args, args.id)
    res = ops.rebind(project, cycle, item, sha=args.sha, commit=not args.no_commit)
    _emit(args, res, _result_text(f"rebound {res['old_commit']} ->", res))
    return EXIT_OK


def cmd_mark(project: Project, args) -> int:
    cycle, item = _item(project, args, args.id)
    res = ops.mark(project, cycle, item, args.status, reason=args.reason or "",
                   unblocked_by=args.unblocked_by or "", commit=args.commit)
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
        cycles = project.live_cycles()
    else:
        cycles = [project.resolve_cycle(args.cycle)]
    if getattr(args, "include_archived", False):
        cycles += [c for c in project.archived_cycles() if c.path not in {x.path for x in cycles}]
    return cycles


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
            "  open fixes: " + ", ".join(f"{k} {v}" for k, v in fx.items())
            + (f"; blocked: {s['open_fixes_blocked']} — {selection.until(s['blocked_fixes'])}"
               if s["blocked_fixes"] else ""),
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
        tokens = [str(max(sum(f.status != "blocked" for f in selection.open_fixes(cycle)), 1))]
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
    res = lifecycle.new_cycle(project, args.name, args.prefix, plan=args.plan, ticket=args.ticket,
                              local=args.local, commit=args.commit)
    lines = [f"created cycle {res['cycle']} [{res['prefix']}] at {res['path']}"
             + (f", ticket {res['ticket']}" if res["ticket"] else "") + (", local" if res["local"] else "")]
    lines += [f"  {p}" for p in res["created"]]
    if res["commit"]:
        lines.append(f"  committed {res['commit']}")
    for path, ignored in (res["ignored"] or {}).items():
        if not ignored:
            lines.append(f"  warning: {path} is not ignored by git; add it to .gitignore to keep it local")
    text = "\n".join(lines)
    _emit(args, res, text)
    return EXIT_OK


def cmd_publish(project: Project, args) -> int:
    from . import lifecycle
    res = lifecycle.publish(project, project.resolve_cycle(args.name))
    _emit(args, res, f"published cycle {res['cycle']}: committed {res['commit']} ({', '.join(res['files'])})")
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
        elif res.get("local"):
            lines.append("  local cycle: moved on disk, nothing committed")
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


def cmd_sections(project: Project, args) -> int:
    from . import sections
    cycles = project.all_cycles() if args.all else [project.resolve_cycle(args.cycle)]
    data = sections.detect(project, cycles)
    lines = [f"# proposed from {len(cycles)} cycle(s): {', '.join(data['cycles'])}", data["block"].rstrip()]
    if args.write:
        data["write"] = sections.write(project, data["keys"])
        written = data["write"]["written"]
        lines.append(f"wrote {', '.join(written)} to {data['write']['file']}" if written
                     else "nothing to write: every detected title is already configured")
    else:
        lines.append("dry run: nothing written (pass --write to merge the matched keys into rite.toml)")
    _emit(args, data, "\n".join(lines))
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


def cmd_tokens(args) -> int:
    """Thin on purpose: the measurement is tools/token_report.py, so the two cannot disagree."""
    tools = Path(__file__).resolve().parent.parent / "tools"
    if str(tools) not in sys.path:
        sys.path.insert(0, str(tools))
    import token_report
    argv = ["--dir", args.dir, "--top", str(args.top), "--tolerance", str(args.tolerance),
            "--cache-weight", str(args.cache_weight)]
    argv += ["--by", args.by]
    for flag in ("project", "since", "until", "markdown", "check"):
        value = getattr(args, flag)
        argv += [f"--{flag}", value] if value else []
    argv += [x for c in args.command or [] for x in ("--command", c)]
    argv += ["--latest"] if args.latest else []
    argv += ["--json"] if args.json else []
    argv += ["--suggest-limits"] if args.suggest_limits else []
    return token_report.main(argv)


def cmd_guard(project: Project, args) -> int:
    from . import guard
    verdict = guard.classify(project.cfg, Path(args.path))
    _emit(args, verdict, verdict["message"] or "allowed")
    return EXIT_FAIL if verdict["blocked"] else EXIT_OK


# --- parser --------------------------------------------------------------------
def _work_commit_args(s: argparse.ArgumentParser) -> None:
    """close and finish: the work commit, or --no-repo when the only artifact lives outside git."""
    s.add_argument("--sha", help="the work commit (default HEAD)")
    s.add_argument("--no-repo", action="store_true",
                   help=f"finished without a work commit (a document outside git); records done_commit: "
                        f"{config.NO_COMMIT}, needs --reason")
    s.add_argument("--reason", default="", help="with --no-repo: what was done and where")


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

    s = sub.add_parser("begin", parents=[common],
                       help="resolve cycle and item, take it, and return everything the work needs")
    s.add_argument("kind", choices=["task", "fix", "review"])
    s.add_argument("--id", help="work on this item instead of the selected one")
    s.add_argument("--no-claim", action="store_true",
                   help="resolve without taking the item: for a run that only plans")
    s.set_defaults(fn=cmd_begin)

    s = sub.add_parser("context", parents=[common],
                       help="the item, its plan section, the profile's rules and matching pitfalls")
    s.add_argument("id")
    s.set_defaults(fn=cmd_context)

    s = sub.add_parser("gates", parents=[common], help="run the global and profile gates")
    s.add_argument("--id", help="run them in this item's repository")
    s.add_argument("--tail", type=int, default=20, help="lines kept from a passing gate")
    s.set_defaults(fn=cmd_gates)

    s = sub.add_parser("reproduce", parents=[common],
                       help="run a fix's Evidence commands and report their output (never a verdict)")
    s.add_argument("id", nargs="?", help="the fix (or --all)")
    s.add_argument("--all", action="store_true", help="every open or blocked fix of the cycle, one after the other")
    s.add_argument("--kind", choices=("fix",), default="fix", help="only fixes carry evidence to reproduce")
    s.add_argument("--tail", type=int, default=20, help="lines kept from a command that exits 0")
    s.add_argument("--scratch", action="store_true", help="run in an exported copy of HEAD")
    s.set_defaults(fn=cmd_reproduce)

    s = sub.add_parser("sweep", parents=[common], help="find stale mentions of what an item changed")
    s.add_argument("--terms", action="append", required=True, help="comma-separated or repeated")
    s.add_argument("--id", help="skip this item's own file")
    s.set_defaults(fn=cmd_sweep)

    s = sub.add_parser("finish", parents=[common], help="close the item, check the cycle, pick the next")
    s.add_argument("id")
    _work_commit_args(s)
    s.add_argument("--no-commit", action="store_true")
    s.set_defaults(fn=cmd_finish)

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
    s.add_argument("--repo", help="workspace: folder of the git repository the work lands in")
    s.set_defaults(fn=cmd_new_task)

    s = sub.add_parser("new-fix", parents=[common], help="create a fix with an atomically allocated ID")
    s.add_argument("--origin", required=True)
    s.add_argument("--title", required=True)
    s.add_argument("--severity", required=True, choices=list(config.SEVERITIES))
    s.add_argument("--depends-on", action="append")
    s.add_argument("--slug")
    s.add_argument("--repo", help="workspace: repository of the fix (default: its origin's)")
    s.set_defaults(fn=cmd_new_fix)

    s = sub.add_parser("commit-new", parents=[common], help="commit a new, filled-in item with the views")
    s.add_argument("id")
    s.set_defaults(fn=cmd_commit_new)

    s = sub.add_parser("close", parents=[common], help="record a finished item from its work commit")
    s.add_argument("id")
    _work_commit_args(s)
    s.add_argument("--no-commit", action="store_true")
    s.add_argument("--force", action="store_true")
    s.set_defaults(fn=cmd_close)

    s = sub.add_parser("rebind", parents=[common],
                       help="point a closed item at its rewritten work commit (after squash/rebase)")
    s.add_argument("id")
    s.add_argument("--sha", required=True, help="the work commit as it is now")
    s.add_argument("--no-commit", action="store_true")
    s.set_defaults(fn=cmd_rebind)

    s = sub.add_parser("commit-refs", parents=[common],
                       help="subject template and trailers for an item's work commit")
    s.add_argument("id")
    s.set_defaults(fn=cmd_commit_refs)

    s = sub.add_parser("mark", parents=[common], help="set pending/in-progress/blocked/skipped")
    s.add_argument("id")
    s.add_argument("status")
    s.add_argument("--reason")
    s.add_argument("--unblocked-by", help="a blocked fix: the command that passes once it can go on")
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
    s.add_argument("--include-archived", action="store_true", help="also archived cycles")
    s.set_defaults(fn=cmd_sync)

    s = sub.add_parser("check", parents=[common], help="validate items, links, views and profile")
    s.add_argument("--all", action="store_true")
    s.add_argument("--include-archived", action="store_true", help="also archived cycles")
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
    s.add_argument("--ticket", help="external tracker key the cycle's commits carry, e.g. PROJ-123")
    s.add_argument("--local", action="store_true", help="documents stay out of git: no bookkeeping commits")
    s.add_argument("--commit", action="store_true")
    s.set_defaults(fn=cmd_new_cycle)

    s = sub.add_parser("publish", parents=[common], help="make a local cycle tracked and commit its documents")
    s.add_argument("name")
    s.set_defaults(fn=cmd_publish)

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
    s.add_argument("--include-archived", action="store_true", help="also archived cycles")
    s.add_argument("--write", action="store_true", help="write changes (default: dry run)")
    s.set_defaults(fn=cmd_relink)

    s = sub.add_parser("sections", parents=[common],
                       help="propose [sections] from the titles items and profiles already use")
    s.add_argument("--all", action="store_true", help="read every cycle, live and archived")
    s.add_argument("--write", action="store_true", help="merge the keys that matched into rite.toml")
    s.set_defaults(fn=cmd_sections)

    s = sub.add_parser("migrate", parents=[common], help="adopt a legacy backlog in place (run on a branch)")
    s.add_argument("--from", dest="source", required=True, help="legacy format: we2002")
    s.add_argument("--write", action="store_true", help="write changes (default: dry run)")
    s.set_defaults(fn=cmd_migrate, needs_project=False)

    s = sub.add_parser("tokens", parents=[common],
                       help="where the tokens went: per command, session, day, project or agent, from transcripts")
    s.add_argument("--dir", default=str(Path.home() / ".claude" / "projects"),
                   help="folder of Claude Code transcripts (default: ~/.claude/projects)")
    s.add_argument("--project", "--glob", dest="project",
                   help="only transcripts whose path matches this pattern")
    s.add_argument("--latest", action="store_true",
                   help="only the project folder written last among those matched: one run, not all")
    s.add_argument("--by", choices=("command", "session", "day", "project", "agent"), default="command",
                   help="what a row is (default: command)")
    s.add_argument("--since", help="only invocations from this day on (UTC, YYYY-MM-DD)")
    s.add_argument("--until", help="only invocations up to this day (UTC, inclusive)")
    s.add_argument("--command", action="append", help="only these commands (repeatable)")
    s.add_argument("--top", type=int, default=0, help="also list the N largest tool results")
    s.add_argument("--markdown", help="also write the report to this markdown file")
    s.add_argument("--check", help="baseline JSON to compare against (needs --by command)")
    s.add_argument("--tolerance", type=float, default=15.0, help="percent a metric may grow")
    s.add_argument("--cache-weight", type=float, default=0.1,
                   help="weight of a cache read in effective tokens (a ratio of rates, not a price)")
    s.add_argument("--suggest-limits", action="store_true",
                   help="suggest [limits].inline_triage_max_output_kb from this window's /rite:fix-all runs")
    s.set_defaults(fn=cmd_tokens, needs_project=False)

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
