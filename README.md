# fundflow

상장사 자금조달 공시(전환사채·신주인수권부사채·교환사채·유상증자)를 금융감독원 DART OpenAPI로 수집하고,
**각 발행이 회사의 자기자본·부채비율을 어떻게 바꾸는지** 보여주는 서비스입니다.

## 서비스 아키텍처

```
DART OpenAPI ──(collector, Python)──▶ Supabase PostgreSQL ──▶ FastAPI (Render) ──▶ 프론트엔드 (Vercel)
 공시·재무제표          수집·정제·적재            companies             /api/*  /docs          슬라이드형 대시보드
                                                funding_events
                                                financials
```

| 구분 | 기술 | 배포 | 위치 |
|---|---|---|---|
| 데이터 수집 | Python, requests, pandas | 로컬 실행 | `collector/` |
| DB | PostgreSQL | Supabase | `supabase/migrations/` |
| 백엔드 | FastAPI | Render | `backend/` |
| 프론트엔드 | HTML·CSS·JavaScript | Vercel | `frontend/` |

문서: [API 설명](docs/API.md) · [DB 테이블](docs/DB.md)

## 사용 데이터와 출처
- 제공 기관: 금융감독원 · 출처: DART OpenAPI <https://opendart.fss.or.kr>
- 사용 API: 공시검색(`list`), 전환사채권 발행결정(`cvbdIsDecsn`), 신주인수권부사채권 발행결정(`bdwtIsDecsn`),
  교환사채권 발행결정(`exbdIsDecsn`), 유상증자 결정(`piicDecsn`), 단일회사 주요계정(`fnlttSinglAcnt`), 고유번호(`corpCode`)

## 실행 방법

### 1. 환경변수 (`.env`, 저장소 루트)
```
DART_API_KEY=발급받은_40자리_키
DATABASE_URL=postgresql://postgres.xxxx:비밀번호@aws-0-ap-northeast-2.pooler.supabase.com:5432/postgres
```
`DATABASE_URL`은 Supabase 대시보드 > Connect > **Session pooler** 문자열을 씁니다 (Render·로컬 모두 IPv4로 접속 가능).

### 2. DB 테이블 생성
Supabase 프로젝트가 GitHub 저장소와 연동되어 있어 `main`에 병합된 `supabase/migrations/*.sql`이 운영 DB에 자동 적용됩니다.
(연동 없이 쓸 때는 Supabase SQL Editor에서 해당 파일을 실행)

### 3. 데이터 수집·적재 (저장소 루트에서)
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python collector/dart_funding.py
python collector/load_db.py
```

### 4. 백엔드 로컬 실행
```bash
pip install -r backend/requirements.txt
cd backend && uvicorn app.main:app --reload     # http://localhost:8000/docs
```

### 5. 프론트엔드 로컬 실행
`frontend/config.js`의 `FUNDFLOW_API`를 백엔드 주소로 맞춘 뒤
```bash
cd frontend && python -m http.server 5500       # http://localhost:5500
```

## 배포
- **Render**: New > Blueprint > 이 저장소 선택 (`render.yaml` 사용). 환경변수 `DATABASE_URL` 입력.
  배포 후 `https://<서비스>.onrender.com/docs`가 Swagger UI 주소입니다.
- **Vercel**: New Project > 이 저장소, Root Directory를 `frontend`로 지정. `config.js`에 Render 주소 입력 후 배포.
- 배포 후 Render 환경변수 `CORS_ORIGINS`를 Vercel 주소로 바꾸면 다른 사이트의 호출을 막을 수 있습니다.

## 계산 가정
- 발행금액: 사채는 권면총액, 유상증자는 자금조달 목적별 금액 합계
- 정정공시: 같은 회사·유형·이사회결의일(유상증자는 신주 수)이면 마지막 접수본만 유효
- 발행 직전 재무제표: 공시일 이전에 공시 기한이 지난 가장 최근 보고서(연결 우선)
- 제외: 발행비용, 파생상품부채 분리, 이자비용, 발행 이후 실적 변화 — 비율은 방향과 규모를 보는 추정치
