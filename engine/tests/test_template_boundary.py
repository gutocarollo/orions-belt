from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]


class TemplateBoundaryTests(unittest.TestCase):
    def test_all_author_qa_files_are_nominally_excluded(self) -> None:
        config = (ROOT / "copier.yml").read_text(encoding="utf-8")
        qa_files = sorted((ROOT / "templates/tests").glob("test_*"))
        missing = [path.name for path in qa_files if f'"/tests/{path.name}"' not in config]
        self.assertFalse(missing, f"author QA would leak into rendered projects: {missing}")


if __name__ == "__main__":
    unittest.main()
