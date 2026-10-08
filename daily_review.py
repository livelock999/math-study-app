"""今日の復習の純粋な選定。予定は保存済み回答から再計算し、書き込みません。

通常・再練習・復習を同じ教材IDに結びます。国語のchain_idは回答内の
再練習系列であり、長期の復習キーとしては使いません。review_due_atは
旧版の誤答時のみの予定なので参照せず、最新までの履歴を使います。
"""

from collections import defaultdict
from datetime import datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))
REVIEW_TYPES = frozenset(("review", "review_retry"))


def _time(value):
    """古いタイムゾーンなしの履歴はJSTとして扱います。"""
    try:
        result = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None
    return result.replace(tzinfo=JST) if result.tzinfo is None else result.astimezone(JST)


def _now(now):
    result = datetime.now(JST) if now is None else _time(now)
    if result is None:
        raise ValueError("復習の日時が不正です。")
    return result


def eligible_records(records, user_id, now=None):
    """学習者を隔離し、未来・不正日時・同じattempt_idの再送を除外。"""
    current = _now(now)
    seen, result = set(), []
    # 保存されたIDは不変。再送で同じ回答が複数届いても一回答にする。
    candidates = []
    for row in records:
        stamp = _time(row.get("datetime"))
        if row.get("user_id") == user_id and stamp is not None and stamp <= current:
            candidates.append((stamp, str(row.get("attempt_id", "")), row))
    for stamp, identifier, row in sorted(candidates, key=lambda item: (item[0], item[1])):
        if identifier and identifier in seen:
            continue
        if identifier:
            seen.add(identifier)
        result.append(row)
    return result


def daily_budget(records, user_id, subject, now=None):
    """教科別に1日5問。保存済みの復習回答のみ、即時再練習は枠を使わない。"""
    if subject not in ("math", "japanese"):
        raise ValueError("教科が不正です。")
    current = _now(now)
    id_field = "problem_id" if subject == "math" else "question_id"
    done = sum(row.get("selection_type") == "review" and bool(row.get(id_field))
               and _time(row["datetime"]).date() == current.date()
               for row in eligible_records(records, user_id, current))
    return {"daily_done": done, "daily_remaining": max(5 - done, 0)}


def _limited_plan(pool, rows, user_id, subject, now, count):
    if type(count) is not int or count < 1:
        raise ValueError("復習の問題数が不正です。")
    budget = daily_budget(rows, user_id, subject, now)
    if not budget["daily_remaining"]:
        return {"items": [], "reasons": {}, "message": "きょうは5問のふくしゅうができました。つづきはあしたにしましょう。", **budget}
    available = min(count, budget["daily_remaining"])
    plan = _plan(pool, schedule(rows, user_id, subject, now), _weak_keys(rows, subject), subject, now, available)
    if plan["items"] and available < count:
        plan["message"] = f"きょうの復習はあと{budget['daily_remaining']}問です。今回は{len(plan['items'])}問で始めます。"
    plan.update(budget)
    return plan


def schedule(records, user_id, subject, now=None):
    """教材IDごとの最新回答とJST復習日。自力正解の日ごとに3→7日。

    同日に誤答またはヒントが一度でもあれば翌日に戻ります。hintが未記録の
    古い正解は自力正解と推測せず、段階を進めません。日時・attempt_idで
    確定的に最新を選び、同日複数回の正解も一段階しか進みません。
    """
    if subject not in ("math", "japanese"):
        raise ValueError("教科が不正です。")
    id_field = "problem_id" if subject == "math" else "question_id"
    correct_field = "is_correct" if subject == "math" else "correct"
    groups = defaultdict(list)
    for row in eligible_records(records, user_id, now):
        if row.get(id_field) and row.get(correct_field) in (True, False):
            groups[row[id_field]].append(row)
    result = {}
    for identifier, rows in groups.items():
        days = defaultdict(list)
        for row in rows:
            days[_time(row["datetime"]).date()].append(row)
        streak, interval = 0, 1
        for day, daily in sorted(days.items()):
            reset = any(not row[correct_field] or row.get("hint_used") in (True, 1) for row in daily)
            clean = all(row[correct_field] and row.get("hint_used") in (False, 0) for row in daily)
            if reset:
                streak, interval = 0, 1
            elif clean:
                streak += 1
                interval = 3 if streak == 1 else 7
            due = day + timedelta(days=interval)
        result[identifier] = {"latest": rows[-1], "due_date": due,
                              "interval_days": interval, "clean_days": streak,
                              "last_date": max(days)}
    return result


def _weak_keys(rows, subject):
    """既存の初回集計基準（5問、80%未満／ヒント30%以上）を使う。"""
    buckets = defaultdict(list)
    for row in rows:
        if subject == "math":
            if row.get("selection_type") != "normal":
                continue
            key = _math_key(row)
        else:
            if row.get("attempt_count") != 1 or row.get("selection_type") in REVIEW_TYPES:
                continue
            key = row.get("category")
        buckets[key].append(row)
    correct_field = "is_correct" if subject == "math" else "correct"
    result = set()
    for key, group in buckets.items():
        known = [r for r in group if r.get("hint_used") in (True, False)]
        rate = sum(bool(r.get(correct_field)) for r in group) / len(group)
        hinted = len(known) >= 5 and sum(bool(r["hint_used"]) for r in known) / len(known) >= .3
        if len(group) >= 5 and (rate < .8 or hinted):
            result.add(key)
    return result


