"""国語画面。既存の算数の進行状態を変えず、科目を切り替えます。"""

from pathlib import Path
from datetime import datetime
import sqlite3
import math
import streamlit as st
import streamlit.components.v1 as components

import learning
import japanese as jp
from japanese_questions import CATEGORIES, QUESTION_LABELS, ERROR_LABELS
from furigana import READINGS

keyboard = components.declare_component("japanese_keyboard", path=str(Path(__file__).parent / "japanese_keyboard"))


def goto(screen):
    st.session_state.screen = screen
    st.rerun()


def open_view(screen, origin):
    st.session_state[f"{screen}_return"] = origin
    goto(screen)


def initialize():
    try:
        jp.init_db()
    except (sqlite3.Error, OSError, ValueError):
        st.error("国語の保存先を開けません。保存先設定を確認してください。")
        if st.button("もういちど", key="jp_init_retry"):
            st.rerun()
        st.stop()


def start(questions, selection="normal"):
    if selection != "retry":
        st.session_state.jp_counts = {}
        st.session_state.jp_first_correct = {}
        st.session_state.jp_chains = {q["question_id"]: learning.new_id("jp_chain") for q in questions}
    st.session_state.jp_round = {"session_id": learning.new_id("jp_session"), "questions": questions,
                                 "selection": selection, "index": 0, "answers": [], "phase": "question",
                                 "pending": None, "user_id": st.session_state.user_id,
                                 "paused": False, "resume_revision": 0, "draft": {}}
    goto("jp_practice")


def load():
    try:
        return jp.read_all(st.session_state.user_id)
    except (sqlite3.Error, OSError, ValueError, KeyError, TypeError):
        st.error("国語の履歴を読み込めませんでした。保存先と接続を確認してください。")
        if st.button("読み込みをやりなおす", key="jp_reload"):
            st.rerun()
        return None


def navigation(origin):
    if st.button("国語の学習履歴", key=f"jp_history_{origin}", use_container_width=True):
        st.session_state.jp_history_page = 0
        open_view("jp_history", origin)
    if st.button("国語の苦手分析（保護者向け）", key=f"jp_analysis_{origin}", use_container_width=True):
        open_view("jp_analysis", origin)


def settings():
    initialize()
    st.subheader(f"{learning.USERS[st.session_state.user_id]}、こくごを れんしゅうしよう")
    paused = st.session_state.get("jp_round")
    if paused and paused.get("paused") and paused.get("user_id") == st.session_state.user_id:
        st.caption("とちゅうの れんしゅうが あるよ。あたらしく はじめても、ほぞんした こたえは のこります。")
        if st.button("つづきから", key="jp_resume", type="primary", use_container_width=True):
            paused["paused"] = False
            goto("jp_practice")
    categories = {"mix": "おまかせ", **CATEGORIES}
    category = st.radio("れんしゅうする こと", list(categories), format_func=categories.get, key="jp_category")
    particle_level = None
    if category == "particles":
        from particles import LEVELS
        particle_level = st.radio("てにをはの レベル", [None, 1, 2, 3],
                                  format_func=lambda n: "おまかせ" if n is None else LEVELS[n], key="jp_particle_level")
    count = st.radio("もんだいの かず", [5, 10], index=1, format_func=lambda n: f"{n}もん",
                     horizontal=True, key="jp_count")
    if st.button("こくご スタート", key="jp_start", type="primary", use_container_width=True):
        start(jp.choose_questions(category, count, particle_level=particle_level))
    if st.button("にがてを れんしゅう", key="jp_weak", use_container_width=True):
        records = load()
        if records is not None:
            from particles import analyze as analyze_particles
            if category == "particles" or analyze_particles(records)["priority_pairs"]:
                start(jp.choose_questions("particles", count, particle_level=particle_level, records=records), "weak_area")
            report = jp.analyze(records)
            if report["weak_categories"]:
                start(jp.choose_questions("mix", count, report["weak_categories"], records=records), "weak_area")
            else:
                st.info("まだ にがてが みつかっていないよ。おまかせで れんしゅうしてね。")
    if st.button("まちがえた もんだいを れんしゅう", key="jp_past_mistakes", use_container_width=True):
        records = load()
        if records is not None:
            latest = {}
            for record in records:  # 履歴は最新順。最後に正解した問題は除きます。
                latest.setdefault(record["question_id"], record)
            wrong = [r for r in latest.values() if not r["correct"]]
            if wrong:
                wrong = wrong[:count]
                st.session_state.jp_counts = {r["question_id"]: r["attempt_count"] for r in wrong}
                st.session_state.jp_chains = {r["question_id"]: r["chain_id"] for r in wrong}
                st.session_state.jp_first_correct = {r["question_id"]: r.get("first_try_correct", r["correct"]) for r in wrong}
                start([snapshot(r) for r in wrong], "retry")
            else:
                st.info("いまは まちがえた もんだいが ないよ。")
    navigation("jp_settings")
    if st.button("さんすうへ", key="jp_math"):
        goto("settings")
    if st.button("なまえを かえる", key="jp_change_user"):
        goto("user")


