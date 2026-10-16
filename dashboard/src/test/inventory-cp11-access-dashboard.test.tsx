import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { AccessConfirmDialog } from '@/pages/inventory/access/AccessConfirmDialog';
import { GrantAccessPanel } from '@/pages/inventory/access/GrantAccessPanel';
import { RoleAccessPanel } from '@/pages/inventory/access/RoleAccessPanel';
import { inventoryAccessCopy } from '@/pages/inventory/access/copy';
import {
  parseLocationPage,
  parsePermissionCatalog,
  parseUserPage,
} from '@/pages/inventory/access/contracts';
import { permissionLabel } from '@/pages/inventory/access/permissionLabels';

describe('CP11 Inventory access Dashboard', () => {
  it('uses complete bilingual operator labels for Inventory, Ledger, Vehicle and Representative capabilities', () => {
    expect(permissionLabel('inventory.read', 'ar')).toBe('قراءة أرصدة المخزون');
    expect(permissionLabel('inventory.read', 'en')).toBe('Read inventory balances');
    expect(permissionLabel('ledger.read', 'ar')).toBe('قراءة سجل الحركات');
    expect(permissionLabel('ledger.adjust', 'en')).toBe('Correct inbound receipt');
    expect(permissionLabel('vehicle.read', 'ar')).toBe('عرض المركبات');
    expect(permissionLabel('vehicle.manage', 'en')).toBe('Manage vehicles');
    expect(permissionLabel('representative.read', 'en')).toBe('View representatives');
    expect(permissionLabel('representative.credentials.reset', 'ar')).toBe('إعادة ضبط بيانات دخول المندوب');
    expect(permissionLabel('unknown.permission', 'en')).toBe('Unsupported permission');
  });

  it('parses canonical Backoffice identity and distinguishes Warehouse from Vehicle locations', () => {
    const users = parseUserPage({
      items: [{
        principal_id: 101,
        backoffice_user_id: 202,
        full_name: 'Independent Backoffice',
        is_company_owner: false,
        is_active: true,
      }],
      next_id: null,
    });
    expect(users.items[0].principal_id).not.toBe(users.items[0].backoffice_user_id);
    expect(parseLocationPage({
      items: [
        { id: 1, name: 'A1', code: 'A1', location_type: 'WAREHOUSE', is_active: true },
        { id: 2, name: 'VA', code: 'VA', location_type: 'VEHICLE', is_active: true },
      ],
      next_id: null,
    }).items.map(item => item.location_type)).toEqual(['WAREHOUSE', 'VEHICLE']);
    expect(() => parseLocationPage({
      items: [{ id: 3, name: 'Branch', code: 'BR', location_type: 'BRANCH' }],
      next_id: null,
    })).toThrow();
    expect(() => parsePermissionCatalog({ permissions: ['inventory.read'], company_only: ['vehicle.read'] })).toThrow();
  });

  it('keeps role editing a native Enter-safe form with the first useful field focused', () => {
    const copy = inventoryAccessCopy('en');
    const onSave = vi.fn(async () => undefined);
    const setEditing = vi.fn();
    const setName = vi.fn();
    const setCodes = vi.fn();
    const { container } = render(
      <RoleAccessPanel
        copy={copy}
        language="en"
        roles={{ items: [], next_id: null }}
        catalog={{ permissions: ['inventory.read'], company_only: [] }}
        editing={null}
        name="Receiver"
        codes={['inventory.read']}
        busy={false}
        roleAfter={0}
        setRoleAfter={vi.fn()}
        setEditing={setEditing}
        setName={setName}
        setCodes={setCodes}
        onSave={onSave}
      />,
    );
    expect(screen.getByLabelText('Role name')).toHaveFocus();
    const form = container.querySelector('form');
    expect(form).not.toBeNull();
    fireEvent.submit(form!);
    expect(onSave).toHaveBeenCalledTimes(1);
  });

  it('renders Warehouse and Vehicle scope distinctly and submits only a valid native form', () => {
    const copy = inventoryAccessCopy('en');
    const onAddGrant = vi.fn(async () => undefined);
    render(
      <GrantAccessPanel
        copy={copy}
        users={{ items: [{
          principal_id: 11,
          backoffice_user_id: 22,
          full_name: 'User A',
          is_company_owner: false,
          is_active: true,
        }], next_id: null }}
        roles={{ items: [{ id: 31, name: 'Reader', permissions: ['inventory.read'], is_system_role: false }], next_id: null }}
        locations={{ items: [
          { id: 41, name: 'A1', code: 'WH-A1', location_type: 'WAREHOUSE' },
          { id: 42, name: 'VA', code: 'VEH-VA', location_type: 'VEHICLE' },
        ], next_id: null }}
        grants={{ items: [], next_id: null }}
        busy={false}
        backofficeUserId="22"
        roleId="31"
        locationId="42"
        scope="location"
        userAfter={0}
        locationAfter={0}
        grantAfter={0}
        setBackofficeUserId={vi.fn()}
        setRoleId={vi.fn()}
        setLocationId={vi.fn()}
        setScope={vi.fn()}
        setUserAfter={vi.fn()}
        setLocationAfter={vi.fn()}
        setGrantAfter={vi.fn()}
        onAddGrant={onAddGrant}
        onRequestRevoke={vi.fn()}
      />,
    );
    expect(screen.getByRole('option', { name: /A1.*Warehouse/ })).toBeTruthy();
    expect(screen.getByRole('option', { name: /VA.*Vehicle/ })).toBeTruthy();
    fireEvent.submit(screen.getByRole('button', { name: 'Add grant' }).closest('form')!);
    expect(onAddGrant).toHaveBeenCalledTimes(1);
  });

  it('traps focus in revoke confirmation, closes on Escape and restores focus after state clears', () => {
    const copy = inventoryAccessCopy('en');
    const trigger = document.createElement('button');
    document.body.appendChild(trigger);
    trigger.focus();
    const onCancel = vi.fn();
    const onConfirm = vi.fn();
    const { rerender } = render(
      <AccessConfirmDialog
        open
        copy={copy}
        busy={false}
        returnFocusTo={trigger}
        onCancel={onCancel}
        onConfirm={onConfirm}
      />,
    );
    const cancel = screen.getByRole('button', { name: 'Cancel' });
    const confirm = screen.getByRole('button', { name: 'Revoke grant' });
    expect(cancel).toHaveFocus();
    confirm.focus();
    fireEvent.keyDown(confirm, { key: 'Tab' });
    expect(cancel).toHaveFocus();
    fireEvent.keyDown(cancel, { key: 'Tab', shiftKey: true });
    expect(confirm).toHaveFocus();
    fireEvent.keyDown(confirm, { key: 'Escape' });
    expect(onCancel).toHaveBeenCalledTimes(1);
    rerender(
      <AccessConfirmDialog
        open={false}
        copy={copy}
        busy={false}
        returnFocusTo={null}
        onCancel={onCancel}
        onConfirm={onConfirm}
      />,
    );
    expect(trigger).toHaveFocus();
    trigger.remove();
  });
});
