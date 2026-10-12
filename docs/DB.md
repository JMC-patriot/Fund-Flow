# fundflow DB 테이블 문서

- DBMS: PostgreSQL (Supabase) · 스키마 정의: [`supabase/migrations/`](../supabase/migrations/)
- 적재: `collector/load_db.py` (재실행 시 upsert로 갱신, 중복 없음)

## 테이블 관계

```
companies (1) ──< (N) funding_events
    │
    └────────────< (N) financials
```

- 회사 1곳은 여러 건의 자금조달 공시를 냅니다.
- 회사 1곳은 보고서(분기·반기·사업)·기준(연결/별도)별로 여러 재무제표를 가집니다.
- 공시와 재무제표는 `corp_code`와 날짜로 연결됩니다. 공시 접수일(`rcept_dt`) 이전에 공시된(`available_from <= rcept_dt`) 가장 최근 재무제표를 발행 직전 재무상태로 씁니다.

## companies — 회사

| 컬럼 | 타입 | 키 | 설명 |
|---|---|---|---|
| `corp_code` | char(8) | **PK** | DART 고유번호 |
| `corp_name` | text | | 회사명 |
| `stock_code` | varchar(6) | | 종목코드 |
| `corp_cls` | char(1) | | 시장 구분 (Y 유가증권 / K 코스닥 / N 코넥스) |
| `updated_at` | timestamptz | | 마지막 갱신 시각 |

## funding_events — 자금조달 공시

| 컬럼 | 타입 | 키 | 설명 |
|---|---|---|---|
| `rcept_no` | varchar(14) | **PK** | DART 접수번호 (앞 8자리 = 접수일) |
| `corp_code` | char(8) | **FK** → companies | 발행 회사 |
| `ftype` | varchar(6) | | `CB` / `BW` / `EB` / `Equity` (check 제약) |
| `rcept_dt` | date | | 공시 접수일 |
| `board_date` | date | | 이사회 결의일 |
| `amount` | numeric(20,0) | | 발행금액(원). 사채는 권면총액, 유상증자는 자금조달 목적별 금액 합계 |
| `dilution_pct` | numeric(9,4) | | 발행 전 주식총수 대비 신주 비율(%) |
| `exercise_price` | numeric(14,2) | | 전환·행사·교환가액 |
| `coupon_rate` / `ytm_rate` | numeric(7,3) | | 표면이자율 / 만기이자율(%) |
| `maturity_date` | date | | 사채 만기일 |
| `method` | text | | 유상증자 방식 (주주배정·제3자배정 등) |
| `superseded` | boolean | | 정정공시로 대체된 원공시 여부 |
| `raw` | jsonb | | DART API 원본 응답 전체 |
| `loaded_at` | timestamptz | | 적재 시각 |

인덱스: `(ftype, rcept_dt) where not superseded`, `(corp_code)`

## financials — 재무상태표 요약

| 컬럼 | 타입 | 키 | 설명 |
|---|---|---|---|
| `corp_code` | char(8) | **PK**, **FK** → companies | 회사 |
| `bsns_year` | smallint | **PK** | 사업연도 |
| `reprt_code` | char(5) | **PK** | 11013 1분기 / 11012 반기 / 11014 3분기 / 11011 사업보고서 |
| `fs_div` | char(3) | **PK** | `CFS` 연결 / `OFS` 별도 |
| `base_date` | date | | 재무제표 기준일 |
| `available_from` | date | | 공시 기한 (분기·반기 +45일, 사업 +90일) |
| `total_assets` | numeric(22,0) | | 자산총계 |
| `total_liabilities` | numeric(22,0) | | 부채총계 |
| `total_equity` | numeric(22,0) | | 자본총계 |

인덱스: `(corp_code, available_from desc)`

## 보안
세 테이블 모두 RLS(Row Level Security)를 켜 두었고 공개 정책은 없습니다. 브라우저에서 DB에 직접 접근할 수 없고, 모든 조회는 FastAPI 백엔드를 거칩니다.