def snapshot(record):
    fields = ("question_id", "category", "problem_format", "text", "question", "choices", "answer",
              "skill_tags", "question_word", "reasoning_level", "difficulty", "hint", "explanation",
              "error_tags", "version")
    question = {key: record[key] for key in fields}
    if record["category"] == "particles":
        for key in ("question_type", "level", "sentence", "correct_answer", "target_particle",
                    "semantic_role", "verb", "noun", "comparison_id"):
            question[key] = record[key]
        question["confusion_pair"] = record["expected_confusion_pair"]
    return question


def save_pending(state):
    try:
        jp.save_record(state["pending"])
    except (sqlite3.Error, OSError, ValueError):
        return False
    record = state["pending"]
    state["answers"].append(record)
    st.session_state.jp_counts[record["question_id"]] = record["attempt_count"]
    if record["attempt_count"] == 1:
        st.session_state.setdefault("jp_first_correct", {})[record["question_id"]] = record["correct"]
    state["pending"] = None
    state["phase"] = "feedback"
    return True


def practice():
    state = st.session_state.jp_round
    index = state["index"]
    question = state["questions"][index]
    st.caption(f"{learning.USERS[st.session_state.user_id]} ／ こくご")
    st.progress(index / len(state["questions"]), text=f"{index + 1} / {len(state['questions'])} もん")
    if state["pending"] is not None:
        st.write(question["text"])
        st.write(question["question"])
        st.write(f"あなたの こたえ：{state['pending']['selected_answer_text']}")
        st.error("きろくを ほぞんできませんでした。もういちど ボタンを おしてね。")
        if st.button("ほぞんを やりなおす", key="jp_retry_save", type="primary"):
            if save_pending(state):
                st.rerun()
        return
    token = f"{state['session_id']}:{index}:{state['phase']}"
    if state.get("resume_revision", 0):
        token += f":resume{state['resume_revision']}"
    previous = state["answers"][-1] if state["phase"] == "feedback" else None
    event = keyboard(token=token, question_id=f"{state['session_id']}:{index}", phase=state["phase"],
                     text=question["text"], question=question["question"], choices=question["choices"],
                     form=question["problem_format"], hint=question["hint"],
                     correct=previous["correct"] if previous else None,
                     selected=previous["selected_answer_text"] if previous else None,
                     correct_answer=jp.answer_text(question, question["answer"]) if previous else None,
                     explanation=question["explanation"] if previous else None,
                     last=index + 1 == len(state["questions"]), key="jp_keyboard", default=None,
                     draft=state.get("draft", {}), furigana=READINGS)
    # 問題中にiframeを破棄するとヒントと計測開始が消えるため、移動は回答保存後に限ります。
    if state["phase"] == "feedback":
        navigation("jp_practice")
    if not isinstance(event, dict) or event.get("token") != token:
        return
    if event.get("action") == "back":
        seconds = event.get("response_time_sec")
        order = event.get("draft_order", [])
        if (type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds < 0
                or type(event.get("hint_used")) is not bool or not isinstance(order, list)
                or any(type(i) is not int or not 0 <= i < len(question["choices"]) for i in order)
                or len(order) != len(set(order))):
            return
        state["draft"] = {"order": order, "hint_used": event["hint_used"], "elapsed": seconds}
        state["user_id"] = st.session_state.user_id
        state["paused"] = True
        state["resume_revision"] = state.get("resume_revision", 0) + 1
        goto("jp_settings")
    if state["phase"] == "question" and event.get("action") == "answer":
        try:
            record = jp.make_record(question, st.session_state.user_id, state["session_id"], index + 1,
                                    state["selection"], event.get("answer"), event.get("response_time_sec"),
                                    st.session_state.jp_counts.get(question["question_id"], 0) + 1,
                                    st.session_state.jp_chains[question["question_id"]], event.get("hint_used", False),
                                    first_try_correct=st.session_state.get("jp_first_correct", {}).get(question["question_id"]))
        except (ValueError, TypeError):
            st.error("こたえを たしかめてね。")
            return
        state["pending"] = record
        save_pending(state)
        st.rerun()
    elif state["phase"] == "feedback" and event.get("action") == "next":
        if index + 1 == len(state["questions"]):
            goto("jp_results")
        state["index"] += 1
        state["phase"] = "question"
        state["draft"] = {}
        st.rerun()


