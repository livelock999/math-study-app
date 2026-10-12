"""家族専用リンクの認証。URLの鍵はサーバー設定と毎回照合する。"""

import hmac
import re
import base64
import hashlib

LINK_PARAMETER = "family"
_KEY = re.compile(r"[A-Za-z0-9_-]{43,128}\Z")


def family_link_key(setting):
    """専用鍵を優先。未設定なら既存サーバー鍵から用途を分けた鍵を導出。"""
    explicit = setting('MATH_FAMILY_LINK_KEY')
    if explicit:
        return explicit if isinstance(explicit, str) and _KEY.fullmatch(explicit) else ''
    server_key = setting('SUPABASE_SECRET_KEY')
    if not isinstance(server_key, str) or len(server_key) < 32:
        return ''
    digest = hmac.new(server_key.encode('utf-8'), b'math-study/family-entry/v1', hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode('ascii').rstrip('=')


def valid_family_link(values, configured_key):
    """未設定・不正値・複数指定は認証しない。鍵はtoken_urlsafe(32)等で生成する。"""
    if not isinstance(configured_key, str) or not _KEY.fullmatch(configured_key):
        return False
    if not isinstance(values, (list, tuple)) or len(values) != 1:
        return False
    candidate = values[0]
    if not isinstance(candidate, str) or not _KEY.fullmatch(candidate):
        return False
    return hmac.compare_digest(candidate, configured_key)
