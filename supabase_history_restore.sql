-- Additive migration: existing answer rows, permissions and settings are kept.
-- Apply supabase_attempts.sql, supabase_japanese.sql and
-- supabase_math_visuals.sql and supabase_three_numbers.sql first, then this file in
-- the learning app project's SQL Editor. No DELETE/UPDATE access is granted.
-- Fill-blank support changes the validation of existing columns. Visual help
-- adds one nullable boolean through supabase_math_visuals.sql. Neither migration
-- rewrites existing answers; their unknown visual-help value remains NULL.
-- Re-run this file after the column migration before publishing the app.
-- Three-number support adds nullable third_operand / second_operation through
-- supabase_three_numbers.sql; existing two-number histories retain NULLs.
-- Three-number word problems reuse those columns. This function update alone
-- adds their format/story/ID validation; no further column migration is needed.
-- Apply supabase_flashcards.sql first for the nullable card/voice metadata.
-- JSON checksums detect accidental file edits in the app; they are not an
-- authentication mechanism. This RPC can only run as the server's service_role.
begin;

create or replace function public.restore_answer_history(backup jsonb)
returns jsonb
language plpgsql
security invoker
set search_path = pg_catalog, public
as $$
declare
    item jsonb;
    spec jsonb;
    field text;
    descriptor jsonb;
    value jsonb;
    uid text;
    math_row public.math_attempts%rowtype;
    prior_math public.math_attempts%rowtype;
    prior_japanese public.japanese_attempts%rowtype;
    math_added integer := 0;
    japanese_added integer := 0;
    math_existing integer := 0;
    japanese_existing integer := 0;
    inserted_count integer;
    unknown_answer boolean;
    actual_correct boolean;
    answer_index integer;
    selected_index integer;
