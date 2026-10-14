# fundflow API 설명 문서

- **기술**: FastAPI (Python 3.12) · **배포**: Render
- **Base URL**: `https://fundflow-api-kr3i.onrender.com`
- **Swagger UI**: https://fundflow-api-kr3i.onrender.com/docs · **ReDoc**: https://fundflow-api-kr3i.onrender.com/redoc
- **요청 방식**: 모든 API는 **GET**, 응답은 **JSON**. 인증 없음(공개 조회 전용).
- **단위**: 금액 원(KRW), 날짜 `YYYY-MM-DD`, 연월 `YYYY-MM`(또는 `2025`, `202501`, `2025.01`도 허용).
- **유형 코드**: `SB` 회사채 · `CB` 전환사채 · `BW` 신주인수권부사채 · `EB` 교환사채 · `RCPS` 상환전환우선주 · `EQUITY` 유상증자 · `IPO` · `CP` 기업어음 · `STB` 단기사채
- 정정공시로 대체됐거나 출처 간 중복인 행은 자동으로 제외합니다.
- 무료 서버라 한동안 요청이 없으면 잠들고, 첫 요청에 30~60초가 걸릴 수 있습니다.

## API 목록

| 구분 | 메서드·경로 | 기능 | 주요 입력값 |
|---|---|---|---|
| meta | `GET /health` | 서버·DB 상태 | – |
| meta | `GET /api/meta` | 유형 목록, 데이터 범위, 최근 적재 시각, 남은 수집 대기 | – |
| meta | `GET /api/sources` | 사용 데이터와 출처 | – |
| macro | `GET /api/macro` | 연도별·월별 × 유형별 발행금액·건수 (신종자본 포함 금액) | `unit`, `types`, `start`, `end`, `fin` |
| macro | `GET /api/maturities` | 잔존 채무증권 만기 분포 | `types`, `fin` |
| macro | `GET /api/league` | 주관사 리그테이블 | `category`, `year`, `quarter`, `start`, `end`, `basis`, `grade`, `fin` |
| macro | `GET /api/league/deals` | 주관사별 딜 목록 | `category`, `underwriter`, 기간, `grade`, `fin` |
| monitor | `GET /api/securities` | 증권별 발행 조건 목록 (만기 Monitor) | 아래 표 |
| monitor | `GET /api/securities/{id}/benchmark` | 발행조건 벤치마크 (비슷한 증권과 비교) | `window_days` |
| monitor | `GET /api/overhang` | 메자닌(CB·BW·EB) 잠재 물량 | `types`, `window`, `itm`, `market`, `q`, `sort`, `limit` |
| company | `GET /api/companies` | 회사 검색 | `q`(필수), `limit` |
| company | `GET /api/companies/{corp_code}` | 회사 정보와 유형별 발행 합계 | – |
| company | `GET /api/companies/{corp_code}/financials` | 요약 재무와 재무지표 추이 | – |
| company | `GET /api/companies/{corp_code}/statements/compare` | 최근 분·반기(+전년동기) + 직전 3개년 재무제표 | `fs_div` |
| company | `GET /api/companies/{corp_code}/statements` | 보고서 하나의 전체 재무제표 | `bsns_year`, `reprt_code`, `fs_div` |
| company | `GET /api/companies/{corp_code}/overhang` | 회사별 전 회차 메자닌 잔액과 잠재 오버행 | – |

### 공통 입력값

| 이름 | 타입 | 설명 |
|---|---|---|
| `types` | 쉼표 구분 문자열 | 유형 코드 (예: `SB,CB,BW`). 생략하면 전체 |
| `fin` | `exclude` \| `include` \| `only` | 금융회사(은행·금융지주·증권·카드·캐피탈·보험 등) 발행분 처리. 대부분 기본 `exclude` |
| `start`, `end` | 연월 | 기간 시작·끝 (끝 연월 포함) |
| `corp_code` | 문자열 8자리 | DART 고유번호 |

---

## meta

### GET /health
```json
{ "status": "ok", "securities": 278088, "latest_rcept_dt": null }
```

### GET /api/meta
```json
{ "types": [{ "code": "CB", "label": "전환사채", "debt": true }],
  "first_issue": "2020-01-02", "last_issue": "2026-10-14",
  "last_loaded": "2026-10-14 21:48", "pending_filings": 0 }
```

