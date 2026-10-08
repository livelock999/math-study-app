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
from math_visuals import visual_model
from furigana import READINGS
from text_display import component_display, plain_label
from practice_mode import is_test_mode, is_test_round, switch_mode, write_learning_answer
from daily_review import plan_math
from parent_insights import adaptive_math, math_hint_steps, review_forecast
from ui_theme import apply_theme, brand, card_heading
import adaptive_difficulty as difficulty
import school_scope as school

WORD_FORMATS = ("word_problem", "three_word_problem")

st.set_page_config(page_title="さんすう・こくご れんしゅう", page_icon="📚", layout="centered")
keyboard = components.declare_component("math_keyboard", path=str(Path(__file__).parent / "keyboard"))


def start_round(problems, selection_type, review_reasons=None, difficulty_plan=None):
    """再練習も独立したセット。回答回数だけは前のセットから引き継ぎます。"""
    if selection_type == "normal":
        st.session_state.practice_count = len(problems)
    st.session_state.round = {
        "session_id": new_id("session"), "problems": problems,
        "selection_type": selection_type, "index": 0, "answers": [],
        "phase": "choose" if problems[0]["problem_format"] in WORD_FORMATS else "question",
        "pending_record": None, "selected_operations": {}, "selected_second_operations": {}, "user_equations": {}, "equation_revision": {},
        "user_id": st.session_state.user_id, "suspended": False, "drafts": {}, "interaction_revision": {},
        "test_mode": is_test_mode(st.session_state),
        "review_reasons": dict(review_reasons or {}),
        "difficulty_plan": difficulty_plan,
        "visual_enabled": bool(st.session_state.get("math_visuals_preference", False)),
    }
    st.session_state.screen = "practice"


def load_math_review_history(user_id):
    """復習の選定には選択した学習者の全履歴を使います。"""
    records, page = [], 0
    while True:
        batch, more = read_attempts(user_id, page=page, page_size=100)
        records.extend(batch)
        if not more:
            return records
        page += 1


def show_review_reasons(state):
    review = state.get("selection_type") in ("review", "review_retry")
    if not review and not (state.get("selection_type") == "weak_area" and state.get("review_reasons")):
        return
    with st.expander("保護者向け：きょうの復習の出題理由" if review else "保護者向け：類題の出題理由"):
        reasons = state.get("review_reasons", {})
        for index, problem in enumerate(state["problems"], 1):
            st.write(f"{index}問目：{reasons.get(problem['problem_id'], '復習した問題の再練習')}")
        st.caption("復習の回答は初回正答率と分けて記録します。" if review else "類題は新しい教材への回答として、通常の苦手練習に記録します。")


def show_problem_feedback(state, problem):
    """問題に紐づく保護者の報告。保存再試行では同じID・内容を再送します。"""
    with st.expander("保護者向け：この問題について報告する"):
        from learning_extensions import make_feedback, save_feedback
        index = state["index"]
        entry = state.setdefault("problem_feedback", {}).setdefault(index, {})
        labels = {"difficult": "難しすぎる", "reading": "読みづらい", "answer": "問題・答えがおかしい"}
        reason = st.selectbox("気になったこと", list(labels), format_func=labels.get,
                              key=f"math_feedback_reason_{state['session_id']}_{index}",
                              disabled=bool(entry.get("pending") or entry.get("saved")))
        if entry.get("saved"):
            st.success("保存せずに報告を確認しました。" if is_test_round(state, st.session_state) else "この問題の報告を保存しました。")
        elif st.button("報告を保存する" if not entry.get("pending") else "報告の保存をやりなおす",
                       key=f"math_feedback_save_{state['session_id']}_{index}"):
            if not entry.get("pending"):
                entry["pending"] = make_feedback(state["user_id"], "math", problem["problem_id"], reason)
            try:
                save_feedback(entry["pending"], test_mode=is_test_round(state, st.session_state))
            except (sqlite3.Error, OSError, ValueError):
                st.error("報告を保存できませんでした。同じボタンでやりなおせます。")
            else:
                entry["saved"] = True
                st.success("保存せずに報告を確認しました。" if is_test_round(state, st.session_state) else "この問題の報告を保存しました。")


def save_pending_answer(state):
    """確定した回答を保存し、成功したときだけ正誤表示へ進みます。"""
    record = state["pending_record"]
    # 更新前から練習中のセット・未保存回答も、実際の問題数を引き継ぎます。
    record.setdefault("round_size", len(state["problems"]))
    record.setdefault("round_completed", record["question_order"] == len(state["problems"]))
    try:
        write_learning_answer(state, st.session_state, save_attempt, record)
    except (sqlite3.Error, OSError, ValueError):
        return False
    state["answers"].append(record)
    st.session_state.attempt_counts[record["problem_id"]] = record["attempt_count"]
    state["pending_record"] = None
    state["phase"] = "feedback"
    return True


