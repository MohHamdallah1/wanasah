import { useCallback, useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useAuthFetch } from './useAuthFetch';

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

export function parseInventoryCapabilities(raw: unknown): InventoryCapabilities {
  if (!raw || typeof raw !== 'object') throw new Error('عقد الصلاحيات غير صالح.');
  const value = raw as Record<string, unknown>;
  for (const key of ['company_id', 'driver_id']) {
    if (!Number.isSafeInteger(value[key]) || Number(value[key]) <= 0) throw new Error('هوية الصلاحيات غير صالحة.');
  }
  if (typeof value.is_company_admin !== 'boolean' ||
      (value.location_id !== null && (!Number.isSafeInteger(value.location_id) || Number(value.location_id) <= 0))) {
    throw new Error('نطاق الصلاحيات غير صالح.');
  }
  for (const key of ['permissions', 'any_permissions', 'location_permissions']) {
    if (!Array.isArray(value[key]) || !(value[key] as unknown[]).every(item => typeof item === 'string')) {
      throw new Error('قائمة الصلاحيات غير صالحة.');
    }
  }
  return value as unknown as InventoryCapabilities;
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
      if (result.location_id !== locationId) throw new Error('استجابة الصلاحيات لا تطابق الموقع.');
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
        throw new Error('عقد صلاحيات المواقع غير صالح.');
      }
      const result: Record<number, string[]> = {};
      for (const [id, codes] of Object.entries(raw.locations)) {
        if (!ids.includes(Number(id)) || !Array.isArray(codes) || !codes.every(c => typeof c === 'string')) {
          throw new Error('نطاق صلاحيات المواقع غير صالح.');
        }
        result[Number(id)] = codes;
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
