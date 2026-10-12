"""
fundflow API — 상장사 자금조달(CB·BW·EB·유상증자) 공시와 재무구조 영향 분석

Swagger UI: /docs   ·   ReDoc: /redoc
"""
import os
from contextlib import asynccontextmanager
from datetime import date
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from .db import pool, fetch_all, fetch_one
from .models import (Source, Summary, MonthlyPoint, Ranking, Impact, Event,
                     Company, Scenario, BaseFinancials, Health)

FType = Literal["CB", "BW", "EB", "Equity"]
TYPE_LABEL = {"CB": "전환사채", "BW": "신주인수권부사채",
              "EB": "교환사채", "Equity": "유상증자"}


@asynccontextmanager
async def lifespan(app):
    pool.open()
    yield
    pool.close()


app = FastAPI(
    title="fundflow API",
    version="1.0.0",
    description=(
        "금융감독원 DART OpenAPI로 수집한 상장사 자금조달 공시(전환사채·신주인수권부사채·"
        "교환사채·유상증자)를 조회하고, 발행이 자기자본·부채비율에 주는 영향을 계산합니다.\n\n"
        "- 금액 단위: 원 (KRW)\n- 날짜 형식: YYYY-MM-DD\n"
        "- 데이터 출처: 금융감독원 전자공시시스템 OpenAPI (https://opendart.fss.or.kr)"),
    lifespan=lifespan,
    openapi_tags=[
        {"name": "meta", "description": "상태 확인·데이터 출처"},
        {"name": "analysis", "description": "요약·추이·순위·재무 영향 분석"},
        {"name": "data", "description": "공시 이벤트·회사 원천 데이터 조회"},
    ],
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "*").split(","),
    allow_methods=["GET"], allow_headers=["*"],
)


# ── 공통 ───────────────────────────────────────────────────────────
def period(start: Optional[date], end: Optional[date]):
    return {"start": start or date(1900, 1, 1), "end": end or date(2999, 12, 31)}


StartQ = Query(None, description="조회 시작일 (공시 접수일 기준, 포함)", examples=["2025-01-01"])
EndQ = Query(None, description="조회 종료일 (포함)", examples=["2026-10-12"])

FIN_LATERAL = """
  left join lateral (
    select f.bsns_year, f.reprt_code, f.fs_div, f.base_date,
           f.total_assets, f.total_liabilities, f.total_equity
    from financials f
    where f.corp_code = b.corp_code and f.available_from <= b.rcept_dt
    order by f.base_date desc, (f.fs_div = 'CFS') desc
    limit 1) f on true"""

REPORT_NM = {"11013": "1분기보고서", "11012": "반기보고서",
             "11014": "3분기보고서", "11011": "사업보고서"}


def scenarios(ftype: str, A: float, L: float, E: float, X: float) -> list[Scenario]:
    """발행금액 X가 재무상태표에 주는 영향 (조달 현금은 자산으로 유입된다고 가정)"""
    rows = [("발행 전", A, L, E)]
    if ftype == "Equity":
        rows.append(("증자 후", A + X, L, E + X))
    else:
        rows.append(("발행 직후", A + X, L + X, E))
        if ftype == "BW":
            rows.append(("전액 행사 후", A + 2 * X, L + X, E + X))
        else:
            rows.append(("전액 전환 후" if ftype == "CB" else "전액 교환 후", A + X, L, E + X))
    return [Scenario(label=n, total_assets=a, total_liabilities=l, total_equity=e,
                     debt_ratio=round(l / e * 100, 2) if e > 0 else None,
                     equity_ratio=round(e / a * 100, 2) if a > 0 else None)
            for n, a, l, e in rows]


def build_impact(r: dict, ftype: str) -> dict:
    base, sc, vs = None, None, None
    if r.get("total_equity") is not None:
        A, L, E = (float(r["total_assets"]), float(r["total_liabilities"]),
                   float(r["total_equity"]))
        base = BaseFinancials(
            report=f'{r["bsns_year"]}년 {REPORT_NM[r["reprt_code"]]}',
            fs_div="연결" if r["fs_div"] == "CFS" else "별도",
            base_date=r["base_date"], total_assets=A, total_liabilities=L, total_equity=E)
        X = float(r["total_amount"])
        sc = scenarios(ftype, A, L, E, X)
        vs = round(X / E * 100, 2) if E > 0 else None
    return {"base": base, "scenarios": sc, "amount_to_equity_pct": vs}


