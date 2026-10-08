"""元の計算式の左・右の数を隠す穴埋め教材。保存用IDは通常計算と分離。"""

from learning import make_problem, problem_pool

POSITIONS = ("left_operand", "right_operand")


def make_fill_problem(operation, limit, left, right, blank_position):
    """correct_answer は計算結果ではなく、□に入る隠れた数。"""
    if (operation not in ("addition", "subtraction") or type(limit) is not int or limit not in (10, 20)
            or blank_position not in POSITIONS
            or type(left) is not int or type(right) is not int
            or not 0 <= left <= limit or not 0 <= right <= limit
            or (left + right > limit if operation == "addition" else right > left)):
        raise ValueError("穴埋めの学習条件が不正です。")
    problem = make_problem(operation, limit, left, right)
    result = problem["correct_answer"]
    hidden = left if blank_position == "left_operand" else right
    sign = "+" if operation == "addition" else "−"
    displayed_left = "□" if blank_position == "left_operand" else str(left)
    displayed_right = "□" if blank_position == "right_operand" else str(right)
    problem.update(
        problem_id=f"fill_blank_v1_{operation}_{limit}_{blank_position}_{left}_{right}",
        problem_format="fill_blank", blank_position=blank_position,
        question_text=f"{displayed_left} {sign} {displayed_right} = {result}",
        correct_answer=hidden, answer_is_10=hidden == 10,
    )
    return problem


def fill_pool(operation, limit, special="auto"):
    """範囲・繰り上がり条件は□を隠す前の基礎式で判定する。"""
    return [make_fill_problem(operation, limit, p["left_operand"], p["right_operand"], position)
            for p in problem_pool(operation, limit, special) for position in POSITIONS]


def hint_steps(problem):
    """答えの数を明示せず、関係→具体物→逆の計算へ進む3段階。"""
    operation, position = problem["operation"], problem["blank_position"]
    if problem.get("problem_format") != "fill_blank" or position not in POSITIONS or operation not in ("addition", "subtraction"):
        raise ValueError("穴埋めの問題が不正です。")
    if operation == "addition":
        return ["□に どんな かずを いれると、あわせた かずに なるかな。",
                "あわせた かずの つみきを ならべよう。わかっている ぶんを よけると、□の ぶんが のこるよ。",
                "あわせた かずから、わかっている かずを ひこう。みつけた かずを □に いれて、たしざんを たしかめよう。"]
    if position == "left_operand":
        return ["はじめの かずが □だよ。ひいた ぶんと のこった ぶんを かんがえよう。",
                "のこった ぶんの つみきを ならべよう。ひいた ぶんを もどすと、はじめの かずに なるよ。",
                "のこった かずと ひいた かずを たそう。みつけた かずを □に いれて、ひきざんを たしかめよう。"]
    return ["ひく かずが □だよ。はじめの かずと のこった かずを くらべよう。",
            "はじめの かずの つみきを ならべよう。のこった ぶんを よけると、ひいた ぶんが わかるよ。",
            "はじめの かずから のこった かずを ひこう。みつけた かずを □に いれて、ひきざんを たしかめよう。"]


def guidance(problem, reveal=False):
    hint = hint_steps(problem)[0]
    if reveal:
        left, right = problem["left_operand"], problem["right_operand"]
        addition = problem["operation"] == "addition"
        result = left + right if addition else left - right
        hint += f" □は {problem['correct_answer']} だよ。ただしい しきは {left} {'+' if addition else '−'} {right} = {result} だよ。"
    return hint
