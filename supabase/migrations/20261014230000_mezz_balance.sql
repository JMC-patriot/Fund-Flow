-- 메자닌(CB·BW·EB) 회차별 잔액 추적: 행사(전환·신주인수권·교환), 전환가액 조정, 만기전 사채취득 공시에서 추출
create table if not exists mezz_balance (
    corp_code   char(8)       not null references companies(corp_code),
    series      varchar(20)   not null,              -- 회차 (숫자 부분)
    rcept_no    varchar(14)   not null,
    rcept_dt    date          not null,
    kind        varchar(10)   not null,              -- EXERCISE / REFIX / REDEEM
    remaining   numeric(20,0),                       -- 신고일 현재 미전환·미행사·미교환 잔액(원)
    conv_price  numeric(16,2),                       -- 현재 전환·행사·교환가액
    shares      numeric(18,0),                       -- 남은 전환·행사·교환 가능 주식수
    primary key (corp_code, series, rcept_no)
);
create index if not exists ix_mb_latest on mezz_balance (corp_code, series, rcept_dt desc);
alter table mezz_balance enable row level security;
