"""Authorization: role permissions, groups, collections, documents and grants (ADR 0007).

The documents table starts minimal (what permissions need) and grows with the knowledge base.

Revision ID: 0005
Revises: 0004
"""

from alembic import op

from synapse.migrations.sql_helpers import tenant_rls

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

TENANT_TABLES = (
    "groups",
    "group_members",
    "collections",
    "documents",
    "collection_grants",
    "document_grants",
)


def upgrade() -> None:
    op.execute("""
        -- What each role may do outside document permissions (manage users, read the audit
        -- log...). The same for every tenant, so it is a catalogue, not tenant data.
        CREATE TABLE role_permissions (
            role       text NOT NULL CHECK (role IN ('admin', 'editor', 'member', 'auditor')),
            permission text NOT NULL CHECK (permission ~ '^[a-z_]+\\.[a-z_]+$'),
            PRIMARY KEY (role, permission)
        );
        INSERT INTO role_permissions (role, permission) VALUES
            ('admin', 'users.manage'),
            ('admin', 'groups.manage'),
            ('admin', 'collections.create'),
            ('admin', 'settings.manage'),
            ('editor', 'collections.create'),
            ('auditor', 'audit.read');
        REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON role_permissions FROM synapse_runtime;

        CREATE TABLE groups (
            id         uuid PRIMARY KEY DEFAULT uuidv7(),
            tenant_id  uuid NOT NULL REFERENCES tenants (id),
            name       text NOT NULL CHECK (length(name) BETWEEN 1 AND 200),
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, name),
            UNIQUE (tenant_id, id)
        );

        CREATE TABLE group_members (
            tenant_id uuid NOT NULL,
            group_id  uuid NOT NULL,
            user_id   uuid NOT NULL,
            PRIMARY KEY (tenant_id, group_id, user_id),
            FOREIGN KEY (tenant_id, group_id) REFERENCES groups (tenant_id, id) ON DELETE CASCADE,
            FOREIGN KEY (tenant_id, user_id) REFERENCES users (tenant_id, id) ON DELETE CASCADE
        );
        CREATE INDEX group_members_user ON group_members (tenant_id, user_id);

        -- Folders. Grants on a collection apply to everything below it.
        CREATE TABLE collections (
            id         uuid PRIMARY KEY DEFAULT uuidv7(),
            tenant_id  uuid NOT NULL REFERENCES tenants (id),
            parent_id  uuid,
            name       text NOT NULL CHECK (length(name) BETWEEN 1 AND 200),
            created_by uuid,
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, id),
            FOREIGN KEY (tenant_id, parent_id) REFERENCES collections (tenant_id, id),
            FOREIGN KEY (tenant_id, created_by) REFERENCES users (tenant_id, id),
            CHECK (parent_id IS DISTINCT FROM id)
        );
        CREATE INDEX collections_parent ON collections (tenant_id, parent_id);
        -- Sibling names are unique, including at the top level (NULL parent).
        CREATE UNIQUE INDEX collections_sibling_name
            ON collections (
                tenant_id,
                coalesce(parent_id, '00000000-0000-0000-0000-000000000000'),
                lower(name)
            );

        CREATE TABLE documents (
            id            uuid PRIMARY KEY DEFAULT uuidv7(),
            tenant_id     uuid NOT NULL REFERENCES tenants (id),
            collection_id uuid NOT NULL,
            title         text NOT NULL CHECK (length(title) BETWEEN 1 AND 500),
            created_by    uuid,
            created_at    timestamptz NOT NULL DEFAULT now(),
            -- Set when deleted; the document leaves search immediately (ADR 0003).
            deleted_at    timestamptz,
            UNIQUE (tenant_id, id),
            FOREIGN KEY (tenant_id, collection_id) REFERENCES collections (tenant_id, id),
            FOREIGN KEY (tenant_id, created_by) REFERENCES users (tenant_id, id)
        );
        CREATE INDEX documents_collection ON documents (tenant_id, collection_id)
            WHERE deleted_at IS NULL;

        -- A grant names exactly one principal: a user, a group or a role.
        CREATE TABLE collection_grants (
            id                 uuid PRIMARY KEY DEFAULT uuidv7(),
            tenant_id          uuid NOT NULL,
            collection_id      uuid NOT NULL,
            principal_user_id  uuid,
            principal_group_id uuid,
            principal_role     text
                               CHECK (principal_role IN ('admin', 'editor', 'member', 'auditor')),
            permission         text NOT NULL CHECK (permission IN ('read', 'write', 'manage')),
            granted_by         uuid,
            granted_at         timestamptz NOT NULL DEFAULT now(),
            CHECK (num_nonnulls(principal_user_id, principal_group_id, principal_role) = 1),
            FOREIGN KEY (tenant_id, collection_id) REFERENCES collections (tenant_id, id)
                ON DELETE CASCADE,
            FOREIGN KEY (tenant_id, principal_user_id) REFERENCES users (tenant_id, id)
                ON DELETE CASCADE,
            FOREIGN KEY (tenant_id, principal_group_id) REFERENCES groups (tenant_id, id)
                ON DELETE CASCADE
        );
        CREATE INDEX collection_grants_collection ON collection_grants (tenant_id, collection_id);

        CREATE TABLE document_grants (
            id                 uuid PRIMARY KEY DEFAULT uuidv7(),
            tenant_id          uuid NOT NULL,
            document_id        uuid NOT NULL,
            principal_user_id  uuid,
            principal_group_id uuid,
            principal_role     text
                               CHECK (principal_role IN ('admin', 'editor', 'member', 'auditor')),
            permission         text NOT NULL CHECK (permission IN ('read', 'write', 'manage')),
            granted_by         uuid,
            granted_at         timestamptz NOT NULL DEFAULT now(),
            CHECK (num_nonnulls(principal_user_id, principal_group_id, principal_role) = 1),
            FOREIGN KEY (tenant_id, document_id) REFERENCES documents (tenant_id, id)
                ON DELETE CASCADE,
            FOREIGN KEY (tenant_id, principal_user_id) REFERENCES users (tenant_id, id)
                ON DELETE CASCADE,
            FOREIGN KEY (tenant_id, principal_group_id) REFERENCES groups (tenant_id, id)
                ON DELETE CASCADE
        );
        CREATE INDEX document_grants_document ON document_grants (tenant_id, document_id);

        -- 'manage' includes 'write', which includes 'read'.
        CREATE FUNCTION permission_rank(permission text) RETURNS integer
            LANGUAGE sql IMMUTABLE PARALLEL SAFE
            SET search_path = pg_catalog
            AS $$ SELECT CASE permission WHEN 'read' THEN 1 WHEN 'write' THEN 2
                                         WHEN 'manage' THEN 3 END $$;

        -- The one definition of "documents this user may use with this permission". Search,
        -- chat and every document endpoint filter through it (ADR 0007). It runs with the
        -- caller's rights, so row-level security still confines it to the current tenant.
        CREATE FUNCTION accessible_documents(p_user_id uuid, p_permission text)
            RETURNS TABLE (document_id uuid)
            LANGUAGE sql STABLE
            SET search_path = synapse, pg_catalog
            AS $$
            WITH RECURSIVE
            me AS (
                SELECT u.id, u.role FROM users u WHERE u.id = p_user_id AND u.status = 'active'
            ),
            my_groups AS (
                SELECT gm.group_id FROM group_members gm JOIN me ON gm.user_id = me.id
            ),
            granted_collections AS (
                SELECT g.collection_id AS id
                FROM collection_grants g, me
                WHERE permission_rank(g.permission) >= permission_rank(p_permission)
                  AND (g.principal_user_id = me.id
                       OR g.principal_role = me.role
                       OR g.principal_group_id IN (SELECT group_id FROM my_groups))
            ),
            reachable_collections AS (
                SELECT id FROM granted_collections
                UNION
                SELECT c.id FROM collections c JOIN reachable_collections r ON c.parent_id = r.id
            )
            SELECT d.id FROM documents d
            WHERE d.deleted_at IS NULL
              AND d.collection_id IN (SELECT id FROM reachable_collections)
            UNION
            SELECT d.id FROM documents d
            JOIN document_grants g ON g.document_id = d.id, me
            WHERE d.deleted_at IS NULL
              AND permission_rank(g.permission) >= permission_rank(p_permission)
              AND (g.principal_user_id = me.id
                   OR g.principal_role = me.role
                   OR g.principal_group_id IN (SELECT group_id FROM my_groups))
            $$;
    """)
    for table in TENANT_TABLES:
        op.execute(tenant_rls(table))


def downgrade() -> None:
    # Downgrades are not supported; recovery is by restoring a backup (ADR 0012).
    raise NotImplementedError
