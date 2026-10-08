"""3つの数を左から計算する教材。途中・最後も設定範囲内に保つ。"""

import random

from learning import make_problem, problem_pool

OPERATIONS = ("addition", "subtraction")
PATTERNS = tuple((first, second) for first in OPERATIONS for second in OPERATIONS)


def _calculate(operation, left, right):
    return left + right if operation == "addition" else left - right


def make_three_problem(op1, op2, limit, a, b, c):
    if (op1 not in OPERATIONS or op2 not in OPERATIONS
            or type(limit) is not int or limit not in (10, 20)
            or any(type(n) is not int or not 0 <= n <= limit for n in (a, b, c))):
        raise ValueError("3つの数の学習条件が不正です。")
    intermediate = _calculate(op1, a, b)
    result = _calculate(op2, intermediate, c)
    if not 0 <= intermediate <= limit or not 0 <= result <= limit:
        raise ValueError("途中の答えと最後の答えは設定した範囲内にしてください。")
    first = make_problem(op1, limit, a, b)
    second = make_problem(op2, limit, intermediate, c)
    additions = [p for p in (first, second) if p["operation"] == "addition"]
    subtractions = [p for p in (first, second) if p["operation"] == "subtraction"]
    first.update(
        problem_id=f"three_numbers_v1_{op1}_{op2}_{limit}_{a}_{b}_{c}",
        problem_format="three_numbers", third_operand=c, second_operation=op2,
        question_text=f"{a} {'+' if op1 == 'addition' else '−'} {b} {'+' if op2 == 'addition' else '−'} {c} = ?",
        correct_answer=result,
        carry=any(p["carry"] for p in additions) if additions else None,
        borrowing=any(p["borrowing"] for p in subtractions) if subtractions else None,
        crosses_10=first["crosses_10"] or second["crosses_10"],
        zero_included=0 in (a, b, c),
        doubles=any(p["doubles"] for p in additions),
        answer_is_10=result == 10,
        operand_contains_10=10 in (a, b, c),
        near_10=any(p["near_10"] for p in additions),
        commutative_pair=None,
    )
    return first


def three_pool(first_operation, limit, special="auto", second_operation=None):
    """共通pool入口。第二演算未指定時は両方を用意する。"""
    if (first_operation not in OPERATIONS or type(limit) is not int or limit not in (10, 20)
            or special not in ("auto", "none", "with")
            or (second_operation is not None and second_operation not in OPERATIONS)):
        raise ValueError("3つの数の学習条件が不正です。")
    seconds = OPERATIONS if second_operation is None else (second_operation,)
    items = []
    # 第1段階の条件だけで特殊計算を除外しない。第2段階も確認する。
    for base in problem_pool(first_operation, limit):
        a, b, intermediate = base["left_operand"], base["right_operand"], base["correct_answer"]
        for op2 in seconds:
            for c in range(limit + 1):
                result = _calculate(op2, intermediate, c)
                if not 0 <= result <= limit:
                    continue
                q = make_three_problem(first_operation, op2, limit, a, b, c)
                has_special = bool(q["carry"] or q["borrowing"])
                if special == "auto" or has_special == (special == "with"):
                    items.append(q)
    return items


def mode_pool(mode, limit, special="auto"):
    if mode == "addition":
        return three_pool("addition", limit, special, "addition")
    if mode == "subtraction":
        return three_pool("subtraction", limit, special, "subtraction")
    if mode == "mix":
        return three_pool("addition", limit, special) + three_pool("subtraction", limit, special)
    raise ValueError("3つの数の学習モードが不正です。")


def generate_three(mode, limit, count, special="auto"):
    """ミックスでは4パターンを順番に割り当て、候補不足は他で補う。"""
    if type(count) is not int or count < 1:
        raise ValueError("問題数が不正です。")
    pool = mode_pool(mode, limit, special)
    if len(pool) < count:
        raise ValueError(f"この条件では{len(pool)}問です。必要な{count}問に足りません。")
    if mode != "mix":
        return random.sample(pool, count)
    by_pattern = {pattern: [q for q in pool if (q["operation"], q["second_operation"]) == pattern]
                  for pattern in PATTERNS}
    patterns = [pattern for pattern in PATTERNS if by_pattern[pattern]]
    random.shuffle(patterns)
    quotas = {pattern: 0 for pattern in patterns}
    remaining = count
    while remaining:
        for pattern in patterns:
            if quotas[pattern] < len(by_pattern[pattern]):
                quotas[pattern] += 1
                remaining -= 1
                if not remaining:
                    break
    items = [q for pattern in patterns for q in random.sample(by_pattern[pattern], quotas[pattern])]
    random.shuffle(items)
    return items


def hint_steps(problem):
    # 最終答えは説明だけ。第3段階では途中の値までを足場にする。
    a, b, c = problem["left_operand"], problem["right_operand"], problem["third_operand"]
    op1, op2 = problem["operation"], problem["second_operation"]
    intermediate = _calculate(op1, a, b)
    return ["ひだりから じゅんばんに けいさんしよう。まず、はじめの 2つの かずを みよう。",
            f"まず {a} {'+' if op1 == 'addition' else '−'} {b} を けいさんしよう。",
            f"はじめの こたえは {intermediate} だよ。つぎに {intermediate} {'+' if op2 == 'addition' else '−'} {c} を けいさんしよう。"]


def guidance(problem, reveal=False):
    hint = hint_steps(problem)[0]
    if reveal:
        a, b, c = problem["left_operand"], problem["right_operand"], problem["third_operand"]
        op1, op2 = problem["operation"], problem["second_operation"]
        intermediate = _calculate(op1, a, b)
        result = _calculate(op2, intermediate, c)
        hint += (f" まず {a} {'+' if op1 == 'addition' else '−'} {b} = {intermediate}。"
                 f" つぎに {intermediate} {'+' if op2 == 'addition' else '−'} {c} = {result}。こたえは {result} だよ。")
    return hint
