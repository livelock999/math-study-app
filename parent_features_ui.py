"""保護者の週間レポート・学習目標・履歴書き出し。"""

from datetime import datetime
import sqlite3

import streamlit as st

from activity import JST
from cross_subject import load_records
from learning import USERS
import learning_extensions as store
import school_scope as school
from parent_insights import weekly_report, error_analysis, csv_export, review_forecast
from practice_mode import is_test_mode
from history_backup_ui import render_backup


def rate(value):
    return f"{value:.0%}" if value is not None else "—"


def render_dashboard():
    user_id = st.session_state.user_id
    st.subheader(f"{USERS[user_id]}の 週間レポート・学習目標")
    if st.button("もどる", key="parent_dashboard_back"):
        st.session_state.screen = st.session_state.get("parent_dashboard_return", "settings")
        st.rerun()
    now = datetime.now(JST)
    try:
        math, japanese = load_records(user_id)
    except (sqlite3.Error, OSError, ValueError, KeyError, TypeError):
        st.error("レポートを読み込めませんでした。保存先と接続を確認してください。")
        if st.button("読み込みをやりなおす", key="parent_dashboard_reload"):
            st.rerun()
        return
    goal_error = False
    try:
        goals = store.read_goals(user_id)
    except (sqlite3.Error, OSError, ValueError):
        goal_error = True
        goals = {"weekly_days": 3, "daily_questions": 5}
        st.warning("学習目標を読み込めませんでした。接続と追加SQLの適用を確認してください。")
    if is_test_mode(st.session_state):
        goals = st.session_state.get("parent_goals_preview", {}).get(user_id, goals)
    report = weekly_report(math, japanese, user_id, now=now, goals=goals)
    weekly, errors, settings = st.tabs(["今週のようす", "つまずき・復習予定", "目標・記録の保存"])
    with weekly:
        _show_weekly(report)
    with errors:
        _show_errors(error_analysis(math, japanese, user_id, now=now))
        st.write("**復習の見通し**")
        forecasts = []
        for subject, title, rows in (("math", "算数", math), ("japanese", "国語", japanese)):
            try:
                scope = school.active_scope(user_id, st.session_state)
                pool = school.review_pool(rows, user_id, scope, subject, now=now)
                prediction = review_forecast(rows, user_id, subject, now=now,
                                             limit=st.session_state.get("math_review_limit", 10),
                                             particle_level=(st.session_state.get("jp_particle_level", 1)
                                                             if st.session_state.get("jp_category") == "particles" else None),
                                             candidate_pool=pool)
            except (sqlite3.Error, OSError, ValueError, KeyError, TypeError):
                st.warning(f"{title}の学校範囲と復習予定を確認できませんでした。接続と追加SQLを確認してください。")
                continue
            forecasts.append({"教科": title, "きょうの対象": prediction["today_total"],
                              "きょう取り組む目安": prediction["today_count"],
                              "あした新しく対象": prediction["tomorrow_total"],
                              "あした取り組む目安": prediction["tomorrow_count"]})
        st.dataframe(forecasts, hide_index=True, width="stretch")
        st.caption("各教科1日5問までです。期限を迎える保存済み問題だけを数えています。"
                   "基本問題の補充は含まず、きょうの回答によって予定は変わります。")
    with settings:
        _show_goals(user_id, goals, disabled=goal_error and not is_test_mode(st.session_state))
        st.write("**学習記録の書き出し**")
        st.caption("選択中のお子さまの、両教科の保存済み全履歴をCSVで保存します。保護者テストの回答は含みません。")
        st.download_button("両教科の履歴をCSVで保存", data=csv_export(math, japanese, user_id, now=now),
                           file_name=f"learning-{user_id}-{now:%Y%m%d}.csv", mime="text/csv",
                           key="parent_history_csv", on_click="ignore", use_container_width=True)
        render_backup(user_id, math, japanese, now)
        _show_feedback(user_id)


def _show_goals(user_id, goals, disabled=False):
    st.write("**取り組む目標（両教科共通）**")
    st.caption("正答数ではなく、取り組んだ日数と問題数で達成を見ます。再練習の繰り返しは問題数を増やしません。")
    with st.form(f"learning_goal_form_{user_id}"):
        weekly_days = st.number_input("週に取り組む日数", min_value=1, max_value=7,
                                      value=goals["weekly_days"], step=1, key=f"learning_goal_days_{user_id}")
        daily_questions = st.number_input("1日に取り組む問題数", min_value=1, max_value=20,
                                          value=goals["daily_questions"], step=1,
                                          key=f"learning_goal_questions_{user_id}")
        label = "保存せずに目標を試す" if is_test_mode(st.session_state) else "学習目標を保存"
        submitted = st.form_submit_button(label, disabled=disabled, use_container_width=True)
    if submitted:
        if is_test_mode(st.session_state):
            preview = dict(st.session_state.get("parent_goals_preview", {}))
            preview[user_id] = {"weekly_days": weekly_days, "daily_questions": daily_questions}
            st.session_state.parent_goals_preview = preview
            st.success("このブラウザで目標を試せます。保存していません。")
        else:
            try:
                store.save_goals(user_id, weekly_days, daily_questions)
            except (sqlite3.Error, OSError, ValueError):
                st.error("目標を保存できませんでした。入力を保ったまま、もう一度保存できます。")
            else:
                st.success("両教科の学習目標を保存しました。")


