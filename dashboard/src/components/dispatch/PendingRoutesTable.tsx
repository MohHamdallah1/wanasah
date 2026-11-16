import { useTranslation } from "react-i18next";
import type { PendingRoute } from "@/types/dispatch";
import { ActiveRouteCard, type ActiveRouteActions } from "@/features/dispatch/routeLifecycle/ActiveRouteCard";
import { activeRouteText } from "@/features/dispatch/routeLifecycle/activeRouteCopy";

// Stable D14/D15 real route list container. The Backend determines command
// authority; this view never treats a pending read as a genuine empty list.
interface PendingRoutesTableProps extends ActiveRouteActions {
  routes: PendingRoute[];
  pending?: boolean;
  actionsPending?: boolean;
}
export function PendingRoutesTable({routes,pending=false,actionsPending=false,...actions}:PendingRoutesTableProps) {
  const {i18n}=useTranslation();
  // A route that is postponed or closed must not become an active control even
  // when a route owner link, stale list, or mixed response includes that row.
  const visible=routes.filter(route=>route.status==="active"||route.status==="waiting");
  return <div className="dispatch-route-list max-h-[45vh] overflow-y-auto divide-y divide-slate-100 rounded-2xl border border-slate-200 bg-white shadow-sm custom-scrollbar"
    dir={i18n.dir()}>
    {!visible.length && <p data-testid="dispatch-routes-read-status"
      role={pending?"status":undefined} className="p-6 text-center text-sm text-slate-500">
      {activeRouteText(i18n.language,pending?"loading":"empty")}
    </p>}
    {visible.map(route=><ActiveRouteCard key={route.id} route={route} pending={pending||actionsPending} {...actions}/>)}
  </div>;
}
