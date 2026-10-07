"""将来の分析に必要な、問題属性と回答保存の振る舞いを検証します。"""

import sqlite3
import os
import json
from contextlib import closing
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError, HTTPError

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
        return AppTest.from_file(str(Path(__file__).with_name("app.py"))).run()

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
        self.assertEqual(len(app.button), 2)
        self.init_mock.assert_called()
        app.run()
        self.assertEqual(len(app.text_input), 0)
        app.button(key="select_user_002").click().run()
        self.assertEqual(app.session_state.user_id, "user_002")

    def test_default_local_is_open_and_secrets_can_require_password(self):
        app = self.app()
        self.assertEqual(len(app.text_input), 0)
        self.assertEqual(len(app.button), 2)
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
        self.save_record = lambda record: original_save(record, self.path)
        self.init_patch = patch("learning.init_db", lambda: original_init(self.path))
        self.save_patch = patch("learning.save_attempt", side_effect=self.save_record)
        self.init_patch.start()
        self.save_mock = self.save_patch.start()
        self.addCleanup(self.init_patch.stop)
        self.addCleanup(self.save_patch.stop)
        self.app = AppTest.from_file(str(Path(__file__).with_name("app.py"))).run()

    def click_label(self, label):
        next(button for button in self.app.button if button.label == label).click().run()
        self.assertEqual(len(self.app.exception), 0)

    def start(self, user_key="select_user_001"):
        self.app.button(key=user_key).click().run()
        self.click_label("れんしゅう スタート")

    def event(self, action, answer=None):
        state = self.app.session_state.round
        token = f"{state['session_id']}:{state['index']}:{state['phase']}"
        event = {"token": token, "action": action, "answer": answer, "response_time_sec": 1.25}
        self.app.session_state["answer_keyboard"] = event
        self.app.run()
        self.assertEqual(len(self.app.exception), 0)
        return event

    def rows(self):
        with closing(sqlite3.connect(self.path)) as db:
            db.row_factory = sqlite3.Row
            return [dict(row) for row in db.execute("SELECT * FROM attempts ORDER BY rowid")]

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


if __name__ == "__main__":
    unittest.main()
