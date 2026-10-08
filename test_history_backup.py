"""Answer backups use temporary stores; no family/cloud data is touched."""

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.error import URLError
from contextlib import closing
import json
import sqlite3
import unittest

import history_backup as backup
import japanese
import learning
from japanese_questions import QUESTIONS


def math_record(user="user_001", **updates):
    row = learning.make_attempt(learning.make_problem("addition", 10, 2, 3), user, "session", 1,
                                "normal", 5, 2.5, 1, round_size=5)
    row.update(updates)
    return row


def japanese_record(user="user_001", **updates):
    q = QUESTIONS[0]
    row = japanese.make_record(q, user, "session", 1, "normal", q["answer"], 2.5, 1, "chain")
    row.update(updates)
    return row


def parsed(math_rows=None, jp_rows=None):
    return backup.parse_backup(backup.export_backup("user_001", math_rows or [], jp_rows or [],
                                                    now=datetime(2026, 10, 8, tzinfo=timezone.utc)), "user_001")


def encoded_changed(data, update):
    value = deepcopy(data)
    update(value)
    value["checksum"] = backup._checksum(value)
    return backup._canonical(value)


class BackupFormatTests(unittest.TestCase):
    def test_lossless_legacy_and_future_dates_roundtrip(self):
        math_row = math_record(datetime="2099-01-01T12:00:00+09:00")
        math_row.pop("reading_help_used")
        math_row.pop("hint_level")
        jp_row = japanese_record()
        jp_row.pop("reading_help_used")
        jp_row["legacy_private_note"] = {"original": "本文", "values": [True, None, 2]}
        value = parsed([math_row], [jp_row])
        self.assertEqual(value["math"][0]["datetime"], math_row["datetime"])
        self.assertIsNone(value["math"][0]["reading_help_used"])
        self.assertIsNone(value["math"][0]["hint_level"])
        self.assertEqual(value["japanese"][0], jp_row)
        self.assertEqual(backup.parse_backup(backup._canonical(value), "user_001"), value)

    def test_selected_learner_is_enforced_everywhere(self):
        for math_rows, jp_rows in (([math_record("user_002")], []), ([], [japanese_record("user_002")])):
            with self.assertRaises(ValueError):
                parsed(math_rows, jp_rows)
        data = backup.export_backup("user_001", [], [])
        with self.assertRaises(ValueError):
            backup.parse_backup(data, "user_002")
        with self.assertRaises(ValueError):
            backup.export_backup("user_999", [], [])

    def test_malformed_json_duplicate_keys_csv_size_and_checksum(self):
        for invalid in (b'{"version":1,"version":1}', b"datetime,answer\nnow,1", b"\xff", b'{"a":NaN}', b"[" * 10000,
                        b" " * (backup.MAX_BYTES + 1)):
            with self.subTest(data=invalid[:50]), self.assertRaises(ValueError):
                backup.parse_backup(invalid, "user_001")
        value = parsed([math_record()], [])
        value["math"][0]["user_answer"] = 9
        with self.assertRaisesRegex(ValueError, "チェックサム"):
            backup.parse_backup(backup._canonical(value), "user_001")

    def test_wrong_structure_or_type_rejected_even_with_valid_checksum(self):
        value = parsed([math_record()], [japanese_record()])
        mutations = [lambda v: v.update(version=True), lambda v: v.update(extra=1),
                     lambda v: v["math"][0].update(question_order=True),
                     lambda v: v["math"][0].update(is_correct="true"),
                     lambda v: v["math"][0].update(datetime="2026-10-08T00:00:00"),
                     lambda v: v["math"][0].update(response_time_sec=-1),
                     lambda v: v["japanese"][0].update(correct=1),
                     lambda v: v["japanese"][0].update(learner_id="user_002"),
                     lambda v: v["japanese"][0].update(hint_level=True),
                     lambda v: v["japanese"][0].pop("chain_id"),
                     lambda v: v["japanese"][0].pop("skill_tags"),
                     lambda v: v["japanese"][0].pop("reading_mode"),
                     lambda v: v["japanese"][0].update(error_cause_tags={}),
                     lambda v: v["japanese"][0].update(answer={"bad": "index"}),
                     lambda v: v["japanese"][0].update(selected_answer=999),
                     lambda v: v["japanese"][0].update(difficulty=True),
                     lambda v: v["math"][0].update(operation="anything"),
                     lambda v: v["math"][0].update(number_range=999),
                     lambda v: v["math"][0].update(correct_answer=999)]
        for mutation in mutations:
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                backup.parse_backup(encoded_changed(value, mutation), "user_001")

    def test_duplicate_backup_ids_and_limits_rejected(self):
        math_row, jp_row = math_record(), japanese_record()
        for rows, jps in (([math_row, math_row], []), ([], [jp_row, jp_row])):
            with self.assertRaisesRegex(ValueError, "重複"):
                parsed(rows, jps)
        with patch.object(backup, "MAX_ROWS", 1), self.assertRaises(ValueError):
            parsed([math_row], [jp_row])

    def test_preview_detects_global_conflicts_and_equivalent_representations(self):
        math_row, jp_row = math_record(datetime="2026-10-08T09:00:00+09:00"), japanese_record(datetime="2026-10-08T09:00:00+09:00")
        value = parsed([math_row], [jp_row])
        old_math = {key: int(item) if type(item) is bool else item for key, item in math_row.items()}
        old_math["datetime"] = "2026-10-08T00:00:00+00:00"
        old_jp = {**jp_row, "datetime": "2026-10-08T00:00:00Z", "response_time_sec": 2.5}
        self.assertEqual(backup.preview_backup(value, [old_math], [old_jp]),
                         dict(math_added=0, japanese_added=0, math_existing=1, japanese_existing=1))
        for update in ({"user_id": "user_002"}, {"user_answer": 7}):
            with self.assertRaisesRegex(ValueError, "回答ID"):
                backup.preview_backup(value, [{**old_math, **update}], [old_jp])
        with self.assertRaisesRegex(ValueError, "回答ID"):
            backup.preview_backup(value, [old_math], [{**old_jp, "correct": False}])

    def test_empty_preview_and_test_mode_do_not_touch_stores(self):
        value = parsed([math_record()], [japanese_record()])
        with patch.object(learning, "get_supabase_config", side_effect=AssertionError("config read")), \
             patch.object(backup.sqlite3, "connect", side_effect=AssertionError("db read")), \
             patch.object(learning, "supabase_urlopen", side_effect=AssertionError("network")):
            counts = backup.restore_backup(value, test_mode=True)
            self.assertTrue(counts["test_mode"])
            self.assertEqual(counts["math_added"], 1)
        self.assertEqual(backup.preview_backup(parsed(), [], []),
                         dict(math_added=0, japanese_added=0, math_existing=0, japanese_existing=0))

    def test_ordering_particles_and_unknown_answers_are_lossless_and_validated(self):
        questions = [next(q for q in QUESTIONS if q["problem_format"] == "ordering"),
                     next(q for q in QUESTIONS if q["category"] == "particles")]
        for question in questions:
            for unknown in (False, True):
                row = japanese.make_record(question, "user_001", "s", 1, "normal", None if unknown else question["answer"],
                                           1, 1, "chain", dont_know_used=unknown)
                self.assertEqual(parsed([], [row])["japanese"], [row])
            row = japanese.make_record(question, "user_001", "s", 1, "normal", question["answer"], 1, 1, "chain")
            value = parsed([], [row])
            invalid_field = "selected_answer_index" if question["category"] == "particles" else "selected_answer"
            with self.assertRaises(ValueError):
                backup.parse_backup(encoded_changed(value, lambda v: v["japanese"][0].update({invalid_field: [0, 0, 0]})), "user_001")

    def test_all_current_materials_can_be_backed_up_without_modifying_payload(self):
        rows = [japanese.make_record(q, "user_001", "s", 1, "normal", q["answer"], 1, 1, "chain_" + q["question_id"])
                for q in QUESTIONS]
        self.assertEqual(parsed([], rows)["japanese"], rows)


class LocalRestoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.math_path = Path(self.temp.name) / "math.sqlite3"
        self.jp_path = Path(self.temp.name) / "japanese.sqlite3"
        learning.init_db(self.math_path)
        japanese.init_db(self.jp_path)

    def restore(self, value, **kwargs):
        return backup.restore_backup(value, math_path=self.math_path, japanese_path=self.jp_path, **kwargs)

    def test_additive_restore_retry_preserves_histories_and_chain_ids(self):
        old = math_record(attempt_id="old")
        learning.save_attempt(old, self.math_path)
        math_row, jp_row = math_record(selection_type="review"), japanese_record(selection_type="review", chain_id="review_chain")
        value = parsed([math_row], [jp_row])
        counts = self.restore(value)
        self.assertEqual(counts, dict(math_added=1, japanese_added=1, math_existing=0, japanese_existing=0))
        counts = self.restore(value)
        self.assertEqual(counts, dict(math_added=0, japanese_added=0, math_existing=1, japanese_existing=1))
        rows, _ = learning.read_attempts("user_001", path=self.math_path)
        self.assertEqual(len(rows), 2)
        self.assertEqual(next(r for r in rows if r["attempt_id"] == "old")["user_answer"], old["user_answer"])
        restored = japanese.read_all("user_001", path=self.jp_path)
        self.assertEqual(restored, [jp_row])
        self.assertEqual(japanese.metrics(restored)["count"], 0)

    def test_other_learner_id_conflict_rechecked_before_either_write(self):
        math_row, jp_row = math_record(), japanese_record()
        japanese.save_record({**jp_row, "user_id": "user_002"}, self.jp_path)
        value = parsed([math_row], [jp_row])
        # Selected-child UI cannot see the other child's collision.
        self.assertEqual(backup.preview_backup(value, [], [])["math_added"], 1)
        with self.assertRaisesRegex(ValueError, "回答ID"):
            self.restore(value)
        self.assertEqual(learning.read_attempts("user_001", path=self.math_path)[0], [])
        self.assertEqual(len(japanese.read_all("user_002", path=self.jp_path)), 1)

    def test_second_database_write_error_rolls_back_first_database(self):
        value = parsed([math_record()], [japanese_record()])
        with closing(sqlite3.connect(self.jp_path)) as db, db:
            db.execute("CREATE TRIGGER reject_restore BEFORE INSERT ON japanese_attempts BEGIN SELECT RAISE(ABORT, 'test storage failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.restore(value)
        self.assertEqual(learning.read_attempts("user_001", path=self.math_path)[0], [])
        self.assertEqual(japanese.read_all("user_001", path=self.jp_path), [])
        with closing(sqlite3.connect(self.jp_path)) as db, db:
            db.execute("DROP TRIGGER reject_restore")
        self.assertEqual(self.restore(value)["math_added"], 1)

    def test_existing_japanese_row_payload_mismatch_blocks_restore(self):
        row = japanese_record()
        japanese.save_record(row, self.jp_path)
        with closing(sqlite3.connect(self.jp_path)) as db, db:
            db.execute("UPDATE japanese_attempts SET user_id='user_002'")
        with self.assertRaisesRegex(ValueError, "保存行"):
            self.restore(parsed([], [row]))

    def test_wal_or_missing_store_fails_without_changes_or_creation(self):
        with closing(sqlite3.connect(self.math_path)) as db, db:
            db.execute("PRAGMA journal_mode=WAL")
        with self.assertRaisesRegex(ValueError, "DELETE"):
            self.restore(parsed([math_record()], [japanese_record()]))
        self.assertEqual(japanese.read_all("user_001", path=self.jp_path), [])
        missing = Path(self.temp.name) / "missing.sqlite3"
        with self.assertRaises(ValueError):
            backup.restore_backup(parsed(), math_path=missing, japanese_path=self.jp_path)
        self.assertFalse(missing.exists())
        with self.assertRaises(ValueError):
            backup.restore_backup(parsed(), math_path=self.math_path)


class Response:
    status = 200

    def __init__(self, counts):
        self.counts = counts

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self.counts).encode()


