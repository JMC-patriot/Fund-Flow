"""
수집 결과(dart_funding_events.csv) + 발행 직전 재무제표 → PostgreSQL(Supabase) 적재

실행 (저장소 루트에서):
    python collector/dart_funding.py     # 1) 공시 수집 → dart_funding_events.csv
    python collector/load_db.py          # 2) DB 적재 (재실행해도 중복 없이 갱신)

필요한 환경변수(.env): DART_API_KEY, DATABASE_URL
"""
import os, re, sys, json, time
from datetime import date
import pandas as pd
import psycopg
from psycopg.types.json import Jsonb
from dotenv import load_dotenv

load_dotenv()
DB_URL = os.environ["DATABASE_URL"]
# .csv 로 끝나는 인자만 입력 파일로 인정 (복사해 붙인 주석 "# ..." 등은 무시)
_csv = [a for a in sys.argv[1:] if a.endswith(".csv")]
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 저장소 루트
SRC = _csv[0] if _csv else os.path.join(ROOT, "dart_funding_events.csv")

from dart_funding import _get_json, _cached, load_companies   # noqa: E402

FDPP = ["fdpp_fclt", "fdpp_bsninh", "fdpp_op", "fdpp_dtrp", "fdpp_ocsa", "fdpp_etc"]
DILUTION_COL = {"CB": "cvisstk_tisstk_vs", "BW": "nstk_isstk_tisstk_vs",
                "EB": "extg_tisstk_vs"}
PRICE_COL = {"CB": "cv_prc", "BW": "ex_prc", "EB": "ex_prc"}


