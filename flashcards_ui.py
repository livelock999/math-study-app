"""けいさんカードの画面。回答保存が成功してから次のカードに進みます。"""

from pathlib import Path
from html import escape
import math
import sqlite3
import time
import streamlit as st
import streamlit.components.v1 as components

import learning
import flashcards
from practice_mode import is_test_mode, is_test_round, write_learning_answer

keyboard = components.declare_component("flashcard_keyboard", path=str(Path(__file__).parent / "flashcard_keyboard"))


def goto(screen):
    st.session_state.screen = screen
    st.rerun()


def open_screen(screen, origin="settings"):
    st.session_state.fc_return = origin
    goto(screen)


def start_round(cards, answer_min=11, answer_max=18, order="shuffle", selection_type="normal", first_attempt_correct=None,
                mode="addition", operand_max=None):
    if (not cards or selection_type not in ("normal", "retry") or mode not in ("addition", "subtraction", "mixed")
            or not (operand_max is None or type(operand_max) is int and operand_max == 100)):
        raise ValueError("カードのセットが不正です。")
    if selection_type == "normal":
        st.session_state.fc_attempt_counts = {}
    st.session_state.fc_round = {
        "session_id": learning.new_id("flashcard"), "user_id": st.session_state.user_id,
        "test_mode": is_test_mode(st.session_state), "cards": cards, "index": 0, "answers": [],
        "phase": "question", "pending": None, "candidate": None, "revision": 0,
        "voice_failures": 0, "total_voice_failures": 0, "elapsed_sec": 0, "session_elapsed_sec": 0,
        "started_at": time.monotonic(), "voice_enabled": False,
        "answer_min": answer_min, "answer_max": answer_max, "order": order,
        "mode": mode, "operand_max": operand_max,
        "selection_type": selection_type, "first_attempt_correct": list(first_attempt_correct or [None] * len(cards)),
    }
    goto("flashcard_practice")


def answer_settings(mode):
    """範囲の切り替えなしで、小さい答えから100以上まで指定できます。"""
    maximum = 100 if mode == "subtraction" else 200
    low, high = {"addition": (11, 18), "subtraction": (0, 9), "mixed": (0, 18)}[mode]
    return 0, maximum, low, high


def reset_mode_range():
    """演算を変えたら、その演算の初期範囲に戻します。"""
    _, _, low, high = answer_settings(st.session_state.fc_mode)
    st.session_state.fc_min = low
    st.session_state.fc_max = high
    if st.session_state.fc_mode == "mixed":
        st.session_state.fc_order = "shuffle"


def settings_screen():
    with st.container(key="fc_settings"):
        _settings_form()


def _settings_form():
    with st.container(key="fc_settings_header"):
        back, title = st.columns([1, 4], gap="small")
        with back:
            if st.button("もどる", key="fc_back", use_container_width=True):
                goto("settings")
        with title:
            name = escape(learning.USERS[st.session_state.user_id])
            st.markdown(f'<h3 class="fc-settings-title"><span>{name} ｜</span> けいさんカード</h3>',
                        unsafe_allow_html=True)
    mode = st.radio("カードの種類", ["addition", "subtraction", "mixed"],
                    format_func=lambda value: {"addition": "たし算", "subtraction": "ひき算",
                                               "mixed": "ミックス"}[value],
                    horizontal=True, key="fc_mode", on_change=reset_mode_range)
    descriptions = {
        "addition": "答えは0〜200から選べます。100までの数を使う たし算にも対応しています。",
        "subtraction": "答えは0〜100から選べます。マイナスになる ひき算は出しません。",
        "mixed": "たし算とひき算をほぼ半分ずつ、シャッフルで出します。答えは0〜200から選べます。",
    }
    minimum, maximum, low_default, high_default = answer_settings(mode)
    # 更新前から開いていた設定の有効な値は維持し、上限外だけ補正します。
    for key in ("fc_min", "fc_max"):
        value = st.session_state.get(key)
        if type(value) is int and not minimum <= value <= maximum:
            st.session_state[key] = max(minimum, min(maximum, value))
    with st.container(key="fc_answer_range"):
        st.markdown("**答えの範囲**")
        smaller, larger = st.columns(2, gap="small")
        with smaller:
            low = st.number_input("小さい数", minimum, maximum, low_default, key="fc_min")
        with larger:
            high = st.number_input("大きい数", minimum, maximum, high_default, key="fc_max")
    count = st.select_slider("カードの数", [5, 10, 20, 30, 50], value=20, key="fc_count")
    order = st.radio("順番", ["shuffle", "ordered"], format_func=lambda value: "シャッフル" if value == "shuffle" else "順番どおり",
                     horizontal=True, key="fc_order", disabled=mode == "mixed")
    if mode == "mixed":
        order = "shuffle"
    # 従来の答え範囲で成立するセットは、問題・IDをそのまま使います。
    # 広い範囲や0のたし算は100までのカードへ自動的に広げます。
    operand_max = None if flashcards.selection_error(low, high, count, order, mode) is None else 100
    error = ("小さい数を、大きい数以下にしてください。" if low > high
             else flashcards.selection_error(low, high, count, order, mode, operand_max))
    if error:
        st.info(error)
    if st.button("カード スタート", key="fc_start", type="primary", disabled=error is not None, use_container_width=True):
        start_round(flashcards.generate_cards(low, high, count, order, mode, operand_max),
                    low, high, order, mode=mode, operand_max=operand_max)
    with st.expander("つかいかた"):
        st.caption(descriptions[mode])
        st.caption("答えを声・数字キー・テンキーで回答すると、自動で次へ進みます。わからないときは答えを見てから次へ進めます。")


