"""Lexical search over chunks: BM25 on PostgreSQL's Turkish configuration (ADR 0010, 0018).

``document_chunks.search`` is what lexical search reads: the document's context, the chunk's
heading path and its text (knowledge/chunking.py, ``contextual_text``), lower-cased the Turkish
way first (knowledge/turkish.py), because PostgreSQL's ``lower`` makes "IĞDIR" "iğdir". It is
written with the chunk. A BM25 index of pg_textsearch reads it with the ``turkish`` text search
configuration (Snowball stems): on the golden set this ranks within a point of the benchmark's
best lexical run and, fused with bge-m3, above it (docs/benchmarks/embeddings.md).

The migrator cannot read tenants' rows (row-level security is forced on it too), so chunks
stored before this migration keep ``search`` empty and are not found by words until their
versions are indexed again (``synapse knowledge reindex``).

Revision ID: 0015
Revises: 0014
"""

from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE document_chunks ADD COLUMN search text CHECK (search <> '');
        CREATE INDEX document_chunks_search ON document_chunks
            USING bm25 (search) WITH (text_config = 'turkish');
    """)


def downgrade() -> None:
    # Downgrades are not supported; recovery is by restoring a backup (ADR 0012).
    raise NotImplementedError
