"""保存済みの回答を集計する、外部AIを使わない学習評価。"""

from statistics import median
import random

from learning import make_problem
from hint_metrics import summarize_hints


def category(record):
    operation = record["operation"]
    special = bool(record["carry"] if operation == "addition" else record["borrowing"])
    return operation, record["number_range"], special


def category_label(key):
    operation, limit, special = key
    name = "たし算" if operation == "addition" else "ひき算"
    attribute = "繰り上がり" if operation == "addition" else "繰り下がり"
    return f"{limit}までの{name}（{attribute}{'あり' if special else 'なし'}）"


def summarize(records):
    records = list(records)
    correct = sum(bool(row["is_correct"]) for row in records)
    times = [row["response_time_sec"] for row in records if row["is_correct"]]
    visual = [row["visual_help_used"] for row in records
              if type(row.get("visual_help_used")) in (bool, int) and row["visual_help_used"] in (0, 1)]
    return {"count": len(records), "correct": correct,
            "rate": correct / len(records) if records else None,
            "seconds": median(times) if times else None,
            "visual_known_count": len(visual), "visual_used_count": sum(bool(v) for v in visual),
            "visual_unknown_count": len(records) - len(visual),
            "visual_rate": sum(bool(v) for v in visual) / len(visual) if visual else None,
            **summarize_hints(records, correct_field="is_correct")}


def assess(records, user_id=None, now=None):
    """初回だけで習熟を評価。範囲・演算・繰り上がり等を揃えて比較します。"""
    # カードの入力・出題テンポは通常練習と異なり、専用集計で比較します。
    records = [row for row in records if row.get("learning_mode") != "flashcard"]
    calculations = [row for row in records if row["problem_format"] == "calculation"]
    words = [row for row in records if row["problem_format"] == "word_problem"]
    normal = sorted((row for row in calculations if row["selection_type"] == "normal"),
                    key=lambda row: (row["datetime"], row["attempt_id"]))
    retries = [row for row in calculations if row["selection_type"] == "retry"]
    buckets = {}
    for row in normal:
        buckets.setdefault(category(row), []).append(row)
    groups = []
    for key, rows in sorted(buckets.items()):
        group = {"key": key, "label": category_label(key), **summarize(rows)}
        if group["count"] < 5:
            group["status"] = "判断保留（5問未満）"
        elif group["rate"] >= .9:
            group["status"] = "よくできています"
        elif group["rate"] >= .8:
            group["status"] = "もう少し練習"
        else:
            group["status"] = "優先して練習"
        group["hint_support"] = (group["hint_known_count"] >= 5
                                 and group["hint_rate"] >= .3)
        group["support_message"] = ("ヒントが理解を支えています。ヒントで考え方を確認し、慣れたら自力でも試しましょう。"
                                    if group["hint_support"] else "")
        group["trend"] = "比較する回答がまだ足りません（20問から）"
        if len(rows) >= 20:
            recent = summarize(rows[-10:])["rate"]
            previous = summarize(rows[-20:-10])["rate"]
            delta = round((recent - previous) * 100)
            group["trend"] = f"直近10問 {recent:.0%} ／ その前10問 {previous:.0%}（{delta:+d}ポイント）"
        groups.append(group)
    eligible = [group for group in groups if group["count"] >= 5]
    weak = [group for group in eligible if group["rate"] < .8]
    target = min(weak, key=lambda group: (group["rate"], -group["count"])) if weak else None
    supported = [group for group in groups if group["hint_support"]]
    if target is None and supported:
        target = max(supported, key=lambda group: (group["hint_rate"], group["hint_known_count"]))
    strengths = [group["label"] for group in eligible if group["rate"] >= .9]
    if not normal:
        message = "初回の回答がまだありません。まず10問練習してみましょう。"
    elif len(normal) < 10:
        message = "まだ回答が少ないため、現状の評価は参考です。まず初回の回答を10問以上集めましょう。"
    elif target:
        message = f"次は「{target['label']}」を5問練習しましょう。初回正答率は{target['rate']:.0%}（{target['count']}問）です。"
    elif eligible:
        message = "5問以上回答した種類は、初回正答率がすべて80%以上です。ミックスで練習を続けましょう。"
    else:
        message = "種類ごとの回答がまだ少ないため、得意・苦手の判断は保留しています。練習を続けましょう。"
    if target and target["hint_support"]:
        message += " ヒントが考え方の支えになっています。必要なときはヒントを使い、慣れたら同じ種類を自力でも試しましょう。"
    return {"overall": summarize(normal), "retry": summarize(retries), "groups": groups,
            "review": summarize([r for r in calculations if r["selection_type"] == "review"]),
            "review_retry": summarize([r for r in calculations if r["selection_type"] == "review_retry"]),
            "strengths": strengths, "message": message,
            "target": target["key"] if target else None,
            "suggested_limit": max((row["number_range"] for row in normal), default=10),
            "word_normal": summarize_words([row for row in words if row["selection_type"] == "normal"]),
            "word_retry": summarize_words([row for row in words if row["selection_type"] == "retry"]),
            "word_review": summarize_words([row for row in words if row["selection_type"] == "review"]),
            "word_review_retry": summarize_words([row for row in words if row["selection_type"] == "review_retry"]),
            **assess_fill(records, user_id=user_id, now=now),
            **assess_three(records, user_id=user_id, now=now),
            **assess_three_word(records, user_id=user_id, now=now)}


def fill_category(record):
    return (*category(record), record["blank_position"])


