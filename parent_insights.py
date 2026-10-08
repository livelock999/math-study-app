"""保護者レポート・類題・段階ヒント。保存や画面に依存しない計算です。"""

from collections import Counter, defaultdict
from datetime import timedelta
import csv
import io
import json

from daily_review import JST, REVIEW_TYPES, _math_key, _now, _time, _weak_keys, daily_budget, eligible_records, schedule, math_name
from hint_metrics import summarize_hints
from japanese_questions import CATEGORIES, ERROR_LABELS


def _correct(row, subject):
    return row.get("is_correct" if subject == "math" else "correct") in (True, 1)


def _known_bool(value):
    return type(value) in (bool, int) and value in (0, 1)


def _initial(row, subject):
    if row.get("selection_type") in REVIEW_TYPES or row.get("selection_type") == "retry":
        return False
    if subject == "math":
        # 従来の算数レポートの初回はnormal。類題weak_areaは別枠にする。
        return row.get("selection_type") == "normal"
    return row.get("attempt_count") == 1


def _summary(rows, subject):
    rows = list(rows)
    correct = sum(_correct(row, subject) for row in rows)
    levels = Counter(row["hint_level"] for row in rows
                     if type(row.get("hint_level")) is int and 0 <= row["hint_level"] <= 3
                     and _known_bool(row.get("hint_used"))
                     and bool(row["hint_level"]) == bool(row["hint_used"]))
    result = {"count": len(rows), "correct": correct,
              "rate": correct / len(rows) if rows else None,
              "dont_know_count": sum(row.get("dont_know_used") in (True, 1) for row in rows),
              "hint_levels": dict(sorted(levels.items())),
              "hint_level_known_count": sum(levels.values()),
              "max_hint_level": max(levels, default=None)}
    result.update(summarize_hints(rows, "is_correct" if subject == "math" else "correct"))
    return result


def _subject_week(rows, subject, start, end, previous_start):
    current = [row for row in rows if start <= _time(row["datetime"]).date() < end]
    previous = [row for row in rows if previous_start <= _time(row["datetime"]).date() < start]
    initial = _summary([row for row in current if _initial(row, subject)], subject)
    previous_initial = _summary([row for row in previous if _initial(row, subject)], subject)
    delta = None if initial["rate"] is None or previous_initial["rate"] is None else initial["rate"] - previous_initial["rate"]
    return {"label": "算数" if subject == "math" else "国語", "all": _summary(current, subject),
            "initial": initial, "previous_initial": previous_initial, "initial_rate_change": delta,
            "review": _summary([row for row in current if row.get("selection_type") == "review"], subject),
            "review_retry": _summary([row for row in current if row.get("selection_type") == "review_retry"], subject),
            "adaptive": _summary([row for row in current if row.get("selection_type") == "weak_area"], subject),
            "learning_days": len({_time(row["datetime"]).date() for row in current})}


def _growth(rows, subject, start, end):
    """同じ教材で、支援/誤答から最後に自力正解できた変化を一度だけ示す。"""
    id_field = "problem_id" if subject == "math" else "question_id"
    grouped = defaultdict(list)
    for row in rows:
        if row.get(id_field):
            grouped[row[id_field]].append(row)
    result = []
    for identifier, history in grouped.items():
        latest = history[-1]
        if (not start <= _time(latest["datetime"]).date() < end or not _correct(latest, subject)
                or not _known_bool(latest.get("hint_used")) or bool(latest["hint_used"])
                or latest.get("dont_know_used") in (True, 1)):
            continue
        transitions = [(before, after) for before, after in zip(history, history[1:])
                       if (not _correct(before, subject) or before.get("hint_used") in (True, 1))
                       and _correct(after, subject) and _known_bool(after.get("hint_used"))
                       and not bool(after["hint_used"]) and after.get("dont_know_used") not in (True, 1)
                       and start <= _time(after["datetime"]).date() < end]
        if not transitions:
            continue
        before, after = transitions[-1]
        reason = "ヒントが必要だった問題を自分で解けた" if before.get("hint_used") in (True, 1) else "前に間違えた問題を自分で解けた"
        result.append({"subject": subject, "problem_id": identifier, "reason": reason,
                       "before_at": before["datetime"], "after_at": after["datetime"],
                       "question_text": latest.get("question_text", latest.get("question", "")),
                       "category": latest.get("category"), "operation": latest.get("operation")})
    return sorted(result, key=lambda item: (_time(item["after_at"]), item["problem_id"]), reverse=True)


