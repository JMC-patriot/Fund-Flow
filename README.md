# fundflow

DART에 공시된 회사들의 자금조달 증권(회사채 SB·CB·BW·EB·RCPS·유상증자·IPO·CP·단기사채)을 **2020년부터 매일** 수집해서
발행 Macro 지표, 만기 임박 순 발행 조건 Monitor, 발행사 재무와 발행 시뮬레이션을 보여주는 대시보드입니다.

## 화면

| 탭 | 내용 |
|---|---|
| 개요 | 연도별·월별 × 증권 종류별 발행금액과 건수, 잔존 채무증권 만기 분포 |
| 만기 Monitor | 전 종목 증권별 발행 조건(Coupon·YTM·만기·전환/교환가액·리픽싱 하한·신용등급·공모/사모). 기본은 잔존 증권을 만기 임박 순으로 보여주고, 6개월 이내는 강조. 발행·만기 연월 검색, CSV |
| 회사 상세 | 잔존 증권, 요약 재무·재무지표 추이, 전체 재무제표(BS·IS·CF), 발행 시뮬레이션(금액·금리·전환비율·자금 용도를 직접 입력) |

## 아키텍처

```
DART OpenAPI ──▶ collector (GitHub Actions, 매일 04:00) ──▶ Supabase PostgreSQL ──▶ FastAPI (Render) ──▶ 화면 (Vercel)
```

| 구분 | 위치 | 배포 |
|---|---|---|
| 수집기 | `collector/` | GitHub Actions `.github/workflows/daily-collect.yml` |
| DB | `supabase/migrations/` | Supabase |
| API | `backend/` | Render (`render.yaml`) |
| 화면 | `frontend/` | Vercel |

문서: [API](docs/API.md) · [DB](docs/DB.md)

## 데이터 출처 (금융감독원 DART OpenAPI)

| 증권 | 출처 | 비고 |
|---|---|---|
| CB·BW·EB | 주요사항보고서 발행결정 | 공모·사모, 금리, 만기, 전환·행사·교환가액, 리픽싱 하한 |
| 유상증자·RCPS | 유상증자 결정 + 공시 원문 | 종류주식 발행은 원문에서 상환전환우선주 여부 판별 |
| 회사채·CP (공모) | 증권신고서(채무증권) | 공시 당일 반영. 금리·등급은 신고서 API에 없음 |
| 회사채·CP·단기사채 (공모·사모) | 정기보고서 채무증권 발행실적 | 금리, 신용등급, 상환 여부. 사업·분기보고서 제출 시 반영 |
| IPO | 증권신고서(지분증권), 비상장사 | 공모가, 공모금액 |
| 재무 | 다중회사 주요계정, 단일회사 전체 재무제표 | 전체 재무제표는 화면에서 요청할 때 받아 저장 |

## 수집 방식

- `python collector/run.py`가 초기 적재와 매일 업데이트를 모두 처리합니다. 공시 목록을 `filings` 대기열에 쌓고, 처리한 것은 다시 호출하지 않습니다.
- DART 일일 한도(2만 회) 때문에 한 번에 최대 18,000회만 호출하고 멈춥니다. 다음 실행이 이어받습니다.
  2020년 이후 초기 적재는 하루 1회 실행 기준 2~3일 걸립니다. 서두르려면 Actions 탭에서 `daily-collect`를 수동 실행하세요(하루 한도 안에서).
- 정정공시는 같은 회차·금액 기준 최신 접수본만, 정기보고서와 공시에 같은 발행이 있으면 공시 행에 등급·상환 여부를 합칩니다.

## 로컬 실행

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r backend/requirements.txt
# .env (저장소 루트)
#   DART_API_KEY=...
#   DATABASE_URL=postgresql://...   (Supabase > Connect > Session pooler)
python collector/run.py --budget 2000          # 수집 (예산을 줄여 시험)
cd backend && uvicorn app.main:app --reload    # http://localhost:8000/docs
cd frontend && python -m http.server 5500      # config.js의 FUNDFLOW_API를 백엔드 주소로
```

## 배포

1. **Supabase**: SQL Editor에서 `supabase/migrations/20261012130000_fundflow_v2.sql` 실행 (또는 GitHub 연동으로 자동 적용).
2. **GitHub**: 저장소에 push → Settings > Secrets and variables > Actions에 `DART_API_KEY`, `DATABASE_URL` 등록 → Actions 탭에서 `daily-collect` 수동 실행.
3. **Render**: New > Blueprint > 저장소 선택. 환경변수 `DATABASE_URL`, `DART_API_KEY` 입력.
4. **Vercel**: New Project > 저장소, Root Directory `frontend`. `frontend/config.js`에 Render 주소를 넣고 배포.
5. Render의 `CORS_ORIGINS`를 Vercel 주소로 바꾸면 다른 사이트의 호출을 막을 수 있습니다.

## 한계

- 2020년 이전 발행분 중 아직 잔존한 증권은 빠질 수 있습니다.
- 공모 회사채의 금리·신용등급과 사모 회사채·CP는 정기보고서 기반이라 최대 한 분기 늦게 반영됩니다.
- 상환 여부는 발행 연도 정기보고서 기준이어서, 이후 조기상환·전환은 반영되지 않을 수 있습니다. 만기 Monitor는 만기일 기준으로 잔존을 판단합니다.
- 시뮬레이션은 발행비용·파생상품부채 분리·이후 실적을 제외한 단순 추정입니다.
