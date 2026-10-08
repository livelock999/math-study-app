"""保護者のレポート・予定・類題・ヒント・CSVの境界検証。"""

import csv
from datetime import datetime, timedelta
import io
import unittest

import learning
import japanese
from daily_review import JST
from japanese_questions import QUESTIONS
from parent_insights import (adaptive_japanese, adaptive_math, csv_export, error_analysis,
                             japanese_hint_steps, math_hint_steps, review_forecast, weekly_report)
from words import make_word_problem


NOW = datetime(2026, 10, 8, 12, tzinfo=JST)
USER = "user_001"


def math_row(identifier="a", day=0, correct=True, hint=False, selection="normal", problem=None):
    problem = problem or learning.make_problem("subtraction", 10, 8, 3)
    row = learning.make_attempt(problem, USER, "session", 1, selection,
                                problem["correct_answer"] if correct else 99, 4, 1,
                                selected_operation=problem["operation"] if problem["problem_format"] == "word_problem" else None,
                                hint_used=hint)
    row.update(attempt_id=identifier, datetime=(NOW - timedelta(days=day)).isoformat())
    return row


def jp_row(identifier="j", day=0, correct=True, hint=False, selection="normal", question=None):
    question = question or QUESTIONS[0]
    answer = question["answer"] if correct else (question["answer"] + 1) % len(question["choices"])
    row = japanese.make_record(question, USER, "session", 1, selection, answer, 4, 1,
                               "chain", hint_used=hint)
    row.update(attempt_id=identifier, datetime=(NOW - timedelta(days=day)).isoformat())
    return row


