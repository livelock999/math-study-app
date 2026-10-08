-- 既存プロジェクトの追加更新。既存の回答・学年設定は削除・変更しません。
-- Supabase SQL Editorでこのファイル全体を実行してから、アプリを更新します。
begin;
alter table public.math_attempts add column if not exists hint_level smallint
    check (hint_level between 0 and 3);
-- 以前の回答はNULLのまま。ヒントなしや「わからない」なしとは推定しません。
alter table public.math_attempts add column if not exists dont_know_used boolean;

create table if not exists public.family_learning_settings (
    user_id text primary key check (user_id in ('user_001', 'user_002')),
    weekly_days smallint not null check (weekly_days between 1 and 7),
    daily_questions smallint not null check (daily_questions between 1 and 20),
    updated_at timestamptz not null
);
create table if not exists public.problem_feedback (
    feedback_id text primary key,
    user_id text not null check (user_id in ('user_001', 'user_002')),
    subject text not null check (subject in ('math', 'japanese')),
    problem_id text not null check (length(problem_id) between 1 and 256),
    reason text not null check (reason in ('difficult', 'reading', 'answer')),
    datetime timestamptz not null
);
create index if not exists feedback_user_date on public.problem_feedback(user_id, datetime);
alter table public.family_learning_settings enable row level security;
alter table public.problem_feedback enable row level security;
revoke all on public.family_learning_settings, public.problem_feedback from public, anon, authenticated;
revoke all on public.family_learning_settings, public.problem_feedback from service_role;
grant select, insert, update on public.family_learning_settings to service_role;
grant select, insert on public.problem_feedback to service_role;
notify pgrst, 'reload schema';
commit;