def user_screen():
    st.subheader("だれが れんしゅうする？")
    if not is_test_mode(st.session_state):
        with st.expander("保護者の操作確認"):
            st.caption("テスト中の回答は、履歴・分析・スタンプに残りません。開始すると途中の練習を終了します。")
            if st.button("保護者のテストを始める（記録しない）", key="parent_test_start", use_container_width=True):
                switch_mode(st.session_state, True)
                st.rerun()
    with st.container(key="user_cards"):
        card_heading("✏️", "きょうも すこしずつ。", "なまえを えらんで はじめよう。")
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
    with st.container(key="flashcard_entry"):
        card_heading("🃏", "けいさんカード", "こたえて、つぎへ。テンポよく れんしゅうしよう。")
        if st.button("けいさんカードを はじめる", key="flashcard_open", use_container_width=True):
            st.session_state.screen = "flashcard_settings"
            st.rerun()
    review_card = st.container(key="review_card_math")
    with st.container(key="practice_card_math"):
        card_heading("✏️", "いつもの れんしゅう", "じぶんの ペースで、ひとつずつ。")
        with st.expander("もんだいを えらぶ・せってい"):
            modes = {"addition": "たしざん", "subtraction": "ひきざん", "mix": "ミックス"}
            mode = st.radio("もんだい", list(modes), format_func=modes.get, horizontal=True)
            limit = st.radio("かずの はんい", [10, 20], format_func=lambda n: f"{n}まで", horizontal=True)
            st.session_state.math_review_limit = limit
            count = st.radio("もんだいの かず", [5, 10, 20], index=[5, 10, 20].index(st.session_state.get("practice_count", 10)),
                             format_func=lambda n: f"{n}もん", horizontal=True, key="problem_count")
            choices = {"auto": "おまかせ", "none": "なし", "with": "あり"}
            special = st.radio("くりあがり・くりさがり", list(choices), format_func=choices.get,
                               horizontal=True, key="special_mode")
            formats = {"calculation": "けいさん", "three_numbers": "3つの かず", "fill_blank": "□の かず",
                       "word_problem": "ぶんしょうだい", "three_word_problem": "3つの かずの ぶんしょうだい"}
            problem_format = st.radio("もんだいの かたち", list(formats), format_func=formats.get,
                                      horizontal=True, key="problem_format")
            if problem_format == "three_numbers":
                st.caption("ひだりの 2つの かずを けいさんしてから、3つめの かずを けいさんしよう。ミックスは、たす・ひくの 4しゅるいです。")
            elif problem_format == "three_word_problem":
                st.caption("2かいの できごとを よんで、たす・ひくを えらび、3つの かずで しきを つくろう。")
            visual_key = f"math_visuals_enable_{st.session_state.get('math_visuals_widget_epoch', 0)}"
            if visual_key not in st.session_state:
                st.session_state[visual_key] = bool(st.session_state.get("math_visuals_preference", False))
            st.session_state.math_visuals_preference = st.checkbox("図で かんがえる", key=visual_key)
            st.caption("けいさん・3つの かず・□の かずを、まるで たしかめられるよ。図を使った回答はヒントありとして記録します。")
            error = selection_error(mode, limit, count, special, problem_format)
            if error:
                st.info(error)
        st.caption(f"1かい {count}もん。まちがえた もんだいは あとで れんしゅうできるよ。")
        if st.button("おまかせで れんしゅう", key="math_adaptive_start", type="primary", use_container_width=True):
            try:
                scope = school.active_scope(st.session_state.user_id, st.session_state)
                plan = school.plan_math(load_math_review_history(st.session_state.user_id),
                                        st.session_state.user_id, scope, mode, limit, count, special, problem_format)
            except (sqlite3.Error, OSError, ValueError, KeyError, TypeError):
                st.error("おまかせの履歴・学校の範囲を読み込めませんでした。接続と追加SQLを確認して、もういちど押してください。")
            else:
                if plan["items"]:
                    st.session_state.attempt_counts = {}
                    start_round(plan["items"], "normal", difficulty_plan=plan)
                    st.rerun()
                else:
                    st.info(plan["message"])
        st.caption("こたえや ヒントに あわせて、つぎの セットの むずかしさを すこしずつ。条件を自分で決めるときは下のスタートを使えます。")
        if st.button(plain_label("れんしゅう スタート", st.session_state.user_id), use_container_width=True, disabled=bool(error)):
            st.session_state.attempt_counts = {}
            start_round(generate_problems(mode, limit, count, special, problem_format), "normal")
            st.rerun()
    with review_card:
        card_heading("🌱", "きょうの ふくしゅう", "さんすうを 5もん。きのうの がんばりを、きょうの じしんに。")
        if st.button("きょうの ふくしゅう", key="math_daily_review", use_container_width=True):
            try:
                records = load_math_review_history(st.session_state.user_id)
                scope = school.active_scope(st.session_state.user_id, st.session_state)
                pool = school.review_pool(records, st.session_state.user_id, scope, "math")
                plan = plan_math(records, st.session_state.user_id, limit=limit, count=5, candidate_pool=pool)
            except (sqlite3.Error, OSError, ValueError, KeyError, TypeError):
                st.error("復習の履歴・学校の範囲を読み込めませんでした。接続と追加SQLを確認して、もういちど押してください。")
            else:
                if plan["items"]:
                    st.session_state.attempt_counts = {}
                    start_round(plan["items"], "review", review_reasons=plan["reasons"])
                    st.rerun()
                else:
                    st.info(plan["message"])
    with st.expander("もっと れんしゅう・ふくしゅうの よてい"):
        if st.button("にた もんだいで れんしゅう", key="math_similar", use_container_width=True):
            try:
                records = load_math_review_history(st.session_state.user_id)
                plan = adaptive_math(records, st.session_state.user_id, limit=limit, count=5)
            except (sqlite3.Error, OSError, ValueError, KeyError, TypeError):
                st.error("練習の履歴を読み込めませんでした。もういちど押してください。")
            else:
                if plan["items"]:
                    st.session_state.attempt_counts = {}
                    start_round(plan["items"], "weak_area", review_reasons=plan.get("reasons"))
                    st.rerun()
                else:
                    st.info(plan["message"])
        with st.container():
            st.caption("保護者向け：復習の予定")
            if st.button("復習の予定をみる", key="math_review_forecast"):
                try:
                    records = load_math_review_history(st.session_state.user_id)
                    scope = school.active_scope(st.session_state.user_id, st.session_state)
                    pool = school.review_pool(records, st.session_state.user_id, scope, "math")
                    forecast = review_forecast(records, st.session_state.user_id, "math", limit=limit, candidate_pool=pool)
                except (sqlite3.Error, OSError, ValueError, KeyError, TypeError):
                    st.error("復習の予定を読み込めませんでした。もういちど押してください。")
                else:
                    st.write(f"きょう：{forecast['today_count']}問 ／ あした：{forecast['tomorrow_count']}問")
                    st.caption("きょうの復習は1日5問まで。きょうの数は回答済みを除いた残りです。基本問題の補充は含みません。")
    with st.expander("がんばりの きろく・ごほうび"):
        if st.button(plain_label("学習履歴", st.session_state.user_id), key="history_settings", use_container_width=True):
            open_history("settings")
        if st.button(plain_label("学習レポート", st.session_state.user_id), key="report_settings", use_container_width=True):
            open_report("settings")
        if st.button(plain_label("学習カレンダー・ごほうび", st.session_state.user_id), key="calendar_settings", use_container_width=True):
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
    for name, max_length in (("answer", 3), ("equation_left", 2), ("equation_right", 2), ("equation_third", 2)):
        value = incoming.get(name, draft.get(name, ""))
        if not isinstance(value, str) or len(value) > max_length or (value and not (value.isascii() and value.isdigit())):
            return False
    choice = incoming.get("selected_operation", draft["selected_operation"])
    second_choice = incoming.get("selected_second_operation", draft.get("selected_second_operation"))
    if choice not in (None, "addition", "subtraction") or second_choice not in (None, "addition", "subtraction"):
        return False
    seconds = event.get("response_time_sec", draft["elapsed_sec"])
    reading_help = incoming.get("reading_help_used", event.get("reading_help_used", draft.get("reading_help_used", False)))
    if type(reading_help) is not bool:
        return False
    if type(seconds) not in (int, float) or not 0 <= seconds < float("inf"):
        return False
    for name in ("answer", "equation_left", "equation_right", "equation_third"):
        draft[name] = incoming.get(name, draft.get(name, ""))
    draft["selected_operation"] = choice
    draft["selected_second_operation"] = second_choice
    draft["elapsed_sec"] = max(draft["elapsed_sec"], seconds)
    draft["reading_help_used"] = draft.get("reading_help_used", False) or reading_help
    return True


