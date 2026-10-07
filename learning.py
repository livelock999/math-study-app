"""問題生成と保存。画面に依存しない、小さな関数をまとめます。"""

from datetime import datetime, timezone, timedelta
from contextlib import closing
from pathlib import Path
import random
import sqlite3
import uuid
import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

DB_PATH = Path(__file__).parent / "data" / "history.sqlite3"
USERS = {"user_001": "なっちゃん", "user_002": "りっちゃん"}


class NoRedirect(HTTPRedirectHandler):
    """保存先からの転送先へ秘密キーを送らないようにします。"""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


supabase_urlopen = build_opener(NoRedirect).open


def get_supabase_config():
    """環境変数を優先し、次に Streamlit Secrets を読みます。"""
    import streamlit as st

    values = []
    for name in ("SUPABASE_URL", "SUPABASE_SECRET_KEY"):
        value = os.environ.get(name)
        if value is None:
            try:
                value = st.secrets.get(name)
            except KeyError:
                value = None
            except FileNotFoundError as error:
                if type(error) is FileNotFoundError or str(error).startswith("No secrets found"):
                    value = None
                else:
                    raise ValueError("Secrets 設定を読み込めません。secrets.toml の形式を確認してください。") from None
        values.append(value)
    url, key = values
    if url is None and key is None:
        return None
    if not isinstance(url, str) or not isinstance(key, str) or not url.strip() or not key.strip():
        raise ValueError("SUPABASE_URL と SUPABASE_SECRET_KEY の両方を設定してください。")
    url, key = url.strip().rstrip("/"), key.strip()
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.path or parsed.query or parsed.fragment):
        raise ValueError("SUPABASE_URL には https:// で始まるプロジェクトURLを設定してください。")
    if not key.startswith("sb_secret_"):
        raise ValueError("SUPABASE_SECRET_KEY には sb_secret_ で始まるサーバー用の鍵を設定してください。")
    return url, key

# 未実装機能の値も保持します。boolean は SQLite では 0/1/NULL です。
COLUMNS = {
    "attempt_id": "TEXT PRIMARY KEY", "user_id": "TEXT NOT NULL",
    "session_id": "TEXT NOT NULL", "datetime": "TEXT NOT NULL",
    "problem_id": "TEXT NOT NULL", "question_order": "INTEGER NOT NULL",
    "selection_type": "TEXT NOT NULL", "problem_format": "TEXT NOT NULL",
    "operation": "TEXT NOT NULL", "number_range": "INTEGER NOT NULL",
    "left_operand": "INTEGER NOT NULL", "right_operand": "INTEGER NOT NULL",
    "carry": "INTEGER", "borrowing": "INTEGER", "crosses_10": "INTEGER",
    "zero_included": "INTEGER", "doubles": "INTEGER", "blank_position": "TEXT",
    "story_type": "TEXT", "unknown_type": "TEXT",
    "operation_selection_correct": "INTEGER", "equation_correct": "INTEGER",
    "calculation_correct": "INTEGER", "question_text": "TEXT NOT NULL",
    "correct_answer": "INTEGER NOT NULL", "user_answer": "INTEGER",
    "is_correct": "INTEGER NOT NULL", "response_time_sec": "REAL NOT NULL",
    "attempt_count": "INTEGER NOT NULL", "hint_used": "INTEGER",
    "dont_know_used": "INTEGER", "retry_flag": "INTEGER",
    "answer_is_10": "INTEGER", "operand_contains_10": "INTEGER",
    "near_10": "INTEGER", "commutative_pair": "TEXT",
}


def new_id(prefix):
    return f"{prefix}_{uuid.uuid4().hex}"


