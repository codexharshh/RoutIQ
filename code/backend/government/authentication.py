"""Timed bearer authentication for the separate government-user database."""

from django.core import signing
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

from .models import GovUser


GOV_TOKEN_MAX_AGE_SECONDS = 60 * 60
_gov_signer = signing.TimestampSigner(salt="routiq.government.bearer.v1")


def issue_gov_token(user: GovUser) -> str:
    """Issue a signed, time-limited token containing only the government user ID."""
    if not user or not user.pk or not user.is_active:
        raise ValueError("An active government user is required.")
    return _gov_signer.sign(str(user.pk))


class GovTokenAuthentication(BaseAuthentication):
    """Validate bearer tokens for GovUser records stored on the government DB alias."""

    def authenticate(self, request):
        auth_header = request.META.get("HTTP_AUTHORIZATION", "")
        if not auth_header:
            return None

        try:
            prefix, token = auth_header.split(" ", 1)
        except ValueError:
            return None

        if prefix.lower() != "bearer":
            return None
        if not token.strip():
            raise AuthenticationFailed("Invalid or expired government token.")

        try:
            user_id = _gov_signer.unsign(
                token.strip(),
                max_age=GOV_TOKEN_MAX_AGE_SECONDS,
            )
            user = GovUser.objects.using("government").get(
                pk=user_id,
                is_active=True,
            )
        except (signing.BadSignature, signing.SignatureExpired, ValueError, GovUser.DoesNotExist):
            raise AuthenticationFailed("Invalid or expired government token.") from None

        return user, token

    def authenticate_header(self, request):
        return "Bearer"
