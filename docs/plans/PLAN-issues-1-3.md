# Plano: resolver issues #1, #2, #3 (aguilasa/rite, v0.14.0)

## Context

Três issues abertas, todas vindas de uso real de `/rite:fix-all` em Windows/Git Bash:

- **#3** `commit-new` não faz push sob `[commit].push = "after-each-item"` e não diz nada; `finish` faz. Tree limpa + branch ahead of origin em silêncio.
- **#2** Evidence com path relativo que não existe (arquivo de scratch da sessão) sai com exit≠0 e parece `NOT REPRODUCED` — fix pode ser marcada stale indevidamente.
- **#1** `reproduce --all` ficou 31+ min sem emitir nada; mesmos comandos à mão ≈5 min. Sem deadline, sem saída parcial.

Decisões (confirmadas): #3 = push + campo `pushed`; #2 = classificar `missing_path` no CLI (+ aviso no `check`); #1 = deadline por comando com kill da árvore + progresso em stderr, stdout JSON inalterado.

Ordem: #3 (pequeno) → #2 → #1 (os dois tocam `_run_one`; #1 por último reescreve a execução). Um commit `fix(...)` por issue, com `Fixes #N`. Sem footer Co-Authored-By (memória do usuário).

---

## #3 — commit-new honra `[commit].push`

Arquivos: [rite_lib/compose.py](rite_lib/compose.py), [rite_lib/ops.py](rite_lib/ops.py), [rite_lib/cli.py](rite_lib/cli.py), [docs/CONFIG.md](docs/CONFIG.md), [parts/commit.md](parts/commit.md), [tests/test_cli.py](tests/test_cli.py).

1. `cmd_commit_new` (cli.py:239) passa a chamar nova `compose.commit_new(project, item_id, cycle)` que envolve `ops.commit_new` e, se houve `commit`, chama `_push_after_close(project, item, no_repo=True)` (compose.py:636) — só a raiz do bookkeeping (commit-new não tem work commit). Retorna `{..., "pushed": [...]}` (lista vazia quando política ≠ after-each-item ou ciclo local).
   - Renomear `_push_after_close` → `_push_after_commit` (docstring genérica) — usado por finish e commit-new.
2. Texto: extrair de `cmd_finish` a linha `pushed:/push failed:` para helper `_pushed_lines(data["pushed"])`, reusado em `cmd_commit_new`.
3. Docs: `docs/CONFIG.md:131` — "`rite finish` e `rite commit-new` rodam `git push`…". `parts/commit.md:10` idem ("`rite finish` and `rite commit-new` push: report a failed entry of their `pushed`…"). Regenerar `commands/*.md` com `python tools/build_commands.py`. Report de `_fix-all.body.md`/`_fix.body.md`/`_review.body.md` ("`pushed`, if any") — incluir pushes de commit-new onde o comando abre fixes.
4. Testes (padrão de `test_finish_pushes_when_configured`, test_cli.py:569): `test_commit_new_pushes_when_configured` (bare remote, log remoto mostra `chore(rite): open …`), `test_commit_new_reports_failed_push` (sem remote, `ok: false`, commit local existe), e `pushed == []` sob default.

## #2 — Evidence que cita path inexistente vira `missing_path`, nunca veredito

Arquivos: [rite_lib/compose.py](rite_lib/compose.py), [rite_lib/cli.py](rite_lib/cli.py), [rite_lib/check.py](rite_lib/check.py), [parts/evidence.md](parts/evidence.md), [commands/_fix-all.body.md](commands/_fix-all.body.md), [commands/_fix.body.md](commands/_fix.body.md), [agents/rite-reproducer.md](agents/rite-reproducer.md), [docs/COMMANDS.md](docs/COMMANDS.md), [tests/test_reproduce.py](tests/test_reproduce.py).

1. compose.py: regex `_MISSING_PATH` sobre a saída de comando com exit≠0, cobrindo as formas comuns: `X: No such file or directory`, `cannot access 'X'`, `can't open file 'X'` (python), `cannot open 'X'`, `ENOENT … 'X'` (node). Extrai os paths; mantém só os que de fato não existem relativos a `where` (evita falso positivo de `grep` que reporta arquivo ausente esperado… ainda assim só marca, não decide).
2. `_run_one` ganha `"missing_path": [paths]` (lista vazia se nada). Por fix, agregado `missing_path` = união; quando não vazio, `cannot_decide: true` ao lado de `shell_error`. Texto do CLI: ` (missing path: cost1.txt, …; cannot decide)` na linha do comando.
3. Regras: `parts/evidence.md:9` já diz "missing path → CANNOT RUN"; tornar mecânico: "`shell_error` or `missing_path` non-empty → CANNOT RUN". `_fix-all.body.md:23` residue inclui `missing_path`. `_fix.body.md:22` idem (escrever Evidence que roda da raiz do repo). `agents/rite-reproducer.md:33` cita o campo. Rebuild commands.
4. `rite check` (check.py `check_evidence_runs`, ~407): novo aviso para argumento relativo com cara de arquivo (tem extensão, sem `$`, `~`, `<`, sem `/` absoluto — reutiliza `_dynamic`) que não existe no repositório e não é criado por linha anterior (`>`/`tee`/`touch`); só antes de qualquer `cd`, mesmo padrão de `missing_scripts`. Mensagem: "`'Evidence' cita `cost1.txt`, que não está no repositório: Evidence roda na raiz do repositório`". Limitar a comandos de leitura conhecidos (`grep`, `cat`, `diff`, `head`, `tail`, `wc`, `cmp`) para evitar ruído.
5. Testes: fix com `grep x nope1.txt nope2.txt` ⇒ `missing_path == ["nope1.txt","nope2.txt"]`, `cannot_decide`; `grep x README` sem match (exit 1) ⇒ `missing_path == []`; check emite aviso para o primeiro e não para arquivo versionado. Atualizar `StaleRuleTest` (test_reproduce.py:287) para exigir menção a `missing_path` na regra.

