# fundflow DB 테이블 문서

- **DBMS**: PostgreSQL 17 (Supabase, 서울 리전)
- **스키마 정의**: [`supabase/migrations/`](../supabase/migrations/) (적용 순서 = 파일명 순서)
- **적재**: `collector/run.py` (GitHub Actions 3시간마다, upsert라 재실행해도 중복 없음)

## 테이블 관계

```
                         ┌───────────────┐
                         │   companies   │  PK corp_code
                         └───────┬───────┘
        ┌──────────────┬─────────┼──────────────┬───────────────┐
        │ 1:N          │ 1:N     │ 1:N          │ 1:N           │ 1:N
 ┌──────▼──────┐ ┌─────▼─────┐ ┌─▼──────────┐ ┌─▼───────────┐ ┌─▼───────────┐
 │ securities  │ │financials │ │ statements │ │mezz_balance │ │ (filings)   │
 │ PK id       │ │PK 4개 열  │ │ PK 4개 열  │ │ PK 3개 열   │ │ PK rcept_no │
 └──────┬──────┘ └───────────┘ └────────────┘ └─────────────┘ └─────────────┘
        │ rcept_no (논리적 연결)
 ┌──────▼───────┐        companies.stock_code ── quotes.stock_code (논리적 연결)
 │underwritings │        fetch_log: 수집 진행 기록 (독립)
 └──────────────┘
```

- 회사 1곳은 여러 증권(`securities`), 여러 보고서별 재무(`financials`, `statements`), 회차별 메자닌 잔액(`mezz_balance`)을 가집니다.
- 증권과 인수단(`underwritings`)은 증권신고서 접수번호(`rcept_no`)로 연결됩니다.
- 주가(`quotes`)는 종목코드(`stock_code`)로 회사와 연결됩니다.

## 테이블 목록

| 테이블 | 내용 | 기본키 | 외래키 |
|---|---|---|---|
| `companies` | DART 공시 회사 | `corp_code` | – |
| `securities` | 증권 발행 1건 = 1행 (9개 유형 통합) | `id` | `corp_code` → companies |
| `financials` | 보고서별 주요 재무 | `(corp_code, bsns_year, reprt_code, fs_div)` | `corp_code` → companies |
| `statements` | 전체 재무제표 캐시 | `(corp_code, bsns_year, reprt_code, fs_div)` | `corp_code` → companies |
| `mezz_balance` | CB·BW·EB 회차별 잔액 | `(corp_code, series, rcept_no)` | `corp_code` → companies |
| `underwritings` | 증권신고서 인수단 (리그테이블) | `(rcept_no, underwriter, role, series)` | – (`rcept_no`로 securities와 논리 연결) |
| `quotes` | 최근 거래일 종가·상장주식수 (KRX) | `stock_code` | – (`stock_code`로 companies와 논리 연결) |
| `filings` | 수집 대상 공시 대기열 | `rcept_no` | – |
| `fetch_log` | 수집 진행 기록 | `task` | – |

---

## companies — 회사

| 컬럼 | 타입 | 설명 |
|---|---|---|
| `corp_code` **PK** | char(8) | DART 고유번호 |
| `corp_name` | text | 회사명 |
| `stock_code` | varchar(6) | 종목코드 (비상장은 null) |
| `corp_cls` | char(1) | Y 유가증권 · K 코스닥 · N 코넥스 · E 기타(비상장) |
| `listed_on` | date | 상장일 (KRX KIND). IPO와 상장사 공모증자 구분에 사용 |
| `updated_at` | timestamptz | 갱신 시각 |

## securities — 증권 (발행 1건 = 1행)

| 컬럼 | 타입 | 설명 |
|---|---|---|
| `id` **PK** | text | 출처별 고유키. `D:`결정공시 접수번호 / `R:`채무증권 신고서:회차 / `S:`지분증권 신고서 / `P:`정기보고서 행 해시 |
| `corp_code` **FK** | char(8) | → companies |
| `sec_type` | varchar(6) | SB · CB · BW · EB · RCPS · EQUITY · IPO · CP · STB |
| `source` | varchar(10) | `decision` 주요사항보고서 · `bond_rs` 채무증권 신고서 · `equity_rs` 지분증권 신고서 · `periodic` 정기보고서 |
| `offering` | varchar(20) | 공모 / 사모 |
| `rcept_no`, `rcept_dt` | varchar(14), date | 원 공시 접수번호·접수일 |
| `name`, `series` | text | 증권 명칭, 회차 |
| `board_date`, `issue_date`, `maturity_date` | date | 이사회 결의일, 발행(납입)일, 만기일 |
| `amount` | numeric | 발행금액(원) |
| `coupon`, `ytm` | numeric | 표면이자율, 만기이자율(%) |
| `conv_price`, `refix_floor` | numeric | 전환·행사·교환가액(유상증자·IPO는 주당 발행가), 리픽싱 최저가 |
| `conv_start`, `conv_end` | date | 전환·행사·교환 청구기간 |
| `underlying`, `shares`, `dilution_pct` | text, numeric | 대상 주식, 주식수, 발행 전 주식총수 대비 % |
| `rating`, `grade` | text | 신용등급 원문, 정규화한 등급(AAA~D, A1~A3) |
| `repaid`, `repaid_asof` | text, date | 상환 / 미상환 / 일부상환 (정기보고서 기준) |
| `method`, `underwriter` | text | 증자·모집 방식, 대표주관사 |
| `dkey` | text | 정정 판별 키 (같은 출처·회사·키면 최신 접수본만 유효) |
| `superseded` | boolean | 정정·중복으로 숨긴 행 |
| `raw` | jsonb | DART 원본 응답 (정기보고서 행은 용량 때문에 비움) |
| `loaded_at` | timestamptz | 적재 시각 |

