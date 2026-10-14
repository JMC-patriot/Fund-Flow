from datetime import date
from typing import Optional
from pydantic import BaseModel, Field


class Health(BaseModel):
    status: str
    securities: int = Field(description="유효 증권 건수")
    latest_rcept_dt: Optional[date] = Field(description="가장 최근 공시 접수일")


class TypeInfo(BaseModel):
    code: str
    label: str
    debt: bool = Field(description="만기가 있는 채무증권 여부")


class Meta(BaseModel):
    types: list[TypeInfo]
    first_issue: Optional[date]
    last_issue: Optional[date]
    last_loaded: Optional[str] = Field(description="마지막 적재 시각")
    pending_filings: int = Field(description="아직 수집하지 않은 공시 수 (초기 적재 진행 상황)")


class MacroPoint(BaseModel):
    period: str = Field(examples=["2025", "2025-03"])
    sec_type: str
    amount: float
    count: int
    companies: int
    hybrid_amount: float = Field(0, description="그중 신종자본증권(영구채·조건부자본증권 포함) 금액")
    hybrid_count: int = 0


class Security(BaseModel):
    id: str
    corp_code: str
    corp_name: str
    stock_code: Optional[str]
    corp_cls: Optional[str]
    sec_type: str
    source: str = Field(description="decision 주요사항보고서 / bond_rs 채무증권 신고서 / equity_rs 지분증권 신고서 / periodic 정기보고서")
    offering: Optional[str] = Field(description="공모 / 사모")
    name: Optional[str]
    series: Optional[str] = Field(description="회차")
    rcept_dt: Optional[date]
    issue_date: Optional[date]
    amount: Optional[float]
    coupon: Optional[float] = Field(description="표면이자율(%)")
    ytm: Optional[float] = Field(description="만기이자율(%)")
    maturity_date: Optional[date]
    days_left: Optional[int] = Field(description="오늘 기준 잔존일수")
    conv_price: Optional[float] = Field(description="전환·행사·교환가액 (유상증자·IPO는 주당 발행가)")
    refix_floor: Optional[float] = Field(description="리픽싱 최저 조정가액")
    conv_start: Optional[date]
    conv_end: Optional[date]
    underlying: Optional[str]
    shares: Optional[float]
    dilution_pct: Optional[float]
    rating: Optional[str]
    grade: Optional[str] = Field(None, description="정규화한 신용등급 (예: AA-, A1)")
    hybrid: bool = Field(False, description="신종자본증권 여부 (신종자본·영구·조건부자본 명칭이거나 만기 30년 이상)")
    repaid: Optional[str] = Field(description="상환 / 미상환 / 일부상환 (정기보고서 기준)")
    repaid_asof: Optional[date]
    method: Optional[str]
    underwriter: Optional[str]
    dart_url: Optional[str]


class SecurityPage(BaseModel):
    total: int
    total_amount: float
    items: list[Security]


class MaturityBucket(BaseModel):
    bucket: str = Field(examples=["0-3m"])
    sec_type: str
    amount: float
    count: int


class CompanyHit(BaseModel):
    corp_code: str
    corp_name: str
    stock_code: Optional[str]
    corp_cls: Optional[str]
    outstanding: float = Field(description="잔존 채무증권 금액")
    total_amount: float
    count: int


class TypeTotal(BaseModel):
    sec_type: str
    amount: float
    count: int
    outstanding: float


class Company(BaseModel):
    corp_code: str
    corp_name: str
    stock_code: Optional[str]
    corp_cls: Optional[str]
    totals: list[TypeTotal]


class Financial(BaseModel):
    bsns_year: int
    reprt_code: str
    report: str
    fs_div: str
    base_date: date
    current_assets: Optional[float]
    noncurrent_assets: Optional[float]
    total_assets: Optional[float]
    current_liab: Optional[float]
    noncurrent_liab: Optional[float]
    total_liab: Optional[float]
    capital: Optional[float]
    retained: Optional[float]
    total_equity: Optional[float]
    revenue: Optional[float]
    op_income: Optional[float]
    pretax_income: Optional[float]
    net_income: Optional[float]
    debt_ratio: Optional[float] = Field(description="부채비율(%) = 부채/자본")
    equity_ratio: Optional[float] = Field(description="자기자본비율(%) = 자본/자산")
    current_ratio: Optional[float] = Field(description="유동비율(%) = 유동자산/유동부채")
    op_margin: Optional[float] = Field(description="영업이익률(%)")


