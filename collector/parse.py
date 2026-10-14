"""DART 응답 → securities 행 변환"""
import hashlib
import re
from typing import Optional

from dart import num, text, to_date, clean

COLS = ["id", "corp_code", "sec_type", "source", "offering", "rcept_no", "rcept_dt", "name",
        "series", "board_date", "issue_date", "amount", "coupon", "ytm", "maturity_date",
        "conv_price", "refix_floor", "conv_start", "conv_end", "underlying", "shares",
        "dilution_pct", "rating", "repaid", "repaid_asof", "method", "underwriter", "dkey", "raw"]

FDPP = ["fdpp_fclt", "fdpp_bsninh", "fdpp_op", "fdpp_dtrp", "fdpp_ocsa", "fdpp_etc"]

DECISION_API = {"CB": "cvbdIsDecsn", "BW": "bdwtIsDecsn", "EB": "exbdIsDecsn", "EQUITY": "piicDecsn"}

# 결정 공시별 필드 이름 (전환가액·청구기간·대상 주식)
_DEC = {
    "CB": dict(price="cv_prc", start="cvrqpd_bgd", end="cvrqpd_edd", under="cvisstk_knd",
               shares="cvisstk_cnt", dil="cvisstk_tisstk_vs"),
    "BW": dict(price="ex_prc", start="expd_bgd", end="expd_edd", under="nstk_isstk_knd",
               shares="nstk_isstk_cnt", dil="nstk_isstk_tisstk_vs"),
    "EB": dict(price="ex_prc", start="exrqpd_bgd", end="exrqpd_edd", under="extg",
               shares="extg_stkcnt", dil="extg_tisstk_vs"),
}


def _row(**kw) -> dict:
    r = {c: None for c in COLS}
    r.update(kw)
    return r


def offering_of(*texts) -> Optional[str]:
    for t in texts:
        t = t or ""
        if "사모" in t or "제3자배정" in t:
            return "사모"
        if "공모" in t or "주주배정" in t or "일반공모" in t:
            return "공모"
    return None


def bond_type(name: str) -> Optional[str]:
    """증권 명칭 → 유형"""
    n = (name or "").replace(" ", "")
    if not n or n in ("-", "합계"):
        return None
    if "기업어음" in n:
        return "CP"
    if "단기사채" in n or "전자단기" in n:
        return "STB"
    if "신주인수권" in n:
        return "BW"
    if "전환사채" in n:
        return "CB"
    if "교환사채" in n:
        return "EB"
    if "사채" in n or "회사채" in n or "채권" in n or "증권" in n:
        return "SB"
    return None


# ── 주요사항보고서: CB / BW / EB / 유상증자 결정 ────────────────────────
def decision(r: dict, ftype: str) -> dict:
    rcept_dt = to_date(r["rcept_no"][:8])
    if ftype == "EQUITY":
        amount = sum(num(r.get(c)) or 0 for c in FDPP)
        new = (num(r.get("nstk_ostk_cnt")) or 0) + (num(r.get("nstk_estk_cnt")) or 0)
        old = (num(r.get("bfic_tisstk_ostk")) or 0) + (num(r.get("bfic_tisstk_estk")) or 0)
        method = text(r.get("ic_mthn"))
        return _row(
            id=f"D:{r['rcept_no']}", corp_code=r["corp_code"], sec_type="EQUITY", source="decision",
            offering=offering_of(method), rcept_no=r["rcept_no"], rcept_dt=rcept_dt,
            name="유상증자" + (f"({method})" if method else ""),
            issue_date=rcept_dt, amount=amount or None, shares=new or None,
            dilution_pct=round(new / old * 100, 4) if old else None, method=method,
            conv_price=round(amount / new, 2) if amount and new else None,
            dkey=f"EQUITY:{int(new)}:{int(amount)}", raw=clean(r))
    f = _DEC[ftype]
    name = text(r.get("bd_knd"))
    return _row(
        id=f"D:{r['rcept_no']}", corp_code=r["corp_code"], sec_type=ftype, source="decision",
        offering=offering_of(r.get("bdis_mthn"), name), rcept_no=r["rcept_no"], rcept_dt=rcept_dt,
        name=name, series=text(r.get("bd_tm")), board_date=to_date(r.get("bddd")),
        issue_date=to_date(r.get("pymd")) or to_date(r.get("sbd")) or rcept_dt,
        amount=num(r.get("bd_fta")), coupon=num(r.get("bd_intr_ex")), ytm=num(r.get("bd_intr_sf")),
        maturity_date=to_date(r.get("bd_mtd")), conv_price=num(r.get(f["price"])),
        refix_floor=num(r.get("act_mktprcfl_cvprc_lwtrsprc")),
        conv_start=to_date(r.get(f["start"])), conv_end=to_date(r.get(f["end"])),
        underlying=text(r.get(f["under"])), shares=num(r.get(f["shares"])),
        dilution_pct=num(r.get(f["dil"])), underwriter=text(r.get("rpmcmp")),
        dkey=f"{ftype}:{text(r.get('bd_tm')) or ''}:{num(r.get('bd_fta')) or 0:.0f}",
        raw=clean(r))


# ── 증권신고서(채무증권) ───────────────────────────────────────────────
def bond_rs(general: dict, lead: Optional[str]) -> Optional[dict]:
    name = text(general.get("bdnmn"))
    t = bond_type(name) or "SB"
    amount = num(general.get("fta")) or num(general.get("slta"))
    if not amount:
        return None
    tm = text(general.get("tm")) or ""
    return _row(
        id=f"R:{general['rcept_no']}:{tm}", corp_code=general["corp_code"], sec_type=t,
        source="bond_rs", offering=offering_of(general.get("slmth"), name) or "공모",
        rcept_no=general["rcept_no"], rcept_dt=to_date(general["rcept_no"][:8]),
        name=name, series=tm or None, issue_date=to_date(general.get("pymd")),
        amount=amount, coupon=num(general.get("intr")), ytm=num(general.get("isrr")),
        maturity_date=to_date(general.get("rpd")), underwriter=lead,
        dkey=f"{t}:{tm}:{general.get('pymd')}", raw=clean(general))


