"""保存済み通常回答から、次のセットの難易度を穏やかに選ぶ。書き込みなし。

難易度は能力の診断ではなく教材内の目安。設定ごと・日本時間の日ごとに
最大一段階。復習/再練習/未保存のテスト回答は判定に混ぜない。
"""

from collections import defaultdict
import random

from daily_review import eligible_records, _time
from learning import problem_pool
from words import word_pool
from japanese_questions import QUESTIONS, CATEGORIES


def math_level(problem):
    if problem.get("carry") or problem.get("borrowing"):
        return 3
    largest = max(problem["left_operand"], problem["right_operand"], problem["correct_answer"])
    if problem["number_range"] == 10:
        return 1 if largest <= 3 else 2 if largest <= 6 else 3
    return 1 if largest <= 10 else 2


def _ordinary(records, user_id, subject, now):
    identifier = "problem_id" if subject == "math" else "question_id"
    return [r for r in eligible_records(records, user_id, now)
            if r.get("selection_type") == "normal" and r.get("attempt_count") == 1
            and r.get(identifier) and not r.get("test_mode")]


def _decide(rows, pool, subject):
    """当日最初の通常回答を教材ごとに一つ使う。再挑戦で段階を稼がない。"""
    identifier = "problem_id" if subject == "math" else "question_id"
    correct = "is_correct" if subject == "math" else "correct"
    level_of = math_level if subject == "math" else lambda q: q["difficulty"]
    levels = sorted({level_of(q) for q in pool})
    level = levels[0]
    by_id = {q[identifier]: q for q in pool}
    days = defaultdict(dict)
    for row in rows:
        if row[identifier] in by_id:
            days[_time(row["datetime"]).date()].setdefault(row[identifier], row)
    message = "履歴が少ないため、基本の問題から始めます。"
    evidence = 0
    pending = []
    for date in sorted(days):
        matched = [r for key, r in days[date].items() if level_of(by_id[key]) == level]
        needed = min(5, sum(level_of(q) == level for q in pool))
        # 最初に必要件数が揃った時点を固定。後の同日回答で今日の判定を覆さない。
        pending.extend(matched[:max(0, needed - len(pending))])
        if needed < 3 or len(pending) < needed:
            continue
        recent = pending
        pending = []  # 判定済みの証拠を次の学習日に再利用しない。
        evidence = len(recent)
        misses = sum(r.get(correct) in (False, 0) or bool(r.get("dont_know_used")) for r in recent)
        hints = sum(bool(r.get("hint_used")) or bool(r.get("hint_level")) for r in recent)
        independent = sum(r.get(correct) in (True, 1) and r.get("hint_used") in (False, 0)
                          and not r.get("hint_level") and not r.get("dont_know_used") for r in recent)
        position = levels.index(level)
        if misses / evidence >= .4 or hints / evidence >= .6:
            level = levels[max(0, position - 1)]
            message = f"{date}までの通常練習で、誤答やヒント使用が多かったため、基本を確かめます。"
        elif independent / evidence >= .8:
            level = levels[min(len(levels) - 1, position + 1)]
            message = f"{date}までの通常練習で、自力正解が8割以上だったため、少し考える問題に進みます。"
            if position == len(levels) - 1:
                message = f"{date}までの通常練習で自力正解が多く、現在の難しさを続けます。"
        else:
            message = f"{date}までの通常練習をもとに、現在の難しさで確かめます。"
    return {"level": level, "reason": message, "evidence_count": evidence}


def _pick(pool, target, count, level_of, identifier, rows, rng):
    seen = {r[identifier] for r in rows}
    shuffled = list(pool)
    rng.shuffle(shuffled)
    # 同じ段階を優先。不足分は近い段階、同距離ならやさしい方。段階内は未回答優先。
    shuffled.sort(key=lambda q: (abs(level_of(q) - target), level_of(q), q[identifier] in seen))
    return shuffled[:count]


def _message(items, count):
    if not items:
        return "この条件の問題を用意できませんでした。"
    if len(items) < count:
        return f"同じ問題を重ねず、用意できる{len(items)}問で始めます。"
    return ""


