"""The audit CSV export, without a database."""

import csv
import io
import uuid
from datetime import UTC, datetime

from synapse.audit.browse import CSV_COLUMNS, StoredEvent, as_csv


def event(name: str, email: str) -> StoredEvent:
    return StoredEvent(
        seq=1,
        id=uuid.uuid4(),
        occurred_at=datetime(2026, 10, 6, tzinfo=UTC),
        actor_user_id=uuid.uuid4(),
        actor_name=name,
        actor_email=email,
        actor_ip=None,
        action="test.csv",
        target_type=None,
        target_id=None,
        outcome="success",
        details={"note": "=1+1"},
        schema_version=1,
        prev_hash="0" * 64,
        hash="1" * 64,
    )


def rows(text: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(text.removeprefix("\ufeff")), delimiter=";"))


def test_text_a_spreadsheet_would_run_as_a_formula_stays_text() -> None:
    for name in ('=HYPERLINK("http://x","y")', "+1", "-1", "@SUM(A1)", "\uff1d1", "\t=1"):
        [row] = rows(as_csv([event(name, "a@example.org")]))
        assert row["actor_name"] == "'" + name


def test_other_values_are_written_as_they_are() -> None:
    [row] = rows(as_csv([event("Ayşe Yılmaz", "ayse@example.org")]))
    assert row["actor_name"] == "Ayşe Yılmaz"
    assert row["actor_email"] == "ayse@example.org"
    assert row["actor_ip"] == ""
    assert row["seq"] == "1"
    # the details are JSON: they start with a brace, whatever is inside them
    assert row["details"] == '{"note":"=1+1"}'
    assert list(row) == list(CSV_COLUMNS)
