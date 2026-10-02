"""A fourth kind of answer (docs/design/answers.md): ``library``, an answer about the collection
itself ("what is in the documents", "how many are there") from what its documents are, their
folders, titles and first words, not from a search of their text. Like ``conversation`` and
``general`` it keeps no sources.

Revision ID: 0020
Revises: 0019
"""

from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE conversation_turns DROP CONSTRAINT conversation_turns_kind_check;
        ALTER TABLE conversation_turns ADD CONSTRAINT conversation_turns_kind_check
            CHECK (kind IN ('documents', 'conversation', 'general', 'library'));
    """)


def downgrade() -> None:
    # Downgrades are not supported; recovery is by restoring a backup (ADR 0012).
    raise NotImplementedError
