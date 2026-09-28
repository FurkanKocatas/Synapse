from datetime import UTC, datetime, timedelta

from synapse.identity.throttle import FREE_ATTEMPTS, MAX_DELAY, blocked_until

NOW = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)


def test_first_attempts_are_free() -> None:
    for failures in range(FREE_ATTEMPTS + 1):
        assert blocked_until(failures, NOW) is None


def test_delay_doubles_from_the_fifth_failure() -> None:
    delays = [blocked_until(FREE_ATTEMPTS + n, NOW) for n in range(1, 5)]
    assert delays == [NOW + timedelta(seconds=s) for s in (1, 2, 4, 8)]


def test_delay_is_capped() -> None:
    assert blocked_until(10_000, NOW) == NOW + MAX_DELAY
