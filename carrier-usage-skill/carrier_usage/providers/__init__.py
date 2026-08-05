"""运营商 Provider 实现与注册入口。"""

import httpx

from carrier_usage.config import AppConfig
from carrier_usage.providers.base import register_provider
from carrier_usage.providers.china_unicom_web import ChinaUnicomWebProvider


def create_china_unicom_provider(
    config: AppConfig, client: httpx.AsyncClient
) -> ChinaUnicomWebProvider:
    """创建使用扫码网页登录会话的中国联通 Provider。"""

    return ChinaUnicomWebProvider(config, client)


register_provider(ChinaUnicomWebProvider.provider_id, create_china_unicom_provider)

__all__ = ["ChinaUnicomWebProvider"]
