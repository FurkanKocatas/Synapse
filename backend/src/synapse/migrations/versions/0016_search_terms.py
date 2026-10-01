"""Lexical search on five-letter terms instead of Snowball stems (docs/design/search.md).

``document_chunks.search`` now holds the chunk's terms (knowledge/search.py, ``lexical_text``):
words cut to their first five letters and identifiers kept whole, indexed with pg_textsearch on
the ``simple`` configuration. On the golden set in PostgreSQL this finds the evidence among
the first ten by words alone for 0.963 of the questions against 0.937 with the ``turkish``
configuration of migration 0015, and among the fifteen the reranker reads for 0.969 against
0.953.

The old contents no longer match what queries ask for, and the migrator cannot rewrite tenants'
rows (row-level security is forced on it), so the column is dropped and added again: empty
until ``synapse knowledge reindex`` writes the terms of every chunk, which keeps chunks and
their vectors.

Revision ID: 0016
Revises: 0015
"""

from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        DROP INDEX document_chunks_search;
        ALTER TABLE document_chunks DROP COLUMN search;
        ALTER TABLE document_chunks ADD COLUMN search text CHECK (search <> '');
        CREATE INDEX document_chunks_search ON document_chunks
            USING bm25 (search) WITH (text_config = 'simple');
    """)


def downgrade() -> None:
    # Downgrades are not supported; recovery is by restoring a backup (ADR 0012).
    raise NotImplementedError
