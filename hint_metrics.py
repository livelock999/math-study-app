"""ヒントの記録がある回答だけで、支援の利用と正答率を集計します。"""


def summarize_hints(records, correct_field="is_correct"):
    assisted, unaided, unknown = [], [], 0
    for row in records:
        value = row.get("hint_used")
        if type(value) not in (bool, int) or value not in (0, 1):
            unknown += 1
        else:
            (assisted if value else unaided).append(row)
    known = len(assisted) + len(unaided)
    result = {"hint_known_count": known, "hint_unknown_count": unknown,
              "hint_count": len(assisted), "hint_rate": len(assisted) / known if known else None}
    for name, rows in (("unaided", unaided), ("assisted", assisted)):
        correct = sum(bool(row[correct_field]) for row in rows)
        result.update({f"{name}_count": len(rows), f"{name}_correct": correct,
                       f"{name}_rate": correct / len(rows) if rows else None})
    return result
