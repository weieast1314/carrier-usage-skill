"""与运营商无关的不可变数据模型。"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum


class Capability(str, Enum):
    ACCOUNT = "account"
    BALANCE = "balance"
    BILLS = "bills"
    PAYMENTS = "payments"
    INVOICES = "invoices"
    REBATES = "rebates"
    CONTRACT_BILLS = "contract_bills"
    USAGE_DETAILS_SECONDARY_AUTH = "usage_details_secondary_auth"
    ALLOWANCES = "allowances"
    PLAN = "plan"
    SUBSCRIPTIONS = "subscriptions"
    MEMBERS = "members"
    RESOURCES = "resources"


class QueryScope(str, Enum):
    OVERVIEW = "overview"
    DATA = "data"
    VOICE = "voice"
    SMS = "sms"
    MEMBERS = "members"
    RESOURCES = "resources"
    ALL = "all"


class Status(str, Enum):
    AVAILABLE = "available"
    PARTIAL = "partial"
    UNSUPPORTED = "unsupported"


class AllowanceCategory(str, Enum):
    DATA = "data"
    VOICE = "voice"
    SMS = "sms"


class AllowanceScope(str, Enum):
    GENERAL = "general"
    EXCLUSIVE = "exclusive"
    REGIONAL = "regional"
    OTHER = "other"


class AllowanceUnit(str, Enum):
    BYTE = "byte"
    SECOND = "second"
    COUNT = "count"


class LineRole(str, Enum):
    PRIMARY = "primary"
    SECONDARY = "secondary"
    MEMBER = "member"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class AccountSnapshot:
    phone_masked: str | None
    balance_cny: Decimal | None
    current_charges_cny: Decimal | None
    amount_due_cny: Decimal | None
    loyalty_points: int | None = None

    def __post_init__(self) -> None:
        if self.loyalty_points is not None and self.loyalty_points < 0:
            raise ValueError("loyalty_points must be non-negative")


@dataclass(frozen=True, slots=True)
class PlanInfo:
    status: Status
    name: str | None = None
    monthly_fee_cny: Decimal | None = None
    effective_at: datetime | None = None
    expires_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class Allowance:
    category: AllowanceCategory
    scope: AllowanceScope
    name: str | None
    unit: AllowanceUnit
    total: int | None
    used: int | None
    remaining: int | None
    overage: int | None
    unlimited: bool
    effective_at: datetime | None = None
    expires_at: datetime | None = None
    raw_type: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("total", "used", "remaining", "overage"):
            value = getattr(self, field_name)
            if value is not None and value < 0:
                raise ValueError(f"{field_name} must be non-negative")


@dataclass(frozen=True, slots=True)
class LineUsage:
    phone_masked: str
    role: LineRole
    allowances: tuple[Allowance, ...]

    def __post_init__(self) -> None:
        if "*" not in self.phone_masked:
            raise ValueError("成员号码必须脱敏")


@dataclass(frozen=True, slots=True)
class ResourceUsage:
    name: str
    tier: str | None
    used: int | None
    total: int | None
    status: str | None

    def __post_init__(self) -> None:
        for field_name in ("used", "total"):
            value = getattr(self, field_name)
            if value is not None and value < 0:
                raise ValueError(f"{field_name} must be non-negative")


@dataclass(frozen=True, slots=True)
class Subscription:
    name: str
    fee_cny: Decimal | None = None
    effective_at: datetime | None = None
    expires_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class CapabilityResult:
    status: Status
    items: tuple[Subscription, ...] = ()


@dataclass(frozen=True, slots=True)
class CarrierSnapshot:
    schema_version: str
    provider: str
    account: AccountSnapshot
    plan: PlanInfo
    allowances: tuple[Allowance, ...]
    subscriptions: CapabilityResult
    queried_at: datetime
    account_id: str | None = None
    account_alias: str | None = None
    lines: tuple[LineUsage, ...] = ()
    resources: tuple[ResourceUsage, ...] = ()
    warnings: tuple[str, ...] = ()