def make_problem(operation, limit, left, right):
    addition = operation == "addition"
    answer = left + right if addition else left - right
    return {
        "problem_id": f"calculation_{operation}_{limit}_{left}_{right}",
        "problem_format": "calculation", "operation": operation,
        "number_range": limit, "left_operand": left, "right_operand": right,
        "question_text": f"{left} {'+' if addition else '−'} {right} = ?",
        "correct_answer": answer,
        "carry": (left % 10 + right % 10 >= 10) if addition else None,
        "borrowing": (left % 10 < right % 10) if not addition else None,
        "crosses_10": (left < 10 and right < 10 and answer > 10) if addition
                      else (left > 10 and answer < 10),
        "zero_included": left == 0 or right == 0,
        "doubles": addition and left == right, "blank_position": "answer",
        "story_type": None, "unknown_type": None,
        "operation_selection_correct": None, "equation_correct": None,
        "answer_is_10": answer == 10, "operand_contains_10": 10 in (left, right),
        "near_10": addition and (8 in (left, right) or 9 in (left, right))
                   and answer > 10,
        "commutative_pair": f"addition_{min(left, right)}_{max(left, right)}"
                            if addition else None,
    }


def generate_problems(mode, limit, count=10):
    """同じセットに重複を出さず、ミックスでは両演算を半数ずつ出します。"""
    if mode not in ("addition", "subtraction", "mix") or limit not in (10, 20):
        raise ValueError("学習モードまたは数の範囲が不正です")
    pools = {}
    for operation in ("addition", "subtraction"):
        pools[operation] = [
            make_problem(operation, limit, left, right)
            for left in range(limit + 1) for right in range(limit + 1)
            if (left + right <= limit if operation == "addition" else right <= left)
        ]
    if mode == "mix":
        problems = random.sample(pools["addition"], (count + 1) // 2)
        problems += random.sample(pools["subtraction"], count // 2)
    else:
        problems = random.sample(pools[mode], count)
    random.shuffle(problems)
    return problems


def init_db(path=None):
    # 明示的な path はテスト用のローカルDB。通常は設定で保存先を選びます。
    if path is None:
        if get_supabase_config() is not None:
            return
        path = DB_PATH
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as connection, connection:
        definitions = ", ".join(f'"{name}" {kind}' for name, kind in COLUMNS.items())
        connection.execute(f"CREATE TABLE IF NOT EXISTS attempts ({definitions})")
        connection.execute("CREATE INDEX IF NOT EXISTS user_sessions ON attempts(user_id, session_id)")


def make_attempt(problem, user_id, session_id, order, selection, answer, seconds, count):
    record = dict(problem)
    record.update(
        attempt_id=new_id("attempt"), user_id=user_id, session_id=session_id,
        datetime=datetime.now(timezone(timedelta(hours=9))).isoformat(),
        question_order=order, selection_type=selection, user_answer=answer,
        is_correct=answer == problem["correct_answer"],
        calculation_correct=answer == problem["correct_answer"],
        response_time_sec=round(max(0, seconds), 3), attempt_count=count,
        hint_used=False, dont_know_used=False, retry_flag=selection == "retry",
    )
    return record


def save_attempt(record, path=None):
    """回答ごとにコミット。同じ attempt_id の再送だけ重複を防ぎます。"""
    names = list(COLUMNS)
    if path is None:
        config = get_supabase_config()
        if config is not None:
            url, key = config
            request = Request(
                f"{url}/rest/v1/math_attempts?on_conflict=attempt_id",
                data=json.dumps({name: record[name] for name in names}, ensure_ascii=False,
                                allow_nan=False).encode("utf-8"),
                headers={"apikey": key, "Content-Type": "application/json",
                         "Prefer": "resolution=ignore-duplicates,return=minimal"},
                method="POST",
            )
            try:
                with supabase_urlopen(request, timeout=15) as response:
                    if not 200 <= response.status < 300:
                        raise OSError("クラウドへ履歴を保存できませんでした。")
            except (HTTPError, URLError, TimeoutError, OSError):
                # 応答本文や秘密キーを画面に出さず、未保存の回答を再試行できます。
                raise OSError("クラウドへ履歴を保存できませんでした。接続と保存先設定を確認してください。") from None
            return
        path = DB_PATH
    with closing(sqlite3.connect(path, timeout=10)) as connection, connection:
        connection.execute(
            f"INSERT INTO attempts ({', '.join(names)}) VALUES ({', '.join('?' for _ in names)}) "
            "ON CONFLICT(attempt_id) DO NOTHING",
            [record[name] for name in names],
        )
