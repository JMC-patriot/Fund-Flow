# fundflow DB 테이블

- DBMS: PostgreSQL (Supabase) · 스키마: [`supabase/migrations/20261012130000_fundflow_v2.sql`](../supabase/migrations/20261012130000_fundflow_v2.sql)
- 적재: `collector/run.py` (upsert, 재실행해도 중복 없음)

```
filings (공시 대기열) ──수집──▶ securities (증권) ──┐
                                                   ├── companies
                     financials / statements ──────┘
fetch_log: 이미 끝낸 목록 구간·원문 확인 기록
```

## securities — 증권 발행 1건 = 1행

| 컬럼 | 설명 |
|---|---|
| `id` | 출처별 고유키. `D:`결정공시 접수번호, `R:`채무증권 신고서 접수번호:회차, `S:`지분증권 신고서, `P:`정기보고서 행 해시 |
| `sec_type` | SB 회사채 · CB · BW · EB · RCPS · EQUITY 유상증자 · IPO · CP 기업어음 · STB 단기사채 |
| `source` | `decision` 주요사항보고서 · `bond_rs` 채무증권 신고서 · `equity_rs` 지분증권 신고서 · `periodic` 정기보고서 발행실적 |
| `offering` | 공모 / 사모 |
| `rcept_no`, `rcept_dt` | 원 공시 접수번호, 접수일 |
| `name`, `series` | 증권 명칭, 회차 |
| `board_date`, `issue_date`, `maturity_date` | 이사회 결의일, 발행(납입)일, 만기일 |
| `amount` | 발행금액(원) |
| `coupon`, `ytm` | 표면이자율, 만기이자율(%) |
| `conv_price`, `refix_floor` | 전환·행사·교환가액 (유상증자·IPO는 주당 발행가), 리픽싱 최저 조정가액 |
| `conv_start`, `conv_end`, `underlying`, `shares`, `dilution_pct` | 청구기간, 대상 주식, 주식수, 발행 전 주식총수 대비 % |
| `rating` | 신용등급(평가기관) — 정기보고서 |
| `repaid`, `repaid_asof` | 상환 / 미상환 / 일부상환, 기준일 — 정기보고서 |
| `method`, `underwriter` | 증자·모집 방식, 대표 주관사 |
| `dkey` | 정정 판별 키. 같은 출처·회사·키면 최신 접수본만 유효 |
| `superseded` | 정정으로 대체됐거나 다른 출처와 중복이라 숨긴 행 |
| `raw` | DART 원본 응답 |

**잔존 판단**: 채무증권(SB·CB·BW·EB·CP·STB) 중 `maturity_date >= 오늘`이고 `repaid <> '상환'`.

## financials — 보고서별 주요 재무

PK `(corp_code, bsns_year, reprt_code, fs_div)`. `reprt_code`: 11013 1분기 · 11012 반기 · 11014 3분기 · 11011 사업.
자산·유동자산·비유동자산·부채·유동부채·비유동부채·자본금·이익잉여금·자본, 매출·영업이익·세전이익·순이익(분기는 연초부터 누적).

## statements — 전체 재무제표 캐시

화면에서 처음 요청할 때 DART `fnlttSinglAcntAll`로 받아 `data`(jsonb)에 저장합니다.

## companies

`corp_code`(DART 고유번호), `corp_name`, `stock_code`(비상장은 null), `corp_cls`(Y 유가 · K 코스닥 · N 코넥스 · E 기타).

## filings — 수집 대기열

공시 목록에서 처리 대상만 저장합니다. `kind`: CB·BW·EB·EQUITY(결정), BOND_RS·EQUITY_RS(신고서), ANNUAL·HALF·Q1·Q3(정기보고서).
`status`(증권 수집), `fin_status`(재무 수집)가 `pending`이면 다음 실행에서 처리합니다.
