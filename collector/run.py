"""
fundflow 수집기 — 초기 적재와 매일 업데이트를 같은 명령으로 처리

    python collector/run.py                    # 기본: 2020-01-01부터, 호출 예산 18,000회
    python collector/run.py --budget 500       # 짧게 시험

흐름 (중단돼도 다음 실행이 이어받음)
  1) 공시 목록 스캔: 주요사항보고서(B)·발행공시(C)·정기공시(A) → filings 대기열
     지난 구간은 한 번만, 최근 15일은 매번 다시 스캔
  2) CB/BW/EB/유상증자 결정 상세        (주요사항보고서)
  3) 회사채·CP 증권신고서, IPO 증권신고서 (발행공시)
  4) 종류주식 유상증자 → 원문에서 RCPS 판별
  5) 정기보고서 채무증권 발행실적(공모·사모 회사채, CP, 신용등급, 상환 여부)
     + 발행 회사의 주요 재무                 (최신 보고서부터, 남은 예산을 나눠 씀)
  6) 정정·중복 정리
"""
import argparse
import os
import re
import sys
from collections import defaultdict
from datetime import date, timedelta

import psycopg
from psycopg.types.json import Jsonb
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dart import Dart, BudgetExceeded, text, to_date  # noqa: E402
import parse  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(ROOT, ".env"))

RECENT_DAYS = 15
REPORT_CODE = {"ANNUAL": "11011", "HALF": "11012", "Q1": "11013", "Q3": "11014"}


# ── 공시 분류 ─────────────────────────────────────────────────────────
def classify(r: dict, ty: str):
    n = r["report_nm"].replace(" ", "")
    if ty == "B":
        for kind, kw in (("CB", "전환사채권발행결정"), ("BW", "신주인수권부사채권발행결정"),
                         ("EB", "교환사채권발행결정"), ("EQUITY", "유상증자결정")):
            if kw in n and "유무상" not in n:
                return kind
    elif ty == "C":
        if "증권신고서(채무증권)" in n:
            return "BOND_RS"
        if "증권신고서(지분증권)" in n:          # 상장 여부는 현재 기준이라 판단에 쓰지 않음 (중복은 정리 단계에서)
            return "EQUITY_RS"
    elif ty == "A" and not n.startswith("["):    # 정정 보고서는 제외 (API가 최종본을 돌려줌)
        m = re.match(r"(사업|반기|분기)보고서\((\d{4})\.(\d{2})\)", n)
        if m:
            k, mm = m.group(1), int(m.group(3))
            if k == "사업":
                return "ANNUAL"
            if k == "반기":
                return "HALF"
            return "Q1" if mm in (3, 4, 5) else "Q3"
    return None


def report_year(report_nm: str) -> int:
    m = re.search(r"\((\d{4})\.(\d{2})\)", report_nm)
    return int(m.group(1))


# ── DB 도우미 ─────────────────────────────────────────────────────────
class Store:
    def __init__(self, url):
        self.con = psycopg.connect(url, autocommit=True, prepare_threshold=None)

    def q(self, sql, params=None):
        with self.con.cursor() as cur:
            cur.execute(sql, params or ())
            return cur.fetchall() if cur.description else None

    def many(self, sql, rows):
        if rows:
            with self.con.cursor() as cur:
                cur.executemany(sql, rows)

    def done(self, task):
        return bool(self.q("select 1 from fetch_log where task=%s and status='done'", (task,)))

    def log(self, task, status="done"):
        self.q("""insert into fetch_log (task, status) values (%s,%s)
                  on conflict (task) do update set status=excluded.status, fetched_at=now()""",
               (task, status))

    def companies(self, rows):
        """rows: (corp_code, corp_name, stock_code, corp_cls)"""
        uniq = {r[0]: r for r in rows}
        self.many("""insert into companies (corp_code, corp_name, stock_code, corp_cls)
            values (%s,%s,%s,%s)
            on conflict (corp_code) do update set corp_name=excluded.corp_name,
              stock_code=coalesce(excluded.stock_code, companies.stock_code),
              corp_cls=excluded.corp_cls, updated_at=now()""", list(uniq.values()))

    def securities(self, rows):
        rows = [{**r, "raw": Jsonb(r["raw"])} for r in rows if r]
        cols = parse.COLS
        upd = ", ".join(f"{c}=excluded.{c}" for c in cols if c not in ("id",))
        self.many(f"""insert into securities ({", ".join(cols)})
            values ({", ".join(f"%({c})s" for c in cols)})
            on conflict (id) do update set {upd}, loaded_at=now()
            where securities.repaid_asof is null or excluded.repaid_asof is null
               or excluded.repaid_asof >= securities.repaid_asof""", rows)