def results():
    state = st.session_state.jp_round
    correct = sum(r["correct"] for r in state["answers"])
    st.subheader("こくごの れんしゅう おわり！")
    st.metric("せいかい", f"{len(state['answers'])}もんちゅう {correct}もん")
    st.metric("せいかいりつ", f"{correct / len(state['answers']):.0%}")
    wrong = [q for q, row in zip(state["questions"], state["answers"]) if not row["correct"]]
    if wrong:
        if st.button("まちがえた もんだいを もういちど", key="jp_retry", type="primary", use_container_width=True):
            start(wrong, "retry")
    else:
        st.success("ぜんぶ せいかい！ よく がんばったね！")
    navigation("jp_results")
    if st.button("あたらしい もんだい", key="jp_new", use_container_width=True):
        goto("jp_settings")
    if st.button("なまえを かえる", key="jp_results_user"):
        goto("user")


def back(screen):
    if st.button("もどる", key=f"{screen}_back"):
        goto(st.session_state[f"{screen}_return"])


def history():
    st.subheader(f"{learning.USERS[st.session_state.user_id]}の 国語の学習履歴")
    back("jp_history")
    records = load()
    if records is None:
        return
    if not records:
        st.info("まだ国語の学習履歴がありません。")
        return
    page = st.session_state.jp_history_page
    latest_chain = {}
    for row in sorted(records, key=lambda r: (r["attempt_count"], r["datetime"], r["attempt_id"]), reverse=True):
        latest_chain.setdefault(row["chain_id"], row)
    table = [{"日時（日本時間）": datetime.fromisoformat(r["datetime"]).astimezone(jp.JST).strftime("%Y/%m/%d %H:%M:%S"),
              "問題": r["question"], "本文": r["text"], "回答": r["selected_answer_text"],
              "正解": jp.answer_text(r, r["answer"]), "正誤": "○" if r["correct"] else "×",
              "分野": CATEGORIES[r["category"]], "スキルタグ": "・".join(r["skill_tags"]),
              "質問タイプ": QUESTION_LABELS[r["question_word"]], "難易度": r["difficulty"],
              "思考レベル": r["reasoning_level"], "回答時間（秒）": r["response_time_sec"],
              "回答回数": r["attempt_count"], "ヒント": "あり" if r["hint_used"] else "なし",
              "読み方": "自力読み" if r["reading_mode"] == "self_read" else "読み上げ",
              "再回答": "あり" if r["retry_flag"] else "なし",
              "最終正誤（現在まで）": "○" if latest_chain[r["chain_id"]]["correct"] else "×",
              "誤答の傾向": "・".join(ERROR_LABELS[t] for t in r["error_cause_tags"])}
             for r in records[page * 50:(page + 1) * 50]]
    st.caption(f"{page + 1}ページ ／ 全{len(records)}回答。初回の不正解も上書きせず残します。")
    st.dataframe(table, hide_index=True, use_container_width=True)
    particle_rows = [r for r in records[page * 50:(page + 1) * 50] if r["category"] == "particles"]
    if particle_rows:
        from particles import ROLES
        st.write("**てにをはの回答の内訳**")
        st.dataframe([{"問題": r["sentence"], "正しい助詞": r["correct_answer"],
                       "選んだ助詞": r["selected_answer_text"], "初回正解": r.get("first_try_correct"),
                       "混同": r["confusion_pair"] or "なし", "意味役割": ROLES[r["semantic_role"]],
                       "レベル": r["level"], "再回答回数": r["retry_count"]} for r in particle_rows],
                     hide_index=True, use_container_width=True)
    left, right = st.columns(2)
    if left.button("前のページ", key="jp_prev_page", disabled=page == 0):
        st.session_state.jp_history_page -= 1
        st.rerun()
    if right.button("次のページ", key="jp_next_page", disabled=(page + 1) * 50 >= len(records)):
        st.session_state.jp_history_page += 1
        st.rerun()


