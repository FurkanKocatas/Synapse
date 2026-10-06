"""The scope a conversation searches: the folders and documents its user chose
(knowledge/scope.py); an empty object is everything the user may read.

Revision ID: 0024
Revises: 0023
"""

from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE conversations
            ADD COLUMN scope jsonb NOT NULL DEFAULT '{}'
                CHECK (jsonb_typeof(scope) = 'object' AND length(scope::text) <= 20000);
    """)


def downgrade() -> None:
    # Downgrades are not supported; recovery is by restoring a backup (ADR 0012).
    raise NotImplementedError
