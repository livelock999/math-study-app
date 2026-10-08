"""穴埋めの独立分析・復習・おまかせ・学校範囲の連携。実DBを使わない。"""
from datetime import datetime, timedelta
import random
import unittest

import adaptive_difficulty as adaptive
import assessment
import daily_review as review
import learning
import parent_insights as parent
import school_scope as school
from fill_blank import make_fill_problem, hint_steps

NOW = datetime(2026, 10, 8, 12, tzinfo=review.JST)


def record(problem=None, identifier="first", day=1, correct=False, selection="normal", count=1, **updates):
    problem = problem or make_fill_problem("addition", 10, 5, 3, "left_operand")
    row = learning.make_attempt(problem, "user_001", identifier, 1, selection,
                                problem["correct_answer"] if correct else 99, 2, count)
    return {**row, "attempt_id": identifier, "datetime": (NOW - timedelta(days=day)).isoformat(), **updates}


class FillLearningTests(unittest.TestCase):
    def test_fill_first_retry_latest_and_hints_leave_calculation_unchanged(self):
        calculation = record(learning.make_problem("addition", 10, 5, 3), "calc", correct=True)
        first = record(identifier="wrong", hint_used=True)
        retry = record(identifier="retry", day=0, selection="retry", count=2, correct=True)
        due = record(identifier="review", day=0, selection="review", correct=True)
        before = assessment.assess([calculation], now=NOW)
        report = assessment.assess([calculation, first, retry, due], now=NOW)
        for key in before:
            if not key.startswith("fill_"):
                self.assertEqual(before[key], report[key], key)
        self.assertEqual(report["fill_normal"]["rate"], 0)
        self.assertEqual(report["fill_normal"]["hint_rate"], 1)
        self.assertEqual(report["fill_retry"]["count"], 1)
        self.assertEqual(report["fill_latest"]["count"], 1)
        self.assertEqual(report["fill_latest"]["rate"], 1)
        self.assertEqual(report["fill_review"]["count"], 1)

    def test_fill_groups_separate_left_right_and_ignore_foreign_future_duplicate(self):
        left = make_fill_problem("addition", 10, 5, 3, "left_operand")
        right = make_fill_problem("addition", 10, 5, 3, "right_operand")
        rows = [record(left, str(i), hint_used=True) for i in range(5)]
        rows.append(record(right, "right", correct=True))
        rows += [rows[0], record(right, "other", user_id="user_002"), record(right, "future", day=-1)]
        report = assessment.assess(rows, user_id="user_001", now=NOW)
        self.assertEqual(report["fill_normal"]["count"], 6)
        groups = {g["key"][-1]: g for g in report["fill_groups"]}
        self.assertEqual(groups["left_operand"]["count"], 5)
        self.assertEqual(groups["right_operand"]["count"], 1)
        self.assertTrue(groups["left_operand"]["hint_support"])
        self.assertEqual(report["fill_target"][-1], "left_operand")
        self.assertIsNone(report["target"])

    def test_visual_known_unknown_and_unaided_are_distinct(self):
        rows = [record(identifier="visual", correct=True, visual_help_used=True, hint_used=True),
                record(identifier="no", correct=True, visual_help_used=False),
                record(identifier="old", correct=True, visual_help_used=None)]
        summary = assessment.assess(rows, now=NOW)["fill_normal"]
        self.assertEqual((summary["visual_known_count"], summary["visual_used_count"], summary["visual_unknown_count"]), (2, 1, 1))
        self.assertEqual(summary["visual_rate"], .5)
        self.assertEqual(summary["unaided_count"], 2)

    def test_review_keeps_fill_id_latest_answer_and_same_day_interval(self):
        first = record(identifier="wrong", day=7)
        clean = record(identifier="clean", day=1, correct=True)
        state = review.schedule([first, clean, clean], "user_001", "math", NOW)[first["problem_id"]]
        self.assertTrue(state["latest"]["is_correct"])
        self.assertEqual(state["interval_days"], 3)
        plan = review.plan_math([first, clean], "user_001", now=NOW)
        self.assertNotIn(first["problem_id"], plan["reasons"])
        repeated = record(identifier="again", day=1, correct=True)
        state = review.schedule([clean, repeated], "user_001", "math", NOW)[first["problem_id"]]
        self.assertEqual(state["clean_days"], 1)
        due = review.plan_math([record(identifier="due")], "user_001", now=NOW)
        self.assertEqual(due["items"][0]["problem_id"], first["problem_id"])
        self.assertIn("穴埋め", due["reasons"][first["problem_id"]])
        foreign = record(identifier="foreign", user_id="user_002")
        future = record(identifier="future", day=-1)
        self.assertEqual(review.plan_math([foreign, future], "user_001", now=NOW),
                         review.plan_math([], "user_001", now=NOW))

    def test_adaptive_fill_uses_base_equation_and_isolated_history(self):
        self.assertEqual(adaptive.math_level(make_fill_problem("addition", 10, 3, 3, "left_operand")), 2)
        from fill_blank import fill_pool
        basic = [p for p in fill_pool("addition", 10) if adaptive.math_level(p) == 1][:5]
        rows = [record(p, str(i), correct=True) for i, p in enumerate(basic)]
        plan = adaptive.plan_math(rows, "user_001", count=5, problem_format="fill_blank", now=NOW, rng=random.Random(2))
        self.assertEqual(plan["decisions"]["addition"]["level"], 2)
        self.assertTrue(all(p["problem_format"] == "fill_blank" for p in plan["items"]))
        calc = adaptive.plan_math(rows, "user_001", count=5, now=NOW)
        self.assertEqual(calc["decisions"]["addition"]["level"], 1)
        foreign = [{**r, "user_id": "user_002"} for r in rows]
        self.assertEqual(adaptive.plan_math(foreign, "user_001", problem_format="fill_blank", now=NOW)["decisions"]["addition"]["level"], 1)

    def test_similar_and_parent_analysis_separate_blank_positions(self):
        rows = [record(identifier=str(i), hint_used=True) for i in range(5)]
        plan = parent.adaptive_math(rows, "user_001", now=NOW)
        self.assertTrue(all(p["problem_format"] == "fill_blank" and p["blank_position"] == "left_operand" for p in plan["items"]))
        self.assertEqual(len({p["problem_id"] for p in plan["items"]}), 5)
        self.assertTrue(all("穴埋め" in reason for reason in plan["reasons"].values()))
        clean = record(identifier="latest", day=0, correct=True)
        for p in parent.adaptive_math([rows[0], clean], "user_001", now=NOW)["items"]:
            self.assertNotEqual(p["problem_id"], clean["problem_id"])
        analysis = parent.error_analysis(rows, [], "user_001", now=NOW)
        components = {c["field"]: c for c in analysis["math"]["components"]}
        self.assertEqual(components["is_correct"]["count"], 0)
        self.assertEqual(components["fill_left_operand"]["wrong_count"], 5)
        self.assertEqual(components["fill_right_operand"]["count"], 0)
        self.assertEqual(parent.math_hint_steps(rows[0]), hint_steps(rows[0]))

    def test_school_scope_fill_candidates_and_prior_review_only_for_owner(self):
        scope = school.validate("user_001", "addition_10", "current")
        plan = school.plan_math([], "user_001", scope, problem_format="fill_blank", count=5, now=NOW)
        self.assertTrue(all(p["problem_format"] == "fill_blank" and p["operation"] == "addition" and p["number_range"] == 10 for p in plan["items"]))
        old = record(make_fill_problem("subtraction", 20, 13, 8, "right_operand"))
        foreign = record(make_fill_problem("subtraction", 20, 14, 9, "right_operand"), "other", user_id="user_002")
        pool = school.review_pool([old, foreign], "user_001", scope, "math", NOW)
        identifiers = {p["problem_id"] for p in pool}
        self.assertIn(old["problem_id"], identifiers)
        self.assertNotIn(foreign["problem_id"], identifiers)
        self.assertEqual(review.plan_math([old], "user_001", now=NOW, candidate_pool=pool)["items"][0]["problem_id"], old["problem_id"])
        self.assertEqual(parent.review_forecast([old], "user_001", "math", now=NOW, candidate_pool=pool)["today_count"], 1)


if __name__ == "__main__":
    unittest.main()