def practice_screen():
    state = st.session_state.round
    difficulty.show_reason(state.get("difficulty_plan"), "math")
    state.setdefault("user_id", st.session_state.user_id)
    if state["user_id"] != st.session_state.user_id:
        st.session_state.screen = "settings"
        st.rerun()
    index = state["index"]
    problems = state["problems"]
    problem = problems[index]
    is_word = problem["problem_format"] in WORD_FORMATS
    is_three_word = problem["problem_format"] == "three_word_problem"
    selected_operation = state.setdefault("selected_operations", {}).get(index)
    selected_second_operation = state.setdefault("selected_second_operations", {}).get(index)
    equation = state.setdefault("user_equations", {}).get(index)
    revision = state.setdefault("equation_revision", {}).get(index, 0)
    draft = state.setdefault("drafts", {}).setdefault(index, {
        "answer": "", "equation_left": "", "equation_right": "", "equation_third": "",
        "selected_operation": None, "selected_second_operation": None,
        "elapsed_sec": 0, "hint_used": False, "hint_level": 0, "hint_visible": False, "explanation_visible": False,
    })
    draft.setdefault("hint_level", 1 if draft.get("hint_used") else 0)
    draft.setdefault("equation_third", "")
    draft.setdefault("selected_second_operation", None)
    can_show_visual = problem["problem_format"] in ("calculation", "fill_blank", "three_numbers")
    draft.setdefault("visual_visible", bool(state.get("visual_enabled") and can_show_visual))
    draft.setdefault("visual_help_used", draft["visual_visible"] and state["phase"] != "feedback")
    interaction_revision = state.setdefault("interaction_revision", {}).get(index, 0)
    st.caption(f"{USERS[st.session_state.user_id]} ／ "
               f"{ {'retry': 'もういちど れんしゅう', 'review': 'きょうの ふくしゅう', 'review_retry': 'ふくしゅうを もういちど'}.get(state['selection_type'], 'れんしゅう')}")
    st.progress(index / len(problems), text=f"{index + 1} / {len(problems)} もん")
    show_review_reasons(state)
    show_problem_feedback(state, problem)
    # 保存失敗中は入力を確定したままにし、前回のコンポーネント値に頼らず再試行します。
    if state["pending_record"] is not None:
        st.subheader(problem["question_text"])
        st.write(f"あなたの こたえ：{'わからない' if state['pending_record'].get('dont_know_used') else state['pending_record']['user_answer']}")
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
    displayed_equation = None
    if is_word and equation and state["phase"] != "equation":
        displayed_equation = f"{equation['left']} {'+' if equation['operation'] == 'addition' else '−'} {equation['right']}"
        if is_three_word:
            displayed_equation += f" {'+' if equation['second_operation'] == 'addition' else '−'} {equation['third']}"
        displayed_equation += " = ?"
    event = keyboard(
        furigana=READINGS,
        **component_display("math", problem, st.session_state.user_id),
        token=token, phase=state["phase"], question=problem["question_text"],
        correct=last_answer["is_correct"] if last_answer else None,
        answer=last_answer["user_answer"] if last_answer else None,
        dont_know_used=bool(last_answer and last_answer.get("dont_know_used")),
        last=index + 1 == len(problems), key="answer_keyboard", default=None,
        word_problem=is_word, question_id=f"{state['session_id']}:{index}",
        three_word_problem=is_three_word,
        answer_label="□に はいる かず" if problem["problem_format"] == "fill_blank" else "こたえ",
        visual_available=can_show_visual, visual_visible=draft["visual_visible"],
        visual_model=visual_model(problem, reveal=state["phase"] == "feedback") if draft["visual_visible"] else None,
        equation=displayed_equation,
        selected_operation=selected_operation,
        selected_second_operation=selected_second_operation,
        equation_left=equation["left"] if equation else None,
        equation_right=equation["right"] if equation else None,
        equation_third=equation.get("third") if equation else None,
        draft=draft, elapsed_sec=draft["elapsed_sec"], hint_used=draft["hint_used"],
        hint_visible=draft["hint_visible"], explanation_visible=draft["explanation_visible"],
        hint_text=math_hint_steps(problem)[max(0, draft["hint_level"] - 1)],
        hint_steps=math_hint_steps(problem), hint_level=draft["hint_level"],
        explanation_text=guidance(problem, reveal=True) if state["phase"] == "feedback" else None,
    )
    # 古い画面から届いた値は無視し、保存後にだけ進行状態を変えます。
    if not isinstance(event, dict) or event.get("token") != token:
        return
    if not remember_practice_draft(state, index, event):
        return
    action = event.get("action")
    if action in ("pause", "open_history", "show_hint", "show_explanation", "show_visual"):
        if action == "show_hint" and state["phase"] != "feedback":
            draft["hint_used"] = True
            draft["hint_visible"] = True
            draft["hint_level"] = min(3, draft["hint_level"] + 1)
        elif action == "show_explanation" and state["phase"] == "feedback":
            draft["explanation_visible"] = True
        elif action == "show_visual" and can_show_visual:
            draft["visual_visible"] = True
            if state["phase"] != "feedback":
                draft["visual_help_used"] = True
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
            state["phase"] = "choose_second" if is_three_word else "equation"
            st.rerun()
    elif state["phase"] == "choose_second" and action == "choose_operation":
        choice = event.get("selected_operation")
        if is_three_word and choice in ("addition", "subtraction"):
            state["selected_second_operations"][index] = choice
            state["phase"] = "equation"
            st.rerun()
    elif state["phase"] == "equation" and event.get("action") == "submit_equation":
        left, right = event.get("equation_left"), event.get("equation_right")
        choice = event.get("selected_operation")
        second_choice, third = event.get("selected_second_operation"), event.get("equation_third")
        if (not is_word or choice not in ("addition", "subtraction")
                or type(left) is not int or type(right) is not int or not 0 <= left <= 99 or not 0 <= right <= 99
                or (is_three_word and (second_choice not in ("addition", "subtraction")
                                       or type(third) is not int or not 0 <= third <= 99))):
            st.error("しきの 3つの すうじを いれてね" if is_three_word else "しきの 2つの すうじを いれてね")
            return
        state["selected_operations"][index] = choice
        state["user_equations"][index] = {"left": left, "right": right, "operation": choice}
        if is_three_word:
            state["selected_second_operations"][index] = second_choice
            state["user_equations"][index].update(third=third, second_operation=second_choice)
        state["phase"] = "question"
        st.rerun()
    elif state["phase"] == "question" and is_word and event.get("action") == "edit_equation":
        state["equation_revision"][index] = revision + 1
        state["phase"] = "equation"
        st.rerun()
    elif ((state["phase"] == "question" and action == "answer")
          or (state["phase"] != "feedback" and action == "dont_know")):
        dont_know = action == "dont_know"
        if not dont_know and is_word and (selected_operation not in ("addition", "subtraction")
                or (is_three_word and selected_second_operation not in ("addition", "subtraction"))):
            return
        answer = None if dont_know else event.get("answer")
        seconds = event.get("response_time_sec")
        if not dont_know and (type(answer) is not int or not 0 <= answer <= 999):
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
            equation_left=equation["left"] if is_word and equation else None,
            equation_right=equation["right"] if is_word and equation else None,
            selected_second_operation=selected_second_operation if is_three_word else None,
            equation_third=equation["third"] if is_three_word and equation else None,
            hint_used=draft["hint_used"],
            hint_level=draft["hint_level"], dont_know_used=dont_know,
            reading_help_used=draft.get("reading_help_used", False),
            visual_help_used=draft.get("visual_help_used", False),
        )
        save_pending_answer(state)
        st.rerun()
    elif state["phase"] == "feedback" and event.get("action") == "next":
        if index + 1 == len(problems):
            st.session_state.screen = "results"
        else:
            state["index"] += 1
            state["phase"] = "choose" if problems[index + 1]["problem_format"] in WORD_FORMATS else "question"
        st.rerun()


