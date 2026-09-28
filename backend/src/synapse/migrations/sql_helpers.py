"""SQL fragments shared by migrations, so every tenant table gets exactly the same policy."""


def tenant_rls(table: str) -> str:
    """Enable and force row-level security on ``table`` with the standard tenant policy.

    ``FORCE`` makes the policy apply to the table owner too, so even the migrator cannot read
    across tenants by accident through application code paths.
    """
    return f"""
        ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
        ALTER TABLE {table} FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON {table}
            USING (tenant_id = app_current_tenant())
            WITH CHECK (tenant_id = app_current_tenant());
    """
