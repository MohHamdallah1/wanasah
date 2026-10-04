import { useEffect } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import { apiErrorMessage } from "@/lib/apiErrors";
import type { PendingRoute, Shortage } from "@/types/dispatch";
import type { DispatchNavigationIntent } from "./navigation";

export function findOwnerRecord<T extends { id: string }>(rows: T[], id: number): T | null {
  return rows.find((row) => String(row.id) === String(id)) ?? null;
}

/** Navigation never executes a command. Owner endpoints re-check current tenant/permissions. */
export function useDispatchOwnerNavigation({ focus, onRoute, onShortage, onConsumed }: {
  focus: DispatchNavigationIntent | null;
  onRoute: (route: PendingRoute, intent: Exclude<DispatchNavigationIntent, { kind: "shortage-owner" }>) => void;
  onShortage: (rows: Shortage[], shortage: Shortage) => void;
  onConsumed: () => void;
}) {
  const authFetch = useAuthFetch();
  const { t } = useTranslation();
  useEffect(() => {
    if (!focus) return;
    const controller = new AbortController();
    void (async () => {
      try {
        if (focus.kind === "shortage-owner") {
          const raw = await authFetch(`/dispatch/shortages?shortage_id=${focus.shortageId}`, { signal: controller.signal });
          if (controller.signal.aborted) return;
          const rows: Shortage[] = Array.isArray(raw) ? raw : [];
          const shortage = findOwnerRecord(rows, focus.shortageId);
          if (!shortage || shortage.status !== "pending") throw new Error(t("archiveOwners.inaccessible"));
          onShortage(rows, shortage);
        } else {
          const raw = await authFetch(`/dispatch/active_routes?route_id=${focus.routeId}`, { signal: controller.signal });
          if (controller.signal.aborted) return;
          const routes: PendingRoute[] = Array.isArray(raw) ? raw : [];
          const route = findOwnerRecord(routes, focus.routeId);
          if (!route || (focus.kind === "route-load" && route.can_execute !== true)) throw new Error(t("archiveOwners.inaccessible"));
          onRoute(route, focus);
        }
      } catch (error: unknown) {
        if (!controller.signal.aborted) toast.error(apiErrorMessage(error, t("archiveOwners.inaccessible")));
      } finally {
        if (!controller.signal.aborted) onConsumed();
      }
    })();
    return () => controller.abort();
  }, [authFetch, focus, onConsumed, onRoute, onShortage, t]);
}