def weekly_report(math_records, jp_records, user_id, now=None, goals=None):
    """今日を含むJST7日とその前7日。未来・別学習者・再送は除外。"""
    current = _now(now)
    start, end = current.date() - timedelta(days=6), current.date() + timedelta(days=1)
    previous_start = start - timedelta(days=7)
    math_rows = eligible_records(math_records, user_id, current)
    jp_rows = eligible_records(jp_records, user_id, current)
    goals = dict(goals or {})
    weekly_days = goals.get("weekly_days", 3)
    daily_questions = goals.get("daily_questions", 5)
    if type(weekly_days) is not int or not 1 <= weekly_days <= 7:
        raise ValueError("週の目標日数は1〜7日にしてください。")
    if type(daily_questions) is not int or not 1 <= daily_questions <= 20:
        raise ValueError("1日の目標問題数は1〜20問にしてください。")
    active_days = {_time(row["datetime"]).date() for row in math_rows + jp_rows
                   if start <= _time(row["datetime"]).date() < end}
    counts = Counter(_time(row["datetime"]).date() for row in math_rows + jp_rows
                     if start <= _time(row["datetime"]).date() < end
                     and row.get("selection_type") in ("normal", "weak_area", "review"))
    attendance = [{"date": (start + timedelta(days=i)).isoformat(),
                   "count": counts[start + timedelta(days=i)],
                   "active": start + timedelta(days=i) in active_days,
                   "daily_goal_met": counts[start + timedelta(days=i)] >= daily_questions}
                  for i in range(7)]
    learning_days = sum(day["active"] for day in attendance)
    return {"start": start.isoformat(), "end": (end - timedelta(days=1)).isoformat(),
            "previous_start": previous_start.isoformat(), "previous_end": (start - timedelta(days=1)).isoformat(),
            "subjects": {"math": _subject_week(math_rows, "math", start, end, previous_start),
                         "japanese": _subject_week(jp_rows, "japanese", start, end, previous_start)},
            "attendance": attendance,
            "goals": {"weekly_days": weekly_days, "daily_questions": daily_questions,
                      "learning_days": learning_days, "weekly_goal_met": learning_days >= weekly_days,
                      "daily_goal_days": sum(day["daily_goal_met"] for day in attendance)},
            "growth": _growth(math_rows, "math", start, end) + _growth(jp_rows, "japanese", start, end)}


def _component(rows, field, label):
    known = [row for row in rows if _known_bool(row.get(field))]
    wrong = sum(not bool(row[field]) for row in known)
    return {"field": field, "label": label, "count": len(known), "wrong_count": wrong,
            "correct_count": len(known) - wrong,
            "wrong_rate": wrong / len(known) if known else None}


