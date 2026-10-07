"""初回正答率、実際の助詞混同、意味役割、優先出題と既存画面への連携。"""

import unittest
from datetime import datetime
from unittest.mock import patch
from tempfile import TemporaryDirectory
from pathlib import Path

import japanese as jp
from particles import QUESTIONS, analyze, confusion_pair, recommended
import test_japanese as jp_tests
from cross_subject import build_report


def attempt(question=None, wrong=False, identifier=0, **changes):
    q = question or next(q for q in QUESTIONS if q["level"] == 3 and q["target_particle"] == "で")
    answer = 1 - q["answer"] if wrong else q["answer"]
    r = jp.make_record(q, "user_001", "session", 1, "normal", answer, 3.5, 1, f"chain{identifier}")
    r.update(attempt_id=f"particle{identifier:03}", datetime="2026-10-07T20:00:00+09:00")
    r.update(changes)
    r["answered_at"] = r["datetime"]
    return r


class ParticleTests(unittest.TestCase):
    def test_questions_cover_four_particles_roles_and_three_levels(self):
        self.assertEqual(len(QUESTIONS), 40)
        self.assertEqual({q["target_particle"] for q in QUESTIONS}, {"は", "を", "に", "で"})
        self.assertEqual({q["semantic_role"] for q in QUESTIONS},
                         {"topic", "object", "destination", "location_action"})
        self.assertEqual({q["level"] for q in QUESTIONS}, {1, 2, 3})
        for q in QUESTIONS:
            self.assertEqual(q["correct_answer"], q["choices"][q["answer"]])
            self.assertEqual(q["sentence"], q["text"])
            self.assertEqual(len(q["choices"]), 2)
            self.assertTrue(q["noun"] and q["verb"] and q["explanation"])
            if q["level"] == 3:
                mate = next(p for p in QUESTIONS if p["level"] == 3 and
                            p["comparison_id"] == q["comparison_id"] and p["semantic_role"] != q["semantic_role"])
                self.assertEqual(mate["noun"], q["noun"])
                self.assertNotEqual(mate["verb"], q["verb"])

    def test_real_confusion_and_all_required_history_fields_survive_storage(self):
        r = attempt(wrong=True)
        self.assertEqual(r["selected_answer"], "に")
        self.assertEqual(r["correct_answer"], "で")
        self.assertEqual(r["confusion_pair"], "に_で")
        self.assertFalse(r["first_try_correct"])
        self.assertEqual(r["semantic_role"], "location_action")
        self.assertEqual(r["retry_count"], 0)
        for key in ("learner_id", "question_id", "answered_at", "selected_answer", "correct_answer", "is_correct",
                    "first_try_correct", "response_time", "level", "target_particle", "semantic_role", "confusion_pair", "retry_count"):
            self.assertIn(key, r)
        with TemporaryDirectory() as folder:
            path = Path(folder) / "history.sqlite3"
            jp.init_db(path)
            jp.save_record(r, path)
            jp.save_record(r, path)
            self.assertEqual(jp.read_all("user_001", path), [r])
            self.assertEqual(jp.read_all("user_002", path), [])
        self.assertIsNone(attempt()["confusion_pair"])
        self.assertEqual(confusion_pair("を", "は"), "は_を")
        self.assertEqual(confusion_pair("へ", "に"), "に_へ")

    def test_retry_preserves_first_error_and_does_not_inflate_confusion(self):
        first = attempt(wrong=True)
        q = next(q for q in QUESTIONS if q["question_id"] == first["question_id"])
        retry = jp.make_record(q, "user_001", "retry", 1, "retry", q["answer"], 2, 2,
                               first["chain_id"], first_try_correct=False)
        self.assertTrue(retry["correct"])
        self.assertFalse(retry["first_try_correct"])
        self.assertEqual(retry["retry_count"], 1)
        self.assertIsNone(retry["confusion_pair"])
        report = analyze([first, first, retry])
        self.assertEqual(report["confusions"], {"に_で": 1})
        self.assertEqual(report["count"], 1)
        self.assertEqual(report["rate"], 0)
        group = next(g for g in report["particles"] if g["key"] == "で")
        self.assertEqual(group["total_count"], 2)
        self.assertEqual(group["total_rate"], .5)

    def test_priority_pairs_precede_other_weaknesses_and_pair_same_noun(self):
        rows = [attempt(wrong=True, identifier=i) for i in range(3)]
        topic = next(q for q in QUESTIONS if q["target_particle"] == "は")
        rows += [attempt(topic, wrong=True, identifier=20)]
        questions = recommended(rows, 5)
        self.assertTrue(all(q["confusion_pair"] == "に_で" for q in questions))
        self.assertEqual(questions[0]["level"], 3)
        self.assertEqual(questions[0]["noun"], questions[1]["noun"])
        self.assertNotEqual(questions[0]["semantic_role"], questions[1]["semantic_role"])
        self.assertEqual(len({q["question_id"] for q in questions}), 5)

    def test_particle_role_recent_error_and_unseen_priority(self):
        rows = [attempt(wrong=True, identifier=i) for i in range(3)]
        with patch("particles.analyze", wraps=analyze) as analysis:
            report = analyze(rows)
            report["priority_pairs"] = []  # 混同の次の優先順位を独立して検証。
            analysis.return_value = report
            questions = recommended(rows, 5)
            self.assertTrue(all(q["target_particle"] == "で" for q in questions if q["level"] != 3))
            self.assertEqual(questions[0]["target_particle"], "で")
        recent = attempt(wrong=True)
        # 初回数が少なくても、直近の誤答を未出題より先に選びます。
        self.assertEqual(recommended([recent], 5)[0]["question_id"], recent["question_id"])
        successful = attempt()
        self.assertTrue(all(q["question_id"] != successful["question_id"] for q in recommended([successful], 5)))

    def test_level_filter_and_independent_groups(self):
        records = [attempt(wrong=True, identifier=i) for i in range(4)]
        for level in (1, 2, 3):
            self.assertTrue(all(q["level"] == level for q in jp.choose_questions("particles", 10, particle_level=level)))
        report = analyze(records)
        self.assertEqual(next(g for g in report["particles"] if g["key"] == "で")["rate"], 0)
        self.assertIsNone(next(g for g in report["particles"] if g["key"] == "を")["rate"])
        self.assertEqual(next(g for g in report["roles"] if g["key"] == "location_action")["count"], 4)
        self.assertEqual(next(g for g in report["levels"] if g["key"] == 3)["count"], 4)

    def test_common_report_filters_subject_user_period_and_audio(self):
        rows = [attempt(wrong=True, identifier=i) for i in range(5)]
        other = attempt(identifier=7, user_id="user_002")
        old = attempt(identifier=8, datetime="2026-09-01T20:00:00+09:00")
        audio = attempt(identifier=9, reading_mode="audio")
        report = build_report([], rows + [other, old, audio], "user_001", now=datetime(2026, 10, 7, 23, tzinfo=jp.JST))
        self.assertEqual(report["groups"][-1]["count"], 5)
        self.assertEqual(report["groups"][-1]["rate"], 0)
        self.assertEqual(len(report["particle_records"]), 5)
        self.assertTrue(any("てにをは" in s for s in report["suggestions"]))


