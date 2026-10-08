import json
import unittest
import xml.etree.ElementTree as ET

from epsotests import (
    Element,
    Rule,
    Scene,
    apply_rule,
    colour_change,
    composite,
    containment,
    deserialize_rule,
    deserialize_scene,
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

    def test_default_rotation_is_visually_observable(self):
        for seed in range(20):
            question = generate_sequence(seed=seed, difficulty="easy")
            frames = question["stimulus"]["frames"]
            self.assertNotEqual(frames[0]["svg"], frames[1]["svg"])

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
            self.assertGreaterEqual(len(question["options"]), 3)
            self.assertIn("<svg", question["options"][0]["svg"])
            self.assertEqual(
                {option["id"] for option in question["options"]}, {"A", "B", "C", "D"}
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
            self.assertGreaterEqual(content.count('>D</text>'), 1)

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
            self.assertEqual(question["metadata"]["seed"], entry["seed"])
            self.assertEqual(question["difficulty"], entry["difficulty"])
            self.assertEqual(question["correctOption"], entry["correctOption"])
            self.assertEqual(len(question["options"]), 4)
            self.assertEqual(
                len({option["svg"] for option in question["options"]}), 4
            )
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
