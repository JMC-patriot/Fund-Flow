-- 최근 거래일 종가·상장주식수 (KRX Open API, 메자닌 오버행 계산용). 종목당 1행만 유지
create table if not exists quotes (
    stock_code  varchar(6)    primary key,
    name        text,
    market      varchar(10),
    bas_dd      date          not null,
    close       numeric(16,2),
    mktcap      numeric(22,0),
    list_shrs   numeric(18,0),
    updated_at  timestamptz   not null default now()
);
alter table quotes enable row level security;
