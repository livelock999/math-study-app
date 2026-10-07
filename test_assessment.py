import unittest

from assessment import assess, category, recommended_problems
from learning import make_attempt, make_problem


def answers(count, correct, operation="subtraction", limit=20, left=13, right=8,
            selection="normal", start=0):
    problem = make_problem(operation, limit, left, right)
    result = []
    for index in range(count):
        row = make_attempt(problem, "user_001", "test", index + 1, selection,
                           problem["correct_answer"] + (index >= correct), index + 1, 1)
        row.update(datetime="2026-10-07T20:00:00+09:00", attempt_id=f"test_{start + index:04}")
        result.append(row)
    return result


class AssessmentTests(unittest.TestCase):
    def test_equation_rate_excludes_legacy_null_and_separates_correct_calculation(self):
        from words import make_word_problem

        problem = make_word_problem("decrease", 20, 13, 8)
        legacy = make_attempt(problem, "user_001", "legacy", 1, "normal", 5, 2, 1,
                              selected_operation="subtraction")
        written = make_attempt(problem, "user_001", "written", 1, "normal", 4, 2, 1,
                               selected_operation="subtraction", equation_left=12, equation_right=8)
        summary = assess([legacy, written])["word_normal"]
        self.assertEqual(summary["count"], 2)
        self.assertEqual(summary["equation_count"], 1)
        self.assertEqual(summary["equation_correct"], 0)
        self.assertEqual(summary["equation_rate"], 0)
        self.assertEqual(summary["operation_rate"], 1)
        self.assertEqual(summary["calculation_rate"], 1)

    def test_word_judgments_do_not_mix_with_calculation_mastery(self):
        from words import make_word_problem

        records = answers(10, 10)
        problem = make_word_problem("decrease", 20, 13, 8)
        for index in range(5):
            records.append(make_attempt(problem, "user_001", "word_test", index + 1, "normal",
                                        21, 1, 1, selected_operation="addition"))
        records.append(make_attempt(problem, "user_001", "word_retry", 1, "retry", 5, 1, 2,
                                    selected_operation="subtraction"))
        report = assess(records)
        self.assertEqual(report["overall"]["count"], 10)
        self.assertEqual(report["overall"]["rate"], 1)
        self.assertEqual(len(report["groups"]), 1)
        self.assertIsNone(report["target"])
        words = report["word_normal"]
        self.assertEqual(words["count"], 5)
        self.assertEqual(words["rate"], 0)
        self.assertEqual(words["operation_rate"], 0)
        self.assertEqual(words["calculation_rate"], 1)
        self.assertEqual(report["word_retry"]["count"], 1)
        self.assertEqual(report["word_retry"]["rate"], 1)

    def test_empty_and_small_samples_do_not_claim_mastery(self):
        report = assess([])
        self.assertIsNone(report["overall"]["rate"])
        self.assertIsNone(report["target"])
        small = assess(answers(4, 0))
        self.assertIsNone(small["target"])
        self.assertIn("判断保留", small["groups"][0]["status"])

    def test_retries_do_not_inflate_initial_accuracy(self):
        records = answers(10, 4) + answers(10, 10, selection="retry", start=10)
        report = assess(records)
        self.assertEqual(report["overall"]["count"], 10)
        self.assertEqual(report["overall"]["rate"], .4)
        self.assertEqual(report["retry"]["rate"], 1)
        self.assertEqual(report["overall"]["seconds"], 2.5)
        problems = recommended_problems(report)
        self.assertEqual(len(problems), 5)
        self.assertEqual(len({p["problem_id"] for p in problems}), 5)
        self.assertTrue(all(category(p) == ("subtraction", 20, True) for p in problems))
        self.assertTrue(all(p["correct_answer"] >= 0 for p in problems))

    def test_trend_compares_matching_categories_in_time_order(self):
        records = answers(10, 2) + answers(10, 8, start=10)
        records += answers(10, 10, operation="addition", limit=10, left=2, right=3, start=20)
        report = assess(list(reversed(records)))
        subtraction = next(g for g in report["groups"] if g["key"][0] == "subtraction")
        self.assertIn("+60ポイント", subtraction["trend"])
        self.assertEqual(len(report["strengths"]), 1)
        self.assertEqual(report["target"], ("subtraction", 20, True))

    def test_fast_errors_and_slow_correct_answers_do_not_change_accuracy_judgment(self):
        records = answers(10, 10)
        for row in records:
            row["response_time_sec"] = 120
        report = assess(records)
        self.assertIsNone(report["target"])
        self.assertEqual(len(report["strengths"]), 1)
        self.assertEqual(len(recommended_problems(report)), 10)

    def test_number_ranges_remain_separate(self):
        report = assess(answers(5, 5, limit=10, left=8, right=3)
                        + answers(5, 0, start=5))
        self.assertEqual(len(report["groups"]), 2)
        self.assertEqual(report["target"], ("subtraction", 20, True))


if __name__ == "__main__":
    unittest.main()
