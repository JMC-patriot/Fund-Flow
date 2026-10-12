# fundflow API

- FastAPI · Swagger UI `/docs` · ReDoc `/redoc`
- 모두 **GET**, JSON 응답, 인증 없음. 금액은 원(KRW), 날짜 `YYYY-MM-DD`, 연월 `YYYY-MM`.
- 유형 코드: `SB` 회사채 · `CB` 전환사채 · `BW` 신주인수권부사채 · `EB` 교환사채 · `RCPS` 상환전환우선주 · `EQUITY` 유상증자 · `IPO` · `CP` 기업어음 · `STB` 단기사채
- 정정으로 대체됐거나 출처 간 중복인 행은 제외합니다.

| 기능 | 경로 | 주요 입력값 |
|---|---|---|
| 서버·DB 상태 | `GET /health` | – |
| 유형 목록·데이터 범위·수집 진행 | `GET /api/meta` | – |
| 사용 데이터와 출처 | `GET /api/sources` | – |
| 연도별·월별 발행 지표 | `GET /api/macro` | `unit`(year·month), `types`, `start`, `end` |
| 잔존 채무증권 만기 분포 | `GET /api/maturities` | `types` |
| 증권 발행 조건 목록 | `GET /api/securities` | 아래 표 |
| 회사 검색 | `GET /api/companies` | `q`(필수), `limit` |
| 회사 정보·유형별 합계 | `GET /api/companies/{corp_code}` | – |
| 요약 재무·재무지표 추이 | `GET /api/companies/{corp_code}/financials` | – |
| 전체 재무제표 | `GET /api/companies/{corp_code}/statements` | `bsns_year`, `reprt_code`, `fs_div`(CFS·OFS) |

## GET /api/securities

| 입력값 | 기본값 | 설명 |
|---|---|---|
| `types` | 전체 | 쉼표 구분 (예: `SB,CB,BW`) |
| `status` | `outstanding` | `outstanding`: 만기 전·미상환 채무증권만 / `all` |
| `offering` | – | `공모` / `사모` |
| `q`, `corp_code` | – | 회사명 일부·종목코드 / DART 고유번호 |
| `issue_from`, `issue_to` | – | 발행 연월 범위 (양 끝 포함) |
| `maturity_from`, `maturity_to` | – | 만기 연월 범위 |
| `sort` | `maturity` | `maturity` 만기 임박 · `issue` 최근 발행 · `amount` · `coupon` |
| `limit`, `offset` | 50, 0 | 최대 500 |

```json
{ "total": 1832, "total_amount": 51230000000000,
  "items": [{ "id": "D:20250312000123", "corp_code": "00123456", "corp_name": "OO", "stock_code": "123456",
    "corp_cls": "K", "sec_type": "CB", "source": "decision", "offering": "사모", "series": "5",
    "name": "무기명식 이권부 무보증 사모 전환사채", "issue_date": "2025-03-20", "amount": 10000000000,
    "coupon": 0.0, "ytm": 3.0, "maturity_date": "2028-03-20", "days_left": 158,
    "conv_price": 5120, "refix_floor": 3584, "conv_start": "2026-03-20", "conv_end": "2028-02-20",
    "rating": null, "repaid": null, "dart_url": "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=..." }] }
```

## GET /api/macro?unit=month&types=SB,CB
```json
[{ "period": "2025-03", "sec_type": "CB", "amount": 635600000000, "count": 41, "companies": 38 }]
```

## GET /api/maturities
구간: `0-3m`, `3-6m`, `6-12m`, `1-2y`, `2-3y`, `3y+` (오늘 기준 잔존일수).
```json
[{ "bucket": "0-3m", "sec_type": "SB", "amount": 12400000000000, "count": 310 }]
```

## GET /api/companies/{corp_code}/financials
보고서별(최신순) 주요 계정과 `debt_ratio` 부채비율, `equity_ratio` 자기자본비율, `current_ratio` 유동비율, `op_margin` 영업이익률(%). 연결 우선.

## GET /api/companies/{corp_code}/statements?bsns_year=2025&reprt_code=11011&fs_div=CFS
처음 요청 시 DART에서 받아 저장(서버에 `DART_API_KEY` 필요). `lines[]`: `sj_div`(BS·IS·CIS·CF·SCE), `account_nm`, `this`·`prev`·`prev2`(당기·전기·전전기).

## 오류
| 코드 | 상황 |
|---|---|
| 404 | 회사 없음 |
| 422 | 입력값 형식 오류 |
| 502 / 503 | DART 오류 / 서버에 DART 키 없음 |
