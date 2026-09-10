-- Incremental migration, never call rebuild_schema for an existing database.
-- Execute as the migration owner. The transaction preserves existing role grants.
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';
LOCK TABLE roles IN SHARE MODE;
LOCK TABLE role_permissions IN ACCESS EXCLUSIVE MODE;
ALTER TABLE role_permissions ADD COLUMN IF NOT EXISTS company_id integer;
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM role_permissions rp LEFT JOIN roles r ON r.id = rp.role_id
        WHERE r.id IS NULL OR (rp.company_id IS NOT NULL AND rp.company_id <> r.company_id)
    ) THEN
        RAISE EXCEPTION 'Role permission tenant mismatch; no data was changed';
    END IF;
END $$;
UPDATE role_permissions rp SET company_id = r.company_id
FROM roles r WHERE r.id = rp.role_id AND rp.company_id IS NULL;
ALTER TABLE role_permissions ALTER COLUMN company_id SET NOT NULL;
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'role_permissions'::regclass
          AND conname = 'fk_role_permissions_tenant_role'
    ) THEN
        ALTER TABLE role_permissions ADD CONSTRAINT fk_role_permissions_tenant_role
        FOREIGN KEY (company_id, role_id) REFERENCES roles(company_id, id) ON DELETE CASCADE;
    END IF;
END $$;
CREATE INDEX IF NOT EXISTS ix_role_permissions_company_role ON role_permissions(company_id, role_id);
ALTER TABLE role_permissions ENABLE ROW LEVEL SECURITY;
ALTER TABLE role_permissions FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_policy ON role_permissions;
CREATE POLICY tenant_isolation_policy ON role_permissions FOR ALL
USING (company_id = NULLIF(current_setting('app.current_tenant', true), '')::integer)
WITH CHECK (company_id = NULLIF(current_setting('app.current_tenant', true), '')::integer);
COMMIT;