def results_screen():
    state = st.session_state.round
    difficulty.show_reason(state.get("difficulty_plan"), "math")
    correct = sum(record["is_correct"] for record in state["answers"])
    total = len(state["answers"])
    st.subheader("れんしゅう おわり！")
    st.write({"retry": "もういちど れんしゅうの けっか", "review": "きょうの ふくしゅうの けっか",
              "review_retry": "ふくしゅうを もういちどの けっか"}.get(state["selection_type"], "はじめの れんしゅうの けっか"))
    show_review_reasons(state)
    st.metric("せいかい", f"{total}もんちゅう {correct}もん")
    st.metric("せいかいりつ", f"{correct / total:.0%}")
    if state["answers"][-1].get("round_completed") and not is_test_round(state, st.session_state):
        st.success("⭐ ごほうびスタンプを 1こ もらったよ！")
    mistakes = [problem for problem, record in zip(state["problems"], state["answers"])
                if not record["is_correct"]]
    if mistakes:
        if st.button("まちがえた もんだいを もういちど", type="primary", use_container_width=True):
            review = state["selection_type"] in ("review", "review_retry")
            start_round(mistakes, "review_retry" if review else "retry", review_reasons=state.get("review_reasons"))
            st.rerun()
    else:
        st.success("ぜんぶ せいかい！ よく がんばったね！")
    new_count = st.session_state.get("practice_count", 10)
    if st.button(f"あたらしい {new_count}もんを れんしゅう", key="new_practice", use_container_width=True):
        st.session_state.screen = "settings"
        st.rerun()
    if st.button(plain_label("学習履歴", st.session_state.user_id), key="history_results", use_container_width=True):
        open_history("results")
    if st.button(plain_label("学習レポート", st.session_state.user_id), key="report_results", use_container_width=True):
        open_report("results")
    if st.button(plain_label("学習カレンダー・ごほうび", st.session_state.user_id), key="calendar_results", use_container_width=True):
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
    if st.button(plain_label("学習レポート", st.session_state.user_id), key="report_history", use_container_width=True):
        open_report("history")
    if st.button("計算カードのレポート", key="fc_report_history", use_container_width=True):
        st.session_state.fc_return = "history"
        st.session_state.screen = "flashcard_report"
        st.rerun()
    if st.button(plain_label("学習カレンダー・ごほうび", st.session_state.user_id), key="calendar_history", use_container_width=True):
        open_calendar("history")
    page = st.session_state.history_page
    try:
        records, has_more = read_attempts(st.session_state.user_id, page=page)
        table = []
        for record in records:
            answered_at = datetime.fromisoformat(record["datetime"]).astimezone(timezone(timedelta(hours=9)))
            table.append({
                "日時（日本時間）": answered_at.strftime("%Y/%m/%d %H:%M:%S"),
                "学習モード": "計算カード" if record.get("learning_mode") == "flashcard" else "いつもの練習",
                "問題": record["question_text"], "自分の回答": "わからない" if record.get("dont_know_used") else record["user_answer"],
                "読み方の確認": "記録なし" if record.get("reading_help_used") is None else "あり" if record["reading_help_used"] else "なし",
                "正しい答え": record["correct_answer"], "正誤": "○" if record["is_correct"] else "×",
                "練習": {"normal": "初回", "retry": "再練習", "weak_area": "苦手練習",
                         "review": "きょうの復習", "review_retry": "復習の再練習"}.get(record["selection_type"], record["selection_type"]),
                "出題順": record["question_order"], "回答回数": record["attempt_count"],
                "回答時間（秒）": record["response_time_sec"],
                "入力方法": {"voice": "音声", "keyboard": "キーボード", "keypad": "画面テンキー"}.get(record.get("input_method"), "記録なし"),
                "音声の認識文字": record.get("recognized_text") or "—",
                "音声認識のやりなおし": record.get("recognition_retry_count"),
                "ヒント": hint_label(record.get("hint_used")),
                "ヒント段階": record["hint_level"] if record.get("hint_level") is not None else "記録なし",
                "図の使用": "記録なし" if record.get("visual_help_used") is None else "あり" if record["visual_help_used"] else "なし",
                "わからない": "あり" if record.get("dont_know_used") else "なし",
                "形式": {"word_problem": "文章題", "fill_blank": "穴埋め", "calculation": "計算", "three_numbers": "3つの数", "three_word_problem": "3つの数の文章題"}.get(record["problem_format"], record["problem_format"]),
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


def hint_label(value):
    return "記録なし" if value is None else "ヒントあり" if value else "ヒントなし"


def display_rate(value):
    return f"{value:.0%}" if value is not None else "—"


def hint_columns(summary):
    return {"ヒント使用率": display_rate(summary["hint_rate"]),
            "ヒント記録数": summary["hint_known_count"],
            "ヒント記録なし": summary["hint_unknown_count"],
            "自力正答率": display_rate(summary["unaided_rate"]),
            "自力回答数": summary["unaided_count"],
            "ヒントあり正答率": display_rate(summary["assisted_rate"]),
            "ヒントあり回答数": summary["assisted_count"]}


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
              "復習回答数": data["review_count"], "復習正答率": rate(data["review_correct"], data["review_count"]),
              "復習の再練習回答数": data["review_retry_count"],
              "スタンプ": data["stamps"]} for day, data in sorted(days.items())]
    st.caption("日別の回答数と正答率（日本時間）。初回と再練習を分けて表示します。表は横にスクロールできます。")
    st.dataframe(table, hide_index=True, use_container_width=True)