class StatementLine(BaseModel):
    sj_div: str = Field(description="BS 재무상태표 / IS 손익계산서 / CIS 포괄손익 / CF 현금흐름표 / SCE 자본변동표")
    sj_nm: Optional[str]
    account_nm: str
    depth: int = 0
    this: Optional[float] = Field(description="당기")
    prev: Optional[float] = Field(description="전기")
    prev2: Optional[float] = Field(description="전전기")


class Statements(BaseModel):
    corp_code: str
    bsns_year: int
    reprt_code: str
    fs_div: str
    lines: list[StatementLine]


class Source(BaseModel):
    name: str
    api: str
    used_for: str


class CompareLine(BaseModel):
    account_nm: str
    values: list[Optional[float]] = Field(description="columns와 같은 순서의 금액(원)")


class CompareSection(BaseModel):
    sj_div: str = Field(description="BS 재무상태표 / IS 손익계산서 / CIS 포괄손익 / CF 현금흐름표 / SCE 자본변동표")
    sj_nm: str
    columns: list[str] = Field(description="예: 2026 반기 누적, 2025 반기 누적 (전년동기), 2025 연간 …")
    lines: list[CompareLine]


class StatementCompare(BaseModel):
    corp_code: str
    fs_div: str
    basis: str = Field(description="사용한 보고서")
    sections: list[CompareSection]


class BenchMetric(BaseModel):
    key: str
    label: str
    unit: str = Field(description="% / 년 / 원")
    value: Optional[float] = Field(description="이 증권의 값")
    n: int = Field(description="비교 가능한 표본 수")
    p10: Optional[float] = None
    p25: Optional[float] = None
    p50: Optional[float] = None
    p75: Optional[float] = None
    p90: Optional[float] = None
    percentile: Optional[float] = Field(None, description="이 증권 값의 표본 내 백분위 (0~100, 높을수록 값이 큼)")


class BenchPeer(BaseModel):
    id: str
    corp_code: str
    corp_name: str
    issue_date: Optional[date]
    amount: Optional[float]
    grade: Optional[str]
    tenor: Optional[float] = Field(description="만기(년)")
    coupon: Optional[float]
    ytm: Optional[float]
    refix_ratio: Optional[float] = Field(description="리픽싱 하한 / 전환가 (%)")
    dilution_pct: Optional[float]
    method: Optional[str]


class Benchmark(BaseModel):
    id: str
    sec_type: str
    basis: str = Field(description="비교 대상 기준 설명")
    n: int
    metrics: list[BenchMetric]
    peers: list[BenchPeer] = Field(description="발행일이 가까운 비교 대상 최대 15건")


class OverhangItem(BaseModel):
    id: str
    corp_code: str
    corp_name: str
    stock_code: Optional[str]
    market: Optional[str]
    sec_type: str
    offering: Optional[str]
    name: Optional[str]
    series: Optional[str]
    issue_date: Optional[date]
    maturity_date: Optional[date]
    amount: Optional[float]
    conv_price: Optional[float] = Field(description="전환·행사·교환가액")
    refix_floor: Optional[float]
    conv_start: Optional[date]
    conv_end: Optional[date]
    underlying: Optional[str] = Field(description="전환·교환 대상 주식")
    ref_name: Optional[str] = Field(description="주가를 가져온 종목 (EB는 교환 대상 회사)")
    close: Optional[float] = Field(description="최근 거래일 종가")
    moneyness: Optional[float] = Field(description="종가 ÷ 전환가 × 100 (%). 100 이상이면 전환 시 이익")
    shares: Optional[float] = Field(description="전환·행사 가능 주식수 (발행 시점 기준, 없으면 금액÷전환가)")
    list_shrs: Optional[float]
    dilution: Optional[float] = Field(description="전환 가능 주식수 ÷ 현재 상장주식수 (%)")
    value: Optional[float] = Field(description="전환 가능 주식수 × 종가 (원)")
    status: str = Field(description="청구 전 / 청구 가능")
    days_to_start: Optional[int]
    warn: Optional[str] = Field(None, description="수치가 비정상적일 때 사유 (주식 병합·액면 변경 등)")
    remaining: Optional[float] = Field(None, description="최신 미전환·미행사·미교환 잔액(원)")
    balance_asof: Optional[date] = Field(None, description="잔액 기준일 (공시일)")
    balance_source: Optional[str] = Field(None, description="공시: 행사·조정·만기전취득 공시 / 발행 기준: 이후 공시 없음")
    conv_price_now: Optional[float] = Field(None, description="현재 전환가 (조정 반영)")


