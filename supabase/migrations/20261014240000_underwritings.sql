-- 증권신고서(채무·지분) 인수인정보: 대표주관·인수단별 인수금액·수수료 (리그테이블용)
create table if not exists underwritings (
    rcept_no     varchar(14)   not null,
    corp_code    char(8)       not null,
    underwriter  text          not null,
    role         varchar(10)   not null,           -- 대표 / 인수 / 주선 등
    series       text          not null default '',-- 회차(채무) 또는 증권 종류(지분)
    amount       numeric(20,0),                    -- 인수금액(원)
    fee_text     text,                             -- 인수대가 원문 (예: 인수금액의 0.30%)
    fee_rate     numeric(8,4),                     -- 수수료율(%) 읽을 수 있을 때
    method       text,                             -- 총액인수 / 잔액인수 / 모집주선
    primary key (rcept_no, underwriter, role, series)
);
create index if not exists ix_uw_rcept on underwritings (rcept_no);
alter table underwritings enable row level security;
