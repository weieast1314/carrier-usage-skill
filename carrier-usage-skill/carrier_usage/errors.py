"""稳定的业务错误和 CLI 退出码。"""


class CarrierUsageError(Exception):
    """所有可预期业务错误的基类。"""

    exit_code = 1


class ConfigurationError(CarrierUsageError):
    """配置缺失或格式无效。"""

    exit_code = 2


class AccountNotFoundError(ConfigurationError):
    """未找到指定账户。"""


class AccountAmbiguousError(ConfigurationError):
    """账户选择存在歧义。"""


class AccountConflictError(ConfigurationError):
    """账户 ID、别名或元数据发生冲突。"""


class AuthenticationError(CarrierUsageError):
    """运营商认证失败或凭据已过期。"""

    exit_code = 3


class SecondaryAuthenticationRequiredError(AuthenticationError):
    """运营商要求用户在官方页面完成二次认证。"""


class RateLimitError(CarrierUsageError):
    """查询过于频繁或被上游限流。"""

    exit_code = 4


class UpstreamChangedError(CarrierUsageError):
    """运营商响应结构已经发生变化。"""

    exit_code = 5


class NetworkError(CarrierUsageError):
    """网络、DNS、TLS 或超时错误。"""

    exit_code = 6


class UnsupportedCapabilityError(CarrierUsageError):
    """当前 Provider 不支持请求的能力。"""

    exit_code = 7