### GET /api/sources
사용한 DART·KRX API 이름과 용도 목록.

---

## macro

### GET /api/macro
| 입력값 | 기본값 | 설명 |
|---|---|---|
| `unit` | `year` | `year` 연도별 / `month` 월별 |
| `start`, `end` | – | 연월 범위 (2020년 이후 발행분만 집계) |

```json
[{ "period": "2025", "sec_type": "CB", "amount": 6200000000000, "count": 403, "companies": 371,
   "hybrid_amount": 120000000000, "hybrid_count": 4 }]
```
`hybrid_*`: 그중 신종자본증권(영구채·조건부자본증권, 또는 만기 30년 이상).

### GET /api/maturities
오늘 기준 잔존 채무증권을 `0-3m`, `3-6m`, `6-12m`, `1-2y`, `2-3y`, `3y+` 구간으로 나눈 금액·건수.

### GET /api/league
| 입력값 | 기본값 | 설명 |
|---|---|---|
| `category` | `bond` | `bond` 공모 회사채 / `equity` 공모 유상증자 / `ipo` IPO |
| `year`, `quarter` | – | 연도, 분기(1~4). 분기는 연도와 함께 |
| `start`, `end` | – | 직접 지정 기간 (연도·분기보다 우선) |
| `basis` | `lead` | `lead` 대표주관 금액 기준(공동 대표주관은 균등 배분) / `uw` 인수 금액 기준(인수단 포함) |
| `grade` | – | 회사채 등급 구간 `AA`(AA 이상) / `A` / `BBB`(BBB 이하) |

```json
{ "category": "ipo", "period": "2025", "basis": "lead", "total_amount": 5230000000000, "total_deals": 100,
  "rows": [{ "rank": 1, "underwriter": "미래에셋증권", "lead_amount": 935300000000, "deals": 21,
             "share": 17.87, "underwritten": 924200000000, "fee_rate": 2.367, "prev_rank": 4 }] }
```
`prev_rank`: 전년 같은 기간의 순위 (분기 선택 시 전년 같은 분기).

### GET /api/league/deals
선택한 증권사가 주관·인수한 딜 목록 (일자, 회사, 금액, 등급, 조건, 대표주관사, 공시 원문 링크).

---

## monitor

### GET /api/securities
| 입력값 | 기본값 | 설명 |
|---|---|---|
| `status` | `outstanding` | `outstanding` 만기 전·미상환 채무증권만 (전량 전환·상환된 메자닌 제외) / `all` |
| `offering` | – | `공모` / `사모` |
| `q` | – | 회사명 일부 또는 종목코드 |
| `issue_from`, `issue_to` | – | 발행 연월 범위 |
| `maturity_from`, `maturity_to` | – | 만기 연월 범위 |
| `hybrid` | – | `only` 신종자본증권만 / `exclude` 제외 |
| `sort` | `maturity` | `maturity` 만기 임박 · `issue` 최근 발행 · `amount` · `coupon` |
| `limit`, `offset` | 50, 0 | 최대 500 |

```json
{ "total": 1796, "total_amount": 46280000000000,
  "items": [{ "id": "D:20250312000123", "corp_name": "OO", "sec_type": "CB", "offering": "사모",
    "series": "5", "issue_date": "2025-03-20", "amount": 10000000000, "remaining": 2000000000,
    "balance_asof": "2026-05-02", "coupon": 0.0, "ytm": 3.0, "maturity_date": "2028-03-20",
    "days_left": 523, "conv_price": 5120, "refix_floor": 3584, "rating": null, "grade": null,
    "hybrid": false, "repaid": null, "dart_url": "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=..." }] }
```
`remaining`: 메자닌의 최신 미전환·미상환 잔액(행사·조정·만기전취득 공시 기준). `grade`: 신용등급 원문(`rating`)에서 뽑은 등급.

