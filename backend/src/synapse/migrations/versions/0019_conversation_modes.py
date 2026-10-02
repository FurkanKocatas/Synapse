"""Two kinds of conversation (docs/design/answers.md).

``conversations.mode``: ``corporate`` for the assistant over the organisation's documents (every
conversation before this migration), ``classic`` for a plain conversation with the chat model
that searches nothing. A conversation keeps the mode it was started in; a classic conversation's
answers are ``general`` turns.

Revision ID: 0019
Revises: 0018
"""

from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE conversations
            ADD COLUMN mode text NOT NULL DEFAULT 'corporate'
                CHECK (mode IN ('corporate', 'classic'));
        DROP INDEX conversations_by_user;
        CREATE INDEX conversations_by_user
            ON conversations (tenant_id, user_id, mode, updated_at DESC);
    """)


def downgrade() -> None:
    # Downgrades are not supported; recovery is by restoring a backup (ADR 0012).
    raise NotImplementedError
