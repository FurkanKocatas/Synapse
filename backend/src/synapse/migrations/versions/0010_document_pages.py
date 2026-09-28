"""Extracted text per page of a document version (ADR 0010).

A "page" is the unit a citation points to: a PDF page, a slide, a spreadsheet sheet. Word files
have no pages until they are rendered, so their text is one unit of kind ``document`` for now.

``needs_ocr`` marks pages whose text layer is missing or unusable; the OCR step fills them.
The version status gains ``parsed``: text extracted, waiting for indexing.

Revision ID: 0010
Revises: 0009
"""

from alembic import op

from synapse.migrations.sql_helpers import tenant_rls

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE document_pages (
            tenant_id   uuid NOT NULL,
            version_id  uuid NOT NULL,
            number      integer NOT NULL CHECK (number >= 1),
            kind        text NOT NULL CHECK (kind IN ('page', 'slide', 'sheet', 'document')),
            -- A sheet's name, for example; NULL where the number says everything.
            label       text CHECK (length(label) <= 200),
            text        text NOT NULL,
            needs_ocr   boolean NOT NULL,
            PRIMARY KEY (tenant_id, version_id, number),
            FOREIGN KEY (tenant_id, version_id) REFERENCES document_versions (tenant_id, id)
                ON DELETE CASCADE
        );

        ALTER TABLE document_versions DROP CONSTRAINT document_versions_status_check;
        ALTER TABLE document_versions ADD CONSTRAINT document_versions_status_check
            CHECK (status IN ('queued', 'parsing', 'parsed', 'ocr', 'embedding', 'ready',
                              'failed'));
    """)
    op.execute(tenant_rls("document_pages"))


def downgrade() -> None:
    # Downgrades are not supported; recovery is by restoring a backup (ADR 0012).
    raise NotImplementedError
