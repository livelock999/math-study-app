"""学習カレンダーの月境界と、保存済み完了回答からのスタンプを検証。"""

from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import tempfile
import unittest

from activity import month_summary
from learning import init_db, make_attempt, make_problem, read_month_attempts, save_attempt


def answer(timestamp, session="session", order=1, size=1, selection="normal", user="user_001"):
    record = make_attempt(make_problem("addition", 10, 2, 3), user, session, order,
                          selection, 5, 1.5, 1, round_size=size)
    record["datetime"] = timestamp
    return record


class ActivityTests(unittest.TestCase):
    def test_jst_month_boundaries_exclude_neighbor_months(self):
        records = [answer("2026-09-30T14:59:59+00:00", "before"),
                   answer("2026-09-30T15:00:00+00:00", "first"),
                   answer("2026-10-31T14:59:59+00:00", "last"),
                   answer("2026-10-31T15:00:00+00:00", "after")]
        result = month_summary(records, 2026, 10)
        self.assertEqual(result["days"][1]["count"], 1)
        self.assertEqual(result["days"][31]["count"], 1)
        self.assertEqual(sum(day["count"] for day in result["days"].values()), 2)
        self.assertEqual(result["stamps"], 2)

    def test_stamps_count_completed_sessions_once_and_retry_separately(self):
        incomplete = answer("2026-10-07T10:00:00+09:00", "incomplete", size=5)
        finished = answer("2026-10-07T11:00:00+09:00", "complete", order=5, size=5)
        retry = answer("2026-10-07T12:00:00+09:00", "retry", selection="retry")
        retry["is_correct"] = False
        legacy = answer("2026-10-07T13:00:00+09:00", "legacy")
        legacy.update(round_size=None, round_completed=None)
        result = month_summary([incomplete, finished, dict(finished), retry, legacy], 2026, 10)
        self.assertEqual(result["stamps"], 2)
        self.assertEqual(result["days"][7]["stamps"], 2)
        self.assertEqual(result["days"][7]["retry_count"], 1)
        self.assertEqual(result["days"][7]["retry_correct"], 0)

    def test_month_reader_includes_more_than_500_and_only_selected_user(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "history.sqlite3"
            init_db(path)
            for index in range(505):
                record = answer("2026-10-07T10:00:00+09:00", f"session_{index}")
                save_attempt(record, path)
            for record in [answer("2026-10-07T11:00:00+09:00", "other", user="user_002"),
                           answer("2026-09-30T14:59:59+00:00", "before"),
                           answer("2026-10-31T15:00:00+00:00", "after"),
                           answer("2026-09-30T15:00:00+00:00", "boundary")]:
                save_attempt(record, path)
            records = read_month_attempts("user_001", 2026, 10, path=path)
            self.assertEqual(len(records), 506)
            self.assertTrue(all(record["user_id"] == "user_001" for record in records))
            result = month_summary(records, 2026, 10)
            self.assertEqual(result["stamps"], 506)
            self.assertEqual(result["days"][7]["count"], 505)
            self.assertEqual(result["days"][1]["count"], 1)
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0], 509)


if __name__ == "__main__":
    unittest.main()
