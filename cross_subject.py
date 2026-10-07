"""科目別の保存済み回答を、同じ期間・学習者で比較します。"""

from datetime import datetime, timedelta
import learning
import japanese
from activity import JST


def load_records(user_id):
    """両科目とも全ページ取得。片方が失敗したら部分レポートを返さない。"""
    if user_id not in learning.USERS:
        raise ValueError("学習者が不正です。")
    math, page = [], 0
    while True:
        batch, more = learning.read_attempts(user_id, page=page, page_size=100)
        math.extend(batch)
        if not more:
            break
        page += 1
    japanese.init_db()
    return math, japanese.read_all(user_id)


def summarize(rows):
    correct = sum(row["correct"] for row in rows)
    return {"count": len(rows), "correct": correct,
            "rate": correct / len(rows) if rows else None}


def build_report(math_records, japanese_records, user_id, days=30, now=None):
    if user_id not in learning.USERS or days not in (7, 30, None):
        raise ValueError("集計条件が不正です。")
    now = (now or datetime.now(JST)).astimezone(JST)
    start = (now.replace(hour=0, minute=0, second=0, microsecond=0)
             - timedelta(days=days - 1)) if days else None
    selected = {"math": [], "japanese": []}
    for subject, records in (("math", math_records), ("japanese", japanese_records)):
        seen = set()
        for record in records:
            if record["user_id"] != user_id or record["attempt_id"] in seen:
                continue
            seen.add(record["attempt_id"])
            at = datetime.fromisoformat(record["datetime"]).astimezone(JST)
            if at > now or (start is not None and at < start):
                continue
            initial = (record["selection_type"] == "normal" if subject == "math" else
                       record["attempt_count"] == 1 and record["selection_type"] != "retry")
            selected[subject].append({"at": at, "initial": initial,
                                      "correct": bool(record["is_correct"] if subject == "math" else record["correct"]),
                                      "source": record})

    subjects, daily = {}, {}
    for subject, rows in selected.items():
        initial = [r for r in rows if r["initial"]]
        retry = [r for r in rows if r["source"]["selection_type"] == "retry"]
        subjects[subject] = {"total": len(rows), "days": len({r["at"].date() for r in rows}),
                             "initial": summarize(initial), "retry": summarize(retry)}
        for row in rows:
            day = daily.setdefault(row["at"].date(), {"math": 0, "japanese": 0})
            day[subject] += 1

    math_initial = [r for r in selected["math"] if r["initial"]]
    jp_initial = [r for r in selected["japanese"] if r["initial"]]
    calculations = [r for r in math_initial if r["source"]["problem_format"] == "calculation"]
    words = [r for r in math_initial if r["source"]["problem_format"] == "word_problem"]
    reading = [r for r in jp_initial if r["source"]["category"] in ("sentence", "information", "passage")
               and r["source"]["reading_mode"] == "self_read"]
    groups = [{"label": "算数：計算問題", **summarize(calculations)},
              {"label": "算数：文章題の全体正解", **summarize(words)}]
    for label, field in (("算数：文章題のたす・ひく選択", "operation_selection_correct"),
                         ("算数：文章題の式に使う数・順序", "equation_correct"),
                         ("算数：文章題の選んだ式の計算", "calculation_correct")):
        evaluated = [{"correct": bool(r["source"][field])} for r in words if r["source"].get(field) is not None]
        groups.append({"label": label, **summarize(evaluated)})
    groups.append({"label": "国語：自力読みの読解（1文・情報抽出・短文）", **summarize(reading)})
    particle_records = [r["source"] for r in selected["japanese"] if r["source"]["category"] == "particles"
                        and r["source"]["reading_mode"] == "self_read"]
    particles = [r for r in jp_initial if r["source"]["category"] == "particles"
                 and r["source"]["reading_mode"] == "self_read"]
    groups.append({"label": "国語：てにをは（助詞）", **summarize(particles)})
    suggestions = []
    for group in groups:
        group["status"] = ("判断保留（5問未満）" if group["count"] < 5 else
                           "練習を提案" if group["rate"] < .8 else "練習を継続")
    if groups[0]["count"] >= 5 and groups[0]["rate"] < .8:
        suggestions.append("算数の計算問題を5問練習し、計算の手順を確認しましょう。")
    if any(g["count"] >= 5 and g["rate"] < .8 for g in groups[2:4]):
        suggestions.append("文章題を5問練習し、増える・減ると、式に使う数を一緒に確認しましょう。")
    if groups[4]["count"] >= 5 and groups[4]["rate"] < .8:
        suggestions.append("文章題で自分が作った式の計算を、1問ずつ確認しましょう。")
    if groups[5]["count"] >= 5 and groups[5]["rate"] < .8:
        suggestions.append("国語の1文読解・だれ／なに／どこ・短文読解から5問練習しましょう。")
    if groups[6]["count"] >= 5 and groups[6]["rate"] < .8:
        suggestions.append("てにをはで、行き先の「に」と動作する場所の「で」などを比べて練習しましょう。")
    if not suggestions:
        suggestions.append("5問未満の項目は回答を増やし、5問以上の項目は今の練習を続けましょう。")
    dates = [r["at"] for rows in selected.values() for r in rows]
    return {"subjects": subjects, "daily": daily, "groups": groups, "suggestions": suggestions,
            "total": len(dates), "days": len(daily), "start": start, "end": now,
            "particle_records": particle_records,
            "first": min(dates) if dates else None, "last": max(dates) if dates else None}
