"""保存済みの回答を集計する、外部AIを使わない学習評価。"""

from statistics import median
import random

from learning import make_problem


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
    correct = sum(bool(row["is_correct"]) for row in records)
    times = [row["response_time_sec"] for row in records if row["is_correct"]]
    return {"count": len(records), "correct": correct,
            "rate": correct / len(records) if records else None,
            "seconds": median(times) if times else None}


def assess(records):
    """初回だけで習熟を評価。範囲・演算・繰り上がり等を揃えて比較します。"""
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
    return {"overall": summarize(normal), "retry": summarize(retries), "groups": groups,
            "strengths": strengths, "message": message,
            "target": target["key"] if target else None,
            "suggested_limit": max((row["number_range"] for row in normal), default=10),
            "word_normal": summarize_words([row for row in words if row["selection_type"] == "normal"]),
            "word_retry": summarize_words([row for row in words if row["selection_type"] == "retry"])}


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
