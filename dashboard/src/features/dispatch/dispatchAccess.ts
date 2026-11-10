import type { InventoryCapabilities } from "@/hooks/useInventoryAccess";

export type DispatchPrivileges = {
  routes: boolean;
  zones: boolean;
  zoneManage: boolean;
  launch: boolean;
  shortages: boolean;
  shortageCreate: boolean;
  shortageCancel: boolean;
  shortageEdit: boolean;
};

/**
 * Existing backend effective grants are authoritative. A company-wide grant
 * permits zone mutations; any-location dispatch.read permits the scoped reads
 * already exposed by /dispatch/init and /dispatch/shops. Owner is not a UI
 * privilege shortcut.
 */
export function dispatchPrivileges(access: InventoryCapabilities | undefined): DispatchPrivileges {
  const company = new Set(access?.permissions ?? []);
  const anyLocation = new Set(access?.any_permissions ?? []);
  const shortageCreate = company.has("shortage.create");
  const shortageCancel = company.has("shortage.cancel");
  return {
    routes: anyLocation.has("dispatch.read"),
    zones: anyLocation.has("dispatch.read"),
    zoneManage: company.has("dispatch.execute"),
    launch: anyLocation.has("dispatch.execute"),
    shortages: company.has("shortage.read"),
    shortageCreate,
    shortageCancel,
    shortageEdit: shortageCreate && shortageCancel,
  };
}

/** A later response cannot repopulate rows after revoke, switch or refresh. */
export function createDispatchReadFence() {
  let revision = 0;
  let controller: AbortController | null = null;
  return {
    start(isSessionCurrent: () => boolean) {
      controller?.abort();
      const active = new AbortController();
      controller = active;
      const ownRevision = ++revision;
      return {
        signal: active.signal,
        isCurrent: () => !active.signal.aborted &&
          revision === ownRevision && isSessionCurrent(),
      };
    },
    revoke() {
      ++revision;
      controller?.abort();
      controller = null;
    },
  };
}
