-- 2026-10-14: DB가 무료 한도(500MB)를 넘어 쿼리가 수 분씩 걸림 → 정기보고서 행의 원본(raw) 비우고 압축 (511MB → 160MB)
-- 이미 운영 DB에 적용됨. 새 DB에서는 수집기가 정기보고서 행에 원본을 저장하지 않으므로 필요 없음.
update securities set raw = '{}'::jsonb where source = 'periodic' and raw <> '{}'::jsonb;
-- vacuum full analyze securities;   -- 트랜잭션 밖에서 별도로 실행
create index if not exists ix_sec_rcept_dt on securities (rcept_dt);
