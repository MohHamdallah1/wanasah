import { useCallback, useEffect, useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useAuthFetch } from './useAuthFetch';
import { useDashboardSession } from './useDashboardSession';
import { isDashboardSessionCurrent, type DashboardSession } from '@/lib/authStorage';

type InventoryAccessContractError = Error & { code: string };

const inventoryAccessContractError = (code: string): never => {
  const error = new Error(code) as InventoryAccessContractError;
  error.code = code;
  throw error;
};

export interface InventoryCapabilities {
  company_id: number;
  principal_id: number;
  backoffice_user_id: number;
  is_company_owner: boolean;
  location_id: number | null;
  permissions: string[];
  any_permissions: string[];
  location_permissions: string[];
}

export function hasInventoryPermission(data: InventoryCapabilities, code: string): boolean {
  return data.permissions.includes(code) || data.location_permissions.includes(code);
}

const parsePermissionCodes = (
  value: unknown,
  code = 'INVENTORY_ACCESS_RESPONSE_INVALID',
): string[] => {
  const items: unknown[] =
    Array.isArray(value)
      ? value
      : inventoryAccessContractError(code);
  if (
    !items.every(
      (item) => typeof item === 'string'
    )
  ) {
    inventoryAccessContractError(code);
  }
  return items.map(
    (item) => item as string
  );
};

export function parseInventoryCapabilities(raw: unknown): InventoryCapabilities {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) {
    inventoryAccessContractError('INVENTORY_ACCESS_RESPONSE_INVALID');
  }
  const value = raw as Record<string, unknown>;
  const companyId = value.company_id;
  const principalId = value.principal_id;
  const backofficeUserId = value.backoffice_user_id;
  const isCompanyOwner = value.is_company_owner;
  const locationId = value.location_id;

  if (
    typeof companyId !== 'number' ||
    !Number.isSafeInteger(companyId) ||
    companyId <= 0 ||
    typeof principalId !== 'number' ||
    !Number.isSafeInteger(principalId) ||
    principalId <= 0 ||
    typeof backofficeUserId !== 'number' ||
    !Number.isSafeInteger(backofficeUserId) ||
    backofficeUserId <= 0 ||
    typeof isCompanyOwner !== 'boolean' ||
    (
      locationId !== null &&
      (
        typeof locationId !== 'number' ||
        !Number.isSafeInteger(locationId) ||
        locationId <= 0
      )
    )
  ) {
    inventoryAccessContractError('INVENTORY_ACCESS_RESPONSE_INVALID');
  }

  return {
    company_id: companyId as number,
    principal_id: principalId as number,
    backoffice_user_id: backofficeUserId as number,
    is_company_owner: isCompanyOwner as boolean,
    location_id: locationId as number | null,
    permissions: parsePermissionCodes(value.permissions),
    any_permissions: parsePermissionCodes(value.any_permissions),
    location_permissions: parsePermissionCodes(value.location_permissions),
  };
}

export function parseInventoryLocationCapabilities(
  raw: unknown,
  expectedLocationIds: number[],
): Record<number, string[]> {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) {
    inventoryAccessContractError('INVENTORY_LOCATION_CAPABILITIES_RESPONSE_INVALID');
  }
  const locations = (raw as Record<string, unknown>).locations;
  if (!locations || typeof locations !== 'object' || Array.isArray(locations)) {
    inventoryAccessContractError('INVENTORY_LOCATION_CAPABILITIES_RESPONSE_INVALID');
  }

  const expected = new Set(expectedLocationIds);
  const result: Record<number, string[]> = {};
  for (const [id, codes] of Object.entries(locations)) {
    const numericId = Number(id);
    if (!Number.isSafeInteger(numericId) || !expected.has(numericId)) {
      inventoryAccessContractError('INVENTORY_LOCATION_CAPABILITIES_RESPONSE_INVALID');
    }
    result[numericId] = parsePermissionCodes(
      codes,
      'INVENTORY_LOCATION_CAPABILITIES_RESPONSE_INVALID',
    );
  }
  return result;
}

type InventorySessionIdentity = {
  companyId: number;
  principalId: number;
  backofficeUserId: number;
};

const positiveStoredId = (value: unknown): number | null => {
  const id = typeof value === 'string' && value.trim() ? Number(value) : NaN;
  return Number.isSafeInteger(id) && id > 0 ? id : null;
};