def error_analysis(math_records, jp_records, user_id, now=None):
    """実際に記録した判断・式・計算の違いを表示。読解原因を断定しません。"""
    math_rows = eligible_records(math_records, user_id, now)
    jp_rows = eligible_records(jp_records, user_id, now)
    math_initial = [row for row in math_rows if _initial(row, "math")]
    jp_initial = [row for row in jp_rows if _initial(row, "japanese")]
    math_answered = [row for row in math_initial if row.get("dont_know_used") not in (True, 1)]
    jp_answered = [row for row in jp_initial if row.get("dont_know_used") not in (True, 1)]
    calculations = [row for row in math_answered if row.get("problem_format") == "calculation"]
    words = [row for row in math_answered if row.get("problem_format") == "word_problem"]
    fills = [row for row in math_answered if row.get("problem_format") == "fill_blank"]
    components = [_component(calculations, "is_correct", "計算問題の答え"),
                  _component(words, "operation_selection_correct", "文章題のたす・ひくの選択"),
                  _component(words, "equation_correct", "文章題の式に入れた数と順序"),
                  _component(words, "calculation_correct", "自分が作った式の計算")]
    for position, label in (("left_operand", "穴埋めの左の□"), ("right_operand", "穴埋めの右の□")):
        component = _component([r for r in fills if r.get("blank_position") == position], "is_correct", label)
        components.append({**component, "field": f"fill_{position}"})
    threes = [row for row in math_answered if row.get("problem_format") == "three_numbers"]
    for first in ("addition", "subtraction"):
        for second in ("addition", "subtraction"):
            group = [r for r in threes if r.get("operation") == first and r.get("second_operation") == second]
            label = ("3つの数のたし算" if first == second == "addition" else "3つの数のひき算"
                     if first == second == "subtraction" else "たし算からひき算" if first == "addition" else "ひき算からたし算")
            components.append({**_component(group, "is_correct", label), "field": f"three_{first}_{second}"})
    three_words = [row for row in math_answered if row.get("problem_format") == "three_word_problem"]
    for name, field, label in (("operation", "operation_selection_correct", "3つの数の文章題の2つの演算選択"),
                               ("equation", "equation_correct", "3つの数の文章題の3数量と順序"),
                               ("calculation", "calculation_correct", "3つの数の文章題で作った全式の計算")):
        components.append({**_component(three_words, field, label), "field": f"three_word_{name}"})
    categories = []
    for category, label in CATEGORIES.items():
        rows = [row for row in jp_answered if row.get("category") == category]
        summary = _summary(rows, "japanese")
        if rows:
            categories.append({"category": category, "label": label, **summary,
                               "wrong_count": summary["count"] - summary["correct"]})
    wrong_jp = [row for row in jp_answered if not _correct(row, "japanese")]
    causes = Counter(tag for row in wrong_jp for tag in set(row.get("error_cause_tags") or []))
    confusion = Counter(row["confusion_pair"] for row in wrong_jp
                        if row.get("category") == "particles" and row.get("confusion_pair"))
    return {"math": {"components": components, "initial_count": len(math_initial),
                     "explanation": "記録された選択・式・計算を分けています。読み違いなどの原因は断定しません。"},
            "japanese": {"categories": categories,
                         "error_tags": [{"tag": tag, "label": ERROR_LABELS.get(tag, tag), "count": count}
                                        for tag, count in causes.most_common()],
                         "particles": [{"pair": pair, "label": pair.replace("_", "・"), "count": count}
                                       for pair, count in confusion.most_common()],
                         "initial_count": len(jp_initial)},
            "dont_know": {"math": sum(row.get("dont_know_used") in (True, 1) for row in math_initial),
                          "japanese": sum(row.get("dont_know_used") in (True, 1) for row in jp_initial)}}


def _csv_cell(value):
    if value is None:
        return ""
    if isinstance(value, (dict, list, tuple)):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True)
    if isinstance(value, str) and (value.startswith(("\t", "\r", "\n")) or value.lstrip().startswith(("=", "+", "-", "@"))):
        return "'" + value
    return value


def csv_export(math_records, jp_records, user_id, now=None):
    """全保存項目の共通CSV。Excel向けBOMと式注入対策を含むbytes。"""
    rows = []
    for subject, records in (("math", math_records), ("japanese", jp_records)):
        for row in eligible_records(records, user_id, now):
            rows.append({**row, "subject": subject,
                         "problem_identifier": row.get("problem_id", row.get("question_id", ""))})
    fields = ["subject", "datetime", "attempt_id", "user_id", "problem_identifier"]
    fields += sorted({field for row in rows for field in row} - set(fields))
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\r\n")
    writer.writerow([_csv_cell(field) for field in fields])
    for row in sorted(rows, key=lambda item: (_time(item["datetime"]), item["subject"], str(item.get("attempt_id", "")))):
        writer.writerow([_csv_cell(row.get(field)) for field in fields])
    return output.getvalue().encode("utf-8-sig")


def _math_pool(limit):
    from learning import problem_pool, get_problem_pool
    from words import word_pool
    pool = []
    for operation in ("addition", "subtraction"):
        pool.extend(problem_pool(operation, limit))
        pool.extend(word_pool(operation, limit))
        pool.extend(get_problem_pool("fill_blank")(operation, limit))
        pool.extend(get_problem_pool("three_numbers")(operation, limit))
        pool.extend(get_problem_pool("three_word_problem")(operation, limit))
    return pool


def _jp_pool(particle_level):
    from japanese_questions import QUESTIONS
    if particle_level not in (None, 1, 2, 3):
        raise ValueError("てにをはのレベルが不正です。")
    return [q for q in QUESTIONS if q["category"] != "particles" or particle_level is None or q["level"] <= particle_level]


