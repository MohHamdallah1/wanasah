import type { Dispatch, SetStateAction } from 'react';
import type { AccessPage, AccessRole, PermissionCatalog } from './contracts';
import type { InventoryAccessCopy } from './copy';
import { permissionLabel } from './permissionLabels';
import { AccessPaging } from './AccessPaging';

interface RoleAccessPanelProps {
  copy: InventoryAccessCopy;
  language: string;
  roles?: AccessPage<AccessRole>;
  catalog?: PermissionCatalog;
  editing: number | null;
  name: string;
  codes: string[];
  busy: boolean;
  roleAfter: number;
  setRoleAfter: (value: number) => void;
  setEditing: Dispatch<SetStateAction<number | null>>;
  setName: Dispatch<SetStateAction<string>>;
  setCodes: Dispatch<SetStateAction<string[]>>;
  onSave: () => Promise<void>;
}

export function RoleAccessPanel({
  copy,
  language,
  roles,
  catalog,
  editing,
  name,
  codes,
  busy,
  roleAfter,
  setRoleAfter,
  setEditing,
  setName,
  setCodes,
  onSave,
}: RoleAccessPanelProps) {
  const reset = () => {
    setEditing(null);
    setName('');
    setCodes([]);
  };

  return (
    <section className="glass-card inventory-access-panel p-5 rounded-2xl space-y-4">
      <div className="inventory-panel-heading">
        <div>
          <p className="inventory-eyebrow">{copy.rolesEyebrow}</p>
          <h3 className="font-black text-slate-900">{editing ? copy.editRole : copy.newRole}</h3>
        </div>
        <span className="inventory-count-chip">{copy.selectedPermissions(codes.length)}</span>
      </div>

      <form
        className="space-y-4"
        onSubmit={event => {
          event.preventDefault();
          if (!busy && name.trim() && catalog) void onSave();
        }}
      >
        <label className="inventory-field">
          <span>{copy.roleName}</span>
          <input
            autoFocus
            aria-label={copy.roleName}
            value={name}
            maxLength={100}
            onChange={event => setName(event.target.value)}
            placeholder={copy.roleNamePlaceholder}
          />
        </label>

        <div className="inventory-permission-grid">
          {catalog?.permissions.map(code => (
            <label key={code} className="inventory-permission-option">
              <input
                type="checkbox"
                checked={codes.includes(code)}
                onChange={event => setCodes(old =>
                  event.target.checked ? [...old, code] : old.filter(value => value !== code)
                )}
              />
              <span>
                {permissionLabel(code, language)}
                {catalog.company_only.includes(code) ? <small>{copy.companyOnly}</small> : null}
              </span>
            </label>
          ))}
        </div>

        <p className="inventory-guidance">{copy.guidance}</p>
        <div className="inventory-action-row">
          <button
            type="submit"
            disabled={busy || !name.trim() || !catalog}
            className="inventory-primary-action"
          >
            {copy.saveRole}
          </button>
          <button type="button" className="inventory-secondary-action" onClick={reset}>
            {copy.resetRole}
          </button>
        </div>
      </form>

      <div className="inventory-role-list">
        {roles?.items.map(role => (
          <button
            type="button"
            key={role.id}
            disabled={role.is_system_role}
            onClick={() => {
              setEditing(role.id);
              setName(role.name);
              setCodes(role.permissions);
            }}
            className="inventory-role-chip"
          >
            <span>{role.name}</span>
            <small>
              {copy.selectedPermissions(role.permissions.length)}
              {role.is_system_role ? ` · ${copy.systemRole}` : ''}
            </small>
          </button>
        ))}
      </div>
      <AccessPaging
        copy={copy}
        next={roles?.next_id}
        current={roleAfter}
        busy={busy}
        onChange={setRoleAfter}
      />
    </section>
  );
}