def _show_feedback(user_id):
    with st.expander("保護者からの問題報告"):
        try:
            rows = store.read_feedback(user_id)
        except (sqlite3.Error, OSError, ValueError):
            st.info("問題報告を読み込めませんでした。接続と追加SQLの適用を確認してください。")
            return
        reasons = {"difficult": "難しすぎる", "reading": "読みづらい", "answer": "答えを確認したい"}
        if not rows:
            st.caption("報告はまだありません。問題画面の保護者向け表示から残せます。")
            return
        st.dataframe([{"日時": r["datetime"], "教科": "算数" if r["subject"] == "math" else "国語",
                       "問題ID": r["problem_id"], "内容": reasons.get(r["reason"], r["reason"])} for r in rows],
                     hide_index=True, width="stretch")
        st.caption("このアプリ内の確認用記録です。自動で外部へ送信しません。")


def _show_weekly(report):
    st.caption(f"日本時間 {report['start']}〜{report['end']} ／ 比較：{report['previous_start']}〜{report['previous_end']}")
    goals = report["goals"]
    active, reached = st.columns(2)
    active.metric("取り組んだ日", f"{goals['learning_days']} / {goals['weekly_days']}日")
    reached.metric("1日の目標を達成した日", f"{goals['daily_goal_days']}日")
    if goals["weekly_goal_met"]:
        st.success("今週の取り組む日数の目標を達成しました。")
    else:
        st.info(f"今週の目標まであと{goals['weekly_days'] - goals['learning_days']}日です。短い練習から続けましょう。")
    summary = []
    for data in report["subjects"].values():
        change = data["initial_rate_change"]
        summary.append({"教科": data["label"], "取り組んだ日": data["learning_days"],
                        "初回回答": data["initial"]["count"], "初回正答率": rate(data["initial"]["rate"]),
                        "前週の初回正答率": rate(data["previous_initial"]["rate"]),
                        "前週との差": f"{change * 100:+.0f}ポイント" if change is not None else "—",
                        "初回ヒント使用率": rate(data["initial"]["hint_rate"]),
                        "復習回答": data["review"]["count"], "復習正答率": rate(data["review"]["rate"]),
                        "復習の再練習": data["review_retry"]["count"],
                        "類題の練習": data["adaptive"]["count"],
                        "わからない": data["all"]["dont_know_count"]})
    st.dataframe(summary, hide_index=True, width="stretch")
    st.caption("初回の集計は既存レポートと同じ基準です。復習は別枠で表示します。"
               "問題の難しさや回答数が変わるため、正答率の差だけで成長を判断しません。")
    with st.expander("ヒントの段階と、自分でできたこと"):
        levels = []
        for data in report["subjects"].values():
            for level, label in ((0, "ヒントなし"), (1, "考えるきっかけ"), (2, "具体的な見方"), (3, "解き方の手順")):
                levels.append({"教科": data["label"], "最後に使った段階": label,
                               "回答数": data["all"]["hint_levels"].get(level, 0)})
        st.dataframe(levels, hide_index=True, width="stretch")
        st.caption("段階を記録した回答だけを数えます。以前のヒント段階が不明な回答は含みません。")
        if report["growth"]:
            st.dataframe([{"教科": "算数" if item["subject"] == "math" else "国語", "できたこと": item["reason"],
                           "問題": item["question_text"], "自力で解けた日時": item["after_at"]}
                          for item in report["growth"]], hide_index=True, width="stretch")
        else:
            st.caption("以前の誤答・ヒント使用から自力正解に変わった問題は、まだ記録されていません。")
    st.write("**毎日の取り組み**")
    st.dataframe([{"日付": day["date"], "取り組み": "あり" if day.get("active", day["count"] > 0) else "これから", "取り組んだ問題": day["count"],
                   "1日の目標": "達成" if day["daily_goal_met"] else "これから"}
                  for day in report["attendance"]], hide_index=True, width="stretch")


def _show_errors(report):
    st.write("**算数：どの段階を確かめるか**")
    st.dataframe([{"項目": row["label"], "評価できる回答": row["count"],
                   "間違い": row["wrong_count"], "間違いの割合": rate(row["wrong_rate"])}
                  for row in report["math"]["components"]], hide_index=True, width="stretch")
    st.caption("通常の初回回答が対象です。式・計算の記録がない項目は未評価です。読み違いなどの原因を断定しません。")
    st.write("**国語：練習する分野**")
    categories = report["japanese"]["categories"]
    if categories:
        st.dataframe([{"分野": row["label"], "回答数": row["count"], "間違い": row["wrong_count"],
                       "正答率": rate(row["rate"])} for row in categories], hide_index=True, width="stretch")
    else:
        st.caption("国語の初回回答はまだありません。")
    if report["japanese"]["error_tags"]:
        st.dataframe([{"間違いに付いている分類": row["label"], "件数": row["count"]}
                      for row in report["japanese"]["error_tags"]], hide_index=True, width="stretch")
    if report["japanese"]["particles"]:
        st.dataframe([{"助詞の選択の違い": row["label"], "件数": row["count"]}
                      for row in report["japanese"]["particles"]], hide_index=True, width="stretch")
    st.caption(f"「わからない」の初回回答：算数{report['dont_know']['math']}問、国語{report['dont_know']['japanese']}問。"
               "正答率では未正解として数え、選んだ答えの間違い方とは分けています。")
