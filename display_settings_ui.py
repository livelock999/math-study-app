"""両教科から開ける保護者用の漢字・読み方設定。"""

import sqlite3
import streamlit as st
from learning import USERS
from learning_profiles import MODES, effective_grade, school_year, save_profile
from text_display import session_profile
from practice_mode import is_test_mode


def settings_screen():
    user_id = st.session_state.user_id
    profile = session_profile(user_id)
    st.subheader(f"{USERS[user_id]}の 漢字・読み方設定")
    st.caption("算数・国語に共通の表示設定です。問題の難しさと、これまでの成績は引き継ぎます。")
    if st.button("もどる", key="display_back"):
        st.session_state.screen = st.session_state.get("display_return", "settings")
        st.rerun()
    if st.session_state.get(f"display_error_{user_id}"):
        st.error("保存した表示設定を読み込めませんでした。いまは小1の表示で開いています。")
        if st.button("設定を読み込み直す", key="display_reload"):
            st.session_state.display_profiles.pop(user_id, None)
            st.rerun()
    if st.session_state.pop("display_saved", False):
        st.success("テスト用の表示に切り替えました。設定は保存していません。" if is_test_mode(st.session_state)
                   else "両教科の表示設定を保存しました。")
    with st.form(f"display_form_{user_id}"):
        grade = st.selectbox("表示する学年", list(range(1, 7)), index=effective_grade(profile) - 1,
                             format_func=lambda n: f"小{n}", key=f"display_grade_{user_id}")
        auto = st.checkbox("毎年4月1日に自動進級する（小6まで）", value=profile["auto_advance"], key=f"display_auto_{user_id}")
        mode = st.radio("ふりがな", list(MODES), index=list(MODES).index(profile["furigana_mode"]),
                        format_func=MODES.get, key=f"display_furigana_{user_id}")
        unlearned = st.text_input("まだ習っていない漢字", value="".join(profile["unlearned"]),
                                 help="例：学校。指定した字を含む語は、ひらがなで表示します。128字まで。",
                                 key=f"display_unlearned_{user_id}")
        tap = st.checkbox("ふりがなのない言葉は、押して読み方を確認できる", value=profile["reading_tap"], key=f"display_tap_{user_id}")
        submitted = st.form_submit_button("保存せずに試す" if is_test_mode(st.session_state) else "両教科に保存", type="primary")
    st.caption("未習の漢字を含む語は、読みを確認した語単位でひらがなにします。"
               "「今年習う漢字だけ」は、その学年の漢字を含む語にふりがなを付けます。"
               "文字そのものを学ぶ国語問題は元の表記を守ります。")
    st.caption("自動進級は4月1日以降にアプリを開くと表示に適用します。解いている途中の問題は、次の問題から切り替わります。"
               "学習内容の難しさは自動変更しません。"
               "読み方を確認したことは、回答時にヒント使用・計算ミスと分けて記録します。")
    if submitted:
        updated = {"user_id": user_id, "grade": grade, "base_school_year": school_year(),
                   "auto_advance": auto, "furigana_mode": mode,
                   "unlearned": [c for c in unlearned if not c.isspace()], "reading_tap": tap}
        try:
            if not is_test_mode(st.session_state):
                save_profile(updated)
        except (OSError, ValueError, sqlite3.Error) as error:
            st.error(str(error) if isinstance(error, ValueError) else "保存できませんでした。設定は変更されていません。")
            return
        st.session_state.display_profiles[user_id] = updated
        st.session_state.pop(f"display_error_{user_id}", None)
        state = st.session_state.get("round")
        if state and state.get("user_id") == user_id:
            revisions = state.setdefault("interaction_revision", {})
            index = state["index"]
            revisions[index] = revisions.get(index, 0) + 1
        state = st.session_state.get("jp_round")
        if state and state.get("user_id") == user_id:
            state["resume_revision"] = state.get("resume_revision", 0) + 1
        st.session_state.display_saved = True
        st.rerun()
