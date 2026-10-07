-- 既存の学習履歴は変更しません。学年表示の設定だけを保存します。
begin;
create table if not exists public.learning_profiles (
    user_id text primary key check (user_id in ('user_001', 'user_002')),
    payload jsonb not null,
    constraint profile_user_matches check (payload->>'user_id' = user_id)
);
alter table public.learning_profiles enable row level security;
revoke all on public.learning_profiles from public, anon, authenticated;
revoke all on public.learning_profiles from service_role;
grant select, insert, update on public.learning_profiles to service_role;
alter table public.math_attempts add column if not exists reading_help_used boolean;
notify pgrst, 'reload schema';
commit;
