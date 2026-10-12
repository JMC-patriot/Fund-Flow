"""
DART 상장사 자금조달 이벤트(CB/BW/EB/유상증자) 수집기

흐름
  1) list.json(주요사항보고서, pblntf_ty=B)으로 기간 내 공시를 훑어서
     CB/BW/EB/유상증자 결정 공시를 낸 상장사만 추림  (3개월 단위로 분할 조회)
  2) 해당 (회사, 유형) 조합에 대해서만 상세 API 호출
  3) 숫자 컬럼 정리, rcept_no 기준 중복 제거 후 CSV 저장

전 상장사 x 4개 유형 전수 루프(약 1.1만 콜) 대신, 실제 공시가 있는 회사만 호출하므로
콜 수가 수백 단위로 줄어듭니다 (일일 한도 2만 콜).
"""
import os, io, json, time, zipfile, requests, xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
import pandas as pd
from dotenv import load_dotenv

load_dotenv()
KEY = os.environ["DART_API_KEY"]
BASE = "https://opendart.fss.or.kr/api"
S = requests.Session()

ENDPOINTS = {"CB": "cvbdIsDecsn", "BW": "bdwtIsDecsn",
             "EB": "exbdIsDecsn", "Equity": "piicDecsn"}
# list.json의 report_nm 매칭용 (공백 제거 후 비교)
REPORT_KEYWORDS = {"CB": "전환사채권발행결정",
                   "BW": "신주인수권부사채권발행결정",
                   "EB": "교환사채권발행결정",
                   "Equity": "유상증자결정"}   # '유무상증자결정'은 매칭되지 않음
LISTED = {"Y", "K", "N"}                     # 유가증권, 코스닥, 코넥스


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 저장소 루트
CACHE = os.path.join(ROOT, "cache")                               # 중간 결과 저장 (재실행 시 이어받기)
os.makedirs(CACHE, exist_ok=True)


def _cached(name, fn):
    """cache/<name>.json 이 있으면 읽고, 없으면 fn() 결과를 저장"""
    p = os.path.join(CACHE, f"{name}.json")
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    data = fn()
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    return data


def _get_json(path, **params):
    """공통 호출: 연결 끊김/타임아웃은 지수 백오프로 재시도, 요청 제한(020)은 대기"""
    global S
    for attempt in range(6):
        try:
            r = S.get(f"{BASE}/{path}", params={"crtfc_key": KEY, **params},
                      timeout=30)
            r.raise_for_status()
            j = r.json()
        except (requests.ConnectionError, requests.Timeout,
                requests.HTTPError, ValueError) as e:
            wait = 2 ** attempt * 3            # 3, 6, 12, 24, 48, 96초
            print(f"  ! {path} 재시도 {attempt + 1}/6 ({type(e).__name__}), {wait}초 대기")
            S.close()
            S = requests.Session()             # 끊긴 연결 버리고 새로
            time.sleep(wait)
            continue
        if j.get("status") == "020":          # 요청 제한 초과
            print("  ! 요청 제한(020), 60초 대기")
            time.sleep(60)
            continue
        return j
    raise RuntimeError(f"{path}: 재시도 6회 모두 실패")


def _check(j):
    if j["status"] == "013":                  # 조회 데이터 없음
        return []
    if j["status"] != "000":
        raise RuntimeError(f'{j["status"]} {j["message"]}')
    return j["list"]


# 1) 상장사 corp_code 목록 (참고/조인용)
def load_companies():
    r = S.get(f"{BASE}/corpCode.xml", params={"crtfc_key": KEY}, timeout=60)
    r.raise_for_status()
    try:
        xml = zipfile.ZipFile(io.BytesIO(r.content)).read("CORPCODE.xml")
    except zipfile.BadZipFile:                # 키 오류 등은 zip이 아닌 에러 메시지로 옴
        raise RuntimeError(f"corpCode 다운로드 실패: {r.text[:200]}")
    rows = []
    for c in ET.fromstring(xml).iter("list"):
        stock = (c.findtext("stock_code") or "").strip()
        if stock:
            rows.append({"corp_code": c.findtext("corp_code"),
                         "corp_name": c.findtext("corp_name"),
                         "stock_code": stock})
    return pd.DataFrame(rows)


