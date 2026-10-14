-- 정기보고서 채무증권 발행실적의 실제 발행회사(isu_cmpny). 모회사 보고서에 연결 자회사 발행분이 섞여 있어 걸러내는 데 사용
alter table securities add column if not exists issuer_name text;
