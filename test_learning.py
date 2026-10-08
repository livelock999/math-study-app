"""将来の分析に必要な、問題属性と回答保存の振る舞いを検証します。"""

import sqlite3
import os
import json
import re
from contextlib import closing
from copy import deepcopy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError, HTTPError
from urllib.parse import parse_qs, urlsplit

from streamlit.testing.v1 import AppTest
import learning

from learning import COLUMNS, generate_problems, init_db, make_attempt, make_problem, save_attempt


def test_environment(values=None):
    """アプリ用設定だけ隔離し、Windows のホーム等の実行環境は保持します。"""
    excluded = {"SUPABASE_URL", "SUPABASE_SECRET_KEY", "MATH_REQUIRE_PASSWORD", "MATH_APP_PASSWORD"}
    result = {key: value for key, value in os.environ.items() if key not in excluded}
    result.update(values or {})
    return result


class LearningTests(unittest.TestCase):
    def test_variable_counts_and_special_filters_produce_valid_unique_sets(self):
        for count in (5, 10, 20):
            for mode in ("addition", "subtraction", "mix"):
                for special in ("auto", "none", "with"):
                    problems = generate_problems(mode, 20, count=count, special=special)
                    self.assertEqual(len(problems), count)
                    self.assertEqual(len({p["problem_id"] for p in problems}), count)
                    for problem in problems:
                        self.assertTrue(0 <= problem["correct_answer"] <= 20)
                        flag = problem["carry"] if problem["operation"] == "addition" else problem["borrowing"]
                        if special != "auto":
                            self.assertEqual(flag, special == "with")

    def test_insufficient_or_invalid_practice_settings_fail_clearly(self):
        for mode in ("addition", "subtraction"):
            self.assertIsNotNone(learning.selection_error(mode, 10, count=10, special="with"))
            with self.assertRaises(ValueError):
                generate_problems(mode, 10, count=10, special="with")
        for kwargs in ({"count": 0}, {"count": -1}, {"count": True}, {"special": "invalid"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                generate_problems("addition", 20, **kwargs)

    def test_round_completion_is_only_marked_on_final_answer(self):
        problem = make_problem("addition", 10, 2, 3)
        for order in range(1, 6):
            record = make_attempt(problem, "user_001", "completion", order, "normal", 5, 1, 1, round_size=5)
            self.assertEqual(record["round_size"], 5)
            self.assertEqual(record["round_completed"], order == 5)

    def test_existing_database_migration_preserves_old_answers(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "old_history.sqlite3"
            old_columns = {name: kind for name, kind in COLUMNS.items()
                           if name not in ("round_size", "round_completed", "user_equation")}
            record = make_attempt(make_problem("addition", 10, 2, 3), "user_001", "old_session",
                                  1, "normal", 5, 1.5, 1)
            with closing(sqlite3.connect(path)) as db, db:
                definitions = ", ".join(f'"{name}" {kind}' for name, kind in old_columns.items())
                db.execute(f"CREATE TABLE attempts ({definitions})")
                names = list(old_columns)
                db.execute(f"INSERT INTO attempts ({', '.join(names)}) VALUES ({', '.join('?' for _ in names)})",
                           [record[name] for name in names])
            init_db(path)
            init_db(path)
            with closing(sqlite3.connect(path)) as db:
                db.row_factory = sqlite3.Row
                saved = dict(db.execute("SELECT * FROM attempts").fetchone())
                self.assertIn("round_size", saved)
                self.assertIn("round_completed", saved)
                self.assertIn("user_equation", saved)
                self.assertIsNone(saved["user_equation"])
                self.assertEqual(saved["attempt_id"], record["attempt_id"])
                self.assertEqual(saved["user_answer"], 5)
                self.assertFalse(saved["round_completed"])
                self.assertEqual(db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0], 1)

    def test_all_problem_bounds_and_attributes(self):
        for limit in (10, 20):
            for operation in ("addition", "subtraction"):
                for left in range(limit + 1):
                    for right in range(limit + 1):
                        if (left + right > limit if operation == "addition" else right > left):
                            continue
                        problem = make_problem(operation, limit, left, right)
                        self.assertTrue(0 <= problem["correct_answer"] <= limit)
                        self.assertEqual(problem["zero_included"], 0 in (left, right))
                        if operation == "addition":
                            self.assertIsNone(problem["borrowing"])
                            self.assertEqual(problem["carry"], left % 10 + right % 10 >= 10)
                        else:
                            self.assertIsNone(problem["carry"])
                            self.assertEqual(problem["borrowing"], left % 10 < right % 10)

    def test_tag_examples_and_ten_boundary(self):
        addition = make_problem("addition", 20, 8, 5)
        subtraction = make_problem("subtraction", 20, 13, 8)
        self.assertTrue(addition["carry"] and addition["crosses_10"] and addition["near_10"])
        self.assertTrue(subtraction["borrowing"] and subtraction["crosses_10"])
        ten = make_problem("addition", 10, 7, 3)
        self.assertTrue(ten["carry"] and ten["answer_is_10"])
        self.assertFalse(ten["crosses_10"])
        self.assertEqual(ten["commutative_pair"], make_problem("addition", 10, 3, 7)["commutative_pair"])

    def test_sets_are_unique_and_mix_balanced(self):
        for limit in (10, 20):
            for mode in ("addition", "subtraction", "mix"):
                problems = generate_problems(mode, limit)
                self.assertEqual(len({p["problem_id"] for p in problems}), 10)
                if mode == "mix":
                    self.assertEqual(sum(p["operation"] == "addition" for p in problems), 5)
                else:
                    self.assertTrue(all(p["operation"] == mode for p in problems))

    def test_append_retry_user_separation_and_duplicate_delivery(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "history.sqlite3"
            init_db(path)
            problem = make_problem("subtraction", 20, 13, 8)
            first = make_attempt(problem, "user_001", "normal-session", 7, "normal", 6, 4.2, 1)
            retry = make_attempt(problem, "user_001", "retry-session", 1, "retry", 5, 2.1, 2)
            other = make_attempt(problem, "user_002", "other-session", 1, "normal", 5, 1, 1)
            self.assertEqual(set(first), set(COLUMNS))
            for record in (first, retry, other, retry):
                save_attempt(record, path)
            with closing(sqlite3.connect(path)) as db:
                rows = db.execute("SELECT question_order, selection_type, attempt_count, is_correct "
                                  "FROM attempts WHERE user_id = ? ORDER BY attempt_count", ("user_001",)).fetchall()
                self.assertEqual(rows, [(7, "normal", 1, 0), (1, "retry", 2, 1)])
                self.assertEqual(db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0], 3)
                self.assertIsNone(db.execute("SELECT story_type FROM attempts LIMIT 1").fetchone()[0])


class ReadingHelpStorageTests(unittest.TestCase):
    def test_migration_preserves_old_unknown_and_new_original_answer(self):
        from hint_metrics import summarize_hints
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "history.sqlite3"
            problem = make_problem("subtraction", 20, 13, 8)
            old = make_attempt(problem, "user_001", "old", 1, "normal", 6, 2, 1)
            old.pop("reading_help_used")
            with closing(sqlite3.connect(path)) as db, db:
                columns = {name: kind for name, kind in COLUMNS.items() if name != "reading_help_used"}
                db.execute("CREATE TABLE attempts (" + ", ".join(f'"{n}" {k}' for n, k in columns.items()) + ")")
                db.execute("INSERT INTO attempts (" + ", ".join(columns) + ") VALUES (" +
                           ", ".join("?" for _ in columns) + ")", [old[name] for name in columns])
            init_db(path)
            new = make_attempt(problem, "user_001", "new", 1, "normal", 5, 3, 1,
                               hint_used=False, reading_help_used=True)
            save_attempt(new, path)
            rows, _ = learning.read_attempts("user_001", path=path)
            by_id = {row["attempt_id"]: row for row in rows}
            self.assertIsNone(by_id[old["attempt_id"]]["reading_help_used"])
            self.assertEqual(by_id[new["attempt_id"]]["reading_help_used"], 1)
            self.assertEqual(by_id[new["attempt_id"]]["hint_used"], 0)
            self.assertEqual(by_id[new["attempt_id"]]["question_text"], problem["question_text"])
            self.assertEqual((by_id[new["attempt_id"]]["user_answer"], by_id[new["attempt_id"]]["is_correct"]), (5, 1))
            summary = summarize_hints(rows)
            self.assertEqual((summary["reading_known_count"], summary["reading_unknown_count"]), (1, 1))
            self.assertEqual((summary["reading_help_rate"], summary["hint_rate"], summary["unaided_rate"]), (1, 0, .5))

    def test_reading_confirmation_rejects_non_boolean_flags(self):
        problem = make_problem("addition", 10, 2, 3)
        for invalid in (None, 0, 1, "true", "false", [], {}):
            with self.subTest(value=invalid), self.assertRaises(ValueError):
                make_attempt(problem, "user_001", "s", 1, "normal", 5, 2, 1, reading_help_used=invalid)


class CloudStorageTests(unittest.TestCase):
    """外部通信をモックし、クラウド指定時にローカルへ逃げないことを確認。"""

    def setUp(self):
        environment = patch.dict(os.environ, test_environment(), clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        secrets = patch("streamlit.secrets", {})
        secrets.start()
        self.addCleanup(secrets.stop)
        self.config = {"SUPABASE_URL": "https://example.supabase.co", "SUPABASE_SECRET_KEY": "sb_secret_test_only"}
        self.record = make_attempt(make_problem("addition", 20, 8, 5), "user_001", "session_test", 1,
                                   "normal", 13, 2.5, 1)

    def test_missing_cloud_config_keeps_local_and_explicit_path_stays_local(self):
        self.assertIsNone(learning.get_supabase_config())
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, self.config), \
                patch("learning.supabase_urlopen") as remote:
            path = Path(folder) / "local.sqlite3"
            init_db(path)
            save_attempt(self.record, path)
            remote.assert_not_called()
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0], 1)

    def test_incomplete_or_invalid_config_never_falls_back(self):
        cases = [
            {"SUPABASE_URL": self.config["SUPABASE_URL"]},
            {"SUPABASE_SECRET_KEY": self.config["SUPABASE_SECRET_KEY"]},
            dict(self.config, SUPABASE_URL=""),
            dict(self.config, SUPABASE_URL="http://example.supabase.co"),
            dict(self.config, SUPABASE_SECRET_KEY="public-anon-key"),
        ]
        for config in cases:
            with self.subTest(config=config), patch.dict(os.environ, test_environment(config), clear=True), \
                    patch("learning.sqlite3.connect") as local, patch("learning.supabase_urlopen") as remote:
                with self.assertRaises(ValueError):
                    init_db()
                with self.assertRaises(ValueError):
                    save_attempt(self.record)
                local.assert_not_called()
                remote.assert_not_called()

    def test_env_overrides_secrets_and_secrets_alone_enable_cloud(self):
        secret_config = dict(self.config, SUPABASE_URL="https://secrets.supabase.co")
        with patch("streamlit.secrets", secret_config):
            self.assertIsNotNone(learning.get_supabase_config())
            with patch.dict(os.environ, self.config), patch("learning.supabase_urlopen") as remote:
                remote.return_value.__enter__.return_value.status = 201
                save_attempt(self.record)
                self.assertTrue(remote.call_args.args[0].full_url.startswith(self.config["SUPABASE_URL"]))

    def test_cloud_payload_and_duplicate_request_preserve_attempt_id(self):
        with patch.dict(os.environ, self.config), patch("learning.sqlite3.connect") as local, \
                patch("learning.supabase_urlopen") as remote:
            remote.return_value.__enter__.return_value.status = 201
            init_db()
            save_attempt(self.record)
            save_attempt(self.record)
            local.assert_not_called()
            self.assertEqual(remote.call_count, 2)
            for call in remote.call_args_list:
                request = call.args[0]
                self.assertEqual(request.get_method(), "POST")
                self.assertEqual(request.full_url, "https://example.supabase.co/rest/v1/math_attempts?on_conflict=attempt_id")
                headers = {key.lower(): value for key, value in request.header_items()}
                self.assertEqual(headers["apikey"], self.config["SUPABASE_SECRET_KEY"])
                self.assertIn("resolution=ignore-duplicates", headers["prefer"])
                self.assertIn("return=minimal", headers["prefer"])
                payload = json.loads(request.data)
                if isinstance(payload, list):
                    self.assertEqual(len(payload), 1)
                    payload = payload[0]
                self.assertEqual(payload, self.record)

    def test_cloud_roundtrip_preserves_reading_flag_without_changing_hint_or_answer(self):
        current = dict(self.record, reading_help_used=True, hint_used=False)
        with patch.dict(os.environ, self.config), patch("learning.supabase_urlopen") as remote:
            response = remote.return_value.__enter__.return_value
            response.status = 201
            save_attempt(current)
            posted = json.loads(remote.call_args.args[0].data)
            self.assertEqual(posted, current)
            self.assertTrue(posted["reading_help_used"])
            self.assertFalse(posted["hint_used"])
            response.status = 200
            response.read.return_value = json.dumps([posted]).encode()
            rows, more = learning.read_attempts("user_001")
            self.assertFalse(more)
            self.assertEqual(rows, [current])

    def test_cloud_payload_saves_written_equation_and_all_three_judgments(self):
        from words import make_word_problem

        record = make_attempt(make_word_problem("decrease", 20, 13, 8), "user_001", "written", 1,
                              "normal", 4, 2.5, 1, selected_operation="subtraction",
                              equation_left=12, equation_right=8)
        with patch.dict(os.environ, self.config), patch("learning.supabase_urlopen") as remote:
            remote.return_value.__enter__.return_value.status = 201
            save_attempt(record)
            payload = json.loads(remote.call_args.args[0].data)
            self.assertEqual(payload["user_equation"], "12 − 8")
            self.assertTrue(payload["operation_selection_correct"])
            self.assertFalse(payload["equation_correct"])
            self.assertTrue(payload["calculation_correct"])
            self.assertFalse(payload["is_correct"])

    def test_remote_errors_never_write_sqlite_or_expose_key(self):
        errors = [URLError("network failure"),
                  HTTPError("https://example.supabase.co", 401, "invalid key", {}, None)]
        for error in errors:
            with self.subTest(error=type(error).__name__), patch.dict(os.environ, self.config), \
                    patch("learning.sqlite3.connect") as local, \
                    patch("learning.supabase_urlopen", side_effect=error):
                with self.assertRaises(OSError) as raised:
                    save_attempt(self.record)
                self.assertNotIn(self.config["SUPABASE_SECRET_KEY"], str(raised.exception))
                local.assert_not_called()

    def test_cloud_history_uses_user_filter_and_pagination(self):
        records = [dict(self.record, attempt_id=f"attempt_{index}") for index in range(4)]
        with patch.dict(os.environ, self.config), patch("learning.sqlite3.connect") as local, \
                patch("learning.supabase_urlopen") as remote:
            response = remote.return_value.__enter__.return_value
            response.status = 200
            response.read.return_value = json.dumps(records).encode("utf-8")
            history, has_more = learning.read_attempts("user_001", page=2, page_size=3)
            self.assertEqual(history, records[:3])
            self.assertTrue(has_more)
            request = remote.call_args.args[0]
            self.assertEqual(request.get_method(), "GET")
            query = parse_qs(urlsplit(request.full_url).query)
            self.assertEqual(query["user_id"], ["eq.user_001"])
            self.assertEqual(query["offset"], ["6"])
            self.assertEqual(query["limit"], ["4"])
            self.assertEqual(query["order"], ["datetime.desc,attempt_id.desc"])
            self.assertEqual(query["select"], ["*"])
            self.assertEqual(dict((k.lower(), v) for k, v in request.header_items())["apikey"],
                             self.config["SUPABASE_SECRET_KEY"])
            local.assert_not_called()

    def test_cloud_history_errors_are_hidden_and_have_no_local_fallback(self):
        for failure in (URLError(self.config["SUPABASE_SECRET_KEY"]),
                        HTTPError("https://example.supabase.co", 403, self.config["SUPABASE_SECRET_KEY"], {}, None)):
            with self.subTest(failure=type(failure).__name__), patch.dict(os.environ, self.config), \
                    patch("learning.sqlite3.connect") as local, \
                    patch("learning.supabase_urlopen", side_effect=failure):
                with self.assertRaises(OSError) as raised:
                    learning.read_attempts("user_002")
                self.assertNotIn(self.config["SUPABASE_SECRET_KEY"], str(raised.exception))
                local.assert_not_called()

    def test_cloud_month_history_reads_all_pages_with_jst_bounds(self):
        records = [dict(self.record, attempt_id=f"month_{index:04}",
                        datetime="2026-10-07T20:00:00+09:00") for index in range(605)]
        with patch.dict(os.environ, self.config), patch("learning.sqlite3.connect") as local, \
                patch("learning.supabase_urlopen") as remote:
            response = remote.return_value.__enter__.return_value
            response.status = 200
            response.read.side_effect = [json.dumps(records[offset:offset + 101]).encode("utf-8")
                                         for offset in range(0, 605, 100)]
            loaded = learning.read_month_attempts("user_001", 2026, 10)
            self.assertEqual(loaded, records)
            self.assertEqual(remote.call_count, 7)
            for index, call in enumerate(remote.call_args_list):
                query = parse_qs(urlsplit(call.args[0].full_url).query)
                self.assertEqual(query["user_id"], ["eq.user_001"])
                self.assertEqual(query["offset"], [str(index * 100)])
                self.assertEqual(query["datetime"], ["gte.2026-09-30T15:00:00+00:00",
                                                     "lt.2026-10-31T15:00:00+00:00"])
            local.assert_not_called()


