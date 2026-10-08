"""復習開始から保存・結果・再練習を実際のアプリ進行で確認します。"""

from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest
from activity import JST
import learning
import japanese as jp
from japanese_questions import QUESTIONS
from learning_profiles import default_profile
from test_learning import test_environment


class DailyReviewAppTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.math_path = Path(self.temp.name) / "math.sqlite3"
        self.jp_path = Path(self.temp.name) / "jp.sqlite3"
        learning.init_db(self.math_path)
        jp.init_db(self.jp_path)
        self.now = datetime.now(JST)
        yesterday = (self.now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        for index in range(5):
            p = learning.make_problem("subtraction", 10, index + 3, 1)
            r = learning.make_attempt(p, "user_001", "seed_math", index + 1, "normal", 99, 2, 1)
            r["datetime"] = (yesterday + timedelta(minutes=index)).isoformat()
            learning.save_attempt(r, self.math_path)
        questions = [q for q in QUESTIONS if q["category"] == "sentence"][:5]
        for index, q in enumerate(questions):
            r = jp.make_record(q, "user_001", "seed_jp", index + 1, "normal",
                               (q["answer"] + 1) % len(q["choices"]), 2, 1, f"seed_chain_{index}")
            r["datetime"] = (yesterday + timedelta(minutes=index)).isoformat()
            jp.save_record(r, self.jp_path)
        self.original_math_save = learning.save_attempt
        self.original_jp_save = jp.save_record
        self.math_lost_response = self.jp_lost_response = False
        read_math, read_jp = learning.read_attempts, jp.read_records
        patches = [patch.dict("os.environ", test_environment(), clear=True), patch("streamlit.secrets", {}),
                   patch("learning.init_db", side_effect=lambda: learning_init(self.math_path)),
                   patch("japanese.init_db", side_effect=lambda: jp_init(self.jp_path)),
                   patch("learning.save_attempt", side_effect=self.math_save),
                   patch("japanese.save_record", side_effect=self.jp_save),
                   patch("learning.read_attempts", side_effect=lambda u, page=0, page_size=50, **kw:
                         read_math(u, page=page, page_size=page_size, path=self.math_path, **kw)),
                   patch("japanese.read_records", side_effect=lambda u, page=0, page_size=100, path=None:
                         read_jp(u, page=page, page_size=page_size, path=self.jp_path)),
                   patch("text_display.load_profile", side_effect=default_profile)]
        # 先に実関数を保存し、モックから自分自身を呼ばない。
        learning_init, jp_init = learning.init_db, jp.init_db
        self.mocks = [p.start() for p in patches]
        for p in patches:
            self.addCleanup(p.stop)
        self.app = AppTest.from_file(str(Path(__file__).with_name("app.py")), default_timeout=10).run()
        self.assertEqual(len(self.app.exception), 0)

    def math_save(self, record):
        self.original_math_save(record, self.math_path)
        if self.math_lost_response:
            self.math_lost_response = False
            raise OSError("保存後の応答だけが失われた場合")

    def jp_save(self, record):
        self.original_jp_save(record, self.jp_path)
        if self.jp_lost_response:
            self.jp_lost_response = False
            raise OSError("保存後の応答だけが失われた場合")

    def math_rows(self):
        return learning.read_attempts("user_001", page_size=100)[0]

    def jp_rows(self):
        return jp.read_all("user_001")

    def click(self, key):
        self.app.button(key=key).click().run()
        self.assertEqual(len(self.app.exception), 0)

    def click_label(self, label):
        next(b for b in self.app.button if b.label == label).click().run()
        self.assertEqual(len(self.app.exception), 0)

    def math_event(self, action, answer=None, **extra):
        state = self.app.session_state.round
        index = state["index"]
        token = f"{state['session_id']}:{index}:{state['phase']}"
        for key, suffix in (("equation_revision", "edit"), ("interaction_revision", "ui")):
            revision = state.get(key, {}).get(index, 0)
            if revision:
                token += f":{suffix}{revision}"
        self.app.session_state["answer_keyboard"] = {
            "token": token, "action": action, "answer": answer, "response_time_sec": 2, **extra}
        self.app.run()
        self.assertEqual(len(self.app.exception), 0)

    def jp_event(self, action, answer=None, **extra):
        state = self.app.session_state.jp_round
        token = f"{state['session_id']}:{state['index']}:{state['phase']}"
        if state.get("resume_revision"):
            token += f":resume{state['resume_revision']}"
        self.app.session_state.jp_keyboard = {"token": token, "action": action, "answer": answer,
                                             "response_time_sec": 2, "hint_used": False, **extra}
        self.app.run()
        self.assertEqual(len(self.app.exception), 0)

    def test_math_review_pause_result_retry_keeps_initial_analysis(self):
        from assessment import assess
        before = assess(self.math_rows())["overall"]
        self.click("select_user_001")
        self.click("math_daily_review")
        state = self.app.session_state.round
        self.assertEqual(state["selection_type"], "review")
        self.assertEqual(len(state["problems"]), 5)
        self.assertEqual(len({p["problem_id"] for p in state["problems"]}), 5)
        self.math_event("pause", draft={"answer": "7", "reading_help_used": True})
        self.click("math_resume")
        self.assertEqual(self.app.session_state.round["drafts"][0]["answer"], "7")
        for index in range(5):
            p = self.app.session_state.round["problems"][index]
            self.math_event("answer", p["correct_answer"] + (index == 0))
            self.math_event("next")
        self.assertEqual(self.app.session_state.screen, "results")
        self.assertEqual(self.app.metric[1].value, "80%")
        self.click_label("まちがえた もんだいを もういちど")
        self.assertEqual(self.app.session_state.round["selection_type"], "review_retry")
        self.math_event("answer", self.app.session_state.round["problems"][0]["correct_answer"])
        self.math_event("next")
        self.assertEqual(assess(self.math_rows())["overall"], before)
        self.assertEqual(sum(r["selection_type"] == "review" for r in self.math_rows()), 5)
        self.assertEqual(sum(r["selection_type"] == "review_retry" for r in self.math_rows()), 1)
        self.click("history_results")
        self.assertTrue(any("ふくしゅう" in str(value) or "復習" in str(value)
                            for value in self.app.dataframe[0].value.astype(str).values.flatten()))

    def test_japanese_review_new_chain_resume_retry_preserves_initial_metrics(self):
        before = jp.metrics(self.jp_rows())
        seed_chains = {r["chain_id"] for r in self.jp_rows()}
        self.click("select_user_001")
        self.click("subject_japanese")
        self.click("jp_daily_review")
        self.assertEqual(self.app.session_state.jp_round["selection"], "review")
        self.assertEqual(len(self.app.session_state.jp_round["questions"]), 5)
        self.assertTrue(seed_chains.isdisjoint(set(self.app.session_state.jp_chains.values())))
        first = self.app.session_state.jp_round["questions"][0]
        chain = self.app.session_state.jp_chains[first["question_id"]]
        self.jp_event("back", hint_used=True, reading_help_used=True)
        self.click("jp_resume")
        for index in range(5):
            q = self.app.session_state.jp_round["questions"][index]
            answer = (q["answer"] + 1) % len(q["choices"]) if index == 0 else q["answer"]
            self.jp_event("answer", answer, hint_used=index == 0, reading_help_used=index == 0)
            self.jp_event("next")
        self.assertEqual(self.app.session_state.screen, "jp_results")
        self.click("jp_retry")
        self.assertEqual(self.app.session_state.jp_round["selection"], "review_retry")
        self.assertEqual(self.app.session_state.jp_chains[first["question_id"]], chain)
        self.jp_event("answer", first["answer"])
        self.jp_event("next")
        after = jp.metrics(self.jp_rows())
        for key in ("count", "initial_correct", "rate", "error_counts", "chains", "retry_count"):
            self.assertEqual(after[key], before[key], key)
        review_retry = next(r for r in self.jp_rows() if r["selection_type"] == "review_retry")
        self.assertEqual(review_retry["attempt_count"], 2)
        self.assertEqual(review_retry["chain_id"], chain)

    def test_review_save_retry_uses_same_answer_id_and_schedule(self):
        from daily_review import schedule
        self.click("select_user_001")
        self.click("math_daily_review")
        self.math_lost_response = True
        self.math_event("answer", self.app.session_state.round["problems"][0]["correct_answer"])
        pending = deepcopy(self.app.session_state.round["pending_record"])
        before = schedule(self.math_rows(), "user_001", "math", now=datetime.now(JST))
        self.click("retry_save")
        after = schedule(self.math_rows(), "user_001", "math", now=datetime.now(JST))
        self.assertEqual(sum(r["attempt_id"] == pending["attempt_id"] for r in self.math_rows()), 1)
        self.assertEqual(before, after)
        self.assertEqual(len(self.app.session_state.round["answers"]), 1)
        self.math_event("pause")
        self.click("subject_japanese")
        self.click("jp_daily_review")
        self.jp_lost_response = True
        self.jp_event("answer", self.app.session_state.jp_round["questions"][0]["answer"])
        pending = deepcopy(self.app.session_state.jp_round["pending"])
        before = schedule(self.jp_rows(), "user_001", "japanese", now=datetime.now(JST))
        self.click("jp_retry_save")
        self.assertEqual(sum(r["attempt_id"] == pending["attempt_id"] for r in self.jp_rows()), 1)
        self.assertEqual(before, schedule(self.jp_rows(), "user_001", "japanese", now=datetime.now(JST)))

    def test_parent_review_both_subjects_never_changes_history_or_schedule(self):
        from daily_review import schedule
        math_before, jp_before = deepcopy(self.math_rows()), deepcopy(self.jp_rows())
        math_due = schedule(math_before, "user_001", "math", now=self.now)
        jp_due = schedule(jp_before, "user_001", "japanese", now=self.now)
        self.click("parent_test_start")
        self.click("select_user_001")
        self.click("math_daily_review")
        for index in range(5):
            p = self.app.session_state.round["problems"][index]
            self.math_event("answer", p["correct_answer"])
            self.math_event("next")
        self.assertFalse(any("スタンプ" in s.value for s in self.app.success))
        self.click_label("あたらしい 10もんを れんしゅう")
        self.click("subject_japanese")
        self.click("jp_daily_review")
        for index in range(5):
            q = self.app.session_state.jp_round["questions"][index]
            self.jp_event("answer", q["answer"], hint_used=True, reading_help_used=True)
            self.jp_event("next")
        self.assertEqual(self.math_rows(), math_before)
        self.assertEqual(self.jp_rows(), jp_before)
        self.assertEqual(schedule(self.math_rows(), "user_001", "math", now=self.now), math_due)
        self.assertEqual(schedule(self.jp_rows(), "user_001", "japanese", now=self.now), jp_due)

    def test_read_failure_does_not_start_fallback_and_small_or_empty_plan(self):
        self.click("select_user_001")
        with patch("learning.read_attempts", side_effect=OSError("offline")):
            self.click("math_daily_review")
        self.assertEqual(self.app.session_state.screen, "settings")
        self.assertTrue(self.app.error)
        p = learning.make_problem("addition", 10, 1, 1)
        with patch("daily_review.plan_math", return_value={"items": [p], "reasons": {p["problem_id"]: "基本問題"}, "message": ""}):
            self.click("math_daily_review")
        self.assertEqual(len(self.app.session_state.round["problems"]), 1)
        self.math_event("answer", 2)
        self.math_event("next")
        self.assertEqual(self.app.session_state.screen, "results")
        self.click_label("あたらしい 10もんを れんしゅう")
        with patch("daily_review.plan_math", return_value={"items": [], "reasons": {}, "message": "今日は対象なし"}):
            self.click("math_daily_review")
        self.assertEqual(self.app.session_state.screen, "settings")
        self.assertTrue(any("対象なし" in s.value for s in self.app.info))

    def test_many_review_rows_do_not_push_initial_rows_out_of_report(self):
        original = self.math_rows()
        reviews = []
        for index in range(501):
            row = dict(original[0], attempt_id=f"daily_{index}", selection_type="review", is_correct=True,
                       datetime=(self.now - timedelta(minutes=index + 1)).isoformat())
            reviews.append(row)
        rows = reviews + original
        self.click("select_user_001")
        with patch("learning.read_attempts", side_effect=lambda u, page=0, page_size=100, **kw:
                   (rows[page * page_size:(page + 1) * page_size], (page + 1) * page_size < len(rows))) as reader:
            self.click("report_settings")
        self.assertEqual(next(m.value for m in self.app.metric if m.label == "初回の回答"), "5問")
        self.assertEqual(reader.call_count, 6)


if __name__ == "__main__":
    unittest.main()
