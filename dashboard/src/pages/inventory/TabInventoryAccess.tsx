import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { useAuthFetch } from '@/hooks/useAuthFetch';
import { apiErrorMessage } from '@/lib/apiErrors';

interface Role { id: number; name: string; permissions: string[]; is_system_role: boolean }
interface User { principal_id: number; backoffice_user_id: number; full_name: string; is_company_owner: boolean; is_active: boolean }
interface Location { id: number; name: string; code: string; location_type: string }
interface Grant { id: number; role_id: number; location_id: number | null }
interface Page<T> { items: T[]; next_id: number | null }
interface PermissionCatalog { permissions: string[]; company_only: string[] }

type InventoryAccessAdminContractError = Error & { code: string };

const accessAdminContractError = (): never => {
  const error = new Error('INVENTORY_ACCESS_ADMIN_RESPONSE_INVALID') as InventoryAccessAdminContractError;
  error.code = 'INVENTORY_ACCESS_ADMIN_RESPONSE_INVALID';
  throw error;
};

const asRecord = (value: unknown): Record<string, unknown> => {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    accessAdminContractError();
  }
  return value as Record<string, unknown>;
};

const asPositiveInt = (value: unknown): number => {
  if (typeof value !== 'number' || !Number.isSafeInteger(value) || value <= 0) {
    accessAdminContractError();
  }
  return value as number;
};

const asText = (value: unknown): string => {
  if (typeof value !== 'string' || !value.trim()) {
    accessAdminContractError();
  }
  return value as string;
};

const asBoolean = (value: unknown): boolean => {
  if (typeof value !== 'boolean') accessAdminContractError();
  return value as boolean;
};

const asStringArray = (value: unknown): string[] => {
  const items: unknown[] =
    Array.isArray(value)
      ? value
      : accessAdminContractError();
  if (
    !items.every(
      (item) => typeof item === 'string'
    )
  ) {
    accessAdminContractError();
  }
  return items.map(
    (item) => item as string
  );
};

const parsePage = <T,>(
  raw: unknown,
  parseItem: (value: unknown) => T,
): Page<T> => {
  const page = asRecord(raw);
  const rawItems = page.items;
  if (!Array.isArray(rawItems)) accessAdminContractError();
  const nextId =
    page.next_id === null
      ? null
      : asPositiveInt(page.next_id);
  return {
    items: (rawItems as unknown[]).map(parseItem),
    next_id: nextId,
  };
};

const parseRolePage = (raw: unknown): Page<Role> =>
  parsePage(raw, (value) => {
    const row = asRecord(value);
    return {
      id: asPositiveInt(row.id),
      name: asText(row.name),
      permissions: asStringArray(row.permissions),
      is_system_role: asBoolean(row.is_system_role),
    };
  });

const parseUserPage = (raw: unknown): Page<User> =>
  parsePage(raw, (value) => {
    const row = asRecord(value);
    return {
      principal_id: asPositiveInt(row.principal_id),
      backoffice_user_id: asPositiveInt(row.backoffice_user_id),
      full_name: asText(row.full_name),
      is_company_owner: asBoolean(row.is_company_owner),
      is_active: asBoolean(row.is_active),
    };
  });

const parseLocationPage = (raw: unknown): Page<Location> =>
  parsePage(raw, (value) => {
    const row = asRecord(value);
    return {
      id: asPositiveInt(row.id),
      name: asText(row.name),
      code: asText(row.code),
      location_type: asText(row.location_type),
    };
  });

const parseGrantPage = (raw: unknown): Page<Grant> =>
  parsePage(raw, (value) => {
    const row = asRecord(value);
    return {
      id: asPositiveInt(row.id),
      role_id: asPositiveInt(row.role_id),
      location_id:
        row.location_id === null
          ? null
          : asPositiveInt(row.location_id),
    };
  });

const parsePermissionCatalog = (raw: unknown): PermissionCatalog => {
  const row = asRecord(raw);
  return {
    permissions: asStringArray(row.permissions),
    company_only: asStringArray(row.company_only),
  };
};