# ── meta ───────────────────────────────────────────────────────────
@app.get("/health", response_model=Health, tags=["meta"], summary="서버·DB 상태")
def health():
    r = fetch_one("select count(*) as n, max(rcept_dt) as latest from funding_events")
    return Health(status="ok", events=r["n"], latest_rcept_dt=r["latest"])


@app.get("/api/sources", response_model=list[Source], tags=["meta"],
         summary="사용 데이터와 출처")
def sources():
    base = "https://opendart.fss.or.kr/guide/main.do"
    return [
        Source(name="전환사채권 발행결정", api="cvbdIsDecsn", provider="금융감독원 DART", url=base,
               fields="권면총액, 전환가액, 표면·만기이자율, 전환주식수 비율"),
        Source(name="신주인수권부사채권 발행결정", api="bdwtIsDecsn", provider="금융감독원 DART", url=base,
               fields="권면총액, 행사가액, 신주 비율"),
        Source(name="교환사채권 발행결정", api="exbdIsDecsn", provider="금융감독원 DART", url=base,
               fields="권면총액, 교환가액, 교환대상 주식 비율"),
        Source(name="유상증자 결정", api="piicDecsn", provider="금융감독원 DART", url=base,
               fields="신주 수, 증자 전 주식총수, 자금조달 목적별 금액, 증자방식"),
        Source(name="공시검색", api="list", provider="금융감독원 DART", url=base,
               fields="주요사항보고서 목록 (대상 회사 선별)"),
        Source(name="단일회사 주요계정", api="fnlttSinglAcnt", provider="금융감독원 DART", url=base,
               fields="자산총계, 부채총계, 자본총계 (연결·별도)"),
        Source(name="고유번호", api="corpCode", provider="금융감독원 DART", url=base,
               fields="회사 고유번호, 회사명, 종목코드"),
    ]


# ── analysis ───────────────────────────────────────────────────────
@app.get("/api/summary", response_model=list[Summary], tags=["analysis"],
         summary="발행 유형별 요약")
def summary(start: Optional[date] = StartQ, end: Optional[date] = EndQ):
    """유형별 발행금액 합계·건수·회사 수·평균 발행금액·평균 희석률."""
    rows = fetch_all("""
        select ftype, sum(amount) as total_amount, count(*) as events,
               count(distinct corp_code) as companies, avg(amount) as avg_amount,
               avg(dilution_pct) as avg_dilution_pct,
               min(rcept_dt) as first_dt, max(rcept_dt) as last_dt
        from funding_events
        where not superseded and rcept_dt between %(start)s and %(end)s
        group by ftype""", period(start, end))
    by = {r["ftype"]: r for r in rows}
    return [Summary(ftype=t, label=TYPE_LABEL[t], **{k: v for k, v in by.get(t, {}).items()
                                                    if k != "ftype"})
            for t in TYPE_LABEL]


@app.get("/api/stats/monthly", response_model=list[MonthlyPoint], tags=["analysis"],
         summary="월별 발행 추이")
def monthly(start: Optional[date] = StartQ, end: Optional[date] = EndQ):
    return fetch_all("""
        select to_char(date_trunc('month', rcept_dt), 'YYYY-MM') as month, ftype,
               sum(amount) as total_amount, count(*) as events
        from funding_events
        where not superseded and rcept_dt between %(start)s and %(end)s
        group by 1, 2 order by 1, 2""", period(start, end))


RANK_SQL = """
    with ev as (
      select * from funding_events
      where not superseded and ftype = %(ftype)s
        and rcept_dt between %(start)s and %(end)s {corp_filter}),
    agg as (
      select corp_code, sum(amount) as total_amount, count(*) as events,
             sum(dilution_pct) as dilution_pct, max(rcept_dt) as last_rcept_dt
      from ev group by corp_code),
    b as (
      select distinct on (corp_code) corp_code, rcept_no, rcept_dt
      from ev order by corp_code, amount desc)
    select a.*, c.corp_name, c.stock_code, b.rcept_no as main_rcept_no, f.*
    from agg a join companies c using (corp_code) join b using (corp_code)
    {fin}
    order by a.total_amount desc
    limit %(limit)s"""


