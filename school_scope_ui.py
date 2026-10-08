"""保護者が子どもごとの学校範囲を保存・試用する画面。"""
import sqlite3
import streamlit as st
from learning import USERS
from practice_mode import is_test_mode
import school_scope as scope


def settings_screen():
    user_id = st.session_state.user_id
    st.subheader(f"{USERS[user_id]}の 学校で習っている範囲")
    if st.button("もどる", key="school_scope_back"):
        st.session_state.screen = st.session_state.get("school_scope_return", "settings")
        st.rerun()
    st.caption("保存した範囲は『おまかせで れんしゅう』に使います。問題数と算数の計算・文章題は練習画面で選べます。手動スタートはこれまでの条件で練習できます。")
    st.info("復習では、今の範囲に加えて、以前このお子さまが解いた問題も使います。成績や復習日は引き継ぎます。")
    cache = st.session_state.setdefault("school_scope_loaded", {})
    if user_id not in cache:
        try:
            cache[user_id] = scope.active_scope(user_id, st.session_state)
        except (sqlite3.Error, OSError, ValueError):
            st.error("学校の範囲を読み込めませんでした。接続と学校範囲の追加SQLを確認してください。")
            if st.button("読み込みをやりなおす", key="school_scope_reload"):
                st.rerun()
            return
    current = cache[user_id]
    pending = st.session_state.get("school_scope_pending", {}).get(user_id)
    with st.form(f"school_scope_form_{user_id}"):
        math = st.selectbox("算数で習っている単元", list(scope.MATH_UNITS),
                            index=list(scope.MATH_UNITS).index(current["math_unit"]),
                            format_func=lambda key: scope.MATH_UNITS[key][0], key=f"school_scope_math_{user_id}", disabled=bool(pending))
        japanese = st.selectbox("国語で習っている分野", list(scope.JP_UNITS),
                                index=list(scope.JP_UNITS).index(current["japanese_unit"]),
                                format_func=scope.JP_UNITS.get, key=f"school_scope_japanese_{user_id}", disabled=bool(pending))
        submitted = st.form_submit_button("保存せずに範囲を試す" if is_test_mode(st.session_state) else "学校の範囲を保存",
                                         disabled=bool(pending), use_container_width=True)
    if submitted:
        pending = scope.validate(user_id, math, japanese)
        st.session_state.setdefault("school_scope_pending", {})[user_id] = pending
    retry = False
    if pending and not submitted:
        st.error("学校の範囲を保存できませんでした。入力を保持し、同じ内容で再試行できます。")
        retry = st.button("学校の範囲の保存をやりなおす", key="school_scope_retry")
    if submitted or retry:
        try:
            saved = scope.save_scope(**pending, test_mode=is_test_mode(st.session_state))
        except (sqlite3.Error, OSError, ValueError):
            st.error("学校の範囲を保存できませんでした。入力を保ったまま、再試行できます。")
            if submitted:
                st.rerun()
        else:
            cache[user_id] = saved
            st.session_state.school_scope_pending.pop(user_id, None)
            if is_test_mode(st.session_state):
                st.session_state.setdefault("school_scope_preview", {})[user_id] = saved
                st.success("このブラウザで範囲を試せます。保存していません。テスト終了で元に戻ります。")
            else:
                st.success("学校で習っている範囲を保存しました。次のおまかせ練習から使います。")
