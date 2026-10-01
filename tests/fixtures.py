"""Fixture repositories built on the fly (temp dir + git)."""

from __future__ import annotations

import contextlib
import io
import json
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


# --- the JSON state, read and written the way a hand edit would ---------------------
def _locate(path: Path) -> tuple[Path, dict, dict | None]:
    """(JSON file, its document, the entry) holding the fields of ``path``: an item's markdown file
    (its entry), or a progress file (entry None: the cycle's meta)."""
    path = path.resolve()
    for base in path.parents:
        for name in ("progress.json", "fixes.json"):
            state_file = base / name
            if not state_file.is_file():
                continue
            data = json.loads(state_file.read_text(encoding="utf-8"))
            for key in ("tasks", "fixes"):
                for entry in data.get(key) or []:
                    if (base / entry["file"]).resolve() == path:
                        return state_file, data, entry
        if (base / "progress.json").is_file() and base == path.parent:
            state_file = base / "progress.json"
            return state_file, json.loads(state_file.read_text(encoding="utf-8")), None
    raise AssertionError(f"no JSON state holds {path}")


def fields(path: Path) -> dict:
    """The fields of an item (by its markdown file) or of a cycle (by its progress file)."""
    _, data, entry = _locate(path)
    if entry is None:
        return {k: v for k, v in data.items() if k not in ("schema", "tasks")}
    return {k: v for k, v in entry.items() if k != "file"}


def set_fields(path: Path, updates: dict) -> None:
    """Edit the JSON by hand — what the guard refuses a model, used to put a repository in a state."""
    from rite_lib import state
    state_file, data, entry = _locate(path)
    if entry is None:
        tasks = data.pop("tasks", [])
        data.update(updates)
        data["tasks"] = tasks
    else:
        entry.update(updates)
    state_file.write_text(state.dumps(data), encoding="utf-8", newline="\n")


def add_item(path: Path, text: str) -> Path:
    """Write an item the pre-JSON way (``text`` with its frontmatter) into a JSON cycle: the frontmatter
    becomes the item's entry and the file keeps its id — as if `new-task`/`new-fix` had made it."""
    from rite_lib import frontmatter, state
    text = textwrap.dedent(text).lstrip("\n")
    meta, body = frontmatter.parse(text)
    base = next(b for b in path.resolve().parents if (b / "progress.json").is_file())
    kind = "fixes" if "origin" in meta else "tasks"
    state_file = base / ("fixes.json" if kind == "fixes" else "progress.json")
    data = json.loads(state_file.read_text(encoding="utf-8")) if state_file.is_file() \
        else {"schema": 1, "fixes": []}
    entry = {"id": meta["id"], "file": path.resolve().relative_to(base).as_posix(),
             **{k: v for k, v in meta.items() if k != "id"}}
    data.setdefault(kind, []).append(entry)
    state_file.write_text(state.dumps(data), encoding="utf-8", newline="\n")
    return write(path, f"---\nid: {meta['id']}\n---\n{body}")


def remove_item(path: Path) -> None:
    """Delete an item: its markdown file and its JSON entry."""
    from rite_lib import state
    state_file, data, entry = _locate(path)
    for key in ("tasks", "fixes"):
        if key in data:
            data[key] = [e for e in data[key] if e is not entry]
    state_file.write_text(state.dumps(data), encoding="utf-8", newline="\n")
    path.unlink()


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

    def _build_ptbr(self) -> None:
        """A pt-BR backlog on a 0.6.0 rite.toml: its sections are titled in Portuguese, and
        `[sections]` names only the three keys 0.6.0 had — Evidence, Gates, Files are not found."""
        r = self.root
        write(r / "rite.toml", """
            [project]
            docs_language = "pt-BR"
            [paths]
            cycles_root = "docs/tasks"
            profiles_dir = "docs/prompts"
            plans_dir = "docs"
            [naming]
            fix_id = "CORR-{prefix}-{n:03}"
            progress_file = "progresso.md"
            fixes_file = "correcoes-progresso.md"
            profile_file = "perfil-{cycle}.md"
            pitfalls_file = "perfil-{cycle}.armadilhas.md"

            [sections]
            # os títulos do repositório
            execution_log = "Log de Execução"   # o log que o Rite escreve
            phase_checks  = "Verificações específicas por fase"
            phase_label   = "Fase"

            [vocab]
            task_types = []
            """)
        write(r / "docs/PLAN-WTE.md", "# Plano\n\n## 1. Contexto\n\n## 2. Extração\n")
        write(r / "docs/prompts/perfil-wte.md", """
            # Perfil — wte

            ## Contexto essencial — decisões já confirmadas

            - **v1 só lê.** Decisão de 2026-09-13.

            ## Estrutura

            A árvore de `src/` e o que cada módulo faz.

            ## Gates deste ciclo

            | alvo | precisa | como se roda | desde |
            | --- | --- | --- | --- |
            | `selftest` | nada | `python -c "print('gate ok')"` | WTE-TASK-01 |
            | `tabela` | `IMAGEM` | `python -c "print('tabela ok')"` | WTE-TASK-02 |

            ## Arquivos quentes deste ciclo

            - `src/tabela.py`

            ## Recursos serializados

            - `emulador` — uma instância por vez

            ## Verificações específicas por fase

            ### Fase 1
            - medir
            """)
        cyc = r / "docs/tasks/wte"
        write(cyc / "progresso.md",
              "---\ncycle: wte\nprefix: WTE\nplan: /docs/PLAN-WTE.md\n---\n\n# Progresso — wte\n")
        write(cyc / "correcoes-progresso.md", "# Correções — wte\n")
        for n, (slug, target) in enumerate((("extrair", "src/tabela.py"), ("validar", "src/outra.py")), start=1):
            write(cyc / f"0{n}-{slug}.md",
                  task(f"WTE-TASK-0{n}", slug.capitalize(), sot="/docs/PLAN-WTE.md#2-extração")
                  + "## Arquivos a criar ou modificar\n\n| Arquivo | Ação |\n|---|---|\n"
                  f"| `{target}` | modificar |\n\n## Log de Execução\n\n- **Criada** (2026-09-20)\n")
        for n, target in ((1, "src/tabela.py"), (2, "src/outra.py")):
            write(cyc / f"CORR-WTE-00{n}.md", f"""\
---
id: CORR-WTE-00{n}
title: "Quebra {n}"
origin: WTE-TASK-0{n}
severity: medium
status: pending
depends_on: []
done_on: null
done_commit: null
---

# CORR-WTE-00{n} — Quebra {n}

## Problema identificado

A leitura de `{target}` quebra.

## Evidência

```text
$ python -c "print('quebrado {n}')"
quebrado {n}
```

## Correção

Consertar `{target}`.

## Arquivos

- {target} (a leitura)

## Verificação

- `python -c "print({n})"` fica verde

## Log de Execução *(preenchido após execução)*
""")
        write(r / "src/tabela.py", "print('tabela')\n")
        write(r / "src/outra.py", "print('outra')\n")
        self._sync()

    def _sync(self) -> None:
        # layouts are written the way Rite <= 0.13 kept them (state in frontmatter); the migration
        # brings them to the JSON state, so every fixture also exercises it
        code, out, err = rite(self.root, "migrate", "--from", "frontmatter", "--write")
        assert code == 0, err
        code, out, err = rite(self.root, "sync", "--all")
        assert code == 0, err