def fill_label(key):
    return f"{category_label(key[:3])}・{'左の□' if key[3] == 'left_operand' else '右の□'}"


def assess_fill(records, user_id=None, now=None):
    """穴埋めの初回・再回答・最新成果。通常計算や復習の成績へ混ぜない。"""
    return _assess_independent(records, "fill_blank", "fill", fill_category, fill_label, user_id, now)


def three_category(record):
    return (record["operation"], record["second_operation"], record["number_range"],
            bool(record.get("carry")), bool(record.get("borrowing")))


def three_label(key):
    first, second, limit, carry, borrowing = key
    name = ("3つの数のたし算" if first == second == "addition" else "3つの数のひき算"
            if first == second == "subtraction" else "たし算からひき算" if first == "addition" else "ひき算からたし算")
    return f"{limit}までの{name}（繰り上がり{'あり' if carry else 'なし'}・繰り下がり{'あり' if borrowing else 'なし'}）"


def assess_three(records, user_id=None, now=None):
    """3つの数の4演算パターンを、通常計算・穴埋めと分けて評価する。"""
    return _assess_independent(records, "three_numbers", "three", three_category, three_label, user_id, now)


def three_word_category(record):
    return (record["story_type"], record["number_range"], bool(record.get("carry")), bool(record.get("borrowing")))


def three_word_label(key):
    story, limit, carry, borrowing = key
    names = {"increase_twice": "2回ふえる", "decrease_twice": "2回へる",
             "increase_then_decrease": "ふえてからへる", "decrease_then_increase": "へってからふえる"}
    return f"{limit}まで・3つの数の文章題（{names.get(story, story)}・繰り上がり{'あり' if carry else 'なし'}・繰り下がり{'あり' if borrowing else 'なし'}）"


def assess_three_word(records, user_id=None, now=None):
    """2演算・3数量・選んだ全式の計算を、旧文章題や3数計算と分ける。"""
    return _assess_independent(records, "three_word_problem", "three_word", three_word_category, three_word_label, user_id, now)


def _assess_independent(records, problem_format, prefix, key_of, label_of, user_id, now):
    from daily_review import _now, _time
    current = _now(now)
    summary_of = summarize_words if problem_format == "three_word_problem" else summarize
    rows = sorted((r for r in records if r.get("problem_format") == problem_format
                   and (user_id is None or r.get("user_id") == user_id)
                   and _time(r.get("datetime")) is not None and _time(r["datetime"]) <= current),
                  key=lambda r: (_time(r["datetime"]), str(r.get("attempt_id", ""))))
    unique, seen = [], set()
    for row in rows:
        identifier = row.get("attempt_id")
        if identifier and identifier in seen:
            continue
        if identifier:
            seen.add(identifier)
        unique.append(row)
    ordinary = [r for r in unique if r["selection_type"] not in ("review", "review_retry")]
    initial = [r for r in ordinary if r["selection_type"] == "normal" and r.get("attempt_count") == 1]
    retries = [r for r in ordinary if r["selection_type"] == "retry"]
    latest = {}
    for row in ordinary:
        latest[row.get("user_id"), row["problem_id"]] = row
    groups = []
    for key in sorted({key_of(r) for r in initial}):
        summary = summary_of([r for r in initial if key_of(r) == key])
        status = ("判断保留（5問未満）" if summary["count"] < 5 else "よくできています"
                  if summary["rate"] >= .9 else "もう少し練習" if summary["rate"] >= .8 else "優先して練習")
        groups.append({"key": key, "label": label_of(key), **summary, "status": status,
                       "hint_support": summary["hint_known_count"] >= 5 and summary["hint_rate"] >= .3,
                       "retry": summary_of([r for r in retries if key_of(r) == key]),
                       "latest": summary_of([r for r in latest.values() if key_of(r) == key])})
    weak = [g for g in groups if g["count"] >= 5 and (g["rate"] < .8 or g["hint_support"])]
    target = min(weak, key=lambda g: (g["rate"], -(g["hint_rate"] or 0), -g["count"])) if weak else None
    return {f"{prefix}_normal": summary_of(initial), f"{prefix}_retry": summary_of(retries),
            f"{prefix}_latest": summary_of(list(latest.values())), f"{prefix}_groups": groups,
            f"{prefix}_target": target["key"] if target else None,
            f"{prefix}_review": summary_of([r for r in unique if r["selection_type"] == "review"]),
            f"{prefix}_review_retry": summary_of([r for r in unique if r["selection_type"] == "review_retry"])}


def summarize_words(records):
    summary = summarize(records)
    for name, column in (("operation", "operation_selection_correct"), ("equation", "equation_correct"),
                         ("calculation", "calculation_correct")):
        evaluated = [row.get(column) for row in records if row.get(column) is not None]
        summary[f"{name}_count"] = len(evaluated)
        summary[f"{name}_correct"] = sum(bool(value) for value in evaluated)
        summary[f"{name}_rate"] = sum(bool(value) for value in evaluated) / len(evaluated) if evaluated else None
    return summary


def recommended_problems(report):
    """優先課題がある場合は、その属性に合う重複しない5問を出します。"""
    from learning import generate_problems

    if report["target"] is None:
        return generate_problems("mix", report["suggested_limit"])
    operation, limit, special = report["target"]
    pool = []
    for left in range(limit + 1):
        for right in range(limit + 1):
            if (left + right > limit if operation == "addition" else right > left):
                continue
            problem = make_problem(operation, limit, left, right)
            if category(problem) == (operation, limit, special):
                pool.append(problem)
    return random.sample(pool, min(5, len(pool)))