def plan_math(records, user_id, mode="addition", limit=10, count=10, special="auto",
              problem_format="calculation", now=None, rng=None):
    if mode not in ("addition", "subtraction", "mix") or type(count) is not int or count not in (5, 10, 20):
        raise ValueError("算数の出題設定が不正です。")
    if problem_format not in ("calculation", "word_problem"):
        raise ValueError("問題の形式が不正です。")
    rows = _ordinary(records, user_id, "math", now)
    pool_fn = problem_pool if problem_format == "calculation" else word_pool
    operations = ("addition", "subtraction") if mode == "mix" else (mode,)
    rng = rng or random.Random()
    items, decisions = [], {}
    for operation in operations:
        pool = pool_fn(operation, limit, special)
        if not pool:
            continue
        relevant = [r for r in rows if r.get("operation") == operation
                    and r.get("number_range") == limit and r.get("problem_format") == problem_format]
        decision = _decide(relevant, pool, "math")
        decisions[operation] = decision
        needed = count if mode != "mix" else (count + 1) // 2 if operation == "addition" else count // 2
        items.extend(_pick(pool, decision["level"], needed, math_level, "problem_id", relevant, rng))
    rng.shuffle(items)
    return {"items": items, "decisions": decisions, "message": _message(items, count)}


def plan_japanese(records, user_id, category="mix", count=10, particle_level=None, now=None, rng=None, particle_ceiling=None):
    if category not in (*CATEGORIES, "mix") or count not in (5, 10) or particle_level not in (None, 1, 2, 3):
        raise ValueError("国語の出題設定が不正です。")
    if particle_ceiling not in (None, 1, 2, 3):
        raise ValueError("てにをはの学校範囲が不正です。")
    rows = _ordinary(records, user_id, "japanese", now)
    rng = rng or random.Random()
    # 手動てにをは分野は指定レベル一致。学校の範囲は上限として別に適用。
    pool = [q for q in QUESTIONS if (category == "mix" or q["category"] == category)
            and (q["category"] != "particles" or particle_level is None
                 or (q["level"] == particle_level if category == "particles" else q["level"] <= particle_level))
            and (q["category"] != "particles" or particle_ceiling is None or q["level"] <= particle_ceiling)]
    groups = {key: [q for q in pool if q["category"] == key] for key in CATEGORIES}
    groups = {key: value for key, value in groups.items() if value}
    decisions, queues = {}, {}
    for key, candidates in groups.items():
        relevant = [r for r in rows if r.get("category") == key]
        decisions[key] = _decide(relevant, candidates, "japanese")
        queues[key] = _pick(candidates, decisions[key]["level"], len(candidates),
                            lambda q: q["difficulty"], "question_id", relevant, rng)
    # おまかせ分野では偏りを抑える。教材が少ない分野は他の分野で補充する。
    keys = list(queues)
    rng.shuffle(keys)
    items = []
    while len(items) < count and any(queues.values()):
        for key in keys:
            if queues[key] and len(items) < count:
                items.append(queues[key].pop(0))
    return {"items": items, "decisions": decisions, "message": _message(items, count)}


def show_reason(plan, subject):
    """画面から呼ぶ任意表示。判定・選定関数はStreamlitを読み込まない。"""
    if not plan:
        return
    import streamlit as st
    if plan.get("message"):
        st.info(plan["message"])
    labels = {"addition": "たし算", "subtraction": "ひき算"} if subject == "math" else CATEGORIES
    with st.expander("保護者向け：おまかせ難易度の理由"):
        if plan.get("scope_label"):
            st.write(f"学校で習う範囲：{plan['scope_label']}")
        for key, decision in plan["decisions"].items():
            st.write(f"{labels[key]}：段階{decision['level']} — {decision['reason']}")
        st.caption("教材内の目安です。分野・条件ごとに通常の初回回答だけで判断し、日本時間の1日につき最大1段階。セット中は変えません。復習・再練習・保護者テストは判定対象外です。候補が足りない場合は近い段階で補います。")
