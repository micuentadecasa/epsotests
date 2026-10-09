import json
from pathlib import Path
import subprocess
import sys
import unittest
import xml.etree.ElementTree as ET

from epsotests import (
    SUPPORTED_VERBAL_QUESTION_TYPES,
    VerbalQuestion,
    explain_verbal_logic,
    generate_verbal_question,
)


class VerbalGeneratorTests(unittest.TestCase):
    def test_generation_is_seed_deterministic_and_typed(self):
        for question_type in SUPPORTED_VERBAL_QUESTION_TYPES:
            first = generate_verbal_question(question_type, seed=17, difficulty="hard")
            second = generate_verbal_question(question_type, seed=17, difficulty="hard")
            self.assertEqual(first, second)
            self.assertEqual(VerbalQuestion.from_dict(first).to_dict(), first)
            self.assertEqual(first["questionType"], question_type)
            self.assertEqual(first["exam"], "verbal")

    def test_adjacent_catalog_seeds_change_evidence_and_explanations(self):
        for question_type in SUPPORTED_VERBAL_QUESTION_TYPES:
            first = generate_verbal_question(question_type, seed=42)
            second = generate_verbal_question(question_type, seed=43)
            with self.subTest(question_type=question_type):
                self.assertNotEqual(
                    first["metadata"]["evidenceSignature"],
                    second["metadata"]["evidenceSignature"],
                )
                self.assertNotEqual(
                    first["metadata"]["answerSignature"],
                    second["metadata"]["answerSignature"],
                )
                self.assertNotEqual(
                    first["metadata"]["explanationSignature"],
                    second["metadata"]["explanationSignature"],
                )
                self.assertNotEqual(
                    first["metadata"]["methodSignature"],
                    second["metadata"]["methodSignature"],
                )

    def test_profiles_have_unique_options_and_one_supported_answer(self):
        for question_type in SUPPORTED_VERBAL_QUESTION_TYPES:
            for profile, count in (("standard", 4), ("five-option", 5)):
                with self.subTest(question_type=question_type, profile=profile):
                    question = generate_verbal_question(
                        question_type, seed=31, exam_profile=profile
                    )
                    self.assertEqual(question["optionCount"], count)
                    self.assertEqual(len(question["options"]), count)
                    self.assertEqual(
                        {option["id"] for option in question["options"]},
                        set("ABCDE"[:count]),
                    )
                    self.assertEqual(
                        len({option["text"] for option in question["options"]}), count
                    )
                    self.assertEqual(
                        sum(
                            evaluation["isCorrect"]
                            for evaluation in question["answerEvaluation"]
                        ),
                        1,
                    )
                    self.assertEqual(
                        question["correctOption"],
                        next(
                            evaluation["option"]
                            for evaluation in question["answerEvaluation"]
                            if evaluation["isCorrect"]
                        ),
                    )
                    self.assertEqual(
                        len(question["metadata"]["distractors"]), count - 1
                    )
                    self.assertTrue(
                        all(item["reason"] for item in question["metadata"]["distractors"])
                    )

    def test_evidence_spans_are_complete_and_address_the_passage(self):
        for question_type in SUPPORTED_VERBAL_QUESTION_TYPES:
            question = generate_verbal_question(question_type, seed=88)
            passage = question["passage"]["text"]
            spans = {span["id"]: span for span in question["evidenceSpans"]}
            self.assertTrue(spans)
            for span in spans.values():
                self.assertEqual(span["text"], passage[span["start"] : span["end"]])
                self.assertGreater(span["end"], span["start"])
            for evaluation in question["answerEvaluation"]:
                self.assertTrue(evaluation["evidence"])
                self.assertTrue(
                    all(evidence_id in spans for evidence_id in evaluation["evidence"])
                )
            correct = next(
                item
                for item in question["answerEvaluation"]
                if item["isCorrect"]
            )
            self.assertTrue(
                any(span["text"] in question["explanation"] for span in (
                    spans[evidence_id] for evidence_id in correct["evidence"]
                ))
            )

    def test_distractors_record_rationale_and_invalid_inferences(self):
        question = generate_verbal_question("inference", seed=12, exam_profile="five-option")
        wrong = [
            item
            for item in question["answerEvaluation"]
            if not item["isCorrect"]
        ]
        self.assertTrue(wrong)
        for item in wrong:
            self.assertTrue(item["rationale"])
            self.assertTrue(
                any(
                    item["option"] in invalid
                    for invalid in question["explanationDetails"]["invalidInferences"]
                )
            )
        self.assertEqual(
            len(question["explanationDetails"]["invalidInferences"]),
            len(wrong),
        )

    def test_explain_logic_is_hidden_until_requested_and_returns_a_copy(self):
        question = generate_verbal_question("true-false", seed=23, exam_profile="five-option")
        action = question["actions"]["explainLogic"]
        self.assertFalse(action["initiallyVisible"])
        self.assertFalse(action["solutionView"]["initiallyVisible"])
        self.assertEqual(action["localizedLabel"], "Ver solución")
        self.assertEqual(action["solutionView"]["hideAction"]["id"], "hide-solution")
        revealed = explain_verbal_logic(question)
        self.assertEqual(revealed["correctOption"], question["correctOption"])
        self.assertEqual(len(revealed["distractors"]), 4)
        revealed["correctOption"] = "mutated"
        self.assertEqual(
            explain_verbal_logic(question)["correctOption"], question["correctOption"]
        )

    def test_cli_and_examples_are_stable(self):
        root = Path(__file__).parents[1]
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "epsotests.cli",
                "verbal",
                "inference",
                "--seed",
                "47",
                "--exam-profile",
                "five-option",
            ],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(json.loads(result.stdout), generate_verbal_question("inference", seed=47, exam_profile="five-option"))
        self.assertEqual(result.stderr, "")

        examples = root / "examples" / "verbal"
        paths = sorted(examples.glob("*.json")) + sorted(examples.glob("*.svg"))
        before = {path: path.read_bytes() for path in paths}
        subprocess.run(
            [sys.executable, "examples/verbal/generate_examples.py"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(before, {path: path.read_bytes() for path in paths})
        manifest = json.loads((examples / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(len(manifest), 4)
        for item in manifest:
            payload = json.loads((examples / item["json"]).read_text(encoding="utf-8"))
            self.assertEqual(payload["correctOption"], item["correctOption"])
            ET.fromstring((examples / item["svg"]).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
