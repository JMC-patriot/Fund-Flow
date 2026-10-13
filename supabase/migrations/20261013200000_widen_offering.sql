-- 공모/사모 값이 '공모(일괄신고)'처럼 길게 오는 경우 대비
alter table securities alter column offering type varchar(20);
