"""ヒントの記録がある回答だけで、支援の利用と正答率を集計します。"""


def summarize_hints(records, correct_field="is_correct"):
    records = list(records)
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
    reading = [row["reading_help_used"] for row in records if type(row.get("reading_help_used")) in (bool, int)
               and row["reading_help_used"] in (0, 1)]
    result.update(reading_known_count=len(reading), reading_unknown_count=len(records) - len(reading),
                  reading_help_count=sum(bool(v) for v in reading),
                  reading_help_rate=sum(bool(v) for v in reading) / len(reading) if reading else None)
    for name, rows in (("unaided", unaided), ("assisted", assisted)):
        correct = sum(bool(row[correct_field]) for row in rows)
        result.update({f"{name}_count": len(rows), f"{name}_correct": correct,
                       f"{name}_rate": correct / len(rows) if rows else None})
    return result
