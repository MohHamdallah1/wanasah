
ALTER TABLE product_batches ENABLE ROW LEVEL SECURITY;
ALTER TABLE product_batches FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_policy ON product_batches;
CREATE POLICY tenant_isolation_policy ON product_batches
    FOR ALL
    USING (company_id = NULLIF(current_setting('app.current_tenant', true), '')::integer)
    WITH CHECK (company_id = NULLIF(current_setting('app.current_tenant', true), '')::integer);

ALTER TABLE inventory_locations ENABLE ROW LEVEL SECURITY;
ALTER TABLE inventory_locations FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_policy ON inventory_locations;
CREATE POLICY tenant_isolation_policy ON inventory_locations
    FOR ALL
    USING (company_id = NULLIF(current_setting('app.current_tenant', true), '')::integer)
    WITH CHECK (company_id = NULLIF(current_setting('app.current_tenant', true), '')::integer);

ALTER TABLE inventory_balances ENABLE ROW LEVEL SECURITY;
ALTER TABLE inventory_balances FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_policy ON inventory_balances;
CREATE POLICY tenant_isolation_policy ON inventory_balances
    FOR ALL
    USING (company_id = NULLIF(current_setting('app.current_tenant', true), '')::integer)
    WITH CHECK (company_id = NULLIF(current_setting('app.current_tenant', true), '')::integer);

ALTER TABLE inventory_movements ENABLE ROW LEVEL SECURITY;
ALTER TABLE inventory_movements FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_policy ON inventory_movements;
CREATE POLICY tenant_isolation_policy ON inventory_movements
    FOR ALL
    USING (company_id = NULLIF(current_setting('app.current_tenant', true), '')::integer)
    WITH CHECK (company_id = NULLIF(current_setting('app.current_tenant', true), '')::integer);
