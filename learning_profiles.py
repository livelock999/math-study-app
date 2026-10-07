"""教科共通の表示設定。学習履歴と別に、子どもごとに保存します。"""

from contextlib import closing
from datetime import datetime
from pathlib import Path
from urllib.request import Request
from urllib.parse import urlencode
from urllib.error import HTTPError, URLError
import json
import sqlite3

import learning
from activity import JST

DB_PATH = Path(__file__).parent / "data" / "profiles.sqlite3"
MODES = {"all": "全部につける", "current": "今年習う漢字だけ", "none": "なし"}


def school_year(now=None):
    now = now or datetime.now(JST)
    if isinstance(now, datetime) and now.tzinfo is not None:
        now = now.astimezone(JST)
    return now.year - (now.month < 4)


def default_profile(user_id, now=None):
    return validate_profile({"user_id": user_id, "grade": 1, "base_school_year": school_year(now),
                             "auto_advance": False, "furigana_mode": "all", "unlearned": [], "reading_tap": True})


def validate_profile(profile):
    if (not isinstance(profile, dict) or not isinstance(profile.get("user_id"), str)
            or profile["user_id"] not in learning.USERS):
        raise ValueError("学習者が不正です。")
    if (type(profile.get("grade")) is not int or not 1 <= profile["grade"] <= 6
            or type(profile.get("base_school_year")) is not int or not 2000 <= profile["base_school_year"] <= 9999
            or type(profile.get("auto_advance")) is not bool or type(profile.get("reading_tap")) is not bool
            or not isinstance(profile.get("furigana_mode"), str) or profile["furigana_mode"] not in MODES):
        raise ValueError("表示設定が不正です。")
    chars = profile.get("unlearned")
    if (not isinstance(chars, list) or len(chars) > 128
            or any(not isinstance(c, str) or len(c) != 1 or not '\u3400' <= c <= '\u9fff' for c in chars)):
        raise ValueError("まだ習っていない漢字を128字以内で指定してください。")
    return {k: (sorted(set(chars)) if k == "unlearned" else profile[k])
            for k in ("user_id", "grade", "base_school_year", "auto_advance", "furigana_mode", "unlearned", "reading_tap")}


def effective_grade(profile, now=None):
    profile = validate_profile(profile)
    elapsed = max(0, school_year(now) - profile["base_school_year"]) if profile["auto_advance"] else 0
    return min(6, profile["grade"] + elapsed)


def load_profile(user_id, path=None, now=None):
    default = default_profile(user_id, now)
    config = learning.get_supabase_config() if path is None else None
    if config:
        url, key = config
        query = urlencode({"user_id": f"eq.{user_id}", "select": "user_id,payload", "limit": 1})
        request = Request(f"{url}/rest/v1/learning_profiles?{query}", headers={"apikey": key, "Accept": "application/json"})
        try:
            with learning.supabase_urlopen(request, timeout=15) as response:
                if not 200 <= response.status < 300:
                    raise ValueError()
                rows = json.loads(response.read().decode("utf-8"))
            if not isinstance(rows, list) or len(rows) > 1:
                raise ValueError()
            if not rows:
                return default
            if rows[0].get("user_id") != user_id or rows[0].get("payload", {}).get("user_id") != user_id:
                raise ValueError()
            return validate_profile(rows[0]["payload"])
        except (HTTPError, URLError, OSError, ValueError, TypeError, AttributeError, KeyError):
            raise OSError("表示設定を読み込めませんでした。保護者設定から再試行してください。") from None
    path = Path(path or DB_PATH)
    if not path.exists():
        return default
    with closing(sqlite3.connect(path)) as connection:
        row = connection.execute("SELECT payload FROM profiles WHERE user_id = ?", (user_id,)).fetchone()
    if not row:
        return default
    profile = validate_profile(json.loads(row[0]))
    if profile["user_id"] != user_id:
        raise ValueError("表示設定の学習者が一致しません。")
    return profile


def save_profile(profile, path=None):
    profile = validate_profile(profile)
    payload = json.dumps(profile, ensure_ascii=False, allow_nan=False)
    config = learning.get_supabase_config() if path is None else None
    if config:
        url, key = config
        request = Request(f"{url}/rest/v1/learning_profiles?on_conflict=user_id",
                          data=json.dumps({"user_id": profile["user_id"], "payload": profile},
                                          ensure_ascii=False, allow_nan=False).encode("utf-8"),
                          headers={"apikey": key, "Content-Type": "application/json",
                                   "Prefer": "resolution=merge-duplicates,return=minimal"}, method="POST")
        try:
            with learning.supabase_urlopen(request, timeout=15) as response:
                if not 200 <= response.status < 300:
                    raise OSError()
        except (HTTPError, URLError, OSError, ValueError, TypeError, AttributeError):
            raise OSError("表示設定を保存できませんでした。接続と保存先設定を確認してください。") from None
        return
    path = Path(path or DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("CREATE TABLE IF NOT EXISTS profiles (user_id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
        connection.execute("INSERT INTO profiles VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET payload=excluded.payload",
                           (profile["user_id"], payload))
