"""起動: python -m streamlit run app.py"""

from pathlib import Path
from datetime import datetime, timezone, timedelta
import hmac
import os
import sqlite3
import streamlit as st
import streamlit.components.v1 as components

from learning import USERS, generate_problems, init_db, make_attempt, new_id, read_attempts, save_attempt
from assessment import assess, recommended_problems

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
    if st.button("学習履歴", key="history_settings", use_container_width=True):
        open_history("settings")
    if st.button("学習レポート", key="report_settings", use_container_width=True):
        open_report("settings")
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
    if st.button("学習履歴", key="history_practice", use_container_width=True):
        open_history("practice")
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
    if st.button("学習履歴", key="history_results", use_container_width=True):
        open_history("results")
    if st.button("学習レポート", key="report_results", use_container_width=True):
        open_report("results")
    if st.button("なまえを かえる"):
        st.session_state.screen = "user"
        st.rerun()


def open_history(return_screen):
    st.session_state.history_return = return_screen
    st.session_state.history_page = 0
    st.session_state.screen = "history"
    st.rerun()


def history_screen():
    st.subheader(f"{USERS[st.session_state.user_id]}の 学習履歴")
    if st.button("もどる", key="history_back"):
        st.session_state.screen = st.session_state.history_return
        st.rerun()
    if st.button("学習レポート", key="report_history", use_container_width=True):
        open_report("history")
    page = st.session_state.history_page
    try:
        records, has_more = read_attempts(st.session_state.user_id, page=page)
        table = []
        for record in records:
            answered_at = datetime.fromisoformat(record["datetime"]).astimezone(timezone(timedelta(hours=9)))
            table.append({
                "日時（日本時間）": answered_at.strftime("%Y/%m/%d %H:%M:%S"),
                "問題": record["question_text"], "自分の回答": record["user_answer"],
                "正しい答え": record["correct_answer"], "正誤": "○" if record["is_correct"] else "×",
                "練習": "初回" if record["selection_type"] == "normal" else "再練習",
                "出題順": record["question_order"], "回答回数": record["attempt_count"],
                "回答時間（秒）": record["response_time_sec"],
            })
    except (sqlite3.Error, OSError, ValueError, KeyError, TypeError):
        st.error("履歴を読み込めませんでした。もういちど試してください。")
        if st.button("読み込みをやりなおす", key="history_reload"):
            st.rerun()
        return
    if not table:
        st.info("まだ学習履歴がありません。れんしゅうすると、ここに表示されます。" if page == 0
                else "このページの履歴はありません。前のページにもどってください。")
    else:
        st.caption("新しい回答から50件ずつ表示します。表は横にスクロールできます。")
        st.dataframe(table, hide_index=True, use_container_width=True)
    st.caption(f"{page + 1} ページ")
    previous, following = st.columns(2)
    with previous:
        if st.button("前のページ", key="history_prev", disabled=page == 0, use_container_width=True):
            st.session_state.history_page -= 1
            st.rerun()
    with following:
        if st.button("次のページ", key="history_next", disabled=not has_more, use_container_width=True):
            st.session_state.history_page += 1
            st.rerun()


def open_report(return_screen):
    st.session_state.report_return = return_screen
    st.session_state.screen = "report"
    st.rerun()


def report_screen():
    st.subheader(f"{USERS[st.session_state.user_id]}の 学習レポート")
    if st.button("もどる", key="report_back"):
        st.session_state.screen = st.session_state.report_return
        st.rerun()
    st.caption("保護者向けの自動集計です。外部AIへの送信・AI利用料はありません。")
    try:
        records = []
        for page in range(5):
            batch, has_more = read_attempts(st.session_state.user_id, page=page, page_size=100)
            records.extend(batch)
            if not has_more:
                break
        report = assess(records)
        dates = [datetime.fromisoformat(row["datetime"]).astimezone(timezone(timedelta(hours=9)))
                 for row in records]
    except (sqlite3.Error, OSError, ValueError, KeyError, TypeError):
        st.error("レポートを読み込めませんでした。もういちど試してください。")
        if st.button("読み込みをやりなおす", key="report_reload"):
            st.rerun()
        return
    if records:
        st.caption(f"集計対象：{'直近' if has_more else '保存済み'}{len(records)}回答 ／ "
                   f"{min(dates):%Y/%m/%d}〜{max(dates):%Y/%m/%d}（日本時間）")
    else:
        st.info("まだ学習履歴がありません。れんしゅうすると、ここに表示されます。")
    overall = report["overall"]
    counts, accuracy, speed = st.columns(3)
    counts.metric("初回の回答", f"{overall['count']}問")
    accuracy.metric("初回正答率", f"{overall['rate']:.0%}" if overall["count"] else "—")
    speed.metric("正解時の回答時間", f"{overall['seconds']:.1f}秒" if overall["seconds"] is not None else "—")
    st.caption("回答時間は正解した初回回答の中央値です。休憩や操作の影響もあるため、速さで苦手を判定しません。")
    st.write("**現状の評価と次の練習**")
    st.info(report["message"])
    if report["strengths"]:
        st.success("得意な点：" + "、".join(report["strengths"]))
    if report["groups"]:
        table = [{"問題の種類": group["label"], "初回回答数": group["count"],
                  "正答率": f"{group['rate']:.0%}", "評価": group["status"],
                  "最近の変化": group["trend"]} for group in report["groups"]]
        st.dataframe(table, hide_index=True, use_container_width=True)
    retry = report["retry"]
    if retry["count"]:
        st.write(f"再練習では{retry['count']}問中{retry['correct']}問正解（{retry['rate']:.0%}）。"
                 "初回の正答率とは分けて表示しています。")
    with st.expander("評価の見方"):
        st.write("種類ごとに5問未満は判断保留、正答率90%以上は「よくできています」、"
                 "80%以上90%未満は「もう少し練習」、80%未満は「優先して練習」です。"
                 "学力の診断ではなく、このアプリで回答した問題の傾向です。")
        st.write("最近の変化は同じ数の範囲・演算・繰り上がり／繰り下がりの種類について、"
                 "直近10問とその前10問を比較します。最大500回答を集計し、再練習は習熟の判定に含めません。")
    label = "おすすめの5問を れんしゅう" if report["target"] else "ミックス10問を れんしゅう"
    if st.button(label, key="report_practice", type="primary", use_container_width=True):
        st.session_state.attempt_counts = {}
        start_round(recommended_problems(report), "normal")
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
           "practice": practice_screen, "results": results_screen, "history": history_screen,
           "report": report_screen}
screens[st.session_state.screen]()
