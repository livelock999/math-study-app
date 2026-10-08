-- 今の保存先（ecg-study-app）の SQL Editor で実行。
-- 記録の件数を見るだけで、書き込み・変更は行いません。
select '算数' as subject, count(*) as records
from public.math_attempts
union all
select '国語' as subject, count(*) as records
from public.japanese_attempts;
