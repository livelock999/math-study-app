"""起動: python -m streamlit run app.py"""

from pathlib import Path
from datetime import datetime, timezone, timedelta
import hmac
import os
import sqlite3
import calendar
import streamlit as st
import streamlit.components.v1 as components

from learning import (USERS, generate_problems, init_db, make_attempt, new_id,
                      read_attempts, read_month_attempts, save_attempt, selection_error)
from assessment import assess, recommended_problems
from activity import JST, month_summary
from words import guidance

st.set_page_config(page_title="さんすう・こくご れんしゅう", page_icon="📚", layout="centered")
keyboard = components.declare_component("math_keyboard", path=str(Path(__file__).parent / "keyboard"))


def start_round(problems, selection_type):
    """再練習も独立したセット。回答回数だけは前のセットから引き継ぎます。"""
    if selection_type == "normal":
        st.session_state.practice_count = len(problems)
    st.session_state.round = {
        "session_id": new_id("session"), "problems": problems,
        "selection_type": selection_type, "index": 0, "answers": [],
        "phase": "choose" if problems[0]["problem_format"] == "word_problem" else "question",
        "pending_record": None, "selected_operations": {}, "user_equations": {}, "equation_revision": {},
        "user_id": st.session_state.user_id, "suspended": False, "drafts": {}, "interaction_revision": {},
    }
    st.session_state.screen = "practice"


def save_pending_answer(state):
    """確定した回答を保存し、成功したときだけ正誤表示へ進みます。"""
    record = state["pending_record"]
    # 更新前から練習中のセット・未保存回答も、実際の問題数を引き継ぎます。
    record.setdefault("round_size", len(state["problems"]))
    record.setdefault("round_completed", record["question_order"] == len(state["problems"]))
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
    previous_round = st.session_state.get("round")
    if (previous_round and previous_round.get("suspended")
            and previous_round.get("user_id") == st.session_state.user_id):
        if st.button("つづきから", key="math_resume", type="primary", use_container_width=True):
            previous_round["suspended"] = False
            st.session_state.screen = "practice"
            st.rerun()
        st.caption("スタートを押すとあたらしく始めます。これまで保存した回答は残ります。")
    modes = {"addition": "たしざん", "subtraction": "ひきざん", "mix": "ミックス"}
    mode = st.radio("もんだい", list(modes), format_func=modes.get, horizontal=True)
    limit = st.radio("かずの はんい", [10, 20], format_func=lambda n: f"{n}まで", horizontal=True)
    count = st.radio("もんだいの かず", [5, 10, 20], index=[5, 10, 20].index(st.session_state.get("practice_count", 10)),
                     format_func=lambda n: f"{n}もん", horizontal=True, key="problem_count")
    choices = {"auto": "おまかせ", "none": "なし", "with": "あり"}
    special = st.radio("くりあがり・くりさがり", list(choices), format_func=choices.get,
                       horizontal=True, key="special_mode")
    formats = {"calculation": "けいさん", "word_problem": "ぶんしょうだい"}
    problem_format = st.radio("もんだいの かたち", list(formats), format_func=formats.get,
                              horizontal=True, key="problem_format")
    error = selection_error(mode, limit, count, special, problem_format)
    if error:
        st.info(error)
    st.caption(f"1かい {count}もん。まちがえた もんだいは あとで れんしゅうできるよ。")
    if st.button("れんしゅう スタート", type="primary", use_container_width=True, disabled=bool(error)):
        st.session_state.attempt_counts = {}
        start_round(generate_problems(mode, limit, count, special, problem_format), "normal")
        st.rerun()
    if st.button("学習履歴", key="history_settings", use_container_width=True):
        open_history("settings")
    if st.button("学習レポート", key="report_settings", use_container_width=True):
        open_report("settings")
    if st.button("学習カレンダー・ごほうび", key="calendar_settings", use_container_width=True):
        open_calendar("settings")
    if st.button("なまえを かえる"):
        st.session_state.screen = "user"
        st.rerun()



