"""
fundflow API — 2020년 이후 DART 공시 회사의 자금조달 증권(SB·CB·BW·EB·RCPS·유상증자·IPO·CP·단기사채)

Swagger UI: /docs   ·   ReDoc: /redoc
"""
import os
from contextlib import asynccontextmanager
from datetime import date
from typing import Literal, Optional

import requests
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from psycopg.types.json import Jsonb

from .db import pool, fetch_all, fetch_one, execute
from .models import (Health, Meta, TypeInfo, MacroPoint, Security, SecurityPage, MaturityBucket,
                     CompanyHit, Company, Financial, Statements, StatementLine, Source)

TYPES = {"SB": "회사채", "CB": "전환사채", "BW": "신주인수권부사채", "EB": "교환사채",
         "RCPS": "상환전환우선주", "EQUITY": "유상증자", "IPO": "IPO", "CP": "기업어음",
         "STB": "단기사채"}
DEBT = ["SB", "CB", "BW", "EB", "CP", "STB"]
REPORT_NM = {"11013": "1분기", "11012": "반기", "11014": "3분기", "11011": "사업"}
SecType = Literal["SB", "CB", "BW", "EB", "RCPS", "EQUITY", "IPO", "CP", "STB"]


@asynccontextmanager
async def lifespan(app):
    pool.open()
    yield
    pool.close()


app = FastAPI(
    title="fundflow API",
    version="2.0.0",
    description=(
        "금융감독원 DART OpenAPI로 수집한 자금조달 증권의 발행 조건·잔존 만기·발행사 재무를 제공합니다.\n\n"
        "- 금액 단위: 원 (KRW) · 날짜: YYYY-MM-DD · 월: YYYY-MM\n"
        "- 유형: SB 회사채, CB 전환사채, BW 신주인수권부사채, EB 교환사채, RCPS 상환전환우선주, "
        "EQUITY 유상증자, IPO, CP 기업어음, STB 단기사채\n"
        "- 데이터 출처: 금융감독원 전자공시시스템 OpenAPI (https://opendart.fss.or.kr)"),
    lifespan=lifespan,
    openapi_tags=[
        {"name": "meta", "description": "상태·출처"},
        {"name": "macro", "description": "연도별·월별 발행 지표, 만기 분포"},
        {"name": "monitor", "description": "증권별 발행 조건 목록"},
        {"name": "company", "description": "발행사 정보·재무"},
    ],
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "*").split(","),
    allow_methods=["GET"], allow_headers=["*"],
)

VALID = "not s.superseded and s.amount > 0"
OUTSTANDING = ("s.sec_type = any(%(debt)s) and s.maturity_date >= current_date "
               "and coalesce(s.repaid, '') <> '상환'")


def types_param(types: Optional[str]) -> list[str]:
    if not types:
        return list(TYPES)
    out = [t.strip().upper() for t in types.split(",") if t.strip()]
    bad = [t for t in out if t not in TYPES]
    if bad:
        raise HTTPException(422, f"알 수 없는 유형: {', '.join(bad)}")
    return out


def month_start(v: Optional[str]) -> Optional[date]:
    if not v:
        return None
    y, *m = v.split("-")
    return date(int(y), int(m[0]) if m else 1, 1)


def month_end(v: Optional[str]) -> Optional[date]:
    if not v:
        return None
    y, *m = v.split("-")
    y, mm = int(y), int(m[0]) if m else 12
    return date(y + (mm == 12), mm % 12 + 1, 1)          # 다음 달 1일 (미만 비교)


TypesQ = Query(None, description="쉼표로 구분한 유형. 생략하면 전체", examples=["SB,CB,BW"])


# ── meta ───────────────────────────────────────────────────────────────
@app.get("/health", response_model=Health, tags=["meta"], summary="서버·DB 상태")
def health():
    r = fetch_one("select count(*) as n, max(rcept_dt) as latest from securities where not superseded")
    return Health(status="ok", securities=r["n"], latest_rcept_dt=r["latest"])


@app.get("/api/meta", response_model=Meta, tags=["meta"], summary="유형 목록과 데이터 범위")
def meta():
    r = fetch_one(f"""select min(issue_date) as f, max(issue_date) as l,
                             to_char(max(loaded_at) at time zone 'Asia/Seoul', 'YYYY-MM-DD HH24:MI') as loaded
                      from securities s where {VALID} and issue_date <= current_date""")
    p = fetch_one("select count(*) as n from filings where status='pending'")
    return Meta(types=[TypeInfo(code=k, label=v, debt=k in DEBT) for k, v in TYPES.items()],
                first_issue=r["f"], last_issue=r["l"], last_loaded=r["loaded"],
                pending_filings=p["n"])


