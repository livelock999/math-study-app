"""原文・採点値に触れず、確認済みの教材を表示するときだけ変換します。"""

import sqlite3
import streamlit as st
from canonical_text import TERMS, canonical_fields, protected_fields
from furigana import READINGS
from grade_kanji import grade_for
from learning_profiles import default_profile, load_profile, effective_grade

CONTROL_TEXTS = {
    "もどる": "戻る", "つぎへ ↵": "次へ ↵", "学習履歴": "学習履歴",
    "こたえる ↵": "答える ↵", "けっかを みる ↵": "結果を 見る ↵",
    "ヒントを みる": "ヒントを 見る", "しきを なおす": "式を 直す",
    "かんがえかた": "考え方", "この しきで こたえる ↵": "この 式で 答える ↵",
    "この じゅんばんで こたえる ↵": "この 順番で 答える ↵",
    "1こ もどす": "1こ 戻す", "ならべなおす": "並べ直す",
    "れんしゅう スタート": "練習 スタート", "こくご スタート": "国語 スタート",
    "学習レポート": "学習レポート", "学習カレンダー・ごほうび": "学習カレンダー・ごほうび",
    "国語の学習履歴": "国語の学習履歴",
}
READINGS_FOR_DISPLAY = {**READINGS, **TERMS, "答える": "こたえる", "結果": "けっか",
                        "直す": "なおす", "考え方": "かんがえかた", "並べ直す": "ならべなおす",
                        "戻す": "もどす", "内容一致": "ないよういっち"}


def session_profile(user_id):
    profiles = st.session_state.setdefault("display_profiles", {})
    if user_id not in profiles:
        try:
            profiles[user_id] = load_profile(user_id)
            st.session_state.pop(f"display_error_{user_id}", None)
        except (OSError, ValueError, sqlite3.Error):
            profiles[user_id] = default_profile(user_id)
            st.session_state[f"display_error_{user_id}"] = True
    return profiles[user_id]


def parts_for(text, profile, now=None):
    grade = effective_grade(profile, now)
    terms = sorted(READINGS_FOR_DISPLAY, key=len, reverse=True)
    parts, position = [], 0
    while position < len(text):
        word = next((word for word in terms if text.startswith(word, position)), None)
        if word is None:
            if parts and not parts[-1]["reading"] and not parts[-1]["help_reading"]:
                parts[-1]["text"] += text[position]
            else:
                parts.append({"text": text[position], "reading": "", "help_reading": ""})
            position += 1
            continue
        reading = READINGS_FOR_DISPLAY[word]
        kanji = [char for char in word if '\u3400' <= char <= '\u9fff']
        allowed = all(grade_for(c) is not None and grade_for(c) <= grade and c not in profile["unlearned"] for c in kanji)
        surface = word if allowed else reading
        ruby = reading if allowed and kanji and (profile["furigana_mode"] == "all" or
                          (profile["furigana_mode"] == "current" and any(grade_for(c) == grade for c in kanji))) else ""
        help_reading = reading if allowed and kanji and not ruby and profile["reading_tap"] else ""
        parts.append({"text": surface, "reading": ruby, "help_reading": help_reading})
        position += len(word)
    return parts


def plain_label(text, user_id):
    return "".join(p["text"] for p in parts_for(CONTROL_TEXTS.get(text, text), session_profile(user_id)))


def component_display(subject, item, user_id):
    profile = session_profile(user_id)
    fields = canonical_fields(subject, item)
    protected = protected_fields(subject, item)
    if subject == "math":
        from words import guidance
        values = {"question": [item["question_text"]], "hint_text": [guidance(item)],
                  "explanation_text": [guidance(item, reveal=True)]}
    else:
        values = {name: [item[name]] for name in ("text", "question", "hint", "explanation")}
        values["choices"] = item["choices"]
        values["selected"] = list(item["choices"]) + list(fields.get("selected", {}))
        values["correct_answer"] = list(values["selected"])
    result = {}
    for name, originals in values.items():
        result[name] = ({} if name in protected or name not in fields else
                        {original: {"parts": parts_for(fields[name].get(original, original), profile)}
                         for original in originals})
    return {"display_words": {original: {"parts": parts_for(canonical, profile)}
                              for original, canonical in CONTROL_TEXTS.items()}, "display_fields": result}