def remember_practice_draft(state, index, event):
    """途中入力と、実際に問題画面で過ごした時間だけを引き継ぎます。"""
    draft = state["drafts"][index]
    incoming = event.get("draft", {})
    if not isinstance(incoming, dict):
        return False
    for name, max_length in (("answer", 3), ("equation_left", 2), ("equation_right", 2)):
        value = incoming.get(name, draft[name])
        if not isinstance(value, str) or len(value) > max_length or (value and not (value.isascii() and value.isdigit())):
            return False
    choice = incoming.get("selected_operation", draft["selected_operation"])
    if choice not in (None, "addition", "subtraction"):
        return False
    seconds = event.get("response_time_sec", draft["elapsed_sec"])
    if type(seconds) not in (int, float) or not 0 <= seconds < float("inf"):
        return False
    for name in ("answer", "equation_left", "equation_right"):
        draft[name] = incoming.get(name, draft[name])
    draft["selected_operation"] = choice
    draft["elapsed_sec"] = max(draft["elapsed_sec"], seconds)
    return True


def practice_screen():
    state = st.session_state.round
    state.setdefault("user_id", st.session_state.user_id)
    if state["user_id"] != st.session_state.user_id:
        st.session_state.screen = "settings"
        st.rerun()
    index = state["index"]
    problems = state["problems"]
    problem = problems[index]
    is_word = problem["problem_format"] == "word_problem"
    selected_operation = state.setdefault("selected_operations", {}).get(index)
    equation = state.setdefault("user_equations", {}).get(index)
    revision = state.setdefault("equation_revision", {}).get(index, 0)
    draft = state.setdefault("drafts", {}).setdefault(index, {
        "answer": "", "equation_left": "", "equation_right": "", "selected_operation": None,
        "elapsed_sec": 0, "hint_used": False, "hint_visible": False, "explanation_visible": False,
    })
    interaction_revision = state.setdefault("interaction_revision", {}).get(index, 0)
    st.caption(f"{USERS[st.session_state.user_id]} ／ "
               f"{'もういちど れんしゅう' if state['selection_type'] == 'retry' else 'れんしゅう'}")
    st.progress(index / len(problems), text=f"{index + 1} / {len(problems)} もん")
    # 保存失敗中は入力を確定したままにし、前回のコンポーネント値に頼らず再試行します。
    if state["pending_record"] is not None:
        st.subheader(problem["question_text"])
        st.write(f"あなたの こたえ：{state['pending_record']['user_answer']}")
        if state["pending_record"].get("user_equation"):
            st.write(f"じぶんの しき：{state['pending_record']['user_equation']}")
        st.error("きろくを ほぞんできませんでした。もういちど ボタンを おしてね。")
        st.caption("回答を保存してから戻れます。いまの回答はそのまま残しています。")
        if st.button("ほぞんを やりなおす", key="retry_save", type="primary"):
            if save_pending_answer(state):
                st.rerun()
        return
    # 更新前から回答中の文章題も、自分で式を作ってから答えます。
    if is_word and state["phase"] == "question" and equation is None:
        state["phase"] = "equation"
        st.rerun()
    token = f"{state['session_id']}:{index}:{state['phase']}"
    if is_word and revision:
        token += f":edit{revision}"
    if interaction_revision:
        token += f":ui{interaction_revision}"
    last_answer = state["answers"][-1] if state["phase"] == "feedback" else None
    event = keyboard(
        token=token, phase=state["phase"], question=problem["question_text"],
        correct=last_answer["is_correct"] if last_answer else None,
        answer=last_answer["user_answer"] if last_answer else None,
        last=index + 1 == len(problems), key="answer_keyboard", default=None,
        word_problem=is_word, question_id=f"{state['session_id']}:{index}",
        equation=(f"{equation['left']} {'+' if equation['operation'] == 'addition' else '−'} {equation['right']} = ?"
                  if is_word and equation and state["phase"] != "equation" else None),
        selected_operation=selected_operation,
        equation_left=equation["left"] if equation else None,
        equation_right=equation["right"] if equation else None,
        draft=draft, elapsed_sec=draft["elapsed_sec"], hint_used=draft["hint_used"],
        hint_visible=draft["hint_visible"], explanation_visible=draft["explanation_visible"],
        hint_text=guidance(problem),
        explanation_text=guidance(problem, reveal=True) if state["phase"] == "feedback" else None,
    )
    # 古い画面から届いた値は無視し、保存後にだけ進行状態を変えます。
    if not isinstance(event, dict) or event.get("token") != token:
        return
    if not remember_practice_draft(state, index, event):
        return
    action = event.get("action")
    if action in ("pause", "open_history", "show_hint", "show_explanation"):
        if action == "show_hint" and state["phase"] != "feedback":
            draft["hint_used"] = True
            draft["hint_visible"] = True
        elif action == "show_explanation" and state["phase"] == "feedback":
            draft["explanation_visible"] = True
        elif action == "pause":
            state["suspended"] = True
            st.session_state.screen = "settings"
        elif action == "open_history":
            st.session_state.history_return = "practice"
            st.session_state.history_page = 0
            st.session_state.screen = "history"
        else:
            return
        state["interaction_revision"][index] = interaction_revision + 1
        st.rerun()
    elif state["phase"] == "choose" and action == "choose_operation":
        choice = event.get("selected_operation")
        if is_word and choice in ("addition", "subtraction"):
            state["selected_operations"][index] = choice
            state["phase"] = "equation"
            st.rerun()
    elif state["phase"] == "equation" and event.get("action") == "submit_equation":
        left, right = event.get("equation_left"), event.get("equation_right")
        choice = event.get("selected_operation")
        if (not is_word or choice not in ("addition", "subtraction")
                or type(left) is not int or type(right) is not int or not 0 <= left <= 99 or not 0 <= right <= 99):
            st.error("しきの 2つの すうじを いれてね")
            return
        state["selected_operations"][index] = choice
        state["user_equations"][index] = {"left": left, "right": right, "operation": choice}
        state["phase"] = "question"
        st.rerun()
    elif state["phase"] == "question" and is_word and event.get("action") == "edit_equation":
        state["equation_revision"][index] = revision + 1
        state["phase"] = "equation"
        st.rerun()
    elif state["phase"] == "question" and event.get("action") == "answer":
        if is_word and selected_operation not in ("addition", "subtraction"):
            return
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
            round_size=len(problems),
            selected_operation=selected_operation,
            equation_left=equation["left"] if is_word else None,
            equation_right=equation["right"] if is_word else None,
            hint_used=draft["hint_used"],
        )
        save_pending_answer(state)
        st.rerun()
    elif state["phase"] == "feedback" and event.get("action") == "next":
        if index + 1 == len(problems):
            st.session_state.screen = "results"
        else:
            state["index"] += 1
            state["phase"] = "choose" if problems[index + 1]["problem_format"] == "word_problem" else "question"
        st.rerun()


