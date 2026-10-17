"""API tokens that expire.

DRF tokens never expire on their own, so a stolen token would work forever.
Here a token is only valid for TOKEN_TTL_HOURS after it was issued; after
that the user must log in again and gets a fresh token.

Service accounts whose tokens are stored on other servers (Ops Central
RemoteServer.auth_token) can be listed in TOKEN_NO_EXPIRY_USERS.
"""

from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from rest_framework.authentication import TokenAuthentication
from rest_framework.authtoken.models import Token
from rest_framework.exceptions import AuthenticationFailed


def _ttl() -> timedelta | None:
    hours = float(getattr(settings, "TOKEN_TTL_HOURS", 24) or 0)
    return timedelta(hours=hours) if hours > 0 else None


def token_expired(token: Token) -> bool:
    ttl = _ttl()
    if ttl is None:
        return False
    if token.user.get_username() in getattr(settings, "TOKEN_NO_EXPIRY_USERS", ()):
        return False
    return token.created < timezone.now() - ttl


def issue_token(user) -> Token:
    """The user's token, replaced with a new one when the old one has expired."""
    token, created = Token.objects.get_or_create(user=user)
    if not created and token_expired(token):
        token.delete()
        token = Token.objects.create(user=user)
    return token


def user_for_token_key(key: str):
    """Active user for a raw token key, or None when unknown, expired or disabled."""
    key = (key or "").strip()
    if not key:
        return None
    try:
        token = Token.objects.select_related("user").get(key=key)
    except Token.DoesNotExist:
        return None
    user = token.user
    if token_expired(token) or not user.is_active or getattr(user, "is_deleted", False):
        return None
    return user


class ExpiringTokenAuthentication(TokenAuthentication):
    def authenticate_credentials(self, key):
        user, token = super().authenticate_credentials(key)
        if token_expired(token):
            raise AuthenticationFailed("Session expired. Please log in again.")
        return user, token
