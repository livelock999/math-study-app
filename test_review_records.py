"""復習回答の保存と、通常の初回評価からの分離。実データには触れません。"""

from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.error import URLError
import json
import random
import unittest

import activity
import assessment
import cross_subject
import japanese
import learning
import particles
from japanese_questions import QUESTIONS
from words import make_word_problem


NOW = datetime(2026, 10, 8, 12, tzinfo=activity.JST)


def math_record(selection="normal", answer=5, question=None):
    row = learning.make_attempt(question or learning.make_problem("addition", 10, 2, 3),
                                "user_001", selection, 1, selection, answer, 2, 1,
                                round_size=1,
                                selected_operation="addition" if question else None)
    row["datetime"] = NOW.isoformat()
    return row


def jp_record(selection="normal", answer=None, question=None, count=1, chain=None):
    question = question or QUESTIONS[0]
    row = japanese.make_record(question, "user_001", selection, 1, selection,
                               question["answer"] if answer is None else answer,
                               2, count, chain or selection,
                               first_try_correct=False if count > 1 else None)
    row["datetime"] = NOW.isoformat()
    return row


class ReviewRecordTests(unittest.TestCase):
    def test_selection_validation_retry_flag_and_chain_contract(self):
        for selection in ("review", "review_retry"):
            self.assertEqual(math_record(selection)["retry_flag"], selection == "review_retry")
            self.assertEqual(jp_record(selection)["retry_flag"], selection == "review_retry")
        root = jp_record("review", answer=1, chain="daily-root")
        retry = jp_record("review_retry", count=2, chain=root["chain_id"])
        self.assertEqual(root["chain_id"], retry["chain_id"])
        for maker in (math_record, jp_record):
            with self.assertRaises(ValueError):
                maker("invalid")

    def test_math_initial_weak_retry_and_word_metrics_unchanged(self):
        rows = [math_record(answer=4) for _ in range(5)]
        word = make_word_problem("increase", 10, 2, 3)
        rows.append(math_record(question=word))
        before = assessment.assess(rows)
        after = assessment.assess(rows + [math_record("review"), math_record("review_retry"),
                                         math_record("review", question=word)])
        for key in before:
            if key not in ("review", "review_retry", "word_review", "word_review_retry"):
                self.assertEqual(before[key], after[key], key)
        self.assertEqual(after["review"]["count"], 1)
        self.assertEqual(after["word_review"]["count"], 1)

    def test_japanese_original_chain_outcomes_and_weak_analysis_unchanged(self):
        rows = [jp_record(answer=1, chain=str(index)) for index in range(5)]
        rows.append(jp_record("retry", count=2, chain="0"))
        extra = [jp_record("review", answer=1, chain="daily"),
                 jp_record("review_retry", count=2, chain="daily")]
        before, after = japanese.metrics(rows), japanese.metrics(rows + extra)
        for key in before:
            if key not in ("review", "review_retry"):
                self.assertEqual(before[key], after[key], key)
        before, after = japanese.analyze(rows, now=NOW), japanese.analyze(rows + extra, now=NOW)
        for key in before:
            if key not in ("review", "review_retry"):
                self.assertEqual(before[key], after[key], key)
        self.assertEqual(after["review"]["count"], 1)
        self.assertEqual(after["review_retry"]["correct"], 1)

    def test_particles_analysis_and_recommendations_unchanged(self):
        question = particles.QUESTIONS[0]
        rows = [jp_record(question=question, answer=1 - question["answer"], chain=str(i)) for i in range(5)]
        extra = [jp_record("review", question=question), jp_record("review_retry", question=question, count=2)]
        self.assertEqual(particles.analyze(rows), particles.analyze(rows + extra))
        random.seed(20)
        before = particles.recommended(rows)
        random.seed(20)
        self.assertEqual(before, particles.recommended(rows + extra))

    def test_cross_subject_initial_groups_retry_and_suggestions_unchanged(self):
        math = [math_record(answer=4) for _ in range(5)]
        jp = [jp_record(answer=1) for _ in range(5)]
        before = cross_subject.build_report(math, jp, "user_001", now=NOW)
        after = cross_subject.build_report(math + [math_record("review"), math_record("review_retry")],
                                           jp + [jp_record("review"), jp_record("review_retry")],
                                           "user_001", now=NOW)
        for subject in ("math", "japanese"):
            self.assertEqual(before["subjects"][subject]["initial"], after["subjects"][subject]["initial"])
            self.assertEqual(before["subjects"][subject]["retry"], after["subjects"][subject]["retry"])
            self.assertEqual(after["subjects"][subject]["review"]["count"], 1)
        self.assertEqual(before["groups"], after["groups"])
        self.assertEqual(before["suggestions"], after["suggestions"])

    def test_calendar_review_is_not_normal_or_retry(self):
        rows = [math_record(selection) for selection in ("normal", "retry", "review", "review_retry")]
        day = activity.month_summary(rows, 2026, 10)["days"][8]
        self.assertEqual([day[f"{name}_count"] for name in ("normal", "retry", "review", "review_retry")], [1, 1, 1, 1])

    def test_sqlite_retry_write_is_idempotent_and_preserves_review_metadata(self):
        with TemporaryDirectory() as directory:
            for module, initializer, saver, reader, row in (
                (learning, learning.init_db, learning.save_attempt, learning.read_attempts, math_record("review")),
                (japanese, japanese.init_db, japanese.save_record, japanese.read_records, jp_record("review")),
            ):
                path = Path(directory) / f"{module.__name__}.sqlite3"
                initializer(path)
                saver(row, path)
                saver(row, path)
                records, more = reader("user_001", path=path)
                self.assertFalse(more)
                self.assertEqual(len(records), 1)
                self.assertEqual(records[0]["attempt_id"], row["attempt_id"])
                self.assertEqual(records[0]["selection_type"], "review")
                self.assertEqual(reader("user_002", path=path)[0], [])

    def test_cloud_save_failure_retry_reuses_same_attempt_id(self):
        for saver, row in ((learning.save_attempt, math_record("review")),
                           (japanese.save_record, jp_record("review"))):
            with patch("learning.get_supabase_config", return_value=("https://example.supabase.co", "sb_secret_test")), \
                 patch("learning.supabase_urlopen") as remote:
                remote.side_effect = URLError("failed")
                with self.assertRaises(OSError):
                    saver(row)
                failed_payload = json.loads(remote.call_args.args[0].data)
                remote.side_effect = None
                remote.return_value.__enter__.return_value.status = 201
                saver(row)
                request = remote.call_args.args[0]
                self.assertEqual(failed_payload, json.loads(request.data))
                self.assertIn("resolution=ignore-duplicates", request.get_header("Prefer"))


if __name__ == "__main__":
    unittest.main()