def results_screen():
    state = st.session_state.round
    correct = sum(record["is_correct"] for record in state["answers"])
    total = len(state["answers"])
    st.subheader("れんしゅう おわり！")
    st.write("もういちど れんしゅうの けっか" if state["selection_type"] == "retry" else "はじめの れんしゅうの けっか")
    st.metric("せいかい", f"{total}もんちゅう {correct}もん")
    st.metric("せいかいりつ", f"{correct / total:.0%}")
    if state["answers"][-1].get("round_completed"):
        st.success("⭐ ごほうびスタンプを 1こ もらったよ！")
    mistakes = [problem for problem, record in zip(state["problems"], state["answers"])
                if not record["is_correct"]]
    if mistakes:
        if st.button("まちがえた もんだいを もういちど", type="primary", use_container_width=True):
            start_round(mistakes, "retry")
            st.rerun()
    else:
        st.success("ぜんぶ せいかい！ よく がんばったね！")
    new_count = st.session_state.get("practice_count", 10)
    if st.button(f"あたらしい {new_count}もんを れんしゅう", key="new_practice", use_container_width=True):
        st.session_state.screen = "settings"
        st.rerun()
    if st.button("学習履歴", key="history_results", use_container_width=True):
        open_history("results")
    if st.button("学習レポート", key="report_results", use_container_width=True):
        open_report("results")
    if st.button("学習カレンダー・ごほうび", key="calendar_results", use_container_width=True):
        open_calendar("results")
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
    if st.button("学習カレンダー・ごほうび", key="calendar_history", use_container_width=True):
        open_calendar("history")
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
                "形式": "文章題" if record["problem_format"] == "word_problem" else "計算",
                "たす・ひくの選択": correctness(record["operation_selection_correct"]),
                "自分の式": record.get("user_equation") or "—（記録なし）",
                "式に使う数・順序": correctness(record["equation_correct"]),
                "選んだ式の計算": correctness(record["calculation_correct"]),
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


