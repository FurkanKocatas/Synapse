"""Where a page's text came from, and the OCR's second reading (docs/benchmarks/ocr.md).

- ``text_source``: ``layer`` (the file's own text) or ``ocr``.
- ``ocr_engine``: set once OCR has read the page, whichever text the page kept; NULL until then,
  which is how a retried OCR job finds the pages it still has to read.
- ``extra_identifiers``: identifiers the second engine read that the text lacks. Search terms
  only: two in five were wrong in the benchmark, so they are never shown as text.
- ``uncertain_identifiers``: identifiers in the text the second engine did not read, so an
  answer quoting one can say it may be misread.

Revision ID: 0012
Revises: 0011
"""

from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE document_pages
            ADD COLUMN text_source text NOT NULL DEFAULT 'layer'
                CHECK (text_source IN ('layer', 'ocr')),
            ADD COLUMN ocr_engine text CHECK (length(ocr_engine) <= 100),
            ADD COLUMN extra_identifiers text[] NOT NULL DEFAULT '{}',
            ADD COLUMN uncertain_identifiers text[] NOT NULL DEFAULT '{}',
            ADD CONSTRAINT document_pages_ocr_text_has_engine
                CHECK (text_source = 'layer' OR ocr_engine IS NOT NULL),
            ADD CONSTRAINT document_pages_only_read_pages_have_readings
                CHECK (ocr_engine IS NOT NULL
                       OR (extra_identifiers = '{}' AND uncertain_identifiers = '{}'));
    """)


def downgrade() -> None:
    # Downgrades are not supported; recovery is by restoring a backup (ADR 0012).
    raise NotImplementedError
