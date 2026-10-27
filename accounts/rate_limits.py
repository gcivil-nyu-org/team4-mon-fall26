"""Database-backed throttles for account access and verification email."""

import hashlib
import hmac
import ipaddress
import math
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

from .models import RateLimitBucket


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    retry_after: int = 0


def _client_ip(request):
    """Use the client address appended by the app's reverse proxy when present."""
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded_for:
        # Elastic Beanstalk's nginx proxy appends its peer to this header. Walk
        # from the trusted end and ignore private proxy addresses where possible.
        for value in reversed(forwarded_for.split(",")):
            try:
                address = ipaddress.ip_address(value.strip())
            except ValueError:
                continue
            if address.is_global:
                return str(address)

    return request.META.get("REMOTE_ADDR", "unknown") or "unknown"


def _bucket_key(scope, identifier):
    value = f"{scope}:{identifier.strip().lower()}".encode("utf-8")
    secret = settings.SECRET_KEY.encode("utf-8")
    return hmac.new(secret, value, hashlib.sha256).hexdigest()


def _status(key, max_attempts, window_seconds, now):
    bucket = RateLimitBucket.objects.filter(pk=key).only(
        "count", "window_started_at"
    ).first()
    if bucket is None or bucket.count < max_attempts:
        return RateLimitDecision(allowed=True)

    expires_at = bucket.window_started_at + timedelta(seconds=window_seconds)
    seconds_left = math.ceil((expires_at - now).total_seconds())
    if seconds_left <= 0:
        return RateLimitDecision(allowed=True)
    return RateLimitDecision(allowed=False, retry_after=seconds_left)


def _consume(key, max_attempts, window_seconds, now):
    """Atomically consume one slot, resetting expired windows as needed."""
    cutoff = now - timedelta(seconds=window_seconds)

    for _ in range(3):
        with transaction.atomic():
            updated = RateLimitBucket.objects.filter(
                pk=key,
                window_started_at__gt=cutoff,
                count__lt=max_attempts,
            ).update(count=F("count") + 1, last_seen_at=now)
            if updated:
                return RateLimitDecision(allowed=True)

            updated = RateLimitBucket.objects.filter(
                pk=key, window_started_at__lte=cutoff
            ).update(count=1, window_started_at=now, last_seen_at=now)
            if updated:
                return RateLimitDecision(allowed=True)

            try:
                # The inner savepoint keeps a duplicate-key race from marking
                # the surrounding transaction as broken.
                with transaction.atomic():
                    RateLimitBucket.objects.create(
                        bucket_key=key,
                        count=1,
                        window_started_at=now,
                        last_seen_at=now,
                    )
                return RateLimitDecision(allowed=True)
            except IntegrityError:
                pass

        decision = _status(key, max_attempts, window_seconds, now)
        if not decision.allowed:
            return decision

    return _status(key, max_attempts, window_seconds, now)


def _prune_stale_buckets(now):
    # Keep the table bounded without a scheduled job. The indexed timestamp
    # makes this a cheap cleanup on the low-volume auth endpoints.
    RateLimitBucket.objects.filter(last_seen_at__lt=now - timedelta(days=2)).delete()


def _combined_decision(decisions):
    blocked = [decision for decision in decisions if not decision.allowed]
    if not blocked:
        return RateLimitDecision(allowed=True)
    return RateLimitDecision(
        allowed=False,
        retry_after=max(decision.retry_after for decision in blocked),
    )


def consume_verification_email_request(email, request):
    """Limit signup/resend mail by recipient and source IP, including unknown emails."""
    now = timezone.now()
    _prune_stale_buckets(now)
    window = settings.VERIFICATION_EMAIL_RATE_LIMIT_WINDOW_SECONDS
    decisions = [
        _consume(
            _bucket_key("verification-email", email),
            settings.VERIFICATION_EMAIL_RATE_LIMIT_EMAIL_ATTEMPTS,
            window,
            now,
        ),
        _consume(
            _bucket_key("verification-ip", _client_ip(request)),
            settings.VERIFICATION_EMAIL_RATE_LIMIT_IP_ATTEMPTS,
            window,
            now,
        ),
    ]
    return _combined_decision(decisions)


def login_rate_limit_status(email, request):
    """Check whether another login attempt is allowed without consuming a slot."""
    now = timezone.now()
    window = settings.LOGIN_RATE_LIMIT_WINDOW_SECONDS
    decisions = [
        _status(
            _bucket_key("login-ip", _client_ip(request)),
            settings.LOGIN_RATE_LIMIT_IP_ATTEMPTS,
            window,
            now,
        )
    ]
    if email:
        decisions.append(
            _status(
                _bucket_key("login-email", email),
                settings.LOGIN_RATE_LIMIT_EMAIL_ATTEMPTS,
                window,
                now,
            )
        )
    return _combined_decision(decisions)


def record_login_failure(email, request):
    """Count a failed login by IP and, when supplied, by normalized email."""
    now = timezone.now()
    _prune_stale_buckets(now)
    window = settings.LOGIN_RATE_LIMIT_WINDOW_SECONDS
    decisions = [
        _consume(
            _bucket_key("login-ip", _client_ip(request)),
            settings.LOGIN_RATE_LIMIT_IP_ATTEMPTS,
            window,
            now,
        )
    ]
    if email:
        decisions.append(
            _consume(
                _bucket_key("login-email", email),
                settings.LOGIN_RATE_LIMIT_EMAIL_ATTEMPTS,
                window,
                now,
            )
        )
    return _combined_decision(decisions)


def clear_login_failures(email, request):
    """Reset the address and source-IP counters after a successful login."""
    keys = [_bucket_key("login-ip", _client_ip(request))]
    if email:
        keys.append(_bucket_key("login-email", email))
    RateLimitBucket.objects.filter(pk__in=keys).delete()