def settings_notes():
    """アプリ共通の保護者向け折りたたみ内に表示する、カードの注意事項。"""
    st.caption("狭い範囲では同じカードを繰り返します。声が数として分からないときは採点しません。")
    st.caption("音声ファイルは保存しません。ブラウザーの音声認識サービスが音声を処理する場合があります。"
               "対応状況は端末・ブラウザーで異なり、使えない場合はテンキーで回答できます。")


def persist_pending(state):
    record = state["pending"]
    try:
        write_learning_answer(state, st.session_state, learning.save_attempt, record)
    except (sqlite3.Error, OSError, ValueError):
        return False
    state["answers"].append(record)
    st.session_state.setdefault("fc_attempt_counts", {})[record["problem_id"]] = record["attempt_count"]
    state["session_elapsed_sec"] = record["session_elapsed_sec"]
    state["pending"] = None
    state["candidate"] = None
    state["phase"] = "saved"
    if state.pop("advance_after_save", False):
        advance_saved_card(state)
    return True


def advance_saved_card(state):
    """保存済み回答だけで進行。連続音声では中間画面の往復を省きます。"""
    if state["index"] + 1 == len(state["cards"]):
        state["phase"] = "finished"
        return
    state.update(index=state["index"] + 1, phase="question", revision=0,
                 elapsed_sec=0, voice_failures=0)


def queue_answer(state, answer, method, transcript, seconds, dont_know_used=False):
    index = state["index"]
    problem = state["cards"][index]
    count = st.session_state.setdefault("fc_attempt_counts", {}).get(problem["problem_id"], 0) + 1
    if state["selection_type"] == "retry":
        count = max(2, count)
    record = learning.make_attempt(problem, state["user_id"], state["session_id"], index + 1,
                                   state["selection_type"], answer, seconds, count, round_size=len(state["cards"]),
                                   dont_know_used=dont_know_used)
    first = state["first_attempt_correct"][index]
    if first is None:
        first = next((row["first_attempt_correct"] for row in state["answers"]
                      if row["problem_id"] == problem["problem_id"]), record["is_correct"])
    now = time.monotonic()
    record.update(learning_mode="flashcard", answer_range_min=state["answer_min"], answer_range_max=state["answer_max"],
                  input_method=method, recognized_text=transcript, parsed_answer=answer if method == "voice" else None,
                  recognition_success=True if method == "voice" else None,
                  recognition_retry_count=state["voice_failures"], first_attempt_correct=first,
                  session_elapsed_sec=max(now - state.get("started_at", now),
                                          state["session_elapsed_sec"] + record["response_time_sec"]),
                  total_recognition_retry_count=state["total_voice_failures"])
    state["pending"] = record
    # 正解した連続音声だけを即時に進める。失敗時もこの方針と同じ回答IDを保持。
    state["advance_after_save"] = method == "voice" and state["voice_enabled"] and record["is_correct"]
    persist_pending(state)


