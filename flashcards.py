"""計算カードの問題、厳密な音声数値の読み取り、速度集計。"""

from collections import defaultdict
from datetime import datetime, timezone, timedelta
from statistics import mean, median
import random
import re
import unicodedata

from learning import make_problem


def card_pool(operation, answer_min, answer_max):
    """1年生の加法・20までの減法から、指定した答えのカードを作ります。"""
    lefts = range(1, 10) if operation == "addition" else range(1, 21)
    pool = [make_problem(operation, 20, left, right)
            for left in lefts for right in range(1, 10)
            if answer_min <= (left + right if operation == "addition" else left - right) <= answer_max]
    return sorted(pool, key=lambda problem: (problem["correct_answer"], problem["left_operand"], problem["right_operand"]))


def selection_error(answer_min=11, answer_max=18, count=20, order="shuffle", mode="addition"):
    if mode not in ("addition", "subtraction", "mixed"):
        return "カードの種類が不正です。"
    minimum, maximum = (2, 18) if mode == "addition" else (0, 19)
    if (any(type(value) is not int for value in (answer_min, answer_max, count))
            or not minimum <= answer_min <= answer_max <= maximum or not 1 <= count <= 100
            or order not in ("ordered", "shuffle")):
        return "カードの答え範囲・問題数・順番が不正です。"
    operations = ("addition", "subtraction") if mode == "mixed" else (mode,)
    if mode == "mixed" and count < 2:
        return "ミックスでは、たし算とひき算を出すため2問以上にしてください。"
    for operation in operations:
        if not card_pool(operation, answer_min, answer_max):
            name = "たし算" if operation == "addition" else "ひき算"
            return f"この答え範囲では{name}のカードがありません。両方を含める範囲にしてください。"
    return None


def _draw_cards(pool, count, shuffle):
    """デッキを使い切るまで重複させず、不足したら繰り返します。"""
    cards = []
    while len(cards) < count:
        deck = list(pool)
        if shuffle:
            random.shuffle(deck)
        if len(deck) > 1 and cards and deck[0]["problem_id"] == cards[-1]["problem_id"]:
            deck[0], deck[1] = deck[1], deck[0]
        cards.extend(dict(problem) for problem in deck[:count - len(cards)])
    return cards


def generate_cards(answer_min=11, answer_max=18, count=20, order="shuffle", mode="addition"):
    error = selection_error(answer_min, answer_max, count, order, mode)
    if error:
        raise ValueError(error)
    if mode != "mixed":
        return _draw_cards(card_pool(mode, answer_min, answer_max), count, order == "shuffle")
    # 奇数の1問は毎回ランダムに配分。ミックスは順番指定でもシャッフルします。
    extra_addition = random.choice((0, 1)) if count % 2 else 0
    addition_count = count // 2 + extra_addition
    cards = (_draw_cards(card_pool("addition", answer_min, answer_max), addition_count, True)
             + _draw_cards(card_pool("subtraction", answer_min, answer_max), count - addition_count, True))
    random.shuffle(cards)
    # 直後連続がある場合だけ並べ直します。残りが多いカードを先に使い、
    # 同数なら上のシャッフル順を採用すると、最後に同一カードが余りません。
    if any(left["problem_id"] == right["problem_id"] for left, right in zip(cards, cards[1:])):
        buckets = defaultdict(list)
        for card in cards:
            buckets[card["problem_id"]].append(card)
        arranged = []
        while buckets:
            previous = arranged[-1]["problem_id"] if arranged else None
            candidates = [key for key in buckets if key != previous] or list(buckets)
            key = max(candidates, key=lambda item: len(buckets[item]))
            arranged.append(buckets[key].pop())
            if not buckets[key]:
                del buckets[key]
        return arranged
    return cards


def parse_spoken_number(text):
    """一つの0〜99だけを認識。曖昧な文から数字を拾って採点しません。"""
    if not isinstance(text, str) or len(text) > 100:
        return None
    text = unicodedata.normalize("NFKC", text).strip().rstrip("。.!！?？").strip()
    text = re.sub(r"^(?:こたえは|答えは|こたえ|答え)", "", text).strip()
    text = re.sub(r"(?:です|だよ|こ)$", "", text).strip()
    if re.fullmatch(r"[0-9]{1,2}", text):
        return int(text)
    # カタカナ音声結果も、ひらがなと同じ小さな表で扱います。
    text = "".join(chr(ord(char) - 96) if "ァ" <= char <= "ヶ" else char for char in text)
    units = {"ぜろ": 0, "れい": 0, "零": 0, "〇": 0, "いち": 1, "一": 1,
             "に": 2, "二": 2, "さん": 3, "三": 3, "よん": 4, "し": 4, "四": 4,
             "ご": 5, "五": 5, "ろく": 6, "六": 6, "なな": 7, "しち": 7, "七": 7,
             "はち": 8, "八": 8, "きゅう": 9, "く": 9, "九": 9}
    if text in units:
        return units[text]
    for ten in ("じゅう", "十"):
        if text.count(ten) == 1:
            before, after = text.split(ten)
            tens = 1 if before == "" else units.get(before)
            ones = 0 if after == "" else units.get(after)
            if tens is not None and 1 <= tens <= 9 and ones is not None:
                return tens * 10 + ones
    return None


