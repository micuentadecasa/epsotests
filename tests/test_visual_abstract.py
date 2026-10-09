import json
import subprocess
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from epsotests import (
    DIFFICULTY_ELEMENT_COUNTS,
    Element,
    ExamProfile,
    MIN_HUMAN_OBSERVABLE_TRANSLATION,
    QUANTIZED_ROTATION_DEGREES,
    Rule,
    Scene,
    SUPPORTED_DIFFICULTIES,
    SUPPORTED_EXAM_PROFILES,
    SUPPORTED_FORMATS,
    resolve_exam_profile,
    apply_rule,
    colour_change,
    composite,
    containment,
    deserialize_rule,
    deserialize_scene,
    explain_logic,
    generate_analogy,
    generate_matrix,
    generate_question,
    generate_sequence,
    make_distractors,
    movement,
    orientation,
    position,
    render_svg,
    serialize_scene,
    shape_addition,
    shape_removal,
    shading,
)


class VisualAbstractGeneratorTests(unittest.TestCase):
    def test_generation_is_deterministic(self):
        first = generate_question("sequence", seed=12, difficulty="hard")
        second = generate_question("sequence", seed=12, difficulty="hard")
        self.assertEqual(first, second)
        self.assertEqual(
            render_svg(Scene.from_dict(first["stimulus"]["frames"][0]["scene"])),
            first["stimulus"]["frames"][0]["svg"],
        )

    def test_adjacent_catalog_seeds_change_rule_and_answer_signatures(self):
        for format_name in SUPPORTED_FORMATS:
            first = generate_question(format_name, seed=42, difficulty="medium")
            second = generate_question(format_name, seed=43, difficulty="medium")
            with self.subTest(format=format_name):
                self.assertNotEqual(
                    first["metadata"]["ruleSignature"],
                    second["metadata"]["ruleSignature"],
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

    def test_default_rotation_is_visually_observable(self):
        for seed in range(20):
            question = generate_sequence(seed=seed, difficulty="easy")
            frames = question["stimulus"]["frames"]
            self.assertNotEqual(frames[0]["svg"], frames[1]["svg"])

    def test_generated_rules_meet_human_observable_visual_audit(self):
        def atomic_rules(rules):
            for rule in rules:
                if rule["kind"] == "composite":
                    yield from atomic_rules(rule["parameters"]["rules"])
                else:
                    yield rule

        expected_terms = {
            "rotation": "rotate",
            "translation": "move",
            "reflection": "reflect",
            "color-change": "colour",
            "fill": "fill",
        }
        for format_name in SUPPORTED_FORMATS:
            for difficulty in SUPPORTED_DIFFICULTIES:
                with self.subTest(format=format_name, difficulty=difficulty):
                    question = generate_question(
                        format_name, seed=42, difficulty=difficulty
                    )
                    scene_data = question["stimulus"]
                    if format_name == "sequence":
                        first_scene = scene_data["frames"][0]["scene"]
                        adjacent_groups = [
                            [frame["svg"] for frame in scene_data["frames"]]
                        ]
                    elif format_name.startswith("matrix"):
                        first_scene = next(
                            cell["scene"]
                            for row in scene_data["grid"]
                            for cell in row
                            if cell
                        )
                        grid = scene_data["grid"]
                        adjacent_groups = [
                            [cell["svg"] for cell in row if cell]
                            for row in grid
                        ]
                        adjacent_groups.extend(
                            [
                                grid[row][column]["svg"]
                                for row in range(len(grid))
                                if grid[row][column]
                            ]
                            for column in range(len(grid[0]))
                        )
                    else:
                        first_scene = scene_data["left"]["A"]["scene"]
                        adjacent_groups = [
                            [figure["svg"] for figure in scene_data["left"].values()]
                        ]
                    self.assertEqual(
                        len(first_scene["elements"]),
                        DIFFICULTY_ELEMENT_COUNTS[difficulty],
                    )
                    for group in adjacent_groups:
                        for previous, current in zip(group, group[1:]):
                            self.assertNotEqual(previous, current)
                    option_svgs = [option["svg"] for option in question["options"]]
                    self.assertEqual(len(option_svgs), len(set(option_svgs)))

                    explanation = question["explanation"].lower()
                    self.assertIn("rule", explanation)
                    for rule in atomic_rules(question["metadata"]["rules"]):
                        kind = rule["kind"]
                        parameters = rule["parameters"]
                        if kind == "rotation":
                            self.assertIn(
                                abs(float(parameters["degrees"])) % 360,
                                QUANTIZED_ROTATION_DEGREES,
                            )
                        elif kind == "translation":
                            delta = max(
                                abs(float(parameters.get("dx", 0))),
                                abs(float(parameters.get("dy", 0))),
                            )
                            self.assertGreaterEqual(
                                delta, MIN_HUMAN_OBSERVABLE_TRANSLATION
                            )
                        term = expected_terms.get(kind)
                        if term:
                            self.assertIn(term, explanation)

    def test_rotation_changes_symmetric_and_line_renderings(self):
        for shape in ("circle", "line", "diamond", "triangle", "star"):
            base = Scene((Element("one", shape=shape),))
            rotated = apply_rule(base, Rule("rotation", {"degrees": 90}))
            self.assertNotEqual(render_svg(base), render_svg(rotated))

    def test_nested_rotation_reaches_child_rendering(self):
        nested = apply_rule(
            Scene((Element("one"),)),
            Rule("nesting", {"shape": "triangle"}),
        )
        rotated_svg = render_svg(apply_rule(nested, Rule("rotation", {"degrees": 90})))
        root = ET.fromstring(rotated_svg)
        orientation = next(
            element
            for element in root
            if element.attrib.get("data-orientation") == "one-inner-nested"
        )
        self.assertGreater(
            float(orientation.attrib["x2"]), float(orientation.attrib["x1"])
        )
        self.assertEqual(orientation.attrib["y2"], orientation.attrib["y1"])

    def test_reflection_mirrors_marker_position_for_each_axis(self):
        base = Scene((Element("one", marker="dot", marker_position=0.25),))
        vertical = apply_rule(base, Rule("reflection", {"axis": "vertical"}))
        horizontal = apply_rule(base, Rule("reflection", {"axis": "horizontal"}))
        both = apply_rule(base, Rule("reflection", {"axis": "diagonal"}))
        self.assertAlmostEqual(vertical.elements[0].marker_position, 0.75)
        self.assertAlmostEqual(horizontal.elements[0].marker_position, 0.75)
        self.assertAlmostEqual(both.elements[0].marker_position, 0.25)
        self.assertEqual(vertical.elements[0].rotation, 0)
        self.assertEqual(horizontal.elements[0].rotation, 180)
        self.assertEqual(both.elements[0].rotation, 180)

    def test_reflection_transforms_nested_children(self):
        child = Element("inner", x=0.2, y=0.3, shape="triangle")
        base = Scene((Element("one", children=(child,)),))
        reflected = apply_rule(base, Rule("reflection", {"axis": "horizontal"}))
        reflected_child = reflected.elements[0].children[0]
        self.assertAlmostEqual(reflected_child.y, 0.7)
        self.assertEqual(reflected_child.rotation, 180)

    def test_colour_changes_remain_visible_when_initially_unshaded(self):
        base = Scene((Element("one", shaded=False),))
        colored = apply_rule(base, Rule("color-change", {"colors": ["#dc2626"]}))
        alternated = apply_rule(base, Rule("alternation", {"property": "fill"}))
        self.assertTrue(colored.elements[0].shaded)
        self.assertTrue(alternated.elements[0].shaded)
        self.assertNotEqual(render_svg(base), render_svg(colored))
        self.assertNotEqual(render_svg(base), render_svg(alternated))

    def test_symmetry_preserves_nested_rendering(self):
        base = Scene((Element("one"),))
        nested = apply_rule(base, Rule("nesting"))
        symmetric = apply_rule(nested, Rule("symmetry", {"order": 2}))
        self.assertEqual(render_svg(symmetric).count("data-element-id="), 4)

    def test_matrix_rejects_unassigned_extra_rules(self):
        with self.assertRaises(ValueError):
            generate_matrix(
                2,
                rules=[Rule("rotation"), Rule("translation"), Rule("fill")],
            )

    def test_every_requested_format_has_visual_options(self):
        questions = [
            generate_sequence(seed=1),
            generate_matrix(2, seed=2),
            generate_matrix(3, seed=3),
            generate_analogy(seed=4),
        ]
        for question in questions:
            self.assertEqual(question["exam"], "abstract")
            self.assertEqual(len(question["options"]), 4)
            self.assertIn("<svg", question["options"][0]["svg"])
            self.assertEqual(
                {option["id"] for option in question["options"]},
                {"A", "B", "C", "D"},
            )
            self.assertIn(question["correctOption"], {"A", "B", "C", "D"})

    def test_all_formats_have_one_rendered_answer_and_complete_provenance(self):
        cases = (
            ("sequence", 101),
            ("matrix-2x2", 102),
            ("matrix-3x3", 103),
            ("analogy", 104),
        )
        for format_name, seed in cases:
            with self.subTest(format=format_name):
                question = generate_question(format_name, seed=seed, difficulty="hard")
                options = question["options"]
                correct_svg = next(
                    option["svg"]
                    for option in options
                    if option["id"] == question["correctOption"]
                )
                self.assertEqual(len(options), 4)
                self.assertEqual(len({option["svg"] for option in options}), 4)
                self.assertEqual(
                    sum(option["svg"] == correct_svg for option in options), 1
                )
                self.assertEqual(len(question["metadata"]["distractors"]), 3)
                self.assertTrue(question["metadata"]["rules"])
                self.assertIn("rule", question["explanation"].lower())
                self.assertIn(question["correctOption"], question["explanation"])
                self.assertEqual(
                    question,
                    generate_question(
                        format_name, seed=seed, difficulty="hard"
                    ),
                )

    def test_public_contract_covers_formats_difficulties_and_review_metadata(self):
        for format_name in SUPPORTED_FORMATS:
            for difficulty in SUPPORTED_DIFFICULTIES:
                with self.subTest(format=format_name, difficulty=difficulty):
                    question = generate_question(
                        format_name,
                        seed=314,
                        difficulty=difficulty,
                    )
                    repeated = generate_question(
                        format_name,
                        seed=314,
                        difficulty=difficulty,
                    )
                    self.assertEqual(question, repeated)
                    self.assertEqual(question["format"], format_name)
                    self.assertEqual(question["difficulty"], difficulty)
                    self.assertEqual(question["examProfile"], "standard")
                    self.assertEqual(question["optionCount"], 4)
                    self.assertEqual(question["metadata"]["examProfile"], "standard")
                    self.assertEqual(question["metadata"]["optionCount"], 4)
                    self.assertEqual(len(question["options"]), 4)
                    self.assertEqual(
                        len({option["svg"] for option in question["options"]}),
                        4,
                    )
                    self.assertIn(
                        question["correctOption"], {"A", "B", "C", "D"}
                    )
                    action = question["actions"]["explainLogic"]
                    self.assertEqual(action["id"], "explain-logic")
                    self.assertEqual(action["type"], "button")
                    self.assertEqual(action["label"], "Explain logic")
                    self.assertFalse(action["initiallyVisible"])
                    self.assertTrue(action["revealsAnswer"])
                    self.assertFalse(action["solutionView"]["initiallyVisible"])
                    self.assertEqual(
                        action["solutionView"]["hideAction"]["id"],
                        "hide-solution",
                    )
                    self.assertEqual(
                        action["solutionView"]["hideAction"]["label"],
                        "Hide solution",
                    )
                    revealed = explain_logic(question)
                    self.assertEqual(
                        revealed["correctOption"], question["correctOption"]
                    )
                    self.assertEqual(revealed["rule"], question["metadata"]["rules"])
                    self.assertEqual(len(revealed["distractors"]), 3)
                    self.assertTrue(all(item["reason"] for item in revealed["distractors"]))
                    revealed["correctOption"] = "mutated"
                    self.assertEqual(
                        explain_logic(question)["correctOption"],
                        question["correctOption"],
                    )

                    for option in question["options"]:
                        self.assertEqual(
                            option["svg"],
                            render_svg(Scene.from_dict(option["figure"])),
                        )
                        ET.fromstring(option["svg"])
                    self.assertEqual(
                        question["metadata"]["rules"],
                        question["metadata"]["ruleMetadata"],
                    )
                    self.assertEqual(
                        question["metadata"]["explanationFragments"],
                        question["explanationFragments"],
                    )
                    answer = next(
                        option
                        for option in question["options"]
                        if option["id"] == question["correctOption"]
                    )
                    self.assertEqual(
                        question["metadata"]["answerFigure"], answer["figure"]
                    )
                    self.assertEqual(
                        question["metadata"]["answerSignature"],
                        Scene.from_dict(answer["figure"]).signature(),
                    )
                    wrong_options = [
                        option
                        for option in question["options"]
                        if option["id"] != question["correctOption"]
                    ]
                    self.assertEqual(
                        sorted(
                            json.dumps(option["mutation"], sort_keys=True)
                            for option in wrong_options
                        ),
                        sorted(
                            json.dumps(mutation, sort_keys=True)
                            for mutation in question["metadata"]["distractors"]
                        ),
                    )
                    self.assertGreater(len(question["explanation"].strip()), 40)
                    self.assertIn("rule", question["explanation"].lower())
                    self.assertIn(
                        question["correctOption"], question["explanation"]
                    )

    def test_exam_profiles_control_option_count_and_stay_deterministic(self):
        self.assertEqual(SUPPORTED_EXAM_PROFILES, ("standard", "five-option"))
        self.assertEqual(resolve_exam_profile().option_count, 4)
        self.assertEqual(resolve_exam_profile("pdf").name, "standard")
        self.assertEqual(resolve_exam_profile("png").option_count, 5)
        custom = ExamProfile("custom-six", 6)
        for profile, expected_count in (
            ("standard", 4),
            ("five-option", 5),
            (custom, 6),
        ):
            with self.subTest(profile=str(profile)):
                question = generate_question(
                    "matrix-3x3",
                    seed=909,
                    difficulty="hard",
                    exam_profile=profile,
                )
                self.assertEqual(question["optionCount"], expected_count)
                self.assertEqual(len(question["options"]), expected_count)
                self.assertEqual(
                    {option["id"] for option in question["options"]},
                    set(custom.option_ids[:expected_count]),
                )
                self.assertEqual(
                    question,
                    generate_question(
                        "matrix-3x3",
                        seed=909,
                        difficulty="hard",
                        exam_profile=profile,
                    ),
                )

    def test_every_serialized_svg_in_a_question_is_valid(self):
        def svg_values(value):
            if isinstance(value, dict):
                if isinstance(value.get("svg"), str):
                    yield value["svg"]
                for child in value.values():
                    yield from svg_values(child)
            elif isinstance(value, list):
                for child in value:
                    yield from svg_values(child)

        for format_name in SUPPORTED_FORMATS:
            with self.subTest(format=format_name):
                question = generate_question(format_name, seed=2718, difficulty="hard")
                figures = list(svg_values(question["stimulus"]))
                figures.extend(option["svg"] for option in question["options"])
                self.assertGreater(len(figures), 4)
                for svg in figures:
                    ET.fromstring(svg)

    def test_cli_emits_the_same_portable_question_contract(self):
        root = Path(__file__).parents[1]
        for format_name, difficulty in zip(
            SUPPORTED_FORMATS, ("easy", "medium", "hard", "medium")
        ):
            with self.subTest(format=format_name):
                result = subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "epsotests.cli",
                        format_name,
                        "--seed",
                        "808",
                        "--difficulty",
                        difficulty,
                    ],
                    cwd=root,
                    check=True,
                    capture_output=True,
                    text=True,
                )
                question = json.loads(result.stdout)
                self.assertEqual(question, generate_question(
                    format_name, seed=808, difficulty=difficulty
                ))
                self.assertEqual(question["optionCount"], 4)
                self.assertEqual(result.stderr, "")

        review = subprocess.run(
            [
                sys.executable,
                "-m",
                "epsotests.cli",
                "analogy",
                "--seed",
                "808",
                "--difficulty",
                "hard",
                "--exam-profile",
                "five-option",
                "--review",
            ],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
        review_payload = json.loads(review.stdout)
        self.assertEqual(review_payload["action"]["id"], "explain-logic")
        self.assertEqual(review_payload["action"]["label"], "Explain logic")
        review_question = generate_question(
            "analogy",
            seed=808,
            difficulty="hard",
            exam_profile="five-option",
        )
        self.assertEqual(review_payload["action"]["result"]["correctOption"], review_question["correctOption"])
        self.assertEqual(review_payload["action"]["result"]["optionCount"], 5)
        self.assertEqual(len(review_payload["action"]["result"]["distractors"]), 4)

    def test_example_regeneration_is_byte_stable(self):
        root = Path(__file__).parents[1]
        examples = root / "examples" / "visual"
        paths = sorted(examples.glob("*.json")) + sorted(examples.glob("*.svg"))
        before = {path: path.read_bytes() for path in paths}
        subprocess.run(
            [sys.executable, "examples/visual/generate_examples.py"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(before, {path: path.read_bytes() for path in paths})

    def test_rule_application_covers_requested_transformations(self):
        base = Scene((Element("one", shape="square", x=0.3, y=0.4, fill="#123456"),))
        cases = [
            (
                Rule("rotation", {"degrees": 90}),
                lambda scene: scene.elements[0].rotation == 90,
            ),
            (
                Rule("reflection", {"axis": "vertical"}),
                lambda scene: scene.elements[0].x == 0.7,
            ),
            (
                Rule("translation", {"dx": 0.1, "dy": 0.1}),
                lambda scene: scene.elements[0].x == 0.4,
            ),
            (
                Rule("alternation", {"property": "shaded"}),
                lambda scene: scene.elements[0].shaded is False,
            ),
            (
                Rule("element-count", {"delta": 1}),
                lambda scene: len(scene.elements) == 2,
            ),
            (
                Rule("shape-change", {"shapes": ["triangle", "diamond"]}),
                lambda scene: scene.elements[0].shape == "diamond",
            ),
            (
                Rule("fill", {"shaded": False}),
                lambda scene: scene.elements[0].shaded is False,
            ),
            (
                Rule("color-change", {"colors": ["#abc000", "#def000"]}),
                lambda scene: scene.elements[0].fill == "#def000",
            ),
            (
                Rule("symmetry", {"order": 2}),
                lambda scene: scene.elements[0].symmetry == 2,
            ),
            (
                Rule("nesting", {"action": "add"}),
                lambda scene: len(scene.elements[0].children) == 1,
            ),
            (
                Rule("line-count", {"delta": 2}),
                lambda scene: scene.elements[0].line_count == 3,
            ),
        ]
        for rule, assertion in cases:
            with self.subTest(rule=rule.kind):
                self.assertTrue(assertion(apply_rule(base, rule)))
                self.assertEqual(apply_rule(base, rule, frame_index=0), base)

        self.assertIn(
            "data-line-count",
            render_svg(apply_rule(base, Rule("line-count", {"delta": 2}))),
        )
        composite = Rule(
            "composite",
            {
                "rules": [
                    Rule("rotation", {"degrees": 90}),
                    Rule("translation", {"dx": 0.1}),
                ]
            },
        )
        changed = apply_rule(base, composite)
        self.assertEqual(changed.elements[0].rotation, 90)
        self.assertAlmostEqual(changed.elements[0].x, 0.4)

    def test_rule_and_scene_metadata_round_trip(self):
        rule = Rule("translation", {"dx": 0.15, "dy": -0.05})
        self.assertEqual(deserialize_rule(rule.to_dict()), rule)
        scene = Scene((Element("x", shape="star", marker="dot"),))
        self.assertEqual(deserialize_scene(serialize_scene(scene)), scene)
        self.assertTrue(json.dumps(scene.to_dict()))

    def test_exactly_one_correct_option_and_plausible_mutations(self):
        question = generate_question("matrix-2x2", seed=99, difficulty="hard")
        answer = next(
            option
            for option in question["options"]
            if option["id"] == question["correctOption"]
        )
        signatures = [
            json.dumps(option["figure"], sort_keys=True)
            for option in question["options"]
        ]
        self.assertEqual(len(signatures), len(set(signatures)))
        self.assertEqual(
            sum(
                signature == json.dumps(answer["figure"], sort_keys=True)
                for signature in signatures
            ),
            1,
        )
        wrong = [
            option
            for option in question["options"]
            if option["id"] != question["correctOption"]
        ]
        self.assertTrue(
            all(option["mutation"]["kind"] != "correct" for option in wrong)
        )
        self.assertTrue(all(option["mutation"]["description"] for option in wrong))

    def test_rule_aliases_and_nested_targets_are_visible(self):
        child = Element("inner", shape="triangle", fill="#123456", shaded=True)
        base = Scene((Element("outer", children=(child,)),))
        cases = [
            movement(0.1, 0.05),
            position(0.1, 0.05),
            orientation(45),
            shading(False),
            colour_change(("#dc2626",)),
            containment("add"),
            shape_addition("square"),
            shape_removal(),
        ]
        for rule in cases:
            with self.subTest(rule=rule.kind):
                changed = apply_rule(base, rule)
                self.assertIsInstance(changed, Scene)
                self.assertNotEqual(render_svg(base), render_svg(changed))
        targeted = apply_rule(
            base,
            Rule("line-count", {"delta": 1, "target": "inner"}),
        )
        self.assertEqual(targeted.elements[0].children[0].line_count, 2)
        self.assertIn("data-line-count", render_svg(targeted))

    def test_composite_alias_round_trip_and_nested_rendering(self):
        rule = composite((orientation(90), movement(0.1), colour_change(("#dc2626",))))
        restored = deserialize_rule(rule.to_dict())
        base = Scene((Element("one", children=(Element("inner"),)),))
        changed = apply_rule(base, restored)
        self.assertEqual(changed.elements[0].rotation, 90)
        self.assertAlmostEqual(changed.elements[0].x, 0.6)
        self.assertEqual(changed.elements[0].fill, "#dc2626")
        self.assertNotEqual(render_svg(base), render_svg(changed))

    def test_distractors_are_svg_unique_and_seed_stable(self):
        base = Scene((Element("one", shape="triangle", marker="dot"), Element("two")))
        rules = [composite((orientation(90), movement(0.1)))]
        first = make_distractors(base, base, rules, seed=13, count=8)
        second = make_distractors(base, base, rules, seed=13, count=8)
        self.assertEqual(first, second)
        rendered = [render_svg(item["scene"]) for item in first]
        self.assertEqual(len(rendered), len(set(rendered)))
        self.assertTrue(all(item["mutation"]["description"] for item in first))
        self.assertIn("partial-rule", {item["mutation"]["kind"] for item in first})

    def test_question_exposes_explanation_fragments_and_visual_uniqueness(self):
        question = generate_sequence(seed=6, difficulty="hard")
        self.assertEqual(len(question["explanationFragments"]), 3)
        self.assertEqual(
            question["metadata"]["explanationFragments"],
            question["explanationFragments"],
        )
        correct_svg = next(
            option["svg"]
            for option in question["options"]
            if option["id"] == question["correctOption"]
        )
        self.assertEqual(
            sum(option["svg"] == correct_svg for option in question["options"]),
            1,
        )
        self.assertEqual(
            len({option["svg"] for option in question["options"]}),
            len(question["options"]),
        )

    def test_inspectable_examples_are_exam_like_svg_panels(self):
        from pathlib import Path

        examples = Path(__file__).parents[1] / "examples" / "visual"
        files = sorted(examples.glob("*.svg"))
        self.assertEqual(len(files), 4)
        for path in files:
            content = path.read_text(encoding="utf-8")
            self.assertIn('role="img"', content)
            self.assertGreaterEqual(content.count('data-element-id='), 4)
            self.assertGreaterEqual(content.count('>A</text>'), 1)
            self.assertGreaterEqual(content.count('>E</text>'), 1)
            self.assertIn('data-option-count="5"', content)

    def test_fixed_seed_json_examples_match_the_index_and_panels(self):
        from pathlib import Path

        examples = Path(__file__).parents[1] / "examples" / "visual"
        index = json.loads((examples / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(len(index), 4)
        for entry in index:
            question_path = examples / entry["json"]
            panel_path = examples / entry["svg"]
            question = json.loads(question_path.read_text(encoding="utf-8"))
            self.assertEqual(question["format"], entry["format"])
            self.assertEqual(question["examProfile"], entry["examProfile"])
            self.assertEqual(question["itemNumber"], entry["itemNumber"])
            self.assertEqual(question["metadata"]["seed"], entry["seed"])
            self.assertEqual(question["difficulty"], entry["difficulty"])
            self.assertEqual(question["correctOption"], entry["correctOption"])
            self.assertEqual(
                question["actions"]["explainLogic"], entry["explainLogic"]
            )
            self.assertEqual(len(question["options"]), 5)
            self.assertEqual(
                len({option["svg"] for option in question["options"]}), 5
            )
            self.assertEqual(len(question["metadata"]["distractors"]), 4)
            self.assertIn('role="img"', panel_path.read_text(encoding="utf-8"))

    def test_explanation_is_complete_and_metadata_can_regenerate(self):
        question = generate_question("analogy", seed=23, difficulty="medium")
        self.assertIn("rule", question["explanation"].lower())
        self.assertIn(question["correctOption"], question["explanation"])
        self.assertTrue(question["metadata"]["rules"])
        self.assertEqual(
            question["metadata"]["answerSignature"],
            json.dumps(
                question["metadata"]["answerFigure"],
                sort_keys=True,
                separators=(",", ":"),
            ),
        )
        regenerated = generate_question(
            question["format"],
            seed=question["metadata"]["seed"],
            difficulty=question["difficulty"],
        )
        self.assertEqual(question, regenerated)


if __name__ == "__main__":
    unittest.main()
