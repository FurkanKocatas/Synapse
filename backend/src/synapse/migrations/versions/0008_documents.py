"""Knowledge base storage: stored files, document versions, and collection access (ADR 0003).

- ``blobs``: one row per distinct file content per tenant. The bytes live in the blob store
  (a local volume), named by their SHA-256; the row records that the tenant holds them.
  Identical uploads share one blob. Deduplication stays inside a tenant: sharing across
  tenants would let one tenant learn that another holds a given file.
- ``document_versions``: every upload of a document. Search uses the document's
  ``current_version_id``, which moves to a new version only when that version is ready, so a
  re-upload never leaves the document half indexed.
- ``accessible_collections``: the collections a user may use with a permission. It is the
  collection half of ``accessible_documents``, which now calls it, so both keep one definition.

Revision ID: 0008
Revises: 0007
"""

from alembic import op

from synapse.migrations.sql_helpers import tenant_rls

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

TABLES = ("blobs", "document_versions")


def upgrade() -> None:
    op.execute("""
        CREATE TABLE blobs (
            tenant_id   uuid NOT NULL REFERENCES tenants (id),
            sha256      bytea NOT NULL CHECK (octet_length(sha256) = 32),
            size_bytes  bigint NOT NULL CHECK (size_bytes > 0),
            media_type  text NOT NULL CHECK (length(media_type) BETWEEN 3 AND 100),
            created_at  timestamptz NOT NULL,
            PRIMARY KEY (tenant_id, sha256)
        );

        CREATE TABLE document_versions (
            id            uuid PRIMARY KEY DEFAULT uuidv7(),
            tenant_id     uuid NOT NULL,
            document_id   uuid NOT NULL,
            version       integer NOT NULL CHECK (version >= 1),
            blob_sha256   bytea NOT NULL,
            -- The name the file had on the uploader's machine, for display and download only.
            filename      text NOT NULL CHECK (length(filename) BETWEEN 1 AND 255),
            status        text NOT NULL DEFAULT 'queued'
                          CHECK (status IN ('queued', 'parsing', 'ocr', 'embedding', 'ready',
                                            'failed')),
            -- A stable reason code when failed, such as 'unreadable' or 'encrypted'.
            failure       text CHECK (length(failure) <= 100),
            created_by    uuid,
            created_at    timestamptz NOT NULL,
            UNIQUE (tenant_id, id),
            UNIQUE (tenant_id, document_id, version),
            FOREIGN KEY (tenant_id, document_id) REFERENCES documents (tenant_id, id),
            FOREIGN KEY (tenant_id, blob_sha256) REFERENCES blobs (tenant_id, sha256),
            FOREIGN KEY (tenant_id, created_by) REFERENCES users (tenant_id, id),
            CHECK ((status = 'failed') = (failure IS NOT NULL))
        );
        CREATE INDEX document_versions_blob ON document_versions (tenant_id, blob_sha256);

        ALTER TABLE documents
            ADD COLUMN current_version_id uuid,
            ADD FOREIGN KEY (tenant_id, current_version_id)
                REFERENCES document_versions (tenant_id, id);

        -- Collections this user may use with this permission: those granted to them, their
        -- groups or their role, and everything nested below those. Runs with the caller's
        -- rights, so row-level security confines it to the current tenant.
        CREATE FUNCTION accessible_collections(p_user_id uuid, p_permission text)
            RETURNS TABLE (collection_id uuid)
            LANGUAGE sql STABLE
            SET search_path = synapse, pg_catalog
            AS $$
            WITH RECURSIVE
            me AS (
                SELECT u.id, u.role FROM users u WHERE u.id = p_user_id AND u.status = 'active'
            ),
            granted AS (
                SELECT g.collection_id AS id
                FROM collection_grants g, me
                WHERE permission_rank(g.permission) >= permission_rank(p_permission)
                  AND (g.principal_user_id = me.id
                       OR g.principal_role = me.role
                       OR g.principal_group_id IN (
                           SELECT gm.group_id FROM group_members gm WHERE gm.user_id = me.id))
            ),
            reachable AS (
                SELECT id FROM granted
                UNION
                SELECT c.id FROM collections c JOIN reachable r ON c.parent_id = r.id
            )
            SELECT id FROM reachable
            $$;

        CREATE OR REPLACE FUNCTION accessible_documents(p_user_id uuid, p_permission text)
            RETURNS TABLE (document_id uuid)
            LANGUAGE sql STABLE
            SET search_path = synapse, pg_catalog
            AS $$
            WITH me AS (
                SELECT u.id, u.role FROM users u WHERE u.id = p_user_id AND u.status = 'active'
            )
            SELECT d.id FROM documents d
            WHERE d.deleted_at IS NULL
              AND d.collection_id IN (
                  SELECT collection_id FROM accessible_collections(p_user_id, p_permission))
            UNION
            SELECT d.id FROM documents d
            JOIN document_grants g ON g.document_id = d.id, me
            WHERE d.deleted_at IS NULL
              AND permission_rank(g.permission) >= permission_rank(p_permission)
              AND (g.principal_user_id = me.id
                   OR g.principal_role = me.role
                   OR g.principal_group_id IN (
                       SELECT gm.group_id FROM group_members gm WHERE gm.user_id = me.id))
            $$;
    """)
    for table in TABLES:
        op.execute(tenant_rls(table))


def downgrade() -> None:
    # Downgrades are not supported; recovery is by restoring a backup (ADR 0012).
    raise NotImplementedError
