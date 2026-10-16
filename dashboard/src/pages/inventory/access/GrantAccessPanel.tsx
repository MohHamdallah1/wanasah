import type { Dispatch, SetStateAction } from 'react';
import type { AccessGrant, AccessLocation, AccessPage, AccessRole, AccessUser } from './contracts';
import type { InventoryAccessCopy } from './copy';
import type { AccessScope } from './useInventoryAccessAdmin';
import { AccessPaging } from './AccessPaging';

interface RevokeRequest {
  grant: AccessGrant;
  trigger: HTMLElement;
}

interface GrantAccessPanelProps {
  copy: InventoryAccessCopy;
  users?: AccessPage<AccessUser>;
  roles?: AccessPage<AccessRole>;
  locations?: AccessPage<AccessLocation>;
  grants?: AccessPage<AccessGrant>;
  busy: boolean;
  backofficeUserId: string;
  roleId: string;
  locationId: string;
  scope: AccessScope;
  userAfter: number;
  locationAfter: number;
  grantAfter: number;
  setBackofficeUserId: Dispatch<SetStateAction<string>>;
  setRoleId: Dispatch<SetStateAction<string>>;
  setLocationId: Dispatch<SetStateAction<string>>;
  setScope: Dispatch<SetStateAction<AccessScope>>;
  setUserAfter: (value: number) => void;
  setLocationAfter: (value: number) => void;
  setGrantAfter: (value: number) => void;
  onAddGrant: () => Promise<void>;
  onRequestRevoke: (request: RevokeRequest) => void;
}

export function GrantAccessPanel({
  copy,
  users,
  roles,
  locations,
  grants,
  busy,
  backofficeUserId,
  roleId,
  locationId,
  scope,
  userAfter,
  locationAfter,
  grantAfter,
  setBackofficeUserId,
  setRoleId,
  setLocationId,
  setScope,
  setUserAfter,
  setLocationAfter,
  setGrantAfter,
  onAddGrant,
  onRequestRevoke,
}: GrantAccessPanelProps) {
  const locationLabel = (location: AccessLocation) =>
    `${location.name} — ${location.code} (${location.location_type === 'WAREHOUSE' ? copy.warehouse : copy.vehicle})`;

  return (
    <section className="glass-card inventory-access-panel p-5 rounded-2xl space-y-4">
      <div className="inventory-panel-heading">
        <div>
          <p className="inventory-eyebrow">{copy.assignmentEyebrow}</p>
          <h3 className="font-black text-slate-900">{copy.grantUser}</h3>
        </div>
        <span className="inventory-count-chip">
          {scope === 'location' ? copy.locationScope : copy.companyScope}
        </span>
      </div>

      <form
        className="inventory-grant-form"
        onSubmit={event => {
          event.preventDefault();
          if (!busy && backofficeUserId && roleId && (scope === 'company' || locationId)) {
            void onAddGrant();
          }
        }}
      >
        <label className="inventory-field inventory-field--wide">
          <span>{copy.user}</span>
          <select
            aria-label={copy.user}
            value={backofficeUserId}
            onChange={event => {
              setBackofficeUserId(event.target.value);
              setGrantAfter(0);
            }}
          >
            <option value="">{copy.chooseUser}</option>
            {users?.items.map(user => (
              <option key={user.backoffice_user_id} value={user.backoffice_user_id}>
                {user.full_name}
                {user.is_company_owner ? ` — ${copy.companyOwner}` : ''}
                {!user.is_active ? ` — ${copy.inactive}` : ''}
              </option>
            ))}
          </select>
        </label>
        <AccessPaging
          copy={copy}
          next={users?.next_id}
          current={userAfter}
          busy={busy}
          onChange={value => {
            setUserAfter(value);
            setBackofficeUserId('');
          }}
        />

        <label className="inventory-field">
          <span>{copy.scope}</span>
          <select
            aria-label={copy.scope}
            value={scope}
            onChange={event => {
              setScope(event.target.value as AccessScope);
              setGrantAfter(0);
              setLocationId('');
            }}
          >
            <option value="location">{copy.locationScope}</option>
            <option value="company">{copy.companyScope}</option>
          </select>
        </label>

        <label className="inventory-field">
          <span>{copy.role}</span>
          <select aria-label={copy.role} value={roleId} onChange={event => setRoleId(event.target.value)}>
            <option value="">{copy.chooseRole}</option>
            {roles?.items.map(role => <option key={role.id} value={role.id}>{role.name}</option>)}
          </select>
        </label>

        {scope === 'location' && (
          <div className="inventory-field inventory-field--wide">
            <label>
              <span>{copy.warehouseOrVehicle}</span>
              <select
                aria-label={copy.warehouseOrVehicle}
                value={locationId}
                onChange={event => setLocationId(event.target.value)}
              >
                <option value="">{copy.chooseLocation}</option>
                {locations?.items.map(location => (
                  <option key={location.id} value={location.id}>{locationLabel(location)}</option>
                ))}
              </select>
            </label>
            <AccessPaging
              copy={copy}
              next={locations?.next_id}
              current={locationAfter}
              busy={busy}
              onChange={value => {
                setLocationAfter(value);
                setLocationId('');
              }}
            />
          </div>
        )}

        <button
          type="submit"
          disabled={busy || !backofficeUserId || !roleId || (scope === 'location' && !locationId)}
          className="inventory-primary-action"
        >
          {copy.addGrant}
        </button>
      </form>

      <div className="inventory-grant-list">
        {!backofficeUserId && <p className="inventory-muted-state">{copy.chooseUserToView}</p>}
        {backofficeUserId && grants?.items.length === 0 && <p className="inventory-muted-state">{copy.noGrants}</p>}
        {grants?.items.map(grant => {
          const role = roles?.items.find(item => item.id === grant.role_id);
          const location = grant.location_id === null
            ? null
            : locations?.items.find(item => item.id === grant.location_id);
          return (
            <div key={grant.id} className="inventory-grant-row">
              <span>
                <strong>{role?.name ?? copy.role}</strong>
                <small>{location ? locationLabel(location) : copy.wholeCompany}</small>
              </span>
              <button
                type="button"
                disabled={busy}
                onClick={event => onRequestRevoke({ grant, trigger: event.currentTarget })}
              >
                {copy.revoke}
              </button>
            </div>
          );
        })}
      </div>
      <AccessPaging
        copy={copy}
        next={grants?.next_id}
        current={grantAfter}
        busy={busy}
        onChange={setGrantAfter}
      />
    </section>
  );
}
