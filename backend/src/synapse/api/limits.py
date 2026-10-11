"""Limits per user on the requests that cost the most (ASVS V2.4.1, V15.2.2; decided 2026-10-07):
two questions answered at once, twenty searches a minute, a hundred uploads an hour. Past one,
the request is refused with 429 ``too_many_requests`` and a Retry-After, and the screen asks the
user to wait a little and try again.

The counts live in the API process, as the chat model's queue does (one API process per
installation, ADR 0002); a restart forgets them, which costs nothing. A question holds its slot
until its answer's stream ends. A slot never given back (the connection closed before the
stream began, so nothing ran to give it back) is free again after QUESTION_LEASE, so a user is
never shut out for good.
"""

import math
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

import structlog
from fastapi import status

from synapse.api.deps import ApiError

log = structlog.get_logger(__name__)

QUESTIONS_AT_ONCE = 2
QUESTION_LEASE = 600.0  # seconds, longer than any answer takes
QUESTION_RETRY = 10  # seconds a refused question is asked to wait: about one answer


@dataclass(frozen=True)
class Rate:
    kind: str
    count: int
    seconds: float


SEARCHES = Rate("search", 20, 60.0)
UPLOADS = Rate("upload", 100, 3600.0)


class Question:
    """A question's slot; ``release`` gives it back, once."""

    def __init__(self, limits: UserLimits, user_id: UUID, started: float) -> None:
        self._limits, self._user_id, self._started = limits, user_id, started
        self._released = False

    def release(self) -> None:
        if not self._released:
            self._released = True
            self._limits.give_back(self._user_id, self._started)


class UserLimits:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._asking: dict[UUID, list[float]] = {}  # when each held slot was taken
        self._recent: dict[tuple[str, UUID], deque[float]] = {}

    def question(self, user_id: UUID) -> Question | None:
        """A slot for one more question, or None while the user has QUESTIONS_AT_ONCE."""
        now = self._clock()
        held = [t for t in self._asking.get(user_id, []) if now - t < QUESTION_LEASE]
        if len(held) >= QUESTIONS_AT_ONCE:
            self._asking[user_id] = held
            return None
        self._asking[user_id] = [*held, now]
        return Question(self, user_id, now)

    def give_back(self, user_id: UUID, started: float) -> None:
        held = self._asking.get(user_id, [])
        if started in held:
            held.remove(started)
        if not held:
            self._asking.pop(user_id, None)

    def wait(self, rate: Rate, user_id: UUID) -> float | None:
        """Counts one request of ``rate``'s kind: None while within it, else the seconds until
        the oldest request in the window leaves it (the refused request is not counted)."""
        now = self._clock()
        times = self._recent.setdefault((rate.kind, user_id), deque())
        while times and now - times[0] >= rate.seconds:
            times.popleft()
        if len(times) >= rate.count:
            return rate.seconds - (now - times[0])
        times.append(now)
        return None


def too_many(kind: str, seconds: float) -> ApiError:
    log.info("api.limited", kind=kind)
    return ApiError(
        status.HTTP_429_TOO_MANY_REQUESTS,
        "too_many_requests",
        {"Retry-After": str(max(1, math.ceil(seconds)))},
    )


def check(limits: UserLimits, rate: Rate, user_id: UUID) -> None:
    """Raises 429 when the user has used up ``rate``."""
    seconds = limits.wait(rate, user_id)
    if seconds is not None:
        raise too_many(rate.kind, seconds)
