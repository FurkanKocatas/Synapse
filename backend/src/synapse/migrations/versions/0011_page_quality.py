"""Text quality per page (ADR 0010, ingestion rule 3), kept so administrators can see it.

Revision ID: 0011
Revises: 0010
"""

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE document_pages
            -- Why the page needs OCR: 'no_text', 'not_turkish_like', 'ocr_artefacts'; NULL if
            -- its text layer is fine.
            ADD COLUMN quality_issue text
                CHECK (quality_issue IN ('no_text', 'not_turkish_like', 'ocr_artefacts')),
            ADD COLUMN char_score real,
            ADD COLUMN artefacts real CHECK (artefacts BETWEEN 0 AND 1),
            ADD CONSTRAINT document_pages_ocr_has_reason
                CHECK (needs_ocr = (quality_issue IS NOT NULL));
    """)


def downgrade() -> None:
    # Downgrades are not supported; recovery is by restoring a backup (ADR 0012).
    raise NotImplementedError
