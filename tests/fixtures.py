"""Fixture repositories built on the fly (temp dir + git)."""

from __future__ import annotations

import contextlib
import io
import os
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from rite_lib import cli  # noqa: E402


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text).lstrip("\n"), encoding="utf-8", newline="\n")
    return path


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True).stdout


def rite(root: Path, *args: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main([*args, "--root", str(root)])
    return code, out.getvalue(), err.getvalue()


def task(item_id: str, title: str, *, phase=1, depends_on="[]", sot: str, type_="feature",
         status="pending", extra: str = "") -> str:
    return f"""\
---
id: {item_id}
title: "{title}"
type: {type_}
phase: {phase}
depends_on: {depends_on}
source_of_truth: "{sot}"
status: {status}
done_on: null
done_commit: null
reviewed_on: null
review_commit: null
{extra}---

# {item_id} — {title}

## Done criteria

- [ ] it works

"""


PLAN = """\
# Plan — alpha

## 1. Context

## 2. Harness

### 2.1 Card diff

### 2.2 Report

## 3. Closing
"""

PROFILE = """\
# Profile — {cycle}

## Confirmed decisions

## Phase-specific checks

### Phase 1 — build
- run the harness

### Phase 2 — close
- recount the numbers
"""


class Fixture:
    """A throw-away git repository laid out per ``layout``."""

    def __init__(self, layout: str):
        self._tmp = tempfile.TemporaryDirectory(prefix=f"rite-{layout}-")
        self.root = Path(self._tmp.name).resolve()
        self.layout = layout
        git(self.root, "init", "-q")
        git(self.root, "config", "user.name", "Rite Test")
        git(self.root, "config", "user.email", "rite@example.invalid")
        git(self.root, "config", "core.autocrlf", "false")
        git(self.root, "config", "commit.gpgsign", "false")
        getattr(self, f"_build_{layout.replace('-', '_')}")()
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "chore: fixture")

    def cleanup(self) -> None:
        with contextlib.suppress(PermissionError):
            self._tmp.cleanup()

    def rite(self, *args: str) -> tuple[int, str, str]:
        return rite(self.root, *args)

    def git(self, *args: str) -> str:
        return git(self.root, *args)

    def work_commit(self, rel: str, content: str, message: str) -> str:
        write(self.root / rel, content)
        self.git("add", "--", rel)
        self.git("commit", "-q", "-m", message)
        return self.git("rev-parse", "--short", "HEAD").strip()

    # --- layouts -----------------------------------------------------------
    def _build_subfolder(self) -> None:
        """Default layout: docs/rite/cycles/<cycle>/, root-absolute links."""
        r = self.root
        write(r / "rite.toml", """
            [project]
            name = "fixture-subfolder"
            [guards]
            read_only = ["vendor/**"]
            [[guards.generated]]
            paths = ["src/gen/**"]
            generator = "tools/gen.py"
            check = "python tools/gen.py --check"
            """)
        write(r / "docs/plans/PLAN-alpha.md", PLAN)
        write(r / "docs/rite/profiles/alpha.md", PROFILE.format(cycle="alpha"))
        cyc = r / "docs/rite/cycles/alpha"
        write(cyc / "progress.md", """
            ---
            cycle: alpha
            prefix: ALP
            plan: /docs/plans/PLAN-alpha.md
            ---

            # Progress — alpha

            Plan: [PLAN-alpha](/docs/plans/PLAN-alpha.md)

            <!-- rite:begin tasks -->
            <!-- rite:end -->
            """)
        write(cyc / "fixes.md", "# Fixes — alpha\n")
        write(cyc / "01-harness.md", task("ALP-TASK-01", "Harness", sot="/docs/plans/PLAN-alpha.md#2.1"))
        write(cyc / "02-report.md", task("ALP-TASK-02", "Report", depends_on="[ALP-TASK-01]",
                                         sot="/docs/plans/PLAN-alpha.md#22-report"))
        write(cyc / "03-close-phase.md", task("ALP-TASK-03", "Close phase", phase=2, type_="closing",
                                              depends_on="[ALP-TASK-02]", sot="/docs/plans/PLAN-alpha.md#3"))
        # a second live cycle with its own prefix
        write(r / "docs/rite/profiles/beta.md", PROFILE.format(cycle="beta"))
        write(r / "docs/rite/cycles/beta/progress.md", "---\ncycle: beta\nprefix: BET\n---\n\n# Progress — beta\n")
        write(r / "docs/rite/cycles/beta/fixes.md", "# Fixes — beta\n")
        write(r / "docs/rite/cycles/beta/01-other.md",
              task("BET-TASK-01", "Other", sot="/docs/plans/PLAN-alpha.md#1"))
        write(r / "src/app.py", "print('hi')\n")
        self._sync()

    def _build_flat(self) -> None:
        """cycles_root itself is the single cycle (no sub-folders)."""
        r = self.root
        write(r / "rite.toml", """
            [paths]
            cycles_root = "docs/tasks"
            archive_dir = "docs/tasks/archive"
            profiles_dir = "docs/profiles"
            """)
        write(r / "docs/plans/PLAN-alpha.md", PLAN)
        write(r / "docs/profiles/tasks.md", PROFILE.format(cycle="tasks"))
        write(r / "docs/tasks/progress.md", "---\nprefix: FLT\n---\n\n# Progress\n")
        write(r / "docs/tasks/01-first.md", task("FLT-TASK-01", "First", sot="/docs/plans/PLAN-alpha.md#2.1"))
        write(r / "docs/tasks/02-second.md", task("FLT-TASK-02", "Second", depends_on="[FLT-TASK-01]",
                                                  sot="/docs/plans/PLAN-alpha.md#2.2"))
        self._sync()

    def _build_legacy(self) -> None:
        """WE2002-style: pt-BR file names, CORR ids, relative links, profiles in docs/prompts."""
        r = self.root
        write(r / "rite.toml", """
            [project]
            docs_language = "pt-BR"
            [paths]
            cycles_root = "docs/tasks"
            archive_dir = "docs/tasks/concluidos"
            profiles_dir = "docs/prompts"
            plans_dir = "docs"
            link_style = "relative"
            [naming]
            fix_id = "CORR-{prefix}-{n:03}"
            progress_file = "progresso.md"
            fixes_file = "correcoes-progresso.md"
            profile_file = "perfil-{cycle}.md"
            pitfalls_file = "perfil-{cycle}.armadilhas.md"
            [sections]
            execution_log = "Log de Execução"
            phase_checks = "Verificações por fase"
            [guards]
            read_only = ["roms/**"]
            read_only_reason = "ROMs originais nunca são alteradas"
            [vocab]
            task_types = []
            """)
        write(r / "docs/PLAN-WTE.md", "# Plano\n\n## 1. Contexto\n\n## 2. Extração\n\n### 2.1 Tabelas\n")
        write(r / "docs/prompts/perfil-wte.md",
              "# Perfil — wte\n\n## Verificações por fase\n\n### Phase 1\n- medir\n")
        cyc = r / "docs/tasks/wte"
        write(cyc / "progresso.md", "---\ncycle: wte\nprefix: WTE\n---\n\n# Progresso — wte\n")
        write(cyc / "01-extrair-tabelas.md",
              task("WTE-TASK-01", "Extrair tabelas", sot="../../PLAN-WTE.md#2.1", type_="extração"))
        write(cyc / "02-validar.md", task("WTE-TASK-02", "Validar", depends_on="[WTE-TASK-01]",
                                          sot="../../PLAN-WTE.md#2-extração", type_="verificação"))
        write(r / "roms/original.bin", "binary\n")
        self._sync()

    def _sync(self) -> None:
        code, out, err = rite(self.root, "sync", "--all")
        assert code == 0, err
