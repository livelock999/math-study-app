"""国語の出題、記録、分析、統合した画面進行を実データと分離して検証。"""

from collections import Counter
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.error import URLError
from urllib.parse import parse_qs, urlsplit
import json
import unittest

from streamlit.testing.v1 import AppTest
import japanese as jp
from japanese_questions import QUESTIONS, CATEGORIES, TAG_LABELS, QUESTION_LABELS, ERROR_LABELS
from test_learning import test_environment


def record(q=None, user="user_001", answer=None, **updates):
    q = q or QUESTIONS[0]
    value = jp.make_record(q, user, "session", 1, "normal", q["answer"] if answer is None else answer,
                           2, 1, "chain")
    value.update(updates)
    return value


class JapaneseQuestionsTests(unittest.TestCase):
    def test_reading_confirmation_rejects_non_boolean_flags(self):
        for invalid in (None, 0, 1, "true", "false", [], {}):
            with self.subTest(value=invalid), self.assertRaises(ValueError):
                jp.make_record(QUESTIONS[0], "user_001", "s", 1, "normal", QUESTIONS[0]["answer"],
                               2, 1, "chain", reading_help_used=invalid)

    def test_all_questions_have_valid_metadata_and_answers(self):
        self.assertEqual(len(QUESTIONS), 136)
        self.assertEqual(len({q["question_id"] for q in QUESTIONS}), 136)
        self.assertEqual(Counter(q["category"] for q in QUESTIONS),
                         {"words": 12, "sentence": 12, "information": 18, "sequence": 10, "passage": 34, "blank": 10,
                          "particles": 40})
        for q in QUESTIONS:
            with self.subTest(question=q["question_id"]):
                self.assertEqual(len(q["choices"]), 2 if q["category"] == "particles" else 3)
                self.assertEqual(len(set(q["choices"])), len(q["choices"]))
                self.assertTrue(jp.validate_answer(q, q["answer"]))
                self.assertTrue(q["skill_tags"] and all(tag in TAG_LABELS for tag in q["skill_tags"]))
                self.assertIn(q["question_word"], QUESTION_LABELS)
                self.assertIn(q["difficulty"], (1, 2, 3))
                self.assertIn(q["reasoning_level"], (1, 2, 3, 4))
                self.assertTrue(q["hint"] and q["explanation"])
                self.assertNotIn("ましか", q["question"])
                correct = record(q)
                self.assertTrue(correct["correct"])
                self.assertEqual(correct["error_cause_tags"], [])
                wrong = list(reversed(q["answer"])) if q["problem_format"] == "ordering" else (q["answer"] + 1) % len(q["choices"])
                if wrong == q["answer"]:
                    wrong = q["answer"][1:] + q["answer"][:1]
                incorrect = record(q, answer=wrong)
                self.assertFalse(incorrect["correct"])
                self.assertTrue(incorrect["error_cause_tags"])
                self.assertTrue(all(tag in ERROR_LABELS for tag in incorrect["error_cause_tags"]))

    def test_generation_filters_and_has_no_duplicates(self):
        for category in ["mix", *CATEGORIES]:
            qs = jp.choose_questions(category, 10)
            self.assertEqual(len(qs), 10)
            self.assertEqual(len({q["question_id"] for q in qs}), 10)
            self.assertTrue(all(category == "mix" or q["category"] == category for q in qs))
        self.assertTrue(all(q["category"] == "blank" for q in jp.choose_questions("mix", 5, ["blank"])))

    def test_invalid_answers_and_timing_are_rejected(self):
        q = next(q for q in QUESTIONS if q["problem_format"] == "ordering")
        for answer in ([0, 0, 1], [0, 1], [0, 1, 3], [True, 0, 2], "123"):
            self.assertFalse(jp.validate_answer(q, answer))
        for answer in (True, -1, 3, None, [0]):
            self.assertFalse(jp.validate_answer(QUESTIONS[0], answer))
        for time in (-1, float("nan"), float("inf"), True):
            with self.assertRaises(ValueError):
                jp.make_record(QUESTIONS[0], "user_001", "s", 1, "normal", 0, time, 1, "chain")