@app.get("/api/rankings", response_model=list[Ranking], tags=["analysis"],
         summary="유형별 발행금액 상위 회사 + 재무 영향")
def rankings(ftype: FType = Query(..., description="발행 유형"),
             limit: int = Query(5, ge=1, le=50, description="상위 N개사"),
             start: Optional[date] = StartQ, end: Optional[date] = EndQ):
    """회사별로 같은 유형의 발행금액을 합산해 순위를 매기고, 각 회사의 **최대 규모 발행 직전에
    공시된 재무제표**를 기준으로 발행 전·후 부채비율과 자기자본비율을 계산합니다."""
    rows = fetch_all(RANK_SQL.format(corp_filter="", fin=FIN_LATERAL),
                     {"ftype": ftype, "limit": limit, **period(start, end)})
    return [Ranking(rank=i, corp_code=r["corp_code"], corp_name=r["corp_name"],
                    stock_code=r["stock_code"], total_amount=r["total_amount"],
                    events=r["events"], dilution_pct=r["dilution_pct"],
                    last_rcept_dt=r["last_rcept_dt"], main_rcept_no=r["main_rcept_no"],
                    **build_impact(r, ftype))
            for i, r in enumerate(rows, 1)]


@app.get("/api/companies/{corp_code}/impact", response_model=Impact, tags=["analysis"],
         summary="회사 한 곳의 발행 전후 재무비율")
def company_impact(corp_code: str, ftype: FType = Query(..., description="발행 유형"),
                   start: Optional[date] = StartQ, end: Optional[date] = EndQ):
    rows = fetch_all(RANK_SQL.format(corp_filter="and corp_code = %(corp_code)s",
                                     fin=FIN_LATERAL),
                     {"ftype": ftype, "limit": 1, "corp_code": corp_code, **period(start, end)})
    if not rows:
        raise HTTPException(404, "해당 회사·유형의 발행 공시가 없습니다")
    r = rows[0]
    return Impact(corp_code=corp_code, corp_name=r["corp_name"], ftype=ftype,
                  total_amount=r["total_amount"], events=r["events"],
                  dilution_pct=r["dilution_pct"], **build_impact(r, ftype))


# ── data ───────────────────────────────────────────────────────────
@app.get("/api/events", response_model=list[Event], tags=["data"], summary="공시 이벤트 목록")
def events(ftype: Optional[FType] = Query(None, description="발행 유형"),
           corp_code: Optional[str] = Query(None, description="DART 고유번호 8자리"),
           start: Optional[date] = StartQ, end: Optional[date] = EndQ,
           include_superseded: bool = Query(False, description="정정으로 대체된 원공시 포함"),
           limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0)):
    return fetch_all("""
        select e.rcept_no, e.corp_code, c.corp_name, e.ftype, e.rcept_dt, e.board_date,
               e.amount, e.dilution_pct, e.exercise_price, e.coupon_rate, e.ytm_rate,
               e.maturity_date, e.method, e.superseded,
               'https://dart.fss.or.kr/dsaf001/main.do?rcpNo=' || e.rcept_no as dart_url
        from funding_events e join companies c using (corp_code)
        where e.rcept_dt between %(start)s and %(end)s
          and (%(ftype)s::text is null or e.ftype = %(ftype)s)
          and (%(corp)s::text is null or e.corp_code = %(corp)s)
          and (%(sup)s or not e.superseded)
        order by e.rcept_dt desc, e.rcept_no desc
        limit %(limit)s offset %(offset)s""",
        {"ftype": ftype, "corp": corp_code, "sup": include_superseded,
         "limit": limit, "offset": offset, **period(start, end)})


@app.get("/api/companies/{corp_code}", response_model=Company, tags=["data"],
         summary="회사 정보와 유형별 발행 합계")
def company(corp_code: str):
    c = fetch_one("select corp_code, corp_name, stock_code, corp_cls from companies "
                  "where corp_code = %(c)s", {"c": corp_code})
    if not c:
        raise HTTPException(404, "회사를 찾을 수 없습니다")
    totals = fetch_all("""
        select ftype, sum(amount) as total_amount, count(*) as events
        from funding_events where corp_code = %(c)s and not superseded
        group by ftype order by total_amount desc""", {"c": corp_code})
    return Company(**c, totals=totals)