@app.get("/api/sources", response_model=list[Source], tags=["meta"], summary="사용 데이터와 출처")
def sources():
    return [
        Source(name="공시검색", api="list", used_for="주요사항보고서·발행공시·정기공시 목록"),
        Source(name="전환사채권 발행결정", api="cvbdIsDecsn", used_for="CB 조건 (금리·만기·전환가액·리픽싱)"),
        Source(name="신주인수권부사채권 발행결정", api="bdwtIsDecsn", used_for="BW 조건"),
        Source(name="교환사채권 발행결정", api="exbdIsDecsn", used_for="EB 조건"),
        Source(name="유상증자 결정", api="piicDecsn", used_for="유상증자·RCPS 금액, 신주 수"),
        Source(name="공시서류원본", api="document", used_for="종류주식 유상증자의 RCPS 여부 판별"),
        Source(name="증권신고서 채무증권", api="bdRs", used_for="공모 회사채·CP 회차·금액·만기·주관사"),
        Source(name="증권신고서 지분증권", api="estkRs", used_for="IPO 공모가·공모금액"),
        Source(name="채무증권 발행실적", api="detScritsIsuAcmslt",
               used_for="공모·사모 회사채·CP·단기사채, 금리, 신용등급, 상환 여부"),
        Source(name="다중회사 주요계정", api="fnlttMultiAcnt", used_for="요약 재무·재무지표"),
        Source(name="단일회사 전체 재무제표", api="fnlttSinglAcntAll", used_for="전체 재무제표 (요청 시)"),
    ]


# ── macro ──────────────────────────────────────────────────────────────
@app.get("/api/macro", response_model=list[MacroPoint], tags=["macro"],
         summary="연도별·월별 유형별 발행금액·건수")
def macro(unit: Literal["year", "month"] = Query("year", description="집계 단위"),
          types: Optional[str] = TypesQ,
          start: Optional[str] = Query(None, description="시작 연월 YYYY-MM", examples=["2020-01"]),
          end: Optional[str] = Query(None, description="끝 연월 YYYY-MM (포함)", examples=["2026-10"])):
    fmt = "YYYY" if unit == "year" else "YYYY-MM"
    return fetch_all(f"""
        select to_char(issue_date, '{fmt}') as period, sec_type, sum(amount) as amount,
               count(*) as count, count(distinct corp_code) as companies
        from securities s
        where {VALID} and issue_date is not null and issue_date <= current_date
          and sec_type = any(%(types)s)
          and (%(s)s::date is null or issue_date >= %(s)s) and (%(e)s::date is null or issue_date < %(e)s)
        group by 1, 2 order by 1, 2""",
        {"types": types_param(types), "s": month_start(start), "e": month_end(end)})


@app.get("/api/maturities", response_model=list[MaturityBucket], tags=["macro"],
         summary="잔존 채무증권의 만기 분포")
def maturities(types: Optional[str] = TypesQ):
    """오늘 기준 잔존만기 구간별 금액. 상환 완료로 확인된 증권은 제외합니다."""
    return fetch_all(f"""
        select case when d <= 90 then '0-3m' when d <= 182 then '3-6m' when d <= 365 then '6-12m'
                    when d <= 730 then '1-2y' when d <= 1095 then '2-3y' else '3y+' end as bucket,
               sec_type, sum(amount) as amount, count(*) as count
        from (select s.*, s.maturity_date - current_date as d from securities s
              where {VALID} and {OUTSTANDING} and s.sec_type = any(%(types)s)) s
        group by 1, 2""",
        {"debt": DEBT, "types": [t for t in types_param(types) if t in DEBT]})


# ── monitor ────────────────────────────────────────────────────────────
SEC_COLS = """s.id, s.corp_code, c.corp_name, c.stock_code, c.corp_cls, s.sec_type, s.source,
  s.offering, s.name, s.series, s.rcept_dt, s.issue_date, s.amount, s.coupon, s.ytm,
  s.maturity_date, s.maturity_date - current_date as days_left, s.conv_price, s.refix_floor,
  s.conv_start, s.conv_end, s.underlying, s.shares, s.dilution_pct, s.rating, s.repaid,
  s.repaid_asof, s.method, s.underwriter,
  case when s.rcept_no is not null then 'https://dart.fss.or.kr/dsaf001/main.do?rcpNo=' || s.rcept_no end as dart_url"""