const inventorySessionIdentity = (
  session: DashboardSession | null,
): InventorySessionIdentity | null => {
  if (!session) return null;
  try {
    const raw: unknown = JSON.parse(session.identity);
    if (!Array.isArray(raw) || raw.length < 3) return null;
    const companyId = positiveStoredId(raw[0]);
    const principalId = positiveStoredId(raw[1]);
    const backofficeUserId = positiveStoredId(raw[2]);
    if (companyId === null || principalId === null || backofficeUserId === null) return null;
    return { companyId, principalId, backofficeUserId };
  } catch {
    return null;
  }
};

const requireInventorySessionIdentity = (
  session: DashboardSession | null,
  identity: InventorySessionIdentity | null,
): InventorySessionIdentity => {
  if (!session || !identity || !isDashboardSessionCurrent(session)) {
    inventoryAccessContractError('INVENTORY_ACCESS_SCOPE_MISMATCH');
  }
  return identity;
};

const assertInventoryCapabilitiesScope = (
  result: InventoryCapabilities,
  locationId: number | null,
  session: DashboardSession | null,
  identity: InventorySessionIdentity | null,
): void => {
  const currentIdentity = requireInventorySessionIdentity(session, identity);
  if (
    result.company_id !== currentIdentity.companyId ||
    result.principal_id !== currentIdentity.principalId ||
    result.backoffice_user_id !== currentIdentity.backofficeUserId ||
    result.location_id !== locationId
  ) {
    inventoryAccessContractError('INVENTORY_ACCESS_SCOPE_MISMATCH');
  }
};

export function useInventoryAccess(locationId: number | null = null) {
  const authFetch = useAuthFetch();
  const session = useDashboardSession();
  const identity = useMemo(() => inventorySessionIdentity(session), [session]);
  const sessionCurrent = Boolean(
    session && identity && isDashboardSessionCurrent(session),
  );
  const query = useQuery({
    queryKey: [
      'inventory-access',
      session?.generation ?? null,
      session?.identity ?? null,
      locationId,
    ],
    enabled: sessionCurrent,
    queryFn: async ({ signal }) => {
      requireInventorySessionIdentity(session, identity);
      const result = parseInventoryCapabilities(await authFetch(
        `/inventory/access/me${locationId === null ? '' : `?location_id=${locationId}`}`,
        { signal },
      ));
      assertInventoryCapabilitiesScope(result, locationId, session, identity);
      return result;
    },
    placeholderData: undefined,
    staleTime: 0,
    refetchOnWindowFocus: true,
    retry: false,
  });
  const data = !sessionCurrent || query.isError ? undefined : query.data;
  const { refetch } = query;
  useEffect(() => {
    const refresh = () => { void refetch(); };
    window.addEventListener('inventory-permission-denied', refresh);
    return () => window.removeEventListener('inventory-permission-denied', refresh);
  }, [refetch]);
  const can = useCallback((code: string) => Boolean(data && (
    data.permissions.includes(code) || (locationId !== null && data.location_permissions.includes(code))
  )), [data, locationId]);
  const canAny = useCallback((code: string) => Boolean(data?.any_permissions.includes(code)), [data]);
  return { ...query, data, can, canAny, isCompanyOwner: data?.is_company_owner === true };
}


export function useLocationCapabilities(locationIds: number[]) {
  const authFetch = useAuthFetch();
  const session = useDashboardSession();
  const identity = useMemo(() => inventorySessionIdentity(session), [session]);
  const sessionCurrent = Boolean(
    session && identity && isDashboardSessionCurrent(session),
  );
  const ids = [...new Set(locationIds)].sort((a, b) => a - b);
  const query = useQuery({
    queryKey: [
      'inventory-access',
      session?.generation ?? null,
      session?.identity ?? null,
      'batch',
      ids,
    ],
    enabled: sessionCurrent && ids.length > 0,
    queryFn: async ({ signal }) => {
      requireInventorySessionIdentity(session, identity);
      const result = parseInventoryLocationCapabilities(
        await authFetch('/inventory/access/locations/capabilities', {
          method: 'POST', signal, body: JSON.stringify({ location_ids: ids }),
        }),
        ids,
      );
      requireInventorySessionIdentity(session, identity);
      return result;
    },
    placeholderData: undefined,
    staleTime: 0,
    retry: false,
    refetchOnWindowFocus: true,
  });
  const { refetch } = query;
  useEffect(() => {
    if (!ids.length) return;
    const refresh = () => { void refetch(); };
    window.addEventListener('inventory-permission-denied', refresh);
    return () => window.removeEventListener('inventory-permission-denied', refresh);
  }, [refetch, ids.length]);
  return (locationId: number, code: string) =>
    sessionCurrent && !query.isError && query.data?.[locationId]?.includes(code) === true;
}
