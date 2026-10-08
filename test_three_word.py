"""3数文章題の時間順、両演算・数量・計算の独立採点と保存。"""

from collections import Counter
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import learning
import practice_mode
import three_word as three
import words


def answer_record(q, answer=None, **updates):
    values = dict(selected_operation=q["operation"], selected_second_operation=q["second_operation"],
                  equation_left=q["left_operand"], equation_right=q["right_operand"], equation_third=q["third_operand"])
    values.update(updates)
    return learning.make_attempt(q, "user_001", "three_word", 1, "normal",
                                  q["correct_answer"] if answer is None else answer, 2, 1, **values)


class ThreeWordTests(unittest.TestCase):
    def test_four_stories_fix_operation_order_and_unknown_result(self):
        cases = {
            "increase_twice": ("addition", "addition", 2, 3, 4, 9),
            "decrease_twice": ("subtraction", "subtraction", 8, 3, 2, 3),
            "increase_then_decrease": ("addition", "subtraction", 5, 3, 2, 6),
            "decrease_then_increase": ("subtraction", "addition", 8, 3, 2, 7),
        }
        for story, (first, second, a, b, c, result) in cases.items():
            q = three.make_three_word_problem(story, 10, a, b, c)
            self.assertEqual(q["problem_id"], f"three_word_v1_{story}_10_{a}_{b}_{c}")
            self.assertEqual(q["problem_format"], "three_word_problem")
            self.assertEqual(q["story_type"], story)
            self.assertEqual(q["unknown_type"], "result")
            self.assertEqual((q["operation"], q["second_operation"]), (first, second))
            self.assertEqual(q["correct_answer"], result)
            self.assertNotIn("=", q["question_text"])
            self.assertNotIn("+", q["question_text"])
            self.assertTrue(set(q) <= set(learning.COLUMNS))
            row = answer_record(q)
            self.assertTrue(row["operation_selection_correct"])
            self.assertTrue(row["equation_correct"])
            self.assertTrue(row["calculation_correct"])
            self.assertTrue(row["is_correct"])
            self.assertEqual(row["user_equation"], f"{a} {'+' if first == 'addition' else '−'} {b} {'+' if second == 'addition' else '−'} {c}")

    def test_two_operations_numbers_and_calculation_are_independent(self):
        q = three.make_three_word_problem("increase_then_decrease", 10, 5, 3, 2)
        cases = [
            ({}, 6, True, True, True, True),
            ({"selected_second_operation": "addition"}, 10, False, True, True, False),
            ({"selected_operation": "subtraction"}, 0, False, True, True, False),
            ({"selected_operation": "subtraction", "selected_second_operation": "addition"}, 4, False, True, True, False),
            ({"equation_left": 4}, 5, True, False, True, False),
            ({}, 5, True, True, False, False),
            ({"equation_left": 3, "equation_right": 5}, 6, True, False, True, False),
            ({"equation_left": 2, "equation_right": 7, "selected_operation": "subtraction", "selected_second_operation": "addition"}, 0, False, False, None, False),
        ]
        for kwargs, answer, operation, equation, calculation, correct in cases:
            with self.subTest(kwargs=kwargs):
                row = answer_record(q, answer, **kwargs)
                self.assertEqual(row["operation_selection_correct"], operation)
                self.assertEqual(row["equation_correct"], equation)
                self.assertEqual(row["calculation_correct"], calculation)
                self.assertEqual(row["is_correct"], correct)
        # −−でも同じ最終値になっただけでは、出来事の順番の数量抽出は正答にしない。
        subtract = three.make_three_word_problem("decrease_twice", 10, 8, 3, 2)
        row = answer_record(subtract, 3, equation_right=2, equation_third=3)
        self.assertFalse(row["equation_correct"])
        self.assertTrue(row["calculation_correct"])
        self.assertFalse(row["is_correct"])

    def test_new_form_requires_two_operations_and_three_valid_equation_numbers(self):
        q = three.make_three_word_problem("increase_twice", 10, 2, 3, 4)
        for invalid in ({"selected_operation": None}, {"selected_second_operation": None},
                        {"selected_second_operation": "multiply"}, {"equation_third": None},
                        {"equation_third": True}, {"equation_third": -1}, {"equation_third": 100},
                        {"equation_left": None}, {"equation_right": "3"}):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                answer_record(q, **invalid)
        with self.assertRaises(ValueError):
            learning.make_attempt(q, "user_001", "missing", 1, "normal", 9, 2, 1,
                                  selected_operation="addition", selected_second_operation="addition")

    def test_old_two_number_word_commutes_and_keeps_legacy_unassessed_fields(self):
        q = words.make_word_problem("increase", 10, 2, 3)
        self.assertEqual(q["problem_id"], "word_v1_increase_10_2_3")
        for left, right in ((2, 3), (3, 2)):
            row = learning.make_attempt(q, "user_001", "old", 1, "normal", 5, 2, 1,
                                         selected_operation="addition", equation_left=left, equation_right=right)
            self.assertTrue(row["equation_correct"])
            self.assertTrue(row["is_correct"])
        legacy = learning.make_attempt(q, "user_001", "legacy", 1, "normal", 5, 2, 1, selected_operation="addition")
        self.assertTrue(legacy["is_correct"])
        self.assertIsNone(legacy["equation_correct"])
        self.assertIsNone(legacy["user_equation"])
        with self.assertRaises(ValueError):
            learning.make_attempt(q, "user_001", "extra", 1, "normal", 5, 2, 1, selected_operation="addition",
                                  equation_left=2, equation_right=3, equation_third=4)

    def test_zero_events_rejected_but_zero_intermediate_or_final_are_allowed(self):
        for story in three.STORIES:
            for numbers in ((0, 3, 2), (5, 0, 2), (5, 3, 0)):
                with self.assertRaises(ValueError):
                    three.make_three_word_problem(story, 10, *numbers)
        q = three.make_three_word_problem("decrease_then_increase", 20, 20, 20, 20)
        self.assertEqual(q["correct_answer"], 20)
        self.assertFalse(q["zero_included"])
        self.assertEqual(three.make_three_word_problem("increase_then_decrease", 10, 2, 3, 5)["correct_answer"], 0)
        self.assertEqual(three.make_three_word_problem("decrease_twice", 10, 5, 3, 2)["correct_answer"], 0)
        for args in (("invalid", 10, 5, 3, 2), ("increase_then_decrease", 10, 8, 5, 3),
                     ("decrease_then_increase", 10, 2, 3, 5), ("increase_twice", 20, 10, 10, 1)):
            with self.assertRaises(ValueError):
                three.make_three_word_problem(*args)

    def test_pool_special_properties_and_balanced_unique_mix_dispatch(self):
        self.assertIs(learning.get_problem_pool("three_word_problem"), three.three_word_pool)
        for limit in (10, 20):
            for first in ("addition", "subtraction"):
                pool = three.three_word_pool(first, limit)
                self.assertEqual(len(pool), len({q["problem_id"] for q in pool}))
                self.assertEqual(len(pool), len({q["question_text"] for q in pool}))
                for q in pool:
                    a, b, c = q["left_operand"], q["right_operand"], q["third_operand"]
                    middle = a + b if first == "addition" else a - b
                    self.assertTrue(1 <= min(a, b, c) <= max(a, b, c) <= limit)
                    self.assertTrue(0 <= middle <= limit and 0 <= q["correct_answer"] <= limit)
            for special in ("auto", "none", "with"):
                for mode in ("addition", "subtraction", "mix"):
                    for count in (5, 10, 20):
                        items = learning.generate_problems(mode, limit, count, special, "three_word_problem")
                        self.assertEqual(len(items), count)
                        self.assertEqual(len({q["problem_id"] for q in items}), count)
                        counts = Counter(q["story_type"] for q in items)
                        if mode == "mix":
                            self.assertEqual(set(counts), set(three.STORIES))
                            self.assertLessEqual(max(counts.values()) - min(counts.values()), 1)
                        else:
                            self.assertEqual(set(counts), {"increase_twice" if mode == "addition" else "decrease_twice"})
                        if special != "auto":
                            self.assertTrue(all(bool(q["carry"] or q["borrowing"]) == (special == "with") for q in items))
        both = three.make_three_word_problem("decrease_then_increase", 20, 13, 8, 9)
        self.assertTrue(both["carry"] and both["borrowing"])
        self.assertIsNotNone(learning.selection_error("addition", 10, 1000, "auto", "three_word_problem"))
        with self.assertRaises(ValueError):
            three.generate_three_word("addition", 10, 1000)

    def test_three_hints_follow_story_order_with_intermediate_but_final_after_answer(self):
        for story, (first, second, _) in three.STORIES.items():
            a, b, c = (5, 3, 2) if first == "addition" else (8, 3, 2)
            q = three.make_three_word_problem(story, 20, a, b, c)
            hints = three.hint_steps(q)
            self.assertEqual(len(hints), 3)
            self.assertEqual(three.guidance(q), hints[0])
            self.assertNotIn("=", hints[0])
            self.assertIn("まずは " + ("たす" if first == "addition" else "ひく"), hints[1])
            self.assertIn("つぎは " + ("たす" if second == "addition" else "ひく"), hints[1])
            middle = a + b if first == "addition" else a - b
            self.assertIn(f"= {middle}", hints[2])
            self.assertIn(f"つぎに {middle} {'+' if second == 'addition' else '−'} {c} を", hints[2])
            self.assertNotIn("こたえは", hints[2])
            self.assertEqual(words.guidance(q), three.guidance(q))
            revealed = three.guidance(q, True)
            self.assertIn(f"{a} {'+' if first == 'addition' else '−'} {b} {'+' if second == 'addition' else '−'} {c} = {q['correct_answer']}", revealed)
            self.assertEqual(words.guidance(q, True), revealed)

    def test_unknown_and_parent_test_do_not_assess_equation_or_write(self):
        q = three.make_three_word_problem("decrease_then_increase", 10, 8, 3, 2)
        unknown = learning.make_attempt(q, "user_001", "unknown", 1, "normal", None, 2, 1, dont_know_used=True)
        self.assertFalse(unknown["is_correct"])
        self.assertIsNone(unknown["operation_selection_correct"])
        self.assertIsNone(unknown["equation_correct"])
        self.assertIsNone(unknown["calculation_correct"])
        self.assertIsNone(unknown["user_equation"])
        self.assertIsNone(unknown["user_answer"])
        with patch.object(learning, "get_supabase_config", side_effect=AssertionError("config")), \
             patch.object(learning.sqlite3, "connect", side_effect=AssertionError("db")), \
             patch.object(learning, "supabase_urlopen", side_effect=AssertionError("cloud")):
            learning.save_attempt(answer_record(q), test_mode=True)
        with patch.object(learning, "save_attempt", side_effect=AssertionError("write")):
            practice_mode.write_learning_answer({"test_mode": True}, {}, learning.save_attempt, answer_record(q))

    def test_sqlite_resend_and_cloud_payload_keep_full_equation_existing_columns(self):
        q = three.make_three_word_problem("increase_then_decrease", 20, 8, 5, 7)
        row = answer_record(q)
        with TemporaryDirectory() as folder:
            path = Path(folder) / "math.sqlite3"
            learning.init_db(path)
            learning.save_attempt(row, path)
            learning.save_attempt(row, path)
            rows, more = learning.read_attempts("user_001", path=path)
            self.assertEqual(len(rows), 1)
            self.assertFalse(more)
            self.assertEqual(rows[0]["user_equation"], "8 + 5 − 7")
            self.assertEqual(rows[0]["third_operand"], 7)
            self.assertEqual(rows[0]["second_operation"], "subtraction")
            self.assertEqual(learning.read_attempts("user_002", path=path)[0], [])
        with patch.object(learning, "get_supabase_config", return_value=("https://example.supabase.co", "sb_secret_test")), \
             patch.object(learning, "supabase_urlopen") as remote:
            response = remote.return_value.__enter__.return_value
            response.status = 201
            learning.save_attempt(row)
            posted = json.loads(remote.call_args.args[0].data)
            self.assertEqual(posted, row)
            response.status = 200
            response.read.return_value = json.dumps([posted]).encode()
            self.assertEqual(learning.read_attempts("user_001")[0], [row])


if __name__ == "__main__":
    unittest.main()