# ── 1) 공시 목록 스캔 ─────────────────────────────────────────────────
def scan_lists(dart, db, since: date, types=("B", "C", "A")):
    today = date.today()
    cutoff = today - timedelta(days=RECENT_DAYS)
    windows, s = [], since
    while s <= cutoff:                                  # 지난 구간: 89일 단위, 한 번만
        e = min(s + timedelta(days=88), cutoff)
        windows.append((s, e, True))
        s = e + timedelta(days=1)
    windows.append((cutoff + timedelta(days=1), today, False))   # 최근 구간: 매번

    for ty in types:
        for s, e, final in windows:
            task = f"list:{ty}:{s:%Y%m%d}:{e:%Y%m%d}"
            if final and db.done(task):
                continue
            rows, page = [], 1
            while True:
                j = dart.json("list", bgn_de=f"{s:%Y%m%d}", end_de=f"{e:%Y%m%d}", pblntf_ty=ty,
                              page_no=page, page_count=100)
                rows += j.get("list", [])
                if page >= int(j.get("total_page") or 1):
                    break
                page += 1
            keep = []
            for r in rows:
                kind = classify(r, ty)
                if kind:
                    keep.append((r["rcept_no"], r["corp_code"], r["corp_name"], r.get("corp_cls"),
                                 text(r.get("stock_code")), r["report_nm"].strip(),
                                 to_date(r["rcept_dt"]), kind))
            db.companies([(k[1], k[2], k[4], k[3]) for k in keep])
            db.many("""insert into filings (rcept_no, corp_code, corp_name, corp_cls, stock_code,
                         report_nm, rcept_dt, kind) values (%s,%s,%s,%s,%s,%s,%s,%s)
                       on conflict (rcept_no) do nothing""", keep)
            if final:
                db.log(task)
            print(f"  목록 {ty} {s}~{e}: {len(rows)}건 중 대상 {len(keep)}건")


def pending(db, kinds, col="status"):
    return db.q(f"""select rcept_no, corp_code, rcept_dt, kind, report_nm, corp_cls from filings
                    where kind = any(%s) and {col}='pending' order by rcept_dt desc""", (list(kinds),))


def mark(db, rcepts, col="status", val="done"):
    db.q(f"update filings set {col}=%s where rcept_no = any(%s)", (val, list(rcepts)))


# ── 2) 결정 공시 ──────────────────────────────────────────────────────
def fetch_decisions(dart, db):
    groups = defaultdict(list)
    for rc, corp, dt, kind, *_ in pending(db, ("CB", "BW", "EB", "EQUITY")):
        groups[(corp, kind)].append((rc, dt))
    print(f"결정 공시: {len(groups)}개 (회사, 유형) 조회")
    for i, ((corp, kind), fl) in enumerate(groups.items(), 1):
        dts = [d for _, d in fl]
        j = dart.json(parse.DECISION_API[kind], corp_code=corp,
                      bgn_de=f"{min(dts):%Y%m%d}", end_de=f"{max(dts):%Y%m%d}")
        db.securities([parse.decision(r, kind) for r in j.get("list", [])])
        mark(db, [rc for rc, _ in fl])
        if i % 200 == 0:
            print(f"  {i}/{len(groups)} (호출 {dart.calls})")


# ── 3) 증권신고서 ─────────────────────────────────────────────────────
def fetch_registrations(dart, db):
    groups = defaultdict(list)
    for rc, corp, dt, kind, *_ in pending(db, ("BOND_RS", "EQUITY_RS")):
        groups[(corp, kind)].append((rc, dt))
    print(f"증권신고서: {len(groups)}개 (회사, 유형) 조회")
    for (corp, kind), fl in groups.items():
        dts = [d for _, d in fl]
        j = dart.json("bdRs" if kind == "BOND_RS" else "estkRs", corp_code=corp,
                      bgn_de=f"{min(dts):%Y%m%d}", end_de=f"{max(dts):%Y%m%d}")
        groups_ = {g["title"]: g.get("list", []) for g in j.get("group", [])}
        leads = {}
        for u in groups_.get("인수인정보", []):
            if (u.get("actsen") or "").strip() == "대표" or u["rcept_no"] not in leads:
                leads[u["rcept_no"]] = text(u.get("actnmn"))
        if kind == "BOND_RS":
            db.securities([parse.bond_rs(g, leads.get(g["rcept_no"])) for g in groups_.get("일반사항", [])])
        else:                                   # 공모가·금액은 '증권의종류', 일정은 '일반사항'
            general = {g["rcept_no"]: g for g in groups_.get("일반사항", [])}
            db.securities([parse.equity_rs(k, general.get(k["rcept_no"], {}), leads.get(k["rcept_no"]))
                           for k in groups_.get("증권의종류", [])])
        mark(db, [rc for rc, _ in fl])


