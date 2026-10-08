-- 算数の図の使用を記録する追加SQL。旧履歴はNULL（記録なし）のまま保持します。
-- アプリ更新・supabase_history_restore.sql更新より前にSQL Editorで実行します。
begin;
alter table public.math_attempts add column if not exists visual_help_used boolean;
notify pgrst, 'reload schema';
commit;
