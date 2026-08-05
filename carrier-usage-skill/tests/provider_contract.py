"""供所有运营商实现复用的行为契约断言。"""

from carrier_usage.models import (
    AccountSnapshot,
    Allowance,
    CapabilityResult,
    LineUsage,
    PlanInfo,
    ResourceUsage,
)
from carrier_usage.providers.base import AuthSession, CarrierProvider


async def assert_provider_results(provider: CarrierProvider) -> None:
    assert isinstance(await provider.authenticate(), AuthSession)
    assert isinstance(await provider.get_account(), AccountSnapshot)
    assert all(isinstance(item, Allowance) for item in await provider.get_allowances())
    assert isinstance(await provider.get_plan(), PlanInfo)
    assert isinstance(await provider.get_subscriptions(), CapabilityResult)
    assert all(isinstance(item, LineUsage) for item in await provider.get_lines())
    assert all(isinstance(item, ResourceUsage) for item in await provider.get_resources())