def summarize(records):
    times = [row["response_time_sec"] for row in records]
    correct = sum(bool(row["is_correct"]) for row in records)
    first = [row for row in records if row.get("attempt_count") == 1 and row.get("selection_type") == "normal"]
    return {"count": len(records), "correct": correct, "rate": correct / len(records) if records else None,
            "first_count": len(first), "first_rate": sum(bool(row["is_correct"]) for row in first) / len(first) if first else None,
            "average_seconds": mean(times) if times else None, "median_seconds": median(times) if times else None,
            "fastest_seconds": min(times) if times else None, "slowest_seconds": max(times) if times else None,
            "mistakes": [row for row in records if not row["is_correct"]]}


def report_tables(records):
    groups = {name: defaultdict(list) for name in ("problems", "structures", "days", "inputs", "ranges", "operations")}
    for record in records:
        groups["problems"][record["question_text"]].append(record)
        addition = record["operation"] == "addition"
        operation_name = "たし算" if addition else "ひき算"
        attribute_name = "繰り上がり" if addition else "繰り下がり"
        attribute = record["carry"] if addition else record["borrowing"]
        groups["operations"][operation_name].append(record)
        structure = (f"{operation_name}／{record['number_range']}まで／{attribute_name}{'あり' if attribute else 'なし'}／"
                     f"10またぎ{'あり' if record['crosses_10'] else 'なし'}")
        if addition:
            structure += f"／同じ数{'あり' if record['doubles'] else 'なし'}"
        groups["structures"][structure].append(record)
        groups["inputs"][{"voice": "声", "keyboard": "数字キー", "keypad": "画面テンキー"}.get(record.get("input_method"), "記録なし")].append(record)
        groups["ranges"][f"答え{record.get('answer_range_min', '—')}〜{record.get('answer_range_max', '—')}"].append(record)
        day = datetime.fromisoformat(record["datetime"]).astimezone(timezone(timedelta(hours=9))).strftime("%Y/%m/%d")
        groups["days"][day].append(record)
    return {name: [{"分類": label, "回答数": len(rows), "正答率": f"{summarize(rows)['rate']:.0%}",
                    "平均（秒）": round(summarize(rows)["average_seconds"], 2),
                    "最速（秒）": round(summarize(rows)["fastest_seconds"], 2),
                    "最長（秒）": round(summarize(rows)["slowest_seconds"], 2),
                    "直近（秒）": round(max(rows, key=lambda row: datetime.fromisoformat(row["datetime"]))["response_time_sec"], 2)}
                   for label, rows in sorted(buckets.items())] for name, buckets in groups.items()}


def session_table(records):
    """保存済み回答からセットを集計し、途中・表示範囲の不足も示します。"""
    sessions = defaultdict(list)
    for row in records:
        sessions[row["session_id"]].append(row)
    table = []
    for rows in sessions.values():
        latest = max(rows, key=lambda row: (datetime.fromisoformat(row["datetime"]), row["question_order"]))
        summary = summarize(rows)
        longest = max(rows, key=lambda row: row["response_time_sec"])
        completed = any(row.get("round_completed") for row in rows)
        status = "完了" if completed else "途中"
        if completed and len(rows) < (latest.get("round_size") or len(rows)):
            status = "完了（集計範囲は一部）"
        table.append({
            "日時（日本時間）": datetime.fromisoformat(latest["datetime"]).astimezone(timezone(timedelta(hours=9))).strftime("%Y/%m/%d %H:%M"),
            "セッション": latest["session_id"], "状態": status,
            "練習": "再練習" if latest["selection_type"] == "retry" else "通常カード",
            "保存済み問題数": len(rows), "設定問題数": latest.get("round_size"),
            "正答数": summary["correct"], "正答率": f"{summary['rate']:.0%}",
            "同カード初回正答率": f"{summary['first_rate']:.0%}" if summary["first_rate"] is not None else "—",
            "平均（秒）": round(summary["average_seconds"], 2), "最速（秒）": round(summary["fastest_seconds"], 2),
            "最長の問題": longest["question_text"], "最長（秒）": longest["response_time_sec"],
            "認識やりなおし（累積）": latest.get("total_recognition_retry_count"),
            "最終回答まで（秒）": latest.get("session_elapsed_sec"),
        })
    return sorted(table, key=lambda row: (row["日時（日本時間）"], row["セッション"]), reverse=True)
