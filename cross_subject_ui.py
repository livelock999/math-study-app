"""両教科から開ける保護者向け共通レポート。"""

import sqlite3
import streamlit as st
from learning import USERS
from cross_subject import load_records, build_report


def report_screen():
    st.subheader(f"{USERS[st.session_state.user_id]}の 共通レポート・教科横断分析")
    if st.button("もどる", key="cross_back"):
        st.session_state.screen = st.session_state.cross_return
        st.rerun()
    periods = {7: "最近7日", 30: "最近30日", None: "全期間"}
    days = st.radio("集計期間", list(periods), index=1, format_func=periods.get,
                    horizontal=True, key="cross_period")
    st.caption("両教科とも同じ期間・学習者で集計します。外部AIへの送信はありません。")
    try:
        math, japanese = load_records(st.session_state.user_id)
        report = build_report(math, japanese, st.session_state.user_id, days)
    except (sqlite3.Error, OSError, ValueError, KeyError, TypeError):
        st.error("共通レポートを読み込めませんでした。両教科の保存先と接続を確認してください。")
        if st.button("読み込みをやりなおす", key="cross_reload"):
            st.rerun()
        return
    start = report["start"]
    st.caption(f"対象期間：{start:%Y/%m/%d}〜{report['end']:%Y/%m/%d}（日本時間）" if start else
               f"対象期間：保存済みの全期間〜{report['end']:%Y/%m/%d}（日本時間）")
    total, active = st.columns(2)
    total.metric("両教科の回答数", f"{report['total']}問")
    active.metric("学習した日", f"{report['days']}日")
    if not report["total"]:
        st.info("この期間の学習履歴はまだありません。期間を変えるか、各教科を練習してください。")

    def rate(value):
        return f"{value:.0%}" if value is not None else "—"

    table = []
    for subject, title in (("math", "算数"), ("japanese", "国語")):
        data = report["subjects"][subject]
        table.append({"教科": title, "全回答数": data["total"], "学習日数": data["days"],
                      "初回回答数": data["initial"]["count"], "初回正答率": rate(data["initial"]["rate"]),
                      "初回ヒント使用率": rate(data["initial"]["hint_rate"]),
                      "初回自力正答率": rate(data["initial"]["unaided_rate"]),
                      "初回自力回答数": data["initial"]["unaided_count"],
                      "初回ヒントあり正答率": rate(data["initial"]["assisted_rate"]),
                      "初回ヒントあり回答数": data["initial"]["assisted_count"],
                      "初回ヒント記録不明": data["initial"]["hint_unknown_count"],
                      "初回の読み方確認": data["initial"]["reading_help_count"],
                      "読み方確認率": rate(data["initial"]["reading_help_rate"]),
                      "再練習回答数": data["retry"]["count"], "再練習正答率": rate(data["retry"]["rate"])})
    st.dataframe(table, hide_index=True, width="stretch")
    st.caption("算数の初回は通常練習、国語の初回は回答回数1（苦手練習を含む）です。復習は初回評価から除外します。"
               "教科ごとに問題・難易度が違うため、正答率は教科間の能力差を示しません。")
    with st.expander("保護者向け：復習の成果（初回評価とは別）"):
        review_table = []
        for subject, title in (("math", "算数"), ("japanese", "国語")):
            for key, label in (("review", "きょうの復習"), ("review_retry", "復習の再練習")):
                result = report["subjects"][subject][key]
                review_table.append({"教科": title, "練習": label, "回答数": result["count"],
                                     "正答率": rate(result["rate"]), "ヒント使用率": rate(result["hint_rate"])})
        st.dataframe(review_table, hide_index=True, width="stretch")
    st.write("**計算・3つの数・□の数・文章題・3つの数の文章題・国語読解を並べて見る**")
    st.dataframe([{"項目": g["label"], "初回評価数": g["count"], "正答率": rate(g["rate"]),
                   "ヒント使用率": rate(g["hint_rate"]),
                   "自力正答率": rate(g["unaided_rate"]), "自力回答数": g["unaided_count"],
                   "ヒントあり正答率": rate(g["assisted_rate"]), "ヒントあり回答数": g["assisted_count"],
                   "ヒント記録不明": g["hint_unknown_count"],
                   "図を使用した回答": g["visual_used_count"] if g["label"].startswith("算数") else None,
                   "次の練習の目安": g["status"]} for g in report["groups"]],
                 hide_index=True, width="stretch")
    st.caption("文章題の各段階は重複する回答です。未評価の項目は分母から除きます。"
               "国語読解は自力読みのみ。5問未満は判断保留、5問以上で80%未満なら練習を提案します。")
    st.caption("算数の図を見て答えた回答はヒントありに含めます。回答後に開いた図は使用数に含めません。旧履歴の図使用は記録なしです。")
    st.caption("ヒント使用率は使用の有無を記録できた回答のみで計算します。"
               "以前の履歴など、記録が不明な回答は自力にもヒントありにも含めません。"
               "自力正答率はヒントなしの回答、ヒントあり正答率はヒントを使った回答で計算します。"
               "ヒントを使うことも学習の一部です。国語の自力読み（音声なし）とヒントなしは別の条件です。")
    st.caption("言葉を押して読み方を確認した回数は、ヒント使用や計算の正誤と分けて記録します。"
               "ふりがなの表示は確認回数に含めません。以前の回答は読み方確認が未記録の場合があります。")
    st.info("文章題と国語読解の結果を並べて、練習内容を選ぶ参考にします。"
            "誤答の原因や教科間の因果関係を断定する分析ではありません。")
    st.write("**次に取り組むこと**")
    for suggestion in report["suggestions"]:
        st.write("・" + suggestion)
    from particles_ui import show_report
    show_report(report["particle_records"])
    math_button, japanese_button = st.columns(2)
    if math_button.button("算数の練習設定へ", key="cross_math", width="stretch"):
        st.session_state.screen = "settings"
        st.rerun()
    if japanese_button.button("国語の練習設定へ", key="cross_japanese", width="stretch"):
        st.session_state.screen = "jp_settings"
        st.rerun()
    if report["daily"]:
        st.write("**日ごとの学習量**")
        st.dataframe([{"日付（日本時間）": day.isoformat(), "算数の回答数": data["math"],
                       "国語の回答数": data["japanese"], "合計": sum(data.values())}
                      for day, data in sorted(report["daily"].items(), reverse=True)],
                     hide_index=True, width="stretch")
