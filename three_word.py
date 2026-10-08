"""時間順の2つの出来事を、3つの数と2つの演算で解く文章題。"""

import random

from three_numbers import make_three_problem, three_pool, PATTERNS

STORIES = {
    "increase_twice": ("addition", "addition", "りんごが {a}こ あります。{b}こ もらいました。そのあと、また {c}こ もらいました。いま なんこ ありますか。"),
    "decrease_twice": ("subtraction", "subtraction", "りんごが {a}こ あります。{b}こ たべました。そのあと、また {c}こ たべました。のこりは なんこ ですか。"),
    "increase_then_decrease": ("addition", "subtraction", "りんごが {a}こ あります。{b}こ もらいました。そのあと、{c}こ たべました。のこりは なんこ ですか。"),
    "decrease_then_increase": ("subtraction", "addition", "りんごが {a}こ あります。{b}こ たべました。そのあと、{c}こ もらいました。いま なんこ ありますか。"),
}
_STORY_BY_PATTERN = {(v[0], v[1]): name for name, v in STORIES.items()}


def make_three_word_problem(story_type, limit, a, b, c):
    if (not isinstance(story_type, str) or story_type not in STORIES
            or any(type(n) is not int or n < 1 for n in (a, b, c))):
        raise ValueError("3つの数の文章題の種類または数量が不正です。")
    op1, op2, template = STORIES[story_type]
    problem = make_three_problem(op1, op2, limit, a, b, c)
    problem.update(problem_id=f"three_word_v1_{story_type}_{limit}_{a}_{b}_{c}",
                   problem_format="three_word_problem", story_type=story_type, unknown_type="result",
                   question_text=template.format(a=a, b=b, c=c))
    return problem


def three_word_pool(first, limit, special="auto", second_operation=None):
    return [make_three_word_problem(_STORY_BY_PATTERN[(q["operation"], q["second_operation"])],
                                   limit, q["left_operand"], q["right_operand"], q["third_operand"])
            for q in three_pool(first, limit, special, second_operation)
            if min(q["left_operand"], q["right_operand"], q["third_operand"]) >= 1]


def mode_pool(mode, limit, special="auto"):
    if mode == "addition":
        return three_word_pool("addition", limit, special, "addition")
    if mode == "subtraction":
        return three_word_pool("subtraction", limit, special, "subtraction")
    if mode == "mix":
        return three_word_pool("addition", limit, special) + three_word_pool("subtraction", limit, special)
    raise ValueError("3つの数の文章題の学習モードが不正です。")


def generate_three_word(mode, limit, count, special="auto"):
    if type(count) is not int or count < 1:
        raise ValueError("問題数が不正です。")
    pool = mode_pool(mode, limit, special)
    if len(pool) < count:
        raise ValueError(f"この条件では{len(pool)}問です。必要な{count}問に足りません。")
    if mode != "mix":
        return random.sample(pool, count)
    by_pattern = {p: [q for q in pool if (q["operation"], q["second_operation"]) == p] for p in PATTERNS}
    patterns = [p for p in PATTERNS if by_pattern[p]]
    random.shuffle(patterns)
    quotas = {p: 0 for p in patterns}
    remaining = count
    while remaining:
        for pattern in patterns:
            if quotas[pattern] < len(by_pattern[pattern]):
                quotas[pattern] += 1
                remaining -= 1
                if not remaining:
                    break
    result = [q for p in patterns for q in random.sample(by_pattern[p], quotas[p])]
    random.shuffle(result)
    return result


def hint_steps(problem):
    a, b, c = problem["left_operand"], problem["right_operand"], problem["third_operand"]
    first, second = problem["operation"], problem["second_operation"]
    first_verb, second_verb = ("もらう" if op == "addition" else "たべる" for op in (first, second))
    first_choice, second_choice = ("たす" if op == "addition" else "ひく" for op in (first, second))
    intermediate = a + b if first == "addition" else a - b
    return [f"はじめの かずから、まず {first_verb} ぶん、つぎに {second_verb} ぶんを じゅんに かんがえよう。",
            f"まずは {first_choice}。つぎは {second_choice}。できごとの じゅんばんで、{a}、{b}、{c}の かずを しきに いれよう。",
            f"まず {a} {'+' if first == 'addition' else '−'} {b} = {intermediate}。つぎに {intermediate} {'+' if second == 'addition' else '−'} {c} を けいさんしよう。"]


def guidance(problem, reveal=False):
    hint = hint_steps(problem)[0]
    if reveal:
        a, b, c = problem["left_operand"], problem["right_operand"], problem["third_operand"]
        first, second = problem["operation"], problem["second_operation"]
        intermediate = a + b if first == "addition" else a - b
        result = intermediate + c if second == "addition" else intermediate - c
        sign1, sign2 = "+" if first == "addition" else "−", "+" if second == "addition" else "−"
        hint += (f" ただしい しきは {a} {sign1} {b} {sign2} {c} = {result} だよ。"
                 f" まず {a} {sign1} {b} = {intermediate}。つぎに {intermediate} {sign2} {c} = {result}。こたえは {result} だよ。")
    return hint