class OverhangCompany(BaseModel):
    corp_code: str
    corp_name: str
    stock_code: Optional[str]
    market: Optional[str]
    count: int
    amount: float
    shares: float
    dilution: Optional[float] = Field(description="회사 주식으로 전환되는 물량 합 ÷ 상장주식수 (%)")
    itm_shares: float = Field(description="그중 현재 이익 구간(종가 ≥ 전환가) 물량")
    value: float
    next_start: Optional[date] = Field(description="아직 청구 전인 것 중 가장 빠른 청구 시작일")
    close: Optional[float]
    warn: bool = Field(False, description="확인이 필요한 증권이 섞여 있음")


class OverhangPage(BaseModel):
    as_of: Optional[date] = Field(description="주가 기준일")
    total: int
    total_value: float
    itm_count: int
    upcoming_3m_value: float
    items: list[OverhangItem]
    companies: list[OverhangCompany]


class CompanyOverhangItem(BaseModel):
    id: str
    sec_type: str
    series: Optional[str]
    name: Optional[str]
    offering: Optional[str]
    issue_date: Optional[date]
    maturity_date: Optional[date]
    amount: Optional[float] = Field(description="발행액(원)")
    conv_price0: Optional[float] = Field(description="최초 전환가")
    conv_price: Optional[float] = Field(description="현재 전환가 (조정 반영)")
    refix_floor: Optional[float]
    conv_start: Optional[date]
    conv_end: Optional[date]
    remaining: Optional[float] = Field(description="남은 잔액(원). 잔존이 아니면 0")
    released: Optional[float] = Field(description="전환·상환으로 줄어든 금액(원)")
    shares: Optional[float] = Field(description="남은 전환 가능 주식수")
    dilution: Optional[float] = Field(description="남은 주식수 ÷ 상장주식수 (%)")
    moneyness: Optional[float] = Field(description="종가 ÷ 현재 전환가 × 100")
    own_stock: bool = Field(description="이 회사 주식으로 전환·교환되는지 (타사주 EB는 false)")
    underlying: Optional[str]
    state: str = Field(description="잔존 / 전량 전환·상환 / 만기 경과 / 상환 / 청구기간 종료")
    balance_asof: Optional[date]
    balance_source: str
    dart_url: Optional[str]


class CompanyOverhang(BaseModel):
    corp_code: str
    close: Optional[float]
    list_shrs: Optional[float]
    as_of: Optional[date] = Field(description="주가 기준일")
    remaining: float = Field(description="잔존 잔액 합계 (이 회사 주식으로 바뀌는 것만)")
    shares: float = Field(description="잠재 오버행 주식수")
    dilution: Optional[float] = Field(description="잠재 오버행 ÷ 상장주식수 (%)")
    value: Optional[float] = Field(description="잠재 오버행 × 종가 (원)")
    items: list[CompanyOverhangItem]


class LeagueRow(BaseModel):
    rank: int
    underwriter: str
    lead_amount: float = Field(description="대표주관 금액 (공동 대표주관은 균등 배분, 원)")
    deals: int = Field(description="대표주관 건수")
    share: float = Field(description="대표주관 금액 점유율 (%)")
    underwritten: float = Field(description="인수 금액 합계 (인수단 참여 포함, 원)")
    fee_rate: Optional[float] = Field(None, description="평균 인수수수료율 (%), 인수금액 가중")
    prev_rank: Optional[int] = Field(None, description="직전 연도 순위 (연도 선택 시)")


class LeagueDeal(BaseModel):
    rcept_no: str
    corp_code: str
    corp_name: str
    issue_date: Optional[date]
    amount: float
    leads: list[str]
    grade: Optional[str]
    detail: Optional[str] = Field(description="회차·만기·금리 또는 공모가·방식")
    dart_url: str


class League(BaseModel):
    category: str
    period: str
    total_amount: float
    total_deals: int
    rows: list[LeagueRow]
