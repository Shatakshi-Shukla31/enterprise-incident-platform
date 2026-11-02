from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import get_settings

_settings = get_settings()
_shared_store = _settings.environment == "production" and not _settings.single_process

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[_settings.rate_limit_default],
    storage_uri=_settings.redis_url if _shared_store else "memory://",
    enabled=_settings.rate_limit_enabled,
    # A Redis outage must not take the API down with it.
    in_memory_fallback_enabled=True,
    in_memory_fallback=[_settings.rate_limit_default],
    swallow_errors=True,
)
