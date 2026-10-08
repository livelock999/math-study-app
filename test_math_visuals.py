"""図に渡す既知数、未知数、0と20の境界を確認します。"""
from copy import deepcopy
import unittest

from fill_blank import fill_pool, make_fill_problem
from learning import make_problem, problem_pool
from math_visuals import visual_model
from words import make_word_problem


class MathVisualTests(unittest.TestCase):
    def test_every_number_in_calculation_and_fill_matches_equation_without_revealing_blank(self):
        for operation in ("addition", "subtraction"):
            for limit in (10, 20):
                for problem in problem_pool(operation, limit) + fill_pool(operation, limit):
                    original = deepcopy(problem)
                    result = problem["left_operand"] + problem["right_operand"] if operation == "addition" else problem["left_operand"] - problem["right_operand"]
                    values = [problem["left_operand"], problem["right_operand"], result]
                    blank = ("left_operand", "right_operand", "answer").index(problem["blank_position"])
                    hidden = visual_model(problem)
                    shown = visual_model(problem, reveal=True)
                    self.assertIsNone(hidden["rows"][blank]["count"])
                    self.assertEqual([r["count"] for r in shown["rows"]], values)
                    self.assertEqual([r["count"] for i, r in enumerate(hidden["rows"]) if i != blank],
                                     [v for i, v in enumerate(values) if i != blank])
                    self.assertEqual(problem, original)

    def test_zero_and_twenty_remain_real_counts(self):
        problem = make_fill_problem("subtraction", 20, 20, 0, "right_operand")
        self.assertEqual([20, None, 20], [r["count"] for r in visual_model(problem)["rows"]])
        self.assertEqual([20, 0, 20], [r["count"] for r in visual_model(problem, True)["rows"]])
        self.assertEqual("remove", visual_model(problem)["rows"][1]["tone"])

    def test_invalid_numbers_and_positions_stop_before_rendering(self):
        problem = make_problem("addition", 20, 8, 9)
        for changes in ({"left_operand": -1}, {"right_operand": 21}, {"left_operand": True},
                        {"number_range": 50}, {"operation": "division"},
                        {"problem_format": "fill_blank", "blank_position": "answer"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                visual_model({**problem, **changes})
        with self.assertRaises(ValueError):
            visual_model(problem, reveal=1)

    def test_word_problem_does_not_get_an_operation_revealing_picture(self):
        self.assertIsNone(visual_model(make_word_problem("increase", 10, 3, 2)))

    def test_common_report_keeps_fill_separate_and_counts_only_initial_visual_use(self):
        from datetime import datetime, timedelta
        from activity import JST
        from cross_subject import build_report
        from learning import make_attempt
        now = datetime(2026, 10, 8, 12, tzinfo=JST)
        problem = make_fill_problem("addition", 10, 5, 3, "left_operand")
        initial = make_attempt(problem, "user_001", "fill", 1, "normal", 5, 2, 1, visual_help_used=True)
        initial["datetime"] = (now - timedelta(days=1)).isoformat()
        review = make_attempt(problem, "user_001", "fill_review", 1, "review", 5, 2, 1)
        review["datetime"] = now.isoformat()
        foreign = {**initial, "attempt_id": "foreign", "user_id": "user_002"}
        future = {**initial, "attempt_id": "future", "datetime": (now + timedelta(days=1)).isoformat()}
        report = build_report([initial, review, initial, foreign, future], [], "user_001", now=now)
        self.assertEqual(report["groups"][0]["count"], 0)
        fill = next(g for g in report["groups"] if g["label"] == "算数：□に入る数")
        self.assertEqual((fill["count"], fill["visual_used_count"], fill["hint_rate"]), (1, 1, 1))
        self.assertEqual(report["subjects"]["math"]["review"]["visual_used_count"], 0)


if __name__ == "__main__":
    unittest.main()
