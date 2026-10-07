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
from urllib.parse import urlencode, urlsplit
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
    "round_size": "INTEGER", "round_completed": "INTEGER",
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


def problem_pool(operation, limit, special="auto"):
    """繰り上がり・繰り下がりの条件に合う、重複のない問題候補。"""
    if operation not in ("addition", "subtraction") or limit not in (10, 20) or special not in ("auto", "none", "with"):
        raise ValueError("学習条件が不正です")
    problems = []
    for left in range(limit + 1):
        for right in range(limit + 1):
            if (left + right > limit if operation == "addition" else right > left):
                continue
            problem = make_problem(operation, limit, left, right)
            attribute = problem["carry"] if operation == "addition" else problem["borrowing"]
            if special == "auto" or attribute == (special == "with"):
                problems.append(problem)
    return problems


def selection_error(mode, limit, count=10, special="auto"):
    """開始できない条件なら理由を返します。問題を無理に重複させません。"""
    if mode not in ("addition", "subtraction", "mix") or type(count) is not int or count < 1:
        return "学習モードまたは問題数が不正です。"
    needs = {"addition": (count + 1) // 2, "subtraction": count // 2} if mode == "mix" else {mode: count}
    for operation, needed in needs.items():
        available = len(problem_pool(operation, limit, special))
        if available < needed:
            name = "たしざん" if operation == "addition" else "ひきざん"
            return f"この条件の{name}は{available}問です。必要な{needed}問に足りないため、問題数や条件を変えてください。"
    return None


def generate_problems(mode, limit, count=10, special="auto"):
    """同じセットに重複を出さず、ミックスでは両演算を半数ずつ出します。"""
    error = selection_error(mode, limit, count, special)
    if error:
        raise ValueError(error)
    pools = {operation: problem_pool(operation, limit, special) for operation in ("addition", "subtraction")}
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
        existing = {row[1] for row in connection.execute("PRAGMA table_info(attempts)")}
        for name in ("round_size", "round_completed"):
            if name not in existing:
                connection.execute(f"ALTER TABLE attempts ADD COLUMN {name} INTEGER")
        connection.execute("CREATE INDEX IF NOT EXISTS user_sessions ON attempts(user_id, session_id)")


def make_attempt(problem, user_id, session_id, order, selection, answer, seconds, count, round_size=None):
    if round_size is not None and (type(round_size) is not int or round_size < 1 or not 1 <= order <= round_size):
        raise ValueError("セットの問題数または出題順が不正です")
    record = dict(problem)
    record.update(
        attempt_id=new_id("attempt"), user_id=user_id, session_id=session_id,
        datetime=datetime.now(timezone(timedelta(hours=9))).isoformat(),
        question_order=order, selection_type=selection, user_answer=answer,
        is_correct=answer == problem["correct_answer"],
        calculation_correct=answer == problem["correct_answer"],
        response_time_sec=round(max(0, seconds), 3), attempt_count=count,
        hint_used=False, dont_know_used=False, retry_flag=selection == "retry",
        round_size=round_size, round_completed=(order == round_size) if round_size is not None else None,
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


def read_attempts(user_id, page=0, page_size=50, path=None, start_at=None, end_at=None):
    """選択した学習者の履歴を最新順に読み、次ページの有無も返します。"""
    if not isinstance(user_id, str) or user_id not in USERS:
        raise ValueError("学習者が不正です。")
    if type(page) is not int or page < 0 or type(page_size) is not int or not 1 <= page_size <= 100:
        raise ValueError("履歴のページ指定が不正です。")
    limit, offset = page_size + 1, page * page_size
    if start_at is not None or end_at is not None:
        if (not isinstance(start_at, datetime) or not isinstance(end_at, datetime)
                or start_at.tzinfo is None or end_at.tzinfo is None or start_at >= end_at):
            raise ValueError("履歴の期間指定が不正です。")
        start_at, end_at = start_at.astimezone(timezone.utc), end_at.astimezone(timezone.utc)
    if path is None:
        config = get_supabase_config()
        if config is not None:
            url, key = config
            filters = [("select", "*"), ("user_id", f"eq.{user_id}"),
                       ("order", "datetime.desc,attempt_id.desc"), ("limit", limit), ("offset", offset)]
            if start_at is not None:
                filters.extend([("datetime", f"gte.{start_at.isoformat()}"), ("datetime", f"lt.{end_at.isoformat()}")])
            query = urlencode(filters)
            request = Request(f"{url}/rest/v1/math_attempts?{query}",
                              headers={"apikey": key, "Accept": "application/json"}, method="GET")
            try:
                with supabase_urlopen(request, timeout=15) as response:
                    if not 200 <= response.status < 300:
                        raise OSError("履歴を読み込めませんでした。")
                    rows = json.loads(response.read().decode("utf-8"))
                if (not isinstance(rows, list) or len(rows) > limit
                        or any(not isinstance(row, dict) or row.get("user_id") != user_id
                               or not set(COLUMNS).issubset(row) for row in rows)):
                    raise ValueError("履歴の応答が不正です。")
                if start_at is not None and any(not start_at <= datetime.fromisoformat(row["datetime"]) < end_at for row in rows):
                    raise ValueError("対象期間外の履歴です。")
            except (HTTPError, URLError, OSError, ValueError, TypeError):
                raise OSError("クラウドの履歴を読み込めませんでした。接続と保存先設定を確認してください。") from None
            return rows[:page_size], len(rows) > page_size
        path = DB_PATH
    with closing(sqlite3.connect(path, timeout=10)) as connection:
        connection.row_factory = sqlite3.Row
        period = " AND julianday(datetime) >= julianday(?) AND julianday(datetime) < julianday(?)" if start_at is not None else ""
        parameters = [user_id]
        if start_at is not None:
            parameters.extend([start_at.isoformat(), end_at.isoformat()])
        parameters.extend([limit, offset])
        rows = [dict(row) for row in connection.execute(
            f"SELECT * FROM attempts WHERE user_id = ?{period} ORDER BY datetime DESC, attempt_id DESC LIMIT ? OFFSET ?",
            parameters,
        )]
    return rows[:page_size], len(rows) > page_size


def read_month_attempts(user_id, year, month, path=None):
    """日本時間の対象月だけを、ページを最後まで読み切って取得します。"""
    if type(year) is not int or type(month) is not int or not 1 <= year <= 9998 or not 1 <= month <= 12:
        raise ValueError("対象月が不正です。")
    jst = timezone(timedelta(hours=9))
    start = datetime(year, month, 1, tzinfo=jst)
    end = datetime(year + (month == 12), 1 if month == 12 else month + 1, 1, tzinfo=jst)
    records, page = [], 0
    while True:
        batch, has_more = read_attempts(user_id, page=page, page_size=100, path=path, start_at=start, end_at=end)
        records.extend(batch)
        if not has_more:
            return records
        page += 1
