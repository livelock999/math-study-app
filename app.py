"""起動: python -m streamlit run app.py"""

from pathlib import Path
import hmac
import os
import sqlite3
import streamlit as st
import streamlit.components.v1 as components

from learning import USERS, generate_problems, init_db, make_attempt, new_id, save_attempt

st.set_page_config(page_title="さんすう れんしゅう", page_icon="🔢", layout="centered")
keyboard = components.declare_component("math_keyboard", path=str(Path(__file__).parent / "keyboard"))


def start_round(problems, selection_type):
    """再練習も独立したセット。回答回数だけは前のセットから引き継ぎます。"""
    st.session_state.round = {
        "session_id": new_id("session"), "problems": problems,
        "selection_type": selection_type, "index": 0, "answers": [],
        "phase": "question", "pending_record": None,
    }
    st.session_state.screen = "practice"


def save_pending_answer(state):
    """確定した回答を保存し、成功したときだけ正誤表示へ進みます。"""
    record = state["pending_record"]
    try:
        save_attempt(record)
    except (sqlite3.Error, OSError, ValueError):
        return False
    state["answers"].append(record)
    st.session_state.attempt_counts[record["problem_id"]] = record["attempt_count"]
    state["pending_record"] = None
    state["phase"] = "feedback"
    return True


def user_screen():
    st.subheader("だれが れんしゅうする？")
    for user_id, name in USERS.items():
        if st.button(name, key=f"select_{user_id}", type="primary", use_container_width=True):
            st.session_state.user_id = user_id
            st.session_state.screen = "settings"
            st.rerun()


def settings_screen():
    st.subheader(f"{USERS[st.session_state.user_id]}、なにを れんしゅうする？")
    modes = {"addition": "たしざん", "subtraction": "ひきざん", "mix": "ミックス"}
    mode = st.radio("もんだい", list(modes), format_func=modes.get, horizontal=True)
    limit = st.radio("かずの はんい", [10, 20], format_func=lambda n: f"{n}まで", horizontal=True)
    st.caption("1かい 10もん。まちがえた もんだいは あとで れんしゅうできるよ。")
    if st.button("れんしゅう スタート", type="primary", use_container_width=True):
        st.session_state.attempt_counts = {}
        start_round(generate_problems(mode, limit), "normal")
        st.rerun()
    if st.button("なまえを かえる"):
        st.session_state.screen = "user"
        st.rerun()


def practice_screen():
    state = st.session_state.round
    index = state["index"]
    problems = state["problems"]
    problem = problems[index]
    st.caption(f"{USERS[st.session_state.user_id]} ／ "
               f"{'もういちど れんしゅう' if state['selection_type'] == 'retry' else 'れんしゅう'}")
    st.progress(index / len(problems), text=f"{index + 1} / {len(problems)} もん")
    # 保存失敗中は入力を確定したままにし、前回のコンポーネント値に頼らず再試行します。
    if state["pending_record"] is not None:
        st.subheader(problem["question_text"])
        st.write(f"あなたの こたえ：{state['pending_record']['user_answer']}")
        st.error("きろくを ほぞんできませんでした。もういちど ボタンを おしてね。")
        if st.button("ほぞんを やりなおす", key="retry_save", type="primary"):
            if save_pending_answer(state):
                st.rerun()
        return
    token = f"{state['session_id']}:{index}:{state['phase']}"
    last_answer = state["answers"][-1] if state["phase"] == "feedback" else None
    event = keyboard(
        token=token, phase=state["phase"], question=problem["question_text"],
        correct=last_answer["is_correct"] if last_answer else None,
        answer=last_answer["user_answer"] if last_answer else None,
        last=index + 1 == len(problems), key="answer_keyboard", default=None,
    )
    # 古い画面から届いた値は無視し、保存後にだけ進行状態を変えます。
    if not isinstance(event, dict) or event.get("token") != token:
        return
    if state["phase"] == "question" and event.get("action") == "answer":
        answer = event.get("answer")
        seconds = event.get("response_time_sec")
        if type(answer) is not int or not 0 <= answer <= 999:
            st.error("すうじを いれてね")
            return
        if not isinstance(seconds, (int, float)) or not 0 <= seconds < float("inf"):
            return
        count = st.session_state.attempt_counts.get(problem["problem_id"], 0) + 1
        state["pending_record"] = make_attempt(
            problem, st.session_state.user_id, state["session_id"], index + 1,
            state["selection_type"], answer, seconds, count,
        )
        save_pending_answer(state)
        st.rerun()
    elif state["phase"] == "feedback" and event.get("action") == "next":
        if index + 1 == len(problems):
            st.session_state.screen = "results"
        else:
            state["index"] += 1
            state["phase"] = "question"
        st.rerun()


def results_screen():
    state = st.session_state.round
    correct = sum(record["is_correct"] for record in state["answers"])
    total = len(state["answers"])
    st.subheader("れんしゅう おわり！")
    st.write("もういちど れんしゅうの けっか" if state["selection_type"] == "retry" else "はじめの れんしゅうの けっか")
    st.metric("せいかい", f"{total}もんちゅう {correct}もん")
    st.metric("せいかいりつ", f"{correct / total:.0%}")
    mistakes = [problem for problem, record in zip(state["problems"], state["answers"])
                if not record["is_correct"]]
    if mistakes:
        if st.button("まちがえた もんだいを もういちど", type="primary", use_container_width=True):
            start_round(mistakes, "retry")
            st.rerun()
    else:
        st.success("ぜんぶ せいかい！ よく がんばったね！")
    if st.button("あたらしい 10もんを れんしゅう", use_container_width=True):
        st.session_state.screen = "settings"
        st.rerun()
    if st.button("なまえを かえる"):
        st.session_state.screen = "user"
        st.rerun()


def check_access():
    """公開時の家族用パスワード。ローカルでは設定しなければ不要です。"""
    def setting(name, default=""):
        if name in os.environ:
            return os.environ[name]
        try:
            return st.secrets.get(name, default)
        except FileNotFoundError:
            return default

    required = str(setting("MATH_REQUIRE_PASSWORD", "false")).lower() == "true"
    if not required:
        return
    password = str(setting("MATH_APP_PASSWORD"))
    if not password:
        st.error("公開用パスワードの設定が必要です。アプリ管理者に確認してください。")
        st.stop()
    if st.session_state.get("access_granted"):
        return
    with st.form("family_login"):
        st.subheader("おうちの パスワード")
        entered = st.text_input("パスワード", type="password", key="family_password")
        submitted = st.form_submit_button("ひらく", type="primary")
    if submitted:
        if hmac.compare_digest(entered.encode("utf-8"), password.encode("utf-8")):
            st.session_state.access_granted = True
            del st.session_state["family_password"]
            st.rerun()
        st.error("パスワードを たしかめてね")
    st.stop()


st.title("🔢 さんすう れんしゅう")
check_access()
try:
    init_db()
except ValueError as error:
    st.error(str(error))
    st.stop()
except (sqlite3.Error, OSError):
    st.error("履歴の保存先を開けません。保存先設定と data フォルダーの書き込み権限を確認してください。")
    st.stop()

if "screen" not in st.session_state:
    st.session_state.screen = "user"

screens = {"user": user_screen, "settings": settings_screen,
           "practice": practice_screen, "results": results_screen}
screens[st.session_state.screen]()
