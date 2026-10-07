-- 国語用。既存の算数・他アプリのテーブルとは独立しています。
create table if not exists public.japanese_attempts (
    attempt_id text primary key,
    user_id text not null,
    session_id text not null,
    datetime timestamptz not null,
    payload jsonb not null
);
create index if not exists japanese_attempts_user_date on public.japanese_attempts(user_id, datetime);
alter table public.japanese_attempts enable row level security;
revoke all on table public.japanese_attempts from public, anon, authenticated;
revoke all on table public.japanese_attempts from service_role;
grant insert, select on table public.japanese_attempts to service_role;
notify pgrst, 'reload schema';
