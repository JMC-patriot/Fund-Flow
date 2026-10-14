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
import time
from collections import defaultdict
from datetime import date, timedelta

import psycopg
from psycopg.types.json import Jsonb
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dart import Dart, BudgetExceeded, num, text, to_date  # noqa: E402
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
    elif ty == "I":                               # 거래소 공시: 메자닌 행사·조정·만기전취득
        import balance
        return balance.kind_of(r["report_nm"])
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
        self.url = url
        self.con = self._connect()

    def _connect(self):
        con = psycopg.connect(self.url, autocommit=True, prepare_threshold=None, connect_timeout=30)
        con.execute("set statement_timeout = '15min'")   # Supabase 기본 2분: 정리(DEDUPE) 쿼리가 커지면 부족
        return con

    def _run(self, fn):
        """연결이 끊겼으면(네트워크 순단·절전) 다시 연결해서 한 번 더 시도"""
        for attempt in range(4):
            try:
                if self.con.closed:
                    self.con = self._connect()
                with self.con.cursor() as cur:
                    return fn(cur)
            except psycopg.OperationalError as e:
                if attempt == 3:
                    raise
                print(f"  ! DB 연결 끊김, 재연결 {attempt + 1}/3 ({str(e).splitlines()[0]})")
                time.sleep(5 * (attempt + 1))
                try:
                    self.con.close()
                except psycopg.Error:
                    pass

    def q(self, sql, params=None):
        def go(cur):
            cur.execute(sql, params or ())
            return cur.fetchall() if cur.description else None
        return self._run(go)

    def many(self, sql, rows):
        if rows:
            self._run(lambda cur: cur.executemany(sql, rows))

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
        rows = [{**r, "raw": Jsonb(r["raw"]),
                 "amount": abs(r["amount"]) if r.get("amount") is not None else None}  # (1,000) 괄호 표기
                for r in rows if r]
        cols = parse.COLS
        upd = ", ".join(f"{c}=excluded.{c}" for c in cols if c not in ("id",))
        cmp = [c for c in cols if c not in ("id", "raw", "dkey")]
        cmp_old = ", ".join(f"securities.{c}" for c in cmp)
        cmp_new = ", ".join(f"excluded.{c}" for c in cmp)
        sql = f"""insert into securities ({", ".join(cols)})
            values ({", ".join(f"%({c})s" for c in cols)})
            on conflict (id) do update set {upd}, loaded_at=now()
            where (securities.repaid_asof is null or excluded.repaid_asof is null
                   or excluded.repaid_asof >= securities.repaid_asof)
              -- 값이 실제로 바뀔 때만 다시 씀 (무료 DB 디스크 쓰기 절약)
              and ({cmp_old}) is distinct from ({cmp_new})"""
        try:
            self.many(sql, rows)
            # 발행회사명은 위 갱신 조건(최신 상환 기준일)과 무관하게 채움
            names = [(r["issuer_name"], r["id"]) for r in rows if r.get("issuer_name")]
            self.many("update securities set issuer_name = %s where id = %s and issuer_name is distinct from %s",
                      [(n, i, n) for n, i in names])
        except psycopg.Error:
            # 이상한 행 하나 때문에 수집 전체가 멈추지 않도록: 한 행씩 넣고 실패한 행만 건너뜀
            for r in rows:
                try:
                    self.many(sql, [r])
                except psycopg.Error as e:
                    print(f"  ! 건너뜀 {r.get('id')}: {str(e).splitlines()[0]}")


# ── 1) 공시 목록 스캔 ─────────────────────────────────────────────────
def list_windows(since: date):
    today = date.today()
    cutoff = today - timedelta(days=RECENT_DAYS)
    windows, s = [], since
    while s <= cutoff:                                  # 지난 구간: 89일 단위, 한 번만
        e = min(s + timedelta(days=88), cutoff)
        windows.append((s, e, True))
        s = e + timedelta(days=1)
    windows.append((cutoff + timedelta(days=1), today, False))   # 최근 구간: 매번
    return windows