const MANAGEMENT_PERMISSION_LABEL_KEYS: Record<string, string> = {
  'representative.read': 'representativesVehicles.representatives.permissionCatalog.read',
  'representative.manage': 'representativesVehicles.representatives.permissionCatalog.manage',
  'representative.credentials.reset': 'representativesVehicles.representatives.permissionCatalog.credentialsReset',
  'vehicle.read': 'representativesVehicles.vehicles.permissionCatalog.read',
  'vehicle.manage': 'representativesVehicles.vehicles.permissionCatalog.manage',
};

const LABELS: Record<string, string> = {
  'location.read': 'رؤية الموقع', 'location.create': 'إنشاء مستودع',
  'location.update': 'تعديل مستودع', 'location.state': 'تفعيل وإيقاف مستودع',
  'inventory.read': 'قراءة الأرصدة', 'inbound.create': 'توريد', 'ledger.read': 'قراءة سجل الحركات',
  'ledger.adjust': 'تصحيح توريد', 'catalog.read': 'قراءة الأصناف', 'catalog.manage': 'إدارة الأصناف',
  'transfer.read': 'قراءة الحوالات', 'transfer.send': 'إرسال حوالة', 'transfer.receive': 'استلام حوالة',
  'transfer.cancel': 'إلغاء حوالة من المصدر', 'transfer.reject': 'رفض حوالة في الوجهة',
  'transfer.destination': 'اختيار الموقع وجهة للحوالة', 'inventory.fefo_override': 'تجاوز FEFO موثق',
  'stocktake.read': 'رؤية جلسات الجرد', 'stocktake.start': 'بدء جرد', 'stocktake.count': 'تنفيذ العد',
  'stocktake.review': 'مراجعة الجرد', 'stocktake.approve': 'اعتماد وترحيل الجرد',
  'stocktake.recount': 'تفويض إعادة العد', 'stocktake.cancel': 'إلغاء الجرد',
  'dispatch.read': 'قراءة التوزيع', 'dispatch.execute': 'تنفيذ التوزيع',
};