# 2) 기간 내 주요사항보고서 목록 (corp_code 없이 조회 시 3개월 제한 → 분할)
def list_major_reports(bgn, end):
    start = datetime.strptime(bgn, "%Y%m%d").date()
    last = datetime.strptime(end, "%Y%m%d").date()
    today = date.today()
    out = []
    while start <= last:
        chunk_end = min(start + timedelta(days=89), last)
        b, e = start.strftime("%Y%m%d"), chunk_end.strftime("%Y%m%d")

        def fetch_chunk(b=b, e=e):
            rows, page = [], 1
            while True:
                j = _get_json("list.json", bgn_de=b, end_de=e, pblntf_ty="B",
                              page_no=page, page_count=100)
                rows += _check(j)
                if j["status"] == "013" or page >= int(j.get("total_page", 1)):
                    return rows
                page += 1
                time.sleep(0.3)

        if chunk_end < today:                  # 끝난 구간만 캐시 (오늘 포함 구간은 매번 새로)
            rows = _cached(f"list_{b}_{e}", fetch_chunk)
        else:
            rows = fetch_chunk()
        print(f"  목록 {b}~{e}: {len(rows)}건")
        out += rows
        start = chunk_end + timedelta(days=1)
    return out


# 3) 상세 이벤트 조회
def fetch_events(corp_code, ftype, bgn, end):
    j = _get_json(f"{ENDPOINTS[ftype]}.json",
                  corp_code=corp_code, bgn_de=bgn, end_de=end)
    rows = _check(j)
    for row in rows:
        row["ftype"] = ftype
    return rows


def _to_numeric(df):
    """'1,000,000' 같은 문자열 숫자를 변환 ('-' 등은 NaN)"""
    skip = {"rcept_no", "corp_code", "corp_name", "corp_cls", "ftype"}
    for col in df.columns:
        if col in skip:
            continue
        s = df[col].astype(str).str.replace(",", "").str.strip()
        num = pd.to_numeric(s, errors="coerce")
        if num.notna().sum() >= 0.8 * s.ne("-").sum() and num.notna().any():
            df[col] = num
    return df


def collect(bgn="20250101", end=None):
    end = end or date.today().strftime("%Y%m%d")

    reports = list_major_reports(bgn, end)
    targets = set()
    for rp in reports:
        if rp.get("corp_cls") not in LISTED:
            continue
        name = rp["report_nm"].replace(" ", "")
        for ftype, kw in REPORT_KEYWORDS.items():
            if kw in name:
                targets.add((rp["corp_code"], ftype))
    print(f"주요사항보고서 {len(reports)}건 → 상세 조회 대상 {len(targets)}건")

    rows = []
    for i, (corp_code, ftype) in enumerate(sorted(targets), 1):
        rows += _cached(f"ev_{ftype}_{corp_code}_{bgn}_{end}",
                        lambda: fetch_events(corp_code, ftype, bgn, end))
        time.sleep(0.3)                       # 분당 호출 과다로 인한 차단 방지
        if i % 100 == 0:
            print(f"  {i}/{len(targets)}")

    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df = df.drop_duplicates(subset=["rcept_no", "ftype"])
    return _to_numeric(df)


if __name__ == "__main__":
    print(len(load_companies()), "개 상장사")
    print(pd.DataFrame(fetch_events("00126380", "CB", "20250101", "20261011")))  # 삼성전자

    df = collect("20250101")
    df.to_csv(os.path.join(ROOT, "dart_funding_events.csv"), index=False, encoding="utf-8-sig")
    print(df.groupby("ftype").size())
