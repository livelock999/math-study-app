"""保護者画面の保存・学習者分離・テストモードを確認します。"""
from pathlib import Path
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from learning_profiles import default_profile
from test_learning import test_environment


class ParentDashboardTests(unittest.TestCase):
    def setUp(self):
        patches = [patch.dict("os.environ", test_environment(), clear=True), patch("streamlit.secrets", {}),
                   patch("learning.init_db"), patch("japanese.init_db"),
                   patch("text_display.load_profile", side_effect=default_profile),
                   patch("parent_features_ui.load_records", return_value=([], [])),
                   patch("learning_extensions.read_goals", side_effect=lambda user: {"user_id": user, "weekly_days": 3, "daily_questions": 5}),
                   patch("learning_extensions.save_goals"),
                   patch("learning_extensions.read_feedback", return_value=[])]
        self.mocks = [p.start() for p in patches]
        for p in patches:
            self.addCleanup(p.stop)
        self.records, self.goals, self.save, self.feedback = self.mocks[-4:]
        self.app = AppTest.from_file(str(Path(__file__).with_name("app.py")), default_timeout=15).run()

    def click(self, key):
        self.app.button(key=key).click().run()
        self.assertFalse(self.app.exception)

    def open(self, user="user_001"):
        self.click("select_" + user)
        self.click("parent_dashboard_open")
        self.assertEqual(self.app.session_state.screen, "parent_dashboard")

    def submit(self, label):
        next(button for button in self.app.button if button.label == label).click().run()
        self.assertFalse(self.app.exception)

    def test_empty_report_goals_export_and_back(self):
        self.open()
        self.records.assert_called_with("user_001")
        self.assertTrue(any("レポート" in title.value for title in self.app.subheader))
        self.assertTrue(any("算数：どの段階" in item.value for item in self.app.markdown))
        self.assertTrue(any("国語：練習する分野" in item.value for item in self.app.markdown))
        self.app.number_input(key="learning_goal_days_user_001").set_value(4)
        self.app.number_input(key="learning_goal_questions_user_001").set_value(6)
        self.submit("学習目標を保存")
        self.save.assert_called_once_with("user_001", 4, 6)
        self.assertTrue(any("学習目標を保存" in item.value for item in self.app.success))
        self.assertEqual(len(self.app.get("download_button")), 1)
        self.click("parent_dashboard_back")
        self.assertEqual(self.app.session_state.screen, "settings")

    def test_parent_test_preview_is_never_saved_and_cleared_on_exit(self):
        self.click("parent_test_start")
        self.open()
        self.app.number_input(key="learning_goal_days_user_001").set_value(7)
        self.submit("保存せずに目標を試す")
        self.save.assert_not_called()
        self.assertEqual(self.app.session_state.parent_goals_preview["user_001"]["weekly_days"], 7)
        self.click("parent_test_end")
        self.assertNotIn("parent_goals_preview", self.app.session_state)
        self.open()
        self.assertEqual(self.app.number_input(key="learning_goal_days_user_001").value, 3)

    def test_save_failure_keeps_input_for_retry(self):
        self.open()
        self.save.side_effect = [OSError("failed"), None]
        self.app.number_input(key="learning_goal_questions_user_001").set_value(9)
        self.submit("学習目標を保存")
        self.assertTrue(self.app.error)
        self.assertEqual(self.app.number_input(key="learning_goal_questions_user_001").value, 9)
        self.submit("学習目標を保存")
        self.assertEqual(self.save.call_count, 2)
        self.save.assert_called_with("user_001", 3, 9)

    def test_second_learner_scoped_load_and_goals(self):
        self.open("user_002")
        self.records.assert_called_with("user_002")
        self.goals.assert_called_with("user_002")
        self.feedback.assert_called_with("user_002")
        self.app.number_input(key="learning_goal_days_user_002").set_value(2)
        self.submit("学習目標を保存")
        self.save.assert_called_with("user_002", 2, 5)

    def test_missing_goal_store_does_not_block_report_or_export(self):
        self.goals.side_effect = OSError("missing table")
        self.open()
        self.assertTrue(self.app.warning)
        self.assertTrue(next(button for button in self.app.button if button.label == "学習目標を保存").disabled)
        self.assertEqual(len(self.app.get("download_button")), 1)
        self.save.assert_not_called()


if __name__ == "__main__":
    unittest.main()
