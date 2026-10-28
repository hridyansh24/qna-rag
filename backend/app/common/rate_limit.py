import uuid

from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config import settings


def _rate_limit_key(request):
    # Dev: all traffic shares one Docker-internal IP — return a UUID so limits
    # never fire during local development.
    if settings.is_development:
        return str(uuid.uuid4())
    # Production: the socket peer is nginx, so key on the client address it
    # forwards. nginx sets X-Real-IP to $remote_addr with proxy_set_header,
    # which replaces any copy the client sent, and the backend is reachable
    # only through nginx (only port 80 is published on the VM).
    return request.headers.get("X-Real-IP") or get_remote_address(request)


# Counters live in Redis in production, so they're shared and survive
# restarts and redeploys. If Redis is unreachable the limiter falls back to
# per-process memory instead of failing logins. Development keys are random
# per request anyway, so there's nothing worth storing there.
limiter = Limiter(
    key_func=_rate_limit_key,
    storage_uri="memory://" if settings.is_development else settings.REDIS_URL,
    in_memory_fallback_enabled=True,
)
