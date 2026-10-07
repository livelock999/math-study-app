"""助詞の分析を国語・共通レポートで共有します。"""

import streamlit as st
from particles import analyze, ROLES


def show_report(records, practice=True):
    report = analyze(records)
    st.write("**てにをは：助詞と意味の使い分け**")
    if not report["total"]:
        st.caption("てにをはの記録はまだありません。国語の「てにをは」から始められます。")
        return
    st.caption("初回正答率と全回答の正答率を分けます。混同回数は初回のみで、再回答や同じ回答の再送は加えません。")
    for title, field in [("助詞別", "particles"), ("意味役割別", "roles"), ("レベル別", "levels")]:
        st.write(f"**{title}**")
        st.dataframe([{"分類": g["label"], "初回回答数": g["count"],
                       "初回正答率": f"{g['rate']:.0%}" if g["rate"] is not None else "—",
                       "全回答数": g["total_count"],
                       "全回答正答率": f"{g['total_rate']:.0%}" if g["total_rate"] is not None else "—",
                       "練習の目安": "判断保留（3問未満）" if g["count"] < 3 else
                                      "重点練習" if g["rate"] < .8 else "練習を継続"}
                      for g in report[field] if field != "roles" or g["count"] or g["key"] in
                      ("topic", "object", "destination", "location_action")],
                     hide_index=True, use_container_width=True)
    pairs = report["confusions"]
    st.write(f"初回の混同：に ↔ で {pairs.get('に_で', 0)}回 ／ は ↔ を {pairs.get('は_を', 0)}回")
    if report["directions"]:
        st.dataframe([{"正しい助詞": g["correct"], "選んだ助詞": g["selected"], "初回の誤答数": g["count"]}
                      for g in report["directions"]], hide_index=True, use_container_width=True)
    stable = [g["key"] for g in report["particles"] if g["count"] >= 5 and g["rate"] >= .9]
    if stable:
        st.success("「" + "」「".join(stable) + "」は初回の正答が安定しています。")
    if "に_で" in report["priority_pairs"]:
        st.info("「に」と「で」の使い分けで誤答が繰り返されています。"
                "「こうえんに いく」と「こうえんで あそぶ」のように、行き先と動作する場所を比べて練習しましょう。")
    elif "は_を" in report["priority_pairs"]:
        st.info("「は」と「を」の使い分けを比べて、だれ・なにの話か、なにをするかを練習しましょう。")
    if practice:
        if st.button("てにをはの にがてを れんしゅう", key="particle_report_practice", type="primary"):
            from japanese_ui import start
            from particles import recommended
            start(recommended(records, 5), "weak_area")
