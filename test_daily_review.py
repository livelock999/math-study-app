"""復習の選定と予定を固定日時で検証。DBや画面には依存しません。"""
from copy import deepcopy
from datetime import datetime, timedelta
import unittest
from unittest.mock import patch

import daily_review as review
from learning import make_problem, problem_pool
from japanese_questions import QUESTIONS

NOW = datetime(2026, 10, 8, 12, tzinfo=review.JST)


def math_row(problem=None, day=7, correct=False, hint=False, user="user_001", identifier="a", hour=10, selection="normal"):
    return {**(problem or make_problem("subtraction", 10, 6, 2)), "attempt_id": identifier,
            "datetime": NOW.replace(day=day, hour=hour).isoformat(), "user_id": user,
            "is_correct": correct, "hint_used": hint, "selection_type": selection,
            "attempt_count": 1}


def jp_row(question=None, **kwargs):
    question = question or QUESTIONS[0]
    row = math_row(**kwargs)
    row.pop("problem_id")
    row["correct"] = row.pop("is_correct")
    return {**row, **question, "chain_id": "chain"}


class ScheduleTests(unittest.TestCase):
    def test_wrong_or_hinted_correct_is_tomorrow(self):
        for correct, hint in ((False, False), (True, True)):
            state = next(iter(review.schedule([math_row(correct=correct, hint=hint)], "user_001", "math", NOW).values()))
            self.assertEqual(state["due_date"], NOW.date())
            self.assertEqual(state["interval_days"], 1)

    def test_clean_day_advances_three_then_seven_and_caps(self):
        rows = [math_row(day=1, correct=True, identifier="a"), math_row(day=4, correct=True, identifier="b"), math_row(day=8, correct=True, identifier="c")]
        first = next(iter(review.schedule(rows[:1], "user_001", "math", NOW).values()))
        second = next(iter(review.schedule(rows[:2], "user_001", "math", NOW).values()))
        third = next(iter(review.schedule(rows, "user_001", "math", NOW).values()))
        self.assertEqual((first["interval_days"], second["interval_days"], third["interval_days"]), (3, 7, 7))
        self.assertEqual(third["due_date"], NOW.date() + timedelta(days=7))

    def test_same_day_multiple_correct_only_one_stage(self):
        rows = [math_row(day=7, correct=True, identifier=str(i), hour=i+1) for i in range(6)]
        state = next(iter(review.schedule(rows, "user_001", "math", NOW).values()))
        self.assertEqual((state["interval_days"], state["clean_days"]), (3, 1))

    def test_same_day_wrong_then_correct_resets_but_latest_solved(self):
        rows = [math_row(day=1, correct=True, identifier="a"), math_row(day=7, identifier="b"), math_row(day=7, correct=True, identifier="c", hour=11)]
        state = next(iter(review.schedule(rows, "user_001", "math", NOW).values()))
        self.assertEqual(state["interval_days"], 1)
        self.assertTrue(state["latest"]["is_correct"])
        plan = review.plan_math(rows, "user_001", now=NOW, count=1)
        self.assertEqual(next(iter(plan["reasons"].values())), "正解した問題をもう一度確認")

    def test_wrong_or_hint_after_two_clean_days_resets(self):
        for last in (math_row(day=7, identifier="c"), math_row(day=7, correct=True, hint=True, identifier="c")):
            rows = [math_row(day=1, correct=True, identifier="a"), math_row(day=4, correct=True, identifier="b"), last]
            state = next(iter(review.schedule(rows, "user_001", "math", NOW).values()))
            self.assertEqual((state["interval_days"], state["clean_days"]), (1, 0))

    def test_unknown_hint_does_not_assume_clean(self):
        state = next(iter(review.schedule([math_row(correct=True, hint=None)], "user_001", "math", NOW).values()))
        self.assertEqual((state["interval_days"], state["clean_days"]), (1, 0))

    def test_future_and_other_user_excluded(self):
        rows = [math_row(user="user_002"), math_row(day=9), math_row(day=8, hour=13)]
        self.assertEqual(review.schedule(rows, "user_001", "math", NOW), {})

    def test_invalid_dates_excluded_and_naive_history_jst(self):
        row = math_row()
        row["datetime"] = "broken"
        valid = math_row(identifier="b")
        valid["datetime"] = "2026-10-07T23:30:00"
        state = next(iter(review.schedule([row, valid], "user_001", "math", NOW).values()))
        self.assertEqual(state["due_date"], NOW.date())

    def test_utc_date_boundary_and_exact_now(self):
        row = math_row()
        row["datetime"] = "2026-10-07T15:00:00+00:00"
        state = next(iter(review.schedule([row], "user_001", "math", NOW).values()))
        self.assertEqual(state["due_date"], NOW.date() + timedelta(days=1))
        row["datetime"] = NOW.isoformat()
        self.assertTrue(review.schedule([row], "user_001", "math", NOW))

    def test_dedup_save_retry_no_extra_stage(self):
        row = math_row(correct=True)
        self.assertEqual(review.schedule([row]*5, "user_001", "math", NOW), review.schedule([row], "user_001", "math", NOW))

    def test_latest_is_deterministic_tied_timestamp(self):
        a = math_row(identifier="a")
        z = math_row(identifier="z", correct=True)
        for rows in ([a,z], [z,a]):
            state = next(iter(review.schedule(rows, "user_001", "math", NOW).values()))
            self.assertEqual(state["latest"]["attempt_id"], "z")

    def test_chains_and_selection_types_share_material_schedule(self):
        rows = [jp_row(day=1, correct=True), jp_row(day=4, correct=True, identifier="b", selection="review")]
        rows[1]["chain_id"] = "other_chain"
        state = next(iter(review.schedule(rows, "user_001", "japanese", NOW).values()))
        self.assertEqual(state["interval_days"], 7)
        rows[1]["review_due_at"] = "2099-01-01T00:00:00+09:00"
        self.assertEqual(next(iter(review.schedule(rows, "user_001", "japanese", NOW).values()))["due_date"].day, 11)