# ── 증권신고서(지분증권) → IPO ─────────────────────────────────────────
def equity_rs(kind: dict, general: dict, lead: Optional[str]) -> Optional[dict]:
    """kind: '증권의종류' 행(종류·수량·공모가·공모총액·모집방법), general: 같은 접수번호의 '일반사항'(청약·납입일)"""
    amount = num(kind.get("slta"))
    cnt, price = num(kind.get("stkcnt")), num(kind.get("slprc"))
    if not amount and cnt and price:
        amount = cnt * price
    if not amount:
        return None
    stk = text(kind.get("stksen")) or ""
    return _row(
        id=f"S:{kind['rcept_no']}:{stk}", corp_code=kind["corp_code"],
        sec_type="IPO", source="equity_rs", offering="공모", rcept_no=kind["rcept_no"],
        rcept_dt=to_date(kind["rcept_no"][:8]), name=f"기업공개({stk})" if stk else "기업공개",
        issue_date=to_date(general.get("pymd")) or to_date(general.get("sbd")), amount=amount,
        conv_price=price, shares=cnt, method=text(kind.get("slmthn")), underwriter=lead,
        dkey=f"IPO:{stk}", raw=clean({**general, **kind}))


# ── 정기보고서: 채무증권 발행실적 ──────────────────────────────────────
def periodic(r: dict) -> Optional[dict]:
    t = bond_type(r.get("scrits_knd_nm"))
    issue = to_date(r.get("isu_de"))
    amount = num(r.get("facvalu_totamt"))
    if not t or not issue or not amount:
        return None
    mtd = to_date(r.get("mtd"))
    key = "|".join(str(x) for x in (r["corp_code"], r.get("scrits_knd_nm"), issue, amount, mtd,
                                    r.get("intrt")))
    h = hashlib.sha1(key.encode()).hexdigest()[:20]
    return _row(
        id=f"P:{h}", corp_code=r["corp_code"], sec_type=t, source="periodic",
        offering=offering_of(r.get("isu_mth_nm")), rcept_no=r.get("rcept_no"),
        rcept_dt=to_date((r.get("rcept_no") or "")[:8]), name=text(r.get("scrits_knd_nm")),
        issue_date=issue, amount=amount, coupon=num(r.get("intrt")), maturity_date=mtd,
        rating=text(r.get("evl_grad_instt")), repaid=repaid_status(r.get("repy_at")),
        repaid_asof=to_date(r.get("stlm_dt")), underwriter=text(r.get("mngt_cmpny")),
        dkey=f"P:{h}", raw={})          # 정기보고서 행은 원본 미저장 (단기사채 등 행이 많아 DB 용량 초과)


def repaid_status(v) -> Optional[str]:
    """회사마다 다른 표기(Y/N, O/X, 상환완료, 전부전환 …) → 상환 / 미상환 / 일부상환"""
    t = re.sub(r"\s+", "", str(v or ""))
    if not t or t in ("-", "(주1)"):
        return None
    if "일부" in t or "부분" in t:
        return "일부상환"
    if "미상환" in t or t in ("N", "X", "부"):
        return "미상환"
    if t in ("Y", "O") or any(k in t for k in ("상환", "전환", "취득", "완료")):
        return "상환"
    return None


# ── 주요 재무 ─────────────────────────────────────────────────────────
ACCOUNTS = {
    "유동자산": "current_assets", "비유동자산": "noncurrent_assets", "자산총계": "total_assets",
    "유동부채": "current_liab", "비유동부채": "noncurrent_liab", "부채총계": "total_liab",
    "자본금": "capital", "이익잉여금": "retained", "자본총계": "total_equity",
    "매출액": "revenue", "영업수익": "revenue", "영업이익": "op_income",
    "영업이익(손실)": "op_income", "법인세차감전 순이익": "pretax_income",
    "법인세비용차감전순이익(손실)": "pretax_income",
    "당기순이익": "net_income", "당기순이익(손실)": "net_income",
}


def financial_rows(items: list, reprt_code: str) -> list:
    """주요계정 응답 → (corp_code, fs_div)별 financials 행"""
    out = {}
    for it in items:
        col = ACCOUNTS.get(it.get("account_nm", "").strip())
        if not col:
            continue
        k = (it["corp_code"], it["fs_div"])
        r = out.setdefault(k, {"corp_code": it["corp_code"], "bsns_year": int(it["bsns_year"]),
                               "reprt_code": reprt_code, "fs_div": it["fs_div"],
                               "rcept_no": it.get("rcept_no"), "base_date": None})
        if it.get("sj_div") == "BS" and not r["base_date"]:
            r["base_date"] = to_date(it.get("thstrm_dt"))
        # 손익은 분기보고서면 누적(thstrm_add_amount) 우선
        v = num(it.get("thstrm_add_amount")) if it.get("sj_div") == "IS" else None
        if v is None:
            v = num(it.get("thstrm_amount"))
        if r.get(col) is None:
            r[col] = v
    return [r for r in out.values() if r["base_date"] and r.get("total_assets") is not None]


def is_rcps(doc: str) -> bool:
    d = re.sub(r"\s+", "", doc)
    return "상환전환우선주" in d or "전환상환우선주" in d
