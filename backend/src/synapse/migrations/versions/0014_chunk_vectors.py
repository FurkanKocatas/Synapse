"""Dense vectors of chunks and the document context they are made from (ADR 0010, ADR 0018).

- ``document_versions.context``: what every chunk of the version is indexed with in front, its
  file name and first 30 words (knowledge/chunking.py, ``document_context``); written with the
  chunks, read by embedding now and by lexical search in step 7.
- ``document_chunks.embedding``: bge-m3's vector of the context and the chunk's indexed text, at
  16 bits; NULL until the embedding job has written it. HNSW with cosine distance.
- ``document_versions.embedded_with``: the model every vector of the version comes from, set
  when the last one is written (status ``ready``); vectors of different models are never
  compared.
- ``document_versions.embedding_failure``: why embedding gave up, such as ``model_unavailable``.
  The version is then back at ``parsed``, not ``failed``: its text is fine and stays searchable
  by words, so ``failure`` (which means the document is unusable) stays empty.

Revision ID: 0014
Revises: 0013
"""

from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE document_versions
            ADD COLUMN context text CHECK (length(context) <= 2000),
            ADD COLUMN embedded_with text CHECK (length(embedded_with) BETWEEN 1 AND 100),
            ADD COLUMN embedding_failure text CHECK (length(embedding_failure) <= 100),
            ADD CHECK (embedding_failure IS NULL OR status = 'parsed');

        ALTER TABLE document_chunks ADD COLUMN embedding halfvec(1024);
        CREATE INDEX document_chunks_embedding ON document_chunks
            USING hnsw (embedding halfvec_cosine_ops);
    """)


def downgrade() -> None:
    # Downgrades are not supported; recovery is by restoring a backup (ADR 0012).
    raise NotImplementedError