class WeeklyReportTests(unittest.TestCase):
    def test_seven_day_boundaries_initial_and_prior_comparison(self):
        rows = [math_row("a", 6, False), math_row("b", 0), math_row("prior", 7),
                math_row("earlier", 14, False), math_row("review", 0, True, selection="review"),
                math_row("review_retry", 0, True, selection="review_retry"),
                math_row("adaptive", 0, True, selection="weak_area")]
        report = weekly_report(rows, [], USER, NOW)
        subject = report["subjects"]["math"]
        self.assertEqual((report["start"], report["end"]), ("2026-10-02", "2026-10-08"))
        self.assertEqual(subject["initial"]["count"], 2)
        self.assertEqual(subject["initial"]["rate"], .5)
        self.assertEqual(subject["previous_initial"]["count"], 1)
        self.assertEqual(subject["initial_rate_change"], -.5)
        self.assertEqual(subject["review"]["count"], 1)
        self.assertEqual(subject["review_retry"]["count"], 1)
        self.assertEqual(subject["adaptive"]["count"], 1)

    def test_japanese_initial_retries_and_review_separate(self):
        first = jp_row("first", 1, False)
        retry = jp_row("retry", 0, selection="retry")
        retry["attempt_count"] = 2
        rows = [first, retry, jp_row("adaptive", 0, selection="weak_area"),
                jp_row("review", 0, selection="review"), jp_row("rr", 0, selection="review_retry")]
        subject = weekly_report([], rows, USER, NOW)["subjects"]["japanese"]
        self.assertEqual(subject["initial"]["count"], 2)
        self.assertEqual(subject["initial"]["rate"], .5)
        self.assertEqual(subject["all"]["count"], 5)
        self.assertEqual(subject["review"]["count"], 1)

    def test_filter_learner_future_duplicate_and_invalid_date(self):
        good = math_row()
        other = dict(math_row("other"), user_id="user_002")
        future = math_row("future", -1)
        invalid = dict(math_row("invalid"), datetime="bad date")
        result = weekly_report([future, other, good, dict(good), invalid], [], USER, NOW)
        self.assertEqual(result["subjects"]["math"]["all"]["count"], 1)

    def test_jst_midnight_and_current_time_cutoff(self):
        rows = [dict(math_row("utc"), datetime="2026-10-01T15:00:00+00:00"),
                dict(math_row("oldutc"), datetime="2026-10-01T14:59:59+00:00"),
                dict(math_row("futurehours"), datetime="2026-10-08T12:00:01+09:00")]
        result = weekly_report(rows, [], USER, NOW)
        self.assertEqual(result["subjects"]["math"]["all"]["count"], 1)
        self.assertEqual(result["attendance"][0]["count"], 1)

    def test_hint_known_counts_and_stages(self):
        rows = [dict(math_row("a", hint=True), hint_level=3),
                dict(math_row("b"), hint_level=0), dict(math_row("c"), hint_used=None)]
        summary = weekly_report(rows, [], USER, NOW)["subjects"]["math"]["initial"]
        self.assertEqual(summary["hint_known_count"], 2)
        self.assertEqual(summary["hint_rate"], .5)
        self.assertEqual(summary["hint_unknown_count"], 1)
        self.assertEqual(summary["max_hint_level"], 3)
        self.assertEqual(summary["hint_levels"], {0: 1, 3: 1})

    def test_growth_transition_not_repeated_old_success(self):
        p1 = learning.make_problem("addition", 10, 1, 2)
        p2 = learning.make_problem("addition", 10, 1, 3)
        rows = [math_row("oldbad", 10, False, problem=p1), math_row("recentgood", 2, problem=p1),
                math_row("recentgoodagain", 0, problem=p1), math_row("olderbad", 20, False, problem=p2),
                math_row("oldergood", 15, problem=p2), math_row("ordinary", 0, problem=p2)]
        growth = weekly_report(rows, [], USER, NOW)["growth"]
        self.assertEqual(len(growth), 1)
        self.assertEqual(growth[0]["problem_id"], p1["problem_id"])
        self.assertEqual(growth[0]["after_at"], rows[1]["datetime"])

    def test_growth_requires_known_unhinted_latest_success(self):
        rows = [math_row("bad", 1, hint=True), dict(math_row("unknown"), hint_used=None)]
        self.assertEqual(weekly_report(rows, [], USER, NOW)["growth"], [])
        rows.append(math_row("good", selection="review"))
        # Unknown assistance is not proof of a new transition from the old hinted answer.
        self.assertEqual(weekly_report(rows, [], USER, NOW)["growth"], [])

    def test_goals_count_effort_with_wrong_answers_but_not_retries(self):
        rows = [math_row("day1", 2, False), math_row("day2", 1, False),
                math_row("day3", 0, False), math_row("r1", 0, False, selection="retry"),
                math_row("r2", 0, False, selection="review_retry")]
        result = weekly_report(rows, [], USER, NOW, {"weekly_days": 3, "daily_questions": 2})
        self.assertTrue(result["goals"]["weekly_goal_met"])
        self.assertEqual(result["goals"]["daily_goal_days"], 0)
        self.assertEqual(result["attendance"][-1]["count"], 1)
        rows.append(math_row("review", 0, False, selection="review"))
        self.assertTrue(weekly_report(rows, [], USER, NOW, {"daily_questions": 2})["attendance"][-1]["daily_goal_met"])

    def test_retry_only_day_counts_as_effort_but_not_new_questions(self):
        rows = [math_row("retry", 1, False, selection="retry"),
                math_row("review_retry", 0, False, selection="review_retry")]
        report = weekly_report(rows, [], USER, NOW, {"weekly_days": 2, "daily_questions": 1})
        self.assertEqual(report["goals"]["learning_days"], 2)
        self.assertTrue(report["goals"]["weekly_goal_met"])
        self.assertEqual(report["goals"]["daily_goal_days"], 0)
        self.assertTrue(report["attendance"][-1]["active"])
        self.assertEqual(report["attendance"][-1]["count"], 0)

    def test_empty_and_invalid_goals(self):
        result = weekly_report([], [], USER, NOW)
        self.assertIsNone(result["subjects"]["math"]["initial"]["rate"])
        self.assertFalse(result["goals"]["weekly_goal_met"])
        for goals in ({"weekly_days": 0}, {"weekly_days": True}, {"daily_questions": 21}):
            with self.assertRaises(ValueError):
                weekly_report([], [], USER, NOW, goals)