SORTS = {"maturity": "s.maturity_date asc nulls last, s.amount desc",
         "issue": "s.issue_date desc nulls last, s.amount desc",
         "amount": "s.amount desc nulls last",
         "coupon": "s.coupon desc nulls last, s.amount desc"}


@app.get("/api/securities", response_model=SecurityPage, tags=["monitor"],
         summary="증권별 발행 조건 목록 (기본: 잔존 채무증권, 만기 임박 순)")
def securities(types: Optional[str] = TypesQ,
               status: Literal["outstanding", "all"] = Query(
                   "outstanding", description="outstanding: 만기 전·미상환 채무증권만 / all: 전체"),
               offering: Optional[Literal["공모", "사모"]] = Query(None),
               q: Optional[str] = Query(None, description="회사명 일부 또는 종목코드"),
               corp_code: Optional[str] = Query(None),
               issue_from: Optional[str] = Query(None, description="발행 연월 시작 YYYY-MM"),
               issue_to: Optional[str] = Query(None, description="발행 연월 끝 YYYY-MM (포함)"),
               maturity_from: Optional[str] = Query(None, description="만기 연월 시작 YYYY-MM"),
               maturity_to: Optional[str] = Query(None, description="만기 연월 끝 YYYY-MM (포함)"),
               sort: Literal["maturity", "issue", "amount", "coupon"] = Query("maturity"),
               limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0)):
    where = f"""{VALID} and s.sec_type = any(%(types)s)
      and (%(status)s = 'all' or ({OUTSTANDING}))
      and (%(off)s::text is null or s.offering = %(off)s)
      and (%(corp)s::text is null or s.corp_code = %(corp)s)
      and (%(q)s::text is null or c.corp_name ilike '%%' || %(q)s || '%%' or c.stock_code = %(q)s)
      and (%(i1)s::date is null or s.issue_date >= %(i1)s) and (%(i2)s::date is null or s.issue_date < %(i2)s)
      and (%(m1)s::date is null or s.maturity_date >= %(m1)s) and (%(m2)s::date is null or s.maturity_date < %(m2)s)"""
    p = {"types": types_param(types), "status": status, "debt": DEBT, "off": offering,
         "corp": corp_code, "q": (q or "").strip() or None,
         "i1": month_start(issue_from), "i2": month_end(issue_to),
         "m1": month_start(maturity_from), "m2": month_end(maturity_to),
         "limit": limit, "offset": offset}
    agg = fetch_one(f"""select count(*) as n, coalesce(sum(s.amount), 0) as amt
                        from securities s join companies c using (corp_code) where {where}""", p)
    items = fetch_all(f"""select {SEC_COLS} from securities s join companies c using (corp_code)
                          where {where} order by {SORTS[sort]}, s.id
                          limit %(limit)s offset %(offset)s""", p)
    return SecurityPage(total=agg["n"], total_amount=agg["amt"], items=items)


# ── company ────────────────────────────────────────────────────────────
@app.get("/api/companies", response_model=list[CompanyHit], tags=["company"], summary="회사 검색")
def search_companies(q: str = Query(..., min_length=1, description="회사명 일부 또는 종목코드"),
                     limit: int = Query(10, ge=1, le=50)):
    return fetch_all(f"""
        select c.corp_code, c.corp_name, c.stock_code, c.corp_cls,
               coalesce(sum(s.amount) filter (where {OUTSTANDING}), 0) as outstanding,
               sum(s.amount) as total_amount, count(*) as count
        from companies c join securities s using (corp_code)
        where {VALID} and (c.corp_name ilike '%%' || %(q)s || '%%' or c.stock_code = %(q)s)
        group by c.corp_code
        order by (c.corp_name = %(q)s) desc, outstanding desc, total_amount desc
        limit %(limit)s""", {"q": q.strip(), "limit": limit, "debt": DEBT})


@app.get("/api/companies/{corp_code}", response_model=Company, tags=["company"],
         summary="회사 정보와 유형별 발행 합계")
def company(corp_code: str):
    c = fetch_one("select corp_code, corp_name, stock_code, corp_cls from companies where corp_code=%(c)s",
                  {"c": corp_code})
    if not c:
        raise HTTPException(404, "회사를 찾을 수 없습니다")
    totals = fetch_all(f"""
        select sec_type, sum(amount) as amount, count(*) as count,
               coalesce(sum(amount) filter (where {OUTSTANDING}), 0) as outstanding
        from securities s where {VALID} and corp_code=%(c)s group by 1 order by 2 desc""",
        {"c": corp_code, "debt": DEBT})
    return Company(**c, totals=totals)