def scan_lists(dart, db, since: date, types=("B", "C", "A")):
    """types: 공시유형(B/C/A) 또는 상세유형(C001 = 증권신고서 지분증권만, 훨씬 적음)"""
    for ty in types:
        flt = {"pblntf_detail_ty": ty} if len(ty) > 1 else {"pblntf_ty": ty}
        for s, e, final in list_windows(since):
            if ty == "I" and final:                   # 거래소 공시는 최근 구간만 (과거는 회사별로 따로 받음)
                continue
            task = f"list:{ty}:{s:%Y%m%d}:{e:%Y%m%d}"
            if final and db.done(task):
                continue
            rows, page = [], 1
            while True:
                j = dart.json("list", bgn_de=f"{s:%Y%m%d}", end_de=f"{e:%Y%m%d}", **flt,
                              page_no=page, page_count=100)
                rows += j.get("list", [])
                if page >= int(j.get("total_page") or 1):
                    break
                page += 1
            keep = []
            for r in rows:
                kind = classify(r, ty[0])
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


# ── 상장일 (한국거래소 KIND 상장법인 목록, DART 한도와 무관) ─────────────
def update_listing_dates(db):
    import html, requests
    try:
        r = requests.get("https://kind.krx.co.kr/corpgeneral/corpList.do",
                         params={"method": "download", "searchType": "13"}, timeout=60)
        txt = r.content.decode("euc-kr", errors="replace")
    except requests.RequestException as e:
        print(f"  ! 상장일 목록을 받지 못했습니다: {e}")
        return
    rows = []
    for tr in re.findall(r"<tr>(.*?)</tr>", txt, re.S):
        tds = [html.unescape(re.sub(r"<[^>]+>", "", c)).strip() for c in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]
        if len(tds) >= 6 and re.fullmatch(r"\d{4}-\d{2}-\d{2}", tds[5]):
            rows.append((tds[5], tds[2]))
    db.many("update companies set listed_on = %s where stock_code = %s", rows)
    print(f"상장일: {len(rows)}개사 갱신")


# ── 주가 (KRX Open API: 최근 거래일 종가·상장주식수, 오버행 계산용) ─────────
def update_quotes(db):
    import requests
    key = (os.getenv("KRX_API_KEY") or "").strip()
    if not key:
        print("  ! KRX_API_KEY가 없어 주가는 건너뜁니다")
        return
    for back in range(0, 10):                          # 휴일이면 빈 응답 → 하루씩 앞으로
        d = date.today() - timedelta(days=back)
        rows = []
        for path in ("sto/stk_bydd_trd", "sto/ksq_bydd_trd"):
            try:
                j = requests.get(f"https://data-dbg.krx.co.kr/svc/apis/{path}", params={"basDd": f"{d:%Y%m%d}"},
                                 headers={"AUTH_KEY": key}, timeout=30).json()
            except (requests.RequestException, ValueError) as e:
                print(f"  ! KRX {path} 실패: {e}")
                return
            rows += j.get("OutBlock_1") or []
        if rows:
            break
    else:
        return
    num = lambda v: float(str(v).replace(",", "")) if v not in (None, "", "-") else None
    db.many("""insert into quotes (stock_code, name, market, bas_dd, close, mktcap, list_shrs)
               values (%s,%s,%s,%s,%s,%s,%s)
               on conflict (stock_code) do update set name=excluded.name, market=excluded.market,
                 bas_dd=excluded.bas_dd, close=excluded.close, mktcap=excluded.mktcap,
                 list_shrs=excluded.list_shrs, updated_at=now()""",
            [(r["ISU_CD"], r["ISU_NM"], r["MKT_NM"], d, num(r["TDD_CLSPRC"]), num(r["MKTCAP"]), num(r["LIST_SHRS"]))
             for r in rows])
    print(f"주가: {d} 기준 {len(rows)}종목")