def correctness(value):
    return "—（未評価）" if value is None else "○" if value else "×"


def open_calendar(return_screen):
    st.session_state.calendar_return = return_screen
    st.session_state.screen = "calendar"
    st.rerun()


def calendar_screen():
    st.subheader(f"{USERS[st.session_state.user_id]}の 学習カレンダー")
    if st.button("もどる", key="calendar_back"):
        st.session_state.screen = st.session_state.calendar_return
        st.rerun()
    today = datetime.now(JST)
    year_column, month_column = st.columns(2)
    year = year_column.number_input("年", min_value=2000, max_value=2100, value=today.year, step=1,
                                    key="calendar_year")
    month = month_column.selectbox("月", list(range(1, 13)), index=today.month - 1,
                                  format_func=lambda n: f"{n}月", key="calendar_month")
    try:
        records = read_month_attempts(st.session_state.user_id, year, month)
        summary = month_summary(records, year, month)
    except (sqlite3.Error, OSError, ValueError, KeyError, TypeError):
        st.error("カレンダーを読み込めませんでした。もういちど試してください。")
        if st.button("読み込みをやりなおす", key="calendar_reload"):
            st.rerun()
        return
    days = summary["days"]
    st.metric("この月の ごほうびスタンプ", f"⭐ {summary['stamps']}こ")
    if summary["stamps"]:
        stars = "⭐ " * min(summary["stamps"], 20)
        remaining = f" ＋{summary['stamps'] - 20}こ" if summary["stamps"] > 20 else ""
        st.write(stars + remaining)
    st.caption("1セットを最後まで答えて保存すると1こ。正解・不正解にかかわらず、再練習でももらえます。")
    st.caption("✅ は学習した日、⭐ はスタンプをもらった日です。更新前の履歴はスタンプ対象外です。")
    # 数字と固定の目印だけの小さな暦。スマートフォンでも7列を保ちます。
    weekdays = "月火水木金土日"
    html = '<table style="width:100%;table-layout:fixed;text-align:center;border-collapse:collapse"><thead><tr>'
    html += "".join(f'<th scope="col" style="padding:6px 0">{day}</th>' for day in weekdays)
    html += "</tr></thead><tbody>"
    for week in calendar.Calendar(firstweekday=0).monthdayscalendar(year, month):
        html += "<tr>"
        for day in week:
            details = days.get(day)
            marks = ("✅" if details else "") + ("⭐" if details and details["stamps"] else "")
            html += f'<td style="height:58px;border:1px solid #d8e4ed;font-size:15px">{day if day else ""}<br>{marks}</td>'
        html += "</tr>"
    html += "</tbody></table>"
    st.markdown(html, unsafe_allow_html=True)
    if not days:
        st.info("この月はまだ学習履歴がありません。")
        return
    def rate(correct, count):
        return f"{correct / count:.0%}" if count else "—"
    table = [{"日": f"{month}/{day}", "回答数": data["count"],
              "正答率": rate(data["correct"], data["count"]),
              "初回回答数": data["normal_count"], "初回正答率": rate(data["normal_correct"], data["normal_count"]),
              "再練習回答数": data["retry_count"], "再練習正答率": rate(data["retry_correct"], data["retry_count"]),
              "スタンプ": data["stamps"]} for day, data in sorted(days.items())]
    st.caption("日別の回答数と正答率（日本時間）。初回と再練習を分けて表示します。表は横にスクロールできます。")
    st.dataframe(table, hide_index=True, use_container_width=True)


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
    st.write("**計算問題の評価（文章題とは別集計）**")
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
    if report["word_normal"]["count"] or report["word_retry"]["count"]:
        st.write("**文章題の回答**")
        word_table = []
        for title, data in (("初回", report["word_normal"]), ("再練習", report["word_retry"])):
            def display_rate(value):
                return f"{value:.0%}" if value is not None else "—"
            word_table.append({"練習": title, "回答数": data["count"],
                               "全体正答率": display_rate(data["rate"]),
                               "たす・ひくの選択": display_rate(data["operation_rate"]),
                               "式に使う数・順序": display_rate(data["equation_rate"]),
                               "式の評価数": data["equation_count"],
                               "選んだ式の計算": display_rate(data["calculation_rate"]),
                               "計算の評価数": data["calculation_count"]})
        st.dataframe(word_table, hide_index=True, use_container_width=True)
        st.caption("演算選択、式に使う数・順序、その式の計算を別に評価します。たし算の数量は交換可、ひき算は順序が必要です。"
                   "式の数と順序の判定は演算選択とは独立です。文章理解そのものを点数化する機能ではありません。"
                   "負の答えは計算未評価、以前の回答は式未評価です。")
    with st.expander("評価の見方"):
        st.write("種類ごとに5問未満は判断保留、正答率90%以上は「よくできています」、"
                 "80%以上90%未満は「もう少し練習」、80%未満は「優先して練習」です。"
                 "学力の診断ではなく、このアプリで回答した問題の傾向です。")
        st.write("最近の変化は同じ数の範囲・演算・繰り上がり／繰り下がりの種類について、"
                 "直近10問とその前10問を比較します。最大500回答を集計し、再練習は習熟の判定に含めません。")
    label = "おすすめの5問を れんしゅう" if report["target"] else "ミックス10問を れんしゅう"
    st.caption("おすすめの練習は計算問題の回答だけから選びます。文章題は設定画面から選べます。")
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