class ParticleAppTests(unittest.TestCase):
    # 既存画面検証の隔離DB・認証・ブラウザーイベントを再利用。
    setUp = jp_tests.JapaneseAppTests.setUp
    event = jp_tests.JapaneseAppTests.event
    def test_particle_back_resume_preserves_hint_time_and_first_error(self):
        self.app.radio(key="jp_category").set_value("particles").run()
        self.app.button(key="jp_start").click().run()
        state = self.app.session_state.jp_round
        question_id = state["questions"][0]["question_id"]
        chain = self.app.session_state.jp_chains[question_id]

        def action(name, seconds, answer=None):
            state = self.app.session_state.jp_round
            token = f"{state['session_id']}:{state['index']}:{state['phase']}"
            if state.get("resume_revision", 0):
                token += f":resume{state['resume_revision']}"
            self.app.session_state.jp_keyboard = {"token": token, "action": name, "answer": answer,
                "response_time_sec": seconds, "hint_used": True, "draft_order": []}
            self.app.run()

        action("back", 4)
        self.assertEqual(self.app.session_state.screen, "jp_settings")
        self.assertEqual(jp.read_all("user_001"), [])
        self.app.button(key="jp_resume").click().run()
        self.assertEqual(self.app.session_state.jp_round["draft"]["elapsed"], 4)
        self.assertTrue(self.app.session_state.jp_round["draft"]["hint_used"])
        q = self.app.session_state.jp_round["questions"][0]
        self.assertEqual(q["question_id"], question_id)
        action("answer", 7, 1 - q["answer"])
        first = jp.read_all("user_001")[0]
        self.assertTrue(first["hint_used"])
        self.assertEqual(first["response_time_sec"], 7)
        self.assertFalse(first["first_try_correct"])
        self.assertEqual(first["chain_id"], chain)
        action("back", 8)
        self.app.button(key="jp_resume").click().run()
        self.assertEqual(self.app.session_state.jp_round["phase"], "feedback")
        self.assertEqual(jp.read_all("user_001"), [first])

    def test_particle_level_retry_snapshot_and_report_button(self):
        self.app.radio(key="jp_category").set_value("particles").run()
        self.app.radio(key="jp_particle_level").set_value(3)
        self.app.radio(key="jp_count").set_value(5)
        self.app.button(key="jp_start").click().run()
        for i in range(5):
            q = self.app.session_state.jp_round["questions"][i]
            self.assertEqual(q["level"], 3)
            self.event(1 - q["answer"])
            self.event(next=True)
        self.app.button(key="jp_retry").click().run()
        q = self.app.session_state.jp_round["questions"][0]
        self.event(q["answer"])
        rows = jp.read_all("user_001")
        self.assertEqual(rows[0]["retry_count"], 1)
        self.assertFalse(rows[0]["first_try_correct"])
        self.assertTrue(rows[0]["correct"])
        self.app.button(key="jp_analysis_jp_practice").click().run()
        self.assertEqual(len(self.app.exception), 0)
        self.assertTrue(any(b.key == "particle_report_practice" for b in self.app.button))
        self.app.button(key="particle_report_practice").click().run()
        self.assertEqual(self.app.session_state.jp_round["selection"], "weak_area")
        self.assertTrue(all(q["category"] == "particles" for q in self.app.session_state.jp_round["questions"]))


if __name__ == "__main__":
    unittest.main()
