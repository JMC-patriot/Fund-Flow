-- fundflow DB 스키마 (PostgreSQL / Supabase)
-- 상장사 자금조달 공시(CB·BW·EB·유상증자)와 발행 직전 재무제표

-- 1) 회사
create table if not exists companies (
    corp_code   char(8)      primary key,               -- DART 고유번호
    corp_name   text         not null,
    stock_code  varchar(6),                              -- 종목코드
    corp_cls    char(1),                                 -- Y 유가 / K 코스닥 / N 코넥스
    updated_at  timestamptz  not null default now()
);

-- 2) 자금조달 공시 이벤트
create table if not exists funding_events (
    rcept_no        varchar(14)   primary key,           -- DART 접수번호
    corp_code       char(8)       not null references companies(corp_code),
    ftype           varchar(6)    not null check (ftype in ('CB','BW','EB','Equity')),
    rcept_dt        date          not null,              -- 공시 접수일
    board_date      date,                                -- 이사회 결의일
    amount          numeric(20,0) not null check (amount > 0),  -- 발행금액(원)
    dilution_pct    numeric(9,4),                        -- 발행 전 주식총수 대비 신주 비율(%)
    exercise_price  numeric(14,2),                       -- 전환·행사·교환가액
    coupon_rate     numeric(7,3),                        -- 표면이자율(%)
    ytm_rate        numeric(7,3),                        -- 만기이자율(%)
    maturity_date   date,                                -- 사채 만기일
    method          text,                                -- 유상증자 방식 등
    superseded      boolean       not null default false,-- 정정공시로 대체된 원공시
    raw             jsonb         not null,              -- API 원본 응답
    loaded_at       timestamptz   not null default now()
);
create index if not exists ix_events_type_dt on funding_events (ftype, rcept_dt) where not superseded;
create index if not exists ix_events_corp    on funding_events (corp_code);

-- 3) 재무상태표 요약 (발행 전후 비율 계산의 기준)
create table if not exists financials (
    corp_code          char(8)       not null references companies(corp_code),
    bsns_year          smallint      not null,
    reprt_code         char(5)       not null,           -- 11013 1Q / 11012 반기 / 11014 3Q / 11011 사업
    fs_div             char(3)       not null check (fs_div in ('CFS','OFS')),  -- 연결/별도
    base_date          date          not null,           -- 재무제표 기준일
    available_from     date          not null,           -- 공시 기한(이 날부터 시장이 알 수 있음)
    total_assets       numeric(22,0) not null,
    total_liabilities  numeric(22,0) not null,
    total_equity       numeric(22,0) not null,
    primary key (corp_code, bsns_year, reprt_code, fs_div)
);
create index if not exists ix_fin_lookup on financials (corp_code, available_from desc);

comment on table companies is 'DART 상장사 (자금조달 공시 발행 회사)';
comment on table funding_events is 'CB/BW/EB/유상증자 결정 공시';
comment on table financials is '발행 직전 재무상태표 요약 (자산/부채/자본총계)';

-- 공개 읽기 전용 접근은 백엔드(FastAPI)만 사용하므로 RLS를 켜고 정책은 두지 않음
alter table companies       enable row level security;
alter table funding_events  enable row level security;
alter table financials      enable row level security;