begin
    if current_user <> 'service_role' then
        raise exception 'service role required' using errcode = '42501';
    end if;
    -- jsonb_populate_record ignores unknown keys. Fail closed if the column
    -- migration was skipped, rather than silently losing the visual-help flag.
    if not exists(select 1 from pg_catalog.pg_attribute
                  where attrelid = 'public.math_attempts'::regclass
                    and attname = 'visual_help_used' and not attisdropped
                    and atttypid = 'boolean'::regtype) then
        raise exception 'apply supabase_math_visuals.sql before restoring history';
    end if;
    if not exists(select 1 from pg_catalog.pg_attribute
                  where attrelid = 'public.math_attempts'::regclass
                    and attname = 'third_operand' and not attisdropped
                    and atttypid = 'integer'::regtype)
       or not exists(select 1 from pg_catalog.pg_attribute
                     where attrelid = 'public.math_attempts'::regclass
                       and attname = 'second_operation' and not attisdropped
                       and atttypid = 'text'::regtype) then
        raise exception 'apply supabase_three_numbers.sql before restoring history';
    end if;
    -- All nullable fields must exist with the expected PostgreSQL type.
    for field, value in select e.key, e.value from jsonb_each('{"learning_mode":"text","answer_range_min":"integer","answer_range_max":"integer","input_method":"text","recognized_text":"text","parsed_answer":"integer","recognition_success":"boolean","recognition_retry_count":"integer","first_attempt_correct":"boolean","session_elapsed_sec":"double precision","total_recognition_retry_count":"integer"}'::jsonb) e loop
        if not exists(select 1 from pg_catalog.pg_attribute
                      where attrelid = 'public.math_attempts'::regclass
                        and attname = field and not attisdropped
                        and atttypid = (value #>> '{}')::regtype) then
            raise exception 'apply supabase_flashcards.sql before restoring history';
        end if;
    end loop;
    if jsonb_typeof(backup) is distinct from 'object'
       or octet_length(backup::text) > 10485760
       or backup->>'format' is distinct from 'family-study-answer-history'
       or backup->'version' is distinct from '1'::jsonb
       or jsonb_typeof(backup->'user_id') is distinct from 'string'
       or jsonb_typeof(backup->'math') is distinct from 'array'
       or jsonb_typeof(backup->'japanese') is distinct from 'array'
       or jsonb_typeof(backup->'created_at') is distinct from 'string'
       or jsonb_typeof(backup->'checksum') is distinct from 'string'
       or length(backup->>'checksum') <> 64
       or (select count(*) from jsonb_object_keys(backup)) <> 7 then
        raise exception 'invalid backup structure';
    end if;
    uid := backup->>'user_id';
    if uid not in ('user_001', 'user_002') then
        raise exception 'invalid learner';
    end if;
    if jsonb_array_length(backup->'math') + jsonb_array_length(backup->'japanese') > 20000 then
        raise exception 'backup row limit exceeded';
    end if;
    if backup->>'created_at' !~ '(Z|[+-][0-9]{2}:[0-9]{2})$' then
        raise exception 'timezone required';
    end if;
    perform (backup->>'created_at')::timestamptz;
    if exists(select 1 from jsonb_array_elements(backup->'math') r
              group by r->>'attempt_id' having count(*) > 1)
       or exists(select 1 from jsonb_array_elements(backup->'japanese') r
                 group by r->>'attempt_id' having count(*) > 1) then
        raise exception 'duplicate backup answer IDs';
    end if;

    -- Serialize restores. Ordinary answer saves may race this RPC: unique-key
    -- INSERT DO NOTHING waits for them, then reread compares their committed
    -- row. This needs only the existing SELECT/INSERT grants.
    perform pg_advisory_xact_lock(61081008);

    -- Entry is [JSON type, required]. Nullable historical fields stay NULL.
    spec := '{"attempt_id":["string",true],"user_id":["string",true],"session_id":["string",true],"datetime":["string",true],"problem_id":["string",true],"question_order":["integer",true],"selection_type":["string",true],"problem_format":["string",true],"operation":["string",true],"number_range":["integer",true],"left_operand":["integer",true],"right_operand":["integer",true],"carry":["boolean",false],"borrowing":["boolean",false],"crosses_10":["boolean",false],"zero_included":["boolean",false],"doubles":["boolean",false],"blank_position":["string",false],"story_type":["string",false],"unknown_type":["string",false],"operation_selection_correct":["boolean",false],"equation_correct":["boolean",false],"calculation_correct":["boolean",false],"question_text":["string",true],"correct_answer":["integer",true],"user_answer":["integer",false],"is_correct":["boolean",true],"response_time_sec":["number",true],"attempt_count":["integer",true],"hint_used":["boolean",false],"dont_know_used":["boolean",false],"retry_flag":["boolean",false],"answer_is_10":["boolean",false],"operand_contains_10":["boolean",false],"near_10":["boolean",false],"commutative_pair":["string",false],"round_size":["integer",false],"round_completed":["boolean",false],"user_equation":["string",false],"reading_help_used":["boolean",false],"hint_level":["integer",false],"visual_help_used":["boolean",false],"third_operand":["integer",false],"second_operation":["string",false],"learning_mode":["string",false],"answer_range_min":["integer",false],"answer_range_max":["integer",false],"input_method":["string",false],"recognized_text":["string",false],"parsed_answer":["integer",false],"recognition_success":["boolean",false],"recognition_retry_count":["integer",false],"first_attempt_correct":["boolean",false],"session_elapsed_sec":["number",false],"total_recognition_retry_count":["integer",false]}'::jsonb;
    for item in select r from jsonb_array_elements(backup->'math') r loop
        if jsonb_typeof(item) <> 'object'
           or (select count(*) from jsonb_object_keys(item)) <> (select count(*) from jsonb_object_keys(spec))
           or item->>'user_id' is distinct from uid then
            raise exception 'invalid math answer structure';
        end if;
        for field, descriptor in select e.key, e.value from jsonb_each(spec) e loop
            value := item->field;
            if not item ? field or (value = 'null'::jsonb and (descriptor->>1)::boolean) then
                raise exception 'missing math field';
            end if;
            if value <> 'null'::jsonb then
                if descriptor->>0 = 'integer' then
                    if jsonb_typeof(value) <> 'number' or value::text !~ '^-?[0-9]+$' then
                        raise exception 'invalid math integer';
                    end if;
                elsif jsonb_typeof(value) is distinct from descriptor->>0 then
                    raise exception 'invalid math field type';
                end if;
                if jsonb_typeof(value) = 'string' and (length(item->>field) = 0 or length(item->>field) > 20000) then
                    raise exception 'invalid math text';
                end if;
            end if;
        end loop;
        if item->>'datetime' !~ '(Z|[+-][0-9]{2}:[0-9]{2})$'
           or (item->>'question_order')::integer < 1
           or (item->>'attempt_count')::integer < 1
           or (item->>'response_time_sec')::double precision < 0
           or (item->>'hint_level')::integer not between 0 and 3 then
            raise exception 'invalid math answer values';
        end if;
        if item->'visual_help_used' = 'true'::jsonb and item->'hint_used' is distinct from 'true'::jsonb then
            raise exception 'visual help requires hint-used flag';
        end if;
        if item->>'selection_type' not in ('normal','weak_area','retry','review','review_retry')
           or item->>'operation' not in ('addition','subtraction')
           or item->>'problem_format' not in ('calculation','word_problem','fill_blank','three_numbers','three_word_problem')
           or (item->>'number_range')::integer not in (10,20)
           or (item->>'left_operand')::integer not between 0 and (item->>'number_range')::integer
           or (item->>'right_operand')::integer not between 0 and (item->>'number_range')::integer
           or (item->>'correct_answer')::integer not between 0 and (item->>'number_range')::integer
           or (item->>'user_answer')::integer not between 0 and 999
           or ((item->>'round_size')::integer is not null and (item->>'round_size')::integer < (item->>'question_order')::integer)
           or (case when item->>'operation'='addition'
                  then (item->>'left_operand')::integer + (item->>'right_operand')::integer
                  else (item->>'left_operand')::integer - (item->>'right_operand')::integer end)
                  not between 0 and (item->>'number_range')::integer then
            raise exception 'invalid math problem or answer';
        end if;
        if item->>'problem_format' = 'three_word_problem' then
            if item->>'story_type' is null or item->>'story_type' not in
                   ('increase_twice','decrease_twice','increase_then_decrease','decrease_then_increase')
               or item->>'unknown_type' is distinct from 'result'
               or (item->>'left_operand')::integer < 1
               or (item->>'right_operand')::integer < 1
               or (item->>'third_operand')::integer < 1
               or item->>'operation' is distinct from (case when item->>'story_type' in ('increase_twice','increase_then_decrease')
                       then 'addition' else 'subtraction' end)
               or item->>'second_operation' is distinct from (case when item->>'story_type' in ('increase_twice','decrease_then_increase')
                       then 'addition' else 'subtraction' end) then
                raise exception 'invalid three-number word story, operands or operations';
            end if;
        end if;
        if item->>'problem_format' in ('three_numbers','three_word_problem') then
            if item->'third_operand' = 'null'::jsonb or item->'second_operation' = 'null'::jsonb
               or (item->>'third_operand')::integer not between 0 and (item->>'number_range')::integer
               or item->>'second_operation' not in ('addition','subtraction')
               or (item->>'problem_format' = 'three_numbers' and item->>'problem_id' is distinct from concat('three_numbers_v1_',item->>'operation','_',
                     item->>'second_operation','_',item->>'number_range','_',item->>'left_operand','_',
                     item->>'right_operand','_',item->>'third_operand'))
               or (item->>'problem_format' = 'three_word_problem' and item->>'problem_id' is distinct from concat('three_word_v1_',
                     item->>'story_type','_',item->>'number_range','_',item->>'left_operand','_',
                     item->>'right_operand','_',item->>'third_operand'))
               or (item->>'correct_answer')::integer <> (case when item->>'second_operation'='addition'
                     then (case when item->>'operation'='addition'
                           then (item->>'left_operand')::integer + (item->>'right_operand')::integer
                           else (item->>'left_operand')::integer - (item->>'right_operand')::integer end)
                           + (item->>'third_operand')::integer
                     else (case when item->>'operation'='addition'
                           then (item->>'left_operand')::integer + (item->>'right_operand')::integer
                           else (item->>'left_operand')::integer - (item->>'right_operand')::integer end)
                           - (item->>'third_operand')::integer end) then
                raise exception 'invalid three-number operand, operation, answer or ID';
            end if;
        elsif item->'third_operand' <> 'null'::jsonb or item->'second_operation' <> 'null'::jsonb then
            raise exception 'two-number history must not have a third operand or operation';
        elsif item->>'problem_format' = 'fill_blank' then
            if item->>'blank_position' is null or item->>'blank_position' not in ('left_operand','right_operand')
               or item->>'problem_id' is distinct from concat('fill_blank_v1_',item->>'operation','_',
                     item->>'number_range','_',item->>'blank_position','_',item->>'left_operand','_',item->>'right_operand')
               or (item->>'correct_answer')::integer <> (case when item->>'blank_position'='left_operand'
                     then (item->>'left_operand')::integer else (item->>'right_operand')::integer end) then
                raise exception 'invalid fill-blank position, answer or ID';
            end if;
        elsif (item->>'correct_answer')::integer <> (case when item->>'operation'='addition'
                  then (item->>'left_operand')::integer + (item->>'right_operand')::integer
                  else (item->>'left_operand')::integer - (item->>'right_operand')::integer end) then
            raise exception 'invalid math result answer';
        end if;
        if item->>'learning_mode' not in ('normal','flashcard','retry','weak_practice')
           or item->>'input_method' not in ('voice','keyboard','keypad')
           or ((item->>'answer_range_min' is null) <> (item->>'answer_range_max' is null))
           or (item->>'answer_range_min')::integer < 0
           or (item->>'answer_range_max')::integer > 20
           or (item->>'answer_range_min')::integer > (item->>'correct_answer')::integer
           or (item->>'answer_range_max')::integer < (item->>'correct_answer')::integer
           or (item->>'recognition_retry_count')::integer < 0
           or (item->>'total_recognition_retry_count')::integer < 0
           or (item->>'total_recognition_retry_count')::integer < (item->>'recognition_retry_count')::integer
           or (item->>'session_elapsed_sec')::double precision < (item->>'response_time_sec')::double precision
           or ((item->>'attempt_count')::integer = 1 and item->'first_attempt_correct' <> 'null'::jsonb
               and item->'first_attempt_correct' is distinct from item->'is_correct') then
            raise exception 'invalid flashcard mode, range, retries, elapsed time or first correctness';
        end if;
        if item->>'input_method' = 'voice' then
            if item->>'recognized_text' is null
               or item->'recognition_success' is distinct from 'true'::jsonb
               or item->'parsed_answer' is distinct from item->'user_answer'
               or item->'parsed_answer' = 'null'::jsonb
               or (item->>'parsed_answer')::integer not between 0 and 99
               or item->'recognition_retry_count' = 'null'::jsonb then
                raise exception 'invalid accepted voice recognition';
            end if;
        elsif item->'recognized_text' <> 'null'::jsonb
           or item->'parsed_answer' <> 'null'::jsonb
           or item->'recognition_success' <> 'null'::jsonb then
            raise exception 'non-voice answers must not contain recognition metadata';
        end if;
        if item->>'learning_mode' = 'flashcard'
           and (item->>'problem_format' <> 'calculation' or item->>'input_method' is null
                or (item->>'user_answer')::integer not between 0 and 99) then
            raise exception 'invalid flashcard format or input method';
        end if;
        math_row := jsonb_populate_record(null::public.math_attempts, item);
        insert into public.math_attempts select math_row.* on conflict(attempt_id) do nothing;
        get diagnostics inserted_count = row_count;
        select * into prior_math from public.math_attempts where attempt_id = math_row.attempt_id;
        -- timestamptz and boolean representations are normalized by the
        -- composite type, so +09:00/UTC and local 0/1 do not conflict.
        if not found or to_jsonb(prior_math) is distinct from to_jsonb(math_row) then
            raise exception 'conflicting math answer ID';
        end if;
        if inserted_count = 1 then
            math_added := math_added + 1;
        else
            math_existing := math_existing + 1;
        end if;
    end loop;

    for item in select r from jsonb_array_elements(backup->'japanese') r loop
        if jsonb_typeof(item) <> 'object' or item->>'user_id' is distinct from uid
           or (item ? 'learner_id' and item->>'learner_id' is distinct from uid) then
            raise exception 'invalid Japanese learner';
        end if;
        foreach field in array array['attempt_id','user_id','session_id','datetime','chain_id','question_id','category','problem_format','selection_type'] loop
            if jsonb_typeof(item->field) is distinct from 'string' or length(item->>field) not between 1 and 200 then
                raise exception 'invalid Japanese identifier';
            end if;
        end loop;
        foreach field in array array['text','question','hint','explanation','selected_answer_text'] loop
            if jsonb_typeof(item->field) is distinct from 'string' then
                raise exception 'invalid Japanese text';
            end if;
        end loop;
        foreach field in array array['question_order','attempt_count'] loop
            if jsonb_typeof(item->field) is distinct from 'number' or item->>field !~ '^[0-9]+$' or (item->>field)::integer < 1 then
                raise exception 'invalid Japanese count';
            end if;
        end loop;
        if jsonb_typeof(item->'correct') is distinct from 'boolean'
           or jsonb_typeof(item->'response_time_sec') is distinct from 'number'
           or (item->>'response_time_sec')::double precision < 0
           or jsonb_typeof(item->'choices') is distinct from 'array'
           or jsonb_array_length(item->'choices') not between 2 and 20
           or exists(select 1 from jsonb_array_elements(item->'choices') c where jsonb_typeof(c) <> 'string')
           or not item ? 'answer' or not item ? 'selected_answer' then
            raise exception 'invalid Japanese answer';
        end if;
        foreach field in array array['hint_used','reading_help_used','dont_know_used','retry_flag','final_correct'] loop
            if item ? field and item->field <> 'null'::jsonb and jsonb_typeof(item->field) <> 'boolean' then
                raise exception 'invalid Japanese boolean';
            end if;
        end loop;
        if item ? 'hint_level' and item->'hint_level' <> 'null'::jsonb then
            if jsonb_typeof(item->'hint_level') <> 'number' or item->>'hint_level' !~ '^[0-9]+$'
               or (item->>'hint_level')::integer not between 0 and 3 then
                raise exception 'invalid Japanese hint';
            end if;
        end if;
        foreach field in array array['datetime','answered_at','review_due_at'] loop
            if item ? field and item->field <> 'null'::jsonb then
                if jsonb_typeof(item->field) <> 'string' or item->>field !~ '(Z|[+-][0-9]{2}:[0-9]{2})$' then
                    raise exception 'Japanese timezone required';
                end if;
                perform (item->>field)::timestamptz;
            end if;
        end loop;
        if item->>'selection_type' not in ('normal','weak_area','retry','review','review_retry')
           or item->>'category' not in ('words','sentence','information','sequence','passage','blank','particles')
           or item->>'problem_format' not in ('choice','ordering','particle_choice')
           or item->>'reading_mode' not in ('self_read','audio')
           or jsonb_typeof(item->'reading_mode') is distinct from 'string'
           or jsonb_typeof(item->'question_word') is distinct from 'string'
           or item->>'question_word' not in ('who','what','where','when','action','why','how','order','reference','match','word','blank','particle') then
            raise exception 'invalid Japanese problem metadata';
        end if;
        foreach field in array array['reasoning_level','difficulty','version'] loop
            if jsonb_typeof(item->field) is distinct from 'number'
               or item->>field !~ '^[0-9]+$' or (item->>field)::integer < 1 then
                raise exception 'invalid Japanese difficulty';
            end if;
        end loop;
        if (item->>'reasoning_level')::integer > 4 or (item->>'difficulty')::integer > 3 then
            raise exception 'invalid Japanese difficulty range';
        end if;
        foreach field in array array['skill_tags','error_cause_tags'] loop
            if jsonb_typeof(item->field) is distinct from 'array'
               or exists(select 1 from jsonb_array_elements(item->field) t where jsonb_typeof(t) <> 'string' or t::text = '""')
               or (field = 'skill_tags' and jsonb_array_length(item->field) = 0) then
                raise exception 'invalid Japanese tags';
            end if;
        end loop;
        if jsonb_typeof(item->'error_tags') is distinct from 'object' then
            raise exception 'invalid Japanese error tags';
        end if;
        for field, value in select e.key, e.value from jsonb_each(item->'error_tags') e loop
            if jsonb_typeof(value) <> 'array'
               or exists(select 1 from jsonb_array_elements(value) t where jsonb_typeof(t) <> 'string') then
                raise exception 'invalid Japanese error classification';
            end if;
        end loop;
        unknown_answer := coalesce((item->>'dont_know_used')::boolean,false);
        if item->>'problem_format' = 'ordering' then
            foreach field in array array['answer','selected_answer'] loop
                if field = 'selected_answer' and unknown_answer then
                    if item->field is distinct from 'null'::jsonb then
                        raise exception 'invalid Japanese unknown answer';
                    end if;
                else
                    if jsonb_typeof(item->field) <> 'array' or jsonb_array_length(item->field) <> jsonb_array_length(item->'choices') then
                        raise exception 'invalid Japanese ordering answer';
                    end if;
                    if exists(select 1 from jsonb_array_elements(item->field) n
                              where jsonb_typeof(n) <> 'number' or n::text !~ '^[0-9]+$') then
                        raise exception 'invalid Japanese ordering index';
                    end if;
                    if exists(select 1 from jsonb_array_elements(item->field) n
                              where n::text::integer not between 0 and jsonb_array_length(item->'choices')-1)
                       or (select count(distinct n) from jsonb_array_elements(item->field) n) <> jsonb_array_length(item->'choices') then
                        raise exception 'invalid Japanese ordering permutation';
                    end if;
                end if;
            end loop;
            actual_correct := not unknown_answer and item->'selected_answer' = item->'answer';
        else
            if jsonb_typeof(item->'answer') <> 'number' or item->>'answer' !~ '^[0-9]+$' then
                raise exception 'invalid Japanese correct answer index';
            end if;
            answer_index := (item->>'answer')::integer;
            if answer_index not between 0 and jsonb_array_length(item->'choices')-1 then
                raise exception 'invalid Japanese correct answer range';
            end if;
            if item->>'category' = 'particles' then
                if item->'correct_answer' is distinct from item->'choices'->answer_index
                   or jsonb_typeof(item->'first_try_correct') is distinct from 'boolean' then
                    raise exception 'invalid particle answer metadata';
                end if;
                if unknown_answer then
                    if item->'selected_answer_index' is distinct from 'null'::jsonb or item->>'selected_answer' is distinct from 'わからない' then
                        raise exception 'invalid particle unknown answer';
                    end if;
                    selected_index := null;
                else
                    if jsonb_typeof(item->'selected_answer_index') is distinct from 'number' or item->>'selected_answer_index' !~ '^[0-9]+$' then
                        raise exception 'invalid particle selected index';
                    end if;
                    selected_index := (item->>'selected_answer_index')::integer;
                    if selected_index not between 0 and jsonb_array_length(item->'choices')-1
                       or item->'selected_answer' is distinct from item->'choices'->selected_index then
                        raise exception 'invalid particle selected answer';
                    end if;
                end if;
            elsif unknown_answer then
                if item->'selected_answer' is distinct from 'null'::jsonb then
                    raise exception 'invalid Japanese unknown choice';
                end if;
                selected_index := null;
            else
                if jsonb_typeof(item->'selected_answer') is distinct from 'number' or item->>'selected_answer' !~ '^[0-9]+$' then
                    raise exception 'invalid Japanese selected index';
                end if;
                selected_index := (item->>'selected_answer')::integer;
                if selected_index not between 0 and jsonb_array_length(item->'choices')-1 then
                    raise exception 'invalid Japanese selected range';
                end if;
            end if;
            actual_correct := not unknown_answer and selected_index = answer_index;
        end if;
        if item->'correct' is distinct from to_jsonb(actual_correct) then
            raise exception 'Japanese correctness does not match selected answer';
        end if;
        insert into public.japanese_attempts(attempt_id,user_id,session_id,datetime,payload)
            values(item->>'attempt_id',uid,item->>'session_id',(item->>'datetime')::timestamptz,item)
            on conflict(attempt_id) do nothing;
        get diagnostics inserted_count = row_count;
        select * into prior_japanese from public.japanese_attempts where attempt_id = item->>'attempt_id';
        -- Complete original JSON payloads must match; only recognized
        -- timestamp strings are compared by instant, not timezone spelling.
        if not found or prior_japanese.user_id is distinct from uid
               or prior_japanese.session_id is distinct from item->>'session_id'
               or prior_japanese.datetime is distinct from (item->>'datetime')::timestamptz
               or (prior_japanese.payload - 'datetime' - 'answered_at' - 'review_due_at')
                  is distinct from (item - 'datetime' - 'answered_at' - 'review_due_at') then
            raise exception 'conflicting Japanese answer ID';
        end if;
        foreach field in array array['datetime','answered_at','review_due_at'] loop
                if (prior_japanese.payload ? field) is distinct from (item ? field)
                   or (prior_japanese.payload->>field)::timestamptz is distinct from (item->>field)::timestamptz then
                    raise exception 'conflicting Japanese answer timestamp';
                end if;
        end loop;
        if inserted_count = 1 then
            japanese_added := japanese_added + 1;
        else
            japanese_existing := japanese_existing + 1;
        end if;
    end loop;
    return jsonb_build_object('math_added',math_added,'japanese_added',japanese_added,
                             'math_existing',math_existing,'japanese_existing',japanese_existing);
end;
$$;

revoke all on function public.restore_answer_history(jsonb) from public, anon, authenticated;
grant execute on function public.restore_answer_history(jsonb) to service_role;
notify pgrst, 'reload schema';
commit;
