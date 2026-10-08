"""Three-event word-problem answers keep their timeline and diagnostic stages."""

from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.error import URLError
import json
import sqlite3
import unittest

import history_backup as backup
import japanese
import learning
import three_word
from test_history_backup import Response, encoded_changed, japanese_record, math_record, parsed
from test_restore_three_numbers import three_record


STORIES = {
    "increase_twice": ("addition", "addition", 2, 3, 4, 9),
    "decrease_twice": ("subtraction", "subtraction", 9, 2, 3, 4),
    "increase_then_decrease": ("addition", "subtraction", 5, 3, 2, 6),
    "decrease_then_increase": ("subtraction", "addition", 8, 3, 4, 9),
}


def word_record(story="increase_then_decrease", limit=10, left=5, right=3, third=2, **updates):
    question = three_word.make_three_word_problem(story, limit, left, right, third)
    row = learning.make_attempt(question, "user_001", "word_session", 1, "normal", question["correct_answer"], 1, 1,
                                selected_operation=question["operation"], selected_second_operation=question["second_operation"],
                                equation_left=left, equation_right=right, equation_third=third, round_size=5)
    row.update(updates)
    if 'is_correct' in updates and 'first_attempt_correct' not in updates:
        row['first_attempt_correct'] = updates['is_correct']
    return row


class ThreeWordBackupTests(unittest.TestCase):
    def test_actual_four_stories_preserve_ids_quantities_equations_and_diagnostics(self):
        rows = [word_record(story, 10, values[2], values[3], values[4]) for story, values in STORIES.items()]
        value = parsed(rows, [])
        self.assertEqual(value["math"], rows)
        for row in value["math"]:
            op1, op2, left, right, third, expected = STORIES[row["story_type"]]
            self.assertEqual((row["operation"], row["second_operation"], row["third_operand"], row["correct_answer"]),
                             (op1, op2, third, expected))
            self.assertEqual(row["unknown_type"], "result")
            self.assertTrue(row["operation_selection_correct"] and row["equation_correct"] and row["calculation_correct"])
            self.assertIn(str(third), row["user_equation"])

    def test_unknown_wrong_operation_wrong_quantity_and_three_digit_error_are_preserved(self):
        problem = three_word.make_three_word_problem("increase_then_decrease", 10, 5, 3, 2)
        wrong_operation = learning.make_attempt(problem, "user_001", "s", 1, "normal", 4, 1, 1,
                    selected_operation="subtraction", selected_second_operation="addition", equation_left=5, equation_right=3, equation_third=2)
        wrong_quantity = learning.make_attempt(problem, "user_001", "s", 1, "normal", 5, 1, 1,
                    selected_operation="addition", selected_second_operation="subtraction", equation_left=4, equation_right=3, equation_third=2)
        unknown = learning.make_attempt(problem, "user_001", "s", 1, "normal", None, 1, 1, dont_know_used=True)
        large = word_record(user_answer=999, is_correct=False, calculation_correct=False)
        rows = [wrong_operation, wrong_quantity, unknown, large]
        self.assertEqual(parsed(rows, [])["math"], rows)
        self.assertFalse(wrong_operation["operation_selection_correct"])
        self.assertTrue(wrong_operation["equation_correct"] and wrong_operation["calculation_correct"])
        self.assertTrue(wrong_quantity["operation_selection_correct"] and wrong_quantity["calculation_correct"])
        self.assertFalse(wrong_quantity["equation_correct"])
        self.assertIsNone(unknown["user_answer"])

    def test_story_mapping_id_answer_positive_operands_and_unknown_type_rejected(self):
        value = parsed([word_record()], [])
        changes = ({"story_type": None}, {"story_type": "anything"}, {"story_type": "increase_twice"},
                   {"operation": "subtraction"}, {"second_operation": "addition"}, {"second_operation": None},
                   {"third_operand": None}, {"third_operand": 0}, {"third_operand": True},
                   {"left_operand": 0}, {"right_operand": 0}, {"unknown_type": None}, {"unknown_type": "initial"},
                   {"correct_answer": 8}, {"problem_id": "three_numbers_v1_addition_subtraction_10_5_3_2"})
        for change in changes:
            with self.subTest(change=change), patch.object(backup.sqlite3, "connect", side_effect=AssertionError("DB read")), \
                 patch.object(learning, "get_supabase_config", side_effect=AssertionError("config read")), \
                 patch.object(learning, "supabase_urlopen", side_effect=AssertionError("network")), self.assertRaises(ValueError):
                backup.parse_backup(encoded_changed(value, lambda data: data["math"][0].update(change)), "user_001")

    def test_legacy_two_number_and_three_number_ids_remain_distinct_and_unchanged(self):
        old = math_record(problem_format="word_problem", story_type="increase", problem_id="word_v1_increase_10_2_3")
        old.pop("third_operand", None)
        old.pop("second_operation", None)
        math_three = three_record()
        word_three = word_record()
        actual = parsed([old, math_three, word_three], [])["math"]
        self.assertIsNone(actual[0]["third_operand"])
        self.assertIsNone(actual[0]["second_operation"])
        self.assertEqual(actual[1]["problem_id"], math_three["problem_id"])
        self.assertEqual(actual[2]["problem_id"], word_three["problem_id"])
        self.assertNotEqual(actual[1]["problem_id"], actual[2]["problem_id"])

    def test_parent_dry_run_never_reads_initializes_or_writes_any_store(self):
        value = parsed([word_record(visual_help_used=True, hint_used=True, hint_level=0)], [japanese_record()])
        with patch.object(learning, "get_supabase_config", side_effect=AssertionError("config read")), \
             patch.object(backup.sqlite3, "connect", side_effect=AssertionError("DB read")), \
             patch.object(learning, "supabase_urlopen", side_effect=AssertionError("network")):
            counts = backup.restore_backup(value, test_mode=True)
        self.assertTrue(counts["test_mode"])
        self.assertEqual((counts["math_added"], counts["japanese_added"]), (1, 1))


class ThreeWordRestoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.math_path = Path(self.temp.name) / "math.sqlite3"
        self.jp_path = Path(self.temp.name) / "japanese.sqlite3"
        learning.init_db(self.math_path)
        japanese.init_db(self.jp_path)

    def restore(self, value):
        return backup.restore_backup(value, math_path=self.math_path, japanese_path=self.jp_path)

    def test_stories_restore_losslessly_and_resending_is_duplicate_only(self):
        rows = [word_record(story, 10, values[2], values[3], values[4]) for story, values in STORIES.items()]
        value = parsed(rows, [japanese_record()])
        self.assertEqual(self.restore(value), dict(math_added=4, japanese_added=1, math_existing=0, japanese_existing=0))
        self.assertEqual(self.restore(value), dict(math_added=0, japanese_added=0, math_existing=4, japanese_existing=1))
        actual = learning.read_attempts("user_001", path=self.math_path)[0]
        self.assertEqual(len(actual), 4)
        for row in actual:
            original = next(item for item in rows if item["attempt_id"] == row["attempt_id"])
            for field in ("problem_id", "story_type", "unknown_type", "user_equation", "third_operand", "second_operation"):
                self.assertEqual(row[field], original[field])

    def test_other_learner_second_subject_conflict_prevents_any_restore_writes(self):
        jp_row = japanese_record()
        japanese.save_record({**jp_row, "user_id": "user_002"}, self.jp_path)
        with self.assertRaises(ValueError):
            self.restore(parsed([word_record()], [jp_row]))
        self.assertEqual(learning.read_attempts("user_001", path=self.math_path)[0], [])

    def test_storage_failure_rolls_back_both_subjects_and_retry_preserves_ids(self):
        value = parsed([word_record()], [japanese_record()])
        with closing(sqlite3.connect(self.jp_path)) as db, db:
            db.execute("CREATE TRIGGER reject_restore BEFORE INSERT ON japanese_attempts BEGIN SELECT RAISE(ABORT,'temporary failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.restore(value)
        self.assertEqual(learning.read_attempts("user_001", path=self.math_path)[0], [])
        with closing(sqlite3.connect(self.jp_path)) as db, db:
            db.execute("DROP TRIGGER reject_restore")
        self.assertEqual(self.restore(value)["math_added"], 1)
        self.assertEqual(self.restore(value)["math_existing"], 1)


class ThreeWordCloudRestoreTests(unittest.TestCase):
    def test_uncertain_rpc_resend_has_identical_payload_no_local_fallback(self):
        value = parsed([word_record()], [])
        counts = dict(math_added=0, japanese_added=0, math_existing=1, japanese_existing=0)
        with patch.object(learning, "get_supabase_config", return_value=("https://example.supabase.co", "sb_secret_test")), \
             patch.object(learning, "supabase_urlopen", side_effect=[URLError("timeout"), Response(counts)]) as call, \
             patch.object(backup.sqlite3, "connect", side_effect=AssertionError("local fallback")):
            with self.assertRaises(OSError):
                backup.restore_backup(value)
            self.assertEqual(backup.restore_backup(value), counts)
        self.assertEqual(call.call_args_list[0].args[0].data, call.call_args_list[1].args[0].data)
        actual = json.loads(call.call_args.args[0].data)["backup"]["math"][0]
        self.assertEqual(actual["problem_format"], "three_word_problem")
        self.assertEqual(actual["story_type"], "increase_then_decrease")
        self.assertEqual(actual["correct_answer"], 6)

    def test_rpc_update_adds_story_validation_without_new_columns_or_permissions(self):
        sql = Path("supabase_history_restore.sql").read_text(encoding="utf-8").lower()
        self.assertIn("create or replace function public.restore_answer_history", sql)
        self.assertIn("'three_word_problem'", sql)
        self.assertIn("invalid three-number word story, operands or operations", sql)
        for story in STORIES:
            self.assertIn(story, sql)
        self.assertNotIn("alter table", sql)
        self.assertNotIn("grant update", sql)
        self.assertNotIn("delete from", sql)


if __name__ == "__main__":
    unittest.main()