# ── 4) RCPS 판별 ──────────────────────────────────────────────────────
def detect_rcps(dart, db):
    rows = db.q("""select id, rcept_no from securities
                   where source='decision' and sec_type='EQUITY' and (raw->>'nstk_estk_cnt') is not null
                     and not exists (select 1 from fetch_log where task='rcps:'||securities.rcept_no)""")
    print(f"종류주식 유상증자 원문 확인: {len(rows)}건")
    for sid, rc in rows:
        if parse.is_rcps(dart.document_text(rc)):
            db.q("update securities set sec_type='RCPS', name=replace(name,'유상증자','RCPS 유상증자') where id=%s", (sid,))
        db.log(f"rcps:{rc}")


# ── 5) 정기보고서: 발행실적 + 재무 ─────────────────────────────────────
def fetch_periodic(dart, db, share: int):
    """채무증권 발행실적: 사업보고서 전부 + 올해 사업보고서가 아직 없는 회사의 최신 분기·반기"""
    stop = dart.calls + share
    cur_year = date.today().year
    rows = pending(db, ("ANNUAL", "HALF", "Q1", "Q3"))
    latest_q = {}
    for rc, corp, dt, kind, nm, _ in rows:
        y = report_year(nm)
        if kind != "ANNUAL" and y >= cur_year - 1 and corp not in latest_q:
            latest_q[corp] = rc
    todo = [r for r in rows if r[3] == "ANNUAL" or latest_q.get(r[1]) == r[0]]
    skip = [r[0] for r in rows if r not in todo]
    mark(db, skip)
    print(f"정기보고서 발행실적: {len(todo)}건 대기")
    for rc, corp, dt, kind, nm, _ in todo:
        if dart.calls >= stop:
            break
        j = dart.json("detScritsIsuAcmslt", corp_code=corp, bsns_year=str(report_year(nm)),
                      reprt_code=REPORT_CODE[kind])
        db.securities([parse.periodic(r) for r in j.get("list", [])])
        mark(db, [rc])


def fetch_financials(dart, db, share: int):
    """발행 이력이 있는 회사의 주요 재무 (다중회사 API로 100개사씩)"""
    stop = dart.calls + share
    db.q("""update filings f set fin_status='skip' where fin_status='pending'
              and kind in ('ANNUAL','HALF','Q1','Q3')
              and not exists (select 1 from securities s where s.corp_code=f.corp_code)
              and status='done'""")
    rows = db.q("""select f.rcept_no, f.corp_code, f.kind, f.report_nm from filings f
                   where f.kind in ('ANNUAL','HALF','Q1','Q3') and f.fin_status='pending'
                     and exists (select 1 from securities s where s.corp_code=f.corp_code)
                   order by f.rcept_dt desc""")
    batches = defaultdict(list)
    for rc, corp, kind, nm in rows:
        batches[(report_year(nm), REPORT_CODE[kind])].append((rc, corp))
    print(f"주요 재무: {len(rows)}건 대기")
    for (y, code), items in sorted(batches.items(), reverse=True):
        for k in range(0, len(items), 100):
            if dart.calls >= stop:
                return
            chunk = items[k:k + 100]
            j = dart.json("fnlttMultiAcnt", corp_code=",".join(c for _, c in chunk),
                          bsns_year=str(y), reprt_code=code)
            fins = parse.financial_rows(j.get("list", []), code)
            got = {f["corp_code"] for f in fins}
            # 다중회사 API에 없는 회사(일부 비상장)는 단일회사 API로
            for rc, corp in chunk:
                if corp in got or dart.calls >= stop:
                    continue
                j1 = dart.json("fnlttSinglAcnt", corp_code=corp, bsns_year=str(y), reprt_code=code)
                fins += parse.financial_rows(j1.get("list", []), code)
            save_fins(db, fins)
            mark(db, [rc for rc, _ in chunk], col="fin_status")


def save_fins(db, fins):
    cols = ["corp_code", "bsns_year", "reprt_code", "fs_div", "base_date", "rcept_no"] + \
        sorted(set(parse.ACCOUNTS.values()))
    rows = [{c: f.get(c) for c in cols} for f in fins]
    upd = ", ".join(f"{c}=excluded.{c}" for c in cols[4:])
    db.many(f"""insert into financials ({", ".join(cols)}) values ({", ".join(f"%({c})s" for c in cols)})
        on conflict (corp_code, bsns_year, reprt_code, fs_div) do update set {upd}""", rows)