class JapaneseStorageTests(unittest.TestCase):
    def test_reading_confirmation_roundtrip_preserves_originals_and_legacy_unknown(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "jp.sqlite3"
            jp.init_db(path)
            question = next(q for q in QUESTIONS if q["category"] == "sentence")
            current = jp.make_record(question, "user_001", "s", 1, "normal", question["answer"],
                                     2, 1, "current", hint_used=False, reading_help_used=True)
            old = record(question, chain_id="old")
            old.pop("reading_help_used")
            for row in (current, old):
                jp.save_record(row, path)
            rows = jp.read_all("user_001", path)
            actual = next(row for row in rows if row["attempt_id"] == current["attempt_id"])
            self.assertEqual(actual, current)
            for field in ("text", "question", "choices", "answer", "explanation"):
                self.assertEqual(actual[field], question[field])
            self.assertEqual(actual["selected_answer_text"], question["choices"][question["answer"]])
            self.assertTrue(actual["correct"])
            self.assertFalse(actual["hint_used"])
            summary = jp.analyze(rows)["summary"]
            self.assertEqual((summary["reading_known_count"], summary["reading_unknown_count"]), (1, 1))
            self.assertEqual((summary["reading_help_rate"], summary["hint_rate"], summary["rate"]), (1, 0, 1))

    def test_roundtrip_user_separation_idempotency_and_pagination(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "jp.sqlite3"
            jp.init_db(path)
            a, b, other = record(), record(), record(user="user_002")
            for r in (a, a, b, other):
                jp.save_record(r, path)
            first, more = jp.read_records("user_001", page_size=1, path=path)
            second, end = jp.read_records("user_001", page=1, page_size=1, path=path)
            self.assertTrue(more)
            self.assertFalse(end)
            self.assertEqual({r["attempt_id"] for r in first + second}, {a["attempt_id"], b["attempt_id"]})
            self.assertEqual(jp.read_all("user_002", path), [other])
            self.assertEqual(first[0]["skill_tags"], a["skill_tags"])

    def test_cloud_saves_snapshot_and_reads_equivalent_utc_timestamp(self):
        r = record()
        config = ("https://example.supabase.co", "sb_secret_test")
        with patch("learning.get_supabase_config", return_value=config), patch("learning.supabase_urlopen") as remote:
            response = remote.return_value.__enter__.return_value
            response.status = 201
            jp.save_record(r)
            request = remote.call_args.args[0]
            posted = json.loads(request.data)
            self.assertEqual(posted["payload"], r)
            self.assertIn("/japanese_attempts", request.full_url)
            response.status = 200
            posted["datetime"] = datetime.fromisoformat(r["datetime"]).astimezone(jp.timezone.utc).isoformat()
            response.read.return_value = json.dumps([posted]).encode()
            records, more = jp.read_records("user_001")
            self.assertEqual(records, [r])
            self.assertFalse(more)
            query = parse_qs(urlsplit(remote.call_args.args[0].full_url).query)
            self.assertEqual(query["user_id"], ["eq.user_001"])

    def test_cloud_failure_never_falls_back_or_discloses_secret(self):
        with patch("learning.get_supabase_config", return_value=("https://example.supabase.co", "sb_secret_test")), \
                patch("learning.supabase_urlopen", side_effect=URLError("sb_secret_test")), \
                patch("japanese.sqlite3.connect") as local:
            for operation in (lambda: jp.save_record(record()), lambda: jp.read_records("user_001")):
                with self.assertRaises(OSError) as error:
                    operation()
                self.assertNotIn("sb_secret_test", str(error.exception))
            local.assert_not_called()

    def test_cloud_rejects_other_users_payload(self):
        other = record(user="user_002")
        row = {key: other[key] for key in ("attempt_id", "user_id", "session_id", "datetime")}
        row["payload"] = other
        with patch("learning.get_supabase_config", return_value=("https://example.supabase.co", "sb_secret_test")), \
                patch("learning.supabase_urlopen") as remote:
            response = remote.return_value.__enter__.return_value
            response.status = 200
            response.read.return_value = json.dumps([row]).encode()
            with self.assertRaises(OSError):
                jp.read_records("user_001")


class JapaneseAnalysisTests(unittest.TestCase):
    def test_hint_breakdown_uses_initial_answers_and_excludes_unknown(self):
        initial = [record(chain_id="none"), record(chain_id="help", hint_used=True),
                   record(chain_id="old", hint_used=None)]
        retry = record(chain_id="none", attempt_count=2, selection_type="retry", hint_used=True)
        summary = jp.analyze(initial + [retry])["summary"]
        self.assertEqual(summary["hint_rate"], .5)
        self.assertEqual(summary["hint_unknown_count"], 1)
        self.assertEqual(summary["unaided_count"], 1)
        self.assertEqual(summary["assisted_count"], 1)
        self.assertEqual(summary["assisted_rate"], 1)
        self.assertEqual(summary["rate"], 1)

    def test_unknown_hint_does_not_lower_japanese_evaluation(self):
        rows = [record(chain_id=f"old{i}", hint_used=None) for i in range(5)]
        group = jp.analyze(rows)["category"][0]
        self.assertEqual(group["status"], "◎ 得意")
        self.assertIsNone(group["hint_rate"])

    def test_initial_errors_retries_and_eventual_success_are_separate(self):
        first = record(answer=1)
        again = record(attempt_count=2, selection_type="retry", retry_flag=True, hint_used=True)
        report = jp.analyze([first, again])
        s = report["summary"]
        self.assertEqual((s["rate"], s["retry_count"], s["retry_success"], s["eventual_correct"]), (0, 1, 1, 1))
        self.assertEqual(report["category"][0]["status"], "判断保留（5問未満）")

    def test_independent_signals_affect_weakness(self):
        records = [record(chain_id=f"chain{i}", hint_used=True) for i in range(5)]
        report = jp.analyze(records)
        self.assertEqual(report["category"][0]["status"], "△ 練習中")
        self.assertEqual(report["weak_categories"], ["words"])
        wrong = [record(answer=1, chain_id=f"chain{i}") for i in range(5)]
        report = jp.analyze(wrong)
        self.assertEqual(report["category"][0]["status"], "× 苦手")
        self.assertIn("同じ種類の誤答が3回以上", report["category"][0]["signals"])

    def test_slow_correct_responses_are_flagged_relative_to_self(self):
        slow = [record(chain_id=f"slow{i}", response_time_sec=60) for i in range(5)]
        q = next(q for q in QUESTIONS if q["category"] == "sentence")
        fast = [record(q, chain_id=f"fast{i}", response_time_sec=2) for i in range(20)]
        report = jp.analyze(slow + fast)
        words = next(g for g in report["category"] if g["key"] == "words")
        self.assertEqual(words["status"], "△ 練習中")
        self.assertTrue(any("時間" in signal for signal in words["signals"]))

    def test_modes_week_and_all_classification_dimensions_are_separate(self):
        records = [record(datetime="2026-10-07T10:00:00+09:00"),
                   record(reading_mode="audio", correct=False, chain_id="audio"),
                   record(datetime="2026-09-01T10:00:00+09:00", chain_id="old")]
        report = jp.analyze(records, now=datetime(2026, 10, 7, tzinfo=jp.JST))
        self.assertEqual(report["week"]["total"], 1)
        self.assertEqual(report["summary"]["rate"], 1)
        for field in ("tags", "category", "question_word", "difficulty", "reasoning"):
            self.assertTrue(report[field])
        self.assertEqual(jp.analyze(records, reading_mode="audio")["summary"]["rate"], 0)


class JapaneseAppTests(unittest.TestCase):
    def setUp(self):
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / "japanese.sqlite3"
        init, save, read = jp.init_db, jp.save_record, jp.read_records
        patches = [patch.dict("os.environ", test_environment(), clear=True), patch("streamlit.secrets", {}),
                   patch("learning.init_db"), patch("japanese.init_db", side_effect=lambda: init(self.path)),
                   patch("japanese.save_record", side_effect=lambda r: save(r, self.path)),
                   patch("japanese.read_records", side_effect=lambda u, page=0, page_size=100, path=None:
                         read(u, page, page_size, self.path))]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.app = AppTest.from_file(str(Path(__file__).with_name("app.py")), default_timeout=10).run()
        self.app.button(key="select_user_001").click().run()
        self.app.button(key="subject_japanese").click().run()
        self.assertEqual(len(self.app.exception), 0)

    def event(self, answer=None, next=False, hint=False, action=None, seconds=2.5, **extra):
        state = self.app.session_state.jp_round
        token = f"{state['session_id']}:{state['index']}:{state['phase']}"
        if state.get("resume_revision"):
            token += f":resume{state['resume_revision']}"
        self.app.session_state.jp_keyboard = {"token": token, "action": action or ("next" if next else "answer"),
                                            "answer": answer, "response_time_sec": seconds, "hint_used": hint,
                                            **extra}
        self.app.run()
        self.assertEqual(len(self.app.exception), 0)

    def test_full_round_retry_history_analysis_and_subject_switch(self):
        self.app.radio(key="jp_count").set_value(5)
        self.app.button(key="jp_start").click().run()
        for i in range(5):
            q = self.app.session_state.jp_round["questions"][i]
            answer = q["answer"]
            if i == 0:
                answer = (answer + 1) % len(q["choices"]) if type(answer) is int else answer[1:] + answer[:1]
            self.event(answer, hint=i == 0)
            self.event(next=True)
        self.assertEqual(self.app.session_state.screen, "jp_results")
        self.assertEqual(self.app.metric[1].value, "80%")
        first = jp.read_all("user_001")
        wrong = next(r for r in first if not r["correct"])
        self.app.button(key="jp_retry").click().run()
        self.event(self.app.session_state.jp_round["questions"][0]["answer"])
        self.event(next=True)
        self.app.button(key="jp_history_jp_results").click().run()
        self.assertEqual(len(self.app.exception), 0)
        self.assertEqual(len(self.app.dataframe[0].value), 6)
        latest = jp.read_all("user_001")[0]
        self.assertEqual(latest["attempt_count"], 2)
        self.assertEqual(latest["chain_id"], wrong["chain_id"])
        self.app.button(key="jp_history_back").click().run()
        self.app.button(key="jp_analysis_jp_results").click().run()
        self.assertEqual(len(self.app.exception), 0)
        self.assertGreaterEqual(len(self.app.dataframe), 5)
        self.app.button(key="jp_analysis_back").click().run()
        self.app.button(key="jp_new").click().run()
        self.app.button(key="subject_math").click().run()
        self.assertEqual(self.app.session_state.screen, "settings")
        self.assertTrue(any(b.key == "history_settings" for b in self.app.button))
        self.app.button(key="subject_japanese").click().run()
        self.app.button(key="jp_change_user").click().run()
        self.app.button(key="select_user_002").click().run()
        self.app.button(key="subject_japanese").click().run()
        self.app.button(key="jp_history_jp_settings").click().run()
        self.assertEqual(len(self.app.dataframe), 0)
        self.assertEqual(len(jp.read_all("user_002")), 0)

    def test_ordering_and_invalid_stale_events(self):
        self.app.radio(key="jp_category").set_value("sequence")
        self.app.radio(key="jp_count").set_value(5)
        self.app.button(key="jp_start").click().run()
        self.event([0, 0, 1])
        self.assertEqual(jp.read_all("user_001"), [])
        self.assertEqual(len(self.app.error), 1)
        self.app.session_state.jp_keyboard = {"token": "old", "action": "answer", "answer": [0, 1, 2]}
        self.app.run()
        self.assertEqual(jp.read_all("user_001"), [])
        self.event(self.app.session_state.jp_round["questions"][0]["answer"])
        self.app.run()
        self.assertEqual(len(jp.read_all("user_001")), 1)

    def test_back_resume_preserves_partial_order_hint_elapsed_and_feedback(self):
        self.app.radio(key="jp_category").set_value("sequence")
        self.app.radio(key="jp_count").set_value(5)
        self.app.button(key="jp_start").click().run()
        question = self.app.session_state.jp_round["questions"][0]
        partial = question["answer"][:1]
        self.event(action="back", hint=True, seconds=12, draft_order=partial)
        self.assertEqual(self.app.session_state.screen, "jp_settings")
        self.assertEqual(jp.read_all("user_001"), [])
        self.assertEqual(self.app.session_state.jp_round["index"], 0)
        self.app.button(key="jp_resume").click().run()
        args = json.loads(self.app.get("component_instance")[0].proto.json_args)
        self.assertEqual(args["draft"], {"order": partial, "hint_used": True, "hint_level": 1,
                                         "elapsed": 12, "reading_help_used": False})
        self.event(question["answer"], hint=True, seconds=18.5)
        saved = jp.read_all("user_001")
        self.assertEqual(len(saved), 1)
        self.assertTrue(saved[0]["hint_used"])
        self.assertEqual(saved[0]["response_time_sec"], 18.5)
        self.event(action="back", hint=True, seconds=19, draft_order=question["answer"])
        self.app.button(key="jp_resume").click().run()
        self.assertEqual(self.app.session_state.jp_round["phase"], "feedback")
        self.assertEqual(jp.read_all("user_001"), saved)
        self.event(next=True)
        self.assertEqual(self.app.session_state.jp_round["index"], 1)
        self.assertEqual(self.app.session_state.jp_round["draft"], {})

    def test_paused_japanese_round_is_not_offered_to_other_user(self):
        self.app.button(key="jp_start").click().run()
        self.event(action="back", seconds=4, draft_order=[])
        self.assertTrue(any(button.key == "jp_resume" for button in self.app.button))
        self.app.button(key="jp_change_user").click().run()
        self.app.button(key="select_user_002").click().run()
        self.app.button(key="subject_japanese").click().run()
        self.assertFalse(any(button.key == "jp_resume" for button in self.app.button))
        self.assertEqual(jp.read_all("user_001"), [])
        self.assertEqual(jp.read_all("user_002"), [])

    def test_save_retry_preserves_record_and_history_return_preserves_progress(self):
        self.app.button(key="jp_start").click().run()
        before = self.app.session_state.jp_round
        self.assertFalse(any(b.key == "jp_history_jp_practice" for b in self.app.button))
        with patch("japanese.save_record", side_effect=OSError("secret_failure")):
            self.event(before["questions"][0]["answer"])
        pending = dict(self.app.session_state.jp_round["pending"])
        self.assertEqual(jp.read_all("user_001"), [])
        self.app.button(key="jp_retry_save").click().run()
        self.assertEqual(jp.read_all("user_001"), [pending])

        self.assertEqual(self.app.session_state.jp_round["phase"], "feedback")
        self.app.button(key="jp_history_jp_practice").click().run()
        self.app.button(key="jp_history_back").click().run()
        self.assertEqual(self.app.session_state.jp_round["phase"], "feedback")
        self.assertEqual(jp.read_all("user_001"), [pending])

    def test_reading_event_survives_back_and_save_retry_without_changing_order_or_hint(self):
        self.app.radio(key="jp_category").set_value("sequence")
        self.app.button(key="jp_start").click().run()
        question = self.app.session_state.jp_round["questions"][0]
        self.event(question["answer"], reading_help_used="true")
        self.assertEqual(jp.read_all("user_001"), [])
        self.event(action="back", seconds=3, draft_order=question["answer"][:1], reading_help_used=True)
        self.app.button(key="jp_resume").click().run()
        args = json.loads(self.app.get("component_instance")[0].proto.json_args)
        self.assertTrue(args["draft"]["reading_help_used"])
        self.assertFalse(args["draft"]["hint_used"])
        self.assertEqual(args["draft"]["order"], question["answer"][:1])
        with patch("japanese.save_record", side_effect=OSError("temporary failure")):
            self.event(question["answer"], seconds=5, reading_help_used=True)
        pending = dict(self.app.session_state.jp_round["pending"])
        self.assertTrue(pending["reading_help_used"])
        self.assertFalse(pending["hint_used"])
        self.assertEqual(pending["selected_answer"], question["answer"])
        self.assertEqual(pending["selected_answer_text"], jp.answer_text(question, question["answer"]))
        self.assertTrue(pending["correct"])
        self.assertEqual(jp.read_all("user_001"), [])
        self.app.button(key="jp_retry_save").click().run()
        self.assertEqual(jp.read_all("user_001"), [pending])
        self.assertEqual(self.app.session_state.jp_round["phase"], "feedback")
        self.app.button(key="jp_history_jp_practice").click().run()
        self.app.button(key="jp_history_back").click().run()
        self.assertEqual(self.app.session_state.jp_round["phase"], "feedback")
        self.assertEqual(jp.read_all("user_001"), [pending])

    def test_weak_area_practice_uses_analysis_and_load_failure_is_recoverable(self):
        jp.init_db()
        q = next(q for q in QUESTIONS if q["category"] == "blank")
        for i in range(5):
            jp.save_record(record(q, answer=(q["answer"] + 1) % 3, chain_id=f"weak{i}"))
        with patch("japanese.read_all", side_effect=OSError("private_secret")):
            self.app.button(key="jp_weak").click().run()
            self.assertEqual(len(self.app.error), 1)
            self.assertNotIn("private_secret", self.app.error[0].value)
        self.app.button(key="jp_weak").click().run()
        self.assertEqual(self.app.session_state.jp_round["selection"], "weak_area")
        self.assertTrue(all(q["category"] == "blank" for q in self.app.session_state.jp_round["questions"]))


if __name__ == "__main__":
    unittest.main()
