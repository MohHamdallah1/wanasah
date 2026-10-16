import { describe, expect, it, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

vi.mock('@/hooks/useAuthFetch', () => ({ useAuthFetch: vi.fn() }));
import { parseInventoryCapabilities } from '@/hooks/useInventoryAccess';
import { parseUserPage } from '@/pages/inventory/access/contracts';

const user = {
  principal_id: 101,
  backoffice_user_id: 202,
  full_name: 'Canonical User',
  is_company_owner: false,
  is_active: true,
};

const source = readFileSync(resolve(process.cwd(), 'src/pages/inventory/TabInventoryAccess.tsx'), 'utf8');
const contractsSource = readFileSync(resolve(process.cwd(), 'src/pages/inventory/access/contracts.ts'), 'utf8');
const grantPanelSource = readFileSync(resolve(process.cwd(), 'src/pages/inventory/access/GrantAccessPanel.tsx'), 'utf8');
const hookSource = readFileSync(resolve(process.cwd(), 'src/hooks/useInventoryAccess.ts'), 'utf8');
const loginSource = readFileSync(resolve(process.cwd(), 'src/pages/Login.tsx'), 'utf8');

describe('canonical inventory access identity', () => {
  it('exposes only canonical Owner terminology in the runtime contract', () => {
    for (const runtime of [source, contractsSource, grantPanelSource, hookSource, loginSource]) {
      for (const alias of ['isCompanyAdmin', 'is_company_admin', 'is_admin']) {
        expect(runtime).not.toContain(alias);
      }
    }
    expect(hookSource).toContain('isCompanyOwner: data?.is_company_owner === true');
  });

  it('addresses an independent Backoffice profile without a legacy user ID', () => {
    const page = parseUserPage({ items: [user], next_id: 202 });
    expect(page.items).toEqual([user]);
    expect(page.items[0].backoffice_user_id).not.toBe(page.items[0].principal_id);
    expect(page.items[0]).not.toHaveProperty('id');
    expect(page.items[0]).not.toHaveProperty('driver_id');
    expect(page.next_id).toBe(202);
  });

  it.each([
    { ...user, principal_id: 0 },
    { ...user, backoffice_user_id: '202' },
    { ...user, is_company_owner: 'true' },
    { id: 303, full_name: 'Legacy User', is_admin: true, is_active: true },
  ])('rejects malformed or legacy user identities', raw => {
    expect(() => parseUserPage({ items: [raw], next_id: null })).toThrow();
  });

  it('parses canonical self-access with no grants and explicit Owner state', () => {
    const raw = {
      company_id: 7,
      principal_id: 11,
      backoffice_user_id: 22,
      is_company_owner: false,
      location_id: null,
      permissions: [],
      any_permissions: [],
      location_permissions: [],
    };
    expect(parseInventoryCapabilities(raw)).toEqual(raw);
    expect(() => parseInventoryCapabilities({ ...raw, backoffice_user_id: 0 })).toThrow();
    expect(() => parseInventoryCapabilities({
      company_id: 7,
      driver_id: 44,
      is_company_admin: true,
      location_id: null,
      permissions: [],
      any_permissions: [],
      location_permissions: [],
    })).toThrow();
  });

  it('stores independent canonical Dashboard IDs and rejects legacy login identity', () => {
    expect(loginSource).toContain("localStorage.setItem('principal_id', String(principalId));");
    expect(loginSource).toContain("localStorage.setItem('backoffice_user_id', String(backofficeUserId));");
    expect(loginSource).toContain("localStorage.removeItem('driver_id');");
    expect(loginSource).not.toContain('data.driver_id');
    expect(loginSource).not.toContain('data.driver_name');
    expect(loginSource).toContain("data.channel !== 'DASHBOARD'");
    expect(loginSource).toContain("data.principal_type !== 'BACKOFFICE'");
  });

  it('keeps grant targeting on canonical Backoffice user ids', () => {
    expect(grantPanelSource).toContain('key={user.backoffice_user_id} value={user.backoffice_user_id}');
    expect(source).toContain('/inventory/access/users/${backofficeUserId}/grants');
    expect(source).toContain('dir={i18n.dir()}');
  });
});
