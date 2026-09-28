"""Exponential backoff for failed logins (ADR 0006).

No permanent lockout, which would let anyone lock a known account out. From the fifth
consecutive failure, the subject must wait 1 s, then 2 s, 4 s ... up to 15 minutes.
"""

from datetime import datetime, timedelta

FREE_ATTEMPTS = 4
# Many users of one office often share a public IP address, so failures counted per address are
# allowed far more room before backoff starts; per-account counting stays strict.
FREE_ATTEMPTS_PER_IP = 50
MAX_DELAY = timedelta(minutes=15)
# After this many consecutive failures on one account, administrators are notified.
NOTIFY_ADMINS_AT = 20


def blocked_until(
    failures: int, last_failure_at: datetime, *, free_attempts: int = FREE_ATTEMPTS
) -> datetime | None:
    """When the next attempt is allowed after ``failures`` consecutive failures."""
    if failures <= free_attempts:
        return None
    exponent = min(failures - free_attempts - 1, 20)  # bound the shift; the cap applies below
    delay = min(timedelta(seconds=2**exponent), MAX_DELAY)
    return last_failure_at + delay
