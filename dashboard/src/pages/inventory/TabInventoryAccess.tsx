import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { apiErrorMessage } from '@/lib/apiErrors';
import type { AccessGrant } from './access/contracts';
import { inventoryAccessCopy } from './access/copy';
import { RoleAccessPanel } from './access/RoleAccessPanel';
import { GrantAccessPanel } from './access/GrantAccessPanel';
import { AccessConfirmDialog } from './access/AccessConfirmDialog';
import { useInventoryAccessAdmin, type AccessScope } from './access/useInventoryAccessAdmin';

interface PendingRevoke {
  grant: AccessGrant;
  trigger: HTMLElement;
}

export function TabInventoryAccess() {
  const { t, i18n } = useTranslation();
  const language = i18n.resolvedLanguage ?? i18n.language;
  const copy = inventoryAccessCopy(language);

  const [roleAfter, setRoleAfter] = useState(0);
  const [userAfter, setUserAfter] = useState(0);
  const [locationAfter, setLocationAfter] = useState(0);
  const [grantAfter, setGrantAfter] = useState(0);
  const [editing, setEditing] = useState<number | null>(null);
  const [name, setName] = useState('');
  const [codes, setCodes] = useState<string[]>([]);
  const [backofficeUserId, setBackofficeUserId] = useState('');
  const [roleId, setRoleId] = useState('');
  const [locationId, setLocationId] = useState('');
  const [scope, setScope] = useState<AccessScope>('location');
  const [pendingRevoke, setPendingRevoke] = useState<PendingRevoke | null>(null);

  const access = useInventoryAccessAdmin({
    roleAfter,
    userAfter,
    locationAfter,
    grantAfter,
    backofficeUserId,
    scope,
  });

  const runMutation = async (url: string, method: string, body?: unknown): Promise<boolean> => {
    try {
      const changed = await access.mutate(url, method, body);
      if (changed) toast.success(t('inventoryAccessAdmin.saved'));
      return changed;
    } catch (error) {
      toast.error(apiErrorMessage(error, t('inventoryAccessAdmin.errors.saveFailed')));
      return false;
    }
  };

  const saveRole = async () => {
    const changed = await runMutation(
      `/inventory/access/roles${editing ? `/${editing}` : ''}`,
      editing ? 'PUT' : 'POST',
      { name, permissions: codes },
    );
    if (changed && editing === null) {
      setName('');
      setCodes([]);
    }
  };

  const addGrant = async () => {
    await runMutation(
      `/inventory/access/users/${backofficeUserId}/grants`,
      'POST',
      {
        role_id: Number(roleId),
        location_id: scope === 'company' ? null : Number(locationId),
      },
    );
  };

  const revokeGrant = async () => {
    if (!pendingRevoke) return;
    const changed = await runMutation(
      `/inventory/access/users/${backofficeUserId}/grants/${pendingRevoke.grant.id}?scope=${scope}`,
      'DELETE',
    );
    if (changed) setPendingRevoke(null);
  };

  return (
    <div className="inventory-view inventory-access overflow-auto flex-1 space-y-5 p-1" dir={i18n.dir()}>
      <header className="glass-card inventory-section-header rounded-2xl p-5">
        <div>
          <p className="inventory-eyebrow">{t('inventoryAccessAdmin.eyebrow')}</p>
          <h2 className="font-black text-xl text-slate-900">{t('inventoryAccessAdmin.title')}</h2>
          <p className="text-sm text-slate-600 mt-1 leading-6">{t('inventoryAccessAdmin.description')}</p>
        </div>
      </header>

      {access.error && (
        <p role="alert" className="inventory-alert-banner p-3 text-sm font-bold">
          {apiErrorMessage(access.error, t('inventoryAccessAdmin.errors.loadFailed'))}
        </p>
      )}

      <div className="inventory-access-grid">
        <RoleAccessPanel
          copy={copy}
          language={language}
          roles={access.roles.data}
          catalog={access.catalog.data}
          editing={editing}
          name={name}
          codes={codes}
          busy={access.busy}
          roleAfter={roleAfter}
          setRoleAfter={setRoleAfter}
          setEditing={setEditing}
          setName={setName}
          setCodes={setCodes}
          onSave={saveRole}
        />

        <GrantAccessPanel
          copy={copy}
          users={access.users.data}
          roles={access.roles.data}
          locations={access.locations.data}
          grants={access.grants.data}
          busy={access.busy}
          backofficeUserId={backofficeUserId}
          roleId={roleId}
          locationId={locationId}
          scope={scope}
          userAfter={userAfter}
          locationAfter={locationAfter}
          grantAfter={grantAfter}
          setBackofficeUserId={setBackofficeUserId}
          setRoleId={setRoleId}
          setLocationId={setLocationId}
          setScope={setScope}
          setUserAfter={setUserAfter}
          setLocationAfter={setLocationAfter}
          setGrantAfter={setGrantAfter}
          onAddGrant={addGrant}
          onRequestRevoke={setPendingRevoke}
        />
      </div>

      <AccessConfirmDialog
        open={pendingRevoke !== null}
        copy={copy}
        busy={access.busy}
        returnFocusTo={pendingRevoke?.trigger ?? null}
        onCancel={() => setPendingRevoke(null)}
        onConfirm={() => void revokeGrant()}
      />
    </div>
  );
}
