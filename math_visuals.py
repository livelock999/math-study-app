"""20までの数を、画面から独立した図のデータにします。"""


def visual_model(problem, reveal=False):
    """既知の数だけを丸で示し、未知の数の個数・長さは渡しません。

    穴埋めは式の3つの数量の関係を表示します。解答後のみ□も埋めます。
    文章題では演算選択の答えを示してしまうため、この図は使用しません。
    """
    if type(reveal) is not bool:
        raise ValueError("図の表示状態が不正です。")
    if problem.get("problem_format") == "three_numbers":
        from three_numbers import make_three_problem
        known = make_three_problem(problem.get("operation"), problem.get("second_operation"),
                                   problem.get("number_range"), problem.get("left_operand"),
                                   problem.get("right_operand"), problem.get("third_operand"))
        if problem.get("correct_answer") != known["correct_answer"]:
            raise ValueError("図にする問題の答えが不正です。")
        rows = [{"label": "はじめの かず", "count": known["left_operand"], "tone": "start"}]
        for operation, value, prefix in ((known["operation"], known["right_operand"], "さいしょに"),
                                         (known["second_operation"], known["third_operand"], "つぎに")):
            rows.append({"label": prefix + (" たす かず" if operation == "addition" else " とる かず"),
                         "count": value, "tone": "add" if operation == "addition" else "remove"})
        rows.append({"label": "さいごの かず", "count": known["correct_answer"] if reveal else None,
                     "tone": "result"})
        return {"rows": rows, "operation": known["operation"], "revealed": reveal,
                "caption": "ひだりから じゅんに、たしたり ひいたり しよう。まるは 1こずつ。"}
    if problem.get("problem_format") not in ("calculation", "fill_blank"):
        return None
    operation, limit = problem.get("operation"), problem.get("number_range")
    left, right = problem.get("left_operand"), problem.get("right_operand")
    if (operation not in ("addition", "subtraction") or limit not in (10, 20)
            or type(left) is not int or type(right) is not int
            or not 0 <= left <= limit or not 0 <= right <= limit
            or (left + right > limit if operation == "addition" else right > left)):
        raise ValueError("図にする問題の数が不正です。")
    position = problem.get("blank_position")
    if problem["problem_format"] == "fill_blank" and position not in ("left_operand", "right_operand"):
        raise ValueError("□の位置が不正です。")
    if problem["problem_format"] == "calculation":
        position = "answer"
    total = left + right if operation == "addition" else left - right
    labels = ("ひだりの かず", "たす かず", "あわせた かず") if operation == "addition" else (
        "はじめの かず", "とる かず", "のこりの かず")
    rows = []
    for field, value, label, tone in zip(
            ("left_operand", "right_operand", "answer"), (left, right, total), labels,
            ("start", "add" if operation == "addition" else "remove", "result")):
        rows.append({"label": label, "count": None if field == position and not reveal else value,
                     "tone": tone})
    return {"rows": rows, "operation": operation, "revealed": reveal,
            "caption": "まるは 1こずつ。10こで ひとまとまり。□の かずを かんがえよう。"}
