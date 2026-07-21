from pathlib import Path
import subprocess
import unittest

from engine.release_check import GATES


ROOT = Path(__file__).resolve().parents[2]


class DistributionBoundaryTests(unittest.TestCase):
    def test_release_gate_uses_existing_nonignored_provider_neutral_paths(self) -> None:
        provider_tokens = (".github", "bitbucket-pipelines", ".gitlab-ci", "jenkins")
        for gate in GATES:
            rendered = " ".join(gate.command).lower()
            self.assertFalse(
                any(token in rendered for token in provider_tokens),
                f"core gate {gate.name} depends on a hosted provider: {gate.command}",
            )
            for token in gate.command:
                if not token.endswith(".py") or "/" not in token:
                    continue
                path = ROOT / token
                self.assertTrue(path.is_file(), f"gate {gate.name} references missing {token}")
                ignored = subprocess.run(
                    ["git", "check-ignore", "-q", "--", token], cwd=ROOT, check=False
                )
                self.assertNotEqual(0, ignored.returncode, f"gate {gate.name} references ignored {token}")

    def test_hosted_ci_is_not_enabled_for_the_framework_repository(self) -> None:
        self.assertFalse((ROOT / ".github/workflows/release-check.yml").exists())

    def test_github_docs_adapter_is_explicitly_opt_in(self) -> None:
        config = (ROOT / "copier.yml").read_text(encoding="utf-8")
        block = config.split("use_github_ci:", 1)[1].split("\n\n", 1)[0]
        self.assertIn("default: false", block)
        adapter = ROOT / "templates/{% if use_github_ci %}.github{% endif %}/workflows/docs-integrity.yaml.jinja"
        self.assertTrue(adapter.is_file())

    def test_installer_provenance_test_uses_the_actual_source_remote(self) -> None:
        test = (ROOT / "templates/tests/test_harness_install_fail_closed.sh").read_text(encoding="utf-8")
        self.assertIn("EXPECTED_SOURCE=", test)
        self.assertNotIn("_src_path: '\\''https://github.com/", test)

    def test_canonical_docs_define_a_provider_agnostic_local_core(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        architecture = (ROOT / "docs/architecture/arquitetura-alvo.md").read_text(encoding="utf-8")
        self.assertIn("provider-agnostic", readme)
        self.assertIn("provider-agnostic", architecture)
        self.assertIn("no hosted CI is enabled by default", readme)
        self.assertNotIn("CI is the independent authority", readme)
        self.assertNotIn("`engine/release_check.py` + GitHub Actions", architecture)

    def test_proof_contract_does_not_promote_hosted_ci_to_authority(self) -> None:
        paths = (
            "templates/.harness/lib/proof_evidence.py",
            "templates/.harness/skills-shared/prova-de-conclusao/SKILL.en.md.jinja",
            "templates/.harness/skills-shared/prova-de-conclusao/SKILL.pt.md.jinja",
        )
        forbidden = ("CI remains the independent authority", "CI independente continua sendo a autoridade")
        for relative in paths:
            text = (ROOT / relative).read_text(encoding="utf-8")
            self.assertIn("adapter opcional" if relative.endswith("pt.md.jinja") else "optional adapter", text)
            self.assertFalse(any(token in text for token in forbidden), relative)


if __name__ == "__main__":
    unittest.main()