def report_screen():
    st.subheader(f"{USERS[st.session_state.user_id]}の 学習レポート")
    if st.button("もどる", key="report_back"):
        st.session_state.screen = st.session_state.report_return
        st.rerun()
    if st.button("計算カードのレポート", key="fc_report_normal", use_container_width=True):
        st.session_state.fc_return = "report"
        st.session_state.screen = "flashcard_report"
        st.rerun()
    st.caption("保護者向けの自動集計です。外部AIへの送信・AI利用料はありません。")
    try:
        all_records = [r for r in load_math_review_history(st.session_state.user_id)
                       if r.get("learning_mode") != "flashcard"]
        # 復習が増えても、従来の通常/再練習500回答を押し出さない。
        records = [r for r in all_records if r["selection_type"] not in ("review", "review_retry")][:500]
        records += [r for r in all_records if r["selection_type"] in ("review", "review_retry")][:500]
        has_more = len(records) < len(all_records)
        report = assess(records, user_id=st.session_state.user_id)
        dates = [datetime.fromisoformat(row["datetime"]).astimezone(timezone(timedelta(hours=9)))
                 for row in records]
    except (sqlite3.Error, OSError, ValueError, KeyError, TypeError):
        st.error("レポートを読み込めませんでした。もういちど試してください。")
        if st.button("読み込みをやりなおす", key="report_reload"):
            st.rerun()
        return
    if records:
        st.caption("通常・再練習は最新500回答まで、復習は別枠の最新500回答まで。復習で初回評価の履歴を押し出しません。")
        st.caption(f"集計対象：{'直近' if has_more else '保存済み'}{len(records)}回答 ／ "
                   f"{min(dates):%Y/%m/%d}〜{max(dates):%Y/%m/%d}（日本時間）")
    else:
        st.info("まだ学習履歴がありません。れんしゅうすると、ここに表示されます。")
    overall = report["overall"]
    st.write("**計算問題の評価**")
    st.caption("計算・3つの数・穴埋め・文章題・3つの数の文章題をそれぞれ集計します。図を使った正解はヒントありの正解に含めます。")
    counts, accuracy, speed = st.columns(3)
    counts.metric("初回の回答", f"{overall['count']}問")
    accuracy.metric("初回正答率", f"{overall['rate']:.0%}" if overall["count"] else "—")
    speed.metric("正解時の回答時間", f"{overall['seconds']:.1f}秒" if overall["seconds"] is not None else "—")
    hint_rate, unaided, assisted = st.columns(3)
    hint_rate.metric("初回のヒント使用率", display_rate(overall["hint_rate"]))
    unaided.metric("自力正答率", display_rate(overall["unaided_rate"]),
                   help=f"ヒントなしの初回回答 {overall['unaided_count']}問")
    assisted.metric("ヒントあり正答率", display_rate(overall["assisted_rate"]),
                    help=f"ヒントを使った初回回答 {overall['assisted_count']}問")
    st.caption(f"ヒント記録あり {overall['hint_known_count']}問、記録なし {overall['hint_unknown_count']}問。"
               "ヒント使用率・自力／ヒントあり正答率は記録のある回答だけで集計します。ヒントは理解を助けるものです。")
    st.caption("回答時間は正解した初回回答の中央値です。計算カードは専用レポートで集計します。休憩や操作の影響もあるため、速さで苦手を判定しません。")
    st.caption(f"図を使った初回回答：{overall['visual_used_count']}問"
               f"（記録あり{overall['visual_known_count']}問・記録なし{overall['visual_unknown_count']}問）。文字ヒントの段階は別に記録します。")
    st.caption(f"読み方を押して確認した初回回答：{overall['reading_help_count']}問"
               f"（記録あり{overall['reading_known_count']}問・記録なし{overall['reading_unknown_count']}問）。"
               "ヒント使用や計算の正誤とは別の記録です。ふりがな表示は確認回数に含めません。")
    st.write("**現状の評価と次の練習**")
    st.info(report["message"])
    if report["strengths"]:
        st.success("得意な点：" + "、".join(report["strengths"]))
    if report["groups"]:
        table = [{"問題の種類": group["label"], "初回回答数": group["count"],
                  "正答率": f"{group['rate']:.0%}", "評価": group["status"],
                  **hint_columns(group), "練習の手がかり": group["support_message"],
                  "最近の変化": group["trend"]} for group in report["groups"]]
        st.dataframe(table, hide_index=True, use_container_width=True)
    retry = report["retry"]
    if retry["count"]:
        st.write(f"再練習では{retry['count']}問中{retry['correct']}問正解（{retry['rate']:.0%}）。"
                 "初回の正答率とは分けて表示しています。")
    with st.expander("きょうの復習の成果（初回とは別集計）"):
        for label, key in (("計算の復習", "review"), ("計算の復習の再練習", "review_retry"),
                           ("3つの数の復習", "three_review"), ("3つの数の復習の再練習", "three_review_retry"),
                           ("3つの数の文章題の復習", "three_word_review"), ("3つの数の文章題の復習の再練習", "three_word_review_retry"),
                           ("穴埋めの復習", "fill_review"), ("穴埋めの復習の再練習", "fill_review_retry"),
                           ("文章題の復習", "word_review"), ("文章題の復習の再練習", "word_review_retry")):
            data = report.get(key, {})
            st.write(f"{label}：{data.get('correct', 0)} / {data.get('count', 0)}問正解")
    if report["fill_normal"]["count"] or report["fill_retry"]["count"]:
        st.write("**□に入る数の練習**")
        fill_table = [{"練習": label, "回答数": data["count"], "正答率": display_rate(data["rate"]),
                       **hint_columns(data), "図を使用": data["visual_used_count"]}
                      for label, data in (("初回", report["fill_normal"]), ("再練習", report["fill_retry"]),
                                          ("各問題の最新回答", report["fill_latest"]))]
        st.dataframe(fill_table, hide_index=True, use_container_width=True)
        if report["fill_groups"]:
            st.dataframe([{"問題の種類": group["label"], "初回回答数": group["count"],
                           "初回正答率": display_rate(group["rate"]), "評価": group["status"],
                           "最新の正答率": display_rate(group["latest"]["rate"]),
                           **hint_columns(group)} for group in report["fill_groups"]],
                         hide_index=True, use_container_width=True)
        st.caption("同じ式でも左の□と右の□は別の問題です。図を見た正解も正解に数え、復習・自力の成果は分けて表示します。")
    if report["three_normal"]["count"] or report["three_retry"]["count"]:
        st.write("**3つの数の練習**")
        three_table = [{"練習": label, "回答数": data["count"], "正答率": display_rate(data["rate"]),
                        **hint_columns(data), "図を使用": data["visual_used_count"]}
                       for label, data in (("初回", report["three_normal"]), ("再練習", report["three_retry"]),
                                           ("各問題の最新回答", report["three_latest"]))]
        st.dataframe(three_table, hide_index=True, use_container_width=True)
        if report["three_groups"]:
            st.dataframe([{"問題の種類": group["label"], "初回回答数": group["count"],
                           "初回正答率": display_rate(group["rate"]), "評価": group["status"],
                           "最新の正答率": display_rate(group["latest"]["rate"]),
                           **hint_columns(group)} for group in report["three_groups"]],
                         hide_index=True, use_container_width=True)
        st.caption("左から順に計算します。2つの演算の組み合わせごとに集計し、従来の計算問題の初回評価とは分けて表示します。")
    if report["three_word_normal"]["count"] or report["three_word_retry"]["count"]:
        st.write("**3つの数の文章題の練習**")
        three_word_table = [{"練習": label, "回答数": data["count"], "全体正答率": display_rate(data["rate"]),
                             "2回のたす・ひく選択": display_rate(data["operation_rate"]),
                             "3つの数・順序": display_rate(data["equation_rate"]),
                             "自分の式の計算": display_rate(data["calculation_rate"]),
                             **hint_columns(data)}
                            for label, data in (("初回", report["three_word_normal"]), ("再練習", report["three_word_retry"]),
                                                ("各問題の最新回答", report["three_word_latest"]))]
        st.dataframe(three_word_table, hide_index=True, use_container_width=True)
        if report["three_word_groups"]:
            st.dataframe([{"問題の種類": group["label"], "初回回答数": group["count"],
                           "初回正答率": display_rate(group["rate"]), "評価": group["status"],
                           "最新の正答率": display_rate(group["latest"]["rate"]),
                           **hint_columns(group)} for group in report["three_word_groups"]],
                         hide_index=True, use_container_width=True)
        st.caption("2回の出来事をたす・ひくで表し、文章の順に3つの数を式へ入れます。選んだ式の計算は独立して評価し、復習と初回は分けます。")
    if report["word_normal"]["count"] or report["word_retry"]["count"]:
        st.write("**文章題の回答**")
        word_table = []
        for title, data in (("初回", report["word_normal"]), ("再練習", report["word_retry"])):
            word_table.append({"練習": title, "回答数": data["count"],
                               "全体正答率": display_rate(data["rate"]),
                               **hint_columns(data),
                               "たす・ひくの選択": display_rate(data["operation_rate"]),
                               "式に使う数・順序": display_rate(data["equation_rate"]),
                               "式の評価数": data["equation_count"],
                               "選んだ式の計算": display_rate(data["calculation_rate"]),
                               "計算の評価数": data["calculation_count"]})
        st.dataframe(word_table, hide_index=True, use_container_width=True)
        word_initial = report["word_normal"]
        if word_initial["hint_known_count"] >= 5 and word_initial["hint_rate"] >= .3:
            st.info("文章題ではヒントが考え方の支えになっています。必要なときはヒントを使い、"
                    "慣れたら同じ種類の文章題を自力でも試しましょう。設定画面から文章題を選べます。")
        st.caption("演算選択、式に使う数・順序、その式の計算を別に評価します。たし算の数量は交換可、ひき算は順序が必要です。"
                   "式の数と順序の判定は演算選択とは独立です。文章理解そのものを点数化する機能ではありません。"
                   "負の答えは計算未評価、以前の回答は式未評価です。")
    with st.expander("評価の見方"):
        st.write("種類ごとに5問未満は判断保留、正答率90%以上は「よくできています」、"
                 "80%以上90%未満は「もう少し練習」、80%未満は「優先して練習」です。"
                 "学力の診断ではなく、このアプリで回答した問題の傾向です。")
        st.write("最近の変化は同じ数の範囲・演算・繰り上がり／繰り下がりの種類について、"
                 "直近10問とその前10問を比較します。最大500回答を集計し、再練習は習熟の判定に含めません。")
        st.write("初回のヒント記録が同じ種類で5問以上あり、使用率が30%以上なら、"
                 "ヒントが支えになっている種類として練習を提案します。正答率の評価はヒント使用の有無で減点しません。"
                 "回答後の解説はヒント使用に含めず、ヒントを開いただけで未回答の問題も回答数に含めません。")
    label = "おすすめの5問を れんしゅう" if report["target"] else "ミックス10問を れんしゅう"
    st.caption("おすすめの練習は計算問題の回答だけから選びます。3つの数・□の数・文章題は設定画面から選べます。")
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


