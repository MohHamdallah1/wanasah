import { useCallback, useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useAuthFetch } from './useAuthFetch';

type InventoryAccessContractError = Error & { code: string };

const inventoryAccessContractError = (code: string): never => {
  const error = new Error(code) as InventoryAccessContractError;
  error.code = code;
  throw error;
};

export interface InventoryCapabilities {
  company_id: number;
  driver_id: number;
  is_company_admin: boolean;
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
  if (
    !Array.isArray(value) ||
    !value.every((item) => typeof item === 'string')
  ) {
    inventoryAccessContractError(code);
  }
  return value.map((item) => item as string);
};

export function parseInventoryCapabilities(raw: unknown): InventoryCapabilities {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) {
    inventoryAccessContractError('INVENTORY_ACCESS_RESPONSE_INVALID');
  }
  const value = raw as Record<string, unknown>;
  const companyId = value.company_id;
  const driverId = value.driver_id;
  const isCompanyAdmin = value.is_company_admin;
  const locationId = value.location_id;

  if (
    typeof companyId !== 'number' ||
    !Number.isSafeInteger(companyId) ||
    companyId <= 0 ||
    typeof driverId !== 'number' ||
    !Number.isSafeInteger(driverId) ||
    driverId <= 0 ||
    typeof isCompanyAdmin !== 'boolean' ||
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
    company_id: companyId,
    driver_id: driverId,
    is_company_admin: isCompanyAdmin,
    location_id: locationId,
    permissions: parsePermissionCodes(value.permissions),
    any_permissions: parsePermissionCodes(value.any_permissions),
    location_permissions: parsePermissionCodes(value.location_permissions),
  };
}

export function useInventoryAccess(locationId: number | null = null) {
  const authFetch = useAuthFetch();
  // Cache partitioning is UX only; the server independently verifies the token.
  const company = localStorage.getItem('company_id');
  const user = localStorage.getItem('driver_id');
  const query = useQuery({
    queryKey: ['inventory-access', company, user, locationId],
    queryFn: async ({ signal }) => {
      const result = parseInventoryCapabilities(await authFetch(
        `/inventory/access/me${locationId === null ? '' : `?location_id=${locationId}`}`, { signal }));
      if (result.location_id !== locationId) inventoryAccessContractError('INVENTORY_ACCESS_SCOPE_MISMATCH');
      return result;
    },
    staleTime: 0,
    refetchOnWindowFocus: true,
    retry: false,
  });
  const data = query.isError ? undefined : query.data;
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
  return { ...query, data, can, canAny, isCompanyAdmin: data?.is_company_admin === true };
}


export function useLocationCapabilities(locationIds: number[]) {
  const authFetch = useAuthFetch();
  const ids = [...new Set(locationIds)].sort((a, b) => a - b);
  const query = useQuery({
    queryKey: ['inventory-access', localStorage.getItem('company_id'), localStorage.getItem('driver_id'), 'batch', ids],
    enabled: ids.length > 0,
    queryFn: async ({ signal }) => {
      const raw = await authFetch('/inventory/access/locations/capabilities', {
        method: 'POST', signal, body: JSON.stringify({ location_ids: ids }),
      }) as { locations?: Record<string, unknown> };
      if (!raw?.locations || typeof raw.locations !== 'object' || Array.isArray(raw.locations)) {
        inventoryAccessContractError('INVENTORY_LOCATION_CAPABILITIES_RESPONSE_INVALID');
      }
      const result: Record<number, string[]> = {};
      for (const [id, codes] of Object.entries(raw.locations)) {
        const numericId = Number(id);
        if (!ids.includes(numericId)) {
          inventoryAccessContractError('INVENTORY_LOCATION_CAPABILITIES_RESPONSE_INVALID');
        }
        result[numericId] = parsePermissionCodes(
          codes,
          'INVENTORY_LOCATION_CAPABILITIES_RESPONSE_INVALID',
        );
      }
      return result;
    },
    staleTime: 0, retry: false, refetchOnWindowFocus: true,
  });
  const { refetch } = query;
  useEffect(() => {
    if (!ids.length) return;
    const refresh = () => { void refetch(); };
    window.addEventListener('inventory-permission-denied', refresh);
    return () => window.removeEventListener('inventory-permission-denied', refresh);
  }, [refetch, ids.length]);
  return (locationId: number, code: string) => !query.isError && query.data?.[locationId]?.includes(code) === true;
}