**잔존 판단**: 채무증권(SB·CB·BW·EB·CP·STB) 중 `maturity_date ≥ 오늘`, `repaid ≠ '상환'`, 메자닌은 최신 잔액(`mezz_balance`) > 0.

## financials — 보고서별 주요 재무

| 컬럼 | 설명 |
|---|---|
| `corp_code` **PK·FK**, `bsns_year` **PK**, `reprt_code` **PK**, `fs_div` **PK** | 회사, 사업연도, 보고서(11013 1분기 · 11012 반기 · 11014 3분기 · 11011 사업), 연결(CFS)/별도(OFS) |
| `base_date`, `rcept_no` | 재무제표 기준일, 보고서 접수번호 |
| `current_assets`, `noncurrent_assets`, `total_assets` | 유동·비유동·자산총계 |
| `current_liab`, `noncurrent_liab`, `total_liab` | 유동·비유동·부채총계 |
| `capital`, `retained`, `total_equity` | 자본금, 이익잉여금, 자본총계 |
| `revenue`, `op_income`, `pretax_income`, `net_income` | 매출, 영업이익, 세전이익, 순이익 (분기는 연초부터 누적) |

## statements — 전체 재무제표 캐시

| 컬럼 | 설명 |
|---|---|
| `corp_code` **PK·FK**, `bsns_year` **PK**, `reprt_code` **PK**, `fs_div` **PK** | financials와 같은 키 |
| `data` | jsonb. DART 단일회사 전체 재무제표 응답 (계정별 당기·전기·전전기) |
| `fetched_at` | 받은 시각. 화면에서 처음 요청할 때 DART에서 받아 저장 |

## mezz_balance — CB·BW·EB 회차별 잔액

| 컬럼 | 설명 |
|---|---|
| `corp_code` **PK·FK**, `series` **PK**, `rcept_no` **PK** | 회사, 회차, 근거 공시 |
| `rcept_dt` | 공시일 (최신값 판단 기준) |
| `kind` | `EXERCISE` 전환·행사·교환 청구 / `REFIX` 전환가액 조정 / `REDEEM` 만기전 사채취득 |
| `remaining` | 신고일 현재 미전환·미상환 잔액(원) |
| `conv_price`, `shares` | 현재 전환가, 남은 전환 가능 주식수 |

## underwritings — 인수단 (리그테이블)

| 컬럼 | 설명 |
|---|---|
| `rcept_no` **PK**, `underwriter` **PK**, `role` **PK**, `series` **PK** | 증권신고서, 증권사, 역할(대표/인수), 회차 또는 주식 종류 |
| `corp_code` | 발행회사 |
| `amount` | 인수금액(원) |
| `fee_text`, `fee_rate` | 인수대가 원문, 읽을 수 있을 때 수수료율(%) |
| `method` | 총액인수 / 잔액인수 / 모집주선 |

## quotes — 주가 (KRX Open API)

| 컬럼 | 설명 |
|---|---|
| `stock_code` **PK** | 종목코드 |
| `name`, `market` | 종목명, KOSPI/KOSDAQ |
| `bas_dd`, `close`, `mktcap`, `list_shrs` | 기준일, 종가, 시가총액, 상장주식수 |

## filings — 수집 대기열

| 컬럼 | 설명 |
|---|---|
| `rcept_no` **PK** | 공시 접수번호 |
| `corp_code`, `corp_name`, `corp_cls`, `stock_code`, `report_nm`, `rcept_dt` | 공시 목록 정보 |
| `kind` | CB·BW·EB·EQUITY(결정) / BOND_RS·EQUITY_RS(신고서) / ANNUAL·HALF·Q1·Q3(정기) / EXERCISE·REFIX·REDEEM(메자닌 잔액) |
| `status`, `fin_status` | `pending`이면 다음 실행에서 처리 |

## fetch_log — 수집 진행 기록

| 컬럼 | 설명 |
|---|---|
| `task` **PK** | 예: `list:B:20250101:20250331`, `rcps:<접수번호>`, `ilist:<회사>` |
| `status`, `fetched_at` | done 등, 처리 시각 |
