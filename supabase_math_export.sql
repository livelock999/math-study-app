-- 旧保存先 ecg-study-app で実行し、結果をCSVで保存します。
-- 件数集計やアプリの表示用履歴ではなく、全列を移行に使います。
select * from public.math_attempts
order by datetime, attempt_id;
