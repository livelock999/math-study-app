"""3つの数の独立分析・復習・類題・難易度・学校単元を検証する。"""
from datetime import datetime, timedelta
import random
import unittest

import adaptive_difficulty as adaptive
import assessment
import daily_review as review
import learning
import parent_insights as parent
import school_scope as school
from three_numbers import PATTERNS, make_three_problem, mode_pool, hint_steps

NOW = datetime(2026, 10, 8, 12, tzinfo=review.JST)


def row(problem=None, identifier="first", day=1, correct=False, selection="normal", count=1, **updates):
    problem = problem or make_three_problem("addition", "subtraction", 10, 2, 3, 1)
    record = learning.make_attempt(problem, "user_001", identifier, 1, selection,
                                   problem["correct_answer"] if correct else 99, 2, count)
    return {**record, "attempt_id": identifier, "datetime": (NOW - timedelta(days=day)).isoformat(), **updates}


class ThreeLearningTests(unittest.TestCase):
    def test_independent_initial_retry_latest_and_review_with_four_patterns(self):
        old = row(learning.make_problem("addition", 10, 2, 3), "calc", correct=True)
        before = assessment.assess([old], now=NOW)
        problems = [make_three_problem(first, second, 10, 4, 1, 1) for first, second in PATTERNS]
        firsts = [row(p, str(i), hint_used=True) for i, p in enumerate(problems)]
        retries = [row(problems[0], "retry", day=0, correct=True, selection="retry", count=2)]
        due = row(problems[0], "review", day=0, correct=True, selection="review")
        report = assessment.assess([old] + firsts + retries + [due], now=NOW)
        for key in before:
            if not key.startswith("three_"):
                self.assertEqual(before[key], report[key], key)
        self.assertEqual(report["three_normal"]["count"], 4)
        self.assertEqual(report["three_normal"]["hint_rate"], 1)
        self.assertEqual(report["three_retry"]["rate"], 1)
        self.assertEqual(report["three_latest"]["count"], 4)
        self.assertEqual(report["three_latest"]["correct"], 1)
        self.assertEqual(report["three_review"]["count"], 1)
        self.assertEqual(len(report["three_groups"]), 4)
        self.assertIsNone(report["target"])

    def test_initial_group_weakness_and_learner_future_duplicate_exclusion(self):
        rows = [row(identifier=str(i), hint_used=True) for i in range(5)]
        rows += [rows[0], row(identifier="other", user_id="user_002"), row(identifier="future", day=-1)]
        result = assessment.assess_three(rows, user_id="user_001", now=NOW)
        self.assertEqual(result["three_normal"]["count"], 5)
        self.assertEqual(result["three_target"][:2], ("addition", "subtraction"))
        self.assertTrue(result["three_groups"][0]["hint_support"])

    def test_review_latest_same_day_streak_id_and_reason(self):
        first = row(day=7)
        clean = row(identifier="clean", correct=True)
        state = review.schedule([first, clean, clean], "user_001", "math", NOW)[first["problem_id"]]
        self.assertEqual(state["interval_days"], 3)
        self.assertTrue(state["latest"]["is_correct"])
        self.assertNotIn(first["problem_id"], review.plan_math([first, clean], "user_001", now=NOW)["reasons"])
        repeated = row(identifier="repeat", correct=True)
        state = review.schedule([clean, repeated], "user_001", "math", NOW)[first["problem_id"]]
        self.assertEqual(state["clean_days"], 1)
        next_day = row(identifier="next", day=0, correct=True)
        self.assertEqual(review.schedule([clean, next_day], "user_001", "math", NOW)[first["problem_id"]]["interval_days"], 7)
        plan = review.plan_math([row()], "user_001", now=NOW)
        self.assertEqual(plan["items"][0]["problem_id"], first["problem_id"])
        self.assertIn("3つの数", plan["reasons"][first["problem_id"]])

    def test_adaptive_checks_intermediate_third_special_and_isolates_patterns(self):
        self.assertEqual(adaptive.math_level(make_three_problem("addition", "subtraction", 10, 3, 3, 5)), 2)
        self.assertEqual(adaptive.math_level(make_three_problem("subtraction", "addition", 10, 3, 3, 6)), 2)
        self.assertEqual(adaptive.math_level(make_three_problem("addition", "subtraction", 20, 8, 5, 4)), 3)
        basics = [p for p in mode_pool("addition", 10) if adaptive.math_level(p) == 1][:5]
        records = [row(p, str(i), correct=True) for i, p in enumerate(basics)]
        plan = adaptive.plan_math(records, "user_001", mode="mix", count=10,
                                  problem_format="three_numbers", now=NOW, rng=random.Random(5))
        self.assertEqual(plan["decisions"]["addition_addition"]["level"], 2)
        self.assertEqual(plan["decisions"]["addition_subtraction"]["level"], 1)
        self.assertEqual(len({p["problem_id"] for p in plan["items"]}), 10)
        self.assertEqual({(p["operation"], p["second_operation"]) for p in plan["items"]}, set(PATTERNS))
        self.assertEqual(adaptive.plan_math(records, "user_001", now=NOW)["decisions"]["addition"]["level"], 1)
        foreign = [{**r, "user_id": "user_002"} for r in records]
        self.assertEqual(adaptive.plan_math(foreign, "user_001", problem_format="three_numbers", now=NOW)["decisions"]["addition_addition"]["level"], 1)

    def test_math_keys_and_similar_do_not_mix_second_operation_or_special(self):
        first = make_three_problem("addition", "subtraction", 20, 8, 5, 4)
        no_borrow = make_three_problem("addition", "subtraction", 20, 8, 5, 2)
        other_pattern = make_three_problem("addition", "addition", 20, 8, 5, 4)
        self.assertNotEqual(review._math_key(first), review._math_key(no_borrow))
        self.assertNotEqual(review._math_key(first), review._math_key(other_pattern))
        plan = parent.adaptive_math([row(first)], "user_001", limit=20, now=NOW)
        self.assertTrue(all(review._math_key(p) == review._math_key(first) for p in plan["items"]))
        self.assertTrue(all("3つの数" in r for r in plan["reasons"].values()))
        result = parent.error_analysis([row(first)], [], "user_001", NOW)
        components = {c["field"]: c for c in result["math"]["components"]}
        self.assertEqual(components["is_correct"]["count"], 0)
        self.assertEqual(components["three_addition_subtraction"]["wrong_count"], 1)
        self.assertEqual(parent.math_hint_steps(first), hint_steps(first))

    def test_school_base_never_introduces_unlearned_second_operation(self):
        for unit in ("addition_10", "subtraction_10", "addition_20_none", "subtraction_20_none",
                     "addition_20_with", "subtraction_20_with", "mix_20"):
            scope = school.validate("user_001", unit, "current")
            mode, limit, special = school.math_settings(scope, "addition", 10, "auto")
            plan = school.plan_math([], "user_001", scope, problem_format="three_numbers", count=5, now=NOW)
            pool = school.review_pool([], "user_001", scope, "math", NOW)
            for p in plan["items"] + [p for p in pool if p["problem_format"] == "three_numbers"]:
                self.assertEqual(p["number_range"], limit)
                if mode != "mix":
                    self.assertEqual((p["operation"], p["second_operation"]), (mode, mode))
                if special != "auto":
                    self.assertEqual(bool(p["carry"] or p["borrowing"]), special == "with")

    def test_school_review_keeps_prior_only_owned_ids_and_forecast(self):
        scope = school.validate("user_001", "addition_10", "current")
        prior = row(make_three_problem("subtraction", "addition", 20, 13, 8, 4))
        foreign = row(make_three_problem("subtraction", "addition", 20, 14, 8, 4), "other", user_id="user_002")
        pool = school.review_pool([prior, foreign], "user_001", scope, "math", NOW)
        ids = {q["problem_id"] for q in pool}
        self.assertIn(prior["problem_id"], ids)
        self.assertNotIn(foreign["problem_id"], ids)
        self.assertEqual(review.plan_math([prior], "user_001", now=NOW, candidate_pool=pool)["items"][0]["problem_id"], prior["problem_id"])
        self.assertEqual(parent.review_forecast([prior], "user_001", "math", now=NOW, candidate_pool=pool)["today_count"], 1)


if __name__ == "__main__":
    unittest.main()
