"""実際の画面進行で穴埋めと図の回答・保存・再開を確認します。"""
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest
from activity import JST
from daily_review import schedule
from learning_profiles import default_profile
from test_learning import test_environment
import learning
import japanese


class FillVisualAppTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "math.sqlite3"
        learning.init_db(self.path)
        japanese.init_db(Path(self.temp.name) / "japanese.sqlite3")
        self.original_save = learning.save_attempt
        self.lost_response = False
        patches = [patch.dict("os.environ", test_environment(), clear=True), patch("streamlit.secrets", {}),
                   patch("learning.get_supabase_config", return_value=None),
                   patch("learning.DB_PATH", self.path),
                   patch("japanese.DB_PATH", Path(self.temp.name) / "japanese.sqlite3"),
                   patch("learning_profiles.DB_PATH", Path(self.temp.name) / "profiles.sqlite3"),
                   patch("learning_extensions.DB_PATH", Path(self.temp.name) / "extensions.sqlite3"),
                   patch("text_display.load_profile", side_effect=default_profile),
                   patch("learning.save_attempt", side_effect=self.save)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.app = AppTest.from_file(str(Path(__file__).with_name("app.py")), default_timeout=10).run()
        self.assertEqual(len(self.app.exception), 0)

    def save(self, record):
        self.original_save(record, self.path)
        if self.lost_response:
            self.lost_response = False
            raise OSError("回答は保存されたが応答が失われた")

    def click(self, key):
        self.app.button(key=key).click().run()
        self.assertEqual(len(self.app.exception), 0)

    def click_label(self, label):
        next(b for b in self.app.button if b.label == label).click().run()
        self.assertEqual(len(self.app.exception), 0)

    def begin(self, visual=False, parent=False):
        if parent:
            self.click("parent_test_start")
        self.click("select_user_001")
        self.app.radio(key="problem_format").set_value("fill_blank")
        self.app.radio(key="problem_count").set_value(5)
        self.visual_checkbox().set_value(visual).run()
        self.click_label("れんしゅう スタート")
        self.assertEqual(len(self.app.session_state.round["problems"]), 5)

    def event(self, action, answer=None, **extra):
        state = self.app.session_state.round
        index = state["index"]
        token = f"{state['session_id']}:{index}:{state['phase']}"
        revision = state.get("interaction_revision", {}).get(index, 0)
        if revision:
            token += f":ui{revision}"
        self.app.session_state.answer_keyboard = {"token": token, "action": action, "answer": answer,
                                                  "response_time_sec": 2, **extra}
        self.app.run()
        self.assertEqual(len(self.app.exception), 0)

    def rows(self):
        return learning.read_attempts("user_001", path=self.path, page_size=100)[0]

    def visual_checkbox(self):
        return next(c for c in self.app.checkbox if c.label == "図で かんがえる")

    def test_manual_picture_pause_result_retry_history_and_independent_report(self):
        self.begin()
        self.event("show_visual", draft={"answer": "3"})
        self.event("pause")
        self.click("math_resume")
        draft = self.app.session_state.round["drafts"][0]
        self.assertEqual(draft["answer"], "3")
        self.assertTrue(draft["visual_visible"])
        self.event("show_hint")
        self.assertEqual(self.app.session_state.round["drafts"][0]["hint_level"], 1)
        for index in range(5):
            problem = self.app.session_state.round["problems"][index]
            self.event("answer", problem["correct_answer"] + (index == 0))
            self.event("next")
        self.assertEqual(self.app.session_state.screen, "results")
        self.assertEqual(self.app.metric[1].value, "80%")
        self.assertEqual(sum(r["visual_help_used"] for r in self.rows()), 1)
        self.click_label("まちがえた もんだいを もういちど")
        problem = self.app.session_state.round["problems"][0]
        self.event("answer", problem["correct_answer"])
        record = deepcopy(self.app.session_state.round["answers"][0])
        self.event("show_visual")  # 答えた後の図は補助使用へ遡及しない。
        self.assertEqual(record, self.app.session_state.round["answers"][0])
        self.assertFalse(record["visual_help_used"])
        self.event("next")
        self.click("report_results")
        self.assertTrue(any("□に入る数" in s.value for s in self.app.markdown))
        counts = [m.value for m in self.app.metric if m.label == "初回の回答"]
        self.assertEqual(counts, ["0問"])
        self.click("report_back")
        self.click("history_results")
        table = self.app.dataframe[0].value
        self.assertEqual(set(table["形式"]), {"穴埋め"})
        self.assertEqual(sum(table["図の使用"] == "あり"), 1)

    def test_auto_picture_parent_test_does_not_save_and_clears_setting(self):
        self.begin(visual=True, parent=True)
        old_epoch = self.app.session_state.math_visuals_widget_epoch
        before = deepcopy(self.rows())
        for index in range(5):
            problem = self.app.session_state.round["problems"][index]
            self.assertTrue(self.app.session_state.round["drafts"][index]["visual_visible"])
            self.event("answer", problem["correct_answer"])
            record = self.app.session_state.round["answers"][-1]
            self.assertTrue(record["visual_help_used"])
            self.assertTrue(record["hint_used"])
            self.assertEqual(record["hint_level"], 0)
            self.event("next")
        self.assertEqual(self.rows(), before)
        self.assertFalse(any("スタンプ" in s.value for s in self.app.success))
        self.click("parent_test_end")
        self.click("select_user_001")
        self.assertFalse(self.visual_checkbox().value)
        self.assertGreater(self.app.session_state.math_visuals_widget_epoch, old_epoch)

    def test_lost_save_response_keeps_one_picture_answer_and_one_due_date(self):
        self.begin(visual=True)
        self.lost_response = True
        problem = self.app.session_state.round["problems"][0]
        self.event("answer", problem["correct_answer"])
        pending = deepcopy(self.app.session_state.round["pending_record"])
        now = datetime.now(JST)
        before = schedule(self.rows(), "user_001", "math", now=now)
        self.click("retry_save")
        self.assertEqual(len(self.rows()), 1)
        self.assertEqual(self.rows()[0]["attempt_id"], pending["attempt_id"])
        self.assertEqual(before, schedule(self.rows(), "user_001", "math", now=now))
        due = before[problem["problem_id"]]["due_date"]
        self.assertEqual(due, now.date() + timedelta(days=1))

    def test_client_picture_flag_cannot_mark_unshown_picture_used(self):
        self.begin()
        problem = self.app.session_state.round["problems"][0]
        self.event("answer", problem["correct_answer"], draft={"visual_help_used": True, "visual_visible": True})
        self.assertFalse(self.rows()[0]["visual_help_used"])
        self.assertFalse(self.rows()[0]["hint_used"])

    def test_auto_picture_preference_survives_results_retry_and_settings(self):
        self.begin(visual=True)
        for index in range(5):
            problem = self.app.session_state.round["problems"][index]
            self.event("answer", problem["correct_answer"] + (index == 0))
            self.event("next")
        self.click_label("まちがえた もんだいを もういちど")
        state = self.app.session_state.round
        self.assertTrue(state["visual_enabled"])
        self.assertTrue(state["drafts"][0]["visual_visible"])
        self.event("answer", state["problems"][0]["correct_answer"])
        self.event("next")
        self.click_label("あたらしい 5もんを れんしゅう")
        self.assertTrue(self.visual_checkbox().value)


if __name__ == "__main__":
    unittest.main()
