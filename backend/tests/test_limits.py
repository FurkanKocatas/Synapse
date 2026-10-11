"""Per-user limits (api/limits.py) on a clock the test moves."""

import uuid
from dataclasses import dataclass

from synapse.api.limits import (
    QUESTION_LEASE,
    QUESTIONS_AT_ONCE,
    Question,
    Rate,
    UserLimits,
    too_many,
)


@dataclass
class Clock:
    now: float = 1000.0

    def __call__(self) -> float:
        return self.now


def take(limits: UserLimits, user: uuid.UUID) -> Question:
    slot = limits.question(user)
    assert slot is not None
    return slot


def test_two_questions_at_once_and_a_slot_given_back_frees_one() -> None:
    limits, user, other = UserLimits(Clock()), uuid.uuid4(), uuid.uuid4()
    first, _ = take(limits, user), take(limits, user)
    assert limits.question(user) is None
    take(limits, other)  # another user is not held back
    first.release()
    first.release()  # twice gives back one slot, not two
    take(limits, user)
    assert limits.question(user) is None


def test_a_slot_never_given_back_frees_itself_after_the_lease() -> None:
    clock = Clock()
    limits, user = UserLimits(clock), uuid.uuid4()
    stale = [take(limits, user) for _ in range(QUESTIONS_AT_ONCE)]
    clock.now += QUESTION_LEASE - 1
    assert limits.question(user) is None
    clock.now += 1
    take(limits, user)
    # A late release of an expired slot does not free the live one's companion.
    stale[0].release()
    take(limits, user)
    assert limits.question(user) is None


def test_a_rate_counts_within_its_window_and_says_how_long_to_wait() -> None:
    clock = Clock()
    limits, user = UserLimits(clock), uuid.uuid4()
    rate = Rate("search", 3, 60.0)
    for _ in range(3):
        assert limits.wait(rate, user) is None
        clock.now += 10
    # The first of the three, at 1000, leaves the window at 1060; it is 1030.
    assert limits.wait(rate, user) == 30.0
    assert limits.wait(rate, user) == 30.0  # a refused request is not counted
    assert limits.wait(Rate("upload", 3, 60.0), user) is None  # each kind counts apart
    assert limits.wait(rate, uuid.uuid4()) is None  # and each user
    clock.now = 1060.0
    assert limits.wait(rate, user) is None


def test_a_refusal_is_429_with_whole_seconds_to_wait() -> None:
    error = too_many("search", 0.2)
    assert (error.status_code, error.code) == (429, "too_many_requests")
    assert error.headers == {"Retry-After": "1"}
    assert too_many("upload", 41.3).headers == {"Retry-After": "42"}