class CloudRestoreTests(unittest.TestCase):
    def test_single_rpc_with_exact_payload_and_server_counts(self):
        value = parsed([math_record()], [japanese_record()])
        counts = dict(math_added=1, japanese_added=1, math_existing=0, japanese_existing=0)
        with patch.object(learning, "get_supabase_config", return_value=("https://example.supabase.co", "sb_secret_test")), \
             patch.object(learning, "supabase_urlopen", return_value=Response(counts)) as call, \
             patch.object(backup.sqlite3, "connect", side_effect=AssertionError("local fallback")):
            self.assertEqual(backup.restore_backup(value), counts)
        request = call.call_args.args[0]
        self.assertEqual(request.full_url, "https://example.supabase.co/rest/v1/rpc/restore_answer_history")
        self.assertEqual(request.method, "POST")
        self.assertEqual(json.loads(request.data), {"backup": value})
        self.assertEqual(request.get_header("Apikey"), "sb_secret_test")

    def test_uncertain_cloud_retry_sends_same_ids_never_local_fallback(self):
        value = parsed([math_record()], [japanese_record()])
        counts = dict(math_added=0, japanese_added=0, math_existing=1, japanese_existing=1)
        with patch.object(learning, "get_supabase_config", return_value=("https://example.supabase.co", "sb_secret_test")), \
             patch.object(learning, "supabase_urlopen", side_effect=[URLError("timeout"), Response(counts)]) as call, \
             patch.object(backup.sqlite3, "connect", side_effect=AssertionError("fallback")):
            with self.assertRaises(OSError):
                backup.restore_backup(value)
            self.assertEqual(backup.restore_backup(value), counts)
        self.assertEqual(call.call_args_list[0].args[0].data, call.call_args_list[1].args[0].data)

    def test_invalid_rpc_response_and_config_failure_do_not_fallback(self):
        value = parsed([math_record()], [])
        for counts in ({}, {"math_added": True, "japanese_added": 0, "math_existing": 0, "japanese_existing": 0},
                       dict(math_added=0, japanese_added=0, math_existing=0, japanese_existing=0)):
            with patch.object(learning, "get_supabase_config", return_value=("https://example.supabase.co", "sb_secret_test")), \
                 patch.object(learning, "supabase_urlopen", return_value=Response(counts)), \
                 patch.object(backup.sqlite3, "connect", side_effect=AssertionError("fallback")), self.assertRaises(OSError):
                backup.restore_backup(value)
        with patch.object(learning, "get_supabase_config", side_effect=ValueError("bad config")), \
             patch.object(backup.sqlite3, "connect", side_effect=AssertionError("fallback")), self.assertRaises(ValueError):
            backup.restore_backup(value)

    def test_additive_sql_has_service_only_transaction_and_global_lock(self):
        sql = Path("supabase_history_restore.sql").read_text(encoding="utf-8").lower()
        self.assertIn("security invoker", sql)
        self.assertIn("current_user <> 'service_role'", sql)
        self.assertIn("from public, anon, authenticated", sql)
        self.assertIn("on conflict(attempt_id) do nothing", sql)
        self.assertIn("get diagnostics inserted_count = row_count", sql)
        self.assertNotIn("lock table", sql)
        self.assertIn("pg_advisory_xact_lock", sql)
        self.assertNotIn("delete from", sql)
        self.assertNotIn("update public", sql)


if __name__ == "__main__":
    unittest.main()
