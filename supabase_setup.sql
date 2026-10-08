-- 新規Supabaseプロジェクト用。学習アプリの3つの保存先をまとめて作成します。
begin;

create table if not exists public.math_attempts (
    attempt_id text primary key,
    user_id text not null, session_id text not null,
    datetime timestamptz not null, problem_id text not null,
    question_order integer not null, selection_type text not null,
    problem_format text not null, operation text not null,
    number_range integer not null, left_operand integer not null,
    right_operand integer not null, third_operand integer, second_operation text,
    carry boolean, borrowing boolean, crosses_10 boolean,
    zero_included boolean, doubles boolean,
    blank_position text, story_type text, unknown_type text,
    operation_selection_correct boolean, equation_correct boolean,
    calculation_correct boolean, question_text text not null,
    correct_answer integer not null, user_answer integer,
    is_correct boolean not null, response_time_sec double precision not null,
    attempt_count integer not null,
    hint_used boolean, dont_know_used boolean, retry_flag boolean,
    answer_is_10 boolean, operand_contains_10 boolean, near_10 boolean,
    commutative_pair text, round_size integer, round_completed boolean,
    user_equation text, reading_help_used boolean, visual_help_used boolean,
    hint_level smallint check (hint_level between 0 and 3)
);
alter table public.math_attempts add column if not exists round_size integer;
alter table public.math_attempts add column if not exists round_completed boolean;
alter table public.math_attempts add column if not exists user_equation text;
alter table public.math_attempts add column if not exists reading_help_used boolean;
alter table public.math_attempts add column if not exists visual_help_used boolean;
alter table public.math_attempts add column if not exists third_operand integer;
alter table public.math_attempts add column if not exists second_operation text;
alter table public.math_attempts add column if not exists hint_level smallint check (hint_level between 0 and 3);
alter table public.math_attempts add column if not exists dont_know_used boolean;
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
create index if not exists math_attempts_user_sessions
    on public.math_attempts (user_id, session_id);

create table if not exists public.japanese_attempts (
    attempt_id text primary key,
    user_id text not null, session_id text not null,
    datetime timestamptz not null, payload jsonb not null
);
create index if not exists japanese_attempts_user_date
    on public.japanese_attempts (user_id, datetime);

create table if not exists public.learning_profiles (
    user_id text primary key check (user_id in ('user_001', 'user_002')),
    payload jsonb not null,
    constraint profile_user_matches check (payload->>'user_id' = user_id)
);

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

alter table public.math_attempts enable row level security;
alter table public.japanese_attempts enable row level security;
alter table public.learning_profiles enable row level security;
alter table public.family_learning_settings enable row level security;
alter table public.problem_feedback enable row level security;
revoke all on table public.math_attempts, public.japanese_attempts,
    public.learning_profiles, public.family_learning_settings, public.problem_feedback from public, anon, authenticated;
revoke all on table public.math_attempts, public.japanese_attempts,
    public.learning_profiles, public.family_learning_settings, public.problem_feedback from service_role;
grant insert, select on table public.math_attempts, public.japanese_attempts
    to service_role;
grant insert, select, update on table public.learning_profiles to service_role;
grant insert, select, update on table public.family_learning_settings to service_role;
grant insert, select on table public.problem_feedback to service_role;

create table if not exists public.family_school_scope (
    user_id text primary key check (user_id in ('user_001', 'user_002')),
    math_unit text not null check (math_unit in ('current','addition_10','subtraction_10','mix_10',
        'addition_20_none','addition_20_with','subtraction_20_none','subtraction_20_with','mix_20')),
    japanese_unit text not null check (japanese_unit in ('current','mix','words','sentence','information',
        'sequence','passage','blank','particles_1','particles_2','particles_3')),
    updated_at timestamptz not null
);
alter table public.family_school_scope enable row level security;
revoke all on public.family_school_scope from public, anon, authenticated, service_role;
grant select, insert, update on public.family_school_scope to service_role;

notify pgrst, 'reload schema';
commit;