apply_theme()
brand()
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

if is_test_mode(st.session_state):
    st.warning("保護者のテスト中 — 回答を記録しません。ヒント・読み方確認・スタンプ・漢字設定も保存しません。")
    st.caption("履歴やレポートには、通常の学習で保存した記録を表示します。テスト終了前にお子さまへ渡さないでください。ページを再読み込みすると通常モードに戻ります。")
    if st.button("テストを終了して通常の学習に戻る", key="parent_test_end", use_container_width=True):
        switch_mode(st.session_state, False)
        st.rerun()

if st.session_state.screen in ("settings", "jp_settings"):
    with st.container(key="subject_navigation"):
        math_tab, japanese_tab = st.columns(2)
        if math_tab.button("🔢 さんすう", key="subject_math", disabled=st.session_state.screen == "settings",
                           use_container_width=True):
            st.session_state.screen = "settings"
            st.rerun()
        if japanese_tab.button("📖 こくご", key="subject_japanese", disabled=st.session_state.screen == "jp_settings",
                               use_container_width=True):
            st.session_state.screen = "jp_settings"
            st.rerun()

from cross_subject_ui import report_screen as cross_report_screen
from display_settings_ui import settings_screen as display_settings_screen
from parent_features_ui import render_dashboard
from school_scope_ui import settings_screen as school_settings_screen

