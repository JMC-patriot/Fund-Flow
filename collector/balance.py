"""메자닌 잔액 공시(거래소 공시) 원문 파싱: 행사·전환가액 조정·만기전 사채취득"""
import re
from typing import Optional

from dart import num


def kind_of(report_nm: str) -> Optional[str]:
    n = re.sub(r"\s+", "", report_nm or "")
    if "가액" in n and "조정" in n:
        return "REFIX"
    if "만기전사채취득" in n:
        return "REDEEM"
    if any(k in n for k in ("전환청구권행사", "신주인수권행사", "교환청구권행사")):
        return "EXERCISE"
    return None


def plain_text(doc: str) -> str:
    t = re.sub(r"<style.*?</style>", " ", doc, flags=re.S | re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    t = re.sub(r"&nbsp;|&#160;", " ", t)
    return re.sub(r"\s+", " ", t)


def series_key(v) -> Optional[str]:
    """'제11회차', '11', '1-5' → '11' / '1' (앞 숫자)"""
    m = re.search(r"\d+", str(v or ""))
    return str(int(m.group())) if m else None


_CUR = r"(?:\s*\(?[A-Z]{3}\)?\s*:?\s*[^\d]{0,30})?"     # 'KRW : South-Korean Won' 같은 통화 표기
_N = r"([\d,]+(?:\.\d+)?)"


def parse(text: str, kind: str) -> list:
    """→ [{series, remaining, conv_price, shares}]"""
    out = []
    if kind == "EXERCISE":
        i = text.rfind("잔액")
        seg = text[i:] if i >= 0 else ""
        pat = re.compile(r"(?<![\d,])(\d{1,3}(?:-\d+)?)\s+" + _N + _CUR + r"\s+" + _N + _CUR + r"\s+" + _N + r"\s+" + _N)
        for m in pat.finditer(seg):
            s, issued, remain, price, shares = m.groups()
            if num(issued) and num(issued) >= 1e6:      # 발행총액이 너무 작으면 다른 표의 숫자
                out.append(dict(series=series_key(s), remaining=num(remain), conv_price=num(price), shares=num(shares)))
    elif kind == "REFIX":
        prices = {}
        m3 = re.search(r"조정에 관한 사항(.*?)(?:4\.|전환ㆍ행사ㆍ교환가능)", text)
        if m3:
            for s, before, after in re.findall(r"(?<![\d,])(\d{1,3}(?:-\d+)?)\s+" + _N + r"\s+" + _N, m3.group(1)):
                prices[series_key(s)] = num(after)
        m4 = re.search(r"가능\s*주식수\s*변동(.*?)(?:5\.|조정사유)", text)
        if m4:
            for s, remain, before, after in re.findall(r"(?<![\d,])(\d{1,3}(?:-\d+)?)\s+" + _N + r"\s+" + _N + r"\s+" + _N, m4.group(1)):
                if num(remain) and num(remain) >= 1e5:
                    out.append(dict(series=series_key(s), remaining=num(remain), conv_price=prices.get(series_key(s)),
                                    shares=num(after)))
        if not out:
            for s, p in prices.items():
                out.append(dict(series=s, remaining=None, conv_price=p, shares=None))
    elif kind == "REDEEM":
        ms = re.search(r"(\d{1,3})\s*회차", text)
        mp = re.search(r"(?:전환|교환|행사)가액\s*\(원\)\s*" + _N, text)
        mr = re.search(r"취득\s*후\s*사채의\s*권면.{0,40}?\(통화단위\)\s*" + _N, text)
        if ms and mr:
            remain, price = num(mr.group(1)), num(mp.group(1)) if mp else None
            out.append(dict(series=series_key(ms.group(1)), remaining=remain, conv_price=price,
                            shares=round(remain / price) if remain is not None and price else None))
    return [o for o in out if o["series"]]
