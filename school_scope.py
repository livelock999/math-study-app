"""子どもごとの学校範囲。設定保存と教材候補の作成を画面から独立させる。"""
from contextlib import closing
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request
import json
import sqlite3

import learning
import learning_extensions as store
import adaptive_difficulty as adaptive
import daily_review as review
from japanese_questions import QUESTIONS, CATEGORIES
from words import word_pool

MATH_UNITS = {
    "current": ("指定しない（練習画面の設定を使う）", None),
    "addition_10": ("10までのたし算", ("addition", 10, "auto")),
    "subtraction_10": ("10までのひき算", ("subtraction", 10, "auto")),
    "mix_10": ("10までのたし算・ひき算", ("mix", 10, "auto")),
    "addition_20_none": ("20までのたし算・くり上がりなし", ("addition", 20, "none")),
    "addition_20_with": ("20までのたし算・くり上がりあり", ("addition", 20, "with")),
    "subtraction_20_none": ("20までのひき算・くり下がりなし", ("subtraction", 20, "none")),
    "subtraction_20_with": ("20までのひき算・くり下がりあり", ("subtraction", 20, "with")),
    "mix_20": ("20までのたし算・ひき算", ("mix", 20, "auto")),
}
JP_UNITS = {"current": "指定しない（練習画面の設定を使う）", "mix": "全分野",
            **{key: value for key, value in CATEGORIES.items() if key != "particles"},
            "particles_1": "てにをは・レベル1まで", "particles_2": "てにをは・レベル2まで",
            "particles_3": "てにをは・レベル3まで"}


def validate(user_id, math_unit, japanese_unit):
    store._learner(user_id)
    if (not isinstance(math_unit, str) or math_unit not in MATH_UNITS
            or not isinstance(japanese_unit, str) or japanese_unit not in JP_UNITS):
        raise ValueError("学校で習う範囲が不正です。")
    return {"user_id": user_id, "math_unit": math_unit, "japanese_unit": japanese_unit}


def default_scope(user_id):
    return validate(user_id, "current", "current")


def read_scope(user_id, path=None):
    default = default_scope(user_id)
    config = learning.get_supabase_config() if path is None else None
    if config:
        url, key = config
        query = urlencode({"user_id": f"eq.{user_id}", "select": "user_id,math_unit,japanese_unit", "limit": 1})
        rows = store._cloud(Request(f"{url}/rest/v1/family_school_scope?{query}",
                                   headers={"apikey": key, "Accept": "application/json"}),
                            "学校の範囲", "supabase_school_scope.sql")
        try:
            if not isinstance(rows, list) or len(rows) > 1:
                raise ValueError()
            if not rows:
                return default
            row = validate(rows[0]["user_id"], rows[0]["math_unit"], rows[0]["japanese_unit"])
            if row["user_id"] != user_id:
                raise ValueError()
            return row
        except (ValueError, TypeError, KeyError):
            raise OSError("学校の範囲の応答を確認できませんでした。再試行してください。") from None
    path = Path(path or store.DB_PATH)
    if not path.exists():
        return default
    with closing(sqlite3.connect(path, timeout=10)) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='family_school_scope'").fetchone():
            return default
        row = db.execute("SELECT math_unit,japanese_unit FROM family_school_scope WHERE user_id=?", (user_id,)).fetchone()
    return validate(user_id, *row) if row else default


