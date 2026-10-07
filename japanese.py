"""国語の出題・回答保存・集計。算数の履歴とは別のテーブルを使います。"""

from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean
from collections import Counter
import json
import math
import random
import sqlite3
from urllib.request import Request
from urllib.parse import urlencode
from urllib.error import HTTPError, URLError

import learning
from japanese_questions import QUESTIONS, CATEGORIES, TAG_LABELS, QUESTION_LABELS, ERROR_LABELS

JST = timezone(timedelta(hours=9))
DB_PATH = Path(__file__).parent / "data" / "japanese.sqlite3"


def choose_questions(category="mix", count=10, weak_categories=None):
    if category not in (*CATEGORIES, "mix") or count not in (5, 10):
        raise ValueError("国語の出題設定が不正です。")
    pool = [q for q in QUESTIONS if category == "mix" or q["category"] == category]
    if weak_categories:
        preferred = [q for q in pool if q["category"] in weak_categories]
        if preferred:
            pool = preferred
    return random.sample(pool, min(count, len(pool)))


def validate_answer(question, answer):
    size = len(question["choices"])
    if question["problem_format"] == "ordering":
        return (isinstance(answer, list) and len(answer) == size
                and all(type(i) is int for i in answer) and sorted(answer) == list(range(size)))
    return type(answer) is int and 0 <= answer < size


def answer_text(question, answer):
    if question["problem_format"] == "ordering":
        return " → ".join(question["choices"][i] for i in answer)
    return question["choices"][answer]


def make_record(question, user_id, session_id, order, selection, answer, seconds, attempt_count,
                chain_id, hint_used=False, reading_mode="self_read"):
    if user_id not in learning.USERS or not validate_answer(question, answer):
        raise ValueError("学習者または回答が不正です。")
    if (type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds < 0
            or type(attempt_count) is not int or attempt_count < 1 or type(hint_used) is not bool
            or selection not in ("normal", "weak_area", "retry") or reading_mode not in ("self_read", "audio")):
        raise ValueError("回答の記録が不正です。")
    correct = answer == question["answer"]
    error_key = "ordering" if question["problem_format"] == "ordering" else str(answer)
    return {**question, "attempt_id": learning.new_id("jp_attempt"), "user_id": user_id,
            "session_id": session_id, "chain_id": chain_id, "question_order": order,
            "selection_type": selection, "selected_answer": answer,
            "selected_answer_text": answer_text(question, answer), "correct": correct,
            "datetime": datetime.now(JST).isoformat(), "response_time_sec": round(seconds, 3),
            "attempt_count": attempt_count, "hint_used": hint_used, "reading_mode": reading_mode,
            "retry_flag": selection == "retry", "final_correct": correct,
            "error_cause_tags": [] if correct else question["error_tags"].get(error_key, []),
            "review_due_at": None if correct else (datetime.now(JST) + timedelta(days=1)).isoformat()}


def init_db(path=None):
    if path is None:
        if learning.get_supabase_config() is not None:
            return
        path = DB_PATH
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("CREATE TABLE IF NOT EXISTS japanese_attempts "
                   "(attempt_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, session_id TEXT NOT NULL, "
                   "datetime TEXT NOT NULL, payload TEXT NOT NULL)")
        db.execute("CREATE INDEX IF NOT EXISTS japanese_user_date ON japanese_attempts(user_id, datetime)")


def save_record(record, path=None):
    payload = json.dumps(record, ensure_ascii=False, allow_nan=False)
    if path is None:
        config = learning.get_supabase_config()
        if config is not None:
            url, key = config
            row = {name: record[name] for name in ("attempt_id", "user_id", "session_id", "datetime")}
            row["payload"] = record
            request = Request(f"{url}/rest/v1/japanese_attempts?on_conflict=attempt_id",
                              data=json.dumps(row, ensure_ascii=False, allow_nan=False).encode("utf-8"),
                              headers={"apikey": key, "Content-Type": "application/json",
                                       "Prefer": "resolution=ignore-duplicates,return=minimal"}, method="POST")
            try:
                with learning.supabase_urlopen(request, timeout=15) as response:
                    if not 200 <= response.status < 300:
                        raise OSError()
            except (HTTPError, URLError, OSError):
                raise OSError("国語の回答をクラウドに保存できませんでした。") from None
            return
        path = DB_PATH
    with closing(sqlite3.connect(path, timeout=10)) as db, db:
        db.execute("INSERT INTO japanese_attempts VALUES (?, ?, ?, ?, ?) ON CONFLICT(attempt_id) DO NOTHING",
                   (record["attempt_id"], record["user_id"], record["session_id"], record["datetime"], payload))