class SelectionTests(unittest.TestCase):
    def test_priority_wrong_then_hint_then_solved(self):
        pool = problem_pool("subtraction", 10)[5:8]
        rows = [math_row(pool[0], day=7), math_row(pool[1], day=7, correct=True, hint=True, identifier="b"), math_row(pool[2], day=1, correct=True, identifier="c")]
        plan = review.plan_math(rows, "user_001", now=NOW)
        self.assertEqual([q["problem_id"] for q in plan["items"][:3]], [q["problem_id"] for q in pool])

    def test_old_error_does_not_override_later_clean(self):
        problem = make_problem("addition", 10, 4, 2)
        rows = [math_row(problem, day=1), math_row(problem, day=7, correct=True, identifier="b")]
        plan = review.plan_math(rows, "user_001", now=NOW, count=1000)
        self.assertNotIn(problem["problem_id"], plan["reasons"])

    def test_selected_range_exact_and_no_duplicate(self):
        old = math_row(make_problem("addition", 20, 4, 2))
        plan = review.plan_math([old], "user_001", limit=10, now=NOW)
        self.assertEqual(len(plan["items"]), 5)
        self.assertTrue(all(q["number_range"] == 10 for q in plan["items"]))
        self.assertNotIn(old["problem_id"], plan["reasons"])
        self.assertEqual(len(set(plan["reasons"])), 5)

    def test_same_operands_other_range_schedule_kept_separate(self):
        ten = make_problem("addition", 10, 4, 2)
        twenty = make_problem("addition", 20, 4, 2)
        rows = [math_row(ten), math_row(twenty, correct=True, identifier="b")]
        states = review.schedule(rows, "user_001", "math", NOW)
        self.assertEqual(states[ten["problem_id"]]["interval_days"], 1)
        self.assertEqual(states[twenty["problem_id"]]["interval_days"], 3)

    def test_plan_other_user_history_has_no_effect(self):
        problem = make_problem("subtraction", 10, 9, 3)
        self.assertEqual(review.plan_math([math_row(problem, user="user_002")], "user_001", now=NOW),
                         review.plan_math([], "user_001", now=NOW))

    def test_math_weak_category_precedes_basic(self):
        problem = make_problem("subtraction", 10, 9, 3)
        rows = [math_row(problem, identifier=str(i)) for i in range(5)]
        plan = review.plan_math(rows, "user_001", now=NOW)
        self.assertEqual(plan["items"][0]["problem_id"], problem["problem_id"])
        self.assertTrue(all(q["operation"] == "subtraction" for q in plan["items"]))
        self.assertIn("苦手分野", list(plan["reasons"].values())[1])

    def test_due_word_problem_is_current_generated_material(self):
        from words import make_word_problem
        question = make_word_problem("decrease", 10, 6, 2)
        row = math_row(question)
        row["question_text"] = "old snapshot"
        plan = review.plan_math([row], "user_001", now=NOW, count=1)
        self.assertEqual(plan["items"][0], question)

    def test_hint_reason_does_not_follow_old_hint(self):
        rows = [jp_row(day=1, correct=True, hint=True), jp_row(day=4, correct=True, identifier="b")]
        plan = review.plan_japanese(rows, "user_001", now=NOW, count=1)
        self.assertEqual(next(iter(plan["reasons"].values())), "正解した問題をもう一度確認")

    def test_no_history_fills_basic(self):
        for plan in (review.plan_math([], "user_001", now=NOW), review.plan_japanese([], "user_001", now=NOW)):
            self.assertEqual(len(plan["items"]), 5)
            self.assertEqual(set(plan["reasons"].values()), {"基本問題で確認"})

    def test_japanese_level_limit_in_mix(self):
        hard = next(q for q in QUESTIONS if q["category"] == "particles" and q["level"] == 3)
        plan = review.plan_japanese([jp_row(hard)], "user_001", particle_level=1, now=NOW, count=200)
        self.assertNotIn(hard["question_id"], plan["reasons"])
        self.assertTrue(all(q["category"] != "particles" or q["level"] <= 1 for q in plan["items"]))

    def test_fewer_and_zero_have_message(self):
        with patch("japanese_questions.QUESTIONS", QUESTIONS[:2]):
            few = review.plan_japanese([], "user_001", now=NOW)
            self.assertEqual(len(few["items"]), 2)
            self.assertIn("2問", few["message"])
            rows = [jp_row(q, day=8, identifier=str(i), correct=True) for i,q in enumerate(QUESTIONS[:2])]
            empty = review.plan_japanese(rows, "user_001", now=NOW)
            self.assertEqual(empty["items"], [])
            self.assertTrue(empty["message"])

    def test_same_day_start_does_not_reserve_or_change_schedule(self):
        rows = [jp_row(day=7)]
        snapshot = deepcopy(rows)
        first = review.plan_japanese(rows, "user_001", now=NOW)
        self.assertEqual(first, review.plan_japanese(rows, "user_001", now=NOW))
        self.assertEqual(rows, snapshot)

    def test_latest_current_catalogue_not_snapshot(self):
        old = jp_row()
        old["text"] = "obsolete"
        old["choices"] = ["obsolete"]
        plan = review.plan_japanese([old], "user_001", now=NOW, count=1)
        self.assertEqual(plan["items"][0], QUESTIONS[0])

    def test_weak_initial_only_and_basic_fallback(self):
        rows = [jp_row(QUESTIONS[0], identifier=str(i)) for i in range(5)]
        # Same known wrong question is due first, then fresh words in weak category.
        plan = review.plan_japanese(rows, "user_001", now=NOW)
        self.assertTrue(all(q["category"] == "words" for q in plan["items"]))
        self.assertIn("苦手分野", list(plan["reasons"].values())[1])
        for row in rows:
            row["selection_type"] = "review"
        plan = review.plan_japanese(rows, "user_001", now=NOW)
        self.assertEqual(list(plan["reasons"].values())[1], "基本問題で確認")

    def test_invalid_arguments(self):
        with self.assertRaises(ValueError): review.plan_math([], "user_001", limit=30)
        with self.assertRaises(ValueError): review.plan_japanese([], "user_001", particle_level=4)
        with self.assertRaises(ValueError): review.plan_math([], "user_001", count=0)
        with self.assertRaises(ValueError): review.schedule([], "user_001", "other")