def save_scope(user_id, math_unit, japanese_unit, path=None, test_mode=False):
    row = validate(user_id, math_unit, japanese_unit)
    if type(test_mode) is not bool:
        raise ValueError("テスト状態が不正です。")
    if test_mode:
        return row
    stamp = datetime.now(review.JST).isoformat()
    config = learning.get_supabase_config() if path is None else None
    if config:
        url, key = config
        store._cloud(Request(f"{url}/rest/v1/family_school_scope?on_conflict=user_id",
                             data=json.dumps({**row, "updated_at": stamp}, ensure_ascii=False).encode("utf-8"),
                             headers={"apikey": key, "Content-Type": "application/json",
                                      "Prefer": "resolution=merge-duplicates,return=minimal"}, method="POST"),
                     "学校の範囲", "supabase_school_scope.sql")
    else:
        path = Path(path or store.DB_PATH)
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(path, timeout=10)) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS family_school_scope (user_id TEXT PRIMARY KEY, "
                       "math_unit TEXT NOT NULL, japanese_unit TEXT NOT NULL, updated_at TEXT NOT NULL)")
            db.execute("INSERT INTO family_school_scope (user_id,math_unit,japanese_unit,updated_at) "
                       "VALUES (?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET math_unit=excluded.math_unit,"
                       "japanese_unit=excluded.japanese_unit,updated_at=excluded.updated_at",
                       (user_id, math_unit, japanese_unit, stamp))
    return row


def active_scope(user_id, session):
    from practice_mode import is_test_mode
    if is_test_mode(session) and user_id in session.get("school_scope_preview", {}):
        return validate(**session["school_scope_preview"][user_id])
    return read_scope(user_id)


def math_settings(scope, mode, limit, special):
    validate(**scope)
    return MATH_UNITS[scope["math_unit"]][1] or (mode, limit, special)


def japanese_settings(scope, category, particle_level):
    validate(**scope)
    unit = scope["japanese_unit"]
    if unit == "current":
        return category, particle_level, None
    if unit.startswith("particles_"):
        return "particles", None, int(unit[-1])
    return unit, None, None


def plan_math(records, user_id, scope, mode="addition", limit=10, count=10, special="auto",
              problem_format="calculation", now=None, rng=None):
    if scope["user_id"] != user_id:
        raise ValueError("学校の範囲の学習者が一致しません。")
    mode, limit, special = math_settings(scope, mode, limit, special)
    plan = adaptive.plan_math(records, user_id, mode, limit, count, special, problem_format, now, rng)
    if scope["math_unit"] != "current":
        plan["scope_label"] = MATH_UNITS[scope["math_unit"]][0]
    return plan


def plan_japanese(records, user_id, scope, category="mix", count=10, particle_level=None, now=None, rng=None):
    if scope["user_id"] != user_id:
        raise ValueError("学校の範囲の学習者が一致しません。")
    category, particle_level, ceiling = japanese_settings(scope, category, particle_level)
    plan = adaptive.plan_japanese(records, user_id, category, count, particle_level, now, rng, particle_ceiling=ceiling)
    if scope["japanese_unit"] != "current":
        plan["scope_label"] = JP_UNITS[scope["japanese_unit"]]
    return plan


def review_pool(records, user_id, scope, subject, now=None):
    """今の単元の補充候補＋本人が回答した現行問題。未知の過去単元は補充しない。"""
    validate(**scope)
    if scope["user_id"] != user_id or subject not in ("math", "japanese"):
        raise ValueError("復習の学習者・教科が不正です。")
    unit = scope["math_unit" if subject == "math" else "japanese_unit"]
    if unit == "current":
        return None
    rows = review.eligible_records(records, user_id, now)
    if subject == "math":
        mode, limit, special = math_settings(scope, "addition", 10, "auto")
        operations = ("addition", "subtraction") if mode == "mix" else (mode,)
        base = [q for operation in operations for fn in (learning.problem_pool, word_pool)
                for q in fn(operation, limit, special)]
        identifier = "problem_id"
        prior = {r.get(identifier) for r in rows}
        history = [q for size in (10, 20) for operation in ("addition", "subtraction")
                   for fn in (learning.problem_pool, word_pool) for q in fn(operation, size)
                   if q[identifier] in prior]
    else:
        category, _, ceiling = japanese_settings(scope, "mix", None)
        base = [q for q in QUESTIONS if (category == "mix" or q["category"] == category)
                and (q["category"] != "particles" or ceiling is None or q["level"] <= ceiling)]
        identifier = "question_id"
        prior = {r.get(identifier) for r in rows}
        history = [q for q in QUESTIONS if q[identifier] in prior]
    return list({q[identifier]: q for q in base + history}.values())
