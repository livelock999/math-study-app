"""Lossless answer-history backups, with additive, idempotent restore.

Settings are deliberately outside this format. A restore never edits an existing
answer. SQLite restores span both files in one attached-database transaction;
cloud restores require the service-role RPC in supabase_history_restore.sql.
"""

from contextlib import closing
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request
import json
import math
import sqlite3

import learning
import japanese

FORMAT = "family-study-answer-history"
VERSION = 1
MAX_BYTES = 10 * 1024 * 1024
MAX_ROWS = 20000
BOOLEAN_COLUMNS = frozenset((
    "carry", "borrowing", "crosses_10", "zero_included", "doubles",
    "operation_selection_correct", "equation_correct", "calculation_correct",
    "is_correct", "hint_used", "dont_know_used", "retry_flag", "answer_is_10",
    "operand_contains_10", "near_10", "round_completed", "reading_help_used",
))
COUNT_KEYS = ("math_added", "japanese_added", "math_existing", "japanese_existing")


def _timestamp(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 100:
        raise ValueError("履歴の日時が不正です。")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("履歴の日時が不正です。") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("履歴の日時にはタイムゾーンが必要です。")
    return parsed.astimezone(timezone.utc).isoformat()


def _text(value, field, limit=20000):
    if not isinstance(value, str) or not value or len(value) > limit or "\x00" in value:
        raise ValueError(f"履歴の {field} が不正です。")


def _json_value(value, depth=0):
    if depth > 20:
        raise ValueError("履歴のデータ構造が深すぎます。")
    if value is None or type(value) is bool:
        return
    if type(value) in (int, float):
        if not math.isfinite(value) or abs(value) > 1e15:
            raise ValueError("履歴の数値が不正です。")
        return
    if isinstance(value, str):
        if len(value) > 100000 or "\x00" in value:
            raise ValueError("履歴の文字列が不正です。")
        return
    if isinstance(value, list):
        if len(value) > 2000:
            raise ValueError("履歴の配列が長すぎます。")
        for item in value:
            _json_value(item, depth + 1)
        return
    if isinstance(value, dict):
        if len(value) > 300 or any(not isinstance(k, str) or len(k) > 200 for k in value):
            raise ValueError("履歴の項目が不正です。")
        for item in value.values():
            _json_value(item, depth + 1)
        return
    raise ValueError("履歴にJSON以外のデータがあります。")


def _math_record(record, user_id):
    if not isinstance(record, dict) or set(record) - set(learning.COLUMNS):
        raise ValueError("算数の履歴項目が不正です。")
    normalized = {}
    for name, kind in learning.COLUMNS.items():
        required = "NOT NULL" in kind or name == "attempt_id"
        if required and (name not in record or record[name] is None):
            raise ValueError(f"算数の履歴に {name} がありません。")
        value = record.get(name)
        if value is not None:
            if name in BOOLEAN_COLUMNS:
                if type(value) not in (int, bool) or value not in (0, 1):
                    raise ValueError(f"算数の {name} が不正です。")
                value = bool(value)
            elif kind.startswith("INTEGER"):
                if type(value) is not int or not -(2**31) <= value < 2**31:
                    raise ValueError(f"算数の {name} が不正です。")
            elif kind.startswith("REAL"):
                if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                    raise ValueError(f"算数の {name} が不正です。")
                value = float(value)
            else:
                _text(value, name, 200 if name.endswith("_id") else 20000)
        normalized[name] = value
    if normalized["user_id"] != user_id:
        raise ValueError("別の学習者の履歴は復元できません。")
    _timestamp(normalized["datetime"])
    if normalized["question_order"] < 1 or normalized["attempt_count"] < 1:
        raise ValueError("算数の回答順または回答回数が不正です。")
    if normalized["hint_level"] is not None and not 0 <= normalized["hint_level"] <= 3:
        raise ValueError("算数のヒント段階が不正です。")
    if (normalized["selection_type"] not in ("normal", "weak_area", "retry", "review", "review_retry")
            or normalized["problem_format"] not in ("calculation", "word_problem")
            or normalized["operation"] not in ("addition", "subtraction")
            or normalized["number_range"] not in (10, 20)):
        raise ValueError("算数の問題設定が不正です。")
    left, right, limit = normalized["left_operand"], normalized["right_operand"], normalized["number_range"]
    expected = left + right if normalized["operation"] == "addition" else left - right
    if not (0 <= left <= limit and 0 <= right <= limit and 0 <= expected <= limit and normalized["correct_answer"] == expected):
        raise ValueError("算数の数量または正しい答えが不正です。")
    if normalized["user_answer"] is not None and not 0 <= normalized["user_answer"] <= 99:
        raise ValueError("算数の回答は0〜99の整数です。")
    if normalized["round_size"] is not None and (normalized["round_size"] < normalized["question_order"] or normalized["round_size"] < 1):
        raise ValueError("算数のセット問題数が不正です。")
    return normalized


def _japanese_record(record, user_id):
    if not isinstance(record, dict):
        raise ValueError("国語の履歴が不正です。")
    _json_value(record)
    for name in ("attempt_id", "user_id", "session_id", "datetime", "chain_id",
                 "question_id", "category", "problem_format", "selection_type"):
        _text(record.get(name), name, 200)
    if record["user_id"] != user_id or record.get("learner_id", user_id) != user_id:
        raise ValueError("別の学習者の履歴は復元できません。")
    _timestamp(record["datetime"])
    for field in ("answered_at", "review_due_at"):
        if record.get(field) is not None:
            _timestamp(record[field])
    for field in ("question_order", "attempt_count"):
        if type(record.get(field)) is not int or record[field] < 1:
            raise ValueError("国語の回答順または回答回数が不正です。")
    if type(record.get("correct")) is not bool:
        raise ValueError("国語の正誤が不正です。")
    seconds = record.get("response_time_sec")
    if type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds < 0:
        raise ValueError("国語の回答時間が不正です。")
    for field in ("hint_used", "reading_help_used", "dont_know_used", "retry_flag", "final_correct"):
        if record.get(field) is not None and type(record[field]) is not bool:
            raise ValueError(f"国語の {field} が不正です。")
    if record.get("hint_level") is not None and (type(record["hint_level"]) is not int or not 0 <= record["hint_level"] <= 3):
        raise ValueError("国語のヒント段階が不正です。")
    for field in ("text", "question", "hint", "explanation", "selected_answer_text"):
        # An empty passage is valid for vocabulary/particle questions.
        if field not in record or not isinstance(record[field], str):
            raise ValueError(f"国語の {field} がありません。")
    choices = record.get("choices")
    if not isinstance(choices, list) or not 2 <= len(choices) <= 20 or any(not isinstance(s, str) for s in choices):
        raise ValueError("国語の選択肢が不正です。")
    if "answer" not in record or "selected_answer" not in record:
        raise ValueError("国語の回答がありません。")
    if (record["selection_type"] not in ("normal", "weak_area", "retry", "review", "review_retry")
            or record["category"] not in japanese.CATEGORIES
            or record["problem_format"] not in ("choice", "ordering", "particle_choice")
            or record.get("reading_mode") not in ("self_read", "audio")):
        raise ValueError("国語の問題設定が不正です。")
    for field, valid in (("reasoning_level", range(1, 5)), ("difficulty", range(1, 4))):
        if type(record.get(field)) is not int or record[field] not in valid:
            raise ValueError(f"国語の {field} が不正です。")
    if type(record.get("version")) is not int or record["version"] < 1:
        raise ValueError("国語の問題版が不正です。")
    if record.get("question_word") not in japanese.QUESTION_LABELS:
        raise ValueError("国語の問いの種類が不正です。")
    for field in ("skill_tags", "error_cause_tags"):
        if (not isinstance(record.get(field), list) or any(not isinstance(tag, str) or not tag for tag in record[field])
                or (field == "skill_tags" and not record[field])):
            raise ValueError(f"国語の {field} が不正です。")
    errors = record.get("error_tags")
    if (not isinstance(errors, dict) or any(not isinstance(tags, list) or any(not isinstance(tag, str) for tag in tags) for tags in errors.values())):
        raise ValueError("国語の誤答分類が不正です。")
    answer, selected = record["answer"], record["selected_answer"]
    unknown = record.get("dont_know_used") is True
    if record["problem_format"] == "ordering":
        valid_order = lambda indices: isinstance(indices, list) and len(indices) == len(choices) and all(type(i) is int for i in indices) and sorted(indices) == list(range(len(choices)))
        if not valid_order(answer) or (not unknown and not valid_order(selected)) or (unknown and selected is not None):
            raise ValueError("国語の並べ替え回答が不正です。")
        actual_correct = not unknown and selected == answer
    else:
        if type(answer) is not int or not 0 <= answer < len(choices):
            raise ValueError("国語の正解番号が不正です。")
        if record["category"] == "particles":
            index = record.get("selected_answer_index")
            if (not unknown and (type(index) is not int or not 0 <= index < len(choices) or selected != choices[index])) or (unknown and (index is not None or selected != "わからない")):
                raise ValueError("国語の助詞回答が不正です。")
            if record.get("correct_answer") != choices[answer]:
                raise ValueError("国語の助詞の正しい答えが不正です。")
            if type(record.get("first_try_correct")) is not bool:
                raise ValueError("国語の助詞の初回正誤が不正です。")
            actual_correct = not unknown and index == answer
        else:
            if (not unknown and (type(selected) is not int or not 0 <= selected < len(choices))) or (unknown and selected is not None):
                raise ValueError("国語の選択回答が不正です。")
            actual_correct = not unknown and selected == answer
    if record["correct"] != actual_correct:
        raise ValueError("国語の回答と正誤が一致しません。")
    # Copy through JSON so callers cannot mutate the validated backup afterwards.
    return json.loads(json.dumps(record, ensure_ascii=False, allow_nan=False))


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _checksum(backup):
    return sha256(_canonical({k: v for k, v in backup.items() if k != "checksum"})).hexdigest()


def _validate_backup(backup, user_id):
    if user_id not in learning.USERS:
        raise ValueError("学習者が不正です。")
    if (not isinstance(backup, dict) or set(backup) != {"format", "version", "user_id", "created_at", "math", "japanese", "checksum"}
            or backup.get("format") != FORMAT or type(backup.get("version")) is not int or backup["version"] != VERSION):
        raise ValueError("対応していないバックアップ形式です。CSVは復元に使えません。")
    if backup["user_id"] != user_id:
        raise ValueError("選択中の学習者とバックアップの学習者が違います。")
    _timestamp(backup["created_at"])
    if any(not isinstance(backup[name], list) for name in ("math", "japanese")):
        raise ValueError("バックアップの履歴一覧が不正です。")
    if len(backup["math"]) + len(backup["japanese"]) > MAX_ROWS:
        raise ValueError("一度に復元できる履歴は20000件までです。")
    if (not isinstance(backup["checksum"], str) or len(backup["checksum"]) != 64
            or backup["checksum"] != _checksum(backup)):
        raise ValueError("バックアップのチェックサムが一致しません。元のファイルを選んでください。")
    normalized = {**backup, "math": [_math_record(row, user_id) for row in backup["math"]],
                  "japanese": [_japanese_record(row, user_id) for row in backup["japanese"]]}
    for name in ("math", "japanese"):
        ids = [row["attempt_id"] for row in normalized[name]]
        if len(set(ids)) != len(ids):
            raise ValueError("バックアップ内で回答IDが重複しています。")
    normalized["checksum"] = _checksum(normalized)
    if len(_canonical(normalized)) > MAX_BYTES:
        raise ValueError("バックアップは10MBまでです。")
    return normalized


def export_backup(user_id, math_records, japanese_records, now=None):
    """Return versioned UTF-8 JSON, preserving timestamps and complete JP payloads."""
    now = now or datetime.now(timezone.utc)
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise ValueError("作成日時が不正です。")
    backup = {"format": FORMAT, "version": VERSION, "user_id": user_id,
              "created_at": now.isoformat(), "math": list(math_records), "japanese": list(japanese_records)}
    backup["checksum"] = _checksum(backup)
    return _canonical(_validate_backup(backup, user_id))


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("JSONに同じ項目名が重複しています。")
        result[key] = value
    return result


def parse_backup(data, user_id):
    if not isinstance(data, (bytes, bytearray)) or len(data) > MAX_BYTES:
        raise ValueError("バックアップは10MB以下のJSONファイルを選んでください。")
    try:
        backup = json.loads(bytes(data).decode("utf-8-sig"), object_pairs_hook=_unique_object,
                            parse_constant=lambda _: (_ for _ in ()).throw(ValueError("不正な数値です。")))
        return _validate_backup(backup, user_id)
    except (UnicodeError, json.JSONDecodeError, RecursionError, OverflowError):
        raise ValueError("バックアップのJSONを読み込めません。") from None


def _comparable(record, subject):
    if subject == "math":
        record = _math_record(record, record.get("user_id"))
    value = dict(record)
    for field in (("datetime",) if subject == "math" else ("datetime", "answered_at", "review_due_at")):
        if value.get(field) is not None:
            value[field] = _timestamp(value[field])
    if subject == "japanese":
        value = _numeric_json(value)
    return _canonical(value)


def _numeric_json(value):
    """JSONB considers 2 and 2.0 equal, while true remains distinct from 1."""
    if type(value) is float and value.is_integer():
        return int(value)
    if isinstance(value, list):
        return [_numeric_json(item) for item in value]
    if isinstance(value, dict):
        return {key: _numeric_json(item) for key, item in value.items()}
    return value


def _counts(backup, existing_math, existing_japanese):
    counts = {}
    for subject, records in (("math", existing_math), ("japanese", existing_japanese)):
        by_id = {}
        for row in records:
            if not isinstance(row, dict) or not isinstance(row.get("attempt_id"), str):
                raise ValueError("現在の履歴が不正です。復元を停止しました。")
            if row["attempt_id"] in by_id:
                raise ValueError("現在の履歴で回答IDが重複しています。")
            by_id[row["attempt_id"]] = row
        duplicate = 0
        for row in backup[subject]:
            previous = by_id.get(row["attempt_id"])
            if previous is not None:
                if previous.get("user_id") != backup["user_id"] or _comparable(previous, subject) != _comparable(row, subject):
                    raise ValueError("同じ回答IDの内容が異なるため復元できません。現在の履歴は変更しません。")
                duplicate += 1
        counts[f"{subject}_added"] = len(backup[subject]) - duplicate
        counts[f"{subject}_existing"] = duplicate
    return counts


def preview_backup(backup, existing_math, existing_japanese):
    validated = _validate_backup(backup, backup.get("user_id") if isinstance(backup, dict) else None)
    return _counts(validated, existing_math, existing_japanese)


def _restore_local(backup, math_path, japanese_path):
    paths = [Path(math_path).resolve(), Path(japanese_path).resolve()]
    if paths[0] == paths[1] or any(not path.is_file() for path in paths):
        raise ValueError("初期化済みの算数・国語の保存先を確認してください。")
    with closing(sqlite3.connect(paths[0].as_uri() + "?mode=rw", uri=True, timeout=15)) as db:
        db.execute("ATTACH DATABASE ? AS jp_store", (paths[1].as_uri() + "?mode=rw",))
        # A file-backed main DB + DELETE journals allow SQLite's super-journal
        # to commit/rollback the attached databases together, including crashes.
        for schema in ("main", "jp_store"):
            mode = db.execute(f"PRAGMA {schema}.journal_mode").fetchone()[0]
            if mode.lower() != "delete":
                raise ValueError("一括復元には両DBのDELETEジャーナルが必要です。WAL等の設定を確認してください。")
            db.execute(f"PRAGMA {schema}.synchronous=FULL")
        db.row_factory = sqlite3.Row
        try:
            db.execute("BEGIN IMMEDIATE")
            existing_math, existing_japanese = [], []
            # Recheck globally under the write lock, including other learners.
            for subject, table, fields in (("math", "main.attempts", "*"),
                                            ("japanese", "jp_store.japanese_attempts", "*")):
                target = existing_math if subject == "math" else existing_japanese
                for candidate in backup[subject]:
                    found = db.execute(f"SELECT {fields} FROM {table} WHERE attempt_id = ?", (candidate["attempt_id"],)).fetchone()
                    if found is None:
                        continue
                    row = dict(found)
                    if subject == "japanese":
                        payload = json.loads(row["payload"], object_pairs_hook=_unique_object)
                        if (any(row[key] != payload.get(key) for key in ("attempt_id", "user_id", "session_id"))
                                or _timestamp(row["datetime"]) != _timestamp(payload.get("datetime"))):
                            raise ValueError("現在の国語履歴と保存行の内容が一致しません。")
                        row = payload
                    target.append(row)
            counts = _counts(backup, existing_math, existing_japanese)
            names = list(learning.COLUMNS)
            for row in backup["math"]:
                db.execute(f"INSERT INTO main.attempts ({', '.join(names)}) VALUES ({', '.join('?' for _ in names)}) ON CONFLICT(attempt_id) DO NOTHING",
                           [row[name] for name in names])
            for row in backup["japanese"]:
                db.execute("INSERT INTO jp_store.japanese_attempts (attempt_id,user_id,session_id,datetime,payload) VALUES (?,?,?,?,?) ON CONFLICT(attempt_id) DO NOTHING",
                           (*[row[name] for name in ("attempt_id", "user_id", "session_id", "datetime")], _canonical(row).decode("utf-8")))
            db.commit()
            return counts
        except BaseException:
            db.rollback()
            raise


def restore_backup(backup, test_mode=False, math_path=None, japanese_path=None):
    """Restore new IDs only; test mode does not read/initialize/write any store."""
    if type(test_mode) is not bool:
        raise ValueError("テスト状態が不正です。")
    validated = _validate_backup(backup, backup.get("user_id") if isinstance(backup, dict) else None)
    if test_mode:
        return {**_counts(validated, [], []), "test_mode": True}
    if (math_path is None) != (japanese_path is None):
        raise ValueError("算数と国語の保存先は両方を指定してください。")
    config = learning.get_supabase_config() if math_path is None else None
    if config is None:
        return _restore_local(validated, math_path or learning.DB_PATH, japanese_path or japanese.DB_PATH)
    url, key = config
    # The RPC owns one transaction. Never fall back to local writes after a
    # timeout: an uncertain server commit is retried with the same answer IDs.
    request = Request(f"{url}/rest/v1/rpc/restore_answer_history",
                      data=_canonical({"backup": validated}),
                      headers={"apikey": key, "Content-Type": "application/json"}, method="POST")
    try:
        with learning.supabase_urlopen(request, timeout=30) as response:
            if not 200 <= response.status < 300:
                raise OSError()
            counts = json.loads(response.read().decode("utf-8"))
        if (not isinstance(counts, dict) or set(counts) != set(COUNT_KEYS)
                or any(type(counts.get(name)) is not int or counts[name] < 0 for name in COUNT_KEYS)
                or counts["math_added"] + counts["math_existing"] != len(validated["math"])
                or counts["japanese_added"] + counts["japanese_existing"] != len(validated["japanese"])):
            raise ValueError()
        return counts
    except (HTTPError, URLError, TimeoutError, OSError, ValueError, UnicodeError):
        raise OSError("クラウドの復元を確認できませんでした。接続と supabase_history_restore.sql の適用を確認し、同じファイルで再試行してください。") from None
