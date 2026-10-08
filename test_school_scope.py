"""学校範囲の保存・教材制約・過去学習の復習を検証する。"""
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit
import json
import sqlite3
import unittest

import school_scope as school
import learning
import learning_extensions as store
import japanese as jp
import daily_review as review
from japanese_questions import QUESTIONS
from parent_insights import review_forecast
from practice_mode import switch_mode

NOW = datetime(2026, 10, 8, 12, tzinfo=review.JST)


class SchoolScopeTests(unittest.TestCase):
    def scope(self, math="current", japanese="current", user="user_001"):
        return school.validate(user, math, japanese)

    def test_default_reads_do_not_create_db_and_separate_children(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "scope.sqlite3"
            self.assertEqual(school.read_scope("user_001", path), self.scope())
            self.assertFalse(path.exists())
            school.save_scope("user_001", "addition_10", "words", path)
            school.save_scope("user_002", "mix_20", "particles_3", path)
            school.save_scope("user_001", "addition_10", "words", path)
            self.assertEqual(school.read_scope("user_001", path), self.scope("addition_10", "words"))
            self.assertEqual(school.read_scope("user_002", path), self.scope("mix_20", "particles_3", "user_002"))
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM family_school_scope").fetchone()[0], 2)

    def test_goals_and_feedback_are_preserved_in_same_db(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "shared.sqlite3"
            store.save_goals("user_001", 4, 7, path)
            report = store.make_feedback("user_001", "math", "problem", "reading")
            store.save_feedback(report, path)
            school.save_scope("user_001", "subtraction_10", "sentence", path)
            store.save_goals("user_001", 5, 10, path)
            self.assertEqual(store.read_goals("user_001", path)["weekly_days"], 5)
            self.assertEqual(store.read_feedback("user_001", path), [report])
            self.assertEqual(school.read_scope("user_001", path), self.scope("subtraction_10", "sentence"))

    def test_invalid_settings_rejected(self):
        for changes in ({"user_id": "other"}, {"math_unit": []}, {"math_unit": "multiply"},
                        {"japanese_unit": "particles_4"}, {"japanese_unit": 1}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                school.save_scope(**{**self.scope(), **changes}, test_mode=True)
        with self.assertRaises(ValueError):
            school.plan_math([], "user_002", self.scope())

    def test_test_mode_no_io_and_preview_cleanup_both_directions(self):
        with patch("learning.get_supabase_config", side_effect=AssertionError("config")), \
                patch("school_scope.sqlite3.connect", side_effect=AssertionError("db")):
            self.assertEqual(school.save_scope(**self.scope("mix_20", "words"), test_mode=True), self.scope("mix_20", "words"))
        session = {"parent_test_mode": True, "school_scope_preview": {"user_001": self.scope("mix_20", "words")},
                   "school_scope_math_user_001": "mix_20", "school_scope_pending": {}, "school_scope_loaded": {}}
        self.assertEqual(school.active_scope("user_001", session)["math_unit"], "mix_20")
        switch_mode(session, False)
        self.assertFalse(any(key.startswith("school_scope_") for key in session))
        session["school_scope_loaded"] = {"user_001": self.scope()}
        switch_mode(session, True)
        self.assertNotIn("school_scope_loaded", session)

    def test_all_units_constrain_adaptive_questions(self):
        for key, (_, settings) in school.MATH_UNITS.items():
            plan = school.plan_math([], "user_001", self.scope(key), count=5, now=NOW)
            self.assertEqual(len({p["problem_id"] for p in plan["items"]}), len(plan["items"]))
            if settings:
                mode, limit, special = settings
                for p in plan["items"]:
                    self.assertEqual(p["number_range"], limit)
                    self.assertTrue(mode == "mix" or p["operation"] == mode)
                    if special != "auto":
                        self.assertEqual(bool(p["carry"] or p["borrowing"]), special == "with")
        for key in school.JP_UNITS:
            plan = school.plan_japanese([], "user_001", self.scope(japanese=key), now=NOW)
            self.assertEqual(len({q["question_id"] for q in plan["items"]}), len(plan["items"]))
            if key.startswith("particles_"):
                self.assertTrue(all(q["category"] == "particles" and q["level"] <= int(key[-1]) for q in plan["items"]))
            elif key not in ("current", "mix"):
                self.assertTrue(all(q["category"] == key for q in plan["items"]))

    def test_school_particle_ceiling_allows_adaptation_but_manual_is_exact(self):
        from test_adaptive_difficulty import jp_rows
        plan = school.plan_japanese(jp_rows(1), "user_001", self.scope(japanese="particles_2"), count=5, now=NOW)
        self.assertEqual(plan["decisions"]["particles"]["level"], 2)
        self.assertTrue(all(q["level"] == 2 for q in plan["items"]))

    def test_review_keeps_previous_problem_ids_and_excludes_foreign_future(self):
        p = learning.make_problem("subtraction", 20, 14, 7)
        old = learning.make_attempt(p, "user_001", "old", 1, "normal", 99, 1, 1)
        old["datetime"] = (NOW - timedelta(days=1)).isoformat()
        other_p = learning.make_problem("subtraction", 20, 15, 6)
        other = {**old, **other_p, "attempt_id": "other", "user_id": "user_002"}
        future = {**old, **other_p, "attempt_id": "future", "datetime": (NOW + timedelta(days=1)).isoformat()}
        rows = [old, old, other, future]
        scope = self.scope("addition_10")
        pool = school.review_pool(rows, "user_001", scope, "math", now=NOW)
        ids = {q["problem_id"] for q in pool}
        self.assertIn(p["problem_id"], ids)
        self.assertNotIn(other_p["problem_id"], ids)
        self.assertTrue(all(q["number_range"] == 10 and q["operation"] == "addition"
                            or q["problem_id"] == p["problem_id"] for q in pool))
        plan = review.plan_math(rows, "user_001", now=NOW, candidate_pool=pool)
        self.assertEqual(plan["items"][0]["problem_id"], p["problem_id"])
        forecast = review_forecast(rows, "user_001", "math", now=NOW, candidate_pool=pool)
        self.assertEqual(forecast["today_total"], 1)
        done = [{**old, "attempt_id": f"done{i}", "selection_type": "review", "datetime": NOW.isoformat()} for i in range(5)]
        self.assertEqual(review.plan_math(rows + done, "user_001", now=NOW, candidate_pool=pool)["items"], [])

    def test_japanese_review_keeps_previous_higher_particle_and_chain(self):
        q = next(q for q in QUESTIONS if q["category"] == "particles" and q["level"] == 3)
        record = jp.make_record(q, "user_001", "old", 1, "normal", (q["answer"] + 1) % len(q["choices"]), 1, 1, "old-chain")
        record["datetime"] = (NOW - timedelta(days=1)).isoformat()
        pool = school.review_pool([record], "user_001", self.scope(japanese="words"), "japanese", now=NOW)
        self.assertEqual({x["category"] for x in pool}, {"words", "particles"})
        plan = review.plan_japanese([record], "user_001", now=NOW, candidate_pool=pool)
        self.assertEqual(plan["items"][0]["question_id"], q["question_id"])
        self.assertEqual(record["chain_id"], "old-chain")
        self.assertEqual(review_forecast([record], "user_001", "japanese", now=NOW, candidate_pool=pool)["today_total"], 1)

    def test_current_scope_preserves_existing_settings_and_review(self):
        plan = school.plan_math([], "user_001", self.scope(), mode="subtraction", limit=20, count=5)
        self.assertTrue(all(q["operation"] == "subtraction" and q["number_range"] == 20 for q in plan["items"]))
        self.assertIsNone(school.review_pool([], "user_001", self.scope(), "math", NOW))


class SchoolCloudTests(unittest.TestCase):
    def setUp(self):
        config = patch("learning.get_supabase_config", return_value=("https://example.supabase.co", "sb_secret_test_only"))
        config.start()
        self.addCleanup(config.stop)

    def test_filtered_read_and_atomic_upsert(self):
        own = school.validate("user_001", "mix_20", "particles_2")
        with patch("learning.supabase_urlopen") as remote, patch("school_scope.sqlite3.connect") as local:
            response = remote.return_value.__enter__.return_value
            response.status = 200
            response.read.return_value = json.dumps([own]).encode()
            self.assertEqual(school.read_scope("user_001"), own)
            self.assertEqual(parse_qs(urlsplit(remote.call_args.args[0].full_url).query)["user_id"], ["eq.user_001"])
            school.save_scope(**own)
            request = remote.call_args.args[0]
            self.assertIn("family_school_scope?on_conflict=user_id", request.full_url)
            self.assertIn("merge-duplicates", request.get_header("Prefer"))
            self.assertEqual({k: json.loads(request.data)[k] for k in own}, own)
            local.assert_not_called()

    def test_invalid_cloud_data_and_missing_table_stop_without_fallback(self):
        for rows in ([school.default_scope("user_002")], [{"user_id": "user_001"}], {}, [school.default_scope("user_001")] * 2):
            with patch("learning.supabase_urlopen") as remote:
                response = remote.return_value.__enter__.return_value
                response.status = 200
                response.read.return_value = json.dumps(rows).encode()
                with self.assertRaises(OSError):
                    school.read_scope("user_001")
        error = HTTPError("https://example.supabase.co/rest/v1/family_school_scope", 404, "test secret", {}, None)
        with patch("learning.supabase_urlopen", side_effect=error), patch("school_scope.sqlite3.connect") as local:
            with self.assertRaisesRegex(OSError, "supabase_school_scope.sql"):
                school.read_scope("user_001")
            local.assert_not_called()

    def test_sql_catalog_matches_and_only_adds_school_table(self):
        sql = Path("supabase_school_scope.sql").read_text(encoding="utf-8")
        setup = Path("supabase_setup.sql").read_text(encoding="utf-8")
        for unit in (*school.MATH_UNITS, *school.JP_UNITS):
            self.assertIn(f"'{unit}'", sql)
            self.assertIn(f"'{unit}'", setup)
        self.assertIn("enable row level security", sql)
        self.assertIn("grant select, insert, update", sql)
        self.assertNotIn("drop ", sql.lower())
        self.assertNotIn("math_attempts", sql)


if __name__ == "__main__":
    unittest.main()
