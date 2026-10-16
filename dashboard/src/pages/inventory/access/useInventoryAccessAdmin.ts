import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useAuthFetch } from '@/hooks/useAuthFetch';
import {
  parseGrantPage,
  parseLocationPage,
  parsePermissionCatalog,
  parseRolePage,
  parseUserPage,
} from './contracts';

export type AccessScope = 'company' | 'location';

interface AdminQueryState {
  roleAfter: number;
  userAfter: number;
  locationAfter: number;
  grantAfter: number;
  backofficeUserId: string;
  scope: AccessScope;
}

export function useInventoryAccessAdmin(state: AdminQueryState) {
  const fetcher = useAuthFetch();
  const cache = useQueryClient();
  const [busy, setBusy] = useState(false);
  const queryPrefix = [
    'inventory-access-admin',
    localStorage.getItem('company_id'),
    localStorage.getItem('principal_id'),
    localStorage.getItem('backoffice_user_id'),
  ];

  const roles = useQuery({
    queryKey: [...queryPrefix, 'roles', state.roleAfter],
    queryFn: async ({ signal }) => parseRolePage(
      await fetcher(`/inventory/access/roles?after_id=${state.roleAfter}`, { signal }),
    ),
    retry: false,
  });
  const users = useQuery({
    queryKey: [...queryPrefix, 'users', state.userAfter],
    queryFn: async ({ signal }) => parseUserPage(
      await fetcher(`/inventory/access/users?after_id=${state.userAfter}`, { signal }),
    ),
    retry: false,
  });
  const locations = useQuery({
    queryKey: [...queryPrefix, 'locations', state.locationAfter],
    queryFn: async ({ signal }) => parseLocationPage(
      await fetcher(`/inventory/access/locations?after_id=${state.locationAfter}`, { signal }),
    ),
    retry: false,
  });
  const catalog = useQuery({
    queryKey: [...queryPrefix, 'catalog'],
    queryFn: async ({ signal }) => parsePermissionCatalog(
      await fetcher('/inventory/access/catalog', { signal }),
    ),
    retry: false,
  });
  const grants = useQuery({
    queryKey: [
      ...queryPrefix,
      'grants',
      state.backofficeUserId,
      state.scope,
      state.grantAfter,
    ],
    enabled: Boolean(state.backofficeUserId),
    queryFn: async ({ signal }) => parseGrantPage(
      await fetcher(
        `/inventory/access/users/${state.backofficeUserId}/grants?scope=${state.scope}&after_id=${state.grantAfter}`,
        { signal },
      ),
    ),
    retry: false,
  });

  const mutate = async (url: string, method: string, body?: unknown): Promise<boolean> => {
    if (busy) return false;
    setBusy(true);
    try {
      await fetcher(url, {
        method,
        ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      });
      await cache.invalidateQueries({ queryKey: ['inventory-access-admin'] });
      await cache.invalidateQueries({ queryKey: ['inventory-access'] });
      return true;
    } finally {
      setBusy(false);
    }
  };

  const error = [roles, users, locations, catalog, grants].find(query => query.isError)?.error;
  return { roles, users, locations, catalog, grants, mutate, busy, error };
}