class AnalysisAndExportTests(unittest.TestCase):
    def test_math_components_evidence_unknown_and_dontknow_separate(self):
        word = make_word_problem("increase", 10, 2, 3)
        first = math_row("first", correct=False, problem=word)
        first.update(operation_selection_correct=False, equation_correct=True, calculation_correct=True, is_correct=False)
        second = math_row("second", problem=word)
        second.update(operation_selection_correct=True, equation_correct=False, calculation_correct=False, is_correct=False)
        unknown = math_row("unknown", problem=word)
        unknown["equation_correct"] = None
        dont = dict(math_row("dont", correct=False, problem=word), dont_know_used=True)
        review = dict(math_row("review", correct=False, problem=word), selection_type="review")
        result = error_analysis([first, second, unknown, dont, review], [], USER, NOW)
        components = {row["field"]: row for row in result["math"]["components"]}
        self.assertEqual(components["operation_selection_correct"]["count"], 3)
        self.assertEqual(components["operation_selection_correct"]["wrong_count"], 1)
        self.assertEqual(components["equation_correct"]["count"], 2)
        self.assertEqual(components["calculation_correct"]["wrong_count"], 1)
        self.assertEqual(result["dont_know"]["math"], 1)
        self.assertIn("断定しません", result["math"]["explanation"])

    def test_japanese_categories_recorded_error_tags_and_particle_pairs(self):
        question = next(q for q in QUESTIONS if q["category"] == "particles")
        wrong = jp_row("wrong", correct=False, question=question)
        dont = dict(jp_row("dont", correct=False, question=question), dont_know_used=True)
        result = error_analysis([], [wrong, dont], USER, NOW)
        self.assertEqual(result["japanese"]["categories"][0]["wrong_count"], 1)
        self.assertEqual(result["japanese"]["particles"][0]["count"], 1)
        self.assertEqual(result["japanese"]["error_tags"][0]["tag"], "particle")
        self.assertEqual(result["dont_know"]["japanese"], 1)

    def test_csv_bom_full_fields_safe_formulas_and_no_other_learner(self):
        math = dict(math_row("math"), question_text=" =HYPERLINK(\"bad\")", hint_level=3,
                    custom_list=["りんご", "みかん"], response_time_sec=-1)
        jp = dict(jp_row("jp"), text="@SUM(1)", selected_answer_text="\t=evil")
        other = dict(math_row("other"), user_id="user_002", secret_note="NEVER_EXPORT")
        data = csv_export([math, math, other, math_row("future", -1)], [jp], USER, NOW)
        self.assertTrue(data.startswith(b"\xef\xbb\xbf"))
        rows = list(csv.DictReader(io.StringIO(data.decode("utf-8-sig"))))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["subject"], "japanese")
        math_csv = next(row for row in rows if row["subject"] == "math")
        jp_csv = next(row for row in rows if row["subject"] == "japanese")
        self.assertTrue(math_csv["question_text"].startswith("' ="))
        self.assertEqual(math_csv["hint_level"], "3")
        self.assertEqual(math_csv["response_time_sec"], "-1")
        self.assertIn("りんご", math_csv["custom_list"])
        self.assertEqual(jp_csv["text"], "'@SUM(1)")
        self.assertEqual(jp_csv["selected_answer_text"], "'\t=evil")
        self.assertNotIn("NEVER_EXPORT", data.decode("utf-8-sig"))
        self.assertNotIn("secret_note", data.decode("utf-8-sig"))

    def test_empty_csv_has_header(self):
        rows = list(csv.reader(io.StringIO(csv_export([], [], USER, NOW).decode("utf-8-sig"))))
        self.assertEqual(len(rows), 1)
        self.assertIn("attempt_id", rows[0])