def review_forecast(records, user_id, subject, now=None, limit=10, particle_level=None, candidate_pool=None):
    """基本問題の補充を含めず、実際の復習予定数を日別に示します。"""
    current = _now(now)
    records = list(records)
    if subject == "math":
        pool, id_field = _math_pool(limit), "problem_id"
    elif subject == "japanese":
        pool, id_field = _jp_pool(particle_level), "question_id"
    else:
        raise ValueError("教科が不正です。")
    if candidate_pool is not None:
        pool = candidate_pool
    identifiers = {q[id_field] for q in pool}
    states = schedule(records, user_id, subject, current)
    budget = daily_budget(records, user_id, subject, current)
    today = sum(state["due_date"] <= current.date() for identifier, state in states.items() if identifier in identifiers)
    tomorrow = sum(state["due_date"] == current.date() + timedelta(days=1)
                   for identifier, state in states.items() if identifier in identifiers)
    today_count = min(today, budget["daily_remaining"])
    return {"today_count": today_count, "tomorrow_count": min(tomorrow, 5),
            "today_total": today, "tomorrow_total": tomorrow,
            "today_overflow": max(today - today_count, 0), "tomorrow_overflow": max(tomorrow - 5, 0),
            **budget,
            "explanation": "履歴からの復習予定です。基本問題の補充は含みません。明日の数は今日の回答で変わります。"}


def _adaptive(pool, rows, subject, count):
    if type(count) is not int or count < 1:
        raise ValueError("問題数が不正です。")
    id_field = "problem_id" if subject == "math" else "question_id"
    latest = {}
    for row in rows:
        if row.get(id_field):
            latest[row[id_field]] = row
    pool_ids = {q[id_field] for q in pool}
    targets = [row for identifier, row in latest.items() if identifier in pool_ids
               and (not _correct(row, subject) or row.get("hint_used") in (True, 1))]
    weak = _weak_keys(rows, subject)
    ranked = []
    for question in pool:
        identifier = question[id_field]
        if subject == "math":
            key = _math_key(question)
            similar = [row for row in targets if _math_key(row) == key]
            name = math_name(question)
            if similar:
                # 文章題は同じ意味関係を優先し、数の近い類題を選ぶ。
                distance = min((int(row.get("story_type") != question.get("story_type")),
                                abs(row["left_operand"] - question["left_operand"]) + abs(row["right_operand"] - question["right_operand"])
                                + abs((row.get("third_operand") or 0) - (question.get("third_operand") or 0)))
                               for row in similar)
                rank, reason = 0, f"前に難しかった{name}と同じ考え方の類題"
            elif key in weak:
                rank, reason, distance = 1, f"苦手な{name}の類題", (0, 0)
            else:
                rank, reason, distance = 2, "基本の類題で確認", (0, question["left_operand"] + question["right_operand"])
            difficulty = int(bool(question.get("carry") or question.get("borrowing")))
        else:
            similar = [row for row in targets if row.get("category") == question["category"]]
            name = CATEGORIES[question["category"]]
            if similar:
                distance = min((int(row.get("question_word") != question.get("question_word")),
                                int(row.get("semantic_role") != question.get("semantic_role")),
                                abs(row.get("difficulty", 1) - question.get("difficulty", 1))) for row in similar)
                rank, reason = 0, f"前に難しかった{name}の別の文・ことば"
            elif question["category"] in weak:
                rank, reason, distance = 1, f"苦手な{name}の別の問題", (0, 0, 0)
            else:
                rank, reason, distance = 2, "基本のことば・文で確認", (0, 0, 0)
            difficulty = question.get("difficulty", 1)
        # 未回答の問題をすべての既回答より優先し、元問題だけの繰り返しを避ける。
        ranked.append(((identifier in latest, rank, distance, difficulty, identifier), question, reason))
    ranked.sort(key=lambda item: item[0])
    items, reasons, seen = [], {}, set()
    for _, question, reason in ranked:
        identifier = question[id_field]
        if identifier in seen:
            continue
        seen.add(identifier)
        items.append(dict(question))
        reasons[identifier] = reason
        if len(items) == count:
            break
    message = "この条件で用意できる問題がありません。" if not items else (f"重複せずに用意できる{len(items)}問で始めます。" if len(items) < count else "")
    return {"items": items, "reasons": reasons, "message": message}


def adaptive_math(records, user_id, limit=10, count=5, now=None):
    return _adaptive(_math_pool(limit), eligible_records(records, user_id, now), "math", count)


def adaptive_japanese(records, user_id, particle_level=None, count=5, now=None):
    return _adaptive(_jp_pool(particle_level), eligible_records(records, user_id, now), "japanese", count)


