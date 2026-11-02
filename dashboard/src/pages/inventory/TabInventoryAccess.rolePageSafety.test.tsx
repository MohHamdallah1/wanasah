import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { inventoryAccessCopy } from './access/copy';
import { GrantAccessPanel } from './access/GrantAccessPanel';
import { TabInventoryAccess } from './TabInventoryAccess';

vi.mock('react-i18next', async (importOriginal) => ({
  ...(await importOriginal<typeof import('react-i18next')>()),
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: 'ar', resolvedLanguage: 'ar', dir: () => 'rtl' },
  }),
}));

const role = { id: 11, name: 'Warehouse reader', permissions: ['inventory.read'], is_system_role: false };
const nextRole = { ...role, id: 12, name: 'Another role' };
const user = {
  principal_id: 3, backoffice_user_id: 9, full_name: 'Warehouse operator',
  is_company_owner: false, is_active: true,
};
const location = {
  id: 42, name: 'Main warehouse', code: 'WH-42', location_type: 'WAREHOUSE' as const,
};

vi.mock('./access/useInventoryAccessAdmin', () => ({
  useInventoryAccessAdmin: () => ({
    roles: { data: { items: [role], next_id: role.id } },
    users: { data: { items: [user], next_id: null } },
    locations: { data: { items: [location], next_id: null } },
    grants: { data: { items: [], next_id: null } },
    catalog: { data: { permissions: ['inventory.read'], company_only: [] } },
    mutate: vi.fn().mockResolvedValue(true),
    busy: false,
    error: null,
  }),
}));

describe('CP11 Inventory Access role-page grant safety', () => {
  for (const language of ['ar', 'en']) {
    for (const scope of ['company', 'location'] as const) {
      it(`denies a hidden role on another page in ${language} / ${scope} scope`, () => {
        const copy = inventoryAccessCopy(language);
        const onAddGrant = vi.fn().mockResolvedValue(undefined);
        const base = {
          copy,
          users: { items: [user], next_id: null },
          roles: { items: [role], next_id: role.id },
          locations: { items: [location], next_id: null },
          grants: { items: [], next_id: null },
          busy: false,
          backofficeUserId: '9',
          roleId: '11',
          locationId: '42',
          scope,
          userAfter: 0,
          locationAfter: 0,
          grantAfter: 0,
          setBackofficeUserId: vi.fn(),
          setRoleId: vi.fn(),
          setLocationId: vi.fn(),
          setScope: vi.fn(),
          setUserAfter: vi.fn(),
          setLocationAfter: vi.fn(),
          setGrantAfter: vi.fn(),
          onAddGrant,
          onRequestRevoke: vi.fn(),
        };
        const { rerender, unmount } = render(<GrantAccessPanel {...base} />);
        const rolePicker = screen.getByRole('combobox', { name: copy.role }) as HTMLSelectElement;
        const submit = screen.getByRole('button', { name: copy.addGrant });
        expect(rolePicker.value).toBe('11');
        expect(submit).toBeEnabled();

        // A role selected on page one must not be silently posted on page two.
        rerender(<GrantAccessPanel {...base} roles={{ items: [nextRole], next_id: null }} />);
        expect(rolePicker.value).toBe('');
        expect(submit).toBeDisabled();
        // Direct form submission must be blocked too, not just the button.
        fireEvent.submit(submit.closest('form')!);
        expect(onAddGrant).not.toHaveBeenCalled();

        // A new explicit selection on the visible page is still valid.
        rerender(<GrantAccessPanel {...base} roleId="12" roles={{ items: [nextRole], next_id: null }} />);
        expect(rolePicker.value).toBe('12');
        expect(submit).toBeEnabled();
        fireEvent.submit(submit.closest('form')!);
        expect(onAddGrant).toHaveBeenCalledTimes(1);
        unmount();
      });
    }
  }

  it('clears the previously selected grant role when the shared role list advances', () => {
    const copy = inventoryAccessCopy('ar');
    render(<TabInventoryAccess />);
    fireEvent.change(screen.getByRole('combobox', { name: copy.user }), { target: { value: '9' } });
    fireEvent.change(screen.getByRole('combobox', { name: copy.role }), { target: { value: '11' } });
    fireEvent.change(screen.getByRole('combobox', { name: copy.warehouseOrVehicle }), { target: { value: '42' } });

    const picker = screen.getByRole('combobox', { name: copy.role }) as HTMLSelectElement;
    expect(picker.value).toBe('11');
    expect(screen.getByRole('button', { name: copy.addGrant })).toBeEnabled();

    // The first Next button belongs to RoleAccessPanel; its paging is shared
    // with GrantAccessPanel, so changing page must reset the grant selection.
    fireEvent.click(screen.getAllByRole('button', { name: copy.next })[0]);
    expect(picker.value).toBe('');
    expect(screen.getByRole('button', { name: copy.addGrant })).toBeDisabled();
  });
});
