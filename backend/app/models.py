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
