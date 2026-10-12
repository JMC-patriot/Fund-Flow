-- fundflow v2 스키마 (PostgreSQL / Supabase)
-- 2020년 이후 DART 공시 회사의 자금조달 증권(SB·CB·BW·EB·RCPS·유상증자·IPO·CP·단기사채)
-- 발행 조건, 상환 여부, 재무제표

-- v1 테이블 정리
drop table if exists funding_events cascade;
drop table if exists financials cascade;

-- 1) 회사
create table if not exists companies (
    corp_code   char(8)      primary key,               -- DART 고유번호
    corp_name   text         not null,
    stock_code  varchar(6),                              -- 종목코드 (비상장은 null)
    corp_cls    char(1),                                 -- Y 유가 / K 코스닥 / N 코넥스 / E 기타
    updated_at  timestamptz  not null default now()
);

-- 2) 증권 (발행 1건 = 1행)
create table if not exists securities (
    id              text          primary key,          -- 출처별 고유키 (예: D:접수번호, R:접수번호:회차, P:해시)
    corp_code       char(8)       not null references companies(corp_code),
    sec_type        varchar(6)    not null check (sec_type in
                      ('SB','CB','BW','EB','RCPS','EQUITY','IPO','CP','STB')),
    source          varchar(10)   not null check (source in ('decision','bond_rs','equity_rs','periodic')),
    offering        varchar(4),                         -- 공모 / 사모
    rcept_no        varchar(14),                        -- 원 공시 접수번호
    rcept_dt        date,                               -- 공시 접수일
    name            text,                               -- 증권 명칭 (예: 무기명식 이권부 무보증 사모 전환사채)
    series          text,                               -- 회차
    board_date      date,                               -- 이사회 결의일
    issue_date      date,                               -- 발행(납입)일
    amount          numeric(20,0) check (amount >= 0),  -- 발행금액(원)
    coupon          numeric(7,3),                       -- 표면이자율(%)
    ytm             numeric(7,3),                       -- 만기이자율(%)
    maturity_date   date,                               -- 만기일
    conv_price      numeric(16,2),                      -- 전환가액 / 행사가액 / 교환가액 / 발행가
    refix_floor     numeric(16,2),                      -- 시가하락 조정 최저가액
    conv_start      date,                               -- 전환·행사·교환 청구 시작일
    conv_end        date,                               -- 청구 종료일
    underlying      text,                               -- 교환대상 / 신주 종류
    shares          numeric(18,0),                      -- 신주(전환·행사·교환 가능) 주식수
    dilution_pct    numeric(9,4),                       -- 발행 전 주식총수 대비 비율(%)
    rating          text,                               -- 신용등급(평가기관)
    repaid          text,                               -- 상환 / 미상환 / 일부상환 (정기보고서 기준)
    repaid_asof     date,                               -- 상환 여부 기준일
    method          text,                               -- 증자 방식 / 인수 방식
    underwriter     text,                               -- 대표 주관사
    dkey            text          not null,             -- 정정 판별 키 (같은 키면 최신 접수본만 유효)
    superseded      boolean       not null default false,-- 정정·중복으로 대체된 행
    raw             jsonb         not null,
    loaded_at       timestamptz   not null default now()
);
create index if not exists ix_sec_maturity on securities (maturity_date) where not superseded;
create index if not exists ix_sec_type_issue on securities (sec_type, issue_date) where not superseded;
create index if not exists ix_sec_corp on securities (corp_code);

-- 3) 주요 재무 (DART 주요계정)
create table if not exists financials (
    corp_code          char(8)       not null references companies(corp_code),
    bsns_year          smallint      not null,
    reprt_code         char(5)       not null,           -- 11013 1Q / 11012 반기 / 11014 3Q / 11011 사업
    fs_div             char(3)       not null check (fs_div in ('CFS','OFS')),
    base_date          date          not null,           -- 재무제표 기준일
    rcept_no           varchar(14),
    current_assets     numeric(22,0),
    noncurrent_assets  numeric(22,0),
    total_assets       numeric(22,0),
    current_liab       numeric(22,0),
    noncurrent_liab    numeric(22,0),
    total_liab         numeric(22,0),
    capital            numeric(22,0),
    retained           numeric(22,0),
    total_equity       numeric(22,0),
    revenue            numeric(22,0),                    -- 누적 기준 (분기보고서는 연초부터)
    op_income          numeric(22,0),
    pretax_income      numeric(22,0),
    net_income         numeric(22,0),
    primary key (corp_code, bsns_year, reprt_code, fs_div)
);
create index if not exists ix_fin_base on financials (corp_code, base_date desc);

-- 4) 전체 재무제표 (상세 화면에서 요청 시 DART에서 받아 저장)
create table if not exists statements (
    corp_code   char(8)      not null references companies(corp_code),
    bsns_year   smallint     not null,
    reprt_code  char(5)      not null,
    fs_div      char(3)      not null,
    data        jsonb        not null,                   -- [{sj_div, account_nm, thstrm_amount, ...}]
    fetched_at  timestamptz  not null default now(),
    primary key (corp_code, bsns_year, reprt_code, fs_div)
);

-- 5) 처리 대상 공시 목록 (수집 작업 대기열)
create table if not exists filings (
    rcept_no    varchar(14)  primary key,
    corp_code   char(8)      not null,
    corp_name   text         not null,
    corp_cls    char(1),
    stock_code  varchar(6),
    report_nm   text         not null,
    rcept_dt    date         not null,
    kind        varchar(10)  not null,                  -- CB/BW/EB/EQUITY 결정, BOND_RS/EQUITY_RS 신고서, ANNUAL/HALF/Q1/Q3 정기보고서
    status      varchar(8)   not null default 'pending',-- 증권 수집: pending / done
    fin_status  varchar(8)   not null default 'pending' -- 재무 수집 (정기보고서만): pending / done / skip
);
create index if not exists ix_filings_todo on filings (kind, status, rcept_dt desc);

-- 6) 수집 진행 기록 (이미 처리한 DART 호출은 다시 하지 않음)
create table if not exists fetch_log (
    task        text         primary key,               -- 예: list:B:20200101, dec:CB:00126380, per:00126380:2024:11011
    status      text         not null,                  -- done / empty / error
    fetched_at  timestamptz  not null default now()
);

comment on table companies  is 'DART 공시 회사';
comment on table securities is '자금조달 증권 발행 내역 (공시·증권신고서·정기보고서 통합)';
comment on table financials is '보고서별 주요 재무 (자산·부채·자본·손익)';
comment on table statements is '전체 재무제표 캐시';
comment on table filings    is '수집 대상 공시 목록';
comment on table fetch_log  is '수집기 진행 기록';
alter table filings    enable row level security;

-- 백엔드(FastAPI)만 접근하므로 RLS를 켜고 정책은 두지 않음
alter table companies  enable row level security;
alter table securities enable row level security;
alter table financials enable row level security;
alter table statements enable row level security;
alter table fetch_log  enable row level security;
