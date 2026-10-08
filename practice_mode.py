"""保護者の操作確認を、このブラウザの一時状態だけに閉じ込めます。"""


def is_test_mode(session):
    return session.get("parent_test_mode") is True


def is_test_round(state, session):
    # セット開始時のモードを固定。通常モードに戻ってもテスト回答を保存しない。
    return state.get("test_mode") is True or is_test_mode(session)


def write_learning_answer(state, session, writer, record):
    if not is_test_round(state, session):
        writer(record)


def switch_mode(session, enabled):
    if type(enabled) is not bool:
        raise ValueError("モードは真偽値で指定してください。")
    visual_epoch = session.get("math_visuals_widget_epoch", 0)
    # 未送信回答・再練習・表示設定のプレビューを別モードへ持ち越さない。
    keys = {"round", "jp_round", "attempt_counts", "jp_counts", "jp_first_correct",
            "jp_chains", "user_id", "practice_count", "display_profiles", "answer_keyboard", "jp_keyboard",
            "math_visuals_enable", "math_visuals_preference", "fc_round", "fc_keyboard"}
    for key in list(session):
        if key in keys or key.startswith(("display_", "learning_goal_", "parent_goals_", "feedback_", "math_feedback_", "jp_feedback_", "school_scope_", "history_backup_", "math_visuals_", "fc_")):
            session.pop(key, None)
    # ブラウザーに残ったチェック状態も、別のウィジェットIDで引き継がせない。
    session["math_visuals_widget_epoch"] = visual_epoch + 1
    session["parent_test_mode"] = enabled
    session["screen"] = "user"
