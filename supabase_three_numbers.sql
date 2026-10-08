-- 3つの数の算数を記録する追加SQL。既存履歴は更新・削除せず、
-- third_operand / second_operation はNULL（従来の2つの数）のままです。
-- アプリ公開更新・supabase_history_restore.sql再実行の前にSQL Editorで実行します。
begin;
alter table public.math_attempts add column if not exists third_operand integer;
alter table public.math_attempts add column if not exists second_operation text;
notify pgrst, 'reload schema';
commit;
