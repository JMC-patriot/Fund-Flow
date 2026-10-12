from datetime import date
from typing import Optional
from pydantic import BaseModel, Field


class Health(BaseModel):
    status: str
    events: int = Field(description="적재된 공시 건수")
    latest_rcept_dt: Optional[date] = Field(description="가장 최근 공시 접수일")


class Source(BaseModel):
    name: str = Field(description="데이터 명칭")
    api: str = Field(description="DART OpenAPI 엔드포인트")
    provider: str = Field(description="제공 기관")
    url: str = Field(description="출처 URL")
    fields: str = Field(description="활용 항목")


class Summary(BaseModel):
    ftype: str = Field(description="CB / BW / EB / Equity")
    label: str
    total_amount: float = 0
    events: int = 0
    companies: int = 0
    avg_amount: Optional[float] = None
    avg_dilution_pct: Optional[float] = None
    first_dt: Optional[date] = None
    last_dt: Optional[date] = None


class MonthlyPoint(BaseModel):
    month: str = Field(examples=["2025-03"])
    ftype: str
    total_amount: float
    events: int


class Scenario(BaseModel):
    label: str = Field(description="발행 전 / 발행 직후 / 전액 전환·행사·교환 후 / 증자 후")
    total_assets: float
    total_liabilities: float
    total_equity: float
    debt_ratio: Optional[float] = Field(description="부채비율(%) = 부채/자본. 자본잠식이면 null")
    equity_ratio: Optional[float] = Field(description="자기자본비율(%) = 자본/자산")


class BaseFinancials(BaseModel):
    report: str = Field(description="기준 보고서", examples=["2025년 반기보고서"])
    fs_div: str = Field(description="연결 / 별도")
    base_date: date
    total_assets: float
    total_liabilities: float
    total_equity: float


class ImpactFields(BaseModel):
    amount_to_equity_pct: Optional[float] = Field(None, description="발행금액 / 자기자본 (%)")
    base: Optional[BaseFinancials] = Field(None, description="발행 직전 재무제표. 없으면 null")
    scenarios: Optional[list[Scenario]] = None


class Ranking(ImpactFields):
    rank: int
    corp_code: str
    corp_name: str
    stock_code: Optional[str]
    total_amount: float = Field(description="기간 내 해당 유형 발행금액 합계(원)")
    events: int
    dilution_pct: Optional[float] = Field(description="희석률 합계(%)")
    last_rcept_dt: date
    main_rcept_no: str = Field(description="최대 규모 공시 접수번호")


class Impact(ImpactFields):
    corp_code: str
    corp_name: str
    ftype: str
    total_amount: float
    events: int
    dilution_pct: Optional[float]


class Event(BaseModel):
    rcept_no: str
    corp_code: str
    corp_name: str
    ftype: str
    rcept_dt: date
    board_date: Optional[date]
    amount: float
    dilution_pct: Optional[float]
    exercise_price: Optional[float] = Field(description="전환·행사·교환가액")
    coupon_rate: Optional[float] = Field(description="표면이자율(%)")
    ytm_rate: Optional[float] = Field(description="만기이자율(%)")
    maturity_date: Optional[date]
    method: Optional[str] = Field(description="유상증자 방식")
    superseded: bool
    dart_url: str


class TypeTotal(BaseModel):
    ftype: str
    total_amount: float
    events: int


class Company(BaseModel):
    corp_code: str
    corp_name: str
    stock_code: Optional[str]
    corp_cls: Optional[str]
    totals: list[TypeTotal]
