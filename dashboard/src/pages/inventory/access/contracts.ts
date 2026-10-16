export interface AccessRole {
  id: number;
  name: string;
  permissions: string[];
  is_system_role: boolean;
}

export interface AccessUser {
  principal_id: number;
  backoffice_user_id: number;
  full_name: string;
  is_company_owner: boolean;
  is_active: boolean;
}

export interface AccessLocation {
  id: number;
  name: string;
  code: string;
  location_type: 'WAREHOUSE' | 'VEHICLE';
  is_active?: boolean;
}

export interface AccessGrant {
  id: number;
  role_id: number;
  location_id: number | null;
}

export interface AccessPage<T> {
  items: T[];
  next_id: number | null;
}

export interface PermissionCatalog {
  permissions: string[];
  company_only: string[];
}

type InventoryAccessAdminContractError = Error & { code: string };

export const accessAdminContractError = (): never => {
  const error = new Error('INVENTORY_ACCESS_ADMIN_RESPONSE_INVALID') as InventoryAccessAdminContractError;
  error.code = 'INVENTORY_ACCESS_ADMIN_RESPONSE_INVALID';
  throw error;
};

const asRecord = (value: unknown): Record<string, unknown> => {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) accessAdminContractError();
  return value as Record<string, unknown>;
};

const asPositiveInt = (value: unknown): number => {
  if (typeof value !== 'number' || !Number.isSafeInteger(value) || value <= 0) accessAdminContractError();
  return value;
};

const asText = (value: unknown): string => {
  if (typeof value !== 'string' || !value.trim()) accessAdminContractError();
  return value;
};

const asBoolean = (value: unknown): boolean => {
  if (typeof value !== 'boolean') accessAdminContractError();
  return value;
};

const asStringArray = (value: unknown): string[] => {
  if (!Array.isArray(value) || !value.every(item => typeof item === 'string')) accessAdminContractError();
  return value as string[];
};

const parsePage = <T,>(raw: unknown, parseItem: (value: unknown) => T): AccessPage<T> => {
  const page = asRecord(raw);
  if (!Array.isArray(page.items)) accessAdminContractError();
  return {
    items: page.items.map(parseItem),
    next_id: page.next_id === null ? null : asPositiveInt(page.next_id),
  };
};

export const parseRolePage = (raw: unknown): AccessPage<AccessRole> => parsePage(raw, value => {
  const row = asRecord(value);
  return {
    id: asPositiveInt(row.id),
    name: asText(row.name),
    permissions: asStringArray(row.permissions),
    is_system_role: asBoolean(row.is_system_role),
  };
});

export const parseUserPage = (raw: unknown): AccessPage<AccessUser> => parsePage(raw, value => {
  const row = asRecord(value);
  return {
    principal_id: asPositiveInt(row.principal_id),
    backoffice_user_id: asPositiveInt(row.backoffice_user_id),
    full_name: asText(row.full_name),
    is_company_owner: asBoolean(row.is_company_owner),
    is_active: asBoolean(row.is_active),
  };
});

export const parseLocationPage = (raw: unknown): AccessPage<AccessLocation> => parsePage(raw, value => {
  const row = asRecord(value);
  const locationType = asText(row.location_type);
  if (locationType !== 'WAREHOUSE' && locationType !== 'VEHICLE') accessAdminContractError();
  return {
    id: asPositiveInt(row.id),
    name: asText(row.name),
    code: asText(row.code),
    location_type: locationType,
    ...(typeof row.is_active === 'boolean' ? { is_active: row.is_active } : {}),
  };
});

export const parseGrantPage = (raw: unknown): AccessPage<AccessGrant> => parsePage(raw, value => {
  const row = asRecord(value);
  return {
    id: asPositiveInt(row.id),
    role_id: asPositiveInt(row.role_id),
    location_id: row.location_id === null ? null : asPositiveInt(row.location_id),
  };
});

export const parsePermissionCatalog = (raw: unknown): PermissionCatalog => {
  const row = asRecord(raw);
  const permissions = asStringArray(row.permissions);
  const companyOnly = asStringArray(row.company_only);
  if (!companyOnly.every(code => permissions.includes(code))) accessAdminContractError();
  return { permissions, company_only: companyOnly };
};