def _math_key(row):
    if row.get("problem_format") in ("three_numbers", "three_word_problem"):
        key = (row["problem_format"], row.get("operation"), row.get("number_range"),
               row.get("second_operation"), bool(row.get("carry")), bool(row.get("borrowing")))
        return (*key, row.get("story_type")) if row["problem_format"] == "three_word_problem" else key
    special = row.get("carry") if row.get("operation") == "addition" else row.get("borrowing")
    key = row.get("problem_format"), row.get("operation"), row.get("number_range"), bool(special)
    return (*key, row.get("blank_position")) if row.get("problem_format") == "fill_blank" else key


def math_name(question):
    name = "たし算" if question.get("operation") == "addition" else "ひき算"
    if question.get("problem_format") == "fill_blank":
        name += "の穴埋め（左の□）" if question["blank_position"] == "left_operand" else "の穴埋め（右の□）"
    elif question.get("problem_format") in ("three_numbers", "three_word_problem"):
        name = f"3つの数の{name}" if question["operation"] == question["second_operation"] else "3つの数のたし算とひき算"
        if question["problem_format"] == "three_word_problem":
            name += "の文章題"
    return name


def _plan(pool, schedules, weak, subject, now, count):
    if type(count) is not int or count < 1:
        raise ValueError("復習の問題数が不正です。")
    id_field = "problem_id" if subject == "math" else "question_id"
    correct_field = "is_correct" if subject == "math" else "correct"
    from japanese_questions import CATEGORIES
    ranked = []
    for question in pool:
        identifier = question[id_field]
        state = schedules.get(identifier)
        name = math_name(question) if subject == "math" else CATEGORIES[question["category"]]
        if state:
            if state["due_date"] > now.date():
                continue
            latest = state["latest"]
            if not latest[correct_field]:
                rank, reason = 0, f"前に間違えた{name}"
            elif latest.get("hint_used") in (True, 1):
                rank, reason = 1, "ヒントを使った問題"
            else:
                rank, reason = 2, "正解した問題をもう一度確認"
            order = state["due_date"].isoformat()
        else:
            key = _math_key(question) if subject == "math" else question["category"]
            rank, reason = (3, f"苦手分野の{name}") if key in weak else (4, "基本問題で確認")
            order = ""
        # 未回答の補充は簡単な教材を先にし、同じ難度はIDで確定。
        difficulty = question.get("difficulty", int(bool(question.get("carry") or question.get("borrowing"))))
        if subject == "math":
            difficulty = (difficulty, question["problem_format"] != "calculation",
                          question["left_operand"] + question["right_operand"] + (question.get("third_operand") or 0))
        ranked.append(((rank, order, difficulty, identifier), question, reason))
    ranked.sort(key=lambda item: item[0])
    items, reasons, seen = [], {}, set()
    for _, question, reason in ranked:
        identifier = question[id_field]
        if identifier in seen:
            continue
        items.append(dict(question))
        reasons[identifier] = reason
        seen.add(identifier)
        if len(items) == count:
            break
    message = ""
    if not items:
        message = "この条件では、復習日を迎えた問題や未回答の基本問題がありません。次の復習日まで待つか、通常の練習を選んでください。"
    elif len(items) < count:
        message = f"重複せずに用意できる{len(items)}問で復習します。"
    return {"items": items, "reasons": reasons, "message": message}


def plan_math(records, user_id, limit=10, now=None, count=5, candidate_pool=None):
    """現在の数の範囲の計算・文章題。教材を再生成し、履歴の本文は使わない。"""
    from learning import problem_pool, get_problem_pool
    from words import word_pool
    current = _now(now)
    rows = eligible_records(records, user_id, current)
    if candidate_pool is not None:
        return _limited_plan(candidate_pool, rows, user_id, "math", current, count)
    pool = []
    for operation in ("addition", "subtraction"):
        pool.extend(problem_pool(operation, limit))
        pool.extend(word_pool(operation, limit))
        pool.extend(get_problem_pool("fill_blank")(operation, limit))
        pool.extend(get_problem_pool("three_numbers")(operation, limit))
        pool.extend(get_problem_pool("three_word_problem")(operation, limit))
    return _limited_plan(pool, rows, user_id, "math", current, count)


def plan_japanese(records, user_id, particle_level=None, now=None, count=5, candidate_pool=None):
    """国語は現行教材を使用。助詞の難度制限はミックスにも適用。"""
    from japanese_questions import QUESTIONS
    if particle_level not in (None, 1, 2, 3):
        raise ValueError("てにをはのレベルが不正です。")
    current = _now(now)
    rows = eligible_records(records, user_id, current)
    if candidate_pool is not None:
        return _limited_plan(candidate_pool, rows, user_id, "japanese", current, count)
    pool = [q for q in QUESTIONS if q["category"] != "particles" or particle_level is None or q["level"] <= particle_level]
    return _limited_plan(pool, rows, user_id, "japanese", current, count)
