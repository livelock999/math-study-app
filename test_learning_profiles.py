"""表示学年の年度境界、学習者ごとの保存、クラウド失敗時の扱いを検証。"""

from contextlib import closing
from copy import deepcopy
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit
import json
import sqlite3
import tempfile
import unittest

import learning_profiles as profiles
from activity import JST


class CloudResponse:
    def __init__(self, rows=None, status=200, body=None):
        self.status = status
        self.body = body if body is not None else json.dumps(rows, ensure_ascii=False).encode("utf-8")

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def profile(user="user_001", **changes):
    result = profiles.default_profile(user, datetime(2026, 10, 8, tzinfo=JST))
    result.update(changes)
    return result


class LearningProfileTests(unittest.TestCase):
    def test_school_year_changes_at_april_first_in_japan(self):
        before = datetime(2026, 3, 31, 14, 59, 59, tzinfo=timezone.utc)
        after = datetime(2026, 3, 31, 15, 0, 0, tzinfo=timezone.utc)
        self.assertEqual(profiles.school_year(before), 2025)
        self.assertEqual(profiles.school_year(after), 2026)
        child = profile(grade=2, base_school_year=2025, auto_advance=True)
        self.assertEqual(profiles.effective_grade(child, before), 2)
        self.assertEqual(profiles.effective_grade(child, after), 3)
        self.assertEqual(profiles.school_year(date(2026, 3, 31)), 2025)
        self.assertEqual(profiles.school_year(date(2026, 4, 1)), 2026)

    def test_calendar_new_year_and_leap_day_do_not_advance_grade(self):
        child = profile(grade=1, base_school_year=2026, auto_advance=True)
        for now, expected in (
            (datetime(2026, 12, 31, tzinfo=JST), 1),
            (datetime(2027, 1, 1, tzinfo=JST), 1),
            (datetime(2028, 2, 29, tzinfo=JST), 2),
            (datetime(2028, 4, 1, tzinfo=JST), 3),
        ):
            with self.subTest(now=now):
                self.assertEqual(profiles.effective_grade(child, now), expected)

    def test_auto_off_preserves_manual_grade_through_future_years(self):
        child = profile(grade=2, base_school_year=2026, auto_advance=False)
        self.assertEqual(profiles.effective_grade(child, date(2038, 4, 1)), 2)
        self.assertEqual(profiles.effective_grade(child, date(2020, 4, 1)), 2)

    def test_skipped_years_advance_once_each_and_cap_at_six(self):
        child = profile(grade=2, base_school_year=2026, auto_advance=True)
        self.assertEqual(profiles.effective_grade(child, date(2029, 4, 1)), 5)
        self.assertEqual(profiles.effective_grade(child, date(2030, 4, 1)), 6)
        self.assertEqual(profiles.effective_grade(child, date(2040, 4, 1)), 6)
        self.assertEqual(profiles.effective_grade(child, date(2025, 4, 1)), 2)
        sixth = profile(grade=6, auto_advance=True)
        self.assertEqual(profiles.effective_grade(sixth, date(2028, 4, 1)), 6)

    def test_manual_change_uses_new_base_year_after_previous_advancement(self):
        now = datetime(2028, 10, 8, tzinfo=JST)
        old = profile(grade=2, base_school_year=2026, auto_advance=True)
        self.assertEqual(profiles.effective_grade(old, now), 4)
        changed = dict(old, grade=3, base_school_year=profiles.school_year(now))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "profiles.sqlite3"
            profiles.save_profile(changed, path)
            saved = profiles.load_profile("user_001", path, now)
        self.assertEqual(saved["base_school_year"], 2028)
        self.assertEqual(profiles.effective_grade(saved, now), 3)
        self.assertEqual(profiles.effective_grade(saved, date(2029, 4, 1)), 4)

    def test_defaults_are_child_specific_and_do_not_enable_auto_advance(self):
        now = datetime(2026, 3, 30, tzinfo=JST)
        first = profiles.default_profile("user_001", now)
        second = profiles.default_profile("user_002", now)
        self.assertEqual(first["base_school_year"], 2025)
        self.assertEqual(first["grade"], 1)
        self.assertFalse(first["auto_advance"])
        self.assertEqual(first["furigana_mode"], "all")
        first["unlearned"].append("学")
        self.assertEqual(second["unlearned"], [])
        self.assertEqual(second["user_id"], "user_002")

    def test_local_roundtrip_updates_one_child_without_changing_another(self):
        first = profile(grade=3, furigana_mode="current", unlearned=["習", "学", "学"])
        second = profile("user_002", grade=2, furigana_mode="none", reading_tap=False)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "nested" / "profiles.sqlite3"
            with patch.object(profiles.learning, "get_supabase_config", side_effect=AssertionError("explicit local path")):
                self.assertEqual(profiles.load_profile("user_001", path, date(2026, 10, 8)), profile())
                profiles.save_profile(first, path)
                profiles.save_profile(second, path)
                first["grade"] = 4
                profiles.save_profile(first, path)
                loaded_first = profiles.load_profile("user_001", path)
                loaded_second = profiles.load_profile("user_002", path)
            self.assertEqual(loaded_first["grade"], 4)
            self.assertEqual(loaded_first["unlearned"], sorted(["習", "学"]))
            self.assertEqual(loaded_second, second)
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM profiles").fetchone()[0], 2)

    def test_local_row_cannot_return_another_childs_payload(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "profiles.sqlite3"
            profiles.save_profile(profile(), path)
            with closing(sqlite3.connect(path)) as db, db:
                db.execute("UPDATE profiles SET payload=? WHERE user_id=?",
                           (json.dumps(profile("user_002")), "user_001"))
            with self.assertRaises(ValueError):
                profiles.load_profile("user_001", path)

    def test_validation_rejects_wrong_types_and_out_of_range_settings(self):
        invalid_values = {
            "user_id": [None, "missing", "", [], {}],
            "grade": [0, 7, -1, True, False, 1.0, "1", None],
            "base_school_year": [1999, 10000, True, 2026.0, "2026", None],
            "auto_advance": [0, 1, "true", None],
            "reading_tap": [0, 1, "true", None],
            "furigana_mode": ["unknown", None, [], {}],
            "unlearned": [None, "学", (), ["学校"], ["あ"], ["A"], [1], ["学"] * 129],
        }
        for name, values in invalid_values.items():
            for value in values:
                with self.subTest(name=name, value=value):
                    invalid = profile()
                    invalid[name] = value
                    with self.assertRaises(ValueError):
                        profiles.validate_profile(invalid)
        for key in profile():
            invalid = profile()
            del invalid[key]
            with self.subTest(missing=key), self.assertRaises(ValueError):
                profiles.validate_profile(invalid)

    def test_validation_returns_normalized_copy_without_mutating_input(self):
        original = profile(unlearned=["習", "学", "学"])
        before = deepcopy(original)
        normalized = profiles.validate_profile(original)
        self.assertEqual(original, before)
        self.assertEqual(normalized["unlearned"], sorted(["習", "学"]))
        normalized["unlearned"].append("校")
        self.assertEqual(original, before)

    def test_cloud_get_filters_user_and_returns_validated_payload(self):
        child = profile(grade=3, furigana_mode="current", unlearned=["学", "学"])
        with patch.object(profiles.learning, "get_supabase_config", return_value=("https://example.test", "test-secret")), \
                patch.object(profiles.learning, "supabase_urlopen",
                             return_value=CloudResponse([{"user_id": "user_001", "payload": child}])) as send, \
                patch.object(profiles.sqlite3, "connect", side_effect=AssertionError("cloud must not read local")):
            result = profiles.load_profile("user_001")
        self.assertEqual(result, profiles.validate_profile(child))
        request = send.call_args.args[0]
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(urlsplit(request.full_url).path, "/rest/v1/learning_profiles")
        query = parse_qs(urlsplit(request.full_url).query)
        self.assertEqual(query["user_id"], ["eq.user_001"])
        self.assertEqual(query["select"], ["user_id,payload"])
        self.assertEqual(query["limit"], ["1"])
        self.assertEqual(dict((k.lower(), v) for k, v in request.header_items())["apikey"], "test-secret")
        self.assertEqual(send.call_args.kwargs["timeout"], 15)

    def test_cloud_missing_profile_returns_defaults_without_local_access(self):
        with patch.object(profiles.learning, "get_supabase_config", return_value=("https://example.test", "test-secret")), \
                patch.object(profiles.learning, "supabase_urlopen", return_value=CloudResponse([])), \
                patch.object(profiles.sqlite3, "connect", side_effect=AssertionError("cloud must not read local")):
            child = profiles.load_profile("user_002", now=date(2027, 4, 1))
        self.assertEqual(child, profiles.default_profile("user_002", date(2027, 4, 1)))

    def test_cloud_post_upserts_child_profile_as_a_single_row(self):
        child = profile(grade=4, furigana_mode="none", unlearned=["学", "学"])
        with patch.object(profiles.learning, "get_supabase_config", return_value=("https://example.test", "test-secret")), \
                patch.object(profiles.learning, "supabase_urlopen", return_value=CloudResponse(status=201)) as send, \
                patch.object(profiles.sqlite3, "connect", side_effect=AssertionError("cloud must not write local")):
            profiles.save_profile(child)
        request = send.call_args.args[0]
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(parse_qs(urlsplit(request.full_url).query), {"on_conflict": ["user_id"]})
        headers = {k.lower(): v for k, v in request.header_items()}
        self.assertEqual(headers["prefer"], "resolution=merge-duplicates,return=minimal")
        self.assertEqual(headers["content-type"], "application/json")
        body = json.loads(request.data)
        self.assertEqual(body["user_id"], "user_001")
        self.assertEqual(body["payload"], profiles.validate_profile(child))

    def test_invalid_child_is_rejected_before_any_cloud_request(self):
        with patch.object(profiles.learning, "get_supabase_config") as config, \
                patch.object(profiles.learning, "supabase_urlopen") as send:
            with self.assertRaises(ValueError):
                profiles.load_profile("user_001&user_id=eq.user_002")
            with self.assertRaises(ValueError):
                profiles.save_profile(profile("unknown"))
        config.assert_not_called()
        send.assert_not_called()

    def test_cloud_read_rejects_wrong_user_and_malformed_rows(self):
        row = {"user_id": "user_001", "payload": profile()}
        bad_rows = [
            {"unexpected": "shape"}, [row, row], [None],
            [{"user_id": "user_002", "payload": profile()}],
            [{"user_id": "user_001", "payload": profile("user_002")}],
            [{"user_id": "user_001", "payload": dict(profile(), grade=True)}],
            [{"user_id": "user_001", "payload": None}],
        ]
        for rows in bad_rows:
            with self.subTest(rows=rows), \
                    patch.object(profiles.learning, "get_supabase_config", return_value=("https://example.test", "test-secret")), \
                    patch.object(profiles.learning, "supabase_urlopen", return_value=CloudResponse(rows)), \
                    patch.object(profiles.sqlite3, "connect", side_effect=AssertionError("no local fallback")):
                with self.assertRaises(OSError) as error:
                    profiles.load_profile("user_001")
                self.assertNotIn("test-secret", str(error.exception))

    def test_cloud_read_and_write_failures_hide_secrets_and_never_fall_back_locally(self):
        secret = "private-config-token"
        errors = [
            URLError(secret),
            HTTPError("https://example.test/" + secret, 403, secret, {}, None),
            OSError(secret),
        ]
        for operation in (lambda: profiles.load_profile("user_001"), lambda: profiles.save_profile(profile())):
            for remote_error in errors:
                with self.subTest(operation=operation, remote_error=type(remote_error).__name__), \
                        patch.object(profiles.learning, "get_supabase_config", return_value=("https://example.test", secret)), \
                        patch.object(profiles.learning, "supabase_urlopen", side_effect=remote_error), \
                        patch.object(profiles.sqlite3, "connect", side_effect=AssertionError("no local fallback")):
                    with self.assertRaises(OSError) as error:
                        operation()
                    self.assertNotIn(secret, str(error.exception))
                    self.assertTrue(error.exception.__suppress_context__)

    def test_cloud_bad_status_or_json_are_sanitized(self):
        bad_reads = [CloudResponse([], status=403), CloudResponse(body=b"private-config-token"),
                     CloudResponse([], status="private-config-token")]
        for response in bad_reads:
            with self.subTest(read=response.status), \
                    patch.object(profiles.learning, "get_supabase_config", return_value=("https://example.test", "private-config-token")), \
                    patch.object(profiles.learning, "supabase_urlopen", return_value=response), \
                    patch.object(profiles.sqlite3, "connect", side_effect=AssertionError("no local fallback")):
                with self.assertRaises(OSError) as error:
                    profiles.load_profile("user_001")
                self.assertNotIn("private-config-token", str(error.exception))
        for status in (400, 500, "private-config-token", None):
            with self.subTest(write=status), \
                    patch.object(profiles.learning, "get_supabase_config", return_value=("https://example.test", "private-config-token")), \
                    patch.object(profiles.learning, "supabase_urlopen", return_value=CloudResponse(status=status)), \
                    patch.object(profiles.sqlite3, "connect", side_effect=AssertionError("no local fallback")):
                with self.assertRaises(OSError) as error:
                    profiles.save_profile(profile())
                self.assertNotIn("private-config-token", str(error.exception))


if __name__ == "__main__":
    unittest.main()

