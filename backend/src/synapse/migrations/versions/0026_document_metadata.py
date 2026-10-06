"""A document's metadata: its kind, date and number, suggested from the document when it is
read, and its tags; ``metadata_set_by_hand`` names the fields a person set, which suggestions
never replace (knowledge/metadata.py).

Revision ID: 0026
Revises: 0025
"""

from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE documents
            ADD COLUMN kind text CHECK (length(kind) BETWEEN 1 AND 80),
            ADD COLUMN document_date date,
            ADD COLUMN reference text CHECK (length(reference) BETWEEN 1 AND 120),
            ADD COLUMN tags text[] NOT NULL DEFAULT '{}' CHECK (cardinality(tags) <= 20),
            ADD COLUMN metadata_set_by_hand text[] NOT NULL DEFAULT '{}'
                CHECK (metadata_set_by_hand <@ ARRAY['kind', 'document_date', 'reference']);
        CREATE INDEX documents_tags ON documents USING gin (tags);
    """)


def downgrade() -> None:
    # Downgrades are not supported; recovery is by restoring a backup (ADR 0012).
    raise NotImplementedError