### GET /api/securities/{id}/benchmark
같은 시기(기본 발행일 ±180일)의 비슷한 증권과 비교합니다.
- 회사채: 같은 등급·비슷한 만기 → 표면금리, 만기, 발행금액
- CB·BW·EB: 같은 유형·공모/사모 → 표면·만기이자율, 리픽싱 하한/전환가, 만기, 발행금액
- 유상증자·RCPS: 같은 증자 방식 → 발행금액, 희석률
```json
{ "basis": "전환사채 · 사모 · 금융회사 제외 · 발행일 ±180일", "n": 372,
  "metrics": [{ "key": "coupon", "label": "표면이자율", "unit": "%", "value": 3.0, "n": 366,
                "p10": 0.0, "p25": 0.0, "p50": 0.0, "p75": 2.0, "p90": 4.0, "percentile": 86.7 }],
  "peers": [{ "corp_name": "세종메디칼", "issue_date": "2025-03-26", "coupon": 0.0, "tenor": 2.0 }] }
```

### GET /api/overhang
잔존 CB·BW·EB를 최근 거래일 주가(KRX)와 비교합니다. EB는 교환 대상 회사의 주가를 씁니다.

| 입력값 | 기본값 | 설명 |
|---|---|---|
| `window` | `all` | `open` 지금 청구 가능 / `1m`·`3m`·`6m`·`12m` 그 기간 안에 청구 시작 |
| `itm` | `false` | `true`면 종가 ≥ 전환가만 |
| `market` | – | `KOSPI` / `KOSDAQ` |
| `sort` | `start` | `start` 청구 시작 임박 · `dilution` · `moneyness` · `value` |

```json
{ "as_of": "2026-10-13", "total": 1549, "total_value": 25900000000000, "itm_count": 406,
  "upcoming_3m_value": 2592800000000,
  "items": [{ "corp_name": "OO", "sec_type": "CB", "series": "11", "remaining": 2300000000,
              "balance_source": "공시", "conv_price_now": 3304, "close": 4150, "moneyness": 125.6,
              "shares": 696125, "dilution": 3.3, "status": "청구 가능", "days_to_start": 0, "warn": null }],
  "companies": [{ "corp_name": "OO", "count": 3, "shares": 2100000, "dilution": 9.8, "next_start": "2026-11-02" }] }
```
`moneyness`: 종가 ÷ 현재 전환가 × 100 (100 이상이면 전환 시 이익). `dilution`: 남은 전환 가능 주식수 ÷ 현재 상장주식수 (%). `warn`: 주식 병합 등으로 수치가 비정상적일 때 사유.

---

## company

### GET /api/companies?q=삼성
자금조달 공시가 있는 회사 중 이름·종목코드로 검색 (잔존 금액이 큰 순).

### GET /api/companies/{corp_code}
```json
{ "corp_code": "00164779", "corp_name": "SK하이닉스", "stock_code": "000660", "corp_cls": "Y",
  "totals": [{ "sec_type": "EQUITY", "amount": 40023070290000, "count": 1, "outstanding": 0 }] }
```

### GET /api/companies/{corp_code}/financials
보고서별(최신순) 자산·부채·자본·매출·영업이익·순이익과 부채비율·자기자본비율·유동비율·영업이익률. 연결 우선. 아직 수집되지 않은 회사는 처음 요청할 때 DART에서 받아 저장합니다.

### GET /api/companies/{corp_code}/statements/compare
```json
{ "basis": "2026년 반기보고서 + 2025년 사업보고서", "fs_div": "CFS",
  "sections": [{ "sj_div": "IS", "sj_nm": "손익계산서",
    "columns": ["2026 반기 누적", "2025 반기 누적 (전년동기)", "2025 연간", "2024 연간", "2023 연간"],
    "lines": [{ "account_nm": "영업이익", "values": [98152900000000, 16653400000000, 47206300000000, 23467300000000, -7730300000000] }] }] }
```

### GET /api/companies/{corp_code}/overhang
그 회사가 발행한 CB·BW·EB 전 회차: 발행액, 전환·상환으로 줄어든 금액, 최신 잔액, 최초·현재 전환가, 남은 주식수, 희석률, 상태(잔존/전량 전환·상환/만기 경과 등). 합계는 이 회사 주식으로 바뀌는 잔존분만 더합니다(타사주 EB 제외).

---

## 오류

| 코드 | 상황 |
|---|---|
| 404 | 회사·증권·재무제표 없음 |
| 422 | 입력값 형식 오류 (예: `types=XX`, 연월 형식) |
| 502 / 503 | DART 응답 오류 / 서버에 DART 키 없음 |
