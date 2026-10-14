-- 신용등급 정규화 (예: 'AA-(한기평/한신평/NICE)' → 'AA-', 단기 'A1') — 발행조건 벤치마크용
alter table securities add column if not exists grade varchar(6);
