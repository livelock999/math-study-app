"""復元画面の確認・再試行・保護者テストを隔離DBで検証します。"""
from copy import deepcopy
from datetime import datetime
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest
import history_backup
import learning
import japanese
from activity import JST
from learning_profiles import default_profile
from japanese_questions import QUESTIONS
from test_learning import test_environment


class BackupUITests(unittest.TestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.math_path = Path(folder.name) / "math.sqlite3"
        self.jp_path = Path(folder.name) / "jp.sqlite3"
        learning.init_db(self.math_path)
        japanese.init_db(self.jp_path)
        self.math = learning.make_attempt(learning.make_problem("addition", 10, 2, 3),
                                          "user_001", "backup_math", 1, "normal", 5, 2, 1)
        q = QUESTIONS[0]
        self.jp = japanese.make_record(q, "user_001", "backup_jp", 1, "normal", q["answer"], 2, 1, "backup_chain")
        self.raw = history_backup.export_backup("user_001", [self.math], [self.jp], now=datetime.now(JST))
        self.upload = BytesIO(self.raw)
        patches = [patch.dict("os.environ", test_environment(), clear=True), patch("streamlit.secrets", {}),
                   patch("learning.DB_PATH", self.math_path), patch("japanese.DB_PATH", self.jp_path),
                   patch("text_display.load_profile", side_effect=default_profile),
                   patch("learning_extensions.read_goals", return_value={"weekly_days": 3, "daily_questions": 5}),
                   patch("learning_extensions.read_feedback", return_value=[]),
                   patch("history_backup_ui.st.file_uploader", side_effect=lambda *a, **k: self.upload)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.app = AppTest.from_file(str(Path(__file__).with_name("app.py")), default_timeout=15).run()

    def click(self, key):
        self.app.button(key=key).click().run()
        self.assertFalse(self.app.exception)

    def open(self, user="user_001", test=False):
        if test:
            self.click("parent_test_start")
        self.click("select_" + user)
        self.click("parent_dashboard_open")

    def confirm(self):
        next(c for c in self.app.checkbox if c.label == "復元先と追加する件数を確認しました").check().run()
        self.assertFalse(self.app.exception)

    def counts(self):
        return len(learning.read_attempts("user_001")[0]), len(japanese.read_all("user_001"))

    def test_review_required_restore_and_idempotent(self):
        self.open()
        self.assertTrue(self.app.button(key="history_backup_restore").disabled)
        self.assertEqual(self.counts(), (0, 0))
        self.confirm()
        self.click("history_backup_restore")
        self.assertEqual(self.counts(), (1, 1))
        self.assertTrue(any("復元しました" in s.value for s in self.app.success))
        self.click("history_backup_restore")
        self.assertEqual(self.counts(), (1, 1))

    def test_response_lost_retry_never_duplicates(self):
        self.open()
        self.confirm()
        restore = history_backup.restore_backup
        requests = []
        def lost(document, **kwargs):
            requests.append(deepcopy(document))
            result = restore(document, **kwargs)
            if len(requests) == 1:
                raise OSError("response lost")
            return result
        with patch("history_backup_ui.backup_store.restore_backup", side_effect=lost):
            self.click("history_backup_restore")
            self.assertTrue(self.app.error)
            self.assertEqual(self.counts(), (1, 1))
            self.click("history_backup_restore")
        self.assertEqual(requests[0], requests[1])
        self.assertEqual(self.counts(), (1, 1))

    def test_other_learner_file_rejected(self):
        self.open("user_002")
        self.assertTrue(self.app.error)
        self.assertFalse(any(b.key == "history_backup_restore" for b in self.app.button))
        self.assertEqual(self.counts(), (0, 0))

    def test_test_mode_verifies_without_any_persistence_and_clears(self):
        self.open(test=True)
        self.confirm()
        self.click("history_backup_restore")
        self.assertEqual(self.counts(), (0, 0))
        self.assertTrue(any("保存していません" in s.value for s in self.app.success))
        self.click("parent_test_end")
        self.assertFalse(any(k.startswith("history_backup_") for k in self.app.session_state._state.filtered_state))
        self.open()
        self.assertTrue(self.app.button(key="history_backup_restore").disabled)

    def test_changed_file_does_not_inherit_confirmation(self):
        self.open()
        self.confirm()
        changed = dict(self.math, attempt_id="changed_attempt")
        self.upload = BytesIO(history_backup.export_backup("user_001", [changed], [self.jp]))
        self.app.run()
        self.assertTrue(self.app.button(key="history_backup_restore").disabled)
        self.assertEqual(self.counts(), (0, 0))

    def test_conflicting_history_blocks_before_any_restore(self):
        learning.save_attempt(dict(self.math, user_answer=0, is_correct=False))
        self.open()
        self.assertTrue(self.app.error)
        self.assertFalse(any(b.key == "history_backup_restore" for b in self.app.button))
        self.assertEqual(self.counts(), (1, 0))


if __name__ == "__main__":
    unittest.main()