screens = {"user": user_screen, "settings": settings_screen,
           "practice": practice_screen, "results": results_screen, "history": history_screen,
           "report": report_screen, "calendar": calendar_screen, "cross_report": cross_report_screen,
           "display_settings": display_settings_screen, "parent_dashboard": render_dashboard,
           "school_settings": school_settings_screen}
if st.session_state.screen.startswith("flashcard_"):
    from flashcards_ui import SCREENS as FLASHCARD_SCREENS
    screens.update(FLASHCARD_SCREENS)
if st.session_state.screen.startswith("jp_"):
    from japanese_ui import SCREENS
    screens.update(SCREENS)
screens[st.session_state.screen]()

if st.session_state.screen in ("settings", "jp_settings", "report", "jp_analysis", "results", "jp_results", "flashcard_results", "flashcard_settings", "flashcard_report"):
    with st.expander("おうちの人へ・レポートと設定"):
        if st.button("週間レポート・学習目標・記録の書き出し（保護者向け）", key="parent_dashboard_open", use_container_width=True):
            st.session_state.parent_dashboard_return = st.session_state.screen
            st.session_state.screen = "parent_dashboard"
            st.rerun()
        if st.button("共通レポート・教科横断分析（保護者向け）", key="cross_open", use_container_width=True):
            st.session_state.cross_return = st.session_state.screen
            st.session_state.screen = "cross_report"
            st.rerun()
        if st.session_state.screen in ("settings", "jp_settings"):
            if st.button("学校で習っている範囲（保護者向け）", key="school_scope_open", use_container_width=True):
                st.session_state.school_scope_return = st.session_state.screen
                st.session_state.screen = "school_settings"
                st.rerun()
            if st.button("漢字・読み方設定（保護者向け・両教科共通）", key="display_open", use_container_width=True):
                st.session_state.display_return = st.session_state.screen
                st.session_state.screen = "display_settings"
                st.rerun()