def practice_screen():
    state = st.session_state.fc_round
    if state["user_id"] != st.session_state.user_id:
        goto("flashcard_settings")
    if state["phase"] == "finished":
        goto("flashcard_results")
    index = state["index"]
    problem = state["cards"][index]
    st.caption(f"{learning.USERS[state['user_id']]} ／ けいさんカード ／ {index + 1} / {len(state['cards'])}")
    if is_test_round(state, st.session_state):
        st.caption("保護者おためし：回答は学習履歴へ保存しません。")
    if state["pending"] is not None:
        st.error("回答を保存できませんでした。保存できるまで次のカードへは進みません。")
        if st.button("ほぞんを やりなおす", key="fc_retry_save", type="primary"):
            if persist_pending(state):
                st.rerun()
        return
    token = f"{state['session_id']}:{index}:{state['phase']}:{state['revision']}"
    last = state["answers"][-1] if state["phase"] == "saved" else None
    event = keyboard(token=token, question_id=f"{state['session_id']}:{index}", phase=state["phase"],
                     question=problem["question_text"], correct=last["is_correct"] if last else None,
                     dont_know_used=last.get("dont_know_used", False) if last else False,
                     correct_answer=problem["correct_answer"] if last and last.get("dont_know_used") else None,
                     candidate=state["candidate"]["answer"] if state["candidate"] else None,
                     elapsed_sec=state["elapsed_sec"], voice_failures=state["voice_failures"],
                     previous_correct=(state["answers"][-1]["is_correct"]
                                       if state["phase"] == "question" and index > 0 else None),
                     voice_enabled=state["voice_enabled"], key="fc_keyboard", default=None)
    if not isinstance(event, dict) or event.get("token") != token:
        return
    action = event.get("action")
    seconds = event.get("response_time_sec", state["elapsed_sec"])
    if type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds < 0:
        return
    seconds = max(seconds, state["elapsed_sec"])
    state["elapsed_sec"] = seconds
    if type(event.get("voice_enabled")) is bool:
        state["voice_enabled"] = event["voice_enabled"]
    if action == "voice_off":
        state["voice_enabled"] = False
        state["revision"] += 1
        st.rerun()
    if state["phase"] == "saved" and action == "next":
        advance_saved_card(state)
        st.rerun()
    if state["phase"] == "confirm":
        if action == "confirm_voice":
            candidate = state["candidate"]
            queue_answer(state, candidate["answer"], "voice", candidate["text"], seconds)
            st.rerun()
        if action == "correct_voice":
            state.update(phase="question", candidate=None, revision=state["revision"] + 1)
            state["voice_failures"] += 1
            state["total_voice_failures"] += 1
            if state["voice_failures"] >= 3:
                state["voice_enabled"] = False
            st.rerun()
        return
    if state["phase"] != "question":
        return
    if action == "back":
        goto("flashcard_settings")
    if action == "dont_know":
        state["voice_enabled"] = False
        queue_answer(state, None, "keypad", None, seconds, dont_know_used=True)
        st.rerun()
    if action not in ("answer", "recognition_failed"):
        return
    method = event.get("input_method", "voice" if action == "recognition_failed" else None)
    transcript = event.get("recognized_text")
    if method == "voice":
        answer = flashcards.parse_spoken_number(transcript)
        if action == "recognition_failed" or answer is None:
            state["voice_failures"] += 1
            state["total_voice_failures"] += 1
            state["revision"] += 1
            if state["voice_failures"] >= 3:
                state["voice_enabled"] = False
            st.rerun()
        if answer != problem["correct_answer"]:
            state.update(phase="confirm", candidate={"answer": answer, "text": transcript})
            st.rerun()
    elif method in ("keyboard", "keypad"):
        answer = event.get("answer")
        if type(answer) is not int or not 0 <= answer <= 999:
            return
        transcript = None
    else:
        return
    queue_answer(state, answer, method, transcript, seconds)
    st.rerun()