# ── 메자닌 잔액 (행사·전환가액 조정·만기전 사채취득 공시) ──────────────────
def fetch_balances(dart, db, per_corp_docs=15):
    """잔존 CB·BW·EB가 있는 회사의 거래소 공시에서 회차별 미전환 잔액·현재 전환가·남은 주식수를 추적"""
    import balance
    corps = db.q("""select s.corp_code, min(s.issue_date) from securities s
                    where not s.superseded and s.sec_type in ('CB','BW','EB') and s.maturity_date >= current_date
                      and coalesce(s.repaid,'') <> '상환' and s.issue_date is not null group by 1""")
    today = date.today()
    todo = [(c, d) for c, d in corps if not db.done(f"ilist:{c}")]       # 회사별 과거 목록은 한 번만
    print(f"메자닌 잔액 공시 목록: {len(todo)}개사")
    for i, (corp, first) in enumerate(todo, 1):
        bgn = min(max(first - timedelta(days=7), date(2019, 1, 1)), today)   # 미래 발행 예정분은 오늘까지
        rows, page = [], 1
        while True:
            j = dart.json("list", corp_code=corp, bgn_de=f"{bgn:%Y%m%d}", end_de=f"{today:%Y%m%d}",
                          pblntf_ty="I", page_no=page, page_count=100)
            rows += j.get("list", [])
            if page >= int(j.get("total_page") or 1):
                break
            page += 1
        keep = [(r["rcept_no"], r["corp_code"], r["corp_name"], r.get("corp_cls"), text(r.get("stock_code")),
                 r["report_nm"].strip(), to_date(r["rcept_dt"]), k)
                for r in rows if (k := balance.kind_of(r["report_nm"]))]
        db.many("""insert into filings (rcept_no, corp_code, corp_name, corp_cls, stock_code, report_nm, rcept_dt, kind)
                   values (%s,%s,%s,%s,%s,%s,%s,%s) on conflict (rcept_no) do nothing""", keep)
        db.log(f"ilist:{corp}")
        if i % 200 == 0:
            print(f"  {i}/{len(todo)} (호출 {dart.calls})")
    # 회사별 최신 공시부터 원문을 읽어 잔액 저장 (회사당 최근 per_corp_docs건까지)
    pend = db.q("""select rcept_no, corp_code, rcept_dt, kind from (
                     select f.*, row_number() over (partition by corp_code order by rcept_dt desc, rcept_no desc) rn
                     from filings f where kind in ('EXERCISE','REFIX','REDEEM') and status='pending') x
                   where rn <= %s order by rcept_dt desc""", (per_corp_docs,))
    print(f"메자닌 잔액 공시 원문: {len(pend)}건")
    for k, (rc, corp, dt, kind) in enumerate(pend, 1):
        try:
            items = balance.parse(balance.plain_text(dart.document_text(rc)), kind)
        except RuntimeError as e:
            print(f"  ! {rc} 건너뜀: {e}")
            continue
        db.many("""insert into mezz_balance (corp_code, series, rcept_no, rcept_dt, kind, remaining, conv_price, shares)
                   values (%s,%s,%s,%s,%s,%s,%s,%s) on conflict do nothing""",
                [(corp, it["series"], rc, dt, kind, it["remaining"], it["conv_price"], it["shares"]) for it in items])
        mark(db, [rc])
        if k % 300 == 0:
            print(f"  {k}/{len(pend)} (호출 {dart.calls})")
    # 회사당 한도를 넘는 오래된 공시는 읽지 않음
    db.q("""update filings set status='skip' where kind in ('EXERCISE','REFIX','REDEEM') and status='pending'""")


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
    for (corp, kind), fl in sorted(groups.items(), key=lambda kv: kv[0][1] != "EQUITY_RS"):  # IPO 먼저
        dts = [d for _, d in fl]
        j = dart.json("bdRs" if kind == "BOND_RS" else "estkRs", corp_code=corp,
                      bgn_de=f"{min(dts):%Y%m%d}", end_de=f"{max(dts):%Y%m%d}")
        groups_ = {g["title"]: g.get("list", []) for g in j.get("group", [])}
        save_underwriters(db, groups_.get("인수인정보", []))
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


def save_underwriters(db, rows):
    """인수인정보 → underwritings (대표·인수단, 인수금액, 수수료)"""
    out = []
    for u in rows:
        name = text(u.get("actnmn"))
        if not name:
            continue
        amt = num(u.get("udtamt"))
        fee_t = text(u.get("udtprc"))
        rate = None
        if fee_t:
            m = re.search(r"([\d.]+)\s*%", fee_t)
            if m:
                rate = float(m.group(1))
            elif amt and num(fee_t):
                rate = round(num(fee_t) / amt * 100, 4)
        out.append((u["rcept_no"], u["corp_code"], name, text(u.get("actsen")) or "인수",
                    text(u.get("tm")) or text(u.get("stksen")) or "", amt, fee_t, rate, text(u.get("udtmth"))))
    uniq = {(r[0], r[2], r[3], r[4]): r for r in out}
    db.many("""insert into underwritings (rcept_no, corp_code, underwriter, role, series, amount, fee_text, fee_rate, method)
               values (%s,%s,%s,%s,%s,%s,%s,%s,%s)
               on conflict (rcept_no, underwriter, role, series) do update set amount=excluded.amount,
                 fee_text=excluded.fee_text, fee_rate=excluded.fee_rate, method=excluded.method""", list(uniq.values()))


