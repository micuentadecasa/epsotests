import json
import unittest

from epsotests import (
    Element,
    Rule,
    Scene,
    apply_rule,
    deserialize_rule,
    deserialize_scene,
    generate_analogy,
    generate_matrix,
    generate_question,
    generate_sequence,
    render_svg,
    serialize_scene,
)


class VisualAbstractGeneratorTests(unittest.TestCase):
    def test_generation_is_deterministic(self):
        first = generate_question("sequence", seed=12, difficulty="hard")
        second = generate_question("sequence", seed=12, difficulty="hard")
        self.assertEqual(first, second)
        self.assertEqual(render_svg(Scene.from_dict(first["stimulus"]["frames"][0]["scene"])), first["stimulus"]["frames"][0]["svg"])

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
            self.assertEqual({option["id"] for option in question["options"]}, {"A", "B", "C", "D"})
            self.assertIn(question["correctOption"], {"A", "B", "C", "D"})

    def test_rule_application_covers_requested_transformations(self):
        base = Scene((Element("one", shape="square", x=0.3, y=0.4, fill="#123456"),))
        cases = [
            (Rule("rotation", {"degrees": 90}), lambda scene: scene.elements[0].rotation == 90),
            (Rule("reflection", {"axis": "vertical"}), lambda scene: scene.elements[0].x == 0.7),
            (Rule("translation", {"dx": 0.1, "dy": 0.1}), lambda scene: scene.elements[0].x == 0.4),
            (Rule("alternation", {"property": "shaded"}), lambda scene: scene.elements[0].shaded is False),
            (Rule("element-count", {"delta": 1}), lambda scene: len(scene.elements) == 2),
            (Rule("shape-change", {"shapes": ["triangle", "diamond"]}), lambda scene: scene.elements[0].shape == "diamond"),
            (Rule("fill", {"shaded": False}), lambda scene: scene.elements[0].shaded is False),
            (Rule("color-change", {"colors": ["#abc000", "#def000"]}), lambda scene: scene.elements[0].fill == "#def000"),
            (Rule("symmetry", {"order": 2}), lambda scene: scene.elements[0].symmetry == 2),
            (Rule("nesting", {"action": "add"}), lambda scene: len(scene.elements[0].children) == 1),
            (Rule("line-count", {"delta": 2}), lambda scene: scene.elements[0].line_count == 3),
        ]
        for rule, assertion in cases:
            with self.subTest(rule=rule.kind):
                self.assertTrue(assertion(apply_rule(base, rule)))
                self.assertEqual(apply_rule(base, rule, frame_index=0), base)

        self.assertIn('data-line-count', render_svg(apply_rule(base, Rule("line-count", {"delta": 2}))))
        composite = Rule("composite", {"rules": [Rule("rotation", {"degrees": 90}), Rule("translation", {"dx": 0.1})]})
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
        answer = next(option for option in question["options"] if option["id"] == question["correctOption"])
        signatures = [json.dumps(option["figure"], sort_keys=True) for option in question["options"]]
        self.assertEqual(len(signatures), len(set(signatures)))
        self.assertEqual(sum(signature == json.dumps(answer["figure"], sort_keys=True) for signature in signatures), 1)
        wrong = [option for option in question["options"] if option["id"] != question["correctOption"]]
        self.assertTrue(all(option["mutation"]["kind"] != "correct" for option in wrong))
        self.assertTrue(all(option["mutation"]["description"] for option in wrong))

    def test_explanation_is_complete_and_metadata_can_regenerate(self):
        question = generate_question("analogy", seed=23, difficulty="medium")
        self.assertIn("rule", question["explanation"].lower())
        self.assertIn(question["correctOption"], question["explanation"])
        self.assertTrue(question["metadata"]["rules"])
        self.assertEqual(question["metadata"]["answerSignature"], json.dumps(question["metadata"]["answerFigure"], sort_keys=True, separators=(",", ":")))
        regenerated = generate_question(question["format"], seed=question["metadata"]["seed"], difficulty=question["difficulty"])
        self.assertEqual(question, regenerated)


if __name__ == "__main__":
    unittest.main()
