-- 한국거래소(KIND) 상장일: IPO와 상장사 공모증자를 구분하는 기준
alter table companies add column if not exists listed_on date;