def backfill_underwriters(dart, db):
    """이미 처리한 증권신고서의 인수단을 회사별로 다시 받아 채움 (한 번만)"""
    groups = db.q("""select corp_code, kind, min(rcept_dt), max(rcept_dt) from filings
                     where kind in ('BOND_RS','EQUITY_RS') and status='done' group by 1,2""")
    todo = [g for g in groups if not db.done(f"uw:{g[1]}:{g[0]}")]
    print(f"인수단 보강: {len(todo)}개 (회사, 유형)")
    for i, (corp, kind, d0, d1) in enumerate(todo, 1):
        j = dart.json("bdRs" if kind == "BOND_RS" else "estkRs", corp_code=corp,
                      bgn_de=f"{d0:%Y%m%d}", end_de=f"{d1:%Y%m%d}")
        save_underwriters(db, [u for g in j.get("group", []) if g["title"] == "인수인정보" for u in g.get("list", [])])
        db.log(f"uw:{kind}:{corp}")
        if i % 300 == 0:
            print(f"  {i}/{len(todo)} (호출 {dart.calls})")


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
    """발행 이력이 있는 회사의 주요 재무 (다중회사 API로 50개사씩 — 100개사면 DART가 가끔 오류 페이지를 줌)"""
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
        for k in range(0, len(items), 50):
            if dart.calls >= stop:
                return
            chunk = items[k:k + 50]
            try:
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
            except RuntimeError as e:             # 이 묶음은 다음 실행으로 넘기고 계속
                print(f"  ! 재무 {y} {code} 묶음 건너뜀: {e}")
                continue
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
DEDUPE_SQL = r"""
-- 숨김(superseded) 최종값을 임시 테이블에서 계산하고, 실제로 바뀌는 행만 반영한다
-- (전 행을 매번 다시 쓰면 무료 DB에서 낡은 행이 쌓여 용량 한도를 넘음)
drop table if exists _sup;
create temp table _sup as
  select s.id, s.source, s.corp_code, s.dkey, s.rcept_no, s.sec_type, s.amount, s.method, s.rcept_dt,
         s.issue_date, s.maturity_date, s.issuer_name, c.corp_name, false as sup
  from securities s join companies c using (corp_code);
create index on _sup (corp_code);

-- 정기보고서: 모회사 보고서에 실린 연결 자회사(현대캐피탈, 해외법인 등) 발행분은 숨김
-- (자기 보고서를 내는 자회사는 그 보고서에서 따로 잡힘)
update _sup set sup = true
where source = 'periodic' and coalesce(issuer_name, '') not in ('', '-', '합계', '합 계')
  and regexp_replace(issuer_name, '\(주\)|㈜|주식회사|\s', '', 'g') <> ''
  and position(regexp_replace(issuer_name, '\(주\)|㈜|주식회사|\s', '', 'g')
               in regexp_replace(corp_name, '\(주\)|㈜|주식회사|\s', '', 'g')) = 0
  and position(regexp_replace(corp_name, '\(주\)|㈜|주식회사|\s', '', 'g')
               in regexp_replace(issuer_name, '\(주\)|㈜|주식회사|\s', '', 'g')) = 0;

-- 같은 출처·같은 키는 최신 접수본만
update _sup s set sup = true
where s.source in ('decision','bond_rs','equity_rs') and exists (
  select 1 from _sup t where t.source = s.source and t.corp_code = s.corp_code
    and t.dkey = s.dkey and t.rcept_no > s.rcept_no);

-- 지분증권 신고서 중 IPO가 아닌 것(상장사의 공모증자)은 숨김
--  · 주주배정 방식이거나
--  · 신고 시점에 이미 상장돼 있었거나 (KIND 상장일 기준)
--  · 상장일을 모를 때(상장폐지 등): 같은 시기 유상증자 결정 공시가 있으면
update _sup r set sup = true
where r.source = 'equity_rs' and not r.sup and (
  coalesce(r.method, '') like '%%주주%%'
  or exists (select 1 from companies c where c.corp_code = r.corp_code
               and c.listed_on is not null and c.listed_on < r.rcept_dt - 10)
  or (not exists (select 1 from companies c where c.corp_code = r.corp_code
                    and c.listed_on between r.rcept_dt - 10 and r.rcept_dt + 200)
      and exists (select 1 from _sup d where d.source = 'decision' and d.sec_type in ('EQUITY','RCPS')
                    and not d.sup and d.amount > 0 and d.corp_code = r.corp_code
                    and abs(d.rcept_dt - r.rcept_dt) <= 120)));

-- 반대로 IPO로 남은 건과 같은 시기의 유상증자 결정(상장 전 공모)은 유상증자 집계에서 제외
update _sup d set sup = true
where d.source = 'decision' and d.sec_type = 'EQUITY' and not d.sup and exists (
  select 1 from _sup i where i.sec_type = 'IPO' and not i.sup
    and i.corp_code = d.corp_code and abs(i.rcept_dt - d.rcept_dt) <= 120);

-- 공모 CB/BW/EB 신고서는 결정 공시와 중복
update _sup r set sup = true
where r.source = 'bond_rs' and r.sec_type in ('CB','BW','EB') and not r.sup and exists (
  select 1 from _sup d where d.source = 'decision' and not d.sup
    and d.corp_code = r.corp_code and d.sec_type = r.sec_type and d.amount = r.amount);

-- 정기보고서 행과 공시 행이 같은 발행이면: 등급·상환 여부·금리를 공시 행에 옮기고 정기보고서 행은 숨김
drop table if exists _m;
create temp table _m as
  select distinct on (p.id) p.id as pid, x.id as xid
  from _sup p join _sup x
    on x.corp_code = p.corp_code and x.sec_type = p.sec_type and x.amount = p.amount
   and x.source <> 'periodic' and not x.sup
   and (abs(x.issue_date - p.issue_date) <= 10 or x.maturity_date = p.maturity_date)
  where p.source = 'periodic' and not p.sup
  order by p.id, abs(x.issue_date - p.issue_date);

update securities x set rating = coalesce(pp.rating, x.rating), grade = coalesce(pp.grade, x.grade),
       repaid = pp.repaid, repaid_asof = pp.repaid_asof, coupon = coalesce(x.coupon, pp.coupon)
from _m join securities pp on pp.id = _m.pid
where x.id = _m.xid
  and (x.rating is distinct from coalesce(pp.rating, x.rating) or x.grade is distinct from coalesce(pp.grade, x.grade)
       or x.repaid is distinct from pp.repaid or x.repaid_asof is distinct from pp.repaid_asof
       or x.coupon is distinct from coalesce(x.coupon, pp.coupon));

update _sup set sup = true where id in (select pid from _m);

-- 바뀐 행만 반영
update securities s set superseded = t.sup from _sup t
where s.id = t.id and s.superseded is distinct from t.sup;
drop table _sup;
drop table _m;
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
    # 1회성 보정: 지분증권 신고서는 C001 목록으로 따로 훑고(빠름), 이미 받은 발행공시(C) 목록은 다시 훑지 않음
    if not db.done("fix:issuer_v1"):                   # 정기보고서를 발행회사명과 함께 다시 받음
        db.q("update filings set status='pending' where kind in ('ANNUAL','HALF','Q1','Q3') and status in ('done','skip')")
        db.log("fix:issuer_v1")
        print("발행회사명 보정: 정기보고서 발행실적을 다시 받습니다")
    if not db.done("fix:ipo_v3"):
        for s, e, final in list_windows(since):
            if final:
                db.log(f"list:C:{s:%Y%m%d}:{e:%Y%m%d}")
        db.q("update filings set status='pending' where kind='EQUITY_RS'")
        db.log("fix:ipo_v3")
        print("IPO 보정: 지분증권 신고서 목록(C001)을 따로 훑습니다")
    try:
        update_listing_dates(db)
        update_quotes(db)
        # 유형별로 목록 → 상세를 바로 이어서 처리 (초기 적재 때 화면에 빨리 데이터가 보이도록)
        scan_lists(dart, db, since, ("B",))
        fetch_decisions(dart, db)
        db.q(DEDUPE_SQL)
        detect_rcps(dart, db)
        scan_lists(dart, db, since, ("C001", "C"))      # IPO(지분증권 신고서)를 먼저
        fetch_registrations(dart, db)
        db.q(DEDUPE_SQL)
        scan_lists(dart, db, since, ("A",))
        backfill_underwriters(dart, db)
        scan_lists(dart, db, since, ("I",))
        fetch_balances(dart, db)
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
