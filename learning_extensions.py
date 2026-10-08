"""共通の学習目標と問題報告。学習回答とは分離し、子どもごとに保存します。"""

from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request
import json
import sqlite3

import learning

JST = timezone(timedelta(hours=9))
DB_PATH = Path(__file__).parent / "data" / "learning_extensions.sqlite3"
FEEDBACK_REASONS = {"difficult": "難しすぎる", "reading": "読みづらい", "answer": "答えがおかしい"}
SUBJECTS = {"math": "算数", "japanese": "国語"}


def _learner(user_id):
    if not isinstance(user_id, str) or user_id not in learning.USERS:
        raise ValueError("学習者が不正です。")


def default_goals(user_id):
    _learner(user_id)
    return {"user_id": user_id, "weekly_days": 3, "daily_questions": 5}


def _goals(user_id, weekly_days, daily_questions):
    _learner(user_id)
    if (type(weekly_days) is not int or not 1 <= weekly_days <= 7
            or type(daily_questions) is not int or not 1 <= daily_questions <= 20):
        raise ValueError("学習目標は週1〜7日、1日1〜20問で設定してください。")
    return {"user_id": user_id, "weekly_days": weekly_days, "daily_questions": daily_questions}


def _cloud(request, label):
    try:
        with learning.supabase_urlopen(request, timeout=15) as response:
            if not 200 <= response.status < 300:
                raise OSError()
            if request.get_method() == "GET":
                return json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        if error.code == 404:
            raise OSError(f"{label}の保存先が未設定です。Supabaseで supabase_learning_extensions.sql を実行してください。") from None
        raise OSError(f"{label}をクラウドで処理できませんでした。接続と保存先設定を確認し、再試行してください。") from None
    except (URLError, OSError, ValueError, TypeError, AttributeError):
        raise OSError(f"{label}をクラウドで処理できませんでした。接続と保存先設定を確認し、再試行してください。") from None


def init_db(path=None):
    if path is None and learning.get_supabase_config() is not None:
        return
    path = Path(path or DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path, timeout=10)) as db, db:
        db.execute("CREATE TABLE IF NOT EXISTS family_learning_settings (user_id TEXT PRIMARY KEY, "
                   "weekly_days INTEGER NOT NULL CHECK(weekly_days BETWEEN 1 AND 7), "
                   "daily_questions INTEGER NOT NULL CHECK(daily_questions BETWEEN 1 AND 20), "
                   "updated_at TEXT NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS problem_feedback (feedback_id TEXT PRIMARY KEY, "
                   "user_id TEXT NOT NULL, subject TEXT NOT NULL, problem_id TEXT NOT NULL, "
                   "reason TEXT NOT NULL, datetime TEXT NOT NULL)")
        db.execute("CREATE INDEX IF NOT EXISTS feedback_user_date ON problem_feedback(user_id, datetime)")


def read_goals(user_id, path=None):
    default = default_goals(user_id)
    config = learning.get_supabase_config() if path is None else None
    if config:
        url, key = config
        query = urlencode({"user_id": f"eq.{user_id}", "select": "user_id,weekly_days,daily_questions", "limit": 1})
        rows = _cloud(Request(f"{url}/rest/v1/family_learning_settings?{query}",
                              headers={"apikey": key, "Accept": "application/json"}), "学習目標")
        try:
            if not isinstance(rows, list) or len(rows) > 1:
                raise ValueError()
            if not rows:
                return default
            row = _goals(rows[0]["user_id"], rows[0]["weekly_days"], rows[0]["daily_questions"])
            if row["user_id"] != user_id:
                raise ValueError()
            return row
        except (ValueError, TypeError, KeyError):
            raise OSError("学習目標の応答を確認できませんでした。再試行してください。") from None
    path = Path(path or DB_PATH)
    if not path.exists():
        return default
    with closing(sqlite3.connect(path, timeout=10)) as db:
        # 読み取りだけで、保護者テストから新しい保存先を作りません。
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='family_learning_settings'").fetchone():
            return default
        row = db.execute("SELECT weekly_days,daily_questions FROM family_learning_settings WHERE user_id=?", (user_id,)).fetchone()
    return _goals(user_id, *row) if row else default


