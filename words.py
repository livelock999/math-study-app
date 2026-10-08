"""短いひらがなの文章題。本文と分類を同じ問題として保存します。"""

from learning import make_problem, problem_pool

STORIES = {
    "increase": ("addition", "result", "りんごが {left}こ あります。{right}こ もらいました。いま なんこ ありますか。"),
    "decrease": ("subtraction", "result", "りんごが {left}こ あります。{right}こ たべました。のこりは なんこ ですか。"),
    "combine": ("addition", "result", "あかい つみきが {left}こ、あおい つみきが {right}こ あります。あわせて なんこ ですか。"),
    "separate": ("subtraction", "result", "いぬと ねこが ぜんぶで {left}ひき います。いぬは {right}ひき です。ねこは なんびき ですか。"),
    "compare": ("subtraction", "difference", "りんごが {left}こ、みかんが {right}こ あります。りんごは みかんより なんこ おおいですか。"),
    "difference": ("subtraction", "difference", "こどもが {left}にん います。いすは {right}こ あります。ひとりに いすが 1こ ひつようです。いすは あと なんこ いりますか。"),
    # left/right は本文の登場順ではなく、求める数の正しい計算式の順。
    "increase_start": ("subtraction", "start", "りんごを {right}こ もらったら、{left}こに なりました。はじめに りんごは なんこ ありましたか。"),
    "increase_change": ("subtraction", "change", "りんごが {right}こ ありました。いくつか もらって、{left}こに なりました。なんこ もらいましたか。"),
    "decrease_start": ("addition", "start", "りんごを {right}こ たべたら、{left}こ のこりました。はじめに りんごは なんこ ありましたか。"),
    "decrease_change": ("subtraction", "change", "りんごが {left}こ ありました。いくつか たべて、{right}こ のこりました。なんこ たべましたか。"),
}

INVERSE_STORIES = frozenset(("increase_start", "increase_change", "decrease_start", "decrease_change"))
POSITIVE_DIFFERENCE_STORIES = frozenset(("separate", "compare", "increase_start", "increase_change", "decrease_change"))


def make_word_problem(story_type, limit, left, right):
    if story_type not in STORIES or limit not in (10, 20):
        raise ValueError("文章題の種類または数の範囲が不正です。")
    operation, unknown, template = STORIES[story_type]
    if (type(left) is not int or type(right) is not int or not 1 <= left <= limit
            or not 1 <= right <= limit or (left + right > limit if operation == "addition" else right > left)
            or (story_type in POSITIVE_DIFFERENCE_STORIES and left == right)):
        raise ValueError("文章題の数量が不正です。")
    problem = make_problem(operation, limit, left, right)
    version = "word_v2" if story_type in INVERSE_STORIES else "word_v1"
    problem.update(problem_id=f"{version}_{story_type}_{limit}_{left}_{right}",
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
            if story_operation != operation or (story_type in POSITIVE_DIFFERENCE_STORIES and left == right):
                continue
            problems.append(make_word_problem(story_type, limit, left, right))
    return problems


def guidance(problem, reveal=False):
    """回答前は考える手がかりだけ、回答後は正しい式と答えも返します。"""
    hints = {
        "increase": "はじめの かずから、もらった ぶんだけ ふえるよ。",
        "decrease": "はじめに あった ものから、たべた ものを とりのぞいて みよう。",
        "combine": "あかと あおを ひとつに まとめて かぞえて みよう。",
        "separate": "ぜんぶの なかから いぬを のぞくと、ねこが のこるよ。",
        "compare": "りんごと みかんを 1こずつ くみにして、あまる かずを かんがえよう。",
        "difference": "こどもと いすを 1つずつ くみにして、いすの ない こどもの かずを かんがえよう。",
        "increase_start": "いまの かずから、もらった ぶんを もどすと、はじめの かずに なるよ。",
        "increase_change": "はじめの かずと いまの かずを くらべると、ふえた ぶんが わかるよ。",
        "decrease_start": "のこった ぶんと たべた ぶんを あわせると、はじめの かずに なるよ。",
        "decrease_change": "はじめの かずと のこった かずを くらべると、たべた ぶんが わかるよ。",
    }
    if problem["problem_format"] == "word_problem":
        hint = hints[problem["story_type"]]
    elif problem["operation"] == "addition":
        hint = ("10の まとまりを つくって、のこりの かずを かんがえよう。" if problem["carry"]
                else "はじめの かずから、もう ひとつの かずだけ すすんで かぞえよう。")
    else:
        hint = ("10の まとまりを ばらして、ひく かずを とりのぞこう。" if problem["borrowing"]
                else "はじめの かずから、ひく かずだけ もどって かぞえよう。")
    if reveal:
        sign = "+" if problem["operation"] == "addition" else "−"
        hint += f" ただしい しきは {problem['left_operand']} {sign} {problem['right_operand']} = {problem['correct_answer']} だよ。"
    return hint
