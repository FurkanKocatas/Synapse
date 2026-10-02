"""What an answer rests on (docs/design/answers.md): the documents, or nothing.

``conversation_turns.kind``: ``documents`` for an answer from the user's documents, with its
sources and citations; ``conversation`` for a reply to a greeting or thanks; ``general`` for an
answer from general knowledge to a question that is not about the organisation. The last two
keep no sources. Turns written before this migration are all ``documents``.

Revision ID: 0018
Revises: 0017
"""

from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE conversation_turns
            ADD COLUMN kind text NOT NULL DEFAULT 'documents'
                CHECK (kind IN ('documents', 'conversation', 'general'));
    """)


def downgrade() -> None:
    # Downgrades are not supported; recovery is by restoring a backup (ADR 0012).
    raise NotImplementedError
