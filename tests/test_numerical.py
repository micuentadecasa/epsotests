import json
from pathlib import Path
import subprocess
import sys
import unittest
import xml.etree.ElementTree as ET

from epsotests import (
    NumericalChart,
    NumericalQuestion,
    NumericalTable,
    SUPPORTED_NUMERICAL_OPERATIONS,
    calculate_growth,
    calculate_percentage_change,
    calculate_proportion,
    calculate_ratio,
    calculate_total,
    explain_numerical_logic,
    generate_numerical_question,
    parse_chart,
    parse_table,
    render_chart_svg,
    render_table_html,
    table_to_chart,
)


class NumericalGeneratorTests(unittest.TestCase):
    def test_calculation_helpers_cover_percentage_ratio_and_totals(self):
        self.assertEqual(calculate_percentage_change(80, 100), 25)
        self.assertEqual(calculate_ratio(18, 12), "3:2")
        self.assertEqual(calculate_proportion(30, 120), 25)
        self.assertEqual(calculate_total([12, 18, 20]), 50)
        self.assertEqual(calculate_growth(100, 10, 2), 121)

    def test_table_and_chart_parsing_preserves_source_data(self):
        table = parse_table({
            "title": "Regional cases",
            "columns": ["Region", "Cases"],
            "rows": [{"Region": "North", "Cases": 12}, {"Region": "South", "Cases": 18}],
        })
        self.assertIsInstance(table, NumericalTable)
        self.assertEqual(table.to_dict()["rows"][1]["Cases"], 18)
        chart = table_to_chart(table, "bar-chart")
        restored = parse_chart(chart.to_dict())
        self.assertIsInstance(restored, NumericalChart)
        self.assertEqual(restored.to_dict(), chart.to_dict())
        self.assertIn("scope=\"col\"", render_table_html(table))
        ET.fromstring(render_chart_svg(chart))

    def test_every_operation_is_seed_deterministic_and_typed(self):
        for operation in SUPPORTED_NUMERICAL_OPERATIONS:
            first = generate_numerical_question(operation, seed=17, representation="table")
            second = generate_numerical_question(operation, seed=17, representation="table")
            self.assertEqual(first, second)
            self.assertEqual(NumericalQuestion.from_dict(first).to_dict(), first)
            self.assertEqual(first["operation"], operation)
            self.assertEqual(first["stimulus"]["sourceData"], first["metadata"]["sourceData"])

    def test_adjacent_catalog_seeds_change_method_steps_and_answers(self):
        for operation in SUPPORTED_NUMERICAL_OPERATIONS:
            first = generate_numerical_question(operation, seed=42)
            second = generate_numerical_question(operation, seed=43)
            with self.subTest(operation=operation):
                self.assertNotEqual(
                    first["metadata"]["operationSignature"],
                    second["metadata"]["operationSignature"],
                )
                self.assertNotEqual(
                    first["metadata"]["calculationSignature"],
                    second["metadata"]["calculationSignature"],
                )
                self.assertNotEqual(
                    first["metadata"]["answerSignature"],
                    second["metadata"]["answerSignature"],
                )
                self.assertNotEqual(
                    first["metadata"]["explanationSignature"],
                    second["metadata"]["explanationSignature"],
                )

    def test_option_profiles_have_exactly_one_correct_answer(self):
        for operation in SUPPORTED_NUMERICAL_OPERATIONS:
            for profile, count in (("standard", 4), ("five-option", 5)):
                question = generate_numerical_question(operation, seed=31, exam_profile=profile)
                self.assertEqual(question["optionCount"], count)
                self.assertEqual(len(question["options"]), count)
                self.assertEqual({option["id"] for option in question["options"]}, set("ABCDE"[:count]))
                values = [json.dumps(option["value"], sort_keys=True) for option in question["options"]]
                self.assertEqual(len(values), len(set(values)))
                self.assertEqual(sum(option["id"] == question["correctOption"] for option in question["options"]), 1)
                self.assertEqual(len(question["metadata"]["distractors"]), count - 1)
                self.assertTrue(all(item["description"] for item in question["metadata"]["distractors"]))

    def test_explanation_contains_formula_substitution_intermediate_units_and_rounding(self):
        question = generate_numerical_question("multi-step", seed=9, difficulty="hard", representation="line-chart")
        explanation = question["explanation"]
        self.assertIn("Formula:", explanation)
        self.assertIn("substitute", explanation)
        self.assertIn("EUR", explanation)
        self.assertIn("rounded", explanation)
        self.assertGreaterEqual(len(question["metadata"]["calculationSteps"]), 5)
        self.assertIn("visualShortcut", question["actions"]["explainLogic"]["result"])
        self.assertEqual(question["actions"]["explainLogic"]["localizedLabel"], "Ver solución")
        revealed = explain_numerical_logic(question)
        self.assertEqual(revealed["correctOption"], question["correctOption"])
        revealed["correctOption"] = "mutated"
        self.assertEqual(explain_numerical_logic(question)["correctOption"], question["correctOption"])

    def test_chart_question_has_accessible_valid_svg_and_table_has_html(self):
        chart_question = generate_numerical_question("growth", seed=4, representation="line-chart")
        self.assertIn('role="img"', chart_question["stimulus"]["svg"])
        self.assertIn('data-chart-type="line-chart"', chart_question["stimulus"]["svg"])
        ET.fromstring(chart_question["stimulus"]["svg"])
        table_question = generate_numerical_question("ratio", seed=4, representation="table")
        self.assertIn("<table", table_question["stimulus"]["html"])
        self.assertIn("<caption>", table_question["stimulus"]["html"])

    def test_cli_numerical_mode_emits_same_payload(self):
        root = Path(__file__).parents[1]
        result = subprocess.run(
            [sys.executable, "-m", "epsotests.cli", "numerical", "ratio", "--seed", "8", "--representation", "table"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(result.stdout)
        self.assertEqual(payload, generate_numerical_question("ratio", seed=8, representation="table"))
        self.assertEqual(result.stderr, "")

    def test_numerical_example_regeneration_is_byte_stable(self):
        root = Path(__file__).parents[1]
        examples = root / "examples" / "numerical"
        paths = sorted(examples.glob("*.json")) + sorted(examples.glob("*.svg"))
        before = {path: path.read_bytes() for path in paths}
        subprocess.run(
            [sys.executable, "examples/numerical/generate_examples.py"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(before, {path: path.read_bytes() for path in paths})

    def test_fixed_numerical_examples_match_manifest(self):
        root = Path(__file__).parents[1] / "examples" / "numerical"
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(len(manifest), 4)
        for entry in manifest:
            question = json.loads((root / entry["json"]).read_text(encoding="utf-8"))
            self.assertEqual(question["operation"], entry["operation"])
            self.assertEqual(question["metadata"]["seed"], entry["seed"])
            self.assertEqual(question["correctOption"], entry["correctOption"])
            self.assertEqual(question["actions"]["explainLogic"], entry["explainLogic"])
            self.assertTrue((root / entry["svg"]).read_text(encoding="utf-8").startswith("<svg"))


if __name__ == "__main__":
    unittest.main()
