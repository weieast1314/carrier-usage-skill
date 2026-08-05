"""可扩展的运营商 Provider 协议和注册表。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import httpx

from carrier_usage.config import AppConfig
from carrier_usage.errors import UnsupportedCapabilityError
from carrier_usage.models import (
    AccountSnapshot,
    Allowance,
    Capability,
    CapabilityResult,
    LineUsage,
    PlanInfo,
    QueryScope,
    ResourceUsage,
)


@dataclass(frozen=True, slots=True)
class AuthSession:
    """不暴露 Provider 凭据的通用认证会话标记。"""

    provider: str


@runtime_checkable
class CarrierProvider(Protocol):
    """所有运营商实现都必须满足的最小协议。"""

    provider_id: str

    def capabilities(self) -> frozenset[Capability]: ...

    async def authenticate(self) -> AuthSession: ...

    async def get_account(self) -> AccountSnapshot: ...

    async def get_allowances(
        self, scope: QueryScope = QueryScope.OVERVIEW
    ) -> tuple[Allowance, ...]: ...

    async def get_plan(self) -> PlanInfo: ...

    async def get_subscriptions(self) -> CapabilityResult: ...

    async def get_lines(self) -> tuple[LineUsage, ...]: ...

    async def get_resources(self) -> tuple[ResourceUsage, ...]: ...


ProviderFactory = Callable[[AppConfig, httpx.AsyncClient], CarrierProvider]
_PROVIDERS: dict[str, ProviderFactory] = {}


def register_provider(provider_id: str, factory: ProviderFactory) -> None:
    """注册一个 Provider 工厂，并拒绝歧义覆盖。"""

    if provider_id in _PROVIDERS:
        raise ValueError(f"Provider 已注册：{provider_id}")
    _PROVIDERS[provider_id] = factory


def create_provider(
    provider_id: str, config: AppConfig, client: httpx.AsyncClient
) -> CarrierProvider:
    """按稳定标识创建 Provider。"""

    factory = _PROVIDERS.get(provider_id)
    if factory is None:
        raise UnsupportedCapabilityError(f"未知 Provider：{provider_id}")
    provider = factory(config, client)
    assert_provider_contract(provider)
    return provider


def assert_provider_contract(provider: CarrierProvider) -> None:
    """尽早发现 Provider 的基础契约错误。"""

    if not provider.provider_id.strip():
        raise ValueError("Provider ID 不能为空")
    capabilities = provider.capabilities()
    if not isinstance(capabilities, frozenset):
        raise TypeError("Provider 能力必须使用 frozenset 返回")
    if not all(isinstance(capability, Capability) for capability in capabilities):
        raise TypeError("Provider 返回了未知能力")
