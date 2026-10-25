"""Small fixed-window throttles for public authentication endpoints."""
from rest_framework.throttling import SimpleRateThrottle


class IPScopedRateThrottle(SimpleRateThrottle):
    """Throttle by client IP without changing rates on unrelated API endpoints."""

    def get_cache_key(self, request, view):
        ident = self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}


class GovernmentLoginThrottle(IPScopedRateThrottle):
    scope = "government-login"
    rate = "10/minute"


class AccountLoginThrottle(IPScopedRateThrottle):
    scope = "account-login"
    rate = "10/minute"


class AccountRegistrationThrottle(IPScopedRateThrottle):
    scope = "account-registration"
    rate = "10/hour"
