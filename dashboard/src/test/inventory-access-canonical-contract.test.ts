import { describe, expect, it, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { transpileModule, ScriptTarget } from 'typescript';

vi.mock('@/hooks/useAuthFetch', () => ({ useAuthFetch: vi.fn() }));
import { parseInventoryCapabilities } from '@/hooks/useInventoryAccess';

const user = {
  principal_id: 101, backoffice_user_id: 202, full_name: 'Canonical User',
  is_company_owner: false, is_active: true,
};

// Exercise the exact private parser without adding non-component exports to a
// Fast Refresh component module or importing unrelated page behavior.
const source = readFileSync(new URL('../pages/inventory/TabInventoryAccess.tsx', import.meta.url), 'utf8');
const pureSource = source.slice(0, source.indexOf('const LABELS:')).replace(/^import .*;\r?$/gm, '');
const javascript = transpileModule(pureSource, { compilerOptions: { target: ScriptTarget.ES2022 } }).outputText;
const parseUserPage = new Function(javascript + '\nreturn parseUserPage;')() as (
  raw: unknown,
) => { items: Array<typeof user>; next_id: number | null };

describe('canonical inventory access identity', () => {
  it('addresses an independent Backoffice profile without a legacy user ID', () => {
    const page = parseUserPage({ items: [user], next_id: 202 });
    expect(page.items).toEqual([user]);
    expect(page.items[0].backoffice_user_id).not.toBe(page.items[0].principal_id);
    expect(page.items[0]).not.toHaveProperty('id');
    expect(page.items[0]).not.toHaveProperty('is_admin');
    expect(page.next_id).toBe(202);
  });

  it.each([
    { ...user, principal_id: 0 }, { ...user, backoffice_user_id: '202' },
    { ...user, is_company_owner: 'true' },
    { id: 303, full_name: 'Legacy User', is_admin: true, is_active: true },
  ])('rejects malformed or legacy user identities', raw => {
    expect(() => parseUserPage({ items: [raw], next_id: null })).toThrow();
  });

  it('parses canonical self-access with no grants and explicit Owner state', () => {
    const raw = {
      company_id: 7, principal_id: 11, backoffice_user_id: 22, is_company_owner: false,
      location_id: null, permissions: [], any_permissions: [], location_permissions: [],
    };
    expect(parseInventoryCapabilities(raw)).toEqual(raw);
    expect(() => parseInventoryCapabilities({ ...raw, backoffice_user_id: 0 })).toThrow();
    expect(() => parseInventoryCapabilities({ company_id: 7, driver_id: 44,
      is_company_admin: true, location_id: null, permissions: [], any_permissions: [],
      location_permissions: [] })).toThrow();
  });
});
