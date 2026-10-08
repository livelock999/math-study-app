"""日本時間の日別学習と、保存済みの完了スタンプを集計します。"""

from datetime import datetime, timezone, timedelta

JST = timezone(timedelta(hours=9))


def month_summary(records, year, month):
    days = {}
    completed_sessions = set()
    for record in records:
        answered_at = datetime.fromisoformat(record["datetime"]).astimezone(JST)
        if (answered_at.year, answered_at.month) != (year, month):
            continue
        day = days.setdefault(answered_at.day, {
            "count": 0, "correct": 0, "normal_count": 0, "normal_correct": 0,
            "retry_count": 0, "retry_correct": 0, "review_count": 0, "review_correct": 0,
            "review_retry_count": 0, "review_retry_correct": 0, "stamps": 0,
        })
        day["count"] += 1
        day["correct"] += bool(record["is_correct"])
        selection = record["selection_type"]
        if selection in ("normal", "retry", "review", "review_retry"):
            day[f"{selection}_count"] += 1
            day[f"{selection}_correct"] += bool(record["is_correct"])
        size = record.get("round_size")
        if (record.get("round_completed") and type(size) is int and size > 0
                and record["question_order"] == size and record["session_id"] not in completed_sessions):
            completed_sessions.add(record["session_id"])
            day["stamps"] += 1
    return {"days": days, "stamps": len(completed_sessions)}
