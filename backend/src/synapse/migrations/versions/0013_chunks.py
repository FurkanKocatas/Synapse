"""Page structure, chunks and their typed entities (ADR 0010, ingestion rules 6 to 8).

- ``document_pages.blocks``: the page's blocks in reading order (knowledge/structure.py), what
  chunking reads. Written by parsing, and again by OCR when a page takes the OCR text.
- ``document_chunks``: the units search will index, in order, with their heading path and
  pages. ``content_hash`` finds exact duplicates (indexed), ``simhash`` near ones.
- ``chunk_entities``: dates, decision and law numbers, articles, amounts and parcels found in
  a chunk, as written and normalised; exact identifier lookup reads ``(kind, value)``.
  ``char_start`` is an offset into the chunk's indexed text: its heading path, one line per
  heading, then its text (knowledge/chunking.py, ``indexed_text``).

Revision ID: 0013
Revises: 0012
"""

from alembic import op

from synapse.migrations.sql_helpers import tenant_rls

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE document_pages ADD COLUMN blocks jsonb NOT NULL DEFAULT '[]'
            CHECK (jsonb_typeof(blocks) = 'array');

        CREATE TABLE document_chunks (
            tenant_id    uuid NOT NULL,
            version_id   uuid NOT NULL,
            ordinal      integer NOT NULL CHECK (ordinal >= 0),
            kind         text NOT NULL CHECK (kind IN ('text', 'table', 'table_summary')),
            text         text NOT NULL CHECK (text <> ''),
            heading_path text[] NOT NULL,
            page_start   integer NOT NULL CHECK (page_start >= 1),
            page_end     integer NOT NULL,
            tokens       integer NOT NULL CHECK (tokens > 0),
            content_hash bytea NOT NULL CHECK (length(content_hash) = 32),
            simhash      bigint NOT NULL,
            PRIMARY KEY (tenant_id, version_id, ordinal),
            CHECK (page_end >= page_start),
            FOREIGN KEY (tenant_id, version_id) REFERENCES document_versions (tenant_id, id)
                ON DELETE CASCADE
        );
        CREATE INDEX document_chunks_duplicates ON document_chunks (tenant_id, content_hash);

        CREATE TABLE chunk_entities (
            tenant_id  uuid NOT NULL,
            version_id uuid NOT NULL,
            ordinal    integer NOT NULL,
            char_start integer NOT NULL CHECK (char_start >= 0),
            kind       text NOT NULL CHECK (kind IN ('date', 'decision_number', 'law_number',
                                                     'article', 'amount', 'parcel')),
            value      text NOT NULL CHECK (value <> '' AND length(value) <= 200),
            written    text NOT NULL CHECK (written <> '' AND length(written) <= 400),
            PRIMARY KEY (tenant_id, version_id, ordinal, char_start),
            FOREIGN KEY (tenant_id, version_id, ordinal)
                REFERENCES document_chunks (tenant_id, version_id, ordinal) ON DELETE CASCADE
        );
        CREATE INDEX chunk_entities_lookup ON chunk_entities (tenant_id, kind, value);
    """)
    op.execute(tenant_rls("document_chunks"))
    op.execute(tenant_rls("chunk_entities"))


def downgrade() -> None:
    # Downgrades are not supported; recovery is by restoring a backup (ADR 0012).
    raise NotImplementedError
