import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from epsotests.static_catalog import generate_static_catalog


class StaticCatalogTests(unittest.TestCase):
    root = Path(__file__).parents[1]

    def test_committed_catalog_is_reproducible_and_covers_all_families(self):
        path = self.root / "epsotests" / "web" / "catalog.json"
        actual = json.loads(path.read_text(encoding="utf-8"))
        expected = generate_static_catalog()
        self.assertEqual(actual, expected)
        self.assertEqual(actual["version"], 1)
        self.assertEqual(actual["seeds"], [42, 43])
        self.assertEqual(len(actual["questions"]), 336)
        self.assertEqual(
            {entry["family"] for entry in actual["questions"]},
            {"visual", "numerical", "verbal"},
        )
        self.assertEqual(
            len({entry["id"] for entry in actual["questions"]}),
            len(actual["questions"]),
        )

    def test_catalog_entries_record_variation_provenance(self):
        catalog = json.loads(
            (self.root / "epsotests" / "web" / "catalog.json").read_text(
                encoding="utf-8"
            )
        )
        required = {
            "id",
            "questionId",
            "methodSignature",
            "answerSignature",
            "explanationSignature",
            "difficulty",
            "profile",
        }
        for entry in catalog["questions"]:
            with self.subTest(entry=entry["id"]):
                self.assertTrue(required <= entry.keys())
                self.assertTrue(entry["methodSignature"])
                self.assertTrue(entry["answerSignature"])
                self.assertTrue(entry["explanationSignature"])
                self.assertEqual(entry["questionId"], entry["id"])
                self.assertTrue(entry["generatorQuestionId"])
        for family in ("visual", "numerical", "verbal"):
            entries = [item for item in catalog["questions"] if item["family"] == family]
            self.assertGreater(len({item["methodSignature"] for item in entries}), 1)

    def test_catalog_public_questions_pair_with_complete_solutions(self):
        catalog = json.loads(
            (self.root / "epsotests" / "web" / "catalog.json").read_text(
                encoding="utf-8"
            )
        )
        for entry in catalog["questions"]:
            with self.subTest(entry=entry["id"]):
                question = entry["question"]
                solution = entry["solution"]
                self.assertEqual(question["metadata"]["seed"], entry["seed"])
                self.assertEqual(question["metadata"]["examProfile"], entry["profile"])
                self.assertEqual(len(question["options"]), question["optionCount"])
                self.assertEqual(
                    {option["id"] for option in question["options"]},
                    set("ABCDE"[: question["optionCount"]]),
                )
                self.assertNotIn("correctOption", question)
                self.assertNotIn("explanation", question)
                self.assertEqual(solution["optionCount"], question["optionCount"])
                self.assertIn(
                    solution["correctOption"],
                    {option["id"] for option in question["options"]},
                )
                self.assertTrue(solution["explanation"])
                self.assertFalse(question["actions"]["explainLogic"].get("result"))

    def test_pages_build_uses_relative_assets_and_static_mode(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "site"
            subprocess.run(
                [sys.executable, "scripts/build_pages.py", "--output", str(output)],
                cwd=self.root,
                check=True,
                capture_output=True,
                text=True,
            )
            index = (output / "index.html").read_text(encoding="utf-8")
            self.assertIn('data-epsotests-mode="static"', index)
            self.assertIn('href="app.css"', index)
            self.assertIn('src="app.js"', index)
            self.assertTrue((output / "catalog.json").is_file())
            self.assertTrue((output / ".nojekyll").is_file())


if __name__ == "__main__":
    unittest.main()
