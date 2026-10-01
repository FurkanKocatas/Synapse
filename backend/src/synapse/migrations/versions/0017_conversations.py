"""Conversations: each user's questions and the answers they got (docs/design/answers.md).

- ``conversations``: one per thread of questions, owned by the user who asked them; only that
  user lists, reads, renames or deletes it (the application filters on ``user_id``).
- ``conversation_turns``: a question and its answer. The sources are kept as references
  (document, version, chunk, pages), never as text: reading a turn again fetches their text
  through the permission filter, so a source the user may no longer read is not shown. The
  answer's text is the user's own history and is kept; the audit log keeps only its hash
  (ADR 0008). A turn is ``pending`` until its answer is written; one the user cancelled, or
  whose connection closed, is ``cancelled``.

Revision ID: 0017
Revises: 0016
"""

from alembic import op

from synapse.migrations.sql_helpers import tenant_rls

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None

TABLES = ("conversations", "conversation_turns")


def upgrade() -> None:
    op.execute("""
        CREATE TABLE conversations (
            id          uuid PRIMARY KEY DEFAULT uuidv7(),
            tenant_id   uuid NOT NULL,
            user_id     uuid NOT NULL,
            title       text NOT NULL CHECK (length(title) BETWEEN 1 AND 200),
            created_at  timestamptz NOT NULL,
            updated_at  timestamptz NOT NULL,
            UNIQUE (tenant_id, id),
            FOREIGN KEY (tenant_id, user_id) REFERENCES users (tenant_id, id) ON DELETE CASCADE
        );
        CREATE INDEX conversations_by_user ON conversations (tenant_id, user_id, updated_at DESC);

        CREATE TABLE conversation_turns (
            tenant_id        uuid NOT NULL,
            conversation_id  uuid NOT NULL,
            ordinal          integer NOT NULL CHECK (ordinal >= 1),
            question         text NOT NULL CHECK (length(question) BETWEEN 1 AND 1000),
            -- The question as searched: rewritten to stand alone when it was a follow-up.
            query            text CHECK (length(query) BETWEEN 1 AND 2000),
            status           text NOT NULL DEFAULT 'pending'
                             CHECK (status IN ('pending', 'answered', 'not_found', 'insufficient',
                                               'failed', 'cancelled')),
            answer           text CHECK (length(answer) <= 20000),
            -- [{document_id, version_id, version, ordinal, title, page_start, page_end}], in the
            -- order the model saw them; citations are 1-based positions in it.
            sources          jsonb NOT NULL DEFAULT '[]' CHECK (jsonb_typeof(sources) = 'array'),
            citations        integer[] NOT NULL DEFAULT '{}',
            -- Scores, verification and timings, for evaluation; never shown as is.
            details          jsonb NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(details) = 'object'),
            feedback         text CHECK (feedback IN ('helpful', 'wrong_source', 'incomplete',
                                                      'invented')),
            created_at       timestamptz NOT NULL,
            finished_at      timestamptz,
            PRIMARY KEY (tenant_id, conversation_id, ordinal),
            FOREIGN KEY (tenant_id, conversation_id) REFERENCES conversations (tenant_id, id)
                ON DELETE CASCADE,
            CHECK ((status = 'pending') = (finished_at IS NULL)),
            CHECK (status = 'answered' OR answer IS NULL)
        );
    """)
    for table in TABLES:
        op.execute(tenant_rls(table))


def downgrade() -> None:
    # Downgrades are not supported; recovery is by restoring a backup (ADR 0012).
    raise NotImplementedError
