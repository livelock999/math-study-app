-- Supabase SQL Editor で実行します。算数app専用のテーブルです。
create table if not exists public.math_attempts (
    attempt_id text primary key,
    user_id text not null,
    session_id text not null,
    datetime timestamptz not null,
    problem_id text not null,
    question_order integer not null,
    selection_type text not null,
    problem_format text not null,
    operation text not null,
    number_range integer not null,
    left_operand integer not null,
    right_operand integer not null,
    carry boolean,
    borrowing boolean,
    crosses_10 boolean,
    zero_included boolean,
    doubles boolean,
    blank_position text,
    story_type text,
    unknown_type text,
    operation_selection_correct boolean,
    equation_correct boolean,
    calculation_correct boolean,
    question_text text not null,
    correct_answer integer not null,
    user_answer integer,
    is_correct boolean not null,
    response_time_sec double precision not null,
    attempt_count integer not null,
    hint_used boolean,
    dont_know_used boolean,
    retry_flag boolean,
    answer_is_10 boolean,
    operand_contains_10 boolean,
    near_10 boolean,
    commutative_pair text,
    round_size integer,
    round_completed boolean,
    user_equation text,
    reading_help_used boolean,
    hint_level smallint check (hint_level between 0 and 3)
);

-- 既存テーブルの更新。以前の行はNULLのままです。
alter table public.math_attempts add column if not exists round_size integer;
alter table public.math_attempts add column if not exists round_completed boolean;
alter table public.math_attempts add column if not exists user_equation text;
alter table public.math_attempts add column if not exists reading_help_used boolean;
alter table public.math_attempts add column if not exists hint_level smallint check (hint_level between 0 and 3);
alter table public.math_attempts add column if not exists dont_know_used boolean;

create index if not exists math_attempts_user_sessions
    on public.math_attempts (user_id, session_id);

alter table public.math_attempts enable row level security;
-- 公開鍵とユーザー認証ではアクセス不可。秘密キーはStreamlitサーバーだけに置きます。
revoke all on table public.math_attempts from public, anon, authenticated;
-- secret key は service_role として動作し、RLS を迂回して保存します。
revoke all on table public.math_attempts from service_role;
grant insert, select on table public.math_attempts to service_role;

notify pgrst, 'reload schema';
