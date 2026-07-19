"""Regressão do MERGE do council (F1.5).

Reativação, com paths adaptados, de 5 dos 7 testes que ficaram
`@unittest.skip` em `engine/contract/tests/test_agent_contract.py` (F1) —
ver o `F15_REASON` lá. Agora que o merge existe de verdade em
`templates/.agents/skills/` (SKILL.md do council + adversarial-review) e
`templates/{% if use_codex %}.codex{% endif %}/agents/` (reviewer.toml),
estes testes rodam contra CONTEÚDO REAL, com as MESMAS asserções do par de
fontes original (`docs/planning/00-plano-consolidado.md` §3/§6 F1.5):

- `agent-swarm/codex/tests/test_agent_contract.py::test_plan_loop_requires_request_and_consumption_handoff`
- `::test_execution_loop_requires_request_and_consumption_handoff`
- `::test_final_negative_statuses_block_success_claims`
- `::test_required_sentinels_exist_once_per_loop_family`
- `::test_structured_schema_mirror_does_not_replace_markdown_sentinels`

NÃO reativados aqui (continuam fora de escopo, não fabricados):
- `test_readme_has_single_ordered_pipeline_with_real_loops` — precisa de um
  README com diagrama mermaid do pipeline PLAN->PLAN_REVIEW->EXECUTION->
  EXECUTION_REVIEW; isso pertence a um README do FRAMEWORK/case-study
  (escopo F7), não ao merge do SKILL.md em si.
- `test_historical_plan_doc_is_marked_non_canonical` — precisa de
  `docs/PLANO-SWARM.md` (doc histórico específico do agent-swarm original),
  não portado; não há equivalente no harness-wiki.

Vive em `templates/tests/` (não em `engine/contract/tests/`) de propósito:
`engine/contract/` é documentado como pacote PORTÁTIL/self-contained (seu
próprio README.md), e o conteúdo do council não pertence a ele — pertence
à árvore de templates que F3 parametriza. `templates/tests/` e
`templates/verification/` são excluídos do render real via `_exclude` do
copier.yml (QA do PRÓPRIO harness-wiki, não conteúdo a instalar num
projeto-alvo). Roda com:
`python3 -m unittest discover -s templates/tests -v` a partir da raiz do
harness-wiki, ou diretamente `python3 templates/tests/test_council_merge.py`.

F3 (restructure pós-review do coordenador, ver docs/planning/00-plano-
consolidado.md e o commit que corrigiu o achado arquitetural): a raiz do
`templates/` agora espelha DIRETAMENTE a raiz do projeto-alvo (sem wrapper
`claude/`/`codex/`/`shared/`) — `.claude` e `.codex` viram Jinja-no-NOME do
próprio diretório de topo (`{% if use_claude %}.claude{% endif %}`), não
mais uma subpasta de um wrapper.
"""

import pathlib
import re
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]  # templates/
CODEX_ROOT = ROOT / "{% if use_codex %}.codex{% endif %}"

# M-ALTA/H4: council + adversarial-review passaram a ser fonte única em
# .harness/skills-shared/ (mesmo mecanismo das outras 6 skills dual-runtime),
# incluída por wrappers de 1 linha em .claude/skills/ e .agents/skills/. Os
# testes de CONTEÚDO leem a FONTE (os wrappers não têm mais o texto -- são
# só {% raw %}{% include %}{% endraw %}); os testes de PARIDADE/gate
# simétrico (test_codex_parity.py / test_skill_runtime_parity.py) leem os
# dois wrappers via render real.
COUNCIL = ROOT / ".harness/skills-shared/delivery-council/SKILL.md.jinja"
ADVERSARIAL = ROOT / ".harness/skills-shared/adversarial-review/SKILL.md.jinja"
REVIEWER = CODEX_ROOT / "agents/{{ project_name }}-adversarial-reviewer.toml.jinja"


def read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def assert_contains_all(testcase: unittest.TestCase, text: str, values: tuple[str, ...], label: str) -> None:
    for value in values:
        testcase.assertIn(value, text, f"{label}: missing {value}")


def assert_payload_block(
    testcase: unittest.TestCase,
    text: str,
    marker: str,
    fields: tuple[str, ...],
    label: str,
) -> None:
    match = re.search(rf"{re.escape(marker)}:\n(?P<body>(?:- .+\n?)+)", text)
    testcase.assertIsNotNone(match, f"{label}: missing bullet payload under {marker}")
    assert_contains_all(testcase, match.group("body"), fields, f"{label}: {marker}")


