-- 計算カードの追加項目。既存回答は書き換えず、過去の値はNULLのままです。
-- 公開更新前に実行し、その後 supabase_history_restore.sql を再実行します。
-- 既存のテーブル権限・RLSは変更しません。
begin;
alter table public.math_attempts add column if not exists learning_mode text;
alter table public.math_attempts add column if not exists answer_range_min integer;
alter table public.math_attempts add column if not exists answer_range_max integer;
alter table public.math_attempts add column if not exists input_method text;
alter table public.math_attempts add column if not exists recognized_text text;
alter table public.math_attempts add column if not exists parsed_answer integer;
alter table public.math_attempts add column if not exists recognition_success boolean;
alter table public.math_attempts add column if not exists recognition_retry_count integer;
alter table public.math_attempts add column if not exists first_attempt_correct boolean;
alter table public.math_attempts add column if not exists session_elapsed_sec double precision;
alter table public.math_attempts add column if not exists total_recognition_retry_count integer;
notify pgrst, 'reload schema';
commit;
