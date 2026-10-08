"""段階ヒント・未回答・目標・問題報告の保存契約を、実履歴と分離して検証。"""

from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit
import json
import sqlite3
import unittest

import assessment
import japanese
import learning
import learning_extensions as ext
from japanese_questions import QUESTIONS
from words import make_word_problem


def math_record(**kwargs):
    return learning.make_attempt(learning.make_problem("addition", 10, 2, 3), "user_001", "s", 1,
                                 "normal", 5, 2, 1, **kwargs)


def jp_record(question=None, **kwargs):
    question = question or QUESTIONS[0]
    return japanese.make_record(question, "user_001", "s", 1, "normal", question["answer"], 2, 1, "chain", **kwargs)


class AnswerSupportTests(unittest.TestCase):
    def test_stage_records_and_legacy_boolean_are_compatible(self):
        for maker in (math_record, jp_record):
            for level in range(4):
                row = maker(hint_level=level)
                self.assertEqual(row["hint_level"], level)
                self.assertEqual(row["hint_used"], level > 0)
                self.assertFalse(row["dont_know_used"])
            self.assertTrue(maker(hint_used=True)["hint_used"])
            for field, values in (("hint_level", (None, True, -1, 4, "2")),
                                  ("dont_know_used", (None, 0, 1, "true"))):
                for value in values:
                    with self.subTest(maker=maker.__name__, field=field, value=value), self.assertRaises(ValueError):
                        maker(**{field: value})

    def test_unknown_math_is_unanswered_and_not_a_false_calculation_diagnosis(self):
        row = math_record(dont_know_used=True, hint_level=2)
        self.assertIsNone(row["user_answer"])
        self.assertFalse(row["is_correct"])
        self.assertIsNone(row["calculation_correct"])
        word = learning.make_attempt(make_word_problem("decrease", 10, 5, 2), "user_001", "w", 1,
                                     "normal", None, 1, 1, selected_operation=None,
                                     equation_left=2, equation_right=None, dont_know_used=True)
        self.assertTrue(word["dont_know_used"])
        for name in ("user_answer", "operation_selection_correct", "equation_correct", "calculation_correct", "user_equation"):
            self.assertIsNone(word[name])

    def test_unknown_japanese_all_formats_preserve_question_and_chain(self):
        for q in (QUESTIONS[0], next(q for q in QUESTIONS if q["problem_format"] == "ordering"),
                  next(q for q in QUESTIONS if q["category"] == "particles")):
            row = japanese.make_record(q, "user_001", "s", 1, "review_retry", None, 2, 2,
                                       "original-chain", first_try_correct=False, dont_know_used=True, hint_level=3)
            self.assertEqual((row["question_id"], row["chain_id"], row["answer"]), (q["question_id"], "original-chain", q["answer"]))
            self.assertTrue(row["retry_flag"])
            self.assertFalse(row["correct"])
            self.assertEqual(row["selected_answer_text"], "わからない")
            self.assertEqual(row["error_cause_tags"], [])
            if q["category"] == "particles":
                self.assertIsNone(row["selected_answer_index"])
                self.assertIsNone(row["confusion_pair"])

    def test_unknown_initial_and_later_retry_do_not_rewrite_first_result(self):
        q = QUESTIONS[0]
        first = japanese.make_record(q, "user_001", "s", 1, "normal", None, 1, 1, "same", dont_know_used=True)
        retry = japanese.make_record(q, "user_001", "retry", 1, "retry", q["answer"], 1, 2, "same")
        result = japanese.metrics([first, retry])
        self.assertEqual((result["count"], result["rate"], result["eventual_correct"], result["retry_success"]), (1, 0, 1, 1))
        math = math_record(dont_know_used=True)
        result = assessment.assess([math])
        self.assertEqual((result["overall"]["count"], result["overall"]["rate"]), (1, 0))

    def test_sqlite_additive_migration_preserves_unknown_old_levels_and_answers(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "old.sqlite3"
            old = math_record(hint_used=True)
            columns = {name: kind for name, kind in learning.COLUMNS.items() if name not in ("hint_level", "dont_know_used")}
            with closing(sqlite3.connect(path)) as db, db:
                db.execute("CREATE TABLE attempts (" + ", ".join(f'"{n}" {k}' for n, k in columns.items()) + ")")
                db.execute("INSERT INTO attempts (" + ", ".join(columns) + ") VALUES (" +
                           ", ".join("?" for _ in columns) + ")", [old[name] for name in columns])
            learning.init_db(path)
            current = math_record(hint_level=3, dont_know_used=True)
            learning.save_attempt(current, path)
            learning.save_attempt(current, path)
            rows, more = learning.read_attempts("user_001", path=path)
            self.assertFalse(more)
            self.assertEqual(len(rows), 2)
            by_id = {row["attempt_id"]: row for row in rows}
            actual = by_id[old["attempt_id"]]
            self.assertIsNone(actual["hint_level"])
            self.assertIsNone(actual["dont_know_used"])
            self.assertEqual((actual["user_answer"], actual["is_correct"], actual["hint_used"]), (5, 1, 1))
            self.assertEqual((by_id[current["attempt_id"]]["hint_level"], by_id[current["attempt_id"]]["dont_know_used"]), (3, 1))

    def test_old_pending_math_payload_saves_level_as_unknown(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "old.sqlite3"
            learning.init_db(path)
            pending = math_record(hint_used=True)
            pending.pop("hint_level")
            learning.save_attempt(pending, path)
            rows, _ = learning.read_attempts("user_001", path=path)
            self.assertIsNone(rows[0]["hint_level"])
            self.assertEqual(rows[0]["hint_used"], 1)

    def test_japanese_new_flags_and_legacy_json_roundtrip(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "jp.sqlite3"
            japanese.init_db(path)
            legacy = jp_record()
            legacy.pop("hint_level")
            legacy.pop("dont_know_used")
            current = jp_record(hint_level=2, dont_know_used=True)
            for row in (legacy, current, current):
                japanese.save_record(row, path)
            rows = japanese.read_all("user_001", path)
            self.assertEqual({r["attempt_id"] for r in rows}, {legacy["attempt_id"], current["attempt_id"]})
            self.assertIn(legacy, rows)
            self.assertIn(current, rows)

    def test_backend_test_mode_performs_no_config_or_file_or_cloud_access(self):
        with patch("learning.get_supabase_config", side_effect=AssertionError("config accessed")), \
                patch("learning.sqlite3.connect", side_effect=AssertionError("database accessed")), \
                patch("learning.supabase_urlopen", side_effect=AssertionError("network accessed")):
            learning.save_attempt(math_record(), test_mode=True)
            japanese.save_record(jp_record(), test_mode=True)
            ext.save_goals("user_001", 4, 10, test_mode=True)
            ext.save_feedback(ext.make_feedback("user_001", "math", "calculation_addition_10_2_3", "reading"), test_mode=True)


class SharedLocalStoreTests(unittest.TestCase):
    def test_read_defaults_does_not_create_database_and_goals_are_separated(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "extensions.sqlite3"
            self.assertEqual(ext.read_goals("user_001", path), {"user_id": "user_001", "weekly_days": 3, "daily_questions": 5})
            self.assertEqual(ext.read_feedback("user_001", path), [])
            self.assertFalse(path.exists())
            ext.save_goals("user_001", 7, 20, path)
            ext.save_goals("user_002", 1, 1, path)
            ext.save_goals("user_001", 4, 10, path)
            ext.save_goals("user_001", 5, 15, path, test_mode=True)
            self.assertEqual(ext.read_goals("user_001", path)["daily_questions"], 10)
            self.assertEqual(ext.read_goals("user_002", path)["weekly_days"], 1)

    def test_feedback_is_idempotent_immutable_and_user_filtered(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "extensions.sqlite3"
            own = ext.make_feedback("user_001", "math", "problem-one", "difficult")
            other = ext.make_feedback("user_002", "japanese", "jp_words_001", "answer")
            for record in (own, own, other, dict(own, reason="reading")):
                ext.save_feedback(record, path)
            ext.save_feedback(ext.make_feedback("user_001", "math", "test", "reading"), path, test_mode=True)
            self.assertEqual(ext.read_feedback("user_001", path), [own])
            self.assertEqual(ext.read_feedback("user_002", path), [other])

    def test_invalid_goals_and_reports_are_rejected(self):
        for week, count in ((0, 5), (8, 5), (3, 0), (3, 21), (True, 5), (3, "5")):
            with self.assertRaises(ValueError):
                ext.save_goals("user_001", week, count, test_mode=True)
        for kwargs in ({"user_id": "someone"}, {"subject": "english"}, {"subject": []}, {"reason": "free-text"},
                       {"problem_id": ""}, {"feedback_id": ""}):
            with self.assertRaises(ValueError):
                ext.make_feedback(**{"user_id": "user_001", "subject": "math", "problem_id": "problem", "reason": "answer", **kwargs})


class SharedCloudStoreTests(unittest.TestCase):
    def setUp(self):
        config = patch("learning.get_supabase_config", return_value=("https://example.supabase.co", "sb_secret_test_only"))
        config.start()
        self.addCleanup(config.stop)

    def test_cloud_goal_upsert_and_feedback_ignore_duplicates(self):
        record = ext.make_feedback("user_001", "japanese", "jp_words_001", "reading")
        with patch("learning.supabase_urlopen") as remote, patch("learning_extensions.sqlite3.connect") as local:
            response = remote.return_value.__enter__.return_value
            response.status = 201
            ext.save_goals("user_001", 4, 10)
            request = remote.call_args.args[0]
            self.assertIn("family_learning_settings?on_conflict=user_id", request.full_url)
            self.assertIn("merge-duplicates", request.get_header("Prefer"))
            ext.save_feedback(record)
            ext.save_feedback(record)
            requests = [call.args[0] for call in remote.call_args_list[-2:]]
            for request in requests:
                self.assertEqual(json.loads(request.data), record)
                self.assertIn("ignore-duplicates", request.get_header("Prefer"))
            local.assert_not_called()

    def test_cloud_reads_use_user_filters_and_reject_other_learners(self):
        own = ext.make_feedback("user_001", "math", "problem", "reading")
        with patch("learning.supabase_urlopen") as remote:
            response = remote.return_value.__enter__.return_value
            response.status = 200
            response.read.return_value = json.dumps([own]).encode()
            self.assertEqual(ext.read_feedback("user_001"), [own])
            query = parse_qs(urlsplit(remote.call_args.args[0].full_url).query)
            self.assertEqual(query["user_id"], ["eq.user_001"])
            response.read.return_value = json.dumps([dict(own, user_id="user_002")]).encode()
            with self.assertRaises(OSError):
                ext.read_feedback("user_001")
            response.read.return_value = json.dumps([{"user_id": "user_002", "weekly_days": 3, "daily_questions": 5}]).encode()
            with self.assertRaises(OSError):
                ext.read_goals("user_001")

    def test_lost_feedback_response_retry_keeps_same_id(self):
        record = ext.make_feedback("user_001", "math", "problem", "difficult")
        sent = []
        def first(request, **kwargs):
            sent.append(json.loads(request.data))
            raise URLError("response lost")
        with patch("learning.supabase_urlopen", side_effect=first):
            with self.assertRaises(OSError):
                ext.save_feedback(record)
        with patch("learning.supabase_urlopen") as remote:
            remote.return_value.__enter__.return_value.status = 201
            ext.save_feedback(record)
            self.assertEqual(json.loads(remote.call_args.args[0].data), sent[0])
            self.assertIn("ignore-duplicates", remote.call_args.args[0].get_header("Prefer"))

    def test_missing_table_explains_sql_without_local_fallback_or_secret(self):
        error = HTTPError("https://example.supabase.co/rest/v1/family_learning_settings", 404,
                          "sb_secret_test_only", {}, None)
        with patch("learning.supabase_urlopen", side_effect=error), patch("learning_extensions.sqlite3.connect") as local:
            with self.assertRaises(OSError) as raised:
                ext.read_goals("user_001")
            self.assertIn("supabase_learning_extensions.sql", str(raised.exception))
            self.assertNotIn("sb_secret_test_only", str(raised.exception))
            local.assert_not_called()

    def test_old_cloud_history_missing_new_column_is_readable(self):
        old = math_record()
        old.pop("hint_level")
        with patch("learning.supabase_urlopen") as remote:
            response = remote.return_value.__enter__.return_value
            response.status = 200
            response.read.return_value = json.dumps([old]).encode()
            rows, more = learning.read_attempts("user_001")
            self.assertFalse(more)
            self.assertIsNone(rows[0]["hint_level"])
            self.assertTrue(rows[0]["is_correct"])


if __name__ == "__main__":
    unittest.main()
