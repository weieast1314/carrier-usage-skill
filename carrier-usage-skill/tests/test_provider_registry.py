from collections.abc import Callable

import httpx
import pytest

from carrier_usage.config import AppConfig
from carrier_usage.errors import UnsupportedCapabilityError
from carrier_usage.providers.base import CarrierProvider, create_provider, register_provider
from carrier_usage.providers.china_unicom_web import ChinaUnicomWebProvider


@pytest.mark.asyncio
async def test_unknown_provider_is_rejected() -> None:
    config = AppConfig(provider="missing", min_refresh_seconds=300)
    async with httpx.AsyncClient() as client:
        with pytest.raises(UnsupportedCapabilityError, match="未知 Provider：missing"):
            create_provider("missing", config, client)


@pytest.mark.asyncio
async def test_unicom_registry_always_creates_web_provider(tmp_path) -> None:
    config = AppConfig(
        provider="china_unicom",
        min_refresh_seconds=300,
        unicom_session_path=tmp_path / "session.json",
    )
    async with httpx.AsyncClient() as client:
        provider = create_provider("china_unicom", config, client)

    assert isinstance(provider, ChinaUnicomWebProvider)


def test_duplicate_provider_registration_is_rejected() -> None:
    factory: Callable[[AppConfig, httpx.AsyncClient], CarrierProvider]

    def factory(config: AppConfig, client: httpx.AsyncClient) -> CarrierProvider:
        raise AssertionError("注册测试不应创建 Provider")

    register_provider("contract_test", factory)

    with pytest.raises(ValueError, match="Provider 已注册：contract_test"):
        register_provider("contract_test", factory)