# ── 값 정리 도우미 ────────────────────────────────────────────────
def num(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    s = str(v).replace(",", "").strip()
    if s in ("", "-", "nan"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def text(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    s = str(v).strip()
    return s if s and s not in ("-", "nan") else None


def to_date(v):
    """'2025년 03월 12일', '2025-03-12', '20250312', '2025.03.12' 모두 처리"""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    d = re.findall(r"\d+", str(v))
    try:
        if len(d) == 1 and len(d[0]) == 8:
            return date(int(d[0][:4]), int(d[0][4:6]), int(d[0][6:]))
        if len(d) >= 3:
            return date(int(d[0]), int(d[1]), int(d[2]))
    except ValueError:
        pass
    return None


def normalize(r):
    ft = r["ftype"]
    if ft == "Equity":
        amount = sum(num(r.get(c)) or 0 for c in FDPP)
        new = (num(r.get("nstk_ostk_cnt")) or 0) + (num(r.get("nstk_estk_cnt")) or 0)
        old = (num(r.get("bfic_tisstk_ostk")) or 0) + (num(r.get("bfic_tisstk_estk")) or 0)
        dilution = new / old * 100 if old else None
    else:
        amount = num(r.get("bd_fta")) or sum(num(r.get(c)) or 0 for c in FDPP)
        dilution = num(r.get(DILUTION_COL[ft]))
    return {
        "rcept_no": r["rcept_no"], "corp_code": r["corp_code"], "ftype": ft,
        "rcept_dt": to_date(r["rcept_no"][:8]),
        "board_date": to_date(r.get("bddd")),
        "amount": amount, "dilution_pct": dilution,
        "exercise_price": num(r.get(PRICE_COL.get(ft, ""))),
        "coupon_rate": num(r.get("bd_intr_ex")), "ytm_rate": num(r.get("bd_intr_sf")),
        "maturity_date": to_date(r.get("bd_mtd")),
        "method": text(r.get("ic_mthn")),
        "raw": {k: v for k, v in r.items() if v is not None and not
                (isinstance(v, float) and pd.isna(v))},
    }


# ── 재무제표 ───────────────────────────────────────────────────────
def report_candidates(issue_dt):
    out = []
    for y in range(issue_dt.year - 2, issue_dt.year + 1):
        out += [(y, "11013", date(y, 3, 31), date(y, 5, 15)),
                (y, "11012", date(y, 6, 30), date(y, 8, 14)),
                (y, "11014", date(y, 9, 30), date(y, 11, 14)),
                (y, "11011", date(y, 12, 31), date(y + 1, 3, 31))]
    return sorted([r for r in out if r[3] <= issue_dt], key=lambda r: r[2], reverse=True)


def fetch_financials(corp_code, issue_dt):
    """발행일 이전에 공시된 가장 최근 재무제표 (연결·별도 둘 다 있으면 둘 다)"""
    for y, code, base, avail in report_candidates(issue_dt)[:4]:
        def call(y=y, code=code):
            time.sleep(0.5)                    # DART 차단 방지 (캐시에 없을 때만 호출됨)
            j = _get_json("fnlttSinglAcnt.json", corp_code=corp_code,
                          bsns_year=str(y), reprt_code=code)
            if j.get("status") not in ("000", "013"):      # 일시 오류는 캐시하지 않음
                raise RuntimeError(f'{j.get("status")} {j.get("message")}')
            return j.get("list", [])
        rows = _cached(f"bs_{corp_code}_{y}_{code}", call)
        found = []
        for fs in ("CFS", "OFS"):
            acc = {r["account_nm"]: num(r.get("thstrm_amount"))
                   for r in rows if r.get("fs_div") == fs and r.get("sj_div") == "BS"}
            A, L, E = acc.get("자산총계"), acc.get("부채총계"), acc.get("자본총계")
            if None not in (A, L, E):
                found.append((corp_code, y, code, fs, base, avail, A, L, E))
        if found:
            return found
    return []


# ── 적재 ───────────────────────────────────────────────────────────
def main():
    if not os.path.exists(SRC):
        sys.exit(f"{SRC} 파일이 없습니다. 먼저 python collector/dart_funding.py 로 수집하세요.")
    df = pd.read_csv(SRC, dtype=str)
    rows = [normalize(r) for r in df.to_dict("records")]
    rows = [r for r in rows if r["amount"] and r["amount"] > 0 and r["rcept_dt"]]

    # 정정공시: 같은 회사·유형·결의일(유상증자는 신주 수)이면 마지막 접수본만 유효
    latest = {}
    for r in sorted(rows, key=lambda r: r["rcept_no"]):
        k2 = r["board_date"] if r["ftype"] != "Equity" else r["raw"].get("nstk_ostk_cnt")
        latest[(r["corp_code"], r["ftype"], str(k2))] = r["rcept_no"]
    keep = set(latest.values())
    for r in rows:
        r["superseded"] = r["rcept_no"] not in keep
    print(f"공시 {len(rows)}건 (정정으로 대체된 원공시 {len(rows) - len(keep)}건)")

    stock = {c["corp_code"]: c["stock_code"] for c in
             _cached("companies", lambda: load_companies().to_dict("records"))}
    corps = {}
    for r in df.to_dict("records"):
        corps[r["corp_code"]] = (r["corp_code"], r["corp_name"],
                                 stock.get(r["corp_code"]), text(r.get("corp_cls")))

    fins = {}
    need = {}
    for r in rows:
        if not r["superseded"]:
            need.setdefault(r["corp_code"], set()).add(r["rcept_dt"])
    stopped = False
    for i, (cc, dts) in enumerate(need.items(), 1):
        try:
            for dt in dts:
                for f in fetch_financials(cc, dt):
                    fins[f[:4]] = f
        except RuntimeError as e:
            # DART가 연결을 막으면 받은 데까지만 적재하고 종료 → 재실행 시 cache/에서 이어받음
            print(f"  ! DART 응답 중단 ({e}). {i - 1}/{len(need)}개사까지 받은 재무제표로 먼저 적재합니다.")
            stopped = True
            break
        if i % 50 == 0:
            print(f"  재무제표 {i}/{len(need)}개사")
    print(f"재무제표 {len(fins)}건 ({len(need)}개사)")

    with psycopg.connect(DB_URL) as con, con.cursor() as cur:
        cur.executemany("""
            insert into companies (corp_code, corp_name, stock_code, corp_cls)
            values (%s,%s,%s,%s)
            on conflict (corp_code) do update set corp_name=excluded.corp_name,
              stock_code=coalesce(excluded.stock_code, companies.stock_code),
              corp_cls=excluded.corp_cls, updated_at=now()""", list(corps.values()))
        cur.executemany("""
            insert into funding_events (rcept_no, corp_code, ftype, rcept_dt, board_date,
              amount, dilution_pct, exercise_price, coupon_rate, ytm_rate, maturity_date,
              method, superseded, raw)
            values (%(rcept_no)s,%(corp_code)s,%(ftype)s,%(rcept_dt)s,%(board_date)s,
              %(amount)s,%(dilution_pct)s,%(exercise_price)s,%(coupon_rate)s,%(ytm_rate)s,
              %(maturity_date)s,%(method)s,%(superseded)s,%(raw)s)
            on conflict (rcept_no) do update set amount=excluded.amount,
              dilution_pct=excluded.dilution_pct, exercise_price=excluded.exercise_price,
              coupon_rate=excluded.coupon_rate, ytm_rate=excluded.ytm_rate,
              maturity_date=excluded.maturity_date, method=excluded.method,
              superseded=excluded.superseded, raw=excluded.raw, loaded_at=now()""",
            [{**r, "raw": Jsonb(r["raw"])} for r in rows])
        cur.executemany("""
            insert into financials (corp_code, bsns_year, reprt_code, fs_div, base_date,
              available_from, total_assets, total_liabilities, total_equity)
            values (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            on conflict (corp_code, bsns_year, reprt_code, fs_div) do update set
              total_assets=excluded.total_assets, total_liabilities=excluded.total_liabilities,
              total_equity=excluded.total_equity""", list(fins.values()))
        con.commit()
    print("DB 적재 완료")
    if stopped:
        print("※ 재무제표가 일부 빠져 있습니다. 10~30분 뒤 같은 명령을 다시 실행하면 나머지를 이어서 채웁니다.")


if __name__ == "__main__":
    main()
