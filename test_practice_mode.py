"""テスト回答の保存漏れと、通常学習へのモード混入を検証します。"""

from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from streamlit.testing.v1 import AppTest
from learning_profiles import default_profile
from practice_mode import switch_mode, write_learning_answer
from test_learning import test_environment


class ModeTests(unittest.TestCase):
    def test_round_mode_stays_unsaved_even_after_session_changes(self):
        writer = Mock()
        for state, session in (({"test_mode": True}, {}), ({}, {"parent_test_mode": True})):
            write_learning_answer(state, session, writer, {"hint_used": True, "reading_help_used": True})
        writer.assert_not_called()
        write_learning_answer({}, {}, writer, {"normal": True})
        writer.assert_called_once_with({"normal": True})

    def test_switch_discards_pending_both_subjects_and_preview_but_keeps_login(self):
        session = {"access_granted": True, "round": {"pending_record": {}}, "jp_round": {"pending": {}},
                   "display_profiles": {"user_001": {}}, "display_grade_user_001": 6,
                   "answer_keyboard": {}, "jp_keyboard": {}, "jp_chains": {}, "user_id": "user_001"}
        switch_mode(session, True)
        self.assertEqual(session, {"access_granted": True, "parent_test_mode": True, "screen": "user"})
        switch_mode(session, False)
        self.assertFalse(session["parent_test_mode"])


class TestModeAppTests(unittest.TestCase):
    def setUp(self):
        patches = [patch.dict("os.environ", test_environment(), clear=True), patch("streamlit.secrets", {}),
                   patch("learning.init_db"), patch("japanese.init_db"),
                   patch("text_display.load_profile", side_effect=default_profile),
                   patch("learning.save_attempt"), patch("japanese.save_record"),
                   patch("display_settings_ui.save_profile")]
        self.mocks = [p.start() for p in patches]
        for p in patches:
            self.addCleanup(p.stop)
        self.math_save, self.jp_save, self.profile_save = self.mocks[-3:]
        self.app = AppTest.from_file(str(Path(__file__).with_name("app.py")), default_timeout=10).run()

    def click(self, key):
        self.app.button(key=key).click().run()
        self.assertEqual(len(self.app.exception), 0)

    def math_event(self, action, answer=None):
        state = self.app.session_state.round
        self.app.session_state["answer_keyboard"] = {
            "token": f"{state['session_id']}:{state['index']}:{state['phase']}",
            "action": action, "answer": answer, "response_time_sec": 2,
            "draft": {"reading_help_used": True}}
        self.app.run()
        self.assertEqual(len(self.app.exception), 0)

    def test_math_completion_retry_and_normal_mode_save(self):
        self.click("parent_test_start")
        self.click("select_user_001")
        self.app.radio(key="problem_count").set_value(5)
        next(b for b in self.app.button if b.label == "れんしゅう スタート").click().run()
        self.assertTrue(self.app.session_state.round["test_mode"])
        for index in range(5):
            correct = self.app.session_state.round["problems"][index]["correct_answer"]
            self.math_event("hint")
            self.math_event("answer", correct + 1 if index == 0 else correct)
            self.math_event("next")
        self.assertEqual(self.app.session_state.screen, "results")
        self.assertFalse(any("スタンプ" in s.value for s in self.app.success))
        next(b for b in self.app.button if b.label == "まちがえた もんだいを もういちど").click().run()
        self.math_event("answer", self.app.session_state.round["problems"][0]["correct_answer"])
        self.math_event("next")
        self.math_save.assert_not_called()
        self.click("parent_test_end")
        self.assertNotIn("round", self.app.session_state)
        self.click("select_user_001")
        next(b for b in self.app.button if b.label == "れんしゅう スタート").click().run()
        self.math_event("answer", self.app.session_state.round["problems"][0]["correct_answer"])
        self.math_save.assert_called_once()

    def test_japanese_hint_reading_back_resume_and_retry_are_unsaved(self):
        self.click("parent_test_start")
        self.click("select_user_001")
        self.click("subject_japanese")
        self.app.radio(key="jp_count").set_value(5)
        self.click("jp_start")
        def event(action, answer=None):
            state = self.app.session_state.jp_round
            token = f"{state['session_id']}:{state['index']}:{state['phase']}"
            if state.get("resume_revision"):
                token += f":resume{state['resume_revision']}"
            self.app.session_state.jp_keyboard = {"token": token, "action": action, "answer": answer,
                                                  "response_time_sec": 2, "hint_used": True,
                                                  "reading_help_used": True}
            self.app.run()
            self.assertEqual(len(self.app.exception), 0)
        event("back")
        self.click("jp_resume")
        for index in range(5):
            q = self.app.session_state.jp_round["questions"][index]
            answer = q["answer"]
            if index == 0:
                answer = (answer + 1) % len(q["choices"]) if type(answer) is int else answer[1:] + answer[:1]
            event("answer", answer)
            event("next")
        self.click("jp_retry")
        event("answer", self.app.session_state.jp_round["questions"][0]["answer"])
        event("next")
        self.jp_save.assert_not_called()
        self.click("parent_test_end")
        self.click("select_user_001")
        self.click("subject_japanese")
        self.click("jp_start")
        event("answer", self.app.session_state.jp_round["questions"][0]["answer"])
        self.jp_save.assert_called_once()

    def test_display_preview_is_discarded_and_normal_settings_still_save(self):
        self.click("parent_test_start")
        self.click("select_user_001")
        self.click("display_open")
        self.app.selectbox(key="display_grade_user_001").set_value(6)
        next(b for b in self.app.button if b.label == "保存せずに試す").click().run()
        self.assertEqual(len(self.app.exception), 0)
        self.profile_save.assert_not_called()
        self.assertEqual(self.app.session_state.display_profiles["user_001"]["grade"], 6)
        self.click("parent_test_end")
        self.click("select_user_001")
        self.click("display_open")
        self.assertEqual(self.app.selectbox(key="display_grade_user_001").value, 1)
        next(b for b in self.app.button if b.label == "両教科に保存").click().run()
        self.profile_save.assert_called_once()


if __name__ == "__main__":
    unittest.main()