class ForecastAndAdaptiveTests(unittest.TestCase):
    def test_due_today_tomorrow_caps_without_basic_fill(self):
        today_rows = [math_row(f"today{i}", 1, False, problem=learning.make_problem("addition", 10, i, 1)) for i in range(7)]
        tomorrow = math_row("tomorrow", 0, False, problem=learning.make_problem("subtraction", 10, 9, 2))
        not_due = math_row("clean", 0, True, problem=learning.make_problem("subtraction", 10, 9, 3))
        old_catalog = dict(math_row("gone", 1, False), problem_id="deleted_problem")
        result = review_forecast(today_rows + [tomorrow, not_due, old_catalog], USER, "math", NOW)
        self.assertEqual((result["today_count"], result["today_total"], result["today_overflow"]), (5, 7, 2))
        self.assertEqual((result["tomorrow_count"], result["tomorrow_total"]), (1, 1))
        self.assertEqual(review_forecast([], USER, "math", NOW)["today_count"], 0)

    def test_forecast_range_level_and_latest_future(self):
        row = math_row("range", 1, False, problem=learning.make_problem("addition", 20, 8, 9))
        self.assertEqual(review_forecast([row], USER, "math", NOW, limit=10)["today_total"], 0)
        question = next(q for q in QUESTIONS if q.get("level") == 3)
        old = jp_row("old", 1, False, question=question)
        future = jp_row("future", -1, True, question=question)
        self.assertEqual(review_forecast([old, future], USER, "japanese", NOW, particle_level=1)["today_total"], 0)
        self.assertEqual(review_forecast([old, future], USER, "japanese", NOW, particle_level=3)["today_total"], 1)

    def test_forecast_respects_saved_daily_review_budget(self):
        due = [math_row(f"due{i}", 1, False, problem=learning.make_problem("addition", 10, i, 1)) for i in range(5)]
        done = [math_row(f"done{i}", 0, selection="review", problem=learning.make_problem("subtraction", 10, 9, i)) for i in range(2)]
        forecast = review_forecast(iter(due + done), USER, "math", NOW)
        self.assertEqual((forecast["daily_done"], forecast["daily_remaining"], forecast["today_count"]), (2, 3, 3))
        self.assertEqual((forecast["today_total"], forecast["today_overflow"]), (5, 2))

    def test_adaptive_math_uses_other_numbers_same_operation_range(self):
        original = learning.make_problem("subtraction", 10, 8, 3)
        plan = adaptive_math([math_row("bad", 1, False, problem=original)], USER, now=NOW)
        self.assertEqual(len(plan["items"]), 5)
        self.assertEqual(len({q["problem_id"] for q in plan["items"]}), 5)
        self.assertNotIn(original["problem_id"], {q["problem_id"] for q in plan["items"]})
        self.assertTrue(all(q["operation"] == "subtraction" and q["number_range"] == 10 for q in plan["items"]))
        self.assertTrue(all("類題" in reason for reason in plan["reasons"].values()))

    def test_adaptive_word_preserves_story_and_changes_numbers(self):
        original = make_word_problem("increase", 10, 3, 2)
        plan = adaptive_math([math_row("bad", 1, False, problem=original)], USER, count=3, now=NOW)
        self.assertTrue(all(q["story_type"] == "increase" for q in plan["items"]))
        self.assertTrue(all((q["left_operand"], q["right_operand"]) != (3, 2) for q in plan["items"]))

    def test_adaptive_japanese_new_context_and_particle_level(self):
        original = next(q for q in QUESTIONS if q["category"] == "particles" and q["level"] == 1)
        plan = adaptive_japanese([jp_row("bad", 1, False, question=original)], USER, particle_level=1, now=NOW)
        self.assertEqual(len(plan["items"]), 5)
        self.assertTrue(all(q["category"] == "particles" and q["level"] == 1 for q in plan["items"]))
        self.assertNotIn(original["question_id"], {q["question_id"] for q in plan["items"]})
        self.assertEqual(len(set(plan["reasons"])), 5)

    def test_adaptive_learner_separation_resolved_latest_and_insufficient(self):
        wrong = dict(math_row("other", 1, False), user_id="user_002")
        future = math_row("future", -1, False)
        self.assertEqual(adaptive_math([wrong, future], USER, now=NOW), adaptive_math([], USER, now=NOW))
        bad = math_row("bad", 1, False)
        good = math_row("good", 0, True)
        self.assertTrue(all(reason == "基本の類題で確認" for reason in adaptive_math([bad, good], USER, now=NOW)["reasons"].values()))
        plan = adaptive_japanese([], USER, count=999, particle_level=1, now=NOW)
        self.assertLess(len(plan["items"]), 999)
        self.assertIn("重複せず", plan["message"])

    def test_adaptive_invalid_settings_and_no_mutation(self):
        row = math_row("bad", 1, False)
        snapshot = dict(row)
        adaptive_math([row], USER, now=NOW)
        self.assertEqual(row, snapshot)
        for callback in (lambda: adaptive_math([], USER, limit=7, now=NOW),
                         lambda: adaptive_japanese([], USER, particle_level=4, now=NOW),
                         lambda: adaptive_math([], USER, count=0, now=NOW)):
            with self.assertRaises(ValueError):
                callback()


class StagedHintTests(unittest.TestCase):
    def test_math_all_current_problem_kinds_three_guiding_steps(self):
        problems = [learning.make_problem("addition", 20, 8, 5),
                    learning.make_problem("subtraction", 20, 13, 7),
                    make_word_problem("compare", 10, 7, 2)]
        for problem in problems:
            steps = math_hint_steps(problem)
            self.assertEqual(len(steps), 3)
            self.assertTrue(all(isinstance(step, str) and step for step in steps))
            self.assertTrue(all("=" not in step and "せいかいは" not in step for step in steps))
            self.assertNotIn(str(problem["correct_answer"]), "".join(steps))

    def test_japanese_all_categories_no_answer_explanation_reveal(self):
        for question in QUESTIONS:
            steps = japanese_hint_steps(question)
            self.assertEqual(len(steps), 3)
            self.assertEqual(steps[0], question["hint"])
            self.assertTrue(all("せいかいは" not in step and "こたえは" not in step for step in steps))
            self.assertNotEqual(steps[2], question["explanation"])

    def test_carry_hint_handles_operands_already_over_ten(self):
        steps = math_hint_steps(learning.make_problem("addition", 20, 12, 8))
        self.assertIn("ばらの かず", steps[2])
        self.assertNotIn("はじめの かずが 10に", steps[2])

    def test_borrowing_hint_handles_twenty_minus_small_and_twelve_minus_eight(self):
        for left, right in ((20, 3), (12, 8)):
            steps = math_hint_steps(learning.make_problem("subtraction", 20, left, right))
            self.assertIn("10の まとまりを ひとつ ばらに", steps[2])
            self.assertNotIn("まず 10に なるまで", steps[2])


if __name__ == "__main__":
    unittest.main()