class HistoryStorageTests(unittest.TestCase):
    def test_local_history_separates_users_and_paginates_with_stable_order(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "history.sqlite3"
            init_db(path)
            problem = make_problem("subtraction", 20, 13, 8)
            for attempt_id, user_id, timestamp in [
                ("attempt_a", "user_001", "2026-10-07T19:00:00+09:00"),
                ("attempt_c", "user_001", "2026-10-07T20:00:00+09:00"),
                ("attempt_b", "user_001", "2026-10-07T20:00:00+09:00"),
                ("attempt_z", "user_002", "2026-10-07T21:00:00+09:00"),
            ]:
                record = make_attempt(problem, user_id, "history_test", 1, "normal", 5, 1, 1)
                record.update(attempt_id=attempt_id, datetime=timestamp)
                save_attempt(record, path)
            first, more = learning.read_attempts("user_001", page_size=2, path=path)
            second, last_more = learning.read_attempts("user_001", page=1, page_size=2, path=path)
            self.assertEqual([r["attempt_id"] for r in first], ["attempt_c", "attempt_b"])
            self.assertEqual([r["attempt_id"] for r in second], ["attempt_a"])
            self.assertTrue(more)
            self.assertFalse(last_more)
            self.assertTrue(all(r["user_id"] == "user_001" for r in first + second))
            self.assertEqual(learning.read_attempts("user_001", page=2, page_size=2, path=path), ([], False))
            other, _ = learning.read_attempts("user_002", path=path)
            self.assertEqual([r["attempt_id"] for r in other], ["attempt_z"])

    def test_history_rejects_bad_user_and_pagination_before_storage_access(self):
        cases = [("unknown", 0, 50), ("user_001' OR 1=1 --", 0, 50),
                 ("user_001", -1, 50), ("user_001", True, 50),
                 ("user_001", 0, 0), ("user_001", 0, 101)]
        for user, page, size in cases:
            with self.subTest(user=user, page=page, size=size), patch("learning.sqlite3.connect") as local, \
                    patch("learning.supabase_urlopen") as remote:
                with self.assertRaises(ValueError):
                    learning.read_attempts(user, page=page, page_size=size)
                local.assert_not_called()
                remote.assert_not_called()


class AuthenticationTests(unittest.TestCase):
    """公開設定で認証前に履歴初期化や学習画面へ進まないことを検証。"""

    def setUp(self):
        self.environment = patch.dict(os.environ, test_environment(), clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        secrets = patch("streamlit.secrets", {})
        secrets.start()
        self.addCleanup(secrets.stop)
        storage = patch("learning.init_db")
        self.init_mock = storage.start()
        self.addCleanup(storage.stop)

    def app(self):
        return AppTest.from_file(str(Path(__file__).with_name("app.py")), default_timeout=10).run()

    def test_password_required_without_password_stops_before_storage(self):
        os.environ["MATH_REQUIRE_PASSWORD"] = "true"
        app = self.app()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(len(app.error), 1)
        self.assertEqual(len(app.button), 0)
        self.init_mock.assert_not_called()

    def test_wrong_password_blocks_and_correct_password_persists(self):
        os.environ.update(MATH_REQUIRE_PASSWORD="true", MATH_APP_PASSWORD="test-family-password")
        app = self.app()
        self.assertEqual(len(app.text_input), 1)
        self.init_mock.assert_not_called()
        app.text_input(key="family_password").input("wrong")
        app.button[0].click().run()
        self.assertEqual(len(app.error), 1)
        self.assertFalse(any(button.key == "select_user_001" for button in app.button))
        self.init_mock.assert_not_called()
        app.text_input(key="family_password").input("test-family-password")
        app.button[0].click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertTrue(app.session_state.access_granted)
        self.assertEqual(len(app.text_input), 0)
        self.assertTrue({"select_user_001", "select_user_002", "parent_test_start"}.issubset({b.key for b in app.button}))
        self.init_mock.assert_called()
        app.run()
        self.assertEqual(len(app.text_input), 0)
        app.button(key="select_user_002").click().run()
        self.assertEqual(app.session_state.user_id, "user_002")

    def test_default_local_is_open_and_secrets_can_require_password(self):
        app = self.app()
        self.assertEqual(len(app.text_input), 0)
        self.assertTrue({"select_user_001", "select_user_002", "parent_test_start"}.issubset({b.key for b in app.button}))
        with patch("streamlit.secrets", {"MATH_REQUIRE_PASSWORD": True,
                                         "MATH_APP_PASSWORD": "test-secret-password"}):
            protected = self.app()
            self.assertEqual(len(protected.text_input), 1)
            self.assertFalse(any(button.key == "select_user_001" for button in protected.button))


class AppFlowTests(unittest.TestCase):
    """実データに触れず、画面進行と1回答1保存の境界を検証します。"""

    def setUp(self):
        environment = patch.dict(os.environ, test_environment(), clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        secrets = patch("streamlit.secrets", {})
        secrets.start()
        self.addCleanup(secrets.stop)
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / "history.sqlite3"
        original_init = learning.init_db
        original_save = learning.save_attempt
        original_read = learning.read_attempts
        original_month_read = learning.read_month_attempts
        self.save_record = lambda record: original_save(record, self.path)
        self.init_patch = patch("learning.init_db", lambda: original_init(self.path))
        self.save_patch = patch("learning.save_attempt", side_effect=self.save_record)
        self.read_patch = patch("learning.read_attempts",
                                side_effect=lambda user_id, page=0, page_size=50, **kwargs:
                                original_read(user_id, page=page, page_size=page_size,
                                              **dict(kwargs, path=self.path)))
        self.month_patch = patch("learning.read_month_attempts",
                                 side_effect=lambda user_id, year, month:
                                 original_month_read(user_id, year, month, path=self.path))
        self.init_patch.start()
        self.save_mock = self.save_patch.start()
        self.read_mock = self.read_patch.start()
        self.month_mock = self.month_patch.start()
        self.addCleanup(self.init_patch.stop)
        self.addCleanup(self.save_patch.stop)
        self.addCleanup(self.read_patch.stop)
        self.addCleanup(self.month_patch.stop)
        self.app = AppTest.from_file(str(Path(__file__).with_name("app.py")), default_timeout=10).run()

    def click_label(self, label):
        next(button for button in self.app.button if button.label == label).click().run()
        self.assertEqual(len(self.app.exception), 0)

    def start(self, user_key="select_user_001"):
        self.app.button(key=user_key).click().run()
        self.click_label("れんしゅう スタート")

    def event(self, action, answer=None, selected_operation=None, equation_left=None, equation_right=None,
              seconds=1.25, draft=None):
        state = self.app.session_state.round
        token = f"{state['session_id']}:{state['index']}:{state['phase']}"
        revision = state.get("equation_revision", {}).get(state["index"], 0)
        if revision:
            token += f":edit{revision}"
        interaction_revision = state.get("interaction_revision", {}).get(state["index"], 0)
        if interaction_revision:
            token += f":ui{interaction_revision}"
        event = {"token": token, "action": action, "answer": answer, "response_time_sec": seconds}
        if draft is not None:
            event["draft"] = draft
        if selected_operation is not None:
            event["selected_operation"] = selected_operation
        if equation_left is not None:
            event["equation_left"] = equation_left
        if equation_right is not None:
            event["equation_right"] = equation_right
        self.app.session_state["answer_keyboard"] = event
        self.app.run()
        self.assertEqual(len(self.app.exception), 0)
        return event

    def rows(self):
        with closing(sqlite3.connect(self.path)) as db:
            db.row_factory = sqlite3.Row
            return [dict(row) for row in db.execute("SELECT * FROM attempts ORDER BY rowid")]

    def assert_round_preserved(self, before):
        """画面往復で更新する下書き・時刻以外の学習記録を保持しているか。"""
        navigation_fields = {"drafts", "interaction_revision", "suspended"}
        current = {key: value for key, value in self.app.session_state.round.items() if key not in navigation_fields}
        expected = {key: value for key, value in before.items() if key not in navigation_fields}
        self.assertEqual(current, expected)

    def test_full_round_retry_and_user_switch_keep_separate_records(self):
        self.start()
        original_session = self.app.session_state.round["session_id"]
        for index in range(10):
            state = self.app.session_state.round
            correct = state["problems"][index]["correct_answer"]
            self.event("answer", correct + 1 if index in (2, 8) else correct)
            self.assertEqual(len(self.rows()), index + 1)
            self.event("next")
        self.assertEqual(self.app.session_state.screen, "results")
        self.assertEqual(self.app.metric[1].value, "80%")
        originals = self.rows()
        self.click_label("まちがえた もんだいを もういちど")
        self.assertNotEqual(self.app.session_state.round["session_id"], original_session)
        self.assertEqual([p["problem_id"] for p in self.app.session_state.round["problems"]],
                         [originals[2]["problem_id"], originals[8]["problem_id"]])
        for index in range(2):
            state = self.app.session_state.round
            self.event("answer", state["problems"][index]["correct_answer"])
            self.event("next")
        self.assertEqual(self.app.metric[1].value, "100%")
        records = self.rows()
        self.assertEqual(records[:10], originals)
        self.assertEqual([(r["question_order"], r["selection_type"], r["attempt_count"], r["retry_flag"])
                          for r in records[10:]], [(1, "retry", 2, 1), (2, "retry", 2, 1)])
        self.click_label("なまえを かえる")
        self.start("select_user_002")
        problem = self.app.session_state.round["problems"][0]
        self.event("answer", problem["correct_answer"])
        self.assertEqual(self.rows()[-1]["user_id"], "user_002")
        self.assertEqual(self.rows()[-1]["attempt_count"], 1)
        self.assertTrue(all(r["user_id"] == "user_001" for r in self.rows()[:-1]))

    def test_stale_and_repeated_events_do_not_create_answers(self):
        self.start()
        self.app.session_state["answer_keyboard"] = {"token": "old-token", "action": "answer", "answer": 1,
                                                     "response_time_sec": 1}
        self.app.run()
        self.assertEqual(self.rows(), [])
        answer = self.app.session_state.round["problems"][0]["correct_answer"]
        delivered = self.event("answer", answer)
        self.app.session_state["answer_keyboard"] = delivered
        self.app.run()
        self.assertEqual(len(self.rows()), 1)
        self.assertEqual(len(self.app.session_state.round["answers"]), 1)

    def test_save_failure_retries_pending_record_without_component_event(self):
        self.start()
        self.save_mock.side_effect = sqlite3.OperationalError("temporary failure")
        answer = self.app.session_state.round["problems"][0]["correct_answer"]
        self.event("answer", answer)
        state = self.app.session_state.round
        pending = dict(state["pending_record"])
        self.assertEqual(state["phase"], "question")
        self.assertEqual(state["answers"], [])
        self.assertEqual(self.rows(), [])
        self.save_mock.side_effect = self.save_record
        self.app.session_state["answer_keyboard"] = None
        self.app.button(key="retry_save").click().run()
        self.assertEqual(len(self.app.exception), 0)
        self.assertEqual(self.app.session_state.round["phase"], "feedback")
        self.assertEqual(self.app.session_state.round["answers"], [pending])
        self.assertEqual(self.rows()[0]["attempt_id"], pending["attempt_id"])
        self.assertEqual(self.rows()[0]["user_answer"], answer)
        self.assertEqual(self.rows()[0]["response_time_sec"], 1.25)

    def test_history_empty_and_read_failure_can_reload_without_losing_selection(self):
        self.app.button(key="select_user_001").click().run()
        self.app.button(key="history_settings").click().run()
        self.assertEqual(self.app.session_state.screen, "history")
        self.assertEqual(len(self.app.exception), 0)
        self.assertEqual(len(self.app.dataframe), 0)
        self.assertTrue(any("まだ" in message.value for message in self.app.info))
        self.assertEqual(self.read_mock.call_args.args[0], "user_001")
        self.read_mock.side_effect = OSError("sb_secret_should_never_show")
        self.app.run()
        self.assertEqual(len(self.app.exception), 0)
        self.assertEqual(len(self.app.error), 1)
        self.assertNotIn("sb_secret_should_never_show", self.app.error[0].value)
        self.read_mock.side_effect = lambda *args, **kwargs: ([], False)
        self.app.button(key="history_reload").click().run()
        self.assertEqual(len(self.app.error), 0)
        self.app.button(key="history_back").click().run()
        self.assertEqual(self.app.session_state.screen, "settings")
        self.assertEqual(self.app.session_state.user_id, "user_001")

    def test_report_targets_selected_user_and_starts_recommended_practice(self):
        for index in range(10):
            record = make_attempt(make_problem("subtraction", 20, 13, 8), "user_001", "report_test",
                                  index + 1, "normal", 6, 2, 1)
            self.save_record(record)
        other = make_attempt(make_problem("addition", 10, 2, 3), "user_002", "other",
                             1, "normal", 5, 1, 1)
        self.save_record(other)
        self.app.button(key="select_user_001").click().run()
        self.app.button(key="report_settings").click().run()
        self.assertEqual(len(self.app.exception), 0)
        self.assertEqual(self.app.metric[0].value, "10問")
        self.assertEqual(self.app.metric[1].value, "0%")
        self.assertEqual(len(self.app.dataframe[0].value), 1)
        self.app.button(key="report_back").click().run()
        self.assertEqual(self.app.session_state.screen, "settings")
        self.app.button(key="report_settings").click().run()
        self.app.button(key="report_practice").click().run()
        self.assertEqual(len(self.app.exception), 0)
        self.assertEqual(self.app.session_state.screen, "practice")
        self.assertEqual(self.app.session_state.round["selection_type"], "normal")
        problems = self.app.session_state.round["problems"]
        self.assertEqual(len(problems), 5)
        self.assertTrue(all(p["operation"] == "subtraction" and p["borrowing"] for p in problems))
        self.assertEqual(len(self.rows()), 11)

    def test_report_failure_reload_and_return_preserve_active_round(self):
        self.start()
        before = deepcopy(self.app.session_state.round)
        self.event("open_history")
        self.app.button(key="report_history").click().run()
        self.assertEqual(len(self.app.exception), 0)
        self.read_mock.side_effect = OSError("private_database_error")
        self.app.run()
        self.assertEqual(len(self.app.error), 1)
        self.assertNotIn("private_database_error", self.app.error[0].value)
        self.read_mock.side_effect = lambda *args, **kwargs: ([], False)
        self.app.button(key="report_reload").click().run()
        self.assertEqual(len(self.app.error), 0)
        self.app.button(key="report_back").click().run()
        self.assertEqual(self.app.session_state.screen, "history")
        self.app.button(key="history_back").click().run()
        self.assert_round_preserved(before)

    def test_report_uses_up_to_500_answers_across_history_pages(self):
        record = make_attempt(make_problem("addition", 10, 2, 3), "user_001", "sample",
                              1, "normal", 5, 1, 1)
        records = [dict(record, attempt_id=f"report_{index:04}") for index in range(501)]
        self.read_mock.side_effect = lambda user_id, page=0, page_size=50: (
            records[page * page_size:(page + 1) * page_size],
            (page + 1) * page_size < len(records))
        self.app.button(key="select_user_001").click().run()
        self.app.button(key="report_settings").click().run()
        self.assertEqual(len(self.app.exception), 0)
        self.assertEqual(self.app.metric[0].value, "500問")
        # 復習を別枠で集計するため全ページを取得し、通常の評価は500回答を保つ。
        self.assertEqual(self.read_mock.call_count, 6)
        self.assertTrue(any("直近500回答" in caption.value for caption in self.app.caption))

    def test_history_user_switch_and_page_navigation(self):
        for index in range(51):
            record = make_attempt(make_problem("addition", 20, 8, 5), "user_001", "history_one", index + 1,
                                  "normal", 13, 1, 1)
            record.update(attempt_id=f"history_{index:03}", datetime="2026-10-07T20:00:00+09:00")
            self.save_record(record)
        other = make_attempt(make_problem("subtraction", 20, 13, 8), "user_002", "history_two", 1,
                             "normal", 5, 1, 1)
        self.save_record(other)
        self.app.button(key="select_user_001").click().run()
        self.app.button(key="history_settings").click().run()
        self.assertEqual(len(self.app.exception), 0)
        self.assertEqual(len(self.app.dataframe[0].value), 50)
        self.app.button(key="history_next").click().run()
        self.assertEqual(self.app.session_state.history_page, 1)
        self.assertEqual(len(self.app.dataframe[0].value), 1)
        self.assertTrue(self.app.button(key="history_next").disabled)
        self.app.button(key="history_prev").click().run()
        self.assertEqual(self.app.session_state.history_page, 0)
        self.app.button(key="history_back").click().run()
        self.click_label("なまえを かえる")
        self.app.button(key="select_user_002").click().run()
        self.app.button(key="history_settings").click().run()
        self.assertEqual(self.app.session_state.history_page, 0)
        self.assertEqual(self.read_mock.call_args.args[0], "user_002")
        table = self.app.dataframe[0].value
        self.assertEqual(len(table), 1)
        self.assertIn("13 − 8 = ?", table.to_string())
        self.assertNotIn("8 + 5 = ?", table.to_string())

    def test_history_from_results_returns_to_same_round_and_can_retry(self):
        self.start()
        for index in range(10):
            state = self.app.session_state.round
            answer = state["problems"][index]["correct_answer"]
            self.event("answer", answer + 1 if index == 0 else answer)
            self.event("next")
        original_round = dict(self.app.session_state.round)
        self.app.button(key="history_results").click().run()
        self.assertEqual(self.app.session_state.screen, "history")
        self.assertEqual(len(self.app.dataframe[0].value), 10)
        self.app.button(key="history_back").click().run()
        self.assertEqual(self.app.session_state.screen, "results")
        self.assertEqual(self.app.session_state.round, original_round)
        self.click_label("まちがえた もんだいを もういちど")
        self.assertEqual(self.app.session_state.round["selection_type"], "retry")
        self.assertEqual(len(self.app.session_state.round["problems"]), 1)

    def test_history_during_practice_preserves_question_and_feedback_without_duplicate_save(self):
        self.start()
        before = deepcopy(self.app.session_state.round)
        self.event("open_history")
        self.assertEqual(self.app.session_state.screen, "history")
        self.app.button(key="history_back").click().run()
        self.assertEqual(self.app.session_state.screen, "practice")
        self.assert_round_preserved(before)
        self.assertEqual(self.rows(), [])
        answer_event = self.event("answer", before["problems"][0]["correct_answer"])
        feedback = deepcopy(self.app.session_state.round)
        self.event("open_history")
        self.app.button(key="history_back").click().run()
        self.assert_round_preserved(feedback)
        self.assertEqual(len(self.rows()), 1)

        self.app.session_state["answer_keyboard"] = answer_event
        self.app.run()
        self.assert_round_preserved(feedback)
        self.assertEqual(len(self.rows()), 1)
        self.event("next")
        self.assertEqual(self.app.session_state.round["index"], 1)
        self.assertEqual(self.app.session_state.round["phase"], "question")
        self.assertEqual(len(self.rows()), 1)

    def test_practice_settings_and_empty_calendar_return(self):
        self.app.button(key="select_user_001").click().run()
        self.app.button(key="calendar_settings").click().run()
        self.assertEqual(len(self.app.exception), 0)
        self.assertEqual(self.app.session_state.screen, "calendar")
        self.app.number_input(key="calendar_year").set_value(2024).run()
        self.app.selectbox(key="calendar_month").set_value(2).run()
        html = next(item.value for item in self.app.markdown if "<table" in item.value)
        self.assertEqual([int(day) for day in re.findall(r'<td[^>]*>(\d+)<br>', html)], list(range(1, 30)))
        self.app.number_input(key="calendar_year").set_value(2025).run()
        html = next(item.value for item in self.app.markdown if "<table" in item.value)
        self.assertEqual([int(day) for day in re.findall(r'<td[^>]*>(\d+)<br>', html)], list(range(1, 29)))
        self.month_mock.side_effect = OSError("private_month_error")
        self.app.run()
        self.assertEqual(len(self.app.error), 1)
        self.assertNotIn("private_month_error", self.app.error[0].value)
        self.month_mock.side_effect = lambda *args: []
        self.app.button(key="calendar_reload").click().run()
        self.assertEqual(len(self.app.error), 0)
        self.app.button(key="calendar_back").click().run()
        self.assertEqual(self.app.session_state.screen, "settings")
        self.app.radio(key="special_mode").set_value("with").run()
        start_button = next(button for button in self.app.button if button.label == "れんしゅう スタート")
        self.assertTrue(start_button.disabled)
        self.app.radio(key="problem_count").set_value(5).run()
        self.app.radio(key="special_mode").set_value("none").run()
        self.click_label("れんしゅう スタート")
        problems = self.app.session_state.round["problems"]
        self.assertEqual(len(problems), 5)
        self.assertTrue(all(not problem["carry"] for problem in problems))

    def test_final_answer_save_failure_and_retry_completion_make_durable_stamps_once(self):
        from activity import month_summary
        from datetime import datetime

        self.app.button(key="select_user_001").click().run()
        self.app.radio(key="problem_count").set_value(5).run()
        self.click_label("れんしゅう スタート")
        for index in range(4):
            answer = self.app.session_state.round["problems"][index]["correct_answer"]
            self.event("answer", answer + 1 if index == 0 else answer)
            self.event("next")
        self.save_mock.side_effect = OSError("save failed")
        answer = self.app.session_state.round["problems"][4]["correct_answer"]
        self.event("answer", answer)
        pending = deepcopy(self.app.session_state.round["pending_record"])
        self.assertTrue(pending["round_completed"])
        self.assertEqual(pending["round_size"], 5)
        timestamp = datetime.fromisoformat(pending["datetime"])
        self.assertEqual(month_summary(self.rows(), timestamp.year, timestamp.month)["stamps"], 0)
        self.assertEqual(len(self.rows()), 4)

        def saved_but_response_lost(record):
            self.save_record(record)
            raise OSError("response lost after save")

        self.save_mock.side_effect = saved_but_response_lost
        self.app.button(key="retry_save").click().run()
        self.assertEqual(len(self.rows()), 5)
        self.assertIsNotNone(self.app.session_state.round["pending_record"])
        self.save_mock.side_effect = self.save_record
        self.app.button(key="retry_save").click().run()
        self.assertEqual(len(self.rows()), 5)
        self.assertEqual(month_summary(self.rows(), timestamp.year, timestamp.month)["stamps"], 1)
        self.event("next")
        self.assertEqual(self.app.session_state.screen, "results")
        self.assertTrue(any("ごほうびスタンプ" in item.value for item in self.app.success))
        self.app.button(key="calendar_results").click().run()
        self.assertEqual(len(self.app.exception), 0)
        self.assertIn("1こ", self.app.metric[0].value)
        self.app.button(key="calendar_back").click().run()
        self.assertEqual(self.app.session_state.screen, "results")
        self.click_label("まちがえた もんだいを もういちど")
        self.event("answer", self.app.session_state.round["problems"][0]["correct_answer"])
        self.event("next")
        self.assertEqual(self.app.session_state.screen, "results")
        self.assertEqual(len(self.rows()), 6)
        self.assertEqual(self.rows()[-1]["selection_type"], "retry")
        self.assertEqual(self.rows()[-1]["round_size"], 1)
        self.assertTrue(self.rows()[-1]["round_completed"])
        self.assertEqual(month_summary(self.rows(), timestamp.year, timestamp.month)["stamps"], 2)
        self.app.button(key="calendar_results").click().run()
        self.assertIn("2こ", self.app.metric[0].value)
        self.app.run()
        self.assertIn("2こ", self.app.metric[0].value)

    def start_words(self):
        self.app.button(key="select_user_001").click().run()
        self.app.radio(key="problem_count").set_value(5).run()
        self.app.radio(key="problem_format").set_value("word_problem").run()
        self.click_label("れんしゅう スタート")

    def test_words_choice_initialization_history_return_and_stale_events(self):
        self.start_words()
        state = self.app.session_state.round
        self.assertEqual(state["phase"], "choose")
        problem = state["problems"][0]
        args = json.loads(self.app.get("component_instance")[0].proto.json_args)
        self.assertNotIn("=", args["question"])
        self.assertIsNone(args.get("equation"))
        self.assertEqual(self.rows(), [])
        self.event("answer", problem["correct_answer"])
        self.assertEqual(self.rows(), [])
        self.assertEqual(self.app.session_state.round["phase"], "choose")
        chosen = self.event("choose_operation", selected_operation=problem["operation"])
        self.assertEqual(self.app.session_state.round["phase"], "equation")
        args = json.loads(self.app.get("component_instance")[0].proto.json_args)
        self.assertIsNone(args.get("equation_left"))
        self.assertIsNone(args.get("equation_right"))
        self.event("submit_equation", selected_operation=problem["operation"],
                   equation_left=problem["left_operand"], equation_right=problem["right_operand"])
        self.assertEqual(self.app.session_state.round["phase"], "question")
        args = json.loads(self.app.get("component_instance")[0].proto.json_args)
        self.assertIn("= ?", args["equation"])
        before = deepcopy(self.app.session_state.round)
        self.event("open_history")
        self.app.button(key="history_back").click().run()
        self.assert_round_preserved(before)
        self.app.session_state["answer_keyboard"] = chosen
        self.app.run()
        self.assert_round_preserved(before)
        answered = self.event("answer", problem["correct_answer"])
        self.assertEqual(len(self.rows()), 1)
        self.assertTrue(self.rows()[0]["is_correct"])
        self.assertTrue(self.rows()[0]["equation_correct"])
        self.assertIsNotNone(self.rows()[0]["user_equation"])
        self.app.session_state["answer_keyboard"] = answered
        self.app.run()
        self.assertEqual(len(self.rows()), 1)
        self.event("next")
        self.assertEqual(self.app.session_state.round["phase"], "choose")
        self.assertIsNone(self.app.session_state.round["selected_operations"].get(1))
        self.assertIsNone(self.app.session_state.round["user_equations"].get(1))

    def test_word_wrong_operation_retry_save_failure_and_reward(self):
        self.start_words()
        state = self.app.session_state.round
        from words import make_word_problem
        state["problems"][0] = make_word_problem("decrease", 20, 13, 8)
        self.app.run()
        self.event("choose_operation", selected_operation="addition")
        self.event("submit_equation", selected_operation="addition", equation_left=13, equation_right=8)
        self.save_mock.side_effect = OSError("word save failed")
        self.event("answer", 21)
        pending = deepcopy(self.app.session_state.round["pending_record"])
        self.assertFalse(pending["operation_selection_correct"])
        self.assertTrue(pending["calculation_correct"])
        self.assertFalse(pending["is_correct"])
        self.assertTrue(pending["equation_correct"])
        self.assertEqual(pending["user_equation"], "13 + 8")
        self.assertEqual(self.rows(), [])
        self.save_mock.side_effect = self.save_record
        self.app.session_state["answer_keyboard"] = None
        self.app.button(key="retry_save").click().run()
        self.assertEqual(self.rows()[0]["attempt_id"], pending["attempt_id"])
        self.assertEqual(self.rows()[0]["user_answer"], 21)
        self.event("next")
        for index in range(1, 5):
            problem = self.app.session_state.round["problems"][index]
            self.event("choose_operation", selected_operation=problem["operation"])
            self.event("submit_equation", selected_operation=problem["operation"],
                       equation_left=problem["left_operand"], equation_right=problem["right_operand"])
            self.event("answer", problem["correct_answer"])
            self.event("next")
        self.assertEqual(self.app.session_state.screen, "results")
        self.assertEqual(self.app.metric[1].value, "80%")
        self.assertTrue(self.rows()[-1]["round_completed"])
        originals = self.rows()
        self.click_label("まちがえた もんだいを もういちど")
        self.assertEqual(self.app.session_state.round["phase"], "choose")
        self.assertEqual(len(self.app.session_state.round["problems"]), 1)
        self.assertEqual(self.app.session_state.round["user_equations"], {})
        self.event("choose_operation", selected_operation="subtraction")
        self.event("submit_equation", selected_operation="subtraction", equation_left=13, equation_right=8)
        self.event("answer", 5)
        self.event("next")
        self.assertEqual(self.app.session_state.screen, "results")
        self.assertEqual(self.app.metric[1].value, "100%")
        self.assertEqual(self.rows()[:5], originals)
        self.assertEqual(self.rows()[-1]["selection_type"], "retry")
        self.assertEqual(self.rows()[-1]["attempt_count"], 2)
        self.assertTrue(self.rows()[-1]["round_completed"])
        self.app.button(key="calendar_results").click().run()
        self.assertEqual(len(self.app.exception), 0)
        self.assertIn("2こ", self.app.metric[0].value)
        self.app.run()
        self.assertIn("2こ", self.app.metric[0].value)

    def test_word_equation_edit_ignores_stale_submission_and_keeps_owned_numbers(self):
        self.start_words()
        from words import make_word_problem

        self.app.session_state.round["problems"][0] = make_word_problem("decrease", 20, 13, 8)
        self.app.run()
        self.event("choose_operation", selected_operation="subtraction")
        submitted = self.event("submit_equation", selected_operation="subtraction", equation_left=12,
                               equation_right=8)
        self.assertEqual(self.app.session_state.round["phase"], "question")
        self.event("edit_equation")
        self.assertEqual(self.app.session_state.round["phase"], "equation")
        before = deepcopy(self.app.session_state.round)
        args = json.loads(self.app.get("component_instance")[0].proto.json_args)
        self.assertEqual(args["equation_left"], 12)
        self.assertEqual(args["equation_right"], 8)
        self.app.session_state["answer_keyboard"] = submitted
        self.app.run()
        self.assert_round_preserved(before)
        self.assertEqual(self.rows(), [])
        self.event("submit_equation", selected_operation="subtraction", equation_left=13,
                   equation_right=8)
        self.event("answer", 5)
        self.assertEqual(len(self.rows()), 1)
        self.assertTrue(self.rows()[0]["equation_correct"])
        self.assertEqual(self.rows()[0]["user_equation"], "13 − 8")

    def test_math_pause_resume_restores_equation_draft_hint_and_elapsed(self):
        self.start_words()
        from words import make_word_problem

        self.app.session_state.round["problems"][0] = make_word_problem("decrease", 20, 13, 8)
        self.app.run()
        self.event("choose_operation", selected_operation="subtraction")
        draft = {"answer": "", "equation_left": "12", "equation_right": "8",
                 "selected_operation": "subtraction"}
        self.event("show_hint", seconds=3, draft=draft)
        args = json.loads(self.app.get("component_instance")[0].proto.json_args)
        self.assertTrue(args["hint_visible"])
        self.assertTrue(args["hint_used"])
        self.event("pause", seconds=8, draft=draft)
        self.assertEqual(self.app.session_state.screen, "settings")
        self.assertEqual(self.rows(), [])
        before = deepcopy(self.app.session_state.round)
        self.app.button(key="math_resume").click().run()
        self.assert_round_preserved(before)
        args = json.loads(self.app.get("component_instance")[0].proto.json_args)
        self.assertEqual(args["draft"]["equation_left"], "12")
        self.assertEqual(args["draft"]["equation_right"], "8")
        self.assertEqual(args["elapsed_sec"], 8)
        self.assertTrue(args["hint_visible"])
        self.event("submit_equation", selected_operation="subtraction", equation_left=13, equation_right=8,
                   seconds=10)
        self.event("answer", 5, seconds=13.5)
        saved = deepcopy(self.rows())
        self.assertEqual(saved[0]["hint_used"], 1)
        self.assertEqual(saved[0]["response_time_sec"], 13.5)
        self.event("show_explanation", seconds=15)
        args = json.loads(self.app.get("component_instance")[0].proto.json_args)
        self.assertTrue(args["explanation_visible"])
        self.assertIn("13 − 8 = 5", args["explanation_text"])
        self.assertEqual(self.rows(), saved)
        self.event("pause", seconds=16)
        self.app.button(key="math_resume").click().run()
        self.assertEqual(self.app.session_state.round["phase"], "feedback")
        self.assertEqual(self.rows(), saved)

    def test_math_paused_round_owner_and_no_hint_remain_separate(self):
        self.start()
        answer = self.app.session_state.round["problems"][0]["correct_answer"]
        self.event("pause", seconds=2, draft={"answer": str(answer), "equation_left": "",
                                              "equation_right": "", "selected_operation": None})
        self.assertTrue(any(button.key == "math_resume" for button in self.app.button))
        self.click_label("なまえを かえる")
        self.app.button(key="select_user_002").click().run()
        self.assertFalse(any(button.key == "math_resume" for button in self.app.button))
        self.click_label("なまえを かえる")
        self.app.button(key="select_user_001").click().run()
        self.app.button(key="math_resume").click().run()
        args = json.loads(self.app.get("component_instance")[0].proto.json_args)
        self.assertEqual(args["draft"]["answer"], str(answer))
        self.assertFalse(args["hint_used"])
        self.save_mock.side_effect = OSError("temporary_failure")
        self.event("answer", answer, seconds=4)
        pending = deepcopy(self.app.session_state.round["pending_record"])
        self.assertFalse(pending["hint_used"])
        self.assertEqual(len(self.app.get("component_instance")), 0)
        self.assertEqual(self.rows(), [])
        self.save_mock.side_effect = self.save_record
        self.app.button(key="retry_save").click().run()
        self.assertEqual(self.rows()[0]["attempt_id"], pending["attempt_id"])
        self.assertEqual(self.rows()[0]["hint_used"], 0)

    def test_reading_confirmation_survives_pause_and_failed_save_without_becoming_hint(self):
        self.start()
        problem = deepcopy(self.app.session_state.round["problems"][0])
        answer = problem["correct_answer"]
        self.event("answer", answer, draft={"reading_help_used": "true"})
        self.assertEqual(self.rows(), [])
        self.assertEqual(self.app.session_state.round["phase"], "question")
        self.event("pause", seconds=3, draft={"answer": str(answer), "reading_help_used": True})
        self.assertEqual(self.rows(), [])
        self.app.button(key="math_resume").click().run()
        args = json.loads(self.app.get("component_instance")[0].proto.json_args)
        self.assertTrue(args["draft"]["reading_help_used"])
        self.assertFalse(args["hint_used"])
        self.save_mock.side_effect = OSError("temporary failure")
        self.event("answer", answer, seconds=5, draft={"reading_help_used": False})
        pending = deepcopy(self.app.session_state.round["pending_record"])
        self.assertTrue(pending["reading_help_used"])
        self.assertFalse(pending["hint_used"])
        self.assertTrue(pending["is_correct"])
        self.assertEqual(pending["question_text"], problem["question_text"])
        self.assertEqual(self.rows(), [])
        self.save_mock.side_effect = self.save_record
        self.app.button(key="retry_save").click().run()
        row = self.rows()[0]
        self.assertEqual(row["attempt_id"], pending["attempt_id"])
        self.assertEqual((row["reading_help_used"], row["hint_used"], row["user_answer"], row["is_correct"]),
                         (1, 0, answer, 1))


if __name__ == "__main__":
    unittest.main()


