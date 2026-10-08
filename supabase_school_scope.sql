-- 既存Supabaseへの追加更新。学習履歴・目標・学年設定は変更しません。
-- SQL Editorで全体を実行後、学校範囲機能とおまかせ難易度を一緒に公開します。
begin;
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