def results_screen():
    state = st.session_state.fc_round
    if state["user_id"] != st.session_state.user_id:
        goto("flashcard_settings")
    summary = flashcards.summarize(state["answers"])
    st.subheader(f"{summary['count']}もん おわり！")
    st.metric("せいかい", f"{summary['correct']}もん せいかい")
    if summary["dont_know"]:
        st.caption(f"わからないを えらんだカード：{summary['dont_know']}もん。あとで もういちど やってみよう。")
    st.metric("へいきん", f"{summary['average_seconds']:.1f}びょう" if summary["count"] else "—")
    with st.expander("保護者向け：時間と回答の詳細"):
        st.write(f"正答率 {summary['rate']:.0%}" if summary["rate"] is not None else "まだ回答がありません。")
        if summary["first_rate"] is not None:
            st.write(f"同カードの初回正答率 {summary['first_rate']:.0%}（{summary['first_count']}回答）")
        st.write(f"開始から最終回答まで {state['session_elapsed_sec']:.1f}秒 ／ 音声のやりなおし {state['total_voice_failures']}回")
        if summary["count"]:
            st.write(f"最速 {summary['fastest_seconds']:.2f}秒 ／ 最長 {summary['slowest_seconds']:.2f}秒")
            st.dataframe(flashcards.report_tables(state["answers"])["problems"], hide_index=True, use_container_width=True)
        st.caption("問題表示から回答確定まで。音声認識の待ち時間も含み、純粋な計算速度とは異なります。")
    if not is_test_round(state, st.session_state):
        st.success("⭐ ごほうびスタンプを 1こ もらったよ！")
    mistakes = [(card, row) for card, row in zip(state["cards"], state["answers"]) if not row["is_correct"]]
    retry_label = "まちがえた・わからなかったカードを もういちど" if summary["dont_know"] else "まちがえたカードを もういちど"
    if mistakes and st.button(retry_label, key="fc_retry", type="primary"):
        start_round([card for card, _ in mistakes], state["answer_min"], state["answer_max"], state["order"],
                    "retry", [row["first_attempt_correct"] for _, row in mistakes], mode=state.get("mode", "addition"),
                    operand_max=state.get("operand_max"))
    if st.button("カードの設定へ", key="fc_settings"):
        goto("flashcard_settings")
    if st.button("保護者のカードレポート", key="fc_report_results"):
        open_screen("flashcard_report", "flashcard_results")


def report_screen():
    st.subheader(f"{learning.USERS[st.session_state.user_id]}の 計算カードレポート")
    if st.button("もどる", key="fc_report_back"):
        goto(st.session_state.get("fc_return", "settings"))
    if is_test_mode(st.session_state):
        st.info("おためしモードでは本番の学習履歴を表示しません。")
        return
    try:
        records = []
        page = 0
        while len(records) < 500:
            rows, more = learning.read_attempts(st.session_state.user_id, page=page, page_size=100)
            records.extend(row for row in rows if row.get("learning_mode") == "flashcard")
            if not more:
                break
            page += 1
        records = records[:500]
    except (sqlite3.Error, OSError, ValueError):
        st.error("レポートを読み込めませんでした。")
        if st.button("もういちど", key="fc_report_reload"):
            st.rerun()
        return
    if not records:
        st.info("カードの保存済み回答はまだありません。")
        return
    st.caption("カードの最新500回答。通常練習の習熟評価と混ぜません。認識遅延・確認時間を含むため参考値です。")
    with st.expander("セッションごとの成績"):
        st.dataframe(flashcards.session_table(records), hide_index=True, use_container_width=True)
    st.caption("同カードの初回は回答回数1だけで集計し、繰り返し回答を分母に加えません。")
    for title, subset in (("通常カード（同カードの初回）", [row for row in records if row["selection_type"] == "normal" and row["attempt_count"] == 1]),
                          ("同カードの2回目以降", [row for row in records if row["selection_type"] == "normal" and row["attempt_count"] > 1]),
                          ("再練習", [row for row in records if row["selection_type"] == "retry"])):
        st.write(f"**{title}**")
        tables = flashcards.report_tables(subset)
        for label, name in (("演算別", "operations"), ("問題別", "problems"), ("構造別", "structures"), ("答えの範囲別", "ranges"),
                            ("入力方法別", "inputs"), ("日別（日本時間）", "days")):
            if tables[name]:
                st.write(label)
                st.dataframe(tables[name], hide_index=True, use_container_width=True)


SCREENS = {"flashcard_settings": settings_screen, "flashcard_practice": practice_screen,
           "flashcard_results": results_screen, "flashcard_report": report_screen}