def percent(value):
    return "—" if value is None else f"{value:.0%}"


def analysis():
    st.subheader(f"{learning.USERS[st.session_state.user_id]}の 国語の苦手分析")
    back("jp_analysis")
    records = load()
    if records is None:
        return
    mode = st.radio("読み方を分けて集計", ["self_read", "audio"],
                    format_func=lambda m: "自力読み" if m == "self_read" else "読み上げ", key="jp_reading_filter")
    report = jp.analyze(records, reading_mode=mode)
    summary = report["summary"]
    if not summary["total"]:
        st.info("この読み方の学習記録はまだありません。読み上げ機能は今後追加予定です。" if mode == "audio"
                else "まだ国語の学習記録がありません。")
        return
    st.caption("外部AIは使いません。正答率・時間・ヒント・再回答・誤答の傾向を組み合わせた参考評価です。")
    st.write(f"**今週の学習**（{report['week_start']:%m/%d}〜、日本時間）")
    week = report["week"]
    first, second = st.columns(2)
    first.metric("今週の回答数（再回答を含む）", f"{week['total']}問")
    second.metric("今週の初回正答率", percent(week["rate"]))
    st.write("**これまでの学習**")
    st.write(f"総回答数：{summary['total']}問 ／ 正解数：{summary['correct']}問 ／ "
             f"全回答の正答率：{percent(summary['correct'] / summary['total'])}")
    st.write(f"初回回答：{summary['count']}問 ／ 初回正答率：{percent(summary['rate'])} ／ "
             f"平均回答時間：{summary['seconds']:.1f}秒 ／ ヒント使用率：{percent(summary['hint_rate'])}"
             if summary["count"] else "この集計には初回の回答がありません。")
    st.write(f"再回答成功：{summary['retry_success']} / {summary['retry_count']}問 ／ "
             f"現在までの最終正解：{summary['eventual_correct']} / {summary['chains']}問")
    from particles_ui import show_report
    show_report([r for r in records if r["reading_mode"] == mode])
    for title, key in [("分野別", "category"), ("スキルタグ別", "tags"), ("質問タイプ別", "question_word"),
                       ("難易度別", "difficulty"), ("思考レベル別", "reasoning")]:
        st.write(f"**{title}**")
        table = [{"分類": g["label"], "初回回答数": g["count"], "初回正答率": percent(g["rate"]),
                  "平均時間（秒）": round(g["seconds"], 1) if g["seconds"] is not None else None,
                  "ヒント率": percent(g["hint_rate"]), "再回答成功": f"{g['retry_success']}/{g['retry_count']}",
                  "評価": g["status"], "気になる傾向": "・".join(g["signals"])} for g in report[key]]
        if table:
            st.dataframe(table, hide_index=True, use_container_width=True)
    strong = [g["label"] for g in report["category"] if g["status"] in ("◎ 得意", "○ できる")]
    if strong:
        st.success("できている分野：" + "、".join(strong))
    if report["weak_categories"]:
        st.info("次に練習したい分野：" + "、".join(CATEGORIES[key] for key in report["weak_categories"]))
        if st.button("にがてを れんしゅう", key="jp_analysis_practice", type="primary"):
            start(jp.choose_questions("mix", 5, report["weak_categories"], records=records), "weak_area")
    errors = summary["error_counts"]
    if errors:
        st.write("**選んだ誤答から分かる傾向**")
        st.write("、".join(f"{ERROR_LABELS[tag]}：{count}回" for tag, count in errors.items()))
    with st.expander("評価基準と記録の見方"):
        st.write("5問未満は判断保留。初回正答率90%以上＝◎、80%以上＝○、60%以上＝△、60%未満＝×。"
                 "初回のヒント使用率30%以上、同じ誤答タグ3回以上、正解時の平均時間が本人の全体平均の1.5倍かつ30秒を超える"
                 "（正解5問以上）場合は、◎・○でも△にします。時間だけで×にはしません。")
        st.write("再回答は初回正答率と分け、説明後の成功を表示します。最終正誤は同じ問題の初回から続く"
                 "再練習の最新結果です。誤答原因は選択肢に基づく可能性で、読めない・ケアレスミス等は断定しません。"
                 "問題の長さ・休憩・操作も時間に影響します。スキルタグは重複して集計されます。")


SCREENS = {"jp_settings": settings, "jp_practice": practice, "jp_results": results,
           "jp_history": history, "jp_analysis": analysis}
