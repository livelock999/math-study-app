"""履歴だけのバックアップ・復元。通常の学習者設定は変更しません。"""
from hashlib import sha256
import sqlite3

import streamlit as st

import history_backup as backup_store
from learning import USERS
from practice_mode import is_test_mode


def render_backup(user_id, math_records, japanese_records, now):
    with st.expander("学習記録のバックアップ・復元（保護者向け）"):
        st.caption("選択中のお子さまの算数・国語の回答履歴をJSONで保存します。"
                   "通常練習・復習・ヒントの記録を含みます。設定と保護者テストの回答は含みません。"
                   "このファイルは個人の学習記録なので、ご家庭で保管してください。")
        try:
            data = backup_store.export_backup(user_id, math_records, japanese_records, now=now)
        except (ValueError, TypeError, KeyError):
            st.error("履歴の形式を確認できないため、バックアップを作成できませんでした。")
            return
        st.download_button("両教科のバックアップを保存（JSON）", data=data,
                           file_name=f"learning-backup-{user_id}-{now:%Y%m%d}.json",
                           mime="application/json", on_click="ignore",
                           key="history_backup_download", use_container_width=True)
        st.write("**保存した履歴を戻す**")
        st.caption(f"{USERS[user_id]}のバックアップだけを復元できます。CSVは復元用ではありません。"
                   "保存済みの同じ記録は追加せず、違う内容で同じ回答IDがある場合は復元を止めます。"
                   "既存の履歴は削除・上書きしません。復習予定・分析・スタンプは復元した履歴から再計算されます。")
        test_mode = is_test_mode(st.session_state)
        if test_mode:
            st.info("保護者テスト中は内容の確認だけです。復元の書き込みや通常の復習予定の更新はしません。")
        uploaded = st.file_uploader("復元するJSONバックアップ", type=["json"],
                                    help="10MB・算数と国語を合わせて20000件までのJSONバックアップに対応します。",
                                    key=f"history_backup_upload_{user_id}_{test_mode}")
        if uploaded is None:
            return
        # ファイルを変更した後に、以前の確認チェックを引き継がない。
        raw = uploaded.getvalue()
        digest = sha256(raw).hexdigest()
        result_key = f"history_backup_result_{user_id}_{test_mode}_{digest}"
        try:
            document = backup_store.parse_backup(raw, user_id)
            counts = backup_store.preview_backup(document, math_records, japanese_records)
        except (ValueError, TypeError, KeyError) as error:
            st.error(str(error))
            return
        st.write(f"復元先：{USERS[user_id]}／算数 {counts['math_added']}件・国語 {counts['japanese_added']}件を追加")
        st.caption(f"保存済みで追加しない記録：算数 {counts['math_existing']}件・国語 {counts['japanese_existing']}件")
        if result_key in st.session_state:
            st.success(st.session_state[result_key])
        checked = st.checkbox("復元先と追加する件数を確認しました", key=f"history_backup_confirm_{user_id}_{test_mode}_{digest}")
        label = "保存せずに復元を確認" if test_mode else "確認した履歴を復元する"
        if st.button(label, disabled=not checked, key="history_backup_restore", use_container_width=True):
            try:
                saved = backup_store.restore_backup(document, test_mode=test_mode)
            except (sqlite3.Error, OSError, ValueError, TypeError, KeyError) as error:
                if isinstance(error, ValueError):
                    st.error(str(error))
                else:
                    st.error("復元を完了できませんでした。同じファイルで再試行できます。"
                             "クラウド利用時は接続と supabase_history_restore.sql の適用を確認してください。"
                             "保存済みの回答IDは再試行で重複しません。")
                return
            if test_mode:
                message = "バックアップの内容を確認しました。履歴と設定は保存していません。"
            else:
                message = f"復元しました：算数 {saved['math_added']}件・国語 {saved['japanese_added']}件を追加しました。"
            st.session_state[result_key] = message
            st.rerun()