def ratios(r: dict) -> dict:
    def div(a, b):
        return round(float(a) / float(b) * 100, 2) if a is not None and b not in (None, 0) and float(b) > 0 else None
    return {**r, "report": f'{r["bsns_year"]}년 {REPORT_NM[r["reprt_code"]]}',
            "fs_div": "연결" if r["fs_div"] == "CFS" else "별도",
            "debt_ratio": div(r["total_liab"], r["total_equity"]),
            "equity_ratio": div(r["total_equity"], r["total_assets"]),
            "current_ratio": div(r["current_assets"], r["current_liab"]),
            "op_margin": div(r["op_income"], r["revenue"]) if r["revenue"] else None}


@app.get("/api/companies/{corp_code}/financials", response_model=list[Financial], tags=["company"],
         summary="요약 재무와 재무지표 추이")
def financials(corp_code: str):
    """보고서별 주요 계정과 부채비율·자기자본비율·유동비율·영업이익률. 연결 우선, 없으면 별도. 최신순."""
    rows = fetch_all("""
        select distinct on (bsns_year, reprt_code) * from financials where corp_code=%(c)s
        order by bsns_year, reprt_code, (fs_div='CFS') desc""", {"c": corp_code})
    rows.sort(key=lambda r: r["base_date"], reverse=True)
    return [ratios(r) for r in rows]


def _dart_statements(corp_code, year, reprt, fs_div):
    key = os.getenv("DART_API_KEY")
    if not key:
        raise HTTPException(503, "서버에 DART_API_KEY가 설정되지 않았습니다")
    j = requests.get("https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json", timeout=30, params={
        "crtfc_key": key.strip(), "corp_code": corp_code, "bsns_year": year, "reprt_code": reprt,
        "fs_div": fs_div}).json()
    if j.get("status") == "013":
        return []
    if j.get("status") != "000":
        raise HTTPException(502, f'DART 오류 {j.get("status")} {j.get("message")}')
    return j["list"]


def _amt(v):
    try:
        return float(str(v).replace(",", "")) if v not in (None, "", "-") else None
    except ValueError:
        return None


@app.get("/api/companies/{corp_code}/statements", response_model=Statements, tags=["company"],
         summary="전체 재무제표 (DART에서 받아 저장)")
def statements(corp_code: str, bsns_year: int = Query(..., ge=2015),
               reprt_code: Literal["11011", "11012", "11013", "11014"] = Query("11011"),
               fs_div: Literal["CFS", "OFS"] = Query("CFS")):
    """처음 요청 시 DART 단일회사 전체 재무제표를 받아 저장하고, 이후에는 저장본을 돌려줍니다."""
    p = {"c": corp_code, "y": bsns_year, "r": reprt_code, "f": fs_div}
    row = fetch_one("""select data from statements where corp_code=%(c)s and bsns_year=%(y)s
                       and reprt_code=%(r)s and fs_div=%(f)s""", p)
    if row:
        data = row["data"]
    else:
        data = _dart_statements(corp_code, bsns_year, reprt_code, fs_div)
        if fetch_one("select 1 as x from companies where corp_code=%(c)s", p):
            execute("""insert into statements (corp_code, bsns_year, reprt_code, fs_div, data)
                       values (%(c)s,%(y)s,%(r)s,%(f)s,%(d)s) on conflict do nothing""",
                    {**p, "d": Jsonb(data)})
    lines = [StatementLine(sj_div=d.get("sj_div", ""), sj_nm=d.get("sj_nm"),
                           account_nm=(d.get("account_nm") or "").strip(),
                           # 분기·반기 손익은 연초부터 누적(add) 우선
                           this=_amt(d.get("thstrm_add_amount")) if _amt(d.get("thstrm_add_amount")) is not None
                           else _amt(d.get("thstrm_amount")),
                           prev=next((v for v in (_amt(d.get(k)) for k in
                                      ("frmtrm_add_amount", "frmtrm_amount", "frmtrm_q_amount"))
                                      if v is not None), None),
                           prev2=_amt(d.get("bfefrmtrm_amount")))
             for d in sorted(data, key=lambda d: (d.get("sj_div", ""), int(d.get("ord") or 0)))]
    return Statements(corp_code=corp_code, bsns_year=bsns_year, reprt_code=reprt_code,
                      fs_div=fs_div, lines=lines)