export function TabInventoryAccess() {
  const fetcher = useAuthFetch();
  const { t, i18n } = useTranslation();
  const cache = useQueryClient();
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
  const [scope, setScope] = useState<'company' | 'location'>('location');
  const [busy, setBusy] = useState(false);
  const queryPrefix = ['inventory-access-admin', localStorage.getItem('company_id'), localStorage.getItem('principal_id'), localStorage.getItem('backoffice_user_id')];
  const roles = useQuery<Page<Role>>({ queryKey: [...queryPrefix, 'roles', roleAfter],
    queryFn: async ({signal}) => parseRolePage(await fetcher(`/inventory/access/roles?after_id=${roleAfter}`, {signal})) });
  const users = useQuery<Page<User>>({ queryKey: [...queryPrefix, 'users', userAfter],
    queryFn: async ({signal}) => parseUserPage(await fetcher(`/inventory/access/users?after_id=${userAfter}`, {signal})) });
  const locations = useQuery<Page<Location>>({ queryKey: [...queryPrefix, 'locations', locationAfter],
    queryFn: async ({signal}) => parseLocationPage(await fetcher(`/inventory/access/locations?after_id=${locationAfter}`, {signal})) });
  const catalog = useQuery<PermissionCatalog>({ queryKey: [...queryPrefix, 'catalog'],
    queryFn: async ({signal}) => parsePermissionCatalog(await fetcher('/inventory/access/catalog', {signal})) });
  const grants = useQuery<Page<Grant>>({ queryKey: [...queryPrefix, 'grants', backofficeUserId, scope, grantAfter], enabled: Boolean(backofficeUserId),
    queryFn: async ({signal}) => parseGrantPage(await fetcher(`/inventory/access/users/${backofficeUserId}/grants?scope=${scope}&after_id=${grantAfter}`, {signal})) });
  const mutate = async (url: string, method: string, body?: unknown) => {
    if (busy) return;
    setBusy(true);
    try {
      await fetcher(url, {method, ...(body === undefined ? {} : {body: JSON.stringify(body)})});
      await cache.invalidateQueries({queryKey: ['inventory-access-admin']});
      await cache.invalidateQueries({queryKey: ['inventory-access']});
      toast.success(t('inventoryAccessAdmin.saved'));
    } catch (error) { toast.error(apiErrorMessage(error, t('inventoryAccessAdmin.errors.saveFailed'))); }
    finally { setBusy(false); }
  };
  const paging = (next: number | null | undefined, current: number, set: (n:number)=>void) => (
    <span className="inventory-inline-paging">
      <button type="button" disabled={!current || busy} onClick={()=>set(0)}>البداية</button>
      <button type="button" disabled={!next || busy} onClick={()=>next && set(next)}>التالي</button>
    </span>
  );
  const error = [roles,users,locations,catalog,grants].find(q=>q.isError)?.error;
  return <div className="inventory-view inventory-access overflow-auto flex-1 space-y-5 p-1" dir={i18n.dir()}>
    <header className="glass-card inventory-section-header rounded-2xl p-5">
      <div>
        <p className="inventory-eyebrow">{t('inventoryAccessAdmin.eyebrow')}</p>
        <h2 className="font-black text-xl text-slate-900">{t('inventoryAccessAdmin.title')}</h2>
        <p className="text-sm text-slate-600 mt-1 leading-6">{t('inventoryAccessAdmin.description')}</p>
      </div>
    </header>

    {error && <p role="alert" className="inventory-alert-banner p-3 text-sm font-bold">{apiErrorMessage(error, t('inventoryAccessAdmin.errors.loadFailed'))}</p>}

    <div className="inventory-access-grid">
      <section className="glass-card inventory-access-panel p-5 rounded-2xl space-y-4">
        <div className="inventory-panel-heading">
          <div>
            <p className="inventory-eyebrow">بناء الأدوار</p>
            <h3 className="font-black text-slate-900">{editing ? 'تعديل دور' : 'دور جديد'}</h3>
          </div>
          <span className="inventory-count-chip">{codes.length} صلاحية محددة</span>
        </div>

        <label className="inventory-field">
          <span>اسم الدور</span>
          <input aria-label="اسم الدور" value={name} maxLength={100} onChange={e=>setName(e.target.value)} placeholder="مثال: مسؤول الاستلام" />
        </label>

        <div className="inventory-permission-grid">
          {catalog.data?.permissions.map(code=><label key={code} className="inventory-permission-option">
            <input type="checkbox" checked={codes.includes(code)} onChange={e=>setCodes(old=>e.target.checked?[...old,code]:old.filter(c=>c!==code))}/>
            <span>{MANAGEMENT_PERMISSION_LABEL_KEYS[code] ? t(MANAGEMENT_PERMISSION_LABEL_KEYS[code]) : code === 'supplier.read' ? t('suppliers.permissions.read') : code === 'supplier.manage' ? t('suppliers.permissions.manage') : LABELS[code] || code}{catalog.data.company_only.includes(code) ? <small>{t('suppliers.permissions.companyOnly')}</small> : null}</span>
          </label>)}
        </div>

        <p className="inventory-guidance">للتنقل في المخزون امنح رؤية الموقع؛ التوريد والعد يحتاجان قراءة الأصناف. صلاحيات العد والمراجعة والاعتماد مستقلة.</p>
        <div className="inventory-action-row">
          <button type="button" disabled={busy || !name.trim() || !catalog.data} className="inventory-primary-action"
            onClick={()=>void mutate(`/inventory/access/roles${editing ? `/${editing}` : ''}`, editing?'PUT':'POST', {name, permissions:codes})}>حفظ الدور</button>
          <button type="button" className="inventory-secondary-action" onClick={()=>{setEditing(null);setName('');setCodes([]);}}>دور جديد</button>
        </div>

        <div className="inventory-role-list">{roles.data?.items.map(role=><button type="button" key={role.id} disabled={role.is_system_role}
          onClick={()=>{setEditing(role.id);setName(role.name);setCodes(role.permissions);}} className="inventory-role-chip">
          <span>{role.name}</span><small>{role.permissions.length} صلاحية{role.is_system_role ? ' · نظامي' : ''}</small>
        </button>)}</div>
        {paging(roles.data?.next_id,roleAfter,setRoleAfter)}
      </section>

      <section className="glass-card inventory-access-panel p-5 rounded-2xl space-y-4">
        <div className="inventory-panel-heading">
          <div>
            <p className="inventory-eyebrow">الإسناد</p>
            <h3 className="font-black text-slate-900">منح المستخدم</h3>
          </div>
          <span className="inventory-count-chip">{scope==='location' ? 'نطاق موقع' : 'نطاق شركة'}</span>
        </div>

        <div className="inventory-grant-form">
          <label className="inventory-field inventory-field--wide">
            <span>{t('inventoryAccessAdmin.user')}</span>
            <select aria-label={t('inventoryAccessAdmin.user')} value={backofficeUserId} onChange={e=>{setBackofficeUserId(e.target.value);setGrantAfter(0);}}>
              <option value="">{t('inventoryAccessAdmin.chooseUser')}</option>{users.data?.items.map(user=><option key={user.backoffice_user_id} value={user.backoffice_user_id}>{user.full_name}{user.is_company_owner ? ` — ${t('inventoryAccessAdmin.companyOwner')}` : ''}{!user.is_active ? ` — ${t('inventoryAccessAdmin.inactive')}` : ''}</option>)}
            </select>
          </label>
          {paging(users.data?.next_id,userAfter,n=>{setUserAfter(n);setBackofficeUserId('');})}

          <label className="inventory-field">
            <span>نطاق المنح</span>
            <select aria-label="نطاق المنح" value={scope} onChange={e=>{setScope(e.target.value as 'company'|'location');setGrantAfter(0);}}>
              <option value="location">موقع محدد</option><option value="company">الشركة كاملة</option>
            </select>
          </label>
          <label className="inventory-field">
            <span>الدور</span>
            <select aria-label="الدور" value={roleId} onChange={e=>setRoleId(e.target.value)}>
              <option value="">اختر الدور</option>{roles.data?.items.map(role=><option key={role.id} value={role.id}>{role.name}</option>)}
            </select>
          </label>
          {scope==='location' && <div className="inventory-field inventory-field--wide">
            <label>
              <span>المستودع أو السيارة</span>
              <select aria-label="الموقع" value={locationId} onChange={e=>setLocationId(e.target.value)}>
                <option value="">اختر المستودع أو السيارة</option>{locations.data?.items.map(loc=><option key={loc.id} value={loc.id}>{loc.name} — {loc.code} ({loc.location_type})</option>)}
              </select>
            </label>
            {paging(locations.data?.next_id,locationAfter,n=>{setLocationAfter(n);setLocationId('');})}
          </div>}
        </div>

        <button type="button" disabled={busy || !backofficeUserId || !roleId || (scope==='location' && !locationId)} className="inventory-primary-action"
          onClick={()=>void mutate(`/inventory/access/users/${backofficeUserId}/grants`,'POST',{role_id:Number(roleId),location_id:scope==='company'?null:Number(locationId)})}>إضافة المنح</button>

        <div className="inventory-grant-list">
          {!backofficeUserId && <p className="inventory-muted-state">اختر مستخدماً لعرض المنح الحالية.</p>}
          {backofficeUserId && grants.data?.items.length === 0 && <p className="inventory-muted-state">لا توجد منح ضمن هذا النطاق.</p>}
          {grants.data?.items.map(grant=><div key={grant.id} className="inventory-grant-row">
            <span><strong>{roles.data?.items.find(role=>role.id===grant.role_id)?.name || `دور #${grant.role_id}`}</strong><small>{grant.location_id ? locations.data?.items.find(location=>location.id===grant.location_id)?.name || `موقع #${grant.location_id}` : 'الشركة كاملة'}</small></span>
            <button type="button" disabled={busy} onClick={()=>void mutate(`/inventory/access/users/${backofficeUserId}/grants/${grant.id}?scope=${scope}`,'DELETE')}>سحب المنح</button>
          </div>)}
        </div>
        {paging(grants.data?.next_id,grantAfter,setGrantAfter)}
      </section>
    </div>
  </div>;
}