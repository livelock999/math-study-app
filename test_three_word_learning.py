"""3数量文章題の時系列判断・独立分析・復習と学校範囲の連携。"""
from datetime import datetime, timedelta
import random
import unittest

import adaptive_difficulty as adaptive
import assessment
import daily_review as review
import learning
import parent_insights as parent
import school_scope as school
from three_word import STORIES, make_three_word_problem, mode_pool, hint_steps

NOW = datetime(2026, 10, 8, 12, tzinfo=review.JST)


def row(problem=None, identifier="first", day=1, answer=None, selection="normal", count=1, **updates):
    problem = problem or make_three_word_problem("increase_then_decrease", 10, 2, 3, 1)
    args = {"selected_operation": problem["operation"], "selected_second_operation": problem["second_operation"],
            "equation_left": problem["left_operand"], "equation_right": problem["right_operand"],
            "equation_third": problem["third_operand"]}
    for key in list(args):
        if key in updates:
            args[key] = updates.pop(key)
    result = learning.make_attempt(problem, "user_001", identifier, 1, selection,
                                   problem["correct_answer"] if answer is None else answer, 2, count, **args)
    return {**result, "attempt_id": identifier, "datetime": (NOW - timedelta(days=day)).isoformat(), **updates}


class ThreeWordLearningTests(unittest.TestCase):
    def test_independent_initial_retry_latest_review_and_full_word_judgments(self):
        from three_numbers import make_three_problem
        from words import make_word_problem
        old = learning.make_attempt(make_three_problem("addition", "subtraction", 10, 2, 3, 1),
                                    "user_001", "old", 1, "normal", 4, 2, 1)
        old_word = learning.make_attempt(make_word_problem("increase", 10, 2, 3),
                                         "user_001", "old_word", 1, "normal", 5, 2, 1, selected_operation="addition")
        for previous in (old, old_word):
            previous["datetime"] = (NOW - timedelta(days=1)).isoformat()
        before = assessment.assess([old, old_word], now=NOW)
        self.assertEqual(before["three_normal"]["count"], 1)
        self.assertEqual(before["word_normal"]["count"], 1)
        wrong_operation = row(identifier="op", selected_second_operation="addition", answer=6)
        wrong_order = row(identifier="order", equation_left=3, equation_right=2, answer=4)
        retry = row(identifier="retry", day=0, selection="retry", count=2)
        due = row(identifier="review", day=0, selection="review")
        result = assessment.assess([old, old_word, wrong_operation, wrong_order, retry, due], now=NOW)
        for key in before:
            if not key.startswith("three_word_"):
                self.assertEqual(before[key], result[key], key)
        summary = result["three_word_normal"]
        self.assertEqual(summary["count"], 2)
        self.assertEqual(summary["rate"], 0)
        self.assertEqual(summary["operation_rate"], .5)
        self.assertEqual(summary["equation_rate"], .5)
        self.assertEqual(summary["calculation_rate"], 1)
        self.assertEqual(result["three_word_retry"]["rate"], 1)
        self.assertEqual(result["three_word_latest"]["count"], 1)
        self.assertEqual(result["three_word_latest"]["rate"], 1)
        self.assertEqual(result["three_word_review"]["count"], 1)

    def test_groups_story_special_and_learner_future_retry_dedup(self):
        records = [row(identifier=str(i), answer=99, hint_used=True) for i in range(5)]
        records += [records[0], row(identifier="other", answer=99, user_id="user_002"), row(identifier="future", day=-1)]
        result = assessment.assess_three_word(records, user_id="user_001", now=NOW)
        self.assertEqual(result["three_word_normal"]["count"], 5)
        self.assertEqual(result["three_word_target"][0], "increase_then_decrease")
        self.assertTrue(result["three_word_groups"][0]["hint_support"])
        patterns = [row(make_three_word_problem(story, 10, 4, 1, 1), story) for story in STORIES]
        self.assertEqual(len(assessment.assess_three_word(patterns, now=NOW)["three_word_groups"]), 4)
        unknown = row(identifier="unknown", dont_know_used=True, operation_selection_correct=None,
                      equation_correct=None, calculation_correct=None)
        summary = assessment.assess_three_word([unknown], now=NOW)["three_word_normal"]
        self.assertIsNone(summary["operation_rate"])
        self.assertIsNone(summary["equation_rate"])
        self.assertIsNone(summary["calculation_rate"])

    def test_review_latest_same_day_and_same_id_intervals(self):
        wrong = row(identifier="wrong", day=7, answer=99)
        clean = row(identifier="clean")
        state = review.schedule([wrong, clean, clean], "user_001", "math", NOW)[wrong["problem_id"]]
        self.assertTrue(state["latest"]["is_correct"])
        self.assertEqual(state["interval_days"], 3)
        self.assertNotIn(wrong["problem_id"], review.plan_math([wrong, clean], "user_001", now=NOW)["reasons"])
        another = row(identifier="repeat")
        self.assertEqual(review.schedule([clean, another], "user_001", "math", NOW)[wrong["problem_id"]]["clean_days"], 1)
        today = row(identifier="today", day=0)
        self.assertEqual(review.schedule([clean, today], "user_001", "math", NOW)[wrong["problem_id"]]["interval_days"], 7)
        plan = review.plan_math([row(answer=99)], "user_001", now=NOW)
        self.assertEqual(plan["items"][0]["problem_id"], wrong["problem_id"])
        self.assertIn("文章題", plan["reasons"][wrong["problem_id"]])

    def test_adaptive_positive_three_quantities_can_advance_and_isolate_calculation(self):
        basics = [p for p in mode_pool("addition", 10) if adaptive.math_level(p) == 1]
        self.assertGreaterEqual(len(basics), 5)
        records = [row(p, str(i)) for i, p in enumerate(basics[:5])]
        plan = adaptive.plan_math(records, "user_001", mode="mix", problem_format="three_word_problem", now=NOW, rng=random.Random(1))
        self.assertEqual(plan["decisions"]["addition_addition"]["level"], 2)
        self.assertEqual(plan["decisions"]["addition_subtraction"]["level"], 1)
        self.assertEqual(len({p["problem_id"] for p in plan["items"]}), 10)
        self.assertTrue(all(p["problem_format"] == "three_word_problem" for p in plan["items"]))
        calc = adaptive.plan_math(records, "user_001", problem_format="three_numbers", now=NOW)
        self.assertEqual(calc["decisions"]["addition_addition"]["level"], 1)
        self.assertEqual(adaptive.math_level(make_three_word_problem("increase_then_decrease", 10, 3, 4, 6)), 2)
        self.assertEqual(adaptive.math_level(make_three_word_problem("increase_then_decrease", 20, 8, 5, 4)), 3)

    def test_similar_story_second_operation_special_and_parent_components(self):
        problem = make_three_word_problem("increase_then_decrease", 20, 8, 5, 4)
        wrong = row(problem, answer=17, selected_second_operation="addition")
        plan = parent.adaptive_math([wrong], "user_001", limit=20, now=NOW)
        self.assertTrue(all(review._math_key(p) == review._math_key(problem) for p in plan["items"]))
        self.assertTrue(all("文章題" in reason for reason in plan["reasons"].values()))
        result = parent.error_analysis([wrong], [], "user_001", NOW)
        components = {c["field"]: c for c in result["math"]["components"]}
        self.assertEqual(components["operation_selection_correct"]["count"], 0)
        self.assertEqual(components["three_word_operation"]["wrong_count"], 1)
        self.assertEqual(components["three_word_equation"]["wrong_count"], 0)
        self.assertEqual(components["three_word_calculation"]["wrong_count"], 0)
        self.assertEqual(parent.math_hint_steps(problem), hint_steps(problem))

    def test_school_scope_both_operators_and_attributes_for_new_candidates(self):
        for unit in ("addition_10", "subtraction_10", "addition_20_none", "subtraction_20_none", "addition_20_with", "subtraction_20_with", "mix_20"):
            scope = school.validate("user_001", unit, "current")
            mode, limit, special = school.math_settings(scope, "addition", 10, "auto")
            plan = school.plan_math([], "user_001", scope, problem_format="three_word_problem", count=5, now=NOW)
            pool = school.review_pool([], "user_001", scope, "math", NOW)
            for q in plan["items"] + [q for q in pool if q["problem_format"] == "three_word_problem"]:
                self.assertEqual(q["number_range"], limit)
                if mode != "mix":
                    self.assertEqual((q["operation"], q["second_operation"]), (mode, mode))
                if special != "auto":
                    self.assertEqual(bool(q["carry"] or q["borrowing"]), special == "with")

    def test_school_past_review_ids_only_owned_history_and_forecast(self):
        scope = school.validate("user_001", "addition_10", "current")
        old = row(make_three_word_problem("decrease_then_increase", 20, 13, 8, 4), answer=99)
        foreign = row(make_three_word_problem("decrease_then_increase", 20, 14, 8, 4), "other", user_id="user_002")
        pool = school.review_pool([old, foreign], "user_001", scope, "math", NOW)
        ids = {q["problem_id"] for q in pool}
        self.assertIn(old["problem_id"], ids)
        self.assertNotIn(foreign["problem_id"], ids)
        self.assertEqual(review.plan_math([old], "user_001", now=NOW, candidate_pool=pool)["items"][0]["problem_id"], old["problem_id"])
        self.assertEqual(parent.review_forecast([old], "user_001", "math", now=NOW, candidate_pool=pool)["today_count"], 1)


if __name__ == "__main__":
    unittest.main()
