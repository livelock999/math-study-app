"""Restore filled-equation operands without replacing their hidden-number answer."""

from contextlib import closing
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json
import sqlite3
import unittest

import history_backup as backup
import japanese
import learning
from test_history_backup import encoded_changed, japanese_record, math_record, parsed


def fill_record(operation="addition", limit=10, left=5, right=3, position="left_operand", **updates):
    problem = learning.make_problem(operation, limit, left, right)
    problem.update(problem_format="fill_blank", blank_position=position,
                   problem_id=f"fill_blank_v1_{operation}_{limit}_{position}_{left}_{right}",
                   question_text=f"{'□' if position == 'left_operand' else left} {'+' if operation == 'addition' else '−'} {'□' if position == 'right_operand' else right} = {problem['correct_answer']}",
                   correct_answer=left if position == "left_operand" else right)
    row = learning.make_attempt(problem, "user_001", "fill_session", 1, "normal", problem["correct_answer"], 1, 1, round_size=5)
    row.update(updates)
    if 'is_correct' in updates and 'first_attempt_correct' not in updates:
        row['first_attempt_correct'] = updates['is_correct']
    return row


class FillBlankBackupTests(unittest.TestCase):
    def test_hidden_operands_roundtrip_for_both_sides_and_operations(self):
        rows = []
        for operation, limit, left, right in (("addition", 10, 5, 3), ("addition", 20, 9, 8),
                                              ("subtraction", 10, 8, 3), ("subtraction", 20, 13, 7),
                                              ("addition", 10, 0, 10), ("subtraction", 20, 20, 20)):
            for position in ("left_operand", "right_operand"):
                rows.append(fill_record(operation, limit, left, right, position))
        value = parsed(rows, [])
        for before, after in zip(rows, value["math"]):
            self.assertEqual(after["correct_answer"], before[before["blank_position"]])
            self.assertEqual(after["left_operand"], before["left_operand"])
            self.assertEqual(after["right_operand"], before["right_operand"])
            self.assertEqual(after["problem_id"], before["problem_id"])
            self.assertEqual(after["question_text"], before["question_text"])
        self.assertEqual(value["math"][0]["correct_answer"], 5)
        self.assertNotEqual(value["math"][0]["correct_answer"], 5 + 3)

    def test_invalid_positions_ids_answers_or_base_equations_rejected_before_io(self):
        value = parsed([fill_record()], [])
        mutations = ({"blank_position": None}, {"blank_position": "answer"}, {"blank_position": "left"},
                     {"correct_answer": 8}, {"correct_answer": 3},
                     {"problem_id": "calculation_addition_10_5_3"},
                     {"left_operand": 9, "right_operand": 9},
                     {"operation": "subtraction", "left_operand": 3, "right_operand": 5},
                     {"problem_id": "fill_blank_v1_addition_10_right_operand_5_3"})
        for change in mutations:
            with self.subTest(change=change), patch.object(backup.sqlite3, "connect", side_effect=AssertionError("DB read")), \
                 patch.object(learning, "get_supabase_config", side_effect=AssertionError("config read")), \
                 patch.object(learning, "supabase_urlopen", side_effect=AssertionError("network")), self.assertRaises(ValueError):
                backup.parse_backup(encoded_changed(value, lambda data: data["math"][0].update(change)), "user_001")
        malformed = deepcopy(value)
        malformed["math"][0]["correct_answer"] = 8
        malformed["checksum"] = backup._checksum(malformed)
        with patch.object(backup.sqlite3, "connect", side_effect=AssertionError("DB read")), self.assertRaises(ValueError):
            backup.restore_backup(malformed, test_mode=True)

    def test_existing_calculation_and_word_answers_keep_their_result_semantics(self):
        calc = math_record()
        word = math_record(problem_format="word_problem", story_type="increase", problem_id="word_v1_increase_10_2_3")
        calc.pop("hint_level")
        calc.pop("reading_help_used")
        value = parsed([calc, word, fill_record()], [])
        self.assertEqual(value["math"][0]["correct_answer"], 5)
        self.assertIsNone(value["math"][0]["hint_level"])
        wrong = encoded_changed(value, lambda data: data["math"][0].update(correct_answer=2))
        with self.assertRaises(ValueError):
            backup.parse_backup(wrong, "user_001")

    def test_answer_input_boundary_matches_three_digit_ui_without_changing_correct_answers(self):
        calculation = math_record(user_answer=999, is_correct=False, calculation_correct=False)
        fill = fill_record(user_answer=999, is_correct=False, calculation_correct=False)
        value = parsed([calculation, fill], [])
        for row in value["math"]:
            self.assertEqual(row["user_answer"], 999)
            self.assertFalse(row["is_correct"])
            self.assertEqual(row["correct_answer"], 5)
        for index in range(2):
            with self.subTest(index=index), self.assertRaisesRegex(ValueError, "0〜999"):
                backup.parse_backup(encoded_changed(value, lambda data: data["math"][index].update(user_answer=1000)), "user_001")
        self.assertIn("not between 0 and 999", Path("supabase_history_restore.sql").read_text(encoding="utf-8"))

    def test_parent_test_with_fill_backup_performs_no_config_db_or_network_io(self):
        row = fill_record(dont_know_used=True, user_answer=None, is_correct=False, calculation_correct=None,
                          visual_help_used=True, hint_used=True)
        value = parsed([row], [japanese_record()])
        with patch.object(learning, "get_supabase_config", side_effect=AssertionError("config read")), \
             patch.object(backup.sqlite3, "connect", side_effect=AssertionError("DB read")), \
             patch.object(learning, "supabase_urlopen", side_effect=AssertionError("network")):
            counts = backup.restore_backup(value, test_mode=True)
        self.assertTrue(counts["test_mode"])
        self.assertEqual(counts["math_added"], 1)

    def test_visual_help_true_false_and_legacy_unknown_roundtrip(self):
        rows = [fill_record(visual_help_used=True, hint_used=True, hint_level=0),
                fill_record(visual_help_used=False, hint_used=False)]
        legacy = fill_record()
        legacy.pop("visual_help_used", None)
        rows.append(legacy)
        value = parsed(rows, [])
        self.assertIs(value["math"][0]["visual_help_used"], True)
        self.assertEqual(value["math"][0]["hint_level"], 0)
        self.assertIs(value["math"][1]["visual_help_used"], False)
        self.assertIsNone(value["math"][2]["visual_help_used"])
        for incorrect in ("true", 2, []):
            with self.subTest(value=incorrect), self.assertRaises(ValueError):
                backup.parse_backup(encoded_changed(value, lambda data: data["math"][0].update(visual_help_used=incorrect)), "user_001")
        with self.assertRaises(ValueError):
            backup.parse_backup(encoded_changed(value, lambda data: data["math"][0].update(hint_used=False)), "user_001")


class FillBlankRestoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.math_path = Path(self.temp.name) / "math.sqlite3"
        self.jp_path = Path(self.temp.name) / "japanese.sqlite3"
        learning.init_db(self.math_path)
        japanese.init_db(self.jp_path)

    def restore(self, value):
        return backup.restore_backup(value, math_path=self.math_path, japanese_path=self.jp_path)

    def test_restore_preserves_operands_hidden_answer_and_retry_is_duplicate(self):
        row = fill_record(position="right_operand", selection_type="review")
        old = math_record(attempt_id="legacy_math")
        learning.save_attempt(old, self.math_path)
        value = parsed([row], [japanese_record()])
        self.assertEqual(self.restore(value), dict(math_added=1, japanese_added=1, math_existing=0, japanese_existing=0))
        self.assertEqual(self.restore(value), dict(math_added=0, japanese_added=0, math_existing=1, japanese_existing=1))
        rows, _ = learning.read_attempts("user_001", path=self.math_path)
        actual = next(r for r in rows if r["attempt_id"] == row["attempt_id"])
        self.assertEqual((actual["left_operand"], actual["right_operand"], actual["correct_answer"]), (5, 3, 3))
        self.assertEqual(actual["selection_type"], "review")
        self.assertEqual(next(r for r in rows if r["attempt_id"] == "legacy_math")["correct_answer"], 5)

    def test_saved_three_digit_errors_restore_for_calculation_and_fill(self):
        rows = [math_record(user_answer=999, is_correct=False, calculation_correct=False),
                fill_record(user_answer=999, is_correct=False, calculation_correct=False)]
        value = parsed(rows, [])
        self.assertEqual(self.restore(value)["math_added"], 2)
        restored, _ = learning.read_attempts("user_001", path=self.math_path)
        self.assertEqual({row["problem_format"] for row in restored}, {"calculation", "fill_blank"})
        self.assertTrue(all(row["user_answer"] == 999 and row["is_correct"] == 0 for row in restored))
        self.assertEqual(self.restore(value)["math_existing"], 2)

    def test_cross_subject_conflict_rolls_back_new_fill_records(self):
        row, jp_row = fill_record(), japanese_record()
        japanese.save_record({**jp_row, "user_id": "user_002"}, self.jp_path)
        with self.assertRaises(ValueError):
            self.restore(parsed([row], [jp_row]))
        self.assertEqual(learning.read_attempts("user_001", path=self.math_path)[0], [])
        self.assertEqual(len(japanese.read_all("user_002", path=self.jp_path)), 1)

    def test_same_fill_id_conflict_preserves_existing_answer_and_other_subject(self):
        row = fill_record()
        learning.save_attempt(row, self.math_path)
        imported = {**row, "user_answer": 99, "is_correct": False}
        with self.assertRaises(ValueError):
            self.restore(parsed([imported], [japanese_record()]))
        actual = learning.read_attempts("user_001", path=self.math_path)[0][0]
        self.assertEqual(actual["user_answer"], 5)
        self.assertEqual(japanese.read_all("user_001", path=self.jp_path), [])

    def test_second_subject_insert_failure_rolls_back_and_retry_retains_fill_id(self):
        value = parsed([fill_record(visual_help_used=True, hint_used=True)], [japanese_record()])
        with closing(sqlite3.connect(self.jp_path)) as db, db:
            db.execute("CREATE TRIGGER reject_restore BEFORE INSERT ON japanese_attempts BEGIN SELECT RAISE(ABORT,'temporary failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.restore(value)
        self.assertEqual(learning.read_attempts("user_001", path=self.math_path)[0], [])
        with closing(sqlite3.connect(self.jp_path)) as db, db:
            db.execute("DROP TRIGGER reject_restore")
        self.assertEqual(self.restore(value)["math_added"], 1)
        self.assertEqual(self.restore(value)["math_existing"], 1)
        self.assertEqual(learning.read_attempts("user_001", path=self.math_path)[0][0]["visual_help_used"], 1)

    def test_migration_adds_only_format_validation_not_tables_or_permissions(self):
        sql = Path("supabase_history_restore.sql").read_text(encoding="utf-8").lower()
        self.assertIn("create or replace function public.restore_answer_history", sql)
        self.assertIn("'fill_blank'", sql)
        self.assertIn("invalid fill-blank position, answer or id", sql)
        self.assertIn("apply supabase_math_visuals.sql before restoring history", sql)
        self.assertIn("attname = 'visual_help_used'", sql)
        self.assertNotIn("alter table", sql)
        self.assertNotIn("grant update", sql)
        self.assertNotIn("delete from", sql)


if __name__ == "__main__":
    unittest.main()
