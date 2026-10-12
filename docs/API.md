# fundflow API 설명 문서

- 기술: FastAPI (Python) · 배포: Render
- Base URL: `https://fundflow-api-scjl.onrender.com`
- Swagger UI: https://fundflow-api-scjl.onrender.com/docs · ReDoc: https://fundflow-api-scjl.onrender.com/redoc
- 모든 API는 **GET** 요청이고 JSON으로 응답합니다. 인증은 없습니다(공개 조회 전용).
- 금액 단위는 원(KRW), 날짜는 `YYYY-MM-DD`. 정정공시로 대체된 원공시는 기본적으로 제외합니다.

## 요약

| 기능 | 메서드·경로 | 주요 입력값 |
|---|---|---|
| 서버·DB 상태 | `GET /health` | – |
| 사용 데이터와 출처 | `GET /api/sources` | – |
| 발행 유형별 요약 | `GET /api/summary` | `start`, `end` |
| 월별 발행 추이 | `GET /api/stats/monthly` | `start`, `end` |
| 유형별 상위 회사 + 재무 영향 | `GET /api/rankings` | `ftype`(필수), `limit`, `start`, `end` |
| 회사 한 곳의 발행 전후 재무비율 | `GET /api/companies/{corp_code}/impact` | `ftype`(필수), `start`, `end` |
| 공시 이벤트 목록 | `GET /api/events` | `ftype`, `corp_code`, `start`, `end`, `include_superseded`, `limit`, `offset` |
| 회사 정보 | `GET /api/companies/{corp_code}` | – |

공통 입력값

| 이름 | 위치 | 타입 | 설명 |
|---|---|---|---|
| `ftype` | query | `CB` \| `BW` \| `EB` \| `Equity` | 전환사채 / 신주인수권부사채 / 교환사채 / 유상증자 |
| `start`, `end` | query | date | 공시 접수일 기준 조회 기간(양 끝 포함). 생략하면 전체 기간 |
| `corp_code` | path·query | string(8) | DART 고유번호 |

---

## GET /health
```json
{ "status": "ok", "events": 1523, "latest_rcept_dt": "2026-10-10" }
```

## GET /api/sources
사용한 DART OpenAPI 목록과 활용 항목.
```json
[{ "name": "전환사채권 발행결정", "api": "cvbdIsDecsn", "provider": "금융감독원 DART",
   "url": "https://opendart.fss.or.kr/guide/main.do", "fields": "권면총액, 전환가액, ..." }]
```

## GET /api/summary
유형별 발행금액 합계, 건수, 회사 수, 평균 발행금액, 평균 희석률. 데이터가 없는 유형도 0으로 반환합니다.
```json
[{ "ftype": "CB", "label": "전환사채", "total_amount": 6793500000000, "events": 30,
   "companies": 12, "avg_amount": 226450000000, "avg_dilution_pct": 8.43,
   "first_dt": "2025-01-12", "last_dt": "2026-06-15" }]
```

## GET /api/stats/monthly
월 × 유형별 발행금액·건수.
```json
[{ "month": "2025-03", "ftype": "CB", "total_amount": 635600000000, "events": 4 }]
```

## GET /api/rankings?ftype=CB&limit=5
회사별로 같은 유형의 발행금액을 합산해 상위 N개사를 반환합니다. 각 회사의 **최대 규모 발행 직전에 공시된 재무제표**(연결 우선)를 기준으로 발행 전후 재무비율을 계산합니다.

| 응답 필드 | 설명 |
|---|---|
| `rank`, `corp_code`, `corp_name`, `stock_code` | 순위와 회사 |
| `total_amount`, `events` | 기간 내 발행금액 합계, 건수 |
| `dilution_pct` | 희석률 합계(발행 전 주식총수 대비 신주 %) |
| `main_rcept_no`, `last_rcept_dt` | 최대 규모 공시 접수번호, 최근 공시일 |
| `amount_to_equity_pct` | 발행금액 ÷ 자기자본 × 100. 자본잠식이면 `null` |
| `base` | 기준 재무제표(보고서명, 연결/별도, 기준일, 자산·부채·자본총계). 없으면 `null` |
| `scenarios[]` | 시점별 자산·부채·자본과 `debt_ratio`(부채/자본 %), `equity_ratio`(자본/자산 %) |

시나리오 계산 (X = 발행금액, 조달 현금은 자산으로 유입)

| 유형 | 시점 | 자산 | 부채 | 자본 |
|---|---|---|---|---|
| CB | 발행 직후 → 전액 전환 후 | +X → +X | +X → 0 | 0 → +X |
| BW | 발행 직후 → 전액 행사 후 | +X → +2X | +X → +X | 0 → +X |
| EB | 발행 직후 → 전액 교환 후 | +X → +X | +X → 0 | 0 → +X |
| 유상증자 | 증자 후 | +X | 0 | +X |

```json
[{ "rank": 1, "corp_code": "00126380", "corp_name": "OO전자", "total_amount": 119110000000,
   "events": 3, "amount_to_equity_pct": 37.11,
   "base": { "report": "2025년 1분기보고서", "fs_div": "연결", "base_date": "2025-03-31",
             "total_assets": 5350553792723, "total_liabilities": 2140653792723, "total_equity": 3209900000000 },
   "scenarios": [
     { "label": "발행 전", "debt_ratio": 66.69, "equity_ratio": 59.99, "...": "..." },
     { "label": "발행 직후", "debt_ratio": 103.8, "equity_ratio": 49.07, "...": "..." },
     { "label": "전액 전환 후", "debt_ratio": 48.64, "equity_ratio": 67.28, "...": "..." }] }]
```

## GET /api/companies/{corp_code}/impact?ftype=CB
`/api/rankings` 한 행과 같은 계산을 특정 회사에 대해 수행합니다. 해당 회사·유형 공시가 없으면 `404`.

## GET /api/events
공시 이벤트 원천 목록(최신순). `dart_url`로 공시 원문에 연결됩니다.

| 입력값 | 기본값 | 설명 |
|---|---|---|
| `include_superseded` | `false` | 정정으로 대체된 원공시 포함 여부 |
| `limit` / `offset` | 50 / 0 | 페이지 크기(최대 500) / 시작 위치 |

```json
[{ "rcept_no": "20260821000123", "corp_code": "00123456", "corp_name": "OO", "ftype": "BW",
   "rcept_dt": "2026-08-21", "board_date": "2026-08-20", "amount": 354000000000,
   "dilution_pct": 6.57, "exercise_price": 89000, "coupon_rate": 0.0, "ytm_rate": 3.0,
   "maturity_date": "2029-08-21", "method": null, "superseded": false,
   "dart_url": "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260821000123" }]
```

## GET /api/companies/{corp_code}
```json
{ "corp_code": "00123456", "corp_name": "OO", "stock_code": "123456", "corp_cls": "K",
  "totals": [{ "ftype": "BW", "total_amount": 797000000000, "events": 4 }] }
```

## 오류
| 코드 | 상황 |
|---|---|
| 404 | 회사 또는 해당 유형 공시 없음 |
| 422 | 입력값 형식 오류 (예: `ftype=XX`, 날짜 형식) |