st.title("📚 さんすう・こくご れんしゅう")
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

if st.session_state.screen in ("settings", "jp_settings"):
    math_tab, japanese_tab = st.columns(2)
    if math_tab.button("🔢 さんすう", key="subject_math", disabled=st.session_state.screen == "settings",
                       use_container_width=True):
        st.session_state.screen = "settings"
        st.rerun()
    if japanese_tab.button("📖 こくご", key="subject_japanese", disabled=st.session_state.screen == "jp_settings",
                           use_container_width=True):
        st.session_state.screen = "jp_settings"
        st.rerun()

if st.session_state.screen in ("settings", "jp_settings", "report", "jp_analysis", "results", "jp_results"):
    if st.button("共通レポート・教科横断分析（保護者向け）", key="cross_open", use_container_width=True):
        st.session_state.cross_return = st.session_state.screen
        st.session_state.screen = "cross_report"
        st.rerun()

from cross_subject_ui import report_screen as cross_report_screen

screens = {"user": user_screen, "settings": settings_screen,
           "practice": practice_screen, "results": results_screen, "history": history_screen,
           "report": report_screen, "calendar": calendar_screen, "cross_report": cross_report_screen}
if st.session_state.screen.startswith("jp_"):
    from japanese_ui import SCREENS
    screens.update(SCREENS)
screens[st.session_state.screen]()