def save_goals(user_id, weekly_days, daily_questions, path=None, test_mode=False):
    row = _goals(user_id, weekly_days, daily_questions)
    if type(test_mode) is not bool:
        raise ValueError("テスト状態が不正です。")
    if test_mode:
        return row
    row["updated_at"] = datetime.now(JST).isoformat()
    config = learning.get_supabase_config() if path is None else None
    if config:
        url, key = config
        _cloud(Request(f"{url}/rest/v1/family_learning_settings?on_conflict=user_id",
                       data=json.dumps(row, ensure_ascii=False, allow_nan=False).encode("utf-8"),
                       headers={"apikey": key, "Content-Type": "application/json",
                                "Prefer": "resolution=merge-duplicates,return=minimal"}, method="POST"), "学習目標")
    else:
        path = Path(path or DB_PATH)
        init_db(path)
        with closing(sqlite3.connect(path, timeout=10)) as db, db:
            db.execute("INSERT INTO family_learning_settings VALUES (?,?,?,?) ON CONFLICT(user_id) "
                       "DO UPDATE SET weekly_days=excluded.weekly_days,daily_questions=excluded.daily_questions,updated_at=excluded.updated_at",
                       (user_id, weekly_days, daily_questions, row["updated_at"]))
    return {name: row[name] for name in ("user_id", "weekly_days", "daily_questions")}


def _feedback(record):
    if not isinstance(record, dict):
        raise ValueError("問題報告が不正です。")
    _learner(record.get("user_id"))
    if (not isinstance(record.get("subject"), str) or record.get("subject") not in SUBJECTS
            or not isinstance(record.get("reason"), str) or record.get("reason") not in FEEDBACK_REASONS
            or any(not isinstance(record.get(name), str) or not 1 <= len(record[name]) <= 256
                   for name in ("problem_id", "feedback_id"))):
        raise ValueError("問題報告の教科・問題・理由が不正です。")
    try:
        timestamp = datetime.fromisoformat(record["datetime"])
        if timestamp.tzinfo is None:
            raise ValueError()
    except (KeyError, TypeError, ValueError):
        raise ValueError("問題報告の日時が不正です。") from None
    return {name: record[name] for name in ("feedback_id", "user_id", "subject", "problem_id", "reason", "datetime")}


def make_feedback(user_id, subject, problem_id, reason, feedback_id=None):
    return _feedback({"feedback_id": feedback_id if feedback_id is not None else learning.new_id("feedback"),
                      "user_id": user_id, "subject": subject, "problem_id": problem_id, "reason": reason,
                      "datetime": datetime.now(JST).isoformat()})


def save_feedback(record, path=None, test_mode=False):
    row = _feedback(record)
    if type(test_mode) is not bool:
        raise ValueError("テスト状態が不正です。")
    if test_mode:
        return
    config = learning.get_supabase_config() if path is None else None
    if config:
        url, key = config
        _cloud(Request(f"{url}/rest/v1/problem_feedback?on_conflict=feedback_id",
                       data=json.dumps(row, ensure_ascii=False, allow_nan=False).encode("utf-8"),
                       headers={"apikey": key, "Content-Type": "application/json",
                                "Prefer": "resolution=ignore-duplicates,return=minimal"}, method="POST"), "問題報告")
        return
    path = Path(path or DB_PATH)
    init_db(path)
    with closing(sqlite3.connect(path, timeout=10)) as db, db:
        db.execute("INSERT INTO problem_feedback VALUES (?,?,?,?,?,?) ON CONFLICT(feedback_id) DO NOTHING",
                   tuple(row.values()))


def read_feedback(user_id, path=None):
    _learner(user_id)
    config = learning.get_supabase_config() if path is None else None
    if config:
        url, key = config
        records, offset = [], 0
        while True:
            query = urlencode({"user_id": f"eq.{user_id}", "select": "*", "order": "datetime.desc,feedback_id.desc",
                               "limit": 101, "offset": offset})
            rows = _cloud(Request(f"{url}/rest/v1/problem_feedback?{query}",
                                  headers={"apikey": key, "Accept": "application/json"}), "問題報告")
            try:
                if not isinstance(rows, list) or len(rows) > 101:
                    raise ValueError()
                rows = [_feedback(row) for row in rows]
                if any(row["user_id"] != user_id for row in rows):
                    raise ValueError()
            except (ValueError, TypeError, KeyError):
                raise OSError("問題報告の応答を確認できませんでした。再試行してください。") from None
            records.extend(rows[:100])
            if len(rows) <= 100:
                return records
            offset += 100
    path = Path(path or DB_PATH)
    if not path.exists():
        return []
    with closing(sqlite3.connect(path, timeout=10)) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='problem_feedback'").fetchone():
            return []
        db.row_factory = sqlite3.Row
        return [_feedback(dict(row)) for row in db.execute("SELECT * FROM problem_feedback WHERE user_id=? "
                                                         "ORDER BY datetime DESC,feedback_id DESC", (user_id,))]