# ── 6) 정정·중복 정리 ─────────────────────────────────────────────────
DEDUPE_SQL = """
-- 같은 출처·같은 키는 최신 접수본만
update securities s set superseded = exists (
  select 1 from securities t where t.source = s.source and t.corp_code = s.corp_code
    and t.dkey = s.dkey and t.rcept_no > s.rcept_no)
where s.source in ('decision','bond_rs','equity_rs');

update securities set superseded = false where source = 'periodic';

-- 지분증권 신고서: 상장사의 공모증자(유상증자 결정 공시가 있거나 주주배정 방식)는 IPO가 아님
update securities r set superseded = true
where r.source = 'equity_rs' and (coalesce(r.method, '') like '%%주주%%' or exists (
  select 1 from securities d where d.source = 'decision' and d.sec_type in ('EQUITY','RCPS')
    and not d.superseded and d.amount > 0 and d.corp_code = r.corp_code
    and abs(d.rcept_dt - r.rcept_dt) <= 120));

-- 공모 CB/BW/EB 신고서는 결정 공시와 중복
update securities r set superseded = true
where r.source = 'bond_rs' and r.sec_type in ('CB','BW','EB') and exists (
  select 1 from securities d where d.source = 'decision' and not d.superseded
    and d.corp_code = r.corp_code and d.sec_type = r.sec_type and d.amount = r.amount);

-- 정기보고서 행과 공시 행이 같은 발행이면: 등급·상환 여부·금리를 공시 행에 옮기고 정기보고서 행은 숨김
with m as (
  select distinct on (p.id) p.id as pid, x.id as xid, p.rating, p.repaid, p.repaid_asof, p.coupon
  from securities p join securities x
    on x.corp_code = p.corp_code and x.sec_type = p.sec_type and x.amount = p.amount
   and x.source <> 'periodic' and not x.superseded
   and (abs(x.issue_date - p.issue_date) <= 10 or x.maturity_date = p.maturity_date)
  where p.source = 'periodic'
  order by p.id, abs(x.issue_date - p.issue_date))
, u as (
  update securities x set rating = coalesce(m.rating, x.rating), repaid = m.repaid,
         repaid_asof = m.repaid_asof, coupon = coalesce(x.coupon, m.coupon)
  from m where x.id = m.xid returning m.pid)
update securities set superseded = true where id in (select pid from u);
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2020-01-01")
    ap.add_argument("--budget", type=int, default=int(os.getenv("DART_BUDGET", 18000)))
    a = ap.parse_args()

    env = {k: (os.getenv(k) or "").strip() for k in ("DART_API_KEY", "DATABASE_URL")}
    missing = [k for k, v in env.items() if not v]
    if missing:
        sys.exit(f"환경변수가 비어 있습니다: {', '.join(missing)} (.env 또는 GitHub Secrets 확인)")
    dart = Dart(env["DART_API_KEY"], a.budget)
    db = Store(env["DATABASE_URL"])
    since = date.fromisoformat(a.since)
    # 1회성 보정: IPO 판별 변경 전에 훑은 발행공시 목록과 지분증권 신고서를 다시 처리
    if not db.done("fix:ipo_v2"):
        db.q("delete from fetch_log where task like 'list:C:%%'")
        db.q("update filings set status='pending' where kind='EQUITY_RS'")
        db.log("fix:ipo_v2")
        print("IPO 보정: 발행공시 목록을 다시 훑습니다")
    try:
        # 유형별로 목록 → 상세를 바로 이어서 처리 (초기 적재 때 화면에 빨리 데이터가 보이도록)
        scan_lists(dart, db, since, ("B",))
        fetch_decisions(dart, db)
        db.q(DEDUPE_SQL)
        detect_rcps(dart, db)
        scan_lists(dart, db, since, ("C",))
        fetch_registrations(dart, db)
        db.q(DEDUPE_SQL)
        scan_lists(dart, db, since, ("A",))
        half = dart.left // 2
        fetch_periodic(dart, db, half)
        fetch_financials(dart, db, dart.left)
        fetch_periodic(dart, db, dart.left)
    except BudgetExceeded as e:
        print(f"※ {e} — 다음 실행에서 이어서 수집합니다.")
    finally:
        db.q(DEDUPE_SQL)
        left = db.q("""select count(*) filter (where status='pending'),
                              count(*) filter (where fin_status='pending' and kind in ('ANNUAL','HALF','Q1','Q3'))
                       from filings""")[0]
        n = db.q("select sec_type, count(*) from securities where not superseded group by 1 order by 1")
        print(f"DART 호출 {dart.calls}회 · 남은 대기: 증권 {left[0]}건, 재무 {left[1]}건")
        print("증권 현황:", ", ".join(f"{t} {c:,}" for t, c in n))


if __name__ == "__main__":
    main()