def read_records(user_id, page=0, page_size=100, path=None):
    if (user_id not in learning.USERS or type(page) is not int or page < 0
            or type(page_size) is not int or not 1 <= page_size <= 100):
        raise ValueError("履歴の指定が不正です。")
    if path is None:
        config = learning.get_supabase_config()
        if config is not None:
            url, key = config
            query = urlencode({"select": "*", "user_id": f"eq.{user_id}",
                               "order": "datetime.desc,attempt_id.desc", "offset": page * page_size,
                               "limit": page_size + 1})
            request = Request(f"{url}/rest/v1/japanese_attempts?{query}",
                              headers={"apikey": key, "Accept": "application/json"})
            try:
                with learning.supabase_urlopen(request, timeout=15) as response:
                    if not 200 <= response.status < 300:
                        raise OSError()
                    rows = json.loads(response.read().decode("utf-8"))
                if not isinstance(rows, list) or len(rows) > page_size + 1:
                    raise ValueError()
                records = []
                for row in rows:
                    payload = row["payload"]
                    if not isinstance(payload, dict) or any(row[name] != payload[name] for name in
                            ("attempt_id", "user_id", "session_id")) or row["user_id"] != user_id:
                        raise ValueError()
                    if datetime.fromisoformat(row["datetime"]) != datetime.fromisoformat(payload["datetime"]):
                        raise ValueError()
                    records.append(payload)
            except (HTTPError, URLError, OSError, ValueError, TypeError, KeyError):
                raise OSError("国語の履歴をクラウドから読み込めませんでした。") from None
            return records[:page_size], len(records) > page_size
        path = DB_PATH
    with closing(sqlite3.connect(path, timeout=10)) as db:
        rows = db.execute("SELECT payload FROM japanese_attempts WHERE user_id = ? "
                          "ORDER BY datetime DESC, attempt_id DESC LIMIT ? OFFSET ?",
                          (user_id, page_size + 1, page * page_size)).fetchall()
    return [json.loads(row[0]) for row in rows[:page_size]], len(rows) > page_size


def read_all(user_id, path=None):
    records, page = [], 0
    while True:
        batch, more = read_records(user_id, page=page, path=path)
        records.extend(batch)
        if not more:
            return records
        page += 1


def metrics(records):
    initial = [r for r in records if r["attempt_count"] == 1]
    chains = {}
    for row in sorted(records, key=lambda r: (r["attempt_count"], r["datetime"], r["attempt_id"])):
        chains.setdefault(row["chain_id"], []).append(row)
    retried = [rows for rows in chains.values() if len(rows) > 1 and not rows[0]["correct"]]
    error_counts = Counter(tag for row in initial for tag in row["error_cause_tags"])
    return {"total": len(records), "correct": sum(r["correct"] for r in records),
            "count": len(initial), "initial_correct": sum(r["correct"] for r in initial),
            "rate": mean(r["correct"] for r in initial) if initial else None,
            "seconds": mean(r["response_time_sec"] for r in initial) if initial else None,
            "correct_seconds": mean([r["response_time_sec"] for r in initial if r["correct"]])
                               if any(r["correct"] for r in initial) else None,
            "hint_rate": mean(r["hint_used"] for r in initial) if initial else None,
            "retry_count": len(retried), "retry_success": sum(rows[-1]["correct"] for rows in retried),
            "eventual_correct": sum(rows[-1]["correct"] for rows in chains.values()),
            "chains": len(chains), "error_counts": dict(error_counts)}


def analyze(records, now=None, reading_mode="self_read"):
    now = now or datetime.now(JST)
    selected = [r for r in records if r["reading_mode"] == reading_mode]
    summary = metrics(selected)
    correct_times = [r["response_time_sec"] for r in selected if r["attempt_count"] == 1 and r["correct"]]
    baseline = mean(correct_times) if correct_times else None

    def grouped(field, labels, multiple=False):
        buckets = {}
        for row in selected:
            keys = row[field] if multiple else [row[field]]
            for key in keys:
                buckets.setdefault(key, []).append(row)
        result = []
        for key, rows in sorted(buckets.items(), key=lambda item: str(item[0])):
            stat = metrics(rows)
            signals = []
            if stat["count"] < 5:
                status = "判断保留（5問未満）"
            else:
                rank = 3 if stat["rate"] >= .9 else 2 if stat["rate"] >= .8 else 1 if stat["rate"] >= .6 else 0
                if stat["rate"] < .8:
                    signals.append("初回の誤答が多い")
                if stat["hint_rate"] >= .3:
                    signals.append("ヒント使用が30%以上")
                    rank = min(rank, 1)
                if (stat["correct_seconds"] is not None and baseline is not None
                        and sum(r["correct"] and r["attempt_count"] == 1 for r in rows) >= 5
                        and stat["correct_seconds"] > max(30, baseline * 1.5)):
                    signals.append("正解時に時間がかかる（本人の平均より長い）")
                    rank = min(rank, 1)
                if any(count >= 3 for count in stat["error_counts"].values()):
                    signals.append("同じ種類の誤答が3回以上")
                    rank = min(rank, 1)
                if stat["retry_count"] >= 3 and stat["retry_success"] / stat["retry_count"] >= .8:
                    signals.append("説明後の再回答では正解できる")
                status = ["× 苦手", "△ 練習中", "○ できる", "◎ 得意"][rank]
            result.append({"key": key, "label": labels.get(key, str(key)), **stat,
                           "status": status, "signals": signals})
        return result

    start = now.astimezone(JST).replace(hour=0, minute=0, second=0, microsecond=0)
    start -= timedelta(days=start.weekday())
    week = [r for r in selected if start <= datetime.fromisoformat(r["datetime"]) < start + timedelta(days=7)]
    groups = {
        "category": grouped("category", CATEGORIES), "tags": grouped("skill_tags", TAG_LABELS, True),
        "question_word": grouped("question_word", QUESTION_LABELS),
        "difficulty": grouped("difficulty", {1: "1（やさしい）", 2: "2（少し考える）"}),
        "reasoning": grouped("reasoning_level", {1: "1：直接書いてある", 2: "2：情報を探す",
                                              3: "3：文をつなげる", 4: "4：推測する"}),
    }
    weak = [g for g in groups["category"] if g["status"] in ("× 苦手", "△ 練習中")]
    weak.sort(key=lambda g: (g["rate"], -g["hint_rate"]))
    return {"summary": summary, "week": metrics(week), "week_start": start, **groups,
            "weak_categories": [g["key"] for g in weak], "reading_mode": reading_mode}
