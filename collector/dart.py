"""DART OpenAPI 호출과 값 정리 도우미"""
import io
import re
import time
import zipfile
from datetime import date
from typing import Optional

import requests

BASE = "https://opendart.fss.or.kr/api"


class BudgetExceeded(Exception):
    """이번 실행에 허용된 호출 수를 다 썼거나 DART 일일 한도(020)에 걸림"""


class Dart:
    def __init__(self, key: str, budget: int, pause: float = 0.15):
        self.key, self.budget, self.pause = key, budget, pause
        self.calls = 0
        self.s = requests.Session()

    @property
    def left(self) -> int:
        return self.budget - self.calls

    def _request(self, path, params, timeout=30):
        if self.calls >= self.budget:
            raise BudgetExceeded(f"호출 예산 {self.budget}회 소진")
        for attempt in range(6):
            try:
                self.calls += 1
                time.sleep(self.pause)
                r = self.s.get(f"{BASE}/{path}", params={"crtfc_key": self.key, **params},
                               timeout=timeout)
                r.raise_for_status()
                return r
            except requests.RequestException as e:          # 연결 끊김·타임아웃·응답 중단 등 전부 재시도
                wait = 2 ** attempt * 3
                print(f"  ! {path} 재시도 {attempt + 1}/6 ({type(e).__name__}), {wait}초 대기")
                self.s.close()
                self.s = requests.Session()
                time.sleep(wait)
        raise RuntimeError(f"{path}: 재시도 6회 모두 실패")

    def json(self, path: str, **params) -> dict:
        """status 000 → 응답, 013(데이터 없음) → {'status':'013'}, 그 외 오류는 예외"""
        for _ in range(3):
            j = self._request(f"{path}.json", params).json()
            st = j.get("status")
            if st in ("000", "013"):
                return j
            if st == "020":
                raise BudgetExceeded("DART 일일 호출 한도 초과(020)")
            if st == "800":                       # 시스템 점검
                time.sleep(60)
                continue
            raise RuntimeError(f"{path} {st} {j.get('message')}")
        raise RuntimeError(f"{path}: DART 점검 중")

    def document_text(self, rcept_no: str) -> str:
        """공시 원문(zip) 전체를 텍스트로"""
        r = self._request("document.xml", {"rcept_no": rcept_no}, timeout=60)
        try:
            z = zipfile.ZipFile(io.BytesIO(r.content))
        except zipfile.BadZipFile:
            return ""
        out = []
        for n in z.namelist():
            b = z.read(n)
            for enc in ("utf-8", "euc-kr", "cp949"):
                try:
                    out.append(b.decode(enc))
                    break
                except UnicodeDecodeError:
                    continue
        return "\n".join(out)


# ── 값 정리 ───────────────────────────────────────────────────────────
def num(v) -> Optional[float]:
    if v is None:
        return None
    s = str(v).replace(",", "").replace("%", "").strip()
    if s in ("", "-", "nan", "N/A"):
        return None
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    try:
        x = float(s)
    except ValueError:
        return None
    return -x if neg else x


def text(v) -> Optional[str]:
    if v is None:
        return None
    s = re.sub(r"\s+", " ", str(v)).strip()
    return s if s and s not in ("-", "nan") else None


def to_date(v) -> Optional[date]:
    """'2025년 03월 12일', '2025-03-12', '20250312', '2025.03.12' 모두 처리"""
    if v is None:
        return None
    d = re.findall(r"\d+", str(v))
    try:
        if len(d) == 1 and len(d[0]) == 8:
            return date(int(d[0][:4]), int(d[0][4:6]), int(d[0][6:]))
        if len(d) >= 3 and len(d[0]) == 4:
            return date(int(d[0]), int(d[1]), int(d[2]))
    except ValueError:
        pass
    return None


def clean(row: dict) -> dict:
    """원본 보관용: 의미 없는 값 제거"""
    return {k: v for k, v in row.items() if v not in (None, "", "-")}
