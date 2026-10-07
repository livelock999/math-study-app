"""助詞MVP（は・を・に・で）の教材と、初回の役割・混同分析。"""

from collections import Counter
from statistics import mean
import random

PARTICLES = ("は", "を", "に", "で")
ROLES = {"topic": "話題（だれ・なにの話）", "object": "動作の対象（なにを）",
         "destination": "行き先（どこに行く）", "location_action": "動作する場所（どこで）",
         "location_existence": "いる場所", "time": "時間", "person": "相手",
         "companion": "いっしょにする人", "direction": "方向"}
LEVELS = {1: "レベル1：きほん", 2: "レベル2：に・で", 3: "レベル3：おなじ ばしょで くらべる"}


def confusion_pair(correct, selected):
    """正解と実際の誤答から作る。正解の場合は混同なし。将来の助詞にも対応。"""
    if correct == selected:
        return None
    for pair in ("に_で", "は_を", "は_が", "に_へ", "が_を", "は_に", "は_で", "を_に", "を_で"):
        if {correct, selected} == set(pair.split("_")):
            return pair
    return "_".join(sorted((correct, selected)))


def build_questions():
    result = []
    choice_order = random.Random(20261007)

    def add(level, sentence, particle, role, noun, verb, explanation, comparison=None):
        pair = "は_を" if particle in ("は", "を") else "に_で"
        choices = pair.split("_")
        choice_order.shuffle(choices)
        prompts = {"topic": "だれ・なにの はなしか わかるように、ことばを いれよう。",
                   "object": "「なにを」するか つたえる ぶんにしよう。",
                   "destination": "いく ばしょを つたえる ぶんにしよう。",
                   "location_action": "そこで することが わかる ぶんにしよう。"}
        result.append({"question_id": f"jp_particles_{len(result) + 1:03}", "category": "particles",
                       "question_type": "particle_choice", "problem_format": "choice", "level": level,
                       "sentence": sentence, "text": sentence, "question": prompts[role], "choices": choices,
                       "correct_answer": particle, "answer": choices.index(particle), "target_particle": particle,
                       "confusion_pair": pair, "semantic_role": role, "verb": verb, "noun": noun,
                       "comparison_id": comparison, "skill_tags": ["particle", "grammar"],
                       "question_word": "particle", "reasoning_level": 1 if level < 3 else 2,
                       "difficulty": level, "explanation": explanation,
                       "hint": {"topic": "だれ・なにの はなしか かんがえよう。",
                                "object": "することと、その あいてに なるものを みよう。",
                                "destination": "どこへ むかうのかな？",
                                "location_action": "どこで するのかな？"}[role],
                       "error_tags": {str(i): ["particle"] for i, p in enumerate(choices) if p != particle},
                       "version": 1})

    for noun, ending in [("わたし", "いちねんせいです"), ("ぼく", "ななさいです"),
                         ("きょう", "おやすみです"), ("これ", "わたしの かばんです"),
                         ("あした", "にちようびです"), ("この ほん", "おもしろいです")]:
        add(1, f"{noun}（　）{ending}。", "は", "topic", noun, "です",
            f"「{noun}は {ending}」。だれ・なにの はなしか つたえるときは「は」だよ。")
    for noun, verb in [("りんご", "たべます"), ("ほん", "よみます"), ("みず", "のみます"),
                       ("ボール", "なげます"), ("え", "かきます"), ("はな", "かざります")]:
        add(1, f"わたしは {noun}（　）{verb}。", "を", "object", noun, verb,
            f"「{noun}を {verb}」。なにを するか つたえるときは「を」だよ。")
    places = [("こうえん", "あそびます"), ("がっこう", "べんきょうします"),
              ("としょかん", "ほんを よみます"), ("おみせ", "かいものを します"),
              ("うみ", "およぎます"), ("いえ", "ごはんを たべます"),
              ("たいいくかん", "うんどうします"), ("にわ", "はなに みずを あげます")]
    for level, settings in [(2, places[:6]), (3, places)]:
        for place, action in settings:
            comparison = f"place_{place}"
            add(level, f"わたしは {place}（　）いきます。", "に", "destination", place, "いきます",
                f"「{place}に いきます」。いく ばしょには「に」を つかうよ。", comparison)
            add(level, f"わたしは {place}（　）{action}。", "で", "location_action", place, action,
                f"「{place}で {action}」。そこで することを つたえるときは「で」を つかうよ。", comparison)
    return result