## #1 — `reproduce` com deadline, sem pipe preso, progresso por fix

Arquivos: [rite_lib/compose.py](rite_lib/compose.py), [rite_lib/cli.py](rite_lib/cli.py), [rite_lib/config.py](rite_lib/config.py), [docs/CONFIG.md](docs/CONFIG.md), [docs/COMMANDS.md](docs/COMMANDS.md), [commands/_fix-all.body.md](commands/_fix-all.body.md), [tests/test_reproduce.py](tests/test_reproduce.py).

Causas prováveis (não diagnosticadas na issue), todas cobertas: (a) neto em background herda o pipe de stdout e `subprocess.run(capture_output=True)` espera EOF para sempre; (b) saída enorme acumulada em memória pelo próprio rite (CPU); (c) comando realmente travado. Hoje não há timeout em `_run_one` (compose.py:478).

1. **Saída em arquivo, não pipe**: `_run_one` escreve stdout+stderr em `tempfile.TemporaryFile` (mesmo handle p/ ambos), lê no fim só o necessário (tail, ou até o limite `inline_triage_max_output_kb` quando exit≠0 + marca truncado). Elimina (a) e (b).
2. **Deadline por comando**: `Popen` + `wait(timeout)`. Ao estourar, matar a árvore: POSIX `start_new_session=True` + `os.killpg(SIGKILL)`; Windows `CREATE_NEW_PROCESS_GROUP` + `taskkill /T /F /PID`. Resultado: `timed_out: true`, `exit_code: null`, `seconds`, e o output parcial. Fix com algum comando timed out ⇒ `cannot_decide: true` (mesmo canal do #2). Cada run ganha `seconds` sempre.
3. Config: `[limits].reproduce_timeout_s` (default 300; validado positivo como `inline_triage_max_output_kb`, ver test `test_the_limit_is_a_positive_number`); CLI `--timeout SECONDS` sobrepõe. Também aplica ao `unblocked_by`.
4. **Progresso em stderr**: `compose.reproduce(..., progress=callable|None)`; `cmd_reproduce` passa callback que imprime em stderr, ao fim de cada fix: `[2/4] CORR-TOOL-012  2 cmd  exit 0,1  41.2s` (ou `TIMEOUT after 300s: <cmd>`), flush imediato. stdout JSON inalterado ⇒ fix-all sem mudança de parse.
5. Docs: COMMANDS.md linha de `reproduce` (`--timeout`, `timed_out`, `seconds`, `missing_path`, `cannot_decide`, progresso em stderr); CONFIG.md `[limits]`; `_fix-all.body.md:16/23` — residue inclui `timed_out`/`cannot_decide`; sugerir rodar `reproduce --all` em background no Bash se o ciclo tem muitas fixes. Rebuild commands.
6. Testes: comando `sleep 5` com `--timeout 1` ⇒ `timed_out`, retorna em < ~3s; comando que deixa neto em background (`(sleep 30 &) ; echo ok`) retorna rápido com exit 0 (regressão do pipe); stderr contém uma linha de progresso por fix e stdout continua JSON válido; testes existentes de tail/over_limit continuam passando.

---

## Fechamento

- `CHANGELOG.md`: nova seção `[0.14.1]` (ou `[0.15.0]` se tratarmos `--timeout`/campos novos como Added) com Fixed #1/#2/#3. Release segue padrão `chore(release): X` existente — só se o usuário pedir.
- Responder/fechar issues via `Fixes #N` nos commits; push só se usuário pedir.

## Verificação

- `python -m unittest discover -s tests` (suite completa, inclui `test_build_commands` que exige commands/ regenerados e `test_examples`/e2e baselines).
- `python tools/build_commands.py --check`.
- Manual, no `examples/python-minimal`: fix com Evidence `grep x cost1.txt` ⇒ `rite reproduce <FIX> --json` mostra `missing_path`; `rite check` avisa; fix com `sleep 600` e `--timeout 2` ⇒ volta em ~2s com `timed_out`, linha em stderr; repo com bare remote + `push = "after-each-item"` ⇒ `rite commit-new <ID> --json` traz `pushed: [{ok: true}]` e `git status -sb` não mostra ahead.