class DailyBudgetTests(unittest.TestCase):
    def test_two_saved_reviews_leave_three_with_notice(self):
        for subject, row_factory, planner in (("math", math_row, review.plan_math),
                                             ("japanese", jp_row, review.plan_japanese)):
            rows = [row_factory(day=8, identifier=str(i), selection="review") for i in range(2)]
            plan = planner(rows, "user_001", now=NOW)
            self.assertEqual((plan["daily_done"], plan["daily_remaining"]), (2, 3))
            self.assertEqual(len(plan["items"]), 3)
            self.assertIn("あと3問", plan["message"])

    def test_five_saved_reviews_stop_both_subjects_and_any_requested_count(self):
        for row_factory, planner in ((math_row, review.plan_math), (jp_row, review.plan_japanese)):
            rows = [row_factory(day=8, identifier=str(i), selection="review") for i in range(5)]
            plan = planner(rows, "user_001", count=100, now=NOW)
            self.assertEqual(plan["items"], [])
            self.assertEqual(plan["daily_remaining"], 0)
            self.assertIn("きょうは5問", plan["message"])

    def test_retry_normal_and_weak_area_do_not_consume_budget(self):
        rows = [math_row(day=8, identifier=str(i), selection=selection)
                for i, selection in enumerate(("review_retry", "retry", "normal", "weak_area"))]
        self.assertEqual(review.daily_budget(rows, "user_001", "math", NOW), {"daily_done": 0, "daily_remaining": 5})
        self.assertEqual(len(review.plan_math(rows, "user_001", now=NOW)["items"]), 5)

    def test_duplicate_attempts_count_once_other_user_future_and_yesterday_excluded(self):
        saved = math_row(day=8, selection="review", identifier="saved")
        rows = [saved, dict(saved), math_row(day=8, selection="review", user="user_002", identifier="other"),
                math_row(day=9, selection="review", identifier="future"),
                math_row(day=8, hour=13, selection="review", identifier="later"),
                math_row(day=7, selection="review", identifier="yesterday")]
        self.assertEqual(review.daily_budget(rows, "user_001", "math", NOW), {"daily_done": 1, "daily_remaining": 4})

    def test_subject_and_range_budget_separate_only_by_subject(self):
        math = math_row(make_problem("addition", 20, 8, 9), day=8, selection="review")
        jp = jp_row(day=8, selection="review", identifier="jp")
        mixed = [math, jp]
        self.assertEqual(review.daily_budget(mixed, "user_001", "math", NOW)["daily_done"], 1)
        self.assertEqual(review.daily_budget(mixed, "user_001", "japanese", NOW)["daily_done"], 1)
        # 数の範囲を変更しても算数の一日上限は増やさない。
        self.assertEqual(len(review.plan_math([math], "user_001", limit=10, now=NOW)["items"]), 4)

    def test_jst_boundary_and_next_day_reset(self):
        before = math_row(selection="review", identifier="before")
        before["datetime"] = "2026-10-07T14:59:59+00:00"
        after = math_row(selection="review", identifier="after")
        after["datetime"] = "2026-10-07T15:00:00+00:00"
        budget = review.daily_budget([before, after], "user_001", "math", NOW)
        self.assertEqual(budget["daily_done"], 1)
        tomorrow = NOW + timedelta(days=1)
        self.assertEqual(review.daily_budget([before, after], "user_001", "math", tomorrow)["daily_remaining"], 5)

    def test_same_day_preview_start_does_not_spend_budget(self):
        rows = [math_row(day=8, selection="review", identifier="saved")]
        original = deepcopy(rows)
        first = review.plan_math(rows, "user_001", now=NOW)
        self.assertEqual(first, review.plan_math(rows, "user_001", now=NOW))
        self.assertEqual(first["daily_remaining"], 4)
        self.assertEqual(rows, original)

    def test_count_cannot_exceed_daily_cap_and_invalid_count_still_rejected(self):
        self.assertEqual(len(review.plan_math([], "user_001", count=100, now=NOW)["items"]), 5)
        rows = [math_row(day=8, identifier=str(i), selection="review") for i in range(5)]
        with self.assertRaises(ValueError):
            review.plan_math(rows, "user_001", count=0, now=NOW)
        with self.assertRaises(ValueError):
            review.daily_budget([], "user_001", "invalid", NOW)


if __name__ == "__main__":
    unittest.main()