def math_hint_steps(problem):
    """答えを直接示さず、手がかり→具体的な操作→解き方の順。"""
    if problem["problem_format"] == "fill_blank":
        from fill_blank import hint_steps
        return hint_steps(problem)
    if problem["problem_format"] == "three_numbers":
        from three_numbers import hint_steps
        return hint_steps(problem)
    if problem["problem_format"] == "three_word_problem":
        from three_word import hint_steps
        return hint_steps(problem)
    from words import guidance
    first = guidance(problem)
    if problem["problem_format"] == "word_problem":
        inverse_steps = {
            "increase_start": ("いま ある りんごを つみきで ならべよう。もらった ぶんだけ よけて、もらう まえの ようすに もどそう。", "いまの かずから もらった かずを ひく しきを つくろう。のこった つみきが、はじめに あった かずだよ。"),
            "increase_change": ("はじめの かずと いまの かずの つみきを、1こずつ くみに しよう。いまの ほうに あまる つみきが ふえた ぶんだよ。", "いまの かずから はじめの かずを ひく しきを つくろう。もらった かずを きかれている ことを たしかめよう。"),
            "decrease_start": ("のこった りんごを つみきで ならべよう。たべた ぶんの つみきを もどして、たべる まえの ようすに しよう。", "のこった かずと たべた かずを たす しきを つくろう。あわせた つみきが、はじめに あった かずだよ。"),
            "decrease_change": ("はじめの かずの つみきを ならべよう。のこった ぶんを よけて、たべた ぶんを たしかめよう。", "はじめの かずから のこった かずを ひく しきを つくろう。たべた かずを きかれている ことを たしかめよう。"),
        }
        second, third = inverse_steps.get(problem.get("story_type"), (
            "たとえば、ものを つみきで おきかえて みよう。ぶんの とおりに ならべたり、うごかしたり しよう。",
            "きかれている かずを たしかめよう。ぶんの 2つの かずで しきを つくり、のこった ものや まとまった ものを かぞえよう。"))
    elif problem["operation"] == "addition":
        second = "たとえば、2つの かずの ぶんだけ つみきを ならべて、ひとつに まとめよう。"
        third = ("それぞれの かずを、10の まとまりと ばらの かずに わけよう。ばらを あわせて 10の まとまりを つくり、まとまりと のこりを あわせよう。"
                 if problem.get("carry") else "はじめの かずを おぼえて、もう ひとつの かずの ぶんだけ 1ずつ ふやして かぞえよう。")
    else:
        second = "たとえば、はじめの かずの つみきを ならべて、ひく かずの ぶんだけ よけよう。"
        third = ("はじめの かずを、10の まとまりと ばらに わけよう。ばらが たりなければ、10の まとまりを ひとつ ばらに かえよう。ひく かずを よけて、のこりを かぞえよう。"
                 if problem.get("borrowing") else "はじめの かずから、ひく かずの ぶんだけ 1ずつ もどろう。さいごに とまった かずを たしかめよう。")
    return [first, second, third]


def japanese_hint_steps(question):
    """既存の初段ヒントを保ち、正解の選択肢や解説を先に見せません。"""
    category = question["category"]
    steps = {
        "words": ("たとえば、ことばを 1もじずつ ゆっくり よんで、いみや もじの ちがいを くらべよう。", "しつもんが きいている ことを たしかめよう。えらぶ ことばが、その いみや もじに あうか もういちど くらべよう。"),
        "sentence": ("ぶんを、だれの こと・なにの こと・どうした、に わけて よんでみよう。", "しつもんの ことばを ぶんの なかから さがそう。その まわりを よんで、あう こたえを えらぼう。"),
        "information": ("たとえば、ひと・もの・ばしょの ことばに ちゅうもくして よんでみよう。", "しつもんは だれ・なに・どこの どれを きいているかな。その しるしが ある ぶんを もういちど よもう。"),
        "sequence": ("できごとを ひとつずつ ならべて、どちらが さきか くらべよう。", "はじめに おきたことから ならべよう。つぎのできごとに つながるか、ならべた ぶんを よんで たしかめよう。"),
        "passage": ("おはなしを 1ぶんずつ よんで、しつもんに かんけいする ところを さがそう。", "えらぶ こたえの しるしが おはなしに あるか たしかめよう。まえと うしろの ぶんも よんで くらべよう。"),
        "blank": ("えらべる ことばを ひとつずつ あなに いれた つもりで よんでみよう。", "ぶんの はじめから おわりまで よもう。まえと うしろの ことばに つながり、いみが とおる ことばを えらぼう。"),
        "particles": ("ぶんが つたえたいことは、だれの はなし・することの あいて・いく ばしょ・する ばしょの どれかな。", "それぞれの ことばを いれて ぶんを よんでみよう。しつもんで つたえたい いみと あうほうを えらぼう。"),
    }
    second, third = steps[category]
    return [question.get("hint", "しつもんを もういちど よんでみよう。"), second, third]
