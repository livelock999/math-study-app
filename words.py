"""短いひらがなの文章題。本文と分類を同じ問題として保存します。"""

from learning import make_problem, problem_pool

STORIES = {
    "increase": ("addition", "result", "りんごが {left}こ あります。{right}こ もらいました。いま なんこ ありますか。"),
    "decrease": ("subtraction", "result", "りんごが {left}こ あります。{right}こ たべました。のこりは なんこ ですか。"),
    "combine": ("addition", "result", "あかい つみきが {left}こ、あおい つみきが {right}こ あります。あわせて なんこ ですか。"),
    "separate": ("subtraction", "result", "いぬと ねこが ぜんぶで {left}ひき います。いぬは {right}ひき です。ねこは なんびき ですか。"),
    "compare": ("subtraction", "difference", "りんごが {left}こ、みかんが {right}こ あります。りんごは みかんより なんこ おおいですか。"),
    "difference": ("subtraction", "difference", "こどもが {left}にん います。いすは {right}こ あります。ひとりに いすが 1こ ひつようです。いすは あと なんこ いりますか。"),
}


def make_word_problem(story_type, limit, left, right):
    if story_type not in STORIES or limit not in (10, 20):
        raise ValueError("文章題の種類または数の範囲が不正です。")
    operation, unknown, template = STORIES[story_type]
    if (type(left) is not int or type(right) is not int or not 1 <= left <= limit
            or not 1 <= right <= limit or (left + right > limit if operation == "addition" else right > left)
            or (story_type in ("separate", "compare") and left == right)):
        raise ValueError("文章題の数量が不正です。")
    problem = make_problem(operation, limit, left, right)
    problem.update(problem_id=f"word_v1_{story_type}_{limit}_{left}_{right}",
                   problem_format="word_problem", story_type=story_type, unknown_type=unknown,
                   question_text=template.format(left=left, right=right))
    return problem


def word_pool(operation, limit, special="auto"):
    problems = []
    for calculation in problem_pool(operation, limit, special):
        left, right = calculation["left_operand"], calculation["right_operand"]
        if left == 0 or right == 0:
            continue
        for story_type, (story_operation, _, _) in STORIES.items():
            if story_operation != operation or (story_type in ("separate", "compare") and left == right):
                continue
            problems.append(make_word_problem(story_type, limit, left, right))
    return problems
