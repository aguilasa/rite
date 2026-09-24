"""Section titles from `[sections]`: a pt-BR backlog is read whole, and a missing title is reported.

Why: one English title (`Evidence`) turned the whole inline triage of a pt-BR repository off, and
nothing said so — every fix came back "no command"."""

import json
import unittest

from fixtures import Fixture

from rite_lib import config, sections
from rite_lib.model import Project


class PtBrBacklogTest(unittest.TestCase):
    def setUp(self):
        self.fx = Fixture("ptbr")
        self.root = self.fx.root
        self.toml = self.root / "rite.toml"

    def tearDown(self):
        self.fx.cleanup()

    def js(self, *args):
        code, out, err = self.fx.rite(*args, "--json")
        self.assertEqual(code, 0, err)
        return json.loads(out)

    def configure(self):
        return self.js("sections", "--cycle", "wte", "--write")

    # --- before: the 0.6.0 config misses the pt-BR titles, and says so -----------------------
    def test_a_missing_title_is_no_section_not_no_command(self):
        fixes = self.js("reproduce", "--all", "--cycle", "wte")["fixes"]
        self.assertEqual([(f["runnable"], f["why"]) for f in fixes], [(False, "no_section")] * 2)
        self.assertEqual(fixes[0]["looked_for"], ["Evidence", "Verification"])
        code, out, _ = self.fx.rite("reproduce", "CORR-WTE-001", "--cycle", "wte")
        self.assertIn('no section: looked for "Evidence", "Verification" in docs/tasks/wte/CORR-WTE-001.md', out)

    def test_check_warns_instead_of_staying_silent(self):
        found = self.js("check", "--cycle", "wte")
        self.assertEqual(found["errors"], 0, found)
        messages = [(f["path"], f["message"]) for f in found["findings"] if f["level"] == "warn"]
        self.assertIn("no section titled 'Gates'", messages[0][1])
        self.assertEqual([p for p, m in messages if "'Evidence' / 'Verification'" in m],
                         ["docs/tasks/wte/CORR-WTE-001.md", "docs/tasks/wte/CORR-WTE-002.md"])

    # --- rite sections -----------------------------------------------------------------------
    def test_sections_proposes_every_key_with_its_evidence(self):
        data = self.js("sections", "--cycle", "wte")
        keys = data["keys"]
        wanted = {"evidence": ["Evidência"], "verification": ["Verificação"], "files": ["Arquivos"],
                  "scope": ["Arquivos a criar ou modificar"],
                  "serialized_resources": ["Recursos serializados"],
                  "confirmed_decisions": ["Contexto essencial — decisões já confirmadas"],
                  "phase_checks": ["Verificações específicas por fase"],
                  # the configured title stays first; the other one the items use is added
                  "execution_log": ["Log de Execução", "Log de Execução *(preenchido após execução)*"]}
        for key, titles in wanted.items():
            self.assertTrue(keys[key]["confident"], key)
            self.assertEqual(keys[key]["titles"], titles, key)
        self.assertEqual(keys["evidence"]["evidence"][0]["example"], "docs/tasks/wte/CORR-WTE-001.md")
        self.assertIn('evidence = "Evidência"', data["block"])
        self.assertFalse(self.toml.read_text(encoding="utf-8").count("Evidência"), "a dry run writes nothing")

    def test_files_and_scope_may_share_a_title(self):
        for task in (self.root / "docs/tasks/wte").glob("0*.md"):
            text = task.read_text(encoding="utf-8").replace("## Arquivos a criar ou modificar", "## Arquivos")
            task.write_text(text, encoding="utf-8", newline="\n")
        keys = self.js("sections", "--cycle", "wte")["keys"]
        self.assertEqual((keys["files"]["titles"], keys["scope"]["titles"]), (["Arquivos"], ["Arquivos"]))

    def test_a_title_in_under_a_tenth_of_the_files_is_only_a_candidate(self):
        detector = sections.Detector(Project(config.load(self.root)), [])
        tally = detector.tallies["scope"]
        tally.files = 143
        tally.votes = {"Arquivos criados/modificados": [sections.Vote("Arquivos criados/modificados", "a.md")] * 2}
        tally.seen = {"Arquivos criados/modificados": 2}
        verdict = detector.verdict("scope")
        self.assertFalse(verdict["confident"])
        self.assertEqual([c["title"] for c in verdict["candidates"]], ["Arquivos criados/modificados"])

    def test_what_nothing_matches_reliably_comes_out_commented(self):
        data = self.js("sections", "--cycle", "wte")
        gates = data["keys"]["gates"]
        self.assertFalse(gates["confident"], "a table under the gates title is a candidate, never read")
        self.assertEqual([c["title"] for c in gates["candidates"]], ["Gates deste ciclo"])
        self.assertIn('# gates = "Gates"', data["block"])
        self.assertIn("a table of 2 command line(s)", data["block"])
        generated = data["keys"]["generated_artifacts"]
        self.assertFalse(generated["confident"])
        self.assertEqual([c["title"] for c in generated["candidates"]], ["Estrutura"])
        self.assertIn('# generated_artifacts = "Generated artifacts"', data["block"])
        self.assertIn('candidates: "Estrutura" (1)', data["block"])

    def test_write_merges_and_keeps_comments_and_order(self):
        before = self.toml.read_text(encoding="utf-8")
        written = self.configure()["write"]["written"]
        self.assertNotIn("generated_artifacts", written)
        after = self.toml.read_text(encoding="utf-8")
        self.assertIn("# os títulos do repositório\n", after)
        self.assertIn('execution_log = ["Log de Execução", "Log de Execução *(preenchido após execução)*"]'
                      "  # o log que o Rite escreve\n", after)
        self.assertIn('phase_label   = "Fase"\nevidence = "Evidência"\n', after)
        # nothing outside [sections] moved
        self.assertEqual(before.split("[sections]")[0], after.split("[sections]")[0])
        self.assertTrue(after.endswith('[vocab]\ntask_types = []\n'))
        cfg = config.load(self.root)
        self.assertEqual(cfg["sections"]["evidence"], "Evidência")
        self.assertEqual(cfg["sections"]["gates"], "Gates", "an unsure key is never written")
        again = self.js("sections", "--cycle", "wte", "--write")["write"]["written"]
        self.assertEqual(again, {}, "a second run has nothing left to add")

    # --- after: every reader finds the pt-BR sections -----------------------------------------
    def test_reproduce_finds_the_commands(self):
        self.configure()
        fixes = self.js("reproduce", "--all", "--cycle", "wte")["fixes"]
        self.assertEqual([(f["runnable"], f["why"], f["heading"]) for f in fixes],
                         [(True, "ok", "Evidência")] * 2)
        self.assertEqual(fixes[0]["commands"][0]["command"], "python -c \"print('quebrado 1')\"")
        self.assertEqual(fixes[0]["recorded"], ["quebrado 1"])

    def test_gates_read_the_bullets_under_the_configured_title(self):
        profile = self.root / "docs/prompts/perfil-wte.md"
        text = profile.read_text(encoding="utf-8")
        profile.write_text(text.replace("## Arquivos quentes", "- `python -c \"print('gate ok')\"`\n\n"
                                        "## Arquivos quentes"), encoding="utf-8", newline="\n")
        self.configure()
        self.assertEqual(config.load(self.root)["sections"]["gates"], "Gates deste ciclo")
        gates = self.js("gates", "--cycle", "wte")["gates"]
        self.assertEqual([g["command"] for g in gates], ["python -c \"print('gate ok')\""])

    def test_batch_plan_predicts_the_bare_paths(self):
        self.configure()
        items = self.js("batch-plan", "all", "--kind", "fix", "--cycle", "wte")["items"]
        self.assertEqual([i["files"] for i in items], [["src/tabela.py"], ["src/outra.py"]])
        self.assertIn("emulador", self.js("batch-plan", "all", "--kind", "fix", "--cycle", "wte")
                      ["serialized_resources"])
        tasks = self.js("batch-plan", "2", "--kind", "task", "--cycle", "wte")["items"]
        self.assertEqual([i["files"] for i in tasks], [["src/tabela.py"], ["src/outra.py"]])

    def test_context_brings_the_profile_sections(self):
        self.configure()
        names = [p["name"] for p in self.js("context", "WTE-TASK-01", "--cycle", "wte")["parts"]]
        self.assertIn("docs/prompts/perfil-wte.md § Contexto essencial — decisões já confirmadas", names)
        self.assertIn("docs/prompts/perfil-wte.md § Verificações específicas por fase (Fase 1)", names)

    def test_check_is_quiet_once_configured(self):
        self.configure()
        found = self.js("check", "--cycle", "wte")
        left = [f["message"] for f in found["findings"] if "no section titled" in f["message"]]
        # the gates title stays for a person to set: its table was not read as gates
        self.assertEqual(len(left), 1, left)
        self.assertIn("'Gates'", left[0])

    def test_the_log_goes_under_the_title_the_item_already_has(self):
        self.configure()
        self.js("mark", "CORR-WTE-001", "in-progress", "--reason", "espera a imagem", "--cycle", "wte")
        text = (self.root / "docs/tasks/wte/CORR-WTE-001.md").read_text(encoding="utf-8")
        self.assertEqual(text.count("## Log de Execução"), 1, text)
        self.assertIn("espera a imagem", text.split("## Log de Execução *(preenchido após execução)*")[1])


class DefaultsTest(unittest.TestCase):
    def test_no_sections_table_means_the_english_defaults(self):
        fx = Fixture("subfolder")
        try:
            project = Project(config.load(fx.root))
            self.assertEqual(project.section_titles("evidence"), ["Evidence"])
            self.assertEqual(project.section_title("gates"), "Gates")
        finally:
            fx.cleanup()

    def test_merge_creates_the_table_and_rewrites_a_multiline_array(self):
        self.assertEqual(sections.merge('[project]\nname = "x"\n', {"evidence": ["E"]}),
                         '[project]\nname = "x"\n\n[sections]\nevidence = "E"\n')
        text = '[sections]\nfiles = [\n  "A",\n  "B",\n]  # tail\nscope = "S"\n\n[commit]\nstyle = "free"\n'
        self.assertEqual(sections.merge(text, {"files": ["X", "Y"], "gates": ["G"]}),
                         '[sections]\nfiles = ["X", "Y"]  # tail\nscope = "S"\ngates = "G"\n\n'
                         '[commit]\nstyle = "free"\n')


if __name__ == "__main__":
    unittest.main()