class CouncilMergeRegressionTest(unittest.TestCase):
    def test_plan_loop_requires_request_and_consumption_handoff(self):
        for path in (COUNCIL, REVIEWER, ADVERSARIAL):
            text = read(path)
            self.assertIn("REPLAN-REQUEST", text, path)

        for path in (COUNCIL,):
            text = read(path)
            self.assertIn("REPLAN-CONSUMED", text, path)

        council = read(COUNCIL)
        reviewer = read(REVIEWER)
        self.assertIn("o Council deve replanejar", council)
        self.assertIn("Sem `REPLAN-REQUEST`", council)
        self.assertIn("REPLAN-REQUEST block is mandatory", reviewer)
        self.assertIn("reviewer does not perform the replan", reviewer)
        for path in (COUNCIL, REVIEWER, ADVERSARIAL):
            assert_payload_block(
                self,
                read(path),
                "REPLAN-REQUEST",
                ("gap:", "evidencia:", "alteracao-obrigatoria:"),
                f"{path} REPLAN-REQUEST payload",
            )
        assert_payload_block(
            self,
            read(COUNCIL),
            "REPLAN-CONSUMED",
            ("source-review-round:", "gaps-incorporados:", "plano-alterado-em:", "decisao-atualizada:"),
            f"{COUNCIL} REPLAN-CONSUMED payload",
        )

    def test_execution_loop_requires_request_and_consumption_handoff(self):
        for path in (COUNCIL, REVIEWER, ADVERSARIAL):
            text = read(path)
            self.assertIn("FIX-REQUEST", text, path)

        for path in (COUNCIL,):
            text = read(path)
            self.assertIn("FIX-CONSUMED", text, path)

        council = read(COUNCIL)
        reviewer = read(REVIEWER)
        self.assertIn("O reviewer nao corrige", council)
        self.assertIn("Sem `FIX-REQUEST`", council)
        self.assertIn("FIX-REQUEST block is mandatory", reviewer)
        self.assertIn("The reviewer does not fix", reviewer)
        for path in (COUNCIL, REVIEWER, ADVERSARIAL):
            assert_payload_block(
                self,
                read(path),
                "FIX-REQUEST",
                ("gap:", "evidencia:", "alteracao-obrigatoria:"),
                f"{path} FIX-REQUEST payload",
            )
        assert_payload_block(
            self,
            read(COUNCIL),
            "FIX-CONSUMED",
            ("source-review-round:", "gaps-corrigidos:", "arquivos-alterados:", "validacao-rodada:"),
            f"{COUNCIL} FIX-CONSUMED payload",
        )

    def test_final_negative_statuses_block_success_claims(self):
        council = read(COUNCIL)
        reviewer = read(REVIEWER)

        # F9-fixes: os caps de rodada viraram variáveis de config (antes eram
        # 2/3 hardcoded — variáveis-fachada com 0 consumidores, gap MEDIA do
        # review). O teste passa a assertar a forma TEMPLATE (o arquivo é lido
        # cru, não renderizado).
        self.assertIn(
            "PLAN-ADVERSARIAL-LOOP: {{ harness_plan_review_max }}/{{ harness_plan_review_max }}, status: PENDENTE",
            council,
        )
        self.assertIn("execucao NAO pode comecar", council)
        self.assertIn("must not proceed to execution", reviewer)

        self.assertIn(
            "ADVERSARIAL-LOOP: {{ harness_execution_review_max }}/{{ harness_execution_review_max }}, status: PENDENTE",
            council,
        )
        self.assertIn("nao declare `ADVERSARIAL-VERIFICATION: SATISFEITO`", council)
        self.assertIn("must not declare SATISFEITO", reviewer)

    def test_required_sentinels_exist_once_per_loop_family(self):
        """M2/H4 (auditoria adversarial): o nome do teste diz 'exist_once' mas a
        implementação original só fazia `assertIn` (existe pelo menos uma vez) --
        duplicar deliberadamente os 2 sentinels no SKILL.md.jinja do council
        mantinha esta suíte 7/7 verde (prova rodada nesta sessão: injetar uma
        2a cópia de cada bloco de sentinel e rodar `python3 -m unittest` antes
        deste fix confirma PASS espúrio). Fix: usar `str.count` de verdade e
        falhar se count != 1 -- "existe UMA vez", não "existe"."""
        council = read(COUNCIL)
        reviewer = read(REVIEWER)
        adversarial = read(ADVERSARIAL)

        for label, text in (("council", council), ("reviewer", reviewer), ("adversarial", adversarial)):
            plan_count = text.count("PLAN-ADVERSARIAL-VERIFICATION: SATISFEITO | REPLANEJAR | SABATINAR | BLOQUEADO")
            self.assertEqual(
                plan_count, 1,
                f"{label}: sentinel PLAN-ADVERSARIAL-VERIFICATION apareceu {plan_count}x (esperado exatamente 1)",
            )
            exec_count = text.count("ADVERSARIAL-VERIFICATION: SATISFEITO | CORRIGIR | BLOQUEADO")
            self.assertEqual(
                exec_count, 1,
                f"{label}: sentinel ADVERSARIAL-VERIFICATION apareceu {exec_count}x (esperado exatamente 1)",
            )

        plan_loop_count = len(
            re.findall(r"PLAN-ADVERSARIAL-LOOP: <rodadas>/\{\{ harness_plan_review_max \}\}", council)
        )
        self.assertEqual(plan_loop_count, 1, f"council: PLAN-ADVERSARIAL-LOOP apareceu {plan_loop_count}x")
        exec_loop_count = len(
            re.findall(r"ADVERSARIAL-LOOP: <rodadas>/\{\{ harness_execution_review_max \}\}", council)
        )
        self.assertEqual(exec_loop_count, 1, f"council: ADVERSARIAL-LOOP apareceu {exec_loop_count}x")

    def test_structured_schema_mirror_does_not_replace_markdown_sentinels(self):
        adversarial = read(ADVERSARIAL)
        reviewer = read(REVIEWER)
        for text in (adversarial, reviewer):
            self.assertIn("schemas/plan-review-result.schema.json", text)
            self.assertIn("schemas/execution-review-result.schema.json", text)
        self.assertIn("nao substitui os\nsentinels Markdown", adversarial)
        self.assertIn("Markdown sentinels remain mandatory", reviewer)

    def test_council_cited_identically_in_claude_and_codex(self):
        """Gate explícito do plano F1.5: "council único citado idêntico em Claude e
        Codex". A skill em si é dual-runtime (mesmo arquivo .agents/skills/ serve os
        dois — não há cópia .claude/skills/ divergente nesta fase, F4 cuida da
        geração de superfícies). O que varia por runtime é o REVIEWER: Codex tem
        .codex/agents/*.toml; o .claude/agents/*.md equivalente é F4 (geradores
        multi-agente), não F1.5. Aqui provamos que a referência ao subagent
        '<project>-adversarial-reviewer' e ao padrão SendMessage/thread-continuation
        é a MESMA string nos dois lugares onde o Council invoca o reviewer."""
        council = read(COUNCIL)
        self.assertIn("Claude Code: Agent tool; Codex: custom agent thread", council)
        self.assertIn("Claude Code: SendMessage; Codex: mesma thread", council)

    def test_witness_and_negative_control_for_council_merge(self):
        """Prova end-to-end (não só leitura de texto): roda
        engine/contract/scripts/verify_witness.py --root templates contra o
        council-witness.json real (6 markers) e contra um witness sintético com
        marker inexistente (teste NEGATIVO — gate explícito do plano F1.5)."""
        import subprocess

        harness_wiki_root = ROOT.parent  # templates/ -> harness-wiki/
        verify_script = harness_wiki_root / "engine" / "contract" / "scripts" / "verify_witness.py"
        witness = ROOT / "verification" / "council-witness.json"

        result = subprocess.run(
            ["python3", str(verify_script), "--witness", str(witness), "--root", str(ROOT)],
            cwd=harness_wiki_root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("6/6 verified", result.stdout)

        import json
        import tempfile

        bad_witness = {
            "schema": "agent-swarm-witness/v1",
            "fixes": [
                {
                    "id": "BAD-COUNCIL-NEGATIVE",
                    "desc": "negative control — marker must not exist",
                    "file": ".harness/skills-shared/delivery-council/SKILL.md.jinja",
                    "marker": "THIS_MARKER_SHOULD_NOT_EXIST_IN_COUNCIL_MERGE",
                }
            ],
        }
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json") as handle:
            json.dump(bad_witness, handle)
            handle.flush()
            bad_result = subprocess.run(
                ["python3", str(verify_script), "--witness", handle.name, "--root", str(ROOT)],
                cwd=harness_wiki_root,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
        self.assertNotEqual(bad_result.returncode, 0)
        self.assertIn("marker missing", bad_result.stdout)


if __name__ == "__main__":
    unittest.main()