QUESTIONS = build_questions()


def analyze(records):
    rows = [r for r in records if r.get("category") == "particles"]
    # 再送を除外し、初回回答だけから混同頻度・初回正答率を作ります。
    unique = {r["attempt_id"]: r for r in rows}
    rows = list(unique.values())
    initial = [r for r in rows if r["attempt_count"] == 1 and r["selection_type"] != "retry"]

    def group(field, labels):
        result = []
        for key, label in labels.items():
            items = [r for r in initial if r[field] == key]
            all_items = [r for r in rows if r[field] == key]
            result.append({"key": key, "label": label, "count": len(items),
                           "correct": sum(r["correct"] for r in items),
                           "rate": mean(r["correct"] for r in items) if items else None,
                           "total_count": len(all_items),
                           "total_rate": mean(r["correct"] for r in all_items) if all_items else None})
        return result

    errors = Counter(r["confusion_pair"] for r in initial if not r["correct"] and r.get("confusion_pair"))
    directions = Counter((r["target_particle"], r["selected_answer_text"]) for r in initial if not r["correct"])
    return {"count": len(initial), "total": len(rows), "rate": mean(r["correct"] for r in initial) if initial else None,
            "particles": group("target_particle", {p: p for p in PARTICLES}),
            "roles": group("semantic_role", ROLES), "levels": group("level", LEVELS),
            "confusions": dict(errors), "directions": [{"correct": a, "selected": b, "count": n}
                                                         for (a, b), n in directions.most_common()],
            "priority_pairs": [pair for pair, count in errors.most_common() if count >= 2]}


def recommended(records, count=5, level=None):
    """混同→助詞→意味役割→最近の誤答→未出題。比較する2問は隣に出します。"""
    report = analyze(records)
    initial = [r for r in records if r.get("category") == "particles" and r["attempt_count"] == 1]
    seen = {r["question_id"] for r in initial}
    latest = {}
    for row in sorted((r for r in records if r.get("category") == "particles"),
                      key=lambda r: (r["datetime"], r["attempt_id"]), reverse=True):
        latest.setdefault(row["question_id"], row)
    wrong = [r["question_id"] for r in latest.values() if not r["correct"]]
    particle_rates = {g["key"]: g["rate"] for g in report["particles"] if g["count"] >= 3 and g["rate"] < .8}
    role_rates = {g["key"]: g["rate"] for g in report["roles"] if g["count"] >= 3 and g["rate"] < .8}
    pool = [q for q in QUESTIONS if level is None or q["level"] == level]
    random.shuffle(pool)

    def rank(q):
        pair = q["confusion_pair"]
        if pair in report["priority_pairs"]:
            return (0, -report["confusions"][pair], 0 if q["level"] == 3 else 1)
        if q["target_particle"] in particle_rates:
            return (1, particle_rates[q["target_particle"]], 0)
        if q["semantic_role"] in role_rates:
            return (2, role_rates[q["semantic_role"]], 0)
        if q["question_id"] in wrong:
            return (3, wrong.index(q["question_id"]), 0)
        return (4 if q["question_id"] not in seen else 5, 0, 0)

    pool.sort(key=rank)
    chosen = []
    for q in pool:
        if q in chosen:
            continue
        chosen.append(q)
        # レベル3で同じ名詞の「行き先」「動作場所」を続けて比較します。
        if q["level"] == 3 and len(chosen) < count:
            mate = next((p for p in pool if p["level"] == 3 and p["comparison_id"] == q["comparison_id"]
                         and p["semantic_role"] != q["semantic_role"] and p not in chosen
                         and (rank(p)[0] < 5 or rank(q)[0] == 5)), None)
            if mate:
                chosen.append(mate)
        if len(chosen) >= count:
            break
    return chosen
